"""Stage D (first half): the only places a model writes anything.

Two kinds of call, and both are narrow by construction:

  beat_sheet()  one structured call. Decides WHAT happens per shot, the camera from the
                closed enum, which sounds are synchronized vs ambient, the style opening,
                the summary sentence and the music. Every enum is re-validated here --
                a schema on this endpoint constrains shape, not sense.

  shot_body()   one prose call per shot, with that shot's span, beat, subjects and word
                target. Per-shot generation is what makes length arithmetic instead of a
                request, and what makes each shot a different beat instead of a restatement.

Prompt text lives in prompts/*.txt so a change to it is a versioned, scoreable artifact
rather than an edit buried in code. The harness proved that matters: a system prompt with
a page of extra craft rules measurably regressed, and only the validator caught it.
"""
from __future__ import annotations

import functools
import json
import re
from pathlib import Path
from typing import Any

from .backend import Backend, user_message
from .config import get_config
from .creativity import ELEMENTS
from .models import AMPLITUDES, AssetCard, Brief, CAMERA_TYPES, Mode, SPEEDS, ShotPlan, SubjectPlan
from .textnorm import normalize


@functools.lru_cache(maxsize=32)
def load_prompt(name: str) -> str:
    p = get_config().paths.spec_dir / name
    if not p.exists():
        raise FileNotFoundError(f"prompt file not found: {p}")
    return p.read_text(encoding="utf-8").strip()


def beat_schema(n_shots: int) -> dict[str, Any]:
    return {
        "title": "BeatSheet",
        "type": "object",
        "additionalProperties": False,
        "required": ["shots", "ambient_sound", "style_phrase", "summary", "music"],
        "properties": {
            "shots": {
                "type": "array",
                "minItems": n_shots,
                "maxItems": n_shots,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["beat", "camera", "subjects", "sync_sound"],
                    "properties": {
                        "beat": {"type": "string"},
                        "camera": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["type"],
                            "properties": {
                                "type": {"type": "string", "enum": list(CAMERA_TYPES)},
                                "amplitude": {"type": "string", "enum": list(AMPLITUDES)},
                                "speed": {"type": "string", "enum": list(SPEEDS)},
                            },
                        },
                        "subjects": {"type": "array", "items": {"type": "string"}},
                        "sync_sound": {"type": "array", "items": {"type": "string"}},
                    },
                },
            },
            "ambient_sound": {"type": "array", "items": {"type": "string"}, "maxItems": 3},
            "style_phrase": {"type": "string"},
            "summary": {"type": "string"},
            "music": {"type": "string"},
        },
    }


def _asset_digest(cards: dict[str, AssetCard], subjects: list[SubjectPlan]) -> str:
    lines = []
    for s in subjects:
        attrs = "; ".join(s.attributes) or "no distinguishing detail recorded"
        lines.append(f"{s.label} = {s.descriptor} ({s.kind}). Features: {attrs}")
    for c in cards.values():
        if c.kind.value == "audio":
            # Facts from the wiring, not a description of sound. Nothing here was heard by a
            # model, so nothing here may be elaborated into one.
            bits = [b for b in (c.summary, c.transcript[:160]) if b]
            if bits:
                lines.append("audio reference (typed facts, do not embellish): "
                             + " | ".join(bits))
    return "\n".join(lines) or "no references attached"


