"""The fallback router: whether Qwen2.5-Omni is allowed to look at this audio at all (spec §10).

Omni is a fallback, never a default path (spec §4.7: "禁止默认每段音频都调用"). The decision
is rule-scored rather than a single confidence comparison, because "the deterministic chain
cannot explain this audio" has several independent shapes -- an empty music profile under
music_style, a voice with speech and no timbre facts, a worker that flagged its own answer as
partial -- and a threshold on one number sees none of them.

The function is pure: observation in, decision out, no I/O. That is what makes every rule
independently testable (spec §28.3) and keeps the fallback call itself in observer.py, which
owns the HTTP.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..models import Role
from .models import AudioObservation

# The caller explicitly asking for a richer reading is rule 1 of spec §10. Detection is a
# conservative keyword list on the caller's own note, and conservative on purpose: a miss means
# no supplement the caller would have liked, a false positive means spending an Omni call the
# caller did not ask for -- the miss is cheaper.
_DETAIL_PHRASES = ("detailed sound", "describe the sound", "sound description",
                   "acoustic environment", "instrumentation", "exact sound character",
                   "soundscape")


@dataclass
class FallbackDecision:
    use_fallback: bool
    reasons: list[str] = field(default_factory=list)


def caller_asked_for_detail(note: str) -> bool:
    n = (note or "").lower()
    return any(p in n for p in _DETAIL_PHRASES)


def decide_fallback(obs: AudioObservation, role: Role, *, caller_note: str = "",
                    confidence_threshold: float = 0.65,
                    event_confidence_threshold: float = 0.55) -> FallbackDecision:
    """Spec §10's seven trigger conditions, one `reasons` entry per condition that fired.

    The "不应 fallback" cases need no code of their own: a clear ASR result, a reliable beat
    grid, or a plain BGM copy trip none of the seven, and the tests pin that silence -- a
    condition list that can only say YES is a default path wearing a gate.
    """
    reasons: list[str] = []

    # 1. The caller asked, in the note, for more than the deterministic tiers can say.
    if caller_asked_for_detail(caller_note):
        reasons.append("the caller's note asks for a detailed sound description")

    # 2. music_style with music present but no usable style facts: the projection would
    #    characterise the style from nothing.
    if (role is Role.MUSIC_STYLE and obs.music.present
            and not obs.music.genres and not obs.music.instruments):
        reasons.append("music_style is wired but the analyser found music without naming "
                       "its genres or instruments")

    # 3. voice_timbre with speech but an empty voice profile: words without a voice.
    v = obs.voice
    voice_empty = not any((v.pitch_class, v.energy, v.pace, v.delivery, v.emotions,
                           v.speaker_count))
    if role is Role.VOICE_TIMBRE and obs.speech and voice_empty:
        reasons.append("voice_timbre is wired and speech was recognised, but no voice "
                       "profile was produced")

    # 4. sfx with no confident events: nothing to project a texture from.
    if role is Role.SFX:
        confident = [e for e in obs.events
                     if e.confidence is not None and e.confidence >= event_confidence_threshold]
        if not confident:
            reasons.append("sfx is wired but no event cleared the confidence threshold")

    # 5. A complex mixture the structured chain cannot explain: speech AND music AND
    #    overlapping events at once. The decidable residue of "复杂混合且结构化分析无法解释"
    #    is the coexistence itself -- all three tiers reporting at once is exactly the input
    #    the tiers have no vocabulary for.
    if obs.speech and obs.music.present and len(obs.events) >= 2:
        reasons.append("speech, music and multiple events overlap, which no single tier "
                       "explains")

    # 6. The worker flagged its own answer as incomplete.
    if obs.partial:
        reasons.append("the audio worker returned a partial observation")

    # 7. Mean tier-2 confidence below threshold, computed over the confidences that EXIST --
    #    a tier that reported nothing abstains rather than dragging the mean toward zero.
    confidences = ([s.confidence for s in obs.speech if s.confidence is not None]
                   + [e.confidence for e in obs.events if e.confidence is not None]
                   + ([obs.rhythm.confidence] if obs.rhythm.confidence is not None else []))
    if confidences and sum(confidences) / len(confidences) < confidence_threshold:
        reasons.append(f"mean analyser confidence "
                       f"{sum(confidences) / len(confidences):.2f} is below "
                       f"{confidence_threshold:.2f}")

    return FallbackDecision(use_fallback=bool(reasons), reasons=reasons)
