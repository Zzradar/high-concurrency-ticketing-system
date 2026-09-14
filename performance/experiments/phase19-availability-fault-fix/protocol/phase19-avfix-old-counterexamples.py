import os,json,subprocess,sys
from pathlib import Path
out=Path(os.environ['TEMP'])/'phase19-avfix-regression';env=dict(os.environ,**json.loads((out/'phase18-env-private.json').read_text()))
with (out/'old-dependency-counterexamples.log').open('w',encoding='utf8') as f:
 p=subprocess.run([sys.executable,'backend/tests/phase19_admission_dependency_test.py'],env=env,stdout=f,stderr=subprocess.STDOUT)
print('counterexamples exit',p.returncode)
for i in range(1,4):
 label='old-16-policies-'+str(i)
 with (out/(label+'.log')).open('w',encoding='utf8') as f:p=subprocess.run([sys.executable,str(Path(os.environ['TEMP'])/'phase19-avfix-trace.py'),label],env=env,stdout=f,stderr=subprocess.STDOUT)
 print(label,'exit',p.returncode,flush=True)
