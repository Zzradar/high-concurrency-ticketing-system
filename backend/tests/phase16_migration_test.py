"""Real PostgreSQL gate; only the explicitly isolated Phase16 container is used."""
from pathlib import Path
import os
import subprocess
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
import re

ROOT = Path(__file__).resolve().parents[1]

class MigrationTest(unittest.TestCase):
    def sql(self, sql, ok=True):
        result = subprocess.run(
            ['docker', 'exec', '-i', os.environ.get('PHASE16_PG_CONTAINER', 'phase16-postgres'),
             'psql', '-U', 'postgres', '-d', 'postgres', '-v', 'ON_ERROR_STOP=1', '-qAt'],
            input=sql, text=True, encoding='utf-8', capture_output=True)
        if ok:
            self.assertEqual(result.returncode, 0, result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0)
        return result.stdout.strip()

    def setUp(self):
        self.schema = 'phase16_' + uuid.uuid4().hex
        self.prefix = 'SET search_path TO ' + self.schema + ';\n'
        self.sql('CREATE SCHEMA ' + self.schema + ';')
        self.addCleanup(lambda: self.sql('DROP SCHEMA ' + self.schema + ' CASCADE;'))
        self.sql(self.prefix + '\n'.join(p.read_text(encoding='utf-8') for p in sorted((ROOT/'db/migrations').glob('*.sql'))))
        self.sql(self.prefix + (ROOT/'db/seeds/001_demo_seed.sql').read_text(encoding='utf-8'))
        self.seat = 'ses-concert-1001-A01'

    def test_defaults_and_existing_schema(self):
        self.assertEqual(self.sql(self.prefix + 'SELECT count(*) FROM session_seats WHERE formal_version <> 0;'), '0')
        self.assertEqual(self.sql(self.prefix + 'SELECT count(*) FROM seat_availability_outbox;'), '0')
        for verifier in sorted((ROOT/'db/tests').glob('*.sql')):
            self.sql(self.prefix + verifier.read_text(encoding='utf-8'))

    def test_lifecycle_noop_and_exact_events(self):
        # Use a new reservation to preserve all original hold pointer constraints.
        self.sql(self.prefix + "INSERT INTO reservations(id,user_id,session_id,status,expires_at) VALUES('p16-r','U-SEED-HOLDER','ses-concert-1001','ACTIVE',now()+interval '1 hour');")
        self.sql(self.prefix + f"UPDATE session_seats SET status='AVAILABLE',current_reservation_id=NULL WHERE id='{self.seat}'; DELETE FROM seat_availability_outbox;")
        version = int(self.sql(self.prefix + f"SELECT formal_version FROM session_seats WHERE id='{self.seat}';"))
        for offset, status in enumerate(['HELD', 'SOLD', 'AVAILABLE'], 1):
            pointer = "'p16-r'" if status == 'HELD' else 'NULL'
            self.sql(self.prefix + f"UPDATE session_seats SET status='{status}',current_reservation_id={pointer} WHERE id='{self.seat}';")
            self.assertEqual(self.sql(self.prefix + f"SELECT status||'|'||formal_version FROM session_seats WHERE id='{self.seat}';"), f'{status}|{version+offset}')
            self.assertEqual(self.sql(self.prefix + f"SELECT formal_status||'|'||formal_version FROM seat_availability_outbox WHERE session_seat_id='{self.seat}' ORDER BY id DESC LIMIT 1;"), f'{status}|{version+offset}')
        self.sql(self.prefix + f"UPDATE session_seats SET status=status WHERE id='{self.seat}';")
        self.assertEqual(self.sql(self.prefix + 'SELECT count(*) FROM seat_availability_outbox;'), '3')

    def test_multi_seat_and_rollback(self):
        before = self.sql(self.prefix + "SELECT string_agg(id||'|'||status||'|'||formal_version, ',' ORDER BY id) FROM session_seats;")
        self.sql(self.prefix + "BEGIN; UPDATE session_seats SET status='SOLD' WHERE status='AVAILABLE'; ROLLBACK;")
        self.assertEqual(self.sql(self.prefix + "SELECT string_agg(id||'|'||status||'|'||formal_version, ',' ORDER BY id) FROM session_seats;"), before)
        self.assertEqual(self.sql(self.prefix + 'SELECT count(*) FROM seat_availability_outbox;'), '0')
        count = self.sql(self.prefix + "SELECT count(*) FROM session_seats WHERE status='AVAILABLE';")
        self.sql(self.prefix + "BEGIN; UPDATE session_seats SET status='SOLD' WHERE status='AVAILABLE'; COMMIT;")
        self.assertEqual(self.sql(self.prefix + 'SELECT count(*) FROM seat_availability_outbox;'), count)
        self.assertEqual(self.sql(self.prefix + 'SELECT count(*) FROM session_seats WHERE formal_version=1;'), count)

    def test_constraints_and_outbox_failure_roll_back_inventory(self):
        self.sql(self.prefix + f"UPDATE session_seats SET formal_version=-1 WHERE id='{self.seat}';", False)
        self.sql(self.prefix + f"UPDATE session_seats SET status='AVAILABLE',current_reservation_id=NULL WHERE id='{self.seat}';")
        version = int(self.sql(self.prefix + f"SELECT formal_version FROM session_seats WHERE id='{self.seat}';"))
        insert = f"INSERT INTO seat_availability_outbox(session_id,session_seat_id,formal_status,formal_version) VALUES('ses-concert-1001','{self.seat}','SOLD',{version+1});"
        self.sql(self.prefix + insert)
        self.sql(self.prefix + insert, False)
        self.sql(self.prefix + f"UPDATE session_seats SET status='SOLD' WHERE id='{self.seat}';", False)
        self.assertEqual(self.sql(self.prefix + f"SELECT status||'|'||formal_version FROM session_seats WHERE id='{self.seat}';"), f'AVAILABLE|{version}')
        self.sql(self.prefix + "UPDATE seat_availability_outbox SET formal_status='INVALID';", False)
        self.sql(self.prefix + "UPDATE seat_availability_outbox SET formal_version=-1;", False)
        self.sql(self.prefix + "UPDATE seat_availability_outbox SET lease_token='orphan';", False)

    def test_claim_skip_locked_and_stale_lease_ack(self):
        self.sql(self.prefix + "INSERT INTO seat_availability_outbox(session_id,session_seat_id,formal_status,formal_version) SELECT 'lease-session','lease-seat-'||i,'AVAILABLE',0 FROM generate_series(1,4) i;")
        worker=(ROOT/'src/workers/SeatAvailabilityProjectionWorker.cpp').read_text(encoding='utf-8')
        claim=re.search(r'R"SQL\((.*?)\)SQL"',worker,re.S).group(1)
        self.assertIn('LIMIT $1::integer',claim)
        def take(token):
            statement=claim.replace('$1::integer','2').replace('$2',"'"+token+"'").replace('$3::double precision','5')
            self.sql(self.prefix+'BEGIN;'+statement+";SELECT pg_sleep(0.2);COMMIT;")
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(take,['worker-a','worker-b']))
        self.assertEqual(self.sql(self.prefix+"SELECT lease_token||'|'||count(*) FROM seat_availability_outbox GROUP BY lease_token ORDER BY lease_token;"),'worker-a|2\nworker-b|2')
        self.sql(self.prefix+"UPDATE seat_availability_outbox SET lease_until=now()-interval '1 second';")
        take('replacement')
        before=self.sql(self.prefix+"SELECT count(*) FROM seat_availability_outbox WHERE lease_token='replacement';")
        self.sql(self.prefix+"DELETE FROM seat_availability_outbox WHERE id IN (SELECT id FROM seat_availability_outbox WHERE lease_token='replacement') AND lease_token='worker-a';")
        self.assertEqual(self.sql(self.prefix+"SELECT count(*) FROM seat_availability_outbox WHERE lease_token='replacement';"),before)

if __name__ == '__main__':
    unittest.main(verbosity=2)
