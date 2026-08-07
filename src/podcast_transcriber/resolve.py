"""Spotify episode URL -> publisher RSS feed -> exact episode -> audio URL.

Pipeline (all HTTP through one injectable httpx.Client so tests can use
MockTransport with zero network):

    1. Parse the Spotify episode id out of the URL.
    2. Fetch *public* metadata (no auth) from the Spotify episode page:
       episode title, show name, duration (best effort via og tags +
       __NEXT_DATA__ JSON).  Public metadata only -- no Spotify API keys.
    3. Find the publisher's RSS feed via the iTunes Search API
       (https://itunes.apple.com/search?entity=podcast) using the show name.
    4. Fetch the feed (via httpx) and match the episode by title similarity
       + duration tolerance; GUID is used when the feed entry exposes one
       matching the Spotify "episode id" style anchor (best effort).
    5. verify.decide() maps candidates onto VERIFIED / REVIEW_REQUIRED /
       UNAVAILABLE.
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import feedparser
import httpx

from .verify import Candidate, VerificationResult, decide

log = logging.getLogger(__name__)

SPOTIFY_EPISODE_RE = re.compile(
    r"open\.spotify\.com/episode/([A-Za-z0-9]{10,})"
)
ITUNES_SEARCH_URL = "https://itunes.apple.com/search"
SPOTIFY_PAGE_URL = "https://open.spotify.com/episode/{id}"

BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

_STRIP_NUMBER_PREFIX = re.compile(
    r"^(?:episode|ep|e)?\s*#?\s*\d+\s*[:\-\s.–—]+"
)


def normalize_title(text: str) -> str:
    """Lowercase, unify unicode, drop episode-number prefixes + punctuation."""
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text)
    text = text.lower()
    text = _STRIP_NUMBER_PREFIX.sub("", text)
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    tokens = [t for t in text.split() if t]
    return " ".join(tokens)


def title_similarity(a: str, b: str) -> float:
    """Token overlap in [0,1]; 1.0 only for identical normalized titles."""
    na, nb = normalize_title(a), normalize_title(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    ta, tb = set(na.split()), set(nb.split())
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / max(len(ta), len(tb))


def parse_duration_seconds(value: Any) -> Optional[float]:
    """Parse RSS itunes_duration: seconds int, 'MM:SS' or 'HH:MM:SS'."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    parts = [p for p in s.split(":") if p != ""]
    if not parts:
        return None
    try:
        nums = [int(p) for p in parts]
    except ValueError:
        return None
    if len(nums) == 1:
        return float(nums[0])
    if len(nums) == 2:
        return float(nums[0] * 60 + nums[1])
    if len(nums) == 3:
        return float(nums[0] * 3600 + nums[1] * 60 + nums[2])
    return None


def compute_confidence(title_sim: float, dur_a: Optional[float],
                       dur_b: Optional[float], tolerance: float) -> float:
    """Combine title similarity and duration agreement into a confidence."""
    conf = 0.85 * title_sim
    if dur_a and dur_b:
        dur_score = 1.0 - min(1.0, abs(dur_a - dur_b) / tolerance)
        conf += 0.15 * dur_score
    else:
        conf += 0.05
    return round(min(1.0, conf), 4)


def parse_spotify_episode_id(url: str) -> Optional[str]:
    m = SPOTIFY_EPISODE_RE.search(url or "")
    return m.group(1) if m else None


@dataclass
class SpotifyMeta:
    spotify_id: str
    url: str
    episode_title: Optional[str] = None
    show_name: Optional[str] = None
    duration_seconds: Optional[float] = None
    guid: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "spotify_id": self.spotify_id,
            "url": self.url,
            "episode_title": self.episode_title,
            "show_name": self.show_name,
            "duration_seconds": self.duration_seconds,
            "guid": self.guid,
        }


# --------------------------------------------------------------------------- #
# Spotify public metadata (no auth).  Primary source: the embed/episode page
# which serves a __NEXT_DATA__ entity {name/title, subtitle (=show name),
# duration (ms)}.  Fallbacks: main-page og tags and the oEmbed title.
# --------------------------------------------------------------------------- #
def _find_entity(data: Any) -> Optional[Dict[str, Any]]:
    """Locate the episode entity dict inside __NEXT_DATA__."""

    def _walk(obj: Any):
        if isinstance(obj, dict):
            is_episode = (
                obj.get("type") == "episode"
                or "spotify:episode:" in (obj.get("uri") or "")
                or (obj.get("name") and isinstance(obj.get("showOf"), dict))
            )
            if is_episode:
                yield obj
            for v in obj.values():
                yield from _walk(v)
        elif isinstance(obj, list):
            for v in obj:
                yield from _walk(v)

    for ent in _walk(data):
        return ent
    return None


