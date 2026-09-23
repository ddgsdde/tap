# Task 60: multi-angle NAND area/depth search

## Result

**No valid cost improvement was found.** The best valid cost remains **117 NAND × 8³ = 59,904**. The repository snapshot was read again: block `123477186`, block time `2026-09-23T01:29:03Z`, circuit `15974`. This is not a fresh live-RPC leaderboard read.

The new depth experiment is **123 NAND, depth 8, cost 62,976**, with all **256/256** inputs correct. It is intentionally marked `VALID_DEPTH_EXPERIMENT_COST_WORSE`: it is a continuation checkpoint, not a better submission.

| Stage | NAND gates | Overall depth | Internal depth-7 nodes | Cost |
|---|---:|---:|---:|---:|
| Correct starting checkpoint | 117 | 8 | 8 | 59,904 |
| First depth-oriented rewrite | 118 | 8 | 7 | 60,416 |
| Second depth-oriented rewrite | 123 | 8 | 6 | 62,976 |

The eight output depths remain `[2,5,6,8,8,8,8,6]`. Shortening some internal branches does not shorten the whole circuit while other critical branches remain. Counting internal depth-7 nodes is a search heuristic, not the cost metric.

The strict winning gate budgets against this snapshot are: **116 at depth 8**, **174 at depth 7**, and **277 at depth 6**. These are arithmetic thresholds, not claims that such circuits have been found.

## What was actually run

Searches included exact 256-bit care-set rewrites, up-to-seven-NAND expression templates, added low-depth helper signals and complemented signals, truth-signature-library remapping, local counterexample-guided SAT synthesis, spare-slot Cartesian evolution, and neutral multi-gate window rewrites followed by exact resubstitution.

Two spare-slot runs used 150 and 174 NAND slots and completed **503,939,072** and **440,442,880** candidate evaluations. Two neutral-window runs completed **519** window queries and accepted **310** function-preserving window changes. Six local SAT tasks performed 14 checks and ended with one restricted UNSAT and five unknown results; none produced a valid cost improvement.

All accepted functional changes were checked on every input. The saved checkpoints were independently rechecked by a scalar multiplication verifier. Evaluation counts can include duplicates. Restricted templates, deduplicated signatures, capped returned expressions, local UNSAT, and timeouts are not a global lower-bound proof.

## Reproduce the saved depth experiment

This repository directory contains the checkpoint and compact results report. Uploading the reproducer script to the repository was blocked by the connector safety check. The standalone reproducer/verifier, full search source, and raw logs are provided in the experiment ZIP supplied in the conversation.

From the extracted experiment directory:

```bash
python3 reproduce_depth_tradeoff.py
python3 reproduce_depth_tradeoff.py --verify depth123_VERIFIED_NOT_IMPROVED.json
```

The reproducer uses only the Python standard library and reads the previous verified checkpoint from `work/task060-mul4-20260923/best_known_117.json`. In the ZIP, a copy of that input is bundled beside the script. It verifies the input hash, applies the two recorded rewrites, and checks all 256 inputs and the resulting hash.

Final raw-netlist SHA-256:

```text
1ab63d05611ec4f0933e03e2e4b52bcfa81bfff9f91e18b979fd4a1133a0b649
```

**No global optimality proof and no on-chain transaction. All searches in this round have stopped.**
