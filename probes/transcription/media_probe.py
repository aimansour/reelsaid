"""Compare approved ASR transports and speech evidence in Apify cloud."""

import json
import os
import re
import subprocess
import tempfile
from contextlib import closing
from pathlib import Path
from time import monotonic
from urllib.parse import urlparse
from urllib.request import Request, urlopen

import webrtcvad
from curl_cffi import CurlMime, requests

from instagram import BASE, emit, graphql, json_values, media_id, walk

MODELS = ("whisper-large-v3-turbo", "whisper-large-v3")
SHORT = "DS46KJNjva9"
SPANISH = "Dfax6SllBLR"
QUIET = "DfaaAP7BvIu"
GROQ = "https://api.groq.com/openai/v1"


def resolve(session, code, lsd):
    page = graphql(session, f"{BASE}/p/{code}/", "27130156389949648",
                   "PolarisLoggedOutDesktopWWWPostRootContentQuery",
                   {"media_id": media_id(code)}, lsd=lsd)
    for value in json_values(page.text):
        for node in walk(value):
            if node.get("code") == code and node.get("video_versions"):
                for variant in node["video_versions"]:
                    url = variant.get("url", "")
                    if (urlparse(url).hostname or "").endswith((".cdninstagram.com", ".fbcdn.net")):
                        return url
    return None


def transcribe(session, account, key, model, case, *, url=None, file=None, language=None):
    values = [("model", model), ("response_format", "verbose_json"), ("temperature", "0"),
              ("timestamp_granularities[]", "segment"), ("timestamp_granularities[]", "word")]
    if url is not None:
        values.append(("url", url))
    if language:
        values.append(("language", language))
    start = monotonic()
    result = {"case": case, "account": account, "model": model, "mediaUploadBytes": file.stat().st_size if file else 0}
    try:
        with closing(CurlMime()) as mime:
            for field, val in values:
                mime.addpart(field, data=val.encode())
            if file is not None:
                mime.addpart("file", filename=file.name, local_path=file)
            response = session.post(GROQ + "/audio/transcriptions", multipart=mime,
                                    headers={"Authorization": "Bearer " + key}, timeout=32)
        result.update(http=response.status_code, limits={k: v for k, v in response.headers.items()
                                                        if k.startswith("x-ratelimit-") or k == "retry-after"})
        if response.ok:
            d = response.json()
            segments = d.get("segments") or []
            words = d.get("words") or []
            result.update(text=d.get("text"), language=d.get("language"), duration=d.get("duration"),
                          segmentCount=len(segments), wordCount=len(words),
                          firstWordStart=words[0].get("start") if words else None,
                          lastWordEnd=words[-1].get("end") if words else None,
                          noSpeechProb=[s.get("no_speech_prob") for s in segments])
        else:
            try:
                error = response.json().get("error", {})
                result["providerCode"] = error.get("code") or error.get("type")
            except ValueError:
                result["providerCode"] = "non_json_response"
    except (ValueError, requests.RequestsError) as exc:
        result["error"] = type(exc).__name__
    result["milliseconds"] = round((monotonic() - start) * 1000)
    emit(result)


def ffmpeg(*args):
    subprocess.run(["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y", *map(str, args)],
                   capture_output=True, check=True, timeout=28)


def voiced_fraction(path):
    result = subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-i", str(path),
                             "-ar", "16000", "-ac", "1", "-f", "s16le", "-"],
                            capture_output=True, check=True, timeout=20)
    pcm = result.stdout
    frames = [pcm[offset:offset + 960] for offset in range(0, len(pcm) - 959, 960)]
    vad = webrtcvad.Vad(3)
    return round(sum(vad.is_speech(f, 16000) for f in frames) / len(frames), 3) if frames else 0


