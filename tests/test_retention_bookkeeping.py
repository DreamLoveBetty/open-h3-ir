"""Three bookkeeping rules the spec states plainly and nothing enforced.

  ref-en.txt 4: "Use one line for each reference label."  `out/X4-fully-copy--s7.json` shipped
  `ready` with TWO lines for `<Audio 1>`, the first of which calls the wav "the image" and gives it
  a Picture-shaped parenthetical about a first frame. One wav was attached and no picture at all.

  ref-en.txt 3: a task type is chosen "according to the actual role each reference asset plays".
  `M5-editing-without-video`, `M7-audio-reuse-without-audio` and `M8-audio-reference-without-audio`
  guard three of the six against being asserted out of nothing; `keyframe completion` and
  `video continuation` had no equivalent, and seven documents claimed `keyframe completion` with no
  image attached at all.

  ref-en.txt 2.1: "One subject may be defined by multiple reference assets ... When the same subject
  comes from multiple assets, combine the sources and state what each asset provides."
  `out/P5b*.json` ships `ready` with the same man defined twice, as `<Subject 1>` from `<Picture 1>`
  and `<Subject 3>` from `<Video 1>`, where the spec's form is one subject citing both.

The asymmetry in severity is the point of the third one: which two definitions describe one person
is a judgement, so it is reported. Whether a label has two lines, and whether a claimed task type
has an asset behind it, are facts.
"""
from __future__ import annotations

from h3ir.validate import Context, validate

DEFS = ("subject_definitions:\n"
        "<Subject 1> is the black car in <Picture 1>, with a carbon fibre body.\n")
DESC = ("detailed_description:\nThe target video is in cinematic style.\n"
        "[Shot 1] The camera pushes in with small amplitude at slow speed on <Subject 1> as it "
        "rolls forward over wet concrete.\n\n"
        "overall_soundscape:\nTyres roll over standing water.\n\nnon_diegetic_music:\nN/A\n")


def _ref(*, defs: str = DEFS, summary: str = "[reference generation] The target video shows "
         "<Subject 1>.", retention: str = "<Subject 1> (appears in [Shot 1]): fully_preserved - "
         "the carbon fibre body is retained.") -> str:
    return (f"{defs}\nsummary:\n{summary}\n\nretention_analysis:\n{retention}\n\n{DESC}")


def _ctx(**kw) -> Context:
    base = dict(mode="ref2va", n_pictures=1, duration_s=8.0)
    base.update(kw)
    return Context(**base)


def _errs(text: str, **kw) -> set[str]:
    return {f.rule for f in validate(text, _ctx(**kw)) if f.severity == "ERROR"}


# ---------------------------------------------------------------- one line per label

def test_a_label_analysed_twice_is_an_error():
    """The X4 shape, reduced: one label, two retention lines, two different markers."""
    text = _ref(retention="<Subject 1> (appears in [Shot 1]): fully_preserved - the body is "
                          "retained.\n<Subject 1> ([Shot 1] first frame): weak_reference - the "
                          "composition is followed.")
    errs = _errs(text)
    assert "R24-label-analysed-twice" in errs, errs
    msg = next(f.msg for f in validate(text, _ctx()) if f.rule == "R24-label-analysed-twice")
    assert "<Subject 1>" in msg and "2" in msg


def test_the_audio_case_that_shipped_ready():
    """Verbatim from `out/X4-fully-copy--s7.json`, whose manifest was one wav and nothing else. The
    document invents an image, calls the wav "the image", and writes two lines for one label."""
    text = _ref(defs="subject_definitions:\n<Audio 1> is the complete and final audio track for "
                     "the target video.\n",
                summary="[audio reuse] The target video reuses <Audio 1> one to one.",
                retention="<Audio 1> ([Shot 1] first frame): reference - the image serves as the "
                          "exact starting frame of the video.\n"
                          "<Audio 1>: fully_copy - <Audio 1> is reused 1:1 as the target video's "
                          "complete final audio track.")
    assert "R24-label-analysed-twice" in _errs(text, n_pictures=0, n_audios=1)


