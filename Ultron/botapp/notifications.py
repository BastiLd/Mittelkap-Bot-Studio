from __future__ import annotations

import asyncio
import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, urlencode, urlsplit

import aiohttp
from defusedxml import ElementTree

from .config import public_url, validate_source
from .store import Store


@dataclass(frozen=True)
class Item:
    id: str
    title: str
    url: str
    creator: str = ""
    kind: str = "video"
    thumbnail_url: str = ""


def normalize_source_account(platform: str, value: str) -> str:
    """Accept names and canonical platform profile URLs, never arbitrary hosts."""
    value = value.strip()
    if platform not in {"youtube", "twitch", "tiktok"}:
        raise ValueError("Bitte YouTube, Twitch oder TikTok auswählen.")
    if "://" in value:
        public_url(value)
        url = urlsplit(value)
        allowed = {"youtube": {"youtube.com", "www.youtube.com", "m.youtube.com"},
                   "twitch": {"twitch.tv", "www.twitch.tv"},
                   "tiktok": {"tiktok.com", "www.tiktok.com"}}
        if url.hostname.lower() not in allowed[platform] or url.port not in (None, 443):
            raise ValueError("Bitte einen direkten Profillink der gewählten Plattform verwenden.")
        parts = url.path.strip("/").split("/")
        if platform == "youtube" and len(parts) == 2 and parts[0] == "channel":
            value = parts[1]
        elif len(parts) == 1:
            value = parts[0]
        else:
            raise ValueError("Bitte das Kanalprofil verlinken, keinen einzelnen Beitrag oder Stream.")
    if platform == "youtube" and re.fullmatch(r"@[\w.-]{3,30}", value):
        return value
    return validate_source(platform, value.lstrip("@") if platform != "youtube" else value)


async def resolve_source_account(session, platform: str, value: str) -> str:
    """Resolve a YouTube handle once; all requests use a fixed official hostname.

    A channel ID remains a stable, offline-compatible alternative if YouTube's
    public profile metadata changes or asks for consent.
    """
    account = normalize_source_account(platform, value)
    if platform != "youtube" or not account.startswith("@"):
        return account
    api_key = os.getenv("YOUTUBE_API_KEY")
    if api_key:
        try:
            async with session.get("https://www.googleapis.com/youtube/v3/channels",
                                   params={"part": "id", "forHandle": account, "key": api_key},
                                   allow_redirects=False, timeout=aiohttp.ClientTimeout(total=15)) as response:
                if response.status != 200:
                    raise ValueError("YouTube-API konnte das Profil nicht auflösen. API-Freigabe prüfen oder UC-Kanal-ID verwenden.")
                body = await response.json()
            matches = body.get("items", [])
            if len(matches) != 1:
                raise ValueError("YouTube hat kein eindeutiges Kanalprofil zu diesem Namen gefunden.")
            return validate_source("youtube", matches[0].get("id", ""))
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            # ClientResponseError URLs may contain the private API key.
            raise ValueError("YouTube-Auflösung derzeit nicht erreichbar. Bitte erneut versuchen oder UC-Kanal-ID verwenden.") from None
    async with session.get("https://www.youtube.com/" + quote(account, safe="@"),
                           allow_redirects=False, timeout=aiohttp.ClientTimeout(total=15)) as response:
        if response.status != 200:
            raise ValueError("YouTube konnte das Profil nicht auflösen. Bitte die UC-Kanal-ID eintragen.")
        data = bytearray()
        async for chunk in response.content.iter_chunked(65536):
            data.extend(chunk)
            if len(data) > 2_000_000:
                raise ValueError("YouTube-Profilantwort zu groß. Bitte die UC-Kanal-ID verwenden.")
    html = bytes(data).decode("utf-8", errors="replace")
    match = re.search(r'"externalId"\s*:\s*"(UC[A-Za-z0-9_-]{22})"', html)
    if not match:
        match = re.search(r'<meta\s+itemprop="channelId"\s+content="(UC[A-Za-z0-9_-]{22})"', html)
    if not match:
        raise ValueError("YouTube-Kanal-ID nicht gefunden. Bitte die UC-Kanal-ID statt des Profillinks verwenden.")
    return validate_source("youtube", match.group(1))


