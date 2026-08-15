"""The creativity dial: proportionality is part of the bar, not a preference.

"If I ask for simple, I want simple, if I say go crazy, I want crazy."

Two failure modes, both real and symmetrical: over-directing a plain ask, and under-directing an
ambitious one. The dial is an explicit input rather than something read out of the request, so these
tests are about what each POSITION licenses -- never about what the request "seems to want".

The guarantees that must survive the feature are tested here too, because they are exactly what a
future change to this file would break: shot count is never a finding at any setting, and an explicit
prohibition outranks every position.
"""
from __future__ import annotations

import pytest

from h3ir.creativity import (ONSCREEN_TEXT, SCORE, SPEECH, Creativity, Scope, build, mentions,
                             parse, prohibitions)
from h3ir.validate import Context, validate


def _brief(desc: str, *, sound="Footsteps echo on stone throughout.", music="N/A") -> str:
    return (f"integrated_multimodal_description:\n{desc}\n\n"
            f"overall_soundscape:\n{sound}\n\nnon_diegetic_music:\n{music}\n")


PLAIN_SHOT = ("[Shot 1] Live-action, cinematic, a wide shot as the man walks forward down the stone "
              "corridor while the camera pushes in with small amplitude at slow speed.")

# The same shot with a COMMITTED camera. `bold` and `extreme` now require at least one maximal value
# (Q3) and `extreme` forbids timid ones (Q4), so a fixture used at those settings has to satisfy the
# magnitude checks -- otherwise every assertion about something else fails for the wrong reason.
COMMITTED_SHOT = ("[Shot 1] Live-action, cinematic, a wide shot as the man strides forward down the "
                  "stone corridor while the camera pushes in with large amplitude at fast speed.")

# The owner's actual plain request, used verbatim so the tests are about a real ask.
PLAIN_REQUEST = ("the man walks forward down the stone corridor toward the camera, torchlight "
                 "flickering across the walls. Cinematic.")


def _rules(text: str, scope: Scope, sev: str = "ERROR") -> set[str]:
    return {f.rule for f in validate(text, Context(mode="t2va", duration_s=8.0, scope=scope))
            if f.severity == sev}


# ---------------------------------------------------------------- the dial itself

def test_the_positions_license_progressively_more():
    r = build(PLAIN_REQUEST, level="restrained")
    b = build(PLAIN_REQUEST, level="balanced")
    o = build(PLAIN_REQUEST, level="bold")
    assert r.licensed == frozenset()
    assert b.licensed == frozenset({SCORE})
    assert o.licensed == frozenset({SCORE, SPEECH, ONSCREEN_TEXT})
    assert r.licensed < b.licensed < o.licensed, "the positions must be nested, not merely different"


def test_balanced_is_the_default_and_an_unknown_word_falls_back_to_it():
    """A caller may be an agent that has never read the source. An unrecognised setting must not
    fail a render -- the compiler records what it actually used."""
    assert parse(None) is Creativity.BALANCED
    assert parse("") is Creativity.BALANCED
    assert parse("cinematic-max") is Creativity.BALANCED
    assert parse("BOLD") is Creativity.BOLD
    assert parse(Creativity.RESTRAINED) is Creativity.RESTRAINED


# ---------------------------------------------------------------- proportionality, enforced

def test_a_score_on_a_plain_request_is_an_error_at_restrained():
    text = _brief(PLAIN_SHOT, music="A slow synth pad swells under the footsteps.")
    assert "Q2-unlicensed-addition" in _rules(text, build(PLAIN_REQUEST, level="restrained"))


def test_the_same_score_is_fine_at_balanced():
    text = _brief(PLAIN_SHOT, music="A slow synth pad swells under the footsteps.")
    assert not _rules(text, build(PLAIN_REQUEST, level="balanced"))


def test_invented_speech_is_an_error_at_balanced_and_licensed_at_bold():
    """The axis in one pair. Nobody supplied these words, so at balanced they came from nowhere;
    at bold that is the point."""
    text = _brief(COMMITTED_SHOT + ' The man (S1) says: <d>[English] Almost there.</d>')
    assert "Q2-unlicensed-addition" in _rules(text, build(PLAIN_REQUEST, level="balanced"))
    assert not _rules(text, build(PLAIN_REQUEST, level="bold"))


