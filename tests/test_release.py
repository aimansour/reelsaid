import json
import os
import subprocess
from pathlib import Path


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