def fix_with_findings(backend: Backend, written: str, findings: list, *,
                      labels: tuple[str, ...] = (), sections: tuple[str, ...] = (),
                      seed: int | None = None, thinking: bool = False) -> str:
    """Hand the model its own text plus the findings and ask for a surgical fix.

    The owner's idea, and better than the code repairers it replaces: a bespoke editor per failure
    mode is a small parser with its own bugs that only handles the shapes someone anticipated,
    while the model already holds the intent behind the text. Validator findings happen to be
    ideal review feedback -- they name the rule, the offence and the offending line.

    The spec is NOT resent. It is already in the system prompt of the composing call, and
    repeating it invites a wholesale rewrite instead of a surgical fix.

    The LABEL INVENTORY is resent, and that distinction is the whole point. The first eval run of
    this loop fell back on three of six briefs, every time on `L2-undefined-subject` /
    `L3-phantom-media` surviving both rounds -- the model had invented a `<Subject 3>` where two
    exist. Those are BINDING faults, and the fix call was being asked to repair a binding with the
    binding table removed: "<Subject 3> is used but never defined" can be satisfied by deleting the
    reference or by inventing a definition for it, and nothing in the ask said which labels are real.
    The inventory is not the specification -- it is a fact about this request's wiring, three lines
    the composing call already hands over, and withholding it was an accident of where the split fell
    rather than a decision.
    """
    numbered = "\n".join(f"{i}. [{f.rule}] {f.msg}" for i, f in enumerate(findings, 1))
    inventory = ""
    if labels:
        inventory = (
            "\nThese are the ONLY labels that exist for this request. Every one of them is real and "
            "no others are — a label outside this list references nothing at all, so the fix for an "
            "unknown label is to remove it or replace it with one of these, never to define it:\n"
            + ", ".join(labels) + "\n")
    ask = (
        "Your brief failed mechanical verification. Below are the exact findings, then your text.\n\n"
        f"FINDINGS\n{numbered}\n"
        f"{inventory}\n"
        "Fix every finding and change nothing else. Keep your shots, your camera moves, your "
        "performance beats, your wording. Do not rewrite, do not shorten, do not re-plan — this is "
        "a correction pass, not a second draft. Output the corrected "
        + (f"{len(sections)} sections ({', '.join(sections)})" if sections else "brief in full")
        + " and nothing else.\n\n"
        f"YOUR TEXT\n{written}"
    )
    reply = backend.chat(
        [{"role": "system", "content": "You correct mechanical faults in your own H3 brief. You "
                                       "make the smallest edit that satisfies each finding."},
         {"role": "user", "content": ask}],
        thinking=thinking, temperature=0.2, seed=seed, max_tokens=20000)
    return reply.content


def _reference_governed(licence) -> list[str]:
    """The attributes to name as reference-governed in the ask.

    **The sentence states the RULE, not a claim about the request.** It used to read "The request is
    silent about {attrs}", which on a detector miss is a false statement about the caller's own
    request, handed to the model beside the request text -- a contradiction, and the wrong resolution
    of it is the drift the policy exists to stop. §35's line is "absence of a statement is not a
    statement of absence"; asserting silence is that mistake made positively. Conditional wording is
    true under a hit and under a miss, so a miss degrades to a weaker hint and the one reader holding
    both the request and the reference description does the disambiguating.

    The MEDIUM is excluded because it already has a better channel: the style block states it with
    the bare-adjective rule attached ("the request did not ask to change the medium, so keep it").
    Listing it here as well would tell the model the request governs the medium wherever the request
    says "anime", which is precisely what the owner's rule refuses.
    """
    from .licence import MEDIUM
    return [a for a, who in licence.governs.items() if who == "reference" and a != MEDIUM]


def audio_task_facts(labels: tuple[str, ...], task_types: tuple[str, ...]) -> str:
    """What the wiring settles about the two audio task types, stated as a fact in the ask.

    The renderer already owns this: "a prose stage that could write the prefix could invent a
    relationship the pack does not contain" (render.render_summary). The write-first inversion
    handed the prefix back to the model without handing over the fact it needed, and the model
    then claimed `audio reuse` on 6 of 7 video edits -- reasonably, because keeping the original
    audio is what editing a video means. It is still a claim the render cannot deliver: a
    soundtrack is a separately wired input, and with none wired the signal never reaches the model.

    The audio half only is pinned, because the wiring decides it completely. Whether reusing a
    person out of a reference video also counts as `reference generation` is a judgement about how
    the reference is used, and ref-en.txt 3 phrases it as one ("normally", "only when"), so the
    model keeps it.
    """
    audio = [lb for lb in labels if lb.startswith("<Audio")]
    if not audio:
        return ("No <Audio N> is attached, so the task-type prefix may NOT contain `audio reuse` "
                "or `audio reference`: both claim a relationship to an attached audio signal and "
                "there is none. If the request implies the source video's own sound, note that a "
                "video's soundtrack is a separately wired input and none is wired here — this "
                "render GENERATES the target video's audio. So do not write that the original "
                "audio is preserved, reused or carried over anywhere in the brief; decide what the "
                "video should sound like and put it in overall_soundscape.")
    declared = [t for t in task_types if t.startswith("audio ")]
    return (f"Attached audio: {', '.join(audio)}. The audio relationship their roles declare is "
            f"{' + '.join(declared) or 'reference generation only'}, and that is the audio task "
            "type to use; do not claim the other one. The retention marker has to agree with it: "
            "`fully_copy` and `partially_copy` are copies, `reference` and `weak_reference` are "
            "not, and a line that says one while the prefix says the other contradicts itself.")


