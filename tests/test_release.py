import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest


def test_deployment_stages_only_actor_files_and_approved_readme(tmp_path):
    package = tmp_path / "public"
    package.mkdir()
    (package / "README.md").write_text("# Approved GitHub title\n\n## Try it\n\nUse an explicit Reel link.\n")
    (package / "other.txt").write_text("Never part of the Actor source upload")
    commands = tmp_path / "bin"
    commands.mkdir()
    capture = tmp_path / "capture"
    cli = commands / "apify"
    cli.write_text("""#!/usr/bin/env bash
set -eu
case "$1 $2 $3" in
    'actors push --dir')
        shift 2
        cp -R -- "$2" "$CAPTURE"
        printf '%s\\n' "$@" > "$CAPTURE/arguments.txt"
        printf '%s\\n' '{"build":{"id":"build","status":"READY"}}' ;;
    'api GET actor-builds/build')
        printf '%s\\n' '{"data":{"id":"build","actId":"actor","status":"SUCCEEDED","buildNumber":"0.1.2"}}' ;;
    'api GET acts/actor')
        printf '%s\\n' '{"data":{"taggedBuilds":{"candidate":{"buildId":"build"}}}}' ;;
    *) exit 99 ;;
esac
""")
    cli.chmod(0o700)
    env = {**os.environ, "PATH": f"{commands}:{os.environ['PATH']}", "CAPTURE": str(capture)}
    subprocess.run(["bash", "scripts/deploy-actor.sh", str(package), "candidate"], env=env, check=True)
    assert (capture / ".actor/README.md").read_text() == "## Try it\n\nUse an explicit Reel link.\n"
    assert (capture / ".actor/input_schema.json").is_file()
    assert (capture / "Dockerfile").is_file() and (capture / "uv.lock").is_file()
    assert (capture / "src/reelsaid/__main__.py").is_file()
    assert all(path.suffix == ".py" for path in (capture / "src/reelsaid").iterdir())
    assert not (capture / ".git").exists() and not (capture / "docs").exists()
    assert not (capture / "other.txt").exists()
    arguments = (capture / "arguments.txt").read_text().splitlines()
    assert arguments[arguments.index("--build-tag") + 1] == "candidate"
    assert arguments[arguments.index("--wait-for-finish") + 1] == "0"
    assert "--no-apply-env-vars-to-build" in arguments
    actor = json.loads((capture / ".actor/actor.json").read_text())
    assert actor["name"] == "reelsaid"


def test_runtime_docker_context_keeps_source_last_and_excludes_private_artifacts():
    docker = Path("Dockerfile").read_text()
    assert docker.index("uv sync --locked") < docker.index("COPY src/")
    assert "RUN --mount=from=uv-tool,source=/uv,target=/usr/local/bin/uv" in docker
    assert docker.index("RUN bash ./scripts/install-quality-models") < docker.index("COPY src/")
    ignore = Path(".dockerignore").read_text().splitlines()
    assert ignore[0] == "**"
    assert set(ignore[1:]) == {
        "!Dockerfile", "!pyproject.toml", "!uv.lock", "!scripts/", "!scripts/install-quality-models",
        "!src/", "!src/reelsaid/", "!src/reelsaid/*.py",
    }


