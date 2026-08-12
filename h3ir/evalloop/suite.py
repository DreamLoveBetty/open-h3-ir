"""The eval suite: a fixed set of briefs, compiled under a named configuration and scored.

This is the part that makes a prompt change a measurement instead of an opinion. A run records
the exact prompt files, profile, seed and model that produced it, so two runs are comparable
and a regression is attributable to one change.

Usage is always: run the static controls first (fast, no model), then the suite, then compare
against the stored baseline. Nothing ships on a regression.
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any

from ..analyse import sha256_file
from ..backend import Backend
from ..compile import compile_brief
from ..config import get_config
from ..models import AssetKind, Brief, DialogueLine, Role
from ..plan import ProfileOptions
from .score import Aggregate, Score, aggregate, compare, score_document


def _asset(name: str, role: Role, note: str, px: tuple[int, int]):
    from ..models import AssetRef
    p = get_config().paths.golden_dir / "assets" / name
    return AssetRef(kind=AssetKind.IMAGE, role=role, sha256=sha256_file(p) if p.exists() else name,
                    path=str(p), note=note, px=px)


def suite_briefs() -> dict[str, Brief]:
    """Chosen to exercise the things that actually broke, not to be broad for its own sake."""
    briefs: dict[str, Brief] = {
        # text-only, multi-shot, one line of dialogue
        "t2va_battle": Brief(
            intent="a knight in battered plate armour rides a huge black dragon low over a "
                   "burning battlefield, cinematic",
            seconds=10, aspect="16:9",
            dialogue=[DialogueLine(text="Hold the line!", speaker_hint="the knight")]),
        # short, silent: music must come back exactly N/A
        "t2va_silent": Brief(
            intent="rain runs down a bus window at night while the city slides past outside",
            seconds=5, aspect="9:16", silent=True),
        # speech capacity: two lines inside five seconds
        "t2va_dialogue_dense": Brief(
            intent="two mechanics argue over an engine in a cramped garage",
            seconds=5, aspect="16:9",
            dialogue=[DialogueLine(text="That belt is done.", speaker_hint="the older mechanic"),
                      DialogueLine(text="It held all week.", speaker_hint="the younger mechanic")]),
        # 15 s, the top of the trained range
        "t2va_long": Brief(
            intent="a lighthouse keeper climbs the tower stairs in a storm and lights the lamp",
            seconds=15, aspect="16:9"),
    }
    assets = get_config().paths.golden_dir / "assets"
    if (assets / "ref1.png").exists() and (assets / "ref2.png").exists():
        # The owner's real case: two subjects named from two different images.
        briefs["ref2va_two_subjects"] = Brief(
            intent="the man in medieval armour rides the dragon into an epic battleground, "
                   "cinematic hollywood scene with dramatic expressions and camera movements",
            seconds=5, aspect="16:9",
            assets=[_asset("ref1.png", Role.SUBJECT, "the man", (700, 500)),
                    _asset("ref2.png", Role.SUBJECT, "the dragon", (700, 700))])
        # anchor language on a single image -> should route to a base mode
        briefs["i2va_animate"] = Brief(
            intent="animate this photo: bring it to life with slow drifting motion",
            seconds=5, aspect="16:9",
            assets=[_asset("ref1.png", Role.SUBJECT, "the subject", (700, 500))])
    return briefs


@dataclass
class RunConfig:
    label: str = "baseline"
    beatsheet_prompt: str = "beatsheet.v1.txt"
    prose_prompt: str = "prose_shot.v2.txt"
    # None means "pick by mode", which is what production does. An explicit name here forced the
    # six-section full-reference composer onto every base-mode brief and so measured the exact bug
    # the mode split had just fixed -- the harness built to verify the fix reintroduced it. Only set
    # this to compare two composers deliberately.
    compose_prompt: str | None = None
    # Blocks to drop from the composing ask, for the ablation. Empty is production.
    omit: tuple[str, ...] = ()
    # Free text stored with the run. On a baseline, say which pipeline it supersedes. Lives on the
    # CONFIG rather than on Run because run_suite saves before the caller could set a Run field --
    # the first version of this landed as an empty string in the file it was written for.
    note: str = ""
    # When set, overrides every brief's own setting so one run measures one position. None means
    # each brief keeps whatever it declares, which is what a normal regression run wants.
    creativity: str | None = None
    profile: str = "h3ir/2026-08-a"
    camera_style: str = "canonical"
    thinking_prose: bool = False
    seed: int = 7
    only: tuple[str, ...] = ()

    def opts(self) -> ProfileOptions:
        return ProfileOptions(name=self.profile, camera_style=self.camera_style)


@dataclass
class Run:
    config: RunConfig
    scores: list[Score] = field(default_factory=list)
    agg: Aggregate = field(default_factory=Aggregate)
    started: float = 0.0
    wall_s: float = 0.0
    model: str = ""
    # A baseline is a reference point, so it has to say WHICH pipeline it is a reference for. The
    # stored baseline was taken under the old composed path and every comparison against it was
    # misleading -- a number that looks like a reference and is not is worse than no baseline.
    commit: str = ""
    errors: list[str] = field(default_factory=list)

    def dict(self) -> dict[str, Any]:
        # `commit` was on the dataclass but not in here, so the provenance it exists to record was
        # dropped on the way to disk and the baseline reported commit=None.
        return {"config": asdict(self.config), "agg": self.agg.dict(),
                "scores": [s.dict() for s in self.scores], "started": self.started,
                "wall_s": self.wall_s, "model": self.model, "commit": self.commit,
                "errors": self.errors}


def run_suite(cfg: RunConfig, *, save: bool = True, verbose: bool = True) -> Run:
    briefs = suite_briefs()
    if cfg.only:
        briefs = {k: v for k, v in briefs.items() if k in cfg.only}
    run = Run(config=cfg, started=time.time(), commit=_commit())
    t0 = time.time()
    with Backend(get_config()) as backend:
        run.model = backend.cfg.model
        backend.require_available()
        for name, brief in briefs.items():
            if cfg.creativity:
                brief = replace(brief, creativity=cfg.creativity)
            try:
                doc = compile_brief(brief, backend=backend, opts=cfg.opts(), seed=cfg.seed,
                                    thinking_prose=cfg.thinking_prose,
                                    beatsheet_prompt=cfg.beatsheet_prompt,
                                    compose_prompt=cfg.compose_prompt,
                                    omit=cfg.omit,
                                    prose_prompt=cfg.prose_prompt)
                s = score_document(doc, name)
                run.scores.append(s)
                if verbose:
                    # The outcome is printed FIRST because it is the question this suite now
                    # exists to answer: clean / repaired after N rounds / fell back.
                    print(f"  {name:24} {s.outcome:9} fix={s.fix_rounds} mode={s.mode:6} "
                          f"words={s.desc_words:4} (x{s.word_ratio:.2f}) shots={s.n_shots} "
                          f"cuts={s.n_timed_cuts} cam={s.camera_level} "
                          f"restate={s.restatement:.2f} dup={s.sound_overlap:.2f} "
                          f"E{s.errors}/W{s.warnings}")
                    for f in doc.errors:
                        print(f"      ERROR {f}")
            except Exception as e:  # noqa: BLE001 - a failed brief is data, not a crash
                run.errors.append(f"{name}: {type(e).__name__}: {e}")
                if verbose:
                    print(f"  {name:24} FAILED: {type(e).__name__}: {e}")
    run.wall_s = round(time.time() - t0, 1)
    run.agg = aggregate(run.scores)
    if save:
        save_run(run)
    return run


def _commit() -> str:
    """The code that produced the run. Recorded so a stored baseline can name its own pipeline."""
    import subprocess
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                             cwd=Path(__file__).resolve().parents[2],
                             capture_output=True, text=True, timeout=5)
        return out.stdout.strip() if out.returncode == 0 else ""
    except Exception:                                                     # noqa: BLE001
        return ""


def eval_dir() -> Path:
    d = get_config().paths.eval_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_run(run: Run) -> Path:
    p = eval_dir() / "runs.jsonl"
    with p.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(run.dict(), ensure_ascii=False) + "\n")
    return p


def load_runs(label: str | None = None) -> list[dict[str, Any]]:
    p = eval_dir() / "runs.jsonl"
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        if label is None or d["config"]["label"] == label:
            out.append(d)
    return out


def baseline_agg(label: str = "baseline") -> Aggregate | None:
    runs = load_runs(label)
    if not runs:
        return None
    return Aggregate(**runs[-1]["agg"])


def set_baseline(run: Run) -> None:
    (eval_dir() / "baseline.json").write_text(json.dumps(run.dict(), indent=1, ensure_ascii=False))


def stored_baseline() -> Aggregate | None:
    p = eval_dir() / "baseline.json"
    if not p.exists():
        return None
    return Aggregate(**json.loads(p.read_text())["agg"])


def stored_baseline_metrics() -> set[str] | None:
    """Which metrics the stored baseline actually measured, as opposed to defaulted."""
    p = eval_dir() / "baseline.json"
    if not p.exists():
        return None
    return set((json.loads(p.read_text()).get("agg") or {}).keys())


def gate(run: Run, baseline: Aggregate | None) -> tuple[bool, list[str]]:
    """True means ship-able. Any compile failure or validator error blocks regardless of trend."""
    lines: list[str] = []
    ok = True
    if run.errors:
        ok = False
        lines.append(f"  {len(run.errors)} brief(s) failed to compile: {run.errors}")
    if run.agg.failures:
        ok = False
        lines.append(f"  validator errors in: {run.agg.failures}")
    if baseline is None:
        lines.append("  no baseline stored, so there is no trend to check yet — "
                     "run again with --set-baseline to record this one")
        return ok, lines
    regressed, cmp_lines = compare(baseline, run.agg, stored_baseline_metrics())
    lines += cmp_lines
    if regressed:
        ok = False
        lines.append("  REGRESSION against baseline — not ship-able")
    return ok, lines
