import json
from pathlib import Path

from reelsaid.input import parse_input


EXAMPLE = json.loads(Path("tests/fixtures/catalog.json").read_text())["shortSpoken"]["url"]


def test_empty_input_never_uses_prefill():
    empty = parse_input({})
    typo = parse_input({"startUrlz": [EXAMPLE]})

    assert not empty.sources and not typo.sources
    assert [outcome.error_code for outcome in empty.outcomes] == ["NO_SOURCE"]
    assert any(outcome.error_code == "UNKNOWN_INPUT" for outcome in typo.outcomes)


def test_mixed_sources_keep_valid_items():
    plan = parse_input({
        "startUrls": ["not a URL", EXAMPLE, "https://video.cdninstagram.com/audio.m4a?oh=abc"],
        "profiles": ["@astro_kjell", "https://www.instagram.com/nasa/reels/"],
        "shortcodes": ["DS46KJNjva9"],
        "datasetId": "someDatasetId",
        "datasetItems": [{"postUrl": EXAMPLE, "audioUrl": "https://video.cdninstagram.com/a.m4a"}],
    })

    assert [s.kind for s in plan.sources] == [
        "post", "cdn", "profile", "profile", "shortcode", "dataset", "dataset_item",
    ]
    assert plan.sources[1].value.endswith("?oh=abc")
    assert [s.value for s in plan.sources[2:4]] == ["astro_kjell", "nasa"]
    assert [error.error_code for error in plan.outcomes] == ["INVALID_URL"]


def test_language_auto_and_hint():
    assert parse_input({"startUrls": [EXAMPLE]}).options.transcript.language == "auto"
    assert parse_input({"startUrls": [EXAMPLE], "language": "ES"}).options.transcript.language == "es"
    assert parse_input({"startUrls": [EXAMPLE], "language": "yue"}).options.transcript.language == "yue"


def test_resume_without_new_source():
    plan = parse_input({"resumeFromDatasetId": "earlierRunDataset", "newReelsOnly": True})
    assert plan.options.resume_from_dataset_id == "earlierRunDataset"
    assert not plan.outcomes


def test_non_instagram_urls_are_rejected_before_resolution():
    plan = parse_input({"startUrls": [
        "https://instagram.com.evil.example/reel/DS46KJNjva9/",
        "https://user@instagram.com/reel/DS46KJNjva9/",
        "https://instagram.com:8888/reel/DS46KJNjva9/",
        "https://www.instagram.com/share/reel/AbCdEf1234/",
    ]})
    assert [s.kind for s in plan.sources] == ["post"]
    assert len(plan.outcomes) == 3


def test_prefill_is_an_explicit_source():
    properties = json.loads(Path(".actor/input_schema.json").read_text())["properties"]
    field = properties["startUrls"]
    assert "default" not in field
    assert field["prefill"] == [EXAMPLE]
    assert parse_input({"startUrls": field["prefill"]}).sources[0].value == EXAMPLE
