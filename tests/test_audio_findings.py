"""The audio validator findings: A22 in the text, A23/A24 in the projection (spec §23).

A20 and A21 are deliberately NOT new rules: R22-audio-marker-role already holds the marker
side for music_style and beat_reference, and R27-reference-audio-claimed-as-copied holds the
prose side. The mapping tests below pin that equivalence, so the spec's cases stay covered
without two rule IDs asserting one fact.

A27 (a caller/analyser conflict must be visible) is structural and needs no rule: the conflict
check and the A9 finding are the same code path in projector.project_audio, so the finding
cannot be absent when the conflict exists. That is stated here so the gap reads as a decision.
"""
from __future__ import annotations

from h3ir.audio.models import (AudioEvent, AudioObservation, AudioRhythm,
                               AudioSignalFacts)
from h3ir.audio.projector import project_audio
from h3ir.models import Role
from h3ir.validate import Context, validate


def _doc(defs_audio_line: str, retention_line: str = "") -> str:
    return ("subject_definitions:\n<Subject 1> is the caller in <Picture 1>, with a red coat.\n"
            f"{defs_audio_line}\n\n"
            "summary:\n[reference generation + audio reference] The target video shows "
            "<Subject 1>.\n\n"
            f"retention_analysis:\n{retention_line}\n\n"
            "detailed_description:\n[Shot 1] The camera holds a static shot on <Subject 1> in "
            "the hall.\n\n"
            "overall_soundscape:\nRoom tone.\n\nnon_diegetic_music:\nN/A\n")


def _rules(text: str, **kw) -> dict[str, str]:
    ctx = Context(mode="ref2va", n_pictures=1, n_audios=1, duration_s=5.167, **kw)
    return {f.rule: f.msg for f in validate(text, ctx)}


# ---------------------------------------------------------------- A22: words are not a voice

def test_a_voice_defined_by_quoting_its_speech_is_flagged():
    """Spec §14.1's own anti-example: 'a voice saying \"Don't move\"' standing in for timbre."""
    found = _rules(_doc('<Audio 1> is the voice-timbre reference for the speaker (S1), '
                        'containing a spoken vocal layer — a voice saying "Don\'t move".'),
                   declared_roles=(("<Audio 1>", "voice_timbre", ""),))
    assert "A22-voice-from-transcript-only" in found
    assert "WARN" not in found["A22-voice-from-transcript-only"]  # severity lives on Finding


def test_a_definition_that_is_the_transcript_is_flagged():
    found = _rules(_doc("<Audio 1> is the voice-timbre reference for the speaker (S1), "
                        "containing a spoken vocal layer — We close at six, not half past."),
                   declared_roles=(("<Audio 1>", "voice_timbre", ""),),
                   audio_transcripts=(("<Audio 1>", "We close at six, not half past."),))
    assert "A22-voice-from-transcript-only" in found


def test_a_real_timbre_description_does_not_fire():
    """The input that must NOT trip the rule: pitch, energy and pace are timbre, whatever the
    transcript says."""
    found = _rules(_doc("<Audio 1> is the voice-timbre reference for the speaker (S1), "
                        "containing a spoken vocal layer — a soft, low voice with a slow, "
                        "tense delivery."),
                   declared_roles=(("<Audio 1>", "voice_timbre", ""),),
                   audio_transcripts=(("<Audio 1>", "We close at six, not half past."),))
    assert "A22-voice-from-transcript-only" not in found


def test_timbre_first_and_a_quotation_after_it_does_not_fire():
    """'says', not 'saying': the quotation illustrates a described voice, it does not replace it."""
    found = _rules(_doc("<Audio 1> is the voice-timbre reference for the speaker (S1), "
                        "containing a spoken vocal layer — a gravelly low voice; she says "
                        "'we close at six'."),
                   declared_roles=(("<Audio 1>", "voice_timbre", ""),),
                   audio_transcripts=(("<Audio 1>", "We close at six, not half past."),))
    assert "A22-voice-from-transcript-only" not in found


# ------------------------------------------------- A20/A21: already held by R22 and R27

def test_spec_a20_music_style_claimed_as_copied_is_r22_and_r27():
    """Spec A20's case, held by the existing rules: the marker side is R22, the prose side R27."""
    marker = _rules(_doc("<Audio 1> is a music-style reference for the target video's newly "
                         "generated score.",
                         "<Audio 1>: partially_copy - the track is reused beneath the mix."),
                    declared_roles=(("<Audio 1>", "music_style", ""),))
    assert "R22-audio-marker-role" in marker
    prose = _rules(_doc("<Audio 1> is a music-style reference for the target video's score. "
                        "<Audio 1> is reused as the complete final audio track."),
                   declared_roles=(("<Audio 1>", "music_style", ""),))
    assert "R27-reference-audio-claimed-as-copied" in prose


def test_spec_a21_beat_reference_must_be_a_reference_is_r22():
    found = _rules(_doc("<Audio 1> is a beat reference whose rhythm sets the timing.",
                        "<Audio 1>: fully_copy - the track is the final audio."),
                   declared_roles=(("<Audio 1>", "beat_reference", ""),))
    assert "R22-audio-marker-role" in found


# ---------------------------------------------------------------- A23/A24: broken analyser data

def _obs(**kw) -> AudioObservation:
    base = dict(sha256="e" * 64, signal=AudioSignalFacts(duration_s=6.0))
    base.update(kw)
    return AudioObservation(**base)


def test_an_out_of_range_event_is_dropped_with_a_warning():
    obs = _obs(events=[AudioEvent(start_s=4.23, end_s=4.31, label="metallic impact"),
                       AudioEvent(start_s=6.10, end_s=7.00, label="ghost")])
    p = project_audio(obs, Role.SFX)
    assert any(f.rule == "A23-audio-event-out-of-range" and f.severity == "WARN"
               for f in p.findings)
    # Dropped, not clamped: the projection never sees the timestamp nobody measured.
    assert "ghost" not in p.characterisation
    spans = [(c["start_s"], c["end_s"]) for c in p.timeline_constraints
             if c["type"] == "sfx_event"]
    assert spans == [(4.23, 4.31)]


def test_an_in_range_event_raises_nothing():
    obs = _obs(events=[AudioEvent(start_s=4.23, end_s=4.31, label="metallic impact")])
    assert project_audio(obs, Role.SFX).findings == []


def test_a_non_monotonic_beat_grid_is_stood_down_with_a_warning():
    obs = _obs(rhythm=AudioRhythm(tempo_bpm=128.0, beat_times_s=[0.47, 0.94, 0.90, 1.41]))
    p = project_audio(obs, Role.BEAT_REFERENCE)
    assert any(f.rule == "A24-beat-times-not-monotonic" for f in p.findings)
    # No grid, no snapping, no named accents -- but the tempo is one number and still true.
    assert not [c for c in p.timeline_constraints if c["type"] == "beat_grid"]
    assert "prominent accents" not in p.characterisation
    assert "128 BPM" in p.characterisation


def test_a_monotonic_grid_projects_normally():
    obs = _obs(rhythm=AudioRhythm(tempo_bpm=128.0, beat_times_s=[0.47, 0.94, 1.41]))
    p = project_audio(obs, Role.BEAT_REFERENCE)
    assert p.findings == []
    assert any(c["type"] == "beat_grid" for c in p.timeline_constraints)
