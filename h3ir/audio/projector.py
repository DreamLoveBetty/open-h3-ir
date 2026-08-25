"""The role-aware projector: one Observation, five different truths.

An `AudioObservation` answers "what is objectively in the audio" and is cached on the bytes.
What the IR is allowed to SAY about those bytes depends entirely on the role the caller wired
the asset into -- the same 128 BPM track is a signal to reuse as `bgm`, a style to follow as
`music_style`, and a timing grid as `beat_reference`, and conflating any two of those writes a
retention claim the render does not deliver. That separation is the design rule of
`audio/models.py`; this module is where it is enforced.

The projection is request-specific and is therefore NEVER cached (the cache key deliberately
excludes role and note -- see audio/cache.py). It produces four things:

  * `characterisation` -- what `ManifestEntry.characterisation` carries into the renderer's
    `<Audio N>` definition line. H3's tokenizer emits only `"<Audio j>: "` and never the
    signal, so this text is the sole channel by which the encoder learns what the audio is.
  * `planner_facts` -- the compressed, planner-safe form (spec §22). Never the full beat
    list: a hundred timestamps is not a fact, it is the observation wearing a thinner coat.
  * `timeline_constraints` -- the full machine-facing form (beat grids, event spans) for
    plan.py's timeline stage to consume. Machine-facing, so it may be complete.
  * `findings` -- caller/analyser conflicts surfaced rather than resolved (spec §13): the
    note wins on role and intent, the analyser wins on acoustic fact, and a disagreement
    between them is a WARN, never a silent override in either direction.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..models import Finding, Role
from .models import AudioObservation

# Phase C snaps at most this far onto a beat; the snapping itself lives in plan.py. Kept here
# because the window is a property of the projection's contract with the timeline: beats sparser
# than this are a hint, not a grid.
MAX_BEAT_SNAP_MS = 250

# How many accents the CHARACTERISATION may name (spec §14.4: "prominent accents around 1.90s,
# 3.80s and 5.70s", and no more). The planner needs to know the pulse has anchors; it does not
# need the grid it could snap to -- that travels in timeline_constraints instead.
MAX_SALIENT_BEATS = 3

_LANGUAGES = {"en": "English", "zh": "Chinese", "ja": "Japanese", "ko": "Korean",
              "es": "Spanish", "fr": "French", "de": "German", "yue": "Cantonese"}


@dataclass
class RoleAudioProjection:
    role: Role | None
    characterisation: str
    planner_facts: list[str] = field(default_factory=list)
    timeline_constraints: list[dict] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)


def _language(obs: AudioObservation) -> str:
    for seg in obs.speech:
        if seg.language:
            return _LANGUAGES.get(seg.language, seg.language)
    return ""


def _fmt_time(s: float) -> str:
    return f"{s:.2f}s"


def _salient_beats(downbeats: list[float], onsets: list[float],
                   beats: list[float]) -> list[float]:
    """The few anchors a characterisation may name, chosen from the strongest tier available.

    Downbeats outrank strong onsets outrank raw beats, because each tier is a stricter reading
    of the same grid. First/middle/last rather than the first three: the characterisation's job
    is to show the pulse spans the clip, and three beats from the first second shows nothing.
    """
    tier = downbeats or onsets or beats
    if len(tier) <= MAX_SALIENT_BEATS:
        return list(tier)
    mid = len(tier) // 2
    return [tier[0], tier[mid], tier[-1]]


def _music_character(obs: AudioObservation) -> str:
    """Broad music character, in the order spec §14.3 lists the projectable properties."""
    bits: list[str] = []
    if obs.music.genres:
        bits.append("/".join(obs.music.genres[:2]))
    if obs.music.instruments:
        bits.append("led by " + ", ".join(obs.music.instruments[:2]))
    if obs.rhythm.tempo_bpm:
        bits.append(f"at approximately {obs.rhythm.tempo_bpm:.0f} BPM")
    if obs.music.mood:
        bits.append("with a " + ", ".join(obs.music.mood[:2]) + " mood")
    return " ".join(bits)


def _note_conflict(obs: AudioObservation, note: str) -> str | None:
    """A caller/analyser disagreement, detected ONLY where both sides are unambiguous.

    The conservative half of spec §13 on purpose: "instrumental"/"no speech" against detected
    speech and "no music" against detected music are the two claims that cannot both be true.
    Anything subtler -- "calm" against an energetic reading, "male" against a high pitch -- is
    a guess about what the caller meant, and guessing the caller's intent is the one move the
    spec forbids outright ("不自动猜测用户真正想要哪个").
    """
    n = note.lower()
    says_no_speech = any(p in n for p in ("instrumental", "no speech", "no vocals",
                                          "no singing", "no dialogue", "unspoken"))
    if says_no_speech and obs.speech:
        return (f'the caller describes it as containing no speech ("{note}"), while the '
                f"analyser recognised {len(obs.speech)} spoken segment(s)")
    says_no_music = any(p in n for p in ("no music", "unmusical", "not music"))
    if says_no_music and obs.music.present:
        return (f'the caller describes it as containing no music ("{note}"), while the '
                "analyser detected a musical layer")
    return None


def _checked_events(obs: AudioObservation) -> tuple[list, list[Finding]]:
    """A23: every event must satisfy 0 <= start <= end <= asset duration.

    An offender is DROPPED, not repaired: the event is an analyser claim about the bytes, and
    clamping it would replace the analyser's fact with one we invented. Dropping is safe (the
    timeline stage maps events onto shots, and a shot mapping needs a sane span) and the WARN
    keeps it loud -- a degradation nobody reports is the one failure mode this codebase refuses.
    """
    duration = obs.signal.duration_s
    good, bad = [], []
    for e in obs.events:
        in_range = 0 <= e.start_s <= e.end_s and (not duration or e.end_s <= duration + 1e-6)
        (good if in_range else bad).append(e)
    findings = [Finding(
        "A23-audio-event-out-of-range", "WARN",
        f"the analyser reported {len(bad)} event(s) outside the asset's 0..{duration:.2f}s span "
        f"({', '.join(f'{e.label}@{e.start_s:.2f}-{e.end_s:.2f}s' for e in bad[:3])}); they are "
        "dropped from the projection rather than clamped, because a clamped timestamp is a fact "
        "nobody measured")] if bad else []
    return good, findings


def _checked_beats(obs: AudioObservation) -> tuple[list[float], list[float], list[float],
                                                   list[Finding]]:
    """A24: beat grids must be strictly increasing to be a grid at all.

    A non-monotonic beat list is not snapped into shape by sorting it: out-of-order beats mean
    the rhythm tier's output is broken in a way sorting would disguise, and the snapping stage
    would then snap cuts onto a grid nobody measured. The whole grid is stood down (the role's
    characterisation still reports the tempo, which is one number and still true) and the WARN
    says so.
    """
    r = obs.rhythm
    tiers = (list(r.downbeat_times_s), list(r.strong_onsets_s), list(r.beat_times_s))
    broken = [name for name, tier in zip(("downbeats", "strong onsets", "beats"), tiers)
              if any(b <= a for a, b in zip(tier, tier[1:]))]
    if not broken:
        return tiers[2], tiers[0], tiers[1], []
    return [], [], [], [Finding(
        "A24-beat-times-not-monotonic", "WARN",
        f"the analyser's {', '.join(broken)} are not strictly increasing, so the beat grid is "
        "stood down for this projection: no cut will snap to it and no accent is named from it. "
        "The tempo figure is unaffected -- it is one number, not an ordering")]


def project_audio(observation: AudioObservation, role: Role, caller_note: str = "",
                  ) -> RoleAudioProjection:
    """Project one Observation into the one role the caller wired it into.

    The caller's note is never dropped and never wins over an acoustic fact: it leads the
    characterisation (it is the intent half), the projected facts follow (the observation
    half), and a flat contradiction between them raises A9-audio-note-discrepancy as a WARN
    rather than being resolved in either direction.
    """
    obs = observation
    out = RoleAudioProjection(role=role, characterisation="")
    note = (caller_note or "").strip()
    # A23/A24 first: everything below projects from the SANITISED lists, so a broken analyser
    # claim can neither reach the IR text nor the timeline.
    events, event_findings = _checked_events(obs)
    beats, downbeats, onsets, beat_findings = _checked_beats(obs)
    out.findings.extend(event_findings + beat_findings)

    facts: list[str] = []
    if role is Role.VOICE_TIMBRE:
        # Timbre, delivery and language are the reference; the transcript is dialogue content
        # and must never stand in for a voice description (validator A22 holds the IR side).
        v = obs.voice
        desc: list[str] = []
        if v.pitch_class:
            desc.append(f"{v.pitch_class}-pitched")
        if v.energy:
            desc.append(f"{v.energy}-energy" if not v.energy.endswith("energy") else v.energy)
        lang = _language(obs)
        head = " ".join(desc)
        speakers = (f", spoken by {v.speaker_count} speaker" +
                    ("s" if v.speaker_count != 1 else "") if v.speaker_count else "")
        delivery = ", ".join(x for x in (v.pace, *v.emotions[:2], v.delivery) if x)
        char = f"a {head + ' ' if head else ''}{lang + ' ' if lang else ''}voice reference"
        if delivery:
            char += f" with a {delivery} delivery"
        char += speakers
        if obs.speech:
            facts.append(f"spoken_segments={len(obs.speech)}")
            if lang:
                facts.append(f"language={lang}")
            facts.append("transcript_available=true")
        if v.speaker_count:
            facts.append(f"speaker_count={v.speaker_count}")

    elif role is Role.BGM:
        # Signal REUSE, so duration and synchronisation are the facts that matter and the
        # characterisation must never read as a style reference (spec §14.2). "Newly generated"
        # is the one phrase this role may not produce -- A20 checks the rendered side.
        char = "the synchronized background music track"
        if obs.signal.duration_s:
            char += f", {obs.signal.duration_s:.1f}s long"
        character = _music_character(obs)
        if character:
            char += f" — {character}"
        elif not obs.music.present:
            char += " — no musical layer detected"
        if obs.signal.duration_s:
            facts.append(f"duration_s={obs.signal.duration_s:.2f}")
        if obs.rhythm.tempo_bpm:
            facts.append(f"tempo_bpm={obs.rhythm.tempo_bpm:.1f}")

    elif role is Role.MUSIC_STYLE:
        # Only the style properties project, and the sentence must close the copy question in
        # the same breath: the score is newly generated, the signal is not taken (spec §14.3).
        character = _music_character(obs)
        char = (f"a music-style reference{' — ' + character if character else ''}; it guides "
                "a newly generated score rather than supplying the audio itself")
        if obs.music.genres:
            facts.append("genres=" + "/".join(obs.music.genres[:3]))
        if obs.rhythm.tempo_bpm:
            facts.append(f"tempo_bpm={obs.rhythm.tempo_bpm:.1f}")

    elif role is Role.BEAT_REFERENCE:
        char = "a rhythmic reference"
        if obs.rhythm.tempo_bpm:
            char += f" with an approximately {obs.rhythm.tempo_bpm:.0f} BPM pulse"
        salient = _salient_beats(downbeats, onsets, beats)
        if salient:
            char += (" and prominent accents around "
                     + ", ".join(_fmt_time(s) for s in salient))
        # Only the timing is referenced. Deliberately worded without the word "copy": the
        # retention note owns that sentence, and a definition line that argues the negative
        # reads as protesting too much.
        if obs.rhythm.tempo_bpm:
            facts.append(f"tempo_bpm={obs.rhythm.tempo_bpm:.1f}")
        if salient:
            facts.append("salient_beats_s=[" + ", ".join(f"{s:.2f}" for s in salient) + "]")
        # The FULL grid travels machine-facing: beat snapping (spec §18.1) needs every beat,
        # not the three the prose may name.
        if beats:
            out.timeline_constraints.append({
                "type": "beat_grid",
                "tempo_bpm": obs.rhythm.tempo_bpm,
                "beats_s": list(beats),
                "downbeats_s": list(downbeats),
                "max_snap_ms": MAX_BEAT_SNAP_MS,
            })

    elif role is Role.SFX:
        # Reference, never a copy, whatever the signal contains -- the retention marker table
        # owns that, and the AGENTS.md note on `_AUDIO_MARKER` records what relaxing it cost.
        if events:
            first = events[0]
            char = (f"a sound-texture reference containing {first.label} "
                    f"at {_fmt_time(first.start_s)}")
            if len(events) > 1:
                char += f" and {len(events) - 1} further event(s)"
        else:
            char = "a sound-texture reference"
        for e in events:
            out.timeline_constraints.append({
                "type": "sfx_event",
                "start_s": e.start_s, "end_s": e.end_s,
                "label": e.label, "confidence": e.confidence,
                # The ambient test (spec §18.3) is a RATIO -- event span over asset span -- so
                # the asset's length has to travel with the event; the timeline stage never sees
                # the observation itself.
                "asset_duration_s": obs.signal.duration_s,
            })
        facts.append(f"events={len(events)}")

    else:
        # A role this projector does not know. The note alone carries the characterisation,
        # exactly as the legacy path always behaved.
        char = ""

    # The caller's words lead: they are the intent half of the description, and the projection
    # adds what the analyser can stand behind. When the note is empty the projection fills the
    # gap alone -- which is also what lets an enhanced observation close X15-audio-uncharacterised.
    if char and note:
        out.characterisation = f"{note}; {char}"
    else:
        out.characterisation = note or char
    out.planner_facts = facts

    if note:
        conflict = _note_conflict(obs, note)
        if conflict:
            out.findings.append(Finding(
                "A9-audio-note-discrepancy", "WARN",
                f"the audio is described by the caller as \"{note}\", but {conflict}. The "
                "caller's description leads the characterisation (intent is theirs); the "
                "analyser's facts are reported alongside it (acoustics are the bytes'), and "
                "neither has been silently rewritten."))
    return out


def project_soundtrack(observation: AudioObservation) -> RoleAudioProjection:
    """The sixth reading: what a reference video's OWN audio sounds like (spec §19).

    Not a role, because the caller declared nothing -- the soundtrack arrives inside the
    video's bytes, and the projection's job is narrower than any role's: state what is
    there, so the writer can say truthfully what the source sounds like instead of guessing
    or ignoring it. It makes no reuse claim in either direction: whether the target's audio
    follows the source is the request's and the writer's business, and an edit that preserves
    timing but not sound is a legitimate brief.

    Two deliberate asymmetries with the role projections:

      * The beat grid DOES travel as a timeline constraint (keyed by the video's label at the
        call site): an edit preserves the source's timing, so its pulse is exactly the grid
        the target's cuts should snap to (spec: soundtrack timing enters H3 planning).
      * Located events do NOT travel as timeline constraints. map_audio_events would write
        them into the TARGET's shots as sync sound, and "the source has a door slam at 4.2s"
        does not entitle the plan to claim the target does. They are stated as planner facts
        for the writer instead.
    """
    obs = observation
    out = RoleAudioProjection(role=None, characterisation="")
    events, event_findings = _checked_events(obs)
    beats, downbeats, onsets, beat_findings = _checked_beats(obs)
    out.findings.extend(event_findings + beat_findings)

    parts: list[str] = []
    if obs.speech:
        lang = _language(obs)
        n_spk = obs.voice.speaker_count
        speech = f"{len(obs.speech)} spoken segment(s)"
        if lang:
            speech += f" in {lang}"
        if n_spk:
            speech += f", {n_spk} speaker" + ("s" if n_spk != 1 else "")
        parts.append(speech)
    if obs.music.present:
        character = _music_character(obs)
        parts.append(f"a musical layer{' — ' + character if character else ''}")
    if events:
        named = ", ".join(f"{e.label} at {_fmt_time(e.start_s)}" for e in events[:3])
        parts.append(f"{len(events)} sound event(s) ({named}"
                     + (", …" if len(events) > 3 else "") + ")")
    if obs.rhythm.tempo_bpm:
        out.planner_facts.append(f"tempo_bpm={obs.rhythm.tempo_bpm:.1f}")

    out.characterisation = ("the source video's existing soundtrack: "
                            + ("; ".join(parts) if parts else "no speech, music or distinct "
                               "events detected"))
    if obs.speech:
        out.planner_facts.append(f"spoken_segments={len(obs.speech)}")
        if _language(obs):
            out.planner_facts.append(f"language={_language(obs)}")
    for e in events:
        out.planner_facts.append(f"source_event={e.label}@{e.start_s:.2f}s")
    if beats:
        out.timeline_constraints.append({
            "type": "beat_grid",
            "tempo_bpm": obs.rhythm.tempo_bpm,
            "beats_s": list(beats),
            "downbeats_s": list(downbeats),
            "max_snap_ms": MAX_BEAT_SNAP_MS,
        })
    return out
