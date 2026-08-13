"""A clip's soundtrack has to arrive paired, or two labels end up naming one file.

The failure is worth stating precisely, because it is invisible from either side alone.
`plan.build_manifest` emits a paired soundtrack's `<Audio j>` label immediately BEFORE its
`<Video k>`, which is the order ComfyUI's own `MiniMaxH3ReferenceToVideo` presents them in. An
unpaired soundtrack instead becomes a standalone audio, numbered after every video. So if the pairing
is lost, the brief says `<Audio 1>` about one thing and the runtime says `<Audio 1>` about another,
the render is wrong, and nothing raises.

It was lost, on this machine, because the pointer to the paired clip was the one path the ComfyUI
node did not translate for a split install, and the service treated an unreadable pointer as no
pointer. Both halves are covered here.
"""
from __future__ import annotations

import wave
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from h3ir import service
from h3ir.models import AssetKind, AssetRef, Brief, Mode, Role
from h3ir.plan import build_manifest
from h3ir.grid import Target


@pytest.fixture()
def client() -> TestClient:
    return TestClient(service.app, raise_server_exceptions=False)


def _silence(path: Path, seconds: float = 1.0) -> Path:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x00\x00" * int(16000 * seconds))
    return path


# ------------------------------------------------------- the ordering the pairing decides

def _manifest(paired: bool):
    video = AssetRef(kind=AssetKind.VIDEO, role=Role.SUBJECT, sha256="v" * 64, frames=72,
                     seconds=3.0)
    sound = AssetRef(kind=AssetKind.AUDIO, role=Role.BGM, sha256="s" * 64, seconds=3.0,
                     paired_video_sha256=("v" * 64) if paired else None)
    brief = Brief(intent="x", assets=[video, sound])
    return build_manifest(brief, Target(nominal_seconds=8.0, frames=192, canvas=(1344, 768)))


def test_a_paired_soundtrack_is_labelled_before_its_own_clip():
    """The order the runtime presents them in, so it is the only order in which the labels are true."""
    got = [(m.label, m.wiring) for m in _manifest(paired=True)]
    assert got == [("<Audio 1>", "ref_video_audio_1"), ("<Video 1>", "ref_video_1")]


def test_losing_the_pairing_moves_the_label_to_a_different_file():
    """THE control. This is what the render looked like when the pointer went missing: the same
    `<Audio 1>` label, on a different wiring slot, in a different position."""
    got = [(m.label, m.wiring) for m in _manifest(paired=False)]
    assert got == [("<Video 1>", "ref_video_1"), ("<Audio 1>", "ref_audio_1")]
    assert got != [(m.label, m.wiring) for m in _manifest(paired=True)], \
        "if these ever agree, the pairing has stopped mattering and this test has stopped guarding "\
        "anything"


def test_a_paired_soundtrack_names_the_clip_it_belongs_to():
    entry = _manifest(paired=True)[0]
    assert entry.paired_with == "<Video 1>"


def test_a_standalone_sound_beside_a_paired_one_is_wired_to_the_socket_that_exists():
    """FOUND BY RENDERING. `ref_audios` and `ref_video_audios` are two separate autogrow lists on
    ComfyUI's H3 node, each numbered from 1, but the LABEL ordinal counts every audio because that is
    the order the runtime emits them in. Numbering the wiring name off the label counter published
    `<Audio 2>` riding `ref_audio_2`, a socket that does not exist: the score goes in `ref_audio_1`.

    A right label with a wrong wiring instruction is worse than either alone, because the label looks
    checked.
    """
    video = AssetRef(kind=AssetKind.VIDEO, role=Role.CONTINUATION_SOURCE, sha256="v" * 64, frames=72,
                     seconds=3.0)
    paired = AssetRef(kind=AssetKind.AUDIO, role=Role.BGM, sha256="p" * 64, seconds=3.0,
                      paired_video_sha256="v" * 64)
    score = AssetRef(kind=AssetKind.AUDIO, role=Role.BGM, sha256="m" * 64, seconds=4.0,
                     note="slow synth score, no drums")
    got = [(m.label, m.wiring) for m in build_manifest(
        Brief(intent="x", assets=[video, paired, score]),
        Target(nominal_seconds=8.0, frames=192, canvas=(1344, 768)))]
    assert got == [("<Audio 1>", "ref_video_audio_1"),
                   ("<Video 1>", "ref_video_1"),
                   ("<Audio 2>", "ref_audio_1")]


