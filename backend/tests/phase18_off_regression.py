"""Reuse unchanged regression assertions with explicit Phase18-only transports."""
import os,sys,subprocess,unittest,importlib
from pathlib import Path
pg=os.environ['PHASE18_POSTGRES_CONTAINER'];redis=os.environ['PHASE18_REDIS_CONTAINER'];base=os.environ['PHASE18_BASE_URL']
assert pg.startswith('phase18-') and redis.startswith('phase18-')
os.environ['TICKETING_BASE_URL']=base
for phase in ['PHASE15','PHASE16','PHASE17']:
 os.environ.update({phase+'_BASE_URL':base,phase+'_POSTGRES_CONTAINER':pg,phase+'_PG_CONTAINER':pg,phase+'_REDIS_CONTAINER':redis})
def sql(statement):
 r=subprocess.run(['docker','exec','-i',pg,'psql','-U','postgres','-qAt','-F','\t','-v','ON_ERROR_STOP=1'],input=statement,text=True,encoding='utf-8',capture_output=True)
 if r.returncode:raise AssertionError(r.stderr)
 return r.stdout.strip()
if __name__=='__main__':
 modules=sys.argv[1:] or ['phase15_reservation_test','phase15_checkout_test','phase15_read_api_test','phase15_observation_test','phase16_migration_test','phase16_read_model_test','phase16_api_test','phase17_venue_test','phase17_publishing_test','payment_integration_test']
 result=True
 for name in modules:
  if name=='phase16_api_test':
   # The original cross-session ownership assertion requires this second real session.
   # Create it solely in this disposable Phase18 database, preserving the assertion.
   sql("INSERT INTO sessions(id,event_id,venue_id,hall_name,start_time,gate_time,status) SELECT 'perf-session-phase16',event_id,venue_id,'Phase18 regression cross session',start_time,gate_time,status FROM sessions WHERE id='ses-concert-1001' ON CONFLICT(id) DO NOTHING; INSERT INTO session_seats(id,session_id,seat_id,venue_id,status,price) SELECT 'p18-cross-'||seat_id,'perf-session-phase16',seat_id,venue_id,'AVAILABLE',price FROM session_seats WHERE session_id='ses-concert-1001' ON CONFLICT(id) DO NOTHING;")
  module=importlib.import_module(name)
  if name=='payment_integration_test':module.psql=sql
  print('REGRESSION MODULE '+name,flush=True)
  run=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(module))
  result=run.wasSuccessful() and result
  if not run.wasSuccessful():break
 sys.exit(not result)
