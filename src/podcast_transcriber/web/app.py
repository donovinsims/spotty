"""FastAPI web UI (Phase 2): HTMX job progress, transcript view, PWA-lite.

All business logic is delegated to the Phase 1 modules -- resolve(), the Store,
download_episode() and transcribe_job() -- nothing is re-implemented here.

Threading note: FastAPI runs sync routes in a threadpool, and sqlite3
connections are not thread-safe, so each thread gets its own Store instance on
the same database file (WAL allows concurrent readers + one writer).
"""

from __future__ import annotations

import html as html_mod
import logging
import re
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import (FileResponse, HTMLResponse, JSONResponse,
                               PlainTextResponse, RedirectResponse)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .. import __version__
from ..config import Config, get_config
from ..download import download_episode
from ..resolve import resolve as do_resolve
from ..store import (
    JOB_COMPLETE,
    JOB_FAILED,
    JOB_PENDING,
    JOB_QUEUED,
    JOB_RUNNING,
    Episode,
    Store,
    VERIFIED,
)
from ..transcribe import transcribe_job
from . import worker as worker_mod
from .auth import is_authorized, is_public_path, token_matches, unauthorized_response

log = logging.getLogger(__name__)

_WEB_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = _WEB_DIR / "templates"
STATIC_DIR = _WEB_DIR / "static"

#: statuses the detail page should keep polling for.
_POLLING_STATUSES = (JOB_PENDING, JOB_RUNNING, JOB_QUEUED)

# --------------------------------------------------------------------------- #
# thread-local Store instances (one per thread; sqlite3 is not thread-safe)
# --------------------------------------------------------------------------- #
_store_local = threading.local()


def _store_for(db_path) -> Store:
    store = getattr(_store_local, "store", None)
    if store is None or str(store.db_path) != str(Path(db_path)):
        store = Store(db_path)
        _store_local.store = store
    return store


# --------------------------------------------------------------------------- #
# display helpers
# --------------------------------------------------------------------------- #
def fmt_ts(seconds: Optional[float]) -> str:
    """Float seconds -> HH:MM:SS."""
    if not seconds:
        seconds = 0.0
    seconds = max(0.0, float(seconds))
    h, rem = divmod(int(seconds), 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def fmt_dt(iso: Optional[str]) -> str:
    """Trim an ISO timestamp to 'YYYY-MM-DD HH:MM' for display."""
    if not iso:
        return ""
    return iso[:16].replace("T", " ")


def fmt_srt(seconds: Optional[float]) -> str:
    if not seconds:
        seconds = 0.0
    seconds = max(0.0, float(seconds))
    ms = int(round((seconds - int(seconds)) * 1000))
    h, rem = divmod(int(seconds), 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _highlight_matches(segments: List[Dict[str, Any]], query: str) -> List[Dict[str, Any]]:
    """Segments containing `query`, with matches wrapped in <mark> (escaped).

    Matching happens against the RAW text (so entities like ``&`` match), then
    the whole string is HTML-escaped once and the match boundaries -- marked
    with sentinel control characters that ``html.escape`` leaves untouched --
    become <mark> tags.  This keeps both the surrounding text and the match
    itself safely escaped for ``|safe`` rendering.
    """
    query = (query or "").strip()
    if not query:
        return []
    lowered = query.lower()
    pattern = re.compile(re.escape(query), re.IGNORECASE)
    out = []
    for seg in segments:
        text = seg.get("text") or ""
        if lowered not in text.lower():
            continue
        marked = pattern.sub(lambda m: "\x00" + m.group(0) + "\x01", text)
        highlighted = (
            html_mod.escape(marked)
            .replace("\x00", "<mark>")
            .replace("\x01", "</mark>")
        )
        out.append(
            {
                "start_time": seg.get("start_time"),
                "end_time": seg.get("end_time"),
                "text": text,
                "highlighted": highlighted,
            }
        )
    return out


#: Query params dropped before storing an episode URL so the same episode
#: pasted with different share/tracking parameters maps to one Episode row
#: (episodes.url has ON CONFLICT(url) dedup).
_TRACKING_PARAMS = {
    "si", "gclid", "fbclid", "dclid", "msclkid", "mc_cid", "mc_eid",
    "igshid", "s_kwcid", "wt_mc", "yclid",
}


def canonical_episode_url(url: str) -> str:
    """Strip tracking params (Spotify si=, utm_*, click IDs) from an episode URL.

    Keeps every other query param so the URL stays functionally equivalent.
    """
    try:
        parts = urlsplit(url)
    except ValueError:
        return url
    if not parts.query:
        return url
    keep = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if k.lower() not in _TRACKING_PARAMS and not k.lower().startswith("utm_")
    ]
    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urlencode(keep), parts.fragment)
    )


