"""A structure-role video lends its camera and cutting and keeps its contents out.

Measured 2026-08-15, matrix row 26 on the tray surface: "take only the camera movement and the
cutting rhythm of the clip and nothing else" produced a document that adopted the structure AND
carried the clip's man, crowd and glowing sphere into the new scene — the document even narrated
the leak ("reimagined as the lighthouse beacon"). There was no role that MEANS structure-only, so
the nearest words ("copy what is in it") did exactly what they say. This is the picture style
role's disease one asset-kind over, and it gets the same cure: a role, a skip in build_subjects, a
standalone definition line in the draft, a stated fact in the writer's ask, and a deterministic
rule (R30) the fix loop must clear.
"""
from __future__ import annotations

from h3ir.prose import structure_facts
from h3ir.validate import Context, validate

DOC_CONTENT_CLAIM = """subject_definitions:
<Subject 1> is the cartoon man in <Video 1>, with a dark beard, black baseball cap and jeans.
<Subject 2> is the lighthouse on the cliff, tall and white with a lantern room.

summary:
[reference generation] The target video depicts <Subject 1> watching <Subject 2> in a storm.

retention_analysis:
<Subject 1> (appears in [Shot 1]): partially_preserved - the man's identity is retained.

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
<Video 1> is the source video providing the camera movement and cutting rhythm for the target
video.

summary:
[reference generation] The target video depicts <Subject 1> in a storm, shot and cut to the
structure of <Video 1>.

retention_analysis:
<Video 1> (camera movement and cutting rhythm): weak_reference - the camera moves and edit timing
are followed, while the video's contents are not reproduced.

detailed_description:
[Shot 1] Live-action, cinematic, a wide shot as waves break under <Subject 1> while the camera
pushes in with small amplitude at slow speed.

overall_soundscape:
Wind and surf against rock throughout.

non_diegetic_music:
N/A
"""


def _ctx() -> Context:
    return Context(
        mode="ref2va", n_pictures=0, n_videos=1, n_audios=0, duration_s=8.0,
        declared_roles=(("<Video 1>", "structure", "weak_reference"),))


def test_a_structure_clips_contents_defined_as_a_subject_is_an_error():
    """The measured failure verbatim: the clip's man walked into the lighthouse video."""
    errs = [f for f in validate(DOC_CONTENT_CLAIM, _ctx()) if f.severity == "ERROR"]
    assert any(f.rule == "R30-structure-cited-as-content" for f in errs), [str(f) for f in errs]
    msg = next(f.msg for f in errs if f.rule == "R30-structure-cited-as-content")
    assert "<Video 1>" in msg and "structure" in msg


def test_the_mandated_construct_satisfies_the_rule():
    errs = [f for f in validate(DOC_PROPER, _ctx())
            if f.severity == "ERROR" and f.rule.startswith("R30")]
    assert not errs, [str(f) for f in errs]


def test_a_subject_role_video_is_untouched_by_the_rule():
    ctx = Context(mode="ref2va", n_pictures=0, n_videos=1, duration_s=8.0,
                  declared_roles=(("<Video 1>", "subject", "fully_preserved"),))
    findings = validate(DOC_CONTENT_CLAIM, ctx)
    assert not any(f.rule.startswith("R30") for f in findings)


def test_the_fact_is_stated_to_the_writer():
    text = structure_facts((("<Video 1>", "structure"), ("<Video 2>", "subject")))
    assert "<Video 1>" in text
    assert "<Video 2>" not in text, "a subject-role video is none of this function's business"
    assert "camera" in text and "cutting" in text
    assert "never" in text.lower()


def test_no_structure_source_means_no_fact_block():
    assert structure_facts((("<Video 1>", "subject"),)) == ""

