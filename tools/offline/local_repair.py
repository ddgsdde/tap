#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, subprocess, sys
from pathlib import Path
from exact_nand import Cnf, neg, truths_from_reference, executable, verify_candidate

def add_nand(cnf, values, out, a, b, patterns, selected=True):
    for word in range(patterns):
        ov,av,bv=values[out][word],values[a][word],values[b][word]
        if selected is True:
            cnf.add(av, ov)
            cnf.add(bv, ov)
            cnf.add(-av, -bv, -ov)
        else:
            cnf.add(-selected, av, ov)
            cnf.add(-selected, bv, ov)
            cnf.add(-selected, -av, -bv, -ov)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--reference",required=True)
    ap.add_argument("--seed-candidate",required=True)
    ap.add_argument("--free-gates",required=True)
    ap.add_argument("--depth",type=int,required=True)
    ap.add_argument("--timeout",type=int,default=600)
    ap.add_argument("--out-dir",required=True)
    args=ap.parse_args()

    inputs,outputs,truths=truths_from_reference(Path(args.reference))
    seed=json.loads(Path(args.seed_candidate).read_text())
    pairs=[tuple(x) for x in seed["pairs"]]
    free={int(x) for x in args.free_gates.split(",") if x.strip()}
    gates=len(pairs)
    patterns=1<<inputs
    base=inputs+2
    cnf=Cnf()
    values=[[cnf.var() for _ in range(patterns)] for _ in range(base+gates)]
    for word in range(patterns):
        cnf.add(-values[0][word]); cnf.add(values[1][word])
        for bit in range(inputs):
            cnf.add(values[2+bit][word] if (word>>bit)&1 else -values[2+bit][word])

    depth=args.depth
    depth_le=[[cnf.var() for _ in range(depth)] for _ in range(gates)]
    def src_le(node,level):
        if node<base: return True
        if level==0: return False
        return depth_le[node-base][level-1]

    selectors=[]
    for gi in range(gates):
        out=base+gi
        for lev in range(depth-1):
            cnf.add(-depth_le[gi][lev],depth_le[gi][lev+1])
        choices=[]
        if gi in free:
            pair_iter=((a,b) for a in range(out) for b in range(a,out))
        else:
            pair_iter=[pairs[gi]]
        for a,b in pair_iter:
            if gi in free:
                sel=cnf.var(); choices.append((a,b,sel)); add_nand(cnf,values,out,a,b,patterns,sel)
                for lev in range(1,depth+1):
                    ole=depth_le[gi][lev-1]; ale=src_le(a,lev-1); ble=src_le(b,lev-1)
                    cnf.add(-sel,-ole,ale); cnf.add(-sel,-ole,ble); cnf.add(-sel,neg(ale),neg(ble),ole)
            else:
                add_nand(cnf,values,out,a,b,patterns,True)
                for lev in range(1,depth+1):
                    ole=depth_le[gi][lev-1]; ale=src_le(a,lev-1); ble=src_le(b,lev-1)
                    cnf.add(-ole,ale); cnf.add(-ole,ble); cnf.add(neg(ale),neg(ble),ole)
        if gi in free:
            cnf.exactly_one([x[2] for x in choices])
        selectors.append(choices)

    first=gates-outputs
    for bit,truth in enumerate(truths):
        node=base+first+bit
        for word in range(patterns):
            cnf.add(values[node][word] if (truth>>word)&1 else -values[node][word])
        cnf.add(depth_le[first+bit][depth-1])

    outdir=Path(args.out_dir); outdir.mkdir(parents=True,exist_ok=True)
    cnfpath=outdir/"repair.cnf"
    with cnfpath.open("w") as f:
        f.write(f"p cnf {cnf.nvars} {len(cnf.clauses)}\n")
        for clause in cnf.clauses: f.write(" ".join(map(str,clause))+" 0\n")
    kissat=executable(Path(".offline/bin/kissat"),"kissat")
    proc=subprocess.run([kissat,"--no-binary",f"--time={args.timeout}",str(cnfpath)],text=True,capture_output=True)
    (outdir/"kissat.log").write_text(proc.stdout+proc.stderr)
    if "s SATISFIABLE" not in proc.stdout:
        status="UNSAT" if "s UNSATISFIABLE" in proc.stdout else "UNKNOWN"
        result={"status":status,"freeGates":sorted(free),"variables":cnf.nvars,"clauses":len(cnf.clauses)}
        (outdir/"result.json").write_text(json.dumps(result,indent=2)+"\n")
        print(json.dumps(result,indent=2)); return 0 if status=="UNSAT" else 3
    positive=set()
    for line in proc.stdout.splitlines():
        if line.startswith("v "):
            positive.update(int(t) for t in line[2:].split() if int(t)>0)
    solved=[]
    for gi in range(gates):
        if gi not in free:
            solved.append(pairs[gi]); continue
        matches=[(a,b) for a,b,s in selectors[gi] if s in positive]
        if len(matches)!=1: raise RuntimeError((gi,matches))
        solved.append(matches[0])
    depths=[0]*base
    for a,b in solved: depths.append(max(depths[a],depths[b])+1)
    cand={"inputs":inputs,"outputs":outputs,"pairs":solved,"gates":gates,
          "outputDepths":depths[-outputs:],"depth":max(depths[-outputs:])}
    cand["cost"]=gates*cand["depth"]**3
    verify_candidate(cand,truths)
    (outdir/"candidate.json").write_text(json.dumps(cand,indent=2)+"\n")
    result={"status":"SAT","candidateVerified":True,"candidate":cand,
            "freeGates":sorted(free),"variables":cnf.nvars,"clauses":len(cnf.clauses)}
    (outdir/"result.json").write_text(json.dumps(result,indent=2)+"\n")
    print(json.dumps(result,indent=2))
    return 0

if __name__=="__main__":
    sys.exit(main())
