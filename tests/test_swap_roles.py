"""Placing a subject into a clip, and swapping one out for it.

The owner's ask, in his words: *"to purposedly, and consistently be able to 'place' or 'replace' a
subject into the video ... for replacing, I mean literally 'it's all the same, same camera, same
motions, same dialog, but a different character which looks different, has different
proportions'"*.

The measurement that shaped every assertion below. Four seeds of "replace the man in this clip with
the elderly woman in the picture: everything else stays exactly the same, the same camera move, the
same actions at the same moments, and the same spoken line", wired the only way the layer could
express it before this file existed -- the clip as `edit_source`, the plate as `subject`:

| what came back | 4 seeds |
|---|---|
| the target video relocated into the PLATE's grey studio backdrop | 4 / 4 |
| the source clip's carpentry workshop described anywhere | 0 / 4 |
| the camera asserted static, against a source that pushes in slowly | 3 / 4 |
| `attribute_transfer` on the figure being swapped out | 0 / 4 |
| a reference label opened and never closed, shipped with zero findings | 1 / 4 |

Three separate causes, and each one has its own test here.

  the style came off the plate      `style.observed_style` walks a dict and takes the first IMAGE
                                    card with a style. On an edit that was a studio portrait of the
                                    person being swapped IN, and its "clean, high-resolution studio
                                    photography" became the target video's style opening every time.
  the clip's world reached nobody   `_definition_lines` walks `subjects`, so a video card's
                                    `environment`, `framing`, `lighting` and `summary` reach
                                    nothing. The only setting anyone described to the writer was
                                    the plate's.
  no role MEANT a swap              `subject` says "this appears in the video" and is true of a
                                    placement, a replacement and an ordinary reference alike, so
                                    the derived retention line could not say which.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from h3ir.analyse import _camera_or_blank
from h3ir.compile import BriefRefused, _edit_source_worlds, _taken_over, check_swap
from h3ir.draft import deterministic_draft
from h3ir.models import (AssetCard, AssetKind, AssetRef, Brief, Mode, Role, SWAP_ROLES,
                         SubjectPlan)
from h3ir.plan import bind_replacement, build_plan, derive_task_types, swap_decisions
from h3ir.prose import edit_source_facts, swap_facts
from h3ir.render import render_ir, render_retention, render_subject_definitions
from h3ir.style import observed_style, resolve_style
from h3ir.validate import Context, validate

CLIP = "sha-clip"
PLATE = "sha-plate"


def _clip_card(people: int = 1, camera: str = "the framing tightens on the subject") -> AssetCard:
    subs = [{"kind": "person", "descriptor": f"the bearded man {i}" if people > 1 else
             "the bearded man", "attributes": ["a red plaid flannel shirt"], "pose": []}
            for i in range(people)]
    subs.append({"kind": "object", "descriptor": "the hammer",
                 "attributes": ["a yellow and black handle"], "pose": []})
    return AssetCard(
        sha256=CLIP, kind=AssetKind.VIDEO, frames_seen=3,
        summary="a bearded man drives a nail at a workbench and turns to the camera",
        environment="a wood-panelled carpentry workshop with large multi-paned windows",
        framing="a medium-wide shot", lighting="bright natural daylight from the windows",
        style="Live-action, cinematic", motion="he raises the hammer and strikes",
        camera=camera, subjects=subs)


def _plate_card() -> AssetCard:
    return AssetCard(
        sha256=PLATE, kind=AssetKind.IMAGE, composition="bare_plate",
        summary="a full-body studio portrait of an elderly woman in a yellow raincoat",
        environment="a seamless grey studio backdrop",
        lighting="even, diffused studio lighting from the front",
        framing="a full-body shot", style="Clean, high-resolution studio photography",
        subjects=[{"kind": "person", "descriptor": "the elderly woman",
                   "attributes": ["short white hair", "a bright yellow raincoat"], "pose": []}])


def _brief(picture_role: Role | None = Role.REPLACEMENT_SUBJECT, *,
           with_clip: bool = True) -> tuple[Brief, dict[str, AssetCard]]:
    assets = []
    cards: dict[str, AssetCard] = {}
    if picture_role is not None:
        assets.append(AssetRef(kind=AssetKind.IMAGE, role=picture_role, sha256=PLATE,
                               px=(1344, 768), role_stated=True))
        cards[PLATE] = _plate_card()
    if with_clip:
        assets.append(AssetRef(kind=AssetKind.VIDEO, role=Role.EDIT_SOURCE, sha256=CLIP,
                               seconds=5.167, frames=124, role_stated=True))
        cards[CLIP] = _clip_card()
    return Brief(intent="swap the man for her and change nothing else", assets=assets,
                 seconds=5.167, shots=1), cards


def _plan(picture_role: Role = Role.REPLACEMENT_SUBJECT, **kw):
    brief, cards = _brief(picture_role, **kw)
    return build_plan(brief, Mode.REF2VA, cards), brief, cards


# ------------------------------------------------------------------ the binding

def test_a_replacement_binds_to_the_one_figure_of_its_own_kind():
    """Like for like. The clip yields a person AND a hammer; a picture of a person takes over from
    the person, and binding to "the subjects from the clip" would have been ambiguous on the very
    first brief anyone ran."""
    plan, _b, _c = _plan()
    taken = [s for s in plan.subjects if s.taken_over_by]
    assert len(taken) == 1, [(s.label, s.descriptor, s.kind) for s in plan.subjects]
    assert taken[0].descriptor == "the bearded man"
    assert taken[0].retention == "attribute_transfer"
    incoming = next(s for s in plan.subjects if s.label == taken[0].taken_over_by)
    assert incoming.descriptor == "the elderly woman"
    assert incoming.retention == "fully_preserved"


def test_a_placement_transfers_nothing():
    """The whole reason there are two roles. A placement ADDS, so no figure in the clip loses
    anything and no line may claim a transfer."""
    plan, _b, _c = _plan(Role.PLACED_SUBJECT)
    assert not [s for s in plan.subjects if s.taken_over_by]
    assert "attribute_transfer" not in render_retention(plan)


def test_an_ordinary_subject_is_untouched_by_the_binding():
    plan, _b, _c = _plan(Role.SUBJECT)
    assert not [s for s in plan.subjects if s.taken_over_by]
    assert "attribute_transfer" not in render_retention(plan)


def test_binding_is_a_no_op_without_an_edit_source():
    brief, cards = _brief(Role.REPLACEMENT_SUBJECT, with_clip=False)
    plan = build_plan(brief, Mode.REF2VA, cards)
    assert bind_replacement(plan.subjects, plan.manifest) == []


# ------------------------------------------------------------------ the refusals

def test_a_swap_role_without_an_edit_source_is_refused_with_a_sentence():
    brief, cards = _brief(Role.REPLACEMENT_SUBJECT, with_clip=False)
    plan = build_plan(brief, Mode.REF2VA, cards)
    with pytest.raises(BriefRefused) as e:
        check_swap(brief, plan)
    assert e.value.code == "swap-without-edit-source"
    assert "edit_source" in str(e.value)


@pytest.mark.parametrize("role", SWAP_ROLES, ids=[r.value for r in SWAP_ROLES])
def test_both_swap_roles_are_refused_without_a_clip(role):
    """The refusal belongs to the pair, not to one of them: a placement with nothing to place into
    is exactly as meaningless as a replacement with nobody to replace."""
    brief, cards = _brief(role, with_clip=False)
    plan = build_plan(brief, Mode.REF2VA, cards)
    with pytest.raises(BriefRefused):
        check_swap(brief, plan)


def test_two_candidates_of_the_same_kind_are_refused_rather_than_guessed():
    """Picking the first would put the wrong figure's name into a document that reads perfectly."""
    brief, cards = _brief(Role.REPLACEMENT_SUBJECT)
    cards[CLIP] = _clip_card(people=2)
    plan = build_plan(brief, Mode.REF2VA, cards)
    with pytest.raises(BriefRefused) as e:
        check_swap(brief, plan)
    assert e.value.code == "replacement-target-ambiguous"
    assert "2 person(s)" in str(e.value)
    # and it names them, so the caller can act on the sentence
    assert "the bearded man 0" in str(e.value) and "the bearded man 1" in str(e.value)


