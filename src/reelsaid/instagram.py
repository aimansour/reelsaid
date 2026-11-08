"""Logged-out HTTP access to public Instagram posts and the profile Reels tab."""

import asyncio
import html
import json
import re
import string
from collections.abc import Iterator
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

from curl_cffi.requests import AsyncSession, RequestsError, Response

from .contracts import JsonObject
from .input import classify_url


BASE = "https://www.instagram.com"
ALPHABET = string.ascii_uppercase + string.ascii_lowercase + string.digits + "-_"
HEADERS = {
    "X-IG-App-ID": "936619743392459",
    "X-ASBD-ID": "359341",
    "X-IG-WWW-Claim": "0",
    "Origin": BASE,
    "Accept": "*/*",
    "X-Requested-With": "XMLHttpRequest",
}
POST_QUERY = ("27130156389949648", "PolarisLoggedOutDesktopWWWPostRootContentQuery")
PROFILE_QUERY = ("27981003384861049", "PolarisLoggedOutDesktopWWWProfileRootContentQuery")
FIRST_REELS_QUERY = ("27838951732404191", "PolarisLoggedOutDesktopWWWProfileReelsTabContentQuery")
NEXT_REELS_QUERY = ("27420265870989234", "PolarisLoggedOutDesktopWWWProfileReelsTabContentQuery_connection")
CODE = re.compile(r"[A-Za-z0-9_-]+")


class InstagramError(Exception):
    def __init__(self, code: str, *, retryable: bool = False):
        super().__init__(code)
        self.code = code
        self.retryable = retryable


@dataclass(frozen=True)
class ProfilePage:
    profile_id: str | None
    entries: tuple[JsonObject, ...]
    cursor: tuple[str, str] | None = None


def object_value(value: object) -> JsonObject:
    return value if isinstance(value, dict) else {}


def records(value: object) -> Iterator[JsonObject]:
    if isinstance(value, list):
        yield from (entry for entry in value if isinstance(entry, dict))


def _nodes(value: object) -> Iterator[JsonObject]:
    stack = [value]
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            yield item
            stack.extend(reversed(item.values()))
        elif isinstance(item, list):
            stack.extend(reversed(item))


def _json_objects(body: str) -> Iterator[object]:
    body = body.removeprefix("for (;;);").strip()
    if body.startswith(("{", "[")):
        try:
            yield json.loads(body)
            return
        except ValueError:
            for line in body.splitlines():
                try:
                    yield json.loads(line)
                except ValueError:
                    continue
    for match in re.finditer(r"<script\b[^>]*>\s*([\[{].*?)</script>", body, re.S | re.I):
        script = match.group(1)
        for value in (script, html.unescape(script)):
            try:
                yield json.loads(value)
                break
            except ValueError:
                continue


def parse_post(body: str, shortcode: str) -> JsonObject | None:
    matches = [
        node
        for value in _json_objects(body)
        for node in _nodes(value)
        if (node.get("code") or node.get("shortcode")) == shortcode
        and {"video_versions", "video_url", "carousel_media", "media_type"}.intersection(node)
    ]
    return max(matches, key=lambda node: (
        bool(node.get("carousel_media") or node.get("video_versions") or node.get("video_url")),
        len(node),
    ), default=None)


def post_shortcode(url: str) -> str | None:
    path = urlsplit(url).path.strip("/").split("/")
    if len(path) == 2 and path[0] in {"reel", "reels", "p", "tv"} and CODE.fullmatch(path[1]):
        return path[1]
    return None


def _media_id(code: str) -> str:
    value = 0
    for character in code:
        value = value * 64 + ALPHABET.index(character)
    return str(value)


def _status_error(response: Response) -> InstagramError | None:
    if response.status_code == 410:
        return InstagramError("CONTENT_REMOVED")
    if response.status_code in {403, 429} or urlsplit(response.url).path.startswith(("/accounts/login", "/challenge")):
        return InstagramError("TEMPORARILY_BLOCKED", retryable=True)
    if response.status_code >= 500:
        return InstagramError("INSTAGRAM_UNAVAILABLE", retryable=True)
    if response.status_code == 404:
        return InstagramError("CONTENT_UNAVAILABLE")
    if response.status_code >= 400:
        return InstagramError("INSTAGRAM_UNAVAILABLE", retryable=True)
    return None


def _graphql_error(body: str) -> InstagramError | None:
    for parsed in _json_objects(body):
        for error in records(object_value(parsed).get("errors")):
            message = str(error.get("message") or "").casefold()
            if any(phrase in message for phrase in ("private account", "account is private", "content is private")):
                return InstagramError("CONTENT_PRIVATE")
            if any(phrase in message for phrase in ("content was deleted", "media was deleted", "post has been removed")):
                return InstagramError("CONTENT_REMOVED")
            if any(phrase in message for phrase in ("rate limit", "please wait", "login required", "temporarily blocked")):
                return InstagramError("TEMPORARILY_BLOCKED", retryable=True)
    return None


