"""A style-role picture lends its look and keeps its contents out of the video.

Measured 2026-08-15, matrix row 19 on the tray surface: a line drawing declared `style`, with a
note reading "Do not put this gnome in the video", produced a written document whose Subject 1 IS
the gnome, fully_preserved, standing in the storm scene — while the report's own marker said
weak_reference. The role reached the service (manifest confirmed); nothing on the writing side
stated what a style reference is or forbade the wrong reading. The storyboard role had this exact
defect and got its fix — a stated fact in the writer's ask plus rule R28 — and style never got the
sibling. This file is that sibling: `style_facts` states the fact, R29 makes the wrong reading an
ERROR the fix loop must clear.
"""
from __future__ import annotations

from h3ir.prose import style_facts
from h3ir.validate import Context, validate

DOC_CONTENT_CLAIM = """subject_definitions:
<Subject 1> is the gnome in <Picture 2>, with pointed conical hat, long full beard, round shoes.
<Subject 2> is the lighthouse on the cliff, tall and white with a lantern room.

summary:
[reference generation] The target video depicts <Subject 1> watching <Subject 2> in a storm.

retention_analysis:
<Subject 1> (appears in [Shot 1]): fully_preserved - the gnome's silhouette and hat are retained.

detailed_description:
[Shot 1] Live-action, cinematic, a wide shot as <Subject 1> stands at the cliff edge while the
camera pushes in with small amplitude at slow speed.

overall_soundscape:
Wind and surf against rock throughout.

non_diegetic_music:
N/A
"""

DOC_PROPER = """subject_definitions:
<Subject 1> is the lighthouse on the cliff, tall and white with a lantern room.
<Picture 2> is the style and composition reference for the target video, defining the
black-outline, white-background, flat-shading aesthetic.

summary:
[reference generation] The target video depicts <Subject 1> in a storm, rendered in the line-art
style of <Picture 2>.

retention_analysis:
<Picture 2> (style and composition): fully_preserved - the target video adheres to the
black-outline, white-background aesthetic defined in the reference.

detailed_description:
[Shot 1] 2D line-art animation, a wide shot as waves break under <Subject 1> while the camera
pushes in with small amplitude at slow speed.

overall_soundscape:
Wind and surf against rock throughout.

non_diegetic_music:
N/A
"""


def _ctx() -> Context:
    return Context(
        mode="ref2va", n_pictures=2, n_videos=0, n_audios=0, duration_s=8.0,
        declared_roles=(("<Picture 1>", "subject", "fully_preserved"),
                        ("<Picture 2>", "style", "weak_reference")))


def test_a_style_plates_contents_defined_as_a_subject_is_an_error():
    """The measured failure verbatim: the gnome walked into the video."""
    errs = [f for f in validate(DOC_CONTENT_CLAIM, _ctx()) if f.severity == "ERROR"]
    assert any(f.rule == "R29-style-cited-as-content" for f in errs), [str(f) for f in errs]
    msg = next(f.msg for f in errs if f.rule == "R29-style-cited-as-content")
    assert "<Picture 2>" in msg and "style" in msg


def test_the_mandated_construct_satisfies_the_rule():
    errs = [f for f in validate(DOC_PROPER, _ctx())
            if f.severity == "ERROR" and f.rule.startswith("R29")]
    assert not errs, [str(f) for f in errs]


def test_a_subject_role_picture_is_untouched_by_the_rule():
    findings = validate(DOC_PROPER, _ctx())
    assert not any(f.rule.startswith("R29") and "<Picture 1>" in f.msg for f in findings)


def test_the_fact_is_stated_to_the_writer():
    text = style_facts((("<Picture 1>", "subject"), ("<Picture 2>", "style")))
    assert "<Picture 2>" in text
    assert "<Picture 1>" not in text, "a subject-role picture is none of this function's business"
    assert "style" in text
    assert "never" in text.lower()


def test_no_style_plate_means_no_fact_block():
    assert style_facts((("<Picture 1>", "subject"),)) == ""