def test_a_correctly_wired_swap_is_not_refused():
    """The control. A refusal that fires on the good case is a broken check, not a strict one."""
    brief, cards = _brief(Role.REPLACEMENT_SUBJECT)
    check_swap(brief, build_plan(brief, Mode.REF2VA, cards))


def test_an_unrelated_brief_is_not_refused():
    brief, cards = _brief(Role.SUBJECT)
    check_swap(brief, build_plan(brief, Mode.REF2VA, cards))


# ------------------------------------------------------------------ what the draft writes

def test_the_draft_states_the_transfer_and_names_where_it_lands():
    plan, _b, _c = _plan()
    ret = render_retention(plan)
    line = next(l for l in ret.splitlines() if "attribute_transfer" in l)
    incoming = next(s.taken_over_by for s in plan.subjects if s.taken_over_by)
    assert incoming in line, line
    assert "appearance is not retained" in line, line


def test_the_draft_states_the_swap_role_in_the_definition():
    plan, _b, _c = _plan()
    defs = render_subject_definitions(plan)
    assert "takes the place of" in defs, defs
    assert "position in frame, actions and timing" in defs, defs


def test_the_replaced_figure_is_defined_with_nothing_to_draw():
    """Measured on the first render of the role: the ordinary definition form spelled out the
    beard, the hair and the red plaid shirt of the man the caller had asked to remove, and H3 drew
    him holding the opening frames before the replacement took over. Nothing cited him in
    detailed_description in any of four seeds -- the identity list in subject_definitions was
    enough on its own, because that section is conditioning like every other."""
    plan, _b, _c = _plan()
    defs = render_subject_definitions(plan)
    line = next(l for l in defs.splitlines() if "does NOT appear" in l)
    assert "red plaid flannel shirt" not in line, line
    assert "the bearded man" in line, line
    assert "<Subject 1>" in line, line
    # and the plate's own subject keeps its attributes, because it IS what gets drawn
    kept = next(l for l in defs.splitlines() if l.startswith("<Subject 1>"))
    assert "bright yellow raincoat" in kept, kept


def test_the_writer_is_handed_the_same_stripped_line():
    """`_definition_lines` is what the ask tells the writer to use or reword, so an attribute list
    surviving there puts it back into the document by a different door."""
    from h3ir.prose import _definition_lines
    plan, _b, cards = _plan()
    lines = _definition_lines(plan.subjects, cards, tuple(m.label for m in plan.manifest))
    line = next(l for l in lines if "does NOT appear" in l)
    assert "red plaid flannel shirt" not in line, line
    assert render_subject_definitions(plan).splitlines()[1] == line, "the two must not drift"


