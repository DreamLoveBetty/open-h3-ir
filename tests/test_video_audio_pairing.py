"""A reference video's OWN soundtrack is observed, never labelled (spec §19).

The spec's literal reading -- extract the track, run the Audio Observer, "keep two logical
assets <Video N> / <Audio N>" -- stops one step short here, and deliberately: the runtime
emits an <Audio N> label only for a soundtrack WIRED as ref_video_audio_k (ref-en.txt 2.5,
validator M7/M8), and an embedded track is not wired. Synthesising a manifest entry for it
would hand the document a label the runtime never emits, shift every later audio's ordinal
(design 1.2 / I1), and let derive_task_types claim an audio reuse nobody can deliver.

So the observation lives on the VIDEO card as `soundtrack_observation` -- a separate field,
never the visual fields -- and reaches the plan as writer-facing facts keyed by the video's
label, plus one thing that does travel structurally: the beat grid, because an edit preserves
the source's timing and snapping the target's cuts to the source's pulse is exactly "soundtrack
timing enters H3 planning".

These tests hold that shape: extraction, the card-cache line, the no-label invariant, the
snap, and the ask's own statement that this audio is not a wired input.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from h3ir.analyse import (AssetAnalysisError, analyse_all, extract_soundtrack, sha256_file)
from h3ir.audio.models import (AudioEvent, AudioObservation, AudioRhythm, AudioSignalFacts)
from h3ir.audio.projector import project_soundtrack
from h3ir.compile import _audio_provenance, _soundtrack_projections
from h3ir.config import AudioConfig, Config, Paths, get_config, set_config
from h3ir.models import AssetCard, AssetKind, AssetRef, Brief, Mode, Role
from h3ir.plan import ProfileOptions, build_plan
from h3ir.prose import soundtrack_facts

from fake_audio_worker import FakeWorker, UnreachableWorker, sample_observation

ffmpeg = pytest.mark.skipif(
    not (shutil.which("ffmpeg") and shutil.which("ffprobe")),
    reason="ffmpeg/ffprobe missing — soundtrack extraction cannot work on this machine")


@pytest.fixture(scope="module")
def voiced_clip(tmp_path_factory) -> Path:
    """A video WITH an audio track: the animated test pattern plus a 440 Hz sine."""
    out = tmp_path_factory.mktemp("voiced") / "clip.mp4"
    subprocess.run(["ffmpeg", "-nostdin", "-y",
                    "-f", "lavfi", "-i", "testsrc=size=320x180:rate=24:duration=6",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=6",
                    "-pix_fmt", "yuv420p", "-shortest", str(out)],
                   capture_output=True, timeout=120, check=True)
    return out


@pytest.fixture(scope="module")
def silent_clip(tmp_path_factory) -> Path:
    """The same pictures, no audio stream at all."""
    out = tmp_path_factory.mktemp("silent") / "clip.mp4"
    subprocess.run(["ffmpeg", "-nostdin", "-y",
                    "-f", "lavfi", "-i", "testsrc=size=320x180:rate=24:duration=6",
                    "-pix_fmt", "yuv420p", str(out)],
                   capture_output=True, timeout=120, check=True)
    return out


@pytest.fixture
def state(tmp_path):
    """An isolated config: audio on, tmp cache. The card cache, the soundtrack wavs and the
    observation cache all land under it, so every test below runs cold."""
    old = get_config()
    set_config(Config(paths=Paths(state_dir=tmp_path),
                      audio=AudioConfig(enabled=True, base_url="http://worker.test")))
    yield tmp_path
    set_config(old)


class _Vision:
    """analyse_all's vision half: a recorded json_call answering the video card schema."""

    class cfg:
        model = "test-model"

    def json_call(self, messages, schema, **kw):
        return {"summary": "a grey bar slides across a running counter", "subjects": []}


def _video_ref(clip: Path, note: str = "") -> AssetRef:
    return AssetRef(kind=AssetKind.VIDEO, role=Role.EDIT_SOURCE,
                    sha256=sha256_file(clip), path=str(clip), note=note)


# --------------------------------------------------------------------------- extraction

