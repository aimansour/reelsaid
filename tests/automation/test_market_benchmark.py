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

    def test_provider_specific_fields_keep_the_same_video_identity(self):
        row = {"status": "success", "normalizedUrl": "https://www.instagram.com/reel/Ddi3q68I1BQ/",
               "transcript": {"text": "Actual speech."}}
        self.assertTrue(usable(row))
        self.assertEqual(benchmark["completed_ids"]([row]), ["Ddi3q68I1BQ"])
        self.assertTrue(usable({"spokenTranscript": "Actual speech."}))

    def test_unverified_partial_is_not_first_usable_text(self):
        row = {"status": "partial", "transcript": "Possible speech."}
        self.assertFalse(usable({**row, "quality": {"affectedFraction": None}}))
        self.assertFalse(usable({**row, "quality": {"affectedFraction": 0.21}}))
        self.assertTrue(usable({**row, "quality": {"affectedFraction": 0.20}}))

    def test_fresh_comparison_rejects_cached_result(self):
        matches = summary["matched_timing"]
        self.assertTrue(matches(observed(), observed()))
        self.assertFalse(matches(observed(), observed(cacheCondition="cached-repeat")))
        self.assertFalse(matches(observed(), observed(cacheCondition="unknown")))

    def test_release_comparison_pins_both_surfaces_to_the_private_candidate(self):
        resolve = benchmark["release_candidate_build"]
        actor = {"isPublic": False, "taggedBuilds": {"launch-standby": {"buildNumber": "0.1.30"}},
                 "actorStandby": {"isEnabled": True, "build": "0.1.30"}}
        self.assertEqual(resolve(actor), "0.1.30")
        with self.assertRaises(RuntimeError):
            resolve({**actor, "isPublic": True})
        with self.assertRaises(RuntimeError):
            resolve({**actor, "actorStandby": {"isEnabled": True, "build": "latest"}})

    def test_delivery_receipt_identifies_reused_transcript_without_cached_flag(self):
        cached = benchmark["is_cached_result"]
        self.assertTrue(cached({"cached": True}))
        self.assertTrue(cached({"status": "transcribed", "charged": False,
                                "statusReason": "Already delivered to your account on 2026-11-07: handed back."}))
        self.assertFalse(cached({"status": "transcribed", "charged": False}))
        self.assertFalse(cached({"status": "no_speech", "charged": False}))

    def test_rejects_shorter_workload(self):
        matches = summary["matched_timing"]
        self.assertTrue(matches(observed(), observed(completedVideoIds=["b", "a"])))
        self.assertFalse(matches(observed(), observed(completedVideoIds=["a"])))
        self.assertFalse(matches(observed(), observed(completedVideoIds=["a", "a"])))
        self.assertFalse(matches(observed(), observed(quality={"equivalent": False})))
        self.assertFalse(matches(observed(completedVideoIds=["a"]), observed(completedVideoIds=["a"])))

    def test_caption_coverage_distinguishes_truncated_transcript(self):
        grade = summary["caption_grade"]
        row = {"transcript": "Here are the best sellers. Good luck.",
               "segments": [{"start": 0.1, "end": 9.8}]}
        fixture = {"captionAnchors": ["here are", "bestsellers", "good luck"],
                   "durationSeconds": 10, "firstSpeechBy": 1, "lastSpeechAtLeast": 9}
        self.assertTrue(grade(row, fixture)["equivalent"])
        self.assertFalse(grade({**row, "transcript": "Here are the best sellers."}, fixture)["equivalent"])
        self.assertFalse(grade({**row, "segments": [{"start": 0.1, "end": 7.8}]}, fixture)["equivalent"])


if __name__ == "__main__":
    unittest.main()
