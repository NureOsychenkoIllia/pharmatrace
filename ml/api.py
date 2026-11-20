"""FastAPI service: batch state, model decisions, audit log and integrity checks."""
from __future__ import annotations

import hashlib
import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from web3 import Web3
from web3.exceptions import TransactionNotFound

from ml.features import engineer
from ml.storage import digest_bytes, load_document

ROOT = Path(__file__).resolve().parent.parent
DEPLOYMENT = ROOT / "deployments/31337.json"
STATES = ["None", "Created", "InTransit", "Delivered", "Dispensed", "Recalled", "Destroyed"]
KINDS = ["None", "RouteAnomaly", "Counterfeit", "RecallRequest", "CustodyDispute"]
SEVERITIES = ["None", "Low", "Medium", "High", "Critical"]
INCIDENT_STATES = ["None", "Open", "ModelReviewed", "Confirmed", "Dismissed", "Resolved"]

BATCH_ABI = [
    {
        "name": "getBatch",
        "type": "function",
        "stateMutability": "view",
        "inputs": [{"name": "tokenId", "type": "uint256"}],
        "outputs": [
            {
                "name": "",
                "type": "tuple",
                "components": [
                    {"name": "productId", "type": "bytes32"},
                    {"name": "metadataHash", "type": "bytes32"},
                    {"name": "modelVersion", "type": "bytes32"},
                    {"name": "dataHash", "type": "bytes32"},
                    {"name": "manufacturer", "type": "address"},
                    {"name": "serial", "type": "uint64"},
                    {"name": "anomalyScore", "type": "uint16"},
                    {"name": "flagged", "type": "bool"},
                    {"name": "state", "type": "uint8"},
                    {"name": "custodian", "type": "address"},
                    {"name": "expiry", "type": "uint64"},
                    {"name": "originCity", "type": "bytes2"},
                    {"name": "pendingRecipient", "type": "address"},
                    {"name": "createdAt", "type": "uint64"},
                    {"name": "quantity", "type": "uint128"},
                    {"name": "parentId", "type": "uint128"},
                ],
            }
        ],
    },
    {
        "name": "batchCount",
        "type": "function",
        "stateMutability": "view",
        "inputs": [],
        "outputs": [{"name": "", "type": "uint256"}],
    },
    {
        "name": "verifySerial",
        "type": "function",
        "stateMutability": "view",
        "inputs": [{"name": "productId", "type": "bytes32"}, {"name": "serial", "type": "uint64"}],
        "outputs": [{"name": "", "type": "uint256"}],
    },
    {
        "name": "getBatches",
        "type": "function",
        "stateMutability": "view",
        "inputs": [{"name": "offset", "type": "uint256"}, {"name": "limit", "type": "uint256"}],
        "outputs": [
            {
                "name": "",
                "type": "tuple[]",
                "components": [
                    {"name": "id", "type": "uint256"},
                    {"name": "productId", "type": "bytes32"},
                    {"name": "serial", "type": "uint64"},
                    {"name": "manufacturer", "type": "address"},
                    {"name": "custodian", "type": "address"},
                    {"name": "expiry", "type": "uint64"},
                    {"name": "createdAt", "type": "uint64"},
                    {"name": "state", "type": "uint8"},
                    {"name": "quantity", "type": "uint128"},
                    {"name": "parentId", "type": "uint128"},
                    {"name": "metadataHash", "type": "bytes32"},
                    {"name": "originCity", "type": "bytes2"},
                    {"name": "flagged", "type": "bool"},
                    {"name": "anomalyScore", "type": "uint16"},
                ],
            }
        ],
    },
    {
        "name": "AnomalyRecorded",
        "type": "event",
        "anonymous": False,
        "inputs": [
            {"name": "tokenId", "type": "uint256", "indexed": True},
            {"name": "scoreBps", "type": "uint16", "indexed": False},
            {"name": "modelVersion", "type": "bytes32", "indexed": False},
            {"name": "dataHash", "type": "bytes32", "indexed": False},
            {"name": "anomalyType", "type": "uint8", "indexed": False},
        ],
    },
]

