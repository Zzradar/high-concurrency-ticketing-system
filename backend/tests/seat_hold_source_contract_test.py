from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class SeatHoldSourceContractTest(unittest.TestCase):
    def test_redis_infrastructure_and_atomic_scripts_are_enabled(self):
        cmake = (ROOT / "CMakeLists.txt").read_text(encoding="utf-8")
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        service = (ROOT / "src/services/SeatHoldService.cpp").read_text(encoding="utf-8")
        main = (ROOT / "src/main.cpp").read_text(encoding="utf-8")

        self.assertIn("set(BUILD_REDIS ON", cmake)
        self.assertIn("libhiredis-dev", dockerfile)
        self.assertIn("libhiredis1.1.0", dockerfile)
        self.assertIn("redis:7.4-alpine", compose)
        self.assertIn("ticketing:seat-hold:{", service)
        self.assertIn("redis.call('SET', key, owner .. '|' .. target_revision", service)
        self.assertIn("current_owner == owner and revision <= target_revision", service)
        self.assertIn("redis.call('GET', key) == expected", service)
        self.assertIn('std::string command = "MGET"', service)
        self.assertIn("SeatHoldService::validateConfiguration()", main)

    def test_configuration_has_short_timeout_and_positive_ttl(self):
        for filename, host in (("config.json", "127.0.0.1"), ("config.docker.json", "redis")):
            config = (ROOT / "config" / filename).read_text(encoding="utf-8")
            self.assertIn('"name": "seat_holds"', config)
            self.assertIn(f'"host": "{host}"', config)
            self.assertIn('"timeout": 0.4', config)
            self.assertIn('"ttl_seconds": 300', config)


if __name__ == "__main__":
    unittest.main()
