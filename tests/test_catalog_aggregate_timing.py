"""Timing tests for catalog_aggregate() from kumonjo.discovery.catalog."""

import time
import unittest

from kumonjo.discovery.catalog import catalog_aggregate


# Max seconds per call; fail if slower (avoids hanging on regressions)
MAX_SECONDS_PER_CALL = 15.0


class TestCatalogAggregateTiming(unittest.TestCase):
    """Measure how long catalog_aggregate() takes for a few example cases."""

    def _timed_aggregate(self, **kwargs) -> tuple[dict, float]:
        """Run catalog_aggregate(**kwargs) and return (result, elapsed_seconds)."""
        start = time.perf_counter()
        result = catalog_aggregate(**kwargs)
        elapsed = time.perf_counter() - start
        return result, elapsed

    def test_aggregate_by_statsField(self) -> None:
        """Time aggregation by statsField (no year/filter)."""
        result, elapsed = self._timed_aggregate(by="statsField", limit=20)
        print(f"  catalog_aggregate(by='statsField', limit=20): {elapsed:.3f}s")
        self.assertLess(elapsed, MAX_SECONDS_PER_CALL, f"by=statsField took {elapsed:.3f}s")
        self.assertIn("groups", result)
        self.assertIn("by", result)
        self.assertEqual(result["by"], "statsField")
        if result["groups"]:
            self.assertIn("value", result["groups"][0])
            self.assertIn("dataset_count", result["groups"][0])

    def test_aggregate_by_surveyYears(self) -> None:
        """Time aggregation by surveyYears."""
        result, elapsed = self._timed_aggregate(by="surveyYears", limit=30)
        print(f"  catalog_aggregate(by='surveyYears', limit=30): {elapsed:.3f}s")
        self.assertLess(elapsed, MAX_SECONDS_PER_CALL, f"by=surveyYears took {elapsed:.3f}s")
        self.assertIn("groups", result)
        self.assertEqual(result["by"], "surveyYears")

    def test_aggregate_by_gov_org_code_with_year(self) -> None:
        """Time aggregation by gov_org_code restricted to a single year."""
        result, elapsed = self._timed_aggregate(
            by="gov_org_code",
            year="2024",
            limit=20,
        )
        print(f"  catalog_aggregate(by='gov_org_code', year='2024', limit=20): {elapsed:.3f}s")
        self.assertLess(elapsed, MAX_SECONDS_PER_CALL, f"by=gov_org_code year=2024 took {elapsed:.3f}s")
        self.assertIn("groups", result)
        self.assertEqual(result["by"], "gov_org_code")
        self.assertEqual(result["year"], "2024")

    def test_aggregate_by_sub_category_name_with_filter(self) -> None:
        """Time aggregation by sub_category_name with filter_column/filter_value."""
        result, elapsed = self._timed_aggregate(
            by="sub_category_name",
            filter_column="statsField",
            filter_value="02",  # 人口・世帯
            limit=15,
        )
        print(
            f"  catalog_aggregate(by='sub_category_name', filter_column='statsField', filter_value='02', limit=15): {elapsed:.3f}s"
        )
        self.assertLess(
            elapsed,
            MAX_SECONDS_PER_CALL,
            f"by=sub_category_name with filter took {elapsed:.3f}s",
        )
        self.assertIn("groups", result)
        self.assertEqual(result["by"], "sub_category_name")
        self.assertEqual(result.get("filter_column"), "statsField")
        self.assertEqual(result.get("filter_value"), "02")

    def test_aggregate_invalid_by_returns_quickly(self) -> None:
        """Invalid 'by' should return quickly (no parquet read)."""
        result, elapsed = self._timed_aggregate(by="invalid_column")
        print(f"  catalog_aggregate(by='invalid_column'): {elapsed:.3f}s")
        self.assertLess(elapsed, 1.0, f"Invalid by should return in <1s, got {elapsed:.3f}s")
        self.assertEqual(result["groups"], [])
        self.assertIn("by は次のいずれかにしてください", result.get("message", ""))

    def test_catalog_aggregate_timing_report(self) -> None:
        """Run a few example cases and assert each completes within max time; report timings."""
        cases = [
            {"by": "statsField", "limit": 20},
            {"by": "surveyYears", "limit": 30},
            {"by": "gov_org_code", "year": "2024", "limit": 20},
            {
                "by": "sub_category_name",
                "filter_column": "statsField",
                "filter_value": "02",
                "limit": 15,
            },
        ]
        for i, kwargs in enumerate(cases):
            with self.subTest(case=i, **kwargs):
                result, elapsed = self._timed_aggregate(**kwargs)
                self.assertLess(
                    elapsed,
                    MAX_SECONDS_PER_CALL,
                    f"catalog_aggregate({kwargs}) took {elapsed:.3f}s",
                )
                self.assertIn("groups", result)
                print(f"  catalog_aggregate({kwargs}): time={elapsed:.3f}s, groups={len(result['groups'])}")
                if result["groups"]:
                    total = sum(g["dataset_count"] for g in result["groups"])
                    print(f"    total datasets: {total}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