def base_mode_label_facts(subjects: list[SubjectPlan], labels: tuple[str, ...],
                          picture_roles: tuple[tuple[str, str], ...]) -> str:
    """What the attached pictures ARE, for the three-section formats.

    A base mode has no `subject_definitions` section, so the facts cannot be definition lines.
    Handing `<Subject 1> is the black car in <Picture 1>` to this format hands the model a sentence
    with nowhere to live: it wrote the label, no section defined it, and L2 rejected the brief. i2va
    degraded on exactly that pair 3 times in 7 -- `<Subject 1>` used and defined inline, and
    `<Picture 1>` never cited at all, so L4 fired too.

    The system prompt for these modes already says subject labels do not exist here. The ask was
    contradicting it with a fact sheet in the other format's shape, and a fact sheet that looks like
    output gets used as output.
    """
    role_says = {
        "frame_anchor_first": "IS the target video's first frame, at 0.00 seconds, and belongs to "
                              "[Shot 1]",
        "frame_anchor_last": "IS the target video's last frame and belongs to the final shot; it "
                             "does not belong to [Shot 1]",
    }
    by_label = dict(picture_roles)
    lines: list[str] = []
    for label in labels:
        shows = [s for s in subjects if label in s.sources]
        what = "; ".join(s.descriptor + (f" ({', '.join(s.attributes[:6])})" if s.attributes else "")
                         for s in shows)
        line = f"{label} {role_says.get(by_label.get(label, ''), 'is a reference for this video')}"
        lines.append(line + (f". It shows {what}." if what else "."))
    return "\n".join(lines) + (
        "\n\nThese are the only labels this request has. This format has NO subject_definitions "
        "section, so `<Subject N>` does not exist in it and writing one is a defect rather than a "
        "style choice: name people, objects and places in plain prose, the same way every time they "
        "appear. Cite each picture above by its label in the shot it belongs to — an attached "
        "picture the brief never names is still wired into the render and still costs rows on every "
        "sampling step.")


def reference_picture_facts(picture_roles: tuple[tuple[str, str], ...]) -> str:
    """The one thing a full-reference brief must not say about its pictures.

    ref2va conditions on a picture as content: what it shows is redrawn into the requested scene,
    and there is no mechanism that pins an exact frame -- which is why an anchor role arriving on
    this route is downgraded to a subject reference with a finding (compile.X10). The system prompt
    is the spec, and the spec teaches the standalone `<Picture N>` line for a picture that IS a
    frame, so the model wrote "is the first frame of [Shot 1]" on a single-image ref2va brief 3
    times in 7 and R10 rejected the whole brief. Nothing had told it which case it was in.

    Emitted only when no attached picture actually carries an anchor role, so the statement is read
    off the wiring rather than asserted.
    """
    if any(role.startswith("frame_anchor") for _, role in picture_roles):
        return ""
    return ("None of the pictures here is a frame of the target video. This checkpoint takes them "
            "as content references — what they show is redrawn into the scene the request asks for "
            "— and it has no exact-frame mechanism, so never write that a picture `is the first "
            "frame of` or `is the last frame of` a shot and never claim `keyframe completion`: both "
            "promise an exactness this render cannot deliver. Cite the picture inside the definition "
            "of what it shows, or as the composition, storyboard or style anchor it is.")


