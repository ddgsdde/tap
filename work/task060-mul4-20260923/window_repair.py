#!/usr/bin/env python3
"""Task 60 local SAT repair. Requires the system libz3 shared library, not z3py.
A timeout or local UNSAT is NOT a global lower-bound proof. No on-chain actions.
"""
import argparse, collections, ctypes as C, ctypes.util, json, random, re, time
from pathlib import Path
from verify import read_gates, verify as verify_scalar
ROOT = Path(__file__).resolve().parent
OUT = ROOT / "candidate_116_verified.json"
M = (1 << 256) - 1
INPUTS = [0, M] + [sum(((x >> i) & 1) << x for x in range(256)) for i in range(8)]
TARGET = [sum(((((x & 15) * (x >> 4)) >> i) & 1) << x for x in range(256)) for i in range(8)]
Z = C.CDLL(ctypes.util.find_library("z3") or "/lib/x86_64-linux-gnu/libz3.so.4")
for name, args, result in [
    ("Z3_mk_config", [], C.c_void_p),
    ("Z3_mk_context", [C.c_void_p], C.c_void_p),
    ("Z3_del_config", [C.c_void_p], None),
    ("Z3_del_context", [C.c_void_p], None),
    ("Z3_eval_smtlib2_string", [C.c_void_p, C.c_char_p], C.c_char_p),
]:
    function = getattr(Z, name)
    function.argtypes, function.restype = args, result


def verify(gs):
    result = verify_scalar({"gates": gs})
    if not result["valid"]:
        raise ValueError("SAT candidate failed independent exhaustive verification")
    return result["cost"], result["gateCount"], result["depth"]


def save(gs, path, history):
    result = verify_scalar({"gates": gs})
    if not result["valid"] or result["cost"] >= 59904:
        raise ValueError("Refusing to save an invalid or non-improving candidate")
    raw = b"".join(bytes([0])+a.to_bytes(3,"big")+b.to_bytes(3,"big") for a,b in gs)
    obj = {"taskId":60, "nIn":8, "nOut":8, "nState":0,
           "status":"VALID_BEATS_SNAPSHOT_123477186", "onChainSubmitted":False,
           "globallyOptimalProved":False, "rawNetlist":"0x"+raw.hex(),
           "verification":result, "searchHistory":history}
    path.write_text(json.dumps(obj, indent=2)+"\n")

def sim(gs):
 v=INPUTS[:];ds=[0]*10
 for a,b in gs:
  v.append(M^(v[a]&v[b]));ds.append(1+max(ds[a],ds[b]))
 return v,ds

def repair_care(gs,i,v):
 w=v[:];w[i]^=M;desc={i}
 for j in range(i+1,len(v)):
  a,b=gs[j-10]
  if a in desc or b in desc:desc.add(j);w[j]=M^(w[a]&w[b])
 bad0=bad1=0
 for a,b,t in zip(v[-8:],w[-8:],TARGET):bad0|=a^t;bad1|=b^t
 if bad0&bad1:return None
 return bad0|bad1,v[i]^bad0,desc

def patch(gs,mutable,timeout=1000,seed=0,divlimit=0,patterns=None, levels=None):
 vv,dd=sim(gs);dd=levels if levels is not None else dd;n=len(vv);mut=set(mutable);affected=set(mut)
 for j in range(10,n):
  if any(x in affected for x in gs[j-10]):affected.add(j)
 if patterns is None:patterns=list(range(256))
 width=len(patterns)
 def val(t):return sum(((t>>x)&1)<<i for i,x in enumerate(patterns))
 def bv(v,w):return f'(_ bv{v} {w})'
 def choose(name,opts,bw):
  expr=opts[-1]
  for j in range(len(opts)-2,-1,-1):expr=f'(ite (= {name} {bv(j,bw)}) {opts[j]} {expr})'
  return expr
 names={j:(f'v{j}' if j in affected else bv(val(vv[j]),width)) for j in range(n)}
 ss=['(set-logic QF_BV)',f'(set-option :timeout {timeout})',f'(set-option :random-seed {seed})']
 choices={}
 for j in sorted(affected):
  ss.append(f'(declare-const v{j} (_ BitVec {width}))')
  if j in mut:
   av=[i for i in range(j) if dd[i]<dd[j]]
   if divlimit and len(av)>divlimit:
    a,b=gs[j-10]
    av=sorted(av,key=lambda x:(x not in (a,b), min((vv[x]^vv[a]).bit_count(),(vv[x]^vv[b]).bit_count()),dd[x]))[:divlimit]
    av.sort()
   choices[j]=av;bw=max(1,len(av).bit_length())
   ss.extend(f'(declare-const {ab}{j} (_ BitVec {bw}))' for ab in ('a','b'))
   ss += [f'(assert (bvule a{j} b{j}))',f'(assert (bvult b{j} {bv(len(av),bw)}))']
   a=choose(f'a{j}',[names[x] for x in av],bw);b=choose(f'b{j}',[names[x] for x in av],bw)
  else:
   a,b=(names[x] for x in gs[j-10])
  ss.append(f'(assert (= v{j} (bvnot (bvand {a} {b}))))')
 for j,t in enumerate(TARGET,n-8):ss.append(f'(assert (= {names[j]} {bv(val(t),width)}))')
 ss.append('(check-sat)')
 config=Z.Z3_mk_config();ctx=Z.Z3_mk_context(config);Z.Z3_del_config(config)
 try:
  status=Z.Z3_eval_smtlib2_string(ctx,'\n'.join(ss).encode()).decode().strip()
  if status!='sat':return status,None
  keys=' '.join(f'a{j} b{j}' for j in sorted(mut))
  model=Z.Z3_eval_smtlib2_string(ctx,f'(get-value ({keys}))'.encode()).decode()
  matches=re.findall(r'\(([ab]\d+)\s+(#x[0-9a-f]+|#b[01]+|\(_ bv\d+ \d+\))\)',model)
  vals={key:(int(s[2:],16) if s.startswith('#x') else int(s[2:],2) if s.startswith('#b') else int(s.split()[1][2:])) for key,s in matches}
  gg=[tuple(x) for x in gs]
  for j in mut:gg[j-10]=(choices[j][vals[f'a{j}']],choices[j][vals[f'b{j}']])
  return 'sat',gg
 finally:Z.Z3_del_context(ctx)