def test_two_standalone_sounds_still_count_up_within_their_own_list():
    sounds = [AssetRef(kind=AssetKind.AUDIO, role=Role.BGM, sha256=c * 64, seconds=1.0)
              for c in "ab"]
    got = [(m.label, m.wiring) for m in build_manifest(
        Brief(intent="x", assets=sounds),
        Target(nominal_seconds=8.0, frames=192, canvas=(1344, 768)))]
    assert got == [("<Audio 1>", "ref_audio_1"), ("<Audio 2>", "ref_audio_2")]


# ------------------------------------------------------- the service refuses a pointer it cannot use

def test_a_pointer_the_service_cannot_open_is_refused_rather_than_ignored(client, tmp_path):
    """Ignoring it produced a brief that silently disagreed with the graph. `asset-missing` is also
    the one code the ComfyUI node retries a path translation on, so refusing here is what lets a
    split install find the spelling that works."""
    sound = _silence(tmp_path / "s.wav")
    r = client.post("/v1/briefs", json={
        "intent": "carry on from this clip",
        "assets": [{"path": str(sound), "kind": "audio", "role": "bgm",
                    "paired_video_path": r"C:\ComfyUI\temp\clip.mp4"}]})
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert detail["code"] == "asset-missing", "the code the caller retries a translation on"
    assert "clip.mp4" in detail["message"]
    assert "paired with" in detail["message"], "say which of the two paths was the unreadable one"


def test_no_pointer_at_all_is_still_a_perfectly_good_standalone_sound(tmp_path):
    """A reference sound that is nobody's soundtrack is the ordinary case and must not be caught by
    the check above. Asserted on the conversion rather than the route, because the route would spend
    a model call and this has nothing to do with a model."""
    sound = _silence(tmp_path / "m.wav")
    brief = service._to_brief(service.BriefIn(
        intent="a slow synth score over an empty street",
        assets=[service.AssetIn(path=str(sound), kind="audio", role="bgm",
                                note="slow synth score, no drums")]))
    assert brief.assets[0].paired_video_sha256 is None
    assert brief.assets[0].note == "slow synth score, no drums"


def test_the_prompt_route_says_which_wiring_slot_and_what_kind_each_label_rides(client):
    """The ComfyUI node's report is built from this, and `ref_audio_1` versus `ref_video_audio_1` is
    the whole difference between a pairing that happened and one that did not.

    Driven through the real route with a stand-in document, because writing a brief needs a language
    model and the projection under test needs none. The manifest entries themselves are real.
    """
    from types import SimpleNamespace

    manifest = _manifest(paired=True)
    doc = SimpleNamespace(
        prompt="a document", mode=Mode.REF2VA, render_hash=lambda: "d" * 64,
        plan=SimpleNamespace(manifest=manifest, subjects=[], target=Target(
            nominal_seconds=8.0, frames=192, canvas=(1344, 768))))
    service._STORE["probe"] = {"doc": doc, "brief": None}
    try:
        p = client.get("/v1/briefs/probe/prompt")
    finally:
        service._STORE.pop("probe", None)
    assert p.status_code == 200, p.text
    got = {e["label"]: (e["wiring"], e["kind"]) for e in p.json()["wiring"]}
    assert got == {"<Audio 1>": ("ref_video_audio_1", "audio"),
                   "<Video 1>": ("ref_video_1", "video")}
    assert set(p.json()["wiring"][0]) >= {"label", "wiring", "sha256", "kind", "sizing", "retention"}
