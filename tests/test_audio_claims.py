"""An audio task type is a claim about an attached signal. No model and no GPU.

A video edit degraded to the deterministic draft on 6 of 7 runs, always on the same rule:
`M7-audio-reuse-without-audio`. The writer kept producing "[video editing + audio reuse] ...
preserving the original audio track", which is what editing a video MEANS, and both correction
rounds failed to remove it.

The rule is right and the writer was not told the one fact that settles it. ref-en.txt 2.5: "An
ordinary reference video does not create `<Audio N>` merely because the file contains sound." The
runtime takes a soundtrack as its own wired input (`ref_video_audio_N`), so with none wired the
signal never reaches the model and the target video's audio is generated. Reuse is a promise the
render cannot keep.

Two changes, both tested here. The finding now says what to write instead, because a finding that
survives being stated plainly is a signal about the finding. And the ask states what the wiring
settles, which is the same principle the renderer already holds: "a prose stage that could write
the prefix could invent a relationship the pack does not contain".
"""
from __future__ import annotations

from h3ir.models import AssetKind, AssetRef, Brief, Role
from h3ir.prose import audio_task_facts
from h3ir.validate import Context, validate


def _ref2va(summary: str, retention: str = "<Subject 1> (appears in [Shot 1]): fully_preserved - "
                                          "the car's identity is retained.") -> str:
    return ("subject_definitions:\n<Subject 1> is the black car in <Video 1>, with a carbon "
            "bonnet.\n<Video 1> is the source video for the target video edit.\n\n"
            f"summary:\n{summary}\n\n"
            f"retention_analysis:\n{retention}\n<Video 1> (source video editing): "
            "fully_preserved - the original framing is maintained.\n\n"
            "detailed_description:\nA style line.\n[Shot 1] The camera holds a static shot on "
            "<Subject 1> as it rolls through the tunnel.\n\n"
            "overall_soundscape:\nTyre noise builds under the engine.\n\nnon_diegetic_music:\nN/A\n")


def _rules(text: str, **kw) -> dict[str, str]:
    ctx = Context(mode="ref2va", n_videos=1, n_audios=0, duration_s=5.167,
                  generation_task=False, **kw)
    return {f.rule: f.msg for f in validate(text, ctx) if f.severity == "ERROR"}


# ---------------------------------------------------------------- the rule still bites

def test_reusing_audio_that_is_not_attached_is_still_an_error():
    found = _rules(_ref2va("[video editing + audio reuse] The target video is an edited version "
                           "of <Video 1>. The white car replaces the black one while the original "
                           "audio track is preserved."))
    assert "M7-audio-reuse-without-audio" in found


def test_referencing_audio_that_is_not_attached_is_the_same_error():
    """The twin hole. `audio reference` claims a relationship to an attached signal exactly as
    `audio reuse` does, and only one of the two was checked."""
    found = _rules(_ref2va("[video editing + audio reference] The target video is an edited "
                           "version of <Video 1>. The new audio continues the original track's "
                           "character."))
    assert "M8-audio-reference-without-audio" in found


def test_a_video_edit_with_no_audio_claim_at_all_is_clean():
    """The shape the writer should produce. If this failed, the fix loop would have nowhere to
    converge to and the rule would be unsatisfiable rather than strict."""
    found = _rules(_ref2va("[video editing] The target video is an edited version of <Video 1>. "
                           "The black car becomes white while the tunnel and framing hold."))
    assert not found, found


def test_the_finding_says_what_to_write_instead():
    """Why it survived two correction rounds: it named the defect and not the remedy. The model was
    asserting something true about the request, so "that is wrong" left it with nothing to change.
    """
    msg = _rules(_ref2va("[video editing + audio reuse] The target video is an edited version of "
                         "<Video 1>. The original audio track is preserved."))[
        "M7-audio-reuse-without-audio"]
    assert "Delete 'audio reuse' from the task-type prefix" in msg
    assert "overall_soundscape" in msg, "it has to say where the sound goes instead"
    assert "ref-en.txt 2.5" in msg, "and why a soundtrack is not an <Audio N>"