def run(gs,secs=180,timeout=1500,seed=0,window=5,divlimit=0):
 rng=random.Random(seed);start=time.monotonic();v,d=sim(gs);n=len(v);counts=collections.Counter();attempt=0
 wrong=[j for j in range(n-8,n) if v[j]!=TARGET[j-(n-8)]]
 anc=set(wrong)
 for j in range(n-1,9,-1):
  if j in anc:anc.update(x for x in gs[j-10] if x>=10)
 eligible=[j for j in anc if repair_care(gs,j,v)]
 fan=[[] for _ in range(n)]
 for j,(a,b) in enumerate(gs,10):fan[a].append(j);fan[b].append(j)
 for loops in range(10000):
  if time.monotonic()-start>=secs:break
  root=eligible[loops%len(eligible)] if eligible else rng.choice(list(anc))
  windowset={root};front={root}
  for k in range(4):
   nearby={y for x in front for y in [*gs[x-10],*fan[x]] if y>=10}
   front=nearby-windowset
   cand=list(front);rng.shuffle(cand)
   for j in cand:
    if len(windowset)>=window:break
    windowset.add(j)
   if len(windowset)>=window:break
  if loops%3==2:
   ww=list(windowset);rng.shuffle(ww)
   windowset=set(ww[:-1]);windowset.add(rng.choice(eligible or list(anc)))
  status,gg=patch(gs,windowset,timeout,seed+loops,divlimit);counts[status]+=1;attempt+=1
  print(json.dumps({'window':sorted(windowset),'status':status,'elapsed':round(time.monotonic()-start,3),'attempt':attempt}),flush=True)
  if status=='sat':
   result=verify(gg)
   print('SUCCESS',result,flush=True);save(gg,OUT,[{'mutable':sorted(windowset),'seed':seed}]);return
 print('DONE',dict(counts),'attempts',attempt,'elapsed',time.monotonic()-start,flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", type=Path, default=ROOT/"near_miss_116_NOT_VALID.json")
    ap.add_argument("--output", type=Path, default=OUT)
    ap.add_argument("--seconds", type=int, default=600)
    ap.add_argument("--timeout", type=int, default=10000, help="Milliseconds per SAT query")
    ap.add_argument("--window", type=int, default=8)
    ap.add_argument("--divlimit", type=int, default=0, help="0 offers all timing-admissible earlier wires")
    ap.add_argument("--seed", type=int, default=6061)
    args = ap.parse_args()
    if min(args.seconds, args.timeout, args.window) <= 0 or args.divlimit < 0:
        ap.error("Durations/window must be positive; divlimit must be nonnegative")
    data = json.loads(args.input.read_text())
    gs, _ = read_gates(data)
    initial = verify_scalar(data)
    if initial["valid"]:
        ap.error("Input is already correct; supply the explicitly invalid repair checkpoint")
    if initial["gateCount"] != 116 or initial["depth"] > 8:
        ap.error("This repair setup expects 116 gates at depth at most 8")
    OUT = args.output
    print(json.dumps({"initialVerification": initial}), flush=True)
    run(gs, args.seconds, args.timeout, args.seed, args.window, args.divlimit)
