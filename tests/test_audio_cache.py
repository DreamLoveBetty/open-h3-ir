"""The observation cache: byte-derived facts are cached, request-specific projections are not.

The property under test is the line spec §16 draws and the old card-cache bug (documented in
test_audio_card_is_not_cached.py) taught from the other direction. One audio file attached as
`bgm`, `music_style` and `beat_reference` must produce ONE worker analysis and ONE cache
entry, because the observation is a function of the bytes -- and three different cards,
because the projection is a function of the request.

Every test here runs cold against a tmp state dir: the falsification log in this repo has a
cache short-circuiting the code under test before, and a warm global cache would do it again.
"""
from __future__ import annotations

import json

import pytest

from h3ir.analyse import analyse_audio
from h3ir.audio.cache import (load_observation, observation_key, save_observation)
from h3ir.audio.client import WorkerInfo
from h3ir.audio.observer import observe_audio
from h3ir.config import AudioConfig, Config, Paths, get_config, set_config
from h3ir.models import AssetKind, AssetRef, Role

from fake_audio_worker import FakeWorker, sample_observation

SHA = "a" * 64


@pytest.fixture
def audio_state(tmp_path):
    """An isolated config with audio on and a tmp cache; restored after the test."""
    old = get_config()
    set_config(Config(paths=Paths(state_dir=tmp_path),
                      audio=AudioConfig(enabled=True, base_url="http://worker.test")))
    yield tmp_path
    set_config(old)


def _ref(role: Role, note: str) -> AssetRef:
    return AssetRef(kind=AssetKind.AUDIO, role=role, sha256=SHA, seconds=3.0,
                    note=note, path="clip.wav")


def test_same_bytes_three_roles_one_worker_call_and_three_cards(audio_state):
    worker = FakeWorker()
    cards = [analyse_audio(_ref(role, note), audio_backend=worker)
             for role, note in ((Role.BGM, "a slow drone"),
                                (Role.MUSIC_STYLE, "use only the style"),
                                (Role.BEAT_REFERENCE, "cut on the hits"))]
    assert worker.analyse_calls == 1, "the observation is byte-derived; analyse once"
    entries = list((audio_state / "cache" / "audio").glob("*.json"))
    assert len(entries) == 1, "one cache entry for one file, however it is used"
    # ...while the projections stay request-specific.
    assert "background music track" in cards[0].summary
    assert "music-style reference" in cards[1].summary
    assert "rhythmic reference" in cards[2].summary
    assert [c.characterisation for c in cards] == ["a slow drone", "use only the style",
                                                   "cut on the hits"]


def test_a_cache_hit_never_calls_analyse(audio_state):
    FakeWorker()  # first run populates
    analyse_audio(_ref(Role.BGM, "first"), audio_backend=FakeWorker())
    warm = FakeWorker()
    card = analyse_audio(_ref(Role.SFX, "second"), audio_backend=warm)
    assert warm.analyse_calls == 0
    assert warm.health_calls == 1, "the key needs the worker identity; the analysis does not"
    assert card.audio_observation is not None
    assert card.audio_observation.rhythm.tempo_bpm == 128.0


def test_the_key_excludes_everything_request_specific():
    """Role, note, target duration and request text are projection inputs. In the key they
    would be content addressed that contributes nothing -- the exact poisoning the card cache
    suffered."""
    w = WorkerInfo(version="audio-worker-1", models={"sensevoice": "SenseVoiceSmall"})
    assert observation_key(SHA, w) == observation_key(SHA, w)
    other = WorkerInfo(version="audio-worker-2", models={"sensevoice": "SenseVoiceSmall"})
    assert observation_key(SHA, w) != observation_key(SHA, other), \
        "the transforming logic is part of the key"
    models = WorkerInfo(version="audio-worker-1", models={"sensevoice": "other-build"})
    assert observation_key(SHA, w) != observation_key(SHA, models), "and so are the models"


def test_a_corrupt_entry_is_a_miss_not_a_crash(audio_state):
    worker = FakeWorker()
    observe_audio(_ref(Role.BGM, "x"), get_config(), client=worker)
    (path,) = (audio_state / "cache" / "audio").glob("*.json")
    path.write_text("{ not json")
    again = FakeWorker()
    observe_audio(_ref(Role.BGM, "x"), get_config(), client=again)
    assert again.analyse_calls == 1, "a corrupt entry must be re-analysed, not served"


def test_an_entry_claiming_other_bytes_is_not_served(audio_state):
    worker = FakeWorker()
    assert load_observation(SHA, worker.info) is None
    obs = sample_observation(sha256="b" * 64)
    save_observation(obs, worker.info)  # stored under b's key; now lie about who's asking
    assert load_observation(SHA, WorkerInfo(version="audio-worker-1",
                                            models=worker.info.models)) is None


def test_disabling_the_cache_analyses_every_time_and_writes_nothing(audio_state):
    set_config(Config(paths=Paths(state_dir=audio_state),
                      audio=AudioConfig(enabled=True, base_url="http://worker.test",
                                        cache_enabled=False)))
    worker = FakeWorker()
    analyse_audio(_ref(Role.BGM, "x"), audio_backend=worker)
    analyse_audio(_ref(Role.BGM, "x"), audio_backend=worker)
    assert worker.analyse_calls == 2
    assert not (audio_state / "cache" / "audio").exists() or \
        not list((audio_state / "cache" / "audio").glob("*.json"))


def test_the_cached_observation_round_trips_through_disk(audio_state):
    worker = FakeWorker()
    first, _ = observe_audio(_ref(Role.BGM, "x"), get_config(), client=worker)
    loaded = load_observation(SHA, worker.info)
    assert loaded == first
    assert loaded.hash() == first.hash()
    # The file on disk is the observation contract, not a pickle of implementation details.
    raw = json.loads(next((audio_state / "cache" / "audio").glob("*.json")).read_text())
    assert raw["analyzer_version"] == "audio-1"
    assert raw["rhythm"]["tempo_bpm"] == 128.0
