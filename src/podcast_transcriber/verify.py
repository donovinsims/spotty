"""Episode verification state machine.

Given candidate matches produced by the resolver, decide whether the audio we
found can be *trusted* as the exact episode the user asked for.  Philosophy:
a false match is worse than a failure, so we are deliberately conservative --
when in doubt we return REVIEW_REQUIRED or UNAVAILABLE rather than VERIFIED.

States:
  * VERIFIED         - single, strong match (title tokens + duration ok)
  * REVIEW_REQUIRED  - a candidate exists but match quality is ambiguous
  * UNAVAILABLE      - no feed / no candidate / unrecoverable
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

VERIFIED = "VERIFIED"
REVIEW_REQUIRED = "REVIEW_REQUIRED"
UNAVAILABLE = "UNAVAILABLE"

#: Minimum confidence for a single candidate to be trusted as VERIFIED.
VERIFIED_THRESHOLD = 0.85


@dataclass
class Candidate:
    audio_url: Optional[str]
    title: Optional[str] = None
    feed_url: Optional[str] = None
    duration_seconds: Optional[float] = None
    confidence: float = 0.0
    reason: str = ""
    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass
class VerificationResult:
    state: str
    confidence: float
    reason: str
    candidates: List[Candidate] = field(default_factory=list)
    # For machine-readable CLI output / future API.
    audio_url: Optional[str] = None
    matched_title: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "state": self.state,
            "confidence": round(self.confidence, 4),
            "reason": self.reason,
            "audio_url": self.audio_url,
            "matched_title": self.matched_title,
            "candidates": [c.__dict__ for c in self.candidates],
        }


def state_for_confidence(confidence: float, n_candidates: int) -> str:
    """Pure state-transition function (unit-testable without network)."""
    if n_candidates == 0:
        return UNAVAILABLE
    if n_candidates == 1 and confidence >= VERIFIED_THRESHOLD:
        return VERIFIED
    return REVIEW_REQUIRED


def decide(candidates: List[Candidate]) -> VerificationResult:
    """Choose the best candidate and map confidence onto a verification states.

    - No capable candidates          -> UNAVAILABLE
    - One candidate above threshold  -> VERIFIED
    - Anything ambiguous             -> REVIEW_REQUIRED
    """
    usable = [c for c in candidates if c.audio_url]
    if not usable:
        confident = max((c.confidence for c in candidates), default=0.0)
        return VerificationResult(
            state=UNAVAILABLE,
            confidence=confident,
            reason="No candidate produced a playable audio enclosure.",
            candidates=usable,
        )

    best = max(usable, key=lambda c: c.confidence)
    state = state_for_confidence(best.confidence, len(usable))

    reasons = {
        VERIFIED: "Single high-confidence match (title and duration agree).",
        REVIEW_REQUIRED: (
            "Candidate available but match quality is ambiguous "
            "(title/duration did not fully agree); manual review advised."
        ),
        UNAVAILABLE: "No usable candidate found.",
    }
    return VerificationResult(
        state=state,
        confidence=best.confidence,
        reason=reasons[state],
        candidates=usable,
        audio_url=best.audio_url,
        matched_title=best.title,
    )