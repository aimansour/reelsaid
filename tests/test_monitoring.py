import os
import shutil
import subprocess
from pathlib import Path

import pytest


RUN_URL = "https://github.com/aimansour/reelsaid/actions/runs/123"


@pytest.fixture
def monitor(tmp_path):
    if not (root := os.environ.get("PACKAGE_ROOT")):
        pytest.skip("Set PACKAGE_ROOT to the public workflow checkout")
    scripts = tmp_path / ".github/scripts"
    scripts.mkdir(parents=True)
    shutil.copyfile(Path(root) / ".github/scripts/monitor.sh", scripts / "monitor.sh")
    (scripts / "private-source.sh").write_text(
        'printf "private-checkout-canary\\n" >&2\nexit "$TEST_CHECKOUT"\n'
    )
    (scripts / "verify.sh").write_text(
        'touch runtime-started\nprintf "private-runtime-canary\\n" >&2\nexit "$TEST_RUNTIME"\n'
    )

    def run(checkout=0, runtime=0):
        env = {**os.environ, "SOURCE_REVISION": "a" * 40, "MONITOR_CASE": "normal",
               "GITHUB_SERVER_URL": "https://github.com", "GITHUB_REPOSITORY": "aimansour/reelsaid",
               "GITHUB_RUN_ID": "123", "TEST_CHECKOUT": str(checkout), "TEST_RUNTIME": str(runtime)}
        result = subprocess.run(["bash", str(scripts / "monitor.sh")], cwd=tmp_path, env=env,
                                capture_output=True, text=True, timeout=15)
        assert "canary" not in result.stdout + result.stderr
        return result, (tmp_path / "runtime-started").exists()

    return run


def test_failure_alert_before_runtime_starts(monitor):
    result, started = monitor(checkout=1)
    assert result.returncode != 0 and not started
    assert result.stdout.count("::error ") == 1
    assert "Source checkout failed" in result.stdout and RUN_URL in result.stdout


@pytest.mark.parametrize(("status", "stage"), [(1, "Runtime check failed"), (124, "Runtime check timed out")])
def test_runtime_failure_alert_preserves_failure(monitor, status, stage):
    result, started = monitor(runtime=status)
    assert result.returncode != 0 and started
    assert result.stdout.count("::error ") == 1
    assert stage in result.stdout and RUN_URL in result.stdout


def test_success_has_no_failure_annotation(monitor):
    result, started = monitor()
    assert result.returncode == 0 and started
    assert "::error " not in result.stdout
