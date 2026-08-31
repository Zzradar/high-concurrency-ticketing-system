from pathlib import Path
import unittest


BACKEND_ROOT = Path(__file__).resolve().parents[1]


class OrderSourceContractTest(unittest.TestCase):
    def test_order_get_route_and_user_scope_are_registered(self) -> None:
        controller = (BACKEND_ROOT / "src/controllers/OrderController.h").read_text(
            encoding="utf-8"
        )
        source = (BACKEND_ROOT / "src/controllers/OrderController.cpp").read_text(
            encoding="utf-8"
        )
        repository = (BACKEND_ROOT / "src/repositories/OrderRepository.cpp").read_text(
            encoding="utf-8"
        )
        self.assertIn('"/orders/{orderId}"', controller)
        self.assertIn("drogon::Get", controller)
        self.assertIn('getHeader("X-User-Id")', source)
        self.assertIn("ticket_order.id = $1", repository)
        self.assertIn("ticket_order.user_id = $2", repository)

    def test_order_query_returns_the_frontend_contract(self) -> None:
        repository = (BACKEND_ROOT / "src/repositories/OrderRepository.cpp").read_text(
            encoding="utf-8"
        )
        dto = (BACKEND_ROOT / "src/dto/TicketDtos.h").read_text(encoding="utf-8")
        for field in (
            "reservation_id",
            "event_id",
            "session_id",
            "session_seat_id",
            "total_amount",
            "expires_at",
            "created_at",
            "paid_at",
        ):
            self.assertIn(field, repository)
        self.assertIn("std::optional<std::string> paidAt", dto)
        self.assertIn('value["paidAt"]', dto)

    def test_order_get_is_read_only(self) -> None:
        repository = (BACKEND_ROOT / "src/repositories/OrderRepository.cpp").read_text(
            encoding="utf-8"
        )
        query_start = repository.index("void OrderRepository::findByIdForUser")
        query_end = repository.index(
            "void OrderRepository::findExpiredCandidateIds", query_start
        )
        query_method = repository[query_start:query_end].upper()
        self.assertNotIn("UPDATE ", query_method)
        self.assertNotIn("DELETE ", query_method)
        self.assertNotIn("INSERT ", query_method)


if __name__ == "__main__":
    unittest.main(verbosity=2)
