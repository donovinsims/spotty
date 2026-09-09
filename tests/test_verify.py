"""Verifier state-machine tests (pure, no network)."""

from __future__ import annotations

from podcast_transcriber.verify import (
    REVIEW_REQUIRED,
    UNAVAILABLE,
    VERIFIED,
    Candidate,
    decide,
    state_for_confidence,
)


def test_no_candidates_is_unavailable():
    res = decide([])
    assert res.state == UNAVAILABLE
    assert res.audio_url is None


def test_candidates_without_audio_unavailable():
    c = Candidate(audio_url=None, title="x", confidence=0.99)
    res = decide([c])
    assert res.state == UNAVAILABLE


def test_single_strong_match_verified():
    c = Candidate(audio_url="https://cdn/x.mp3", title="Ep #100 - Great",
                  duration_seconds=1800, confidence=0.95)
    res = decide([c])
    assert res.state == VERIFIED
    assert res.audio_url == "https://cdn/x.mp3"
    assert res.confidence == 0.95


def test_single_weak_match_review_required():
    c = Candidate(audio_url="https://cdn/x.mp3", title="maybe?", confidence=0.6)
    res = decide([c])
    assert res.state == REVIEW_REQUIRED


def test_multiple_matches_review_required_even_if_top_is_strong():
    a = Candidate(audio_url="https://cdn/a.mp3", title="A", confidence=0.99)
    b = Candidate(audio_url="https://cdn/b.mp3", title="B", confidence=0.99)
    res = decide([a, b])
    # Ambiguity (2 near-tied candidates both plausible) must never auto-verify.
    assert res.state == REVIEW_REQUIRED


def test_clear_winner_beats_distant_runner_up_verified():
    """A runaway winner (1.00 vs 0.63) is safe to auto-verify even though a
    weaker candidate exists -- the near-miss is not a plausible alternative."""
    a = Candidate(audio_url="https://cdn/a.mp3", title="Episode 2", confidence=1.0)
    b = Candidate(audio_url="https://cdn/b.mp3", title="Episode 1", confidence=0.63)
    res = decide([a, b])
    assert res.state == VERIFIED
    assert res.audio_url == "https://cdn/a.mp3"
    assert res.matched_title == "Episode 2"


def test_clear_winner_margin_boundary():
    """Exactly CLEAR_WINNER_MARGIN ahead is verified; just below is not."""
    win = Candidate(audio_url="https://cdn/a.mp3", title="A", confidence=0.95)
    edge = Candidate(audio_url="https://cdn/b.mp3", title="B", confidence=0.85)
    assert decide([win, edge]).state == VERIFIED

    close = Candidate(audio_url="https://cdn/b.mp3", title="B", confidence=0.86)
    assert decide([win, close]).state == REVIEW_REQUIRED


def test_runner_up_without_audio_blocks_only_when_close():
    """M6 revisit: a near-identical title lacking an enclosure still blocks a
    close best match, but a distant one must not (false negative fix)."""
    with_audio = Candidate(audio_url="https://cdn/a.mp3", title="Ep #1 - The Show",
                           confidence=0.99)
    no_audio_close = Candidate(audio_url=None, title="Ep #1 - The Show (Reprise)",
                               confidence=0.9)
    res = decide([with_audio, no_audio_close])
    assert res.state == REVIEW_REQUIRED
    assert res.audio_url == "https://cdn/a.mp3"
    assert res.confidence == 0.99

    no_audio_distant = Candidate(audio_url=None, title="Ep #1 - The Show (Reprise)",
                                 confidence=0.5)
    assert decide([with_audio, no_audio_distant]).state == VERIFIED


def test_ambiguous_candidate_without_audio_not_verified():
    """Two near-identical titles, one lacking an enclosure: the TOTAL candidate
    count decides the state (M6).  One usable candidate must NOT auto-verify."""
    with_audio = Candidate(audio_url="https://cdn/a.mp3", title="Ep #1 - The Show",
                           confidence=0.99)
    no_audio = Candidate(audio_url=None, title="Ep #1 - The Show (Reprise)",
                         confidence=0.9)
    res = decide([with_audio, no_audio])
    assert res.state == REVIEW_REQUIRED
    # The best *usable* candidate still drives audio_url / confidence.
    assert res.audio_url == "https://cdn/a.mp3"
    assert res.confidence == 0.99


def test_state_for_confidence_thresholds():
    assert state_for_confidence(0.9, 1) == VERIFIED
    assert state_for_confidence(0.84, 1) == REVIEW_REQUIRED
    # 2 candidates, no runner-up info -> conservative (ambiguous).
    assert state_for_confidence(1.0, 2) == REVIEW_REQUIRED
    # 2 candidates, distant runner-up -> clear winner.
    assert state_for_confidence(1.0, 2, 0.63) == VERIFIED
    # 2 candidates, near-tie runner-up -> ambiguous.
    assert state_for_confidence(1.0, 2, 0.95) == REVIEW_REQUIRED
    assert state_for_confidence(1.0, 0) == UNAVAILABLE


def test_verification_result_serializable():
    c = Candidate(audio_url="https://cdn/x.mp3", title="t", confidence=0.9)
    d = decide([c]).as_dict()
    assert d["state"] == VERIFIED
    assert set(d) >= {"state", "confidence", "reason", "candidates", "audio_url"}