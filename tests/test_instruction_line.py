"""The first line of a keyframe brief, which nothing checked in any mode.

`grep -cE 'second mark|fully referenced|How the reference pictures' h3ir/validate.py` returned 0.
base-en.txt 2.1 prints the mandated line for I2VA, FL2VA and L2VA verbatim and states two facts
about it that were both unguarded:

  * "`S.SS` is the effective video duration formatted to exactly two decimal places" -- the written
    path emitted three decimals in 7 of 8 recorded runs, because the ask hands the model
    `{effective_seconds:.3f}` and it copies that number straight into the line;
  * "the instruction must be the first line of the final prompt, followed by one blank line".

Underneath sat a worse disagreement: the deterministic renderer deliberately wrote the NOMINAL
duration there (`ProfileOptions.s_ss_policy = "nominal"`) while the model wrote the effective one,
so for a 13.3 s request the draft said the last frame lands at 13.30 and the written brief said
13.667. The spec's word is "effective", so the draft was the side that was wrong.

The line is computable from the wiring in every mode, so it is repaired mechanically like the
label namespace, and the validator is the backstop rather than the mechanism.
"""
from __future__ import annotations

import pytest

from h3ir.compile import _assess
from h3ir.draft import deterministic_draft
from h3ir.grid import Target, instruction_line_for, s_ss_text
from h3ir.models import AssetCard, AssetKind, AssetRef, Brief, Mode, Role
from h3ir.plan import ProfileOptions
from h3ir.repair import repair
from h3ir.validate import Context, validate


def _base(desc: str, instruction: str | None) -> str:
    head = "" if instruction is None else instruction + "\n\n"
    return (f"{head}integrated_multimodal_description: {desc}\n\n"
            "overall_soundscape: Tyres roll over wet concrete.\n\nnon_diegetic_music: N/A\n")


BODY = ("[Shot 1] Live-action, cinematic, the black car waits in the empty showroom. The camera "
        "pushes in with small amplitude at slow speed as it rolls forward.")

L2VA_OK = ("How the reference pictures align with the target video — <Picture 1> (from [Shot 1]) "
           "aligns with the 13.67-second mark of the target video.")


# ---------------------------------------------------------------- the two-decimal rule

def test_three_decimals_in_the_instruction_line_is_an_error():
    """The exact defect, measured 4 of 4 on l2va and 3 of 4 on fl2va: `13.667-second mark`."""
    bad = L2VA_OK.replace("13.67-second", "13.667-second")
    found = validate(_base(BODY, bad), Context(mode="l2va", n_pictures=1, duration_s=328 / 24))
    assert [f.rule for f in found if f.severity == "ERROR"] == ["I2-instruction-line-not-exact"]
    assert "13.67" in found[0].msg, found[0].msg


def test_two_decimals_of_the_effective_duration_passes():
    found = validate(_base(BODY, L2VA_OK),
                     Context(mode="l2va", n_pictures=1, duration_s=328 / 24))
    assert not found, [str(f) for f in found]


def test_the_nominal_duration_in_the_instruction_line_is_an_error():
    """The disagreement between the two paths, stated as a test: for a 13.3 s request the render is
    13.667 s, and 13.30 is the number the deterministic renderer used to write."""
    bad = L2VA_OK.replace("13.67-second", "13.30-second")
    errs = [f for f in validate(_base(BODY, bad),
                                Context(mode="l2va", n_pictures=1, duration_s=328 / 24))
            if f.severity == "ERROR"]
    assert [f.rule for f in errs] == ["I2-instruction-line-not-exact"]


def test_s_ss_rounds_half_up_and_never_to_three_places():
    assert s_ss_text(328 / 24) == "13.67"
    assert s_ss_text(8.0) == "8.00"
    assert s_ss_text(10.125) == "10.13"          # half-up, not Python's half-even 10.12
    assert s_ss_text(124 / 24) == "5.17"


# ---------------------------------------------------------------- the line's shape, per mode

def test_a_missing_instruction_line_is_an_error_in_every_keyframe_mode():
    for mode, n in (("i2va", 1), ("fl2va", 2), ("l2va", 1)):
        errs = {f.rule for f in validate(_base(BODY, None),
                                        Context(mode=mode, n_pictures=n, duration_s=8.0))
                if f.severity == "ERROR"}
        assert "I1-instruction-line-missing" in errs, (mode, errs)


