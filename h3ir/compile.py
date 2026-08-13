"""The orchestrator: Brief -> validated IRDocument.

Stage order, and why it is this order:

  B  analyse      per-asset, cached, no dependencies -> can always run first
  A' mode         needs the cards (the anchor-vs-reference call reads what the images ARE)
  A" lora         needs the mode (a LoRA is valid for one checkpoint, not both)
  C1 plan         deterministic skeleton: labels, subjects, speakers, shot spans, budgets
  D1 beat sheet   one structured call: what happens per shot, camera, the sound partition
  C2 plan         rebuilt with the beats folded in
  D2 prose        one call per shot, each with its own span and word budget
  E  render       deterministic; then validated, then re-rendered and byte-compared
"""
from __future__ import annotations

import logging
import re
import time
from dataclasses import replace
from typing import Any

from .analyse import analyse_all
from .backend import Backend, BackendError
from .config import get_config
from . import creativity
from .creativity import Scope
from .draft import deterministic_draft
from .lora import resolve_loras
from .mode import infer_mode, needs_clarification
from .models import AssetCard, AssetKind, Brief, Finding, IRDocument, Mode, Role
from .plan import ProfileOptions, allocate_from_proposal, build_plan
from .licence import resolve_licence
from .style import resolve_style
from .prose import beat_sheet, compose_brief, plan_shots, shot_body
from .render import render_ir
from .repair import repair as repair_brief
from .tokens import count as token_count
from .validate import Context, validate

log = logging.getLogger("h3ir.compile")

IR_VERSION = "1"

# Two rounds. A third has never converged in practice and each costs a full generation.
MAX_FIX_ROUNDS = 2


class CompilerInvariantError(RuntimeError):
    """The deterministic path produced something invalid. Ours to fix, never shipped."""


