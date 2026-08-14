"""A storyboard plans the shots and never appears in the video, and the document must say so.

FOUND BY RENDERING, through the node: a picture attached with the declared role `storyboard` came
back defined as `<Subject 2> ... the modern showroom environment in <Picture 2>`, shipped `ready`.
Reproduced service-direct at the same seed, so it is the compiler, not the node. `build_subjects`
correctly refuses to make a subject out of a storyboard (plan.py), and the deterministic draft
writes the mandated construct (render.py), but the written path told the writer nothing: the label
fell into the "attached and not yet described" block, whose instruction is to define it, so the
writer defined it as scenery. The same disease `audio_task_facts` and `video_task_facts` cure for
sound and footage: a fact the wiring settles was never stated, and a rule never checked the claim.

No model and no GPU anywhere in this file.
"""
from __future__ import annotations

from h3ir.prose import storyboard_facts
from h3ir.validate import Context, validate

DOC_CONTENT_CLAIM = """subject_definitions:
<Subject 1> is the black sports car in <Picture 1>, with sharp angular geometry.
<Subject 2> is the modern showroom environment in <Picture 2>, with a polished concrete floor.

summary:
[reference generation] The target video shows <Subject 1> prowling through <Subject 2>.

retention_analysis:
<Subject 1> (appears in [Shot 1]): fully_preserved - the car's geometry is retained.
<Subject 2> (appears in [Shot 1]): fully_preserved - the showroom is retained.

detailed_description:
The target video is in a cinematic live-action style.
[Shot 1] A low tracking shot follows <Subject 1> across the floor of <Subject 2>.

overall_soundscape:
Tyre noise on polished concrete.

non_diegetic_music:
N/A
"""

DOC_PROPER = """subject_definitions:
<Subject 1> is the black sports car in <Picture 1>, with sharp angular geometry.
<Picture 2> is a storyboard reference for [Shot 1] and [Shot 2], defining their viewpoint, subject placement, and shot order.

summary:
[reference generation] The target video shows <Subject 1> prowling a showroom, staged per <Picture 2>.

retention_analysis:
<Subject 1> (appears in [Shot 1], [Shot 2]): fully_preserved - the car's geometry is retained.
<Picture 2> (storyboard reference): weak_reference - the viewpoint, subject placement and shot order are followed, while the drawing itself is not reproduced.

detailed_description:
The target video is in a cinematic live-action style.
[Shot 1] A low tracking shot follows <Subject 1> across the showroom floor.
[Shot 2] At 00:04.000, the shot cuts to a high wide view of <Subject 1> stopping.

overall_soundscape:
Tyre noise on polished concrete.

non_diegetic_music:
N/A
"""


def _ctx() -> Context:
    return Context(
        mode="ref2va", n_pictures=2, n_videos=0, n_audios=0, duration_s=8.0,
        declared_roles=(("<Picture 1>", "subject", "fully_preserved"),
                        ("<Picture 2>", "storyboard", "weak_reference")))


def test_a_storyboard_defined_as_scenery_is_an_error():
    """The measured failure verbatim: the board became an environment subject."""
    errs = [f for f in validate(DOC_CONTENT_CLAIM, _ctx()) if f.severity == "ERROR"]
    assert any(f.rule == "R28-storyboard-cited-as-content" for f in errs), \
        [str(f) for f in errs]
    msg = next(f.msg for f in errs if f.rule == "R28-storyboard-cited-as-content")
    assert "<Picture 2>" in msg and "storyboard" in msg


def test_the_mandated_construct_satisfies_the_rule():
    errs = [f for f in validate(DOC_PROPER, _ctx())
            if f.severity == "ERROR" and f.rule.startswith("R27")]
    assert not errs, [str(f) for f in errs]


def test_a_subject_role_picture_is_untouched_by_the_rule():
    """<Subject 1> is sourced from <Picture 1>, role subject. R27 must never fire on it."""
    findings = validate(DOC_PROPER, _ctx())
    assert not any(f.rule.startswith("R27") and "<Picture 1>" in f.msg for f in findings)


def test_the_fact_is_stated_to_the_writer():
    """The ask names the board and forbids the two wrong readings, mirroring video_task_facts."""
    text = storyboard_facts((("<Picture 1>", "subject"), ("<Picture 2>", "storyboard")))
    assert "<Picture 2>" in text
    assert "<Picture 1>" not in text, "a subject-role picture is none of this function's business"
    assert "storyboard" in text
    assert "never appears" in text or "does not appear" in text


def test_no_storyboard_means_no_fact_block():
    assert storyboard_facts((("<Picture 1>", "subject"),)) == ""
