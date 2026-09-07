"""Transcript export helpers: guest guessing, smart filenames, output builders.

Shared by the CLI (``pt transcript --format/--output``) and the web download
endpoints so filenames and content stay consistent everywhere.

Formats:
  txt   Plain text with a small metadata header. [HH:MM:SS] per segment.
  md    Markdown with YAML frontmatter (show / guest / episode / source...).
  json  Structured ``{"metadata": ..., "segments": [...]}``.
  srt   SubRip subtitles.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from .store import Episode, Job, Transcript

#: Word-boundary separators that commonly wrap a guest name.
_SEP_RE = re.compile(r"\s+[-–|]\s+")

#: "Guest: Topic" (Huberman style) is only trusted when the part before the
#: colon is short and name-like -- a long first segment is a titled subtitle,
#: not a guest ("The Man Who Made $100M Before 32: The Secret Was ...").
_COLON_MIN_RIGHT_WORDS = 3

_WITH_RE = re.compile(r"\b(?:with|featuring|ft\.?)\s+(.+)$", re.IGNORECASE)

#: Small words that make a segment unlikely to be a person name.
_STOP_WORDS = {
    "a", "an", "and", "at", "ep", "episode", "feat", "for", "from", "ft",
    "in", "live", "of", "on", "part", "special", "the", "to", "vs", "with",
}

_INVALID_FS_RE = re.compile(r'[/\\:*?"<>|\x00-\x1f]')


# --------------------------------------------------------------------------- #
# guest guessing (best-effort; missing guest is fine)
# --------------------------------------------------------------------------- #
def _looks_like_name(seg: str) -> bool:
    seg = seg.strip().strip(".'\"“”")
    if not seg or any(ch.isdigit() for ch in seg):
        return False
    words = seg.split()
    if not (2 <= len(words) <= 5):
        return False
    if any(w.lower() in _STOP_WORDS for w in words):
        return False
    # first two words capitalized => person-name shaped, not a sentence.
    return words[0][0].isupper() and words[1][0].isupper()


def _name_from_tail(tail: str) -> Optional[str]:
    """First capitalized name-shaped phrase at the start of ``tail``."""
    words = tail.split()
    for n in range(min(len(words), 5), 0, -1):
        cand = " ".join(words[:n])
        if _looks_like_name(cand):
            return cand
    return None


def extract_guest(title: Optional[str]) -> Optional[str]:
    """Heuristically extract a guest name from an episode title.

    Handles the patterns seen in the wild:

      * ``"Topic - Guest - #922"`` (Modern Wisdom)
      * ``"#2549 - Jared Diamond"`` (Joe Rogan)
      * ``"Long Topic | Alex Ho"`` (Diary Of A CEO)
      * ``"Dr. Lex Fridman: 2-Hour Protocol..."`` (Huberman)
      * ``"How I Built This with Guy Raz"``

    Returns ``None`` when nothing name-shaped is found (e.g. ``"Live from
    NYC"``, ``"Episode 100 - Recap"``).
    """
    if not title:
        return None

    parts = [p.strip() for p in _SEP_RE.split(title) if p.strip()]
    if len(parts) >= 2:
        # guest lives on the right of the first separator; walk left.
        for part in parts[1:]:
            guest = _name_from_tail(part)
            if guest:
                return guest
        stomach = _name_from_tail(parts[0])
        if stomach:
            return stomach

    if ":" in title:
        left, right = title.split(":", 1)
        if _looks_like_name(left) and len(right.split()) >= _COLON_MIN_RIGHT_WORDS:
            return left.strip()

    m = _WITH_RE.search(title)
    if m:
        guest = _name_from_tail(m.group(1).strip())
        if guest:
            return guest

    return None


# --------------------------------------------------------------------------- #
# filenames
# --------------------------------------------------------------------------- #
def sanitize_filename(s: Optional[str], max_len: int = 80) -> str:
    """Filesystem-safe, whitespace-collapsed, word-boundary-truncated text."""
    if not s:
        return ""
    s = _INVALID_FS_RE.sub("-", s)
    s = re.sub(r"-{2,}", "-", s)
    s = re.sub(r"\s+", " ", s).strip()
    if len(s) > max_len:
        cut = s[:max_len]
        s = cut.rsplit(" ", 1)[0] if " " in cut else cut
    return s.strip(" .-")


def _strip_guest_from_title(title: str, guest: str) -> str:
    """Remove the guest occurrence so the filename snippet isn't redundant."""
    if not guest:
        return title
    t = re.sub(r"\b" + re.escape(guest) + r"\b", "", title)
    # "Topic - Guest - #922" -> "Topic -  - #922" -> collapse the empty segment.
    t = re.sub(r"\s*[-–|]\s*[-–|]\s*", " ", t)
    t = re.sub(r"\s+[-–|]\s*|\s*[-–|]\s+", " - ", t)
    t = re.sub(r"\s+", " ", t).strip(" -")
    return t


def build_transcript_filename(
    episode: Optional[Episode], ext: str = "md", job_id: Optional[int] = None
) -> str:
    """``Show - Guest - Episode-snippet.ext`` with each part made filesystem-safe.

    Omitted parts drop out; empty episodes fall back to ``transcript-{id}.ext``.
    """
    if episode is None:
        return f"transcript-{job_id}.{ext}" if job_id else f"transcript.{ext}"

    title = _title(episode)
    show = sanitize_filename(episode.show_name or "", 60)
    guest = sanitize_filename(extract_guest(title) or "", 40)
    snippet = sanitize_filename(_strip_guest_from_title(title, guest or ""), 80)

    parts = [p for p in (show, guest, snippet) if p]
    if not parts:
        return f"transcript-{job_id}.{ext}" if job_id else f"transcript.{ext}"
    return f"{' - '.join(parts)}.{ext}"


# --------------------------------------------------------------------------- #
# content builders
# --------------------------------------------------------------------------- #
def format_timestamp(seconds: Optional[float]) -> str:
    """Float seconds -> HH:MM:SS (whole seconds)."""
    seconds = max(0, int(float(seconds or 0)))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def _fmt_srt(seconds: Optional[float]) -> str:
    seconds = max(0.0, float(seconds or 0))
    ms = int(round((seconds - int(seconds)) * 1000))
    h, rem = divmod(int(seconds), 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _yaml_value(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def _title(ep: Episode) -> str:
    return (ep.title or "").strip()


def transcript_to_markdown(
    episode: Optional[Episode],
    job: Optional[Job],
    tx: Optional[Transcript],
    segments: List[Dict[str, Any]],
) -> str:
    ep = episode or Episode()
    title = _title(ep) or (f"Job {job.id}" if job and job.id else "Transcript")
    guest = extract_guest(ep.title)
    lines = ["---"]
    lines.append(f'show: "{_yaml_value(ep.show_name or "")}"')
    if guest:
        lines.append(f'guest: "{_yaml_value(guest)}"')
    lines.append(f'episode: "{_yaml_value(_title(ep))}"')
    if ep.publisher:
        lines.append(f'publisher: "{_yaml_value(ep.publisher)}"')
    if ep.duration_seconds:
        lines.append(f"duration_seconds: {float(ep.duration_seconds):g}")
    if job and job.id:
        lines.append(f"job_id: {job.id}")
    if ep.url:
        lines.append(f'source_url: "{_yaml_value(ep.url)}"')
    if tx and tx.language:
        lines.append(f"language: {tx.language}")
    if tx and tx.created_at:
        lines.append(f'transcribed_at: "{tx.created_at}"')
    lines += ["---", "", f"# {title}", ""]
    for seg in segments:
        lines.append(f"[{format_timestamp(seg.get('start_time'))}] {seg.get('text') or ''}")
    return "\n".join(lines) + "\n"


def transcript_to_json(
    episode: Optional[Episode],
    job: Optional[Job],
    tx: Optional[Transcript],
    segments: List[Dict[str, Any]],
) -> Dict[str, Any]:
    ep = episode or Episode()
    guest = extract_guest(ep.title)
    metadata: Dict[str, Any] = {
        "show": ep.show_name or "",
        "episode": _title(ep),
        "job_id": job.id if job and job.id else None,
    }
    if guest:
        metadata["guest"] = guest
    if ep.publisher:
        metadata["publisher"] = ep.publisher
    if ep.duration_seconds:
        metadata["duration_seconds"] = float(ep.duration_seconds)
    if ep.url:
        metadata["source_url"] = ep.url
    if tx:
        if tx.language:
            metadata["language"] = tx.language
        if tx.created_at:
            metadata["transcribed_at"] = tx.created_at
    out_segments = [
        {
            "start_time": seg.get("start_time"),
            "end_time": seg.get("end_time"),
            "text": seg.get("text") or "",
        }
        for seg in segments
    ]
    return {"metadata": metadata, "segments": out_segments}


def transcript_to_txt(
    episode: Optional[Episode],
    job: Optional[Job],
    segments: List[Dict[str, Any]],
) -> str:
    ep = episode or Episode()
    lines = [
        f"Title: {_title(ep)}",
        f"Show: {ep.show_name or ''}",
        f"Source: {ep.url or ''}",
        f"Job: {job.id if job else ''}",
        "",
    ]
    for seg in segments:
        lines.append(f"[{format_timestamp(seg.get('start_time'))}] {seg.get('text') or ''}")
    return "\n".join(lines) + "\n"


def transcript_to_srt(segments: List[Dict[str, Any]]) -> str:
    blocks = []
    for i, seg in enumerate(segments, start=1):
        start = _fmt_srt(seg.get("start_time"))
        end = _fmt_srt(seg.get("end_time"))
        blocks.append(f"{i}\n{start} --> {end}\n{seg.get('text') or ''}\n")
    return "\n".join(blocks)