def compile_brief(brief: Brief, *, backend: Backend | None = None,
                  opts: ProfileOptions | None = None, seed: int | None = None,
                  use_cache: bool = True, thinking_prose: bool = False, llm: bool = True,
                  thinking_planning: bool | None = None,
                  write_first: bool = True,
                  beatsheet_prompt: str = "beatsheet.v1.txt",
                  shotplan_prompt: str = "shotplan.v1.txt",
                  # None selects by mode: the six-section composer carries the full-reference
                  # guide and the three-section one carries the base guide. A single composer for
                  # both modes was why five of six suite briefs fell back -- every base-mode brief
                  # was handed a spec that teaches <Subject N>, then failed L2 for using it.
                  compose_prompt: str | None = None,
                  prose_prompt: str = "prose_shot.v2.txt",
                  omit: tuple[str, ...] = (),
                  transcripts: dict[str, str] | None = None) -> IRDocument:
    cfg = get_config()
    opts = opts or ProfileOptions(name=cfg.profile)
    own_backend = backend is None
    backend = backend or Backend(cfg)
    timings: dict[str, float] = {}
    # arXiv:2606.09662: thinking helps PLANNING constraints (+5.3pp) and hurts PRECISION ones
    # (-8.5pp). Planning is what the beat sheet does; every precision field is owned by code.
    # That contingency is what makes thinking safe here -- see the note in prose.beat_sheet.
    if thinking_planning is None:
        thinking_planning = cfg.llm.default_thinking

    try:
        backend.require_available()

        t = time.time()
        cards: dict[str, AssetCard] = analyse_all(
            backend, brief.assets, use_cache=use_cache, seed=seed, transcripts=transcripts)
        timings["analyse_s"] = round(time.time() - t, 2)

        t = time.time()
        decision = infer_mode(brief, cards, backend)
        mode = decision.mode
        timings["mode_s"] = round(time.time() - t, 2)
        log.info("mode=%s (%s, conf %.2f)", mode.value, decision.rule_fired, decision.confidence)

        loras, lora_findings = resolve_loras(brief.loras, mode, brief)

        # A caller override is honoured, and T2VA binds no reference labels at all -- so assets plus
        # T2VA is a contradiction the caller stated. Honour the mode, DROP the assets, and say so.
        # Dropping them is what keeps the manifest honest: it must never publish an asset the text
        # cannot bind, because the app wires the graph from it. Inference never produces this pairing;
        # only an explicit `brief.mode` can, and nothing checked it.
        if mode is Mode.T2VA and brief.assets:
            dropped = [a.kind.value for a in brief.assets]
            lora_findings.append(Finding(
                "X16-assets-dropped-for-mode", "WARN",
                f"the caller pinned mode=t2va and attached {len(dropped)} reference(s) "
                f"({', '.join(sorted(set(dropped)))}). Text-to-video binds no reference labels, so "
                "they cannot be referenced and have been dropped rather than published in a manifest "
                "the app would wire in against text that never mentions them. Remove the override to "
                "have the mode inferred from the assets."))
            brief = replace(brief, assets=[])
            cards = {}

        # One resolution, used by both paths. The caller's stated style wins; a contradiction with
        # what the reference actually looks like is REPORTED, never silently resolved and never
        # turned into a question. See style.py for why that asymmetry is the right one.
        licence = resolve_licence(brief, cards)
        style = resolve_style(brief, cards, licence)
        if style.note():
            lora_findings.append(Finding("S6-style-discrepancy", "WARN", style.note()))
        if licence.note():
            lora_findings.append(Finding("S7-transformation-intent", "INFO", licence.note()))

        # A frame-anchor role is an FL2VA-checkpoint concept: that checkpoint pins the keyframe
        # as a cond latent that is never denoised. Ref2VA has no such mechanism, so carrying the
        # role into a Ref2VA plan would write a retention line promising something the render
        # cannot deliver. Downgrade it and say so, rather than asserting it.
        if mode is Mode.REF2VA:
            for a in brief.assets:
                if a.role in (Role.FRAME_ANCHOR_FIRST, Role.FRAME_ANCHOR_LAST):
                    lora_findings.append(Finding(
                        "X10-anchor-role-downgraded", "WARN",
                        f"an asset was marked {a.role.value} but this request routes to the "
                        "ref2va checkpoint, which has no exact-frame mechanism; treating it as "
                        "a subject reference instead"))
                    a.role = Role.SUBJECT

        # --- the product floor: a complete, valid IR with no prose model involved ---------
        t = time.time()
        draft_plan = deterministic_draft(brief, mode, cards, opts=opts, loras=loras,
                                         mode_decision=decision)
        _inject_lora_triggers(draft_plan, opts)
        sheet_flags = tuple(c.is_reference_sheet for c in cards.values())
        draft_result, draft_findings, draft_tokens = _assess(
            draft_plan, brief, mode, opts, lora_findings, sheet_flags, licence, style)
        timings["draft_s"] = round(time.time() - t, 2)
        draft_errors = [f for f in draft_findings if f.severity == "ERROR"]
        if draft_errors:
            # The draft is deterministic. If it is invalid that is our bug, not the model's,
            # and there is nothing to fall back to -- so it raises rather than shipping.
            raise CompilerInvariantError(
                "the deterministic draft failed its own validator: "
                + "; ".join(str(f) for f in draft_errors[:4]))

        # Filled by the planning stage; read by _document, which is defined before it runs.
        shot_plan_record: dict[str, Any] = {}

        def _document(plan, result, findings, n_tokens, source, reason=None) -> IRDocument:
            return IRDocument(
                ir_version=IR_VERSION, profile=opts.name, mode=mode,
                prompt=result.prompt, plan=plan, sections=result.sections,
                prompt_tokens=n_tokens, findings=findings,
                source=source, fallback_reason=reason,
                provenance={
                    "analyzer_model": backend.cfg.model,
                    "prose_model": backend.cfg.model if source == "enriched" else None,
                    "source": source,
                    "fallback_reason": reason,
                    "seed": seed,
                    # What the dial decided, in the record. Proportionality is now part of the bar
                    # the output is judged against, so the setting and its consequences have to be
                    # auditable next to the artifact rather than inferred from it.
                    "creativity": _scope(brief, draft_plan).note(),
                    "omit": list(omit) or None,
                    "request": brief.intent,
                    "beatsheet_prompt": beatsheet_prompt,
                "shotplan_prompt": shotplan_prompt,
                "shot_plan": dict(shot_plan_record) or None,
                    "prose_prompt": prose_prompt,
                    "thinking_prose": thinking_prose,
                    "thinking_planning": thinking_planning,
                    "guided_decoding": cfg.llm.guided_decoding,
                    "server_version": backend.server_version(),
                    "card_hashes": {k: v.hash() for k, v in cards.items()},
                    "plan_hash": plan.hash(),
                    "draft_tokens": draft_tokens,
                    "timings": timings,
                    "clarification": needs_clarification(decision),
                })

        if not llm:
            return _document(draft_plan, draft_result, draft_findings, draft_tokens,
                             "draft", "the caller asked for the draft only")

        # --- write first, verify second --------------------------------------------------
        # The inversion. Two composed architectures produced structurally identical output while
        # an unharnessed write beat both, so the machinery moves from BUILDING the text to
        # CHECKING it. Every guarantee survives; none of them pre-writes a sentence any more.
        if write_first:
            try:
                t = time.time()
                labels = tuple(m.label for m in draft_plan.manifest)
                imgs = [a.path for a in brief.assets
                        if a.kind.value == "image" and a.path][:2] or None
                scope = _scope(brief, draft_plan)
                chosen_compose = compose_prompt or (
                    "compose.v2.txt" if mode is Mode.REF2VA else "compose_base.v1.txt")
                # The wiring's own facts travel with the ask: which mode's document shape this is,
                # what the pictures are, and what the audio roles settle. Each of those was a
                # question the model had to guess at, and each guess had a rule waiting for it.
                pic_roles = tuple((m.label, m.role.value) for m in draft_plan.manifest
                                  if m.kind.value == "image")
                written = compose_brief(backend, brief, draft_plan.subjects, cards,
                                       draft_plan.target, labels,
                                       prompt_name=chosen_compose, seed=seed,
                                       thinking=thinking_planning, images=imgs,
                                       style=style, licence=licence, scope=scope,
                                       mode=mode, task_types=tuple(draft_plan.task_types),
                                       picture_roles=pic_roles, omit=omit)
                timings["compose_s"] = round(time.time() - t, 2)

                from .prose import _definition_lines
                from .prose import _definition_lines, fix_with_findings

                def _verify(candidate: str):
                    fx = repair_brief(candidate, target=draft_plan.target, mode=mode,
                                      labels=labels,
                                      dialogue=tuple(d.text for d in brief.dialogue),
                                      style_phrase=style.phrase,
                                      definitions=tuple(_definition_lines(
                                          draft_plan.subjects, cards, labels)))
                    n = token_count(fx.text)
                    found = validate(fx.text, _written_context(
                        brief, mode, draft_plan, cards, n, style, licence))
                    return fx, found, n

                fixed, found, n_tokens = _verify(written)
                errors = [f for f in found if f.severity == "ERROR"]
                rounds, mechanical_repairs = 0, list(fixed.repairs)
                stuck: list[str] = []

                # Send the findings back to the model rather than editing the text ourselves.
                # Capped, for the same reason the truncation ladder is capped: an unbounded retry
                # turns a stubborn failure into minutes of waiting.
                #
                # ERRORs only, and this is now load-bearing rather than incidental. An ERROR is a
                # decidable fact about the artifact; a WARN may be a judgement a competent director
                # would argue with. Sending a WARN here would have the model rewrite legitimate work
                # to satisfy a rule that should never have had a vote -- which is exactly what a
                # similarity heuristic promoted to ERROR was doing before the rule audit. Keep the
                # boundary: nothing reaches the model that the owner might disagree with.
                while errors and rounds < MAX_FIX_ROUNDS:
                    rounds += 1
                    before = {f.rule for f in errors}
                    t2 = time.time()
                    # Both namespaces: the media labels come from the wiring and the subject
                    # labels from the plan, and L2 is about the second kind.
                    inventory = labels + tuple(x.label for x in draft_plan.subjects)
                    # The section list too: the fix ask used to say "the corrected six
                    # sections" unconditionally, which pushed a three-section base brief toward the
                    # full-reference format during the pass meant to correct it.
                    candidate = fix_with_findings(backend, fixed.text, errors,
                                                  labels=inventory, sections=_sections_for(mode),
                                                  seed=seed)
                    timings[f"fix{rounds}_s"] = round(time.time() - t2, 2)
                    fixed, found, n_tokens = _verify(candidate)
                    mechanical_repairs += fixed.repairs
                    errors = [f for f in found if f.severity == "ERROR"]
                    after = {f.rule for f in errors}
                    survived = before & after
                    if survived:
                        # A finding that survives being stated plainly is a signal about the
                        # FINDING, not only about the model: either the message is unclear or the
                        # rule is wrong. Recorded distinctly so the validator can improve.
                        stuck.extend(sorted(survived))
                        log.warning("findings survived fix round %d: %s", rounds,
                                    ", ".join(sorted(survived)))
                    if not errors:
                        break

                for r in mechanical_repairs:
                    lora_findings.append(Finding("X12-brief-repaired", "INFO", r))
                for rule in dict.fromkeys(stuck):
                    lora_findings.append(Finding(
                        "X14-finding-unfixable", "WARN",
                        f"{rule} survived a correction pass unchanged — the message may be "
                        "unclear or the rule may be wrong"))

                findings = list(lora_findings) + list(fixed.findings) + found
                if errors:
                    reason = (f"the written brief still failed after {rounds} correction pass(es): "
                              + "; ".join(f.rule for f in errors[:4]))
                    log.warning("falling back to the draft — %s", reason)
                    doc = _document(draft_plan, draft_result, draft_findings, draft_tokens,
                                    "draft", reason)
                    doc.findings = list(draft_findings) + [
                        Finding("X13-written-rejected", "WARN", reason)]
                    doc.provenance["rejected_written"] = fixed.text
                    doc.provenance["rejected_rules"] = [f"{f.rule}: {f.msg}" for f in errors]
                    doc.provenance["fix_rounds"] = rounds
                    doc.provenance["repairs"] = mechanical_repairs
                    return doc

                doc = _document(draft_plan, draft_result, draft_findings, draft_tokens,
                                "written")
                doc.source = "written"
                doc.prompt = fixed.text
                doc.sections = _split_written(fixed.text)
                doc.prompt_tokens = n_tokens
                doc.findings = findings
                doc.provenance["repairs"] = mechanical_repairs
                doc.provenance["fix_rounds"] = rounds
                doc.provenance["unfixable"] = list(dict.fromkeys(stuck))
                doc.provenance["compose_prompt"] = chosen_compose
                doc.provenance["timings"] = timings
                return doc
            except BackendError as e:
                reason = f"the composing model failed: {type(e).__name__}: {e}"
                log.warning("falling back to the draft — %s", reason)
                doc = _document(draft_plan, draft_result, draft_findings, draft_tokens,
                                "draft", reason)
                doc.findings = list(draft_findings) + [
                    Finding("X9-model-unavailable-midway", "WARN", reason)]
                return doc

        # --- the additive pass: prose enrichment over a bounded surface ------------------
        try:
            skeleton = build_plan(brief, mode, cards, opts=opts, loras=loras,
                                  mode_decision=decision)

            # The model decides the edit. Code then proves it legal; a proposal that cannot be
            # repaired unambiguously falls back to the draft rather than being forced into shape.
            t = time.time()
            scope = _scope(brief, skeleton)
            proposal = plan_shots(backend, brief, skeleton.subjects, cards, skeleton.target,
                                  prompt_name=shotplan_prompt, seed=seed,
                                  thinking=thinking_planning, max_shots=opts.max_shots,
                                  licence=licence, scope=scope)
            for sug in proposal.suggestions:
                lora_findings.append(Finding("S8-planner-suggestion", "INFO", sug))
            timings["shotplan_s"] = round(time.time() - t, 2)
            for r in proposal.repairs:
                lora_findings.append(Finding("X11-shot-plan-repaired", "WARN", r))
            if not proposal.ok:
                raise BackendError("the shot plan was rejected: "
                                   + "; ".join(proposal.rejections))
            shot_plan_record.update({
                "shots": len(proposal.shots),
                "reasoning": proposal.reasoning,
                "purposes": [f"{sh.purpose}/{sh.framing}" for sh in proposal.shots],
                "cuts_s": [round(sh.start_ms / 1000, 3) for sh in proposal.shots[1:]],
                "repairs": list(proposal.repairs),
                "suggestions": list(proposal.suggestions),
            })
            log.info("shot plan: %d shot(s) — %s", len(proposal.shots), proposal.reasoning[:120])

            t = time.time()
            sheet = beat_sheet(backend, brief, mode, skeleton.subjects, cards,
                               allocate_from_proposal(skeleton.target, proposal.shots, mode, opts),
                               prompt_name=beatsheet_prompt, seed=seed,
                               thinking=False, style=style)
            timings["beats_s"] = round(time.time() - t, 2)

            sound_events: list[dict[str, Any]] = []
            for i, sh in enumerate(sheet["shots"], 1):
                for txt in sh.get("sync_sound", []):
                    sound_events.append({"text": txt, "layer": "sync", "shot": i})
            for txt in sheet.get("ambient_sound", []):
                sound_events.append({"text": txt, "layer": "ambient"})

            plan = build_plan(brief, mode, cards, proposal=proposal.shots,
                              sound_events=sound_events,
                              style_phrase=sheet["style_phrase"], music=sheet["music"],
                              opts=opts, loras=loras, mode_decision=decision)
            plan.summary = sheet["summary"]
            _inject_lora_triggers(plan, opts)

            t = time.time()
            anchor_images = [m for m in plan.manifest if m.kind.value == "image"]
            anchor_label = (anchor_images[0].label
                            if anchor_images and mode is not Mode.REF2VA else None)
            for shot in plan.shots:
                imgs = None
                if shot.n == 1 and anchor_images:
                    paths = [a.path for a in brief.assets
                             if a.sha256 in {m.sha256 for m in anchor_images} and a.path]
                    imgs = paths[:2] or None
                shot.body = shot_body(backend, brief, mode, shot, plan.subjects,
                                      plan.style_phrase, prompt_name=prose_prompt,
                                      thinking=thinking_prose, seed=seed, images=imgs,
                                      anchor_label=anchor_label if shot.n == 1 else None)
                # Under-writing is the documented failure mode of a prose model on this task,
                # so the floor is enforced with one retry rather than asked for again.
                floor = int(shot.word_target * 0.75)
                if len(shot.body.split()) < floor:
                    log.info("shot %d landed %d words under a %d floor; expanding once",
                             shot.n, len(shot.body.split()), floor)
                    shot.body = shot_body(backend, brief, mode, shot, plan.subjects,
                                          plan.style_phrase, prompt_name=prose_prompt,
                                          thinking=thinking_prose, seed=(seed or 0) + 101,
                                          images=imgs,
                                          anchor_label=anchor_label if shot.n == 1 else None,
                                          expand_from=shot.body)
            timings["prose_s"] = round(time.time() - t, 2)

            _reconcile_scopes(plan)
            result, findings, n_tokens = _assess(plan, brief, mode, opts, lora_findings,
                                                 sheet_flags, licence, style)
            errors = [f for f in findings if f.severity == "ERROR"]
            if errors:
                reason = ("the enriched brief failed validation: "
                          + "; ".join(f"{f.rule}" for f in errors[:4]))
                log.warning("falling back to the deterministic draft — %s", reason)
                doc = _document(draft_plan, draft_result, draft_findings, draft_tokens,
                                "draft", reason)
                doc.findings = list(draft_findings) + [
                    Finding("X8-enriched-rejected", "WARN", reason)]
                return doc
            return _document(plan, result, findings, n_tokens, "enriched")

        except BackendError as e:
            reason = f"the prose model failed: {type(e).__name__}: {e}"
            log.warning("falling back to the deterministic draft — %s", reason)
            doc = _document(draft_plan, draft_result, draft_findings, draft_tokens,
                            "draft", reason)
            doc.findings = list(draft_findings) + [
                Finding("X9-model-unavailable-midway", "WARN", reason)]
            return doc

    finally:
        if own_backend:
            backend.close()


