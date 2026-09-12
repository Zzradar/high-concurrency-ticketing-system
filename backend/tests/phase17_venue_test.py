import copy,unittest
from phase17_http_test import AuthenticatedClient,sql,setUpModule

def plan():return {'name':'测试场馆','city':'成都','zones':[{'code':'FLOOR','name':'内场','rows':[{'label':'A','seatCount':2},{'label':'B','seatCount':3}]},{'code':'STAND','name':'看台','rows':[{'label':'A','seatCount':2}]}]}
class VenueTest(unittest.TestCase):
    def setUp(self):self.admin=AuthenticatedClient('admin')
    def create(self,body=None):
        status,result,_=self.admin.request('/admin/venues',method='POST',body=body or plan());self.assertEqual(status,201,result);return result
    def test_create_detail_list_and_set_based_seats(self):
        v=self.create();self.assertEqual(v['totalSeats'],7);self.assertEqual([z['seatCount'] for z in v['zones']],[5,2]);self.assertFalse(v['frozen'])
        self.assertEqual(sql("SELECT count(*) FROM seats WHERE venue_id='"+v['id']+"' AND seat_label='A001';"),'2')
        self.assertEqual(self.admin.request('/admin/venues/'+v['id'])[1]['zones'],v['zones'])
        self.assertIn(v['id'],[x['id'] for x in self.admin.request('/admin/venues')[1]])
    def test_invalid_inputs_and_limits(self):
        cases=[]
        for field,value in [('name',' '),('city',''),('zones',[])]:
            p=plan();p[field]=value;cases.append(p)
        p=plan();p['zones'][1]['code']='floor';cases.append(p)
        p=plan();p['zones'][1]['name']='内场';cases.append(p)
        p=plan();p['zones'][0]['rows'][1]['label']='A';cases.append(p)
        for count in [0,-1,501,True,1.0]:
            p=plan();p['zones'][0]['rows'][0]['seatCount']=count;cases.append(p)
        p=plan();p['zones'][0]['rows']=[{'label':str(i),'seatCount':500} for i in range(41)];cases.append(p)
        for p in cases:
            with self.subTest(body=p):self.assertEqual(self.admin.request('/admin/venues',method='POST',body=p)[0],400)
    def test_replace_resets_draft_prices_and_frozen_rejects(self):
        v=self.create();vid=v['id'];zone=v['zones'][0]['id'];eid='e-'+vid;sid='s-'+vid
        sql(f"INSERT INTO events(id,primary_venue_id,name,description,status,category,cover_url,date_range,sales_starts_at,sales_ends_at) VALUES('{eid}','{vid}','E','','DRAFT','C','cover','',now(),now()+interval '1 day'); INSERT INTO sessions(id,event_id,venue_id,hall_name,start_time,gate_time,status) VALUES('{sid}','{eid}','{vid}','H',now()+interval '1 day',now(),'DRAFT'); INSERT INTO session_zone_prices(session_id,zone_id,venue_id,price) VALUES('{sid}','{zone}','{vid}',100);")
        body=plan();body['zones'][0]['rows'][0]['seatCount']=4
        status,updated,_=self.admin.request('/admin/venues/'+vid,method='PUT',body=body)
        self.assertEqual(status,200,updated);self.assertTrue(updated['pricingReset']);self.assertEqual(updated['totalSeats'],9)
        self.assertEqual(sql(f"SELECT count(*) FROM session_zone_prices WHERE session_id='{sid}';"),'0')
        sql(f"UPDATE events SET status='ON_SALE' WHERE id='{eid}'; UPDATE sessions SET status='ON_SALE' WHERE id='{sid}'; INSERT INTO session_seats(id,session_id,seat_id,venue_id,status,price) SELECT 'ss-'||id,'{sid}',id,venue_id,'AVAILABLE',100 FROM seats WHERE venue_id='{vid}';")
        self.assertTrue(self.admin.request('/admin/venues/'+vid)[1]['frozen'])
        status,error,_=self.admin.request('/admin/venues/'+vid,method='PUT',body=body);self.assertEqual((status,error['code']),(409,'VENUE_SEAT_PLAN_FROZEN'))
    def test_backend_permissions(self):
        c=AuthenticatedClient();self.assertEqual(c.request('/admin/venues')[1]['code'],'ADMIN_REQUIRED')
        self.assertEqual(self.admin.request('/admin/venues',method='POST',body=plan(),csrf=False)[1]['code'],'CSRF_INVALID')
if __name__=='__main__':unittest.main(verbosity=2)
