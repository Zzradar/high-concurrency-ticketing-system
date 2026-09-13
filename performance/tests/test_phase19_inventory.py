import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("phase19_inventory", ROOT / "performance/scripts/phase19_inventory.py")
inventory = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inventory)


class InventoryTests(unittest.TestCase):
    def test_reproduces_committed_inventory_from_baseline_objects(self):
        expected = json.loads((inventory.OUT / "inventory.json").read_text(encoding="utf-8"))
        self.assertEqual(inventory.inventory(), expected)
        self.assertEqual(inventory.markdown(expected), (inventory.OUT / "POLLING_INVENTORY.md").read_text(encoding="utf-8"))

    def test_known_network_risks_and_display_only_timers_are_not_conflated(self):
        data = inventory.inventory()
        rows = {r["id"]: r for r in data["pollers"]}
        self.assertEqual(len(rows), 8)
        self.assertFalse(rows["notifications"]["serial"])
        self.assertTrue(rows["refund"]["hiddenPause"])
        self.assertFalse(rows["payment"]["hiddenPause"])
        self.assertFalse(rows["submitting"]["hiddenPause"])
        self.assertEqual(rows["order-countdown"]["endpoints"], [])
        self.assertEqual(len(rows["sales-boundary"]["endpoints"]), 1)
        self.assertFalse(data["phase18BrowserScope"]["provesGlobalPolling"])

    def test_reviewed_anchors_exist_in_frozen_source(self):
        app = inventory.source("frontend/src/App.vue").decode()
        order = inventory.source("frontend/src/pages/OrderPage.vue").decode()
        seat = inventory.source("frontend/src/pages/SeatSelectionPage.vue").decode()
        sales = inventory.source("frontend/src/utils/salesWindow.ts").decode()
        self.assertIn("setInterval(() => void refreshNotifications(), 5000)", app)
        self.assertIn("setTimeout(() => void refreshOrder(true), 2000)", order)
        self.assertIn("setTimeout(poll, 1000)", order)
        self.assertIn("setTimeout(poll, 2000)", seat)
        self.assertIn("!visited.has(key)", sales)
        self.assertIn("void refresh().catch", sales)


if __name__ == "__main__":
    unittest.main()
