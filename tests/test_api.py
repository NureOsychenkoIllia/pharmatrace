"""API tests with a fake chain gateway, so no node is required."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ml.api import app, get_gateway
from ml.storage import digest

ROOT = Path(__file__).resolve().parent.parent


class FakeGateway:
    def __init__(self, metadata_hash: str | None = None):
        self.metadata_hash = metadata_hash or digest(ROOT / "data/offchain/batch-1001.json")

    def list_batches(self, limit=50):
        return [
            {
                "id": 1,
                "serial": 1001,
                "state": 3,
                "stateName": "Delivered",
                "quantity": 1000,
                "custodian": "0x90F79bf6EB2c4f870365E785982E1f101E93b906",
                "flagged": False,
                "anomalyScore": 0,
                "originCity": "KY",
                "metadataHash": self.metadata_hash,
            }
        ]

    def get_batch(self, token_id):
        if token_id != 1:
            raise ValueError("BatchNotFound")
        return self.list_batches()[0]

    def anomaly_logs(self, limit=50):
        return [
            {
                "tokenId": 1,
                "scoreBps": 9600,
                "modelVersion": "0x" + "ab" * 32,
                "dataHash": "0x" + "cd" * 32,
                "anomalyType": 3,
                "txHash": "0x" + "ef" * 32,
                "block": 7,
            }
        ]

    def list_incidents(self, limit=50):
        return [
            {
                "id": 1,
                "batchId": 1,
                "kindName": "Counterfeit",
                "severityName": "Critical",
                "statusName": "Confirmed",
                "scoreBps": 9600,
            }
        ]

    def verify_serial(self, product_id, serial):
        return 1 if serial == 1001 else 0


class BrokenGateway(FakeGateway):
    def list_batches(self, limit=50):
        raise ConnectionError("rpc down")


@pytest.fixture()
def client():
    app.dependency_overrides[get_gateway] = lambda: FakeGateway()
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_health(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["model"] == "xgboost"
    assert 0 < body["threshold"] < 1


def test_analyze_normal(client):
    response = client.post(
        "/api/analyze",
        json={
            "distance_km": 120,
            "transit_hours": 3,
            "quantity_sent": 100,
            "quantity_received": 100,
            "temperature_c": 20,
            "cold_chain": 0,
            "event_type": "receive",
            "product_category": "antibiotic",
            "license_status": "active",
            "scans_24h": 1,
            "same_serial_cities_24h": 1,
            "route_step": 1,
            "cumulative_distance_km": 120,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["is_anomaly"] is False
    assert len(body["top_factors"]) == 5


def test_analyze_clone(client):
    response = client.post(
        "/api/analyze",
        json={
            "distance_km": 1400,
            "transit_hours": 1.2,
            "quantity_sent": 500,
            "quantity_received": 500,
            "temperature_c": 20,
            "cold_chain": 0,
            "event_type": "scan",
            "product_category": "antibiotic",
            "license_status": "active",
            "scans_24h": 14,
            "same_serial_cities_24h": 4,
            "route_step": 2,
            "cumulative_distance_km": 900,
            "to_lat": 50.45,
            "to_lon": 30.52,
            "scan_lat": 49.84,
            "scan_lon": 24.03,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["is_anomaly"] is True
    assert body["score"] >= body["threshold"]
    assert any("scan" in factor["feature"] for factor in body["top_factors"])


def test_analyze_validation_error(client):
    response = client.post("/api/analyze", json={"transit_hours": "not-a-number"})
    assert response.status_code == 422


def test_batches(client):
    response = client.get("/api/batches")
    assert response.status_code == 200
    assert response.json()[0]["serial"] == 1001


def test_batch_detail_includes_offchain(client):
    response = client.get("/api/batches/1")
    assert response.status_code == 200
    body = response.json()
    assert body["stateName"] == "Delivered"
    assert body["offchain"]["gtin"] == "04812345678901"


def test_batch_not_found(client):
    response = client.get("/api/batches/99")
    assert response.status_code == 404


def test_integrity_match(client):
    response = client.get("/api/integrity/1")
    assert response.status_code == 200
    assert response.json()["match"] is True


def test_integrity_mismatch(client):
    app.dependency_overrides[get_gateway] = lambda: FakeGateway("0x" + "00" * 32)
    try:
        response = client.get("/api/integrity/1")
        assert response.status_code == 200
        assert response.json()["match"] is False
    finally:
        app.dependency_overrides.clear()


def test_audit(client):
    response = client.get("/api/audit")
    assert response.status_code == 200
    assert response.json()[0]["scoreBps"] == 9600


def test_incidents(client):
    response = client.get("/api/incidents")
    assert response.status_code == 200
    assert response.json()[0]["kindName"] == "Counterfeit"


def test_verify(client):
    token = "0x" + "11" * 32
    assert client.get(f"/api/verify?product_id={token}&serial=1001").json()["found"] is True
    assert client.get(f"/api/verify?product_id={token}&serial=777").json()["found"] is False


def test_chain_unavailable(client):
    app.dependency_overrides[get_gateway] = lambda: BrokenGateway()
    try:
        response = client.get("/api/batches")
        assert response.status_code == 503
    finally:
        app.dependency_overrides.clear()


def test_openapi_documents_endpoints(client):
    schema = client.get("/openapi.json").json()
    assert "/api/analyze" in schema["paths"]
    assert "/api/integrity/{token_id}" in schema["paths"]


def test_root_redirects(client):
    response = client.get("/", follow_redirects=False)
    assert response.status_code in (302, 307)
    assert response.headers["location"].endswith("/app/index.html")
