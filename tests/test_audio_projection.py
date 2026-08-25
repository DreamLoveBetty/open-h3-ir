"""Role-aware projection: the same Observation must tell five different truths (spec §28.2).

The fixture is ONE observation — a 128 BPM electronic track — projected into the roles that
must not be conflated, because each conflation writes a retention claim the render does not
deliver. The assertions are on the projection itself; render.py's side of the same contract
(the definition stems and the marker table) is pinned by the existing validator tests.
"""
from __future__ import annotations

from h3ir.audio.models import (AudioEvent, AudioMusicProfile, AudioObservation,
                               AudioRhythm, AudioSignalFacts, AudioVoiceProfile,
                               TimedSpeech)
from h3ir.audio.projector import MAX_BEAT_SNAP_MS, project_audio
from h3ir.models import Role


def _track() -> AudioObservation:
    """A 128 BPM electronic track, per spec §28.2. No speech, a musical layer, a beat grid
    longer than the prose may ever name."""
    return AudioObservation(
        sha256="b" * 64,
        signal=AudioSignalFacts(duration_s=6.0, sample_rate=48000, channels=2),
        music=AudioMusicProfile(present=True, genres=["electronic"],
                                instruments=["synth bass"], mood=["driving"]),
        rhythm=AudioRhythm(tempo_bpm=128.0, confidence=0.94,
                           beat_times_s=[0.47, 0.94, 1.41, 1.88, 2.34, 2.81, 3.28],
                           downbeat_times_s=[1.90, 3.80, 5.70]),
    )


def _voice() -> AudioObservation:
    return AudioObservation(
        sha256="c" * 64,
        signal=AudioSignalFacts(duration_s=3.0, sample_rate=48000, channels=1),
        speech=[TimedSpeech(start_s=0.5, end_s=2.4, text="Don't move.", language="en",
                            speaker_id="SPK_0", emotion="tense", confidence=0.93)],
        voice=AudioVoiceProfile(speaker_count=1, pitch_class="low", energy="low",
                                pace="slow", emotions=["tense"]),
    )


# --- the mutually exclusive truths of one 128 BPM track -------------------------------------

def test_bgm_is_signal_reuse_and_never_a_style_reference():
    p = project_audio(_track(), Role.BGM)
    assert "background music" in p.characterisation
    assert "synchronized" in p.characterisation
    assert "128" in p.characterisation
    # The one phrase this role may not produce (A20 checks the rendered side).
    assert "newly generated" not in p.characterisation
    assert "style" not in p.characterisation.lower()


def test_music_style_projects_style_properties_and_a_new_score():
    p = project_audio(_track(), Role.MUSIC_STYLE)
    assert "newly generated score" in p.characterisation
    assert "electronic" in p.characterisation
    assert "128" in p.characterisation
    # It must not read as the signal being taken. "rather than supplying the audio itself" is
    # the sanctioned negative; a reuse CLAIM is the offence.
    for claim in ("is reused", "copied", "1:1", "as the target video's audio track"):
        assert claim not in p.characterisation


def test_beat_reference_projects_timing_and_not_the_signal():
    p = project_audio(_track(), Role.BEAT_REFERENCE)
    assert "rhythm" in p.characterisation
    assert "128" in p.characterisation
    # Salient accents named from the downbeat tier, per spec §14.4's example.
    assert "1.90s" in p.characterisation and "5.70s" in p.characterisation
    for claim in ("is reused", "copied", "1:1"):
        assert claim not in p.characterisation
    # The FULL grid travels machine-facing for beat snapping; the prose never sees it.
    grid = next(c for c in p.timeline_constraints if c["type"] == "beat_grid")
    assert len(grid["beats_s"]) == 7 and grid["max_snap_ms"] == MAX_BEAT_SNAP_MS
    # ...while the planner gets at most the salient few.
    beats_fact = next(f for f in p.planner_facts if f.startswith("salient_beats_s="))
    assert beats_fact.count(",") <= 2


def test_voice_timbre_projects_the_voice_and_never_the_words():
    p = project_audio(_voice(), Role.VOICE_TIMBRE)
    assert "low-pitched" in p.characterisation
    assert "English" in p.characterisation
    assert "slow" in p.characterisation and "tense" in p.characterisation
    # The transcript is dialogue content, not a timbre description (spec §14.1; A22 holds the
    # IR side of the same rule).
    assert "Don't move" not in p.characterisation
    assert "transcript_available=true" in p.planner_facts


def test_sfx_projects_events_as_a_reference():
    obs = _track()
    obs.events = [AudioEvent(start_s=4.23, end_s=4.31, label="metallic impact",
                             confidence=0.88, source="clap")]
    p = project_audio(obs, Role.SFX)
    assert "sound-texture reference" in p.characterisation
    assert "metallic impact" in p.characterisation and "4.23s" in p.characterisation
    events = [c for c in p.timeline_constraints if c["type"] == "sfx_event"]
    assert [e["start_s"] for e in events] == [4.23]


# --- the caller's note: intent leads, facts follow, conflicts surface -----------------------

def test_the_note_leads_and_the_projection_follows():
    p = project_audio(_track(), Role.MUSIC_STYLE, caller_note="the client's title track")
    assert p.characterisation.startswith("the client's title track;")
    assert "newly generated score" in p.characterisation


def test_an_empty_note_leaves_the_projection_to_characterise():
    p = project_audio(_track(), Role.BGM, caller_note="")
    assert "background music" in p.characterisation


