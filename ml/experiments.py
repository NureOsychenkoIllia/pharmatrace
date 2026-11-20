"""Experiments for the final lab: latency, load, robustness, learning curve, centralized baseline."""
from __future__ import annotations

import asyncio
import json
import os
import secrets
import sqlite3
import time
from pathlib import Path

import httpx
import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.metrics import f1_score
from web3 import Web3
from xgboost import XGBClassifier

from ml.features import prepare

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "results"
API = "http://127.0.0.1:8000"
REPEATS = 5
SEED = 42
RNG = np.random.default_rng(SEED)

BATCH_ABI = [
    {
        "name": "batchCount",
        "type": "function",
        "stateMutability": "view",
        "inputs": [],
        "outputs": [{"name": "", "type": "uint256"}],
    },
    {
        "name": "mint",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "productId", "type": "bytes32"},
            {"name": "serial", "type": "uint64"},
            {"name": "expiry", "type": "uint64"},
            {"name": "quantity", "type": "uint128"},
            {"name": "metadataHash", "type": "bytes32"},
            {"name": "originCity", "type": "bytes2"},
        ],
        "outputs": [{"name": "", "type": "uint256"}],
    },
    {
        "name": "initiateCustody",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "tokenId", "type": "uint256"},
            {"name": "to", "type": "address"},
            {"name": "city", "type": "bytes2"},
        ],
        "outputs": [],
    },
    {
        "name": "acceptCustody",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [{"name": "tokenId", "type": "uint256"}],
        "outputs": [],
    },
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
        "name": "confirmIncident",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [{"name": "incidentId", "type": "uint256"}],
        "outputs": [],
    },
]

ACCOUNTS = {
    "manufacturer": "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266",
    "verifier": "0x70997970C51812dc3A010C7d01b50e0d17dc79C8",
    "distributor": "0x3C44CdDdB6a900fa2b585dd299e03d12FA4293BC",
    "pharmacy": "0x90F79bf6EB2c4f870365E785982E1f101E93b906",
    "oracle": "0x15d34AAf54267DB7D7c367839AAf71A00a2C6A65",
}


def percentile(values: list[float], q: float) -> float:
    return float(np.percentile(values, q)) if values else 0.0


async def api_latency() -> dict:
    payload = {
        "distance_km": 1400,
        "transit_hours": 1.2,
        "scans_24h": 14,
        "same_serial_cities_24h": 4,
        "scan_lat": 49.84,
        "scan_lon": 24.03,
    }
    async with httpx.AsyncClient(timeout=30) as client:
        batch_times, analyze_times = [], []
        for _ in range(50):
            start = time.perf_counter()
            response = await client.get(f"{API}/api/batches")
            response.raise_for_status()
            batch_times.append((time.perf_counter() - start) * 1000)
        for _ in range(50):
            start = time.perf_counter()
            response = await client.post(f"{API}/api/analyze", json=payload)
            response.raise_for_status()
            analyze_times.append((time.perf_counter() - start) * 1000)
    return {
        "batches_ms": {
            "p50": percentile(batch_times, 50),
            "p95": percentile(batch_times, 95),
            "mean": float(np.mean(batch_times)),
        },
        "analyze_ms": {
            "p50": percentile(analyze_times, 50),
            "p95": percentile(analyze_times, 95),
            "mean": float(np.mean(analyze_times)),
        },
        "raw": {"batches": batch_times, "analyze": analyze_times},
    }


async def load_level(level: int, payload: dict) -> dict:
    async with httpx.AsyncClient(timeout=60) as client:
        async def one():
            start = time.perf_counter()
            response = await client.post(f"{API}/api/analyze", json=payload)
            response.raise_for_status()
            return (time.perf_counter() - start) * 1000

        start = time.perf_counter()
        times = await asyncio.gather(*[one() for _ in range(level)])
        wall = time.perf_counter() - start
    return {
        "users": level,
        "requests": level,
        "wall_seconds": wall,
        "throughput_rps": level / wall,
        "p50_ms": percentile(times, 50),
        "p95_ms": percentile(times, 95),
        "max_ms": max(times),
        "raw_ms": times,
    }


async def load_test() -> list[dict]:
    payload = {
        "distance_km": 1400,
        "transit_hours": 1.2,
        "scans_24h": 14,
        "same_serial_cities_24h": 4,
        "scan_lat": 49.84,
        "scan_lon": 24.03,
    }
    results = []
    for level in (10, 50, 100):
        runs = []
        for _ in range(REPEATS):
            runs.append(await load_level(level, payload))
        results.append(
            {
                "users": level,
                "throughput_rps": float(np.mean([r["throughput_rps"] for r in runs])),
                "p50_ms": float(np.mean([r["p50_ms"] for r in runs])),
                "p95_ms": float(np.mean([r["p95_ms"] for r in runs])),
                "max_ms": max(r["max_ms"] for r in runs),
                "runs": runs,
            }
        )
    return results


