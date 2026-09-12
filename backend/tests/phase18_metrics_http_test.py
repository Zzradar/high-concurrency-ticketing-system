"""High-cardinality identities must not create Phase18 metric label identities."""
import json,os,re,unittest,urllib.request,uuid
import phase18_admission_http_test as f
from auth_test_support import AuthenticatedClient,test_user_values,username_for_user
class MetricsHTTP(unittest.TestCase):
 def test_many_events_and_users_keep_fixed_label_series(self):
  ids=['p18-metric-'+uuid.uuid4().hex for _ in range(16)]
  f.sql('INSERT INTO app_users(id,display_name,username,password_hash,status) VALUES '+test_user_values(ids))
  clients=[AuthenticatedClient(username_for_user(i)) for i in ids]
  for c in clients:c.login()
  events=[];sizes=[]
  for wave in range(8):
   case=f.AdmissionHTTP();case.setUp();case.policy('OBSERVE');events.append(case.e)
   for c in clients:self.assertEqual(c.request(case.path,method='POST')[0],200)
   with urllib.request.urlopen(os.environ['PHASE18_BASE_URL']+'/metrics') as response:text=response.read().decode()
   series=[line.split(' ')[0] for line in text.splitlines() if line.startswith(('ticketing_admission_','ticketing_rate_limit_','ticketing_traffic_','ticketing_overload_'))]
   for identity in ids+events:self.assertNotIn(identity,'\n'.join(series))
   for line in series:
    labels=re.findall(r'(\w+)="([^"\n]*)"',line)
    self.assertTrue({k for k,v in labels}<={'mode','outcome','request_class','scope','resource'})
   sizes.append(len(series))
  # Repeated equivalent identities exercise identical finite paths, not one series per ID.
  self.assertEqual(sizes[2:], [sizes[2]]*6,sizes)
  self.assertLess(sizes[-1],150)
  print('16 authenticated users x 8 events = 128 joins; bounded Phase18 series counts '+json.dumps(sizes))
if __name__=='__main__':unittest.main(verbosity=2)