def test_an_attached_audio_makes_the_claim_legal_again():
    """The rule is about the wiring, not about the words. With a soundtrack wired, reuse is exactly
    what ref-en.txt 3 says to claim."""
    text = ("subject_definitions:\n<Subject 1> is the black car in <Video 1>, with a carbon "
            "bonnet.\n<Video 1> is the source video for the target video edit.\n"
            "<Audio 1> is the synchronized audio track of <Video 1>, providing the engine "
            "noise.\n\nsummary:\n[video editing + audio reuse] The target video is an edited "
            "version of <Video 1>. The white car replaces the black one and <Audio 1> stays "
            "audible.\n\nretention_analysis:\n<Subject 1> (appears in [Shot 1]): fully_preserved - "
            "the car's identity is retained.\n<Video 1> (source video editing): fully_preserved - "
            "the original framing is maintained.\n<Audio 1>: partially_copy - the engine noise is "
            "kept under the new mix.\n\ndetailed_description:\nA style line.\n[Shot 1] The camera "
            "holds a static shot on <Subject 1> as it rolls through the tunnel with <Audio 1> "
            "continuing underneath.\n\noverall_soundscape:\nTyre noise builds under the engine.\n\n"
            "non_diegetic_music:\nN/A\n")
    found = [f for f in validate(text, Context(mode="ref2va", n_videos=1, n_audios=1,
                                               duration_s=5.167, generation_task=False))
             if f.severity == "ERROR"]
    assert not found, [str(f) for f in found]


# ---------------------------------------------------------------- one finding making the next

def test_the_editing_opening_finding_does_not_ask_for_the_prefix_to_be_moved():
    """Measured on live output. Told "video-editing summaries must open with 'The target video is an
    edited version of <Video 1>.'", the model moved that sentence in FRONT of the task-type prefix
    and tripped M1 on the next round -- 3 of 7 runs degraded on M1 after M7 was fixed. ref-en.txt 3
    says "begin the summary AFTER the task-type prefix with" that sentence, so the message now says
    which order and shows the whole shape.
    """
    msg = _rules(_ref2va("[video editing] The white car replaces the black one in <Video 1>."))[
        "M6-editing-opening"]
    assert "immediately after the task-type prefix" in msg
    assert "keep the prefix first" in msg
    assert "[video editing] The target video is an edited version of <Video 1>." in msg
    assert "Add the sentence, do not move the prefix" in msg


def test_the_mandated_sentence_may_carry_on_with_a_comma():
    """Measured on live output. Demanding the full stop rejected "The target video is an edited
    version of <Video 1>, where the vehicle is changed to a white car" -- the mandated clause, said
    once, continuing into the specifics. The model then satisfied the finding by prepending the
    sentence it had already written and shipped it twice.
    """
    found = _rules(_ref2va("[video editing] The target video is an edited version of <Video 1>, "
                           "where the vehicle is changed to a white car while the tunnel holds."))
    assert "M6-editing-opening" not in found, found


def test_the_mandated_sentence_written_twice_is_an_error():
    """What shipped `ready` while the rule was byte-strict, and the reason the strictness was the
    thing that produced it."""
    found = _rules(_ref2va("[video editing] The target video is an edited version of <Video 1>. The "
                           "target video is an edited version of <Video 1>, where the vehicle is "
                           "changed to a white car."))
    assert "M10-editing-opening-repeated" in found
    assert "belongs once" in found["M10-editing-opening-repeated"]


