"""One spoken line, one cut: `<scenetrans>`, `<cutoff>`, and the line that shipped twice.

base-en.txt 4.4: "When the same line of dialogue or lyrics crosses a cut, use `<scenetrans>` at the
connecting points in both parts and explicitly state that the audio continues across the cut."

The construct is ONE line divided at the cut. What the compiler produced on an explicit request was
the WHOLE line inside `<d>` on both sides, 7 of 7 recorded runs, which as conditioning tells H3 to
speak the line, cut, and speak the whole line again.

That was not the writer being careless. `D4-dialogue-not-verbatim` required the caller's line to
appear inside ONE `<d>` block, so the spec's own construct was an ERROR and the duplication was
clean:

    SPLIT at the cut (base-en 4.4's construct)      ERRORS: ['D4-dialogue-not-verbatim']
    WHOLE line twice (what the compiler emitted)    ERRORS: none

So the fix is in both directions at once: D4 accepts a line divided across consecutive blocks, and
the divided form now has to be marked the way the spec marks it, while the duplicate is the thing
that fails. Every test here hands the validator a document; the reachability half (a natural request
producing the marker at all) is measured against the live service, not asserted here.
"""
from __future__ import annotations

from h3ir.models import Mode
from h3ir.validate import Context, validate

LINE = ("If it turns halfway and stops, the pin is worn, so you change the pin and not the "
        "whole lock.")
HALF_A = "If it turns halfway and stops, the pin is worn,"
HALF_B = "so you change the pin and not the whole lock."

CONTINUITY = "The audio continues seamlessly across the cut."


def _doc(desc: str) -> str:
    return (f"integrated_multimodal_description: {desc}\n\n"
            "overall_soundscape: A brass key scrapes in a vice.\n\n"
            "non_diegetic_music: N/A\n")


def _ctx(**kw) -> Context:
    # 294 frames, the aligned length a 12 s request snaps up to.
    base = dict(mode="t2va", n_pictures=0, duration_s=294 / 24,
                expected_dialogue=(LINE,))
    base.update(kw)
    return Context(**base)


SHOT1 = ("[Shot 1] Live-action, cinematic, the locksmith leans over the vice. The camera pushes in "
         "with small amplitude at slow speed as he (S1) begins to speak: ")
# Deliberately says nothing about continuity, so the continuity check has something to miss: the
# first draft of this fixture opened with "as his voice carries over from the previous shot" and
# satisfied the rule it was meant to fail.
SHOT2 = "[Shot 2] At 00:06.000, the shot cuts to the heavy wooden door of the shop: "


def _split(scenetrans_before: bool = True, scenetrans_after: bool = True,
           continuity: bool = True) -> str:
    tail = " <scenetrans>" if scenetrans_before else ""
    lead = "<scenetrans> " if scenetrans_after else ""
    cont = f" {CONTINUITY}" if continuity else ""
    return _doc(f"{SHOT1}<d>[English] {HALF_A}</d>{tail}{cont}\n"
                f"{SHOT2}{lead}<d>[English] {HALF_B}</d>")


# ---------------------------------------------------------------- the spec's construct is legal

def test_a_line_divided_at_the_cut_is_not_a_verbatim_failure():
    """The exact arm that used to fail. Neither half matches the whole line, so D4 fired on the
    construct base-en.txt 4.4 mandates."""
    found = validate(_split(), _ctx())
    assert "D4-dialogue-not-verbatim" not in {f.rule for f in found}, [str(f) for f in found]
    assert not [f for f in found if f.severity == "ERROR"], [str(f) for f in found]


def test_a_line_still_inside_one_block_is_untouched():
    found = validate(_doc(SHOT1 + f"<d>[English] {LINE}</d>"), _ctx())
    assert not [f for f in found if f.severity == "ERROR"], [str(f) for f in found]


def test_an_altered_line_is_still_rejected_however_it_is_arranged():
    """The relaxation must not become a hole. Splitting is legal; rewording is not, in either half,
    and the concatenation is compared to the caller's words including their punctuation."""
    bad = _split().replace("the pin is worn,", "the pin is worn out,")
    errs = {f.rule for f in validate(bad, _ctx()) if f.severity == "ERROR"}
    assert "D4-dialogue-not-verbatim" in errs, errs


def test_a_dropped_comma_at_the_join_is_still_a_verbatim_failure():
    """base-en.txt 4.4: "Preserve every original word and punctuation mark verbatim". The comma at
    the split point is the caller's."""
    bad = _split().replace("the pin is worn,", "the pin is worn")
    errs = {f.rule for f in validate(bad, _ctx()) if f.severity == "ERROR"}
    assert "D4-dialogue-not-verbatim" in errs, errs


