from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parents[2]
REPORT = REPO_ROOT / "performance" / "experiments" / "phase10b-scale" / "report.md"


class Phase10BScaleReportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = REPORT.read_text(encoding="utf-8")

    def test_scale_dimensions_are_not_conflated(self):
        for heading in (
            "## Data Cardinality",
            "## Arrival Rate 与 Business Throughput",
            "## Contention Level",
        ):
            self.assertIn(heading, self.report)
        self.assertIn("100 万注册用户”不等于 100 万并发用户", self.report)

    def test_workloads_record_stable_unstable_generator_and_correctness(self):
        for column in (
            "Phase 10A stable",
            "B-2 highest tested stable",
            "first observed unstable",
            "generator limit",
            "correctness / primary signal",
        ):
            self.assertIn(column, self.report)
        self.assertIn("10,000 req/s", self.report)
        self.assertIn("60 req/s（5,000 seats，0%/90%）", self.report)

    def test_interrupted_observation_is_not_reported_as_passed(self):
        self.assertIn("30-minute local observation", self.report)
        self.assertIn("没有完成，也不算 endurance pass", self.report)
        self.assertIn("4,940 dropped iterations", self.report)
        self.assertIn("8 分 46 秒", self.report)
        self.assertNotIn("production endurance", self.report.lower())

    def test_database_correctness_and_inflight_failure_are_both_preserved(self):
        self.assertIn("数据库 14 项业务不变量全部通过", self.report)
        self.assertIn("1,000 个请求仍在途", self.report)
        self.assertIn("in-flight 回到 0", self.report)

    def test_report_does_not_claim_unimplemented_optimizations(self):
        self.assertIn("B-3 以后候选（未实施）", self.report)
        self.assertIn("不进入自动实施", self.report)
        self.assertNotIn("已实施 Seat Map cache", self.report)

    def test_external_comparisons_keep_scope_caveats(self):
        self.assertIn("pretix Scaling Guide", self.report)
        self.assertIn("Hi.Events", self.report)
        self.assertIn("aryahmph/concert-ticket", self.report)
        self.assertIn("Ticket-Blitz", self.report)
        self.assertIn("不是本项目目标", self.report)


if __name__ == "__main__":
    unittest.main()
