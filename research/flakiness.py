#!/usr/bin/env python
"""How reproducible is a compile, and is the flake spread evenly or concentrated in one mode?

`i2va_animate` fell back twice inside suite runs and then came through `written` when run alone, at
the same fixed seed. That is either endpoint nondeterminism under concurrent load or something
specific to one mode, and the two want different responses: the first is an operational fact the
product has to be honest about, the second is a bug.

So this measures both, and separates them:

  * N repeats of the WHOLE suite — six briefs sharing one backend, which is the batched condition
    where the flake was seen.
  * N repeats of one brief ALONE — the unbatched condition where it passed.

Every compile uses the same fixed seed, so any variation is nondeterminism rather than sampling.
The outcome is tabulated per brief AND per mode, because "one mode in six is flaky" and "every mode
is a bit flaky" have different fixes and only the second is a retry policy.
"""
from __future__ import annotations

import collections
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from h3ir.backend import Backend
from h3ir.compile import compile_brief
from h3ir.config import get_config
from h3ir.evalloop.suite import suite_briefs
from h3ir.plan import ProfileOptions

SEED = 7


def _outcome(doc) -> str:
    if doc.fell_back:
        return "fell_back"
    return "repaired" if (doc.provenance.get("fix_rounds") or 0) else "clean"


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repeats", type=int, default=5)
    ap.add_argument("--solo", default="i2va_animate",
                    help="the brief to also run unbatched, for the load comparison")
    args = ap.parse_args()

    briefs = suite_briefs()
    opts = ProfileOptions(name="h3ir/2026-08-a")
    # brief -> [outcome per repeat]
    batched: dict[str, list[str]] = collections.defaultdict(list)
    solo: list[str] = []
    modes: dict[str, str] = {}
    t0 = time.time()

    with Backend(get_config()) as backend:
        backend.require_available()
        for r in range(args.repeats):
            print(f"-- suite repeat {r + 1}/{args.repeats}")
            for name, brief in briefs.items():
                try:
                    doc = compile_brief(brief, backend=backend, opts=opts, seed=SEED)
                    batched[name].append(_outcome(doc))
                    modes[name] = doc.mode.value
                except Exception as e:                                    # noqa: BLE001
                    batched[name].append(f"raised:{type(e).__name__}")
                print(f"   {name:24} {batched[name][-1]}")

        if args.solo in briefs:
            print(f"-- {args.solo} alone, {args.repeats}x")
            for r in range(args.repeats):
                try:
                    doc = compile_brief(briefs[args.solo], backend=backend, opts=opts, seed=SEED)
                    solo.append(_outcome(doc))
                except Exception as e:                                    # noqa: BLE001
                    solo.append(f"raised:{type(e).__name__}")
                print(f"   {r + 1}: {solo[-1]}")

    print(f"\n-- per brief, {args.repeats} repeats each, batched ({time.time() - t0:.0f}s) --")
    for name, outs in batched.items():
        c = collections.Counter(outs)
        stable = "STABLE" if len(c) == 1 else "FLAKY"
        print(f"  {name:24} {modes.get(name, '?'):7} {stable:7} "
              + "  ".join(f"{k}={v}" for k, v in c.most_common()))

    print("\n-- by mode --")
    by_mode: dict[str, list[str]] = collections.defaultdict(list)
    for name, outs in batched.items():
        by_mode[modes.get(name, "?")].extend(outs)
    for mode, outs in sorted(by_mode.items()):
        c = collections.Counter(outs)
        n = len(outs)
        fb = c.get("fell_back", 0)
        print(f"  {mode:7} n={n:3}  fell_back={fb:3} ({fb / n:.0%})  "
              + "  ".join(f"{k}={v}" for k, v in c.most_common()))

    if solo:
        c = collections.Counter(solo)
        cb = collections.Counter(batched.get(args.solo, []))
        print(f"\n-- {args.solo}: batched vs alone --")
        print(f"  batched  " + "  ".join(f"{k}={v}" for k, v in cb.most_common()))
        print(f"  alone    " + "  ".join(f"{k}={v}" for k, v in c.most_common()))
        print("\n  Same brief, same seed. A difference between these two rows is load-dependent")
        print("  nondeterminism; the same spread in both is nondeterminism regardless of load.")

    flaky = [n for n, outs in batched.items() if len(set(outs)) > 1]
    print(f"\n  {len(flaky)}/{len(batched)} briefs varied across identical runs: {flaky or 'none'}")
    print("  A single eval run is therefore indicative, not a measurement — anything that decides")
    print("  something needs repeats. And a user can get a fallback on one day and a clean write on")
    print("  the next from identical input, which the product has to say rather than present a")
    print("  fallback as a property of their request.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
