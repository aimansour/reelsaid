"""Inject the two authorized QA caller fingerprints into a disposable package."""

from hashlib import sha256
import json
import os
from pathlib import Path
import sys
from urllib.request import Request, urlopen


def caller(token):
    with urlopen(Request("https://api.apify.com/v2/users/me",
                         headers={"Authorization": "Bearer " + token}), timeout=12) as response:
        return sha256(json.load(response)["data"]["id"].encode()).hexdigest()[:16]


path = Path(sys.argv[1])
identities = {caller(os.environ[key]) for key in ("APIFY_TOKEN", "APIFY_STANDBY_TEST_TOKEN")}
if len(identities) != 2:
    raise RuntimeError("Two distinct authorized Apify accounts are required.")
path.write_text(f"CALLER_HASHES = frozenset({tuple(sorted(identities))!r})\n")
definition_path = path.parent / ".actor" / "actor.json"
definition = json.loads(definition_path.read_text())
definition["usesStandbyMode"] = False
definition_path.write_text(json.dumps(definition, indent=2) + "\n")
