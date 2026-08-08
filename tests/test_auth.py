"""Phase 3 tests: optional auth middleware + healthz + new config fields.

Auth-on and auth-off modes are both covered, fully offline (no launchd, no
tailscale, no network).  The web worker runs against a tmp-path SQLite DB.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
import pytest

from podcast_transcriber.config import Config
from podcast_transcriber.resolve import Resolution, SpotifyMeta
from podcast_transcriber.store import Store
from podcast_transcriber.verify import VERIFIED, Candidate, VerificationResult
from podcast_transcriber.web import create_app
from podcast_transcriber.web.auth import (
    is_public_path,
    token_from_request,
    token_matches,
)

URL1 = "https://open.spotify.com/episode/authauthaa"
TOKEN = "test-super-secret-token"


def make_app(store: Store, tmp_path, token: str | None = None, **overrides):
    cfg = Config(data_dir=str(tmp_path / "data"), auth_token=token)
    kwargs = dict(
        resolve_func=lambda url, **kw: Resolution(
            spotify_id="abc",
            source_url=url,
            metadata=SpotifyMeta(spotify_id="abc", url=url,
                                 episode_title="Auth Ep", show_name="S",
                                 duration_seconds=60.0),
            feed_url="https://feed.example.test/rss",
            result=VerificationResult(
                state=VERIFIED, confidence=0.99, reason="ok",
                audio_url="https://cdn.example.test/ep.mp3",
                matched_title="Auth Ep",
                candidates=[Candidate(audio_url="https://cdn.example.test/ep.mp3",
                                      title="Auth Ep", confidence=0.99)],
            ),
        ),
        download_func=lambda *a, **kw: {"episode_id": a[1], "audio_path": "/x"},
        transcribe_func=lambda *a, **kw: {"job_id": a[1]},
    )
    kwargs.update(overrides)
    return create_app(store=store, cfg=cfg, **kwargs)


# --------------------------------------------------------------------------- #
# config: PT_HOST / PT_PORT / PT_AUTH_TOKEN
# --------------------------------------------------------------------------- #
def test_config_defaults():
    cfg = Config()
    assert cfg.host == "127.0.0.1"
    assert cfg.port == 8765
    assert cfg.auth_token is None


def test_config_auth_token_empty_string_means_no_auth():
    assert Config(auth_token="").auth_token is None
    assert Config(auth_token=None).auth_token is None


def test_config_env_overrides(monkeypatch):
    monkeypatch.setenv("PT_HOST", "0.0.0.0")
    monkeypatch.setenv("PT_PORT", "9000")
    monkeypatch.setenv("PT_AUTH_TOKEN", "env-token")
    cfg = Config()
    assert cfg.host == "0.0.0.0"
    assert cfg.port == 9000
    assert cfg.auth_token == "env-token"


def test_config_explicit_args_win_over_env(monkeypatch):
    monkeypatch.setenv("PT_HOST", "0.0.0.0")
    monkeypatch.setenv("PT_PORT", "9000")
    monkeypatch.setenv("PT_AUTH_TOKEN", "env-token")
    cfg = Config(host="127.0.0.1", port=8765, auth_token="arg-token")
    assert cfg.host == "127.0.0.1"
    assert cfg.port == 8765
    assert cfg.auth_token == "arg-token"


def test_config_invalid_port_raises(monkeypatch):
    monkeypatch.setenv("PT_PORT", "not-a-number")
    with pytest.raises(ValueError):
        Config()


# --------------------------------------------------------------------------- #
# auth helpers
# --------------------------------------------------------------------------- #
def test_token_matches_constant_time():
    assert token_matches("abc", "abc") is True
    assert token_matches("abc", "abd") is False
    assert token_matches("", "abc") is False
    assert token_matches("abc", "") is False
    assert token_matches(None, "abc") is False
    assert token_matches("abc", None) is False


def test_token_from_request_bearer_header(store, tmp_path):
    with TestClient(make_app(store, tmp_path, token=TOKEN)) as client:
        r = client.get("/", headers={"Authorization": f"Bearer {TOKEN}"})
    assert r.status_code == 200


def test_token_from_request_query_param(store, tmp_path):
    with TestClient(make_app(store, tmp_path, token=TOKEN)) as client:
        r = client.get(f"/?token={TOKEN}")
    assert r.status_code == 200


def test_is_public_path():
    assert is_public_path("/healthz") is True
    assert is_public_path("/static/style.css") is True
    assert is_public_path("/login") is True
    assert is_public_path("/logout") is True
    assert is_public_path("/") is False
    assert is_public_path("/jobs/1/transcript/download") is False


# --------------------------------------------------------------------------- #
# healthz (always public)
# --------------------------------------------------------------------------- #
def test_healthz_open_without_auth(store, tmp_path):
    with TestClient(make_app(store, tmp_path)) as client:
        r = client.get("/healthz")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["db"] == "ok"
    assert body["version"]


def test_healthz_open_with_auth_enabled(store, tmp_path):
    with TestClient(make_app(store, tmp_path, token=TOKEN)) as client:
        r = client.get("/healthz")  # no token at all
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


# --------------------------------------------------------------------------- #
# auth OFF: current single-user behaviour
# --------------------------------------------------------------------------- #
def test_no_auth_mode_all_routes_open(store, tmp_path):
    with TestClient(make_app(store, tmp_path)) as client:
        assert client.get("/").status_code == 200
        assert client.get("/jobs").status_code == 200
        assert client.get("/static/style.css").status_code == 200
        # /login just bounces to / when auth is disabled
        assert client.get("/login", follow_redirects=False).status_code == 302
        assert client.post("/login", data={"token": "x"},
                           follow_redirects=False).status_code == 302


# --------------------------------------------------------------------------- #
# auth ON: unauthenticated requests
# --------------------------------------------------------------------------- #
def test_auth_on_browser_get_redirects_to_login(store, tmp_path):
    with TestClient(make_app(store, tmp_path, token=TOKEN)) as client:
        r = client.get("/", follow_redirects=False,
                       headers={"accept": "text/html"})
    assert r.status_code == 302
    assert r.headers["location"].startswith("/login?next=")


def test_auth_on_bearer_header_grants_access(store, tmp_path):
    with TestClient(make_app(store, tmp_path, token=TOKEN)) as client:
        r = client.get("/", headers={"Authorization": f"Bearer {TOKEN}"})
    assert r.status_code == 200
    assert "Spotify episode URL" in r.text


def test_auth_on_wrong_token_rejected(store, tmp_path):
    with TestClient(make_app(store, tmp_path, token=TOKEN)) as client:
        r = client.get("/", headers={"Authorization": "Bearer wrong-token",
                                     "accept": "text/html"},
                       follow_redirects=False)
    assert r.status_code in (302, 401)


def test_auth_on_api_post_without_token_is_401_json(store, tmp_path):
    with TestClient(make_app(store, tmp_path, token=TOKEN)) as client:
        r = client.post("/jobs", data={"url": URL1},
                        headers={"accept": "application/json"})
    assert r.status_code == 401
    assert r.json()["detail"] == "Unauthorized"


def test_auth_on_htmx_unauthorized_gets_redirect_header(store, tmp_path):
    with TestClient(make_app(store, tmp_path, token=TOKEN)) as client:
        r = client.post("/jobs", data={"url": URL1},
                        headers={"hx-request": "true"})
    assert r.status_code == 401
    assert r.headers.get("hx-redirect") == "/login"


def test_auth_on_authenticated_api_post_works(store, tmp_path):
    with TestClient(make_app(store, tmp_path, token=TOKEN)) as client:
        r = client.post("/jobs", data={"url": URL1},
                        headers={"Authorization": f"Bearer {TOKEN}"})
    assert r.status_code == 200
    assert r.headers.get("hx-redirect") is not None  # job created


def test_auth_on_static_assets_open(store, tmp_path):
    with TestClient(make_app(store, tmp_path, token=TOKEN)) as client:
        r = client.get("/static/style.css")
    assert r.status_code == 200


# --------------------------------------------------------------------------- #
# auth ON: login / logout cookie flow
# --------------------------------------------------------------------------- #
def test_login_flow_sets_cookie_and_grants_access(store, tmp_path):
    with TestClient(make_app(store, tmp_path, token=TOKEN)) as client:
        # browser GET / -> login page
        r = client.get("/", follow_redirects=False,
                       headers={"accept": "text/html"})
        login_url = r.headers["location"]
        assert login_url.startswith("/login")

        # login page renders
        page = client.get("/login")
        assert page.status_code == 200
        assert "Sign in" in page.text

        # wrong token -> 401, no cookie
        bad = client.post(login_url, data={"token": "nope"})
        assert bad.status_code == 401
        assert "Invalid token" in bad.text

        # right token -> 302 + Set-Cookie
        good = client.post(login_url, data={"token": TOKEN},
                           follow_redirects=False)
        assert good.status_code == 302
        assert good.headers["location"] == "/"
        assert "pt_token" in good.headers["set-cookie"]

        # cookie now grants access
        authed = client.get("/")
        assert authed.status_code == 200


def test_logout_clears_cookie(store, tmp_path):
    with TestClient(make_app(store, tmp_path, token=TOKEN)) as client:
        client.post("/login", data={"token": TOKEN})
        assert client.get("/").status_code == 200
        out = client.post("/logout", follow_redirects=False)
        assert out.status_code == 302
        assert client.get("/", follow_redirects=False,
                          headers={"accept": "text/html"}).status_code == 302


def test_login_next_redirect_stays_local(store, tmp_path):
    with TestClient(make_app(store, tmp_path, token=TOKEN)) as client:
        # absolute / protocol-relative next values are ignored
        evil = client.post("/login?next=//evil.example", data={"token": TOKEN},
                           follow_redirects=False)
        assert evil.headers["location"] == "/"
        local = client.post("/login?next=/jobs/3", data={"token": TOKEN},
                            follow_redirects=False)
        assert local.headers["location"] == "/jobs/3"
