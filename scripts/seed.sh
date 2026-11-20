#!/usr/bin/env bash
# Seeds the local chain: licenses, three batches, a custody chain and a split.
set -euo pipefail
cd "$(dirname "$0")/.."

RPC="${RPC_URL:-http://127.0.0.1:8545}"
DEP="deployments/31337.json"
PY=".venv/bin/python"

A0=0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266
A1=0x70997970C51812dc3A010C7d01b50e0d17dc79C8
A2=0x3C44CdDdB6a900fa2b585dd299e03d12FA4293BC
A3=0x90F79bf6EB2c4f870365E785982E1f101E93b906
A5=0x9965507D1a55bcC2695C58ba16FB37d819B0A4dc

json() { "$PY" -c "import json;print(json.load(open('$DEP'))['$1'])"; }
REG=$(json registry)
BATCH=$(json batch)
INC=$(json incidents)

send() { cast send "$@" --rpc-url "$RPC" --unlocked --json >/dev/null; }
call() { cast call "$@" --rpc-url "$RPC"; }

EXPIRY=$(( $(date +%s) + 365 * 86400 ))
PRODUCT1=$(cast keccak "AMOX-500")
PRODUCT2=$(cast keccak "INSULIN-100")
PRODUCT3=$(cast keccak "AZITHRO-250")
META1=$("$PY" -m ml.storage put data/offchain/batch-1001.json)
META2=$("$PY" -m ml.storage put data/offchain/batch-1002.json)
META3=$("$PY" -m ml.storage put data/offchain/batch-1003.json)

echo "== contracts =="
echo "registry     $REG"
echo "batch        $BATCH"
echo "incidents    $INC"
echo

echo "== licenses (verifier $A1) =="
send "$REG" "register(address,uint8,bytes32,bytes2)" "$A0" 1 "$(cast keccak "UA-MFG-0042")" 0x4b59 --from "$A1"
send "$REG" "register(address,uint8,bytes32,bytes2)" "$A2" 2 "$(cast keccak "UA-DST-0117")" 0x4b59 --from "$A1"
send "$REG" "register(address,uint8,bytes32,bytes2)" "$A3" 3 "$(cast keccak "UA-PHM-0231")" 0x4c56 --from "$A1"
send "$REG" "register(address,uint8,bytes32,bytes2)" "$A5" 3 "$(cast keccak "UA-PHM-0448")" 0x444e --from "$A1"
send "$REG" "register(address,uint8,bytes32,bytes2)" "$A1" 4 "$(cast keccak "UA-REG-0001")" 0x4b59 --from "$A1"
echo "participants: $(call "$REG" 'participantCount()(uint256)')"
echo

echo "== batches =="
send "$BATCH" "mint(bytes32,uint64,uint64,uint128,bytes32,bytes2)" "$PRODUCT1" 1001 "$EXPIRY" 1000 "$META1" 0x4b59 --from "$A0"
send "$BATCH" "mint(bytes32,uint64,uint64,uint128,bytes32,bytes2)" "$PRODUCT2" 1002 "$EXPIRY" 500 "$META2" 0x4b59 --from "$A0"
send "$BATCH" "mint(bytes32,uint64,uint64,uint128,bytes32,bytes2)" "$PRODUCT3" 1003 "$EXPIRY" 800 "$META3" 0x4b59 --from "$A0"
echo "batches: $(call "$BATCH" 'batchCount()(uint256)')"
echo

echo "== batch 1: manufacturer -> distributor -> pharmacy =="
send "$BATCH" "initiateCustody(uint256,address,bytes2)" 1 "$A2" 0x4b59 --from "$A0"
send "$BATCH" "acceptCustody(uint256)" 1 --from "$A2"
send "$BATCH" "initiateCustody(uint256,address,bytes2)" 1 "$A3" 0x4c56 --from "$A2"
send "$BATCH" "acceptCustody(uint256)" 1 --from "$A3"
echo "batch 1 state: $(call "$BATCH" 'stateOf(uint256)(uint8)' 1) custodian: $(call "$BATCH" 'ownerOf(uint256)(address)' 1)"
echo

echo "== batch 2: split into 200 and 300 =="
send "$BATCH" "split(uint256,uint128[])" 2 "[200,300]" --from "$A0"
echo "parent quantity: $(call "$BATCH" 'quantityOf(uint256)(uint128)' 2)"
echo "child batches: 4 and 5"
echo

echo "== on-chain serial lookup =="
echo "serial 1001 -> token $(call "$BATCH" 'verifySerial(bytes32,uint64)(uint256)' "$PRODUCT1" 1001)"
echo "serial 1001 -> token $(call "$BATCH" 'verifySerial(bytes32,uint64)(uint256)' "$PRODUCT2" 1001)"
