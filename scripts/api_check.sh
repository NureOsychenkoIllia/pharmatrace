#!/usr/bin/env bash
# Compact API demonstration for the report screenshot.
set -euo pipefail
API="${API_URL:-http://127.0.0.1:8000}"
echo "GET /api/health"
curl -s "$API/api/health" | .venv/bin/python -m json.tool
echo
echo "GET /api/batches/1 (state and anomaly)"
curl -s "$API/api/batches/1" | .venv/bin/python -c "import json,sys; d=json.load(sys.stdin); print({k:d[k] for k in ('id','serial','stateName','custodian','flagged','anomalyScore')})"
echo
echo "POST /api/analyze (clone scan)"
curl -s -X POST "$API/api/analyze" -H 'Content-Type: application/json' \
  -d '{"distance_km":1400,"transit_hours":1.2,"scans_24h":14,"same_serial_cities_24h":4,"scan_lat":49.84,"scan_lon":24.03}' \
  | .venv/bin/python -c "import json,sys; d=json.load(sys.stdin); print({'score':round(d['score'],4),'threshold':round(d['threshold'],4),'is_anomaly':d['is_anomaly'],'top':d['top_factors'][0]['feature']})"
echo
echo "GET /api/integrity/1"
curl -s "$API/api/integrity/1" | .venv/bin/python -m json.tool
