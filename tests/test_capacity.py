"""The limits the service declares, enforced. No model and no GPU.

`/v1/capabilities` published `max_assets` and nothing checked it. Ten images compiled to
`status: ready` with a manifest carrying `<Picture 10>` and wiring `ref_image_10` -- a socket the
runtime does not have (`nodes_minimax_h3.py`: `ref_image_` min=0 max=9). Four videos and four
audios did the same. design.md 12 had already decided what should happen: "Refusals, not guesses,
for over-capacity requests ... The layer returns a clear, actionable error naming what to drop.
Silently dropping a reference the user attached is the worst available outcome."

The numbers come from the runtime's socket templates rather than from the note, and that changed one
of them: there is no total-file ceiling. 9 images, 3 videos, each video's soundtrack and 3 standalone
audios all have sockets, so the published `total_files: 12` would have refused a legal call.
"""
from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from h3ir import service
from h3ir.compile import OverCapacity, check_capacity
from h3ir.grid import (MAX_REF_AUDIOS, MAX_REF_IMAGES, MAX_REF_VIDEOS,
                       MAX_REF_VIDEO_SOUNDTRACKS, MIN_REF_VIDEO_FRAMES)
from h3ir.models import AssetKind, AssetRef, Brief, Role

REPO_STILL = "docs/media/plate-car.jpg"


def _img(i: int) -> AssetRef:
    return AssetRef(kind=AssetKind.IMAGE, role=Role.SUBJECT, sha256=f"i{i}", px=(1024, 576))


def _vid(i: int, frames: int = 240) -> AssetRef:
    return AssetRef(kind=AssetKind.VIDEO, role=Role.EDIT_SOURCE, sha256=f"v{i}", frames=frames,
                    seconds=frames / 24)


def _aud(i: int, paired: str | None = None) -> AssetRef:
    return AssetRef(kind=AssetKind.AUDIO, role=Role.BGM, sha256=f"a{i}", seconds=3.0,
                    paired_video_sha256=paired)


# ---------------------------------------------------------------- at the limit, and one past it

def test_the_declared_maximum_of_each_kind_is_allowed():
    """The limit is a limit, not a limit minus one. A refusal at nine images would be the same
    defect pointing the other way."""
    check_capacity(Brief(intent="x", assets=[_img(i) for i in range(MAX_REF_IMAGES)]))
    check_capacity(Brief(intent="x", assets=[_vid(i) for i in range(MAX_REF_VIDEOS)]))
    check_capacity(Brief(intent="x", assets=[_aud(i) for i in range(MAX_REF_AUDIOS)]))


def test_a_tenth_image_is_refused_and_the_message_says_what_to_drop():
    with pytest.raises(OverCapacity) as e:
        check_capacity(Brief(intent="x", assets=[_img(i) for i in range(MAX_REF_IMAGES + 1)]))
    msg = str(e.value)
    assert "10 image references attached and H3 takes at most 9" in msg
    assert "ref_image_1 to ref_image_9" in msg, "name the sockets, so the limit is checkable"
    assert "drop one image reference" in msg
    assert "yours to decide" in msg, "we must not choose which reference to lose"


def test_a_fourth_video_and_a_fourth_audio_are_refused():
    with pytest.raises(OverCapacity):
        check_capacity(Brief(intent="x", assets=[_vid(i) for i in range(MAX_REF_VIDEOS + 1)]))
    with pytest.raises(OverCapacity):
        check_capacity(Brief(intent="x", assets=[_aud(i) for i in range(MAX_REF_AUDIOS + 1)]))


def test_paired_soundtracks_are_counted_against_their_own_sockets():
    """`ref_video_audio_N` and `ref_audio_N` are separate templates with separate maxima, so a
    soundtrack must not consume a standalone audio's socket. Three videos with soundtracks plus
    three standalone audios is legal and used to be over the published total of 12."""
    assets = [_vid(i) for i in range(3)] + [_aud(f"p{i}", paired=f"v{i}") for i in range(3)] \
        + [_aud(i) for i in range(3)]
    check_capacity(Brief(intent="x", assets=assets))
    with pytest.raises(OverCapacity) as e:
        check_capacity(Brief(intent="x", assets=assets + [_aud("p4", paired="v0")]))
    assert "paired soundtrack" in str(e.value)


def test_every_kind_over_at_once_reports_all_of_them():
    """A caller who over-attached twice should not have to compile twice to find out."""
    with pytest.raises(OverCapacity) as e:
        check_capacity(Brief(intent="x", assets=[_img(i) for i in range(10)]
                             + [_vid(i) for i in range(4)]))
    assert "image" in str(e.value) and "video" in str(e.value)


def test_a_video_too_short_for_the_runtime_is_refused_before_anything_is_analysed():
    """`execute` raises outright below five frames, so there is nothing to compile against. The
    check reads what the caller declared, which is all this layer has before ffprobe runs."""
    with pytest.raises(OverCapacity) as e:
        check_capacity(Brief(intent="x", assets=[_vid(0, frames=MIN_REF_VIDEO_FRAMES - 1)]))
    assert "at least 5" in str(e.value)
    check_capacity(Brief(intent="x", assets=[_vid(0, frames=MIN_REF_VIDEO_FRAMES)]))


