from pathlib import Path
import unittest
ROOT=Path(__file__).resolve().parents[1]
class SalesContracts(unittest.TestCase):
    def test_gate_uses_one_database_clock_without_global_write_lock(self):
        s=(ROOT/'src/repositories/SalesWindowRepository.cpp').read_text()
        self.assertEqual(s.count('clock_timestamp()'),1)
        self.assertIn('AS MATERIALIZED',s);self.assertNotIn('FOR UPDATE',s)
        self.assertIn('remaining_milliseconds',s)
    def test_fresh_init_installs_window_before_seed(self):
        for path in ['docker-compose.yml','tests/compose.phase11.yml','tests/compose.phase12.yml','../performance/docker-compose.performance.yml']:
            s=(ROOT/path).read_text(encoding='utf-8')
            targets=[l.split('/docker-entrypoint-initdb.d/')[1].split(':')[0] for l in s.splitlines() if '/docker-entrypoint-initdb.d/' in l]
            self.assertIn('011_add_event_sales_window.sql',targets)
            self.assertIn('012_demo_seed.sql',targets)
            self.assertLess('011_add_event_sales_window.sql','012_demo_seed.sql')
            self.assertNotIn('010_demo_seed.sql',targets)
    def test_read_fields_remain_independent_of_static_status(self):
        for name in ['Event','Session']:
            s=(ROOT/('src/repositories/'+name+'Repository.cpp')).read_text(encoding='utf-8')
            self.assertIn('statement_timestamp()',s);self.assertIn('SalesWindow::fromRow(row)',s)
            self.assertIn('sales_evaluated_at',s)
if __name__=='__main__':unittest.main(verbosity=2)