def test_the_renderer_does_not_prepend_a_sentence_the_body_already_opens_with():
    """The same brittleness in the deterministic path: `startswith` matched only the full-stop form,
    so the renderer duplicated the sentence for exactly the bodies the rule had just rejected."""
    from h3ir.grid import Target
    from h3ir.models import AssetKind, ManifestEntry, Mode, Plan, ShotPlan
    from h3ir.render import render_summary

    plan = Plan(mode=Mode.REF2VA, target=Target.build(5.0),
                manifest=[ManifestEntry(slot=0, label="<Video 1>", kind=AssetKind.VIDEO,
                                        sha256="v1", wiring="ref_video_1", role=Role.EDIT_SOURCE)],
                subjects=[], speakers=[], shots=[ShotPlan(n=1, start_ms=0, end_ms=5000)],
                task_types=["video editing"])
    plan.summary = ("The target video is an edited version of <Video 1>, where the vehicle is "
                    "changed to a white car.")
    out = render_summary(plan)
    assert out.count("The target video is an edited version of <Video 1>") == 1, out


def test_a_prefix_in_front_of_the_prefix_is_caught_as_a_missing_prefix():
    """What the model actually produced: `<Video 1> The target video is an edited version of
    <Video 1>.` -- the mandated sentence pulled to the front and the prefix gone."""
    found = _rules(_ref2va("<Video 1> The target video is an edited version of <Video 1>. The white "
                           "car replaces the black one."))
    assert "M1-task-prefix" in found
    assert "before any other text" in found["M1-task-prefix"]


def test_the_prefix_appearing_twice_is_an_error():
    """The other way the same correction went wrong, and it shipped `ready`: the model prepended the
    mandated sentence with a fresh prefix and left its original one in place. M1 reads the opening
    and M3 reads inside one bracket group, so neither could see it."""
    found = _rules(_ref2va("[video editing] The target video is an edited version of <Video 1>. "
                           "[video editing] The white car replaces the black one."))
    assert "M9-task-prefix-repeated" in found


def test_a_bracketed_shot_marker_in_the_summary_is_not_a_second_prefix():
    """The rule counts a later bracket group only when its contents are all task types, so ordinary
    bracketed asides are untouched. A rule that fired on '[Shot 1]' would be worse than none."""
    found = _rules(_ref2va("[video editing] The target video is an edited version of <Video 1>. The "
                           "white car replaces the black one from [Shot 1] onward."))
    assert "M9-task-prefix-repeated" not in found, found


# ---------------------------------------------------------------- what the writer is told

def test_with_no_audio_attached_the_ask_rules_out_both_audio_types():
    fact = audio_task_facts(("<Video 1>",), ("video editing",))
    assert "may NOT contain `audio reuse` or `audio reference`" in fact
    assert "separately wired input and none is wired here" in fact
    assert "overall_soundscape" in fact


def test_the_ask_forbids_the_prose_claim_too_and_not_only_the_prefix():
    """Dropping the task type while still writing "the original audio is preserved" would satisfy
    every rule and keep the false promise, so the ask names the sentence as well as the prefix."""
    fact = audio_task_facts(("<Video 1>",), ("video editing",))
    assert "do not write that the original audio is preserved, reused or carried over" in fact


def test_with_audio_attached_the_ask_names_the_relationship_the_roles_declare():
    fact = audio_task_facts(("<Video 1>", "<Audio 1>"), ("video editing", "audio reuse"))
    assert "<Audio 1>" in fact
    assert "audio reuse" in fact
    assert "may NOT contain" not in fact


def test_the_ask_is_built_from_the_wiring_a_real_brief_produces():
    """Not from a hand-written label tuple. The point of the fact is that it agrees with the
    manifest the app will wire, so it is derived from the same function the manifest is."""
    from h3ir.grid import Target
    from h3ir.plan import build_manifest, derive_task_types

    brief = Brief(intent="change the car to a white one", assets=[
        AssetRef(kind=AssetKind.VIDEO, role=Role.EDIT_SOURCE, sha256="v1", seconds=5.0,
                 frames=120)])
    manifest = build_manifest(brief, Target.build(5.0))
    fact = audio_task_facts(tuple(m.label for m in manifest),
                            tuple(derive_task_types(manifest, brief)))
    assert "may NOT contain `audio reuse` or `audio reference`" in fact
