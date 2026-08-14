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
from .grid import INSTRUCTION_OPENINGS, instruction_line_for, s_ss_text
from .models import (AMPLITUDES, AUDIO_MARKERS, CAMERA_TYPES, Finding, SPEEDS, TASK_TYPES,
                     VISUAL_MARKERS)

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

# base-en.txt 4.2's closed set for an ordinary cut, plus the three it allows only on an explicit
# request. Written as the spec writes them, because the trained token is the point: a synonym
# ("the framing changes and", "the scene cuts to", "the whip-pan resolves onto") is a near miss in
# exactly the way <Image 1> is a near miss for <Picture 1>.
CUT_PHRASES = ("the camera cuts to", "the shot cuts to", "the shot transitions to",
               "the shot changes to", "the shot switches to")
CUT_PHRASE_PRESENT = re.compile(
    "|".join([re.escape(p) for p in CUT_PHRASES]
             + [r"cross[- ]dissolve", r"\bfades?\s+(?:to|into|out)\b", r"\bwipes?\s+(?:to|across)\b",
                r"\bwipe reveals\b", r"\bwipe\b[^.]{0,20}\breveals?\b"]), re.I)

# The two dimensions base-en.txt 4.3 closes, checked for what is written rather than for what is
# missing. The old detector asked whether a LEGAL value was present, so an illegal one sitting beside
# it was invisible and a document carrying only an illegal one got an INFO saying the idiom was
# absent rather than that the value was wrong.
AMPLITUDES_WRITTEN = re.compile(r"\bwith\s+(\w+)\s+amplitude\b", re.I)
SPEEDS_WRITTEN = re.compile(r"\bat\s+(?:a\s+)?(\w+)\s+speed\b", re.I)

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

# "Do not use abstract mood words or explain the emotional function of the score" (base-en.txt 4.7).
# Two shapes: a word that names a feeling instead of a sound, and a clause that explains what the
# music is FOR. Words that describe the signal are deliberately absent from this list -- sparse,
# minimal, restrained, driving, sustained, muted are all properties of what is played.
MOOD_WORDS = re.compile(
    r"\b(?:melanchol(?:y|ic)|wistful|nostalgic|hopeful|hopeless|uplifting|triumphant|heroic|"
    r"epic|romantic|joyful|cheerful|sad|happy|tense|ominous|foreboding|sinister|menacing|eerie|"
    r"haunting|mysterious|dreamy|whimsical|playful|somber|sombre|brooding|serene|tranquil|"
    r"melodramatic|emotional|poignant|bittersweet|triumphal|"
    r"(?:creating|evoking|conveying|suggesting|underscoring|reinforcing|heightening)\s+"
    r"(?:a|an|the)?\s*[\w\s-]{0,30}?(?:mood|atmosphere|feeling|emotion|tension|sense)|"
    r"(?:mood|atmosphere|emotional\s+\w+)\s+of\s+the\s+(?:scene|video|piece))\b", re.I)

VOICEOVER_PHRASE = "says in an off-screen voiceover"
LIPS_CLOSED = re.compile(r"lips?\b[^.]*\b(closed|shut)", re.I)

# base-en.txt 4.4 mandates the statement and then offers four phrasings for it ("Continuity may be
# expressed with ..."), so the wording is open. Matched loosely for that reason: the four listed
# forms, plus the verbs they are built from, so a competent rewording still counts.
CONTINUITY_STATED = re.compile(
    r"\b(?:continue[sd]?|continuing|carries over|carrying over|carried over|remains audible|"
    r"uninterrupted|unbroken|seamlessly)\b", re.I)


