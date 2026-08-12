"""Reconstruct-and-diff: verify a freely-written brief and correct it in place.

The inversion. The model writes the whole brief; this module recomputes every field that has a
right answer from the wiring and the grid, and rewrites the text where the model's disagrees. A
wrong ordinal or an off-grid timestamp is a text substitution, not a reason to re-roll.

Why the composed pipeline had to give way. Every guarantee it bought was real, but it bought them
by pre-writing the parts it guaranteed, and pre-written parts cannot be woven into prose. The
clearest case is the camera: the composer inserted "The camera pushes in with small amplitude at
slow speed." as its own sentence, and the brief that beat it wrote

    "The camera pushes in slowly with small amplitude, holding him centred as he closes the
     distance, and the torchlight climbs his trousers, then his chest, then his face."

Same vocabulary, and a completely different instruction, because the move is joined to what it
reveals. A template can guarantee the words and cannot produce that sentence. So the machinery
moves to verification, where it costs the prose nothing.

Repair is deliberately conservative. Anything mechanical is fixed; anything requiring judgement is
reported, and a brief that still fails validation falls back to the deterministic draft.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .grid import Target, ms_to_timestamp, timestamp_to_ms
from .models import AUDIO_MARKERS, Finding, Mode, VISUAL_MARKERS
from .textnorm import normalize

# The SIX-section full-reference shape. Base modes have three, and conflating the two cost the whole
# description on every base-mode brief: `_split_written` searched only these names, found no
# `integrated_multimodal_description`, and returned a sections dict with the description missing --
# silently, because the validator reads the prompt text rather than this dict, and because until the
# base composer landed every base-mode brief fell back to the draft, which builds its sections a
# different way. The eval reported 0 words on four briefs that were in fact written correctly.
SECTION_NAMES = ("subject_definitions", "summary", "retention_analysis",
                 "detailed_description", "overall_soundscape", "non_diegetic_music")
BASE_SECTION_NAMES = ("integrated_multimodal_description", "overall_soundscape",
                      "non_diegetic_music")


def section_names(mode: Mode | None) -> tuple[str, ...]:
    return SECTION_NAMES if mode is None or mode is Mode.REF2VA else BASE_SECTION_NAMES

MIN_SHOT_MS = 1200

# Markers a model reaches for that are not in the enum, mapped to what it meant.
MARKER_SYNONYMS = {
    "mostly_preserved": "partially_preserved", "partly_preserved": "partially_preserved",
    "preserved": "fully_preserved", "fully preserved": "fully_preserved",
    "full_preserved": "fully_preserved", "retained": "fully_preserved",
    "transferred": "attribute_transfer", "attribute_transferred": "attribute_transfer",
    "loose_reference": "weak_reference", "weak": "weak_reference",
    "copied": "fully_copy", "full_copy": "fully_copy", "partial_copy": "partially_copy",
    "referenced": "reference",
}


@dataclass
class RepairResult:
    text: str
    repairs: list[str] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)

    @property
    def n(self) -> int:
        return len(self.repairs)


def _strip_fence(text: str) -> str:
    t = text.strip()
    t = re.sub(r"^```[a-zA-Z]*\s*", "", t)
    t = re.sub(r"\s*```$", "", t)
    # Some replies open with a sentence before the first section name.
    m = re.search(r"^subject_definitions\s*:", t, re.M)
    return t[m.start():].strip() if m else t


def repair(text: str, *, target: Target, mode: Mode, labels: tuple[str, ...],
           dialogue: tuple[str, ...] = (), style_phrase: str = "",
           definitions: tuple[str, ...] = ()) -> RepairResult:
    """Correct everything mechanical in a written brief."""
    res = RepairResult(text=_strip_fence(text))
    if res.text != text.strip():
        res.repairs.append("stripped a fence or preamble from the reply")

    # Deliberately minimal. Everything with judgement in it now goes back to the MODEL as
    # findings (see prose.fix_with_findings) rather than being edited by a bespoke parser here.
    # What stays is only what the model cannot know or must never re-type:
    #   * the label namespace and ordinals -- only the wiring knows the socket order
    #   * the caller's dialogue -- their words, never round-tripped through a model
    #   * unicode hazards -- zero judgement, and a curly quote is a different token sequence
    res.text = _fix_unicode(res.text, res)
    res.text = _fix_labels(res.text, labels, res)
    res.text = _fix_dialogue(res.text, dialogue, res)
    if not res.text.endswith("\n"):
        res.text += "\n"
    return res


# --------------------------------------------------------------------------- pieces

def _fix_unicode(text: str, res: RepairResult) -> str:
    """Verbatim spans keep whatever they contain; everything else is normalised."""
    parts, out, last = list(re.finditer(r"<d>.*?</d>|\"[^\"]*\"", text, re.S)), [], 0
    for m in parts:
        out.append(normalize(text[last:m.start()]))
        out.append(m.group(0))
        last = m.end()
    out.append(normalize(text[last:]))
    fixed = "".join(out)
    if fixed != text:
        res.repairs.append("normalised curly quotes / non-breaking spaces outside verbatim spans")
    return fixed


def _fix_labels(text: str, labels: tuple[str, ...], res: RepairResult) -> str:
    """The wiring owns the label namespace. A model that writes <Image 1> means <Picture 1>."""
    by_kind: dict[str, list[str]] = {}
    for lab in labels:
        m = re.match(r"<(\w+)\s+(\d+)>", lab)
        if m:
            by_kind.setdefault(m.group(1), []).append(lab)

    aliases = {"Image": "Picture", "Img": "Picture", "Photo": "Picture", "Frame": "Picture",
               "Ref": "Picture", "Reference": "Picture", "Clip": "Video", "Footage": "Video",
               "Sound": "Audio", "Track": "Audio"}
    for wrong, right in aliases.items():
        pat = re.compile(rf"<\s*{wrong}\s+(\d+)\s*>")
        if pat.search(text) and by_kind.get(right):
            text = pat.sub(lambda m: f"<{right} {m.group(1)}>", text)
            res.repairs.append(f"rewrote <{wrong} N> to <{right} N> — the runtime emits "
                               f"<{right} N>, so the model's label pointed at nothing")

    # Ordinals beyond what is attached: clamp to the highest real one.
    for kind, have in by_kind.items():
        top = len(have)
        def clamp(m: re.Match) -> str:
            n = int(m.group(1))
            if n <= top:
                return m.group(0)
            res.repairs.append(f"<{kind} {n}> exceeds the {top} attached; rewrote to <{kind} {top}>")
            return f"<{kind} {top}>"
        text = re.sub(rf"<{kind}\s+(\d+)>", clamp, text)
    return text


def _fix_timestamps(text: str, target: Target, res: RepairResult) -> str:
    """Cut times: strictly increasing, inside the render, never on the first shot.

    Scoped to detailed_description ONLY. An earlier version ran over the whole document and
    renumbered the `[Shot N]` mentions inside retention_analysis as if they were shot headers,
    which pushed the real description to shots 5 and 6 -- the repair corrupting what it was
    repairing.
    """
    m = re.search(r"^detailed_description\s*:(.*?)(?=^overall_soundscape\s*:|\Z)",
                  text, re.M | re.S)
    if not m:
        return text
    fixed = _fix_timestamps_in(m.group(1), target, res)
    return text[:m.start(1)] + fixed + text[m.end(1):]


def _fix_timestamps_in(text: str, target: Target, res: RepairResult) -> str:
    total_ms = int(round(target.effective_seconds * 1000))
    shots = list(re.finditer(r"\[Shot\s+(\d+)\]\s*(At\s+(\d{1,2}):(\d{2})\.(\d{1,3}),?)?", text))
    if not shots:
        return text

    # Drop a timestamp on shot 1.
    first = shots[0]
    if first.group(2):
        text = text[:first.start()] + f"[Shot {first.group(1)}] " + text[first.end():]
        res.repairs.append("removed the timestamp from [Shot 1]; a first shot has none")
        shots = list(re.finditer(r"\[Shot\s+(\d+)\]\s*(At\s+(\d{1,2}):(\d{2})\.(\d{1,3}),?)?", text))

    times: list[int] = []
    for i, m in enumerate(shots):
        if i == 0:
            times.append(0)
            continue
        if m.group(2):
            ms = (int(m.group(3)) * 60 + int(m.group(4))) * 1000 + int(m.group(5).ljust(3, "0"))
        else:
            ms = int(total_ms * i / len(shots))
            res.repairs.append(f"[Shot {m.group(1)}] had no cut time; placed it at "
                               f"{ms_to_timestamp(ms)}")
        times.append(ms)

    fixed = list(times)
    for i in range(1, len(fixed)):
        floor = fixed[i - 1] + MIN_SHOT_MS
        ceiling = total_ms - MIN_SHOT_MS * (len(fixed) - i)
        fixed[i] = max(floor, min(fixed[i], ceiling))

    out, last = [], 0
    for i, m in enumerate(shots):
        out.append(text[last:m.start()])
        if i == 0:
            out.append(f"[Shot {i + 1}] ")
        else:
            out.append(f"[Shot {i + 1}] At {ms_to_timestamp(fixed[i])}, ")
            if fixed[i] != times[i]:
                res.repairs.append(
                    f"[Shot {i + 1}] cut moved from {ms_to_timestamp(times[i])} to "
                    f"{ms_to_timestamp(fixed[i])} to stay inside {target.effective_seconds:.3f}s")
        last = m.end()
    out.append(text[last:])
    result = "".join(out)
    return re.sub(r",\s*,", ",", result)


def _fix_markers(text: str, res: RepairResult) -> str:
    """A marker outside the enum is usually a synonym, not a new idea."""
    def sub(m: re.Match) -> str:
        label, paren, marker = m.group(1), m.group(2) or "", m.group(3)
        if marker in VISUAL_MARKERS or marker in AUDIO_MARKERS:
            return m.group(0)
        want = MARKER_SYNONYMS.get(marker.lower())
        if want is None:
            want = "reference" if label.startswith("<Audio") else "partially_preserved"
        res.repairs.append(f"{label}: marker {marker!r} is not in the vocabulary, wrote {want!r}")
        return f"{label} {paren}: {want}".replace("  ", " ")

    return re.sub(r"(<(?:Subject|Picture|Video|Audio)\s+\d+>)\s*(\([^)]*\))?\s*:\s*(\w+)",
                  sub, text)


def _fix_speaker_ids(text: str, res: RepairResult) -> str:
    """(SN) numbered by first speech, and never inside retention_analysis."""
    body = text
    m = re.search(r"^retention_analysis\s*:(.*?)(?=^\w+\s*:|\Z)", body, re.M | re.S)
    if m and re.search(r"\(S\d+\)", m.group(1)):
        cleaned = re.sub(r"\s*\(S\d+\)", "", m.group(1))
        body = body[:m.start(1)] + cleaned + body[m.end(1):]
        res.repairs.append("removed speaker IDs from retention_analysis, where they are forbidden")

    desc = re.search(r"^detailed_description\s*:(.*?)(?=^overall_soundscape\s*:|\Z)",
                     body, re.M | re.S)
    if not desc:
        return body
    seen: dict[str, str] = {}
    def renumber(m: re.Match) -> str:
        old = m.group(0)
        if old not in seen:
            seen[old] = f"(S{len(seen) + 1})"
        return seen[old]
    fixed = re.sub(r"\(S\d+\)", renumber, desc.group(1))
    if any(k != v for k, v in seen.items()):
        res.repairs.append("renumbered speaker IDs into order of first speech")
    return body[:desc.start(1)] + fixed + body[desc.end(1):]


def _fix_dialogue(text: str, expected: tuple[str, ...], res: RepairResult) -> str:
    """The user's words, exactly. A paraphrase inside <d> is replaced."""
    if not expected:
        return text
    blocks = list(re.finditer(r"<d>\s*(\[[^\]]*\]\s*)?(.*?)</d>", text, re.S))
    for want in expected:
        if any(want in b.group(2) for b in blocks):
            continue
        if not blocks:
            res.findings.append(Finding("D4-dialogue-not-verbatim", "ERROR",
                                        f"the brief contains no <d> block for {want[:48]!r}"))
            continue
        target_block = min(blocks, key=lambda b: abs(len(b.group(2)) - len(want)))
        lang = target_block.group(1) or "[English] "
        text = text[:target_block.start()] + f"<d>{lang}{want}</d>" + text[target_block.end():]
        res.repairs.append(f"replaced a paraphrase with the caller's exact line: {want[:40]!r}")
        blocks = list(re.finditer(r"<d>\s*(\[[^\]]*\]\s*)?(.*?)</d>", text, re.S))
    return text


