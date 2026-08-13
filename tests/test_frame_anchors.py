"""First-and-last-frame work: the whole mode, end to end. No model and no GPU.

FL2VA could not be compiled at all. Both paths ended at the same place — the model's brief failed
the validator twice, the deterministic draft failed it too, and `compile_brief` raised
`CompilerInvariantError` — because of one notation mismatch. base-en.txt mandates a BARE citation
for this mode and only for this mode (`Picture 1 (from Shot 1)`, section 2.1, and the same form
throughout its own published example in section 5), while the validator's label scanner read only
the bracketed `<Picture N>`. So every citation an FL2VA brief can legally contain was invisible,
`used["Picture"]` came out empty, and `L4-unused-media` took its total-miss branch — the ERROR
branch — on text that had bound both pictures correctly.

MiniMax's own published FL2VA example fails the same rule the same way, which is the tell that the
rule was wrong rather than the text. That example is now a fixture and a control.

Two more defects in the same mode, found while proving the first one, are fixed here too:

  * the picture ordinals came from the caller's asset order, so a brief that listed its closing
    plate first published a manifest whose `<Picture 1>` was the LAST frame — against an
    instruction line asserting Picture 1 lands at 0.00 seconds. The runtime pins the ordinals
    (`MiniMaxH3ImageToVideo.execute` presents `first_frame` then `last_frame`), so the role decides
    the number, not the order the caller happened to list the files in. Silent otherwise: a base
    mode has no retention_analysis, so no other line of the brief could contradict it.

  * the deterministic floor described BOTH plates in the opening frame, which is what the spec's
    FL2VA section explicitly forbids ("should not repeat two static image descriptions") and which
    asserts the closing plate's content at 0.00 seconds.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from h3ir.compile import _assess
from h3ir.draft import deterministic_draft
from h3ir.grid import Target
from h3ir.models import AssetCard, AssetKind, AssetRef, Brief, Mode, Role
from h3ir.plan import ProfileOptions, build_manifest
from h3ir.validate import Context, validate

SPEC = Path(__file__).resolve().parents[1] / "h3ir/prompts/base-en.txt"
GOLDEN = Path(__file__).resolve().parents[1] / "h3ir/golden/official_fl2va_example.txt"


def _fl2va(desc: str, *, instruction: str | None = None,
           sound: str = "Rain falls steadily on the pavement.", music: str = "N/A") -> str:
    """A base-mode document: the instruction line, a blank line, then the three core fields."""
    head = "" if instruction is None else instruction + "\n\n"
    return (f"{head}integrated_multimodal_description: {desc}\n\n"
            f"overall_soundscape: {sound}\n\nnon_diegetic_music: {music}\n")


ALIGN = ("How the reference pictures align with the target video — Picture 1 (from Shot 1) aligns "
         "with the 0.00-second mark of the target video; Picture 2 (from Shot 1) aligns with the "
         "5.17-second mark of the target video.")

BODY = ("[Shot 1] Live-action, cinematic, the cyclist begins in the framing established by "
        "Picture 1. The camera pulls out with small amplitude at slow speed as she raises the "
        "umbrella, and settles into the composition established by Picture 2 at the end of the "
        "shot.")


def _anchor_cards() -> tuple[list[AssetRef], dict[str, AssetCard]]:
    """Two plates that could not be confused for each other: an empty room and a car."""
    first = AssetRef(kind=AssetKind.IMAGE, role=Role.FRAME_ANCHOR_FIRST, sha256="opening",
                     px=(1024, 576))
    last = AssetRef(kind=AssetKind.IMAGE, role=Role.FRAME_ANCHOR_LAST, sha256="closing",
                    px=(1024, 576))
    cards = {
        "opening": AssetCard(sha256="opening", kind=AssetKind.IMAGE,
                             style="Live-action, cinematic", environment="an empty showroom floor",
                             subjects=[{"kind": "environment",
                                        "descriptor": "the empty showroom floor",
                                        "attributes": ["polished concrete"]}]),
        "closing": AssetCard(sha256="closing", kind=AssetKind.IMAGE,
                             style="Live-action, cinematic",
                             subjects=[{"kind": "object", "descriptor": "the black sports car",
                                        "attributes": ["carbon fibre body"]}]),
    }
    return [first, last], cards


# ---------------------------------------------------------------- the spec's own artifact

def test_the_published_fl2va_example_is_the_spec_text_byte_for_byte():
    """The fixture is only evidence if it is the spec's example and not a paraphrase of it."""
    assert GOLDEN.read_text(encoding="utf-8").strip() in SPEC.read_text(encoding="utf-8")


