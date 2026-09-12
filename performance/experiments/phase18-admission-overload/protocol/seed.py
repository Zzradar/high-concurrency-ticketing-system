"""Deterministic business fixture, seed 18. Timestamps in fingerprints exclude DB-generated audit times."""
import hashlib
def seed(sql):
 for n in (5000,10000):
  v=f'p18-v-{n}';e=f'p18-e-{n}';s=f'p18-s-{n}'
  sql(f"""BEGIN;
INSERT INTO venues(id,name,city) VALUES('{v}','Phase18 {n}','Test');
INSERT INTO venue_zones(id,venue_id,code,name,sort_order) SELECT '{v}-z-'||i,'{v}','Z'||i,'Zone '||i,i FROM generate_series(0,4) i;
INSERT INTO seats(id,venue_id,zone_id,row_no,seat_no,seat_label)
SELECT '{s}-seat-'||lpad(i::text,5,'0'),'{v}','{v}-z-'||((i-1)/{n//5}),lpad(((i-1)/100)::text,3,'0'),(i-1)%100+1,'P'||lpad(i::text,5,'0') FROM generate_series(1,{n}) i;
INSERT INTO events(id,primary_venue_id,name,description,status,category,cover_url,date_range,sales_starts_at,sales_ends_at,published_at,published_by)
VALUES('{e}','{v}','Phase18 {n}','Fixed seed 18','ON_SALE','Concert','/images/concert-cover.png','2030.01.03','2026-01-01Z','2030-01-02Z','2026-01-01Z','U-ADMIN-DEMO');
INSERT INTO sessions(id,event_id,venue_id,hall_name,start_time,gate_time,status) VALUES('{s}','{e}','{v}','Hall','2030-01-03T12:00:00Z','2030-01-03T11:00:00Z','ON_SALE');
INSERT INTO session_zone_prices(session_id,zone_id,venue_id,price) SELECT '{s}',id,'{v}',10000 FROM venue_zones WHERE venue_id='{v}';
INSERT INTO session_seats(id,session_id,seat_id,venue_id,status,price) SELECT '{s}-ss-'||lpad(i::text,5,'0'),'{s}','{s}-seat-'||lpad(i::text,5,'0'),'{v}','AVAILABLE',10000 FROM generate_series(1,{n}) i;
COMMIT;""")
 sql("INSERT INTO app_users(id,display_name,username,password_hash,status,role) SELECT 'p18-user-'||i,'Stage0 user '||i,'p18-user-'||i,password_hash,'ACTIVE','CUSTOMER' FROM app_users CROSS JOIN generate_series(0,7) i WHERE username='demo';")
 return fingerprints(sql)
def fingerprints(sql):
 rows=[]
 for n in (5000,10000):
  raw=sql(f"SELECT s.id,s.zone_id,s.row_no,s.seat_no,s.seat_label,i.id,i.price,i.status,i.formal_version FROM seats s JOIN session_seats i ON i.seat_id=s.id WHERE i.session_id='p18-s-{n}' ORDER BY s.id;")
  rows.append({'seatCount':n,'zoneCount':5,'inventorySha256':hashlib.sha256(raw.encode()).hexdigest()})
 return {'seed':18,'fixtures':rows}
