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

#: A top candidate must also beat the runner-up by this margin to auto-verify.
#: A near-tie between two plausible episodes is genuinely ambiguous and stays
#: REVIEW_REQUIRED, but a runaway winner (e.g. 1.00 vs 0.63) is safe to trust.
CLEAR_WINNER_MARGIN = 0.10


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


def state_for_confidence(confidence: float, n_candidates: int,
                         runner_up_confidence: Optional[float] = None) -> str:
    """Pure state-transition function (unit-testable without network).

    Auto-verify only when the best candidate is strong AND clearly better than
    the runner-up (if any); anything else is ambiguous -> REVIEW_REQUIRED.
    With several candidates but no runner-up confidence supplied, stay
    conservative (REVIEW_REQUIRED).
    """
    if n_candidates == 0:
        return UNAVAILABLE
    if confidence < VERIFIED_THRESHOLD:
        return REVIEW_REQUIRED
    if n_candidates > 1:
        if runner_up_confidence is None:
            return REVIEW_REQUIRED
        # round() absorbs binary-float noise so 0.95 vs 0.85 counts as the
        # intended 0.10 margin, not 0.09999... .
        margin = round(confidence - runner_up_confidence, 6)
        if margin < CLEAR_WINNER_MARGIN:
            return REVIEW_REQUIRED
    return VERIFIED


def decide(candidates: List[Candidate]) -> VerificationResult:
    """Choose the best candidate and map confidence onto a verification states.

    - No capable candidates                    -> UNAVAILABLE
    - Best candidate above threshold and clearly
      ahead of the runner-up (if any)          -> VERIFIED
    - Anything ambiguous                       -> REVIEW_REQUIRED
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

    ranked_all = sorted(candidates, key=lambda c: c.confidence, reverse=True)
    best = max(usable, key=lambda c: c.confidence)
    # The runner-up is the best *other* candidate overall -- including entries
    # without an audio enclosure.  Decide the state from the TOTAL candidate
    # list: two near-identical titles -- one with an enclosure, one silently
    # lacking one -- is still ambiguous and must not auto-verify (false match
    # worse than failure).
    runner_up = next((c for c in ranked_all if c is not best), None)
    state = state_for_confidence(
        best.confidence,
        len(candidates),
        runner_up.confidence if runner_up is not None else None,
    )

    if state == VERIFIED:
        reason = "Single high-confidence match (title and duration agree)."
        if runner_up is not None:
            reason = (
                f"Clear winner: best match beats the next candidate by "
                f"{best.confidence - runner_up.confidence:.2f} confidence."
            )
    else:
        reason = {
            REVIEW_REQUIRED: (
                "Candidate available but match quality is ambiguous "
                "(title/duration did not fully agree); manual review advised."
            ),
            UNAVAILABLE: "No usable candidate found.",
        }.get(state, f"{state}.")
    return VerificationResult(
        state=state,
        confidence=best.confidence,
        reason=reason,
        candidates=usable,
        audio_url=best.audio_url,
        matched_title=best.title,
    )