def main():
    keys = json.loads(os.environ["REELSAID_GROQ_KEYS"])
    session = requests.Session(impersonate="chrome", trust_env=False)
    root = session.get(BASE + "/", timeout=8)
    eqmc = re.search(r'id="__eqmc"[^>]*>\s*({.*?})</script>', root.text, re.S)
    lsd = json.loads(eqmc.group(1)).get("l") if eqmc else None
    if not lsd:
        match = re.search(r'\["LSD",\[\],\{"token":"([^"]+)"', root.text)
        lsd = match.group(1) if match else None
    short, spanish, quiet = [resolve(session, code, lsd) for code in (SHORT, SPANISH, QUIET)]
    if not short:
        emit({"case": "acquisition", "shortResolved": False})
        return
    emit({"case": "acquisition", "shortResolved": True, "spanishResolved": bool(spanish), "quietResolved": bool(quiet)})
    input_path = f"https://api.apify.com/v2/key-value-stores/{os.environ['APIFY_DEFAULT_KEY_VALUE_STORE_ID']}/records/INPUT"
    with urlopen(Request(input_path, headers={"Authorization": f"Bearer {os.environ['APIFY_TOKEN']}"}), timeout=8) as payload:
        mode = json.load(payload).get("mode")
    if mode == "expiry":
        expired = re.sub(r"([?&]oe=)[0-9a-fA-F]+", r"\g<1>64A00000", short, count=1)
        assert expired != short
        with closing(session.get(expired, headers={"Range": "bytes=0-1023"}, stream=True, timeout=8)) as response:
            emit({"case": "expired_cdn", "http": response.status_code,
                  "expiryMessage": b"expired" in response.content[:300].lower()})
        account, key = next(iter(keys.items()))
        transcribe(session, account, key, MODELS[0], "expired_direct", url=expired)
        refreshed = resolve(session, SHORT, lsd)
        if refreshed:
            transcribe(session, account, key, MODELS[0], "refreshed_direct", url=refreshed)
        return
    start = monotonic()
    node = subprocess.run(["node", "-e", """
const url='https://www.instagram.com/p/DS46KJNjva9/';
fetch(url,{signal:AbortSignal.timeout(8000)}).then(async r=>{
 const body=await r.text();
 console.log(JSON.stringify({http:r.status,login:r.url.includes('/accounts/login/'),
                              bytes:Buffer.byteLength(body),media:body.includes('video_versions')}));
}).catch(e=>console.log(JSON.stringify({error:e.name})));
"""], capture_output=True, text=True, timeout=12)
    emit({"case": "node-fetch-control", "milliseconds": round((monotonic() - start) * 1000),
          **json.loads(node.stdout)})
    for account, key in keys.items():
        for model in MODELS:
            transcribe(session, account, key, model, "direct_short", url=short)
    account, key = next(iter(keys.items()))
    if spanish:
        transcribe(session, account, key, MODELS[0], "spanish_auto", url=spanish)
        transcribe(session, account, key, MODELS[1], "spanish_hint", url=spanish, language="es")
    if quiet:
        transcribe(session, account, key, MODELS[0], "public_no_speech_candidate", url=quiet)

    with tempfile.TemporaryDirectory() as scratch:
        work = Path(scratch)
        start = monotonic()
        video = session.get(short, timeout=15)
        video.raise_for_status()
        (work / "sample.mp4").write_bytes(video.content)
        speech, silence, music, mixed = (work / name for name in ("speech.flac", "silence.flac", "music.flac", "mixed.flac"))
        ffmpeg("-i", work / "sample.mp4", "-vn", "-ar", "16000", "-ac", "1", speech)
        emit({"case": "media_preparation", "sourceBytes": len(video.content), "sidecarBytes": speech.stat().st_size,
              "milliseconds": round((monotonic() - start) * 1000)})
        ffmpeg("-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono", "-t", "9", silence)
        ffmpeg("-f", "lavfi", "-i", "aevalsrc=0.10*sin(2*PI*220*t)+0.08*sin(2*PI*277*t)+0.07*sin(2*PI*330*t):s=16000",
               "-t", "9", music)
        ffmpeg("-i", speech, "-i", music, "-filter_complex", "amix=inputs=2:duration=first:weights='1 0.35'",
               mixed)
        emit({"case": "speech_evidence", "webrtcVoiceFraction": {
            name: voiced_fraction(path) for name, path in
            (("speech", speech), ("silence", silence), ("instrumental", music), ("speechOverMusic", mixed))}})
        for model in MODELS:
            for case, path in (("sidecar_upload", speech), ("silence", silence),
                               ("instrumental", music), ("speech_over_music", mixed)):
                transcribe(session, account, key, model, case, file=path)


if __name__ == "__main__":
    main()