def test_speech_the_caller_supplied_is_obedience_not_addition():
    text = _brief(PLAIN_SHOT + ' The man (S1) says: <d>[English] Almost there.</d>')
    scope = build(PLAIN_REQUEST, level="restrained", has_dialogue=True)
    assert not _rules(text, scope), "the caller's own line cannot be an unlicensed addition"


def test_speech_the_request_asks_for_in_prose_counts_as_requested():
    """"he says something" is a request for speech even with no verbatim line supplied. Stripping it
    would be as wrong as adding one unasked, so the detector abstains in the safe direction."""
    scope = build("the man walks down the corridor and says something to the camera",
                  level="restrained")
    assert SPEECH in scope.requested
    text = _brief(PLAIN_SHOT + ' The man (S1) says: <d>[English] Almost there.</d>')
    assert not _rules(text, scope)


def test_onscreen_text_is_bold_only():
    text = _brief(COMMITTED_SHOT + ' A sign on the wall reads "LEVEL 3".')
    assert "Q2-unlicensed-addition" in _rules(text, build(PLAIN_REQUEST, level="balanced"))
    assert not _rules(text, build(PLAIN_REQUEST, level="bold"))


# ---------------------------------------------------------------- prohibitions outrank the dial

@pytest.mark.parametrize("request_text,element", [
    ("the man walks down the corridor. No dialogue. No background music.", SPEECH),
    ("the man walks down the corridor. No dialogue. No background music.", SCORE),
    ("a quiet walk down a corridor, without any music", SCORE),
    ("he walks the length of the hall, nobody speaks", SPEECH),
    ("a slow push down the corridor, no on-screen text", ONSCREEN_TEXT),
])
def test_an_explicit_prohibition_is_read_from_the_request(request_text, element):
    assert element in build(request_text, level="bold").forbidden


def test_bold_does_not_license_what_the_request_forbade():
    """The hard case, and the one the failure is likeliest to run in now that bold exists."""
    scope = build("the man walks down the corridor. No dialogue. No background music.", level="bold")
    # Only what was forbidden loses its licence. This request says nothing about on-screen text, so
    # bold still licenses that -- a prohibition is surgical, not a switch back to restrained.
    assert not scope.permits(SPEECH) and not scope.permits(SCORE)
    assert scope.permits(ONSCREEN_TEXT)
    text = _brief(PLAIN_SHOT + ' The man (S1) says: <d>[English] Almost there.</d>',
                  music="A slow synth pad swells.")
    fired = _rules(text, scope)
    assert "Q1-forbidden-element-present" in fired
    assert "Q2-unlicensed-addition" not in fired, "a forbidden element gets the clearer rule"


def test_a_forbidden_element_is_removed_from_the_LICENCE_not_only_from_permits():
    """`permits()` checks prohibitions on its own, so the validator would reject a forbidden element
    even if `licensed` were wrong -- and that is the trap. `licensed` is what the WRITER is told it
    may add. If the two disagree, the model is invited to write something the validator then rejects,
    which burns a fix round on a contradiction we authored."""
    scope = build("he walks the corridor. No background music.", level="bold")
    assert SCORE not in scope.licensed
    assert SCORE not in scope.note().split("may add:")[-1]
    assert "score" not in scope.brief_instruction().lower().split("rules these out")[0] \
        .split("Creativity: BOLD".lower())[-1], "bold's blurb must not offer a forbidden score"


def test_the_silent_flag_and_the_phrase_agree():
    assert SCORE in build(PLAIN_REQUEST, silent=True).forbidden
    assert SCORE in build(PLAIN_REQUEST + " No music.").forbidden


def test_a_prohibition_beats_a_mention_of_the_same_word():
    """"No background music" contains the word "music". Reading that as a request for a score
    inverts the instruction, so precedence is not optional."""
    scope = build("the man walks down the corridor. No background music.", level="bold")
    assert SCORE in scope.forbidden
    assert SCORE not in scope.requested
    assert not scope.permits(SCORE)


