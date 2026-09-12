import unittest
import json
from stats import summary,phase_at,redis_cli_json
class StatisticsTest(unittest.TestCase):
 def test_redis_info_is_raw_while_other_commands_are_json(self):
  raw='# Commandstats\r\ncmdstat_get:calls=7,usec=11\r\n'
  self.assertEqual(json.loads(redis_cli_json('INFO',raw)),raw)
  self.assertEqual(json.loads(redis_cli_json('HGET','"1"')),'1')
  self.assertEqual(json.loads(redis_cli_json('LRANGE','["Zone 0"]')),['Zone 0'])
 def test_nearest_rank_and_failures_included(self):
  s=[{'ms':i,'status':200 if i<20 else 503} for i in range(1,21)]
  self.assertEqual(summary(s),{'count':20,'errorRate':.05,'p50Ms':10,'p95Ms':19,'p99Ms':20})
 def test_empty_is_not_success_or_zero_latency(self):
  self.assertEqual(summary([]),{'count':0,'errorRate':None,'p50Ms':None,'p95Ms':None,'p99Ms':None})
 def test_boundary_uses_start_time(self):
  self.assertEqual([phase_at(t,10,20) for t in (9,10,19,20)],['visible','hidden','hidden','restored'])
if __name__=='__main__':unittest.main()
