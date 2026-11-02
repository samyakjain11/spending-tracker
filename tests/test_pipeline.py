"""Tests use made-up data only."""
import shutil
import tempfile
import unittest
from pathlib import Path

from spending.analyze import load, summarize
from spending.report import build

FIX = Path(__file__).parent / "fixtures"
EXAMPLE_RULES = Path(__file__).parent.parent / "examples" / "personal-rules.example.toml"


class PipelineTest(unittest.TestCase):
    def setUp(self):
        self.ds = load([FIX / "apple_sample.csv"], EXAMPLE_RULES)
        self.s = summarize(self.ds)

    def test_payments_are_skipped(self):
        pay = [t for t in self.ds.txns if t.source_type == "Payment"]
        self.assertTrue(pay and all(t.kind == "skip" for t in pay))

    def test_categories_and_one_offs(self):
        jan = self.s["months"]["2026-01"]
        self.assertEqual(jan["one_offs"], {"Flights": 400.0})
        self.assertEqual(jan["everyday"], {"Restaurants and bars": 60.0})  # return dropped
        feb = self.s["months"]["2026-02"]
        self.assertEqual(feb["everyday"], {"Fast food": 25.0})
        self.assertEqual(feb["counts"], {"Fast food": 2})

    def test_same_file_twice_is_not_double_counted(self):
        with tempfile.TemporaryDirectory() as d:
            for name in ("a.csv", "b.csv"):
                shutil.copy(FIX / "apple_sample.csv", Path(d) / name)
            s = summarize(load([Path(d)], EXAMPLE_RULES))
        self.assertEqual(s["months"]["2026-02"]["everyday"], {"Fast food": 25.0})

    def test_completeness(self):
        # Example settings expect four accounts; only Apple is present.
        self.assertFalse(self.s["months"]["2026-01"]["complete"])
        self.assertIn("chase", self.s["months"]["2026-01"]["missing_accounts"])

    def test_report_renders(self):
        html = build(self.s, "2026-02")
        self.assertIn("<title>Spending, February 2026</title>", html)
        self.assertIn("Partial month", html)


if __name__ == "__main__":
    unittest.main()
