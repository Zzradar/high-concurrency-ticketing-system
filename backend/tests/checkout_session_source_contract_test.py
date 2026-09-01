from pathlib import Path
import unittest


BACKEND_ROOT = Path(__file__).resolve().parents[1]


def read(relative_path: str) -> str:
    return (BACKEND_ROOT / relative_path).read_text(encoding="utf-8")


class CheckoutSessionSourceContractTest(unittest.TestCase):
    def test_controller_registers_only_the_phase5_routes(self) -> None:
        header = read("src/controllers/CheckoutSessionController.h")
        source = read("src/controllers/CheckoutSessionController.cpp")
        for route in (
            '"/checkout-sessions"',
            '"/checkout-sessions/{id}"',
            '"/checkout-sessions/{id}/seats"',
            '"/checkout-sessions/{id}/confirm"',
            '"/checkout-sessions/{id}/abandon"',
        ):
            self.assertIn(route, header)
        self.assertIn('getHeader("X-User-Id")', source)
        self.assertNotIn('getHeader("Idempotency-Key")', source)

    def test_selected_seats_are_full_set_replacement_under_row_lock(self) -> None:
        repository = read("src/repositories/CheckoutSessionRepository.cpp")
        service = read("src/services/CheckoutSessionService.cpp")
        self.assertIn("FOR UPDATE", repository)
        self.assertIn("DELETE FROM checkout_session_seats", repository)
        self.assertIn("replaceDeleteSeats(state)", service)
        self.assertIn("replaceInsertSeats(state)", service)
        self.assertIn("normalizeSeatIds(body[\"seatIds\"], 0)", service)
        self.assertIn("status != \"SELECTING\"", service)

    def test_confirm_generates_one_server_key_and_reuses_phase3(self) -> None:
        service = read("src/services/CheckoutSessionService.cpp")
        reservation = read("src/services/ReservationService.cpp")
        self.assertIn('"CHK-CONFIRM-" + drogon::utils::getUuid(true)', service)
        self.assertIn("activeConfirmIdempotencyKey", service)
        self.assertIn("setSubmitting", service)
        self.assertIn("createReservationForCheckout", service)
        self.assertIn("finalizeReserved", service)
        self.assertIn("resetAfterBusinessFailure", service)
        self.assertIn("createReservation(CreateReservationInput", reservation)

    def test_submitting_retry_waits_for_checkout_transaction_commit(self) -> None:
        service = read("src/services/CheckoutSessionService.cpp")
        submitting_branch = service.split(
            'if (status == "SUBMITTING")', 1
        )[1].split('if (status != "SELECTING")', 1)[0]
        self.assertIn("confirmPrepareCommit(state);", submitting_branch)
        self.assertNotIn("runFormalReservation(state);", submitting_branch)
        self.assertNotIn("rollback()", submitting_branch)
        self.assertIn("setCommitCallback", service)
        self.assertIn("if (!committed)", service)

    def test_unknown_failure_stays_submitting_and_reconciliation_is_passive(self) -> None:
        service = read("src/services/CheckoutSessionService.cpp")
        repository = read("src/repositories/CheckoutSessionRepository.cpp")
        main = read("src/main.cpp")
        self.assertIn("CreateReservationOutcome::InternalError", service)
        self.assertIn("failConfirm(state, CheckoutSessionOutcome::InternalError)", service)
        self.assertIn("JOIN reservations AS reservation", repository)
        self.assertIn("JOIN orders AS ticket_order", repository)
        self.assertIn("WHERE checkout.status = 'SUBMITTING'", repository)
        self.assertIn("reconcileSubmitting", main)
        self.assertIn('getCustomConfig()["checkout_session_reconciliation"]', main)
        self.assertIn("checkoutReconciliationBatchSize", main)
        self.assertNotIn("runAfter", main)

    def test_checkout_dto_hides_internal_confirm_key(self) -> None:
        dto = read("src/dto/TicketDtos.h")
        repository_header = read("src/repositories/CheckoutSessionRepository.h")
        self.assertIn("struct CheckoutSession", dto)
        self.assertNotIn('value["activeConfirmIdempotencyKey"]', dto)
        self.assertIn("activeConfirmIdempotencyKey", repository_header)


if __name__ == "__main__":
    unittest.main()