def _fix_definition_form(text: str, res: RepairResult) -> str:
    """`<Subject 1> = ...` or `<Subject 1>: ...` never registers as a definition. Rewrite to `is`."""
    m = re.search(r"^subject_definitions\s*:(.*?)(?=^summary\s*:|\Z)", text, re.M | re.S)
    if not m:
        return text
    body = m.group(1)
    fixed = re.sub(r"^(\s*<(?:Subject|Picture|Video|Audio)\s+\d+>)\s*(?:=|:)\s*",
                   r"\1 is ", body, flags=re.M)
    if fixed != body:
        res.repairs.append("rewrote definition lines from '=' or ':' to the required "
                           "'<Label> is ...' form")
    return text[:m.start(1)] + fixed + text[m.end(1):]


def _fix_missing_definitions(text: str, definitions: tuple[str, ...],
                             res: RepairResult) -> str:
    """A `<Subject N>` used but never defined is a repair, not a bin.

    We have the AssetCards, so the definition line can be synthesised. Discarding several hundred
    words of usable direction because one definition line is absent is the wrong trade -- that is
    what the fallback kept doing.
    """
    if not definitions:
        return text
    used = {int(n) for n in re.findall(r"<Subject\s+(\d+)>", text)}
    if not used:
        return text

    m = re.search(r"^subject_definitions\s*:(.*?)(?=^summary\s*:|\Z)", text, re.M | re.S)
    if not m:
        # The whole section is gone: rebuild it from the cards rather than reject the brief.
        block = "subject_definitions:\n" + "\n".join(definitions) + "\n\n"
        res.repairs.append("subject_definitions was absent; rebuilt it from the asset cards")
        return block + text.lstrip()

    body = m.group(1)
    defined = {int(n) for n in re.findall(r"^\s*<Subject\s+(\d+)>\s+is\b", body, re.M)}
    missing = sorted(used - defined)
    if not missing:
        return text

    by_num: dict[int, str] = {}
    for line in definitions:
        d = re.match(r"\s*<Subject\s+(\d+)>", line)
        if d:
            by_num[int(d.group(1))] = line.strip()

    added, renumbered = [], []
    for n in missing:
        if n in by_num:
            added.append(by_num[n])
        elif defined:
            # No card for it: point it at a subject that IS defined rather than leave a dangling
            # label, which references nothing at all.
            target_n = min(defined)
            text = re.sub(rf"<Subject\s+{n}>", f"<Subject {target_n}>", text)
            renumbered.append((n, target_n))
    if added:
        body_fixed = body.rstrip() + "\n" + "\n".join(added) + "\n"
        text = text[:m.start(1)] + body_fixed + text[m.end(1):]
        res.repairs.append(f"synthesised {len(added)} missing subject definition(s) from the "
                           f"asset cards: {', '.join(re.match(r'<Subject \d+>', a).group(0) for a in added)}")
    for n, t in renumbered:
        res.repairs.append(f"<Subject {n}> had no definition and no card; pointed it at "
                           f"<Subject {t}> rather than leaving a label that references nothing")
    return text