def _reconcile_scopes(plan) -> None:
    """Make the retention contract describe what the description actually says.

    The beat sheet names which subjects are in which shot, and when it names none the planner
    used to claim ALL of them -- which then reads as a contract promising a subject the prose
    never mentions. Rather than warn about a contradiction we created, derive the scope from the
    rendered prose: `(appears in [Shot N])` now means "the prose of Shot N cites this label".

    A subject cited in no shot at all is still a real finding, caught by R5/L7 -- it means the
    definition earned no place in the video.
    """
    for subj in plan.subjects:
        cited = [s.n for s in plan.shots if subj.label in (s.body or "")]
        planned = [s.n for s in plan.shots if subj.label in s.subjects]
        # Never NARROW the contract to the citations. A shot may describe a subject without
        # re-labelling it, and claiming "(appears in [Shot 2])" when the man also walks through
        # Shot 1 tells H3 his identity need not hold there -- a weaker instruction, not a truer
        # one. The union is what is true of the video; being cited nowhere at all is the real
        # finding, and R5/L7 report that.
        if cited:
            subj.appears_in = sorted(set(planned) | set(cited)) or cited
        # shot.subjects is deliberately NOT pruned: X7 reads it to notice a planned subject the
        # prose never named, and pruning it first made that check unable to fire.


