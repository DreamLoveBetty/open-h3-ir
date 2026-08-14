"""Two closed vocabularies the spec states and nothing checked: the cut phrase and the camera's
amplitude and speed values.

Both are the same class of defect as the label namespace: a near-miss synonym lands off the
distribution the model was trained on, costs real quality, and is invisible afterwards because the
document reads fine. Measured over the recorded corpus:

  * of 169 timestamped shot openings, 135 opened with one of base-en.txt 4.2's five cut phrases and
    34 did not, mostly by stating no transition at all and opening on a camera move instead;
  * amplitude was clean (small x150, large x6, nothing else) while speed was not: `at normal speed`
    once and `at high speed` three times, against a dimension base-en.txt 4.3 closes to slow and
    fast. The detector at the time asked only whether a LEGAL value was present, never whether an
    illegal one was, so an off-list value beside a legal one was invisible.

The two get different severities on purpose, and the reason is in the corpus. One of those four
`at high speed` hits is "As the train rushes past her at high speed", which is a train and not a
camera: a rule loose enough to catch every off-list value also rejects correct prose. So the camera
rule fires only where the spec's own idiom puts the value, and the cut-phrase rule stays a WARN
because a golden control that a human passed on legality contains a shot opening without one.
"""
from __future__ import annotations

from pathlib import Path

from h3ir.validate import Context, validate

GOLDEN = Path(__file__).resolve().parents[1] / "h3ir/golden"


def _doc(desc: str) -> str:
    return (f"integrated_multimodal_description: {desc}\n\n"
            "overall_soundscape: Rain runs off the awning.\n\n"
            "non_diegetic_music: N/A\n")


def _ctx() -> Context:
    return Context(mode="t2va", n_pictures=0, duration_s=294 / 24)


SHOT1 = ("[Shot 1] Live-action, cinematic, the fishmonger sets a crate on the stall. The camera "
         "pushes in with small amplitude at slow speed.")


# ---------------------------------------------------------------- the cut phrase

def test_a_shot_that_opens_on_a_camera_move_instead_of_a_cut_is_reported():
    """The largest group of the 34: a new shot that states no transition at all."""
    text = _doc(SHOT1 + " [Shot 2] At 00:06.000, the camera tracks alongside the crowd with small "
                        "amplitude at slow speed.")
    found = [f for f in validate(text, _ctx()) if f.rule == "P7-cut-phrase-off-vocabulary"]
    assert found and found[0].severity == "WARN", [str(f) for f in validate(text, _ctx())]
    assert "the shot cuts to" in found[0].msg, "the message has to name the words that satisfy it"
    assert "[Shot 2]" in found[0].msg


def test_a_near_miss_synonym_does_not_count():
    """"the framing changes and ..." appeared six times, and "the scene cuts to" once. The point of a
    closed vocabulary is the trained token, not a synonym for it."""
    for opening in ("the framing changes and the crowd fills the frame",
                    "the scene cuts to a wide of the market",
                    "the whip-pan resolves sharply onto the stall"):
        text = _doc(f"{SHOT1} [Shot 2] At 00:06.000, {opening}. The camera holds a static shot.")
        assert [f for f in validate(text, _ctx()) if f.rule == "P7-cut-phrase-off-vocabulary"], \
            opening


def test_all_five_of_the_guides_phrases_satisfy_it():
    for phrase in ("the camera cuts to", "the shot cuts to", "the shot transitions to",
                   "the shot changes to", "the shot switches to"):
        text = _doc(f"{SHOT1} [Shot 2] At 00:06.000, {phrase} a wide of the market waking up. "
                    "The camera holds a static shot.")
        found = [f for f in validate(text, _ctx()) if f.rule == "P7-cut-phrase-off-vocabulary"]
        assert not found, (phrase, [str(f) for f in found])


def test_a_requested_transition_satisfies_it_too():
    """base-en.txt 4.2: "When explicitly requested by the user, cross-dissolve, fade, or wipe may
    also be used." A rule that only knew the five would reject the three."""
    for phrase in ("a cross-dissolve carries the frame into", "the shot fades to",
                   "a slow wipe reveals"):
        text = _doc(f"{SHOT1} [Shot 2] At 00:06.000, {phrase} the empty stall. The camera holds a "
                    "static shot.")
        assert not [f for f in validate(text, _ctx())
                    if f.rule == "P7-cut-phrase-off-vocabulary"], phrase


def test_the_first_shot_is_never_asked_for_a_cut_phrase():
    """[Shot 1] is not a cut into anything, and it carries no timestamp."""
    assert not [f for f in validate(_doc(SHOT1), _ctx())
                if f.rule == "P7-cut-phrase-off-vocabulary"]


def test_it_is_a_warning_and_not_an_error():
    """Deliberate, and the reason is a control. `shipped_repeated_shot.txt` is a MUST PASS on
    legality: a human rejected the prose on taste and the validator's job is the decidable class.
    Its [Shot 2] opens "<Subject 1> strides forward down the stone corridor" with no cut phrase, so
    an ERROR here would turn a taste judgement into a hard failure and, in the fix loop, would send
    a legitimate edit back to be rewritten. The phrase is a distribution nicety, not a binding
    pointer, and a wrong ERROR costs the whole written brief."""
    text = (GOLDEN / "shipped_repeated_shot.txt").read_text(encoding="utf-8")
    found = validate(text, Context(n_pictures=2, duration_s=8.0))
    assert not [f for f in found if f.severity == "ERROR"], [str(f) for f in found]
    assert "P7-cut-phrase-off-vocabulary" in {f.rule for f in found}, \
        "the drift is still reported, just not as a gate"