INCIDENT_ABI = [
    {
        "name": "incidentCount",
        "type": "function",
        "stateMutability": "view",
        "inputs": [],
        "outputs": [{"name": "", "type": "uint256"}],
    },
    {
        "name": "getIncident",
        "type": "function",
        "stateMutability": "view",
        "inputs": [{"name": "incidentId", "type": "uint256"}],
        "outputs": [
            {
                "name": "",
                "type": "tuple",
                "components": [
                    {"name": "batchId", "type": "uint256"},
                    {"name": "kind", "type": "uint8"},
                    {"name": "severity", "type": "uint8"},
                    {"name": "status", "type": "uint8"},
                    {"name": "reporter", "type": "address"},
                    {"name": "createdAt", "type": "uint64"},
                    {"name": "scoreBps", "type": "uint16"},
                    {"name": "modelVersion", "type": "bytes32"},
                    {"name": "dataHash", "type": "bytes32"},
                    {"name": "noteHash", "type": "bytes32"},
                ],
            }
        ],
    },
]


def _hex(value: bytes | str) -> str:
    if isinstance(value, bytes):
        return "0x" + value.hex()
    return value


def _city(value: bytes) -> str:
    return bytes(value).decode("ascii", errors="ignore")


class ChainGateway:
    def __init__(self, rpc_url: str, deployment: dict):
        self.w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 5}))
        self.batch = self.w3.eth.contract(
            address=Web3.to_checksum_address(deployment["batch"]), abi=BATCH_ABI
        )
        self.incidents = self.w3.eth.contract(
            address=Web3.to_checksum_address(deployment["incidents"]), abi=INCIDENT_ABI
        )

    def batch_count(self) -> int:
        return int(self.batch.functions.batchCount().call())

    def get_batch(self, token_id: int) -> dict[str, Any]:
        raw = self.batch.functions.getBatch(token_id).call()
        keys = [c["name"] for c in BATCH_ABI[0]["outputs"][0]["components"]]
        value = dict(zip(keys, raw))
        value["id"] = token_id
        value["stateName"] = STATES[int(value["state"])]
        value["originCity"] = _city(value["originCity"])
        for key in ("productId", "metadataHash", "modelVersion", "dataHash"):
            value[key] = _hex(value[key])
        return value

    def list_batches(self, limit: int = 50) -> list[dict[str, Any]]:
        raw = self.batch.functions.getBatches(0, limit).call()
        keys = [c["name"] for c in BATCH_ABI[3]["outputs"][0]["components"]]
        rows = []
        for item in raw:
            value = dict(zip(keys, item))
            value["stateName"] = STATES[int(value["state"])]
            value["originCity"] = _city(value["originCity"])
            for key in ("productId", "metadataHash"):
                value[key] = _hex(value[key])
            rows.append(value)
        return rows

    def verify_serial(self, product_id: str, serial: int) -> int:
        return int(self.batch.functions.verifySerial(bytes.fromhex(product_id[2:]), serial).call())

    def transaction(self, tx_hash: str) -> dict[str, Any]:
        receipt = self.w3.eth.get_transaction_receipt(tx_hash)
        return {
            "hash": _hex(receipt["transactionHash"]),
            "block": receipt["blockNumber"],
            "status": receipt["status"],
            "gasUsed": receipt["gasUsed"],
            "from": receipt["from"],
            "to": receipt["to"],
        }

    def anomaly_logs(self, limit: int = 50) -> list[dict[str, Any]]:
        event = self.batch.events.AnomalyRecorded()
        logs = event.get_logs(from_block=0, to_block="latest")
        rows = []
        for log in logs[-limit:][::-1]:
            rows.append(
                {
                    "tokenId": int(log["args"]["tokenId"]),
                    "scoreBps": int(log["args"]["scoreBps"]),
                    "modelVersion": _hex(log["args"]["modelVersion"]),
                    "dataHash": _hex(log["args"]["dataHash"]),
                    "anomalyType": int(log["args"]["anomalyType"]),
                    "txHash": _hex(log["transactionHash"]),
                    "block": int(log["blockNumber"]),
                }
            )
        return rows

    def incident_count(self) -> int:
        return int(self.incidents.functions.incidentCount().call())

    def get_incident(self, incident_id: int) -> dict[str, Any]:
        raw = self.incidents.functions.getIncident(incident_id).call()
        keys = [c["name"] for c in INCIDENT_ABI[1]["outputs"][0]["components"]]
        value = dict(zip(keys, raw))
        value["id"] = incident_id
        value["kindName"] = KINDS[int(value["kind"])]
        value["severityName"] = SEVERITIES[int(value["severity"])]
        value["statusName"] = INCIDENT_STATES[int(value["status"])]
        for key in ("modelVersion", "dataHash", "noteHash"):
            value[key] = _hex(value[key])
        return value

    def list_incidents(self, limit: int = 50) -> list[dict[str, Any]]:
        count = self.incident_count()
        start = max(1, count - limit + 1)
        return [self.get_incident(i) for i in range(count, start - 1, -1)]