@ffmpeg
def test_extraction_pulls_the_audio_track_out_of_a_video(state, voiced_clip):
    wav = extract_soundtrack(voiced_clip, sha256_file(voiced_clip))
    assert wav is not None and wav.stat().st_size > 1000
    assert wav.suffix == ".wav"
    # 16 kHz mono, per the observer's input contract.
    probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a",
                            "-show_entries", "stream=sample_rate,channels",
                            "-of", "csv=p=0", str(wav)],
                           capture_output=True, text=True, timeout=60)
    assert probe.stdout.strip() == "16000,1"
    # Cached on the video's content hash: a second extraction reuses the bytes.
    mtime = wav.stat().st_mtime_ns
    assert extract_soundtrack(voiced_clip, sha256_file(voiced_clip)).stat().st_mtime_ns == mtime


@ffmpeg
def test_a_silent_video_extracts_to_nothing(state, silent_clip):
    """No audio stream is a fact about the clip, not a failure."""
    assert extract_soundtrack(silent_clip, sha256_file(silent_clip)) is None


# --------------------------------------------------------------------------- onto the card

@ffmpeg
def test_analyse_all_observes_the_soundtrack_onto_the_video_card(state, voiced_clip):
    worker = FakeWorker()
    ref = _video_ref(voiced_clip)
    cards = analyse_all(_Vision(), [ref], audio_backend=worker)
    card = cards[ref.sha256]
    assert worker.analyse_calls == 1
    assert card.soundtrack_observation is not None
    assert card.soundtrack_observation.rhythm.tempo_bpm == 128.0
    # The visual fields are the VISION model's alone; the audio facts never bleed into them.
    assert card.summary == "a grey bar slides across a running counter"
    assert card.frames_seen > 0


@ffmpeg
def test_a_silent_video_simply_has_no_soundtrack(state, silent_clip):
    worker = FakeWorker()
    ref = _video_ref(silent_clip)
    cards = analyse_all(_Vision(), [ref], audio_backend=worker)
    assert cards[ref.sha256].soundtrack_observation is None
    assert worker.analyse_calls == 0, "nothing to hear, so the worker is never asked"


@ffmpeg
def test_the_worker_hears_the_extracted_wav_and_never_the_videos_note(state, voiced_clip,
                                                                      monkeypatch):
    """The synthetic ref's sha is the WAV's, so the observation cache keys on the bytes the
    worker actually heard; and the video's note describes the PICTURE -- as a caller_note it
    would feed the fallback router's keyword scan with words about the wrong asset."""
    import h3ir.audio.observer as observer

    seen: dict = {}
    real = observer.observe_audio

    def spy(ref, cfg, **kw):
        seen["ref"] = ref
        return real(ref, cfg, **kw)

    monkeypatch.setattr(observer, "observe_audio", spy)
    ref = _video_ref(voiced_clip, note="a neon city at night")
    analyse_all(_Vision(), [ref], audio_backend=FakeWorker())
    heard: AssetRef = seen["ref"]
    assert heard.kind is AssetKind.AUDIO
    assert heard.path.endswith(".wav")
    assert heard.sha256 == sha256_file(heard.path)
    assert heard.sha256 != ref.sha256, "container bytes are not the soundtrack's bytes"
    assert not heard.note


@ffmpeg
def test_the_soundtrack_never_enters_the_visual_card_cache(state, voiced_clip):
    """Two caches, two keys: the visual card is the model's reading of frames (keyed on
    sha|version|model|kind), the observation is byte-derived (keyed on the wav + worker
    identity). A card-cache hit must STILL hear the video -- through the observation cache --
    and the card file on disk must never carry the observation."""
    ref = _video_ref(voiced_clip)
    first_run = FakeWorker()
    analyse_all(_Vision(), [ref], audio_backend=first_run)
    assert first_run.analyse_calls == 1

    second_run = FakeWorker()
    cards = analyse_all(_Vision(), [ref], audio_backend=second_run)
    assert second_run.analyse_calls == 0, "the observation cache answered, not the worker"
    assert second_run.health_calls == 1, "the cache key still needs the worker's identity"
    assert cards[ref.sha256].soundtrack_observation is not None, \
        "a card-cache hit does not mean a silent soundtrack"

    (card_file,) = (state / "cache" / "cards").glob("*.json")
    assert "soundtrack" not in card_file.read_text(), \
        "the observation must not ride the visual card's cache entry"


@ffmpeg
def test_a_required_worker_failure_on_a_soundtrack_raises(state, voiced_clip):
    set_config(Config(paths=Paths(state_dir=state),
                      audio=AudioConfig(enabled=True, base_url="http://worker.test",
                                        required=True)))
    with pytest.raises(AssetAnalysisError, match="audio analysis is required"):
        analyse_all(_Vision(), [_video_ref(voiced_clip)], audio_backend=UnreachableWorker())