def _split_written(text: str) -> dict[str, str]:
    """Both namespaces. Searching only the six-section names dropped the entire description from
    every base-mode brief -- `integrated_multimodal_description` is not in that list -- and did it
    silently, because the validator reads the prompt text and not this dict. The written text's own
    headers say which shape it is; there is no need to be told."""
    from .repair import BASE_SECTION_NAMES, SECTION_NAMES
    out: dict[str, str] = {}
    hits = [(m.start(), m.end(), n) for n in dict.fromkeys(SECTION_NAMES + BASE_SECTION_NAMES)
            for m in [re.search(rf"^{n}\s*:", text, re.M)] if m]
    hits.sort()
    for i, (s0, e0, name) in enumerate(hits):
        end = hits[i + 1][0] if i + 1 < len(hits) else len(text)
        out[name] = text[e0:end].strip()
    return out


def _written_context(brief: Brief, mode, plan, cards, n_tokens: int, style, licence=None):
    """The same Context the composed path used. The rules do not change; only where they run."""
    counts = plan.label_counts()
    declared = tuple((m.label, m.role.value, "") for m in plan.manifest)
    paired = tuple((m.label, m.paired_with or "", m.seconds,
                    next((v.seconds for v in plan.manifest if v.label == m.paired_with), None))
                   for m in plan.manifest if m.paired_with)
    return Context(
        mode=mode.value,
        duration_s=plan.target.effective_seconds,
        n_pictures=counts["Picture"], n_videos=counts["Video"], n_audios=counts["Audio"],
        expected_dialogue=tuple(d.text for d in brief.dialogue),
        lora_triggers=tuple(t for l in plan.loras for t in l.triggers),
        onscreen_text=tuple(brief.onscreen_text),
        prompt_tokens=n_tokens,
        require_music_na=True if brief.silent else None,
        generation_task="video editing" not in plan.task_types,
        declared_roles=declared, paired_audio=paired,
        standalone_audio=_standalone_audio(plan),
        forbid_keyframe_refs=(mode is Mode.REF2VA),
        pose_licensed=any(x.pose_licensed for x in plan.subjects),
        has_reference_sheet=any(c.is_reference_sheet for c in cards.values()),
        wardrobe_terms=_wardrobe_terms(plan, licence),
        transformed_from=_transformed_from(style, licence),
        scope=_scope(brief, plan),
    )


