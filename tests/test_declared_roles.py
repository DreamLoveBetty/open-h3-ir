"""A role the caller states is ground truth, in both directions. No model and no GPU.

`mode.infer_mode` counted only `frame_anchor_first` / `frame_anchor_last` as role evidence. Every
other declared role fell through to the language heuristics and the classifier, so an image the
caller explicitly called a storyboard, a style plate or an environment could be routed to i2va --
where it becomes a conditioning latent pinned to frame 0 that is never denoised. The manifest went
on reporting `role: storyboard` while the mode said that picture IS the opening frame. No finding,
status ready. "Follow this storyboard frame for the shot of the car" wired a storyboard drawing as
the video's literal first frame.

The reverse direction was guarded from the start: compile.X10 downgrades a frame-anchor role to a
subject reference on the ref2va route and says so in a finding.

What made the missing half hard is that `role` alone cannot answer "did the caller say this?" -- the
service fills an omitted role with the kind's default, so an explicit `role: "subject"` and no role
at all arrive identical. `AssetRef.role_stated` is that distinction, and without it this fix would
have broken every "animate this photo" request that names no role.
"""
from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from h3ir import service
from h3ir.mode import infer_mode
from h3ir.models import AssetCard, AssetKind, AssetRef, Brief, Mode, Role

ANCHOR_WORDING = "Animate this photo so the car pulls forward out of the dark."


def _image(role: Role, stated: bool) -> AssetRef:
    return AssetRef(kind=AssetKind.IMAGE, role=role, sha256="plate", px=(1024, 576),
                    note="the black supercar", role_stated=stated)


def _cards() -> dict[str, AssetCard]:
    return {"plate": AssetCard(sha256="plate", kind=AssetKind.IMAGE,
                               summary="a black supercar in a dark showroom",
                               subjects=[{"kind": "object", "descriptor": "the black supercar",
                                          "attributes": ["carbon fibre body"]}])}


# ---------------------------------------------------------------- the promotion is blocked

@pytest.mark.parametrize("role", [Role.STORYBOARD, Role.STYLE, Role.ENVIRONMENT, Role.SUBJECT])
def test_a_declared_reference_role_is_not_promoted_to_a_keyframe(role):
    """All four routed to i2va before, on the strength of the request's wording alone."""
    brief = Brief(intent=ANCHOR_WORDING, assets=[_image(role, stated=True)])
    d = infer_mode(brief, _cards(), backend=None)
    assert d.mode is Mode.REF2VA, (role, d.mode, d.rule_fired)
    assert d.rule_fired == "explicit-role-reference"
    assert d.confidence == 1.0


def test_the_decision_records_that_the_wording_was_overridden():
    """Reported, never silently resolved: the request said "animate this photo" and the role said
    storyboard, and the caller has to be able to see which one won."""
    brief = Brief(intent=ANCHOR_WORDING, assets=[_image(Role.STORYBOARD, stated=True)])
    d = infer_mode(brief, _cards(), backend=None)
    assert any("overridden by the declared role" in s for s in d.signals), d.signals
    assert any("storyboard" in s for s in d.signals)


def test_a_declared_role_with_no_anchor_wording_says_nothing_about_an_override():
    """No contradiction, no note. A finding that fires when nothing disagreed is noise."""
    brief = Brief(intent="Put this car in a night race through a tunnel.",
                  assets=[_image(Role.SUBJECT, stated=True)])
    d = infer_mode(brief, _cards(), backend=None)
    assert d.mode is Mode.REF2VA
    assert not any("overridden" in s for s in d.signals), d.signals


def test_an_anchor_role_still_wins_when_that_is_what_was_declared():
    """The pre-existing branch has to keep working: this fix is about the roles that were ignored,
    not about ignoring the ones that were not."""
    brief = Brief(intent="Put this car in a night race.",
                  assets=[_image(Role.FRAME_ANCHOR_FIRST, stated=True)])
    assert infer_mode(brief, _cards(), backend=None).mode is Mode.I2VA


# ---------------------------------------------------------------- and inference still works

