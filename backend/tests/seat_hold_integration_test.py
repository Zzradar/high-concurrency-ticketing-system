import subprocess
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor

from checkout_session_test_support import (
    BACKEND_ROOT,
    SESSION_ID,
    TEST_SEATS,
    TEST_USERS,
    cleanup_phase5_data,
    cleanup_seat_holds,
    confirm_checkout,
    create_checkout,
    psql,
    redis_cli,
    request_json,
)


def hold_key(seat_id: str) -> str:
    return f"ticketing:seat-hold:{{{SESSION_ID}}}:{seat_id}"


def compose(*arguments: str) -> None:
    completed = subprocess.run(
        ["docker", "compose", *arguments],
        cwd=BACKEND_ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if completed.returncode != 0:
        raise AssertionError(completed.stderr)


def start_redis() -> None:
    compose("start", "redis")
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            if redis_cli("PING") == "PONG":
                time.sleep(1.0)
                return
        except AssertionError:
            pass
        time.sleep(0.2)
    raise AssertionError("Redis did not become ready")


class SeatHoldIntegrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        start_redis()
        cleanup_phase5_data(recreate_users=True)

    @classmethod
    def tearDownClass(cls) -> None:
        start_redis()
        cleanup_phase5_data()

    def setUp(self) -> None:
        start_redis()
        cleanup_phase5_data(recreate_users=True)

    def test_create_holds_all_seats_with_owner_revision_and_ttl(self) -> None:
        status, checkout = create_checkout(TEST_USERS[0], TEST_SEATS[:2])
        self.assertEqual(status, 201, checkout)
        for seat_id in TEST_SEATS[:2]:
            self.assertEqual(redis_cli("GET", hold_key(seat_id)), f"{checkout['id']}|0")
            ttl = int(redis_cli("TTL", hold_key(seat_id)))
            self.assertGreater(ttl, 0)
            self.assertLessEqual(ttl, 300)
        inventory = psql(
            f"SELECT string_agg(status, ',' ORDER BY id) FROM session_seats "
            f"WHERE id IN ({', '.join(repr(seat) for seat in TEST_SEATS[:2])});"
        )
        self.assertEqual(inventory, "AVAILABLE,AVAILABLE")

    def test_concurrent_create_has_one_winner_and_explicit_temporary_conflict(self) -> None:
        barrier = threading.Barrier(2)

        def create(user_id):
            barrier.wait()
            return create_checkout(user_id, [TEST_SEATS[0]])

        with ThreadPoolExecutor(max_workers=2) as executor:
            responses = list(executor.map(create, TEST_USERS[:2]))
        self.assertEqual(sorted(status for status, _ in responses), [201, 409])
        conflict = next(body for status, body in responses if status == 409)
        winner = next(body for status, body in responses if status == 201)
        self.assertEqual(conflict["code"], "SEAT_TEMPORARILY_HELD")
        self.assertEqual(redis_cli("GET", hold_key(TEST_SEATS[0])), f"{winner['id']}|0")
        self.assertEqual(
            psql(
                f"SELECT COUNT(*) FROM checkout_sessions WHERE user_id IN "
                f"('{TEST_USERS[0]}','{TEST_USERS[1]}');"
            ),
            "1",
        )

    def test_seat_map_masks_other_hold_but_not_owner_and_expires(self) -> None:
        _, checkout = create_checkout(TEST_USERS[0], [TEST_SEATS[0]])

        def status_for(path):
            status, seats = request_json(path, user_id=TEST_USERS[0])
            self.assertEqual(status, 200)
            return next(seat["status"] for seat in seats if seat["id"] == TEST_SEATS[0])

        path = f"/sessions/{SESSION_ID}/seats"
        self.assertEqual(status_for(path), "HELD")
        self.assertEqual(
            status_for(f"{path}?checkoutSessionId={checkout['id']}"), "AVAILABLE"
        )
        redis_cli("EXPIRE", hold_key(TEST_SEATS[0]), "1")
        time.sleep(1.2)
        self.assertEqual(status_for(path), "AVAILABLE")

    def test_replace_conflict_is_atomic_and_success_uses_revision_fence(self) -> None:
        _, first = create_checkout(TEST_USERS[0], [TEST_SEATS[0]])
        _, second = create_checkout(TEST_USERS[1], [TEST_SEATS[1]])
        status, conflict = request_json(
            f"/checkout-sessions/{first['id']}/seats",
            method="PUT",
            user_id=TEST_USERS[0],
            body={"seatIds": [TEST_SEATS[1], TEST_SEATS[2]], "expectedRevision": 0},
        )
        self.assertEqual(status, 409, conflict)
        self.assertEqual(conflict["code"], "SEAT_TEMPORARILY_HELD")
        _, current = request_json(
            f"/checkout-sessions/{first['id']}", user_id=TEST_USERS[0]
        )
        self.assertEqual(current["seatIds"], [TEST_SEATS[0]])
        self.assertEqual(current["revision"], 0)
        self.assertEqual(redis_cli("GET", hold_key(TEST_SEATS[0])), f"{first['id']}|0")
        self.assertEqual(redis_cli("GET", hold_key(TEST_SEATS[1])), f"{second['id']}|0")
        self.assertEqual(redis_cli("GET", hold_key(TEST_SEATS[2])), "")

        status, updated = request_json(
            f"/checkout-sessions/{first['id']}/seats",
            method="PUT",
            user_id=TEST_USERS[0],
            body={"seatIds": [TEST_SEATS[2]], "expectedRevision": 0},
        )
        self.assertEqual(status, 200, updated)
        self.assertEqual(updated["revision"], 1)
        self.assertEqual(redis_cli("GET", hold_key(TEST_SEATS[2])), f"{first['id']}|1")
        self.assertEqual(redis_cli("GET", hold_key(TEST_SEATS[0])), "")

        fencing_script = """
        local value = redis.call('GET', KEYS[1])
        local separator = string.find(value, '|', 1, true)
        local owner = string.sub(value, 1, separator - 1)
        local revision = tonumber(string.sub(value, separator + 1))
        if owner == ARGV[1] and revision <= tonumber(ARGV[2]) then
          return redis.call('DEL', KEYS[1])
        end
        return 0
        """
        redis_cli("SET", hold_key(TEST_SEATS[0]), f"{first['id']}|5", "EX", "300")
        redis_cli("EVAL", fencing_script, "1", hold_key(TEST_SEATS[0]), first["id"], "4")
        self.assertEqual(redis_cli("GET", hold_key(TEST_SEATS[0])), f"{first['id']}|5")
        redis_cli("EVAL", fencing_script, "1", hold_key(TEST_SEATS[0]), first["id"], "5")
        self.assertEqual(redis_cli("GET", hold_key(TEST_SEATS[0])), "")

    def test_postgres_failure_aborts_only_new_exact_revision_holds(self) -> None:
        psql(
            f"""
            CREATE FUNCTION phase7_force_checkout_failure()
            RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN
                IF NEW.user_id = '{TEST_USERS[0]}' THEN
                    RAISE EXCEPTION 'phase7 forced checkout failure';
                END IF;
                RETURN NEW;
            END;
            $$;
            CREATE TRIGGER phase7_force_checkout_failure
            BEFORE INSERT ON checkout_sessions
            FOR EACH ROW EXECUTE FUNCTION phase7_force_checkout_failure();
            """
        )
        try:
            status, error = create_checkout(TEST_USERS[0], [TEST_SEATS[0]])
            self.assertEqual(status, 500, error)
            self.assertEqual(redis_cli("GET", hold_key(TEST_SEATS[0])), "")
            self.assertEqual(
                psql(
                    f"SELECT COUNT(*) FROM checkout_sessions "
                    f"WHERE user_id = '{TEST_USERS[0]}';"
                ),
                "0",
            )
        finally:
            psql(
                "DROP TRIGGER IF EXISTS phase7_force_checkout_failure ON checkout_sessions; "
                "DROP FUNCTION IF EXISTS phase7_force_checkout_failure();"
            )

    def test_confirm_barrier_and_terminal_cleanup(self) -> None:
        _, blocked = create_checkout(TEST_USERS[0], [TEST_SEATS[0]])
        redis_cli("SET", hold_key(TEST_SEATS[0]), "other-checkout|9", "EX", "300")
        status, error = confirm_checkout(blocked["id"], TEST_USERS[0])
        self.assertEqual(status, 409, error)
        self.assertEqual(error["code"], "SEAT_TEMPORARILY_HELD")
        state = psql(
            f"SELECT status, active_confirm_idempotency_key IS NULL "
            f"FROM checkout_sessions WHERE id = '{blocked['id']}';"
        )
        self.assertEqual(state.split("\t"), ["SELECTING", "t"])

        cleanup_seat_holds()
        _, checkout = create_checkout(TEST_USERS[1], [TEST_SEATS[1]])
        status, confirmed = confirm_checkout(checkout["id"], TEST_USERS[1])
        self.assertEqual(status, 200, confirmed)
        self.assertEqual(redis_cli("GET", hold_key(TEST_SEATS[1])), "")
        self.assertEqual(
            psql(f"SELECT status FROM session_seats WHERE id = '{TEST_SEATS[1]}';"),
            "HELD",
        )

    def test_business_failure_and_abandon_release_holds(self) -> None:
        _, winner = create_checkout(TEST_USERS[0], [TEST_SEATS[0]])
        cleanup_seat_holds()
        _, loser = create_checkout(TEST_USERS[1], [TEST_SEATS[0]])
        cleanup_seat_holds()
        self.assertEqual(confirm_checkout(winner["id"], TEST_USERS[0])[0], 200)
        status, error = confirm_checkout(loser["id"], TEST_USERS[1])
        self.assertEqual(status, 409, error)
        self.assertEqual(error["code"], "SEAT_CONFLICT")
        self.assertEqual(redis_cli("GET", hold_key(TEST_SEATS[0])), "")

        _, abandoned = create_checkout(TEST_USERS[2], [TEST_SEATS[2]])
        status, value = request_json(
            f"/checkout-sessions/{abandoned['id']}/abandon",
            method="POST",
            user_id=TEST_USERS[2],
        )
        self.assertEqual(status, 200, value)
        self.assertEqual(redis_cli("GET", hold_key(TEST_SEATS[2])), "")

    def test_redis_outage_degrades_without_changing_postgres_correctness(self) -> None:
        compose("stop", "redis")
        try:
            status, checkout = create_checkout(TEST_USERS[0], [TEST_SEATS[0]])
            self.assertEqual(status, 201, checkout)
            status, updated = request_json(
                f"/checkout-sessions/{checkout['id']}/seats",
                method="PUT",
                user_id=TEST_USERS[0],
                body={"seatIds": [TEST_SEATS[1]], "expectedRevision": 0},
            )
            self.assertEqual(status, 200, updated)
            status, seats = request_json(f"/sessions/{SESSION_ID}/seats")
            self.assertEqual(status, 200, seats)
            self.assertEqual(confirm_checkout(checkout["id"], TEST_USERS[0])[0], 200)
        finally:
            start_redis()

    def test_redis_restart_loses_only_soft_state(self) -> None:
        _, checkout = create_checkout(TEST_USERS[0], [TEST_SEATS[0]])
        self.assertNotEqual(redis_cli("GET", hold_key(TEST_SEATS[0])), "")
        compose("kill", "redis")
        compose("rm", "-f", "redis")
        compose("up", "-d", "redis")
        start_redis()
        self.assertEqual(redis_cli("GET", hold_key(TEST_SEATS[0])), "")
        _, current = request_json(
            f"/checkout-sessions/{checkout['id']}", user_id=TEST_USERS[0]
        )
        self.assertEqual(current["status"], "SELECTING")
        self.assertEqual(current["seatIds"], [TEST_SEATS[0]])


if __name__ == "__main__":
    unittest.main(verbosity=2)
