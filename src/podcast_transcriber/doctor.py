"""`pt doctor` preflight health checks (Phase 4).

Runs a battery of local checks and prints one line per check:

    [PASS] check name: detail
    [WARN] check name: detail      (non-fatal: tailnet/service/model optional)
    [FAIL] check name: detail      (fatal: exit code 1)

Exit code is 0 when every check PASSes, 1 when any check FAILs (WARNs never
fail the run).  Every check catches its own exceptions so one broken piece
cannot crash the whole doctor.

Checks are plain module-level functions so tests can monkeypatch them or the
helpers they call (shutil.disk_usage, subprocess, env) directly.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
import sys
from contextlib import closing
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from . import __version__
from .config import Config
from .store import JOB_RUNNING, Store

PASS = "PASS"
WARN = "WARN"
FAIL = "FAIL"

#: A health check returns (status, human-readable detail).
CheckResult = Tuple[str, str]

MIN_FREE_BYTES = 1024 ** 3  # 1 GiB
FFMPEG_DIRS = ("/opt/homebrew/bin", "/usr/local/bin")
TAILSCALE_BIN = "/Applications/Tailscale.app/Contents/MacOS/Tailscale"
LAUNCHD_LABEL = "com.podcasttranscriber.serve"

#: PT_* keys the .env check reports on (values masked, never printed).
PT_ENV_KEYS = (
    "PT_MODEL", "PT_DATA_DIR", "PT_HOST", "PT_PORT", "PT_AUTH_TOKEN",
    "PT_MAX_DOWNLOAD_BYTES", "PT_WORKER_STOP_TIMEOUT", "PT_CHUNK_MINUTES",
    "PT_TOP_RESULTS", "PT_DURATION_TOLERANCE", "PT_RATE_LIMIT_PER_MIN",
    "PT_MAX_QUEUED", "PT_TRUST_PROXY",
)

#: Keys whose VALUES are secret and must never appear in doctor output.
_SECRET_ENV = {"PT_AUTH_TOKEN"}


def _which(name: str) -> Optional[str]:
    """shutil.which plus a fixed lookup in the standard Homebrew locations."""
    found = shutil.which(name)
    if found:
        return found
    for d in FFMPEG_DIRS:
        candidate = Path(d) / name
        if candidate.is_file():
            return str(candidate)
    return None


def _ver_prefix(text: str) -> str:
    """'1.102.2-t6cac91817' -> '1.102.2' (empty when no version is present)."""
    match = re.match(r"(\d+\.\d+\.\d+)", text.strip())
    return match.group(1) if match else ""


def _run(cmd: List[str], timeout: float = 10.0) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


# --------------------------------------------------------------------------- #
# individual checks
# --------------------------------------------------------------------------- #
def check_python() -> CheckResult:
    """Python + venv sanity: mlx_whisper importable (or note model-only)."""
    py = f"python {sys.version.split()[0]}"
    try:
        import mlx_whisper  # noqa: F401 - importability is the point
        return PASS, f"{py} · mlx_whisper importable"
    except Exception as exc:  # noqa: BLE001 - report, never crash
        return WARN, (
            f"{py} · mlx_whisper NOT importable ({exc.__class__.__name__}); "
            "CLI/web transcription jobs will fail (model-dependent features only)"
        )


def check_ffmpeg() -> CheckResult:
    """ffmpeg + ffprobe on PATH or in the standard Homebrew location."""
    missing = [name for name in ("ffmpeg", "ffprobe") if _which(name) is None]
    if not missing:
        return PASS, "ffmpeg + ffprobe found"
    return FAIL, (
        f"missing: {', '.join(missing)} (checked PATH and {', '.join(FFMPEG_DIRS)})"
    )


def check_data_dir(cfg: Config) -> CheckResult:
    """Data dir writable + at least 1 GiB of free disk."""
    try:
        cfg.ensure_dirs()
    except Exception as exc:  # noqa: BLE001
        return FAIL, f"data dir {cfg.data_dir} not writable: {exc}"
    try:
        usage = shutil.disk_usage(cfg.data_dir)
    except Exception as exc:  # noqa: BLE001
        return FAIL, f"cannot stat disk for {cfg.data_dir}: {exc}"
    free_gib = usage.free / (1024 ** 3)
    if usage.free < MIN_FREE_BYTES:
        return FAIL, f"{cfg.data_dir} writable but only {free_gib:.1f} GiB free (< 1 GiB)"
    return PASS, f"{cfg.data_dir} writable · {free_gib:.1f} GiB free"


def check_env(cfg: Config) -> CheckResult:
    """.env loaded; which PT_* are set (secret values masked)."""
    set_keys: List[str] = []
    for key in PT_ENV_KEYS:
        value = os.getenv(key)
        if value is not None and value != "":
            set_keys.append(key if key not in _SECRET_ENV else f"{key}=<set, masked>")
    if not set_keys:
        return WARN, "no PT_* env vars set (.env not loaded? defaults in use)"
    return PASS, ".env loaded · " + ", ".join(set_keys)


def check_db(cfg: Config) -> CheckResult:
    """Open the Store, ping, report counts + schema version."""
    try:
        store = Store(cfg.db_path)
        try:
            ping = store.ping()
            schema = store.schema_version()
            with closing(store.connect()) as conn:
                episodes = conn.execute("SELECT COUNT(*) FROM episodes").fetchone()[0]
                jobs = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
        finally:
            store.close()
    except Exception as exc:  # noqa: BLE001
        return FAIL, f"cannot open DB {cfg.db_path}: {exc}"
    if not ping:
        return FAIL, f"DB {cfg.db_path} opened but ping failed"
    return PASS, f"schema v{schema} · {episodes} episode(s) · {jobs} job(s)"


def check_worker_state(cfg: Config) -> CheckResult:
    """RUNNING/PENDING/QUEUED jobs; flag possibly-stale RUNNING rows."""
    try:
        store = Store(cfg.db_path)
        try:
            running = [j for j in store.active_jobs() if j.status == JOB_RUNNING]
            waiting = store.count_queued_jobs()
        finally:
            store.close()
    except Exception as exc:  # noqa: BLE001
        return FAIL, f"cannot read job state: {exc}"
    if running:
        ids = ", ".join(str(j.id) for j in running)
        return WARN, (
            f"{len(running)} job(s) RUNNING (ids {ids}); if no transcription is "
            "actually running they are stale -- scripts/restart.sh recovers them"
        )
    if waiting:
        return PASS, f"no RUNNING job · {waiting} waiting (PENDING/QUEUED)"
    return PASS, "no active or queued jobs"


def check_tailscale(cfg: Config, ts_bin: Optional[str] = None) -> CheckResult:
    """Tailscale: up, single-version install, tunnel + MagicDNS functional,
    and our serve entry for cfg.port present.  WARN-only (never FAIL) so a
    broken tailnet cannot take the local app down.

    `tailscale status` can say "up" while the tunnel is half-broken (stale
    network extension / mixed installs): MagicDNS stops resolving and the
    data plane dies.  The extra probes below catch exactly that state.
    """
    ts_bin = ts_bin or os.getenv("TS_BIN") or TAILSCALE_BIN
    if not Path(ts_bin).is_file():
        return WARN, f"tailscale CLI not found at {ts_bin} (set TS_BIN to override)"
    try:
        status = _run([ts_bin, "status"])
    except Exception as exc:  # noqa: BLE001
        return WARN, f"tailscale status failed: {exc}"
    if status.returncode != 0:
        return WARN, "tailscale is not up (tailnet access unavailable; app still works locally)"

    problems: List[str] = []

    # Client vs daemon version mismatch: a mixed install (e.g. Homebrew CLI +
    # App Store app) is a known cause of a half-broken tunnel.  Compare only
    # the leading x.y.z -- the daemon prints its commit suffix.
    try:
        client = _run([ts_bin, "version"]).stdout or ""
        data = json.loads((_run([ts_bin, "status", "--json"]).stdout) or "{}")
        daemon = str(data.get("Version") or "")
        client_v, daemon_v = _ver_prefix(client), _ver_prefix(daemon)
        if client_v and daemon_v and client_v != daemon_v:
            problems.append(
                f"client {client_v} != daemon {daemon_v} (mixed Tailscale "
                "installs? quit the app, remove any Homebrew tailscale, restart)"
            )
    except Exception:  # noqa: BLE001 - never fail the check on a version hiccup
        pass

    # A tailnet IPv4 must be assigned; without one the tunnel has no data plane.
    ipv4 = _run([ts_bin, "ip", "-4"])
    if ipv4.returncode != 0 or not (ipv4.stdout or "").strip():
        problems.append("no tailnet IPv4 (tunnel not up)")

    # MagicDNS: resolve our own tailnet name.  When the network extension
    # fails to install the split-DNS entry, status says up but the hostname
    # does not resolve on this Mac.
    try:
        data = json.loads((_run([ts_bin, "status", "--json"]).stdout) or "{}")
        dns_name = str((data.get("Self") or {}).get("DNSName") or "").rstrip(".")
        if dns_name:
            socket.getaddrinfo(dns_name, None)
    except OSError:
        problems.append(
            "MagicDNS broken: our tailnet name does not resolve "
            "(quit + reopen the Tailscale app)"
        )
    except Exception:  # noqa: BLE001
        pass

    try:
        serve = _run([ts_bin, "serve", "status", "--json"])
        data = json.loads(serve.stdout or "{}")
        web = data.get("Web") or {}
        port_key = f":{cfg.port}"
        entry = next((k for k in web if k.endswith(port_key)), None)
    except Exception as exc:  # noqa: BLE001
        return WARN, f"tailscale up but serve status unreadable: {exc}"

    if not entry:
        problems.append(
            f"no serve entry for port {cfg.port} (run scripts/tailscale-serve.sh)"
        )
    base = (
        f"tailscale up · serve {entry} → http://127.0.0.1:{cfg.port}"
        if entry
        else "tailscale up"
    )
    if problems:
        return WARN, base + " · " + "; ".join(problems)
    return PASS, base


def check_launchd() -> CheckResult:
    """launchd service loaded + running (WARN, never FAIL)."""
    try:
        out = _run(["launchctl", "list"])
    except Exception as exc:  # noqa: BLE001
        return WARN, f"launchctl unavailable: {exc}"
    lines = [line for line in out.stdout.splitlines() if LAUNCHD_LABEL in line]
    if not lines:
        return WARN, f"launchd service {LAUNCHD_LABEL} not loaded (run scripts/install.sh)"
    pid = lines[0].split()[0]
    if pid and pid != "-":
        return PASS, f"launchd service {LAUNCHD_LABEL} loaded · running (pid {pid})"
    return WARN, f"launchd service {LAUNCHD_LABEL} loaded but not running"


def check_model_cache(cfg: Config) -> CheckResult:
    """Size of the local model cache under data/cache."""
    cache = cfg.cache_dir
    if not cache.exists():
        return PASS, f"model cache {cache} empty (nothing downloaded yet)"
    try:
        total = sum(
            f.stat().st_size for f in cache.rglob("*") if f.is_file()
        )
    except Exception as exc:  # noqa: BLE001
        return WARN, f"cannot size model cache {cache}: {exc}"
    return PASS, f"model cache {cache} · {total / (1024 ** 2):.1f} MiB"


# --------------------------------------------------------------------------- #
# runner
# --------------------------------------------------------------------------- #
def run_checks(
    cfg: Config,
    *,
    tailscale_bin: Optional[str] = None,
    out: Callable[[str], None] = print,
) -> int:
    """Run every check, print results, return the process exit code."""
    cfg.ensure_dirs()
    checks: List[Tuple[str, Callable[[], CheckResult]]] = [
        ("Python & venv", check_python),
        ("ffmpeg / ffprobe", check_ffmpeg),
        ("Data dir & disk", lambda: check_data_dir(cfg)),
        (".env / PT_* vars", lambda: check_env(cfg)),
        ("Database", lambda: check_db(cfg)),
        ("Worker state", lambda: check_worker_state(cfg)),
        ("Tailscale", lambda: check_tailscale(cfg, tailscale_bin)),
        ("launchd service", check_launchd),
        ("Model cache", lambda: check_model_cache(cfg)),
    ]
    counts = {PASS: 0, WARN: 0, FAIL: 0}
    out(f"podcast-transcriber doctor v{__version__}")
    out(f"data dir : {cfg.data_dir}")
    for name, fn in checks:
        try:
            status, detail = fn()
        except Exception as exc:  # noqa: BLE001 - a check must never crash the doctor
            status, detail = FAIL, f"check raised: {exc!r}"
        counts[status] += 1
        out(f"[{status:>4}] {name}: {detail}")
    out("")
    out(
        f"summary: {counts[PASS]} pass · {counts[WARN]} warn · "
        f"{counts[FAIL]} fail"
    )
    return 1 if counts[FAIL] else 0
