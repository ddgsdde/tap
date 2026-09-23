#!/usr/bin/env python3
"""Reproduce the correct 117-NAND repair; this is not a 116-gate improvement.
Standard-library only. Defaults find the previous repository work directory,
or the input checkpoints bundled beside this script.
"""
import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MASK = (1 << 256) - 1
INPUTS = [0, MASK] + [sum(((x >> k) & 1) << x for x in range(256)) for k in range(8)]
NEAR_HASH = '82b555c3ec0c711508220edc4c0523da77d62b7070bce948a67c2470155ad650'
DONOR_HASH = '835d12c74762bce0a85ab1060488bce7c52707aff56c0237fdb8041849efc192'
RESULT_HASH = 'e3c109514b8ff3589e87c3ed3456ec040baae875a77e3507e6eccac6b0aba1c1'


def load(path, expected_hash):
    obj = json.loads(path.read_text())
    raw = bytes.fromhex(obj['rawNetlist'].removeprefix('0x'))
    if hashlib.sha256(raw).hexdigest() != expected_hash:
        raise ValueError('Checkpoint does not match this reproducible repair: ' + str(path))
    if len(raw) % 7:
        raise ValueError('Invalid NAND encoding length')
    gates = []
    for p in range(0, len(raw), 7):
        a = int.from_bytes(raw[p+1:p+4], 'big')
        b = int.from_bytes(raw[p+4:p+7], 'big')
        if raw[p] != 0 or max(a, b) >= len(gates)+10:
            raise ValueError('Invalid opcode or forward reference')
        gates.append((a, b))
    return gates


def simulate(gates):
    values, depths = INPUTS[:], [0]*10
    for a, b in gates:
        values.append(MASK ^ (values[a] & values[b]))
        depths.append(1 + max(depths[a], depths[b]))
    return values, depths


def normalize(gates, replace):
    output_start = len(gates)+2
    mapped, seen, active, result = {i: i for i in range(10)}, {}, set(), []

    def resolve(x):
        if not isinstance(x, int):
            a, b = resolve(x[0]), resolve(x[1])
            if a == 0 or b == 0:
                return 1
            if a == 1 and b == 1:
                return 0
            key = tuple(sorted((a, b)))
            if key not in seen:
                seen[key] = len(result)+10
                result.append(key)
            return seen[key]
        if x in mapped:
            return mapped[x]
        if x >= output_start or x in active:
            raise ValueError('Cycle or dependence on physical output')
        active.add(x)
        expression = replace[1] if x == replace[0] else gates[x-10]
        mapped[x] = resolve(expression)
        active.remove(x)
        return mapped[x]

    outputs = []
    for node in range(output_start, len(gates)+10):
        expression = replace[1] if node == replace[0] else gates[node-10]
        outputs.append((resolve(expression[0]), resolve(expression[1])))
    return result + outputs


def verify(gates):
    errors, table = [], bytearray()
    for word in range(256):
        values = [0, 1] + [(word >> k) & 1 for k in range(8)]
        for a, b in gates:
            if not (0 <= a < len(values) and 0 <= b < len(values)):
                raise ValueError('Malformed gate')
            values.append(1 ^ (values[a] & values[b]))
        actual = sum(bit << k for k, bit in enumerate(values[-8:]))
        a, b = word & 15, word >> 4
        table.append(actual)
        if actual != a*b:
            errors.append({'a': a, 'b': b, 'expected': a*b, 'actual': actual})
    _, depths = simulate(gates)
    return {'valid': not errors, 'gateCount': len(gates), 'depth': max(depths),
            'cost': len(gates)*max(depths)**3, 'outputDepths': depths[-8:],
            'testedInputs': 256, 'passedInputs': 256-len(errors),
            'counterexamples': errors,
            'truthTableSha256': hashlib.sha256(table).hexdigest()}


def repair(near, donor):
    if not verify(donor)['valid']:
        raise ValueError('Donor circuit is incorrect')
    bad_values, bad_depths = simulate(near)
    good_values, _ = simulate(donor)
    bad_root, good_root = 80, 81
    descendants = {bad_root}
    for node in range(bad_root+1, len(bad_values)):
        if any(x in descendants for x in near[node-10]):
            descendants.add(node)
    lookup = {}
    for node in sorted(range(len(bad_values)-8), key=lambda i: (bad_depths[i], i)):
        if node not in descendants:
            lookup.setdefault(bad_values[node], node)

    def expression(node):
        if good_values[node] in lookup:
            return lookup[good_values[node]]
        a, b = donor[node-10]
        return expression(a), expression(b)

    gates = normalize(near, (bad_root, expression(good_root)))
    values, depths = simulate(gates)
    low_bit = sum((((x & 15)*(x >> 4)) & 1) << x for x in range(256))
    wire = next(i for i in range(len(values)-8) if values[i] == (MASK ^ low_bit) and depths[i] == 1)
    gates = normalize(gates, (len(gates)+2, (wire, 1)))
    result = verify(gates)
    raw = b''.join(b'\x00' + a.to_bytes(3, 'big') + b.to_bytes(3, 'big') for a, b in gates)
    digest = hashlib.sha256(raw).hexdigest()
    if not result['valid'] or digest != RESULT_HASH:
        raise ValueError('Repair failed exhaustive verification or reproducibility check')
    result['rawNetlistSha256'] = digest
    return {'taskId': 60, 'nIn': 8, 'nOut': 8, 'nState': 0,
            'status': 'VALID_TIES_SNAPSHOT_NOT_IMPROVED', 'onChainSubmitted': False,
            'globallyOptimalProved': False, 'rawNetlist': '0x'+raw.hex(), 'verification': result}


def default_input(name):
    local = ROOT/name
    return local if local.exists() else ROOT.parent/'task060-mul4-20260923'/name


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--near', type=Path, default=default_input('near_miss_116_NOT_VALID.json'))
    parser.add_argument('--donor', type=Path, default=default_input('best_known_117.json'))
    parser.add_argument('--out', type=Path, default=ROOT/'reproduced117.json')
    args = parser.parse_args()
    result = repair(load(args.near, NEAR_HASH), load(args.donor, DONOR_HASH))
    args.out.write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result['verification'], indent=2))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, KeyError, StopIteration) as exc:
        raise SystemExit('Repair failed: ' + str(exc))
