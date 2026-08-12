"""The validator. It exists to REJECT.

Proved by controls, not by inspection:
  * MiniMax's own published Ref2VA example must PASS with zero findings.
    A rule that fires on the spec's own example is a wrong rule, not a strict one --
    that control has already corrected two of them (the 350-word floor, and requiring
    the closed camera vocabulary).
  * Known-bad inputs must FAIL on the specific rules they break.

Severities: ERROR blocks the render. WARN is reported. INFO is advisory only.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable

from .creativity import (COMMITS_CAMERA, MAXIMAL_CAMERA, ONSCREEN_TEXT, SCORE, SPEECH,
                         Scope)
from .models import AUDIO_MARKERS, CAMERA_TYPES, Finding, TASK_TYPES, VISUAL_MARKERS

REF_SECTIONS = ["subject_definitions", "summary", "retention_analysis",
                "detailed_description", "overall_soundscape", "non_diegetic_music"]
BASE_SECTIONS = ["integrated_multimodal_description", "overall_soundscape", "non_diegetic_music"]

# The mechanical constraint is frame ALIGNMENT (n % 17 == 5), not membership in the node's stated
# trained band. The band is a note about where the model was trained, and the owner renders past
# it routinely -- 1920x1088 and beyond ten seconds, just slower. So an off-grid duration is an
# error and an out-of-band one is at most a note.
TRAINED_BAND_FRAMES = (124, 362)


def frames_for(duration_s: float) -> int:
    return int(round(duration_s * 24))


# A caller writes 5.167, not 5.166666. Tolerate rounding to three decimals (max error 0.0005)
# and nothing looser: 5.17 is genuinely not a duration this model produces.
GRID_TOLERANCE_S = 0.0006


def is_on_grid(duration_s: float) -> bool:
    n = frames_for(duration_s)
    return abs(n / 24 - duration_s) <= GRID_TOLERANCE_S and n % 17 == 5


def nearest_on_grid(duration_s: float) -> float:
    n = frames_for(duration_s)
    lo = n - ((n - 5) % 17)
    hi = lo + 17
    return min((lo / 24, hi / 24), key=lambda x: abs(x - duration_s))

# Characters that silently change tokenization if they replace their ASCII counterpart.
UNICODE_HAZARDS = {
    "‘": "'", "’": "'", "“": '"', "”": '"',
    " ": " ", "〈": "<", "〉": ">", "＜": "<", "＞": ">",
    "（": "(", "）": ")", "［": "[", "］": "]",
}

# Phrases that describe what a subject is DOING rather than what they look like. Deliberately
# narrow and anchored: "clenched fists" as identity, not the word "hand".
POSE_PATTERNS = tuple(re.compile(p, re.I) for p in (
    r"\b(?:fists?|hands?|arms?|legs?)\s+(?:clenched|crossed|raised|folded|outstretched|on hips)",
    r"\b(?:in|adopting)\s+a\s+\w+(?:\s+\w+)?\s+(?:stance|pose|posture)\b",
    r"\bposed?\s+(?:for|in|with)\b",
    r"\bmid-(?:stride|step|jump|swing|air)\b",
    r"\b(?:looking|gazing|staring|facing)\s+(?:at|into|toward)\s+the\s+camera\b",
    r"\b(?:smiling|frowning|grimacing|scowling|shouting)\s+(?:at|toward)\b",
    r"\bseen\s+from\s+a\s+\w+\s+angle\b",
    r"\b(?:fighting|combat|battle|defensive|heroic)\s+(?:stance|pose)\b",
))

# Case-INSENSITIVE for phrases that are unambiguous, and case-SENSITIVE for the burned-in labels:
# they are printed in capitals on the sheet, whereas "back" and "front" are ordinary words. A
# rule that fired on "he looks back" would reject innocent prose.
# One rule for the whole sentence. Each entry is a shape that has actually been emitted.
STYLE_OPENING_FAULTS: tuple[tuple[re.Pattern, str], ...] = (
    (re.compile(r"\bstyle\s+style\b", re.I), "the word 'style' is doubled"),
    (re.compile(r"\bwith\s+(?:resembling|similar to|like)\b", re.I),
     "a joining word follows 'with'"),
    # Only when the clause ENDS there: "with cinematic." is the bug, "with cinematic, warm
    # afternoon light." is ordinary English and must not be flagged.
    (re.compile(r"\bwith\s+(?:cinematic|moody|dramatic|grainy|soft|warm|cold|muted|saturated)"
                r"\s*\.", re.I), "'with' is followed by a bare adjective and nothing else"),
    (re.compile(r"\bwith\s*[.,]"), "'with' has no object"),
    (re.compile(r",\s*,"), "an empty list item"),
    (re.compile(r"\bin\s+style\b", re.I), "the medium is missing before 'style'"),
    (re.compile(r"\bwith\s+[A-Z][a-z]"), "a spliced clause keeps its capital mid-sentence"),
)

SHEET_ARTEFACTS: tuple[tuple[re.Pattern, str], ...] = (
    (re.compile(r"\b(?:turnaround|model sheet|character sheet|contact sheet|reference sheet)\b",
                re.I), "the sheet itself"),
    (re.compile(r"\b(?:panel|panels|panel grid|tile[sd]?\s+layout|four[- ]by[- ]two|2x4|4x2)\b",
                re.I), "the sheet's layout"),
    (re.compile(r"\b(?:FRONT|BACK|LEFT PROFILE|RIGHT PROFILE|LEFT 3/4 VIEW|RIGHT 3/4 VIEW|"
                r"RELAXED STANDING POSE|CASUAL CONFIDENT POSE)\b"),
     "a label burned into the sheet"),
    (re.compile(r"\b(?:studio (?:grey|gray|backdrop)|seamless (?:grey|gray|white)|"
                r"plain grey background|neutral grey backdrop)\b", re.I),
     "the sheet's studio backdrop"),
    (re.compile(r"\b(?:multiple|several|eight|four)\s+(?:views|angles|poses)\s+of\b", re.I),
     "the sheet's multiple views"),
)

# Interpretations masquerading as observations.
INFERRED_ATTRIBUTES = tuple(re.compile(p, re.I) for p in (
    r"\b(?:fighting|combat|battle|heroic|power|defensive|aggressive|ready)\s+(?:stance|pose|posture)\b",
    r"\b(?:determined|menacing|confident|threatening|sinister|noble|proud|anxious|nervous)\b",
    r"\bready\s+to\s+\w+",
    r"\babout\s+to\s+\w+",
    r"\b(?:conveying|suggesting|implying|radiating|exuding)\b",
    r"\bair\s+of\s+\w+",
))

# Canonical renderings of the closed vocabulary, in the forms prose actually uses.
CAMERA_MOTION_PHRASE = re.compile(
    r"\b(?:zoom(?:s|ing)?\s+(?:in|out)|push(?:es|ing)?\s+in|pull(?:s|ing)?\s+(?:out|back)"
    r"|pan(?:s|ning)?\s+(?:left|right)|truck(?:s|ing)?\s+(?:left|right)"
    r"|tilt(?:s|ing)?\s+(?:up|down)|pedestal(?:s|ing)?\s+(?:up|down)"
    r"|arc(?:s|ing)?\s+(?:around|about)|track(?:s|ing)?\s+(?:with|alongside|behind)"
    r"|holds?\s+(?:a\s+)?static|static\s+shot|shakes?\s+(?:slightly|strongly)"
    r"|rolls?\s+(?:clock|counter)|point\s+of\s+view|\bPOV\b)", re.I)

# A bare stem, but only counted inside a clause that is talking about the camera.
CAMERA_STEM_IN_CONTEXT = re.compile(
    r"\b(?:zoom|push|pull|pan|truck|tilt|pedestal|arc|track|static|shake|roll|drift|glide|"
    r"crane|dolly)\w*", re.I)

CAMERA_LABEL_STACK = re.compile(
    r"^\s*Camera\s*:\s*\w|\bCamera\s*:\s*(?:Push|Pull|Zoom|Pan|Truck|Tilt|Pedestal|Arc|"
    r"Track|Static|Shake|Roll|POV)\b", re.M)

# "Subject 1" as prose, not "<Subject 1>". Requires the capital, so "the subject" is untouched.
BARE_SUBJECT_NAME = re.compile(r"(?<!<)\bSubject\s+\d+\b(?!>)")

CAMERA_CONTRADICTIONS = tuple((re.compile(p, re.I), w) for p, w in (
    (r"push(?:es|ing)?\s+in\b(?P<gap>[^.]{0,80}?)\b(?:backward|backwards|away from|retreat)",
     "a push in cannot move backward"),
    (r"pull(?:s|ing)?\s+(?:out|back)\b(?P<gap>[^.]{0,80}?)\b(?:closer|toward the subject|forward)",
     "a pull out cannot move closer"),
    (r"static\s+shot\b(?P<gap>[^.]{0,80}?)\b(?:pushes|pans|trucks|tilts|tracks|moves)\b",
     "a static shot does not move"),
    (r"\b(?:holds?\s+static)\b(?P<gap>[^.]{0,60}?)\b(?:while|as)\s+(?:it|the camera)\s+"
     r"(?:moves|drifts)",
     "a held camera does not drift"),
))

# The gap between a camera move and its supposed contradiction decides whether there IS one. Two
# ways the match is innocent, and both are ordinary good writing rather than defects:
#   * a new actor took over the sentence -- "the camera pushes in as he steps backward" is a push
#     in on a retreating subject, which is a real shot, not a contradiction;
#   * a temporal connective made it a sequence -- "holds static, then pans right" is two states in
#     order, not one state contradicting itself.
# Without these the rule fired ERROR on legitimate direction and, since ERRORs are what the fix
# loop sends back to the model, would have had it rewrite the shot to satisfy a phantom.
_NEW_ACTOR = re.compile(
    r"\b(?:he|she|they|him|her|them|his|hers|their|<Subject\s+\d+>|the\s+(?:man|woman|figure|"
    r"boy|girl|child|subject|character|dog|cat|animal|rider|runner|driver|crowd))\b", re.I)
_SEQUENCE = re.compile(r"\b(?:then|before|after|until|once|later|afterwards?|first)\b", re.I)


def _contradiction_is_real(gap: str) -> bool:
    return not (_NEW_ACTOR.search(gap) or _SEQUENCE.search(gap))

VOICEOVER_PHRASE = "says in an off-screen voiceover"
LIPS_CLOSED = re.compile(r"lips?\b[^.]*\b(closed|shut)", re.I)


@dataclass
class Context:
    """What the validator needs to know beyond the text itself."""

    mode: str = "ref2va"
    duration_s: float | None = None          # effective (real) duration
    n_pictures: int | None = None
    n_videos: int = 0
    n_audios: int = 0
    expected_dialogue: tuple[str, ...] = ()  # verbatim user lines
    lora_triggers: tuple[dict, ...] = ()     # {"text","count","slot"}
    onscreen_text: tuple[str, ...] = ()
    token_budget: tuple[int, int] = (350, 1400)
    prompt_tokens: int | None = None
    require_music_na: bool | None = None
    generation_task: bool = True             # editing tasks are exempt from the word range
    # (label, role, marker) triples from the wiring, for marker-legality checks
    declared_roles: tuple[tuple[str, str, str], ...] = ()
    # (audio_label, video_label, audio_seconds, video_seconds)
    paired_audio: tuple[tuple[str, str, float | None, float | None], ...] = ()
    # Audio labels the wiring KNOWS are attached standalone rather than as a video's soundtrack. A
    # positive assertion on purpose: an empty tuple means "not stated", never "none are paired".
    standalone_audio: tuple[str, ...] = ()
    forbid_keyframe_refs: bool = False
    require_start_at_zero: bool = True
    # True only when a reference plate IS a frame of the video (a frame anchor), which is the one
    # case where the plate's pose legitimately belongs to the subject's definition.
    pose_licensed: bool = False
    # True when any attached plate is a character sheet / turnaround, which brings its own class
    # of contamination: grid, burned-in labels, studio backdrop.
    has_reference_sheet: bool = False
    # Garment words the subject should be re-named with at every appearance, as a drift defence.
    wardrobe_terms: tuple[str, ...] = ()
    # The REFERENCE's medium bucket, set only when the request asked to depart from it and the two
    # buckets actually differ. The style opening must not come back reading as this. Empty means the
    # question does not arise, which is what every caller that predates R23 gets.
    transformed_from: str = ""
    # What this request licenses the writer to ADD. None means the check abstains, which is what
    # every caller that predates the dial gets -- including the golden controls and the independent
    # validator, neither of which knows what was asked.
    scope: Scope | None = None


def _sections(text: str, names: Iterable[str]) -> tuple[dict[str, str], list[str]]:
    idx = []
    for name in names:
        m = re.search(rf"^{name}\s*:", text, re.M)
        if m:
            idx.append((m.start(), m.end(), name))
    idx.sort()
    out, order = {}, []
    for i, (s, e, name) in enumerate(idx):
        end = idx[i + 1][0] if i + 1 < len(idx) else len(text)
        out[name] = text[e:end].strip()
        order.append(name)
    return out, order


_STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "in", "on", "at", "to", "with", "as", "is", "are",
    "its", "his", "her", "their", "it", "from", "by", "for", "into", "over", "under", "while",
    "across", "through", "then", "up", "down", "out", "off", "above", "below", "behind", "was",
    "be", "has", "have", "had", "but", "so", "than", "very", "more", "most", "one", "continues",
    "throughout", "video", "shot", "scene", "camera",
}


def _content_words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z][a-z'-]{2,}", text.lower()) if w not in _STOPWORDS}


def _content_overlap(a: str, b: str) -> float:
    wa, wb = _content_words(a), _content_words(b)
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / len(wa)


def _shared_phrase(a: str, b: str, n: int = 5) -> str | None:
    def grams(s: str) -> set[str]:
        w = re.findall(r"[a-z][a-z'-]*", s.lower())
        return {" ".join(w[i:i + n]) for i in range(max(0, len(w) - n + 1))}
    common = grams(a) & grams(b)
    return sorted(common)[0] if common else None


def _shot_signature(body: str) -> tuple[str, str, str]:
    """Delegates to shots.depiction_signature so the text rule and the proposal rule agree."""
    from .shots import depiction_signature
    return depiction_signature(body)


def _labels_cited(body: str) -> set[str]:
    return set(re.findall(r"<(?:Subject|Picture|Video|Audio)\s+\d+>", body))


def _strip_verbatim(s: str) -> str:
    """Remove spans whose contents are user-owned: dialogue and quoted on-screen text."""
    s = re.sub(r"<d>.*?</d>", " ", s, flags=re.S)
    return re.sub(r'"[^"]*"', " ", s)


def validate(text: str, ctx: Context | None = None, **kw) -> list[Finding]:
    ctx = ctx or Context(**kw)
    f: list[Finding] = []
    add = lambda r, s, m: f.append(Finding(r, s, m))  # noqa: E731

    is_ref = ctx.mode == "ref2va"
    names = REF_SECTIONS if is_ref else BASE_SECTIONS
    sec, order = _sections(text, names)
    main_field = "detailed_description" if is_ref else "integrated_multimodal_description"

    # ---------------------------------------------------------------- structure
    for name in names:
        if name not in sec:
            add("S1-missing-section", "ERROR", f"'{name}:' is absent")
    if order and order != [s for s in names if s in sec]:
        add("S2-section-order", "ERROR", f"sections out of mandated order: {order}")
    body_start = text.lstrip()
    if is_ref and not body_start.startswith("subject_definitions:"):
        add("S3-preamble", "ERROR", "brief must begin with 'subject_definitions:'")
    if "```" in text:
        add("S4-code-fence", "ERROR", "output contains a markdown code fence")
    wrong_field = "integrated_multimodal_description" if is_ref else "detailed_description"
    if re.search(rf"^{wrong_field}\s*:", text, re.M):
        add("S5-mode-field-crossed", "ERROR",
            f"'{wrong_field}' is the other mode's field name; {ctx.mode} uses '{main_field}'")
    # "Complete" is one of the four things the service is judged on: everything H3 expects,
    # populated meaningfully. A present-but-empty section satisfied every rule until now -- an empty
    # overall_soundscape validated clean, and H3 is a model that generates audio. Purely mechanical:
    # the header is there and there is nothing under it.
    #
    # `non_diegetic_music: N/A` is exempt because N/A is the value the spec DEFINES for that field
    # when there is no score. An empty soundscape is a section nobody wrote; an N/A score is an
    # answer. The dial decides whether N/A is the right answer, not this rule.
    for name in names:
        if name in sec and not sec[name].strip():
            add("S9-section-empty", "ERROR",
                f"'{name}:' is present but empty; every section H3 expects has to be populated"
                + (" (only non_diegetic_music may be 'N/A')" if name != "non_diegetic_music" else ""))

    defs = sec.get("subject_definitions", "")
    ret = sec.get("retention_analysis", "")
    desc = sec.get(main_field, "")
    summ = sec.get("summary", "")
    # Verbatim spans (dialogue, quoted on-screen text) are the user's; no structural rule reads
    # them. Computed once here because several rules below need it.
    scrubbed_all = _strip_verbatim(text)
    scrubbed = scrubbed_all

    # ---------------------------------------------------------------- labels
    def labels(s: str, kind: str) -> set[int]:
        return {int(x) for x in re.findall(rf"<{kind}\s+(\d+)>", s)}

    used = {k: labels(text, k) for k in ("Subject", "Picture", "Video", "Audio")}

    bad_kinds = set(re.findall(r"<\s*([A-Za-z]+)\s+\d+\s*>", text)) - {
        "Subject", "Picture", "Video", "Audio"}
    for k in sorted(bad_kinds):
        add("L1-unknown-label", "ERROR",
            f"<{k} N> is not in the label vocabulary (Subject/Picture/Video/Audio); the runtime "
            f"emits <Picture N>/<Video N>/<Audio N>, so <{k} N> points at nothing")

    defined_subj = set()
    for line in defs.splitlines():
        m = re.match(r"\s*<Subject\s+(\d+)>\s+is\b", line)
        if m:
            defined_subj.add(int(m.group(1)))
    for n in sorted(used["Subject"] - defined_subj):
        add("L2-undefined-subject", "ERROR",
            f"<Subject {n}> is used but never defined with '<Subject {n}> is ...' in "
            "subject_definitions (a colon form does not register as a definition)")

    for kind, n_have in (("Picture", ctx.n_pictures), ("Video", ctx.n_videos),
                         ("Audio", ctx.n_audios)):
        if n_have is None:
            continue
        over = {n for n in used[kind] if n > n_have}
        if over:
            add("L3-phantom-media", "ERROR",
                f"<{kind} {sorted(over)}> referenced but only {n_have} {kind.lower()}(s) attached")
        # `and used[kind]` used to guard this, which skipped the check whenever a kind was used ZERO
        # times -- the worst case, not an exempt one. A brief that attaches an audio reference and
        # never binds it published a manifest entry the app would wire in, against text that never
        # mentions the asset: inert conditioning plus contradictory context, and silent. `n_have`
        # already handles "nothing attached", so the extra guard only ever hid the total miss.
        if n_have and set(range(1, n_have + 1)) - used[kind]:
            add("L4-unused-media", "ERROR" if not used[kind] else "WARN",
                f"attached {kind.lower()}(s) {sorted(set(range(1, n_have + 1)) - used[kind])} "
                "never referenced — they cost rows on every sampling step for no effect")

    # A standalone <Picture N>/<Video N> line is LEGAL when that label is analysed separately
    # later. The spec forbids it only when the label "will not be analyzed or used separately",
    # so the test is whether retention_analysis carries an entry for it -- not the wording.
    analysed_labels = set(re.findall(r"^\s*<((?:Picture|Video|Audio)\s+\d+)>", ret, re.M))
    for line in defs.splitlines():
        m = re.match(r"\s*<((Picture|Video)\s+(\d+))>\s*(is|:)", line)
        if not m:
            continue
        if not re.search(r"\b(reference for|source of|the reference image for)\b", line, re.I):
            continue
        if m.group(1) in analysed_labels:
            continue        # separately analysed, so it has earned its own line
        add("L5-redundant-source-line", "ERROR",
            f"<{m.group(1)}> is cited only as a source and has no retention_analysis entry, so "
            f"it gets no line of its own: {line.strip()[:80]!r}")

    if summ:
        new_in_summary = {f"<{k} {n}>" for k in ("Subject",) for n in labels(summ, k)} - {
            f"<Subject {n}>" for n in defined_subj}
        if new_in_summary:
            add("M4-new-label-in-summary", "ERROR",
                f"summary introduces undefined label(s): {sorted(new_in_summary)}")

    # ---------------------------------------------------------------- summary
    if is_ref:
        pref = re.match(r"\s*\[([^\]]+)\]", summ)
        if not pref:
            add("M1-task-prefix", "ERROR", "summary must open with a [task type] prefix")
        else:
            parts = [p.strip() for p in pref.group(1).split("+")]
            for p in parts:
                if p not in TASK_TYPES:
                    add("M2-task-type", "ERROR", f"'{p}' is not a legal task type")
            if len(parts) != len(set(parts)):
                add("M3-task-dupe", "ERROR", "task type repeated in the prefix")
            if "video editing" in parts:
                if not used["Video"]:
                    add("M5-editing-without-video", "ERROR",
                        "'video editing' claimed but no <Video N> is referenced")
                elif not re.search(r"The target video is an edited version of <Video \d+>\.", summ):
                    add("M6-editing-opening", "ERROR",
                        "video-editing summaries must open with "
                        "'The target video is an edited version of <Video N>.'")
            if "audio reuse" in parts and not used["Audio"]:
                add("M7-audio-reuse-without-audio", "ERROR",
                    "'audio reuse' claimed but no <Audio N> is referenced")

    # ---------------------------------------------------------------- retention
    if is_ref:
        analysed = set()
        for line in [l for l in ret.splitlines() if l.strip()]:
            m = re.match(r"\s*<(Subject|Picture|Video|Audio)\s+(\d+)>\s*(\([^)]*\))?\s*:\s*(\w+)",
                         line)
            if not m:
                add("R1-malformed-entry", "ERROR", f"unparseable retention line: {line.strip()[:80]!r}")
                continue
            kind, num, paren, marker = m.group(1), m.group(2), m.group(3), m.group(4)
            if kind == "Subject":
                analysed.add(int(num))
            legal = AUDIO_MARKERS if kind == "Audio" else VISUAL_MARKERS
            if marker not in legal:
                add("R2-illegal-marker", "ERROR",
                    f"<{kind} {num}>: '{marker}' is not a legal {kind} relationship marker "
                    f"({', '.join(legal)})")
            if kind == "Subject" and not (paren and "appears in" in paren):
                add("R3-missing-appears-in", "ERROR",
                    f"<Subject {num}> is missing the mandated '(appears in [Shot N])'")
            if re.search(r"\(S\d", line):
                add("R4-speaker-in-retention", "ERROR",
                    "speaker IDs must not appear in retention_analysis")
        for n in sorted(defined_subj - analysed):
            add("R5-unanalysed-subject", "WARN",
                f"<Subject {n}> defined but absent from retention_analysis")

    # ---------------------------------------------------------------- pose contamination
    # A reference plate licenses APPEARANCE, not POSE. Scoped to subject_definitions and
    # retention_analysis, where a phrase is an assertion about who the subject IS; the same
    # words are perfectly legal in the description, where they describe what happens.
    if not ctx.pose_licensed:
        for section, body in (("subject_definitions", defs), ("retention_analysis", ret)):
            for m in POSE_PATTERNS:
                hit = m.search(body)
                if hit:
                    add("R12-pose-as-identity", "WARN",
                        f"{section} asserts a pose from the reference plate "
                        f"({hit.group(0)!r}); stance and gesture belong to that photograph, not "
                        "to the subject's identity, and the request owns the action")
                    break

    # ---------------------------------------------------------------- sheet contamination
    # A turnaround's grid, its burned-in labels and its studio backdrop belong to the SHEET, not to
    # the character. H3 renders legible text well, so "FRONT" or "LEFT PROFILE" reaching the brief
    # is a live risk of it appearing in the video, and the brief is the only defence.
    if ctx.has_reference_sheet:
        for pat, what in SHEET_ARTEFACTS:
            hit = pat.search(scrubbed_all)
            if hit:
                add("R13-sheet-artefact", "WARN",
                    f"the brief describes {what} ({hit.group(0)!r}) — that belongs to the "
                    "reference sheet, not to the character. A clean studio turnaround renders "
                    "fine, so this is about the BRIEF not introducing the artefact rather than "
                    "about the sheet being risky")
                break

    # An attribute that names a stance, an emotion or an intention is an interpretation, not an
    # observation. It is how a walking posture became "fists clenched in a fighting stance" and
    # arrived in a corridor as combat readiness.
    for section, body in (("subject_definitions", defs), ("retention_analysis", ret)):
        for pat in INFERRED_ATTRIBUTES:
            hit = pat.search(body)
            if hit:
                add("R14-inferred-attribute", "WARN",
                    f"{section} states an interpretation rather than an observation "
                    f"({hit.group(0)!r}); describe what is visible, not what it means")
                break

    # ---------------------------------------------------------------- role/marker coupling
    # The gap the prior-art sweep found unclaimed: marker LEGALITY against the declared role,
    # not merely whether the marker is in the enum.
    for label, role, marker in ctx.declared_roles:
        entry = re.search(rf"^\s*{re.escape(label)}\s*(\([^)]*\))?\s*:\s*(\w+)", ret, re.M)
        if not entry:
            continue
        got = entry.group(2)
        if role in ("frame_anchor_first", "frame_anchor_last") and got != "fully_preserved":
            add("R6-anchor-must-be-preserved", "ERROR",
                f"{label} is a frame anchor, which requires fully_preserved, not {got!r} — a "
                "concrete frame cannot be partially kept")
        if label.startswith("<Picture") and got == "attribute_transfer":
            add("R7-picture-cannot-transfer", "ERROR",
                f"{label} is a Picture role and cannot silently carry attribute_transfer")
        if role == "edit_source" and got not in ("fully_preserved", "partially_preserved"):
            add("R8-edit-source-marker", "ERROR",
                f"{label} is an edit source; {got!r} is not a coherent claim about it")

    # An invented PROVENANCE claim. The first video+audio brief anyone compiled wrote "<Audio 1> is the
    # ambient sound track from <Video 1>" for an audio asset wired standalone (`ref_audio_1`), not as
    # that video's soundtrack (`ref_video_audio_1`). The model cannot know the wiring and guessed from
    # the fact that both existed; the runtime pairing is a fact this layer holds, so the guess is
    # checkable. Nothing here can hear, which makes an invented claim about an audio asset the exact
    # class of error the whole audio path is built to refuse.
    # Fires on a POSITIVE fact only. The first version keyed off `paired_audio` being empty, which
    # conflates "the wiring says these are not paired" with "nobody told us" -- and it fired on
    # MiniMax's own published Ref2VA example, whose control declares no pairing while the example's
    # audio genuinely IS that video's track. Same false positive as L5: absence of information read as
    # a negative claim. `standalone_audio` is the compiler asserting which labels it KNOWS are
    # unpaired, so a caller who supplies nothing gets no finding.
    for m in re.finditer(r"(<Audio\s+\d+>)[^.\n]{0,80}?\b(?:from|of|track of)\s+(<Video\s+\d+>)", defs):
        a_label, v_label = m.group(1), m.group(2)
        if a_label in ctx.standalone_audio:
            # Says what to write INSTEAD. The first version named the fault and not the fix, and it
            # survived both correction rounds on a real request before forcing a fallback -- a
            # finding that survives is a signal about the finding.
            add("R21-audio-provenance-invented", "ERROR",
                f"{a_label} is claimed to come from {v_label}, and the wiring does not pair them — "
                f"{a_label} is attached on its own. Rewrite the definition with no source claim at "
                f"all: say what {a_label} IS and what it is for, using only the note supplied for "
                f"it, and delete the words 'from {v_label}'. Nothing here can hear the asset, so its "
                "provenance is only what the manifest says it is")

    # Audio marker legality against the audio ROLE. Visual markers have had this since R6-R8; audio
    # never did, and the edit case demonstrated the gap on real output -- a `voice_timbre` reference
    # came back as `fully_copy`, claiming the whole clip becomes the target's final audio track when the
    # declared role is "only the timbre is referenced". Same citation as the visual rules, ref-en.txt 4:
    # "Choose each relationship marker only within the reference role already defined for that label in
    # subject_definitions", read against the marker table's own definitions -- `reference` is "the signal
    # is not copied directly; only timbre, rhythm, music style, dialogue content, or sound texture", and
    # `fully_copy` is the complete final track.
    #
    # Narrow on purpose: only the two roles whose definition IS "a property is referenced, not the
    # signal". `bgm` and paired soundtracks legitimately copy, and nothing here legislates them.
    for label, role, _marker in ctx.declared_roles:
        if role not in ("voice_timbre", "sfx"):
            continue
        entry = re.search(rf"^\s*{re.escape(label)}\s*(\([^)]*\))?\s*:\s*(\w+)", ret, re.M)
        if entry and entry.group(2) in ("fully_copy", "partially_copy"):
            add("R22-audio-marker-role", "ERROR",
                f"{label} is wired as {role}, which references a property rather than copying the "
                f"signal, and the brief claims {entry.group(2)!r} — that marker says the clip becomes "
                "the target's audio. Use 'reference', or 'weak_reference' for broad similarity only")

    if len(re.findall(r":\s*fully_copy\b", ret)) > 1:
        add("R9-multiple-full-copies", "ERROR",
            "more than one <Audio N> claims fully_copy; only one audio can be the complete "
            "final track")

    if is_ref and ctx.forbid_keyframe_refs:
        for phrase in ("first frame", "last frame"):
            if re.search(rf"\bis the {phrase} of\b", defs, re.I):
                add("R10-mode-role-contamination", "ERROR",
                    f"a Ref2VA brief declares a {phrase} anchor; keyframe anchors belong to the "
                    "FL2VA checkpoint, so this mixes two modes' roles")

    for label, video_label, a_secs, v_secs in ctx.paired_audio:
        if a_secs is not None and v_secs is not None and a_secs + 0.05 < v_secs:
            add("A6-paired-audio-short", "WARN",
                f"{label} is {a_secs:.2f}s but {video_label} is {v_secs:.2f}s; a paired "
                "soundtrack that does not cover its video desyncs silently")

    # ---------------------------------------------------------------- timeline
    shots = re.findall(r"\[Shot\s+(\d+)\]([^\[]*)", desc)
    if not shots:
        add("T1-no-shot", "ERROR", f"{main_field} has no [Shot N] marker")
    seen: list[tuple[int, float]] = []
    nums = []
    for num, body in shots:
        n = int(num)
        nums.append(n)
        head = body[:70]
        ts = re.match(r"\s*,?\s*At\s+(\d{2}):(\d{2})\.(\d{3})", head)
        loose = re.match(r"\s*,?\s*At\s+(\d+)[.:](\d+)", head)
        if n == 1:
            if ts or loose:
                add("T2-shot1-timestamp", "ERROR", "[Shot 1] must not carry a timestamp")
        elif ts:
            seen.append((n, int(ts.group(1)) * 60 + int(ts.group(2)) + int(ts.group(3)) / 1000))
        elif loose:
            add("T3-timestamp-format", "ERROR",
                f"[Shot {n}] time must be MM:SS.mmm, got 'At {loose.group(1)}.{loose.group(2)}'")
        else:
            add("T4-missing-cut-time", "ERROR", f"[Shot {n}] has no 'At MM:SS.mmm' cut time")
    if nums and nums != list(range(1, len(nums) + 1)):
        add("T8-shot-numbering", "ERROR", f"shot numbers must be contiguous from 1, got {nums}")
    for i in range(1, len(seen)):
        if seen[i][1] <= seen[i - 1][1]:
            add("T5-non-increasing", "ERROR",
                f"[Shot {seen[i][0]}] cut time {seen[i][1]} is not greater than the previous cut")
    if ctx.duration_s is not None:
        for n, t in seen:
            if t >= ctx.duration_s:
                add("T6-time-past-end", "ERROR",
                    f"[Shot {n}] cuts at {t:.3f}s, at or beyond the real duration "
                    f"{ctx.duration_s:.3f}s — the render never reaches it")
        if not is_on_grid(ctx.duration_s):
            add("T7-illegal-duration", "ERROR",
                f"{ctx.duration_s}s is {frames_for(ctx.duration_s)} frames, which is not on the "
                f"17k+5 alignment grid; nearest aligned {nearest_on_grid(ctx.duration_s):.3f}s")
        else:
            n = frames_for(ctx.duration_s)
            if not (TRAINED_BAND_FRAMES[0] <= n <= TRAINED_BAND_FRAMES[1]):
                add("T10-outside-trained-band", "INFO",
                    f"{n} frames ({ctx.duration_s:.3f}s) is outside the node's stated trained "
                    f"band of {TRAINED_BAND_FRAMES[0]}-{TRAINED_BAND_FRAMES[1]} frames; that is a "
                    "note about training, not a limit — it renders, just slower")

    # A subject scoped to [Shot N] must actually be cited in that shot's prose, or the
    # retention contract and the description contradict each other.
    shot_bodies = {int(n): b for n, b in shots}
    for m in re.finditer(r"^\s*(<Subject\s+\d+>)\s*\(appears in ([^)]*)\)", ret, re.M):
        label, scope = m.group(1), m.group(2)
        for sn in {int(x) for x in re.findall(r"\[Shot\s+(\d+)\]", scope)}:
            body = shot_bodies.get(sn)
            if body is not None and label not in body:
                # INFO, not WARN: MiniMax's own example scopes its coffee-shop environment to
                # all three shots and re-cites it in none of them, which is correct writing --
                # a persistent setting does not need re-labelling. Text alone cannot tell an
                # environment from an actor, so the actor case is checked in the compiler where
                # the subject's kind is known (X7-subject-not-cited).
                add("R11-scope-not-cited", "INFO",
                    f"{label} is scoped to [Shot {sn}] but that shot's description never cites "
                    "it (fine for a persistent setting, suspect for an actor)")

    if ctx.require_start_at_zero and shots and shots[0][0] == "1":
        # the opening shot carries no timestamp, so "starts at zero" is the absence of one;
        # a leading elapsed-time clause contradicts it
        if re.match(r"\s*(?:,\s*)?(?:after|from)\s+\d", shots[0][1], re.I):
            add("T9-first-shot-not-at-zero", "ERROR",
                "[Shot 1] must begin at 0.000 s; its description opens by displacing the start")

    # The style opening has now produced three separate grammar bugs ("anime style style",
    # "style with resembling ...", "in anime style with cinematic."), so it gets a rule on the
    # ASSEMBLED sentence instead of another one-off fix at each source.
    opening = (desc.split("[Shot 1]")[0].strip() if "[Shot 1]" in desc else "")
    if opening:
        for pat, why in STYLE_OPENING_FAULTS:
            hit = pat.search(opening)
            if hit:
                add("R16-style-opening-malformed", "ERROR",
                    f"the style opening is malformed — {why} ({hit.group(0)!r}): {opening[:90]!r}")
                break

    # Did the transformation actually travel? R16 checks the opening's GRAMMAR and P1 checks it
    # EXISTS; until now nothing checked what it says. That was the only unverified channel, and since
    # the retention marker stopped carrying the intent (§43) it is the ONLY channel -- exactly the
    # shape §41 already burned us on: the caller asked for a departure and silently got the
    # reference's style back, with no finding at all.
    #
    # **Detects the FAILURE, never confirms the success, and that asymmetry is measured rather than
    # cautious.** `classify_medium("1990s cel animation")` is None -- the targets a transformation
    # names are routinely outside the closed vocabulary, which is why `transform_target` reads them
    # from the request in the first place. So a rule demanding the opening MATCH the requested medium
    # would fire on the very requests it exists to serve. What is decidable is the one bad outcome:
    # the opening came back in the REFERENCE's medium bucket. `ctx.transformed_from` carries that
    # bucket and is set only when a transformation was asked for and the two buckets actually differ.
    #
    # WARN, by §40's test, decided before shipping rather than after four narrowings. Right: the model
    # rewrites one sentence, decidable, converges. Wrong: the opening already names the requested
    # medium and the classifier misbucketed it -- the model has nothing to change, both rounds
    # exhaust, and the whole written brief is lost to the fallback. Same shape as the phrase blacklist
    # that demoted G2. A false positive here must cost nothing.
    if opening and ctx.transformed_from:
        from .style import classify_medium
        if classify_medium(opening) == ctx.transformed_from:
            add("R23-transformation-not-in-style-opening", "WARN",
                f"the request asked to depart from the reference's medium, but the style opening "
                f"still reads as {ctx.transformed_from} — the transformation did not reach the one "
                f"section that carries it: {opening[:90]!r}")

    # A cut across which NOTHING STATED CHANGES. This rule was rewritten after it was caught
    # encoding taste: the previous version fired when two shots shared a coarse framing/action/
    # camera signature, which a competent director can legitimately disagree with -- two beats of
    # one walk at one distance revealing different things is a defensible edit, and the rule called
    # it an error. Shot count is not a defect and similarity is not a defect.
    #
    # What IS decidable is the spec's own sentence (base-en.txt 4.2): "A cut should introduce new
    # information about the subject, space, state, viewpoint, or time. If only the distance or a
    # slight angle needs to change, prefer camera motion." So the test is literal: the later shot
    # states nothing the earlier one did not. Same framing, same camera, same labels, same dialogue
    # state, and not one content word of its own. Prose almost never satisfies that, which is the
    # point -- it fires on degenerate repetition (a real and silent LLM failure mode) and abstains
    # on every judgement call. WARN, because the spec says "should" and because ERROR would send
    # this back to the model in the fix loop and have it rewrite a legitimate edit.
    if len(shots) > 1:
        for (pn, pbody), (num, body) in zip(shots, shots[1:]):
            psig, sig = _shot_signature(pbody), _shot_signature(body)
            if psig != sig or not any(sig):
                continue
            if _labels_cited(pbody) != _labels_cited(body):
                continue
            if bool(re.search(r"<d>", pbody)) != bool(re.search(r"<d>", body)):
                continue
            novel = _content_words(_strip_verbatim(body)) - _content_words(_strip_verbatim(pbody))
            if novel:
                continue
            add("R17-cut-states-nothing-new", "WARN",
                f"the cut into [Shot {num}] states nothing [Shot {pn}] had not already stated — "
                f"same framing, same camera, same labels and no content word of its own. The spec "
                "asks a cut to introduce new information about subject, space, state, viewpoint or "
                "time; if only the distance changes, camera motion says it without a cut")
            break

    # ---------------------------------------------------------------- prose craft
    if is_ref:
        first = desc.split("[Shot 1]")[0].strip() if "[Shot 1]" in desc else ""
        if not first:
            add("P1-no-style-opening", "ERROR",
                "Ref2VA needs one or two style sentences on their own line before [Shot 1]")
    else:
        m = re.match(r"\s*\[Shot 1\]\s*([^.]*)", desc)
        if m and not m.group(1).strip():
            add("P6-no-style-in-shot1", "WARN",
                "base modes establish style inside [Shot 1]; nothing follows the marker")

    words = len(re.findall(r"\b[\w'-]+\b", desc))
    # The 350-500 range is stated for Ref2VA detailed_description only; the base guide gives
    # no range, and MiniMax's own published T2VA is 251 words. Applying it to base modes would
    # flag the spec's own artifact, so it is scoped to ref2va generation tasks.
    #
    # WARN, permanently. Do not promote either of these and do not let them trigger a repair: the
    # spec that states the range also states its own escape clauses -- "normally 350-500",
    # "prioritizes fitting the complete spoken timeline rather than mechanically reaching a word
    # count", "a single shot does not automatically justify a shorter description" -- and MiniMax's
    # own Ref2VA example is 336 words against their own floor. Length correlates with quality in
    # neither direction here: a 274-word brief directed well and a 636-word one did not.
    if is_ref and ctx.generation_task and words < 300:
        add("P2-too-short", "WARN",
            f"{main_field} is {words} words; spec guidance 350-500, official example 336")
    elif words > 700:
        add("P3-too-long", "WARN", f"{main_field} is {words} words; spec guidance 350-500")

    # Camera reporting is graded rather than pass/fail, because the closed vocabulary is a
    # plausible lever that nobody uses AND the spec's own example ignores it. The grades are
    # what the A/B needs to measure; none of them is an error.
    has_amp_speed = bool(re.search(r"with (small|large) amplitude|at (slow|fast) speed", desc, re.I))
    # Bare stems match ordinary prose -- "pulls the dog back" and "rolled-up sleeves" made the
    # official example look on-vocabulary, so the control was passing for the wrong reason. A
    # motion type counts only in canonical form, or as a stem inside a clause about the camera.
    has_motion = bool(CAMERA_MOTION_PHRASE.search(desc)) or any(
        CAMERA_STEM_IN_CONTEXT.search(clause)
        for clause in re.split(r"(?<=[.!?])\s+", desc)
        if re.search(r"\b(?:camera|shot|lens|frame)\b", clause, re.I))
    # ERROR, but NOT on the grounds it was previously given. The stated basis was "H3 drifts and
    # reframes when the camera is unspecified"; that claim traces to a single community author's
    # sysprompt line and this project's own prior-art sweep recorded it as UNVERIFIED and
    # single-source. A rule may not rest on that.
    #
    # It rests on the spec instead, which is enough on its own:
    #   * base-en.txt 4.3 defines a closed camera vocabulary and the exact idiom to write it in.
    #   * All five of base-en.txt's worked examples state a camera motion -- there is no shipped
    #     example of a brief that leaves the camera unstated.
    #   * `Static Shot` is itself a member of that vocabulary, so there is no such thing as a shot
    #     with no camera state. Silence is not "the camera is still", it is an unstated variable.
    #   * base-en.txt 4.2's "if only the distance or a slight angle needs to change, prefer camera
    #     motion" presupposes a stated camera.
    # ref-en.txt's own Ref2VA example omits a motion type; that is the spec disagreeing with itself,
    # recorded as the one documented control exception rather than treated as licence.
    #
    # This is the one complaint in its class that is mechanical: absence of a required field, not a
    # judgement about the writing.
    if not re.search(r"\bcamera\b|\bshot\b", desc, re.I):
        add("P4-no-camera-at-all", "ERROR",
            "the camera is never described; H3 drifts and reframes on its own when it is "
            "unspecified, so an unstated camera is a defect rather than a stylistic choice")
    elif not has_motion:
        add("P5-camera-no-motion-type", "ERROR",
            "framing is described but no motion type from the closed vocabulary appears "
            "(Push In / Pull Out / Pan / Truck / Tilt / Static Shot / ...). Every shot needs a "
            "stated camera or the model chooses its own")
    elif not has_amp_speed:
        add("P5b-camera-no-amplitude", "INFO",
            "a motion type appears but without the 'with <small|large> amplitude at "
            "<slow|fast> speed' idiom the spec defines")

    # Three defects the write-first path produced that no rule caught. All three are the same
    # family: something that looks like an instruction but is not one.
    #
    # 1. Camera as a metadata header. "Camera: Push In, slow speed, large amplitude." on its own
    #    line is a label stack, which base-en.txt 4.3 explicitly forbids -- camera belongs in the
    #    sentence as an action. The bar weaves it into what the move reveals; a header is the same
    #    mistake the template made, in a different coat.
    for m in CAMERA_LABEL_STACK.finditer(desc):
        add("R18-camera-as-label-stack", "ERROR",
            f"camera is stated as a metadata header ({m.group(0)[:40]!r}); the spec requires it "
            "written as an action inside the shot, joined to what the move reveals")
        break

    # 2. A bare subject NAME is not a label. "Subject 1 walks forward" references nothing: the
    #    binding is the angle brackets, and this is the <Image 1> failure wearing another shape.
    bare = BARE_SUBJECT_NAME.findall(_strip_verbatim(desc)) + \
        BARE_SUBJECT_NAME.findall(_strip_verbatim(ret))
    if bare:
        add("R19-bare-subject-name", "ERROR",
            f"{len(bare)} reference(s) to a subject by bare name ({bare[0]!r}) instead of its "
            "label; only <Subject N> binds to the attached reference")

    # 3. A camera move contradicting its own description. "Push In" with "moves backward" is not a
    #    style choice; the model will do one of the two and there is no way to know which.
    for pat, why in CAMERA_CONTRADICTIONS:
        m = next((x for x in pat.finditer(desc) if _contradiction_is_real(x.group("gap"))), None)
        if m:
            add("R20-camera-contradiction", "ERROR",
                f"the camera move contradicts its description — {why} ({m.group(0)[:60]!r})")
            break

    # ---------------------------------------------------------------- dialogue
    if desc.count("<d>") != desc.count("</d>"):
        add("D1-unbalanced-d", "ERROR", f"{desc.count('<d>')} <d> vs {desc.count('</d>')} </d>")
    for variant in ("<D>", "</D>", "< d >", "<d >", "< d>"):
        if variant in text:
            add("D5-marker-not-byte-exact", "ERROR",
                f"{variant!r} is not the marker; it must be exactly '<d>' / '</d>' or the "
                "token sequence changes")
    blocks = re.findall(r"<d>(.*?)</d>", desc, re.S)
    for blk in blocks:
        m = re.match(r"\s*\[([A-Za-z][^\]]*)\]", blk)
        if not m:
            add("D2-missing-lang-tag", "ERROR", f"<d> block lacks a [Language] tag: {blk[:40]!r}")
        # D6-unusual-language REMOVED by the source audit. It reported that a language tag was
        # "outside H3's 11 stably-supported languages", and that list has no traceable source: it is in
        # neither spec document, neither the plumbing audit nor the prior-art sweep, and the only thing
        # behind it was a comment asserting it. An INFO that states a fact about the model is still
        # stating a fact about the model. The language TAG requirement stays (D2) -- that one is stated,
        # in ref-en.txt 7: "Write dialogue and lyrics as `<d>[Language] ...</d>`".
        if re.search(r"[~•…]|[!?.]{2,}|[\U0001F300-\U0001FAFF]", blk):
            add("D7-decorative-punctuation", "WARN",
                f"<d> content should carry only basic punctuation: {blk[:40]!r}")
    for want in ctx.expected_dialogue:
        if want and not any(want in b for b in blocks):
            add("D4-dialogue-not-verbatim", "ERROR",
                f"user line is missing or altered inside <d>: {want[:60]!r}")
    sids = sorted({int(x) for x in re.findall(r"\(S(\d+)(?:\s*,\s*S\d+)*\)", desc)})
    if sids and sids[0] != 1:
        add("D3-speaker-numbering", "ERROR", f"speaker IDs start at S{sids[0]}, must start at S1")
    if sids and sids != list(range(1, len(sids) + 1)):
        add("D8-speaker-gap", "WARN", f"speaker IDs are not contiguous: {sids}")
    for m in re.finditer(re.escape(VOICEOVER_PHRASE), desc):
        tail = desc[m.end():m.end() + 400]
        if not LIPS_CLOSED.search(tail):
            add("D9-voiceover-no-lips-clause", "ERROR",
                "every voiceover <d> must be followed by a statement that the on-screen "
                "character's lips remain closed")

    # ---------------------------------------------------------------- sound
    sound = sec.get("overall_soundscape", "")
    music = sec.get("non_diegetic_music", "")
    # A1 is RESTORED, and its deletion was my error. I removed it having searched only ref-en.txt,
    # wrote in the design doc that "the spec says no such thing" and that the number was mine, and so
    # deleted a legitimate rule on a false confession. The numbers are stated, in base-en.txt:
    #
    #   4.6  "Use 1-4 English sentences in one continuous paragraph to summarize the ambient sound..."
    #   4.7  "Use 1-3 English sentences to describe background music..."
    #
    # ref-en.txt 6 does not restate them because it explicitly DEFERS: "The definitions of these two
    # sound categories follow the Video Prompt Writing Guide (T2VA / I2VA / FL2VA / L2VA)". Silence in
    # ref-en is a pointer, not an absence -- the same mistake as reading an empty `paired_audio` as
    # "not paired" (R21) and a standalone source line as always illegal (L5). Third instance tonight of
    # treating one document's silence as the specification's.
    #
    # WARN, because length is never a gate here and the spec phrases both as instructions.
    def _sentences(text: str) -> int:
        return len([x for x in re.split(r"(?<=[.!?])\s+", text.strip()) if x.strip()])

    if sound.strip() not in ("", "N/A") and _sentences(sound) > 4:
        add("A1-soundscape-length", "WARN",
            f"overall_soundscape is {_sentences(sound)} sentences; base-en.txt 4.6 says 1-4")
    if music.strip() not in ("", "N/A") and _sentences(music) > 3:
        add("A7-music-length", "WARN",
            f"non_diegetic_music is {_sentences(music)} sentences; base-en.txt 4.7 says 1-3")
    if sound.strip() not in ("", "N/A"):
        # Measure the overlap rather than matching the word "sound": the phrase heuristic fires
        # on ordinary prose and misses actual duplication that uses different verbs.
        shared = _shared_phrase(_strip_verbatim(desc), sound, 5)
        if shared:
            add("A2-sound-duplicated", "WARN",
                f"overall_soundscape repeats a phrase already in the description: {shared!r}")
        else:
            # Containment, not Jaccard: what share of the soundscape's own vocabulary also
            # appears in the description. Two sentences about the same rainy street legitimately
            # share "rain" and "street", and the sync/ambient partition already guarantees no
            # shared EVENT -- so this is deliberately loose. The shared-phrase check above is
            # the strong signal; this one only catches wholesale restatement.
            # The 65% is a proxy for a real spec rule (ref-en.txt 6 partitions synchronized events
            # into detailed_description and ambience into overall_soundscape), not a rule itself.
            # Stays WARN for that reason: the partition is the spec's, the number is mine.
            overlap = _content_overlap(sound, _strip_verbatim(desc))
            if overlap > 0.65:
                add("A2-sound-duplicated", "WARN",
                    f"{overlap:.0%} of overall_soundscape's content words also appear in the "
                    "description; it reads as a restatement rather than a separate layer")
    if re.findall(r"<d>.*?</d>", sound + music, re.S):
        add("A3-dialogue-outside-desc", "ERROR",
            "complete dialogue belongs only in the main description")
    if ctx.require_music_na is True and music.strip() != "N/A":
        add("A4-music-should-be-na", "ERROR",
            "no non-diegetic music was requested, so non_diegetic_music must be exactly 'N/A'")
    if music.strip() and music.strip() != "N/A":
        if not re.search(r"\b(tempo|beat|bpm|slow|fast|moderate|rhythm)\b", music, re.I):
            add("A5-music-no-tempo", "INFO",
                "non_diegetic_music should state instrumentation, tempo and dynamics")

    # ------------------------------------------------------------ proportionality (the dial)
    # "If I ask for simple, I want simple, if I say go crazy, I want crazy." An output that adds
    # content the request never supplied is not better output -- it is not doing what was asked.
    #
    # Only three elements, and each is here because its source can only be the model: words for a
    # character to speak, a score for the audience, text burned into the frame. Shot count, cuts and
    # camera moves are NOT on this list at any setting -- they are how the same content is shown, and
    # putting them here would be shot count re-entering the validator through a side door.
    if ctx.scope is not None:
        present = {
            SPEECH: bool(re.search(r"<d>", text)),
            SCORE: music.strip() not in ("", "N/A"),
            # quoted spans that are not dialogue: what the frame will actually render as lettering
            ONSCREEN_TEXT: bool(re.findall(r'"[^"]*"', re.sub(r"<d>.*?</d>", " ", desc, flags=re.S))),
        }
        for element, is_present in present.items():
            if not is_present or ctx.scope.permits(element):
                continue
            if element in ctx.scope.forbidden:
                # Highest-confidence rule in this family: the caller said no and it is there anyway.
                # Its own id, because the fix is unambiguous and the message must say who forbade it.
                add("Q1-forbidden-element-present", "ERROR",
                    f"the request explicitly ruled out {element} and the brief contains it; no "
                    "creativity setting overrides an explicit prohibition")
            else:
                add("Q2-unlicensed-addition", "ERROR",
                    f"the brief adds {element}, which {ctx.scope.why_not(element)}. Proportionality "
                    "is part of the bar: a plain request gets a plain answer, and content the "
                    f"request never supplied is not an improvement ({ctx.scope.note()})")

        # The one position whose own setting defines what correct means, which is why this can be a
        # check at all: `extreme` asks for the far end of a CLOSED vocabulary, so "is this brief at
        # the far end" is countable rather than a judgement. A director who wanted a slow push would
        # have asked for `bold`; at `extreme` they asked for the boldest value available.
        #
        # Silence fails it too, and that is the spec's own doing: base-en.txt 4.3 omits amplitude and
        # speed to MEAN medium and normal, so a brief that states neither is played at the middle.
        #
        # Deliberately wholesale-only. "None of the maximal values appears anywhere" is a fact; "not
        # enough of them appear" would be a threshold, and a threshold is where taste re-enters.
        # `extreme` ONLY. A check for `bold` existed briefly and was removed: "bold just means if a
        # little nudge can do it, don't mechanically enforce it". So the dial owns exactly one rule at
        # the top and one at the bottom (Q2), and the two middle positions are unverified by design --
        # see the asymmetry note in creativity.py before adding anything here.
        if ctx.scope.magnitude in COMMITS_CAMERA and re.search(r"\bcamera\b", desc, re.I):
            if not any(v in desc.lower() for v in MAXIMAL_CAMERA):
                add("Q3-extreme-not-honoured", "ERROR",
                    "the creativity setting is `extreme`, which asks for the far end of the "
                    "format's camera vocabulary, and the brief states no 'with large amplitude' and "
                    "no 'at fast speed' anywhere — omitting them means medium and normal by the "
                    "guide's own default, so the shot is played at the middle. State the maximal "
                    "values, or the setting had no effect")
            # NOTHING forbids a quiet move here. A rule that did (Q4-extreme-not-committed) was built
            # and removed by the owner: "hold, hold, then hit is how a lot of real direction works",
            # and a setting that forbids the hold cannot express the hit. `extreme` reaches for big
            # and fast; it is not obliged to be uniformly loud.

    # ---------------------------------------------------------------- reasoning leakage
    # vLLM #35221 puts in-progress reasoning into `content` when generation truncates before
    # `</think>`; #39697 injects the reasoning-end string mid-content. On a thinking model this
    # is an expected input, so it is a rule rather than a surprise.
    for marker in ("<think>", "</think>", "<reasoning>", "</reasoning>", "assistantfinal"):
        if marker in text:
            add("G1-reasoning-leaked", "ERROR",
                f"{marker!r} appears in the prompt — this is leaked reasoning, not a brief "
                "(vLLM #35221 / #39697); fall back to the deterministic draft")
    scrubbed_prose = _strip_verbatim(desc)
    # WARN, not ERROR, and the reason is a severity heuristic worth stating generally:
    #
    #   A CHECK WHOSE FALSE POSITIVE IS UNFIXABLE BY THE THING BEING CHECKED MUST NOT BE AN ERROR.
    #
    # ERROR means "the model can repair this". When G2 is right, it can. When G2 is WRONG there is
    # nothing wrong in the text, so the model cannot converge, so the loop exhausts its rounds and the
    # ENTIRE written brief is lost to the fallback. A false WARN costs nothing, and a true positive is
    # still reported -- leaked self-narration is the sort of thing a human spots instantly in the text.
    #
    # Four narrowings are their own evidence: a rule needing repeated tightening is a rule whose
    # detection does not match its concept. G1 stays ERROR because an explicit `<think>` marker cannot
    # be a false positive -- the detection there cannot be wrong.
    #
    # Deliberately narrow. An earlier draft of this rule matched bare "okay" and "the request",
    # which fire on ordinary description ("he gives an okay sign", "he ignores the request") --
    # a false positive here costs a valid brief, since the penalty is falling back to the draft.
    # Kept: phrases with no third-person-scene reading outside dialogue, which is already
    # stripped. Anchored where the leak actually appears (the opening of the reply).
    for pat, why in (
        (r"\b(?:I'll|I will|let me|we should|I need to|I should)\b",
         "first-person planning language"),
        (r"\b(?:the user|per the (?:spec|instructions|guide)|as requested)\b",
         "meta-commentary about the request"),
    ):
        m = re.search(pat, scrubbed_prose, re.I)
        if m:
            add("G2-model-self-narration", "WARN",
                f"{why} in the description ({m.group(0)!r}) — the model narrated its plan "
                "inside the deliverable")
    # A self-narrating opener lands at the START of a generated block, which after rendering is
    # the start of a shot body. Anchoring there keeps "he gives an okay sign" legal mid-sentence.
    for num, body in shots:
        opener = re.sub(r"^\s*(?:At\s+\d{2}:\d{2}\.\d{3},?\s*)?", "", _strip_verbatim(body))
        m = re.match(r"\s*(okay|alright|sure|got it|here'?s|certainly|of course)\b", opener, re.I)
        if m:
            add("G2-model-self-narration", "WARN",
                f"[Shot {num}] opens with {m.group(1)!r} — a self-narrating preamble, not a shot")

    # Wardrobe drift between GENERATIONS is real and locally observed -- an H3 render came back in
    # olive-grey trousers where the sheet has blue jeans, and every later test inherited it. Drift
    # between SHOTS OF ONE CLIP, which is what this rule guards, traces to the same single community
    # author as the camera claim and is unverified here. Restating the garments in every shot is
    # also a real prose cost a director may legitimately refuse. So: WARN, never more, until the
    # per-shot claim is measured rather than inherited.
    if ctx.wardrobe_terms:
        for num, body in shots:
            if not re.search(r"<Subject\s+\d+>", body):
                continue
            if not any(w.lower() in body.lower() for w in ctx.wardrobe_terms):
                add("R15-wardrobe-not-restated", "WARN",
                    f"[Shot {num}] names the subject but not the garments "
                    f"({', '.join(ctx.wardrobe_terms[:3])}); wardrobe drifts between shots when "
                    "it is only stated once")

    # ---------------------------------------------------------------- hygiene
    hazards = sorted({c for c in UNICODE_HAZARDS if c in scrubbed})
    if hazards:
        add("H1-unicode-hazard", "ERROR",
            "structural text contains characters that change tokenization: "
            + ", ".join(f"U+{ord(c):04X} (use {UNICODE_HAZARDS[c]!r})" for c in hazards))
    for s in ctx.onscreen_text:
        if s and f'"{s}"' not in text:
            add("H2-onscreen-text-unquoted", "WARN",
                f"on-screen text should appear verbatim in straight double quotes: {s[:40]!r}")

    if ctx.prompt_tokens is not None:
        lo, hi = ctx.token_budget
        if not (lo <= ctx.prompt_tokens <= hi):
            add("H3-token-band", "WARN",
                f"prompt is {ctx.prompt_tokens} tokens, outside the {lo}-{hi} band "
                "(published hosted IRs are 537-919); distribution drift, not a cost problem")

    # ---------------------------------------------------------------- loras
    for trig in ctx.lora_triggers:
        want_text = trig.get("text", "")
        want_n = int(trig.get("count", 1) or 1)
        if not want_text:
            continue
        got = scrubbed.count(want_text)
        if got == 0:
            # W, not X: these are LoRA rules that happen to live in the validator. The
            # prefix tracks what a rule is ABOUT, not which file emits it.
            add("W2-lora-trigger-missing", "ERROR",
                f"LoRA trigger {want_text!r} never reached the prompt text — the LoRA will be "
                "loaded and have no effect")
        elif got != want_n:
            add("W3-lora-trigger-count", "WARN",
                f"LoRA trigger {want_text!r} appears {got}x, expected {want_n}x "
                "(a common-word trigger may be leaking into content prose)")
        slot = trig.get("slot", "style")
        if slot == "style" and got:
            head = (desc.split("[Shot 1]")[0] if is_ref else desc[:220])
            if want_text not in head:
                add("W4-lora-trigger-slot", "ERROR",
                    f"LoRA trigger {want_text!r} is present but not in the style slot "
                    f"({'style line before [Shot 1]' if is_ref else '[Shot 1] style prefix'})")

    return f


# --------------------------------------------------------------------------- reporting

@dataclass
class Report:
    name: str
    findings: list[Finding] = field(default_factory=list)

    @property
    def errors(self):
        return [x for x in self.findings if x.severity == "ERROR"]

    @property
    def warnings(self):
        return [x for x in self.findings if x.severity == "WARN"]

    @property
    def infos(self):
        return [x for x in self.findings if x.severity == "INFO"]

    @property
    def verdict(self) -> str:
        if self.errors:
            return "FAIL"
        return "PASS (with warnings)" if self.warnings else "PASS"

    def text(self, show_info: bool = False) -> str:
        lines = [f"{'=' * 74}", f"{self.name}",
                 f"  -> {self.verdict}   {len(self.errors)} error(s), "
                 f"{len(self.warnings)} warning(s), {len(self.infos)} info",
                 f"{'=' * 74}"]
        shown = self.errors + self.warnings + (self.infos if show_info else [])
        lines += [f"  {x}" for x in shown]
        return "\n".join(lines)