def test_supplied_content_beats_a_stale_prohibition():
    """A caller who fills in a dialogue line AND writes "no dialogue" has contradicted themselves.
    The concrete line is the better evidence; refusing to render it would lose real input."""
    scope = build("he walks down the corridor. No dialogue.", level="restrained", has_dialogue=True)
    assert SPEECH not in scope.forbidden
    assert scope.permits(SPEECH)


def test_an_adjective_is_not_a_prohibition():
    """The same reasoning that says a loose adjective cannot override a reference plate says it
    cannot forbid a section. "Quiet" is a mood, not an instruction to leave music out."""
    for word in ("a quiet walk down the corridor", "an understated, minimal scene",
                 "a subdued corridor walk"):
        assert not build(word, level="balanced").forbidden, word


# ---------------------------------------------------------------- what the dial must NEVER do

def test_shot_count_is_not_a_finding_at_any_setting():
    """The dial governs ADDED CONTENT, not effort. One shot for an eight-second walk is legitimate
    at bold; four shots are legitimate at restrained. If this ever fails, shot count has re-entered
    the validator through the dial."""
    one = _brief(COMMITTED_SHOT)
    four = _brief(COMMITTED_SHOT
                  + " [Shot 2] At 00:02.000, a close framing holds a static shot on his hands."
                  + " [Shot 3] At 00:04.000, a wide shot trucks left past a burning sconce."
                  + " [Shot 4] At 00:06.000, a close shot tilts up to the vaulted ceiling.")
    for level in ("restrained", "balanced", "bold"):
        scope = build(PLAIN_REQUEST, level=level)
        for text, name in ((one, "one shot"), (four, "four shots")):
            fired = _rules(text, scope)
            assert not [r for r in fired if r.startswith("Q")], (level, name, fired)


def test_a_missing_camera_is_still_an_error_at_restrained():
    """Restrained does not mean under-specified. H3 requires a stated camera at every setting, and
    `Static Shot` is in the vocabulary, so there is always something to say."""
    text = _brief("[Shot 1] Live-action, cinematic, the man walks forward down the stone corridor.")
    assert "P5-camera-no-motion-type" in _rules(text, build(PLAIN_REQUEST, level="restrained"))


def test_no_dialogue_is_never_itself_a_finding():
    """A brief with no speech is complete. The absence of an addition can never be a defect --
    that is the under-direction half of the failure, and it is the owner's call, not a rule."""
    text = _brief(COMMITTED_SHOT)
    for level in ("restrained", "balanced", "bold", "extreme"):
        assert not _rules(text, build(PLAIN_REQUEST, level=level))


def test_an_absent_scope_makes_the_whole_family_abstain():
    """Every caller that predates the dial -- the golden controls, the independent validator -- passes
    no scope, and must see no Q findings whatever the brief contains."""
    text = _brief(PLAIN_SHOT + ' He (S1) says: <d>[English] Almost there.</d>',
                  music="A synth pad swells.")
    fired = {f.rule for f in validate(text, Context(mode="t2va", duration_s=8.0))}
    assert not [r for r in fired if r.startswith("Q")], fired


# ---------------------------------------------------------------- completeness

def test_an_empty_section_is_an_error():
    """"Complete" is part of the bar: everything H3 expects, populated meaningfully. An empty
    overall_soundscape validated clean before this rule, and H3 generates audio."""
    text = _brief(PLAIN_SHOT, sound="")
    assert "S9-section-empty" in _rules(text, build(PLAIN_REQUEST, level="balanced"))


def test_na_is_a_legitimate_score_and_not_an_empty_section():
    """N/A is the value the spec DEFINES for a scoreless video. Only non_diegetic_music may use it."""
    text = _brief(PLAIN_SHOT, music="N/A")
    fired = _rules(text, build(PLAIN_REQUEST, level="balanced"))
    assert "S9-section-empty" not in fired and not fired


# ---------------------------------------------------------------- what the writer is told

