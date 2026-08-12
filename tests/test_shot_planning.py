"""The model plans the edit; code proves it legal.

The failure that moved the decision: the planner divided duration by 3.4, spaced the cuts evenly,
and handed the model two four-second containers of the same continuous action. Both came back as
"the man walks down the corridor".

The first fix over-reached. It made "these two shots look alike to my taxonomy" an ERROR, which is a
judgement a competent director can disagree with, and ERRORs are what the fix loop sends back to the
model -- so the rule could make it rewrite a legitimate edit. What survives is the spec's own
sentence (base-en.txt 4.2): a cut should introduce new information about subject, space, state,
viewpoint or time. In the plan that is decidable from the `what_changes` field; in the text it is
decidable only in the degenerate case where the later shot states nothing at all that the earlier
one had not. Shot count is not a defect, and similarity is not a defect.
"""
from __future__ import annotations

import pytest

from h3ir.grid import Target
from h3ir.shots import (MIN_SHOT_MS, ProposedShot, spans, validate_proposal)
from h3ir.validate import Context, _shot_signature, validate

T8 = Target.build(8)          # 192 frames, 8.000 s exactly


def _shot(purpose="establish", framing="wide", action="he walks forward down the corridor",
          changes="he closes the distance", start=0.0, cam="Push In"):
    return {"purpose": purpose, "framing": framing, "action": action,
            "what_changes": changes, "starts_at_s": start,
            "camera": {"type": cam, "amplitude": "small", "speed": "slow"},
            "subjects": ["<Subject 1>"], "sync_sound": []}


# ---------------------------------------------------------------- one shot is a real answer

def test_a_single_shot_proposal_is_accepted():
    """The old code could never choose this: 8 / 3.4 rounds to 2, so a continuous push was always
    cut in half. A request for one steady movement wants one take."""
    res = validate_proposal({"shots": [_shot()], "reasoning": "one continuous push"}, T8)
    assert res.ok and len(res.shots) == 1
    assert res.shots[0].start_ms == 0
    assert spans(res.shots, T8) == [(0, 8000)]


def test_two_distinct_shots_are_accepted():
    res = validate_proposal({"shots": [
        _shot(purpose="establish", framing="wide", action="he walks in from the darkness",
              changes="torchlight reaches him"),
        _shot(purpose="react", framing="close", action="he stops and turns his head",
              changes="the walk ends and he looks off left", start=4.5, cam="Static Shot"),
    ], "reasoning": "wide then close"}, T8)
    assert res.ok, res.rejections
    assert [s.start_ms for s in res.shots] == [0, 4500]


# ---------------------------------------------------------------- the judged defect

def test_a_cut_whose_new_information_repeats_the_previous_one_is_REJECTED():
    """The decidable version of the defect: the planner states what each cut introduces, and here
    it states the same thing twice. That is a fact about the proposal, not an opinion about it."""
    res = validate_proposal({"shots": [
        _shot(action="he walks forward down the corridor"),
        _shot(action="he strides ahead along the passage", start=4.0),
    ], "reasoning": "two shots"}, T8)
    assert not res.ok
    assert any("same change" in r for r in res.rejections), res.rejections


def test_two_similar_shots_with_DIFFERENT_stated_changes_are_ACCEPTED():
    """The rule that used to live here rejected this, and it was wrong to. Same framing, same
    camera, the same kind of action -- and two different pieces of information. A director may
    shoot two beats of one walk at one distance; the validator does not get a vote on that."""
    res = validate_proposal({"shots": [
        _shot(action="he walks forward down the corridor",
              changes="torchlight reaches his boots"),
        _shot(action="he keeps walking down the corridor",
              changes="the torchlight reaches his face and he squints", start=4.0),
    ], "reasoning": "two beats of one approach"}, T8)
    assert res.ok, res.rejections


def test_a_shot_that_changes_nothing_is_rejected():
    res = validate_proposal({"shots": [
        _shot(),
        _shot(purpose="develop", framing="close", action="he keeps walking", changes="", start=4.0),
    ], "reasoning": "x"}, T8)
    assert not res.ok
    assert any("nothing that changes" in r for r in res.rejections)


# ---------------------------------------------------------------- code still owns the clock

def test_a_first_shot_that_does_not_start_at_zero_is_repaired():
    res = validate_proposal({"shots": [_shot(start=1.5)], "reasoning": "x"}, T8)
    assert res.ok and res.shots[0].start_ms == 0
    assert any("begins at 0" in r for r in res.repairs)


def test_a_cut_past_the_end_is_pulled_back_inside():
    res = validate_proposal({"shots": [
        _shot(),
        _shot(purpose="close", framing="close", action="he stops", changes="the walk ends",
              start=20.0, cam="Static Shot"),
    ], "reasoning": "x"}, T8)
    assert res.ok, res.rejections
    assert res.shots[1].start_ms <= 8000 - MIN_SHOT_MS
    assert any("stay inside" in r for r in res.repairs)


def test_cuts_too_close_together_are_spaced():
    res = validate_proposal({"shots": [
        _shot(),
        _shot(purpose="react", framing="close", action="he stops", changes="the walk ends",
              start=0.2, cam="Static Shot"),
    ], "reasoning": "x"}, T8)
    assert res.ok, res.rejections
    assert res.shots[1].start_ms - res.shots[0].start_ms >= MIN_SHOT_MS