def test_an_undeclared_duration_is_not_guessed_at():
    """No frames and no seconds means the caller said nothing, and a refusal on silence would
    block every curl caller who omits an optional field."""
    check_capacity(Brief(intent="x", assets=[
        AssetRef(kind=AssetKind.VIDEO, role=Role.EDIT_SOURCE, sha256="v9")]))


# ---------------------------------------------------------------- the refusal over HTTP

def test_over_capacity_is_a_422_naming_the_code(tmp_path):
    """422, not a truncated manifest and not a 500. The caller can act on it."""
    f = tmp_path / "plate.jpg"
    f.write_bytes(b"\xff\xd8\xff\xd9")
    client = TestClient(service.app, raise_server_exceptions=False)
    r = client.post("/v1/briefs", json={
        "intent": "Put all of these together.",
        "assets": [{"path": str(f), "kind": "image"} for _ in range(MAX_REF_IMAGES + 1)]})
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["code"] == "over-capacity"
    assert "at most 9" in r.json()["detail"]["message"]


def test_the_refusal_happens_before_anything_is_analysed(monkeypatch):
    """Analysis is the expensive stage: ten images is ten vision calls, and not one of them can
    change the answer. So the check runs before the analyser and before the backend is even probed.

    Both are replaced with something that fails loudly rather than with a stub that would let the
    test pass whether or not the order is right.
    """
    import h3ir.compile as C

    def never(*a, **k):
        raise AssertionError("reached the expensive stage before refusing")

    monkeypatch.setattr(C, "analyse_all", never)

    class _Backend:
        class cfg:
            model = "x"
        def require_available(self): never()
        def close(self): pass

    with pytest.raises(OverCapacity):
        C.compile_brief(Brief(intent="x", assets=[_img(i) for i in range(10)]),
                        backend=_Backend())


# ---------------------------------------------------------------- silent truncation

def _edit_brief(video_seconds: float, target_seconds: float = 5.0):
    from h3ir.models import AssetCard

    sha = "clip"
    ref = AssetRef(kind=AssetKind.VIDEO, role=Role.EDIT_SOURCE, sha256=sha,
                   seconds=video_seconds, frames=int(video_seconds * 24))
    cards = {sha: AssetCard(sha256=sha, kind=AssetKind.VIDEO, summary="a car in a tunnel",
                            motion="the car crosses frame", frames_seen=3)}
    return Brief(intent="change the car to a white one", seconds=target_seconds,
                 assets=[ref]), cards


def test_a_reference_video_longer_than_the_target_says_so():
    """`execute` does `frames[:frame_count]` and then walks back to the 17k+5 grid, so a 10-second
    clip on a 5-second target conditions the render with its first 5 seconds only, and the brief is
    written about footage the model never sees. The audit's own video-edit repro is exactly this: a
    10.14s clip against the default 5s target, and no finding mentioned it.
    """
    from h3ir.compile import _assess
    from h3ir.draft import deterministic_draft
    from h3ir.models import Mode
    from h3ir.plan import ProfileOptions

    brief, cards = _edit_brief(10.14)
    plan = deterministic_draft(brief, Mode.REF2VA, cards, opts=ProfileOptions())
    _, findings, _ = _assess(plan, brief, Mode.REF2VA, ProfileOptions(), [])
    hit = [f for f in findings if f.rule == "X17-reference-video-truncated"]
    assert hit, [str(f) for f in findings]
    assert hit[0].severity == "WARN"
    assert "only the first 5.17s" in hit[0].msg
    assert "Lengthen the target, or trim the clip" in hit[0].msg


def test_a_reference_video_inside_the_target_is_not_flagged():
    """The clip fits, nothing is lost, and a warning here would be noise on the common case."""
    from h3ir.compile import _assess
    from h3ir.draft import deterministic_draft
    from h3ir.models import Mode
    from h3ir.plan import ProfileOptions

    brief, cards = _edit_brief(4.0, target_seconds=10.0)
    plan = deterministic_draft(brief, Mode.REF2VA, cards, opts=ProfileOptions())
    _, findings, _ = _assess(plan, brief, Mode.REF2VA, ProfileOptions(), [])
    assert not [f for f in findings if f.rule == "X17-reference-video-truncated"]


# ---------------------------------------------------------------- what is published

def test_the_published_limits_are_the_runtime_socket_maxima():
    """The declared limit and the enforced limit have to be the same number, or one of them is a
    lie. Both now read from the constants that cite the runtime."""
    published = service.capabilities()["max_assets"]
    assert published["images"] == MAX_REF_IMAGES == 9
    assert published["videos"] == MAX_REF_VIDEOS == 3
    assert published["audios"] == MAX_REF_AUDIOS == 3
    assert published["video_soundtracks"] == MAX_REF_VIDEO_SOUNDTRACKS == 3


def test_the_published_total_is_not_a_limit_the_runtime_imposes():
    """It used to say 12, which would refuse 9 images plus 3 videos plus 3 soundtracks plus 3
    standalone audios -- all of which have sockets. A limit that refuses legal work is worse than
    no limit."""
    published = service.capabilities()["max_assets"]
    assert published["total_files"] == 18
    check_capacity(Brief(intent="x", assets=(
        [_img(i) for i in range(9)] + [_vid(i) for i in range(3)]
        + [_aud(f"p{i}", paired=f"v{i}") for i in range(3)] + [_aud(i) for i in range(3)])))