def test_one_line_each_for_several_labels_is_fine():
    text = _ref(defs=DEFS + "<Subject 2> is the wet dock road in <Picture 2>, with black asphalt.\n",
                retention="<Subject 1> (appears in [Shot 1]): fully_preserved - the body is "
                          "retained.\n<Subject 2> (appears in [Shot 1]): fully_preserved - the "
                          "asphalt is retained.")
    text = text.replace("[Shot 1] The camera", "[Shot 1] <Subject 2> holds the frame. The camera")
    assert "R24-label-analysed-twice" not in _errs(text, n_pictures=2)


def test_the_official_example_has_one_line_per_label():
    from pathlib import Path
    golden = Path(__file__).resolve().parents[1] / "h3ir/golden/official_ref2va_example.txt"
    found = [f for f in validate(golden.read_text(encoding="utf-8"),
                                 Context(mode="ref2va", n_pictures=4, n_videos=2, n_audios=1))
             if f.rule == "R24-label-analysed-twice"]
    assert not found, [str(f) for f in found]


# ---------------------------------------------------------------- a task type needs its asset

def test_keyframe_completion_with_no_picture_attached_is_an_error():
    """Seven documents claimed it with only a wav attached. The three audio and video task types
    were guarded and this one was not, so the same defect had a rule in one direction only."""
    text = _ref(defs="subject_definitions:\n<Audio 1> is a sound-texture reference for the target "
                     "video.\n",
                summary="[keyframe completion + audio reuse] The target video uses <Audio 1>.",
                retention="<Audio 1>: partially_copy - part of <Audio 1> is reused.")
    errs = _errs(text, n_pictures=0, n_audios=1)
    assert "M11-keyframe-without-picture" in errs, errs


def test_video_continuation_with_no_video_attached_is_an_error():
    text = _ref(summary="[video continuation] The target video continues the scene.")
    assert "M12-continuation-without-video" in _errs(text)


def test_the_guards_stay_quiet_when_the_asset_is_there():
    text = _ref(summary="[keyframe completion] The target video lands on <Picture 1>.",
                retention="<Subject 1> (appears in [Shot 1]): fully_preserved - the body is "
                          "retained.\n<Picture 1> ([Shot 1] first frame): fully_preserved - the "
                          "composition is held.")
    text = text.replace("on <Subject 1> as it", "from <Picture 1> as <Subject 1>")
    errs = _errs(text)
    assert "M11-keyframe-without-picture" not in errs, errs


def test_a_downgraded_anchor_does_not_manufacture_this_finding():
    """The rule has to stay clear of rows 22 and 36. When a caller declares a frame anchor on a
    request that routes to ref2va, the role is downgraded (X10) and `keyframe completion` is no
    longer derived -- but a picture IS attached, so this rule cannot fire on that case. It fires only
    on a claim with no picture anywhere, which is not something the downgrade can produce."""
    text = _ref(summary="[keyframe completion + reference generation] The target video lands on "
                        "<Picture 1>.",
                retention="<Subject 1> (appears in [Shot 1]): fully_preserved - the body is "
                          "retained.")
    assert "M11-keyframe-without-picture" not in _errs(text)


# ---------------------------------------------------------------- one subject, several assets

def test_the_same_subject_defined_twice_from_two_assets_is_reported():
    """`out/P5b*.json`: "Take the man's face and clothes from the picture and his walk from the
    clip" produced <Subject 1> "is the man in <Picture 1>" and <Subject 3> "is the man in
    <Video 1>". One man, two labels, and it shipped ready."""
    text = _ref(defs="subject_definitions:\n"
                     "<Subject 1> is the man in <Picture 1>, with short dark hair and a dark blue "
                     "t-shirt.\n"
                     "<Subject 3> is the man in <Video 1>, whose walking motion is referenced.\n",
                retention="<Subject 1> (appears in [Shot 1]): fully_preserved - the hair is "
                          "retained.\n<Subject 3> (appears in [Shot 1]): fully_preserved - the "
                          "gait is retained.")
    text = text.replace("on <Subject 1> as it", "on <Subject 1> and <Subject 3> as he")
    found = [f for f in validate(text, _ctx(n_videos=1)) if f.rule == "R25-subject-defined-twice"]
    assert found and found[0].severity == "WARN", [str(f) for f in validate(text, _ctx(n_videos=1))]
    assert "<Picture 1>" in found[0].msg and "<Video 1>" in found[0].msg
    assert "whose appearance comes from" in found[0].msg, "the message shows the spec's own form"