def test_a_missing_line_is_still_an_error():
    errs = {f.rule for f in validate(_doc(SHOT1 + "he works in silence."), _ctx())
            if f.severity == "ERROR"}
    assert "D4-dialogue-not-verbatim" in errs, errs


# ---------------------------------------------------------------- the duplicate is the defect

def test_the_whole_line_on_both_sides_of_the_cut_is_an_error():
    """What shipped 7 of 7 on `X1-scenetrans-explicit`: as conditioning it instructs the model to
    speak the whole line twice."""
    doubled = _doc(f"{SHOT1}<d>[English] {LINE}</d> <scenetrans> {CONTINUITY}\n"
                   f"{SHOT2}<scenetrans> <d>[English] {LINE}</d>")
    errs = [f for f in validate(doubled, _ctx()) if f.severity == "ERROR"]
    assert [f.rule for f in errs] == ["D10-dialogue-line-duplicated"], [str(f) for f in errs]
    assert "twice" in errs[0].msg


def test_the_whole_line_then_a_recap_of_its_tail_is_the_same_defect():
    """The shape the writer moved to once the whole-line duplicate was rejected, measured live:
    the complete line in [Shot 1], then "<d>[English] ...and not the whole lock.</d>" after the cut.
    Fewer words duplicated, same instruction to say them twice."""
    text = _doc(f"{SHOT1}<d>[English] {LINE}</d> <scenetrans> {CONTINUITY}\n"
                f"{SHOT2}<scenetrans> his sentence finishes: <d>[English] ...and not the whole "
                f"lock.</d>")
    errs = [f for f in validate(text, _ctx()) if f.severity == "ERROR"]
    assert [f.rule for f in errs] == ["D10-dialogue-line-duplicated"], [str(f) for f in errs]
    assert "again" in errs[0].msg and "ellipsis" in errs[0].msg


def test_a_second_unrelated_line_is_not_an_echo():
    """The threshold is four consecutive words of the caller's own line, which two different
    utterances do not share by accident."""
    text = _doc(f"{SHOT1}<d>[English] {LINE}</d>\n{SHOT2}the apprentice (S2) answers: "
                f"<d>[English] I will change it in the morning.</d>")
    assert not [f for f in validate(text, _ctx()) if f.severity == "ERROR"], \
        [str(f) for f in validate(text, _ctx())]


def test_the_duplicate_rule_only_counts_lines_the_caller_supplied():
    """A repeated shout the caller wrote as one line ("Pull it! Pull it!") lives inside one block
    and is none of this rule's business."""
    found = validate(_doc(SHOT1 + "<d>[English] Pull it! Pull it!</d>"),
                     _ctx(expected_dialogue=("Pull it! Pull it!",)))
    assert "D10-dialogue-line-duplicated" not in {f.rule for f in found}


def test_nothing_fires_when_the_caller_supplied_no_dialogue():
    found = validate(_doc(SHOT1 + "<d>[English] Anything at all.</d>"), _ctx(expected_dialogue=()))
    assert not [f for f in found if f.rule.startswith("D1")], [str(f) for f in found]


# ---------------------------------------------------------------- the marker is now required

def test_a_split_line_with_no_scenetrans_at_all_is_an_error():
    errs = [f for f in validate(_split(scenetrans_before=False, scenetrans_after=False), _ctx())
            if f.severity == "ERROR"]
    assert [f.rule for f in errs] == ["D11-split-line-no-scenetrans"], [str(f) for f in errs]
    assert "<scenetrans>" in errs[0].msg


def test_a_split_line_marked_on_only_one_side_is_an_error():
    """"at the connecting points in both parts" is two markers: the end of the first part and the
    start of the second."""
    for before, after in ((True, False), (False, True)):
        errs = [f for f in validate(_split(scenetrans_before=before, scenetrans_after=after),
                                    _ctx()) if f.severity == "ERROR"]
        assert [f.rule for f in errs] == ["D11-split-line-no-scenetrans"], (before, after, errs)
        assert "one side" in errs[0].msg, errs[0].msg


def test_a_split_line_with_no_continuity_statement_is_a_warning():
    """The spec mandates the statement and offers four phrasings for it, so the wording is open and
    the absence is reportable rather than a gate."""
    found = validate(_split(continuity=False), _ctx())
    assert not [f for f in found if f.severity == "ERROR"], [str(f) for f in found]
    warns = [f for f in found if f.rule == "D12-split-line-no-continuity-statement"]
    assert warns and warns[0].severity == "WARN", [str(f) for f in found]


def test_every_continuity_phrase_the_spec_lists_satisfies_it():
    for phrase in ("continues seamlessly across the cut",
                   "continues uninterrupted into the next shot",
                   "carries over from the previous shot",
                   "remains audible across the transition"):
        text = _split(continuity=False).replace("</d> <scenetrans>",
                                                f"</d> <scenetrans> His voice {phrase}.")
        found = [f for f in validate(text, _ctx())
                 if f.rule == "D12-split-line-no-continuity-statement"]
        assert not found, (phrase, [str(f) for f in found])