def thumbnail(value: str) -> str:
    if not isinstance(value, str) or not value:
        return ""
    try:
        return public_url(value)
    except ValueError:
        return ""


def youtube_items(xml: bytes) -> list[Item]:
    if len(xml) > 1_000_000:
        raise ValueError("YouTube-Feed ist unerwartet groß.")
    ns = {"a": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015", "media": "http://search.yahoo.com/mrss/"}
    root = ElementTree.fromstring(xml)
    if root.tag != "{http://www.w3.org/2005/Atom}feed":
        raise ValueError("YouTube-Antwort ist kein Atom-Feed.")
    result = []
    creator = root.findtext("a:author/a:name", default="", namespaces=ns) or root.findtext("a:title", default="", namespaces=ns)
    for entry in root.findall("a:entry", ns):
        video = entry.findtext("yt:videoId", default="", namespaces=ns)
        if re.fullmatch(r"[A-Za-z0-9_-]{11}", video):
            preview = entry.find("media:group/media:thumbnail", ns)
            result.append(Item(video, entry.findtext("a:title", default="Neues Video", namespaces=ns)[:250],
                               f"https://www.youtube.com/watch?v={video}", entry.findtext("a:author/a:name", default=creator, namespaces=ns)[:150],
                               thumbnail_url=thumbnail(preview.get("url", "")) if preview is not None else ""))
    return result


class Fetcher:
    def __init__(self, session: aiohttp.ClientSession, auth_path: Path | None = None):
        self.session = session
        self.token = None
        self.expires = 0.0
        self.validated = 0.0
        self.tiktok_auth_path = auth_path
        self.tiktok_auth = {}
        if auth_path and auth_path.exists():
            self.tiktok_auth = json.loads(auth_path.read_text(encoding="utf-8"))

    async def tiktok_access_token(self, force=False):
        token = self.tiktok_auth.get("access_token") or os.getenv("TIKTOK_ACCESS_TOKEN")
        expires = self.tiktok_auth.get("expires_at", 0)
        if token and not force and (not expires or time.time() < expires - 60):
            return token
        refresh = self.tiktok_auth.get("refresh_token") or os.getenv("TIKTOK_REFRESH_TOKEN")
        client_key, secret = os.getenv("TIKTOK_CLIENT_KEY"), os.getenv("TIKTOK_CLIENT_SECRET")
        if not refresh or not client_key or not secret:
            raise ValueError("TikTok benötigt einen freigegebenen Nutzerzugang mit video.list; Token später einrichten.")
        async with self.session.post("https://open.tiktokapis.com/v2/oauth/token/", data={
            "client_key": client_key, "client_secret": secret, "grant_type": "refresh_token", "refresh_token": refresh
        }) as response:
            response.raise_for_status()
            body = await response.json()
        if not body.get("access_token"):
            raise ValueError("TikTok konnte den Zugang nicht erneuern.")
        self.tiktok_auth = {"access_token": body["access_token"], "refresh_token": body.get("refresh_token", refresh),
                            "expires_at": time.time() + int(body["expires_in"])}
        if self.tiktok_auth_path:
            temporary = self.tiktok_auth_path.with_suffix(".tmp")
            temporary.write_text(json.dumps(self.tiktok_auth), encoding="utf-8")
            temporary.replace(self.tiktok_auth_path)
        return body["access_token"]

    async def tiktok(self, account: str) -> list[Item]:
        account = validate_source("tiktok", account)
        for attempt in range(2):
            token = await self.tiktok_access_token(force=attempt > 0)
            async with self.session.post("https://open.tiktokapis.com/v2/video/list/", params={
                "fields": "id,title,video_description,share_url,create_time,cover_image_url"
            }, headers={"Authorization": f"Bearer {token}"}, json={"max_count": 20}) as response:
                if response.status == 401 and attempt == 0:
                    continue
                response.raise_for_status()
                body = await response.json()
            error = body.get("error", {}).get("code", "ok")
            if error in {"access_token_invalid", "access_token_expired"} and attempt == 0:
                continue
            if error != "ok":
                raise ValueError("TikTok hat die Videoabfrage abgelehnt. Freigabe und Scopes prüfen.")
            result = []
            for video in body.get("data", {}).get("videos", []):
                video_id = str(video.get("id", ""))
                if video_id.isdigit():
                    # Construct the canonical URL instead of trusting arbitrary response URLs.
                    result.append(Item(video_id, (video.get("title") or video.get("video_description") or "Neues TikTok-Video")[:250],
                                       f"https://www.tiktok.com/@{account}/video/{video_id}", account, "video", thumbnail(video.get("cover_image_url", ""))))
            return result
        return []

    async def youtube(self, account: str) -> list[Item]:
        validate_source("youtube", account)
        url = "https://www.youtube.com/xml/feeds/videos.xml?" + urlencode({"channel_id": account})
        async with self.session.get(url) as response:
            response.raise_for_status()
            data = bytearray()
            async for chunk in response.content.iter_chunked(65536):
                data.extend(chunk)
                if len(data) > 1_000_000:
                    raise ValueError("YouTube-Feed ist unerwartet groß.")
        items = youtube_items(bytes(data))
        # With a Data API key, distinguish scheduled/live/completed broadcasts from uploads.
        # This prevents a stream getting both an upload and a live-start notification.
        api_key = os.getenv("YOUTUBE_API_KEY")
        if not api_key or not items:
            return items
        async with self.session.get("https://www.googleapis.com/youtube/v3/videos", params={
            "part": "snippet,liveStreamingDetails", "id": ",".join(item.id for item in items), "key": api_key
        }) as response:
            response.raise_for_status()
            body = await response.json()
        videos = {v["id"]: v for v in body["items"]}
        return [item for item in items if item.id in videos and not videos[item.id].get("liveStreamingDetails")
                and videos[item.id].get("snippet", {}).get("liveBroadcastContent", "none") == "none"]

    async def youtube_live(self, account: str) -> list[Item]:
        validate_source("youtube", account)
        key = os.getenv("YOUTUBE_API_KEY")
        if not key:
            raise ValueError("YouTube-Livestream-Erkennung benötigt einen YOUTUBE_API_KEY.")
        async with self.session.get("https://www.googleapis.com/youtube/v3/search", params={
            "part": "snippet", "channelId": account, "type": "video", "eventType": "live", "maxResults": 50, "key": key
        }) as response:
            response.raise_for_status()
            body = await response.json()
        result = []
        for video in body["items"]:
            video_id = video.get("id", {}).get("videoId", "")
            snippet = video.get("snippet", {})
            if re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id) and snippet.get("channelId") == account:
                images = snippet.get("thumbnails", {})
                image = next((images[k].get("url", "") for k in ("maxres", "high", "medium", "default") if k in images), "")
                result.append(Item(video_id, snippet.get("title", "Livestream")[:250], f"https://www.youtube.com/watch?v={video_id}", snippet.get("channelTitle", account)[:150], "live", thumbnail(image)))
        return result

    async def access_token(self):
        client_id, secret = os.getenv("TWITCH_CLIENT_ID"), os.getenv("TWITCH_CLIENT_SECRET")
        if not client_id or not secret:
            raise ValueError("Twitch-App-Zugangsdaten fehlen; Quelle wird später erneut geprüft.")
        now = time.monotonic()
        if self.token and now < self.expires and now - self.validated >= 3600:
            async with self.session.get("https://id.twitch.tv/oauth2/validate", headers={"Authorization": f"OAuth {self.token}"}) as response:
                if response.status == 401:
                    self.token = None
                else:
                    response.raise_for_status()
                    self.validated = now
        if not self.token or now >= self.expires:
            async with self.session.post("https://id.twitch.tv/oauth2/token", data={
                "client_id": client_id, "client_secret": secret, "grant_type": "client_credentials"
            }) as response:
                response.raise_for_status()
                body = await response.json()
            self.token = body["access_token"]
            self.expires = now + max(0, int(body["expires_in"]) - 60)
            self.validated = now
        return client_id, self.token

    async def twitch(self, account: str) -> list[Item]:
        account = validate_source("twitch", account)
        for attempt in range(2):
            client_id, token = await self.access_token()
            async with self.session.get("https://api.twitch.tv/helix/streams", params={"user_login": account},
                                        headers={"Client-Id": client_id, "Authorization": f"Bearer {token}"}) as response:
                if response.status == 401 and attempt == 0:
                    self.token = None
                    continue
                response.raise_for_status()
                body = await response.json()
            return [Item(str(s["id"]), str(s["title"])[:250], f"https://www.twitch.tv/{account}", str(s.get("user_name", account))[:150], "live",
                         thumbnail(s.get("thumbnail_url", "").replace("{width}", "1280").replace("{height}", "720"))) for s in body["data"]]
        return []


