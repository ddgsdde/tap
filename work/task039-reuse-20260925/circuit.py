"""NAND2 circuit utilities and exact ROBDD checks for task 39.
No third-party Python modules. The outputs are the final seventeen physical gates.
"""
from functools import lru_cache
import ctypes as C, ctypes.util, hashlib, json, random, time
from pathlib import Path
NI=32;NO=17;BASE=34

class BDD:
    """Reduced ordered BDD with complemented edges; terminals are 0 and 1."""
    def __init__(self):
        self.nodes=[(1000,0,0)]
        self.unique={}
        self.cache={}
    def mk(self,var,lo,hi):
        if lo==hi:return lo
        flip=hi&1
        if flip:lo^=1;hi^=1
        key=(var,lo,hi)
        r=self.unique.get(key)
        if r is None:
            r=2*len(self.nodes);self.unique[key]=r;self.nodes.append(key)
        return r^flip
    def var(self,i):return self.mk(i,0,1)
    def and_(self,a,b):
        if a>b:a,b=b,a
        if a==0 or a==(b^1):return 0
        if a==1:return b
        if a==b:return a
        key=(a,b)
        r=self.cache.get(key)
        if r is not None:return r
        av,al,ah=self.nodes[a//2];bv,bl,bh=self.nodes[b//2]
        v=min(av,bv)
        if av==v:al^=a&1;ah^=a&1
        else:al=ah=a
        if bv==v:bl^=b&1;bh^=b&1
        else:bl=bh=b
        r=self.mk(v,self.and_(al,bl),self.and_(ah,bh));self.cache[key]=r
        return r
    def nand(self,a,b):return self.and_(a,b)^1
    def or_(self,a,b):return self.and_(a^1,b^1)^1
    def xor(self,a,b):return self.or_(self.and_(a,b^1),self.and_(a^1,b))
    def evaluate(self,node,word):
        while node>1:
            v,lo,hi=self.nodes[node//2]
            idx=v//2+(16 if v&1 else 0)
            node=(hi if word>>idx&1 else lo)^(node&1)
        return node

B=BDD()
INPUTS=[0,1]+[B.var(2*i) for i in range(16)]+[B.var(2*i+1) for i in range(16)]
TARGET=[];carry=0
for i in range(16):
    a,b=INPUTS[i+2],INPUTS[i+18]
    p=B.xor(a,b);TARGET.append(B.xor(p,carry))
    carry=B.or_(B.and_(a,b),B.and_(p,carry))
TARGET.append(carry)

def decode(obj):
    raw=bytes.fromhex(obj['rawNetlist'].removeprefix('0x'))
    if len(raw)%7:raise ValueError('Byte length is not a multiple of 7')
    gates=[]
    for p in range(0,len(raw),7):
        a=int.from_bytes(raw[p+1:p+4],'big');b=int.from_bytes(raw[p+4:p+7],'big')
        if raw[p]!=0 or max(a,b)>=BASE+len(gates):raise ValueError('Invalid NAND or forward reference')
        gates.append((a,b))
    if len(gates)<NO:raise ValueError('Missing physical outputs')
    return gates

def encode(g):return b''.join(b'\0'+a.to_bytes(3,'big')+b.to_bytes(3,'big') for a,b in g)
def load(p):return decode(json.loads(Path(p).read_text()))
def depths(gs):
    ds=[0]*BASE
    for a,b in gs:ds.append(1+max(ds[a],ds[b]))
    return ds

def metrics(gs):
    d=depths(gs)
    return {'gateCount':len(gs),'depth':max(d),'cost':len(gs)*max(d)**3,'outputDepths':d[-NO:]}

def simulate_bdd(gs):
    v=INPUTS[:]
    for a,b in gs:v.append(B.nand(v[a],v[b]))
    return v

def check_bdd(gs):return simulate_bdd(gs)[-NO:]==TARGET

def scalar(gs,word):
    v=[0,1]+[(word>>i)&1 for i in range(NI)]
    for a,b in gs:v.append(1^(v[a]&v[b]))
    return sum(x<<i for i,x in enumerate(v[-NO:]))

def normalize(gs,replace=None,semantic=True):
    """Prune/merge internal gates. Preserve the final ordered physical outputs."""
    replacements = replace if isinstance(replace, dict) else ({replace[0]:replace[1]} if replace else {})
    ds=depths(gs);vals=simulate_bdd(gs) if semantic and not replacements else None
    best={}
    if vals is not None:
        for i in sorted(range(len(vals)-NO),key=lambda i:(ds[i],i)):
            best.setdefault(vals[i],i)
    mapping={i:i for i in range(BASE)};seen={};body=[];busy=set()
    def expr(e):
        if isinstance(e,int):
            if e in replacements:return expr(replacements[e])
            if vals is not None:e=best.get(vals[e],e)
            if e in mapping:return mapping[e]
            if e in busy:raise ValueError('Cycle')
            busy.add(e);mapping[e]=expr(gs[e-BASE]);busy.remove(e)
            return mapping[e]
        a,b=sorted((expr(e[0]),expr(e[1])))
        if a==0:return 1
        if a==1 and b==1:return 0
        key=(a,b)
        if key not in seen:
            seen[key]=len(body)+BASE;body.append(key)
        return seen[key]
    outputs=[]
    for o in range(BASE+len(gs)-NO,BASE+len(gs)):
        e=replacements.get(o,gs[o-BASE])
        if isinstance(e,int):
            # A physical NAND output is mandatory, not an arbitrary output pointer.
            if e>=BASE:e=gs[e-BASE]
            else:e=((e,1),1)
        outputs.append((expr(e[0]),expr(e[1])))
    return body+outputs

def z3_miter(gs,filename=None,timeout=60000,reference=None):
    """UNSAT means no input can distinguish candidate from 17-bit A+B."""
    Z=C.CDLL(ctypes.util.find_library('z3') or 'libz3.so.4')
    for name,ats,rt in [('Z3_mk_config',[],C.c_void_p),('Z3_mk_context',[C.c_void_p],C.c_void_p),('Z3_del_config',[C.c_void_p],None),('Z3_del_context',[C.c_void_p],None),('Z3_eval_smtlib2_string',[C.c_void_p,C.c_char_p],C.c_char_p)]:
        f=getattr(Z,name);f.argtypes=ats;f.restype=rt
    s=['(set-logic QF_BV)',f'(set-option :timeout {timeout})','(declare-const A (_ BitVec 16))','(declare-const B (_ BitVec 16))','(define-fun n0 () Bool false)','(define-fun n1 () Bool true)']
    for i in range(32):s.append(f'(define-fun n{i+2} () Bool (= ((_ extract {i%16} {i%16}) {"A" if i<16 else "B"}) #b1))')
    for i,(a,b) in enumerate(gs,BASE):s.append(f'(declare-const n{i} Bool)\n(assert (= n{i} (not (and n{a} n{b}))))')
    s.append('(define-fun expected () (_ BitVec 17) (bvadd ((_ zero_extend 1) A) ((_ zero_extend 1) B)))')
    wrong=[f'(xor n{j} (= ((_ extract {k} {k}) expected) #b1))' for k,j in enumerate(range(BASE+len(gs)-NO,BASE+len(gs)))]
    if reference is not None:
        for i,(a,b) in enumerate(reference,BASE):
            na=f'n{a}' if a<BASE else f'r{a}';nb=f'n{b}' if b<BASE else f'r{b}'
            s.append(f'(declare-const r{i} Bool)\n(assert (= r{i} (not (and {na} {nb}))))')
        wrong=[f'(xor n{j} r{k})' for j,k in zip(range(BASE+len(gs)-NO,BASE+len(gs)),range(BASE+len(reference)-NO,BASE+len(reference)))]
    s.append('(assert (or '+' '.join(wrong)+'))');s.append('(check-sat)')
    text='\n'.join(s)+'\n'
    if filename:Path(filename).write_text(text)
    cfg=Z.Z3_mk_config();ctx=Z.Z3_mk_context(cfg);Z.Z3_del_config(cfg)
    start=time.monotonic()
    try:
        result=Z.Z3_eval_smtlib2_string(ctx,text.encode()).decode().strip()
        model=None
        if result=='sat':model=Z.Z3_eval_smtlib2_string(ctx,b'(get-value (A B))').decode()
    finally:Z.Z3_del_context(ctx)
    return {'result':result,'seconds':time.monotonic()-start,'counterexample':model,'allInputAssignments':2**32 if result=='unsat' else None}

def save(gs,path,method,extra=None):
    if not check_bdd(gs):raise ValueError('Incorrect output function')
    raw=encode(gs);obj={'taskId':39,'nIn':32,'nOut':17,'nState':0,'status':'VALID_BEATS_SNAPSHOT' if metrics(gs)['cost']<330088 else 'VALID_NOT_IMPROVED','method':method,'rawNetlist':'0x'+raw.hex(),'verification':{**metrics(gs),'bddEquivalentToAddition':True,'rawNetlistSha256':hashlib.sha256(raw).hexdigest(),'allInputAssignments':2**32},'onChainSubmitted':False,'globallyOptimalProved':False,'comparisonBaseline':{'snapshotBlock':123848100,'circuitId':'16160','gateCount':248,'depth':11,'cost':330088}}
    if extra:obj.update(extra)
    Path(path).write_text(json.dumps(obj,indent=2)+'\n')
    return obj

if __name__=='__main__':
    import argparse
    ap=argparse.ArgumentParser();ap.add_argument('file',nargs='+');args=ap.parse_args()
    for f in args.file:
        gs=load(f);print(f,metrics(gs),'BDD',check_bdd(gs),'nodes',len(B.nodes),flush=True)
        print('Z3',z3_miter(gs),flush=True)
        ng=normalize(gs);print('normalized',metrics(ng),'BDD',check_bdd(ng),flush=True)
        save(ng,Path(f).with_suffix('.norm.json'),'Exact functional merging and dead-logic elimination of '+str(f))
