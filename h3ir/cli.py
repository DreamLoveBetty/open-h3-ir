"""h3ir command line.

  h3ir doctor                     what the endpoints are and whether they answer
  h3ir controls                   static control gate (no model, under a second)
  h3ir compile "brief" [opts]     compile one brief, print the IR and its findings
  h3ir eval [--label X]           run the suite, score it, gate against the baseline
  h3ir baseline                   record the last run as the baseline
  h3ir loras                      what the registry sees
  h3ir budget                     packed-sequence cost for a duration/canvas
  h3ir serve                      run the HTTP service
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config import get_config
from .models import AssetKind, AssetRef, Brief, DialogueLine, Role


def _print_findings(doc) -> None:
    from .validate import Report
    print(Report(f"{doc.mode.value} IR", doc.findings).text(show_info=True))


def cmd_doctor(args) -> int:
    from .backend import probe
    from .comfy import probe as comfy_probe
    cfg = get_config()
    print("profile:", cfg.profile)
    print("state dir:", cfg.paths.state_dir)
    print("lora dirs:", [str(p) for p in cfg.paths.lora_dirs])
    print("\n-- reasoning model --")
    for k, v in probe(cfg).items():
        print(f"  {k}: {v}")
    print("\n-- comfyui --")
    for k, v in comfy_probe(cfg).items():
        print(f"  {k}: {v}")
    print("\n-- tokenizer --")
    from .tokens import count, label_cost
    print("  label cost:", label_cost())
    print("  self-test:", count("<d>[English] hello</d>"), "tokens for a short dialogue block")
    return 0


def cmd_controls(args) -> int:
    from .evalloop.controls import print_controls, run_controls
    ok, res = run_controls()
    print_controls(res)
    n = sum(1 for r in res if not r.passed)
    print(f"\n{len(res)} controls, {n} failing")
    return 0 if ok else 1


def cmd_compile(args) -> int:
    from .compile import compile_brief
    from .plan import ProfileOptions
    from .analyse import sha256_file

    assets = []
    for spec in args.image or []:
        path, _, note = spec.partition(":")
        p = Path(path)
        if not p.exists():
            print(f"no such image: {p}", file=sys.stderr)
            return 2
        role = Role.FRAME_ANCHOR_FIRST if args.anchor else Role.SUBJECT
        assets.append(AssetRef(kind=AssetKind.IMAGE, role=role, sha256=sha256_file(p),
                               path=str(p), note=note or None,
                               sizing="max" if args.max_refs else "match"))
    dialogue = [DialogueLine(text=t) for t in (args.say or [])]
    brief = Brief(intent=args.intent, assets=assets, seconds=args.seconds, aspect=args.aspect,
                  dialogue=dialogue, shots=args.shots, silent=args.silent,
                  creativity=args.creativity, director=args.director,
                  loras=[{"id": x} for x in (args.lora or [])])

    doc = compile_brief(brief, seed=args.seed,
                        opts=ProfileOptions(name=get_config().profile,
                                            camera_style=args.camera_style),
                        thinking_prose=args.thinking,
                        beatsheet_prompt=args.beatsheet, prose_prompt=args.prose)
    print(f"\nmode={doc.mode.value}  tokens={doc.prompt_tokens}  "
          f"timings={doc.provenance['timings']}")
    _print_findings(doc)
    if args.json:
        print(json.dumps({"presentation": doc.presentation(),
                          "prompt": doc.prompt,
                          "mode_decision": doc.plan.mode_decision.__dict__
                          if doc.plan.mode_decision else None}, default=str, indent=1))
    else:
        print("\n" + doc.prompt)
    if args.out:
        Path(args.out).write_text(doc.prompt, encoding="utf-8")
        print(f"[written to {args.out}]")
    return 0 if doc.ok else 1


def cmd_eval(args) -> int:
    from .evalloop.controls import print_controls, run_controls
    from .evalloop.suite import RunConfig, gate, run_suite, set_baseline, stored_baseline

    ok, res = run_controls()
    print("-- static controls --")
    print_controls(res)
    if not ok:
        print("\ncontrols failed; not running the suite")
        return 1

    cfg = RunConfig(label=args.label, beatsheet_prompt=args.beatsheet, prose_prompt=args.prose,
                    compose_prompt=args.compose, creativity=args.creativity,
                    omit=tuple(args.omit or ()), note=args.note,
                    camera_style=args.camera_style, thinking_prose=args.thinking, seed=args.seed,
                    only=tuple(args.only or ()))
    print(f"\n-- suite ({cfg.label}) --")
    run = run_suite(cfg)
    print(f"\nmeans over {run.agg.n} brief(s), {run.wall_s}s wall:")
    for k, v in run.agg.dict().items():
        if k not in ("failures", "n"):
            print(f"  {k:16} {v}")

    base = stored_baseline()
    print("\n-- gate --")
    shipable, lines = gate(run, base)
    for line in lines:
        print(line)
    print(f"\n{'SHIP-ABLE' if shipable else 'BLOCKED'}")
    if args.set_baseline and shipable:
        set_baseline(run)
        print("recorded as the new baseline")
    return 0 if shipable else 1


def cmd_baseline(args) -> int:
    from .evalloop.suite import Run, RunConfig, load_runs, set_baseline
    from .evalloop.score import Aggregate, Score
    runs = load_runs(args.label)
    if not runs:
        print(f"no stored runs with label {args.label!r}", file=sys.stderr)
        return 2
    d = runs[-1]
    run = Run(config=RunConfig(**d["config"]), agg=Aggregate(**d["agg"]),
              scores=[Score(**s) for s in d["scores"]], started=d["started"],
              wall_s=d["wall_s"], model=d.get("model", ""), commit=d.get("commit", ""),
              errors=d.get("errors", []))
    set_baseline(run)
    print(f"baseline set from run of {run.config.label} ({run.agg.n} briefs)")
    return 0


def cmd_loras(args) -> int:
    from .lora import load_registry
    records, findings, revision = load_registry()
    print(f"registry revision {revision}, {len(records)} lora(s)")
    for r in records.values():
        print(f"\n  {r.id}  ({r.name})")
        print(f"    kind={r.kind} target={r.target} variants={list(r.h3_variant)}")
        print(f"    triggers={[t['text'] for t in r.triggers]} strength={r.strength}")
        if r.what_for():
            print(f"    for: {r.what_for()[:160]}")
    for f in findings:
        print(f"  {f}")
    return 0 if not [f for f in findings if f.severity == "ERROR"] else 1


def cmd_budget(args) -> int:
    from .grid import Target, rows_per_latent_frame
    t = Target.build(args.seconds, args.aspect)
    print(f"requested {args.seconds}s -> {t.frames} frames = {t.effective_seconds:.3f}s "
          f"(nominal S.SS {t.s_ss()})")
    print(f"canvas {t.canvas[0]}x{t.canvas[1]}, latent_t {t.latent_t}")
    print(f"video rows {t.video_rows:,}  audio rows {t.audio_rows:,}")
    per_ref = rows_per_latent_frame(*t.canvas)
    print(f"ref image at 'match' ~{per_ref:,} rows; at 'max' (2048 short edge) ~7,296 rows")
    print(f"an 800-token IR is {800 / (t.video_rows + t.audio_rows + 800) * 100:.2f}% of the pack")
    return 0


def cmd_acceptance(args) -> int:
    from .acceptance import build
    out = Path(args.out)
    rep = build(out, Path(args.image_a), Path(args.image_b), seconds=args.seconds,
                aspect=args.aspect, seed=args.seed)
    print(f"wrote {len(rep['arms'])} arms to {out}")
    for name, arm in rep["arms"].items():
        n = len(arm["validator"]["errors"])
        print(f"  {name:28} {n} validator error(s)"
              + (f"  <- {arm['validator']['errors'][0][:70]}" if n else ""))
    print(f"\nread {out / 'README.md'} for what each outcome would mean")
    print("nothing was submitted to ComfyUI; sequencing the render is the graph owner's call")
    return 0


def cmd_directors(args) -> int:
    """The seven, and the whole text of one when it is named.

    The prose is printed rather than summarised, because a profile is a paragraph to read and edit,
    not a switch to flip. `h3ir directors wong > mine.txt` is how somebody starts their own.
    """
    from . import director as D
    named = (getattr(args, "which", "") or "").strip().lower()
    if named:
        d = D.BY_ID.get(named)
        if d is None:
            print(f"no director called {named!r}. The list is `h3ir directors`.")
            return 2
        print(d.notes)
        return 0
    print("whose taste fills what your prompt and your references leave open\n")
    for d in D.DIRECTORS:
        first = d.notes.split(".")[0]
        print(f"  {d.id:<12} {d.name:<20} {first[:44]}...")
    print("\n`h3ir directors <id>` prints the whole thing, which is what a profile is: prose.")
    print("shot count and cut times are never a director's; anything your prompt states "
          "explicitly outranks one.")
    return 0


def cmd_serve(args) -> int:
    import uvicorn
    uvicorn.run("h3ir.service:app", host=args.host, port=args.port, log_level="info")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="h3ir", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("doctor").set_defaults(func=cmd_doctor)
    sub.add_parser("controls").set_defaults(func=cmd_controls)

    c = sub.add_parser("compile")
    c.add_argument("intent")
    c.add_argument("--seconds", type=float, default=5.0)
    c.add_argument("--aspect", default="16:9")
    c.add_argument("--image", action="append", metavar="PATH[:note]")
    c.add_argument("--anchor", action="store_true", help="treat images as frame anchors")
    c.add_argument("--max-refs", action="store_true", help="2048 short edge reference sizing")
    c.add_argument("--say", action="append", metavar="LINE")
    c.add_argument("--shots", type=int)
    c.add_argument("--silent", action="store_true")
    c.add_argument("--creativity", choices=["restrained", "balanced", "bold", "extreme"], default="balanced",
                   help="how much the writer may add beyond the request (default: balanced)")
    c.add_argument("--director", default="",
                   help="whose taste fills what the request and the references leave open "
                        "(`h3ir directors` for the list; default: nobody's)")
    c.add_argument("--lora", action="append")
    c.add_argument("--seed", type=int, default=7)
    c.add_argument("--camera-style", default="canonical", choices=["canonical", "prose"])
    c.add_argument("--beatsheet", default="beatsheet.v1.txt")
    c.add_argument("--prose", default="prose_shot.v2.txt")
    c.add_argument("--thinking", action="store_true", help="reasoning on for prose (slower)")
    c.add_argument("--json", action="store_true")
    c.add_argument("--out")
    c.set_defaults(func=cmd_compile)

    e = sub.add_parser("eval")
    e.add_argument("--label", default="baseline")
    e.add_argument("--beatsheet", default="beatsheet.v1.txt")
    e.add_argument("--prose", default="prose_shot.v2.txt")
    e.add_argument("--compose", default=None,
                   help="force one composer for every mode (an A/B lever). Default None picks by "
                        "mode, which is what production does.")
    e.add_argument("--creativity", choices=["restrained", "balanced", "bold", "extreme"], default=None,
                   help="force every brief to one position, to measure the dial")
    e.add_argument("--director", default=None,
                   help="force every brief to one director, to measure one arm across the suite")
    e.add_argument("--camera-style", default="canonical", choices=["canonical", "prose"])
    e.add_argument("--thinking", action="store_true")
    e.add_argument("--seed", type=int, default=7)
    e.add_argument("--only", action="append")
    e.add_argument("--set-baseline", action="store_true")
    e.add_argument("--note", default="", help="recorded with the run; say what a baseline supersedes")
    e.add_argument("--omit", action="append",
                   choices=["facts", "style", "licence", "scope", "director"],
                   help="drop a block from the composing ask (ablation; repeatable)")
    e.set_defaults(func=cmd_eval)

    b = sub.add_parser("baseline")
    b.add_argument("--label", default="baseline")
    b.set_defaults(func=cmd_baseline)

    sub.add_parser("loras").set_defaults(func=cmd_loras)
    d = sub.add_parser("directors")
    d.add_argument("which", nargs="?", default="",
                   help="one id, to print the whole profile instead of the list")
    d.set_defaults(func=cmd_directors)

    bu = sub.add_parser("budget")
    bu.add_argument("--seconds", type=float, default=5.0)
    bu.add_argument("--aspect", default="16:9")
    bu.set_defaults(func=cmd_budget)

    ac = sub.add_parser("acceptance")
    ac.add_argument("--image-a", required=True, help="the man")
    ac.add_argument("--image-b", required=True, help="the dragon")
    ac.add_argument("--out", default="acceptance")
    ac.add_argument("--seconds", type=float, default=5.0)
    ac.add_argument("--aspect", default="16:9")
    ac.add_argument("--seed", type=int, default=7)
    ac.set_defaults(func=cmd_acceptance)

    s = sub.add_parser("serve")
    s.add_argument("--host", default="0.0.0.0")
    s.add_argument("--port", type=int, default=8420)
    s.set_defaults(func=cmd_serve)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
