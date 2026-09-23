#!/usr/bin/env python3
"""Reproduce the valid 118-NAND local-timing experiment, NOT a cost improvement.
Python standard library only. The original 117-NAND checkpoint is hash-checked.
"""
import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCE_SHA = 'e3c109514b8ff3589e87c3ed3456ec040baae875a77e3507e6eccac6b0aba1c1'
RESULT_SHA = '16b4d9d142aa86a68865adc845307ce720ab6d2d158a7ded0afb8683e0b3cc34'


def encode(gates):
    return b''.join(b'\0' + a.to_bytes(3, 'big') + b.to_bytes(3, 'big') for a, b in gates)


def verify(gates):
    depths = [0] * 10
    for i, (a, b) in enumerate(gates, 10):
        if not (0 <= a < i and 0 <= b < i):
            raise ValueError('Invalid NAND reference')
        depths.append(1 + max(depths[a], depths[b]))
    table, expected_table, errors = bytearray(), bytearray(), []
    for word in range(256):
        values = [0, 1] + [(word >> bit) & 1 for bit in range(8)]
        for a, b in gates:
            values.append(1 ^ (values[a] & values[b]))
        actual = sum(value << bit for bit, value in enumerate(values[-8:]))
        a, b = word & 15, word >> 4
        expected = a * b
        table.append(actual)
        expected_table.append(expected)
        if actual != expected:
            errors.append({'a': a, 'b': b, 'actual': actual, 'expected': expected})
    depth = max(depths)
    return {'valid': not errors, 'gateCount': len(gates), 'depth': depth,
            'cost': len(gates) * depth**3, 'outputDepths': depths[-8:],
            'testedInputs': 256, 'passedInputs': 256-len(errors),
            'counterexamples': errors,
            'rawNetlistSha256': hashlib.sha256(encode(gates)).hexdigest(),
            'truthTableSha256': hashlib.sha256(table).hexdigest(),
            'expectedTruthTableSha256': hashlib.sha256(expected_table).hexdigest()}


def balanced_output(gates):
    output_start = len(gates) + 2
    mapped, seen, new_gates = {i: i for i in range(10)}, {}, []

    def resolve(expr):
        if isinstance(expr, int):
            if expr in mapped:
                return mapped[expr]
            if expr >= output_start:
                raise ValueError('Internal dependency on physical output')
            mapped[expr] = resolve(gates[expr-10])
            return mapped[expr]
        a, b = resolve(expr[0]), resolve(expr[1])
        if a == 0 or b == 0:
            return 1
        if a == 1 and b == 1:
            return 0
        pair = tuple(sorted((a, b)))
        if pair not in seen:
            seen[pair] = len(new_gates) + 10
            new_gates.append(pair)
        return seen[pair]

    physical_outputs = []
    for bit, pair in enumerate(gates[-8:]):
        if bit == 1:
            # XOR(~(a1*b0), ~(a0*b1)), balanced into four NANDs.
            pair = ((11, (11, 12)), (12, (11, 12)))
        physical_outputs.append((resolve(pair[0]), resolve(pair[1])))
    return new_gates + physical_outputs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, default=ROOT/'best_valid_117.json')
    parser.add_argument('--out', type=Path, default=ROOT/'reproduced_timing_118.json')
    args = parser.parse_args()
    source = json.loads(args.input.read_text())
    raw = bytes.fromhex(source['rawNetlist'].removeprefix('0x'))
    if hashlib.sha256(raw).hexdigest() != SOURCE_SHA:
        raise ValueError('Wrong input checkpoint for this deterministic experiment')
    if len(raw) % 7 or any(raw[i] != 0 for i in range(0, len(raw), 7)):
        raise ValueError('Expected NAND-only bytecode')
    gates = [(int.from_bytes(raw[i+1:i+4], 'big'), int.from_bytes(raw[i+4:i+7], 'big'))
             for i in range(0, len(raw), 7)]
    baseline = verify(gates)
    if not baseline['valid'] or baseline['cost'] != 59904:
        raise ValueError('Invalid comparison baseline')
    result_gates = balanced_output(gates)
    result = verify(result_gates)
    if not result['valid'] or result['rawNetlistSha256'] != RESULT_SHA:
        raise ValueError('Reproduction or full-input verification failed')
    output = {'taskId': 60, 'nIn': 8, 'nOut': 8, 'nState': 0,
              'status': 'VALID_LOCAL_TIMING_EXPERIMENT_HIGHER_TOTAL_COST',
              'rawNetlist': '0x'+encode(result_gates).hex(), 'verification': result,
              'baselineCost': 59904, 'beatsSnapshot': False,
              'onChainSubmitted': False, 'globallyOptimalProved': False}
    args.out.write_text(json.dumps(output, indent=2)+'\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, KeyError, TypeError) as exc:
        raise SystemExit('Reproduction failed: '+str(exc))