class InstagramClient:
    def __init__(self, session: AsyncSession):
        self._session = session
        self._ready = False
        self._lsd = None
        self._bootstrap_lock = asyncio.Lock()

    async def _get(self, url: str) -> Response:
        for _ in range(5):
            response = await self._session.get(url, timeout=8, allow_redirects=False)
            if response.status_code not in {301, 302, 303, 307, 308}:
                return response
            location = response.headers.get("location")
            if not location:
                break
            url = urljoin(url, location)
            classified = classify_url(url)
            if not classified or classified[0] == "cdn":
                if urlsplit(url).hostname == "www.instagram.com" and urlsplit(url).path.startswith(
                    ("/accounts/login", "/challenge")
                ):
                    raise InstagramError("TEMPORARILY_BLOCKED", retryable=True)
                raise InstagramError("INVALID_REDIRECT")
        raise InstagramError("INSTAGRAM_UNAVAILABLE", retryable=True)

    async def _bootstrap(self) -> None:
        async with self._bootstrap_lock:
            if self._ready:
                return
            # This fixed origin's guest home may redirect. Only accept its guest tokens.
            response = await self._session.get(f"{BASE}/", timeout=8, allow_redirects=False)
            match = re.search(r'id="__eqmc"[^>]*>\s*({.*?})</script>', response.text, re.S)
            if match:
                try:
                    self._lsd = object_value(json.loads(match.group(1))).get("l")
                except ValueError:
                    pass
            if not self._lsd:
                match = re.search(r'\["LSD",\[\],\{"token":"([^"]+)"', response.text)
                self._lsd = match.group(1) if match else None
            self._ready = True

    async def _graphql(self, query: tuple[str, str], variables: JsonObject, referer: str) -> Response:
        await self._bootstrap()
        doc_id, friendly_name = query
        headers = {**HEADERS, "Referer": referer, "X-FB-Friendly-Name": friendly_name}
        data = {
            "doc_id": doc_id,
            "variables": json.dumps(variables, separators=(",", ":")),
            "server_timestamps": "true",
            "fb_api_caller_class": "RelayModern",
            "fb_api_req_friendly_name": friendly_name,
        }
        if self._lsd:
            data["lsd"] = headers["X-FB-LSD"] = self._lsd
        if csrf := self._session.cookies.get("csrftoken"):
            headers["X-CSRFToken"] = csrf
        response = await self._session.post(
            f"{BASE}/api/graphql", data=data, headers=headers, timeout=8, allow_redirects=False,
        )
        if response.status_code in {301, 302, 303, 307, 308}:
            raise InstagramError("TEMPORARILY_BLOCKED", retryable=True)
        return response

    async def resolve_share(self, url: str) -> str:
        try:
            response = await self._get(url)
        except RequestsError as exc:
            raise InstagramError("INSTAGRAM_UNAVAILABLE", retryable=True) from exc
        if error := _status_error(response):
            raise error
        if code := post_shortcode(response.url):
            return code
        raise InstagramError("CONTENT_UNAVAILABLE")

    async def post(self, shortcode: str) -> JsonObject:
        post_url = f"{BASE}/p/{shortcode}/"
        failures = []
        try:
            response = await self._graphql(POST_QUERY, {"media_id": _media_id(shortcode)}, post_url)
            error = _status_error(response) or _graphql_error(response.text)
            if error:
                failures.append(error)
            elif post := parse_post(response.text, shortcode):
                return post
        except RequestsError:
            failures.append(InstagramError("INSTAGRAM_UNAVAILABLE", retryable=True))
        except InstagramError as exc:
            failures.append(exc)

        try:
            response = await self._get(post_url)
            error = _status_error(response)
            if error:
                failures.append(error)
            elif post := parse_post(response.text, shortcode):
                return post
        except RequestsError:
            failures.append(InstagramError("INSTAGRAM_UNAVAILABLE", retryable=True))
        except InstagramError as exc:
            failures.append(exc)

        for code in ("CONTENT_PRIVATE", "CONTENT_REMOVED", "TEMPORARILY_BLOCKED", "INSTAGRAM_UNAVAILABLE"):
            if failure := next((error for error in failures if error.code == code), None):
                raise failure
        raise InstagramError("CONTENT_UNAVAILABLE")

    async def profile(self, username: str, cursor: tuple[str, str] | None = None) -> ProfilePage:
        referer = f"{BASE}/{username}/reels/"
        try:
            if cursor is None:
                response = await self._graphql(FIRST_REELS_QUERY, {"username": username, "first": 12}, referer)
            else:
                response = await self._graphql(
                    NEXT_REELS_QUERY, {"id": cursor[0], "after": cursor[1], "first": 12}, referer,
                )
            if error := _status_error(response) or _graphql_error(response.text):
                raise error
            for payload in _json_objects(response.text):
                for node in _nodes(payload):
                    connection = object_value(node.get("polaris_clips_connection"))
                    if not isinstance(connection.get("edges"), list):
                        continue
                    edges = tuple(
                        media for edge in records(connection["edges"])
                        if (media := object_value(edge.get("node"))) and isinstance(media.get("code"), str)
                    )
                    page = object_value(connection.get("page_info"))
                    following = None
                    if page.get("has_next_page"):
                        relay_id = node.get("id") or (cursor[0] if cursor else None)
                        next_cursor = page.get("end_cursor")
                        if not isinstance(relay_id, str) or not isinstance(next_cursor, str):
                            raise InstagramError("PROFILE_PAGINATION_UNAVAILABLE", retryable=True)
                        following = (relay_id, next_cursor)
                    if node.get("is_private") is True:
                        raise InstagramError("CONTENT_PRIVATE")
                    pk = node.get("pk")
                    return ProfilePage(str(pk) if pk is not None else None, edges, following)
            response = await self._graphql(PROFILE_QUERY, {"username": username}, referer)
            if error := _status_error(response) or _graphql_error(response.text):
                raise error
            for payload in _json_objects(response.text):
                for node in _nodes(payload):
                    handle = node.get("username")
                    if isinstance(handle, str) and handle.casefold() == username and node.get("is_private") is True:
                        raise InstagramError("CONTENT_PRIVATE")
        except RequestsError as exc:
            raise InstagramError("INSTAGRAM_UNAVAILABLE", retryable=True) from exc
        raise InstagramError("PROFILE_DISCOVERY_UNAVAILABLE", retryable=True)
