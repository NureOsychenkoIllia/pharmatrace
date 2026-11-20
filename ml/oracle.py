"""Oracle service: turns chain events into model decisions and incidents."""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

import joblib
import pandas as pd
from web3 import Web3
from web3.logs import DISCARD

from ml.features import engineer

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "results/oracle_state.db"
LOG = ROOT / "results/oracle.log"

BATCH_ABI = [
    {
        "name": "recordAnomaly",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "tokenId", "type": "uint256"},
            {"name": "scoreBps", "type": "uint16"},
            {"name": "modelVersion", "type": "bytes32"},
            {"name": "dataHash", "type": "bytes32"},
            {"name": "anomalyType", "type": "uint8"},
        ],
        "outputs": [],
    },
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
        "name": "CustodyAccepted",
        "type": "event",
        "anonymous": False,
        "inputs": [
            {"name": "tokenId", "type": "uint256", "indexed": True},
            {"name": "from", "type": "address", "indexed": True},
            {"name": "to", "type": "address", "indexed": True},
        ],
    },
]

INCIDENT_ABI = [
    {
        "name": "reportOracleIncident",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "batchId", "type": "uint256"},
            {"name": "kind", "type": "uint8"},
            {"name": "severity", "type": "uint8"},
            {"name": "scoreBps", "type": "uint16"},
            {"name": "modelVersion", "type": "bytes32"},
            {"name": "dataHash", "type": "bytes32"},
            {"name": "noteHash", "type": "bytes32"},
        ],
        "outputs": [{"name": "incidentId", "type": "uint256"}],
    },
    {
        "name": "submitModelDecision",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "incidentId", "type": "uint256"},
            {"name": "scoreBps", "type": "uint16"},
            {"name": "modelVersion", "type": "bytes32"},
            {"name": "dataHash", "type": "bytes32"},
        ],
        "outputs": [],
    },
    {
        "name": "registeredModels",
        "type": "function",
        "stateMutability": "view",
        "inputs": [{"name": "modelVersion", "type": "bytes32"}],
        "outputs": [{"name": "", "type": "bool"}],
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
    {
        "name": "ModelDecisionRecorded",
        "type": "event",
        "anonymous": False,
        "inputs": [
            {"name": "incidentId", "type": "uint256", "indexed": True},
            {"name": "scoreBps", "type": "uint16", "indexed": False},
            {"name": "modelVersion", "type": "bytes32", "indexed": False},
            {"name": "dataHash", "type": "bytes32", "indexed": False},
        ],
    },
    {
        "name": "registerModel",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [{"name": "modelVersion", "type": "bytes32"}],
        "outputs": [],
    },
]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.FileHandler(LOG), logging.StreamHandler()],
)
log = logging.getLogger("oracle")


def sha256_bytes(payload: bytes) -> bytes:
    return hashlib.sha256(payload).digest()


def sha256_json(payload: dict) -> bytes:
    return sha256_bytes(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode())


