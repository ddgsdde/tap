#!/usr/bin/env python3
"""Offline exact synthesis and optimality proofs for combinational NAND2 DAGs.

The physical model matches TapeOut: constants 0/1 and primary inputs are
available at depth zero, every gate is a two-input NAND, and the final nOut
physical gates are the ordered outputs.  A bounded UNSAT result is accepted
only after drat-trim verifies Kissat's proof certificate.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_KISSAT = ROOT / ".offline" / "bin" / "kissat"
DEFAULT_DRAT = ROOT / ".offline" / "bin" / "drat-trim"


class Cnf:
    def __init__(self) -> None:
        self.nvars = 0
        self.clauses: list[list[int]] = []

    def var(self) -> int:
        self.nvars += 1
        return self.nvars

    def add(self, *literals: int | bool) -> None:
        if any(literal is True for literal in literals):
            return
        self.clauses.append([int(literal) for literal in literals if literal is not False])

    def exactly_one(self, variables: list[int]) -> None:
        self.add(*variables)
        if len(variables) < 2:
            return
        prefix = [self.var() for _ in range(len(variables) - 1)]
        self.add(-variables[0], prefix[0])
        for index in range(1, len(variables) - 1):
            self.add(-variables[index], prefix[index])
            self.add(-prefix[index - 1], prefix[index])
            self.add(-variables[index], -prefix[index - 1])
        self.add(-variables[-1], -prefix[-1])


def neg(literal: int | bool) -> int | bool:
    return not literal if isinstance(literal, bool) else -literal


def parse_truths(text: str, inputs: int, outputs: int) -> list[int]:
    values = [int(part.strip(), 0 if part.strip().lower().startswith("0x") else 16)
              for part in text.split(",")]
    if len(values) != outputs:
        raise ValueError("--truth-hex needs one comma-separated column per output")
    limit = 1 << (1 << inputs)
    if any(value < 0 or value >= limit for value in values):
        raise ValueError("truth column does not fit the input width")
    return values


def truths_from_reference(path: Path) -> tuple[int, int, list[int]]:
    record = json.loads(path.read_text())
    task = record["task"]
    if task["kind"] != "comb":
        raise ValueError("exact truth extraction currently supports combinational tasks")
    inputs, outputs = int(task["nIn"]), int(task["nOut"])
    if inputs > 20:
        raise ValueError("refusing to enumerate more than 2^20 input patterns")
    elements = record["decoded"]["elements"]
    if any(element["op"] != "NAND" for element in elements):
        raise ValueError("reference must be a pure NAND combinational netlist")
    columns = [0] * outputs
    for word in range(1 << inputs):
        signals = [0, 1] + [(word >> bit) & 1 for bit in range(inputs)]
        for element in elements:
            if element["out"] != len(signals):
                raise ValueError("reference signals are not topologically contiguous")
            signals.append(1 ^ (signals[element["a"]] & signals[element["b"]]))
        for bit, value in enumerate(signals[-outputs:]):
            columns[bit] |= value << word
    return inputs, outputs, columns


def resolve_truth(args: argparse.Namespace) -> tuple[int, int, list[int]]:
    if args.reference:
        inputs, outputs, truths = truths_from_reference(Path(args.reference))
        if args.inputs is not None and args.inputs != inputs:
            raise ValueError("--inputs disagrees with the reference")
        if args.outputs is not None and args.outputs != outputs:
            raise ValueError("--outputs disagrees with the reference")
        return inputs, outputs, truths
    if args.truth_hex is None or args.inputs is None or args.outputs is None:
        raise ValueError("provide --reference or --truth-hex with --inputs and --outputs")
    return args.inputs, args.outputs, parse_truths(args.truth_hex, args.inputs, args.outputs)


def generate(inputs: int, outputs: int, truths: list[int], gates: int, depth: int,
             cnf_path: Path, metadata_path: Path) -> dict:
    if inputs < 0 or outputs < 1 or gates < outputs or depth < 1:
        raise ValueError("invalid circuit dimensions")
    patterns = 1 << inputs
    base = inputs + 2
    cnf = Cnf()
    values = [[cnf.var() for _ in range(patterns)] for _ in range(base + gates)]
    for word in range(patterns):
        cnf.add(-values[0][word])
        cnf.add(values[1][word])
        for bit in range(inputs):
            cnf.add(values[2 + bit][word] if (word >> bit) & 1 else -values[2 + bit][word])

    depth_le = [[cnf.var() for _ in range(depth)] for _ in range(gates)]
    for gate in range(gates):
        for level in range(depth - 1):
            cnf.add(-depth_le[gate][level], depth_le[gate][level + 1])

    def source_depth_le(node: int, level: int) -> int | bool:
        if node < base:
            return True
        if level == 0:
            return False
        return depth_le[node - base][level - 1]

    selectors: list[list[tuple[int, int, int]]] = []
    for gate in range(gates):
        out_node = base + gate
        choices: list[tuple[int, int, int]] = []
        for left in range(out_node):
            for right in range(left, out_node):
                selected = cnf.var()
                choices.append((left, right, selected))
                for word in range(patterns):
                    out, a, b = values[out_node][word], values[left][word], values[right][word]
                    cnf.add(-selected, a, out)
                    cnf.add(-selected, b, out)
                    cnf.add(-selected, -a, -b, -out)
                for level in range(1, depth + 1):
                    out_le = depth_le[gate][level - 1]
                    a_le = source_depth_le(left, level - 1)
                    b_le = source_depth_le(right, level - 1)
                    cnf.add(-selected, -out_le, a_le)
                    cnf.add(-selected, -out_le, b_le)
                    cnf.add(-selected, neg(a_le), neg(b_le), out_le)
        cnf.exactly_one([selected for _, _, selected in choices])
        selectors.append(choices)

    first_output = gates - outputs
    for bit, truth in enumerate(truths):
        node = base + first_output + bit
        for word in range(patterns):
            cnf.add(values[node][word] if (truth >> word) & 1 else -values[node][word])
        cnf.add(depth_le[first_output + bit][depth - 1])

    cnf_path.parent.mkdir(parents=True, exist_ok=True)
    with cnf_path.open("w") as handle:
        handle.write(f"p cnf {cnf.nvars} {len(cnf.clauses)}\n")
        for clause in cnf.clauses:
            handle.write(" ".join(map(str, clause)) + " 0\n")
    metadata = {
        "schemaVersion": 1,
        "inputs": inputs,
        "outputs": outputs,
        "truthHex": [hex(value) for value in truths],
        "gates": gates,
        "depthBound": depth,
        "base": base,
        "selectors": selectors,
        "cnf": {"variables": cnf.nvars, "clauses": len(cnf.clauses)},
    }
    metadata_path.write_text(json.dumps(metadata, separators=(",", ":")) + "\n")
    return metadata


def parse_model(text: str, metadata: dict) -> dict:
    positive: set[int] = set()
    for line in text.splitlines():
        if line.startswith("v "):
            positive.update(int(token) for token in line[2:].split() if int(token) > 0)
    pairs = []
    for choices in metadata["selectors"]:
        matches = [(left, right) for left, right, selected in choices if selected in positive]
        if len(matches) != 1:
            raise ValueError(f"expected one selected fan-in pair, got {matches}")
        pairs.append(matches[0])
    base = metadata["base"]
    depths = [0] * base
    for left, right in pairs:
        depths.append(max(depths[left], depths[right]) + 1)
    output_depths = depths[-metadata["outputs"]:]
    candidate = {
        "inputs": metadata["inputs"],
        "outputs": metadata["outputs"],
        "pairs": pairs,
        "gates": len(pairs),
        "outputDepths": output_depths,
        "depth": max(output_depths),
    }
    candidate["cost"] = candidate["gates"] * candidate["depth"] ** 3
    return candidate


def verify_candidate(candidate: dict, truths: list[int]) -> None:
    inputs, outputs = candidate["inputs"], candidate["outputs"]
    pairs = candidate["pairs"]
    if len(pairs) < outputs:
        raise ValueError("candidate has fewer gates than outputs")
    observed = [0] * outputs
    depths = [0] * (inputs + 2)
    for word in range(1 << inputs):
        signals = [0, 1] + [(word >> bit) & 1 for bit in range(inputs)]
        for gate, (left, right) in enumerate(pairs):
            if not (0 <= left <= right < inputs + 2 + gate):
                raise ValueError(f"gate {gate} has an invalid forward reference")
            signals.append(1 ^ (signals[left] & signals[right]))
        for bit, value in enumerate(signals[-outputs:]):
            observed[bit] |= value << word
    for gate, (left, right) in enumerate(pairs):
        depths.append(max(depths[left], depths[right]) + 1)
    if observed != truths:
        raise ValueError(f"candidate truth mismatch: {[hex(x) for x in observed]}")
    if max(depths[-outputs:]) != candidate["depth"]:
        raise ValueError("candidate depth mismatch")


def executable(path: Path, fallback: str) -> str:
    if path.is_file() and path.stat().st_mode & 0o111:
        return str(path)
    found = shutil.which(fallback)
    if found:
        return found
    raise FileNotFoundError(f"{fallback} is unavailable; run tools/offline/build.sh")


def prove(args: argparse.Namespace) -> dict:
    inputs, outputs, truths = resolve_truth(args)
    out = Path(args.out_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)
    cnf_path, metadata_path = out / "query.cnf", out / "query.meta.json"
    proof_path, solver_log = out / "query.drat", out / "kissat.log"
    metadata = generate(inputs, outputs, truths, args.gates, args.depth, cnf_path, metadata_path)
    kissat = executable(Path(args.kissat), "kissat")
    command = [kissat, "--no-binary", f"--time={args.timeout}"]
    if args.seed is not None:
        command.append(f"--seed={args.seed}")
    command.extend([str(cnf_path), str(proof_path)])
    started = time.monotonic()
    process = subprocess.run(command, text=True, capture_output=True, check=False)
    elapsed = time.monotonic() - started
    solver_log.write_text(process.stdout + process.stderr)
    status = ("UNSAT" if "s UNSATISFIABLE" in process.stdout else
              "SAT" if "s SATISFIABLE" in process.stdout else "UNKNOWN")
    result = {
        "status": status,
        "seconds": round(elapsed, 3),
        "solverExitCode": process.returncode,
        "bounds": {"gatesAtMost": args.gates, "depthAtMost": args.depth},
        "truthHex": [hex(value) for value in truths],
        "cnf": metadata["cnf"],
        "proofVerified": False,
        "candidateVerified": False,
    }
    if status == "UNSAT":
        drat = executable(Path(args.drat_trim), "drat-trim")
        checked = subprocess.run([drat, str(cnf_path), str(proof_path)],
                                 text=True, capture_output=True, check=False)
        (out / "drat-trim.log").write_text(checked.stdout + checked.stderr)
        result["proofVerified"] = checked.returncode == 0 and "VERIFIED" in checked.stdout
        if not result["proofVerified"]:
            raise RuntimeError("UNSAT proof failed independent drat-trim verification")
    elif status == "SAT":
        candidate = parse_model(process.stdout, metadata)
        verify_candidate(candidate, truths)
        (out / "candidate.json").write_text(json.dumps(candidate, indent=2) + "\n")
        result["candidateVerified"] = True
        result["candidate"] = candidate
    else:
        result["reason"] = "timeout or solver UNKNOWN; this is not an optimality proof"
    for path, key in ((cnf_path, "cnfSha256"), (proof_path, "proofSha256")):
        if path.exists():
            result[key] = hashlib.sha256(path.read_bytes()).hexdigest()
    (out / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    return result


def sweep(args: argparse.Namespace) -> dict:
    inputs, outputs, _truths = resolve_truth(args)
    maximum_depth = 0
    while outputs * (maximum_depth + 1) ** 3 < args.incumbent_cost:
        maximum_depth += 1
    root = Path(args.out_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    queries = []
    for depth in range(1, maximum_depth + 1):
        gates = (args.incumbent_cost - 1) // depth ** 3
        if gates < outputs:
            continue
        if args.max_gates is not None and gates > args.max_gates:
            queries.append({"depth": depth, "gatesAtMost": gates, "status": "SKIPPED_LIMIT"})
            continue
        query_args = argparse.Namespace(**vars(args))
        query_args.command = "prove"
        query_args.gates = gates
        query_args.depth = depth
        query_args.out_dir = str(root / f"d{depth:02d}-g{gates}")
        result = prove(query_args)
        queries.append({"depth": depth, "gatesAtMost": gates, **result})
        if result["status"] == "SAT":
            break
    found = next((query for query in queries if query["status"] == "SAT"), None)
    complete = found is None and all(query["status"] == "UNSAT" and query["proofVerified"]
                                     for query in queries)
    summary = {
        "incumbentCost": args.incumbent_cost,
        "inputs": inputs,
        "outputs": outputs,
        "maximumRelevantDepth": maximum_depth,
        "queries": queries,
        "cheaperCircuitFound": found is not None,
        "globalCostOptimalityProved": complete,
    }
    if found:
        summary["cheaperCandidate"] = found.get("candidate")
    elif not complete:
        summary["reason"] = "at least one cheaper cost region was skipped or UNKNOWN"
    (root / "sweep-summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))
    return summary


def add_truth_arguments(parser: argparse.ArgumentParser) -> None:
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--reference", help="exported data/latest/netlists/... JSON")
    group.add_argument("--truth-hex", help="comma-separated truth columns; bit x is input x")
    parser.add_argument("--inputs", type=int)
    parser.add_argument("--outputs", type=int)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    command = sub.add_parser("prove", help="solve one gate/depth bound and verify its result")
    add_truth_arguments(command)
    command.add_argument("--gates", type=int, required=True)
    command.add_argument("--depth", type=int, required=True)
    command.add_argument("--timeout", type=int, default=900)
    command.add_argument("--seed", type=int)
    command.add_argument("--out-dir", required=True)
    command.add_argument("--kissat", default=str(DEFAULT_KISSAT))
    command.add_argument("--drat-trim", default=str(DEFAULT_DRAT))
    sweep_command = sub.add_parser("sweep", help="check every gate/depth region cheaper than an incumbent cost")
    add_truth_arguments(sweep_command)
    sweep_command.add_argument("--incumbent-cost", type=int, required=True)
    sweep_command.add_argument("--timeout", type=int, default=900)
    sweep_command.add_argument("--seed", type=int)
    sweep_command.add_argument("--max-gates", type=int,
                               help="resource guard; skipped regions make the conclusion incomplete")
    sweep_command.add_argument("--out-dir", required=True)
    sweep_command.add_argument("--kissat", default=str(DEFAULT_KISSAT))
    sweep_command.add_argument("--drat-trim", default=str(DEFAULT_DRAT))
    args = parser.parse_args()
    try:
        result = prove(args) if args.command == "prove" else sweep(args)
    except (ValueError, FileNotFoundError, RuntimeError) as error:
        parser.error(str(error))
    if args.command == "prove" and result["status"] == "UNKNOWN":
        sys.exit(3)
    if args.command == "sweep" and not (result["globalCostOptimalityProved"] or result["cheaperCircuitFound"]):
        sys.exit(3)


if __name__ == "__main__":
    main()
