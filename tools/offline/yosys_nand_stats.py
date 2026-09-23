#!/usr/bin/env python3
from __future__ import annotations
import argparse, json
from pathlib import Path

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("json_file")
    ap.add_argument("--out")
    args=ap.parse_args()
    doc=json.loads(Path(args.json_file).read_text())
    if len(doc.get("modules",{})) != 1:
        raise SystemExit("expected one module")
    module_name,module=next(iter(doc["modules"].items()))
    ports=module["ports"]
    inputs=[(name,p["bits"][0]) for name,p in ports.items() if p["direction"]=="input"]
    outputs=[(name,p["bits"][0]) for name,p in ports.items() if p["direction"]=="output"]
    raw=[]
    for name,c in module.get("cells",{}).items():
        typ=c["type"]
        if typ not in ("$_NAND_","$_NOT_","$_BUF_"):
            raw.append({"name":name,"type":typ,"unsupported":True})
            continue
        ins=[c["connections"]["A"][0]]
        if typ=="$_NAND_":
            ins.append(c["connections"]["B"][0])
        raw.append({"name":name,"type":typ,"ins":ins,"y":c["connections"]["Y"][0]})
    unsupported=[c for c in raw if c.get("unsupported")]
    if unsupported:
        raise SystemExit(f"unsupported cells: {[x['type'] for x in unsupported]}")
    cells=[c for c in raw if not c.get("unsupported")]
    known=set(bit for _,bit in inputs) | {"0","1"}
    depths={bit:0 for bit in known}
    topo=[]
    rem=cells[:]
    while rem:
        progressed=False
        for c in rem[:]:
            if all(x in known for x in c["ins"]):
                if c["type"]=="$_BUF_":
                    depths[c["y"]]=max(depths[x] for x in c["ins"])
                else:
                    depths[c["y"]]=1+max(depths[x] for x in c["ins"])
                known.add(c["y"]); topo.append(c); rem.remove(c); progressed=True
        if not progressed:
            raise SystemExit("cell graph is not acyclic/topologically resolvable")
    fanout={}
    for c in topo:
        for x in c["ins"]:
            fanout[x]=fanout.get(x,0)+1
    outrows=[]
    for name,bit in outputs:
        outrows.append({
            "name":name,
            "wire":bit,
            "depth":depths.get(bit,0),
            "internalFanout":fanout.get(bit,0),
            "direct": bit in {x for _,x in inputs} or bit in ("0","1"),
        })
    result={
        "module":module_name,
        "inputCount":len(inputs),
        "outputCount":len(outputs),
        "cells":{
            "nand":sum(c["type"]=="$_NAND_" for c in topo),
            "not":sum(c["type"]=="$_NOT_" for c in topo),
            "buf":sum(c["type"]=="$_BUF_" for c in topo),
            "nandEquivalent":sum(c["type"] in ("$_NAND_","$_NOT_") for c in topo),
        },
        "outputDepths":[x["depth"] for x in outrows],
        "maxOutputDepth":max((x["depth"] for x in outrows),default=0),
        "outputs":outrows,
    }
    text=json.dumps(result,indent=2)+"\n"
    if args.out: Path(args.out).write_text(text)
    print(text,end="")
if __name__=="__main__":
    main()
