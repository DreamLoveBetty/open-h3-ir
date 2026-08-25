"""Timeline audio: beat snapping, SFX -> shot mapping, ambient detection (spec §18, §28.5).

The snapping tests hold the two directions of spec §28.5 -- 3.67s pulls onto a 3.80s beat
inside the 250ms window, and does NOT move when the nearest beat is 4.10s -- plus the guards
that keep following the beat from ever breaking the edit. The mapping tests hold that a
located sound lands in the shot it happened in, and that a sound spanning most of its asset is
the scene's weather, not an event.
"""
from __future__ import annotations

from h3ir.audio.models import (AudioEvent, AudioObservation, AudioRhythm,
                               AudioSignalFacts)
from h3ir.audio.projector import MAX_BEAT_SNAP_MS
from h3ir.models import (AssetCard, AssetKind, AssetRef, AudioPlanContext, Brief, Mode,
                         Role, ShotPlan)
from h3ir.plan import (AMBIENT_COVERAGE, MIN_SHOT_MS, ProfileOptions, build_plan,
                       map_audio_events, snap_cuts_to_beats)


def _shots(*bounds_ms: int) -> list[ShotPlan]:
    return [ShotPlan(n=i + 1, start_ms=bounds_ms[i], end_ms=bounds_ms[i + 1])
            for i in range(len(bounds_ms) - 1)]


# --------------------------------------------------------------------------- beat snapping

def test_a_cut_inside_the_window_snaps_onto_the_beat():
    """Spec §28.5's own numbers: the model proposed 3.67s, the beat is at 3.80s."""
    shots = _shots(0, 3670, 6000)
    snaps = snap_cuts_to_beats(shots, [1.90, 3.80, 5.70], MAX_BEAT_SNAP_MS)
    assert snaps == [(2, 3670, 3800)]
    # The cut is shared: both shots it separates see the move.
    assert shots[0].end_ms == 3800 and shots[1].start_ms == 3800


def test_a_cut_outside_the_window_does_not_move():
    """Nearest beat 4.10s: 430ms away is a different edit, not a refinement of this one."""
    shots = _shots(0, 3670, 6000)
    assert snap_cuts_to_beats(shots, [4.10], MAX_BEAT_SNAP_MS) == []
    assert shots[1].start_ms == 3670


def test_the_first_cut_is_the_video_start_and_never_moves():
    shots = _shots(0, 2000, 4000)
    snap_cuts_to_beats(shots, [0.10, 2.00], MAX_BEAT_SNAP_MS)
    assert shots[0].start_ms == 0


def test_a_snap_that_would_squeeze_a_shot_under_the_floor_is_skipped():
    """The grid loses to the structure: 1.60s -> 1.40s is inside the window but leaves the
    opening shot at 1.40s, under the 1.50s floor."""
    shots = _shots(0, 1600, 4000)
    assert snap_cuts_to_beats(shots, [1.40], MAX_BEAT_SNAP_MS) == []
    assert shots[1].start_ms == 1600


def test_several_cuts_snap_independently():
    shots = _shots(0, 1900, 3760, 6000)
    snaps = snap_cuts_to_beats(shots, [1.90, 3.80], MAX_BEAT_SNAP_MS)
    assert (3, 3760, 3800) in snaps and (2, 1900, 1900) not in snaps
    starts = [s.start_ms for s in shots]
    assert starts == sorted(starts) and len(set(starts)) == len(starts)


# --------------------------------------------------------------------------- SFX -> shot

def _ctx_with_events(events: list[AudioEvent], asset_s: float) -> AudioPlanContext:
    ctx = AudioPlanContext()
    ctx.timeline_constraints["<Audio 1>"] = [
        {"type": "sfx_event", "start_s": e.start_s, "end_s": e.end_s, "label": e.label,
         "asset_duration_s": asset_s} for e in events]
    return ctx


