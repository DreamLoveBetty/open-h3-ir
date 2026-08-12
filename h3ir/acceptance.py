"""Builds the acceptance comparison: one-liner vs compiled IR, ready to render.

Produces the prompts and the wiring, and never touches the GPU. Rendering is sequenced by
whoever owns the graph; this module only prepares an A/B where exactly one field differs.

Five arms, because two would not be conclusive:

  0  the deterministic draft — no prose model at all. The free baseline: if the compiled brief
     cannot beat its own no-LLM draft, the prose pass is not earning its place.
  A  a hand-written prompt verbatim, as a person actually typed it, with <Image 1> / <Image 2>
  B  the same prose, labels corrected to <Picture 1> / <Picture 2>
  C  the compiled Ref2VA IR from the same brief and the same references
  D  arm B with the two references SWAPPED IN THE WIRING ONLY, prompt text untouched

D is the control that makes the rest mean something. If the output follows the labels -- the
armour on the dragon, or the wrong subject riding -- then labels genuinely bind and the broken
pointer in arm A is a real defect. If the output ignores the swap and still renders
man-rides-dragon, then position binds, the labels are decorative, and the case for the fix
rests on C vs B alone. Either result is worth knowing before building further on it.
"""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .analyse import sha256_file
from .backend import Backend
from .compile import compile_brief
from .config import get_config
from .models import AssetKind, AssetRef, Brief, Role
from .plan import ProfileOptions
from .validate import Context, Report, validate

# A real hand-written prompt, verbatim, including the label namespace that does not exist. This is
# what the compiler is being compared against, so it is quoted rather than tidied.
HANDWRITTEN_PROMPT = (" The man from the <Image 1>, dressed in medieval armor rides the dragon of the "
                "<Image 2> into an epic battleground. Cinematic hollywood scene, dramatic "
                "expressions and camera movements. ")

HANDWRITTEN_INTENT = ("the man in medieval armour rides the dragon into an epic battleground, "
                "cinematic hollywood scene, dramatic expressions and camera movements")