def test_the_merged_form_the_spec_prints_is_clean():
    """ref-en.txt 2.1, verbatim. The construct appeared in 0 of 11 shipped documents; it must at
    least be legal, or the fix would be pointless."""
    text = _ref(defs="subject_definitions:\n<Subject 1> is the man whose appearance comes from "
                     "<Picture 1> and whose walking motion comes from <Video 1>, with short dark "
                     "hair.\n")
    found = validate(text, _ctx(n_videos=1))
    assert not [f for f in found if f.severity == "ERROR"], [str(f) for f in found]
    assert "R25-subject-defined-twice" not in {f.rule for f in found}


def test_two_different_subjects_from_two_assets_are_not_a_duplicate():
    """The rule keys on the same descriptor from different single sources, so a car and a road do
    not collide."""
    text = _ref(defs="subject_definitions:\n"
                     "<Subject 1> is the black car in <Picture 1>, with a carbon fibre body.\n"
                     "<Subject 2> is the wet dock road in <Video 1>, with black asphalt.\n",
                retention="<Subject 1> (appears in [Shot 1]): fully_preserved - the body is "
                          "retained.\n<Subject 2> (appears in [Shot 1]): fully_preserved - the "
                          "asphalt is retained.")
    text = text.replace("[Shot 1] The camera", "[Shot 1] <Subject 2> fills the frame. The camera")
    assert "R25-subject-defined-twice" not in {
        f.rule for f in validate(text, _ctx(n_videos=1))}


def test_two_subjects_from_the_same_single_asset_are_not_a_duplicate():
    """The other half of ref-en.txt 2.1 -- one asset providing several subjects -- is a construct the
    compiler produces correctly, and this rule must not touch it."""
    text = _ref(defs="subject_definitions:\n"
                     "<Subject 1> is the man in <Picture 1>, with short dark hair.\n"
                     "<Subject 2> is the man in <Picture 1>, standing further back in a grey coat.\n",
                retention="<Subject 1> (appears in [Shot 1]): fully_preserved - the hair is "
                          "retained.\n<Subject 2> (appears in [Shot 1]): fully_preserved - the "
                          "coat is retained.")
    text = text.replace("on <Subject 1> as it", "on <Subject 1> and <Subject 2> as they")
    assert "R25-subject-defined-twice" not in {f.rule for f in validate(text, _ctx())}


# ---------------------------------------------------------------- what the writer is licensed to do

def test_the_ask_licenses_the_merged_definition():
    """The deterministic definition lines are handed over as facts to use or reword, one per
    manifest entry, so the writer rewords two lines into two lines. Nothing told it that combining
    them is the spec's own form when the request says one subject draws on several assets."""
    from h3ir.draft import deterministic_draft
    from h3ir.models import AssetCard, AssetKind, AssetRef, Brief, Mode, Role
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

    refs = [AssetRef(kind=AssetKind.IMAGE, role=Role.SUBJECT, sha256=s, px=(1024, 576))
            for s in ("a", "b")]
    cards = {s: AssetCard(sha256=s, kind=AssetKind.IMAGE, style="Live-action",
                          subjects=[{"kind": "object", "descriptor": "the black sports car",
                                     "attributes": ["carbon fibre body"]}])
             for s in ("a", "b")}
    brief = Brief(intent="Define it once as a single subject that draws its body from the first "
                         "picture and its wheels from the second.", seconds=8.0, assets=refs)
    plan = deterministic_draft(brief, Mode.REF2VA, cards, opts=ProfileOptions())
    backend = Capture()
    compose_brief(backend, brief, plan.subjects, cards, plan.target,
                  tuple(m.label for m in plan.manifest), prompt_name="compose.v2.txt",
                  mode=Mode.REF2VA, task_types=tuple(plan.task_types))
    ask = backend.asks[0]
    assert "whose appearance comes from <Picture 1> and whose walking motion comes from" in ask
    assert "never define the same person or object twice" in ask.lower()


# ---------------------------------------------------------------- a wav is not a picture