def test_an_event_lands_in_the_shot_that_contains_its_onset():
    """Spec §18.2: a metallic impact at 4.23s, shot 2 spanning 3.8-6.4s."""
    shots = _shots(0, 3800, 6400)
    ctx = _ctx_with_events([AudioEvent(start_s=4.23, end_s=4.31, label="metallic impact")], 6.0)
    sync, ambient = map_audio_events(shots, ctx)
    assert sync == {2: ["a metallic impact"]} and ambient == []


def test_a_long_event_is_ambience_not_an_event():
    """0.0-5.4s of a 6.0s asset is 90% coverage: the weather of the scene, said once."""
    shots = _shots(0, 3000, 6000)
    ctx = _ctx_with_events([AudioEvent(start_s=0.0, end_s=5.4, label="rain")], 6.0)
    sync, ambient = map_audio_events(shots, ctx)
    assert sync == {} and ambient == ["rain continues throughout the video"]


def test_just_under_the_coverage_threshold_is_still_an_event():
    shots = _shots(0, 3000, 6000)
    span = 6.0 * AMBIENT_COVERAGE - 0.1
    ctx = _ctx_with_events([AudioEvent(start_s=1.0, end_s=1.0 + span, label="crowd")], 6.0)
    sync, ambient = map_audio_events(shots, ctx)
    assert ambient == [] and sync == {1: ["a crowd"]}


def test_an_onset_past_the_last_cut_belongs_to_the_last_shot():
    shots = _shots(0, 3000, 6000)
    ctx = _ctx_with_events([AudioEvent(start_s=5.9, end_s=6.0, label="explosion")], 6.0)
    sync, _ambient = map_audio_events(shots, ctx)
    assert sync == {2: ["an explosion"]}


# --------------------------------------------------------------------------- through build_plan

def _brief(role: Role) -> Brief:
    return Brief(intent="a test render", seconds=8.0,
                 assets=[AssetRef(kind=AssetKind.AUDIO, role=role, sha256="d" * 64,
                                  seconds=6.0)])


def _card(obs: AudioObservation) -> AssetCard:
    return AssetCard(sha256=obs.sha256, kind=AssetKind.AUDIO, audio_observation=obs)


def test_build_plan_snaps_a_cut_onto_a_wired_beat_reference():
    """Integration: learn where the even split puts the cut, then put a beat 100ms after it --
    inside the window -- and the rebuilt plan must land on the beat."""
    obs = AudioObservation(sha256="d" * 64, signal=AudioSignalFacts(duration_s=6.0),
                           rhythm=AudioRhythm(tempo_bpm=128.0, beat_times_s=[0.5]))
    cards = {"d" * 64: _card(obs)}
    plain = build_plan(_brief(Role.BGM), Mode.REF2VA, cards, opts=ProfileOptions())
    assert len(plain.shots) > 1
    cut_s = plain.shots[1].start_ms / 1000.0
    obs.rhythm.beat_times_s = [cut_s + 0.10]
    snapped = build_plan(_brief(Role.BEAT_REFERENCE), Mode.REF2VA, cards,
                         opts=ProfileOptions())
    assert snapped.shots[1].start_ms == plain.shots[1].start_ms + 100
    assert any(f.rule == "X20-beat-snapped" for f in snapped.audio_context.findings)


def test_build_plan_maps_sfx_events_into_shots_and_ambience():
    obs = AudioObservation(
        sha256="d" * 64, signal=AudioSignalFacts(duration_s=6.0),
        events=[AudioEvent(start_s=4.23, end_s=4.31, label="metallic impact"),
                AudioEvent(start_s=0.0, end_s=5.4, label="rain")])
    plan = build_plan(_brief(Role.SFX), Mode.REF2VA, {"d" * 64: _card(obs)},
                      opts=ProfileOptions())
    hit = next((s for s in plan.shots if s.start_ms <= 4230 < s.end_ms), plan.shots[-1])
    assert "a metallic impact" in hit.sync_sound
    assert "rain continues throughout the video" in plan.ambient_sound
    # The partition still holds: an ambient sound appears in no shot.
    assert all("rain continues" not in snd for s in plan.shots for snd in s.sync_sound)
