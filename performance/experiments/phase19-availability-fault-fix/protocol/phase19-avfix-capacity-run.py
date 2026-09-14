import os,sys,subprocess,json
from pathlib import Path
root=Path.cwd();private=Path(os.environ['TEMP'])/'phase19-avfix-capacity-runtime';out=Path(os.environ['TEMP'])/'phase19-avfix-capacity-points';out.mkdir(exist_ok=False)
full=Path(os.environ['TEMP'])/'phase19-avfix-full-regression/full-run.log'
assert 'FULL 166 GATES PASSED' in full.read_text(encoding='utf8')
subprocess.run(['docker','stop','phase18-phase19-avfix-full-api','phase18-phase19-avfix-full-no-secret-api','phase18-phase19-avfix-full-postgres','phase18-phase19-avfix-full-redis'],check=True)
points=[
 ('closed-2000-10m',['--mode','closed','--vus','2000','--warmup','30','--seconds','600']),
 ('open-precheck',['--mode','open','--read-rate','50','--transitions-rate','5','--warmup','0','--seconds','30']),
 ('open-l1',['--mode','open','--read-rate','100','--transitions-rate','10','--warmup','30','--seconds','60']),
 ('open-l2',['--mode','open','--read-rate','250','--transitions-rate','25','--warmup','30','--seconds','120']),
 ('open-l3',['--mode','open','--read-rate','500','--transitions-rate','50','--warmup','30','--seconds','120']),
 ('journeys-5001',['--mode','journeys','--vus','100','--warmup','0','--seconds','250','--journey-rate','20']),
 ('hotspot-1000',['--mode','hotspot','--vus','1000','--warmup','0','--seconds','30'])]
for name,args in points:
 print('START '+name,flush=True)
 with (out/(name+'.log')).open('w',encoding='utf8') as f:
  run=subprocess.run([sys.executable,'performance/experiments/phase19-global-polling-mixed-load/protocol/measure.py','--private',str(private),'--out',str(out/name),'--generator-memory-gib','4',*args],stdout=f,stderr=subprocess.STDOUT)
 print('END '+name+' exit='+str(run.returncode),flush=True)
 if run.returncode:sys.exit(run.returncode)
print('ALL CAPACITY POINTS PASSED',flush=True)
