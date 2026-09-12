import unittest
from datetime import datetime
from phase15_test_support import sql,anonymous_request,EVENT,SESSION
class SalesReadApiTest(unittest.TestCase):
    def setUp(self):
        self.old=sql("SELECT sales_starts_at||'|'||sales_ends_at FROM events WHERE id='"+EVENT+"';").split('|')
        self.addCleanup(lambda:sql("UPDATE events SET sales_starts_at='"+self.old[0]+"',sales_ends_at='"+self.old[1]+"' WHERE id='"+EVENT+"';"))
    def get(self,path):
        status,body,_=anonymous_request(path);self.assertEqual(status,200,body)
        w=body['salesWindow'];self.assertEqual(set(w),{'startsAt','endsAt','state','evaluatedAt'})
        for field in ['startsAt','endsAt','evaluatedAt']:
            self.assertTrue(w[field].endswith('Z'));datetime.fromisoformat(w[field].replace('Z','+00:00'))
        return body
    def test_time_states_and_static_independence(self):
        for start,end,state in [(100,200,'NOT_STARTED'),(-100,100,'OPEN'),(-200,-100,'ENDED')]:
            sql("UPDATE events SET sales_starts_at=clock_timestamp()+make_interval(secs=>"+str(start)+"),sales_ends_at=clock_timestamp()+make_interval(secs=>"+str(end)+") WHERE id='"+EVENT+"';")
            for path in ['/events/'+EVENT,'/sessions/'+SESSION]:
                with self.subTest(path=path,state=state):
                    body=self.get(path);self.assertEqual(body['salesWindow']['state'],state);self.assertEqual(body['status'],'ON_SALE')
    def test_effective_end_clamped_to_session_and_last_session(self):
        sql("UPDATE events SET sales_starts_at='2026-01-01Z',sales_ends_at='2027-01-01Z' WHERE id='"+EVENT+"';")
        event=self.get('/events/'+EVENT);session=self.get('/sessions/'+SESSION)
        expected=sql("SELECT to_char(MAX(start_time) AT TIME ZONE 'UTC','YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"') FROM sessions WHERE event_id='"+EVENT+"';")
        self.assertEqual(event['salesWindow']['endsAt'],expected)
        expected=sql("SELECT to_char(start_time AT TIME ZONE 'UTC','YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"') FROM sessions WHERE id='"+SESSION+"';")
        self.assertEqual(session['salesWindow']['endsAt'],expected)
if __name__=='__main__':unittest.main(verbosity=2)
