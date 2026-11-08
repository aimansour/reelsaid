"""Measure logged-out HTTP access from the default Apify network."""

import html
import json
import os
import re
import string
import subprocess
from contextlib import closing
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


def describe(response, target_code=None):
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
    target = next((node for node in nodes if target_code and
                   (node.get("code") or node.get("shortcode")) == target_code and
                   ("video_versions" in node or "carousel_media" in node)), {})
    children = target.get("carousel_media") or []
    variants = target.get("video_versions") or []
    media = variants[0].get("url") if variants and isinstance(variants[0], dict) else None
    media_probe = None
    if media and (urlparse(media).hostname or "").endswith((".cdninstagram.com", ".fbcdn.net")):
        try:
            with closing(requests.get(media, headers={"Range": "bytes=0-1023"}, stream=True, timeout=6)) as cdn:
                media_probe = {"http": cdn.status_code, "contentType": cdn.headers.get("content-type")}
        except requests.RequestsError as exc:
            media_probe = {"error": type(exc).__name__}
    return {
        "targetVideoVariants": len(variants),
        "targetVideoChildren": sum(bool(c.get("video_versions")) for c in children if isinstance(c, dict)),
        "targetCdnProbe": media_probe,
        "listingAnchors": len(set(re.findall(r"/(?:reel|p)/([A-Za-z0-9_-]{8,16})/", text))),
        "profileNode": bool(keys & {"xig_user_by_username", "polaris_ordered_timeline_connection"}),
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
    def fetch(route, fn, target_code=None):
        start = monotonic()
        try:
            res = fn()
            detail = describe(res, target_code)
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
        fetch(f"post-page-{code}", lambda: session.get(post, timeout=8), code)
        fetch(f"embed-{code}", lambda: session.get(post + "embed/captioned/", timeout=8))
        fetch(f"post-graphql-{code}", lambda: graphql(
            session, post, "27130156389949648", "PolarisLoggedOutDesktopWWWPostRootContentQuery",
            {"media_id": media_id(code)}, lsd=lsd), code)
        fetch(f"media-web-{code}", lambda: session.get(
            f"{BASE}/api/v1/media/{media_id(code)}/info/", headers=BASE_HEADERS, timeout=8))
    for name in (PERSONAL, PROFILE):
        profile = f"{BASE}/{name}/"
        with requests.Session(impersonate="chrome", trust_env=False) as fresh:
            fetch(f"profile-fresh-{name}", lambda: fresh.get(profile + "?hl=en", timeout=8,
                  headers={"Referer": "https://www.google.com/"}))
            fetch(f"profile-embed-{name}", lambda: fresh.get(profile + "embed/", timeout=8))
            fetch(f"profile-posts-{name}", lambda: fresh.get(profile + "posts/", timeout=8))
        with requests.Session(impersonate="safari_ios", trust_env=False) as mobile:
            fetch(f"profile-mobile-{name}", lambda: mobile.get(profile, timeout=8))
        fetch(f"profile-by-id-graphql-{name}", lambda: graphql(
            session, profile, "27937681195819736", "PolarisProfilePageContentQuery",
            {"id": PROFILE_IDS[name], "render_surface": "PROFILE", "enable_integrity_filters": True,
             "__relay_internal__pv__PolarisCannesGuardianExperienceEnabledrelayprovider": True,
             "__relay_internal__pv__PolarisCASB976ProfileEnabledrelayprovider": False,
             "__relay_internal__pv__PolarisRepostsConsumptionEnabledrelayprovider": False,
             "__relay_internal__pv__PolarisWebSchoolsEnabledrelayprovider": False}, lsd=lsd))
        fetch(f"profile-posts-graphql-{name}", lambda: graphql(
            session, profile, "29104886249145907", "PolarisProfilePostsTabContentQuery_connection",
            {"data": {"count": 12, "include_reel_media_seen_timestamp": True,
                      "include_relationship_info": True, "latest_besties_reel_media": True,
                      "latest_reel_media": True}, "first": 12, "include_multi_captions": True,
             "username": name, "__relay_internal__pv__PolarisMultiCaptionCarouselEnabledrelayprovider": True,
             "__relay_internal__pv__PolarisShortDramaEnabledrelayprovider": True,
             "__relay_internal__pv__PolarisSEOIsCrawlerrelayprovider": False,
             "__relay_internal__pv__PolarisThreadsStyleCommentsEnabledrelayprovider": False,
             "__relay_internal__pv__PolarisReelsRecoDebugOverlayEnabledrelayprovider": False}, lsd=lsd))
        fetch(f"logged-out-profile-posts-{name}", lambda: graphql(
            session, profile, "28904005159232689", "PolarisLoggedOutDesktopWWWProfilePostsTabContentQuery_connection",
            {"id": PROFILE_IDS[name], "__relay_internal__pv__PolarisSEOIsCrawlerrelayprovider": False}, lsd=lsd))
        fetch(f"topsearch-{name}", lambda: session.get(
            BASE + "/api/v1/web/search/topsearch/", params={"query": name, "context": "blended"},
            headers=BASE_HEADERS, timeout=8))
        fetch(f"mobile-user-{name}", lambda: session.get(
            f"https://i.instagram.com/api/v1/users/{PROFILE_IDS[name]}/info/",
            headers={"User-Agent": "Instagram 269.0.0.18.75 Android", "X-IG-App-ID": "567067343352427"},
            timeout=8))
        start = monotonic()
        try:
            tested = subprocess.run(["python", "-c", """
import instaloader, json, sys
loader = instaloader.Instaloader(max_connection_attempts=1, request_timeout=8, sleep=False)
profile = instaloader.Profile.from_username(loader.context, sys.argv[1])
print(json.dumps({"isPrivate": profile.is_private, "pk": profile.userid,
                  "firstCode": next(iter(profile.get_posts()), None).shortcode}))
""", name], capture_output=True, text=True, timeout=25)
            emit({"route": f"instaloader-profile-{name}", "exit": tested.returncode,
                  "result": json.loads(tested.stdout) if tested.returncode == 0 else None,
                  "error": tested.stderr.splitlines()[-1][:220] if tested.returncode and tested.stderr else None,
                  "milliseconds": round((monotonic() - start) * 1000)})
        except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
            emit({"route": f"instaloader-profile-{name}", "error": type(exc).__name__})
    emit(from_library("yt-dlp-short", ["python", "-m", "yt_dlp", "--no-config", "--no-playlist",
                                      "--socket-timeout", "7", "--retries", "0", "--skip-download",
                                      "--dump-single-json", f"{BASE}/reel/{SHORT}/"]))
    emit(from_library("yt-dlp-carousel", ["python", "-m", "yt_dlp", "--no-config",
                                         "--socket-timeout", "7", "--retries", "0", "--skip-download",
                                         "--dump-single-json", f"{BASE}/p/{CAROUSEL}/"]))


if __name__ == "__main__":
    main()
