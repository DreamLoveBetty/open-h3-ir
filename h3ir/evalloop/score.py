"""Scoring an IR beyond pass/fail.

The validator answers "is this legal". These metrics answer "is this good", and they exist
because the four problems the harness runs surfaced are all invisible to a legality check:

  desc_words        under-length was the consistent failure (170-240 against a 336-word
                    official example)
  n_shots           timed beats were absent entirely
  restatement       "one static description restated in different words" -- the max pairwise
                    similarity between shot bodies. High means the cuts carry no new
                    information, which is the failure a shot count alone cannot detect.
  sound_overlap     ambient sound described twice, in the body and again in the soundscape
  camera_level      0 none / 1 framing only / 2 motion type / 3 motion + amplitude + speed

Every one is a number, so a prompt change can be compared instead of believed. That is the
whole point: a system prompt that looked like an improvement measurably regressed, and only
mechanical checking caught it.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

STOP = {
    "the", "a", "an", "and", "or", "of", "in", "on", "at", "to", "with", "as", "is", "are",
    "its", "his", "her", "their", "it", "he", "she", "they", "this", "that", "from", "by",
    "for", "into", "over", "under", "while", "against", "across", "through", "then", "now",
    "up", "down", "out", "off", "above", "below", "behind", "before", "after", "was", "were",
    "be", "been", "has", "have", "had", "but", "so", "than", "very", "more", "most", "one",
}
CAMERA_STEMS = ("zoom", "push", "pull", "pan ", "truck", "tilt", "pedestal", "arc",
                "track", "static", "shake", "pov", "roll")


def content_words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z][a-z'-]{2,}", text.lower()) if w not in STOP}


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def shared_ngram(a: str, b: str, n: int = 5) -> str | None:
    """An exact shared n-gram is stronger evidence of duplication than word overlap."""
    def grams(s: str) -> set[str]:
        w = re.findall(r"[a-z][a-z'-]*", s.lower())
        return {" ".join(w[i:i + n]) for i in range(max(0, len(w) - n + 1))}
    common = grams(a) & grams(b)
    return sorted(common)[0] if common else None


@dataclass
class Score:
    name: str = ""
    ok: bool = False
    errors: int = 0
    warnings: int = 0
    infos: int = 0
    error_rules: list[str] = field(default_factory=list)
    warn_rules: list[str] = field(default_factory=list)
    tokens: int = 0
    desc_words: int = 0
    word_target: int = 0
    word_ratio: float = 0.0
    n_shots: int = 0
    n_timed_cuts: int = 0
    restatement: float = 0.0
    # 1.0 when every shot depicts something different; 0.0 when two shots are the same shot.
    # This is the metric that should have caught the repeated shot -- `restatement` read 0.21 on
    # two shots that showed the same moment, because their WORDING differed.
    shot_distinctness: float = 1.0
    n_planned_shots: float = 0.0
    # How often the template had to correct the model. Not a defect in the artifact -- the repair
    # worked -- but a rising number means the prose stage is drifting and is worth watching.
    repairs: int = 0
    # clean | repaired | fell_back — the number that says whether the compose prompt is working.
    outcome: str = "clean"
    # How many correction passes it took. 0 with outcome=clean means the compose prompt is good;
    # a rising number with clean outcomes means compose is drifting and fix is covering for it.
    fix_rounds: int = 0
    sound_overlap: float = 0.0
    sound_shared_phrase: str | None = None
    camera_level: int = 0
    dialogue_ok: bool = True
    mode: str = ""
    wall_s: float = 0.0
    timings: dict[str, float] = field(default_factory=dict)

    def dict(self) -> dict[str, Any]:
        return asdict(self)


# The fallback event has its own first-class number (`outcome` / `fallback_rate`), so counting it as a
# warning too meant one event moved two figures and the warning count could not be read. Reported in
# `warn_rules` like everything else -- excluded only from the countable aggregate.
_NOT_COUNTABLE = {"X13-written-rejected"}


def _countable_warnings(doc) -> list:
    return [f for f in doc.warnings if f.rule not in _NOT_COUNTABLE]


def _shot_bodies(desc: str) -> list[str]:
    """The prose of each shot, from the text that actually ships."""
    hits = list(re.finditer(r"\[Shot\s+(\d+)\]", desc))
    return [desc[m.end():(hits[i + 1].start() if i + 1 < len(hits) else len(desc))].strip()
            for i, m in enumerate(hits)]


def score_document(doc, name: str = "") -> Score:
    """Score a compiled IRDocument."""
    main = ("detailed_description" if "detailed_description" in doc.sections
            else "integrated_multimodal_description")
    desc = doc.sections.get(main, "")
    soundscape = doc.sections.get("overall_soundscape", "")

    # Split out of the SHIPPED description, not off the plan. In the write-first path the plan is the
    # deterministic draft's -- the model's prose never goes back into `plan.shots[].body` -- so
    # reading the plan measured the draft while the brief that ships is something else entirely. It
    # reported restatement 1.00 on written briefs whose shots are visibly different, and the baseline
    # was recorded under the old composed path where the two happened to be the same object. The
    # validator has always read the text; these metrics now agree with it.
    bodies = _shot_bodies(desc) or [s.body for s in doc.plan.shots if s.body]
    restate = 0.0
    for i in range(len(bodies)):
        for j in range(i + 1, len(bodies)):
            restate = max(restate, jaccard(content_words(bodies[i]), content_words(bodies[j])))

    from ..validate import _shot_signature
    # Only signatures the rule can actually judge. An all-empty signature means the prose named no
    # framing, no action group and no camera move -- R17 abstains there, so a metric that counted
    # it as a duplicate disagreed with the rule and reported a defect nobody could act on.
    sigs = [sig for sig in (_shot_signature(b) for b in bodies) if any(sig)]
    distinct = (len(set(sigs)) / len(sigs)) if sigs else 1.0

    sc_words = content_words(soundscape) if soundscape.strip() != "N/A" else set()
    overlap = jaccard(sc_words, content_words(desc))
    phrase = shared_ngram(desc, soundscape) if sc_words else None

    low = desc.lower()
    has_motion = any(s in low for s in CAMERA_STEMS)
    has_amp = bool(re.search(r"with (small|large) amplitude|at (slow|fast) speed", low))
    has_frame = bool(re.search(r"\bcamera\b|\bshot\b", low))
    camera_level = 3 if (has_motion and has_amp) else (2 if has_motion else (1 if has_frame else 0))

    target = doc.plan.total_word_target()
    words = len(re.findall(r"\b[\w'-]+\b", desc))
    dialogue_ok = not any(f.rule.startswith("D4") for f in doc.findings)

    return Score(
        name=name or doc.mode.value,
        ok=doc.ok,
        errors=len(doc.errors), warnings=len(_countable_warnings(doc)),
        infos=len([f for f in doc.findings if f.severity == "INFO"]),
        error_rules=sorted({f.rule for f in doc.errors}),
        warn_rules=sorted({f.rule for f in doc.warnings}),   # every rule, reported in full
        tokens=doc.prompt_tokens,
        desc_words=words, word_target=target,
        word_ratio=round(words / target, 3) if target else 0.0,
        # The shipped brief's shot count, not the plan's -- the same confusion `restatement` had, and
        # `n_planned_shots` below already exists to carry the plan's number. It showed as 2 and 4
        # shots against 0 timed cuts on briefs with no validator errors, which is impossible: T4
        # requires a cut time on every shot after the first, so the disagreement was two fields
        # describing two different artifacts.
        n_shots=len(bodies) or len(doc.plan.shots),
        n_timed_cuts=len(re.findall(r"At \d{2}:\d{2}\.\d{3}", desc)),
        restatement=round(restate, 3),
        shot_distinctness=round(distinct, 3),
        n_planned_shots=len(doc.plan.shots),
        repairs=len([f for f in doc.findings if f.rule == "X5-render-note"])
        + len(doc.provenance.get("repairs") or []),
        fix_rounds=int(doc.provenance.get("fix_rounds") or 0),
        outcome=("fell_back" if doc.fell_back else
                 ("repaired" if (doc.provenance.get("fix_rounds") or
                                 doc.provenance.get("repairs")) else "clean")),
        sound_overlap=round(overlap, 3),
        sound_shared_phrase=phrase,
        camera_level=camera_level,
        dialogue_ok=dialogue_ok,
        mode=doc.mode.value,
        timings=dict(doc.provenance.get("timings") or {}),
    )


# Direction of goodness for each metric, used by the regression gate.
HIGHER_IS_BETTER = {"desc_words": False, "word_ratio": None, "n_shots": None,
                    "n_timed_cuts": None, "restatement": False, "sound_overlap": False,
                    "camera_level": True, "errors": False, "warnings": False,
                    # `None` = reported, never gated. shot_distinctness measures how similar two
                    # shots look to a taxonomy I wrote; a director may legitimately shoot two beats
                    # at one distance, so a drop is information, not a regression. It gated at 0.01
                    # before, which made a taste heuristic able to block the suite. Same reason
                    # n_shots and n_timed_cuts have always been ungated: shot count is not a defect.
                    "shot_distinctness": None, "repairs": False,
                    "fallback_rate": False, "clean_rate": True, "fix_rounds": False}

# A change beyond this on the mean is treated as a real move rather than noise.
TOLERANCE = {"word_ratio": 0.10, "restatement": 0.05, "sound_overlap": 0.05,
             "camera_level": 0.5, "errors": 0.0, "warnings": 0.5,
             "shot_distinctness": 0.01, "repairs": 1.0, "fallback_rate": 0.0,
             "clean_rate": 0.15, "fix_rounds": 0.5}

# Metrics that are REPORTED with their delta but can never turn the gate red. Removing them from
# TOLERANCE would have hidden them instead, and the observation is worth keeping.
UNGATED = {
    "shot_distinctness",
    # Distance from `plan.total_word_target()` -- a number the writer is never given in the
    # write-first path, so in the mode being measured it is distance from a target that does not
    # exist in the pipeline. Even if it did, a length gate is the class the rule audit purged: a
    # 274-word brief directed well and a 636-word one did not.
    "word_ratio",
    # A single count that sums "this brief is 143 words" with a real content finding can only be
    # uninterpretable -- a move in it never says which of the two moved. The individual rules are
    # reported in `warn_rules`, where they can be read.
    "warnings",
}


@dataclass
class Aggregate:
    n: int = 0
    errors: float = 0.0
    warnings: float = 0.0
    word_ratio: float = 0.0
    desc_words: float = 0.0
    restatement: float = 0.0
    # 1.0 when every shot depicts something different; 0.0 when two shots are the same shot.
    # This is the metric that should have caught the repeated shot -- `restatement` read 0.21 on
    # two shots that showed the same moment, because their WORDING differed.
    shot_distinctness: float = 1.0
    n_planned_shots: float = 0.0
    # How often the template had to correct the model. Not a defect in the artifact -- the repair
    # worked -- but a rising number means the prose stage is drifting and is worth watching.
    repairs: int = 0
    # clean | repaired | fell_back — the number that says whether the compose prompt is working.
    outcome: str = "clean"
    # How many correction passes it took. 0 with outcome=clean means the compose prompt is good;
    # a rising number with clean outcomes means compose is drifting and fix is covering for it.
    fix_rounds: int = 0
    sound_overlap: float = 0.0
    camera_level: float = 0.0
    n_timed_cuts: float = 0.0
    repairs: float = 0.0
    fallback_rate: float = 0.0
    clean_rate: float = 0.0
    fix_rounds: float = 0.0
    failures: list[str] = field(default_factory=list)

    def dict(self) -> dict[str, Any]:
        return asdict(self)


def aggregate(scores: list[Score]) -> Aggregate:
    if not scores:
        return Aggregate()
    mean = lambda k: round(sum(getattr(s, k) for s in scores) / len(scores), 3)  # noqa: E731
    return Aggregate(
        n=len(scores), errors=mean("errors"), warnings=mean("warnings"),
        word_ratio=mean("word_ratio"), desc_words=mean("desc_words"),
        restatement=mean("restatement"), shot_distinctness=mean("shot_distinctness"),
        sound_overlap=mean("sound_overlap"),
        camera_level=mean("camera_level"), n_timed_cuts=mean("n_timed_cuts"),
        # Was never computed, so it reported 0 while every brief planned shots. Harmless -- it is
        # ungated -- but a metric that reads 0 forever is indistinguishable from one saying something.
        # Now it says what it means: how many shots the DRAFT planned, against `n_shots` for how many
        # the shipped brief has. The gap between the two is the interesting number.
        n_planned_shots=mean("n_planned_shots"),
        repairs=mean("repairs"),
        fallback_rate=round(sum(1 for s in scores if s.outcome == "fell_back") / len(scores), 3),
        clean_rate=round(sum(1 for s in scores if s.outcome == "clean") / len(scores), 3),
        fix_rounds=mean("fix_rounds"),
        failures=[s.name for s in scores if not s.ok])


def compare(baseline: Aggregate, candidate: Aggregate,
            baseline_metrics: set[str] | None = None) -> tuple[bool, list[str]]:
    """Returns (regressed, lines).

    A metric the baseline never MEASURED cannot be compared: its stored value is the dataclass
    default, not an observation, so comparing against it invents a regression. Adding a metric was
    reported as a quality drop the first time exactly this way.
    """
    lines: list[str] = []
    regressed = False
    for key, tol in TOLERANCE.items():
        if baseline_metrics is not None and key not in baseline_metrics:
            lines.append(f"  {key:16} {'(new metric, not in the baseline — not compared)':>44}")
            continue
        b, c = getattr(baseline, key, 0.0), getattr(candidate, key, 0.0)
        better = HIGHER_IS_BETTER.get(key)
        delta = c - b
        verdict = "same"
        if key in UNGATED:
            lines.append(f"  {key:16} {b:8.3f} -> {c:8.3f}  ({delta:+.3f})  "
                         f"{'moved' if abs(delta) > tol else 'same'} (not gated)")
            continue
        if better is True and delta < -tol:
            verdict, regressed = "REGRESSED", True
        elif better is False and delta > tol:
            verdict, regressed = "REGRESSED", True
        elif better is True and delta > tol:
            verdict = "improved"
        elif better is False and delta < -tol:
            verdict = "improved"
        elif key == "word_ratio":
            # Closeness to 1.0 is what matters, in either direction.
            if abs(c - 1.0) > abs(b - 1.0) + tol:
                verdict, regressed = "REGRESSED", True
            elif abs(c - 1.0) < abs(b - 1.0) - tol:
                verdict = "improved"
        lines.append(f"  {key:16} {b:8.3f} -> {c:8.3f}  ({delta:+.3f})  {verdict}")
    return regressed, lines
