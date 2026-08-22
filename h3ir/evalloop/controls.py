"""Static controls. No model, no GPU, runs in under a second.

Two directions, because a validator proved in only one direction is not proved:

  MUST PASS   MiniMax's own published Ref2VA example, with zero findings. A rule that fires
              on the spec's own artifact is a wrong rule, and this control has already
              corrected two of them (the 350-word floor, and requiring the closed camera
              vocabulary). It is the reason those are guidance and not law.

  MUST FAIL   mutants of that same example, each carrying exactly one defect class, each
              asserted to trip a NAMED rule. A rule that cannot be made to fire is not a
              rule. Mutants are used rather than a captured community artifact so that every
              expected failure is one we can point at in the text.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from ..config import get_config
from ..validate import Context, Report, validate

OFFICIAL = "official_ref2va_example.txt"
OFFICIAL_CTX = Context(mode="ref2va", n_pictures=4, n_videos=2, n_audios=1)


def golden_dir() -> Path:
    return get_config().paths.golden_dir


def load(name: str) -> str:
    return (golden_dir() / name).read_text(encoding="utf-8")


@dataclass
class ControlResult:
    name: str
    passed: bool
    detail: str


# --------------------------------------------------------------------------- mutants

def _mut_redundant_source(t: str) -> str:
    """A pure source identifier given a line of its own -- the defect the spec forbids and
    that a 'fixed facts' list in the system prompt provokes."""
    return t.replace("subject_definitions:\n",
                     "subject_definitions:\n<Picture 1> is the reference for the coffee shop.\n", 1)


def _mut_colon_subject(t: str) -> str:
    """`<Subject N>:` instead of `<Subject N> is` -- the subject never registers as defined,
    so every later use of it is a dangling pointer."""
    return t.replace("<Subject 1> is the coffee-shop environment",
                     "<Subject 1>: the coffee-shop environment", 1)


def _mut_missing_appears_in(t: str) -> str:
    return re.sub(r"(<Subject 2>) \(appears in [^)]*\):", r"\1:", t, count=1)


def _mut_wrong_label_namespace(t: str) -> str:
    """The owner's real defect: <Image N> instead of <Picture N>. The runtime emits
    '<Picture 1>: ' immediately before the image, so <Image 1> names nothing."""
    return t.replace("<Picture 1>", "<Image 1>")


def _mut_shot1_timestamp(t: str) -> str:
    return t.replace("[Shot 1] A medium shot", "[Shot 1] At 00:00.000, A medium shot", 1)


def _mut_bad_marker(t: str) -> str:
    return t.replace("fully_preserved - the exposed brick wall", "mostly_preserved - the exposed brick wall", 1)


def _mut_audio_marker_on_subject(t: str) -> str:
    return t.replace("<Subject 2> (appears in [Shot 1], [Shot 2]): fully_preserved",
                     "<Subject 2> (appears in [Shot 1], [Shot 2]): fully_copy", 1)


def _mut_speaker_in_retention(t: str) -> str:
    return t.replace("<Audio 1>: reference -", "<Audio 1> (S1): reference -", 1)


def _mut_smart_quote(t: str) -> str:
    return t.replace("the Samoyed's thick white fur", "the Samoyed’s thick white fur", 1)


def _mut_task_type(t: str) -> str:
    return t.replace("[reference generation + audio reference]", "[reference generation + vibes]", 1)


def _mut_editing_without_video(t: str) -> str:
    return t.replace("[reference generation + audio reference]", "[video editing]", 1)


def _mut_duplicate_prefix(t: str) -> str:
    """The task-type prefix twice, which is what a correction round produced on live output: the
    model prepended the mandated editing sentence with a fresh prefix and kept its original one.
    M1 reads only the opening and M3 reads only inside one bracket group, so it shipped clean."""
    return t.replace("[reference generation + audio reference] The target video",
                     "[reference generation + audio reference] The target video is described "
                     "below. [reference generation + audio reference] The target video", 1)


def _mut_out_of_order(t: str) -> str:
    """Swap two sections so the mandated order is broken."""
    i, j = t.index("summary:"), t.index("retention_analysis:")
    k = t.index("detailed_description:")
    return t[:i] + t[j:k] + t[i:j] + t[k:]


def _mut_code_fence(t: str) -> str:
    return "```text\n" + t + "\n```"


def _mut_dialogue_marker_case(t: str) -> str:
    return t.replace("<d>[English] Hey!", "<D>[English] Hey!", 1)


def _mut_label_not_closed(t: str) -> str:
    r"""A label opened and never closed. Found SHIPPED with zero findings, in the first live
    replacement brief anybody compiled: "<Subject 4> is the piece of wood in <Video 1," -- the '>'
    dropped and a comma in its place. Every other label rule walks `<(Kind) (\d+)>`, so the broken
    one matched none of them and the reference simply vanished."""
    return t.replace("<Subject 2> is the fluffy white Samoyed in <Picture 2>,",
                     "<Subject 2> is the fluffy white Samoyed in <Picture 2,", 1)


MUTANTS: list[tuple[str, callable, str]] = [
    ("redundant <Picture N> source line", _mut_redundant_source, "L5-redundant-source-line"),
    ("<Subject N>: colon form", _mut_colon_subject, "L2-undefined-subject"),
    ("missing (appears in [Shot N])", _mut_missing_appears_in, "R3-missing-appears-in"),
    ("<Image N> instead of <Picture N>", _mut_wrong_label_namespace, "L1-unknown-label"),
    ("timestamp on [Shot 1]", _mut_shot1_timestamp, "T2-shot1-timestamp"),
    ("invented retention marker", _mut_bad_marker, "R2-illegal-marker"),
    ("audio marker on a subject", _mut_audio_marker_on_subject, "R2-illegal-marker"),
    ("speaker ID in retention_analysis", _mut_speaker_in_retention, "R4-speaker-in-retention"),
    ("curly apostrophe in structural text", _mut_smart_quote, "H1-unicode-hazard"),
    ("invented task type", _mut_task_type, "M2-task-type"),
    ("'video editing' with no edit source", _mut_editing_without_video, "M6-editing-opening"),
    ("the task-type prefix written twice", _mut_duplicate_prefix, "M9-task-prefix-repeated"),
    ("sections out of order", _mut_out_of_order, "S2-section-order"),
    ("wrapped in a code fence", _mut_code_fence, "S4-code-fence"),
    ("<D> instead of <d>", _mut_dialogue_marker_case, "D5-marker-not-byte-exact"),
    ("a label opened and never closed", _mut_label_not_closed, "L6-label-not-closed"),
]


# --------------------------------------------------------------------------- runner

def run_controls(verbose: bool = False) -> tuple[bool, list[ControlResult]]:
    results: list[ControlResult] = []
    official = load(OFFICIAL)

    # ONE documented exception, authorised deliberately rather than discovered.
    # P5 (no motion type from the closed vocabulary) is now an ERROR, and MiniMax's own example
    # trips it. That is intended: their example is a single static shot of a seated conversation,
    # where an unstated camera costs nothing, while our briefs are motion and the owner's own
    # reference material says H3 drifts and reframes when the camera is unspecified. Three of our
    # generations had no motion type and every validator passed them.
    # The example must still be clean on EVERYTHING ELSE, which is what this asserts.
    OFFICIAL_EXPECTED = {"P5-camera-no-motion-type"}
    findings = validate(official, OFFICIAL_CTX)
    errs = [f for f in findings if f.severity == "ERROR" and f.rule not in OFFICIAL_EXPECTED]
    warns = [f for f in findings if f.severity == "WARN" and f.rule not in OFFICIAL_EXPECTED]
    ok = not errs and not warns
    results.append(ControlResult(
        "MUST PASS: MiniMax official Ref2VA example (P5 exempt, see note)", ok,
        "clean apart from the documented P5 exception"
        if ok else "; ".join(str(x) for x in errs + warns)))
    fired = {f.rule for f in findings}
    results.append(ControlResult(
        "EXPECTED: the official example lacks a motion type", "P5-camera-no-motion-type" in fired,
        "P5 fired as documented" if "P5-camera-no-motion-type" in fired
        else "P5 did not fire — the rule may be matching ordinary prose again"))

    for name, mutate, expect in MUTANTS:
        text = mutate(official)
        if text == official:
            results.append(ControlResult(f"MUST FAIL: {name}", False,
                                         "mutation did not apply — the control is stale"))
            continue
        rules = {f.rule for f in validate(text, OFFICIAL_CTX) if f.severity == "ERROR"}
        hit = expect in rules
        results.append(ControlResult(
            f"MUST FAIL: {name}", hit,
            f"{expect} fired" if hit else f"expected {expect}, got {sorted(rules) or 'nothing'}"))

    # The arm a human rejected on taste, assembled from its emitted sentences (the acceptance
    # directory is gitignored, so this is the real prose rather than the original file).
    #
    # This control has been INVERTED, and the inversion is the honest reading of what happened. It
    # used to assert that R17 fires here, which made a taste judgement into a mechanical pass/fail:
    # the two shots are worded differently, describe different sentences, and are only "the same
    # shot" to an eye that has decided so. The rule that fired on it was a similarity heuristic over
    # my own taxonomy, and it would equally have fired on legitimate edits.
    #
    # So the control now asserts the truth: this file is mechanically clean, and the defect in it is
    # invisible to the validator. The validator's job is the silent class -- a wrong label, an
    # off-grid duration, a cut past the end, an unstated camera -- not whether an edit is good. If
    # someone re-adds a similarity rule, this control goes red and the message explains why.
    p = golden_dir() / "shipped_repeated_shot.txt"
    if p.exists():
        found = validate(p.read_text(encoding="utf-8"), Context(n_pictures=2, duration_s=8.0))
        errs = {f.rule for f in found if f.severity == "ERROR"}
        results.append(ControlResult(
            "MUST PASS mechanically: a shot rejected on taste, not on legality", not errs,
            "clean, as it should be — the repeated shot is a judgement the validator cannot make, "
            "and a human is the judge on it"
            if not errs else
            f"a rule now fires on prose that was rejected on taste: {sorted(errs)}. If that rule "
            "judges the writing rather than a decidable fact, it does not belong in the validator"))

    # official_fl2va_example.txt is base-en.txt's own case 3, copied out byte for byte (a test
    # asserts it still matches the shipped spec). It is here because its absence is how a rule that
    # rejected EVERY legal first-and-last-frame brief shipped green: fl2va cites its pictures bare,
    # the label scanner read only the bracketed form, and L4 fired on correct text. There were
    # controls for t2va, i2va and ref2va, so those three modes were protected and this one was not.
    for name, ctx in (("t2va.ir.txt", Context(mode="t2va", n_pictures=0, duration_s=10.125)),
                      ("i2va.ir.txt", Context(mode="i2va", n_pictures=1, duration_s=8.0)),
                      ("official_fl2va_example.txt",
                       Context(mode="fl2va", n_pictures=2, duration_s=8.0)),
                      ("ref2va.ir.txt", Context(mode="ref2va", n_pictures=0, n_videos=1,
                                                n_audios=2, duration_s=5.167,
                                                generation_task=False))):
        p = golden_dir() / name
        if not p.exists():
            continue
        e = [f for f in validate(p.read_text(encoding="utf-8"), ctx) if f.severity == "ERROR"]
        results.append(ControlResult(f"MUST PASS: published {name}", not e,
                                     "clean" if not e else "; ".join(str(x) for x in e)))

    return all(r.passed for r in results), results


def print_controls(results: list[ControlResult]) -> None:
    width = max(len(r.name) for r in results)
    for r in results:
        mark = "ok  " if r.passed else "FAIL"
        print(f"  [{mark}] {r.name:<{width}}  {r.detail if not r.passed else ''}".rstrip())