def test_the_published_fl2va_example_validates_clean():
    """The control that was missing. There are goldens for t2va, i2va and ref2va and none for this
    mode, which is how a rule that rejects every legal FL2VA brief shipped green.

    8.00 s is on the frame grid (192 frames, 192 % 17 == 5), so nothing here is exempted.
    """
    found = validate(GOLDEN.read_text(encoding="utf-8"),
                     Context(mode="fl2va", n_pictures=2, duration_s=8.0))
    assert not found, [str(f) for f in found]


# ---------------------------------------------------------------- the citation notation

def test_the_bare_citation_binds_the_picture_it_names():
    text = _fl2va(BODY, instruction=ALIGN)
    found = validate(text, Context(mode="fl2va", n_pictures=2, duration_s=5.167))
    assert "L4-unused-media" not in {f.rule for f in found}, [str(f) for f in found]


def test_an_fl2va_brief_that_binds_neither_picture_is_still_an_error():
    """The rule has to keep biting, or the fix is just a hole with a comment on it."""
    text = _fl2va("[Shot 1] Live-action, cinematic, a cyclist opens an umbrella. The camera pulls "
                  "out with small amplitude at slow speed.")
    errs = [f for f in validate(text, Context(mode="fl2va", n_pictures=2, duration_s=5.167))
            if f.rule == "L4-unused-media"]
    assert errs and errs[0].severity == "ERROR", errs


def test_an_fl2va_brief_that_binds_only_the_opening_plate_is_a_warning():
    """Partly bound is a lesser mistake than a total miss, and the severity split predates this."""
    text = _fl2va("[Shot 1] Live-action, cinematic, the cyclist begins in the framing established "
                  "by Picture 1. The camera pulls out with small amplitude at slow speed.",
                  instruction=ALIGN.split(";")[0] + ".")
    found = [f for f in validate(text, Context(mode="fl2va", n_pictures=2, duration_s=5.167))
             if f.rule == "L4-unused-media"]
    assert found and found[0].severity == "WARN", found
    assert "[2]" in found[0].msg


@pytest.mark.parametrize("mode,n_pictures", [("i2va", 1), ("ref2va", 1)])
def test_the_bare_form_does_not_count_in_the_modes_that_bracket(mode, n_pictures):
    """Scoped deliberately. FL2VA is the only mode whose spec notation is bare; ref-en.txt brackets
    every one of its twelve label citations, and i2va's mandated instruction line brackets too. A
    bare mention in those modes is drift, and drift must not silently satisfy the binding check."""
    if mode == "ref2va":
        text = ("subject_definitions:\n<Subject 1> is the man in Picture 1, with dark hair.\n\n"
                "summary:\n[reference generation] The target video shows <Subject 1>.\n\n"
                "retention_analysis:\n<Subject 1> (appears in [Shot 1]): fully_preserved - the "
                "hair is retained.\n\ndetailed_description:\nA style line.\n[Shot 1] The camera "
                "holds a static shot on <Subject 1>.\n\noverall_soundscape:\nRoom tone.\n\n"
                "non_diegetic_music:\nN/A\n")
    else:
        text = _fl2va("[Shot 1] Live-action, cinematic, the man from Picture 1 turns to the "
                      "window. The camera pushes in with small amplitude at slow speed.")
    errs = [f for f in validate(text, Context(mode=mode, n_pictures=n_pictures, duration_s=5.167))
            if f.rule == "L4-unused-media"]
    assert errs and errs[0].severity == "ERROR", errs


def test_a_picture_named_in_the_users_own_words_is_not_a_citation():
    """Dialogue and on-screen text are the user's, and no structural rule reads them. Counting a
    bare form inside them would let a line of dialogue about a photograph bind a conditioning
    image that the brief never mentions."""
    text = _fl2va(
        '[Shot 1] Live-action, cinematic, the cyclist begins in the framing established by '
        'Picture 1 beneath a sign reading "Picture 2". The camera pulls out with small amplitude '
        'at slow speed as she (S1) says: <d>[English] Picture 2 is the one I meant.</d>')
    found = [f for f in validate(text, Context(mode="fl2va", n_pictures=2, duration_s=5.167,
                                               expected_dialogue=("Picture 2 is the one I meant.",),
                                               onscreen_text=("Picture 2",)))
             if f.rule == "L4-unused-media"]
    assert found and "[2]" in found[0].msg, found


def test_a_bare_citation_beyond_what_is_attached_is_a_phantom():
    """The same blind spot in the other direction: an over-numbered bare citation pointed at
    nothing and no rule could see it, because L3 also reads only the bracketed form."""
    text = _fl2va("[Shot 1] Live-action, cinematic, the cyclist begins in the framing established "
                  "by Picture 1 and ends in Picture 3. The camera pulls out with small amplitude "
                  "at slow speed.")
    errs = {f.rule for f in validate(text, Context(mode="fl2va", n_pictures=2, duration_s=5.167))
            if f.severity == "ERROR"}
    assert "L3-phantom-media" in errs, errs


