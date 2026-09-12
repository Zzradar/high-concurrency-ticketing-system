from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


class SeatSplitSourceContractTest(unittest.TestCase):
    def test_routes_and_minimal_dtos_are_distinct(self) -> None:
        controller = read("src/controllers/SeatController.h")
        dto = read("src/dto/TicketDtos.h")
        self.assertIn('"/sessions/{sessionId}/seat-layout"', controller)
        self.assertIn('"/sessions/{sessionId}/seat-availability"', controller)

        layout = dto.split("struct SeatLayout", 1)[1].split("struct SeatAvailability", 1)[0]
        availability = dto.split("struct SeatAvailability", 1)[1].split("struct Reservation", 1)[0]
        for field in ('value["id"]', 'value["label"]', 'value["row"]',
                      'value["number"]', 'value["zone"]', 'value["price"]'):
            self.assertIn(field, layout)
        self.assertNotIn('value["status"]', layout)
        self.assertNotIn('value["sessionId"]', layout)
        self.assertEqual(set(re.findall(r'value\["([^"]+)"\]', availability)),
                         {"id", "status"})

    def test_availability_query_is_minimal_and_does_not_join_seats(self) -> None:
        repository = read("src/repositories/SeatRepository.cpp")
        availability = repository.split(
            "void SeatRepository::listAvailabilityBySessionId", 1
        )[1].split("void SeatRepository::sessionExists", 1)[0]
        compact = " ".join(availability.split())
        self.assertIn("SELECT id, status FROM session_seats", compact)
        self.assertIn("WHERE session_id = $1", compact)
        self.assertIn("ORDER BY id ASC", compact)
        self.assertNotRegex(availability, r"\bJOIN\b")
        self.assertNotIn("seat_label", availability)

    def test_layout_query_omits_dynamic_status(self) -> None:
        repository = read("src/repositories/SeatRepository.cpp")
        layout = repository.split(
            "void SeatRepository::listLayoutBySessionId", 1
        )[1].split("void SeatRepository::listAvailabilityBySessionId", 1)[0]
        select_list = layout.split("SELECT inventory.id", 1)[1].split("FROM session_seats", 1)[0]
        select_list = "inventory.id" + select_list
        self.assertIn("r.revision layout_revision", layout)
        self.assertIn("LEFT JOIN LATERAL", layout)
        self.assertNotIn("status", select_list)
        for field in ("inventory.id", "seat.seat_label", "seat.row_no",
                      "seat.seat_no", "zone.name AS zone", "inventory.price"):
            self.assertIn(field, select_list)
        self.assertIn("JOIN seats", layout)
        self.assertIn("JOIN venue_zones", layout)
        self.assertIn("ORDER BY layout_rows.sort_order,layout_rows.row_no,layout_rows.seat_no,layout_rows.id", layout)

    def test_shared_overlay_and_capacity_guard_are_reused(self) -> None:
        service = read("src/services/SeatService.cpp")
        overlay = read("src/services/SeatDisplayStatus.cpp")
        self.assertGreaterEqual(service.count("displaySeatStatus("), 2)
        self.assertGreaterEqual(service.count("executor->trySubmit("), 3)
        self.assertIn('formalStatus != "AVAILABLE"', overlay)
        self.assertIn('return "HELD"', overlay)

    def test_low_cardinality_split_stages_are_registered(self) -> None:
        metrics = read("src/observability/PerformanceMetrics.cpp")
        for stage in (
            "layout_db_fetch_and_materialize", "layout_json_build",
            "availability_db_fetch_and_materialize", "availability_redis_lookup",
            "availability_overlay", "availability_json_build",
        ):
            self.assertIn(f'"{stage}"', metrics)
        for route in ("seat-layout", "seat-availability"):
            self.assertIn(route, metrics)


if __name__ == "__main__":
    unittest.main(verbosity=2)