def test_a_line_broken_inside_one_shot_is_an_error_of_its_own():
    """No cut between the halves, so `<scenetrans>` is not the remedy: the line is simply broken in
    two for no reason, and one supplied line is spoken once."""
    text = _doc(f"{SHOT1}<d>[English] {HALF_A}</d> he pauses, then adds: "
                f"<d>[English] {HALF_B}</d>")
    errs = [f for f in validate(text, _ctx()) if f.severity == "ERROR"]
    assert [f.rule for f in errs] == ["D13-line-split-without-a-cut"], [str(f) for f in errs]


def test_a_line_split_across_three_shots_needs_the_marker_at_both_joins():
    """The construct generalises: every join the line crosses is a connecting point."""
    a, b, c = ("If it turns halfway and stops,", "the pin is worn,",
               "so you change the pin and not the whole lock.")
    good = _doc(
        f"{SHOT1}<d>[English] {a}</d> <scenetrans> {CONTINUITY}\n"
        f"[Shot 2] At 00:04.000, the shot cuts to the apprentice as the voice carries over from "
        f"the previous shot: <scenetrans> <d>[English] {b}</d> <scenetrans> {CONTINUITY}\n"
        f"[Shot 3] At 00:08.000, the shot cuts to the shop door and the voice remains audible "
        f"across the transition: <scenetrans> <d>[English] {c}</d>")
    assert not [f for f in validate(good, _ctx()) if f.severity == "ERROR"], \
        [str(f) for f in validate(good, _ctx())]
    bad = good.replace(f"<scenetrans> <d>[English] {b}</d>", f"<d>[English] {b}</d>", 1)
    errs = {f.rule for f in validate(bad, _ctx()) if f.severity == "ERROR"}
    assert "D11-split-line-no-scenetrans" in errs, errs


# ---------------------------------------------------------------- what the writer is told

def test_the_ask_states_how_a_line_crossing_a_cut_is_written():
    """`<scenetrans>` appeared in 0 of 7 natural requests and `<cutoff>` in 0 of 7. Both markers
    existed only as one line of spec text inside a long system prompt; the ask never mentioned them
    beside the lines the writer is placing. This asserts the rule of the format is stated there.
    Whether it lands is measured against the live service."""
    from h3ir.draft import deterministic_draft
    from h3ir.models import Brief, DialogueLine
    from h3ir.plan import ProfileOptions
    from h3ir.prose import compose_brief

    class Capture:
        class _Cfg:
            model = "capture"
        cfg = _Cfg()

        class _Reply:
            content = "integrated_multimodal_description: [Shot 1] ...\n"

        def __init__(self) -> None:
            self.asks: list[str] = []

        def chat(self, messages, **kw):
            self.asks.append(messages[-1]["content"])
            return self._Reply()

    brief = Brief(intent="A locksmith keeps talking while the shot cuts to the shop door.",
                  seconds=12.0,
                  dialogue=[DialogueLine(text=LINE, speaker_hint="the locksmith")])
    plan = deterministic_draft(brief, Mode.T2VA, {}, opts=ProfileOptions())
    backend = Capture()
    compose_brief(backend, brief, plan.subjects, {}, plan.target, (),
                  prompt_name="compose_base.v1.txt", mode=Mode.T2VA)
    ask = backend.asks[0]
    assert "spoken once" in ask.lower()
    assert "<scenetrans>" in ask
    assert "<cutoff>" in ask
    assert "no word appears in both" in ask
    assert "says them" in ask, "the consequence of a repeat has to be stated, not just forbidden"


def test_a_brief_with_no_dialogue_is_not_given_the_dialogue_rules():
    from h3ir.draft import deterministic_draft
    from h3ir.models import Brief
    from h3ir.plan import ProfileOptions
    from h3ir.prose import compose_brief

    class Capture:
        class _Cfg:
            model = "capture"
        cfg = _Cfg()

        class _Reply:
            content = "x"

        def __init__(self) -> None:
            self.asks: list[str] = []

        def chat(self, messages, **kw):
            self.asks.append(messages[-1]["content"])
            return self._Reply()

    brief = Brief(intent="Rain runs down a shop window.", seconds=8.0)
    plan = deterministic_draft(brief, Mode.T2VA, {}, opts=ProfileOptions())
    backend = Capture()
    compose_brief(backend, brief, plan.subjects, {}, plan.target, (),
                  prompt_name="compose_base.v1.txt", mode=Mode.T2VA)
    assert "<scenetrans>" not in backend.asks[0]