def test_the_published_examples_all_carry_a_cut_phrase():
    """Every worked example in both guides does, which is what says the rule belongs at all."""
    for name, ctx in (("t2va.ir.txt", Context(mode="t2va", n_pictures=0, duration_s=10.125)),
                      ("official_ref2va_example.txt",
                       Context(mode="ref2va", n_pictures=4, n_videos=2, n_audios=1))):
        found = [f for f in validate((GOLDEN / name).read_text(encoding="utf-8"), ctx)
                 if f.rule == "P7-cut-phrase-off-vocabulary"]
        assert not found, (name, [str(f) for f in found])


# ---------------------------------------------------------------- amplitude and speed

def test_an_off_list_speed_in_the_specs_own_idiom_is_an_error():
    """`out/M5-dialogue-verbatim--s7.json`, verbatim. base-en.txt 4.3 closes the speed dimension to
    `at slow speed` and `at fast speed`, and says medium amplitude and normal speed are omitted
    rather than written."""
    text = _doc("[Shot 1] Live-action, cinematic, the vendor turns to the queue. The camera pushes "
                "in with small amplitude at normal speed as he calls out.")
    errs = [f for f in validate(text, _ctx()) if f.severity == "ERROR"]
    assert [f.rule for f in errs] == ["P8-camera-modifier-off-vocabulary"], [str(f) for f in errs]
    assert "normal" in errs[0].msg and "at slow speed" in errs[0].msg


def test_an_off_list_amplitude_is_an_error():
    text = _doc("[Shot 1] Live-action, cinematic, the vendor turns. The camera pushes in with "
                "moderate amplitude at slow speed.")
    errs = {f.rule for f in validate(text, _ctx()) if f.severity == "ERROR"}
    assert "P8-camera-modifier-off-vocabulary" in errs, errs


def test_an_off_list_speed_attached_to_a_camera_move_is_an_error():
    """`out/RM-ref2va-1img--s205.json`: "The camera tracks alongside <Subject 1> at a low angle,
    moving at high speed to match the car's acceleration." No amplitude in sight, and the value is
    still modifying the camera."""
    text = _doc("[Shot 1] Live-action, cinematic, the camera tracks alongside the car at a low "
                "angle, moving at high speed to match its acceleration.")
    errs = {f.rule for f in validate(text, _ctx()) if f.severity == "ERROR"}
    assert "P8-camera-modifier-off-vocabulary" in errs, errs


def test_a_subject_moving_at_high_speed_is_not_a_camera_value():
    """The false positive this rule is shaped around. `out/M6-singing--s203.json`: "As the train
    rushes past her at high speed, creating a blur of motion and light, she continues her
    performance without breaking eye contact with the camera." The sentence mentions the camera and
    the value belongs to the train, so a sentence-wide rule would reject correct prose. The prior
    measurement counted this as camera drift; it is not."""
    text = _doc("[Shot 1] Live-action, cinematic, the busker sings in the tunnel. As the train "
                "rushes past her at high speed, creating a blur of light, she continues without "
                "breaking eye contact with the camera. The camera holds a static shot.")
    assert not [f for f in validate(text, _ctx()) if f.severity == "ERROR"], \
        [str(f) for f in validate(text, _ctx())]


def test_the_legal_values_still_pass():
    for amp, speed in (("small", "slow"), ("large", "fast"), ("small", "fast")):
        text = _doc(f"[Shot 1] Live-action, cinematic, the vendor turns. The camera pans right with "
                    f"{amp} amplitude at {speed} speed.")
        assert not [f for f in validate(text, _ctx()) if f.severity == "ERROR"], (amp, speed)


def test_omitting_amplitude_and_speed_entirely_is_not_an_error():
    """The guide says to add them "only when they are meaningful". Absence is a note (P5b, INFO),
    never a defect."""
    text = _doc("[Shot 1] Live-action, cinematic, the vendor turns. The camera pushes in toward "
                "the crate of ice.")
    assert not [f for f in validate(text, _ctx()) if f.severity == "ERROR"]


def test_the_goldens_are_clean_of_both_rules():
    for name, ctx in (("official_fl2va_example.txt",
                       Context(mode="fl2va", n_pictures=2, duration_s=8.0)),
                      ("shipped_repeated_shot.txt", Context(n_pictures=2, duration_s=8.0)),
                      ("official_ref2va_example.txt",
                       Context(mode="ref2va", n_pictures=4, n_videos=2, n_audios=1))):
        found = [f for f in validate((GOLDEN / name).read_text(encoding="utf-8"), ctx)
                 if f.rule == "P8-camera-modifier-off-vocabulary"]
        assert not found, (name, [str(f) for f in found])


# ---------------------------------------------------------------- stated where it is written

def test_both_composer_prompts_state_the_cut_vocabulary():
    """The validator reports the drift; the prompt is what reduces it. A vocabulary stated only in
    the middle of a copied specification is the shape that produced 34 misses."""
    prompts = Path(__file__).resolve().parents[1] / "h3ir/prompts"
    for name in ("compose.v2.txt", "compose_base.v1.txt"):
        tail = (prompts / name).read_text(encoding="utf-8").split("=== END SPECIFICATION ===")[-1]
        assert "the shot cuts to" in tail, name
        assert "the shot switches to" in tail, name
