import os,json,subprocess,sys
from pathlib import Path
out=Path(os.environ['TEMP'])/'phase19-avfix-regression';env=dict(os.environ,**json.loads((out/'phase18-env-private.json').read_text()))
for module in ['phase19_admission_dependency_test','phase18_traffic_http_test']:
 with (out/('fixed-r2-'+module+'.log')).open('w',encoding='utf8') as f:p=subprocess.run([sys.executable,'backend/tests/'+module+'.py'],env=env,stdout=f,stderr=subprocess.STDOUT)
 print(module,'exit',p.returncode,flush=True)
 if p.returncode:sys.exit(1)
for i in range(1,4):
 label='fixed-full-sequence-'+str(i)
 with (out/(label+'.log')).open('w',encoding='utf8') as f:p=subprocess.run([sys.executable,str(Path(os.environ['TEMP'])/'phase19-avfix-trace.py'),label],env=env,stdout=f,stderr=subprocess.STDOUT)
 print(label,'exit',p.returncode,flush=True)
 if p.returncode:sys.exit(1)
