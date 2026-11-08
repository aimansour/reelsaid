"""Stage the temporary probe and run it from the public verification workflow."""

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

mode = sys.argv[1] if len(sys.argv) > 1 else "expiry"

with tempfile.TemporaryDirectory(prefix="reelsaid-asr-probe-") as directory:
    target = Path(directory) / "actor"
    shutil.copytree("probes/transcription", target)
    shutil.copyfile("probes/instagram/probe.py", target / "instagram.py")
    shutil.copyfile("scripts/install-quality-models", target / "install-quality-models")
    package = target / "reelsaid"
    package.mkdir()
    for module in ("contracts", "input", "instagram", "discovery", "media", "groq", "audio_quality", "quality"):
        shutil.copyfile(Path("src/reelsaid") / f"{module}.py", package / f"{module}.py")
    subprocess.run(["apify", "actors", "push", "--dir", str(target), "--no-apply-env-vars-to-build",
                    "--wait-for-finish", "420", "--json"], check=True)
    subprocess.run(["apify", "actors", "call", "aimansour/reelsaid-transcription-probe",
                    "--input", json.dumps({"mode": mode}), "--timeout", "340", "--memory", "1024",
                    "--silent", "--json"], check=True)
