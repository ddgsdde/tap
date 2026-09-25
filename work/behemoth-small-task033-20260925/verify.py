#!/usr/bin/env python3
"""Exhaustive independent verifier for task 33, unsigned 4-bit addition with carry-in."""
import argparse,hashlib,json
from pathlib import Path

def encode(gates):
 return b''.join(b'\0'+a.to_bytes(3,'big')+b.to_bytes(3,'big') for a,b in gates)
def decode(obj):
 if 'rawNetlist' in obj:
  raw=bytes.fromhex(obj['rawNetlist'].removeprefix('0x'))
  if len(raw)%7 or any(raw[i] for i in range(0,len(raw),7)):raise ValueError('Invalid NAND encoding')
  gs=[(int.from_bytes(raw[i+1:i+4],'big'),int.from_bytes(raw[i+4:i+7],'big')) for i in range(0,len(raw),7)]
 else:gs=[tuple(x) for x in obj['gates']]
 if len(gs)<5:raise ValueError('Five final physical output gates are required')
 for j,(a,b) in enumerate(gs,11):
  if not(0<=a<j and 0<=b<j):raise ValueError(f'Forward/invalid reference at {j}')
 return gs

def verify(gs):
 decode({'gates':gs});dep=[0]*11
 for a,b in gs:dep.append(1+max(dep[a],dep[b]))
 table=[];expected=[];errors=[]
 for x in range(512):
  a=x&15;b=(x>>4)&15;c=x>>8
  v=[0,1]+[(x>>i)&1 for i in range(9)]
  for p,q in gs:v.append(1^(v[p]&v[q]))
  y=sum(t<<i for i,t in enumerate(v[-5:]));table.append(y);expected.append(a+b+c)
  if y!=a+b+c:errors.append({'a':a,'b':b,'cin':c,'expected':a+b+c,'actual':y})
 return {'valid':not errors,'gateCount':len(gs),'depth':max(dep),'outputDepths':dep[-5:],'cost':len(gs)*max(dep)**3,'testedInputs':512,'passedInputs':512-len(errors),'counterexamples':errors,'rawNetlistSha256':hashlib.sha256(encode(gs)).hexdigest(),'truthTableSha256':hashlib.sha256(bytes(table)).hexdigest(),'expectedTruthTableSha256':hashlib.sha256(bytes(expected)).hexdigest()}

def export(gs,path,origin):
 v=verify(gs)
 if not v['valid']:raise ValueError(v)
 obj={'taskId':33,'srcId':34,'taskName':'4-bit unsigned adder with carry-in','nIn':9,'nOut':5,'nState':0,'processorAddress':'0x1F5Cb4aeaE1807Bf60c3b9C0D8aDBCC14e91f12C','status':'VALID_BEATS_BEHEMOTH_SNAPSHOT' if v['cost']<25088 else 'VALID_NOT_IMPROVED','onChainSubmitted':False,'globallyOptimalProved':False,'baseline':{'snapshotBlock':123888327,'snapshotTimeUTC':'2026-09-25T04:53:48Z','circuitId':'2025','gateCount':49,'depth':8,'cost':25088},'origin':origin,'rawNetlist':'0x'+encode(gs).hex(),'gates':gs,'verification':v}
 Path(path).write_text(json.dumps(obj,indent=2)+'\n');return obj

if __name__=='__main__':
 ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('file',type=Path);a=ap.parse_args();v=verify(decode(json.loads(a.file.read_text())));print(json.dumps(v,indent=2));raise SystemExit(0 if v['valid'] else 1)
