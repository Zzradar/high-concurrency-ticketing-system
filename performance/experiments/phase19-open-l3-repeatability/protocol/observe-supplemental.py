import os,json,subprocess,time,datetime
from pathlib import Path
base=Path(os.environ['TEMP'])/'phase19-l3-repeatability';dest=base/'supplemental';dest.mkdir(exist_ok=False)
def run(args):
 p=subprocess.run(args,capture_output=True,text=True,encoding='utf8',timeout=5)
 if p.returncode:raise RuntimeError(p.stderr[-200:])
 return p.stdout
for n in range(1,4):
 prefix=f'phase19-l3-independent-r{n}';point=base/f'r{n}-points/l3';rows=[]
 while not (point/'identity.json').exists():
  if 'THREE INDEPENDENT' in (base.parent/'phase19-l3-repeatability-run.log').read_text(encoding='utf8'):break
  time.sleep(1)
 while not (point/'result.json').exists():
  row={'utc':datetime.datetime.now(datetime.timezone.utc).isoformat()}
  try:
   for role in ['api','postgres','redis']:
    raw=run(['docker','exec',prefix+'-'+role,'cat','/sys/fs/cgroup/cpu.stat'])
    row[role+'CpuStat']={k:int(v) for k,v in (line.split() for line in raw.splitlines())}
   logs=json.loads(run(['docker','exec',prefix+'-redis','redis-cli','--json','SLOWLOG','GET','128']))
   row['redisSlowlog']=[{'id':x[0],'unixSeconds':x[1],'durationMicroseconds':x[2],'command':x[3][0]} for x in logs]
  except Exception as e:row['error']=str(e)
  rows.append(row);(dest/f'r{n}-l3.json').write_text(json.dumps(rows,indent=2),encoding='utf8')
  time.sleep(10)
print('SUPPLEMENTAL FINISHED',flush=True)