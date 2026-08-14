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


# ---------------------------------------------------------------- the video half of the prefix

"""A declared `edit_source` decides the task type, and the intent's shape does not.

Found from the node side and reproduced service-direct on this code: a clip attached as
`edit_source` with the intent "the same volley, but the stadium is empty and it is raining hard"
shipped `[reference generation]` in 6 of 7 seeds, with no "The target video is an edited version of
<Video 1>." opening and the clip taken apart into four subjects. The earlier re-measure passed 7 of 7
on "change the car in this clip to a white one", so the behaviour tracked how the intent READ rather
than what the caller declared. A user who picks "edit it" got a document describing a new video built
out of the old one's contents.

The wiring settles this completely, and the codebase already says so three times:
`plan.derive_task_types` works "From roles, never from prose"; `render.render_summary` keeps the
prefix out of prose because "a prose stage that could write the prefix could invent a relationship
the pack does not contain"; and `prose.audio_task_facts` pins the audio half of the prefix for
exactly this failure, having watched the writer claim `audio reuse` on 6 of 7 video edits. The video
half had no equivalent in either direction: nothing told the writer and no rule read it.
"""

VIDEO_DEFS = ("subject_definitions:\n"
              "<Subject 1> is the footballer in <Video 1>, with a green jersey.\n"
              "<Video 1> is the source video for the target video edit.\n")
VIDEO_DESC = ("detailed_description:\nThe target video is in live-action style.\n"
              "[Shot 1] The camera holds a static shot as <Subject 1> strikes the volley in the "
              "empty stadium while rain sheets across the pitch.\n\n"
              "overall_soundscape:\nRain hammers the empty stand.\n\nnon_diegetic_music:\nN/A\n")


def _video_doc(prefix: str, *, marker: str = "partially_preserved") -> str:
    return (f"{VIDEO_DEFS}\nsummary:\n[{prefix}] "
            + ("The target video is an edited version of <Video 1>, now empty and rain-swept. "
               if "video editing" in prefix else "")
            + "<Subject 1> is preserved.\n\nretention_analysis:\n"
              "<Subject 1> (appears in [Shot 1]): fully_preserved - the green jersey is retained.\n"
              f"<Video 1> (source video editing): {marker} - the framing and setting are "
              f"maintained.\n\n{VIDEO_DESC}")


def _video_ctx(role: str = "edit_source"):
    from h3ir.validate import Context
    return Context(mode="ref2va", n_pictures=0, n_videos=1, duration_s=8.0,
                   generation_task=False,
                   declared_roles=(("<Subject 1>", "edit_source", ""),
                                   ("<Video 1>", role, "")))


def test_a_declared_edit_source_must_be_claimed_as_video_editing():
    from h3ir.validate import validate

    errs = [f for f in validate(_video_doc("reference generation"), _video_ctx())
            if f.severity == "ERROR"]
    assert [f.rule for f in errs] == ["M13-declared-edit-not-claimed"], [str(f) for f in errs]
    assert "edit_source" in errs[0].msg and "video editing" in errs[0].msg


def test_claiming_it_satisfies_the_rule():
    from h3ir.validate import validate

    for prefix in ("video editing", "video editing + reference generation",
                   "reference generation + video editing"):
        errs = [f for f in validate(_video_doc(prefix), _video_ctx()) if f.severity == "ERROR"]
        assert not errs, (prefix, [str(f) for f in errs])


def test_a_declared_continuation_source_must_be_claimed_too():
    from h3ir.validate import validate

    doc = _video_doc("reference generation").replace(
        "<Video 1> is the source video for the target video edit.",
        "<Video 1> is the source video the target video continues from.").replace(
        "(source video editing)", "(continuation source)")
    errs = {f.rule for f in validate(doc, _video_ctx("continuation_source"))
            if f.severity == "ERROR"}
    assert "M14-declared-continuation-not-claimed" in errs, errs


def test_the_two_are_not_interchangeable():
    """An edit is not a continuation. Claiming the other one is the same defect wearing the other
    hat, and ref-en.txt 3 defines them against each other."""
    from h3ir.validate import validate

    errs = {f.rule for f in validate(_video_doc("video continuation"), _video_ctx())
            if f.severity == "ERROR"}
    assert "M13-declared-edit-not-claimed" in errs, errs


