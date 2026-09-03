from pathlib import Path
import re
import unittest


BACKEND_ROOT = Path(__file__).resolve().parents[1]


def read(relative_path: str) -> str:
    return (BACKEND_ROOT / relative_path).read_text(encoding="utf-8")


class ReadApiSourceContractTest(unittest.TestCase):
    def test_public_catalog_read_routes_are_registered(self) -> None:
        controllers = "\n".join(
            read(path)
            for path in (
                "src/controllers/EventController.h",
                "src/controllers/SessionController.h",
                "src/controllers/SeatController.h",
            )
        )
        for route in (
            '"/events"',
            '"/events/{eventId}"',
            '"/events/{eventId}/sessions"',
            '"/sessions/{sessionId}"',
            '"/sessions/{sessionId}/seats"',
        ):
            self.assertIn(route, controllers)
        self.assertEqual(controllers.count("drogon::Get"), 5)
        self.assertNotRegex(controllers, r"drogon::Post|drogon::Put|drogon::Delete")

    def test_path_ids_are_handler_arguments(self) -> None:
        sources = "\n".join(
            read(path)
            for path in (
                "src/controllers/EventController.h",
                "src/controllers/EventController.cpp",
                "src/controllers/SessionController.h",
                "src/controllers/SessionController.cpp",
                "src/controllers/SeatController.h",
                "src/controllers/SeatController.cpp",
            )
        )
        self.assertNotIn('getParameter("eventId")', sources)
        self.assertNotIn('getParameter("sessionId")', sources)
        self.assertGreaterEqual(len(re.findall(r"std::string eventId", sources)), 4)
        self.assertGreaterEqual(len(re.findall(r"std::string sessionId", sources)), 2)

    def test_repositories_are_read_only_and_use_bound_parameters(self) -> None:
        repositories = "\n".join(
            read(path)
            for path in (
                "src/repositories/EventRepository.cpp",
                "src/repositories/SessionRepository.cpp",
                "src/repositories/SeatRepository.cpp",
            )
        )
        self.assertNotRegex(repositories, r"\b(?:INSERT|UPDATE|DELETE)\b")
        self.assertGreaterEqual(repositories.count("execSqlAsync("), 6)
        self.assertGreaterEqual(repositories.count("$1"), 5)
        self.assertIn("COUNT(session.id)", repositories)
        self.assertIn("MIN(inventory.price)", repositories)
        self.assertIn("Asia/Shanghai", repositories)
        self.assertIn("inventory.id", repositories)
        self.assertIn("seat.row_no ASC", repositories)

    def test_service_owns_effective_inventory_display_rules(self) -> None:
        service = read("src/services/SessionService.cpp")
        self.assertIn('row.databaseStatus == "SOLD_OUT"', service)
        self.assertIn("row.totalCount == 0", service)
        self.assertIn("row.availableCount == 0", service)
        self.assertIn("row.availableCount * 100 <= row.totalCount * 20", service)
        for value in ("SOLD_OUT", "ON_SALE", "售罄", "紧张", "充足"):
            self.assertIn(value, service)


if __name__ == "__main__":
    unittest.main()
