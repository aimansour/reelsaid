import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from jsonschema import validate


ROOT = Path(__file__).resolve().parents[1]
CLI_FIXTURE = """\
import asyncio
from dataclasses import replace
from pathlib import Path

from reelsaid import __main__ as actor
from test_actor import Case

case = Case()
run = actor.run

async def with_fixture(input_data, context):
    try:
        return await run(input_data, replace(context, instagram=case.instagram,
                                             inspect=case.inspect, evaluate=case.evaluate))
    finally:
        Path("asr-count").write_text(str(len(case.asr_calls)))

actor.run = with_fixture
asyncio.run(actor.main())
"""


def run_cli_fixture(tmp_path, input_data):
    apify = shutil.which("apify")
    if not apify:
        pytest.skip("Apify CLI is required for the runner integration tests")
    package = tmp_path / "fixture"
    package.mkdir()
    (package / "__init__.py").touch()
    (package / "__main__.py").write_text(CLI_FIXTURE)
    env = {name: value for name, value in os.environ.items()
           if not name.startswith(("APIFY_", "ACTOR_", "REELSAID_", "GROQ_"))}
    env.update(
        PATH=f"{Path(sys.executable).parent}:{env['PATH']}",
        PYTHONPATH=os.pathsep.join((str(ROOT / "src"), str(ROOT / "tests"))),
        APIFY_API_BASE_URL="http://127.0.0.1:1",
        APIFY_LOCAL_STORAGE_DIR=str(tmp_path / "storage"),
    )
    command = [apify, "run", "--entrypoint", "fixture", "--user-agent",
               "apify-agent-skills/apify-actor-development"]
    if input_data is not None:
        command.extend(["--input", json.dumps(input_data)])
    result = subprocess.run(command, cwd=tmp_path, env=env, stdin=subprocess.DEVNULL,
                            capture_output=True, text=True, timeout=40)
    assert result.returncode == 0, result.stdout + result.stderr
    folder = tmp_path / "storage/datasets/default"
    row, = [json.loads(item.read_text()) for item in folder.glob("[0-9]*.json")]
    schema = json.loads((ROOT / ".actor/dataset_schema.json").read_text())
    validate(row, schema["fields"])
    return row, int((tmp_path / "asr-count").read_text())


def test_local_apify_run_writes_default_dataset(tmp_path):
    row, asr_calls = run_cli_fixture(tmp_path, {"shortcodes": ["DS46KJNjva9"]})
    assert row["status"] == "success" and row["transcript"].strip()
    assert row["charged"] is False
    assert asr_calls == 1


@pytest.mark.parametrize(("input_data", "code"), [
    (None, "NO_SOURCE"),
    ({}, "NO_SOURCE"),
    ({"startUrl": "https://www.instagram.com/reel/DS46KJNjva9/"}, "UNKNOWN_INPUT"),
])
def test_local_invalid_input_is_free(tmp_path, input_data, code):
    row, asr_calls = run_cli_fixture(tmp_path, input_data)
    assert row["errorCode"] == code and row["charged"] is False
    assert asr_calls == 0
