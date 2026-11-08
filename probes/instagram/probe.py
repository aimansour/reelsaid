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
    def verify_cdn(url):
        if not url or not (urlparse(url).hostname or "").endswith((".cdninstagram.com", ".fbcdn.net")):
            return None
        try:
            with closing(requests.get(url, headers={"Range": "bytes=0-1023"}, stream=True, timeout=6)) as cdn:
                return {"http": cdn.status_code, "contentType": cdn.headers.get("content-type")}
        except requests.RequestsError as exc:
            return {"error": type(exc).__name__}
    publisher = target.get("user") or target.get("owner") or {}
    coauthors = target.get("coauthor_producers") or []
    return {
        "targetPublisher": publisher.get("username") if target else None,
        "targetCoauthors": [c.get("username") for c in coauthors if isinstance(c, dict)],
        "targetChildChecks": [{"position": i, "id": c.get("pk") or c.get("id"),
                               "http": (verify_cdn(c["video_versions"][0].get("url")) or {}).get("http")}
                              for i, c in enumerate(children) if isinstance(c, dict) and c.get("video_versions")],
        "targetVideoVariants": len(variants),
        "targetVideoChildren": sum(bool(c.get("video_versions")) for c in children if isinstance(c, dict)),
        "targetCdnProbe": verify_cdn(media),
        "listingAnchors": len(set(re.findall(r"/(?:reel|p)/([A-Za-z0-9_-]{8,16})/", text))),
        "profileNode": bool(keys & {"xig_user_by_username", "polaris_ordered_timeline_connection"}),
        "profileHints": {k: bool(re.search(r'["\']' + k + r'["\']', text))
                         for k in ("profile_id", "xig_user_by_username", "polaris_ordered_timeline_connection", "user_id")},
        "http": response.status_code,
        "bytes": len(response.content),
        "finalHost": urlparse(response.url).hostname,
        "loginRedirect": urlparse(response.url).path.startswith("/accounts/login"),
        "videoUrlCount": len(links),
        "codes": sorted(codes)[:35],
        "hasCursor": bool(keys & {"end_cursor", "max_id", "next_max_id"}),
        "hasCarousel": bool(keys & {"carousel_media", "edge_sidecar_to_children"}),
        "profile": {k: profile.get(k) for k in ("username", "is_private", "is_professional_account", "account_type", "id", "pk")} if profile else None,
        "fields": sorted(keys & {"video_versions", "video_url", "video_duration", "play_count", "view_count",
                                "like_count", "comment_count", "caption", "taken_at", "coauthor_producers",
                                "clips_metadata", "xig_polaris_media", "polaris_ordered_timeline_connection",
                                "xdt_api__v1__clips__user__connection_v2"}),
        "errors": errors[:3],
    }


def graphql(session, referer, doc_id, friendly_name, variables, *, lsd=None, endpoint="/api/graphql"):
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
    return session.post(f"{BASE}{endpoint}", data=data, headers=headers, timeout=8)


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
    for code in ("CsuFa_Mga41", "DfaaAP7BvIu"):
        post = f"{BASE}/p/{code}/"
        fetch(f"post-graphql-{code}", lambda: graphql(
            session, post, "27130156389949648", "PolarisLoggedOutDesktopWWWPostRootContentQuery",
            {"media_id": media_id(code)}, lsd=lsd), code)
    for name in (PERSONAL, PROFILE):
        profile = f"{BASE}/{name}/"
        reels = profile + "reels/"

        def clips(response):
            if response is None:
                return None
            for value in json_values(response.text):
                for node in walk(value):
                    connection = node.get("polaris_clips_connection")
                    if isinstance(connection, dict) and isinstance(connection.get("edges"), list):
                        return node
            return None

        def page_record(route, node):
            if not node:
                emit({"route": route, "outcome": "no_listing"})
                return set(), {}
            connection = node["polaris_clips_connection"]
            entries = []
            for edge in connection["edges"]:
                media = edge.get("node") or {}
                if media.get("code"):
                    entries.append({k: media.get(k) for k in ("code", "product_type", "play_count",
                                    "like_count", "comment_count", "clips_tab_pinned_user_ids")})
            page = connection.get("page_info") or {}
            emit({"route": route, "profilePk": node.get("pk"), "profileRelayId": node.get("id"),
                  "count": len(entries), "hasNext": page.get("has_next_page"),
                  "hasCursor": bool(page.get("end_cursor")), "entries": entries[:4]})
            return {entry["code"] for entry in entries}, page

        nav_headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/157.0.0.0 Safari/537.36",
                       "Sec-CH-UA": '"Not-A.Brand";v="99", "Google Chrome";v="157", "Chromium";v="157"',
                       "Sec-CH-UA-Platform": '"Windows"', "Sec-CH-UA-Mobile": "?0",
                       "Accept-Language": "ar-EG,ar;q=0.9,en;q=0.8",
                       "Sec-Fetch-Site": "none", "Sec-Fetch-Mode": "navigate",
                       "Sec-Fetch-Dest": "document", "Sec-Fetch-User": "?1"}
        with requests.Session(impersonate="chrome", trust_env=False) as fresh:
            page_record(f"guest-html-clips-{name}", clips(fetch(f"guest-reels-html-{name}", lambda: fresh.get(
                reels, headers=nav_headers, timeout=8))))

        fetch(f"guest-profile-query-{name}", lambda: graphql(
            session, reels, "27981003384861049", "PolarisLoggedOutDesktopWWWProfileRootContentQuery",
            {"username": name}, lsd=lsd))
        listing = fetch(f"guest-clips-query-{name}", lambda: graphql(
            session, reels, "27838951732404191", "PolarisLoggedOutDesktopWWWProfileReelsTabContentQuery",
            {"username": name, "first": 12}, lsd=lsd))
        first = clips(listing)
        first_codes, page_info = page_record(f"guest-clips-first-{name}", first)
        if first and page_info.get("has_next_page") and page_info.get("end_cursor"):
            followup = fetch(f"guest-clips-next-query-{name}", lambda: graphql(
                session, reels, "27420265870989234", "PolarisLoggedOutDesktopWWWProfileReelsTabContentQuery_connection",
                {"id": first["id"], "first": 12, "after": page_info["end_cursor"]}, lsd=lsd))
            second_codes, _ = page_record(f"guest-clips-second-{name}", clips(followup))
            emit({"route": f"guest-clips-pagination-{name}", "firstCount": len(first_codes),
                  "secondCount": len(second_codes), "newCodes": len(second_codes - first_codes)})
    emit(from_library("yt-dlp-short", ["python", "-m", "yt_dlp", "--no-config", "--no-playlist",
                                      "--socket-timeout", "7", "--retries", "0", "--skip-download",
                                      "--dump-single-json", f"{BASE}/reel/{SHORT}/"]))
    emit(from_library("yt-dlp-carousel", ["python", "-m", "yt_dlp", "--no-config",
                                         "--socket-timeout", "7", "--retries", "0", "--skip-download",
                                         "--dump-single-json", f"{BASE}/p/{CAROUSEL}/"]))


if __name__ == "__main__":
    main()