@ffmpeg
def test_an_optional_worker_failure_degrades_to_no_soundtrack(state, voiced_clip):
    """The video card still ships -- the same rule analyse_audio has always had -- and the
    degradation is stamped for the provenance record (spec §25 via §19)."""
    cards = analyse_all(_Vision(), [_video_ref(voiced_clip)],
                        audio_backend=UnreachableWorker())
    card = cards[_video_ref(voiced_clip).sha256]
    assert card.soundtrack_observation is None
    assert card.summary == "a grey bar slides across a running counter"
    assert card.audio_degraded and "did not answer" in card.audio_degraded


@ffmpeg
def test_an_audio_disabled_config_never_extracts(state, voiced_clip):
    set_config(Config(paths=Paths(state_dir=state), audio=AudioConfig(enabled=False)))
    cards = analyse_all(_Vision(), [_video_ref(voiced_clip)], audio_backend=FakeWorker())
    assert cards[_video_ref(voiced_clip).sha256].soundtrack_observation is None
    assert not (state / "cache" / "soundtracks").exists()


# --------------------------------------------------------------------------- the projection

def _obs_with_events() -> AudioObservation:
    return AudioObservation(
        sha256="c" * 64, signal=AudioSignalFacts(duration_s=6.0),
        rhythm=AudioRhythm(tempo_bpm=120.0, beat_times_s=[0.5, 1.0, 1.5]),
        events=[AudioEvent(start_s=4.2, end_s=4.3, label="door slam")])


def test_the_projection_states_what_the_source_sounds_like():
    proj = project_soundtrack(sample_observation("b" * 64))
    assert proj.role is None, "no role: the caller wired nothing"
    assert proj.characterisation.startswith("the source video's existing soundtrack:")
    assert "spoken segment" in proj.characterisation
    assert "tempo_bpm=128.0" in proj.planner_facts
    assert "spoken_segments=1" in proj.planner_facts
    assert "language=English" in proj.planner_facts


def test_the_beat_grid_travels_but_source_events_do_not_become_target_shots():
    """The asymmetry spec §19 implies: an edit preserves the source's TIMING, so its pulse may
    snap the target's cuts; but 'the source has a door slam at 4.2s' does not entitle the plan
    to claim the TARGET does, so events are planner facts, never timeline constraints."""
    proj = project_soundtrack(_obs_with_events())
    assert [c["type"] for c in proj.timeline_constraints] == ["beat_grid"]
    assert proj.timeline_constraints[0]["beats_s"] == [0.5, 1.0, 1.5]
    assert "source_event=door slam@4.20s" in proj.planner_facts


def test_the_projection_still_stands_down_a_broken_grid():
    """A24 applies here too: out-of-order beats mean the rhythm tier is broken, and sorting
    would disguise it."""
    obs = _obs_with_events()
    obs.rhythm.beat_times_s = [1.0, 0.5]
    proj = project_soundtrack(obs)
    assert proj.timeline_constraints == []
    assert any(f.rule == "A24-beat-times-not-monotonic" for f in proj.findings)


# --------------------------------------------------------------------------- through the plan

VSHA = "e" * 64


def _edit_brief() -> Brief:
    return Brief(intent="recut this clip", seconds=8.0,
                 assets=[AssetRef(kind=AssetKind.VIDEO, role=Role.EDIT_SOURCE,
                                  sha256=VSHA, seconds=6.0)])


def _reference_brief() -> Brief:
    """A video wired as a plain reference. An EDIT_SOURCE brief allocates one span (the edit
    preserves the source's structure, so there is nothing to snap), which makes it useless for
    watching a grid move a cut; this shape allocates several shots and lets the snap show."""
    return Brief(intent="a new scene in this clip's world", seconds=8.0,
                 assets=[AssetRef(kind=AssetKind.VIDEO, role=None, sha256=VSHA, seconds=6.0)])


def _video_card(obs: AudioObservation | None) -> AssetCard:
    return AssetCard(sha256=VSHA, kind=AssetKind.VIDEO, summary="a clip",
                     soundtrack_observation=obs)