@lru_cache(maxsize=1)
def get_gateway() -> ChainGateway:
    deployment = json.loads(Path(os.environ.get("DEPLOYMENT_PATH", DEPLOYMENT)).read_text())
    rpc = os.environ.get("RPC_URL", "http://127.0.0.1:8545")
    return ChainGateway(rpc, deployment)


@lru_cache(maxsize=1)
def get_model():
    model = joblib.load(ROOT / "artifacts/xgboost.joblib")
    pre = joblib.load(ROOT / "artifacts/preprocessor.joblib")
    meta = json.loads((ROOT / "results/model_metrics.json").read_text())
    return model, pre, meta


class AnalyzeRequest(BaseModel):
    distance_km: float = 120.0
    transit_hours: float = 3.0
    quantity_sent: int = 100
    quantity_received: int = 100
    temperature_c: float = 20.0
    cold_chain: int = 0
    event_type: str = "receive"
    product_category: str = "antibiotic"
    license_status: str = "active"
    license_age_days: int = 500
    scans_24h: int = 1
    same_serial_cities_24h: int = 1
    batch_age_hours: float = 48.0
    route_step: int = 1
    route_length: int = 3
    cumulative_distance_km: float = 120.0
    to_lat: float = 50.45
    to_lon: float = 30.52
    scan_lat: float = 50.45
    scan_lon: float = 30.52
    timestamp: str = "2026-10-01T12:00:00Z"


class AnalyzeResponse(BaseModel):
    score: float
    threshold: float
    is_anomaly: bool
    model_version: str
    data_hash: str
    top_factors: list[dict[str, Any]]


def _feature_row(payload: AnalyzeRequest) -> pd.DataFrame:
    row = payload.model_dump()
    row["from_id"] = "API"
    row["to_id"] = "API"
    row["from_city"] = "Kyiv"
    row["to_city"] = "Kyiv"
    row["from_lat"] = payload.to_lat
    row["from_lon"] = payload.to_lon
    row["scan_city"] = "Kyiv"
    return pd.DataFrame([row])


def _explain(model, pre, frame: pd.DataFrame, limit: int = 5) -> list[dict[str, Any]]:
    matrix = pre.transform(frame)
    names = list(pre.get_feature_names_out())
    try:
        import shap

        explainer = shap.TreeExplainer(model)
        values = explainer.shap_values(matrix)
        if isinstance(values, list):
            values = values[-1]
        values = np.asarray(values)
        if values.ndim == 2:
            values = values[0]
    except Exception:
        values = model.feature_importances_ * np.asarray(matrix)[0]
    order = np.argsort(np.abs(values))[::-1][:limit]
    factors = []
    for index in order:
        factors.append(
            {
                "feature": names[int(index)],
                "value": float(np.asarray(matrix)[0][int(index)]),
                "contribution": float(values[int(index)]),
            }
        )
    return factors


app = FastAPI(
    title="PharmaTrace API",
    version="1.0.0",
    description="Batch state, model decisions, audit log and off-chain integrity checks.",
)