# ---------------------------------------------------------------- the mode compiles

def test_a_first_and_last_frame_brief_passes_its_own_validator():
    """The exact invariant `compile_brief` raises on (compile.py, the draft-errors branch): the
    deterministic draft is our own deterministic output, so an ERROR in it is our bug and there is
    nothing to fall back to. This is the 500 the service returned, minus the network."""
    assets, cards = _anchor_cards()
    brief = Brief(intent="the car drives out of the showroom and onto the street at dusk",
                  seconds=5.0, assets=assets)
    plan = deterministic_draft(brief, Mode.FL2VA, cards, opts=ProfileOptions())
    _, findings, _ = _assess(plan, brief, Mode.FL2VA, ProfileOptions(), [])
    assert not [f for f in findings if f.severity == "ERROR"], [str(f) for f in findings]


# ---------------------------------------------------------------- which plate is which

def test_the_anchor_role_decides_the_picture_number_not_the_caller_order():
    """`MiniMaxH3ImageToVideo.execute` appends first_frame and then last_frame, so the runtime
    emits "<Picture 1>: " before the opening plate and "<Picture 2>: " before the closing one. The
    ordinal is a fact about the role, and the instruction line asserts it. Listing the closing
    plate first used to swap the two."""
    assets, _ = _anchor_cards()
    first, last = assets
    for order in ([first, last], [last, first]):
        manifest = build_manifest(Brief(intent="x", assets=list(order)), Target.build(5.0))
        by_label = {m.label: m for m in manifest}
        assert by_label["<Picture 1>"].role is Role.FRAME_ANCHOR_FIRST
        assert by_label["<Picture 1>"].sha256 == "opening"
        assert by_label["<Picture 2>"].role is Role.FRAME_ANCHOR_LAST
        assert by_label["<Picture 2>"].sha256 == "closing"
        assert [m.wiring for m in manifest] == ["ref_image_1", "ref_image_2"]


def test_a_single_closing_anchor_is_still_picture_one():
    """L2VA. Only last_frame is connected, so it is the only image the runtime presents and it
    takes ordinal 1 — which is what the mandated L2VA instruction line says."""
    _, cards = _anchor_cards()
    last = AssetRef(kind=AssetKind.IMAGE, role=Role.FRAME_ANCHOR_LAST, sha256="closing",
                    px=(1024, 576))
    manifest = build_manifest(Brief(intent="x", assets=[last]), Target.build(5.0))
    assert [(m.label, m.role) for m in manifest] == [("<Picture 1>", Role.FRAME_ANCHOR_LAST)]


def test_the_other_images_keep_the_order_they_arrived_in():
    """Reordering is for anchors only. Every other image keeps the caller's order, because for a
    reference brief that order IS the numbering the caller will wire."""
    refs = [AssetRef(kind=AssetKind.IMAGE, role=Role.SUBJECT, sha256=f"s{i}", px=(512, 512))
            for i in range(1, 4)]
    manifest = build_manifest(Brief(intent="x", assets=refs), Target.build(5.0))
    assert [m.sha256 for m in manifest] == ["s1", "s2", "s3"]


# ---------------------------------------------------------------- one mode, one notation

WRITTEN = (
    "How the reference pictures align with the target video — <Picture 1> (from [Shot 1]) aligns "
    "with the 0.00-second mark of the target video; <Picture 2> (from [Shot 2]) aligns with the "
    "5.17-second mark of the target video.\n\n"
    "integrated_multimodal_description: [Shot 1] Cinematic, live-action, the empty showroom shown "
    "in <Picture 1>. The camera pushes in with small amplitude at slow speed. [Shot 2] At "
    "00:04.500, the shot cuts to the composition shown in <Picture 2>.\n\n"
    "overall_soundscape: Tyres roll over polished concrete.\n\nnon_diegetic_music: N/A\n")


def test_the_written_path_gets_the_notation_the_renderer_already_uses():
    """Real output from the live endpoint, trimmed. The model is handed the mandated FL2VA line
    verbatim in its system prompt and wrote the bracketed form anyway — so the same mode shipped
    the spec's notation when the draft won and a bracketed near-miss when the model won."""
    from h3ir.repair import repair

    out = repair(WRITTEN, target=Target.build(5.0), mode=Mode.FL2VA,
                 labels=("<Picture 1>", "<Picture 2>"))
    assert out.text.startswith("How the reference pictures align with the target video — Picture 1 "
                               "(from Shot 1) aligns with the 0.00-second mark")
    assert "Picture 2 (from Shot 2) aligns with the 5.17-second mark" in out.text
    assert "<Picture" not in out.text
    assert any("bare spec form" in r for r in out.repairs), out.repairs
    # The shot markers in the body are mandated in every mode and must survive untouched.
    assert "[Shot 1] Cinematic" in out.text and "[Shot 2] At 00:04.500" in out.text