def compose_brief(backend: Backend, brief: Brief, subjects: list[SubjectPlan],
                  cards: dict[str, AssetCard], target, labels: tuple[str, ...], *,
                  prompt_name: str = "compose.v2.txt", seed: int | None = None,
                  thinking: bool | None = None, images: list[str] | None = None,
                  style=None, licence=None, scope=None,
                  mode: Mode | None = None,
                  task_types: tuple[str, ...] = (),
                  picture_roles: tuple[tuple[str, str], ...] = (),
                  omit: tuple[str, ...] = ()) -> str:
    """One call. The model writes all six sections and decides everything creative in them.

    The facts are handed over and the craft is not. Labels, duration and dialogue are stated as
    givens; shot count, cuts, camera, performance and the sound shape are the model's.
    """
    # `None` keeps the six-section shape, which is what every caller predating the split passes.
    is_ref = mode is None or mode is Mode.REF2VA
    if not is_ref:
        label_facts = base_mode_label_facts(subjects, labels, picture_roles) if labels else ""
    else:
        # Handed over as the definition LINES, in the exact form the spec wants. An earlier version
        # listed them as "LABEL = description" and the model copied that shape straight into
        # subject_definitions, which then failed the "<Subject N> is ..." rule. A fact sheet that
        # looks like output gets used as output.
        label_facts = "\n".join(_definition_lines(subjects, cards, labels))
        # Every label in the wiring, not only the subject ones. `_definition_lines` walks `subjects`,
        # so an <Audio N> or a bare <Video N> was never named in the ask at all -- and a model cannot
        # bind a label it was not told exists. A video-plus-audio brief came back with the audio
        # referenced nowhere, which is an asset the app would wire in against text that never
        # mentions it.
        unnamed = [lb for lb in labels if lb not in label_facts]
        if unnamed:
            label_facts += ("\n" if label_facts else "") + (
                "Also attached and NOT yet described above: " + ", ".join(unnamed) + ". Every one of these "
                "is wired into the render and must be referenced in the brief — define what it is, and "
                "give it a retention line. An attached reference the text never mentions is dead weight "
                "the model still pays for.\n"
                "For any <Audio N> in that list: you have NOT heard it and cannot describe what it "
                "contains. Say only what its note above states, and never claim it came from a <Video N> "
                "— the wiring decides that and you have not been told it.")
        pics = reference_picture_facts(picture_roles)
        if pics and any(lb.startswith("<Picture") for lb in labels):
            label_facts += ("\n" if label_facts else "") + pics
    dlg = "\n".join(f'- "{d.text}" ({d.language})'
                      + (f", spoken by {d.speaker_hint}" if d.speaker_hint else "")
                      + (" as an off-screen voiceover" if d.voiceover else "")
                      for d in brief.dialogue) or "none — the video has no dialogue"

    ask = (
        f"Request: {brief.intent}\n\n"
        f"Duration is exactly {target.effective_seconds:.3f} seconds; every cut time strictly less "
        f"than {int(target.effective_seconds // 60):02d}:"
        f"{target.effective_seconds % 60:06.3f}, written MM:SS.mmm.\n\n"
        # Three cases, and the middle one used to be told the wrong thing. A base mode with an
        # image attached has a real <Picture 1> and no definition lines at all, so keying the message
        # off the definition lines announced "nothing is attached" over a live reference.
        + (("Facts you must honour — these are the definition lines, use or reword them:\n"
            if is_ref else "Facts you must honour — what each attached picture is:\n")
           + f"{label_facts}\n\n" if label_facts.strip() else
           (f"The only labels that exist for this request are {', '.join(labels)}, and they carry no "
            "separate definitions. Everything else — people, objects, the place — is named in plain "
            "prose, the same way every time it appears.\n\n" if labels else
            "There are NO labels for this request: nothing is attached, so no `<Subject N>`, "
            "`<Picture N>`, `<Video N>` or `<Audio N>` exists. Name people and objects in plain "
            "prose and name them the same way every time.\n\n"))
        +
        f"Dialogue:\n{dlg}\n"
        # Scoped to the full-reference shape: a base mode has no task-type prefix to constrain, and
        # cannot have an <Audio N> at all -- any audio attachment routes to ref2va (mode.py 12.2#1).
        + (f"\n{audio_task_facts(labels, task_types)}\n" if is_ref else "")
    )
    # Ablation lever. Each name drops one block from the ask, so the question "does this block earn
    # its place" is a measurement instead of a belief. Production passes nothing.
    #   facts    the definition lines / the statement of which labels exist
    #   style    what the references look like, or the look the request asked for
    #   licence  which attributes the references govern where the request does not specify them
    #   scope    the creativity setting and its prohibitions
    def kept(block: str) -> bool:
        return block not in omit

    if "facts" in omit:
        ask = re.sub(r"Facts you must honour[^\n]*\n(?:.*?\n)?\n", "", ask, count=1, flags=re.S)
        ask = re.sub(r"(?:The only labels that exist|There are NO labels)[^\n]*\n\n", "", ask,
                     count=1, flags=re.S)
    if kept("style") and style is not None and style.phrase:
        if style.source == "reference":
            ask += (f"\nThe references look like: {style.phrase}. The request did not ask to change "
                    "the medium, so keep it — do not substitute a different one.\n")
        else:
            ask += f"\nThe request asks for this look: {style.phrase}.\n"
    if kept("licence") and licence is not None:
        free = _reference_governed(licence)
        if free:
            ask += (f"\nWhere the request does not specify them, the references govern "
                    f"{', '.join(free)} — read those off the references rather than inventing them; "
                    "where the request does specify one, the request governs it. Anything neither "
                    "the request nor the references settles is yours.\n")
    if kept("scope") and scope is not None:
        # The dial, stated in the ask rather than baked into the system prompt. The same request at
        # two settings must be able to produce two different answers, so this cannot live in a file.
        ask += "\n" + scope.brief_instruction() + "\n"
    if brief.onscreen_text:
        ask += ("\nText that must be visible in frame, in straight double quotes, verbatim: "
                + "; ".join(f'"{t}"' for t in brief.onscreen_text) + "\n")
    if brief.constraints:
        ask += "\nHard constraints:\n" + "\n".join(f"- {c}" for c in brief.constraints)

    reply = backend.chat(
        [{"role": "system", "content": load_prompt(prompt_name)},
         user_message(ask, images)],
        thinking=(True if thinking is None else thinking),
        # 0.3, not 0.85. The binding constraint on a free write is format compliance, and a
        # side-by-side showed 0.3 returning a near-valid six-section brief while 0.85 drifted into
        # preamble and dropped sections. Creativity here comes from the latitude, not the sampler.
        temperature=0.3, seed=seed, max_tokens=20000)
    return reply.content