def test_a_soundtrack_mints_no_audio_label_and_no_audio_task_type():
    """The invariant this whole design exists for: the runtime emits <Audio N> only for a
    wired soundtrack (ref-en.txt 2.5), so an observed-but-unwired one must not shift the
    numbering or claim an audio task type."""
    obs = AudioObservation(sha256="c" * 64, signal=AudioSignalFacts(duration_s=6.0),
                           rhythm=AudioRhythm(tempo_bpm=120.0, beat_times_s=[0.5]))
    plan = build_plan(_edit_brief(), Mode.REF2VA, {VSHA: _video_card(obs)},
                      opts=ProfileOptions())
    assert plan.label_counts()["Audio"] == 0
    assert plan.label_counts()["Video"] == 1
    assert "audio reuse" not in plan.task_types
    assert "audio reference" not in plan.task_types
    assert "video editing" in plan.task_types
    # ...while the observation still reaches the writer, keyed by the VIDEO's label.
    char, facts = plan.audio_context.soundtracks["<Video 1>"]
    assert char.startswith("the source video's existing soundtrack:")
    assert "tempo_bpm=120.0" in facts
    assert "<Video 1>" in plan.audio_context.timeline_constraints


def test_the_soundtracks_beat_grid_snaps_the_cuts():
    """Soundtrack timing enters H3 planning: the same snapping a wired beat_reference gets,
    sourced from the video's own pulse."""
    obs = AudioObservation(sha256="c" * 64, signal=AudioSignalFacts(duration_s=6.0),
                           rhythm=AudioRhythm(tempo_bpm=128.0, beat_times_s=[0.5]))
    cards = {VSHA: _video_card(obs)}
    plain = build_plan(_reference_brief(), Mode.REF2VA, cards, opts=ProfileOptions())
    assert len(plain.shots) > 1
    cut_ms = plain.shots[1].start_ms
    obs.rhythm.beat_times_s = [cut_ms / 1000.0 + 0.10]
    snapped = build_plan(_reference_brief(), Mode.REF2VA, cards, opts=ProfileOptions())
    assert snapped.shots[1].start_ms == cut_ms + 100
    finding = next(f for f in snapped.audio_context.findings
                   if f.rule == "X20-beat-snapped")
    assert "<Video 1>" in finding.msg, "the finding names WHERE the grid came from"


def test_source_events_are_facts_for_the_writer_not_claims_about_the_target():
    obs = _obs_with_events()
    plan = build_plan(_edit_brief(), Mode.REF2VA, {VSHA: _video_card(obs)},
                      opts=ProfileOptions())
    assert all("door slam" not in snd for s in plan.shots for snd in s.sync_sound)
    _char, facts = plan.audio_context.soundtracks["<Video 1>"]
    assert "source_event=door slam@4.20s" in facts


# --------------------------------------------------------------------------- ask + provenance

def test_the_soundtrack_reaches_the_ask_as_source_side_facts():
    obs = AudioObservation(sha256="c" * 64, signal=AudioSignalFacts(duration_s=6.0),
                           rhythm=AudioRhythm(tempo_bpm=120.0, beat_times_s=[0.5]))
    plan = build_plan(_edit_brief(), Mode.REF2VA, {VSHA: _video_card(obs)},
                      opts=ProfileOptions())
    (label, char, facts), = _soundtrack_projections(plan)
    assert label == "<Video 1>"
    text = soundtrack_facts(((label, char, facts),))
    assert "not a wired input" in text
    assert "never as a" in text and "signal" in text
    assert "<Video 1>" in text
    assert "tempo_bpm=120.0" in text


def test_the_soundtrack_gets_the_same_provenance_as_a_wired_audio():
    """Spec §24's traceability does not stop at wired inputs: the same analyser chain produced
    these facts, so the same record says which bytes and which models."""
    obs = AudioObservation(sha256="c" * 64, signal=AudioSignalFacts(duration_s=6.0),
                           rhythm=AudioRhythm(tempo_bpm=120.0, beat_times_s=[0.5]),
                           model_ids={"audio_worker": "audio-worker-1",
                                      "speech": "SenseVoiceSmall"})
    cards = {VSHA: _video_card(obs)}
    plan = build_plan(_edit_brief(), Mode.REF2VA, cards, opts=ProfileOptions())
    prov = _audio_provenance(plan, cards, get_config())
    assert set(prov) == {"<Video 1>"}, "keyed by the video's label, never a minted <Audio N>"
    rec = prov["<Video 1>"]
    assert rec["projection_role"] == "edit_source (embedded soundtrack)"
    assert rec["observation_hash"] == obs.hash()
    assert rec["sensevoice_model"] == "SenseVoiceSmall"
