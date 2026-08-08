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

import ipaddress
import json
import logging
import os
import shutil
import socket
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

#: SSRF/size-limit configuration.
_MAX_REDIRECTS = 5
DEFAULT_MAX_DOWNLOAD_BYTES = 1 << 30  # 1 GiB
MAX_DOWNLOAD_BYTES_ENV = "PT_MAX_DOWNLOAD_BYTES"


class DownloadError(RuntimeError):
    pass


def _max_download_bytes() -> int:
    """Read PT_MAX_DOWNLOAD_BYTES (bytes); default 1 GiB."""
    raw = os.getenv(MAX_DOWNLOAD_BYTES_ENV)
    if raw is None or not raw.strip():
        return DEFAULT_MAX_DOWNLOAD_BYTES
    try:
        return max(1, int(raw))
    except ValueError:
        log.warning("invalid %s=%r; using default %d",
                    MAX_DOWNLOAD_BYTES_ENV, raw, DEFAULT_MAX_DOWNLOAD_BYTES)
        return DEFAULT_MAX_DOWNLOAD_BYTES


def _uses_mock_transport(client: httpx.Client) -> bool:
    """True when the client is wired to httpx.MockTransport.

    Test seam: MockTransport never touches the network, so there is no SSRF
    risk and the hostname cannot be resolved through real DNS anyway.  IP
    literals are still checked (the guard never needs DNS for those).
    """
    return isinstance(getattr(client, "_transport", None), httpx.MockTransport)


def _assert_public_url(url: str, *, resolve: bool = True) -> None:
    """SSRF guard: refuse to download from non-public hosts.

    Hostnames are resolved via DNS and *every* resolved address must be a
    global public IP (loopback, private, link-local, unspecified, multicast,
    reserved, CGNAT, ... are all refused).  When ``resolve`` is False (mock
    transport), only IP-literal hosts are checked.
    """
    try:
        parsed = httpx.URL(url)
    except ValueError:
        raise DownloadError(f"invalid download URL: {url}") from None
    host = parsed.host
    if not host:
        raise DownloadError(f"download URL has no host: {url}")

    # IP literals are checked directly; no DNS needed.
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None
    if ip is not None:
        if not _is_public_ip(ip):
            raise DownloadError(
                f"refusing to download from non-public address {host}"
            )
        return

    if not resolve:
        return  # mock transport: hostname is fake, never actually connected

    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise DownloadError(f"cannot resolve host {host!r}: {exc}") from exc
    for info in infos:
        try:
            addr = ipaddress.ip_address(info[4][0])
        except ValueError:
            continue
        if not _is_public_ip(addr):
            raise DownloadError(
                f"refusing to download from non-public address {addr} ({host})"
            )


def _is_public_ip(ip: ipaddress._BaseAddress) -> bool:
    """True only for global-scope public addresses.

    ``is_global`` alone is not enough (multicast 224/4 reports is_global=True
    on some Python versions), so check the named ranges explicitly as well.
    """
    return not (
        ip.is_loopback
        or ip.is_private
        or ip.is_link_local
        or ip.is_unspecified
        or ip.is_multicast
        or ip.is_reserved
        or not ip.is_global
    )


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
    max_bytes: int,
    resolve_ips: bool = True,
) -> Path:
    """Stream body into dest (atomically via .part); returns final path.

    Redirects are followed manually so the SSRF guard is re-applied to every
    hop (including the final URL) BEFORE any connection is made, and the body
    is capped at ``max_bytes`` (checked against Content-Length and while
    streaming, in case the server lies or omits it).

    The extension is refined from the response Content-Type once headers arrive,
    so ``<dest>`` may be renamed (e.g. URL says .mp4 but body is audio/mpeg).
    """
    current = url
    for _hop in range(_MAX_REDIRECTS + 1):
        _assert_public_url(current, resolve=resolve_ips)
        with http.stream("GET", current, follow_redirects=False, timeout=timeout) as resp:
            if resp.is_redirect and "location" in resp.headers:
                target = str(resp.url.join(resp.headers["location"]))
                try:
                    scheme = httpx.URL(target).scheme
                except ValueError:
                    scheme = ""
                if scheme not in ("http", "https"):
                    raise DownloadError(
                        f"redirect to unsupported scheme '{scheme}': {target}"
                    )
                current = target
                continue
            resp.raise_for_status()
            total = int(resp.headers.get("content-length", "0") or 0)
            if max_bytes and total > max_bytes:
                raise DownloadError(
                    f"download of {current} exceeds {max_bytes} byte limit "
                    f"(content-length {total})"
                )
            ext = extension_for(current, resp.headers.get("content-type"))
            dest = dest.with_suffix(ext)
            tmp = dest.with_name(dest.name + ".part")
            tmp.parent.mkdir(parents=True, exist_ok=True)
            written = 0
            with open(tmp, "wb") as fh:
                for chunk in resp.iter_bytes(chunk_size=DEFAULT_CHUNK_BYTES):
                    fh.write(chunk)
                    written += len(chunk)
                    if max_bytes and written > max_bytes:
                        raise DownloadError(
                            f"download exceeded {max_bytes} byte limit"
                        )
                    if progress is not None:
                        progress(f"  downloaded {written}/{total} bytes")
            tmp.replace(dest)
            return dest
    raise DownloadError(f"too many redirects downloading {url}")


def download_episode(
    store: Store,
    episode_id: int,
    audio_dir,
    *,
    ffprobe_bin: str = FFPROBE,
    progress: Optional[object] = None,
    client: Optional[httpx.Client] = None,
    timeout: Optional[float] = 60.0,
    max_bytes: Optional[int] = None,
) -> Dict[str, object]:
    """Download an episode's audio + ensure a PENDING job. Returns a summary dict.

    ``max_bytes`` caps the streamed body (default: PT_MAX_DOWNLOAD_BYTES, 1 GiB).
    SSRF guard: every connection target (including redirect hops) must resolve
    to public IPs only.
    """
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
    cap = _max_download_bytes() if max_bytes is None else max_bytes
    resolve_ips = not _uses_mock_transport(http)

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
                dest = _stream_body(http, url, dest, progress=progress,
                                    timeout=timeout, max_bytes=cap,
                                    resolve_ips=resolve_ips)
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