def test_the_ask_says_why_the_replaced_figure_carries_no_appearance():
    plan, _b, _c = _plan()
    text = swap_facts((("<Picture 1>", "replacement_subject"),),
                      (("<Video 1>", "edit_source"),), _taken_over(plan))
    assert "NO appearance detail" in text
    assert "does not appear in the target video" in text


def test_the_draft_says_the_clip_keeps_camera_and_timing_under_a_swap():
    """What survives IS the request. A clip line that says only 'while the edit is applied' leaves
    the same camera, the same motion and the same words all unstated."""
    plan, _b, _c = _plan()
    line = next(l for l in render_retention(plan).splitlines() if l.startswith("<Video 1>"))
    for word in ("camera movement", "timing", "setting"):
        assert word in line, line


def test_a_placement_says_so_on_both_lines():
    plan, _b, _c = _plan(Role.PLACED_SUBJECT)
    assert "is placed into <Video 1>" in render_subject_definitions(plan)
    assert "is placed into the scene" in render_retention(plan)


def test_the_swap_draft_passes_its_own_validator():
    """The invariant `compile_brief` raises on: the draft is deterministic, so an ERROR in it is
    our bug and there is nothing to fall back to."""
    for role in SWAP_ROLES:
        brief, cards = _brief(role)
        plan = deterministic_draft(brief, Mode.REF2VA, cards)
        text = render_ir(plan).prompt
        ctx = Context(mode="ref2va", n_pictures=1, n_videos=1, duration_s=plan.target.effective_seconds,
                      generation_task=False,
                      declared_roles=tuple((m.label, m.role.value, "") for m in plan.manifest))
        errs = [f for f in validate(text, ctx) if f.severity == "ERROR"]
        assert not errs, (role, [str(f) for f in errs], text)


def test_rendering_a_swap_plan_twice_is_byte_identical():
    """The invariant the whole service rests on (X1-render-determinism): `IRDocument.prompt` is a
    pure function of the plan. `_swap_clause` reads the manifest and the subject list, so a
    dict-ordering dependency here would break re-rendering rather than any test above."""
    for role in SWAP_ROLES:
        brief, cards = _brief(role)
        plan = deterministic_draft(brief, Mode.REF2VA, cards)
        assert render_ir(plan).prompt == render_ir(plan).prompt, role


def test_both_task_types_are_derived():
    """`video editing` from the clip and `reference generation` from the picture, and ref-en.txt 3
    combines them with ` + ` rather than making them exclusive."""
    plan, _b, _c = _plan()
    assert "video editing" in plan.task_types
    assert "reference generation" in plan.task_types
    assert derive_task_types(plan.manifest, _b) == plan.task_types


# ------------------------------------------------------------------ the root cause: whose look

def test_the_edit_source_owns_the_look_not_the_plate():
    """The measured cause of 4 of 4 relocations. `observed_style` took the first IMAGE card it
    found, which on an edit is the person being swapped IN, photographed in a studio."""
    cards = {PLATE: _plate_card(), CLIP: _clip_card()}
    assert "studio" in observed_style(cards).lower(), "the fixture must reproduce the old answer"
    got = observed_style(cards, prefer=CLIP)
    assert "studio" not in got.lower(), got
    assert "cinematic" in got.lower(), got


def test_resolve_style_prefers_the_edit_source_end_to_end():
    brief, cards = _brief(Role.REPLACEMENT_SUBJECT)
    decision = resolve_style(brief, cards)
    assert "studio" not in decision.phrase.lower(), decision.phrase
    assert "daylight" in decision.phrase.lower(), decision.phrase


def test_without_an_edit_source_the_plate_still_governs():
    """The control: this must change the answer only where an edit source exists."""
    brief, cards = _brief(Role.SUBJECT, with_clip=False)
    assert "studio" in resolve_style(brief, cards).phrase.lower()


# ------------------------------------------------------------------ what the writer is told

def test_the_clips_world_reaches_the_ask():
    plan, _b, cards = _plan()
    worlds = _edit_source_worlds(plan, cards)
    assert len(worlds) == 1
    label, world, camera = worlds[0]
    assert label == "<Video 1>"
    assert "carpentry workshop" in world
    assert "daylight" in world
    text = edit_source_facts(worlds, (("<Picture 1>", "replacement_subject"),))
    assert "carpentry workshop" in text
    assert "the framing tightens" in text
    # and the plate's own backdrop is ruled out in as many words
    assert "belong to the photograph" in text


def test_an_unobserved_camera_is_declared_unobserved_rather_than_left_silent():
    """Silence measured as 'static camera' in 3 of 4 seeds. A description with nothing to say about
    the camera says it holds still, which is an assertion about a clip nothing here has checked."""
    text = edit_source_facts((("<Video 1>", "a workshop", ""),))
    assert "NOT observed" in text
    assert "do not write" in text and "static" in text
    assert "the framing tightens" not in text


def test_an_observed_camera_is_handed_over_and_the_prohibition_drops():
    text = edit_source_facts((("<Video 1>", "a workshop", "the framing tightens"),))
    assert "the framing tightens" in text
    assert "NOT observed" not in text


def test_no_edit_source_means_no_edit_block():
    assert edit_source_facts(()) == ""


def test_swap_facts_names_the_bound_figure_and_the_marker():
    plan, _b, _c = _plan()
    taken = _taken_over(plan)
    assert taken == (("<Picture 1>", "<Subject 2>"),), taken
    text = swap_facts((("<Picture 1>", "replacement_subject"),),
                      (("<Video 1>", "edit_source"),), taken)
    assert "<Subject 2>" in text
    assert "attribute_transfer" in text
    assert "fully_preserved" in text          # named as the thing it must not be
    assert "the same camera movement" in text