def _parse_spotify_html(html: str) -> Dict[str, Optional[str]]:
    """Best-effort extraction of episode title / show name / duration (seconds)."""
    meta: Dict[str, Optional[str]] = {"title": None, "show": None, "duration": None}

    next_data = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    if next_data:
        try:
            data = json.loads(next_data.group(1))
        except json.JSONDecodeError:
            data = None
        if data:
            ent = _find_entity(data)
            if ent:
                meta["title"] = ent.get("title") or ent.get("name")
                meta["show"] = ent.get("subtitle") or (
                    (ent.get("showOf") or {}).get("name")
                )
                dur = ent.get("duration") or ent.get("durationMs")
                if isinstance(dur, (int, float)) and dur > 0:
                    # Both `duration` and `durationMs` are milliseconds.
                    meta["duration"] = str(float(dur) / 1000.0)

    # og tags as a fallback (works when a crawler-facing page is served).
    og_title = re.search(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)', html)
    og_desc = re.search(r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\']([^"\']+)', html)
    if og_title:
        meta["title"] = meta["title"] or og_title.group(1)
    if og_desc:
        m = re.search(r"from\s+(.+?)\s+on Spotify", og_desc.group(1))
        if m and not meta["show"]:
            meta["show"] = m.group(1).strip()
    return meta


def fetch_spotify_metadata(client: httpx.Client, spotify_id: str) -> SpotifyMeta:
    sources = [
        "https://open.spotify.com/embed/episode/{id}",
        SPOTIFY_PAGE_URL,
    ]
    meta: Dict[str, Optional[str]] = {"title": None, "show": None, "duration": None}
    for template in sources:
        url = template.format(id=spotify_id)
        try:
            resp = client.get(url, headers={"User-Agent": BROWSER_UA})
            resp.raise_for_status()
        except Exception:  # noqa: BLE001 - try the next source
            continue
        parsed = _parse_spotify_html(resp.text)
        for k in ("title", "show", "duration"):
            meta[k] = meta[k] or parsed[k]
        if meta["title"] and meta["show"]:
            break

    if not meta["title"]:
        # oEmbed: returns JSON {title: ...} without needing page scraping.
        try:
            resp = client.get(
                "https://open.spotify.com/oembed",
                params={"url": f"https://open.spotify.com/episode/{spotify_id}"},
            )
            payload = resp.json()
            meta["title"] = payload.get("title")
        except Exception:  # noqa: BLE001
            pass

    duration: Optional[float] = None
    if meta.get("duration"):
        try:
            duration = float(meta["duration"])  # type: ignore[arg-type]
        except ValueError:
            duration = None

    return SpotifyMeta(
        spotify_id=spotify_id,
        url=f"https://open.spotify.com/episode/{spotify_id}",
        episode_title=meta.get("title"),
        show_name=meta.get("show"),
        duration_seconds=duration,
    )


# --------------------------------------------------------------------------- #
# iTunes Search API
# --------------------------------------------------------------------------- #
@dataclass
class ItunesShow:
    collection_name: str
    feed_url: Optional[str]
    artist_name: Optional[str] = None
    collection_id: Optional[int] = None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "collection_name": self.collection_name,
            "feed_url": self.feed_url,
            "artist_name": self.artist_name,
            "collection_id": self.collection_id,
        }


def search_itunes(client: httpx.Client, show_name: str, limit: int = 25) -> List[ItunesShow]:
    resp = client.get(
        ITUNES_SEARCH_URL,
        params={"term": show_name, "entity": "podcast", "limit": limit},
    )
    resp.raise_for_status()
    payload = resp.json()
    shows = []
    for r in payload.get("results", []):
        if not r.get("collectionName"):
            continue
        shows.append(
            ItunesShow(
                collection_name=str(r["collectionName"]),
                feed_url=r.get("feedUrl"),
                artist_name=r.get("artistName"),
                collection_id=r.get("collectionId"),
            )
        )
    return shows


def select_feed(shows: List[ItunesShow], show_name: Optional[str]) -> List[ItunesShow]:
    """Pick shows whose name matches the target; keep order, exact first."""
    if not show_name:
        return [s for s in shows if s.feed_url]
    norm = normalize_title(show_name)

    def score(s: ItunesShow) -> float:
        names = [s.collection_name, s.artist_name or ""]
        return max(title_similarity(norm, n) for n in names if n)

    scored = sorted(((score(s), s) for s in shows), key=lambda x: x[0], reverse=True)
    top = [s for sc, s in scored if sc >= 0.6]
    if not top:
        top = [s for sc, s in scored[:3]]
    return [s for s in top if s.feed_url]


