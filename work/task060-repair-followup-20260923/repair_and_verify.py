#!/usr/bin/env python3
"""Restore task 60's output bit 4 and exhaustively verify all 256 products.
This is reference-based correctness repair, not a proof of optimality.
Standard library only. Never submits a transaction.
"""
import argparse
import hashlib
import json
from pathlib import Path
MASK = (1 << 256) - 1
INPUTS = [0, MASK] + [sum(((x >> i) & 1) << x for x in range(256)) for i in range(8)]
ROOT = Path(__file__).resolve().parent


def decode(obj):
    if 'rawNetlist' in obj:
        raw = bytes.fromhex(obj['rawNetlist'].removeprefix('0x'))
        if len(raw) % 7 or any(raw[p] for p in range(0, len(raw), 7)):
            raise ValueError('Expected NAND-only 7-byte instructions')
        gates = [(int.from_bytes(raw[p+1:p+4], 'big'), int.from_bytes(raw[p+4:p+7], 'big'))
                 for p in range(0, len(raw), 7)]
        if 'gates' in obj and gates != [tuple(x) for x in obj['gates']]:
            raise ValueError('rawNetlist and gates disagree')
    else:
        gates = [tuple(x) for x in obj['gates']]
    if len(gates) < 8:
        raise ValueError('Eight physical output gates are required')
    for signal, pair in enumerate(gates, 10):
        if len(pair) != 2 or any(not isinstance(x, int) or x < 0 or x >= signal for x in pair):
            raise ValueError(f'Invalid references at signal {signal}')
    return gates


def simulate(gates):
    values, depths = INPUTS[:], [0] * 10
    for a, b in gates:
        values.append(MASK ^ (values[a] & values[b]))
        depths.append(1 + max(depths[a], depths[b]))
    return values, depths


def encode(gates):
    return b''.join(b'\0' + a.to_bytes(3, 'big') + b.to_bytes(3, 'big') for a, b in gates)


def verify(gates):
    decode({'gates': gates})
    _, depths = simulate(gates)
    errors, observed, expected_table = [], bytearray(), bytearray()
    for word in range(256):
        a, b = word & 15, word >> 4
        signals = [0, 1] + [(word >> i) & 1 for i in range(8)]
        for left, right in gates:
            signals.append(1 ^ (signals[left] & signals[right]))
        actual = sum(bit << i for i, bit in enumerate(signals[-8:]))
        expected = a * b
        observed.append(actual)
        expected_table.append(expected)
        if actual != expected:
            errors.append({'a': a, 'b': b, 'expected': expected, 'actual': actual,
                           'wrongOutputBits': [i for i in range(8) if (actual ^ expected) >> i & 1]})
    return {'valid': not errors, 'gateCount': len(gates), 'depth': max(depths),
            'outputDepths': depths[-8:], 'cost': len(gates) * max(depths)**3,
            'testedInputs': 256, 'passedInputs': 256 - len(errors),
            'wrongOutputBitCount': sum(len(x['wrongOutputBits']) for x in errors),
            'counterexamples': errors, 'rawNetlistSha256': hashlib.sha256(encode(gates)).hexdigest(),
            'truthTableSha256': hashlib.sha256(observed).hexdigest(),
            'expectedTruthTableSha256': hashlib.sha256(expected_table).hexdigest()}


def normalize(gates, replacement=None):
    """Merge identical internal NANDs and prune unused nodes, preserving output order."""
    out0 = len(gates) + 2
    mapping, seen, body, busy = {i: i for i in range(10)}, {}, [], set()
    def resolve(expr):
        if isinstance(expr, int):
            if expr in mapping:
                return mapping[expr]
            if expr >= out0 or expr in busy:
                raise ValueError('Cycle or internal dependency on a physical output')
            busy.add(expr)
            result = resolve(gates[expr-10])
            mapping[expr] = result
            busy.remove(expr)
            return result
        a, b = sorted((resolve(expr[0]), resolve(expr[1])))
        if a == 0:
            return 1
        if a == b == 1:
            return 0
        key = (a, b)
        if key not in seen:
            seen[key] = len(body) + 10
            body.append(key)
        return seen[key]
    outputs = []
    for signal in range(out0, out0 + 8):
        expr = replacement[1] if replacement and replacement[0] == signal else gates[signal-10]
        outputs.append((resolve(expr[0]), resolve(expr[1])))
    return body + outputs


def repair(near, reference):
    if not verify(reference)['valid']:
        raise ValueError('The reference must compute multiplication correctly')
    near = normalize(near)
    nv, nd = simulate(near)
    rv, _ = simulate(reference)
    available = {}
    for j in sorted(range(len(nv)-8), key=lambda j: (nd[j], j)):
        available.setdefault(nv[j], j)
    mapping = {}
    def expression(j):
        if j not in mapping:
            if rv[j] in available:
                mapping[j] = available[rv[j]]
            else:
                a, b = reference[j-10]
                mapping[j] = (expression(a), expression(b))
        return mapping[j]
    repaired = normalize(near, (len(near)+6, expression(len(reference)+6)))
    # Canonical two-level implementation of product bit 0.
    repaired = normalize(repaired, (len(repaired)+2, ((2, 6), 1)))
    result = verify(repaired)
    if not result['valid']:
        raise ValueError('Reconstructed circuit failed independent exhaustive verification')
    return repaired, result


def main():
    previous = ROOT.parent / 'task060-mul4-20260923'
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--near', type=Path, default=previous/'near_miss_116_NOT_VALID.json')
    ap.add_argument('--reference', type=Path, default=previous/'best_known_117.json')
    ap.add_argument('--output', type=Path, default=ROOT/'repaired_117_VERIFIED.json')
    ap.add_argument('--verify', type=Path, help='Verify a file only, without repair or writes')
    args = ap.parse_args()
    if args.verify:
        result = verify(decode(json.loads(args.verify.read_text())))
        print(json.dumps(result, indent=2))
        return 0 if result['valid'] else 1
    gates, result = repair(decode(json.loads(args.near.read_text())),
                           decode(json.loads(args.reference.read_text())))
    obj = {'taskId': 60, 'nIn': 8, 'nOut': 8, 'nState': 0,
           'status': 'VALID_NOT_IMPROVED' if result['cost'] >= 59904 else 'VALID_BEATS_SNAPSHOT',
           'baseline': {'snapshotBlock': 123477186, 'circuitId': '15974',
                        'gateCount': 117, 'depth': 8, 'cost': 59904},
           'globallyOptimalProved': False, 'onChainSubmitted': False,
           'method': 'Reference-based repair of output bit 4 with exact truth-signature reuse',
           'rawNetlist': '0x' + encode(gates).hex(), 'verification': result}
    args.output.write_text(json.dumps(obj, indent=2) + '\n')
    print(json.dumps(result, indent=2))
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise SystemExit(f'Error: {exc}')
