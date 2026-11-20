#!/usr/bin/env bash
# Integrity check: the original document matches, the substituted one does not.
set -euo pipefail
cd "$(dirname "$0")/.."
HASH=$(.venv/bin/python -m ml.storage put data/offchain/batch-1001.json)
cp data/offchain/batch-1001.json data/offchain/batch-1001-tampered.json
.venv/bin/python - <<'PY'
import json
p = "data/offchain/batch-1001-tampered.json"
d = json.load(open(p))
d["quantity"] = 100000
json.dump(d, open(p, "w"), ensure_ascii=False, sort_keys=True)
PY
echo "original document"
.venv/bin/python -m ml.storage verify data/offchain/batch-1001.json "$HASH" || true
echo
echo "substituted document"
.venv/bin/python -m ml.storage verify data/offchain/batch-1001-tampered.json "$HASH" || true
rm -f data/offchain/batch-1001-tampered.json
