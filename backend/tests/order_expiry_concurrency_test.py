from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import subprocess
import unittest

from order_expiry_integration_test import (
    BACKEND_ROOT,
    PREFIX,
    TEST_SEATS,
    cleanup_test_data,
    create_order,
    make_expired,
    psql,
    wait_for_order_status,
)


PEER_CONTAINER = "ticketing-phase4-expiry-peer"
COMPOSE_NETWORK = "backend_default"


def docker(args: list[str], *, check: bool = True) -> subprocess.CompletedProcess:
    completed = subprocess.run(
        ["docker", *args],
        cwd=Path(BACKEND_ROOT),
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if check and completed.returncode != 0:
        raise AssertionError(
            f"docker {' '.join(args)} failed ({completed.returncode}): "
            f"{completed.stderr}"
        )
    return completed


def remove_peer() -> None:
    docker(["rm", "-f", PEER_CONTAINER], check=False)


class OrderExpiryConcurrencyTest(unittest.TestCase):
    def setUp(self) -> None:
        remove_peer()
        docker(["compose", "up", "-d", "--wait", "backend"])
        cleanup_test_data()

    def tearDown(self) -> None:
        remove_peer()
        docker(["compose", "up", "-d", "--wait", "backend"])
        cleanup_test_data()

    def test_two_workers_expire_one_order_once(self) -> None:
        order_id, reservation_id = create_order(
            PREFIX + "two-workers", [TEST_SEATS[0]]
        )
        docker(["compose", "stop", "backend"])
        make_expired(order_id, reservation_id)

        commands = (
            ["compose", "up", "-d", "--force-recreate", "backend"],
            [
                "run",
                "-d",
                "--name",
                PEER_CONTAINER,
                "--network",
                COMPOSE_NETWORK,
                "backend-backend:latest",
            ],
        )
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(docker, commands))
        self.assertEqual([result.returncode for result in results], [0, 0])

        wait_for_order_status(order_id, "EXPIRED", timeout=20)
        docker(["compose", "up", "-d", "--wait", "backend"])

        state = psql(
            f"""
            SELECT ticket_order.status,
                   reservation.status,
                   inventory.status,
                   inventory.current_reservation_id IS NULL,
                   COUNT(item.session_seat_id),
                   SUM(item.reserved_price)
            FROM orders AS ticket_order
            JOIN reservations AS reservation
              ON reservation.id = ticket_order.reservation_id
            JOIN reservation_session_seats AS item
              ON item.reservation_id = reservation.id
            JOIN session_seats AS inventory
              ON inventory.id = item.session_seat_id
            WHERE ticket_order.id = '{order_id}'
            GROUP BY ticket_order.status,
                     reservation.status,
                     inventory.status,
                     inventory.current_reservation_id;
            """
        )
        self.assertEqual(
            state.split("\t"),
            ["EXPIRED", "EXPIRED", "AVAILABLE", "t", "1", "128000"],
        )

        docker(["compose", "stop", "backend"])
        docker(["stop", "-t", "3", PEER_CONTAINER])
        primary_result = docker(
            ["compose", "logs", "--no-color", "backend"]
        )
        peer_result = docker(["logs", PEER_CONTAINER])
        primary_logs = primary_result.stdout + primary_result.stderr
        peer_logs = peer_result.stdout + peer_result.stderr
        success_count = (primary_logs + peer_logs).count(
            "expired=1, skipped=0"
        )
        self.assertEqual(success_count, 1, primary_logs + peer_logs)


if __name__ == "__main__":
    unittest.main(verbosity=2)
