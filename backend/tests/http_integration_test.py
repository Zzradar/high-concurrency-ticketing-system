import json
import os
import unittest
from urllib.error import HTTPError
from urllib.request import urlopen


BASE_URL = os.environ.get("TICKETING_BASE_URL", "http://127.0.0.1:8080")


def request_json(path: str, expected_status: int = 200):
    try:
        with urlopen(BASE_URL + path, timeout=5) as response:
            status = response.status
            payload = json.load(response)
    except HTTPError as error:
        status = error.code
        payload = json.load(error)
    except Exception as error:
        raise AssertionError(
            f"Backend is required at {BASE_URL}; request to {path} failed: {error}"
        ) from error

    if status != expected_status:
        raise AssertionError(
            f"{path} returned HTTP {status}, expected {expected_status}: {payload}"
        )
    return payload


class ReadApiHttpIntegrationTest(unittest.TestCase):
    event_fields = {
        "id",
        "name",
        "description",
        "city",
        "venue",
        "dateRange",
        "status",
        "cover",
        "sessionCount",
        "category",
    }
    session_fields = {
        "id",
        "eventId",
        "date",
        "time",
        "weekday",
        "venue",
        "gateTime",
        "status",
        "priceFrom",
        "availability",
    }
    seat_fields = {
        "id",
        "sessionId",
        "label",
        "row",
        "number",
        "status",
        "zone",
        "price",
    }

    def test_health_uses_the_database(self) -> None:
        self.assertEqual(request_json("/health"), {"database": "up", "status": "ok"})

    def test_events_and_event_detail(self) -> None:
        events = request_json("/events")
        self.assertEqual([event["id"] for event in events], [
            "evt-concert-2026",
            "evt-basketball-finals",
        ])
        self.assertEqual([event["sessionCount"] for event in events], [3, 2])
        for event in events:
            self.assertEqual(set(event), self.event_fields)
            self.assertEqual(event["city"], "上海")
            self.assertTrue(event["cover"].startswith("/images/"))

        detail = request_json("/events/evt-concert-2026")
        self.assertEqual(detail, events[0])
        self.assertEqual(
            request_json("/events/not-present", 404),
            {"code": "EVENT_NOT_FOUND", "message": "Event not found"},
        )

    def test_sessions_are_aggregated_and_formatted(self) -> None:
        cases = {
            "evt-concert-2026": (3, 58000, ["10月01日", "10月02日", "10月03日"]),
            "evt-basketball-finals": (2, 38000, ["11月08日", "11月09日"]),
        }
        all_sessions = []
        for event_id, (count, price_from, dates) in cases.items():
            sessions = request_json(f"/events/{event_id}/sessions")
            self.assertEqual(len(sessions), count)
            self.assertEqual([session["date"] for session in sessions], dates)
            for session in sessions:
                self.assertEqual(set(session), self.session_fields)
                self.assertEqual(session["eventId"], event_id)
                self.assertEqual(session["priceFrom"], price_from)
                self.assertEqual(session["status"], "ON_SALE")
                self.assertEqual(session["availability"], "充足")
                self.assertRegex(session["time"], r"^\d{2}:\d{2}$")
                self.assertRegex(session["gateTime"], r"^\d{2}:\d{2}$")
                self.assertIn(session["weekday"], {
                    "周一", "周二", "周三", "周四", "周五", "周六", "周日"
                })
            all_sessions.extend(sessions)

        self.assertEqual(
            request_json("/events/not-present/sessions", 404),
            {"code": "EVENT_NOT_FOUND", "message": "Event not found"},
        )
        self.__class__.all_sessions = all_sessions

    def test_every_seed_session_has_ordered_inventory(self) -> None:
        session_ids = [
            "ses-concert-1001",
            "ses-concert-1002",
            "ses-concert-1003",
            "ses-basketball-2001",
            "ses-basketball-2002",
        ]
        expected_labels = [
            f"{row}{number:02d}"
            for row in "ABCDEF"
            for number in range(1, 11)
        ]
        for session_id in session_ids:
            seats = request_json(f"/sessions/{session_id}/seats")
            self.assertEqual(len(seats), 60)
            self.assertEqual([seat["label"] for seat in seats], expected_labels)
            self.assertEqual(
                {status: sum(seat["status"] == status for seat in seats)
                 for status in ("AVAILABLE", "HELD", "SOLD")},
                {"AVAILABLE": 51, "HELD": 4, "SOLD": 5},
            )
            for seat in seats:
                self.assertEqual(set(seat), self.seat_fields)
                self.assertEqual(seat["sessionId"], session_id)
                self.assertEqual(seat["id"], f"{session_id}-{seat['label']}")
                self.assertEqual(seat["number"], int(seat["label"][1:]))
                self.assertIsInstance(seat["price"], int)

        self.assertEqual(
            request_json("/sessions/not-present/seats", 404),
            {"code": "SESSION_NOT_FOUND", "message": "Session not found"},
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
