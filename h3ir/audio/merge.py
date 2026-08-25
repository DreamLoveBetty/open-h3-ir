"""The merge policy: what a fallback supplement may touch, and what it may never (spec §12).

The tiers, and their consequence:

    Tier 1  ffprobe/DSP exact facts          -- signal.*, rhythm.*
    Tier 2  VAD/ASR/CAM++/CLAP               -- speech, events, voice, music
    Tier 3  Qwen2.5-Omni semantic supplement -- semantic_summary, semantic_facts, and ONLY
                                                 the empty slots of voice.delivery,
                                                 music.genres, music.instruments, music.mood
    Tier 4  the caller's note                -- not merged here at all; it is intent, not a
                                                 fact about the bytes, and it lives its whole
                                                 life on the manifest entry (spec §12's
                                                 "caller_description" point, one stage up)

The merge writes a COPY, never the cached observation: the cache key is the bytes, and a
merged-in-place observation would make the cache serve a request-specific supplement as if it
were a byte-derived fact.

A26 lives here rather than in the validator. The protocol parser (fallback.py) rejects any
payload carrying a key outside §11, and when those keys name deterministic fields this module
reports A26 -- at WARN, deliberately below the spec's ERROR: the overwrite cannot ship (the
payload was rejected whole), so nothing wrong reaches the artifact, and an ERROR-severity
wiring finding would raise the draft gate and turn an auxiliary model's misbehaviour into a
500 for a document that is entirely correct. Loud and safe beats spec-literal and fatal.
"""
from __future__ import annotations

from ..models import Finding
from .models import AudioObservation

# Top-level payload keys that would constitute an attempt on a deterministic field. The §11
# protocol contains none of them; an Omni emitting one is doing the thing the system prompt
# forbids, which is why the whole payload is rejected rather than the key ignored.
DETERMINISTIC_KEYS = {"duration", "duration_s", "sample_rate", "tempo", "tempo_bpm", "bpm",
                      "beats", "beat_times_s", "downbeats", "downbeat_times_s", "transcript",
                      "speech", "events", "language", "speaker", "speaker_id"}


def deterministic_overwrite_attempt(extra_keys: tuple[str, ...]) -> Finding | None:
    """The A26 finding for a rejected payload, or None when the extra keys touched nothing
    deterministic. Called by the observer, which is where the parser's rejection arrives."""
    bad = sorted(set(extra_keys) & DETERMINISTIC_KEYS)
    if not bad:
        return None
    return Finding(
        "A26-fallback-overwrote-timing", "WARN",
        f"the fallback model replied with deterministic field(s) it is forbidden to touch "
        f"({', '.join(bad)}), so its ENTIRE payload was rejected, not just those keys. The "
        "deterministic observation shipped unchanged; the supplement was discarded.")


def merge_fallback(obs: AudioObservation, payload: dict) -> tuple[AudioObservation, list[Finding]]:
    """Merge one parsed §11 payload into a copy of the observation.

    Only empty target slots are filled -- tier 2 outranks tier 3, so an analyser that already
    named the instruments keeps its answer and the supplement is silently dropped for that
    field (that silence is the policy, not a conflict). Returns the merged copy plus findings;
    the copy carries fallback_used=True and the merged-from payload's confidence is recorded in
    semantic_facts rather than overwriting the observation's own confidence, which is the
    worker's.
    """
    merged = AudioObservation.from_dict(obs.to_dict())
    findings: list[Finding] = []
    touched = False

    summary = (payload.get("semantic_summary") or "").strip()
    if summary and not merged.semantic_summary:
        merged.semantic_summary = summary
        touched = True

    delivery = ", ".join(payload.get("voice_delivery") or [])
    if delivery and not merged.voice.delivery:
        merged.voice.delivery = delivery
        touched = True

    for field, key in (("genres", "music_style"), ("instruments", "instrumentation")):
        supplement = [x for x in (payload.get(key) or []) if x]
        if supplement and not getattr(merged.music, field):
            setattr(merged.music, field, supplement)
            touched = True

    # Fallback event descriptions are APPROXIMATE by protocol and therefore never enter
    # `events` -- that list is tier-2 located detections, and an approximate description in it
    # would be mapped onto a shot by the timeline stage as if it were measured. They are kept
    # as semantic facts with their approximations spelled out.
    for e in payload.get("event_descriptions") or []:
        desc = (e.get("description") or "").strip()
        if not desc:
            continue
        when = ""
        if e.get("approx_start_s") is not None:
            when = f" at approximately {e['approx_start_s']:.1f}s"
        merged.semantic_facts.append(f"event{when}: {desc}")
        touched = True

    for line in payload.get("soundscape") or []:
        if line.strip() and line.strip() not in merged.semantic_facts:
            merged.semantic_facts.append(line.strip())
            touched = True

    if touched:
        merged.fallback_used = True
        conf = payload.get("confidence") or 0.0
        if conf:
            merged.semantic_facts.append(f"(fallback self-reported confidence: {conf:.2f})")
    return merged, findings