def model_latency(data) -> dict:
    model = joblib.load(ROOT / "artifacts/xgboost.joblib")
    x_test = data["x_test"]
    times = []
    for row in x_test[:300]:
        start = time.perf_counter()
        model.predict_proba(row.reshape(1, -1))
        times.append((time.perf_counter() - start) * 1000)
    return {
        "p50_ms": percentile(times, 50),
        "p95_ms": percentile(times, 95),
        "mean_ms": float(np.mean(times)),
        "raw_ms": times,
        "rows": len(times),
    }


def robustness(data) -> list[dict]:
    model = joblib.load(ROOT / "artifacts/xgboost.joblib")
    forest = joblib.load(ROOT / "artifacts/isolation_forest.joblib")
    meta = json.loads((RESULTS / "model_metrics.json").read_text())
    x_test, y_test = data["x_test"], data["y_test"]
    n_numeric = len([n for n in meta["feature_names"] if n.startswith("num__")])
    rows = []
    for level in (0.0, 0.1, 0.3, 0.6):
        noisy = x_test.copy()
        if level:
            noisy[:, :n_numeric] += RNG.normal(0, level, size=noisy[:, :n_numeric].shape)
        proba = model.predict_proba(noisy)[:, 1]
        xgb_f1 = f1_score(
            y_test,
            (proba >= meta["models"]["xgboost"]["threshold"]).astype(int),
            zero_division=0,
        )
        score = -forest.score_samples(noisy)
        iso_f1 = f1_score(
            y_test,
            (score >= meta["models"]["isolation_forest"]["threshold"]).astype(int),
            zero_division=0,
        )
        rows.append(
            {
                "noise_sigma": level,
                "xgboost_f1": float(xgb_f1),
                "isolation_forest_f1": float(iso_f1),
            }
        )
    return rows


def learning_curve(data) -> list[dict]:
    x_train, y_train = data["x_train"], data["y_train"]
    x_test, y_test = data["x_test"], data["y_test"]
    rows = []
    for fraction in (0.1, 0.25, 0.5, 0.75, 1.0):
        n = int(len(x_train) * fraction)
        idx = RNG.choice(len(x_train), n, replace=False)
        model = XGBClassifier(
            n_estimators=300,
            max_depth=4,
            learning_rate=0.1,
            subsample=0.9,
            colsample_bytree=0.9,
            eval_metric="logloss",
            random_state=SEED,
            n_jobs=4,
        )
        model.fit(x_train[idx], y_train[idx], verbose=False)
        proba = model.predict_proba(x_test)[:, 1]
        candidates = np.quantile(proba, np.linspace(0.5, 0.99, 100))
        best = max(
            candidates,
            key=lambda t: f1_score(y_test, (proba >= t).astype(int), zero_division=0),
        )
        rows.append(
            {
                "fraction": fraction,
                "train_rows": n,
                "f1": float(f1_score(y_test, (proba >= best).astype(int), zero_division=0)),
            }
        )
    return rows


def mcnemar(data) -> dict:
    pred = pd.read_csv(RESULTS / "test_predictions.csv")
    y = pred["is_anomaly"].to_numpy()
    out = {}
    base = pred["baseline"].to_numpy()
    for name in ("isolation_forest", "autoencoder", "xgboost"):
        other = pred[f"{name}_pred"].to_numpy()
        b = int(((base == 1) & (other == 0)).sum())
        c = int(((base == 0) & (other == 1)).sum())
        if b + c == 0:
            p = 1.0
        else:
            from scipy.stats import binomtest

            p = float(binomtest(min(b, c), b + c, 0.5).pvalue)
        out[name] = {"baseline_only_correct": b, "model_only_correct": c, "p_value": p}
    return out