def _fix_summary(text: str, style_phrase: str, res: RepairResult) -> str:
    """A summary that is only its bracketed prefix is not a summary."""
    m = re.search(r"^summary\s*:\s*(.*?)(?=^retention_analysis\s*:|\Z)", text, re.M | re.S)
    if not m:
        return text
    body = m.group(1).strip()
    after = re.sub(r"^\[[^\]]*\]\s*", "", body).strip()
    if after:
        return text
    subs = re.findall(r"<Subject\s+\d+>", text)
    who = ", ".join(dict.fromkeys(subs)) or "the described scene"
    filled = f"{body} The target video shows {who} as described below."
    res.repairs.append("the summary carried only its task-type prefix; added a sentence")
    return text[:m.start(1)] + filled + "\n\n" + text[m.end(1):]


def _fix_style_opening(text: str, style_phrase: str, res: RepairResult) -> str:
    """Ref2VA needs one style sentence on its own line before [Shot 1]."""
    m = re.search(r"^detailed_description\s*:\s*(.*?)(?=^overall_soundscape\s*:|\Z)",
                  text, re.M | re.S)
    if not m:
        return text
    body = m.group(1)
    head = body.split("[Shot 1]")[0].strip() if "[Shot 1]" in body else ""
    if head:
        return text
    phrase = (style_phrase or "Live-action, cinematic").strip().rstrip(".,")
    first, _, rest = phrase.partition(",")
    first = first.strip()
    first = first[0].lower() + first[1:] if first else first
    sentence = (f"The target video is in {first} style with {rest.strip()}."
                if rest.strip() else f"The target video is in {first} style.")
    res.repairs.append("added the missing style sentence before [Shot 1]")
    return text[:m.start(1)] + sentence + "\n" + body.lstrip() + text[m.end(1):]