def test_note_discrepancy_warns_and_resolves_nothing():
    p = project_audio(_voice(), Role.VOICE_TIMBRE, caller_note="instrumental, no speech")
    a1 = [f for f in p.findings if f.rule == "A9-audio-note-discrepancy"]
    assert len(a1) == 1 and a1[0].severity == "WARN"
    # Neither side is rewritten: the note still leads, the speech fact still appears.
    assert p.characterisation.startswith("instrumental, no speech;")
    assert "transcript_available=true" in p.planner_facts


def test_note_discrepancy_for_music():
    p = project_audio(_track(), Role.BGM, caller_note="no music, just ambience")
    assert any(f.rule == "A9-audio-note-discrepancy" for f in p.findings)


def test_a_note_that_agrees_raises_nothing():
    p = project_audio(_voice(), Role.VOICE_TIMBRE, caller_note="a low, tense whisper")
    assert p.findings == []


def test_a_speechy_note_claiming_no_music_but_music_present_is_the_only_music_trigger():
    # "no music" against a spoken-word recording must NOT fire: conservative means the music
    # check requires the analyser to have actually found a musical layer.
    p = project_audio(_voice(), Role.VOICE_TIMBRE, caller_note="no music at all")
    assert p.findings == []


# --- plan-level integration: the projection reaches the manifest, the render and the ask ----

from h3ir.compile import wiring_findings, _audio_projections
from h3ir.draft import deterministic_draft
from h3ir.models import AssetCard, AssetKind, AssetRef, Brief, Mode
from h3ir.plan import ProfileOptions, build_plan
from h3ir.prose import audio_projection_facts
from h3ir.render import render_ir, render_subject_definitions


def _brief_with_audio(role: Role, note: str = "") -> Brief:
    return Brief(intent="a car commercial with a driving beat", seconds=8.0,
                 assets=[AssetRef(kind=AssetKind.AUDIO, role=role, sha256="b" * 64,
                                  seconds=6.0, note=note)])


def _card_with_obs(obs: AudioObservation) -> AssetCard:
    return AssetCard(sha256=obs.sha256, kind=AssetKind.AUDIO, audio_observation=obs)


def test_build_plan_hydrates_the_manifest_from_the_observation():
    brief = _brief_with_audio(Role.BGM, note="the client's title track")
    plan = build_plan(brief, Mode.REF2VA, {"b" * 64: _card_with_obs(_track())},
                      opts=ProfileOptions())
    entry = next(m for m in plan.manifest if m.kind is AssetKind.AUDIO)
    assert entry.characterisation.startswith("the client's title track;")
    assert "background music" in entry.characterisation and "128" in entry.characterisation
    assert plan.audio_context is not None
    assert plan.audio_context.planner_facts["<Audio 1>"]


def test_the_legacy_path_is_untouched():
    """No observation means no projection: the note IS the characterisation, and 'not analysed'
    raises nothing."""
    brief = _brief_with_audio(Role.BGM, note="the client's title track")
    plan = build_plan(brief, Mode.REF2VA, {"b" * 64: AssetCard(sha256="b" * 64,
                                                               kind=AssetKind.AUDIO)},
                      opts=ProfileOptions())
    entry = next(m for m in plan.manifest if m.kind is AssetKind.AUDIO)
    assert entry.characterisation == "the client's title track"
    assert plan.audio_context.findings == [] and plan.audio_context.planner_facts == {}


def test_the_projected_characterisation_reaches_the_definition_line():
    brief = _brief_with_audio(Role.BEAT_REFERENCE)
    cards = {"b" * 64: _card_with_obs(_track())}
    plan = build_plan(brief, Mode.REF2VA, cards, opts=ProfileOptions())
    defs = render_subject_definitions(plan)
    assert "a beat reference" in defs
    assert "128 BPM" in defs and "1.90s" in defs
    # The full grid must NOT leak into the prose-facing text.
    assert "0.47s" not in defs


def test_a_note_conflict_surfaces_as_a_wiring_finding_on_the_draft():
    brief = _brief_with_audio(Role.MUSIC_STYLE, note="instrumental, no speech")
    obs = _track()
    obs.speech = [TimedSpeech(start_s=0.5, end_s=2.4, text="hey", language="en")]
    plan = deterministic_draft(brief, Mode.REF2VA, {obs.sha256: _card_with_obs(obs)},
                               opts=ProfileOptions())
    rules = [f.rule for f in wiring_findings(plan, brief)]
    assert "A9-audio-note-discrepancy" in rules


def test_the_projection_is_byte_reproducible_through_the_renderer():
    brief = _brief_with_audio(Role.MUSIC_STYLE)
    cards = {"b" * 64: _card_with_obs(_track())}
    plan = deterministic_draft(brief, Mode.REF2VA, cards, opts=ProfileOptions())
    assert render_ir(plan).prompt == render_ir(plan).prompt


def test_the_ask_carries_the_compressed_facts_and_never_the_grid():
    brief = _brief_with_audio(Role.BEAT_REFERENCE)
    cards = {"b" * 64: _card_with_obs(_track())}
    plan = build_plan(brief, Mode.REF2VA, cards, opts=ProfileOptions())
    projections = _audio_projections(plan)
    assert [p[0] for p in projections] == ["<Audio 1>"]
    block = audio_projection_facts(projections)
    assert '"role": "beat_reference"' in block
    assert "tempo_bpm=128.0" in block
    # spec §22: the planner gets the salient beats, never the raw observation's grid.
    assert "0.47" not in block
    assert audio_projection_facts(()) == ""