def _standalone_audio(plan) -> tuple[str, ...]:
    """Which <Audio N> labels are wired standalone. Stated positively so the validator can tell "the
    wiring says unpaired" from "nobody said", which is the difference between a real finding and the
    false positive that fired on the spec's own example."""
    return tuple(m.label for m in plan.manifest
                 if m.kind is AssetKind.AUDIO and not m.paired_with)


def _sections_for(mode) -> tuple[str, ...]:
    from .validate import BASE_SECTIONS, REF_SECTIONS
    return tuple(REF_SECTIONS if mode is Mode.REF2VA else BASE_SECTIONS)


def _scope(brief: Brief, plan) -> Scope:
    """The request's licence, read once and used by the writer, the validator and the record.

    An attached `<Audio N>` counts as the caller supplying speech: the spec's own audio-reuse case
    reperforms lines from a reference, and those `<d>` blocks are obedience, not invention. Better to
    abstain than to strip a legitimate reperformance.
    """
    counts = plan.label_counts()
    return creativity.build(
        brief.intent, level=brief.creativity, constraints=tuple(brief.constraints),
        has_dialogue=bool(brief.dialogue) or counts["Audio"] > 0,
        has_onscreen_text=bool(brief.onscreen_text),
        silent=brief.silent)


def _transformed_from(style=None, licence=None) -> str:
    """The reference's medium bucket, when the request asked to depart from it. Otherwise "".

    Four conditions, all necessary, and the fourth was caught by its own false positive on a real
    compile before shipping. A transformation must have been asked for; the style decision must
    actually have gone to the request (if `resolve_style` fell through to the plate, the prose is
    SUPPOSED to read as the reference and R23 would be fighting our own output); **both media must be
    classifiable**; and the buckets must differ.

    The third condition is the one that matters and it is §35's line one layer down. The first version
    armed whenever `observed != requested`, which is True when `requested` is `None` -- and `None`
    means *the classifier could not place it*, not *it is different*. On the live brief the plate is
    "Digital illustration" (`2d-animation`) and the target is "a 1990s cel animation"
    (`None` -- outside the closed vocabulary, which is exactly why `transform_target` reads targets
    from the request). Both media are in fact 2D, so the correct opening lands in the reference's own
    bucket and the rule fired on output that was right. Absence of a statement is not a statement of
    absence.

    **What this costs, stated plainly: R23 only covers transformations that cross a bucket the
    classifier knows** -- live-action to animation, animation to stop-motion, and so on. A restyle
    within one family is invisible to it, and no bucket comparison can see that one. That is the
    honest limit of a deterministic check here.
    """
    if style is None or licence is None or not licence.medium_transferred:
        return ""
    if style.source != "request" or not style.observed_medium or not style.requested_medium:
        return ""
    return "" if style.observed_medium == style.requested_medium else style.observed_medium


