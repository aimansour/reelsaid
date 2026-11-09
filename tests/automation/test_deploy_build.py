import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]


class DeploymentTest(unittest.TestCase):
    def deploy(self, status):
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / "apify"
            executable.write_text("""#!/usr/bin/env bash
case "$1 $2 $3" in
    'actors push --dir')
        printf '%s\\n' '{"build":{"id":"candidate","status":"READY"}}' ;;
    'api GET actor-builds/candidate')
        printf '{"data":{"id":"candidate","actId":"actor","status":"%s","buildNumber":"0.1.20"}}\\n' "$TEST_BUILD_STATUS" ;;
    'api GET acts/actor')
        printf '%s\\n' '{"data":{"taggedBuilds":{"private-check":{"buildId":"candidate"}}}}' ;;
    *) exit 99 ;;
esac
""")
            executable.chmod(0o755)
            return subprocess.run(
                ["bash", "scripts/deploy-actor.sh", "", "private-check"], cwd=ROOT, capture_output=True, text=True,
                env={**os.environ, "PATH": directory + os.pathsep + os.environ["PATH"], "TEST_BUILD_STATUS": status},
                timeout=10,
            )

    def test_queued_build_is_confirmed_by_id_and_tag(self):
        result = self.deploy("SUCCEEDED")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["build"]["status"], "SUCCEEDED")
        self.assertEqual(json.loads(result.stdout)["build"]["number"], "0.1.20")

    def test_failed_build_does_not_emit_a_success_receipt(self):
        result = self.deploy("FAILED")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
