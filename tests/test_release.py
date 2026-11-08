import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest


def test_deployment_stages_only_actor_files_and_approved_readme(tmp_path):
    package = tmp_path / "public"
    package.mkdir()
    (package / "README.md").write_text("# Approved Store README\n")
    (package / "other.txt").write_text("Never part of the Actor source upload")
    commands = tmp_path / "bin"
    commands.mkdir()
    capture = tmp_path / "capture"
    cli = commands / "apify"
    cli.write_text(
        '#!/usr/bin/env bash\nset -eu\n'
        'while [[ "$1" != --dir ]]; do shift; done\n'
        'cp -R -- "$2" "$CAPTURE"\n'
        'printf "%s\\n" "$@" > "$CAPTURE/arguments.txt"\n'
    )
    cli.chmod(0o700)
    env = {**os.environ, "PATH": f"{commands}:{os.environ['PATH']}", "CAPTURE": str(capture)}
    subprocess.run(["bash", "scripts/deploy-actor.sh", str(package), "candidate"], env=env, check=True)
    assert (capture / ".actor/README.md").read_bytes() == (package / "README.md").read_bytes()
    assert (capture / ".actor/input_schema.json").is_file()
    assert (capture / "Dockerfile").is_file() and (capture / "uv.lock").is_file()
    assert (capture / "src/reelsaid/__main__.py").is_file()
    assert all(path.suffix == ".py" for path in (capture / "src/reelsaid").iterdir())
    assert not (capture / ".git").exists() and not (capture / "docs").exists()
    assert not (capture / "other.txt").exists()
    arguments = (capture / "arguments.txt").read_text().splitlines()
    assert arguments[arguments.index("--build-tag") + 1] == "candidate"
    assert "--no-apply-env-vars-to-build" in arguments
    actor = json.loads((capture / ".actor/actor.json").read_text())
    assert actor["name"] == "reelsaid"


def test_runtime_docker_context_keeps_source_last_and_excludes_private_artifacts():
    docker = Path("Dockerfile").read_text()
    assert docker.index("RUN uv sync --locked") < docker.index("COPY src/")
    assert docker.index("RUN bash ./scripts/install-quality-models") < docker.index("COPY src/")
    ignore = Path(".dockerignore").read_text().splitlines()
    assert ignore[0] == "**"
    assert set(ignore[1:]) == {
        "!Dockerfile", "!pyproject.toml", "!uv.lock", "!scripts/", "!scripts/install-quality-models",
        "!src/", "!src/reelsaid/", "!src/reelsaid/*.py",
    }


@pytest.mark.parametrize("effective_paid_plan", [False, True])
def test_publish_requires_effective_approved_price_and_reconciles_lost_ack(tmp_path, effective_paid_plan):
    package = tmp_path / "public"
    (package / "store").mkdir(parents=True)
    (package / "store/listing.json").write_text('{"title":"ReelSaid"}\n')
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
        "pricingInfos": plans,
    }))
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
    case ["api", "GET", "key-value-stores/fixture/records/CANDIDATE"]:
        result = {"source": os.environ["FIXTURE_SOURCE"], "package": os.environ["FIXTURE_PACKAGE"], "buildId": "build"}
    case ["api", "GET", "actor-builds/build"]:
        result = {"data": {"id": "build", "actId": "actor", "status": "SUCCEEDED", "buildNumber": "0.1.2",
                  "options": {"useCache": True}, "imageDigest": "a" * 64,
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
        "FIXTURE_ACTOR": str(state), "FIXTURE_SOURCE": source, "FIXTURE_PACKAGE": package_revision,
        "RELEASE_PRICING_SHA256": approved_digest,
    }
    result = subprocess.run(
        ["bash", "scripts/release-actor.sh", "publish", source, package_revision], env=env, capture_output=True,
    )
    actor = json.loads(state.read_text())
    if effective_paid_plan:
        assert result.returncode == 0, result.stderr
        assert actor["isPublic"] and actor["defaultRunOptions"]["build"] == "0.1.2"
        assert state.with_suffix(".writes").read_text() == "promotion\n"
    else:
        assert result.returncode != 0
        assert not actor["isPublic"] and not state.with_suffix(".writes").exists()