def test_swap_facts_is_silent_for_a_placement_target_it_has_none_of():
    text = swap_facts((("<Picture 1>", "placed_subject"),), (("<Video 1>", "edit_source"),), ())
    assert "ADDED into <Video 1>" in text
    assert "attribute_transfer" not in text


def test_swap_facts_is_empty_without_a_swap_role_or_without_a_clip():
    assert swap_facts((("<Picture 1>", "subject"),), (("<Video 1>", "edit_source"),), ()) == ""
    assert swap_facts((("<Picture 1>", "replacement_subject"),), (), ()) == ""


def test_the_role_token_never_appears_in_the_ask_as_prose():
    """P9's ground. `replacement_subject` is a wiring name; the ask may say the caller declared it,
    but the words the writer copies into the document have to be English."""
    plan, _b, _c = _plan()
    text = swap_facts((("<Picture 1>", "replacement_subject"),),
                      (("<Video 1>", "edit_source"),), _taken_over(plan))
    # the one mention is the declaration itself, in capitals, not a phrase to copy
    assert "REPLACEMENT" in text
    assert "`replacement_subject`" not in text


def test_unknown_camera_is_stored_as_nothing():
    """A card field that is empty means "not observed" everywhere else in the analyser, and the
    literal string would be spliced into an ask as a fact about the clip."""
    assert _camera_or_blank("unknown") == ""
    assert _camera_or_blank("  Unknown. ") == ""
    assert _camera_or_blank("n/a") == ""
    assert _camera_or_blank("the framing tightens") == "the framing tightens"


# ------------------------------------------------------------------ the surface it is picked on

def test_both_swap_roles_can_be_picked_in_the_media_tray():
    """The half that shipped missing: a role no interface offers is a role nobody can use.

    Everything above proves the compiler does the right thing with these two, and every one of
    those tests passed while `ROLES["picture"]` in the node pack offered the original six and the
    only way to ask for a swap was to write JSON into the tray widget by hand.

    The pack imports nothing from `h3ir` and must not start now -- it talks to the service over
    HTTP and is installed on machines where this package is absent. So the tie is asserted from
    here, which is the one place that legitimately sees both sides. tray.js is held against
    `comfyui/tray.py` by tests/test_panel_agrees_with_the_tray.py, so these two lines reach the
    dropdown a user actually opens.
    """
    from comfyui.tray import PICTURE_ROLES
    offered = set(PICTURE_ROLES.values())
    missing = sorted(r.value for r in SWAP_ROLES if r.value not in offered)
    assert not missing, (
        f"{missing} cannot be picked on a picture slot in the media tray, so this feature is "
        "reachable over HTTP and not from the node pack it was built for. Add it to PICTURE_ROLES "
        "in comfyui/tray.py, in the words the panel shows.")


def test_the_words_the_tray_shows_for_a_swap_are_not_the_role_tokens():
    """P9's ground again, one layer out. The panel's vocabulary is the user's craft, not the wire
    format: a dropdown reading `replacement_subject` is a dropdown that has to be explained."""
    from comfyui.tray import PICTURE_ROLES
    for words, role in PICTURE_ROLES.items():
        if role in {r.value for r in SWAP_ROLES}:
            assert "_" not in words and words != role, words
            assert "clip" in words, (
                f"{words!r} says nothing about the clip, and both of these roles are statements "
                "about one: a picture set to either without a clip being edited is refused.")


# ------------------------------------------------------------------ the rules

_GOOD = """subject_definitions:
<Subject 1> is the elderly woman in <Picture 1>, with short white hair and a yellow raincoat.
<Subject 2> is the bearded man in <Video 1>, with a red plaid flannel shirt.
<Video 1> is the source video for the target video edit.

summary:
[video editing + reference generation] The target video is an edited version of <Video 1>, with
<Subject 1> in the place of <Subject 2>.

retention_analysis:
<Subject 1> (appears in [Shot 1]): fully_preserved - her white hair and yellow raincoat are retained.
<Subject 2> (appears in [Shot 1]): attribute_transfer - <Subject 1> takes over the position in frame, the actions and the timing of the bearded man, whose own appearance is not retained.
<Video 1> (source video editing): partially_preserved - the framing, setting and timing are held.

detailed_description:
The target video is in a live-action, cinematic style with bright natural daylight.
[Shot 1] <Subject 1> stands at the workbench in the wood-panelled workshop and drives a nail.

overall_soundscape:
Workshop room tone throughout.

non_diegetic_music:
N/A
"""


def _swap_ctx() -> Context:
    return Context(mode="ref2va", n_pictures=1, n_videos=1, duration_s=5.167,
                   generation_task=False,
                   declared_roles=(("<Picture 1>", "replacement_subject", ""),
                                   ("<Video 1>", "edit_source", "")))


def _errs(text: str, ctx: Context | None = None) -> list[str]:
    return [f.rule for f in validate(text, ctx or _swap_ctx()) if f.severity == "ERROR"]


def test_the_mandated_document_trips_no_rule():
    """The input that must NOT fire. Written before the rules, because a rule proved only in the
    direction it fires is a rule nobody has shown to be narrow."""
    assert _errs(_GOOD) == [], validate(_GOOD, _swap_ctx())


