"""Measure logged-out HTTP access from the default Apify network."""

import html
import json
import os
import re
import string
import subprocess
from time import monotonic
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from curl_cffi import requests

BASE = "https://www.instagram.com"
BASE_HEADERS = {
    "X-IG-App-ID": "936619743392459", "X-ASBD-ID": "359341",
    "X-IG-WWW-Claim": "0", "Origin": BASE, "Accept": "*/*",
}
SHORT = "DS46KJNjva9"
CAROUSEL = "Ddm6E9OGt5D"
PERSONAL = "astro_kjell"
PROFILE = "nasa"
PROFILE_IDS = {PERSONAL: "2074163374", PROFILE: "528817151"}
ALPHABET = string.ascii_uppercase + string.ascii_lowercase + string.digits + "-_"


def media_id(code):
    value = 0
    for char in code:
        value = value * 64 + ALPHABET.index(char)
    return str(value)


def json_values(text):
    try:
        yield json.loads(text)
    except ValueError:
        pass
    for content in re.findall(r"<script[^>]*>(\s*[\[{].*?)</script>", text, re.S):
        try:
            yield json.loads(content)
        except ValueError:
            continue


def walk(node):
    if isinstance(node, dict):
        yield node
        for val in node.values():
            yield from walk(val)
    elif isinstance(node, list):
        for child in node:
            yield from walk(child)


def describe(response):
    text = html.unescape(response.text)
    nodes = [node for obj in json_values(text) for node in walk(obj)]
    keys = {key for node in nodes for key in node}
    links = {
        match for match in re.findall(r"https://[^\s\"'<>]+", text.replace("\\/", "/"))
        if re.search(r"\.(cdninstagram\.com|fbcdn\.net)/", match) and ".mp4" in match
    }
    codes = {node.get("code") or node.get("shortcode") for node in nodes
             if isinstance(node.get("code") or node.get("shortcode"), str)}
    profile = next((node for node in nodes if node.get("username") in PROFILE_IDS
                    and ("is_private" in node or "is_professional_account" in node)), {})
    errors = [node.get("message", "")[:100] for node in nodes
              if isinstance(node.get("message"), str) and ("severity" in node or "code" in node)]
    return {
        "http": response.status_code,
        "bytes": len(response.content),
        "finalHost": urlparse(response.url).hostname,
        "loginRedirect": urlparse(response.url).path.startswith("/accounts/login"),
        "videoUrlCount": len(links),
        "codes": sorted(codes)[:35],
        "hasCursor": bool(keys & {"end_cursor", "max_id", "next_max_id"}),
        "hasCarousel": bool(keys & {"carousel_media", "edge_sidecar_to_children"}),
        "profile": {k: profile.get(k) for k in ("username", "is_private", "is_professional_account", "account_type")} if profile else None,
        "fields": sorted(keys & {"video_versions", "video_url", "video_duration", "play_count", "view_count",
                                "like_count", "comment_count", "caption", "taken_at", "coauthor_producers",
                                "clips_metadata", "xig_polaris_media", "polaris_ordered_timeline_connection",
                                "xdt_api__v1__clips__user__connection_v2"}),
        "errors": errors[:3],
    }


def graphql(session, referer, doc_id, friendly_name, variables, *, lsd=None):
    headers = {**BASE_HEADERS, "Referer": referer, "X-FB-Friendly-Name": friendly_name,
               "X-Requested-With": "XMLHttpRequest"}
    data = {"doc_id": doc_id, "variables": json.dumps(variables, separators=(",", ":")),
            "server_timestamps": "true", "fb_api_caller_class": "RelayModern",
            "fb_api_req_friendly_name": friendly_name}
    if lsd:
        data["lsd"] = headers["X-FB-LSD"] = lsd
    csrf = session.cookies.get("csrftoken")
    if csrf:
        headers["X-CSRFToken"] = csrf
    return session.post(f"{BASE}/api/graphql", data=data, headers=headers, timeout=8)