def test_too_many_shots_to_fit_is_rejected_not_squeezed():
    shots = [_shot(start=0.0)]
    for i in range(1, 4):
        shots.append(_shot(purpose="develop", framing=("close", "medium", "wide")[i - 1],
                           action=f"action {i}", changes=f"change {i}", start=0.1 * i))
    res = validate_proposal({"shots": shots, "reasoning": "x"}, Target.build(5), max_shots=4)
    assert res.ok or res.rejections, "either it fits after repair or it is refused"
    if res.ok:
        starts = [s.start_ms for s in res.shots]
        assert starts == sorted(starts) and len(set(starts)) == len(starts)
        assert starts[-1] <= int(Target.build(5).effective_seconds * 1000) - MIN_SHOT_MS


def test_an_out_of_vocabulary_purpose_is_repaired_not_accepted():
    res = validate_proposal({"shots": [_shot(purpose="vibes", framing="cinematic")],
                             "reasoning": "x"}, T8)
    assert res.ok
    assert res.shots[0].purpose == "establish" and res.shots[0].framing == "medium"
    assert len(res.repairs) >= 2


def test_an_empty_proposal_is_rejected():
    assert not validate_proposal({"shots": [], "reasoning": "x"}, T8).ok


# ---------------------------------------------------------------- the text-level rule

def _two_shot_brief(b1: str, b2: str) -> str:
    return ("integrated_multimodal_description: [Shot 1] Live-action, cinematic, " + b1 +
            " [Shot 2] At 00:04.000, " + b2 + "\n\noverall_soundscape: Wind.\n\n"
            "non_diegetic_music: N/A\n")


def _rules(text: str, severity: str | None = None) -> set[str]:
    return {f.rule for f in validate(text, Context(mode="t2va", duration_s=8.0))
            if severity is None or f.severity == severity}


def test_a_cut_that_restates_the_previous_shot_and_nothing_else_is_flagged():
    """The degenerate case, and the only one this rule claims: shot 2 says nothing shot 1 did not.
    Same framing, same camera, not one content word of its own."""
    text = _two_shot_brief(
        "a wide shot as the man walks forward down the corridor while the camera pushes in slowly.",
        "a wide shot as the man walks forward down the corridor while the camera pushes in.")
    assert "R17-cut-states-nothing-new" in _rules(text, "WARN")


def test_one_new_fact_across_the_cut_is_enough_to_clear_it():
    """The falsification half. Identical to the case above except the second shot states one thing
    the first did not -- which is exactly what the spec asks a cut to do."""
    text = _two_shot_brief(
        "a wide shot as the man walks forward down the corridor while the camera pushes in slowly.",
        "a wide shot as the man walks forward down the corridor toward a doorway while the camera "
        "pushes in.")
    assert "R17-cut-states-nothing-new" not in _rules(text)


def test_similar_shots_worded_differently_are_NOT_flagged():
    """This is the case the old rule fired on as an ERROR, which sent it into the fix loop and had
    the model rewrite a legitimate edit. Two beats of one walk at one distance is a real choice."""
    text = _two_shot_brief(
        "a wide shot as the man walks forward while the camera pushes in slowly.",
        "a wide view in which he strides ahead into the torchlight as the camera pushes onward.")
    assert "R17-cut-states-nothing-new" not in _rules(text)


def test_the_distinctness_rule_can_never_be_an_error():
    """It is a WARN by design: the spec says a cut *should* carry new information, and ERRORs are
    what the fix loop sends back to the model. A rule that can be argued with must not do that."""
    text = _two_shot_brief(
        "a wide shot as the man walks forward down the corridor while the camera pushes in slowly.",
        "a wide shot as the man walks forward down the corridor while the camera pushes in.")
    assert not any(f.rule.startswith("R17") and f.severity == "ERROR"
                   for f in validate(text, Context(mode="t2va", duration_s=8.0)))


def test_the_validator_accepts_two_shots_with_different_jobs():
    text = _two_shot_brief(
        "a wide shot as the man walks forward while the camera pushes in slowly.",
        "a close framing holds a static shot as he stops and turns his head to look off left.")
    assert "R17-cut-states-nothing-new" not in _rules(text)


def test_a_single_shot_cannot_trip_the_rule():
    """Shot count is not a defect. One shot for an eight-second walk is a legitimate answer, and
    the spec says so itself: 'a single shot does not automatically justify a shorter description'."""
    text = ("integrated_multimodal_description: [Shot 1] Live-action, a wide shot as the man walks "
            "forward while the camera pushes in.\n\noverall_soundscape: Wind.\n\n"
            "non_diegetic_music: N/A\n")
    assert not [r for r in _rules(text) if r.startswith("R17")]


def test_the_signature_ignores_wording_and_reads_content():
    """The signature is semantic GROUPS, so synonyms collapse: walk/stride are both locomotion,
    'pushes in' and 'pushes onward' are both an inward camera move."""
    a = _shot_signature("A wide shot as the man walks forward, camera pushing in.")
    b = _shot_signature("A wide view in which he strides ahead while the lens pushes onward.")
    assert a == b, (a, b)
    assert a[0] == "wide" and "locomotion" in a[1] and a[2] == "in"
    c = _shot_signature("A close framing holds a static shot as he stops and looks off left.")
    assert c != a
    assert "held" in c[2] and "stopping" in c[1]


def test_the_metric_scores_identical_shots_as_zero_distinctness():
    """The signature still collapses synonyms, which is what makes `shot_distinctness` worth
    reporting. It is REPORTED and never gated: a drop means two shots look alike to a taxonomy in
    this file, which is information for whoever reads the run, not a verdict on the edit."""
    from h3ir.evalloop.score import content_words, jaccard
    a = "A wide shot as the man walks forward while the camera pushes in slowly."
    b = "A wide view in which he strides ahead as the camera pushes onward."
    assert jaccard(content_words(a), content_words(b)) < 0.4, "word overlap looks fine"
    assert _shot_signature(a) == _shot_signature(b), "content is identical"
