from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
ORDER_CONTROLLER = (ROOT / "src/controllers/OrderController.h").read_text(encoding="utf-8")
ORDER_REPOSITORY = (ROOT / "src/repositories/OrderRepository.cpp").read_text(encoding="utf-8")
ORDER_SERVICE = (ROOT / "src/services/OrderService.cpp").read_text(encoding="utf-8")
SESSION_CONTROLLER = (ROOT / "src/controllers/SessionController.h").read_text(encoding="utf-8")
SESSION_REPOSITORY = (ROOT / "src/repositories/SessionRepository.cpp").read_text(encoding="utf-8")
RESERVATION = (ROOT / "src/services/ReservationService.cpp").read_text(encoding="utf-8")


class OrderRecoverySourceContractTest(unittest.TestCase):
    def test_order_list_is_scoped_filtered_and_bounded_without_n_plus_one(self) -> None:
        self.assertIn('"/orders"', ORDER_CONTROLLER)
        self.assertIn('"ticketing::AuthFilter"', ORDER_CONTROLLER)
        method = ORDER_REPOSITORY.split("void OrderRepository::listForUser", 1)[1].split(
            "void OrderRepository::findExpiredCandidateIds", 1
        )[0]
        self.assertEqual(method.count("execSqlAsync"), 1)
        self.assertIn("ticket_order.user_id = $1", method)
        self.assertIn("ticket_order.status = $2", method)
        self.assertIn("reservation.session_id = $3", method)
        self.assertIn("LIMIT $4", method)
        self.assertIn("ticket_order.created_at DESC", method)
        self.assertIn("limit > 100", ORDER_SERVICE)

    def test_session_detail_is_public_and_database_backed(self) -> None:
        self.assertIn('"/sessions/{sessionId}"', SESSION_CONTROLLER)
        self.assertNotIn('"ticketing::AuthFilter"', SESSION_CONTROLLER)
        self.assertIn("WHERE session.id = $1", SESSION_REPOSITORY)

    def test_order_created_notification_is_in_reservation_transaction(self) -> None:
        self.assertIn("notificationRepository_.insert", RESERVATION)
        self.assertIn('"ORDER_CREATED"', RESERVATION)
        self.assertIn('"order-created:" + state->orderId', RESERVATION)
        notification = RESERVATION.index("createOrderNotification(state)")
        commit = RESERVATION.index("commit(state);", notification)
        self.assertLess(notification, commit)


if __name__ == "__main__":
    unittest.main(verbosity=2)