def test_the_instruction_states_the_licence_without_naming_a_quota():
    """A number of shots or camera moves in this text would be the taste-as-mechanics trap one layer
    up from the validator, where nothing would catch it."""
    for level in ("restrained", "balanced", "bold"):
        text = build(PLAIN_REQUEST, level=level).brief_instruction().lower()
        assert level in text
        # Narrowed from a blanket ban on "at least": bold now legitimately says "At least one move
        # states `with large amplitude`", a camera VALUE commitment rather than a shot quota. The ban
        # was always about counts of shots and cuts.
        for banned in ("two shots", "three shots", "at least two", "at least one shot",
                       "more shots", "another shot", "add a cut"):
            assert banned not in text, (level, banned)


def test_the_instruction_states_prohibitions_absolutely():
    text = build("he walks the corridor. No dialogue. No music.", level="bold").brief_instruction()
    assert "no setting overrides" in text.lower()
    assert SPEECH in text and SCORE in text


def test_the_note_records_what_the_dial_decided():
    note = build("he walks the corridor. No music.", level="bold").note()
    assert "bold" in note and "forbidden" in note and "may add" in note
    assert "nothing beyond the request" not in note, "bold still licenses speech here"
    assert "nothing beyond the request" in build(PLAIN_REQUEST, level="restrained").note()


def test_the_detectors_are_independent_of_each_other():
    assert prohibitions("no dialogue") == (SPEECH,)
    assert prohibitions("no soundtrack") == (SCORE,)
    assert mentions("a soaring orchestral theme") == (SCORE,)
    assert mentions("he whispers to her") == (SPEECH,)
    assert prohibitions("the man walks down the corridor") == ()
    assert mentions("the man walks down the corridor") == ()


# ---------------------------------------------------------------- the metric reads what ships

def test_the_restatement_metric_reads_the_shipped_text_not_the_plan():
    """In the write-first path the plan is the deterministic DRAFT's -- the model's prose never goes
    back into plan.shots[].body -- so a metric reading the plan measured an artifact that was thrown
    away. It reported restatement 1.00 on written briefs whose shots are visibly different."""
    from h3ir.evalloop.score import _shot_bodies

    desc = ("Live-action, cinematic.\n"
            "[Shot 1] A wide shot as the knight rides low over the burning field.\n"
            "[Shot 2] At 00:04.000, a close framing holds static on the dragon's eye.")
    bodies = _shot_bodies(desc)
    assert len(bodies) == 2
    assert "knight" in bodies[0] and "knight" not in bodies[1]
    assert "dragon" in bodies[1]
    assert not _shot_bodies("no shot markers here at all")


def test_shots_and_cuts_describe_the_same_artifact():
    """n_shots read the plan while n_timed_cuts read the text, so a run could report 4 shots and 0
    cuts with no validator errors -- impossible, since T4 requires a cut time on every shot after the
    first. Two fields were describing two different artifacts."""
    from h3ir.evalloop.score import _shot_bodies

    one = "Live-action.\n[Shot 1] A wide shot as the keeper climbs, camera pushing in."
    two = one + " [Shot 2] At 00:04.000, a close shot holds static on the lamp."
    assert len(_shot_bodies(one)) == 1, "one shot in the text is one shot"
    assert len(_shot_bodies(two)) == 2
    # a shipped brief with N shots carries N-1 timestamps; the two counts must move together
    import re
    for text in (one, two):
        assert len(re.findall(r"At \d{2}:\d{2}\.\d{3}", text)) == len(_shot_bodies(text)) - 1


# ---------------------------------------------------------------- what may gate a run

def test_length_can_never_gate_a_run():
    """`word_ratio` measures distance from `plan.total_word_target()` -- a number the writer is never
    given in the write-first path. In the mode being measured it is distance from a target that does
    not exist in the pipeline. And a length gate is the class the audit purged."""
    from h3ir.evalloop.score import Aggregate, UNGATED, compare

    assert "word_ratio" in UNGATED
    base = Aggregate(n=6, word_ratio=1.232, errors=0.0)
    cand = Aggregate(n=6, word_ratio=0.400, errors=0.0)
    regressed, lines = compare(base, cand, {"word_ratio", "errors"})
    assert not regressed, lines
    assert any("word_ratio" in ln for ln in lines), "it must still be REPORTED"


