#!/usr/bin/env bash
# Main scenario: verify a package, detect a clone, recall the batch, check integrity.
set -euo pipefail
cd "$(dirname "$0")/.."

RPC="${RPC_URL:-http://127.0.0.1:8545}"
DEP="deployments/31337.json"
PY=".venv/bin/python"

A0=0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266
A1=0x70997970C51812dc3A010C7d01b50e0d17dc79C8
A3=0x90F79bf6EB2c4f870365E785982E1f101E93b906
A4=0x15d34AAf54267DB7D7c367839AAf71A00a2C6A65
OUT=0x00000000000000000000000000000000000000ff

json() { "$PY" -c "import json;print(json.load(open('$DEP'))['$1'])"; }
REG=$(json registry)
BATCH=$(json batch)
INC=$(json incidents)

send() { cast send "$@" --rpc-url "$RPC" --unlocked --json >/dev/null; }
call() { cast call "$@" --rpc-url "$RPC"; }

PRODUCT1=$(cast keccak "AMOX-500")
META1=$("$PY" -m ml.storage put data/offchain/batch-1001.json)
MODEL=$("$PY" -m ml.storage put artifacts/model.json)
DATA=$(cast keccak "features:batch-1:clone")

echo "== patient scans the package QR =="
echo "serial 1001 -> batch $(call "$BATCH" 'verifySerial(bytes32,uint64)(uint256)' "$PRODUCT1" 1001)"
echo "state        $(call "$BATCH" 'stateOf(uint256)(uint8)' 1)  (3 = Delivered)"
echo "custodian    $(call "$BATCH" 'ownerOf(uint256)(address)' 1)"
echo

echo "== integrity of the off-chain batch document =="
"$PY" -m ml.storage verify data/offchain/batch-1001.json "$META1"
echo

echo "== a clone of serial 1001 is scanned in another city =="
send "$BATCH" "recordAnomaly(uint256,uint16,bytes32,bytes32,uint8)" 1 9600 "$MODEL" "$DATA" 3 --from "$A4"
send "$INC" "reportOracleIncident(uint256,uint8,uint8,uint16,bytes32,bytes32,bytes32)" 1 2 4 9600 "$MODEL" "$DATA" "$(cast keccak "clone-serial-1001")" --from "$A4"
echo "anomaly score $(call "$BATCH" 'anomalyOf(uint256)(uint16,bool,bytes32,bytes32)' 1 | cut -d' ' -f1)"
echo "incident state $(call "$INC" 'getIncident(uint256)((uint256,uint8,uint8,uint8,address,uint64,uint16,bytes32,bytes32,bytes32))' 1 | tr ',' '\n' | sed -n '4p') (2 = ModelReviewed)"
echo

echo "== regulator confirms and the batch is recalled =="
send "$INC" "confirmIncident(uint256)" 1 --from "$A1"
send "$INC" "resolveIncident(uint256)" 1 --from "$A1"
echo "batch state    $(call "$BATCH" 'stateOf(uint256)(uint8)' 1) (5 = Recalled)"
echo "incident state $(call "$INC" 'getIncident(uint256)((uint256,uint8,uint8,uint8,address,uint64,uint16,bytes32,bytes32,bytes32))' 1 | tr ',' '\n' | sed -n '4p') (5 = Resolved)"
echo

echo "== negative checks =="
if send "$BATCH" "recall(uint256,bytes32)" 1 "$(cast keccak "x")" --from "$OUT" 2>/dev/null; then
  echo "unexpected: outsider recalled the batch"
else
  echo "outsider recall: rejected (NotManufacturer)"
fi
if send "$INC" "submitModelDecision(uint256,uint16,bytes32,bytes32)" 1 9000 "$MODEL" "$DATA" --from "$A0" 2>/dev/null; then
  echo "unexpected: non-oracle wrote a decision"
else
  echo "non-oracle decision: rejected (AccessControl)"
fi
if send "$INC" "confirmIncident(uint256)" 1 --from "$A1" 2>/dev/null; then
  echo "unexpected: incident confirmed twice"
else
  echo "replay confirm: rejected (InvalidTransition)"
fi
echo

echo "== tampered batch document =="
cp data/offchain/batch-1001.json data/offchain/batch-1001-tampered.json
"$PY" - <<'PY'
import json
p = "data/offchain/batch-1001-tampered.json"
d = json.load(open(p))
d["quantity"] = 100000
json.dump(d, open(p, "w"), ensure_ascii=False, sort_keys=True)
PY
"$PY" -m ml.storage verify data/offchain/batch-1001-tampered.json "$META1" || true