def _definition_lines(subjects: list[SubjectPlan], cards: dict[str, AssetCard],
                      labels: tuple[str, ...]) -> list[str]:
    """The subject_definitions lines themselves, ready to use or reword."""
    out = []
    for s in subjects:
        attrs = ", ".join(s.attributes) or "as shown in the reference"
        src = ", ".join(s.sources)
        out.append(f"{s.label} is {s.descriptor} in {src}, with {attrs}.")
        if s.pose:
            out.append(f"    (the reference shows {s.label} in a fixed pose; that pose does NOT "
                       "carry over — the request and your beats decide what it does)")
    return out


def plan_shots(backend: Backend, brief: Brief, subjects: list[SubjectPlan],
               cards: dict[str, AssetCard], target, *,
               prompt_name: str = "shotplan.v1.txt", seed: int | None = None,
               thinking: bool | None = None, max_shots: int = 4, licence=None,
               scope=None):
    """The model decides the edit; shots.validate_proposal proves it legal.

    Thinking defaults ON here and nowhere else. The earlier measurement found reasoning worthless
    because every planning field was code-owned -- there was nothing to think about. This call is
    the first real decision the model has been given, so it is the one place the 3.7x is plausibly
    earned, and the eval loop can now actually test that.
    """
    from .shots import shot_schema, validate_proposal

    ask = (
        f"Request: {brief.intent}\n\n"
        f"Total duration: {target.effective_seconds:.3f} seconds "
        f"({target.frames} frames at 24 fps). Every cut must fall inside it.\n\n"
        f"Available subject labels:\n{_asset_digest(cards, subjects)}\n\n"
        f"Maximum {max_shots} shots. One shot is a legitimate answer.\n"
    )
    if brief.shots:
        ask += f"\nThe caller asked for {brief.shots} shot(s); honour that.\n"
    if brief.constraints:
        ask += "\nHard constraints:\n" + "\n".join(f"- {c}" for c in brief.constraints)
    if licence is not None:
        free = _reference_governed(licence)
        if free:
            ask += (f"\nWhere the request does not specify them, the references govern "
                    f"{', '.join(free)}; where the request does specify one, the request governs it. "
                    "Everything the request and the references BOTH leave open is yours to decide.\n")
    if scope is not None:
        ask += "\n" + scope.brief_instruction() + "\n"
        if scope.forbidden or scope.licensed != frozenset(ELEMENTS):
            # The planner has a suggestions channel, so a withheld idea is not a lost one. This is
            # the honest place for "the clip wants a line here": reported to the caller, not added.
            ask += ("If you think the clip would be better with something this setting does not "
                    "license, say so in `suggestions` — it will be reported, not added.\n")

    raw = backend.json_call(
        [{"role": "system", "content": load_prompt(prompt_name)},
         {"role": "user", "content": ask}],
        shot_schema(max_shots), required=("shots",), seed=seed, max_tokens=16000,
        thinking=True if thinking is None else thinking)
    return validate_proposal(raw, target, max_shots=max_shots)


