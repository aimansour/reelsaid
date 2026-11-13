import json
import os
from pathlib import Path
import subprocess

from jsonschema import Draft7Validator
import pytest

from reelsaid.input import parse_input


def test_task_examples_use_explicit_valid_sources():
    tasks = json.loads(Path("store/tasks.json").read_text())
    schema = json.loads(Path(".actor/input_schema.json").read_text())
    schema["additionalProperties"] = False
    views = json.loads(Path(".actor/dataset_schema.json").read_text())["views"]
    assert 4 <= len(tasks) <= 10
    assert len({task["slug"] for task in tasks}) == len({task["title"] for task in tasks}) == len(tasks)
    assert len({task["description"] for task in tasks}) == len(tasks)
    readme = Path("README.md").read_text()
    for task in tasks:
        assert task["slug"].startswith("reelsaid-") and task["slug"].replace("-", "").isalnum()
        assert 3 <= len(task["title"]) <= 63 and 1 <= len(task["description"]) <= 400
        public = task["publicConfig"]
        assert 1 <= len(public["seoTitle"]) <= 60 and 1 <= len(public["seoDescription"]) <= 160
        assert public["datasetView"] in views
        assert public["inputSchemaFields"] and set(public["inputSchemaFields"]) <= task["input"].keys()
        assert 3 <= len(public["faq"]) <= 10
        for pair in public["faq"]:
            assert 1 <= len(pair["question"]) <= 120 and 1 <= len(pair["answer"]) <= 250
        Draft7Validator(schema).validate(task["input"])
        plan = parse_input(task["input"])
        assert plan.sources and not plan.outcomes and not task["input"].get("forceRefresh")
        assert f"https://apify.com/aimansour/reelsaid/examples/{task['slug']}" in readme


def test_task_sync_is_idempotent(tmp_path):
    definition = {
        "slug": "reelsaid-reel-subtitles", "title": "Make SRT subtitles for an Instagram Reel",
        "description": "Get timed subtitles for your public Reel.",
        "input": {"startUrls": ["https://www.instagram.com/reel/DS46KJNjva9/"]},
        "publicConfig": {"inputSchemaFields": ["startUrls"], "datasetView": "overview"},
    }
    manifest = tmp_path / "tasks.json"
    manifest.write_text(json.dumps([definition]))
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"tasks": [], "created": 0, "updated": 0}))
    cli = tmp_path / "apify"
    cli.write_text("""#!/usr/bin/env python3
import json
import os
from pathlib import Path
import sys

path = Path(os.environ["TASK_TEST_STATE"])
state = json.loads(path.read_text())
match sys.argv[1:4]:
    case ["api", "GET", "acts/aimansour~reelsaid"]:
        data = {"id": "actor", "isPublic": False, "userId": "owner"}
    case ["api", "GET", "actor-tasks"]:
        data = {"total": len(state["tasks"]), "items": state["tasks"]}
    case ["api", "POST", "actor-tasks"]:
        args = json.load(sys.stdin)
        assert args["actId"] == "actor" and not state["tasks"]
        data = {"id": "task-id", "userId": "owner", "isPublic": False, **args}
        state["tasks"].append(data)
        state["created"] += 1
    case ["api", "GET", "actor-tasks/task-id"]:
        data = state["tasks"][0]
    case ["api", "PUT", "actor-tasks/task-id"]:
        args = json.load(sys.stdin)
        assert args.get("isPublic") is not True
        data = state["tasks"][0] | args
        state["tasks"][0] = data
        state["updated"] += 1
    case _:
        sys.exit(2)
path.write_text(json.dumps(state))
print(json.dumps({"data": data}))
""")
    cli.chmod(0o700)
    env = {**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}", "TASK_TEST_STATE": str(state)}
    command = ["bash", "scripts/prepare-tasks.sh", str(manifest)]
    first = subprocess.check_output(command, env=env, text=True)
    repeated = subprocess.check_output(command, env=env, text=True)
    assert json.loads(first) == json.loads(repeated) == {"slug": definition["slug"], "id": "task-id"}
    result = json.loads(state.read_text())
    assert result["created"] == result["updated"] == 1
    assert result["tasks"][0]["input"] == definition["input"]
    assert result["tasks"][0]["publicConfig"] == definition["publicConfig"]
    result["tasks"][0].update(isPublic=True)
    result["tasks"][0]["publicConfig"]["publishedAt"] = "2026-11-10T00:00:00Z"
    state.write_text(json.dumps(result))
    assert subprocess.check_output(command, env=env, text=True) == first
    assert json.loads(state.read_text()) == result
