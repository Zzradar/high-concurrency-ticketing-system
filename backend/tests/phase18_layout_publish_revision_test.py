"""Actual ADMIN bulk publication must write one revision per Session, not per Seat."""
import json
import unittest
import uuid
import phase18_admission_http_test as fixture
from auth_test_support import AuthenticatedClient

class PublishRevision(unittest.TestCase):
    def test_5000_and_10000_seats_two_sessions(self):
        admin=AuthenticatedClient('admin');admin.login()
        fixture.sql("CREATE TABLE p18_publish_revision_writes(session_id text);CREATE FUNCTION p18_capture_publish_revision() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN INSERT INTO p18_publish_revision_writes VALUES(NEW.session_id);RETURN NEW;END $$;CREATE TRIGGER p18_capture_publish_revision AFTER UPDATE ON session_layout_revisions FOR EACH ROW EXECUTE FUNCTION p18_capture_publish_revision()")
        self.addCleanup(lambda:fixture.sql('DROP TRIGGER p18_capture_publish_revision ON session_layout_revisions;DROP FUNCTION p18_capture_publish_revision();DROP TABLE p18_publish_revision_writes;'))
        def post(path,body,expected=201):
            status,result,_=admin.request(path,method='POST',body=body,timeout=30)
            self.assertEqual(status,expected,result)
            return result
        for count in [5000,10000]:
            with self.subTest(seats=count):
                venue=post('/admin/venues',{'name':'Revision bulk '+uuid.uuid4().hex,'city':'Shanghai','zones':[{'code':'A','name':'A','rows':[{'label':'R'+str(i),'seatCount':100} for i in range(count//100)]}]})
                event=post('/admin/events',{'name':'Revision publication','description':'','category':'Test','coverUrl':'/images/concert-cover.png','venueId':venue['id'],'salesStartsAt':fixture.instant(-1),'salesEndsAt':fixture.instant(3)})['id']
                sessions=[]
                for i in range(2):
                    sid=post('/admin/events/'+event+'/sessions',{'hallName':'Hall '+str(i),'startTime':fixture.instant(2),'gateTime':fixture.instant(1)})['savedSessionId']
                    sessions.append(sid)
                    status,result,_=admin.request('/admin/events/'+event+'/sessions/'+sid+'/prices',method='PUT',body={'prices':[{'zoneId':venue['zones'][0]['id'],'price':100}]})
                    self.assertEqual(status,200,result)
                fixture.sql('DELETE FROM p18_publish_revision_writes')
                result=post('/admin/events/'+event+'/publish',None,200)
                self.assertEqual(result['inventory']['sessionSeatCount'],2*count)
                self.assertEqual(fixture.sql('SELECT count(*) FROM p18_publish_revision_writes'),'2')
                for sid in sessions:
                    self.assertEqual(fixture.sql("SELECT count(*) FROM p18_publish_revision_writes WHERE session_id='"+sid+"'"),'1')
                    self.assertEqual(fixture.sql("SELECT revision FROM session_layout_revisions WHERE session_id='"+sid+"'"),'2')
                    status,layout,headers=fixture.anonymous_request('/sessions/'+sid+'/seat-layout',timeout=30)
                    self.assertEqual(status,200);self.assertEqual(len(layout['seats']),count)
                print(json.dumps({'seatsPerSession':count,'sessions':2,'inventoryRows':2*count,'revisionRowUpdates':2}),flush=True)

if __name__=='__main__':unittest.main(verbosity=2)