# --------------------------------------------------------------------------- #
# Feed parsing + episode matching
# --------------------------------------------------------------------------- #
def _enclosure_url(entry: Any) -> Optional[str]:
    for enc in getattr(entry, "enclosures", []):
        t = (enc.get("type") or "").lower()
        if "audio" in t or t in ("", "application/octet-stream"):
            if enc.get("href"):
                return enc["href"]
    for link in getattr(entry, "links", []):
        if link.get("rel") == "enclosure" and link.get("href"):
            return link["href"]
    return None


def feed_entries(client: httpx.Client, feed_url: str) -> List[Any]:
    resp = client.get(feed_url, headers={"User-Agent": BROWSER_UA}, follow_redirects=True)
    resp.raise_for_status()
    parsed = feedparser.parse(resp.content)
    if parsed.get("bozo") and not parsed.entries:
        raise ValueError(f"Feed parse failed: {parsed.get('bozo_exception')}")
    return parsed.entries


def match_episodes(entries: List[Any], meta: SpotifyMeta,
                   tolerance: float, top_n: int = 5) -> List[Candidate]:
    candidates: List[Candidate] = []
    for entry in entries:
        title = entry.get("title")
        if not title:
            continue
        audio_url = _enclosure_url(entry)
        dur = parse_duration_seconds(getattr(entry, "itunes_duration", None))
        title_sim = title_similarity(meta.episode_title or "", title)
        confidence = compute_confidence(title_sim, meta.duration_seconds, dur, tolerance)
        if confidence < 0.45:
            continue
        reason_bits = [f"title_sim={title_sim:.2f}"]
        if meta.duration_seconds and dur:
            diff = abs(meta.duration_seconds - dur)
            reason_bits.append(f"dur_diff={diff:.0f}s")
        candidates.append(
            Candidate(
                audio_url=audio_url,
                title=title,
                feed_url=getattr(entry, "feed", None) or meta.guid or None,
                duration_seconds=dur,
                confidence=confidence,
                reason=", ".join(reason_bits),
                extra={"guid": entry.get("id"), "published": entry.get("published")},
            )
        )
    candidates.sort(key=lambda c: c.confidence, reverse=True)
    return candidates[:top_n]


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
@dataclass
class Resolution:
    spotify_id: str
    source_url: str
    metadata: SpotifyMeta
    feed_url: Optional[str] = None
    feed_collection: Optional[str] = None
    result: Optional[VerificationResult] = None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "spotify_id": self.spotify_id,
            "source_url": self.source_url,
            "metadata": self.metadata.as_dict(),
            "feed_url": self.feed_url,
            "feed_collection": self.feed_collection,
            "result": self.result.as_dict() if self.result else None,
        }


def resolve(spotify_url: str, client: Optional[httpx.Client] = None,
            top_results: int = 25, duration_tolerance: float = 600.0) -> Resolution:
    """Full pipeline. Raises ValueError on unusable input."""
    spotify_id = parse_spotify_episode_id(spotify_url)
    if not spotify_id:
        raise ValueError(
            f"Not a Spotify episode URL: {spotify_url!r} "
            "(expected https://open.spotify.com/episode/<id>)"
        )

    own_client = client is None
    http = client or httpx.Client(follow_redirects=True, timeout=30.0)
    try:
        meta = fetch_spotify_metadata(http, spotify_id)
        res = Resolution(spotify_id=spotify_id, source_url=spotify_url, metadata=meta)

        if not meta.show_name:
            res.result = VerificationResult(
                state="UNAVAILABLE",
                confidence=0.0,
                reason="Could not extract the show name from the public Spotify page.",
            )
            return res

        shows = search_itunes(http, meta.show_name, limit=top_results)
        candidates: List[Candidate] = []
        feed_used: Optional[ItunesShow] = None
        for show in select_feed(shows, meta.show_name):
            try:
                entries = feed_entries(http, show.feed_url)  # type: ignore[arg-type]
            except Exception as exc:  # noqa: BLE001 - try next feed on failure
                log.warning("Feed fetch failed for %s: %s", show.collection_name, exc)
                continue
            matched = match_episodes(entries, meta, duration_tolerance)
            if matched:
                feed_used = show
                candidates = matched
                break

        if feed_used:
            res.feed_url = feed_used.feed_url
            res.feed_collection = feed_used.collection_name
        res.result = decide(candidates)
        return res
    finally:
        if own_client:
            http.close()