def test_the_warning_count_can_never_gate_a_run():
    """A single count that sums "this brief is 143 words" with a real content finding cannot be read:
    a move in it never says which of the two moved. The rules stay in warn_rules."""
    from h3ir.evalloop.score import Aggregate, UNGATED, compare

    assert "warnings" in UNGATED
    regressed, lines = compare(Aggregate(n=6, warnings=0.167), Aggregate(n=6, warnings=3.0),
                               {"warnings"})
    assert not regressed, lines
    assert any("warnings" in ln for ln in lines)


def test_a_validator_error_still_blocks():
    """Ungating trends must not ungate faults. An ERROR is a decidable defect and always blocks."""
    from h3ir.evalloop.score import Aggregate, compare

    regressed, _ = compare(Aggregate(n=6, errors=0.0), Aggregate(n=6, errors=1.0), {"errors"})
    assert regressed, "errors must still gate"


def test_the_fallback_event_is_not_counted_twice():
    """X13-written-rejected IS the fallback, and `fallback_rate` already carries it. Counting it as a
    warning too meant one event moved two numbers."""
    from h3ir.evalloop.score import _countable_warnings
    from h3ir.models import Finding

    class _Doc:
        warnings = [Finding("X13-written-rejected", "WARN", "the written brief was rejected"),
                    Finding("R15-wardrobe-not-restated", "WARN", "garments not restated")]

    kept = _countable_warnings(_Doc())
    assert [f.rule for f in kept] == ["R15-wardrobe-not-restated"]


# ---------------------------------------------------------------- extreme: magnitude, not addition

def test_extreme_licenses_nothing_beyond_bold():
    """Not an omission. There are three addable elements and bold has all of them, so a fourth
    position could only be a longer list if the list grew -- and growing it means inventing events or
    facts about the caller's material, which was proposed and rejected outright."""
    bold = build(PLAIN_REQUEST, level="bold")
    extreme = build(PLAIN_REQUEST, level="extreme")
    assert extreme.licensed == bold.licensed
    assert extreme.magnitude == "maximal" and bold.magnitude == "assertive"


def test_the_magnitude_axis_is_ordered_across_all_four():
    order = [build(PLAIN_REQUEST, level=lv).magnitude
             for lv in ("restrained", "balanced", "bold", "extreme")]
    assert order == ["plain", "measured", "assertive", "maximal"]
    assert len(set(order)) == 4, "four positions must mean four distinct magnitudes"


def test_extreme_is_a_real_setting_not_an_alias():
    assert parse("extreme") is Creativity.EXTREME
    assert parse("EXTREME") is Creativity.EXTREME


def test_a_brief_at_extreme_that_states_no_maximal_camera_value_fails():
    """The one position whose own setting defines what correct means, which is why it can be checked
    at all: `extreme` asks for the far end of a CLOSED vocabulary, so "is this at the far end" is
    countable. A director who wanted a slow push would have asked for bold."""
    timid = _brief("[Shot 1] Live-action, a wide shot as the man walks forward while the camera "
                   "pushes in with small amplitude at slow speed.")
    assert "Q3-extreme-not-honoured" in _rules(timid, build(PLAIN_REQUEST, level="extreme"))


def test_silence_about_amplitude_also_fails_at_extreme():
    """The guide omits amplitude and speed to MEAN medium and normal, so stating neither plays the
    shot at the middle -- the opposite of the setting."""
    silent_camera = _brief("[Shot 1] Live-action, a wide shot as the man walks forward while the "
                           "camera pushes in toward him.")
    assert "Q3-extreme-not-honoured" in _rules(silent_camera,
                                                build(PLAIN_REQUEST, level="extreme"))