def test_the_repaired_brief_still_binds_both_pictures():
    """The repair and the binding check have to agree, or normalising the notation would trade one
    failure for another."""
    from h3ir.repair import repair

    out = repair(WRITTEN, target=Target.build(5.0), mode=Mode.FL2VA,
                 labels=("<Picture 1>", "<Picture 2>"))
    found = validate(out.text, Context(mode="fl2va", n_pictures=2, duration_s=5.167))
    assert not [f for f in found if f.severity == "ERROR"], [str(f) for f in found]


def test_the_modes_that_bracket_are_left_alone():
    """i2va and l2va bracket their labels in the spec, so their briefs must come back untouched."""
    from h3ir.repair import repair

    i2va = ("For the target video, at 0.00 seconds into the target video, <Picture 1> (from "
            "[Shot 1]) is fully referenced.\n\n"
            "integrated_multimodal_description: [Shot 1] Cinematic, live-action, the man in "
            "<Picture 1> turns. The camera pushes in with small amplitude at slow speed.\n\n"
            "overall_soundscape: Room tone.\n\nnon_diegetic_music: N/A\n")
    out = repair(i2va, target=Target.build(5.0), mode=Mode.I2VA, labels=("<Picture 1>",))
    assert out.text == i2va
    assert not out.repairs, out.repairs


# ---------------------------------------------------------------- the floor describes a path

def test_the_floor_puts_the_closing_plate_at_the_end_and_not_at_zero_seconds():
    """The draft is the product floor, so when the prose model fails this is what ships. It used
    to open with both plates at once — "The frame holds <the empty showroom> and <the black sports
    car>" — which asserts the closing plate's content at 0.00 seconds and does the one thing the
    spec's FL2VA section forbids outright."""
    assets, cards = _anchor_cards()
    brief = Brief(intent="the car drives out of the showroom and onto the street at dusk",
                  seconds=5.0, assets=assets)
    plan = deterministic_draft(brief, Mode.FL2VA, cards, opts=ProfileOptions())
    assert len(plan.shots) == 1, "the spec says FL2VA favours a single shot"
    body = plan.shots[0].body

    assert "Picture 1" in body and "Picture 2" in body
    opening, closing = body.split("Picture 2", 1)
    assert "showroom" in opening, body
    assert "sports car" not in opening, "the closing plate is being asserted in the opening frame"
    assert "sports car" in closing, body
    assert brief.intent in body, "the request is the only statement of the path between the plates"


def test_the_floor_still_cites_both_anchors_with_nothing_to_say_about_them():
    """The thinnest possible case: two plates whose cards carry no subjects, so there is no content
    to place at either end. The anchors still have to be bound, because they are still wired into
    the render and still cost their rows."""
    assets, _ = _anchor_cards()
    brief = Brief(intent="the car pulls away", seconds=5.0, assets=assets)
    plan = deterministic_draft(brief, Mode.FL2VA, {}, opts=ProfileOptions())
    body = plan.shots[0].body
    assert "Picture 1" in body and "Picture 2" in body, body
    _, findings, _ = _assess(plan, brief, Mode.FL2VA, ProfileOptions(), [])
    assert not [f for f in findings if f.severity == "ERROR"], [str(f) for f in findings]


def test_the_floor_still_reaches_the_renderer_intact():
    """A body the renderer cannot substitute into is not a floor. The camera placeholder has to
    survive the rewrite, and the rendered brief has to carry the mandated instruction line."""
    assets, cards = _anchor_cards()
    brief = Brief(intent="the car drives out of the showroom", seconds=5.0, assets=assets)
    plan = deterministic_draft(brief, Mode.FL2VA, cards, opts=ProfileOptions())
    assert "{{CAM}}" in plan.shots[0].body
    result, findings, _ = _assess(plan, brief, Mode.FL2VA, ProfileOptions(), [])
    assert result.prompt.startswith("How the reference pictures align with the target video — "
                                    "Picture 1 (from Shot 1)")
    assert "{{CAM}}" not in result.prompt
    assert "pulls out" in result.prompt or "pushes in" in result.prompt
    assert not [f for f in findings if f.severity == "ERROR"], [str(f) for f in findings]
