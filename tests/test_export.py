"""Export helpers: guest guessing, smart filenames, format builders."""

from __future__ import annotations

from podcast_transcriber.export import (
    build_transcript_filename,
    extract_guest,
    format_timestamp,
    sanitize_filename,
    transcript_to_json,
    transcript_to_markdown,
    transcript_to_srt,
    transcript_to_txt,
)
from podcast_transcriber.store import Episode, Job, Transcript


def _episode(**kw) -> Episode:
    defaults = dict(url="https://open.spotify.com/episode/abc", title="", show_name="")
    defaults.update(kw)
    return Episode(**defaults)


# --------------------------------------------------------------------------- #
# guest guessing (patterns from real stored episodes)
# --------------------------------------------------------------------------- #
def test_extract_guest_modern_wisdom_middle_segment():
    assert extract_guest("44 Harsh Truths About Human Nature - Naval Ravikant - #922") == "Naval Ravikant"


def test_extract_guest_jre_after_dash():
    assert extract_guest("#2549 - Jared Diamond") == "Jared Diamond"


def test_extract_guest_diary_of_ceo_after_pipe():
    t = "The Man Who Made $100M Before 32: The Secret Was To Stop Letting Them Control Me | Alex Ho"
    assert extract_guest(t) == "Alex Ho"


def test_extract_guest_huberman_colon():
    assert extract_guest("Dr. Lex Fridman: 2-Hour Protocol for Daily Focus") == "Dr. Lex Fridman"


def test_extract_guest_with_phrase():
    assert extract_guest("How I Built This with Guy Raz") == "Guy Raz"


def test_extract_guest_none_for_non_names():
    assert extract_guest("Episode 100 - Live from NYC") is None
    assert extract_guest("The Future of AI") is None
    assert extract_guest("44 Harsh Truths About Human Nature - #922") is None
    assert extract_guest("") is None
    assert extract_guest(None) is None


# --------------------------------------------------------------------------- #
# filenames
# --------------------------------------------------------------------------- #
def test_build_filename_with_guest():
    ep = _episode(show_name="Modern Wisdom",
                  title="44 Harsh Truths About Human Nature - Naval Ravikant - #922")
    name = build_transcript_filename(ep, "md", job_id=24)
    assert name == "Modern Wisdom - Naval Ravikant - 44 Harsh Truths About Human Nature #922.md"


def test_build_filename_no_guest_drops_segment():
    ep = _episode(show_name="The Startup Ideas Podcast",
                  title="These AI Marketing Agents Get You Customers")
    assert build_transcript_filename(ep, "md", job_id=15) == (
        "The Startup Ideas Podcast - These AI Marketing Agents Get You Customers.md"
    )


def test_build_filename_guest_not_duplicated_in_snippet():
    ep = _episode(show_name="The Joe Rogan Experience", title="#2549 - Jared Diamond")
    assert build_transcript_filename(ep, "txt", job_id=20) == (
        "The Joe Rogan Experience - Jared Diamond - #2549.txt"
    )


def test_build_filename_empty_episode_fallback():
    assert build_transcript_filename(None, "md", job_id=7) == "transcript-7.md"
    assert build_transcript_filename(_episode(), "md") == "transcript.md"


def test_sanitize_filename_replaces_illegal_chars_and_truncates():
    assert sanitize_filename('a/b:c*?"<>|', 80) == "a-b-c"
    long = "x" * 200 + " yyy"
    assert len(sanitize_filename(long, 80)) <= 80
    assert sanitize_filename(None) == ""


# --------------------------------------------------------------------------- #
# timestamps / formats
# --------------------------------------------------------------------------- #
def test_format_timestamp():
    assert format_timestamp(0) == "00:00:00"
    assert format_timestamp(61) == "00:01:01"
    assert format_timestamp(3661.5) == "01:01:01"
    assert format_timestamp(11764) == "03:16:04"
    assert format_timestamp(-5) == "00:00:00"


def test_markdown_has_frontmatter_and_hms_lines():
    ep = _episode(show_name="Modern Wisdom",
                  title="44 Harsh Truths About Human Nature - Naval Ravikant - #922",
                  duration_seconds=11764.0, publisher="Chris Williamson")
    job = Job(id=24, episode_id=21)
    tx = Transcript(language="en", created_at="2026-09-06T15:19:50Z")
    segs = [{"start_time": 0.0, "end_time": 2.8, "text": "Happiness is being satisfied."},
            {"start_time": 11763.5, "end_time": 11764.2, "text": "All right."}]
    md = transcript_to_markdown(ep, job, tx, segs)
    assert "show: \"Modern Wisdom\"" in md
    assert 'guest: "Naval Ravikant"' in md
    assert "job_id: 24" in md
    assert "duration_seconds: 11764" in md
    assert 'transcribed_at: "2026-09-06T15:19:50Z"' in md
    assert "[00:00:00] Happiness is being satisfied." in md
    assert "[03:16:03] All right." in md
    assert md.startswith("---\n")


def test_json_structured_metadata_and_segments():
    ep = _episode(show_name="Show", title="Ep - Jane Doe - #1", url="https://x/e")
    job = Job(id=5, episode_id=1)
    tx = Transcript(language="en", created_at="2026-09-06T00:00:00Z")
    segs = [{"start_time": 0.0, "end_time": 1.0, "text": "hi"}]
    out = transcript_to_json(ep, job, tx, segs)
    assert out["metadata"]["show"] == "Show"
    assert out["metadata"]["guest"] == "Jane Doe"
    assert out["metadata"]["job_id"] == 5
    assert out["metadata"]["language"] == "en"
    assert out["metadata"]["source_url"] == "https://x/e"
    assert out["segments"] == [{"start_time": 0.0, "end_time": 1.0, "text": "hi"}]


def test_txt_header_and_hms_lines():
    ep = _episode(show_name="Show", title="Ep", url="https://x/e")
    job = Job(id=3, episode_id=1)
    segs = [{"start_time": 61.0, "end_time": 62.0, "text": "one minute in"}]
    txt = transcript_to_txt(ep, job, segs)
    assert txt.splitlines()[:4] == ["Title: Ep", "Show: Show", "Source: https://x/e", "Job: 3"]
    assert "[00:01:01] one minute in" in txt


def test_srt_blocks():
    segs = [{"start_time": 0.0, "end_time": 2.5, "text": "First"},
            {"start_time": 61.0, "end_time": 63.25, "text": "Second"}]
    srt = transcript_to_srt(segs)
    assert "1\n00:00:00,000 --> 00:00:02,500\nFirst" in srt
    assert "2\n00:01:01,000 --> 00:01:03,250\nSecond" in srt