def test_a_maximal_brief_passes_at_extreme():
    maxed = _brief("[Shot 1] Live-action, an extreme close framing as the man strides forward while "
                   "the camera pushes in with large amplitude at fast speed, hard torchlight "
                   "raking across him.")
    assert not _rules(maxed, build(PLAIN_REQUEST, level="extreme"))


def test_the_extreme_check_applies_at_no_other_position():
    """A slow, small push is exactly right at restrained and defensible at bold. Only `extreme`
    ruled it out, and only because that is what the caller asked for."""
    timid = _brief("[Shot 1] Live-action, a wide shot as the man walks forward while the camera "
                   "pushes in with small amplitude at slow speed.")
    for level in ("restrained", "balanced", "bold"):
        assert "Q3-extreme-not-honoured" not in _rules(timid, build(PLAIN_REQUEST, level=level))


def test_extreme_still_obeys_a_prohibition():
    """The highest-risk position for exactly this. No setting overrides an explicit prohibition."""
    scope = build("he walks the corridor with large amplitude. No dialogue. No background music.",
                  level="extreme")
    assert not scope.permits(SPEECH) and not scope.permits(SCORE)
    text = _brief("[Shot 1] Live-action, a wide shot as the camera pushes in with large amplitude at "
                  "fast speed. He (S1) says: <d>[English] Almost there.</d>",
                  music="A synth pad swells.")
    fired = _rules(text, scope)
    assert "Q1-forbidden-element-present" in fired


def test_extreme_never_governs_shot_count():
    """The line: magnitude governs VALUES, never COUNTS. "Where it is choosing between N and N+1
    shots, take N+1" was declined -- the moment a setting licenses more cuts it is a rule about shot
    count again, one layer above the validator where nothing catches it."""
    scope = build(PLAIN_REQUEST, level="extreme")
    one = _brief("[Shot 1] Live-action, an extreme close framing as the camera pushes in with large "
                 "amplitude at fast speed.")
    assert not _rules(one, scope), "one shot is legitimate at extreme"
    instruction = scope.brief_instruction().lower()
    for banned in ("more shots", "another shot", "take n+1", "add a cut", "at least two"):
        assert banned not in instruction, banned


def test_the_extreme_instruction_says_magnitude_not_invention():
    text = build(PLAIN_REQUEST, level="extreme").brief_instruction()
    assert "large amplitude" in text and "fast speed" in text
    assert "not adding events" in text.lower()
    assert "magnitude, not invention" in text.lower()


def test_the_deterministic_floor_satisfies_every_setting_the_product_offers():
    """The draft is the product floor, not a degraded mode. At `extreme` its small/slow rotation
    tripped Q3, so the draft failed its own validator and the compile RAISED -- a user-facing setting
    turned into a crash. The raise was right; exempting the draft would have been wrong, because a
    floor that quietly ignores the setting is the silent degradation this service refuses."""
    from h3ir.draft import deterministic_draft
    from h3ir.models import Brief, Mode
    from h3ir.plan import ProfileOptions
    from h3ir.render import render_ir

    for level in ("restrained", "balanced", "bold", "extreme"):
        b = Brief(intent="the man walks down the stone corridor", seconds=8.0, creativity=level)
        plan = deterministic_draft(b, Mode.T2VA, {})
        rendered = render_ir(plan, ProfileOptions(name="standard"))
        errs = [f for f in validate(rendered.prompt,
                                   Context(mode="t2va", duration_s=8.0,
                                           scope=build(b.intent, level=level)))
                if f.severity == "ERROR"]
        assert not errs, (level, [str(f) for f in errs])