def test_a_declared_replacement_with_no_transfer_line_is_an_error():
    """The measured shape: `partially_preserved` on the figure being swapped out, which reads "the
    referenced content is still used" -- the one thing that is no longer true of him."""
    bad = _GOOD.replace(
        "<Subject 2> (appears in [Shot 1]): attribute_transfer - <Subject 1> takes over the "
        "position in frame, the actions and the timing of the bearded man, whose own appearance "
        "is not retained.",
        "<Subject 2> (appears in [Shot 1]): partially_preserved - the man's identity is replaced.")
    assert "attribute_transfer" not in bad
    assert "R31-replacement-not-recorded" in _errs(bad)


def test_the_rule_is_silent_when_no_replacement_is_declared():
    ctx = Context(mode="ref2va", n_pictures=1, n_videos=1, duration_s=5.167,
                  generation_task=False,
                  declared_roles=(("<Picture 1>", "subject", ""),
                                  ("<Video 1>", "edit_source", "")))
    bad = _GOOD.replace("attribute_transfer", "partially_preserved")
    assert "R31-replacement-not-recorded" not in _errs(bad, ctx)


def test_a_transfer_that_names_no_target_is_an_error():
    """The shape the marker was misused in before it was removed from the compiler: written for a
    restyle, where there is no different target subject at all, and legal in the enum every time."""
    bad = _GOOD.replace(
        "<Subject 2> (appears in [Shot 1]): attribute_transfer - <Subject 1> takes over the "
        "position in frame, the actions and the timing of the bearded man, whose own appearance "
        "is not retained.",
        "<Subject 2> (appears in [Shot 1]): attribute_transfer - the look moves across to the new figure.")
    assert "R32-transfer-target-unnamed" in _errs(bad)


def test_a_label_opened_and_never_closed_is_an_error():
    """Found shipped with zero findings, in the first live replacement brief anybody compiled."""
    bad = _GOOD.replace("<Subject 2> is the bearded man in <Video 1>,",
                        "<Subject 2> is the bearded man in <Video 1,")
    rules = _errs(bad)
    assert "L6-label-not-closed" in rules, rules


def test_every_closed_label_shape_is_left_alone():
    """The input that must NOT trip it, including the two-digit and the spaced forms."""
    ok = ("<Subject 1> and <Picture 12> and <Video 3> and <Audio 10> are all fine, "
          "and so is a sentence ending on <Subject 2>.")
    assert not [f for f in validate(ok, Context(mode="ref2va"))
                if f.rule == "L6-label-not-closed"]


def test_the_published_example_never_trips_the_new_rules():
    """MiniMax's own Ref2VA example is the control the whole validator is proved against: a rule
    that fires on it is a wrong rule, not a strict one."""
    spec = Path(__file__).resolve().parents[1] / "h3ir" / "prompts" / "ref-en.txt"
    body = spec.read_text(encoding="utf-8")
    example = body[body.index("subject_definitions:"):body.index("</details>")]
    fired = [f.rule for f in validate(example, Context(mode="ref2va"))
             if f.rule in ("L6-label-not-closed", "R31-replacement-not-recorded",
                           "R32-transfer-target-unnamed")]
    assert not fired, fired


# ------------------------------------------------------------------ the spec, machine-checked

def test_the_spec_still_defines_attribute_transfer_as_a_DIFFERENT_target_subject():
    """Everything above rests on one sentence in ref-en.txt 4.1, and build-log 43 is the record of
    what happens when that sentence is read from memory instead of from the file: a legal value
    from the correct closed set, carrying the wrong meaning, validating perfectly for weeks.

    If MiniMax reword this row, `bind_replacement` and R31/R32 have to be re-derived, and this is
    the test that says so out loud rather than leaving it to whoever notices."""
    spec = Path(__file__).resolve().parents[1] / "h3ir" / "prompts" / "ref-en.txt"
    row = next(l for l in spec.read_text(encoding="utf-8").splitlines()
               if l.startswith("| `attribute_transfer`"))
    assert re.search(r"transferred to a different identifiable target subject", row, re.I), row


def test_the_role_pair_is_the_contract_not_a_local_list():
    """Five stages read `SWAP_ROLES`; a role added to one and forgotten in another is how a
    document ends up claiming a swap the wiring does not perform."""
    assert set(SWAP_ROLES) == {Role.PLACED_SUBJECT, Role.REPLACEMENT_SUBJECT}
    from h3ir.plan import _ROLE_MARKER
    for r in SWAP_ROLES:
        assert _ROLE_MARKER[r] == "fully_preserved"


def test_swap_decisions_reports_rather_than_chooses():
    """The function returns the candidates and a named problem so the caller can refuse; a version
    that picked one would make the ambiguity invisible."""
    brief, cards = _brief(Role.REPLACEMENT_SUBJECT)
    cards[CLIP] = _clip_card(people=2)
    plan = build_plan(brief, Mode.REF2VA, cards)
    decided = swap_decisions(plan.subjects, plan.manifest)
    assert len(decided) == 1
    d = decided[0]
    assert d.incoming is not None
    assert d.target is None and d.problem == "crowded"
    assert len(d.candidates) == 2
    assert all(isinstance(c, SubjectPlan) for c in d.candidates)
    assert not [s for s in plan.subjects if s.taken_over_by], "nothing may be bound"


# ------------------------------------------------------- saying WHO each picture takes over from

PLATE2 = "sha-plate-2"


