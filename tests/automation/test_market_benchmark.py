from pathlib import Path
import runpy
import unittest


benchmark = runpy.run_path(str(Path(__file__).resolve().parents[2] / "scripts/benchmark-market.py"))
usable = benchmark["usable"]
summary = runpy.run_path(str(Path(__file__).resolve().parents[2] / "scripts/summarize-performance.py"))


def observed(**changes):
    return {
        "surface": "native", "case": "matched-batch", "status": "SUCCEEDED", "cacheCondition": "fresh",
        "requestedVideoIds": ["a", "b"], "completedVideoIds": ["a", "b"], "quality": {"equivalent": True},
        "firstUsableSeconds": 3.0, "totalSeconds": 5.0, **changes,
    }


class MarketBenchmarkTest(unittest.TestCase):
    def test_error_text_does_not_count_as_transcription(self):
        self.assertFalse(usable({"status": "error", "transcript": "Content unavailable"}))
        self.assertFalse(usable({"errMsg": "Private", "text": "Content unavailable"}))
        self.assertTrue(usable({"status": "success", "transcript": "Actual speech."}))

    def test_fresh_comparison_rejects_cached_result(self):
        matches = summary["matched_timing"]
        self.assertTrue(matches(observed(), observed()))
        self.assertFalse(matches(observed(), observed(cacheCondition="cached-repeat")))
        self.assertFalse(matches(observed(), observed(cacheCondition="unknown")))

    def test_rejects_shorter_workload(self):
        matches = summary["matched_timing"]
        self.assertTrue(matches(observed(), observed(completedVideoIds=["b", "a"])))
        self.assertFalse(matches(observed(), observed(completedVideoIds=["a"])))
        self.assertFalse(matches(observed(), observed(completedVideoIds=["a", "a"])))
        self.assertFalse(matches(observed(), observed(quality={"equivalent": False})))
        self.assertFalse(matches(observed(completedVideoIds=["a"]), observed(completedVideoIds=["a"])))


if __name__ == "__main__":
    unittest.main()
