from pathlib import Path
import os,sys,subprocess,json
out=Path(os.environ['TEMP'])/'phase19-avfix-capacity-points';private=Path(os.environ['TEMP'])/'phase19-avfix-capacity-runtime'
assert json.loads((Path(os.environ['TEMP'])/'phase19-avfix-regression/l3-r1-after-abort-convergence.json').read_text())['passed']
points=[('open-l3-r2',['--mode','open','--read-rate','500','--transitions-rate','50','--warmup','30','--seconds','120']),('journeys-5001',['--mode','journeys','--vus','100','--warmup','0','--seconds','250','--journey-rate','20']),('hotspot-1000',['--mode','hotspot','--vus','1000','--warmup','0','--seconds','30'])]
for name,args in points:
 print('START '+name,flush=True)
 with (out/(name+'.log')).open('w',encoding='utf8') as f:r=subprocess.run([sys.executable,'performance/experiments/phase19-global-polling-mixed-load/protocol/measure.py','--private',str(private),'--out',str(out/name),'--generator-memory-gib','4',*args],stdout=f,stderr=subprocess.STDOUT)
 print('END '+name+' exit='+str(r.returncode),flush=True)
 if r.returncode:sys.exit(r.returncode)
print('REMAINING CAPACITY POINTS PASSED',flush=True)
