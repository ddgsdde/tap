#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,subprocess,sys
from pathlib import Path
from exact_nand import resolve_truth,generate,parse_model,verify_candidate,executable

def main():
    ap=argparse.ArgumentParser()
    g=ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--reference")
    g.add_argument("--truth-hex")
    ap.add_argument("--inputs",type=int);ap.add_argument("--outputs",type=int)
    ap.add_argument("--gates",type=int,required=True);ap.add_argument("--depth",type=int,required=True)
    ap.add_argument("--timeout",type=int,default=900);ap.add_argument("--seed",type=int,default=1)
    ap.add_argument("--out-dir",required=True)
    args=ap.parse_args()
    inputs,outputs,truths=resolve_truth(args)
    out=Path(args.out_dir);out.mkdir(parents=True,exist_ok=True)
    meta=generate(inputs,outputs,truths,args.gates,args.depth,out/"query.cnf",out/"query.meta.json")
    kissat=executable(Path(".offline/bin/kissat"),"kissat")
    cmd=[kissat,f"--time={args.timeout}",f"--seed={args.seed}",str(out/"query.cnf")]
    proc=subprocess.run(cmd,text=True,capture_output=True)
    (out/"kissat.log").write_text(proc.stdout+proc.stderr)
    status="SAT" if "s SATISFIABLE" in proc.stdout else ("UNSAT" if "s UNSATISFIABLE" in proc.stdout else "UNKNOWN")
    res={"status":status,"bounds":{"gatesAtMost":args.gates,"depthAtMost":args.depth},"cnf":meta["cnf"]}
    if status=="SAT":
        cand=parse_model(proc.stdout,meta);verify_candidate(cand,truths)
        res["candidateVerified"]=True;res["candidate"]=cand
        (out/"candidate.json").write_text(json.dumps(cand,indent=2)+"\n")
    (out/"result.json").write_text(json.dumps(res,indent=2)+"\n")
    print(json.dumps(res,indent=2))
    return 0 if status!="UNKNOWN" else 3
if __name__=="__main__":sys.exit(main())