def beat_sheet(backend: Backend, brief: Brief, mode: Mode, subjects: list[SubjectPlan],
               cards: dict[str, AssetCard], shots: list[ShotPlan], *,
               prompt_name: str = "beatsheet.v1.txt", seed: int | None = None,
               thinking: bool | None = None, style=None) -> dict[str, Any]:
    spans = "\n".join(
        f"Shot {s.n}: {s.start_ms / 1000:.2f}s to {s.end_ms / 1000:.2f}s "
        f"({s.duration_ms / 1000:.2f}s long)" for s in shots)
    dlg = "\n".join(f'- "{d.text}" ({d.language})' for d in brief.dialogue) or "none"
    ask = (
        f"Creative request: {brief.intent}\n\n"
        f"Total duration: {sum(s.duration_ms for s in shots) / 1000:.3f} seconds, "
        f"{len(shots)} shot(s).\n{spans}\n\n"
        f"Available subject labels:\n{_asset_digest(cards, subjects)}\n\n"
        f"Dialogue that will be spoken (inserted later, do not write it):\n{dial}\n"
    )
    if brief.constraints:
        ask += "\nHard constraints from the caller:\n" + "\n".join(f"- {c}" for c in brief.constraints)
    if style is not None and style.source == "request":
        ask += (f"\nThe caller stated the style: \"{style.phrase}\". Use it verbatim as "
                "style_phrase, optionally adding lighting or colour detail after it. Do not "
                "substitute a different medium.\n")
        if style.discrepancy:
            ask += (f"The references happen to look like {style.observed_phrase!r}. The caller's "
                    "word still wins; do not blend the two into a contradiction.\n")
    elif style is not None and style.observed_phrase:
        ask += (f"\nThe caller stated no style. The references look like "
                f"{style.observed_phrase!r} — use that as the basis for style_phrase.\n")
    if brief.silent:
        ask += ("\nThe caller asked for NO background music: music must be exactly \"N/A\". "
                "Ambient and physical sound still belong in ambient_sound and sync_sound.")

    obj = backend.json_call(
        [{"role": "system", "content": load_prompt(prompt_name)},
         {"role": "user", "content": ask}],
        beat_schema(len(shots)),
        required=("shots", "style_phrase", "summary", "music"),
        seed=seed, max_tokens=12000, thinking=thinking)
    return _sanitise_beats(obj, subjects, len(shots), style)