def _second_plate() -> AssetCard:
    return AssetCard(
        sha256=PLATE2, kind=AssetKind.IMAGE, composition="bare_plate",
        summary="a full-body studio portrait of a young man in a blue coat",
        environment="a seamless grey studio backdrop", lighting="even studio lighting",
        framing="a full-body shot", style="Clean, high-resolution studio photography",
        subjects=[{"kind": "person", "descriptor": "the young man",
                   "attributes": ["a blue coat"], "pose": []}])


def _crowd_card() -> AssetCard:
    """A clip whose two people are told apart by their own words, which is the case the caller's
    words have to resolve. `_clip_card(people=2)` names them '... 0' and '... 1', which no user
    would ever type."""
    card = _clip_card()
    card.subjects = [
        {"kind": "person", "descriptor": "the bearded man in the plaid shirt",
         "attributes": ["a red plaid flannel shirt"], "pose": []},
        {"kind": "person", "descriptor": "the young woman at the lathe",
         "attributes": ["a grey apron"], "pose": []},
        {"kind": "object", "descriptor": "the hammer", "attributes": [], "pose": []},
    ]
    return card


def _two_swaps(first: str, second: str, clip: AssetCard | None = None):
    """Two pictures, both replacing somebody, each saying who in the caller's own words."""
    assets = [
        AssetRef(kind=AssetKind.IMAGE, role=Role.REPLACEMENT_SUBJECT, sha256=PLATE,
                 px=(1344, 768), role_stated=True, replaces=first),
        AssetRef(kind=AssetKind.IMAGE, role=Role.REPLACEMENT_SUBJECT, sha256=PLATE2,
                 px=(1344, 768), role_stated=True, replaces=second),
        AssetRef(kind=AssetKind.VIDEO, role=Role.EDIT_SOURCE, sha256=CLIP,
                 seconds=5.167, frames=124, role_stated=True),
    ]
    cards = {PLATE: _plate_card(), PLATE2: _second_plate(), CLIP: clip or _crowd_card()}
    brief = Brief(intent="swap them both", assets=assets, seconds=5.167, shots=1)
    return brief, cards


def test_two_replacements_each_take_over_from_the_figure_they_name():
    """The defect this field was built for: two pictures both replacing, one candidate taken by
    whichever came first, and the second picture attached, labelled and doing nothing."""
    brief, cards = _two_swaps("the man in the plaid shirt", "the woman at the lathe")
    plan = build_plan(brief, Mode.REF2VA, cards)
    check_swap(brief, plan)
    taken = {s.descriptor: s.taken_over_by for s in plan.subjects if s.taken_over_by}
    assert len(taken) == 2, [(s.label, s.descriptor, s.taken_over_by) for s in plan.subjects]
    by_label = {s.label: s for s in plan.subjects}
    # <Picture 1> is the elderly woman and she takes the plaid shirt; <Picture 2> the young man,
    # who takes the lathe. Crossed bindings would read perfectly and swap the wrong two people.
    for target, expected in (("the man in the plaid shirt", "the elderly woman"),
                             ("the woman at the lathe", "the young man")):
        incoming = by_label[taken[target]]
        assert incoming.descriptor == expected, (target, incoming.descriptor)


def test_the_words_the_caller_wrote_are_what_the_brief_calls_the_figure():
    """Their words, not the analyser's reading of three frames: it is what they will recognise."""
    brief, cards = _two_swaps("the man in the plaid shirt", "the woman at the lathe")
    plan = build_plan(brief, Mode.REF2VA, cards)
    defs = render_subject_definitions(plan)
    assert "the man in the plaid shirt" in defs, defs
    assert "the bearded man in the plaid shirt" not in defs, "the card's wording should give way"


def test_a_named_figure_the_analyser_never_saw_becomes_a_subject_of_its_own():
    """The owner's case, and the reason this is free text: the service reads three sampled frames,
    so somebody can be in none of them and walk in later. The clip's own person stays untouched."""
    brief, cards = _two_swaps("the bearded man", "the woman who walks in at the end",
                              clip=_clip_card())
    plan = build_plan(brief, Mode.REF2VA, cards)
    check_swap(brief, plan)
    walked_in = next(s for s in plan.subjects
                     if s.descriptor == "the woman who walks in at the end")
    assert walked_in.retention == "attribute_transfer"
    assert walked_in.taken_over_by
    assert walked_in.sources == ["<Video 1>"], walked_in.sources
    assert not walked_in.attributes, "there is nothing to draw of a figure being removed"
    assert len({s.label for s in plan.subjects}) == len(plan.subjects), "labels must stay unique"


def test_one_candidate_binds_whatever_the_caller_called_it():
    """No matching where there is nothing to choose between: the clip's own reading found one
    person, so a name that reads nothing like it is a description and never a failed query."""
    brief, cards = _brief(Role.REPLACEMENT_SUBJECT)
    brief.assets[0].replaces = "the guy in the cap"
    plan = build_plan(brief, Mode.REF2VA, cards)
    check_swap(brief, plan)
    taken = [s for s in plan.subjects if s.taken_over_by]
    assert len(taken) == 1
    assert taken[0].descriptor == "the guy in the cap"


