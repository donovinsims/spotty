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
    # Ambiguity (2 candidates both plausible) must never auto-verify.
    assert res.state == REVIEW_REQUIRED


def test_state_for_confidence_thresholds():
    assert state_for_confidence(0.9, 1) == VERIFIED
    assert state_for_confidence(0.84, 1) == REVIEW_REQUIRED
    assert state_for_confidence(1.0, 2) == REVIEW_REQUIRED
    assert state_for_confidence(1.0, 0) == UNAVAILABLE


def test_verification_result_serializable():
    c = Candidate(audio_url="https://cdn/x.mp3", title="t", confidence=0.9)
    d = decide([c]).as_dict()
    assert d["state"] == VERIFIED
    assert set(d) >= {"state", "confidence", "reason", "candidates", "audio_url"}