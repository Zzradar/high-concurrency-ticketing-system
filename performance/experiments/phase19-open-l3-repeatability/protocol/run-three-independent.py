import sys,os,json,subprocess,hashlib,argparse
from pathlib import Path
ROOT=Path.cwd(); P=ROOT/'performance/experiments/phase19-global-polling-mixed-load/protocol';sys.path.insert(0,str(P))
import harness
base=Path(os.environ['TEMP'])/'phase19-l3-repeatability';base.mkdir(exist_ok=False)
original=harness.run
for round_no in range(1,4):
 prefix=f'phase19-l3-independent-r{round_no}'; private=base/f'r{round_no}-runtime'; points=base/f'r{round_no}-points';points.mkdir()
 def transport(*args,**kwargs):
  if args[:3]==('docker','network','create'):
   net=0 if args[-1].endswith('-data') else 1
   args=(*args[:3],'--subnet',f'10.253.{30+round_no*2+net}.0/24',*args[3:])
  return original(*args,**kwargs)
 harness.run=transport
 print(f'ROUND {round_no} FRESH SETUP',flush=True)
 harness.setup(argparse.Namespace(private=private,prefix=prefix,binary=Path(os.environ['TEMP'])/'phase19-avfix-binary/ticketing_backend',api_port=18500+round_no*2,frontend_port=18501+round_no*2))
 stack=harness.Stack(private)
 harness.save(points/'initial-observation.json',stack.observation());harness.save(points/'initial-inventory.json',stack.inventory_counters())
 specs=[('precheck',50,5,0,30),('l1',100,10,30,60),('l2',250,25,30,120),('l3',500,50,30,120)]
 results=[]
 try:
  for name,read,write,warm,seconds in specs:
   print(f'ROUND {round_no} START {name}',flush=True)
   harness.save(points/(name+'-boundary-observation.json'),stack.observation())
   with (points/(name+'.log')).open('w',encoding='utf8') as log:
    result=subprocess.run([sys.executable,str(P/'measure.py'),'--private',str(private),'--out',str(points/name),'--generator-memory-gib','4','--mode','open','--read-rate',str(read),'--transitions-rate',str(write),'--warmup',str(warm),'--seconds',str(seconds)],stdout=log,stderr=subprocess.STDOUT)
   results.append({'name':name,'exit':result.returncode});harness.save(points/'sequence-results.json',results)
   print(f'ROUND {round_no} END {name} EXIT {result.returncode}',flush=True)
   if result.returncode and name!='l3': raise RuntimeError('Lower-tier failure; stop qualification')
 finally:
  original('docker','stop',*[prefix+'-'+role for role in ['api','frontend','postgres','redis']])
 print(f'ROUND {round_no} COMPLETE',flush=True)
print('THREE INDEPENDENT SEQUENCES COMPLETE',flush=True)