def test_a_name_that_fits_nobody_in_the_reading_becomes_the_figure_itself():
    """The owner's ruling, and the case that shows it is not a looser match.

    <Picture 2> says it replaces "the person on the roof". The analyser read two people in the
    clip and one of them is already taken, so exactly one candidate is left over -- and the words
    must NOT land on it. That leftover binding is the pick-what-is-left guess this layer exists to
    refuse, and it is the specific way dropping the refusal could have gone wrong. The words make
    their own subject instead, and the figure that was read stays exactly as it was read.
    """
    brief, cards = _two_swaps("the man in the plaid shirt", "the person on the roof")
    plan = build_plan(brief, Mode.REF2VA, cards)
    check_swap(brief, plan)                      # no refusal: the caller saw the clip

    roof = next(s for s in plan.subjects if s.descriptor == "the person on the roof")
    assert roof.retention == "attribute_transfer"
    assert roof.taken_over_by, "it has to be the figure <Picture 2> takes over from"
    assert roof.sources == ["<Video 1>"]

    lathe = next(s for s in plan.subjects if s.descriptor == "the young woman at the lathe")
    assert lathe.retention == "fully_preserved", "the leftover figure is not up for grabs"
    assert not lathe.taken_over_by


def test_a_name_that_fits_two_of_them_is_also_taken_at_its_word():
    """Ambiguous against a reading of three frames is not ambiguous to the person who watched the
    clip. Neither figure the analyser read is touched, and the words stand as their own subject."""
    brief, cards = _brief(Role.REPLACEMENT_SUBJECT)
    brief.assets[0].replaces = "the man"
    cards[CLIP] = _crowd_card()
    cards[CLIP].subjects = [
        {"kind": "person", "descriptor": "the bearded man in the plaid shirt", "attributes": []},
        {"kind": "person", "descriptor": "the older man at the lathe", "attributes": []},
    ]
    plan = build_plan(brief, Mode.REF2VA, cards)
    check_swap(brief, plan)

    said = next(s for s in plan.subjects if s.descriptor == "the man")
    assert said.retention == "attribute_transfer" and said.taken_over_by
    for read in ("the bearded man in the plaid shirt", "the older man at the lathe"):
        figure = next(s for s in plan.subjects if s.descriptor == read)
        assert figure.retention == "fully_preserved", read
        assert not figure.taken_over_by, read


def test_neither_removed_refusal_can_be_raised_any_more():
    """A code that can no longer fire is a lie in an error vocabulary. These two were published in
    a report; nothing may go on producing them."""
    import pathlib as _p

    body = (_p.Path(__file__).resolve().parents[1] / "h3ir" / "compile.py").read_text()
    for code in ("replacement-target-unmatched", "replacement-target-tied"):
        assert code not in body, code


def test_saying_who_on_a_role_that_cannot_replace_is_refused_rather_than_dropped():
    brief, cards = _brief(Role.SUBJECT)
    brief.assets[0].replaces = "the man in the plaid shirt"
    plan = build_plan(brief, Mode.REF2VA, cards)
    with pytest.raises(BriefRefused) as e:
        check_swap(brief, plan)
    assert e.value.code == "replaces-without-the-role"


def test_a_crowded_clip_now_asks_for_the_words_instead_of_only_refusing():
    """The message the old refusal gave had no way out except trimming the clip."""
    brief, cards = _brief(Role.REPLACEMENT_SUBJECT)
    cards[CLIP] = _clip_card(people=2)
    plan = build_plan(brief, Mode.REF2VA, cards)
    with pytest.raises(BriefRefused) as e:
        check_swap(brief, plan)
    assert e.value.code == "replacement-target-ambiguous"
    assert "say who it replaces" in str(e.value).lower()


def test_the_clip_line_names_every_change_not_only_the_first():
    brief, cards = _two_swaps("the man in the plaid shirt", "the woman at the lathe")
    plan = build_plan(brief, Mode.REF2VA, cards)
    line = next(l for l in render_retention(plan).splitlines() if l.startswith("<Video 1>"))
    assert line.count("takes the place of") == 2, line


def test_two_swaps_render_byte_identically_twice():
    brief, cards = _two_swaps("the man in the plaid shirt", "the woman at the lathe")
    plan = deterministic_draft(brief, Mode.REF2VA, cards)
    assert render_ir(plan).prompt == render_ir(plan).prompt


def test_the_two_swap_draft_passes_its_own_validator():
    brief, cards = _two_swaps("the man in the plaid shirt", "the woman at the lathe")
    plan = deterministic_draft(brief, Mode.REF2VA, cards)
    text = render_ir(plan).prompt
    ctx = Context(mode="ref2va", n_pictures=2, n_videos=1,
                  duration_s=plan.target.effective_seconds, generation_task=False,
                  declared_roles=tuple((m.label, m.role.value, "") for m in plan.manifest))
    errs = [f"{f.rule}: {f.message}" for f in validate(text, ctx) if f.severity == "ERROR"]
    assert not errs, (errs, text)


def test_a_silent_picture_is_refused_by_both_halves_when_another_one_replaces_too():
    """Two replacements and one of them silent is refused on both sides of the pack, and neither
    refusal rests on a head count. The tray refuses because two pictures replace and one says
    nothing, which is decidable without seeing the clip at all. The compiler refuses because the
    clip it CAN see holds more than one figure of that kind, so the leftover is not a fact. Binding
    the figure nobody named would be answering the question by picking what was left."""
    from comfyui.tray import ServiceError as TrayRefusal, Slot, check_swaps
    brief, cards = _two_swaps("the man in the plaid shirt", "")
    plan = build_plan(brief, Mode.REF2VA, cards)
    with pytest.raises(BriefRefused) as e:
        check_swap(brief, plan)
    assert e.value.code == "replacement-target-ambiguous"

    slots = [Slot(kind="picture", label="one", role="replacement_subject", file="a.png [input]",
                  replaces="the man in the plaid shirt"),
             Slot(kind="picture", label="two", role="replacement_subject", file="b.png [input]")]
    with pytest.raises(TrayRefusal) as t:
        check_swaps(slots)
    assert str(t.value).startswith("@two does not say who it replaces.")


