#!/usr/bin/env python3
"""Independent, scalar all-input verifier for TapeOut task 60 (4x4 unsigned multiply).
No third-party Python dependencies. Exit 0 only for a correct, well-formed circuit.
"""
import argparse
import hashlib
import json
from pathlib import Path


def read_gates(obj):
    if 'rawNetlist' in obj:
        raw = bytes.fromhex(obj['rawNetlist'].removeprefix('0x'))
        if len(raw) % 7:
            raise ValueError('NAND-only bytecode length must be a multiple of 7')
        gates = []
        for p in range(0, len(raw), 7):
            if raw[p] != 0:
                raise ValueError(f'Non-NAND opcode at byte {p}')
            gates.append((int.from_bytes(raw[p+1:p+4], 'big'),
                          int.from_bytes(raw[p+4:p+7], 'big')))
    elif 'gates' in obj:
        gates = [tuple(pair) for pair in obj['gates']]
        raw = b''.join(bytes([0]) + a.to_bytes(3, 'big') + b.to_bytes(3, 'big')
                       for a, b in gates)
    else:
        raise ValueError('Expected rawNetlist or gates')
    if 'gates' in obj and gates != [tuple(p) for p in obj['gates']]:
        raise ValueError('gates and rawNetlist disagree')
    if len(gates) < 8:
        raise ValueError('Eight final physical output gates are required')
    for signal, (a, b) in enumerate(gates, 10):
        if not (0 <= a < signal and 0 <= b < signal):
            raise ValueError(f'Invalid/forward reference at signal {signal}: {(a,b)}')
    outputs = list(range(len(gates)+2, len(gates)+10))
    if 'outputs' in obj and obj['outputs'] != outputs:
        raise ValueError('Outputs must be the final eight physical gates in order')
    return gates, raw


def verify(obj):
    gates, raw = read_gates(obj)
    depth = [0] * 10
    for a, b in gates:
        depth.append(1 + max(depth[a], depth[b]))
    errors, observed, expected_table = [], bytearray(), bytearray()
    for word in range(256):
        a, b = word & 15, word >> 4
        signals = [0, 1] + [(word >> k) & 1 for k in range(8)]
        for left, right in gates:
            signals.append(1 ^ (signals[left] & signals[right]))
        actual = sum(bit << k for k, bit in enumerate(signals[-8:]))
        expected = a * b
        observed.append(actual)
        expected_table.append(expected)
        if actual != expected:
            errors.append({'a': a, 'b': b, 'expected': expected, 'actual': actual,
                           'wrongOutputBits': [k for k in range(8)
                                               if ((actual ^ expected) >> k) & 1]})
    physical_depth = max(depth)
    return {'valid': not errors, 'gateCount': len(gates), 'depth': physical_depth,
            'outputDepths': depth[-8:], 'cost': len(gates)*physical_depth**3,
            'testedInputs': 256, 'passedInputs': 256-len(errors),
            'wrongOutputBitCount': sum(len(e['wrongOutputBits']) for e in errors),
            'counterexamples': errors, 'rawNetlistSha256': hashlib.sha256(raw).hexdigest(),
            'truthTableSha256': hashlib.sha256(observed).hexdigest(),
            'expectedTruthTableSha256': hashlib.sha256(expected_table).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('netlist', type=Path)
    parser.add_argument('--pairs-out', type=Path,
                        help='Export integer pairs for the C++ stochastic search')
    parser.add_argument('--reference-out', type=Path,
                        help='Export a VALID reference for tools/offline/exact_nand.py')
    args = parser.parse_args()
    obj = json.loads(args.netlist.read_text())
    result = verify(obj)
    gates, raw = read_gates(obj)
    if args.pairs_out:
        args.pairs_out.write_text(str(len(gates))+'\n'+''.join(f'{a} {b}\n' for a,b in gates))
    if args.reference_out:
        if not result['valid']:
            raise ValueError('Refusing to turn an incorrect circuit into a synthesis reference')
        reference = {'task': {'taskId': 60, 'name': '4x4 unsigned multiplier',
                             'kind': 'comb', 'nIn': 8, 'nOut': 8},
                     'rawNetlist': '0x'+raw.hex(),
                     'decoded': {'elements': [dict(op='NAND', a=a, b=b, out=i)
                                              for i,(a,b) in enumerate(gates,10)]}}
        args.reference_out.write_text(json.dumps(reference, indent=2)+'\n')
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result['valid'] else 1


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise SystemExit(f'Verification error: {exc}')
