#!/usr/bin/env python
"""Does the creativity dial scale with the ask, or is it just loud?

Two settings on one request cannot answer that. A dial that adds music and 130 words to
*everything* looks identical, at one request, to a dial that reads the ask correctly.

So: two requests x two settings, and what matters is the INTERACTION.

    plain request      restrained vs bold  ->  spread should be SMALL
    ambitious request  restrained vs bold  ->  spread should be LARGE

Small spread on the plain request is the feature, not a failure. A one-sentence walking shot with no
beats named and nothing forbidden *should* come back restrained even at a high setting; two easy
shots is a proportionate answer. If the two settings diverge wildly there, that is the
over-directing failure wearing the dial's clothes.

The two requests share their subject and their setting on purpose. The only thing that differs is
how much the ask invites, so the interaction cannot be an artifact of one prompt being about a
dragon and the other about a corridor.
"""
from __future__ import annotations

import re
import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from h3ir.backend import Backend
from h3ir.compile import compile_brief
from h3ir.config import get_config
from h3ir.creativity import ONSCREEN_TEXT, SCORE, SPEECH
from h3ir.analyse import sha256_file
from h3ir.models import AssetKind, AssetRef, Brief, Role
from h3ir.plan import ProfileOptions
from h3ir.tokens import word_count

# One sentence. A subject, a setting, a light source, a look. No beats named, nothing forbidden,
# nothing that invites escalation. This is the owner's own plain request.
PLAIN = ("the man walks forward down the stone corridor toward the camera, torchlight flickering "
         "across the walls. Cinematic.")

# Same man, same corridor. What changes is that the ask now contains events, a turn, and an explicit
# invitation to go big -- so a bold reading has something to be bold WITH.
AMBITIOUS = ("the man is hunted down the stone corridor — he hears something behind him, breaks "
             "into a run as the torchlight gutters, and turns at the last moment to face whatever "
             "reached the corridor's mouth. Go big with it: dramatic, cinematic, build the dread.")

SECONDS = 8.0
SEED = 7

# All four, once `extreme` existed. The three-position version left `balanced` out to save compiles,
# but the owner judges these by looking and a gap in the middle of a dial he is being shown is a gap
# in the thing being judged.
LEVELS = ("restrained", "balanced", "bold", "extreme")

# The reference plates, for the reference-mode run. The text-only run stays available and is what
# the ablation baselined against, but use a character you know by sight: identity is hardest to
# hold exactly where `extreme` pushes, in a frame filled by a face, and you can only judge that
# on a face you can recognise.
# Point these at your own reference plates. A character turnaround sheet and an empty
# location plate is the pair these scripts were written against.
IMAGE_DIR = Path(os.environ.get("H3IR_REF_IMAGE_DIR", "."))
CHARACTER = IMAGE_DIR / os.environ.get("H3IR_REF_CHARACTER",
                                       "character_turnaround.png")
CORRIDOR = IMAGE_DIR / os.environ.get("H3IR_REF_SCENE", "bare_corridor.png")

# Framing terms in rough order of how hard they are played, from the spec's vocabulary.
FRAMING_RE = re.compile(r"extreme close[- ]?up|extreme close|close[- ]?up|close framing|"
                        r"medium[- ]wide|medium shot|medium framing|wide shot|wide view|"
                        r"extreme wide", re.I)


def _assets() -> list[AssetRef]:
    """Order is load-bearing: it becomes <Picture 1> then <Picture 2>."""
    return [
        AssetRef(kind=AssetKind.IMAGE, role=Role.SUBJECT, sha256=sha256_file(CHARACTER),
                 path=str(CHARACTER), note="the man (character turnaround sheet)", px=(1448, 1086)),
        AssetRef(kind=AssetKind.IMAGE, role=Role.ENVIRONMENT, sha256=sha256_file(CORRIDOR),
                 path=str(CORRIDOR), note="the stone corridor (environment reference)",
                 px=(403, 552)),
    ]