AUDIO_ONLY = ("subject_definitions:\n<Audio 1> is the complete and final audio track for the "
              "target video.\n\nsummary:\n[audio reuse] The target video is a single-shot "
              "sequence of a ferry pulling away from a jetty, {claim}. <Audio 1> is fully copied "
              "as the complete final audio track.\n\nretention_analysis:\n{ret}\n\n"
              "detailed_description:\nThe target video is in cinematic style.\n[Shot 1] The camera "
              "pushes in with small amplitude at slow speed as the ferry pulls away from the "
              "jetty.\n\noverall_soundscape:\nWater slaps the hull.\n\nnon_diegetic_music:\nN/A\n")
GOOD_RET = "<Audio 1>: fully_copy - <Audio 1> is reused 1:1 as the target video's final track."


def _audio_ctx(**kw) -> Context:
    base = dict(mode="ref2va", n_pictures=0, n_audios=1, duration_s=8.0)
    base.update(kw)
    return Context(**base)


def test_an_audio_asserted_to_be_a_frame_is_an_error():
    """Measured on 4 of 50 recorded audio-only briefs, all of them `ready`: "anchored by <Audio 1>
    as the opening frame", "<Audio 1>, which serves as the first frame". No image is attached in any
    of them, so the brief tells H3 that a wav is a picture."""
    for claim in ("anchored by <Audio 1> as the opening frame",
                  "opening on <Audio 1>, which serves as the first frame",
                  "closing on <Audio 1> as the last frame"):
        text = AUDIO_ONLY.format(claim=claim, ret=GOOD_RET)
        errs = {f.rule for f in validate(text, _audio_ctx()) if f.severity == "ERROR"}
        assert "R26-audio-described-as-a-frame" in errs, (claim, errs)


def test_the_picture_shaped_parenthetical_on_an_audio_line_is_an_error():
    """The other half of the worst document in the corpus: an <Audio N> retention line carrying a
    frame scope, with a note calling the wav "the image"."""
    text = AUDIO_ONLY.format(
        claim="a quiet crossing",
        ret="<Audio 1> ([Shot 1] first frame): reference - the image serves as the exact starting "
            "frame of the video.\n" + GOOD_RET)
    errs = {f.rule for f in validate(text, _audio_ctx()) if f.severity == "ERROR"}
    assert "R26-audio-described-as-a-frame" in errs, errs


def test_ordinary_prose_about_when_an_audio_is_heard_is_untouched():
    """ref-en.txt's own example writes "continues through the final frame" about a laugh track. A
    rule that fired on that would be rejecting the spec's own sentence."""
    text = AUDIO_ONLY.format(
        claim="scored throughout",
        ret=GOOD_RET).replace("Water slaps the hull.",
                              "<Audio 1> continues through the final frame of the video.")
    assert "R26-audio-described-as-a-frame" not in {
        f.rule for f in validate(text, _audio_ctx())}


def test_a_brief_with_no_picture_at_all_is_told_so():
    """The statement was emitted only when a <Picture N> existed, so the brief that had none was
    left to infer from the specification in its system prompt, which teaches the construct."""
    from h3ir.analyse import analyse_audio
    from h3ir.draft import deterministic_draft
    from h3ir.models import AssetKind, AssetRef, Brief, Mode, Role
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

    ref = AssetRef(kind=AssetKind.AUDIO, role=Role.BGM, sha256="wav", seconds=4.0,
                   note="a slow piano loop")
    cards = {"wav": analyse_audio(ref, "")}
    brief = Brief(intent="Use this recording as the complete final audio of a ferry leaving a "
                         "jetty.", seconds=8.0, assets=[ref])
    plan = deterministic_draft(brief, Mode.REF2VA, cards, opts=ProfileOptions())
    backend = Capture()
    compose_brief(backend, brief, plan.subjects, cards, plan.target,
                  tuple(m.label for m in plan.manifest), prompt_name="compose.v2.txt",
                  mode=Mode.REF2VA, task_types=tuple(plan.task_types))
    ask = backend.asks[0]
    assert "No image is attached to this request." in ask
    assert "never claim `keyframe completion`" in ask
    assert "it has no frames and it is not an image" in ask
