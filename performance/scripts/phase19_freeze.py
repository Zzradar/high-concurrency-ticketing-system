"""Freeze a fully qualified candidate before any formal baseline measurement."""
import argparse
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import subprocess

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


def main(args):
    frozen=EVIDENCE/'protocol-sha256.json'
    if frozen.exists():raise ValueError('Refuse replacing a frozen protocol')
    git=lambda *a:subprocess.check_output(['git','-C',str(ROOT),*a],text=True).strip()
    if git('diff',BASE,'--','backend/src','backend/config','backend/db/migrations','frontend/src','frontend/public'):
        raise ValueError('Production changed before baseline freeze')
    files={p.name:sha(p) for p in PROTOCOL.iterdir() if p.is_file()}
    points={}
    tiers=[100,250,500,1000]
    if args.memory_gib==4 and (args.private/'phase19-calibration-4g-2000-r1/result.json').exists():tiers.append(2000)
    for vus in tiers:
        directory=args.private/f'phase19-calibration-4g-{vus}-r1' if args.memory_gib==4 else args.private/f'phase19-calibration-{vus}-r3'
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
    main(parser.parse_args())