def test_t2va_must_not_carry_one_and_is_not_asked_for_one():
    """T2VA "has no image-alignment instruction and begins directly with the three core fields"."""
    errs = {f.rule for f in validate(_base(BODY, None),
                                     Context(mode="t2va", n_pictures=0, duration_s=8.0))
            if f.severity == "ERROR"}
    assert not {r for r in errs if r.startswith("I")}, errs


def test_ref2va_is_not_asked_for_one():
    ref = ("subject_definitions:\n<Subject 1> is the black car in <Picture 1>, with a carbon "
           "body.\n\nsummary:\n[reference generation] The target video shows <Subject 1>.\n\n"
           "retention_analysis:\n<Subject 1> (appears in [Shot 1]): fully_preserved - the carbon "
           "body is retained.\n\ndetailed_description:\nThe target video is in cinematic style.\n"
           "[Shot 1] The camera pushes in with small amplitude at slow speed on <Subject 1>.\n\n"
           "overall_soundscape:\nTyres roll.\n\nnon_diegetic_music:\nN/A\n")
    errs = {f.rule for f in validate(ref, Context(mode="ref2va", n_pictures=1, duration_s=8.0))
            if f.severity == "ERROR"}
    assert not {r for r in errs if r.startswith("I")}, errs


def test_the_i2va_line_is_checked_byte_for_byte():
    """It carries no variable at all, so any difference is drift."""
    near = ("For the target video, at 0.00 seconds into the target video, <Picture 1> (from "
            "[Shot 1]) is referenced.")
    errs = {f.rule for f in validate(_base(BODY, near),
                                     Context(mode="i2va", n_pictures=1, duration_s=8.0))
            if f.severity == "ERROR"}
    assert "I2-instruction-line-not-exact" in errs, errs
    exact = instruction_line_for("i2va", 1, "8.00")
    assert not validate(_base(BODY, exact),
                        Context(mode="i2va", n_pictures=1, duration_s=8.0))


def test_the_shot_index_must_be_the_actual_final_shot():
    """`N` is "the index of the actual final shot". A two-shot l2va brief whose line says Shot 1
    tells the model the last frame lands inside the first shot."""
    two = (BODY + " [Shot 2] At 00:06.000, the shot cuts to the car under the lights.")
    bad = L2VA_OK.replace("[Shot 1]", "[Shot 1]")            # unchanged: still claims shot 1
    errs = {f.rule for f in validate(_base(two, bad),
                                     Context(mode="l2va", n_pictures=1, duration_s=328 / 24))
            if f.severity == "ERROR"}
    assert "I2-instruction-line-not-exact" in errs, errs
    good = L2VA_OK.replace("[Shot 1]", "[Shot 2]")
    assert not [f for f in validate(_base(two, good),
                                    Context(mode="l2va", n_pictures=1, duration_s=328 / 24))
                if f.severity == "ERROR"]


def test_the_mandated_blank_line_after_it_is_checked():
    text = (L2VA_OK + "\nintegrated_multimodal_description: " + BODY
            + "\n\noverall_soundscape: Tyres roll.\n\nnon_diegetic_music: N/A\n")
    errs = {f.rule for f in validate(text, Context(mode="l2va", n_pictures=1,
                                                   duration_s=328 / 24))
            if f.severity == "ERROR"}
    assert "I3-instruction-line-no-blank-line" in errs, errs


def test_the_published_examples_still_pass_their_own_new_rule():
    """base-en.txt's own FL2VA and I2VA artifacts, which are controls. A rule that fires on them
    is a wrong rule."""
    from pathlib import Path
    golden = Path(__file__).resolve().parents[1] / "h3ir/golden"
    for name, ctx in (("official_fl2va_example.txt",
                       Context(mode="fl2va", n_pictures=2, duration_s=8.0)),
                      ("i2va.ir.txt", Context(mode="i2va", n_pictures=1, duration_s=8.0))):
        found = [f for f in validate((golden / name).read_text(encoding="utf-8"), ctx)
                 if f.rule.startswith("I")]
        assert not found, (name, [str(f) for f in found])


# ---------------------------------------------------------------- repaired, not rejected

