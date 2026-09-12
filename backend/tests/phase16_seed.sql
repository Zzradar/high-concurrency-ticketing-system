-- Dedicated Phase16 performance fixture: 5000 seats, five ordered Zones.
BEGIN;
INSERT INTO venues(id,name,city) VALUES('perf-venue-phase16','Phase16 verification venue','Test');
INSERT INTO sessions(id,event_id,venue_id,hall_name,start_time,gate_time,status)
SELECT 'perf-session-phase16',event_id,'perf-venue-phase16','Phase16 hall',start_time,gate_time,'ON_SALE'
FROM sessions WHERE id='ses-concert-1001';
INSERT INTO venue_zones(id,venue_id,code,name,sort_order)
SELECT 'VZ-P16-'||i,'perf-venue-phase16','ZONE_'||i,'Zone '||i,i FROM generate_series(0,4) i;
INSERT INTO seats(id,venue_id,row_no,seat_no,seat_label,zone_id)
SELECT 'perf-seat-phase16-'||lpad(i::text,5,'0'),'perf-venue-phase16',lpad(((i-1)/100)::text,3,'0'),
       (i-1)%100+1,'P'||lpad(i::text,5,'0'),'VZ-P16-'||((i-1)/1000)
FROM generate_series(1,5000) i;
INSERT INTO session_seats(id,session_id,seat_id,venue_id,status,price)
SELECT 'perf-ss-phase16-'||lpad(i::text,5,'0'),'perf-session-phase16',
       'perf-seat-phase16-'||lpad(i::text,5,'0'),'perf-venue-phase16','AVAILABLE',10000
FROM generate_series(1,5000) i;
COMMIT;