class Oracle:
    def __init__(self, rpc: str, private_key: str):
        self.w3 = Web3(Web3.HTTPProvider(rpc, request_kwargs={"timeout": 10}))
        self.account = self.w3.eth.account.from_key(private_key)
        deployment = json.loads((ROOT / f"deployments/{self.w3.eth.chain_id}.json").read_text())
        self.batch = self.w3.eth.contract(
            address=Web3.to_checksum_address(deployment["batch"]), abi=BATCH_ABI
        )
        self.incidents = self.w3.eth.contract(
            address=Web3.to_checksum_address(deployment["incidents"]), abi=INCIDENT_ABI
        )
        self.model = joblib.load(ROOT / "artifacts/xgboost.joblib")
        self.pre = joblib.load(ROOT / "artifacts/preprocessor.joblib")
        self.meta = json.loads((ROOT / "results/model_metrics.json").read_text())
        self.threshold = float(self.meta["models"]["xgboost"]["threshold"])
        self.model_hash = bytes.fromhex(self.meta["models"]["xgboost"]["hash"][2:])
        self.conn = sqlite3.connect(DB)
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS processed (key TEXT PRIMARY KEY, token_id INTEGER, "
            "score REAL, incident_id INTEGER, created_at TEXT)"
        )
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS oracle_transactions "
            "(key TEXT PRIMARY KEY, scope TEXT NOT NULL, nonce INTEGER NOT NULL, raw BLOB NOT NULL,"
            "UNIQUE(scope, nonce))"
        )
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS oracle_inputs (key TEXT PRIMARY KEY, payload TEXT NOT NULL)"
        )
        genesis = self.w3.eth.get_block(0)["hash"].hex()
        self.scope = f"{self.w3.eth.chain_id}:{genesis}:{self.account.address}"
        self.namespace = f"{self.scope}:{self.batch.address}:{self.incidents.address}"
        self.conn.commit()

    def _seen(self, key: str) -> bool:
        row = self.conn.execute("SELECT 1 FROM processed WHERE key=?", (key,)).fetchone()
        return row is not None

    def _mark(self, key: str, token_id: int, score: float, incident_id: int) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO processed VALUES (?,?,?,?,?)",
            (key, token_id, score, incident_id, datetime.now(timezone.utc).isoformat()),
        )
        self.conn.commit()

    def _input(self, key: str, token_id: int, clone: bool) -> dict:
        key = f"{self.namespace}:{key}"
        self.conn.execute("BEGIN IMMEDIATE")
        with self.conn:
            saved = self.conn.execute("SELECT payload FROM oracle_inputs WHERE key=?", (key,)).fetchone()
            if saved is not None:
                return json.loads(saved[0])
            _, raw = self.features(token_id, clone)
            self.conn.execute("INSERT INTO oracle_inputs VALUES (?, ?)", (key, json.dumps(raw)))
            return raw

    def _send(self, key: str, function, gas: int = 500_000, attempts: int = 4):
        key = f"{self.namespace}:{key}"
        last = None
        for attempt in range(attempts):
            try:
                self.conn.execute("BEGIN IMMEDIATE")
                with self.conn:
                    saved = self.conn.execute(
                        "SELECT raw FROM oracle_transactions WHERE key=?", (key,)
                    ).fetchone()
                    if saved is None:
                        nonce = self.w3.eth.get_transaction_count(self.account.address, "pending")
                        highest, = self.conn.execute(
                            "SELECT MAX(nonce) FROM oracle_transactions WHERE scope=?", (self.scope,)
                        ).fetchone()
                        if highest is not None:
                            nonce = max(nonce, highest + 1)
                        tx = function.build_transaction(
                            {
                                "from": self.account.address,
                                "nonce": nonce,
                                "gas": gas,
                                "gasPrice": self.w3.eth.gas_price,
                                "chainId": self.w3.eth.chain_id,
                            }
                        )
                        raw = bytes(self.w3.eth.account.sign_transaction(tx, self.account.key).raw_transaction)
                        self.conn.execute(
                            "INSERT INTO oracle_transactions VALUES (?, ?, ?, ?)", (key, self.scope, nonce, raw)
                        )
                    else:
                        raw = saved[0]
                tx_hash = Web3.keccak(raw)
                try:
                    self.w3.eth.send_raw_transaction(raw)
                except Exception as exc:
                    # The node may already have received or mined this exact transaction.
                    log.debug("broadcast %s: %s", tx_hash.hex(), exc)
                receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=30)
            except Exception as exc:  # retry on transient RPC errors
                last = exc
                log.warning("attempt %d failed: %s", attempt + 1, exc)
                time.sleep(2**attempt)
                continue
            if receipt.status != 1:
                with self.conn:
                    self.conn.execute("DELETE FROM oracle_transactions WHERE key=? AND raw=?", (key, raw))
                raise RuntimeError(f"reverted {tx_hash.hex()}")
            log.info("tx %s", tx_hash.hex())
            return receipt
        raise RuntimeError(f"transaction failed after {attempts} attempts: {last}")

    def _register_model(self) -> None:
        if not self.incidents.functions.registeredModels(self.model_hash).call():
            self._send(
                f"model:{self.model_hash.hex()}", self.incidents.functions.registerModel(self.model_hash)
            )

    def features(self, token_id: int, clone: bool) -> tuple[pd.DataFrame, dict]:
        raw = self.batch.functions.getBatch(token_id).call()
        keys = [c["name"] for c in BATCH_ABI[1]["outputs"][0]["components"]]
        batch = dict(zip(keys, raw))
        far_lat, far_lon = (49.8397, 24.0297)
        row = {
            "distance_km": 1400.0 if clone else 120.0,
            "transit_hours": 1.2 if clone else 3.0,
            "quantity_sent": int(batch["quantity"]),
            "quantity_received": int(batch["quantity"]),
            "temperature_c": 20.0,
            "cold_chain": 0,
            "event_type": "scan",
            "product_category": "antibiotic",
            "license_status": "active",
            "license_age_days": 500,
            "scans_24h": 14 if clone else 1,
            "same_serial_cities_24h": 4 if clone else 1,
            "batch_age_hours": max(1.0, (time.time() - int(batch["createdAt"])) / 3600),
            "route_step": 2,
            "route_length": 3,
            "cumulative_distance_km": 900.0 if clone else 120.0,
            "from_id": "ORACLE",
            "to_id": "ORACLE",
            "from_city": "Kyiv",
            "to_city": "Kyiv",
            "from_lat": 50.4501,
            "from_lon": 30.5234,
            "to_lat": 50.4501,
            "to_lon": 30.5234,
            "scan_city": "Lviv" if clone else "Kyiv",
            "scan_lat": far_lat if clone else 50.4501,
            "scan_lon": far_lon if clone else 30.5234,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        return pd.DataFrame([row]), row

    def process_token(self, token_id: int, clone: bool = True, event_key: str | None = None) -> dict:
        source = event_key or f"token:{token_id}:clone={clone}"
        key = f"{source}:model={self.model_hash.hex()}"
        legacy = f"{source}:model={self.meta['models']['xgboost']['hash'][:16]}"
        if self._seen(f"{self.namespace}:{key}") or self._seen(legacy):
            log.info("already processed %s", key)
            return {"status": "skipped"}
        raw = self._input(key, token_id, clone)
        frame = pd.DataFrame([raw])
        score = float(self.model.predict_proba(self.pre.transform(engineer(frame)))[0, 1])
        score_bps = min(10_000, int(round(score * 10_000)))
        data_hash = sha256_json(raw)
        kind = 2 if clone else 1
        severity = 4 if score >= self.threshold else 3
        note = sha256_bytes(
            json.dumps({"token": token_id, "clone": clone, "score": score}).encode()
        )
        log.info(
            "token=%s score=%.4f threshold=%.4f bps=%d", token_id, score, self.threshold, score_bps
        )
        self._register_model()
        self._send(
            f"{key}:batch",
            self.batch.functions.recordAnomaly(
                token_id, score_bps, self.model_hash, data_hash, kind
            )
        )
        receipt = self._send(
            f"{key}:incident",
            self.incidents.functions.reportOracleIncident(
                token_id, kind, severity, score_bps, self.model_hash, data_hash, note
            )
        )
        decision, = self.incidents.events.ModelDecisionRecorded().process_receipt(receipt, errors=DISCARD)
        incident_id = int(decision["args"]["incidentId"])
        self._mark(f"{self.namespace}:{key}", token_id, score, incident_id)
        return {
            "status": "submitted",
            "score": score,
            "scoreBps": score_bps,
            "incidentId": incident_id,
            "txHash": receipt.transactionHash.hex(),
        }

    def submit_decision(self, incident_id: int, clone: bool = True) -> dict:
        keys = [c["name"] for c in INCIDENT_ABI[2]["outputs"][0]["components"]]
        incident = dict(zip(keys, self.incidents.functions.getIncident(incident_id).call()))
        token_id = int(incident["batchId"])
        key = f"incident:{incident_id}:model={self.model_hash.hex()}"
        legacy = f"incident:{incident_id}:model={self.meta['models']['xgboost']['hash'][:16]}"
        if self._seen(f"{self.namespace}:{key}") or self._seen(legacy):
            log.info("already processed %s", key)
            return {"status": "skipped"}
        raw = self._input(key, token_id, clone)
        frame = pd.DataFrame([raw])
        score = float(self.model.predict_proba(self.pre.transform(engineer(frame)))[0, 1])
        score_bps = min(10_000, int(round(score * 10_000)))
        data_hash = sha256_json(raw)
        log.info("incident=%s token=%s score=%.4f bps=%d", incident_id, token_id, score, score_bps)
        self._register_model()
        receipt = self._send(
            key,
            self.incidents.functions.submitModelDecision(
                incident_id, score_bps, self.model_hash, data_hash
            )
        )
        self._mark(f"{self.namespace}:{key}", token_id, score, incident_id)
        return {
            "status": "submitted",
            "score": score,
            "scoreBps": score_bps,
            "incidentId": incident_id,
            "txHash": receipt.transactionHash.hex(),
        }

    def listen(self, from_block: int = 0, interval: int = 3) -> None:
        event = self.batch.events.CustodyAccepted()
        last = from_block
        log.info("listening from block %d", last)
        while True:
            try:
                latest = self.w3.eth.block_number
                entries = event.get_logs(from_block=last, to_block=latest) if latest >= last else []
            except Exception as exc:
                log.warning("event polling failed, will retry: %s", exc)
            else:
                for entry in entries:
                    token_id = int(entry["args"]["tokenId"])
                    key = f"event:{entry['transactionHash'].hex()}:{entry['logIndex']}"
                    if self._seen(key):
                        continue
                    try:
                        self.process_token(token_id, clone=False, event_key=key)
                    except Exception as exc:
                        log.error("event processing failed, will retry: %s", exc)
                        last = int(entry["blockNumber"])
                        break
                else:
                    last = max(last, latest + 1)
            time.sleep(interval)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rpc", default=os.environ.get("RPC_URL", "http://127.0.0.1:8545"))
    parser.add_argument("--key-env", default="ORACLE_PRIVATE_KEY")
    parser.add_argument("--token", type=int)
    parser.add_argument("--incident", type=int)
    parser.add_argument("--clone", action="store_true")
    parser.add_argument("--listen", action="store_true")
    parser.add_argument("--from-block", type=int, default=0)
    args = parser.parse_args()
    key = os.environ.get(args.key_env)
    if not key:
        raise SystemExit(f"{args.key_env} is not set")
    oracle = Oracle(args.rpc, key)
    if args.token:
        log.info("result %s", oracle.process_token(args.token, args.clone))
    if args.incident:
        log.info("result %s", oracle.submit_decision(args.incident, args.clone))
    if args.listen:
        oracle.listen(args.from_block)


if __name__ == "__main__":
    main()