def from_library(label, args):
    start = monotonic()
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=28)
        answer = {"route": label, "exit": result.returncode}
        if result.returncode == 0:
            data = json.loads(result.stdout)
            items = data.get("entries") or [data]
            answer.update(videos=len(items), formatCount=sum(len(i.get("formats", [])) for i in items))
        else:
            answer["error"] = result.stderr.splitlines()[-1][:270] if result.stderr else None
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        answer = {"route": label, "error": type(exc).__name__}
    answer["milliseconds"] = round((monotonic() - start) * 1000)
    return answer


def emit(row):
    target = f"https://api.apify.com/v2/datasets/{os.environ['APIFY_DEFAULT_DATASET_ID']}/items"
    req = Request(target, json.dumps(row).encode(), {
        "Authorization": f"Bearer {os.environ['APIFY_TOKEN']}", "Content-Type": "application/json",
    }, method="POST")
    with urlopen(req, timeout=10):
        pass


def main():
    session = requests.Session(impersonate="chrome", trust_env=False)
    def fetch(route, fn):
        start = monotonic()
        try:
            res = fn()
            detail = describe(res)
        except requests.RequestsError as exc:
            res = None
            detail = {"error": type(exc).__name__}
        emit({"route": route, "milliseconds": round((monotonic() - start) * 1000), **detail})
        return res

    root = fetch("anonymous-session", lambda: session.get(BASE + "/", timeout=8))
    lsd = None
    if root is not None:
        m = re.search(r'id="__eqmc"[^>]*>\s*({.*?})</script>', root.text, re.S)
        if m:
            try:
                lsd = json.loads(m.group(1)).get("l")
            except ValueError:
                pass
        if not lsd:
            m = re.search(r'\["LSD",\[\],\{"token":"([^"]+)"', root.text)
            lsd = m.group(1) if m else None
    for code in (SHORT, CAROUSEL):
        post = f"{BASE}/p/{code}/"
        fetch(f"post-page-{code}", lambda: session.get(post, timeout=8))
        fetch(f"embed-{code}", lambda: session.get(post + "embed/captioned/", timeout=8))
        fetch(f"post-graphql-{code}", lambda: graphql(
            session, post, "27130156389949648", "PolarisLoggedOutDesktopWWWPostRootContentQuery",
            {"media_id": media_id(code)}, lsd=lsd))
        fetch(f"media-web-{code}", lambda: session.get(
            f"{BASE}/api/v1/media/{media_id(code)}/info/", headers=BASE_HEADERS, timeout=8))
    for name in (PERSONAL, PROFILE):
        profile = f"{BASE}/{name}/"
        fetch(f"profile-page-{name}", lambda: session.get(profile, timeout=8))
        fetch(f"reels-tab-{name}", lambda: session.get(profile + "reels/", timeout=8))
        fetch(f"web-profile-info-{name}", lambda: session.get(
            BASE + "/api/v1/users/web_profile_info/", params={"username": name},
            headers=BASE_HEADERS, timeout=8))
        fetch(f"reels-graphql-{name}", lambda: graphql(
            session, profile, "7845543455542541", "PolarisProfileReelsTabContentQuery_connection",
            {"data": {"page_size": 12, "include_feed_video": True, "target_user_id": PROFILE_IDS[name]}}, lsd=lsd))
        fetch(f"clips-api-{name}", lambda: session.post(
            BASE + "/api/v1/clips/user/", data={"target_user_id": PROFILE_IDS[name], "page_size": "12",
                                               "include_feed_video": "true"}, headers=BASE_HEADERS, timeout=8))
    emit(from_library("yt-dlp-short", ["python", "-m", "yt_dlp", "--no-config", "--no-playlist",
                                      "--socket-timeout", "7", "--retries", "0", "--skip-download",
                                      "--dump-single-json", f"{BASE}/reel/{SHORT}/"]))
    emit(from_library("yt-dlp-carousel", ["python", "-m", "yt_dlp", "--no-config",
                                         "--socket-timeout", "7", "--retries", "0", "--skip-download",
                                         "--dump-single-json", f"{BASE}/p/{CAROUSEL}/"]))


if __name__ == "__main__":
    main()
