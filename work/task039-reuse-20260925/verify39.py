#!/usr/bin/env python3
"""Read-only task-39 verifier. Requires circuit.py and the system libz3 library.
Exit 0 only when the ROBDD check and an independent arithmetic SMT miter agree.
No private keys, RPC calls, repository writes, or blockchain transactions.
"""
import argparse
import hashlib
import json
from pathlib import Path
import circuit


def verify(path: Path, timeout_ms: int = 60000) -> dict:
    obj = json.loads(path.read_text())
    dimensions = obj.get('task', obj)
    for key, expected in [('nIn', 32), ('nOut', 17), ('nState', 0)]:
        actual = dimensions.get(key, obj.get(key, expected))
        if actual != expected:
            raise ValueError(f'{key} must be {expected}, got {actual}')
    gates = circuit.decode(obj)
    raw = circuit.encode(gates)
    bdd_ok = circuit.check_bdd(gates)
    miter = circuit.z3_miter(gates, timeout=timeout_ms)
    valid = bdd_ok and miter['result'] == 'unsat'
    return {
        'file': path.name,
        'valid': valid,
        **circuit.metrics(gates),
        'rawNetlistSha256': hashlib.sha256(raw).hexdigest(),
        'bddEquivalentTo17BitAddition': bdd_ok,
        'arithmeticMiter': miter,
        'symbolicallyCoveredInputs': 2**32 if valid else None,
        'literalExhaustiveSimulationPerformed': False,
        'beatsSnapshot123848100': valid and circuit.metrics(gates)['cost'] < 330088,
        'onChainSubmitted': False,
        'globallyOptimalProved': False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('netlist', type=Path, nargs='+')
    parser.add_argument('--timeout-ms', type=int, default=60000)
    args = parser.parse_args()
    if args.timeout_ms <= 0:
        parser.error('--timeout-ms must be positive')
    results = [verify(p, args.timeout_ms) for p in args.netlist]
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0 if all(r['valid'] for r in results) else 1


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise SystemExit(f'Verification failed: {exc}')
