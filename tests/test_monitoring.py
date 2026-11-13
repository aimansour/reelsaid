import os
import shutil
import subprocess
from pathlib import Path

import pytest


RUN_URL = "https://github.com/wip-bunker-42/reelsaid/actions/runs/123"


@pytest.fixture
def monitor(tmp_path):
    root = Path(__file__).resolve().parents[1]
    scripts = tmp_path / ".github/scripts"
    scripts.mkdir(parents=True)
    shutil.copyfile(Path(root) / ".github/scripts/monitor.sh", scripts / "monitor.sh")
    (scripts / "verify.sh").write_text(
        'printf "attempt\\n" >> runtime-attempts\n'
        'printf "private-runtime-canary\\n" >&2\n'
        'if [[ $(wc -l < runtime-attempts) == 1 ]]; then exit "$TEST_RUNTIME"; fi\n'
        'exit "$TEST_RETRY"\n'
    )

    def run(scenario="normal", runtime=0, retry=None):
        env = {**os.environ, "MONITOR_CASE": scenario,
               "GITHUB_SERVER_URL": "https://github.com", "GITHUB_REPOSITORY": "wip-bunker-42/reelsaid",
               "GITHUB_RUN_ID": "123", "TEST_RUNTIME": str(runtime),
               "TEST_RETRY": str(runtime if retry is None else retry)}
        result = subprocess.run(["bash", str(scripts / "monitor.sh")], cwd=tmp_path, env=env,
                                capture_output=True, text=True, timeout=15)
        assert "canary" not in result.stdout + result.stderr
        attempts = tmp_path / "runtime-attempts"
        return result, len(attempts.read_text().splitlines()) if attempts.exists() else 0

    return run


def test_failure_alert_before_runtime_starts(monitor):
    result, started = monitor(scenario="checkout-failure")
    assert result.returncode != 0 and not started
    assert result.stdout.count("::error ") == 1
    assert "Source checkout failed" in result.stdout and RUN_URL in result.stdout


@pytest.mark.parametrize(("status", "retry", "attempts", "stage"), [
    (1, None, 1, "Runtime check failed"),
    (124, 124, 2, "Runtime check timed out"),
    (137, 137, 2, "Runtime check timed out"),
    (124, 1, 2, "Runtime check failed"),
])
def test_runtime_failure_alert_preserves_failure(monitor, status, retry, attempts, stage):
    result, count = monitor(runtime=status, retry=retry)
    assert result.returncode != 0 and count == attempts
    assert result.stdout.count("::error ") == 1
    assert stage in result.stdout and RUN_URL in result.stdout


def test_success_has_no_failure_annotation(monitor):
    result, started = monitor()
    assert result.returncode == 0 and started
    assert "::error " not in result.stdout


def test_timed_out_check_can_recover_without_sending_failure_alert(monitor):
    result, attempts = monitor(runtime=124, retry=0)
    assert result.returncode == 0 and attempts == 2
    assert "::error " not in result.stdout