# --------------------------------------------------------------------------- #
# app factory
# --------------------------------------------------------------------------- #
def create_app(
    *,
    store: Optional[Store] = None,
    cfg: Optional[Config] = None,
    resolve_func: Callable = do_resolve,
    download_func: Callable = download_episode,
    transcribe_func: Callable = transcribe_job,
) -> FastAPI:
    """Build the Phase 2 web application.

    ``store``/``cfg`` pin the database + configuration (tests inject a tmp-path
    store); the *_func arguments let tests mock resolve/download/transcribe so
    the suite never touches the network or the MLX model.
    """
    cfg = cfg or get_config()
    db_path = store.db_path if store is not None else cfg.db_path

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Crash recovery: a RUNNING job left behind by a killed process would
        # otherwise deadlock the single-active-job slot forever (partial unique
        # index).  Safe under the single-writer-per-DB assumption -- at this
        # point no other process is mid-transcription against this database.
        try:
            recover = Store(db_path)
            try:
                n = recover.recover_stale_running()
                if n:
                    log.warning("recovered %d stale RUNNING job(s) -> PENDING", n)
            finally:
                recover.close()
        except Exception:  # noqa: BLE001 - startup must not fail on a sweep
            log.exception("stale-RUNNING recovery sweep failed")

        w = worker_mod.get_worker(
            db_path,
            cfg,
            download_func=download_func,
            transcribe_func=transcribe_func,
        )
        app.state.worker = w
        w.start()
        try:
            yield
        finally:
            worker_mod.stop_worker(db_path, timeout=cfg.worker_stop_timeout)

    app = FastAPI(title="podcast-transcriber", lifespan=lifespan)
    app.state.db_path = db_path
    app.state.cfg = cfg
    app.state.resolve_func = resolve_func

    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    templates.env.filters["ts"] = fmt_ts
    templates.env.filters["dt"] = fmt_dt
    templates.env.globals["auth_enabled"] = bool(cfg.auth_token)
    templates.env.globals["app_version"] = __version__
    app.state.templates = templates

    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/manifest.webmanifest")
    def manifest():
        return FileResponse(STATIC_DIR / "manifest.webmanifest",
                            media_type="application/manifest+json")

    @app.get("/sw.js")
    def sw():
        return FileResponse(STATIC_DIR / "sw.js", media_type="application/javascript")

    # ------------------------------------------------------------------ #
    # helpers
    # ------------------------------------------------------------------ #
    def store() -> Store:
        return _store_for(app.state.db_path)

    def render(name: str, request: Request, context: Optional[dict] = None,
               status_code: int = 200):
        return templates.TemplateResponse(request, name, context or {},
                                          status_code=status_code)

    def status_view(job) -> Dict[str, Any]:
        s = store()
        cps = s.checkpoints_for_job(job.id)  # type: ignore[arg-type]
        done = sum(1 for c in cps if c.get("status") == "done")
        total = job.chunk_count or 0
        pct = round(done / total * 100) if total else 0
        segs = s.segments_for_job(job.id) if job.status == JOB_COMPLETE else []  # type: ignore[arg-type]
        return {
            "job": job,
            "chunks_done": done,
            "chunks_total": total,
            "progress_pct": min(pct, 100),
            "last_progress": worker_mod.progress_for(job.id or 0),
            "segments_count": len(segs),
            "active": job.status in _POLLING_STATUSES,
        }

    def job_or_404(job_id: int):
        job = store().get_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
        return job

    def submit_area(
        request: Request,
        *,
        submitted_url: str = "",
        result: Optional[Dict[str, Any]] = None,
    ):
        return render("fragments/submit_area.html", request, {
            "submitted_url": submitted_url,
            "result": result,
        })

    # ------------------------------------------------------------------ #
    # optional single-user auth (PT_AUTH_TOKEN; Phase 3)
    # ------------------------------------------------------------------ #
    auth_token: Optional[str] = cfg.auth_token
    if auth_token:
        @app.middleware("http")
        async def require_auth(request: Request, call_next):
            if is_public_path(request.url.path) or is_authorized(request, auth_token):
                return await call_next(request)
            return unauthorized_response(request)

    # ------------------------------------------------------------------ #
    # routes
    # ------------------------------------------------------------------ #
    @app.get("/healthz")
    def healthz():
        """Liveness + DB reachability probe (always public)."""
        db_ok = store().ping()
        payload = {
            "status": "ok",
            "version": __version__,
            "db": "ok" if db_ok else "error",
        }
        return JSONResponse(payload, status_code=200 if db_ok else 503)

    @app.get("/login")
    def login_page(request: Request):
        if not auth_token:
            return RedirectResponse("/", status_code=302)
        return render("login.html", request, {"error": None})

    @app.post("/login")
    def login_submit(request: Request, token: str = Form("")):
        if not auth_token:
            return RedirectResponse("/", status_code=302)
        if not token_matches(token, auth_token):
            return render("login.html", request,
                          {"error": "Invalid token — try again."}, status_code=401)
        # Only allow local relative redirects (no open-redirect via next=).
        next_url = request.query_params.get("next", "/")
        if not next_url.startswith("/") or next_url.startswith("//"):
            next_url = "/"
        response = RedirectResponse(next_url, status_code=302)
        response.set_cookie(
            "pt_token", auth_token, httponly=True, samesite="lax",
            max_age=60 * 60 * 24 * 30,  # 30 days
        )
        return response

    @app.post("/logout")
    def logout():
        response = RedirectResponse("/login", status_code=302)
        response.delete_cookie("pt_token")
        return response

    @app.get("/")
    def index(request: Request):
        return render("index.html", request)

    @app.post("/jobs")
    def create_job(request: Request, url: str = Form(...)):
        cfg = app.state.cfg
        url = url.strip()
        try:
            res = app.state.resolve_func(
                url, top_results=cfg.top_results, duration_tolerance=cfg.duration_tolerance
            )
        except ValueError as exc:
            return submit_area(request, submitted_url=url, result={
                "kind": "error",
                "headline": "Not a Spotify episode URL",
                "message": str(exc),
            })
        except Exception:  # noqa: BLE001 - network/resolver failure
            # Do not surface the raw exception (it can contain internal URLs /
            # hostnames); log the detail server-side instead.
            log.exception("resolution failed for %r", url)
            return submit_area(request, submitted_url=url, result={
                "kind": "error",
                "headline": "Resolution failed",
                "message": (
                    "Could not resolve that episode. Check the URL and try "
                    "again — the server log has the technical detail."
                ),
            })

        result = res.result
        if result is None or result.state != VERIFIED:
            state = result.state if result is not None else "UNAVAILABLE"
            kind = "warn" if state == "REVIEW_REQUIRED" else "error"
            headline = {
                "REVIEW_REQUIRED": "Manual review required — no job created",
                "UNAVAILABLE": "Episode unavailable — no job created",
            }.get(state, f"{state} — no job created")
            return submit_area(request, submitted_url=url, result={
                "kind": kind,
                "headline": headline,
                "message": result.reason if result is not None else "No result.",
                "candidates": [c.__dict__ for c in (result.candidates if result else [])],
            })

        meta = res.metadata
        ep = Episode(
            spotify_id=res.spotify_id,
            # Store the canonical URL (tracking params stripped) so the same
            # episode pasted with/without ?si=... dedups to one row.
            url=canonical_episode_url(res.source_url),
            title=meta.episode_title,
            show_name=meta.show_name,
            rss_url=res.feed_url,
            audio_url=result.audio_url,
            duration_seconds=meta.duration_seconds,
            state=result.state,
            confidence=result.confidence,
            reason=result.reason,
            candidates=[c.__dict__ for c in result.candidates],
        )
        s = store()
        episode_id = s.upsert_episode(ep)
        job = s.create_job_queued(episode_id, model=cfg.model, chunk_minutes=cfg.chunk_minutes)

        # Kick the in-process worker (idempotent) and hand off to the job page.
        app.state.worker.start()
        response = job_detail(request, job.id)  # type: ignore[misc]
        response.headers["HX-Redirect"] = f"/jobs/{job.id}"
        return response

    @app.get("/jobs")
    def jobs_list(request: Request):
        s = store()
        jobs = s.list_jobs_by_created(limit=100)
        rows = [(j, s.get_episode(j.episode_id)) for j in jobs]  # type: ignore[arg-type]
        return render("jobs_list.html", request, {"rows": rows})

    @app.get("/jobs/{job_id}")
    def job_detail(request: Request, job_id: int):
        job = job_or_404(job_id)
        s = store()
        episode = s.get_episode(job.episode_id)  # type: ignore[arg-type]
        return render("job_detail.html", request, {
            "job": job,
            "episode": episode,
            "view": status_view(job),
        })

    @app.get("/jobs/{job_id}/status")
    def job_status(request: Request, job_id: int):
        job = job_or_404(job_id)
        return render("fragments/status.html", request, {
            "job": job,
            "view": status_view(job),
        })

    @app.get("/jobs/{job_id}/transcript")
    def transcript(request: Request, job_id: int):
        job = job_or_404(job_id)
        s = store()
        episode = s.get_episode(job.episode_id)  # type: ignore[arg-type]
        segments = s.segments_for_job(job_id)  # type: ignore[arg-type]
        tx = s.get_transcript(job_id)
        return render("transcript.html", request, {
            "job": job,
            "episode": episode,
            "segments": segments,
            "tx": tx,
        })

    @app.post("/jobs/{job_id}/transcript/search")
    def transcript_search(request: Request, job_id: int, q: str = Form("")):
        job_or_404(job_id)
        segments = store().segments_for_job(job_id)  # type: ignore[arg-type]
        matches = _highlight_matches(segments, q)
        return render("fragments/search_results.html", request, {
            "q": q.strip(),
            "matches": matches,
        })

    @app.get("/jobs/{job_id}/transcript/download")
    def transcript_download(job_id: int):
        job = job_or_404(job_id)
        s = store()
        episode = s.get_episode(job.episode_id)  # type: ignore[arg-type]
        segments = s.segments_for_job(job_id)  # type: ignore[arg-type]
        lines = [
            f"Title: {episode.title if episode else ''}",
            f"Show: {episode.show_name if episode else ''}",
            f"Source: {episode.url if episode else ''}",
            f"Job: {job.id}",
            "",
        ]
        for seg in segments:
            lines.append(f"[{fmt_ts(seg.get('start_time'))}] {seg.get('text') or ''}")
        body = "\n".join(lines) + "\n"
        return PlainTextResponse(
            body,
            media_type="text/plain; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="transcript-{job.id}.txt"'},
        )

    @app.get("/jobs/{job_id}/transcript/srt")
    def transcript_srt(job_id: int):
        job = job_or_404(job_id)
        segments = store().segments_for_job(job_id)  # type: ignore[arg-type]
        blocks = []
        for i, seg in enumerate(segments, start=1):
            blocks.append(
                f"{i}\n{fmt_srt(seg.get('start_time'))} --> {fmt_srt(seg.get('end_time'))}\n"
                f"{seg.get('text') or ''}\n"
            )
        body = "\n".join(blocks)
        return PlainTextResponse(
            body,
            media_type="text/plain; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="transcript-{job.id}.srt"'},
        )

    @app.get("/search")
    def episode_search(request: Request, q: str = ""):
        q = q.strip()
        s = store()
        episodes = s.find_episodes(q) if q else []
        # newest job id per episode, for quick navigation
        job_by_episode: Dict[int, int] = {}
        if episodes:
            for j in s.list_jobs_by_created(limit=500):
                if j.episode_id is not None and j.episode_id not in job_by_episode:
                    job_by_episode[j.episode_id] = j.id  # type: ignore[assignment]
        return render("fragments/episode_results.html", request, {
            "q": q,
            "episodes": episodes,
            "ep_jobs": job_by_episode,
        })

    # ------------------------------------------------------------------ #
    # error handlers (HTMX-aware: fragments for htmx requests)
    # ------------------------------------------------------------------ #
    def _error_response(request: Request, status_code: int, detail: str,
                        status: int) -> HTMLResponse:
        """Render error.html (full page) or the error fragment for htmx."""
        template = (
            "fragments/error.html"
            if request.headers.get("HX-Request")
            else "error.html"
        )
        return templates.TemplateResponse(
            request,
            template,
            {"status_code": status_code, "detail": detail},
            status_code=status,
        )

    @app.exception_handler(HTTPException)
    def http_exception_handler(request: Request, exc: HTTPException):
        if exc.status_code in (404, 500):
            return _error_response(request, exc.status_code, str(exc.detail),
                                   exc.status_code)
        return HTMLResponse(
            f"<h1>{exc.status_code}</h1><p>{html_mod.escape(str(exc.detail))}</p>",
            status_code=exc.status_code,
        )

    @app.exception_handler(RequestValidationError)
    def validation_exception_handler(request: Request, exc: RequestValidationError):
        log.warning("validation error on %s: %s", request.url.path, exc.errors())
        return _error_response(request, 422, "Invalid request parameters.", 422)

    @app.exception_handler(Exception)
    def unhandled_exception_handler(request: Request, exc: Exception):
        # Log the full traceback; the client sees only a generic message.
        log.exception("unhandled error on %s", request.url.path)
        return _error_response(request, 500, "Internal server error.", 500)

    return app