def _fix_sections(text: str, res: RepairResult, names: tuple[str, ...] = SECTION_NAMES) -> str:
    """Present and in order. Missing sound sections get N/A rather than absence."""
    found = {n: re.search(rf"^{n}\s*:", text, re.M) for n in names}
    missing = [n for n, m in found.items() if not m]
    for n in missing:
        if n in ("overall_soundscape", "non_diegetic_music"):
            text = text.rstrip() + f"\n\n{n}:\nN/A\n"
            res.repairs.append(f"added the missing '{n}' section as N/A")
        elif n == "retention_analysis":
            # Derivable: one line per defined label, preservation by default. Better than binning
            # a brief whose description is fine.
            labels_in_defs = re.findall(
                r"^\s*(<(?:Subject|Picture|Video|Audio)\s+\d+>)\s+is\b",
                (re.search(r"^subject_definitions\s*:(.*?)(?=^\w+\s*:|\Z)", text, re.M | re.S)
                 or re.match("", "")).group(1) if re.search(
                    r"^subject_definitions\s*:", text, re.M) else "", re.M)
            shots = sorted({int(x) for x in re.findall(r"\[Shot\s+(\d+)\]", text)}) or [1]
            scope = ", ".join(f"[Shot {i}]" for i in shots)
            lines = [f"{lab} (appears in {scope}): fully_preserved - "
                     "its referenced features are retained." for lab in labels_in_defs]
            if lines:
                anchor = re.search(r"^detailed_description\s*:", text, re.M)
                block = "retention_analysis:\n" + "\n".join(lines) + "\n\n"
                text = (text[:anchor.start()] + block + text[anchor.start():]) if anchor \
                    else text.rstrip() + "\n\n" + block
                res.repairs.append("retention_analysis was absent; derived one line per defined "
                                   "label from the definitions and the shot list")
    order = [n for n in names if found.get(n)]
    if order and order != [n for n in names if n in order]:
        res.findings.append(Finding("S2-section-order", "ERROR",
                                    f"sections are out of order: {order}"))
    return text
