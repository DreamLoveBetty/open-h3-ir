"""The one honest thing to do about a capability the released weights cannot reach in one pass, and
the guard that could never fire.

`H3-Base-FL2VA` and `H3-Base-Ref2VA` are two task-specific checkpoints with their own Omni
Transformer weights (design.md 12.1, from the release table): FL2VA takes 0, 1 or 2 images as frame
anchors and Ref2VA takes the omni-reference set. So "this picture is an exact frame AND these other
references apply" is not something one local render can do, and a request that attaches a video, an
audio, or a third picture routes to Ref2VA (mode.py 12.2#1 and 12.2#2) where the anchor role has no
mechanism behind it. The compiler downgrades the role and says so, which is right.

Two things about it were not right, and both are here:

  * `prose.reference_picture_facts` opened with a guard that returned "" when a picture carried an
    anchor role. `pic_roles` is read off `draft_plan.manifest` (compile.py) AFTER the downgrade has
    rewritten every anchor role to `subject`, so no picture ever does, and the guard could not fire
    through the service. A test asserted the guard's behaviour on a hand-written input, which is how
    unreachable code stays green.
  * the finding said the checkpoint "has no exact-frame mechanism" without saying why the request was
    on that route or what the caller could do instead, so the one message a caller gets about a
    capability they asked for and are not getting explained neither.
"""
from __future__ import annotations

import pytest

from h3ir.models import AssetCard, AssetKind, AssetRef, Brief, Mode, Role
from h3ir.plan import ProfileOptions


def _plate(role: Role, sha: str) -> AssetRef:
    return AssetRef(kind=AssetKind.IMAGE, role=role, sha256=sha, px=(1024, 576),
                    note="the black supercar")


def _card(sha: str) -> AssetCard:
    return AssetCard(sha256=sha, kind=AssetKind.IMAGE, style="Live-action, cinematic",
                     summary="a black supercar",
                     subjects=[{"kind": "object", "descriptor": "the black supercar",
                                "attributes": ["carbon fibre body"]}])


def _compile_with_a_declared_anchor(monkeypatch, capture: dict):
    """A real compile of the case that produces the downgrade: a declared last-frame anchor on a
    request that also attaches a clip, which routes to ref2va by mode.py 12.2#1."""
    import h3ir.compile as C
    from h3ir.models import ModeDecision

    pic = _plate(Role.FRAME_ANCHOR_LAST, "closing")
    clip = AssetRef(kind=AssetKind.VIDEO, role=Role.CONTINUATION_SOURCE, sha256="clip",
                    seconds=4.0, frames=96)
    cards = {"closing": _card("closing"),
             "clip": AssetCard(sha256="clip", kind=AssetKind.VIDEO, summary="a car on a dock road",
                               subjects=[{"kind": "object", "descriptor": "the black car",
                                          "attributes": ["carbon fibre body"]}])}

    def spy(backend, brief, subjects, cards_, target, labels, **kw):
        capture.update(kw)
        capture["labels"] = labels
        raise RuntimeError("stop here")

    class _Backend:
        class cfg:
            model = "capture"

        def require_available(self): pass
        def server_version(self): return "test"
        def close(self): pass

    monkeypatch.setattr(C, "compose_brief", spy)
    monkeypatch.setattr(C, "analyse_all", lambda *a, **k: cards)
    monkeypatch.setattr(C, "infer_mode", lambda *a, **k: ModeDecision(
        mode=Mode.REF2VA, confidence=1.0, rule_fired="12.2#1",
        signals=["a video or audio reference is attached; the FL2VA checkpoint cannot accept them"]))
    brief = Brief(intent="Continue from the end of this clip and land exactly on this picture as "
                         "the final frame.", seconds=8.0, assets=[pic, clip])
    with pytest.raises(RuntimeError):
        C.compile_brief(brief, backend=_Backend(), opts=ProfileOptions())


def test_the_downgrade_says_why_the_request_is_on_this_route(monkeypatch):
    """It is the only message the caller gets about a capability they asked for and cannot have, so
    it has to name the cause, the consequence and the alternative."""
    import h3ir.compile as C
    from h3ir.models import ModeDecision

    findings: list = []
    real = C.deterministic_draft

    def grab(brief, mode, cards, **kw):
        return real(brief, mode, cards, **kw)

    monkeypatch.setattr(C, "deterministic_draft", grab)
    seen: dict = {}
    _compile_with_a_declared_anchor(monkeypatch, seen)

    # The finding is built before compose_brief is reached, so re-run the same path and read it off
    # the document the service would have returned. Simplest honest route: call the piece directly.
    from h3ir.compile import _anchor_downgrade_finding
    f = _anchor_downgrade_finding(Role.FRAME_ANCHOR_LAST, "12.2#1",
                                 ["a video or audio reference is attached; the FL2VA checkpoint "
                                  "cannot accept them"])
    findings.append(f)
    assert f.rule == "X10-anchor-role-downgraded"
    assert f.severity == "WARN"
    msg = f.msg
    assert "frame_anchor_last" in msg
    assert "two" in msg and "checkpoint" in msg, "the cause is that the weights are split in two"
    assert "keyframe completion" in msg, "the consequence for the task-type prefix"
    assert "a video or audio reference is attached" in msg, "why THIS request is on that route"
    assert "composition" in msg, "what the picture will be used as instead"


def test_the_alternative_is_stated_and_is_actually_available():
    """"Drop the other references" is only useful advice if it really does change the route, so the
    remedy the message names is checked against the router rather than asserted."""
    from h3ir.compile import _anchor_downgrade_finding
    from h3ir.mode import infer_mode

    msg = _anchor_downgrade_finding(Role.FRAME_ANCHOR_LAST, "12.2#1", []).msg
    assert "on its own" in msg or "only reference" in msg, msg
    alone = Brief(intent="End on this photo after the car rolls to a stop.", seconds=8.0,
                  assets=[_plate(Role.FRAME_ANCHOR_LAST, "closing")])
    assert infer_mode(alone).mode is Mode.L2VA


def test_the_picture_arrives_at_the_writer_already_downgraded(monkeypatch):
    """The plumbing fact the deleted guard was pretending to check. Everything the writer is told
    about the pictures is read off the manifest, and by then the role is `subject`."""
    seen: dict = {}
    _compile_with_a_declared_anchor(monkeypatch, seen)
    assert seen["picture_roles"] == (("<Picture 1>", "subject"),)
    assert not any(r.startswith("frame_anchor") for _, r in seen["picture_roles"])


def test_the_statement_handed_to_the_writer_is_true_of_what_it_describes():
    """`reference_picture_facts` no longer takes a guard it cannot exercise. On this route no picture
    is a frame, so the statement is unconditional and honest; the guard read the roles after they had
    been rewritten and returned "" for nothing."""
    from h3ir.prose import reference_picture_facts

    text = reference_picture_facts()
    assert "None of the pictures here is a frame of the target video." in text
    assert "never claim `keyframe completion`" in text


def test_no_caller_passes_roles_to_it_any_more():
    """A signature that still accepted the roles would invite the dead branch back."""
    import inspect

    from h3ir.prose import reference_picture_facts

    assert not inspect.signature(reference_picture_facts).parameters
