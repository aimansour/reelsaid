"""Stage the temporary probe and run it from the public verification workflow."""

from pathlib import Path
import shutil
import subprocess
import tempfile

with tempfile.TemporaryDirectory(prefix="reelsaid-asr-probe-") as directory:
    target = Path(directory) / "actor"
    shutil.copytree("probes/transcription", target)
    shutil.copyfile("probes/instagram/probe.py", target / "instagram.py")
    subprocess.run(["apify", "actors", "push", "--dir", str(target), "--no-apply-env-vars-to-build",
                    "--wait-for-finish", "420", "--json"], check=True)
    subprocess.run(["apify", "actors", "call", "aimansour/reelsaid-transcription-probe",
                    "--input", "{}", "--timeout", "340", "--memory", "1024", "--silent", "--json"], check=True)