def test_the_words_the_node_collects_reach_the_field_the_compiler_reads():
    """The one hop none of the tests above crosses, and the one that was broken the whole time.

    The version of this test that stood here asserted two things: that `nodes.py` contains the line
    `extra["replaces"] = slot.replaces`, and that `AssetIn` declares a field called `replaces`. Both
    were true. Between them, `h3ir_client._asset_facts` copied four keys out of `extra` into the
    request and this was not one of them, so the words never left the machine -- and this test was
    green for as long as that lasted, because it compared two pieces of source text and never looked
    at the request.

    So it is asked of the REQUEST now, through the same function the node calls, and it is asked of
    both delivery routes because which one runs is decided later by whether the service can open
    ComfyUI's disk. `tests/test_contract_drift.py` holds the general form of this: nothing about
    what crosses is asserted from source text where it can be asserted from the payload.
    """
    from h3ir.service import AssetIn

    from comfyui.h3ir_client import plan_assets, plan_uploaded_assets

    field = "replaces"
    assert field in AssetIn.model_fields, "the compiler no longer takes it under that name"
    written = [("carguy", "image", "/comfy/input/a.png",
                {"role": "replacement_subject", "note": "carguy",
                 field: "the man in the plaid shirt"})]
    for planned in (plan_assets(written, "match", "", ""),
                    plan_uploaded_assets(written, "match", lambda _p: "0" * 64)):
        assert planned[0].get(field) == "the man in the plaid shirt", (
            "the words saying who this picture takes over from do not reach the request, so the "
            "compiler binds the swap to whoever it happens to find instead")


def test_the_clip_line_does_not_contradict_its_own_marker():
    """`partially_preserved` means some characteristics change; "held exactly" says none do. The
    line under a swap said both, and it promised a frame-for-frame match that AGENTS.md's own
    measurement says these weights do not deliver.

    The shape is MiniMax's, from the worked example in their README rather than from ref-en.txt,
    which defines the four markers and shows no example of a video being edited: `fully_preserved`
    and "are maintained while ... is edited". The non-swap branch already read that way, so both
    branches of this line now say the same kind of thing.
    """
    for role in SWAP_ROLES:
        brief, cards = _brief(role)
        plan = build_plan(brief, Mode.REF2VA, cards)
        line = next(l for l in render_retention(plan).splitlines() if l.startswith("<Video 1>"))
        assert "fully_preserved" in line, line
        assert "partially_preserved" not in line, line
        assert "held exactly" not in line, line
        assert "are maintained while" in line, line


def test_both_branches_of_the_clip_line_agree_about_what_survives():
    """The swap branch and the plain-edit branch are one claim about a source video, and a reader
    comparing two briefs should not find them disagreeing about the marker or the verb."""
    swap, cards = _brief(Role.REPLACEMENT_SUBJECT)
    plain = Brief(intent="the same clip, in the rain", seconds=5.167, shots=1, assets=[
        AssetRef(kind=AssetKind.VIDEO, role=Role.EDIT_SOURCE, sha256=CLIP, seconds=5.167,
                 frames=124, role_stated=True)])
    lines = []
    for brief in (swap, plain):
        plan = build_plan(brief, Mode.REF2VA, cards)
        lines.append(next(l for l in render_retention(plan).splitlines()
                          if l.startswith("<Video 1>")))
    for line in lines:
        assert "(source video editing): fully_preserved - the original " in line, line
        assert " are maintained while " in line, line


def test_the_wiring_that_shipped_two_prefixes_now_derives_and_writes_one():
    """The measured case, tied to `derive_task_types` rather than restating its answer.

    Two live renders through the node pack, same wiring shape: a `replacement_subject` picture, an
    `edit_source` clip, and the clip's soundtrack sent along as `bgm`. It derives three task types.
    One render shipped all three; the other shipped `[video editing + audio reuse]`, dropping the
    one the picture is the entire reason for, and no rule fired on either.
    """
    from h3ir.grid import Target
    from h3ir.repair import repair

    brief, cards = _brief(Role.REPLACEMENT_SUBJECT)
    brief.assets.append(AssetRef(kind=AssetKind.AUDIO, role=Role.BGM, sha256="sha-track",
                                 seconds=5.18, paired_video_sha256=CLIP, role_stated=True))
    cards["sha-track"] = AssetCard(sha256="sha-track", kind=AssetKind.AUDIO,
                                   summary="the clip's own soundtrack")
    plan = build_plan(brief, Mode.REF2VA, cards)
    assert set(plan.task_types) == {"reference generation", "video editing", "audio reuse"}

    written = ("subject_definitions:\n<Subject 1> is the elderly woman in <Picture 1>.\n\n"
               "summary:\n[video editing + audio reuse] The target video is an edited version of "
               "<Video 1>.\n")
    fixed = repair(written, target=Target.build(5.167), mode=Mode.REF2VA,
                   labels=tuple(m.label for m in plan.manifest),
                   task_types=tuple(plan.task_types))
    prefix = fixed.text.split("summary:", 1)[1].lstrip().split("]", 1)[0] + "]"
    assert set(p.strip() for p in prefix.strip("[]").split("+")) == set(plan.task_types), prefix
    assert "reference generation" in prefix
