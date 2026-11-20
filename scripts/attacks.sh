#!/usr/bin/env bash
# Five practical attacks against the deployed system.
set -uo pipefail
cd "$(dirname "$0")/.."

RPC="${RPC_URL:-http://127.0.0.1:8545}"
DEP="deployments/31337.json"
PY=".venv/bin/python"

A0=0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266
A1=0x70997970C51812dc3A010C7d01b50e0d17dc79C8
A2=0x3C44CdDdB6a900fa2b585dd299e03d12FA4293BC
A4=0x15d34AAf54267DB7D7c367839AAf71A00a2C6A65

json() { "$PY" -c "import json;print(json.load(open('$DEP'))['$1'])"; }
BATCH=$(json batch)
INC=$(json incidents)

call() { cast call "$@" --rpc-url "$RPC"; }
try_send() { cast send "$@" --rpc-url "$RPC" --unlocked --json >/tmp/attack.out 2>/tmp/attack.err; }
error_name() {
  grep -hoE 'NotManufacturer\([^)]*\)|AccessControlUnauthorizedAccount\([^)]*\)|InvalidTransition\([^)]*\)|InvalidSplit(\(\))?' /tmp/attack.err /tmp/attack.out 2>/dev/null | head -1
}

echo "== attack 1: distributor mints a batch without a manufacturer license =="
if try_send "$BATCH" "mint(bytes32,uint64,uint64,uint128,bytes32,bytes2)" "$(cast keccak 'FAKE')" 999999 1999999999 10 "$(cast keccak 'fake')" 0x4b59 --from "$A2"; then
  echo "RESULT: accepted (bad)"
else
  echo "RESULT: rejected: $(error_name)"
fi

echo "== attack 2: manufacturer writes a model decision without the oracle role =="
if try_send "$BATCH" "recordAnomaly(uint256,uint16,bytes32,bytes32,uint8)" 1 9999 "$(cast keccak 'fake-model')" "$(cast keccak 'fake-data')" 2 --from "$A0"; then
  echo "RESULT: accepted (bad)"
else
  echo "RESULT: rejected: $(error_name)"
fi

echo "== attack 3: replay a model decision for a closed incident =="
if try_send "$INC" "submitModelDecision(uint256,uint16,bytes32,bytes32)" 1 9999 "$(cast keccak 'model')" "$(cast keccak 'data')" --from "$A4"; then
  echo "RESULT: accepted (bad)"
else
  echo "RESULT: rejected: $(error_name)"
fi

echo "== attack 4: substitute the off-chain batch document =="
cp data/offchain/batch-1001.json /tmp/batch-1001.attack.json
"$PY" - <<'PY'
import json
p='data/offchain/batch-1001.json'
d=json.load(open(p)); d['quantity']=999999
json.dump(d,open(p,'w'),ensure_ascii=False)
PY
EXPECTED=$(call "$BATCH" "getBatch(uint256)((bytes32,bytes32,bytes32,bytes32,address,uint64,uint16,bool,uint8,address,uint64,bytes2,address,uint64,uint128,uint128))" 1 | tr ',' '\n' | sed -n '2p' | tr -d ' ')
"$PY" -m ml.storage verify data/offchain/batch-1001.json "$EXPECTED" | tail -1 | sed 's/^/RESULT: /'
cp /tmp/batch-1001.attack.json data/offchain/batch-1001.json

echo "== attack 5: split into 51 parts to exhaust the loop bound =="
PARTS=$("$PY" -c "print('[' + ','.join(['1']*51) + ']')")
if try_send "$BATCH" "split(uint256,uint128[])" 3 "$PARTS" --from "$A0"; then
  echo "RESULT: accepted (bad)"
else
  echo "RESULT: rejected: $(error_name)"
fi

echo "== anomalous input reaches the model =="
curl -s -X POST http://127.0.0.1:8000/api/analyze -H 'Content-Type: application/json' \
  -d '{"distance_km":1400,"transit_hours":1.2,"scans_24h":14,"same_serial_cities_24h":4,"scan_lat":49.84,"scan_lon":24.03}' \
  | "$PY" -c "import json,sys; d=json.load(sys.stdin); print('RESULT: score %.4f, anomaly=%s' % (d['score'], d['is_anomaly']))"
