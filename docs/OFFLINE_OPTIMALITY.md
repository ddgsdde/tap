# Offline SAT optimality toolkit

This repository carries the solver source and the exact NAND encoder needed to
search for cheaper TapeOut combinational circuits in a sandbox with no network
access.

## What is included

- Kissat 4.0.4 source for SAT and UNSAT solving.
- drat-trim source for independent checking of Kissat UNSAT certificates.
- `tools/offline/exact_nand.py`, a Python standard-library encoder, model
  decoder, exhaustive candidate verifier and cost-bound sweep driver.
- Current task metadata, leaderboard netlists and official vectors under
  `data/`.

The only host requirements are POSIX shell, Python 3, `make` and a C compiler.
No pip, npm, apt, Homebrew, wallet, RPC or internet connection is used after
the repository has been obtained.

## Build and test without downloads

```bash
sh tools/offline/build.sh
sh tools/offline/selftest.sh
```

The self-test proves that two-input XOR is impossible with at most three NAND
gates, checks the resulting DRAT certificate, then synthesizes and exhaustively
verifies its four-gate implementation.

## Prove one bound

Truth-table columns use hexadecimal integers where bit `x` is the output for
input word `x`. This checks whether XOR2 fits at most three gates and depth
three:

```bash
python3 tools/offline/exact_nand.py prove \
  --truth-hex 6 --inputs 2 --outputs 1 \
  --gates 3 --depth 3 \
  --out-dir offline-results/xor2-3g
```

For a current pure-NAND combinational leader, the tool can derive the complete
truth table directly from the exported chain netlist:

```bash
python3 tools/offline/exact_nand.py prove \
  --reference data/latest/netlists/tapeout/task-018-circuit-1056.json \
  --gates 11 --depth 5 \
  --out-dir offline-results/task18-11g5d
```

The circuit ID in a filename can change after an hourly scan. Select the
current file by its `task-NNN-` prefix.

## Prove minimum scoring cost

For incumbent cost `C`, every cheaper circuit must satisfy
`G <= floor((C-1)/d^3)` at some relevant depth `d`. `sweep` generates one
at-most-gate query for each such depth:

```bash
python3 tools/offline/exact_nand.py sweep \
  --reference data/latest/netlists/tapeout/task-018-circuit-1056.json \
  --incumbent-cost 1500 --timeout 3600 \
  --out-dir offline-results/task18-global-cost
```

`globalCostOptimalityProved: true` is emitted only when every cheaper region is
UNSAT and every certificate passes drat-trim. A SAT result contains an
exhaustively verified candidate. A timeout, skipped resource guard, malformed
model or failed certificate leaves the conclusion incomplete.

`--max-gates N` may protect memory on a small sandbox. It deliberately changes
the final conclusion to incomplete if a required region exceeds that limit.

## Model and limits

The exact model uses constants 0 and 1, free primary inputs, two-input NAND
gates, ordered final physical output gates, and cost `G × d³`. It currently
handles pure-NAND combinational netlists and enumerates at most `2^20` reference
inputs. Sequential LATCH tasks need a separate bounded-model encoder. Large
gate bounds can generate very large CNFs; timeout or resource exhaustion is
evidence of neither SAT nor UNSAT.

The snapshot field `optimal: true` is an on-chain status. It is separate from
the certificate-backed mathematical conclusion produced here.
