"""Exercise the probe using the SDK configuration on an ephemeral port."""

import json
import os
from pathlib import Path
import socket
import subprocess
import sys
from tempfile import TemporaryDirectory
from time import monotonic, sleep
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener


def request(opener, url, path, *, data=None, headers=None):
    try:
        response = opener.open(Request(url + path, data=data, headers=headers or {}), timeout=2)
    except HTTPError as error:
        response = error
    with response:
        return response.status, response.read()


def main():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    url = f"http://127.0.0.1:{port}"
    opener = build_opener(ProxyHandler({}))
    with TemporaryDirectory(prefix="reelsaid-standby-local-") as storage:
        environment = os.environ | {
            "ACTOR_WEB_SERVER_PORT": str(port),
            "APIFY_META_ORIGIN": "STANDBY",
            "APIFY_LOCAL_STORAGE_DIR": storage,
            "APIFY_IS_AT_HOME": "0",
            "ACTOR_MAX_TOTAL_CHARGE_USD": "0.015",
        }
        server = subprocess.Popen([sys.executable, "probe.py"], cwd=Path(__file__).parent, env=environment)
        try:
            deadline = monotonic() + 8
            while server.poll() is None:
                try:
                    status, body = request(opener, url, "/", headers={
                        "X-Apify-Container-Server-Readiness-Probe": "true",
                    })
                except URLError:
                    if monotonic() >= deadline:
                        raise
                    sleep(.1)
                else:
                    assert (status, body) == (200, b"OK")
                    break
            else:
                raise RuntimeError("The Standby probe exited before readiness.")
            status, body = request(opener, url, "/")
            assert status == 200 and json.loads(body) == {"status": "ready"}
            json_header = {"Content-Type": "application/json"}
            assert request(opener, url, "/probe", data=b"{", headers=json_header)[0] == 400
            assert request(opener, url, "/probe", data=b"{}", headers=json_header)[0] == 400
            status, body = request(opener, url, "/probe", data=b'{"mode":"observe"}', headers=json_header)
            observation = json.loads(body)
            assert status == 200 and observation["origin"] == "STANDBY"
            assert observation["port"] == port and observation["readinessSeen"]
            assert observation["platformBudget"] == "0.015"
            status, body = request(opener, url, "/probe", data=b'{"mode":"charge","maxTotalChargeUsd":0}',
                                   headers=json_header)
            assert status == 200 and json.loads(body)["settlement"] == "budget-rejected"
        finally:
            if server.poll() is None:
                server.terminate()
                server.wait(timeout=8)
    print("Standby SDK port, readiness, repeated HTTP requests, and input checks passed.")


if __name__ == "__main__":
    main()
