from pathlib import Path
import runpy
import unittest


benchmark = runpy.run_path(str(Path(__file__).resolve().parents[2] / "scripts/benchmark-market.py"))
usable = benchmark["usable"]


class MarketBenchmarkTest(unittest.TestCase):
    def test_error_text_does_not_count_as_transcription(self):
        self.assertFalse(usable({"status": "error", "transcript": "Content unavailable"}))
        self.assertFalse(usable({"errMsg": "Private", "text": "Content unavailable"}))
        self.assertTrue(usable({"status": "success", "transcript": "Actual speech."}))


if __name__ == "__main__":
    unittest.main()
