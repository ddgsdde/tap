#!/usr/bin/env python3
"""Exact NAND2 depth lower bounds for the full hexadecimal decoder and 4-bit cube.
Inputs/constants have depth zero. NAND inputs may coincide. Sharing and fanout
are unrestricted. No external modules or solver are needed.

Induction: S[d] is exactly the set of Boolean functions realizable at depth <=d.
Each non-input root is NAND of two functions in S[d-1]; conversely every
such pair can be implemented by placing its networks in parallel and adding
one NAND. Thus an output missing from S[4] cannot be implemented at depth <=4,
regardless of gate count. The supplied 5-layer witnesses establish attainability.
This proves minimum depth, NOT minimum area or globally minimum area*depth^3.
"""
from pathlib import Path
import hashlib,json
SEGMENTS=[0x3f,0x06,0x5b,0x4f,0x66,0x6d,0x7d,0x07,0x7f,0x6f,0x77,0x7c,0x39,0x5e,0x79,0x71]

WITNESSES={57: {'nOut': 7, 'gateCount': 37, 'rawSha256': 'f3b63e830ad96cb2f725da259a424d6e2f77d2ad7de066f2c3bf179373f262aa', 'rawNetlist': '00000002000002000000040000040000000400000500000006000007000000030000030000000a000008000000020000030000000c00000800000008000009000000020000040000000f00000d000000050000050000000400000c000000110000120000001300000b00000004000003000000050000150000000a00000f00000016000017000000180000100000000500000f0000001100000f0000001200001b0000001700001c0000000c0000030000000900001a0000000c00001f0000000a00000b000000130000210000001e00001f00000018000020000000130000190000000e0000190000001d00002300000009000014000000220000230000002200001d'}, 90: {'nOut': 12, 'gateCount': 41, 'rawSha256': '921c6fcfac844f4199b93d92d954ba67626f3529d1ccaec0516d0710d993eab5', 'rawNetlist': '0000000400000500000003000005000000030000040000000200000500000002000004000000020000030000000b0000040000000a00000b000000090000050000000a000003000000080000090000000700000a000000070000090000000a0000020000000600000700000010000011000000120000040000000c0000110000000b0000120000000b00001000000009000014000000080000110000000900000f0000000600000d0000001b00001c000000180000140000001600000400000015000012000000150000110000000a0000130000000b0000010000000a0000010000001e0000220000001900001d00000007000022000000200000210000001900001a000000170000010000000e0000210000001f00000100000016000001'}}

def verify_witness(tid, table):
    """Independently check the embedded chain witness on all sixteen inputs."""
    witness=WITNESSES[tid]
    raw=bytes.fromhex(witness["rawNetlist"])
    assert hashlib.sha256(raw).hexdigest()==witness["rawSha256"]
    assert len(raw)==7*witness["gateCount"]
    gates=[];depths=[0]*6
    for pos in range(0,len(raw),7):
        a=int.from_bytes(raw[pos+1:pos+4],"big")
        b=int.from_bytes(raw[pos+4:pos+7],"big")
        assert raw[pos]==0 and max(a,b)<6+len(gates)
        gates.append((a,b));depths.append(1+max(depths[a],depths[b]))
    for x in range(16):
        values=[0,1]+[(x>>i)&1 for i in range(4)]
        for a,b in gates:values.append(1^(values[a]&values[b]))
        actual=sum(bit<<i for i,bit in enumerate(values[-witness["nOut"]:]))
        assert actual==table[x],(tid,x,actual,table[x])
    assert max(depths)==5
    return {"gateCount":len(gates),"depth":max(depths),"allInputRowsChecked":16,
            "rawSha256":witness["rawSha256"],"source":"Frozen TapeOut chain witness; not a new cost improvement"}

def output_functions(table,nout):
    return [sum(((value>>bit)&1)<<row for row,value in enumerate(table)) for bit in range(nout)]

def prove(destination=None):
    primary={0,65535,0xaaaa,0xcccc,0xf0f0,0xff00}
    levels=[primary];minimum={f:0 for f in primary}
    for depth in range(1,5):
        previous=sorted(levels[-1]);current=set(previous)
        for i,a in enumerate(previous):
            for b in previous[:i+1]:current.add(65535^(a&b))
        for f in current-levels[-1]:minimum[f]=depth
        levels.append(current)
    counts=[len(s) for s in levels]
    assert counts==[6,16,79,1001,10664]
    data=b''.join(f.to_bytes(2,'little') for f in sorted(levels[4]))
    report={'model':'NAND2, constants 0/1 and primary inputs at depth zero; unrestricted sharing/fanout',
            'functionsAtDepthAtMost':dict(enumerate(counts)),
            'depth4SetEncoding':'sorted unsigned 16-bit little-endian truth tables; row x is bit x',
            'depth4SetSha256':hashlib.sha256(data).hexdigest(),'tasks':{}}
    for tid,table,nout in [(57,SEGMENTS,7),(90,[x**3 for x in range(16)],12)]:
        witness=verify_witness(tid,table)
        targets=output_functions(table,nout)
        missing=[i for i,f in enumerate(targets) if f not in levels[4]]
        assert missing
        report['tasks'][str(tid)]={'truthTablesHex':[f'{f:04x}' for f in targets],
            'outputBitsNotRealizableAtDepth4':missing,'provedMinimumDepthLowerBound':5,
            'knownVerifiedWitnessDepth':5,'minimumDepth':5,
            'minimumBooleanFunctionDepthByOutput':[minimum.get(f,5) for f in targets],
            'globalCostOptimalityProved':False,'verifiedEmbeddedWitness':witness}
    if destination:
        destination=Path(destination);destination.mkdir(parents=True,exist_ok=True)
        (destination/'depth4_functions.bin').write_bytes(data)
        (destination/'depth_proof.json').write_text(json.dumps(report,indent=2)+'\n')
    return report

if __name__=='__main__':
    print(json.dumps(prove(Path(__file__).parent),indent=2))
