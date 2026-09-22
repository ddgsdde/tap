#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
OUT="$ROOT/.offline/selftest"
mkdir -p "$OUT"

sh "$ROOT/tools/offline/build.sh"

# XOR2 needs four NAND gates at depth three.  The three-gate query must be
# UNSAT and its DRAT certificate must independently verify.
python3 "$ROOT/tools/offline/exact_nand.py" prove \
  --truth-hex 6 --inputs 2 --outputs 1 --gates 3 --depth 3 \
  --out-dir "$OUT/unsat-3g"

# The matching four-gate query must produce a candidate that passes exhaustive
# truth-table and depth verification.
python3 "$ROOT/tools/offline/exact_nand.py" prove \
  --truth-hex 6 --inputs 2 --outputs 1 --gates 4 --depth 3 \
  --out-dir "$OUT/sat-4g"

python3 - "$OUT" <<'PY'
import json, pathlib, sys
root = pathlib.Path(sys.argv[1])
unsat = json.loads((root / "unsat-3g" / "result.json").read_text())
sat = json.loads((root / "sat-4g" / "result.json").read_text())
assert unsat["status"] == "UNSAT" and unsat["proofVerified"] is True
assert sat["status"] == "SAT" and sat["candidateVerified"] is True
assert sat["candidate"]["gates"] == 4 and sat["candidate"]["depth"] == 3
print("offline SAT self-test: PASS")
PY
