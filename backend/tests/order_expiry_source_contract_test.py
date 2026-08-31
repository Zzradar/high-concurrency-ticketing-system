from pathlib import Path
import unittest


BACKEND_ROOT = Path(__file__).resolve().parents[1]


def read(relative_path: str) -> str:
    return (BACKEND_ROOT / relative_path).read_text(encoding="utf-8")


class OrderExpirySourceContractTest(unittest.TestCase):
    def test_candidate_scan_uses_database_time_index_shape_and_batch_limit(self) -> None:
        source = read("src/repositories/OrderRepository.cpp")
        self.assertIn("status = 'PENDING_PAYMENT'", source)
        self.assertIn("expires_at <= CURRENT_TIMESTAMP", source)
        self.assertIn("ORDER BY expires_at ASC, id ASC", source)
        self.assertIn("LIMIT $1", source)

    def test_single_order_lock_and_fixed_domain_lock_order(self) -> None:
        repository = read("src/repositories/OrderRepository.cpp")
        service = read("src/services/OrderExpiryService.cpp")
        self.assertIn("FOR UPDATE SKIP LOCKED", repository)
        self.assertIn("ORDER BY inventory.id ASC", repository)
        self.assertIn("FOR UPDATE OF inventory", repository)
        self.assertLess(
            service.index("lockOrder(state)"),
            service.index("lockReservation(state)"),
        )
        self.assertLess(
            service.index("lockReservation(state)"),
            service.index("lockSeats(state)"),
        )

    def test_release_has_membership_status_and_owner_guards(self) -> None:
        source = read("src/repositories/OrderRepository.cpp")
        self.assertIn("item.reservation_id = $1", source)
        self.assertIn("item.session_seat_id = inventory.id", source)
        self.assertIn("inventory.status = 'HELD'", source)
        self.assertIn("inventory.current_reservation_id = $1", source)
        self.assertIn("SET status = 'AVAILABLE'", source)
        self.assertIn("current_reservation_id = NULL", source)

    def test_service_checks_counts_and_transaction_lifecycle(self) -> None:
        source = read("src/services/OrderExpiryService.cpp")
        self.assertIn("released != state->expectedSeatCount", source)
        self.assertGreaterEqual(source.count("updated != 1"), 2)
        self.assertIn("newTransactionAsync", source)
        self.assertIn("setCommitCallback", source)
        self.assertIn("state->transaction->rollback()", source)
        self.assertNotIn('execSqlAsync("COMMIT")', source)

    def test_worker_is_configured_and_self_schedules_without_overlap(self) -> None:
        main = read("src/main.cpp")
        worker = read("src/workers/OrderExpiryWorker.cpp")
        config = read("config/config.docker.json")
        self.assertIn("registerBeginningAdvice", main)
        self.assertIn('getCustomConfig()["order_expiry_worker"]', main)
        self.assertIn('"batch_size": 100', config)
        self.assertIn('"interval_seconds": 5.0', config)
        self.assertIn("service_.runOnce", worker)
        self.assertIn("self->scheduleNextRound()", worker)
        self.assertIn("getLoop()->runAfter", worker)
        self.assertNotIn("runEvery", worker)


if __name__ == "__main__":
    unittest.main()
