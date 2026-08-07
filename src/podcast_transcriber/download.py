"""Phase 1 audio download: fetch an episode's enclosure URL into a local dir.

The resolver stores the audio *enclosure URL* in ``episodes.audio_url``, but
transcription needs a local decodable file.  ``download_episode``:

  1. Reads the episode's audio_url.
  2. If it is already a local path (or file://), skips the network fetch.
  3. Otherwise streams the URL via httpx into ``<audio_dir>/<episode_id><ext>``
     (rejecting non-http(s) schemes), verifying redirects + http errors.
  4. Verifies the result is decodable audio via ffprobe.
  5. Points ``episodes.audio_url`` at the local path.
  6. Creates a PENDING job for the episode if it does not already have one.

All HTTP goes through an injectable :class:`httpx.Client` so tests can use
``httpx.MockTransport`` with zero network.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from pathlib import Path
from typing import Dict, Optional

import httpx

from .store import JOB_PENDING, Store

log = logging.getLogger(__name__)

FFPROBE = "/opt/homebrew/bin/ffprobe"

#: Audio file extensions we trust as-is; anything else / unknown -> .mp3.
_AUDIO_EXTS = {
    ".mp3", ".m4a", ".wav", ".ogg", ".opus", ".aac", ".flac", ".wma",
    ".wav", ".caf", ".m4b", ".mp4",
}
_MIME_EXT = {
    "audio/mpeg": ".mp3",
    "audio/mp3": ".mp3",
    "audio/x-m4a": ".m4a",
    "audio/mp4": ".m4a",
    "audio/aac": ".aac",
    "audio/x-aac": ".aac",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/wave": ".wav",
    "audio/ogg": ".ogg",
    "application/ogg": ".ogg",
    "audio/opus": ".opus",
    "audio/flac": ".flac",
}

DEFAULT_CHUNK_BYTES = 1 << 20  # 1 MiB streamed read buffer


class DownloadError(RuntimeError):
    pass


def is_local_audio_url(url: str) -> bool:
    """True when `url` is a filesystem path (or file://), not a remote URL."""
    if url.startswith("file://"):
        return True
    try:
        scheme = httpx.URL(url).scheme
    except ValueError:
        return True
    # A bare path like /tmp/x.wav or a relative file has an empty scheme.
    return not scheme


def extension_for(url: str, content_type: Optional[str] = None) -> str:
    """Choose a sensible extension from the URL path, then the Content-Type."""
    try:
        path_ext = Path(httpx.URL(url).path).suffix.lower()
    except ValueError:
        path_ext = ""
    if path_ext in _AUDIO_EXTS:
        return path_ext
    if content_type:
        base = content_type.split(";")[0].strip().lower()
        if base in _MIME_EXT:
            return _MIME_EXT[base]
    return ".mp3"


def verify_audio(path: str, ffprobe_bin: str = FFPROBE) -> float:
    """Confirm `path` decodes as audio; return its duration in seconds."""
    probe = shutil.which("ffprobe") or ffprobe_bin
    if not Path(probe).exists():
        raise DownloadError(
            "ffprobe not found; install ffmpeg (provides ffprobe on PATH or "
            f"at {FFPROBE}) to verify downloaded audio"
        )
    try:
        res = subprocess.run(
            [probe, "-v", "error", "-show_entries", "format=duration",
             "-of", "json", str(path)],
            capture_output=True, text=True, timeout=30,
        )
    except FileNotFoundError:
        raise DownloadError(
            "ffprobe not found; install ffmpeg (provides ffprobe) on PATH"
        ) from None
    if res.returncode != 0:
        raise DownloadError(
            f"downloaded audio is not decodable: {path} "
            f"({res.stderr.strip() or 'ffprobe error'})"
        )
    try:
        data = json.loads(res.stdout or "{}")
    except json.JSONDecodeError:
        data = {}
    duration = (data.get("format") or {}).get("duration")
    if duration is None:
        raise DownloadError(f"downloaded audio has no duration: {path}")
    try:
        return float(duration)
    except (TypeError, ValueError):
        raise DownloadError(f"downloaded audio has invalid duration: {duration}") from None


def _stream_body(
    http: httpx.Client,
    url: str,
    dest: Path,
    *,
    progress: Optional[object],
    timeout: Optional[float],
) -> Path:
    """Stream body into dest (atomically via .part); returns final path.

    The extension is refined from the response Content-Type once headers arrive,
    so ``<dest>`` may be renamed (e.g. URL says .mp4 but body is audio/mpeg).
    """
    with http.stream("GET", url, follow_redirects=True, timeout=timeout) as resp:
        resp.raise_for_status()
        total = int(resp.headers.get("content-length", "0") or 0)
        ext = extension_for(url, resp.headers.get("content-type"))
        dest = dest.with_suffix(ext)
        tmp = dest.with_name(dest.name + ".part")
        tmp.parent.mkdir(parents=True, exist_ok=True)
        written = 0
        with open(tmp, "wb") as fh:
            for chunk in resp.iter_bytes(chunk_size=DEFAULT_CHUNK_BYTES):
                fh.write(chunk)
                written += len(chunk)
                if progress is not None:
                    progress(f"  downloaded {written}/{total} bytes")
        tmp.replace(dest)
        return dest


def download_episode(
    store: Store,
    episode_id: int,
    audio_dir,
    *,
    ffprobe_bin: str = FFPROBE,
    progress: Optional[object] = None,
    client: Optional[httpx.Client] = None,
    timeout: Optional[float] = 60.0,
) -> Dict[str, object]:
    """Download an episode's audio + ensure a PENDING job. Returns a summary dict."""
    audio_dir = Path(audio_dir)
    ep = store.get_episode(episode_id)
    if ep is None:
        raise DownloadError(f"episode {episode_id} not found")
    url = ep.audio_url or ""
    if not url:
        raise DownloadError(
            f"episode {episode_id} has no audio_url; run `pt resolve <url> --store` first"
        )

    own_client = client is None
    http = client or httpx.Client(follow_redirects=True, timeout=timeout)

    def _note(msg: str) -> None:
        if progress is not None:
            progress(msg)

    try:
        if url.startswith("file://"):
            url = url[len("file://"):]

        if is_local_audio_url(url):
            _note(f"audio is already local, skipping download: {url}")
            local_path = url
        else:
            try:
                scheme = httpx.URL(url).scheme
            except ValueError:
                scheme = ""
            if scheme not in ("http", "https"):
                raise DownloadError(
                    f"unsupported audio URL scheme '{scheme}': {url}"
                )
            dest = audio_dir / f"{episode_id}{extension_for(url)}"
            _note(f"downloading {url}")
            try:
                dest = _stream_body(http, url, dest, progress=progress, timeout=timeout)
            except httpx.HTTPStatusError as exc:
                raise DownloadError(
                    f"download failed: HTTP {exc.response.status_code} for {url}"
                ) from exc
            except (httpx.TransportError, httpx.TimeoutException) as exc:
                raise DownloadError(f"download failed for {url}: {exc}") from exc
            except Exception as exc:  # noqa: BLE001 - surface a clear user error
                raise DownloadError(f"download failed for {url}: {exc}") from exc
            local_path = str(dest)
            _note(f"downloaded to {local_path}")

        duration = verify_audio(Path(local_path), ffprobe_bin)
        _note(f"verified audio ({duration:.1f}s): {local_path}")

        store.set_episode_audio_url(episode_id, local_path)
        ep.audio_url = local_path

        job = next(
            (j for j in store.list_jobs() if j.episode_id == episode_id), None
        )
        if job is None:
            job = store.create_job(episode_id)
    finally:
        if http is not None and client is None:
            http.close()

    return {
        "episode_id": episode_id,
        "audio_path": local_path,
        "duration": duration,
        "job": job,
    }