@app.get("/api/health")
def health() -> dict[str, Any]:
    model, _, meta = get_model()
    return {
        "status": "ok",
        "model": meta["best_model"],
        "threshold": meta["models"]["xgboost"]["threshold"],
        "model_version": meta["models"]["xgboost"]["hash"],
    }


@app.get("/api/batches")
def batches(limit: int = 50, gateway: ChainGateway = Depends(get_gateway)) -> list[dict[str, Any]]:
    try:
        return gateway.list_batches(min(limit, 100))
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"chain unavailable: {exc}") from exc


@app.get("/api/batches/{token_id}")
def batch(token_id: int, gateway: ChainGateway = Depends(get_gateway)) -> dict[str, Any]:
    try:
        value = gateway.get_batch(token_id)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=f"batch not found: {exc}") from exc
    doc = load_document(ROOT / "data/offchain", value["serial"])
    value["offchain"] = (
        json.loads(doc[1]) if doc and digest_bytes(doc[1]).lower() == value["metadataHash"].lower() else None
    )
    return value


@app.post("/api/analyze", response_model=AnalyzeResponse)
def analyze(payload: AnalyzeRequest) -> AnalyzeResponse:
    model, pre, meta = get_model()
    frame = engineer(_feature_row(payload))
    matrix = pre.transform(frame)
    score = float(model.predict_proba(matrix)[0, 1])
    threshold = float(meta["models"]["xgboost"]["threshold"])
    data_hash = "0x" + hashlib.sha256(
        json.dumps(payload.model_dump(), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return AnalyzeResponse(
        score=score,
        threshold=threshold,
        is_anomaly=score >= threshold,
        model_version=meta["models"]["xgboost"]["hash"],
        data_hash=data_hash,
        top_factors=_explain(model, pre, frame),
    )


@app.get("/api/audit")
def audit(limit: int = 50, gateway: ChainGateway = Depends(get_gateway)) -> list[dict[str, Any]]:
    try:
        return gateway.anomaly_logs(min(limit, 100))
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"chain unavailable: {exc}") from exc


@app.get("/api/incidents")
def incidents(limit: int = 50, gateway: ChainGateway = Depends(get_gateway)) -> list[dict[str, Any]]:
    try:
        return gateway.list_incidents(min(limit, 100))
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"chain unavailable: {exc}") from exc


@app.get("/api/verify")
def verify(
    product_id: str, serial: int, gateway: ChainGateway = Depends(get_gateway)
) -> dict[str, Any]:
    try:
        token_id = gateway.verify_serial(product_id, serial)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"chain unavailable: {exc}") from exc
    return {"tokenId": token_id, "found": token_id != 0}


@app.get("/api/integrity/{token_id}")
def integrity(token_id: int, gateway: ChainGateway = Depends(get_gateway)) -> dict[str, Any]:
    try:
        value = gateway.get_batch(token_id)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=f"batch not found: {exc}") from exc
    doc = load_document(ROOT / "data/offchain", value["serial"])
    if doc is None:
        raise HTTPException(status_code=404, detail="off-chain document not found")
    source, payload = doc
    actual = digest_bytes(payload)
    return {
        "tokenId": token_id,
        "file": source,
        "sha256": actual,
        "onChain": value["metadataHash"],
        "match": actual.lower() == value["metadataHash"].lower(),
    }


@app.get("/api/transactions/{tx_hash}")
def transaction(tx_hash: str, gateway: ChainGateway = Depends(get_gateway)) -> dict[str, Any]:
    if len(tx_hash) != 66 or not tx_hash.startswith("0x") or any(
        digit not in "0123456789abcdefABCDEF" for digit in tx_hash[2:]
    ):
        raise HTTPException(status_code=422, detail="invalid transaction hash")
    try:
        return gateway.transaction(tx_hash)
    except TransactionNotFound as exc:
        raise HTTPException(status_code=404, detail="transaction not found") from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="chain unavailable") from exc


app.mount("/app", StaticFiles(directory=ROOT / "web", html=True), name="web")


@app.get("/")
def root() -> RedirectResponse:
    return RedirectResponse("/app/index.html")
