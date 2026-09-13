"""Freeze a fully qualified candidate before any formal baseline measurement."""
import argparse
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import subprocess
import re

ROOT=Path(__file__).resolve().parents[2]
EVIDENCE=ROOT/'performance/experiments/phase19-global-polling-mixed-load'
PROTOCOL=EVIDENCE/'protocol'
BASE='2c680e78d532eace9e7f28862e7efb6ef2bdf4fb'


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def qualification(result,identity,current,expected_vus,memory_gib):
    if not result.get('valid') or result.get('vus')!=expected_vus or result.get('initializedVUs')!=expected_vus:
        raise ValueError('Invalid actual-VU qualification')
    if result.get('droppedIterations')!=0 or result.get('interruptedOrUncompletedIterations')!=0:
        raise ValueError('Dropped or uncompleted qualification')
    if identity['limits']['generator']['memoryBytes']!=memory_gib*1024**3:
        raise ValueError('Qualification belongs to another memory identity')
    for name in ['workload.js','policy.mjs','stub.py','calibrate.py']:
        if identity['protocolSha256'].get(name)!=current[name]:raise ValueError('Executed qualification core drift: '+name)
    if identity['protocolSha256']!=current:
        raise ValueError('Executed qualification protocol drift outside core')


def qualification_directory(parent,memory_gib,vus,template=None):
    if template is not None:
        if not re.fullmatch(r'phase19-[a-z0-9-]*\{vus\}[a-z0-9-]*',template):
            raise ValueError('Qualification template must be a single Phase19 directory name')
        return parent/template.format(vus=vus)
    return parent/(f'phase19-calibration-4g-{vus}-r1' if memory_gib==4 else f'phase19-calibration-{vus}-r3')


def qualified_tiers(max_vus):
    if max_vus not in [1000,2000,3000]:raise ValueError('Unsupported qualified maximum')
    return [n for n in [100,250,500,1000,2000,3000] if n<=max_vus]


def main(args):
    frozen=EVIDENCE/'protocol-sha256.json'
    if frozen.exists():raise ValueError('Refuse replacing a frozen protocol')
    git=lambda *a:subprocess.check_output(['git','-C',str(ROOT),*a],text=True).strip()
    if git('diff',BASE,'--','backend/src','backend/config','backend/db/migrations','frontend/src','frontend/public'):
        raise ValueError('Production changed before baseline freeze')
    files={p.name:sha(p) for p in PROTOCOL.iterdir() if p.is_file()}
    points={}
    template=getattr(args,'qualification_template',None)
    max_vus=getattr(args,'max_vus',None)
    next_point=qualification_directory(args.private,args.memory_gib,2000,template)
    if max_vus is None:max_vus=2000 if args.memory_gib==4 and (next_point/'result.json').exists() else 1000
    tiers=qualified_tiers(max_vus)
    for vus in tiers:
        directory=qualification_directory(args.private,args.memory_gib,vus,template)
        result=json.loads((directory/'result.json').read_text())
        identity=json.loads((directory/'identity.json').read_text())
        qualification(result,identity,files,vus,args.memory_gib)
        points[str(vus)]={'resultSha256':sha(directory/'result.json'),'identitySha256':sha(directory/'identity.json'),'valid':True}
    artifact={'frozenUtc':datetime.now(timezone.utc).isoformat(),'baseCommit':BASE,'protocolParentCommit':git('rev-parse','HEAD'),
        'productionTrees':{path:git('rev-parse',BASE+':'+path) for path in ['backend/src','backend/config','backend/db/migrations','frontend/src','frontend/public']},
        'generatorMemoryGiB':args.memory_gib,'qualification':points,'files':files}
    frozen.write_bytes((json.dumps(artifact,indent=2)+'\n').encode())
    print('Frozen protocol SHA256 '+sha(frozen))


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--private',type=Path,required=True)
    parser.add_argument('--memory-gib',type=int,choices=[2,4],required=True)
    parser.add_argument('--qualification-template')
    parser.add_argument('--max-vus',type=int,choices=[1000,2000,3000])
    main(parser.parse_args())