def test_no_declared_video_role_means_no_finding():
    """The rule reads the wiring, so with nothing declared it abstains: that is what every caller
    predating `declared_roles` passes, including the golden controls."""
    from h3ir.validate import Context, validate

    errs = {f.rule for f in validate(_video_doc("reference generation"),
                                     Context(mode="ref2va", n_pictures=0, n_videos=1,
                                             duration_s=8.0, generation_task=False))
            if f.severity == "ERROR"}
    assert not {r for r in errs if r.startswith("M1")}, errs


def test_a_reference_role_on_a_video_is_left_to_the_writer():
    """ref-en.txt 3: "If a reference video provides only camera movement, cuts, or rhythm, it
    normally belongs to reference generation. Use `video editing` or `video continuation` only when
    that video is directly edited or continued." So a `style` role must NOT be pushed either way."""
    from h3ir.validate import validate

    errs = [f for f in validate(_video_doc("reference generation"), _video_ctx("style"))
            if f.severity == "ERROR"]
    assert not errs, [str(f) for f in errs]


def test_the_deterministic_draft_satisfies_its_own_new_rule():
    """It templates the prefix from the roles, so it must already pass; if it did not, the compiler
    would raise instead of falling back and every edit request would 500."""
    from h3ir.compile import _assess
    from h3ir.draft import deterministic_draft
    from h3ir.plan import ProfileOptions

    clip = AssetRef(kind=AssetKind.VIDEO, role=Role.EDIT_SOURCE, sha256="clip", seconds=8.0,
                    frames=192, role_stated=True)
    cards = {"clip": AssetCard(sha256="clip", kind=AssetKind.VIDEO,
                               summary="a footballer striking a volley",
                               subjects=[{"kind": "person", "descriptor": "the footballer",
                                          "attributes": ["green jersey"]}])}
    brief = Brief(intent="the same volley, but the stadium is empty and it is raining hard",
                  seconds=8.0, assets=[clip])
    plan = deterministic_draft(brief, Mode.REF2VA, cards, opts=ProfileOptions())
    assert "video editing" in plan.task_types
    result, findings, _ = _assess(plan, brief, Mode.REF2VA, ProfileOptions(), [])
    assert "[video editing]" in result.prompt
    assert not [f for f in findings if f.severity == "ERROR"], [str(f) for f in findings]


def test_the_writer_is_told_what_the_video_role_settles():
    """The other half of the fix, and the half that stops the fix loop being needed: the ask states
    the fact, the same way `audio_task_facts` does for the audio half."""
    from h3ir.draft import deterministic_draft
    from h3ir.plan import ProfileOptions
    from h3ir.prose import compose_brief

    class Capture:
        class _Cfg:
            model = "capture"
        cfg = _Cfg()

        class _Reply:
            content = "subject_definitions:\n"

        def __init__(self) -> None:
            self.asks: list[str] = []

        def chat(self, messages, **kw):
            c = messages[-1]["content"]
            self.asks.append(c if isinstance(c, str) else c[0]["text"])
            return self._Reply()

    clip = AssetRef(kind=AssetKind.VIDEO, role=Role.EDIT_SOURCE, sha256="clip", seconds=8.0,
                    frames=192, role_stated=True)
    cards = {"clip": AssetCard(sha256="clip", kind=AssetKind.VIDEO,
                               summary="a footballer striking a volley",
                               subjects=[{"kind": "person", "descriptor": "the footballer",
                                          "attributes": ["green jersey"]}])}
    brief = Brief(intent="the same volley, but the stadium is empty and it is raining hard",
                  seconds=8.0, assets=[clip])
    plan = deterministic_draft(brief, Mode.REF2VA, cards, opts=ProfileOptions())
    backend = Capture()
    compose_brief(backend, brief, plan.subjects, cards, plan.target,
                  tuple(m.label for m in plan.manifest), prompt_name="compose.v2.txt",
                  mode=Mode.REF2VA, task_types=tuple(plan.task_types),
                  video_roles=tuple((m.label, m.role.value) for m in plan.manifest
                                    if m.kind is AssetKind.VIDEO))
    ask = backend.asks[0]
    assert "<Video 1>" in ask and "video editing" in ask
    assert "The target video is an edited version of <Video 1>." in ask
    assert "however the request is phrased" in ask


def test_the_ask_says_nothing_when_no_video_is_attached():
    from h3ir.prose import video_task_facts

    assert video_task_facts((), ()) == ""
    assert video_task_facts((("<Video 1>", "style"),), ("reference generation",)) == ""
