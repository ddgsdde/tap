#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, re, shutil, subprocess, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "offline"))
from exact_nand import truths_from_reference, verify_candidate

def bv(v, w):
    return f"(_ bv{v} {w})"

def mux(sel, exprs, sw):
    out = exprs[-1]
    for i in range(len(exprs)-2, -1, -1):
        out = f"(ite (= {sel} {bv(i, sw)}) {exprs[i]} {out})"
    return out

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--reference", required=True)
    ap.add_argument("--gates", type=int, required=True)
    ap.add_argument("--depth", type=int, required=True)
    ap.add_argument("--timeout", type=int, default=1200)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--seed-candidate")
    ap.add_argument("--free-gates", help="comma-separated gate indexes; all other gates are fixed to the seed")
    ap.add_argument("--out-dir", required=True)
    args=ap.parse_args()

    inputs, outputs, truths = truths_from_reference(Path(args.reference))
    if inputs > 8:
        raise SystemExit("bitvec prototype is for small-input tasks")
    gates=args.gates
    seed_pairs=None
    free=None
    if args.seed_candidate:
        seed_doc=json.loads(Path(args.seed_candidate).read_text())
        seed_pairs=[tuple(sorted(map(int,p))) for p in seed_doc["pairs"]]
        if len(seed_pairs)!=gates:
            raise SystemExit("seed candidate gate count disagrees with --gates")
        free=set(int(x) for x in (args.free_gates or "").split(",") if x.strip())

    base=inputs+2
    patterns=1<<inputs
    vw=patterns
    sw=max(1,(base+gates-1).bit_length())
    dw=max(2,(gates+2).bit_length())
    mask=(1<<patterns)-1

    vals=[bv(0,vw), bv(mask,vw)]
    for bit in range(inputs):
        col=sum(1<<word for word in range(patterns) if (word>>bit)&1)
        vals.append(bv(col,vw))
    deps=[bv(0,dw) for _ in range(base)]

    lines=["(set-logic QF_BV)",
           f"(set-option :timeout {args.timeout*1000})",
           f"(set-option :smt.random_seed {args.seed})",
           "(set-option :produce-models true)"]
    for gi in range(gates):
        out=base+gi
        lines += [
            f"(declare-fun a{gi} () (_ BitVec {sw}))",
            f"(declare-fun b{gi} () (_ BitVec {sw}))",
            f"(declare-fun g{gi} () (_ BitVec {vw}))",
            f"(declare-fun d{gi} () (_ BitVec {dw}))",
            f"(assert (bvule a{gi} b{gi}))",
            f"(assert (bvult b{gi} {bv(out,sw)}))",
        ]
        if seed_pairs is not None and gi not in free:
            sa,sb=seed_pairs[gi]
            lines.append(f"(assert (= a{gi} {bv(sa,sw)}))")
            lines.append(f"(assert (= b{gi} {bv(sb,sw)}))")
        av=mux(f"a{gi}", vals, sw)
        bb=mux(f"b{gi}", vals, sw)
        ad=mux(f"a{gi}", deps, sw)
        bd=mux(f"b{gi}", deps, sw)
        lines.append(f"(assert (= g{gi} (bvnot (bvand {av} {bb}))))")
        lines.append(f"(assert (= d{gi} (bvadd {bv(1,dw)} (ite (bvuge {ad} {bd}) {ad} {bd}))))")
        vals.append(f"g{gi}")
        deps.append(f"d{gi}")

    first=gates-outputs
    for bit,t in enumerate(truths):
        gi=first+bit
        lines.append(f"(assert (= g{gi} {bv(t,vw)}))")
        lines.append(f"(assert (bvule d{gi} {bv(args.depth,dw)}))")

    names=" ".join(sum(([f"a{i}",f"b{i}",f"d{i}"] for i in range(gates)),[]))
    lines += ["(check-sat)", f"(get-value ({names}))"]
    out=Path(args.out_dir); out.mkdir(parents=True,exist_ok=True)
    smt=out/"query.smt2"; smt.write_text("\n".join(lines)+"\n")
    z3=shutil.which("z3")
    if not z3: raise SystemExit("z3 not found")
    start=time.monotonic()
    proc=subprocess.run([z3, str(smt)], text=True, capture_output=True)
    elapsed=time.monotonic()-start
    (out/"z3.log").write_text(proc.stdout+proc.stderr)
    status=proc.stdout.splitlines()[0].strip() if proc.stdout.strip() else "unknown"
    result={"status":status.upper(),"seconds":round(elapsed,3),"gates":gates,"depthBound":args.depth,
            "inputs":inputs,"outputs":outputs,"truthHex":[hex(x) for x in truths],
            "freeGates":sorted(free) if free is not None else None}
    if status=="sat":
        found={}
        for name,val in re.findall(r"\((a\d+|b\d+|d\d+)\s+(#x[0-9a-fA-F]+|#b[01]+|\(_ bv\d+ \d+\))\)",proc.stdout):
            if val.startswith("#x"): found[name]=int(val[2:],16)
            elif val.startswith("#b"): found[name]=int(val[2:],2)
            else: found[name]=int(re.search(r"bv(\d+)",val).group(1))
        pairs=[(found[f"a{i}"],found[f"b{i}"]) for i in range(gates)]
        ds=[found[f"d{i}"] for i in range(gates)]
        cand={"inputs":inputs,"outputs":outputs,"pairs":pairs,"gates":gates,
              "outputDepths":ds[-outputs:],"depth":max(ds[-outputs:])}
        cand["cost"]=gates*cand["depth"]**3
        verify_candidate(cand, truths)
        (out/"candidate.json").write_text(json.dumps(cand,indent=2)+"\n")
        result["candidateVerified"]=True
        result["candidate"]=cand
    (out/"result.json").write_text(json.dumps(result,indent=2)+"\n")
    print(json.dumps(result,indent=2))

if __name__=="__main__":
    main()