def _identity_proxies(doc, field: str) -> dict:
    """Decidable stand-ins for "did his character survive". The render is the owner's call -- these
    are the things the TEXT can be held to, and they are where identity is lost before a frame exists:
    a subject label absent from a shot, a retention marker that does not claim preservation, wardrobe
    stated once and never again."""
    import re as _re
    desc = doc.sections.get(field, "")
    shots = _re.findall(r"\[Shot\s+\d+\]", desc)
    bodies = _re.split(r"\[Shot\s+\d+\]", desc)[1:]
    subj = [b for b in bodies if _re.search(r"<Subject\s+1>", b)]
    ret = doc.sections.get("retention_analysis", "")
    return {
        "binds_subject_in": f"{len(subj)}/{len(shots)}" if shots else "0/0",
        "marker": (_re.search(r"<Subject 1>[^:]*:\s*(\w+)", ret).group(1)
                   if _re.search(r"<Subject 1>[^:]*:\s*(\w+)", ret) else "none"),
        "wardrobe_warn": any(f.rule.startswith("R15") for f in doc.findings),
    }


def _measure(name: str, intent: str, level: str, backend: Backend, opts,
             refs: bool = False) -> dict:
    doc = compile_brief(Brief(intent=intent, seconds=SECONDS, aspect="16:9", creativity=level,
                              assets=_assets() if refs else []),
                        backend=backend, opts=opts, seed=SEED)
    field = ("detailed_description" if "detailed_description" in doc.sections
             else "integrated_multimodal_description")
    music = doc.sections.get("non_diegetic_music", "").strip()
    used = [e for e, present in (
        (SPEECH, "<d>" in doc.prompt),
        (SCORE, music not in ("", "N/A")),
        (ONSCREEN_TEXT, '"' in doc.sections.get(field, "").replace("<d>", "")),
    ) if present]
    desc = doc.sections.get(field, "")
    return {
        "name": name, "level": level, "words": word_count(desc),
        # From the SHIPPED text. `len(doc.plan.shots)` is the deterministic draft's count in the
        # write-first path, and reading it here reported 2 shots on every cell of the grid while four
        # of the six briefs contain one. Third instance of the same mistake in one evening: a metric
        # reading an object the pipeline discards, then a confident conclusion drawn from it.
        "shots": len(re.findall(r"\[Shot\s+\d+\]", desc)),
        "outcome": doc.provenance.get("source"),
        "fix_rounds": doc.provenance.get("fix_rounds") or 0,
        "errors": len(doc.errors), "used": used, "music": music,
        "scope": doc.provenance.get("creativity"), "prompt": doc.prompt, "request": intent,
        # The magnitude axis, countable: does the brief actually reach the far end of the spec's
        # camera vocabulary? At `extreme` this is checked (Q3); everywhere else it is an observation.
        "maximal_camera": any(v in desc.lower()
                              for v in ("with large amplitude", "at fast speed")),
        "mode": doc.mode.value,
        **(_identity_proxies(doc, field) if refs else {}),
        # EVERY framing used, and how many maximal-camera phrases appear -- not the first of each.
        # Reporting the first hid the signal completely: plain/extreme showed "medium shot" while the
        # brief also contains an extreme close-up, and a three-shot brief has three framings. Fourth
        # measurement tonight that reported a real value about the wrong slice of the artifact.
        "framings": sorted({m.group(0).lower() for m in FRAMING_RE.finditer(desc)}) or ["unstated"],
        "maximal_n": len(re.findall(r"with large amplitude|at fast speed", desc, re.I)),
        "timid_n": len(re.findall(r"with small amplitude|at slow speed", desc, re.I)),
    }


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=None)
    ap.add_argument("--refs", action="store_true",
                    help="bind the character sheet as a subject and the corridor as environment, so "
                         "the briefs come out six-section and actually reference the assets")
    args = ap.parse_args()
    default_dir = "proportionality-refs" if args.refs else "proportionality"
    args.out = args.out or str(Path.home() / "h3ir" / "acceptance" / default_dir)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    opts = ProfileOptions(name="h3ir/2026-08-a")
    rows: list[dict] = []
    with Backend(get_config()) as backend:
        backend.require_available()
        for label, intent in (("plain", PLAIN), ("ambitious", AMBITIOUS)):
            for level in LEVELS:
                r = _measure(label, intent, level, backend, opts, refs=args.refs)
                rows.append(r)
                (out / f"{label}_{level}.txt").write_text(r["prompt"], encoding="utf-8")
                extra = (f" binds={r['binds_subject_in']} marker={r['marker']}"
                         if args.refs else "")
                print(f"  {label:10} {level:10} {r['mode']:6} {r['outcome']:9} "
                      f"fix={r['fix_rounds']} words={r['words']:4} shots={r['shots']} "
                      f"E{r['errors']}{extra} used={r['used'] or 'nothing'}")

    print("\n-- the interaction --")
    spread = {}
    for label in ("plain", "ambitious"):
        cells = [r for r in rows if r["name"] == label]
        words = [c["words"] for c in cells]
        spread[label] = max(words) - min(words)
        print(f"  {label}")
        for c in cells:
            print(f"    {c['level']:11} {c['words']:4}w  {c['shots']} shot(s)  "
                  f"maximal={c['maximal_n']} timid={c['timid_n']}  "
                  f"framings={'/'.join(c['framings'])}  "
                  f"added={', '.join(c['used']) or 'nothing'}")

    # No automatic verdict. Word-count SPREAD was the first instrument here and it is the wrong one:
    # the plain/extreme brief came back SHORTER than plain/bold while being unmistakably harder --
    # an extreme close-up, large amplitude at fast speed, hard-edged shadows, a drone cut to silence.
    # Words measure verbosity. Declaring the dial "loud" off that number would have been a fourth
    # confident conclusion drawn from a metric pointed at the wrong thing.
    print("\n-- what to read --")
    print("  Magnitude shows in `framing` and `maximal-camera`, which are spec vocabulary and")
    print("  countable. Words are reported as context, never as the magnitude instrument.")
    print(f"  word spread: plain {spread['plain']}w, ambitious {spread['ambitious']}w — context only.")
    print("  Proportional would mean the DIAL does more where the request supplied less: on an")
    print("  ambitious ask the request already carries the energy, so the positions should sit")
    print("  closer together than they do on a plain one. The owner judges the briefs themselves.")

    # The ask ships beside the result, per arm.
    ref_cols = "| binds Subject 1 | retention marker " if args.refs else "| "
    lines = ["# Proportionality: does the dial scale with the ask?\n",
             f"Seed {SEED}, {SECONDS}s, same subject and setting in both requests.\n",
             f"## The plain request\n\n> {PLAIN}\n",
             f"## The ambitious request\n\n> {AMBITIOUS}\n",
             "## Results\n",
             f"| request | setting | framings used | maximal / timid camera | shots | words {ref_cols}| errors |",
             "|---|---|---|---|---|---|" + ("---|---|" if args.refs else "") + "---|"]
    for r in rows:
        extra = (f"| {r['binds_subject_in']} | {r['marker']} " if args.refs else "| ")
        lines.append(f"| {r['name']} | **{r['level']}** | {', '.join(r['framings'])} | "
                     f"**{r['maximal_n']}** / {r['timid_n']} | {r['shots']} | {r['words']} "
                     f"{extra}| {r['errors']} |")
    lines.append("\nMagnitude shows in **framing** and **maximal camera** — both spec vocabulary, "
                 "both countable. Words are context, not the instrument: the plain/extreme brief "
                 f"came back shorter than plain/bold while being plainly harder. Word spread was "
                 f"plain {spread['plain']}w, ambitious {spread['ambitious']}w.\n\n"
                 "The briefs are below with the ask above each one. **The owner judges these.**\n")
    for r in rows:
        lines.append(f"\n## {r['name']} / {r['level']}\n\nscope: `{r['scope']}`\n\n"
                     f"```text\n{r['prompt']}```\n")
    (out / "README.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"\n  wrote {out}/README.md and four briefs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