def _wardrobe_terms(plan, licence=None) -> tuple[str, ...]:
    """Garment words the subject should be re-named with, as a drift defence -- UNLESS the request is
    changing the wardrobe.

    R15 fired on a brief whose entire purpose was "change the shirt on the man in this video", telling
    it to keep restating the reference's navy t-shirt. Holding onto the garment the caller asked to
    replace is not drift protection, it is the opposite. `licence.governs[WARDROBE] == "request"` is
    already the settled answer to who owns that attribute, so this defers to it.
    """
    from .licence import GARMENT_WORDS, WARDROBE
    if licence is not None and licence.governs.get(WARDROBE) == "request":
        return ()
    out: list[str] = []
    for s in plan.subjects:
        for a in s.attributes:
            for w in GARMENT_WORDS:
                if w in a.lower() and w not in out:
                    out.append(w)
    return tuple(out[:4])


def _assess(plan, brief: Brief, mode, opts: ProfileOptions,
            lora_findings: list[Finding], sheet_flags=(),
            licence=None, style=None) -> tuple[Any, list[Finding], int]:
    """Render, prove the render is reproducible, and validate. One path for the deterministic
    draft and for the enriched brief, so they cannot diverge in how they are checked."""
    result = render_ir(plan, opts)
    again = render_ir(plan, opts)
    findings: list[Finding] = list(lora_findings)
    if again.prompt != result.prompt:
        findings.append(Finding("X1-render-determinism", "ERROR",
                                "re-rendering the same plan produced different text"))
    counts = plan.label_counts()
    n_tokens = token_count(result.prompt)
    declared = tuple((m.label, m.role.value, "") for m in plan.manifest)
    paired = tuple((m.label, m.paired_with or "", m.seconds,
                    next((v.seconds for v in plan.manifest if v.label == m.paired_with), None))
                   for m in plan.manifest if m.paired_with)
    ctx = Context(
        mode=mode.value,
        duration_s=plan.target.effective_seconds,
        n_pictures=counts["Picture"], n_videos=counts["Video"], n_audios=counts["Audio"],
        expected_dialogue=tuple(d.text for d in brief.dialogue),
        lora_triggers=tuple(t for l in plan.loras for t in l.triggers),
        onscreen_text=tuple(brief.onscreen_text),
        prompt_tokens=n_tokens,
        require_music_na=True if brief.silent else None,
        generation_task="video editing" not in plan.task_types,
        declared_roles=declared,
        paired_audio=paired,
        standalone_audio=_standalone_audio(plan),
        forbid_keyframe_refs=(mode is Mode.REF2VA),
        pose_licensed=any(x.pose_licensed for x in plan.subjects),
        has_reference_sheet=any(c for c in (sheet_flags or ()) if c),
        wardrobe_terms=_wardrobe_terms(plan, licence),
        transformed_from=_transformed_from(style, licence),
        scope=_scope(brief, plan),
    )
    # Nothing in this system can hear, so an audio reference whose ROLE claims a sonic property and
    # whose text describes none is a reference carrying no information at all -- H3's tokenizer emits
    # `"<Audio j>: "` and never the signal. A transcript does not close this: it supplies the words,
    # not the timbre, the delivery or the tempo. Only the caller can say what it sounds like, so this
    # names what to supply rather than guessing.
    for m in plan.manifest:
        if m.kind is not AssetKind.AUDIO or m.characterisation:
            continue
        want = {Role.VOICE_TIMBRE: "the voice — \"his own voice, calm and low\"",
                Role.BGM: "the music — instrumentation and tempo",
                Role.SFX: "the sound"}.get(m.role)
        if want:
            findings.append(Finding(
                "X15-audio-uncharacterised", "WARN",
                f"{m.label} is wired as {m.role.value} but nothing describes {want}. Nothing here "
                "can hear, and the IR text is the only channel the encoder has for that audio, so "
                "an uncharacterised reference contributes nothing. Supply it as the asset's note."))

    findings += validate(result.prompt, ctx)
    for note in result.notes:
        # INFO, not WARN. Each of these reports a repair that SUCCEEDED -- a missing label
        # attached, a redundant camera sentence removed, an overrun trimmed. The artifact is
        # correct afterwards, so counting them as warnings made the gate block on the machinery
        # working. Their frequency still matters and is tracked as its own metric.
        findings.append(Finding("X5-render-note", "INFO", note))
    actors = {x.label for x in plan.subjects if x.kind in ("person", "animal", "character")}
    for shot in plan.shots:
        shipped = result.shot_bodies.get(shot.n, shot.body or "")
        for label in shot.subjects:
            if label in actors and label not in shipped:
                findings.append(Finding("X7-subject-not-cited", "WARN",
                                        f"{label} is planned into shot {shot.n} but its prose "
                                        "never names it"))
    return result, findings, n_tokens


