from pathlib import Path
import unittest


BACKEND_ROOT = Path(__file__).resolve().parents[1]


def read(relative_path: str) -> str:
    return (BACKEND_ROOT / relative_path).read_text(encoding="utf-8")


class ReservationSourceContractTest(unittest.TestCase):
    def test_controller_registers_only_the_phase3_write_route(self) -> None:
        header = read("src/controllers/ReservationController.h")
        source = read("src/controllers/ReservationController.cpp")
        self.assertIn('"/reservations"', header)
        self.assertIn("drogon::Post", header)
        self.assertIn('getHeader("X-User-Id")', source)
        self.assertIn('getHeader("Idempotency-Key")', source)
        self.assertNotIn('body["userId"]', source)
        self.assertNotIn('body["price"]', source)
        self.assertNotIn('body["totalAmount"]', source)

    def test_service_normalizes_and_bounds_the_request(self) -> None:
        source = read("src/services/ReservationService.cpp")
        self.assertIn("idempotencyKey.size() > 128", source)
        self.assertIn("seats.size() > 6", source)
        self.assertIn("uniqueSeatIds.insert", source)
        self.assertIn("std::sort(seatIds.begin(), seatIds.end())", source)
        self.assertIn('"RSV-" + drogon::utils::getUuid(true)', source)
        self.assertIn('"TKT-" + drogon::utils::getUuid(true)', source)

    def test_idempotency_is_arbitrated_before_seat_locks(self) -> None:
        repository = read("src/repositories/ReservationRepository.cpp")
        service = read("src/services/ReservationService.cpp")
        conflict = repository.index(
            "ON CONFLICT (user_id, idempotency_key)"
        )
        seat_lock = repository.index("ORDER BY id ASC FOR UPDATE")
        self.assertLess(conflict, seat_lock)
        self.assertLess(
            service.index("arbitrateIdempotency(state)"),
            service.index("lockSeats(state)"),
        )
        self.assertIn("DO NOTHING", repository)
        self.assertIn("RETURNING", repository)
        self.assertIn("queryExisting(state, true)", service)

    def test_all_writes_receive_the_transaction(self) -> None:
        header = read("src/repositories/ReservationRepository.h")
        repository = read("src/repositories/ReservationRepository.cpp")
        for method in (
            "insertReservation",
            "lockSessionSeats",
            "holdSessionSeats",
            "insertReservationSeats",
            "insertOrder",
        ):
            method_start = header.index(f"void {method}")
            method_end = header.index(";", method_start)
            self.assertIn("TransactionPtr", header[method_start:method_end])
        self.assertNotIn('getDbClient("default")', repository)
        self.assertIn("status = 'AVAILABLE'", repository)
        self.assertIn("current_reservation_id = $1", repository)
        self.assertIn("reserved_price", repository)

    def test_transaction_lifecycle_is_explicit(self) -> None:
        source = read("src/services/ReservationService.cpp")
        self.assertIn("newTransactionAsync", source)
        self.assertIn("setCommitCallback", source)
        self.assertIn("state->transaction->rollback()", source)
        self.assertIn("state->transaction.reset()", source)
        self.assertNotIn('execSqlAsync("COMMIT")', source)
        self.assertNotIn("static sequence", source)


if __name__ == "__main__":
    unittest.main()