def test_the_maximal_rotation_drops_the_static_shot():
    """amplitude and speed are meaningless for a camera that does not move, so inventing values for
    `Static Shot` would be on-vocabulary nonsense -- and a held frame is not the boldest option
    available, which is what `maximal` asks for."""
    from h3ir.draft import draft_camera

    plain = draft_camera("plain")
    maximal = draft_camera("maximal")
    assert any(c["type"] == "Static Shot" for c in plain)
    assert not any(c["type"] == "Static Shot" for c in maximal)
    assert all(c["amplitude"] == "large" and c["speed"] == "fast" for c in maximal)
    # `assertive` keeps its own rotation even though nothing CHECKS the camera at bold: a fallback
    # that ignores the setting the caller asked for is silent degradation, and enforcement is not the
    # reason the floor is faithful.
    assertive = draft_camera("assertive")
    assert assertive != plain and assertive != maximal, "three rotations for three magnitudes"
    assert all(c["amplitude"] == "large" for c in assertive if c["type"] != "Static Shot")
    assert not any(c["speed"] == "fast" for c in assertive), "assertive commits on ONE dimension"
    assert draft_camera("measured") == plain, "plain and measured share one; no instruction to lean on"


def test_a_stored_run_carries_its_provenance():
    """A baseline is a reference point, so it has to say which pipeline it references. `commit` was
    on the dataclass but not in `Run.dict()`, and `note` was a Run field assigned AFTER run_suite had
    already saved -- so the baseline written to record provenance recorded commit=None and an empty
    note. Both were reported as done without being looked at."""
    from h3ir.evalloop.suite import Run, RunConfig, _commit

    d = Run(config=RunConfig(label="x", note="supersedes the composed path"), commit="abc1234").dict()
    assert d["commit"] == "abc1234"
    assert d["config"]["note"] == "supersedes the composed path"
    assert d["config"]["compose_prompt"] is None and d["config"]["omit"] == ()
    assert _commit(), "the repo's HEAD must be readable, or a baseline cannot name its pipeline"


# ---------------------------------------------------------------- bold is deliberately unenforced

def test_bold_is_not_enforced_and_must_not_become_so():
    """The dial is asymmetric ON PURPOSE and this is the guard on it. A check for `bold` was built and
    removed on the owner's narrowing: "bold just means if a little nudge can do it, don't mechanically
    enforce it". A brief at bold with a timid camera is a legitimate outcome — the model declined the
    nudge, which is allowed.

    If this test ever fails, someone re-added the check. The lever for a nudge that lands too rarely is
    the WORDING, never a rule."""
    timid = _brief(PLAIN_SHOT)          # small amplitude at slow speed
    for level in ("restrained", "balanced", "bold"):
        fired = _rules(timid, build(PLAIN_REQUEST, level=level))
        assert not fired, (level, fired)
    # and the top is still enforced, so the asymmetry is real rather than an absence of rules
    assert "Q3-extreme-not-honoured" in _rules(timid, build(PLAIN_REQUEST, level="extreme"))


def test_only_the_top_position_holds_the_camera_to_anything():
    from h3ir.creativity import COMMITS_CAMERA, MAGNITUDE

    commits = {lv.value for lv in Creativity if MAGNITUDE[lv] in COMMITS_CAMERA}
    assert commits == {"extreme"}, commits


def test_no_position_checks_the_camera_except_extreme_and_extreme_only_requires_a_reach():
    """The two-part fact this dial rests on, and the one worth locking:

      1. No position checks the camera except `extreme`.
      2. `extreme` REQUIRES a maximal value and does not FORBID a quiet one.

    The owner was asked twice — once on an overstated premise of mine, once on the corrected one — and
    chose contrast-allowed both times: "hold, hold, then hit is how a lot of real direction works". A
    setting that forbids the hold cannot express the hit. If this test fails, someone re-added a
    uniformity rule."""
    mixed = _brief(
        "[Shot 1] Live-action, a wide shot as the camera pushes in with large amplitude at fast "
        "speed. [Shot 2] At 00:04.000, a close shot holds as the camera trucks left with small "
        "amplitude.")
    for level in ("restrained", "balanced", "bold", "extreme"):
        assert not _rules(mixed, build(PLAIN_REQUEST, level=level)), level

    # and the reach is still enforced: quiet ONLY, with nothing committed anywhere, still fails
    all_quiet = _brief(
        "[Shot 1] Live-action, a wide shot as the camera pushes in with small amplitude at slow speed.")
    assert "Q3-extreme-not-honoured" in _rules(all_quiet, build(PLAIN_REQUEST, level="extreme"))


