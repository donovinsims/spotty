"""Resolver tests -- fully offline via httpx.MockTransport."""

from __future__ import annotations

import httpx
import pytest

from podcast_transcriber import resolve
from podcast_transcriber.verify import REVIEW_REQUIRED, UNAVAILABLE, VERIFIED

EPISODE_ID = "abc123def456"
SPOTIFY_URL = f"https://open.spotify.com/episode/{EPISODE_ID}"
FEED_URL = "https://example.test/feed.xml"

SPOTIFY_HTML = (
    '<html><head>'
    '<meta property="og:title" content="Ep #100 - The Great Adventure"/>'
    '<meta property="og:description" content="Listen to this episode from The Test Show on Spotify."/>'
    '<script id="__NEXT_DATA__" type="application/json">'
    '{"props":{"pageProps":{"state":{"data":{"entity":{'
    '"name":"Ep #100 - The Great Adventure","showOf":{"name":"The Test Show"},'
    '"durationMs":1800000}}}}}'
    '</script></head></html>'
)

# Show embed page structure (for episode IDs that map to shows)
SPOTIFY_SHOW_EMBED_HTML = (
    '<html><head>'
    '<script id="__NEXT_DATA__" type="application/json">'
    '{"props":{"pageProps":{"state":{"data":{"entity":{'
    '"type":"episode","name":"Ep #100 - The Great Adventure",'
    '"subtitle":"The Test Show","durationMs":1800000}}}}}}'
    '</script></head></html>'
)

ITUNES_JSON = {
    "resultCount": 1,
    "results": [
        {
            "collectionName": "The Test Show",
            "artistName": "Test Network",
            "feedUrl": FEED_URL,
            "collectionId": 42,
        }
    ],
}

RSS_VALID = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd">
<channel><title>The Test Show</title>
<item><title>Ep #100 - The Great Adventure</title>
<guid>spotify:episode:abc123def456</guid>
<itunes:duration>1800</itunes:duration>
<enclosure url="https://cdn.test/show/100.mp3" type="audio/mpeg"/>
</item>
<item><title>Ep #99 - Something Else</title>
<itunes:duration>2400</itunes:duration>
<enclosure url="https://cdn.test/show/99.mp3" type="audio/mpeg"/>
</item>
</channel></rss>
"""


def make_client(spotify_html=SPOTIFY_HTML, itunes=ITUNES_JSON, feed=RSS_VALID):
    """Create a mock client where all Spotify URLs return the same HTML."""
    def handler(request: httpx.Request) -> httpx.Response:
        host = request.url.host
        if host == "open.spotify.com":
            return httpx.Response(200, text=spotify_html)
        if host == "itunes.apple.com":
            return httpx.Response(200, json=itunes)
        return httpx.Response(200, text=feed)

    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)


def make_client_show_embed_fallback(itunes=ITUNES_JSON, feed=RSS_VALID):
    """Create a mock client where episode embed 404s, show embed works, main page empty."""
    def handler(request: httpx.Request) -> httpx.Response:
        host = request.url.host
        url_str = str(request.url)
        if host == "open.spotify.com":
            if "/embed/episode/" in url_str:
                return httpx.Response(404, text="Not found")
            if "/embed/show/" in url_str:
                return httpx.Response(200, text=SPOTIFY_SHOW_EMBED_HTML)
            return httpx.Response(200, text='<html><head></head></html>')
        if host == "itunes.apple.com":
            return httpx.Response(200, json=itunes)
        return httpx.Response(200, text=feed)

    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)


def test_normalize_title():
    assert resolve.normalize_title("Ep #100 - The Great Adventure") == \
        resolve.normalize_title("#100 The Great Adventure") == "the great adventure"
    assert resolve.normalize_title("episode 12: Hello, World!") == "hello world"


def test_title_similarity():
    assert resolve.title_similarity("A B C", "A B C") == 1.0
    assert resolve.title_similarity("A B C", "A B D") < 1.0
    assert resolve.title_similarity("", "x") == 0.0


def test_parse_duration():
    assert resolve.parse_duration_seconds("0:45") == 45.0
    assert resolve.parse_duration_seconds("1:00:00") == 3600.0
    assert resolve.parse_duration_seconds(1800) == 1800.0
    assert resolve.parse_duration_seconds("junk") is None


def test_parse_episode_id():
    assert resolve.parse_spotify_episode_id(SPOTIFY_URL) == EPISODE_ID
    assert resolve.parse_spotify_episode_id("https://open.spotify.com/show/xyz") is None


def test_resolve_verified():
    client = make_client()
    res = resolve.resolve(SPOTIFY_URL, client=client)
    assert res.result is not None
    assert res.result.state == VERIFIED
    assert res.result.audio_url == "https://cdn.test/show/100.mp3"
    assert res.metadata.show_name == "The Test Show"
    assert res.metadata.episode_title == "Ep #100 - The Great Adventure"
    assert res.feed_url == FEED_URL


def test_resolve_review_required_ambiguous():
    rss = """<?xml version="1.0"?><rss version="2.0"><channel>
<item><title>Ep #100 - The Great Adventure (Live)</title>
<enclosure url="https://cdn.test/live.mp3" type="audio/mpeg"/></item>
<item><title>Ep #100 - The Great Adventure (Reprise)</title>
<enclosure url="https://cdn.test/reprise.mp3" type="audio/mpeg"/></item>
</channel></rss>"""
    # No itunes:duration and no spotify duration -> ambiguous => REVIEW_REQUIRED.
    spotify_no_dur = SPOTIFY_HTML.replace("1800000", "1")
    client = make_client(spotify_html=spotify_no_dur, feed=rss)
    res = resolve.resolve(SPOTIFY_URL, client=client)
    assert res.result.state == REVIEW_REQUIRED


def test_resolve_unavailable_no_feed():
    rss = """<?xml version="1.0"?><rss version="2.0"><channel>
    <item><title>Totally Unrelated Show</title>
    <enclosure url="https://cdn.test/x.mp3" type="audio/mpeg"/></item>
    </channel></rss>"""
    client = make_client(feed=rss)
    res = resolve.resolve(SPOTIFY_URL, client=client)
    assert res.result.state == UNAVAILABLE


def test_resolve_bad_url_raises():
    with pytest.raises(ValueError):
        resolve.resolve("https://example.org/not-spotify")


def test_resolve_no_show_name_unavailable():
    # Spotify page without any show signal -> UNAVAILABLE, no false positive.
    html = '<html><meta property="og:title" content="Mystery"/></html>'
    client = make_client(spotify_html=html)
    res = resolve.resolve(SPOTIFY_URL, client=client)
    assert res.result.state == UNAVAILABLE
    assert "show name" in res.result.reason


def test_resolve_show_embed_fallback():
    """Episode ID that maps to a show: episode embed 404s, show embed works."""
    client = make_client_show_embed_fallback()
    res = resolve.resolve(SPOTIFY_URL, client=client)
    assert res.result is not None
    assert res.result.state == VERIFIED
    assert res.result.audio_url == "https://cdn.test/show/100.mp3"
    assert res.metadata.show_name == "The Test Show"
    assert res.metadata.episode_title == "Ep #100 - The Great Adventure"
    assert res.feed_url == FEED_URL