def _consecutive_run(spoken: list[str], want: str) -> tuple[int, int] | None:
    """The shortest run of consecutive <d> blocks whose contents join back into `want`.

    Consecutive, not any subset: a line divided at a cut is divided in playback order, and allowing
    an arbitrary combination would let two unrelated blocks satisfy a line neither of them says.
    """
    for i in range(len(spoken)):
        for j in range(i + 1, len(spoken)):
            if want in " ".join(spoken[i:j + 1]):
                return i, j
    return None


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
    # (audio_label, transcript) for every attached recording the CALLER transcribed with a real
    # recogniser. Nothing here listens, so this is the only channel by which the words on a
    # recording are known, and ref-en.txt 5.4 governs where they may and may not appear.
    audio_transcripts: tuple[tuple[str, str], ...] = ()
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

    # ---------------------------------------------------------------- the instruction line
    # base-en.txt 2.1 prints it verbatim per mode and states two facts about it: it is the FIRST
    # line, followed by exactly one blank line, and its `S.SS` is "the effective video duration
    # formatted to exactly two decimal places". Nothing checked either, in any mode -- the one part
    # of the document the spec hands over as a literal string was the only part with no rule.
    #
    # ERROR, and safe at that severity because there is no legal variation to be wrong about: the
    # spec says "always uses" and prints the template, so the expected line is computable and the
    # message can simply show it. It is also repaired mechanically before this runs
    # (repair._fix_instruction_line), so reaching here means a path that skipped the repair.
    if ctx.mode in ("i2va", "fl2va", "l2va"):
        lines = text.strip().splitlines()
        first = lines[0].strip() if lines else ""
        last_shot = max((int(n) for n in re.findall(r"\[Shot\s+(\d+)\]", text)), default=1)
        if not first.startswith(INSTRUCTION_OPENINGS):
            add("I1-instruction-line-missing", "ERROR",
                f"a {ctx.mode} brief must open with the mandated alignment instruction, then one "
                f"blank line, then the core fields (base-en.txt 2.1). Expected:\n"
                + instruction_line_for(ctx.mode, last_shot,
                                       s_ss_text(ctx.duration_s) if ctx.duration_s else "S.SS"))
        else:
            if ctx.duration_s is not None:
                want = instruction_line_for(ctx.mode, last_shot, s_ss_text(ctx.duration_s))
                if first != want:
                    add("I2-instruction-line-not-exact", "ERROR",
                        f"the instruction line differs from the mandated one. Expected:\n{want}\n"
                        f"Got:\n{first}\n(`S.SS` is the effective duration to exactly two decimal "
                        "places, and `N` is the index of the actual final shot)")
            if len(lines) > 1 and lines[1].strip():
                add("I3-instruction-line-no-blank-line", "ERROR",
                    "the instruction line must be followed by one blank line before the core "
                    f"fields (base-en.txt 2.1); the next line is {lines[1][:60]!r}")

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

    # FL2VA cites its pictures BARE. base-en.txt says so twice -- the mandated instruction line in
    # 2.1 is `Picture 1 (from Shot 1) ...`, and its own published example in 5 keeps the bare form
    # right through the body -- while every other mode brackets (ref-en.txt brackets all twelve of
    # its citations, and the i2va and l2va instruction lines bracket too). Reading only the
    # bracketed form made every legal FL2VA citation invisible: `used["Picture"]` came out empty on
    # correct text, so L4 took its total-miss branch and the mode could not be compiled by either
    # path. MiniMax's own published FL2VA example fails identically, which is what says the rule was
    # wrong rather than the text.
    #
    # Read off the verbatim-stripped copy, unlike the bracketed scan above: nobody writes
    # `<Picture 2>` in a line of dialogue, but "Picture 2" is ordinary English, and a picture named
    # in the user's own words must not bind a conditioning image the brief never mentions.
    if ctx.mode == "fl2va":
        used["Picture"] |= {int(n) for n in re.findall(r"\bPicture\s+(\d+)", scrubbed_all)}

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
            add("M1-task-prefix", "ERROR",
                "summary must open with a [task type] prefix, before any other text: "
                "'[video editing] The target video is an edited version of <Video 1>. ...'")
        else:
            parts = [p.strip() for p in pref.group(1).split("+")]
            for p in parts:
                if p not in TASK_TYPES:
                    add("M2-task-type", "ERROR", f"'{p}' is not a legal task type")
            if len(parts) != len(set(parts)):
                add("M3-task-dupe", "ERROR", "task type repeated in the prefix")
            if "video editing" in parts:
                # The mandated sentence, allowed to CONTINUE. A full stop is what ref-en.txt 3
                # prints, and demanding it byte-exact rejected "The target video is an edited
                # version of <Video 1>, where the vehicle is changed to a white car" -- the same
                # mandated clause, carrying on into the specifics. The model then obeyed the finding
                # by prepending the sentence it had already written, and the brief shipped with it
                # twice. So a comma continuation satisfies the rule and the doubling is what gets
                # caught.
                opening = re.compile(r"The target video is an edited version of <Video \d+>\s*[.,]")
                hits = opening.findall(summ)
                if not used["Video"]:
                    add("M5-editing-without-video", "ERROR",
                        "'video editing' claimed but no <Video N> is referenced")
                elif not hits:
                    # "must open with" was read literally by the model it was sent to, which moved
                    # the sentence in FRONT of the task-type prefix and tripped M1 on the next
                    # round -- one finding manufacturing the next. The spec's own words are "For
                    # video-editing tasks, begin the summary AFTER the task-type prefix with", so
                    # the message now says that and shows the whole shape.
                    add("M6-editing-opening", "ERROR",
                        "a video-editing summary must contain the mandated opening sentence "
                        "immediately after the task-type prefix, and keep the prefix first: "
                        "'[video editing] The target video is an edited version of <Video 1>. ...' "
                        "(ref-en.txt 3: begin the summary after the task-type prefix with that "
                        "sentence; it may continue with a comma instead of stopping). Add the "
                        "sentence, do not move the prefix")
                elif len(hits) > 1:
                    add("M10-editing-opening-repeated", "ERROR",
                        f"the mandated editing sentence appears {len(hits)} times in the summary; "
                        "it is the opening, so it belongs once. Keep the first one and let the rest "
                        "of the paragraph say what the edit actually changes")
            # A second prefix mid-summary, which is how the fix loop's own output came back once the
            # message above was ambiguous: the model prepended the mandated sentence with a fresh
            # prefix and left its original one in place. Every existing rule passed -- M1 reads the
            # opening and M3 reads inside one bracket group -- and the doubled prefix shipped.
            # Counted only when a later bracket group is entirely task types, so '[Shot 1]' and any
            # other bracketed aside is untouched.
            for m in list(re.finditer(r"\[([^\]]+)\]", summ))[1:]:
                bits = [p.strip() for p in m.group(1).split("+")]
                if bits and all(b in TASK_TYPES for b in bits):
                    add("M9-task-prefix-repeated", "ERROR",
                        f"the task-type prefix appears again inside the summary ({m.group(0)!r}); "
                        "it belongs once, at the very start, and the rest of the paragraph is prose")
                    break
            # Both audio task types claim a relationship to an attached audio SIGNAL, so both are
            # unsupported when nothing is attached. The message says what to write instead, and
            # that is the fix rather than a nicety: this rule fired on 6 of 7 video-edit briefs and
            # survived both correction rounds every time, because naming the defect without naming
            # the remedy leaves the model to guess -- and the thing it is asserting ("the original
            # audio is preserved") is what a video edit MEANS, so it re-asserted it.
            #
            # The reason it is still wrong: ref-en.txt 2.5 says an ordinary reference video does
            # not create an <Audio N> merely because the file contains sound. The runtime takes a
            # video's soundtrack as a separate wired input, so with none wired the signal never
            # reaches the model and the target's audio is generated. Claiming reuse promises
            # something the render cannot do.
            # The same guard the other three task types have had, for the two that did not.
            # `M5-editing-without-video` protects `video editing`, M7 and M8 protect the two audio
            # types, and `keyframe completion` and `video continuation` protected nothing: seven
            # documents in the corpus claimed `keyframe completion` with only a wav attached, so the
            # prefix asserted a frame relationship to an asset that has no frames.
            #
            # Deliberately NOT a comparison against the types the wiring derives. A brief whose
            # caller declared a frame anchor on a ref2va route has that role downgraded (X10) and
            # loses `keyframe completion` from the derivation, so a full derived-versus-shipped check
            # would fire on the downgrade rather than on a defect. This fires only when the claim has
            # no asset of the right KIND anywhere, which the downgrade cannot produce.
            for claimed, kind, rule in (
                    ("keyframe completion", "Picture", "M11-keyframe-without-picture"),
                    ("video continuation", "Video", "M12-continuation-without-video")):
                if claimed in parts and not used[kind]:
                    add(rule, "ERROR",
                        f"the summary claims {claimed!r} and no <{kind} N> is referenced anywhere in "
                        f"the brief. That task type is a statement about "
                        + ("an image serving as a concrete frame of the target video"
                           if kind == "Picture" else
                           "a source video the target continues from")
                        + f", and there is no {kind.lower()} here to play that part. Remove "
                        f"{claimed!r} from the task-type prefix and keep only the types the attached "
                        "references actually support")

            for claimed, rule in (("audio reuse", "M7-audio-reuse-without-audio"),
                                  ("audio reference", "M8-audio-reference-without-audio")):
                if claimed in parts and not used["Audio"]:
                    add(rule, "ERROR",
                        f"the summary claims {claimed!r} and no <Audio N> is attached. A source "
                        "video's soundtrack is not an <Audio N> unless it is wired as one "
                        "(ref-en.txt 2.5), so nothing here can be "
                        + ("reused" if claimed == "audio reuse" else "referenced")
                        + " and this render generates the target video's audio instead. Delete "
                        f"{claimed!r} from the task-type prefix, and say what the audio should "
                        "sound like in overall_soundscape rather than claiming the original is "
                        + ("reused." if claimed == "audio reuse" else "referenced."))

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

        # ref-en.txt 4: "Use one line for each reference label." R5 catches the opposite case, a
        # label defined and never analysed, at WARN; nothing caught a label analysed twice, and the
        # worst single document in the corpus is one of those. It shipped `ready` with two lines for
        # <Audio 1>, the first calling the wav "the image" and giving it a first-frame parenthetical
        # on a request with no picture attached at all.
        #
        # ERROR: counting lines is a fact, and the repair is unambiguous -- keep the line that states
        # the label's actual reference role and delete the other, since both cannot be true of one
        # label whose meaning is fixed in subject_definitions.
        seen_labels: dict[str, int] = {}
        for line in [l for l in ret.splitlines() if l.strip()]:
            m = re.match(r"\s*<((?:Subject|Picture|Video|Audio)\s+\d+)>", line)
            if m:
                seen_labels[m.group(1)] = seen_labels.get(m.group(1), 0) + 1
        for label, n_lines in seen_labels.items():
            if n_lines > 1:
                add("R24-label-analysed-twice", "ERROR",
                    f"<{label}> has {n_lines} lines in retention_analysis and ref-en.txt 4 gives "
                    "each reference label exactly one. A label's meaning is fixed in "
                    "subject_definitions, so two lines about it state two different relationships "
                    "for one asset: keep the one that matches its defined role and delete the rest")

        # ref-en.txt 2.1: "One subject may be defined by multiple reference assets ... When the same
        # subject comes from multiple assets, combine the sources and state what each asset
        # provides." The corpus contains 0 merged definitions and one shipped document defining the
        # same man twice, once from a picture and once from a video, with the second subject appearing
        # in no shot and no retention line.
        #
        # WARN, because which two descriptors are the same person is a judgement and the descriptor
        # is all the text gives: two men in one video legitimately both read as "the man". A false
        # ERROR here would rewrite a correct cast list.
        by_descriptor: dict[str, list[tuple[str, str]]] = {}
        for m in re.finditer(r"^\s*(<Subject\s+\d+>)\s+is\s+(?:the|a|an)\s+([^,.]+?)\s+"
                             r"(?:in|from)\s+(<(?:Picture|Video|Audio)\s+\d+>)\s*[,.]",
                             defs, re.M):
            by_descriptor.setdefault(m.group(2).strip().lower(), []).append((m.group(1), m.group(3)))
        for descriptor, entries in by_descriptor.items():
            sources = {src for _, src in entries}
            if len(entries) > 1 and len(sources) == len(entries):
                add("R25-subject-defined-twice", "WARN",
                    f"{' and '.join(lb for lb, _ in entries)} are both defined as "
                    f"{descriptor!r}, each from a different asset ({', '.join(sorted(sources))}). "
                    "If that is one subject drawn from several references, ref-en.txt 2.1 combines "
                    "them into one definition that says what each asset provides: '<Subject 1> is "
                    "the woman whose appearance comes from <Picture 1> and whose walking motion "
                    "comes from <Video 1>.' Two labels for one person split the identity the render "
                    "is supposed to hold")

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

    # An <Audio N> asserted to BE a frame of the video. Measured on 4 of 50 recorded audio briefs,
    # all of them audio-only: "anchored by <Audio 1> as the opening frame", "<Audio 1>, which serves
    # as the first frame", and in retention_analysis the Picture-shaped parenthetical
    # "<Audio 1> ([Shot 1] first frame): reference - the image serves as the exact starting frame".
    # There is no image attached in any of them. This is the compiler telling H3 that a wav is a
    # picture, in a document that reads perfectly well.
    #
    # M11 stops the `keyframe completion` claim in the prefix and does not stop this: blocking the
    # task type moved the same invention into prose rather than ending it, which is why the claim
    # needs its own rule. ERROR, and safe at that severity because an audio asset is never a frame
    # under any reading: the deletion is unambiguous. Scoped to the assertion ("as the first frame",
    # "is the opening frame", a frame parenthetical on an Audio line) so that ordinary prose about
    # timing -- an <Audio N> continuing through the final frame -- is untouched.
    for pat in (re.compile(r"<Audio\s+\d+>[^.\n]{0,80}?(?:as|is)\s+(?:the\s+)?(?:exact\s+)?"
                           r"(?:opening|first|starting|final|last)\s+frame", re.I),
                re.compile(r"^\s*<Audio\s+\d+>\s*\(\[?Shot\s+\d+\]?[^)]*\bframe\b[^)]*\)",
                           re.M | re.I)):
        m = pat.search(scrubbed_all)
        if m:
            add("R26-audio-described-as-a-frame", "ERROR",
                f"an audio reference is described as a frame of the video ({m.group(0)[:70]!r}). An "
                "<Audio N> is a sound signal and has no frames; only an image can be a concrete "
                "frame, and this request has none attached. Delete the claim and say what the audio "
                "IS and where it is heard")
            break

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
        # A leading `<scenetrans>` is skipped rather than treated as missing time. base-en.txt 4.4
        # puts the marker "at the connecting points in both parts", and the connecting point of the
        # SECOND part is its start, so `[Shot 2] <scenetrans> At 00:06.000, ...` is the two rules
        # meeting. The cut time is there and unambiguous; reading it as absent cost a whole written
        # brief on the one request that asked for the join to be marked on both sides.
        head = re.sub(r"^\s*(?:<scenetrans>\s*)+", " ", head)
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
        # The message lists the WHOLE vocabulary, and that is a fix rather than a detail. A brief
        # that said "the camera begins a slow, smooth orbit to the right, circling the car" was
        # rejected twice by this rule and lost to the fallback: it had directed a real move, in a
        # word the closed list does not contain, and the message ended in an ellipsis that hid the
        # entry it needed (Arc Shot). Naming the defect without naming the remedy is what makes a
        # finding survive a correction pass. The paraphrase still does not count -- the point of a
        # closed vocabulary is the trained token, not a synonym for it.
        add("P5-camera-no-motion-type", "ERROR",
            "framing is described but no motion type from the closed vocabulary appears. Use one of "
            "these words exactly, woven into the sentence rather than as a label: "
            + ", ".join(CAMERA_TYPES)
            + ". A paraphrase of a move (orbits, circles, glides, drifts, sweeps) is not one of "
            "them, and an orbit around the subject is 'Arc Shot'. Every shot needs a stated camera "
            "or the model chooses its own")
    elif not has_amp_speed:
        add("P5b-camera-no-amplitude", "INFO",
            "a motion type appears but without the 'with <small|large> amplitude at "
            "<slow|fast> speed' idiom the spec defines")

    # The same vocabulary, checked in the other direction: what was WRITTEN, not what is missing.
    #
    # ERROR, and narrow enough to deserve it. Only two positions count: the spec's own idiom slot
    # (`with X amplitude`, `... amplitude at X speed`) and an `at X speed` that follows a canonical
    # camera phrase closely enough to be modifying it. A looser rule was tried against the corpus and
    # rejects correct prose -- "As the train rushes past her at high speed ... without breaking eye
    # contact with the camera" is a train, in a sentence that mentions the camera. The repair is two
    # words either way, so a true positive converges immediately and a false one would not.
    off_amp = [m.group(1) for m in AMPLITUDES_WRITTEN.finditer(desc)
               if m.group(1).lower() not in AMPLITUDES]
    off_speed = [m.group(1) for m in SPEEDS_WRITTEN.finditer(desc)
                 if m.group(1).lower() not in SPEEDS
                 and (desc[max(0, m.start() - 12):m.start()].rstrip().lower().endswith("amplitude")
                      or any(0 <= m.start() - c.end() <= 50
                             for c in CAMERA_MOTION_PHRASE.finditer(desc)))]
    if off_amp or off_speed:
        add("P8-camera-modifier-off-vocabulary", "ERROR",
            "the camera carries a modifier outside the closed vocabulary: "
            + ", ".join(sorted({f"{w!r}" for w in off_amp + off_speed}))
            + ". base-en.txt 4.3 closes both dimensions: amplitude is 'with small amplitude' or "
              "'with large amplitude', speed is 'at slow speed' or 'at fast speed', and medium "
              "amplitude and normal speed are omitted rather than written. Use one of those four or "
              "drop the modifier")

    # The cut phrase itself. base-en.txt 4.2 gives a closed set for an ordinary cut and 34 of 169
    # timestamped shot openings in the corpus used none of it, most often by stating no transition at
    # all and opening on a camera move instead.
    #
    # WARN, and that is a decision rather than caution: `shipped_repeated_shot.txt` is a control that
    # MUST pass on legality, its [Shot 2] opens without a cut phrase, and a human judged that prose
    # on taste rather than on rules. An ERROR here would send a legitimate edit back through the fix
    # loop and, failing twice, would lose the whole written brief over a phrase. The prompt is where
    # this is reduced; the rule is how the drift stays visible.
    for num, body in shots:
        if int(num) == 1:
            continue
        opening = re.sub(r"^\s*,?\s*At\s+\d{2}:\d{2}\.\d{3},?\s*", "", body)[:160]
        if not CUT_PHRASE_PRESENT.search(opening):
            add("P7-cut-phrase-off-vocabulary", "WARN",
                f"[Shot {num}] is a cut and its opening states no transition from base-en.txt 4.2's "
                "closed set: " + ", ".join(f"`{p}`" for p in CUT_PHRASES)
                + " (a cross-dissolve, fade or wipe only if the request asked for one). A synonym "
                  "is a near miss in the same way a wrong label is: "
                + f"{opening[:60]!r}")
            break

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
    spans = list(re.finditer(r"<d>(.*?)</d>", desc, re.S))
    blocks = [m.group(1) for m in spans]
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
    # The caller's words, and how they may be arranged. D4 used to demand the whole line inside ONE
    # <d> block, which made base-en.txt 4.4's own construct illegal: a line crossing a cut is
    # DIVIDED at the cut, so neither half matches and the correct document was an ERROR. The
    # compiler's way out was to write the whole line inside <d> on both sides of the cut, 7 of 7 on
    # an explicit request, which passed every rule and instructs H3 to speak the line twice.
    #
    # So the arrangement is now checked instead of forbidden. Verbatim is still verbatim: the line
    # has to be present, word for word and punctuation mark for punctuation mark, either inside one
    # block or as the concatenation of consecutive ones.
    spoken = [re.sub(r"\s+", " ", re.sub(r"^\s*\[[^\]]*\]\s*", "", b)).strip() for b in blocks]
    for want in ctx.expected_dialogue:
        if not want:
            continue
        w = re.sub(r"\s+", " ", want).strip()
        whole = [i for i, s in enumerate(spoken) if w in s]
        if whole:
            if len(whole) > 1:
                add("D10-dialogue-line-duplicated", "ERROR",
                    f"the line {w[:48]!r} appears in full inside {len(whole)} separate <d> blocks, "
                    "which tells the model to speak it twice. The caller supplied it once, so it "
                    "is spoken once: if it runs across a cut, divide it at the cut and mark both "
                    "connecting points with <scenetrans> (base-en.txt 4.4) rather than repeating "
                    "the whole line on both sides")
            else:
                # The same defect in a smaller coat, and the shape the writer moved to once the
                # whole-line duplicate was rejected: the complete line in one shot, then a TAIL of it
                # spoken again after the cut ("<d>[English] ...and not the whole lock.</d>"). The
                # words in that fragment are still scheduled twice. Four consecutive words is the
                # threshold because it is well past coincidence between two different utterances.
                echo = next(((i, p) for i, s in enumerate(spoken) if i != whole[0]
                             for p in [_shared_phrase(w, s, 4)] if p), None)
                if echo:
                    add("D10-dialogue-line-duplicated", "ERROR",
                        f"the line {w[:40]!r} is spoken in full in one <d> block and part of it is "
                        f"spoken again in another ({echo[1]!r}), so those words are scheduled twice. "
                        "Either the line belongs to one shot and is not repeated after the cut, or it "
                        "runs across the cut and is DIVIDED at it: the first part closes one <d> "
                        "block, the remaining words open the next, each half appearing exactly once, "
                        "with <scenetrans> at both connecting points. An ellipsis standing in for the "
                        "missing half is not the construct either")
            continue
        run = _consecutive_run(spoken, w)
        if run is None:
            add("D4-dialogue-not-verbatim", "ERROR",
                f"user line is missing or altered inside <d>: {want[:60]!r}. It may be divided "
                "across a cut, in which case the parts must join back into the caller's exact "
                "words, including punctuation")
            continue
        # Divided across consecutive blocks. Legal, and base-en.txt 4.4 says how it is marked: at
        # the connecting points in BOTH parts, which is one marker at the end of the earlier part
        # and one at the start of the later one.
        i, j = run
        for k in range(i, j):
            gap = desc[spans[k].end():spans[k + 1].start()]
            if not re.search(r"\[Shot\s+\d+\]", gap):
                add("D13-line-split-without-a-cut", "ERROR",
                    f"the line {w[:48]!r} is divided into separate <d> blocks with no cut between "
                    "them, so a continuity marker is not the remedy: inside one shot a supplied "
                    "line is spoken once, in one block")
                continue
            n_marks = gap.count("<scenetrans>")
            if n_marks < 2:
                add("D11-split-line-no-scenetrans", "ERROR",
                    f"the line {w[:48]!r} runs across the cut into [Shot "
                    + (re.search(r"\[Shot\s+(\d+)\]", gap).group(1))
                    + "] and "
                    + ("only one side of the join is marked"
                       if n_marks == 1 else "neither side of the join is marked")
                    + ". base-en.txt 4.4 puts <scenetrans> at the connecting points in both parts: "
                    "once after the first part's </d> and once before the second part's <d>")
            elif not CONTINUITY_STATED.search(gap):
                add("D12-split-line-no-continuity-statement", "WARN",
                    "the join is marked but nothing states that the audio continues across it; "
                    "base-en.txt 4.4 asks for it explicitly and offers `continues seamlessly "
                    "across the cut`, `continues uninterrupted into the next shot`, `carries over "
                    "from the previous shot` or `remains audible across the transition`")
    # ---------------------------------------------------------------- reference audio's own words
    # ref-en.txt 5.4, both halves. Reperformance is requested by the PROMPT, which this layer cannot
    # read, so only what the document itself settles is enforced:
    #   * a block that plainly reperforms the line and gets it wrong        -> decidable, ERROR
    #   * a `fully_copy` claim, which puts every word of the source in the
    #     target's final track by the marker's own definition               -> decidable, ERROR
    #   * words supplied and used nowhere                                   -> not decidable, WARN
    # The third is the measured defect (0 of 7) and it is deliberately the weakest rule of the three:
    # when only timbre or delivery is referenced, 5.4 forbids carrying the words over, so a brief
    # that leaves them out can be exactly right.
    for label, transcript in ctx.audio_transcripts:
        if not (transcript or "").strip():
            continue
        said = re.sub(r"\s+", " ", transcript).strip()
        sents = [s.strip() for s in re.split(r"(?<=[.!?])\s+", said)
                 if len(s.split()) >= 3] or [said]
        if any(s in b for s in sents for b in spoken):
            continue
        entry = re.search(rf"^\s*{re.escape(label)}\s*(\([^)]*\))?\s*:\s*(\w+)", ret, re.M)
        marker = entry.group(2) if entry else ""
        near = next((p for b in spoken for p in [_shared_phrase(said, b, 5)] if p), None)
        if near:
            add("D14-reperformance-altered", "ERROR",
                f"a <d> block reperforms {label}'s words and alters them (it shares {near!r} with "
                f"the transcript and matches none of its sentences). ref-en.txt 5.4: preserve the "
                f"exact source words and the original language. The words are: {said[:120]!r}")
        elif marker == "fully_copy":
            add("D15-copied-audio-words-missing", "ERROR",
                f"{label} is marked fully_copy, so the complete source audio is the target video's "
                f"final track and every word on it is audible in the render, but none of them "
                f"appears inside <d>. Write them verbatim in their original language where they "
                f"are heard (ref-en.txt 5.4). The words are: {said[:120]!r}")
        else:
            add("D16-transcript-not-reperformed", "WARN",
                f"the caller transcribed {label} and none of those words appears inside <d>. If the "
                "request asks for them to be reperformed, ref-en.txt 5.4 requires them verbatim in "
                f"their original language inside <d>: {said[:120]!r}. If only the timbre, rhythm or "
                "delivery is referenced, leaving them out is correct and this is nothing to fix")

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
        # base-en.txt 4.7's own prohibition, which had no rule while its positive half (state a
        # tempo) had one. A mood word is a description of the effect rather than of the signal, and
        # the encoder gets the word: "melancholic" is not a sound H3 can render, where "sustained low
        # strings increasing in volume" is.
        #
        # WARN. The word list is a closed reading of "abstract mood words" and reasonable people put
        # the line in slightly different places, so the finding informs; the spec sentence is the
        # spec's and the list is mine. Scoped to the score alone, because 4.6 says nothing of the
        # kind about physical sound.
        mood = sorted({m.group(0).lower() for m in MOOD_WORDS.finditer(music)})
        if mood:
            add("A8-music-mood-word", "WARN",
                "non_diegetic_music states the score's mood or emotional function rather than its "
                f"sound: {', '.join(repr(w) for w in mood)}. base-en.txt 4.7 asks for "
                "instrumentation, speed, rhythm and dynamic change and rules those out explicitly. "
                "Name what is playing and what it does across the duration instead")

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