def _inject_lora_triggers(plan, opts: ProfileOptions) -> None:
    """A trigger is text in the IR, so it goes in the mode's style slot -- the one place the
    spec already reserves for a style declaration. Wrong slot or wrong bytes and the LoRA is
    loaded, costs full compute, and does nothing."""
    triggers = [t["text"] for l in plan.loras for t in l.triggers
                if t.get("placement", "style") == "style" for _ in range(int(t.get("count", 1)))]
    if not triggers:
        return
    joined = " ".join(triggers)
    phrase = plan.style_phrase.strip().rstrip(".,")
    # The trigger becomes item one of the style list, which both modes render from.
    plan.style_phrase = f"{joined}, {phrase}" if phrase else joined


AMEND_SCHEMA = {
    "title": "BriefAmendment",
    "type": "object",
    "additionalProperties": False,
    "required": ["intent", "changed"],
    "properties": {
        "intent": {"type": "string"},
        "seconds": {"type": "number"},
        "shots": {"type": "integer"},
        "constraints": {"type": "array", "items": {"type": "string"}},
        "changed": {"type": "array", "items": {"type": "string"}},
    },
}


def amend_brief(brief: Brief, change: str, backend: Backend) -> tuple[Brief, list[str]]:
    """Turn a plain-language refinement into an amended Brief.

    Only fields a caller could legitimately set are amendable; nothing structural is, because
    the compiler owns structure. Assets and dialogue are never touched by the model -- a
    refinement cannot silently rewrite the user's own words.
    """
    ask = (f"Current request: {brief.intent}\n"
           f"Current duration: {brief.seconds} seconds. Current shot count: "
           f"{brief.shots or 'automatic'}.\n"
           f"Existing constraints: {brief.constraints or 'none'}\n\n"
           f"The user now says: {change}\n\n"
           "Rewrite the request to incorporate what they asked for. Keep everything they did "
           "not ask to change. If they asked for a different length or a different number of "
           "shots, set those fields. Put stylistic or negative instructions in `constraints`. "
           "List in `changed` which fields you altered.")
    obj = backend.json_call(
        [{"role": "system", "content": "You amend a video request. Change only what was asked."},
         {"role": "user", "content": ask}],
        AMEND_SCHEMA, required=("intent", "changed"), max_tokens=2500)

    seconds = brief.seconds
    if isinstance(obj.get("seconds"), (int, float)) and 1 <= float(obj["seconds"]) <= 15:
        seconds = float(obj["seconds"])
    shots = brief.shots
    if isinstance(obj.get("shots"), int) and 1 <= obj["shots"] <= 4:
        shots = obj["shots"]
    constraints = [str(c) for c in (obj.get("constraints") or brief.constraints)]

    amended = replace(brief, intent=str(obj.get("intent") or brief.intent),
                      seconds=seconds, shots=shots, constraints=constraints)
    return amended, [str(c) for c in (obj.get("changed") or [])]


def refine(brief: Brief, change: str, *, backend: Backend | None = None,
           opts: ProfileOptions | None = None, seed: int | None = None,
           **kw) -> tuple[IRDocument, Brief, list[str]]:
    """Plain-language refinement. Maps onto the cache keys: a prose-only change re-renders,
    a duration change replans, and the AssetCards are untouched either way."""
    cfg = get_config()
    own = backend is None
    backend = backend or Backend(cfg)
    try:
        amended, changed = amend_brief(brief, change, backend)
        doc = compile_brief(amended, backend=backend, opts=opts, seed=seed, **kw)
        doc.provenance["refined_from"] = brief.hash()
        doc.provenance["refinement"] = change
        doc.provenance["changed_fields"] = changed
        return doc, amended, changed
    finally:
        if own:
            backend.close()