def _sanitise_beats(obj: dict[str, Any], subjects: list[SubjectPlan], n: int,
                    style=None) -> dict[str, Any]:
    """The schema constrains shape, not sense. Enforce the enums and label vocabulary here."""
    valid_labels = {s.label for s in subjects}
    shots = obj.get("shots") or []
    clean_shots = []
    for i in range(n):
        s = shots[i] if i < len(shots) else {}
        cam = s.get("camera") or {}
        ctype = cam.get("type") if cam.get("type") in CAMERA_TYPES else None
        clean_shots.append({
            "beat": _one_line(s.get("beat") or ""),
            "camera": {
                "type": ctype,
                "amplitude": cam.get("amplitude") if cam.get("amplitude") in AMPLITUDES else None,
                "speed": cam.get("speed") if cam.get("speed") in SPEEDS else None,
            } if ctype else {},
            "subjects": [x for x in (s.get("subjects") or []) if x in valid_labels],
            "sync_sound": [_one_line(x) for x in (s.get("sync_sound") or []) if x][:3],
        })

    ambient = [_one_line(x) for x in (obj.get("ambient_sound") or []) if x][:3]
    # Enforce the partition: a sound cannot be both synchronized and ambient.
    sync_all = {t.lower() for sh in clean_shots for t in sh["sync_sound"]}
    ambient = [a for a in ambient if a.lower() not in sync_all]

    return {
        "shots": clean_shots,
        "ambient_sound": ambient,
        "style_phrase": _resolve_style_phrase(obj.get("style_phrase") or "", style),
        "summary": _strip_labels(obj.get("summary") or "", keep_subjects=True).strip(),
        "music": _one_line(obj.get("music") or "") or "N/A",
    }


def _resolve_style_phrase(model_phrase: str, style) -> str:
    """A stated style is a requirement, not a suggestion. If the model dropped or replaced the
    caller's medium, put it back in front rather than shipping a substitution."""
    phrase = _strip_labels(_one_line(model_phrase)).rstrip(".")
    if style is None or style.source != "request" or not style.phrase:
        return phrase or (style.phrase if style else "")
    from .style import classify_medium
    if classify_medium(phrase) == style.requested_medium and style.requested_medium:
        return phrase
    head = style.phrase
    rest = ", ".join(x.strip() for x in phrase.split(",") if x.strip()
                     and x.strip().lower() not in head.lower())
    return f"{head}, {rest}" if rest else head


def _one_line(s: str) -> str:
    return re.sub(r"\s+", " ", normalize(str(s))).strip()


def _strip_labels(s: str, keep_subjects: bool = False) -> str:
    """Remove grounded media labels the prose stage must not introduce.

    The harness found that naming attached media in the prompt induces the model to emit
    definition lines for them. Those labels are the template's business, so any that leak
    into prose are removed rather than trusted.
    """
    s = re.sub(r"<\s*(?:Picture|Video|Audio)\s+\d+\s*>", "", s)
    if not keep_subjects:
        s = re.sub(r"<\s*Subject\s+\d+\s*>", "", s)
    return re.sub(r"\s{2,}", " ", s).strip()