def test_the_repair_rewrites_a_three_decimal_line_from_the_wiring():
    """The number is a fact this layer holds, so it is a substitution and not a reason to re-roll:
    the same class as the label namespace and fl2va's bare notation."""
    bad = _base(BODY, L2VA_OK.replace("13.67-second", "13.667-second"))
    out = repair(bad, target=Target.build(13.3), mode=Mode.L2VA, labels=("<Picture 1>",))
    assert "13.67-second mark" in out.text
    assert "13.667" not in out.text
    assert any("instruction line" in r for r in out.repairs), out.repairs
    assert not [f for f in validate(out.text, Context(mode="l2va", n_pictures=1,
                                                      duration_s=328 / 24))
                if f.severity == "ERROR"]


def test_the_repair_adds_the_line_when_the_model_omitted_it_entirely():
    out = repair(_base(BODY, None), target=Target.build(8.0), mode=Mode.I2VA,
                 labels=("<Picture 1>",))
    assert out.text.startswith("For the target video, at 0.00 seconds into the target video, "
                               "<Picture 1> (from [Shot 1]) is fully referenced.\n\n")
    assert any("instruction line" in r for r in out.repairs), out.repairs


def test_the_repair_leaves_a_correct_line_untouched():
    good = _base(BODY, L2VA_OK)
    out = repair(good, target=Target.build(13.3), mode=Mode.L2VA, labels=("<Picture 1>",))
    assert out.text == good
    assert not out.repairs, out.repairs


def test_the_repair_does_not_invent_a_line_for_t2va_or_ref2va():
    for mode in (Mode.T2VA, Mode.REF2VA):
        out = repair(_base(BODY, None), target=Target.build(8.0), mode=mode, labels=())
        assert "second mark" not in out.text
        assert "fully referenced" not in out.text


# ---------------------------------------------------------------- one number, both paths

def test_the_deterministic_renderer_writes_the_effective_duration_too():
    """The two paths disagreed about which number belongs there and both cannot be right.

    13.3 s becomes 328 frames, 13.667 s. The draft used to say the closing plate lands at 13.30,
    which is a moment 0.37 s before the end of the render it describes.
    """
    ref = AssetRef(kind=AssetKind.IMAGE, role=Role.FRAME_ANCHOR_LAST, sha256="closing",
                   px=(1024, 576))
    cards = {"closing": AssetCard(sha256="closing", kind=AssetKind.IMAGE,
                                  style="Live-action, cinematic",
                                  subjects=[{"kind": "object",
                                             "descriptor": "the black sports car",
                                             "attributes": ["carbon fibre body"]}])}
    brief = Brief(intent="the car rolls to a stop under the lights", seconds=13.3, assets=[ref])
    plan = deterministic_draft(brief, Mode.L2VA, cards, opts=ProfileOptions())
    result, findings, _ = _assess(plan, brief, Mode.L2VA, ProfileOptions(), [])
    assert "13.67-second mark" in result.prompt, result.prompt.splitlines()[0]
    assert not [f for f in findings if f.severity == "ERROR"], [str(f) for f in findings]


@pytest.mark.parametrize("mode", [Mode.I2VA, Mode.FL2VA, Mode.L2VA])
def test_the_renderer_and_the_validator_agree_on_the_line_for_every_keyframe_mode(mode):
    """One source of truth: `grid.instruction_line_for`. Two implementations of a mandated string
    is how the fl2va notation split into two forms depending on which path won."""
    from h3ir.render import instruction_line

    assets = {
        Mode.I2VA: [AssetRef(kind=AssetKind.IMAGE, role=Role.FRAME_ANCHOR_FIRST, sha256="a",
                             px=(1024, 576))],
        Mode.L2VA: [AssetRef(kind=AssetKind.IMAGE, role=Role.FRAME_ANCHOR_LAST, sha256="b",
                             px=(1024, 576))],
        Mode.FL2VA: [AssetRef(kind=AssetKind.IMAGE, role=Role.FRAME_ANCHOR_FIRST, sha256="a",
                              px=(1024, 576)),
                     AssetRef(kind=AssetKind.IMAGE, role=Role.FRAME_ANCHOR_LAST, sha256="b",
                              px=(1024, 576))],
    }[mode]
    brief = Brief(intent="the car rolls forward", seconds=13.3, assets=assets)
    plan = deterministic_draft(brief, mode, {}, opts=ProfileOptions())
    rendered = instruction_line(plan, ProfileOptions())
    assert rendered == instruction_line_for(mode.value, plan.shots[-1].n, s_ss_text(328 / 24))