def test_an_unstated_role_leaves_the_wording_in_charge():
    """The over-fix this guards against. The service fills an omitted role with `subject`, so if a
    default counted as a declaration every "animate this photo" request with no role would have been
    dragged to ref2va -- turning a silent promotion into a silent demotion.
    """
    brief = Brief(intent=ANCHOR_WORDING, assets=[_image(Role.SUBJECT, stated=False)])
    d = infer_mode(brief, _cards(), backend=None)
    assert d.mode is Mode.I2VA, d.rule_fired
    assert d.rule_fired == "12.3-anchor-language"


def test_an_omitted_role_over_http_is_not_a_declaration():
    """Where the two cases actually separate. `role` is absent in the request body, and the brief
    the service builds must remember that."""
    still = "docs/media/plate-car.jpg"
    b = service.BriefIn(intent=ANCHOR_WORDING, assets=[service.AssetIn(path=still, kind="image")])
    brief = service._to_brief(b)
    assert brief.assets[0].role is Role.SUBJECT
    assert brief.assets[0].role_stated is False

    b2 = service.BriefIn(intent=ANCHOR_WORDING,
                         assets=[service.AssetIn(path=still, kind="image", role="subject")])
    assert service._to_brief(b2).assets[0].role_stated is True


# ---------------------------------------------------------------- the compiler says so

def test_the_compiler_reports_the_override_as_a_finding():
    """X18, the counterpart to X10. Compiled for real with the model switched off, so this is the
    finding list a caller receives rather than a hand-built one."""
    from h3ir import compile as C

    class _Backend:
        class cfg:
            model = "test-model"
        def require_available(self): pass
        def server_version(self): return "test"
        def close(self): pass

    cards = _cards()
    brief = Brief(intent=ANCHOR_WORDING, assets=[_image(Role.STORYBOARD, stated=True)])
    real_analyse = C.analyse_all
    C.analyse_all = lambda *a, **k: cards
    try:
        doc = C.compile_brief(brief, backend=_Backend(), llm=False)
    finally:
        C.analyse_all = real_analyse
    hit = [f for f in doc.findings if f.rule == "X18-role-overrides-anchor-language"]
    assert hit, [str(f) for f in doc.findings]
    assert hit[0].severity == "WARN"
    assert "frame_anchor_first" in hit[0].msg, "the message has to say how to get the other reading"
    assert doc.mode is Mode.REF2VA


# ---------------------------------------------------------------- an unknown role is not a default

def test_a_role_that_does_not_exist_is_refused_rather_than_ignored():
    """`frame_anchor` is one word short of `frame_anchor_first`, and it used to fall through to the
    kind default: the caller asked for the video's opening frame and silently got a content
    reference. Anchor versus reference is the product's central distinction and this field is the
    only place a caller can state it."""
    client = TestClient(service.app, raise_server_exceptions=False)
    r = client.post("/v1/briefs", json={
        "intent": ANCHOR_WORDING,
        "assets": [{"path": "docs/media/plate-car.jpg", "kind": "image", "role": "frame_anchor"}]})
    assert r.status_code == 422, r.text
    detail = r.json()["detail"]
    assert detail["code"] == "unknown-role"
    assert "frame_anchor_first" in detail["message"], "list the roles that do exist"
    assert "Omit `role`" in detail["message"], "and say what omitting it does"


def test_the_roles_offered_are_the_ones_that_fit_the_kind():
    """A wav cannot be a first frame. Listing all eleven under a typo'd audio role would be a worse
    message than naming the three that apply."""
    client = TestClient(service.app, raise_server_exceptions=False)
    r = client.post("/v1/briefs", json={
        "intent": "A supercar starts up.",
        "assets": [{"path": "docs/media/off-vs-on.mp4", "kind": "audio", "role": "sound_effect"}]})
    assert r.status_code == 422, r.text
    msg = r.json()["detail"]["message"]
    assert "sfx" in msg and "voice_timbre" in msg and "bgm" in msg
    assert "frame_anchor_first" not in msg