def shot_body(backend: Backend, brief: Brief, plan_mode: Mode, shot: ShotPlan,
              subjects: list[SubjectPlan], style_opening: str, *,
              prompt_name: str = "prose_shot.v2.txt", thinking: bool = False,
              seed: int | None = None, images: list[str] | None = None,
              anchor_label: str | None = None, expand_from: str | None = None) -> str:
    """`label_policy` is mode-derived, not a preference.

    `<Subject N>` is a Ref2VA construct: it only means anything because subject_definitions
    defines it, and base modes have no such section. Emitting one in a base mode produces a
    label that names nothing -- the same defect class as <Image 1>. So the instruction and the
    post-clean are both keyed to the mode rather than trusting one wording to cover both.
    """
    ref2va = plan_mode is Mode.REF2VA
    present = [s for s in subjects if s.label in shot.subjects] or subjects
    if ref2va:
        subj_lines = "\n".join(
            f"{s.label} = {s.descriptor}. Appearance (carry these forward): "
            f"{'; '.join(s.attributes) or 'as referenced'}"
            # The plate's pose is NOT named here on purpose. Naming it in order to exclude it
            # made the model negotiate with it instead -- one shot came back with "fists loosely
            # clenched" and the next with "hands relaxed rather than clenched", both of which are
            # the contamination in hedged form. What it is never told, it cannot argue with.
            + (f". Pose comes from the beat, not the reference" if s.pose and not s.pose_licensed
               else "")
            for s in present) or "no referenced subjects"
        label_rule = ("Refer to referenced content by its <Subject N> label exactly as given. "
                      "Never write <Picture N>, <Video N> or <Audio N>.")
    else:
        subj_lines = "\n".join(
            f"{s.descriptor} — appearance: {'; '.join(s.attributes) or 'as referenced'}"
            + (". Pose comes from the beat, not the reference"
               if s.pose and not s.pose_licensed else "")
            for s in present) or "no referenced subjects"
        if anchor_label:
            label_rule = (f"The opening frame is supplied as {anchor_label}. You may write "
                          f"{anchor_label} once when describing what it establishes. Never write "
                          "<Subject N>, <Video N> or <Audio N> — they do not exist in this mode.")
        else:
            label_rule = ("Describe everything in plain words. Never write <Subject N>, "
                          "<Picture N>, <Video N> or <Audio N> — no reference labels exist here.")
    dlg = "\n".join(
        f"{{{{D{i}}}}} = a line spoken by {(d.speaker_hint or 'the speaker')}"
        f"{' as an off-screen voiceover' if d.voiceover else ''} "
        f"({len(d.text.split())} words, {d.language})"
        for i, d in enumerate(shot.dialogue, 1)) or "none"
    sync = "\n".join(f"- {t}" for t in shot.sync_sound) or "none"
    text_on_screen = "\n".join(f'- "{t}"' for t in shot.onscreen_text) or "none"

    ask = (
        f"Creative request: {brief.intent}\n"
        f"Overall style (already stated elsewhere, do not restate it): {style_opening}\n\n"
        f"You are writing SHOT {shot.n} of {'1' if shot.n == 1 else 'the sequence'}, covering "
        f"{shot.start_ms / 1000:.2f}s to {shot.end_ms / 1000:.2f}s "
        f"({shot.duration_ms / 1000:.2f} seconds of screen time).\n"
        f"What must happen in this shot: {shot.beat or brief.intent}\n\n"
        f"Subjects visible in this shot:\n{subj_lines}\n\n"
        f"Synchronized sound caused inside this shot (weave in where it occurs):\n{sync}\n\n"
        f"Dialogue placeholders to place:\n{dial}\n\n"
        f"Text visible in frame:\n{text_on_screen}\n\n"
        f"WORD TARGET: {shot.word_target} words. HARD MAXIMUM: "
        f"{int(shot.word_target * 1.1)} words. Do not exceed the maximum.\n\n"
        f"How to name things in this shot: {label_rule}\n"
    )
    if shot.n > 1:
        ask += ("This shot follows a cut. Open by naming the new framing or subject so the cut "
                "carries new information.\n")
    if shot.camera:
        ask += "Place {{CAM}} exactly once, where the camera move happens.\n"
    if expand_from:
        # Under-writing is the documented failure mode here, so the retry hands back the short
        # draft and asks for more OBSERVATION rather than repeating the request for length.
        ask += ("\nA previous attempt came in short:\n\n" + expand_from
                + "\n\nRewrite it at the target length by describing MORE OF WHAT IS IN THE "
                  "FRAME — surfaces, materials, the ground, the background, the light, the "
                  "direction of each movement. Keep every placeholder. Add no new events.\n")

    reply = backend.chat(
        [{"role": "system", "content": load_prompt(prompt_name)},
         user_message(ask, images)],
        thinking=thinking, temperature=0.8, seed=seed, max_tokens=6000)
    return _clean_body(reply.content, keep_subjects=ref2va, keep_picture=bool(anchor_label))


def _clean_body(s: str, keep_subjects: bool = True, keep_picture: bool = False) -> str:
    s = s.strip()
    s = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", s).strip()
    # Strip anything that looks like the model reintroducing structure.
    s = re.sub(r"^\s*(detailed_description|integrated_multimodal_description)\s*:\s*", "", s)
    s = re.sub(r"\[Shot\s+\d+\]\s*", "", s)
    s = re.sub(r"^\s*At\s+\d{2}:\d{2}\.\d{3},?\s*", "", s)
    drop = ["Video", "Audio"]
    if not keep_picture:
        drop.append("Picture")
    if not keep_subjects:
        drop.append("Subject")
    s = re.sub(rf"<\s*(?:{'|'.join(drop)})\s+\d+\s*>", "", s)
    return re.sub(r"[ \t]+", " ", normalize(s)).strip()
