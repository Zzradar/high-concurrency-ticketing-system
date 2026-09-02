import unittest

from checkout_session_test_support import (
    SESSION_ID,
    TEST_SEATS,
    TEST_USERS,
    cleanup_phase5_data,
    confirm_checkout,
    create_checkout,
    psql,
    request_json,
)


class CheckoutSessionHttpIntegrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cleanup_phase5_data(recreate_users=True)

    @classmethod
    def tearDownClass(cls) -> None:
        cleanup_phase5_data()

    def setUp(self) -> None:
        cleanup_phase5_data(recreate_users=True)

    def assert_checkout(self, value, *, user_id, seat_ids, status, revision=None):
        self.assertEqual(value["userId"], user_id)
        self.assertEqual(value["sessionId"], SESSION_ID)
        self.assertEqual(value["seatIds"], sorted(seat_ids))
        self.assertEqual(value["status"], status)
        self.assertIsInstance(value["revision"], int)
        if revision is not None:
            self.assertEqual(value["revision"], revision)
        self.assertTrue(value["id"].startswith("CHK-"))
        self.assertTrue(value["createdAt"].endswith("Z"))
        self.assertTrue(value["updatedAt"].endswith("Z"))

    def test_create_get_list_replace_empty_and_abandon(self) -> None:
        first_status, first = create_checkout(TEST_USERS[0], [TEST_SEATS[0]])
        second_status, second = create_checkout(TEST_USERS[0], [TEST_SEATS[1]])
        self.assertEqual((first_status, second_status), (201, 201))
        self.assertNotEqual(first["id"], second["id"])
        self.assertEqual((first["revision"], second["revision"]), (0, 0))

        get_status, fetched = request_json(
            f"/checkout-sessions/{first['id']}", user_id=TEST_USERS[0]
        )
        self.assertEqual(get_status, 200, fetched)
        self.assertEqual(fetched["revision"], 0)

        status, values = request_json(
            f"/checkout-sessions?sessionId={SESSION_ID}&recoverable=true",
            user_id=TEST_USERS[0],
        )
        self.assertEqual(status, 200, values)
        self.assertEqual({value["id"] for value in values}, {first["id"], second["id"]})
        self.assertEqual({value["revision"] for value in values}, {0})

        status, updated = request_json(
            f"/checkout-sessions/{first['id']}/seats",
            method="PUT",
            user_id=TEST_USERS[0],
            body={
                "seatIds": [TEST_SEATS[2], TEST_SEATS[1]],
                "expectedRevision": 0,
            },
        )
        self.assertEqual(status, 200, updated)
        self.assert_checkout(
            updated,
            user_id=TEST_USERS[0],
            seat_ids=[TEST_SEATS[1], TEST_SEATS[2]],
            status="SELECTING",
            revision=1,
        )

        status, empty = request_json(
            f"/checkout-sessions/{first['id']}/seats",
            method="PUT",
            user_id=TEST_USERS[0],
            body={"seatIds": [], "expectedRevision": 1},
        )
        self.assertEqual(status, 200, empty)
        self.assertEqual(empty["seatIds"], [])
        self.assertEqual(empty["revision"], 2)

        wrong_status, wrong = request_json(
            f"/checkout-sessions/{first['id']}", user_id=TEST_USERS[1]
        )
        self.assertEqual(wrong_status, 404, wrong)
        self.assertEqual(wrong["code"], "CHECKOUT_SESSION_NOT_FOUND")

        abandon_status, abandoned = request_json(
            f"/checkout-sessions/{first['id']}/abandon",
            method="POST",
            user_id=TEST_USERS[0],
        )
        repeated_status, repeated = request_json(
            f"/checkout-sessions/{first['id']}/abandon",
            method="POST",
            user_id=TEST_USERS[0],
        )
        self.assertEqual((abandon_status, repeated_status), (200, 200))
        self.assertEqual(abandoned["status"], "ABANDONED")
        self.assertEqual(repeated, abandoned)

        _, recoverable = request_json(
            f"/checkout-sessions?sessionId={SESSION_ID}&recoverable=true",
            user_id=TEST_USERS[0],
        )
        self.assertEqual([value["id"] for value in recoverable], [second["id"]])

    def test_validation_and_atomic_replace_failure(self) -> None:
        cases = (
            ({"sessionId": SESSION_ID, "seatIds": []}, 400),
            ({"sessionId": SESSION_ID, "seatIds": [TEST_SEATS[0]] * 2}, 400),
            ({"sessionId": SESSION_ID, "seatIds": [f"missing-{i}" for i in range(7)]}, 400),
            ({"sessionId": SESSION_ID, "seatIds": ["ses-concert-1002-A01"]}, 400),
            ({"sessionId": "missing-session", "seatIds": [TEST_SEATS[0]]}, 404),
        )
        for body, expected in cases:
            with self.subTest(body=body):
                status, _ = request_json(
                    "/checkout-sessions",
                    method="POST",
                    user_id=TEST_USERS[0],
                    body=body,
                )
                self.assertEqual(status, expected)

        max_status, maximum = create_checkout(TEST_USERS[0], TEST_SEATS)
        self.assertEqual(max_status, 201, maximum)
        self.assertEqual(maximum["seatIds"], TEST_SEATS)

        status, checkout = create_checkout(TEST_USERS[0], TEST_SEATS[:2])
        self.assertEqual(status, 201, checkout)
        failed_status, failed = request_json(
            f"/checkout-sessions/{checkout['id']}/seats",
            method="PUT",
            user_id=TEST_USERS[0],
            body={
                "seatIds": [TEST_SEATS[2], "ses-concert-1002-A01"],
                "expectedRevision": 0,
            },
        )
        self.assertEqual(failed_status, 400, failed)
        _, current = request_json(
            f"/checkout-sessions/{checkout['id']}", user_id=TEST_USERS[0]
        )
        self.assertEqual(current["seatIds"], TEST_SEATS[:2])
        self.assertEqual(current["revision"], 0)

        wrong_status, wrong = request_json(
            f"/checkout-sessions/{checkout['id']}/seats",
            method="PUT",
            user_id=TEST_USERS[1],
            body={"seatIds": [TEST_SEATS[2]], "expectedRevision": 0},
        )
        self.assertEqual(wrong_status, 404, wrong)
        self.assertEqual(wrong["code"], "CHECKOUT_SESSION_NOT_FOUND")

        invalid_revisions = (
            {"seatIds": [TEST_SEATS[2]]},
            {"seatIds": [TEST_SEATS[2]], "expectedRevision": "0"},
            {"seatIds": [TEST_SEATS[2]], "expectedRevision": -1},
            {"seatIds": [TEST_SEATS[2]], "expectedRevision": 1.5},
        )
        for body in invalid_revisions:
            with self.subTest(body=body):
                invalid_status, invalid = request_json(
                    f"/checkout-sessions/{checkout['id']}/seats",
                    method="PUT",
                    user_id=TEST_USERS[0],
                    body=body,
                )
                self.assertEqual(invalid_status, 400, invalid)
                self.assertEqual(invalid["code"], "INVALID_ARGUMENT")

        success_status, success = request_json(
            f"/checkout-sessions/{checkout['id']}/seats",
            method="PUT",
            user_id=TEST_USERS[0],
            body={"seatIds": [TEST_SEATS[2]], "expectedRevision": 0},
        )
        self.assertEqual(success_status, 200, success)
        self.assertEqual(success["revision"], 1)
        stale_status, stale = request_json(
            f"/checkout-sessions/{checkout['id']}/seats",
            method="PUT",
            user_id=TEST_USERS[0],
            body={"seatIds": [TEST_SEATS[3]], "expectedRevision": 0},
        )
        self.assertEqual(stale_status, 409, stale)
        self.assertEqual(stale["code"], "CHECKOUT_SESSION_VERSION_CONFLICT")
        _, after_stale = request_json(
            f"/checkout-sessions/{checkout['id']}", user_id=TEST_USERS[0]
        )
        self.assertEqual(after_stale["seatIds"], [TEST_SEATS[2]])
        self.assertEqual(after_stale["revision"], 1)

        inventory = psql(
            f"SELECT string_agg(status, ',' ORDER BY id) FROM session_seats "
            f"WHERE id IN ({', '.join(repr(seat) for seat in TEST_SEATS[:2])});"
        )
        self.assertEqual(inventory, "AVAILABLE,AVAILABLE")

    def test_confirm_success_and_terminal_state_guards(self) -> None:
        _, checkout = create_checkout(TEST_USERS[0], TEST_SEATS[:2])
        status, confirmed = confirm_checkout(checkout["id"], TEST_USERS[0])
        self.assertEqual(status, 200, confirmed)
        self.assert_checkout(
            confirmed,
            user_id=TEST_USERS[0],
            seat_ids=TEST_SEATS[:2],
            status="RESERVED",
            revision=0,
        )
        self.assertEqual(confirmed["reservation"]["id"], confirmed["reservationId"])
        self.assertEqual(
            confirmed["order"]["reservationId"], confirmed["reservationId"]
        )
        self.assertNotIn("orderId", confirmed)

        row = psql(
            f"""
            SELECT checkout.status,
                   checkout.active_confirm_idempotency_key LIKE 'CHK-CONFIRM-%',
                   COUNT(DISTINCT reservation.id),
                   COUNT(DISTINCT ticket_order.id),
                   COUNT(item.session_seat_id)
            FROM checkout_sessions AS checkout
            JOIN reservations AS reservation ON reservation.id = checkout.reservation_id
            JOIN orders AS ticket_order ON ticket_order.reservation_id = reservation.id
            JOIN reservation_session_seats AS item ON item.reservation_id = reservation.id
            WHERE checkout.id = '{checkout['id']}'
            GROUP BY checkout.status, checkout.active_confirm_idempotency_key;
            """
        )
        self.assertEqual(row.split("\t"), ["RESERVED", "t", "1", "1", "2"])

        put_status, put_error = request_json(
            f"/checkout-sessions/{checkout['id']}/seats",
            method="PUT",
            user_id=TEST_USERS[0],
            body={
                "seatIds": [TEST_SEATS[2]],
                "expectedRevision": checkout["revision"],
            },
        )
        abandon_status, abandon_error = request_json(
            f"/checkout-sessions/{checkout['id']}/abandon",
            method="POST",
            user_id=TEST_USERS[0],
        )
        self.assertEqual(put_status, 409, put_error)
        self.assertEqual(put_error["code"], "CHECKOUT_SESSION_NOT_MODIFIABLE")
        self.assertEqual(abandon_status, 409, abandon_error)
        self.assertEqual(abandon_error["code"], "CHECKOUT_SESSION_NOT_ABANDONABLE")
        preserved = psql(
            f"SELECT COUNT(*) FROM orders WHERE reservation_id = "
            f"'{confirmed['reservationId']}';"
        )
        self.assertEqual(preserved, "1")

    def test_business_seat_conflict_resets_to_selecting(self) -> None:
        _, winner = create_checkout(TEST_USERS[0], [TEST_SEATS[0]])
        _, loser = create_checkout(TEST_USERS[1], [TEST_SEATS[0]])
        winner_status, _ = confirm_checkout(winner["id"], TEST_USERS[0])
        loser_status, loser_error = confirm_checkout(loser["id"], TEST_USERS[1])
        self.assertEqual(winner_status, 200)
        self.assertEqual(loser_status, 409, loser_error)
        self.assertEqual(loser_error["code"], "SEAT_CONFLICT")

        state = psql(
            f"""
            SELECT status,
                   active_confirm_idempotency_key IS NULL,
                   reservation_id IS NULL,
                   (SELECT COUNT(*) FROM checkout_session_seats
                    WHERE checkout_session_id = checkout_sessions.id)
            FROM checkout_sessions WHERE id = '{loser['id']}';
            """
        )
        self.assertEqual(state.split("\t"), ["SELECTING", "t", "t", "1"])

    def test_submitting_retry_reuses_stored_key_and_cannot_be_abandoned(self) -> None:
        _, checkout = create_checkout(TEST_USERS[0], [TEST_SEATS[0]])
        stored_key = "it-phase5-user-retry"
        psql(
            f"UPDATE checkout_sessions SET status = 'SUBMITTING', "
            f"active_confirm_idempotency_key = '{stored_key}' "
            f"WHERE id = '{checkout['id']}';"
        )
        abandon_status, abandon_error = request_json(
            f"/checkout-sessions/{checkout['id']}/abandon",
            method="POST",
            user_id=TEST_USERS[0],
        )
        self.assertEqual(abandon_status, 409, abandon_error)
        self.assertEqual(abandon_error["code"], "CHECKOUT_SESSION_NOT_ABANDONABLE")

        confirm_status, confirmed = confirm_checkout(checkout["id"], TEST_USERS[0])
        self.assertEqual(confirm_status, 200, confirmed)
        key_and_count = psql(
            f"""
            SELECT checkout.active_confirm_idempotency_key,
                   COUNT(reservation.id)
            FROM checkout_sessions AS checkout
            JOIN reservations AS reservation
              ON reservation.user_id = checkout.user_id
             AND reservation.idempotency_key = checkout.active_confirm_idempotency_key
            WHERE checkout.id = '{checkout['id']}'
            GROUP BY checkout.active_confirm_idempotency_key;
            """
        )
        self.assertEqual(key_and_count.split("\t"), [stored_key, "1"])

    def test_technical_failure_keeps_submitting_and_server_key(self) -> None:
        _, checkout = create_checkout(TEST_USERS[0], [TEST_SEATS[0]])
        psql(
            f"""
            CREATE FUNCTION phase5_force_reservation_failure()
            RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN
                IF NEW.user_id = '{TEST_USERS[0]}' THEN
                    RAISE EXCEPTION 'phase5 forced unknown result';
                END IF;
                RETURN NEW;
            END;
            $$;
            CREATE TRIGGER phase5_force_reservation_failure
            BEFORE INSERT ON reservations
            FOR EACH ROW EXECUTE FUNCTION phase5_force_reservation_failure();
            """
        )
        try:
            status, error = confirm_checkout(checkout["id"], TEST_USERS[0])
            self.assertEqual(status, 500, error)
            self.assertEqual(error["code"], "INTERNAL_ERROR")
            state = psql(
                f"""
                SELECT status,
                       active_confirm_idempotency_key LIKE 'CHK-CONFIRM-%',
                       reservation_id IS NULL
                FROM checkout_sessions WHERE id = '{checkout['id']}';
                """
            )
            self.assertEqual(state.split("\t"), ["SUBMITTING", "t", "t"])
            formal_count = psql(
                f"SELECT COUNT(*) FROM reservations WHERE user_id = '{TEST_USERS[0]}';"
            )
            self.assertEqual(formal_count, "0")
        finally:
            psql(
                "DROP TRIGGER IF EXISTS phase5_force_reservation_failure ON reservations; "
                "DROP FUNCTION IF EXISTS phase5_force_reservation_failure();"
            )

        get_status, current = request_json(
            f"/checkout-sessions/{checkout['id']}", user_id=TEST_USERS[0]
        )
        self.assertEqual(get_status, 200, current)
        self.assertEqual(current["status"], "SUBMITTING")


if __name__ == "__main__":
    unittest.main(verbosity=2)
