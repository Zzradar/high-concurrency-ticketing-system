"""Offline boundaries; behavioral coverage lives in the external PG/HTTP gates."""
from pathlib import Path
import unittest
ROOT=Path(__file__).resolve().parents[1]
class Phase17SourceTest(unittest.TestCase):
    def test_active_validation_returns_role_in_same_query(self):
        source=(ROOT/'src/repositories/UserSessionRepository.cpp').read_text()
        active=source.split('void UserSessionRepository::isActive(')[1].split('void UserSessionRepository::touch(')[0]
        self.assertEqual(active.count('execSqlAsync('),1)
        self.assertIn('SELECT app_user.role',active)
        service=(ROOT/'src/services/AuthSessionService.cpp').read_text()
        self.assertIn('cached->role = std::move(*role)',service)
    def test_filter_only_uses_verified_context(self):
        source=(ROOT/'src/filters/AdminFilter.cpp').read_text()
        self.assertIn('authContext(request)',source)
        self.assertIn('context->role != "ADMIN"',source)
        self.assertNotIn('getDbClient',source)
        self.assertNotIn('validCsrf',source)
    def test_zone_runtime_has_one_source_and_explicit_order(self):
        for name in ('src/repositories/SeatRepository.cpp','src/services/SeatAvailabilityReadModel.cpp'):
            source=(ROOT/name).read_text()
            self.assertNotRegex(source,r'seat\.zone(?!_id)')
            self.assertIn('JOIN venue_zones',source)
            self.assertIn('zone.name AS zone',source)
            self.assertIn('ORDER BY zone.sort_order',source)
    def test_initdb_order(self):
        for name in ('docker-compose.yml','tests/compose.phase11.yml','tests/compose.phase12.yml','../performance/docker-compose.performance.yml'):
            source=(ROOT/name).read_text()
            self.assertLess(source.index('012_add_admin_event_publishing.sql'),source.index('013_demo_seed.sql'))
    def test_admin_probe_is_opt_in(self):
        source=(ROOT/'CMakeLists.txt').read_text()
        self.assertIn('if(BUILD_TESTING AND TICKETING_PHASE17_EXTERNAL_TESTS)',source)
        probe=(ROOT/'tests/phase17_auth_probe.cpp').read_text()
        self.assertIn('"ticketing::AuthFilter", "ticketing::AdminFilter"',probe)
if __name__=='__main__': unittest.main(verbosity=2)