def build(out_dir: Path, image_a: Path, image_b: Path, *, seconds: float = 5.0,
          aspect: str = "16:9", seed: int = 7) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    cfg = get_config()

    arm_b_prompt = HANDWRITTEN_PROMPT.replace("<Image 1>", "<Picture 1>").replace("<Image 2>",
                                                                            "<Picture 2>")
    brief = Brief(
        intent=HANDWRITTEN_INTENT, seconds=seconds, aspect=aspect,
        assets=[AssetRef(kind=AssetKind.IMAGE, role=Role.SUBJECT, sha256=sha256_file(image_a),
                         path=str(image_a), note="the man in medieval armour"),
                AssetRef(kind=AssetKind.IMAGE, role=Role.SUBJECT, sha256=sha256_file(image_b),
                         path=str(image_b), note="the dragon")])

    with Backend(cfg) as backend:
        backend.require_available()
        opts = ProfileOptions(name=cfg.profile)
        draft_doc = compile_brief(brief, backend=backend, opts=opts, seed=seed, llm=False)
        doc = compile_brief(brief, backend=backend, opts=opts, seed=seed)

    wiring = [{"label": m.label, "wiring": m.wiring, "sha256": m.sha256,
               "path": str(image_a if m.label == "<Picture 1>" else image_b),
               "sizing": m.sizing} for m in doc.plan.manifest]
    swapped = [dict(w) for w in wiring]
    if len(swapped) == 2:
        swapped[0]["path"], swapped[1]["path"] = swapped[1]["path"], swapped[0]["path"]
        swapped[0]["sha256"], swapped[1]["sha256"] = swapped[1]["sha256"], swapped[0]["sha256"]

    ctx_kw = dict(mode="ref2va", n_pictures=2, duration_s=doc.plan.target.effective_seconds)
    arms = {
        "0_deterministic_draft": {
            "prompt": draft_doc.prompt,
            "wiring": wiring,
            "why": "no prose model at all — the product floor and the free A/B baseline",
            "findings": draft_doc.findings,
        },
        "A_handwritten_verbatim": {
            "prompt": HANDWRITTEN_PROMPT,
            "wiring": wiring,
            "why": "the prompt as it is used today; <Image N> is not a label the runtime emits",
            "findings": validate(HANDWRITTEN_PROMPT, Context(**ctx_kw)),
        },
        "B_labels_corrected": {
            "prompt": arm_b_prompt,
            "wiring": wiring,
            "why": "identical prose, labels corrected — isolates the label fix from everything else",
            "findings": validate(arm_b_prompt, Context(**ctx_kw)),
        },
        "C_compiled_ir": {
            "prompt": doc.prompt,
            "wiring": wiring,
            "why": "the compiled six-section IR: defined subjects, a retention contract, "
                   "timed beats and canonical camera",
            "findings": doc.findings,
        },
        "D_control_swapped_wiring": {
            "prompt": arm_b_prompt,
            "wiring": swapped,
            "why": "arm B with the two references swapped in the WIRING ONLY. Decides whether "
                   "the labels bind or the position does.",
            "findings": validate(arm_b_prompt, Context(**ctx_kw)),
        },
    }

    report = {
        "target": {"nominal_seconds": doc.plan.target.nominal_seconds,
                   "frames": doc.plan.target.frames,
                   "effective_seconds": round(doc.plan.target.effective_seconds, 3),
                   "canvas": list(doc.plan.target.canvas)},
        "seed": seed,
        "hold_constant": ["graph", "checkpoint", "seed", "sampler", "steps", "shifts",
                          "canvas", "frames", "reference sizing"],
        "vary": "the prompt text, and in arm D the wiring order",
        "mode_decision": asdict(doc.plan.mode_decision) if doc.plan.mode_decision else None,
        "compiled_tokens": doc.prompt_tokens,
        "draft_tokens": draft_doc.prompt_tokens,
        "compiled_source": doc.provenance.get("source"),
        "fallback_reason": doc.provenance.get("fallback_reason"),
        "arms": {},
    }
    for name, arm in arms.items():
        (out_dir / f"{name}.txt").write_text(arm["prompt"], encoding="utf-8")
        errs = [f for f in arm["findings"] if f.severity == "ERROR"]
        warns = [f for f in arm["findings"] if f.severity == "WARN"]
        report["arms"][name] = {
            "prompt_file": f"{name}.txt",
            "why": arm["why"],
            "wiring": arm["wiring"],
            "validator": {"errors": [f"{f.rule}: {f.msg}" for f in errs],
                          "warnings": [f"{f.rule}: {f.msg}" for f in warns]},
        }
    (out_dir / "acceptance.json").write_text(json.dumps(report, indent=1, ensure_ascii=False),
                                             encoding="utf-8")
    (out_dir / "README.md").write_text(_readme(report), encoding="utf-8")
    return report


def _readme(report: dict[str, Any]) -> str:
    t = report["target"]
    lines = [
        "# Acceptance comparison — one-liner vs compiled IR",
        "",
        f"Held constant: {', '.join(report['hold_constant'])}.  Varied: {report['vary']}.",
        "",
        f"Duration: {t['nominal_seconds']:g}s requested -> {t['frames']} frames = "
        f"{t['effective_seconds']}s real. Canvas {t['canvas'][0]}x{t['canvas'][1]}. "
        f"Seed {report['seed']}.",
        "",
        "## Arms",
        "",
    ]
    for name, arm in report["arms"].items():
        errs = arm["validator"]["errors"]
        lines += [f"### {name}", "", arm["why"], "",
                  f"- prompt: `{arm['prompt_file']}`",
                  f"- validator: {len(errs)} error(s)"
                  + (f" — {errs[0]}" if errs else ""),
                  "- wiring:"]
        for w in arm["wiring"]:
            lines.append(f"  - `{w['label']}` <- `{w['wiring']}` <- {Path(w['path']).name}")
        lines.append("")
    lines += [
        "## What each result would mean",
        "",
        "- **C beats 0:** the prose pass earns its cost. If it does not, the deterministic "
        "draft is the product and the model is optional — worth knowing either way.",
        "- **A and B differ, C best:** the broken label was costing real fidelity and the "
        "structure adds more on top. The expected outcome.",
        "- **A and B indistinguishable:** the label fix is cosmetic on two references. The case "
        "for the layer then rests on C vs B — the retention contract and the timed beats.",
        "- **D follows the labels** (wrong subject rides): labels bind, so a dangling label is a "
        "real defect and arm A was losing information.",
        "- **D ignores the swap** (still man-rides-dragon): position binds, labels are "
        "decorative at two references, and the compiler's value is structural rather than "
        "referential. Worth knowing before building further on the label argument.",
        "",
        "Judgement on look is a human's; this file only fixes what is compared.",
    ]
    return "\n".join(lines) + "\n"
