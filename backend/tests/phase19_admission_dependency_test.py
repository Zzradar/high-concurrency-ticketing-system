"""Deterministic Redis dependency failures must not invalidate unrelated OFF policy.

Runs only on the explicitly owned Phase18/19 fixture. Redis ACL command denial
holds each failure until cleanup; no timing delay is used to create the race.
"""
import os
import subprocess
import unittest

import phase18_admission_http_test as fixture
from auth_test_support import anonymous_request
from phase18_fixture_topology import topology


class AdmissionDependencyIsolation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        count = int(fixture.sql("SELECT count(*) FROM event_admission_policies WHERE mode<>'OFF'"))
        if count < 16:
            for _ in range(16 - count):
                case = fixture.AdmissionHTTP()
                case.setUp()
                case.policy('ENFORCED')

    def check_failure(self, command):
        self.assertTrue(fixture.REDIS.startswith('phase18-phase19-'))
        api = topology()['api']
        target = 'p18-s-5000'
        self.assertEqual(fixture.sql(
            "SELECT coalesce(p.mode,'OFF') FROM sessions s LEFT JOIN "
            "event_admission_policies p ON p.event_id=s.event_id "
            "WHERE s.id='p18-s-5000'"), 'OFF')
        self.assertGreaterEqual(int(fixture.sql(
            "SELECT count(*) FROM event_admission_policies WHERE mode<>'OFF'")), 16)

        def restart(faulted=False):
            subprocess.run(['docker', 'restart', api], capture_output=True, check=True)
            def healthy():
                try:
                    status, body, _ = anonymous_request('/health')
                    return status == 200 or (faulted and status == 503 and body.get('code') == 'ADMISSION_NOT_READY')
                except OSError:
                    return False
            fixture.until(healthy, seconds=25)

        def restore():
            fixture.redis('ACL', 'SETUSER', 'default', '+' + command)
            restart()

        self.addCleanup(restore)
        fixture.redis('ACL', 'LOG', 'RESET')
        fixture.redis('ACL', 'SETUSER', 'default', '-' + command)
        restart(faulted=True)
        # Observe the actual Redis denial, not merely the API's health endpoint.
        denied = fixture.until(lambda: next((entry for entry in fixture.redis('ACL', 'LOG', 128)
            if (entry if isinstance(entry, dict) else dict(zip(entry[::2], entry[1::2]))).get('object', '').lower() == command), None), seconds=15)
        self.assertIsNotNone(denied)
        status, body, _ = anonymous_request('/sessions/' + target + '/seat-availability?zone=Zone%200')
        self.assertEqual(status, 200, body)
        # ZRANGEBYSCORE is also used by availability: its denial must yield
        # an explicitly degraded PostgreSQL snapshot, still HTTP 200.
        self.assertEqual(body['degraded'], command == 'zrangebyscore')
        self.assertEqual(body['mode'], 'snapshot')
        protected = fixture.sql("SELECT s.id FROM sessions s JOIN event_admission_policies p "
            "ON p.event_id=s.event_id WHERE p.mode IN ('ENFORCED','PAUSED') ORDER BY s.id LIMIT 1")
        self.assertTrue(protected)
        status, body, _ = anonymous_request('/sessions/' + protected + '/seats')
        self.assertEqual(status, 401, body)
        self.assertEqual(body['code'], 'UNAUTHENTICATED')
        print('Redis denied ' + command + ': unrelated OFF=200; protected session=401', flush=True)

    def test_schedule_publication_failure_isolated(self):
        self.check_failure('zadd')

    def test_scheduler_failure_isolated(self):
        self.check_failure('zrangebyscore')


if __name__ == '__main__':
    unittest.main(verbosity=2)