def publish_candidate(tmp_path, *, effective_paid_plan=True, drift=None):
    package = tmp_path / "public"
    (package / "store").mkdir(parents=True)
    (package / "store/listing.json").write_text('{"title":"ReelSaid"}\n')
    definition = {
        "slug": "reelsaid-example", "title": "Transcribe a Reel", "description": "Read the spoken text.",
        "input": {"startUrls": ["https://www.instagram.com/reel/DS46KJNjva9/"]},
        "publicConfig": {"inputSchemaFields": ["startUrls"], "datasetView": "overview"},
    }
    manifest = package / "store/tasks.json"
    manifest.write_text(json.dumps([definition]))
    subprocess.run(["git", "init", "-q", str(package)], check=True)
    subprocess.run(["git", "-C", str(package), "add", "."], check=True)
    subprocess.run([
        "git", "-C", str(package), "-c", "user.email=test@example.com", "-c", "user.name=Test",
        "commit", "-qm", "Approved package",
    ], check=True)
    source = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    package_revision = subprocess.check_output(["git", "-C", str(package), "rev-parse", "HEAD"], text=True).strip()
    paid_plan = {"pricingModel": "PAY_PER_EVENT", "startedAt": "2020-01-01T00:00:00.000Z"}
    plans = [paid_plan]
    if not effective_paid_plan:
        plans.append({"pricingModel": "FREE", "startedAt": "2020-02-01T00:00:00.000Z"})
    approved_digest = hashlib.sha256(
        (json.dumps(paid_plan, sort_keys=True, separators=(",", ":")) + "\n").encode()
    ).hexdigest()

    state = tmp_path / "actor.json"
    state.write_text(json.dumps({
        "id": "actor", "isPublic": False, "isSourceCodeHidden": True,
        "actorPermissionLevel": "LIMITED_PERMISSIONS", "defaultRunOptions": {"build": "latest"},
        "actorStandby": {"isEnabled": True, "build": "0.1.2"}, "pricingInfos": plans,
    }))
    openapi_file = Path(".actor/web_server_schema.json")
    openapi = json.loads(openapi_file.read_text())
    if drift == "deployed-openapi":
        openapi["info"]["title"] = "Changed title"
    (tmp_path / "openapi.json").write_text(json.dumps(openapi))
    task = {"id": "task", "actId": "actor", "name": definition["slug"], "isPublic": False,
            **{key: value for key, value in definition.items() if key != "slug"}}
    if drift == "saved-task":
        task["input"] = {}
    if drift == "saved-task-options":
        task["options"] = {"build": "latest"}
    (tmp_path / "task.json").write_text(json.dumps(task))
    receipt = {
        "source": source, "package": package_revision, "buildId": "build", "build": "0.1.2",
        "openApiSha256": hashlib.sha256(openapi_file.read_bytes()).hexdigest(),
        "taskManifestSha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
        "tasks": [{"slug": definition["slug"], "id": "task"}],
    }
    (tmp_path / "receipt.json").write_text(json.dumps(receipt))
    if drift == "task-manifest":
        manifest.write_text(json.dumps([{**definition, "description": "Changed task definition."}]))
    cli = tmp_path / "apify"
    cli.write_text("""#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

state = Path(os.environ["FIXTURE_ACTOR"])
actor = json.loads(state.read_text())
args = sys.argv[1:]
match args[:3]:
    case ["api", "GET", "acts/aimansour~reelsaid"]:
        result = {"data": actor}
    case ["api", "POST", "key-value-stores"]:
        result = {"data": {"id": "fixture"}}
    case ["api", "PUT", "key-value-stores/fixture"]:
        assert json.loads(args[4]) == {"generalAccess": "RESTRICTED"}
        state.with_suffix(".store-access").write_text("RESTRICTED")
        result = {"data": {"id": "fixture", "generalAccess": "RESTRICTED"}}
    case ["api", "GET", "key-value-stores/fixture/records/CANDIDATE"]:
        assert state.with_suffix(".store-access").read_text() == "RESTRICTED"
        result = json.loads(state.with_name("receipt.json").read_text())
    case ["api", "GET", "actor-tasks/task"]:
        result = {"data": json.loads(state.with_name("task.json").read_text())}
    case ["api", "GET", "key-value-stores/fixture/records/TASK-reelsaid-example"]:
        result = {"id": "task", "slug": "reelsaid-example", "build": "0.1.2", "verified": True}
    case ["api", "GET", "actor-builds/build"]:
        result = {"data": {"id": "build", "actId": "actor", "status": "SUCCEEDED", "buildNumber": "0.1.2",
                  "options": {"useCache": True}, "imageDigest": "a" * 64,
                  "actorDefinition": {"webServerSchema": json.loads(state.with_name("openapi.json").read_text())},
                  "inputSchema": json.dumps({"properties": {"startUrls": {"prefill": ["https://www.instagram.com/reel/DS46KJNjva9/"]}}})}}
    case ["api", "POST", "acts/aimansour~reelsaid/runs"]:
        result = {"data": {"status": "SUCCEEDED", "buildId": "build", "stats": {"durationMillis": 1000},
                  "defaultDatasetId": "fixture"}}
    case ["datasets", "get-items", "fixture"]:
        result = [{"status": "success", "language": "en", "transcript": "speech", "wordCount": 25,
                  "subtitles": {"srt": {}, "vtt": {}}}]
    case ["api", "PUT", "acts/aimansour~reelsaid"]:
        patch = json.load(sys.stdin)
        assert patch["isPublic"] is True and patch["defaultRunOptions"]["build"] == "0.1.2"
        state.write_text(json.dumps(actor | patch))
        with state.with_suffix(".writes").open("a") as log:
            print("promotion", file=log)
        sys.exit(1)
    case ["api", "GET", "acts/aimansour~reelsaid/builds/default"]:
        result = {"data": {"id": "build" if actor["defaultRunOptions"]["build"] == "0.1.2" else "stable",
                  "status": "SUCCEEDED"}}
    case _:
        sys.exit(2)
print(json.dumps(result))
""")
    cli.chmod(0o700)
    env = {
        **os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}", "PACKAGE_ROOT": str(package),
        "FIXTURE_ACTOR": str(state),
        "RELEASE_PRICING_SHA256": approved_digest,
    }
    result = subprocess.run(
        ["bash", "scripts/release-actor.sh", "publish", source, package_revision], env=env, capture_output=True,
    )
    return result, json.loads(state.read_text()), state.with_suffix(".writes")


@pytest.mark.parametrize("effective_paid_plan", [False, True])
def test_publish_requires_effective_approved_price_and_reconciles_lost_ack(tmp_path, effective_paid_plan):
    result, actor, writes = publish_candidate(tmp_path, effective_paid_plan=effective_paid_plan)
    if effective_paid_plan:
        assert result.returncode == 0, result.stderr
        assert actor["isPublic"] and actor["defaultRunOptions"]["build"] == "0.1.2"
        assert writes.read_text() == "promotion\n"
    else:
        assert result.returncode != 0
        assert not actor["isPublic"] and not writes.exists()


@pytest.mark.parametrize("drift", ["deployed-openapi", "task-manifest", "saved-task", "saved-task-options"])
def test_release_rejects_unverified_task_or_schema(tmp_path, drift):
    result, actor, writes = publish_candidate(tmp_path, drift=drift)
    assert result.returncode != 0 and not actor["isPublic"] and not writes.exists()