def test_bolds_nudge_is_concrete_without_being_a_requirement():
    """The whole scope of the work after the narrowing: a more concrete nudge, not a softer adjective,
    and not an obligation. It names the vocabulary and explicitly permits declining it."""
    text = build(PLAIN_REQUEST, level="bold").brief_instruction()
    assert "with large amplitude" in text and "at fast speed" in text, "name the words for it"
    assert "if a nudge would carry the shot" in text, "invite, do not require"
    assert "a quiet camera is the right answer" in text, "and say declining is allowed"
    for demanded in ("must", "COMMIT", "at least one"):
        assert demanded not in text, demanded
    # extreme still demands, so the two are not the same instruction
    assert "NOWHERE" in build(PLAIN_REQUEST, level="extreme").brief_instruction()


def test_bold_does_not_oblige_the_model_to_spend_its_content_licence():
    """Also a refusal, and it survives the narrowing unchanged. Making bold REQUIRE a spoken line or
    on-screen text would turn the dial from permitting content into pushing it — what the owner
    rejected when he rejected "hallucination extreme" — and would make bold worse on a plain request."""
    spare = _brief(PLAIN_SHOT)          # no speech, no text, no score, timid camera
    assert not _rules(spare, build(PLAIN_REQUEST, level="bold"))
    assert not [r for r in _rules(spare, build(PLAIN_REQUEST, level="bold"), sev="WARN")
                if r.startswith("Q")], "not even as a warning"


# ---------------------------------------------------------------- the caller's own quotes
# Measured 2026-08-15, matrix rows 8, 9, 11 and 13 on the tray surface: four briefs died on
# CompilerInvariantError because the deterministic draft echoed the request's own quoted words and
# Q2 read them as added lettering. @speaks resolution leaves spoken lines quoted in the sentence BY
# DESIGN, and quoted sign text in the sentence is the node's documented mechanism for lettering.
# What the caller's request already contains cannot be an addition.

def test_quoted_lettering_in_the_request_is_supplied_not_added():
    """Row 13's crash: the sign text is in the request, quoted; the brief rendering it is
    obedience."""
    scope = build('a hand hangs a wooden sign on the shop door that reads "BACK AT NOON" and '
                  'straightens it', level="balanced")
    assert ONSCREEN_TEXT in scope.requested
    text = _brief(PLAIN_SHOT + ' The wooden sign reads "BACK AT NOON".')
    assert "Q2-unlicensed-addition" not in _rules(text, scope)


def test_quotes_that_are_the_dialogue_lines_do_not_license_lettering():
    """The control on the fix above: a request whose only quotes are its spoken lines has supplied
    speech, not lettering — the two channels must not blur."""
    scope = build('the mechanic says "It was never the engine." and turns away',
                  level="balanced", has_dialogue=True,
                  dialogue_texts=("It was never the engine.",))
    assert ONSCREEN_TEXT not in scope.requested


def test_a_dialogue_line_echoed_in_prose_is_speech_not_lettering():
    """Rows 8, 9, 11's crash: the draft echoes the sentence, the sentence quotes the line, and the
    same line sits in its <d> block. The echo is the caller's own words twice, not lettering."""
    line = "It was never the engine."
    text = _brief(PLAIN_SHOT + f' The mechanic says "{line}" — she (S1) says: '
                  f'<d>[English] {line}</d>')
    ctx = Context(mode="t2va", duration_s=8.0, expected_dialogue=(line,),
                  scope=build(PLAIN_REQUEST, level="balanced", has_dialogue=True,
                              dialogue_texts=(line,)))
    fired = {f.rule for f in validate(text, ctx) if f.severity == "ERROR"}
    assert "Q2-unlicensed-addition" not in fired


def test_invented_lettering_still_fails_at_balanced():
    """The rule must survive its own fix: a quoted span that is in neither the request nor the
    dialogue is still an addition."""
    text = _brief(PLAIN_SHOT + ' A neon sign reads "OPEN ALL NIGHT".')
    assert "Q2-unlicensed-addition" in _rules(text, build(PLAIN_REQUEST, level="balanced"))