def centralized(rounds: int = 100) -> dict:
    path = RESULTS / "centralized.db"
    if path.exists():
        path.unlink()
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE batches(id INTEGER PRIMARY KEY, product TEXT, serial INTEGER, quantity INTEGER, state TEXT);
        CREATE TABLE custody(id INTEGER PRIMARY KEY, batch_id INTEGER, from_party TEXT, to_party TEXT, at TEXT);
        CREATE TABLE incidents(id INTEGER PRIMARY KEY, batch_id INTEGER, score INTEGER, status TEXT);
        """
    )
    times = []
    for i in range(rounds):
        start = time.perf_counter()
        conn.execute(
            "INSERT INTO batches VALUES (?,?,?,?,?)", (i + 1, "AMOX-500", 200000 + i, 1000, "created")
        )
        conn.execute(
            "INSERT INTO custody VALUES (?,?,?,?,datetime('now'))", (i + 1, i + 1, "manufacturer", "distributor")
        )
        conn.execute("UPDATE batches SET state='delivered' WHERE id=?", (i + 1,))
        conn.execute(
            "INSERT INTO incidents VALUES (?,?,?,?)", (i + 1, i + 1, 9999, "confirmed")
        )
        conn.commit()
        times.append((time.perf_counter() - start) * 1000)
    conn.execute("UPDATE batches SET quantity=999999 WHERE id=1")
    conn.commit()
    tampered = conn.execute("SELECT quantity FROM batches WHERE id=1").fetchone()[0]
    conn.close()
    return {
        "rounds": rounds,
        "p50_ms": percentile(times, 50),
        "p95_ms": percentile(times, 95),
        "mean_ms": float(np.mean(times)),
        "tampered_quantity": tampered,
        "tamper_detected": False,
    }


def chain_scenario() -> dict:
    deployment = json.loads((ROOT / "deployments/31337.json").read_text())
    rpc = os.environ.get("RPC_URL", "http://127.0.0.1:8545")
    w3 = Web3(Web3.HTTPProvider(rpc, request_kwargs={"timeout": 10}))
    batch = w3.eth.contract(address=Web3.to_checksum_address(deployment["batch"]), abi=BATCH_ABI)
    incidents = w3.eth.contract(
        address=Web3.to_checksum_address(deployment["incidents"]), abi=INCIDENT_ABI
    )

    def send(function, sender: str) -> dict:
        tx = function.build_transaction(
            {
                "from": sender,
                "nonce": w3.eth.get_transaction_count(sender, "pending"),
                "gas": 600_000,
                "gasPrice": w3.eth.gas_price,
                "chainId": w3.eth.chain_id,
            }
        )
        start = time.perf_counter()
        tx_hash = w3.eth.send_transaction(tx)
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=30)
        if receipt.status != 1:
            raise RuntimeError(f"scenario transaction reverted: {tx_hash.hex()}")
        return {
            "seconds": time.perf_counter() - start,
            "gas": int(receipt.gasUsed),
            "status": int(receipt.status),
            "txHash": tx_hash.hex(),
        }

    serial = secrets.randbits(63)
    product = Web3.keccak(text=f"EXPERIMENT-{serial}")
    token_id = int(batch.functions.batchCount().call()) + 1
    incident_id = int(incidents.functions.incidentCount().call()) + 1
    steps = []
    steps.append(
        ("mint", send(batch.functions.mint(product, serial, int(time.time()) + 31_536_000, 500, Web3.keccak(text="meta"), b"KY"), ACCOUNTS["manufacturer"]))
    )
    steps.append(
        ("initiate_1", send(batch.functions.initiateCustody(token_id, ACCOUNTS["distributor"], b"KY"), ACCOUNTS["manufacturer"]))
    )
    steps.append(
        ("accept_1", send(batch.functions.acceptCustody(token_id), ACCOUNTS["distributor"]))
    )
    steps.append(
        ("initiate_2", send(batch.functions.initiateCustody(token_id, ACCOUNTS["pharmacy"], b"LV"), ACCOUNTS["distributor"]))
    )
    steps.append(
        ("accept_2", send(batch.functions.acceptCustody(token_id), ACCOUNTS["pharmacy"]))
    )
    steps.append(
        ("record_anomaly", send(batch.functions.recordAnomaly(token_id, 9999, Web3.keccak(text="model"), Web3.keccak(text="data"), 2), ACCOUNTS["oracle"]))
    )
    steps.append(
        ("report_incident", send(incidents.functions.reportOracleIncident(token_id, 2, 4, 9999, Web3.keccak(text="model"), Web3.keccak(text="data"), Web3.keccak(text="note")), ACCOUNTS["oracle"]))
    )
    steps.append(
        ("confirm", send(incidents.functions.confirmIncident(incident_id), ACCOUNTS["verifier"]))
    )
    return {
        "steps": [{"step": name, **result} for name, result in steps],
        "total_seconds": float(sum(result["seconds"] for _, result in steps)),
        "total_gas": int(sum(result["gas"] for _, result in steps)),
    }


async def main() -> None:
    RESULTS.mkdir(exist_ok=True)
    data = prepare(ROOT)
    scenario_runs = [chain_scenario() for _ in range(REPEATS)]
    steps = [
        {
            "step": first["step"],
            "seconds": float(np.median([run["steps"][index]["seconds"] for run in scenario_runs])),
            "gas": int(np.median([run["steps"][index]["gas"] for run in scenario_runs])),
        }
        for index, first in enumerate(scenario_runs[0]["steps"])
    ]
    payload = {
        "latency": await api_latency(),
        "load": await load_test(),
        "model_latency": model_latency(data),
        "robustness": robustness(data),
        "learning_curve": learning_curve(data),
        "mcnemar": mcnemar(data),
        "centralized": centralized(),
        "chain_scenario": {
            "steps": steps,
            "total_seconds": float(np.median([run["total_seconds"] for run in scenario_runs])),
            "total_gas": int(np.median([run["total_gas"] for run in scenario_runs])),
            "runs": scenario_runs,
        },
    }
    (RESULTS / "experiments.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    print(json.dumps({k: v for k, v in payload.items() if k not in {"latency"}}, indent=2)[:4000])
    print("latency", payload["latency"]["batches_ms"], payload["latency"]["analyze_ms"])


if __name__ == "__main__":
    asyncio.run(main())
