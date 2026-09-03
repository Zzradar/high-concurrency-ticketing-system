from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


class AuthenticatedRoutesSourceContractTest(unittest.TestCase):
    def test_business_routes_use_filter_and_context(self) -> None:
        controllers = (
            "ReservationController",
            "CheckoutSessionController",
            "OrderController",
            "PaymentController",
            "NotificationController",
        )
        for name in controllers:
            header = read(f"src/controllers/{name}.h")
            source = read(f"src/controllers/{name}.cpp")
            self.assertIn('"ticketing::AuthFilter"', header, name)
            self.assertNotIn("X-User-Id", source, name)
            self.assertIn("authenticatedUserId(request)", source, name)

    def test_public_seat_map_requires_authenticated_database_ownership(self) -> None:
        header = read("src/controllers/SeatController.h")
        source = read("src/controllers/SeatController.cpp")
        self.assertNotIn('"ticketing::AuthFilter"', header)
        self.assertIn("authService_.authenticate", source)
        self.assertIn("checkoutRepository_.findByIdForUser", source)
        self.assertIn("checkout->value.sessionId == sessionId", source)
        self.assertNotIn("X-User-Id", source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