class Notifications:
    def __init__(self, store: Store, fetcher: Fetcher):
        self.store, self.fetcher = store, fetcher
        self.lock = asyncio.Lock()
        with self.store.db:
            self.store.db.execute("""CREATE TABLE IF NOT EXISTS notification_pending (
                guild INTEGER NOT NULL, source TEXT NOT NULL, item TEXT NOT NULL,
                first_seen REAL NOT NULL, due REAL NOT NULL,
                PRIMARY KEY (guild, source, item))""")

    @staticmethod
    def source_key(source: dict, live: bool = False) -> str:
        account = validate_source(source["platform"], source["account"])
        return f"{source['platform']}{'-live' if live else ''}:{account}"

    def next_due(self, guild: int, source: dict, live: bool = False) -> float | None:
        row = self.store.db.execute("SELECT MIN(due) FROM notification_pending WHERE guild=? AND source=?",
                                    (guild, self.source_key(source, live))).fetchone()
        return row[0] if row else None

    async def poll(self, guild: int, source: dict, send, live: bool = False, delay_seconds: int = 0):
        platform, account = source["platform"], source["account"]
        account = validate_source(platform, account)
        key = self.source_key(source, live)
        if source.get("enabled", True) is False:
            with self.store.db:
                self.store.db.execute("DELETE FROM notification_pending WHERE guild=? AND source=?", (guild, key))
            return
        delay = source.get("delay_seconds", delay_seconds)
        if not isinstance(delay, int) or isinstance(delay, bool) or not 0 <= delay <= 86400:
            raise ValueError("Stream-Verzögerung muss zwischen 0 und 86400 Sekunden liegen.")
        async with self.lock:
            items = await getattr(self.fetcher, "youtube_live" if live else platform)(account)
            is_stream = live or platform == "twitch"
            now = time.time()
            # Only a successful provider response may cancel ended streams.
            # Failed fetches leave scheduled announcements untouched for retry.
            if is_stream:
                current = {item.id for item in items}
                with self.store.db:
                    for row in self.store.db.execute("SELECT item FROM notification_pending WHERE guild=? AND source=?", (guild, key)).fetchall():
                        if row[0] not in current:
                            self.store.db.execute("DELETE FROM notification_pending WHERE guild=? AND source=? AND item=?", (guild, key, row[0]))
            # On first successful YouTube check, record the current feed without posting old uploads.
            # A Twitch stream already live at first startup is announced immediately.
            if platform in {"youtube", "tiktok"} and not live and not self.store.state(guild, f"seeded:{key}"):
                for item in items:
                    self.store.mark(guild, f"content:{key}:{item.id}")
                self.store.set_state(guild, f"seeded:{key}", "yes")
                return
            for item in reversed(items):
                delivery = f"content:{key}:{item.id}"
                if not self.store.seen(guild, delivery):
                    if is_stream:
                        with self.store.db:
                            self.store.db.execute("INSERT OR IGNORE INTO notification_pending VALUES (?,?,?,?,?)", (guild, key, item.id, now, now + delay))
                            # Editing the delay changes pending announcements as well.
                            self.store.db.execute("UPDATE notification_pending SET due=first_seen+? WHERE guild=? AND source=? AND item=?", (delay, guild, key, item.id))
                        row = self.store.db.execute("SELECT due FROM notification_pending WHERE guild=? AND source=? AND item=?", (guild, key, item.id)).fetchone()
                        if now < row[0]:
                            continue
                    public_url(item.url)
                    # Item comes from the current poll: title and thumbnail are
                    # refreshed after the waiting period, never taken from cache.
                    await send(platform, account, item)
                    self.store.mark(guild, delivery)
                    with self.store.db:
                        self.store.db.execute("DELETE FROM notification_pending WHERE guild=? AND source=? AND item=?", (guild, key, item.id))
