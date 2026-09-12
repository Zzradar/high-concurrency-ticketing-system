from pathlib import Path
import json
import unittest
ROOT=Path(__file__).resolve().parents[1]
class Phase16Contract(unittest.TestCase):
    def test_config_variants_preserve_existing_capacity(self):
        for path in (ROOT/'config').glob('config*.json'):
            config=json.loads(path.read_text(encoding='utf-8'))
            custom=config['custom_config']
            for group in ['seat_availability_read_model','seat_availability_projection']:
                self.assertTrue(all(isinstance(v,(int,float)) and v>0 for v in custom[group].values()),str(path))
            holds=[c for c in config['redis_clients'] if c['name']=='seat_holds']
            self.assertEqual(len(holds),1)
            self.assertEqual(holds[0]['number_of_connections'],2)
            self.assertEqual(config['db_clients'][0]['number_of_connections'],4)
    def test_all_fresh_database_stacks_install_phase16_before_seed(self):
        for path in [ROOT/'docker-compose.yml',ROOT/'tests/compose.phase11.yml',ROOT/'tests/compose.phase12.yml',ROOT/'../performance/docker-compose.performance.yml']:
            text=path.read_text(encoding='utf-8')
            self.assertIn('010_add_seat_availability_read_model.sql',text)
            self.assertLess(text.index('010_add_seat_availability_read_model.sql'),text.index('012_demo_seed.sql'))

    def test_worker_lease_and_atomic_model_boundaries(self):
        worker=(ROOT/'src/workers/SeatAvailabilityProjectionWorker.cpp').read_text(encoding='utf-8')
        self.assertIn('FOR UPDATE SKIP LOCKED',worker)
        self.assertIn('WHERE id=$1::bigint AND lease_token=$2',worker)
        self.assertIn('runAfter',worker)
        self.assertNotIn('std::thread',worker)
        model=(ROOT/'src/services/SeatAvailabilityReadModel.cpp').read_text(encoding='utf-8')
        self.assertIn('executor->trySubmit',model)
        self.assertIn('std::vector<std::array<std::string,4>> rows',model)
        self.assertIn('owned.push_back(v.asString())',model)
        self.assertNotIn('new SeatMapComputeExecutor',model)
        for path in (ROOT/'src/availability').glob('*.lua'):
            text=path.read_text(encoding='utf-8')
            self.assertNotIn("redis.call('KEYS'",text)
            self.assertNotIn("redis.call('SCAN'",text)
    def test_migration_is_additive_and_atomic(self):
        migration=(ROOT/'db/migrations/010_add_seat_availability_read_model.sql').read_text()
        self.assertTrue(migration.startswith('BEGIN;'))
        self.assertTrue(migration.rstrip().endswith('COMMIT;'))
        self.assertEqual(migration.count('WHEN (OLD.status IS DISTINCT FROM NEW.status)'),2)
        self.assertIn('OLD.formal_version + 1',migration)
        self.assertNotIn('AFTER INSERT',migration)
if __name__=='__main__':unittest.main(verbosity=2)
