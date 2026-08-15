"""A number in `shots` is a contract; `auto` stays the writer's freedom.

The design decision, recorded in prose.py's writer docstring, is that shot count belongs to the
model's craft. The `shots` field then arrived and got half-wired: the plan stage was told to honour
it, the writer kept its original freedom, and the writer goes last — so `shots: 3` shipped one shot,
silently (measured: row 1 v1, brief 3820af491ae34f93; the socket-era matrix counted 6 of 28 runs
diverging). The owner settled it: `auto` keeps the freedom, a number binds every stage, up to 10.

The chain proven here: intake refuses an impossible or out-of-range pin with the arithmetic; the
deterministic draft delivers the pinned count instead of clamping it to the profile ceiling; the
plan schema is pinned so guided decoding cannot return a different count; the validator makes a
wrong count an ERROR (which the fix loop sends back to the writer, and an unfixed ERROR ships the
draft — which carries the pinned count by construction); and the fix ask stops telling the writer
to keep its shots when the shot count itself is the finding.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from h3ir.compile import BriefRefused, check_request
from h3ir.models import Brief, Mode
from h3ir.plan import ProfileOptions, shot_count, build_manifest
from h3ir.prose import fix_with_findings
from h3ir.shots import MIN_SHOT_MS, PINNED_SHOTS_MAX, shot_schema
from h3ir.grid import Target
from h3ir.models import Finding
from h3ir.validate import Context, validate


def _brief(**kw) -> Brief:
    base = dict(intent="a fishmonger slams a crate of ice onto the stall", seconds=15.0)
    base.update(kw)
    return Brief(**base)


# --------------------------------------------------------------------------- intake

def test_a_pin_beyond_ten_is_refused_naming_the_ceiling():
    with pytest.raises(BriefRefused) as e:
        check_request(_brief(shots=11))
    assert "10" in str(e.value)


def test_a_pin_below_one_is_refused():
    with pytest.raises(BriefRefused):
        check_request(_brief(shots=0))


def test_a_pin_that_cannot_fit_is_refused_with_the_arithmetic():
    """10 shots need 12s of floor at 1.2s a shot; an 8s render cannot hold them, and the refusal
    says so in seconds rather than leaving the caller to guess."""
    with pytest.raises(BriefRefused) as e:
        check_request(_brief(shots=10, seconds=8.0))
    msg = str(e.value)
    assert "10" in msg and "1.2" in msg


def test_a_pin_that_fits_passes_intake():
    check_request(_brief(shots=6, seconds=8.0))   # 7.2s of floor inside 8.0s
    check_request(_brief(shots=10, seconds=15.0))


# --------------------------------------------------------------------------- the draft path

def test_a_pinned_count_is_delivered_not_clamped_to_the_profile_ceiling():
    """The old clamp `min(opts.max_shots, brief.shots)` silently turned 8 into 4."""
    brief = _brief(shots=8)
    target = Target.build(15)
    n = shot_count(target, brief, Mode.REF2VA, ProfileOptions(), build_manifest(brief, target))
    assert n == 8


def test_auto_keeps_the_heuristic_and_its_ceiling():
    brief = _brief()
    target = Target.build(15)
    n = shot_count(target, brief, Mode.REF2VA, ProfileOptions(), build_manifest(brief, target))
    assert 1 <= n <= ProfileOptions().max_shots


# --------------------------------------------------------------------------- the plan schema

def test_the_plan_schema_is_pinned_exactly():
    s = shot_schema(6, exact=6)["properties"]["shots"]
    assert s["minItems"] == 6 and s["maxItems"] == 6


def test_the_plan_schema_stays_free_when_nothing_is_pinned():
    s = shot_schema(4)["properties"]["shots"]
    assert s["minItems"] == 1 and s["maxItems"] == 4


def test_the_ceiling_is_ten():
    assert PINNED_SHOTS_MAX == 10
    assert MIN_SHOT_MS == 1200   # the feasibility arithmetic above rests on this


# --------------------------------------------------------------------------- the validator

SHOT2 = "[Shot 2] At 00:06.000, the camera cuts to a wide of the market waking up. "
SHOT3 = "[Shot 3] At 00:10.000, the camera cuts to a close-up of a hand counting coins. "


def _doc(desc: str) -> str:
    return (f"integrated_multimodal_description: {desc}\n\n"
            "overall_soundscape: Ice rattles across a steel tray.\n\n"
            "non_diegetic_music: N/A\n")


def _text(n: int) -> str:
    body = "[Shot 1] Live-action, cinematic, a fishmonger slams a crate of ice onto the stall. "
    if n >= 2:
        body += SHOT2
    if n >= 3:
        body += SHOT3
    return _doc(body)


def _ctx(**kw) -> Context:
    base = dict(mode="t2va", n_pictures=0, duration_s=15.125)
    base.update(kw)
    return Context(**base)


def test_a_document_short_of_the_pinned_count_is_an_error_naming_both_numbers():
    found = validate(_text(1), _ctx(pinned_shots=3))
    hits = [f for f in found if f.rule == "T11-shot-count-pinned"]
    assert hits and hits[0].severity == "ERROR"
    assert "3" in hits[0].msg and "1" in hits[0].msg


def test_the_pinned_count_present_is_clean():
    found = validate(_text(3), _ctx(pinned_shots=3))
    assert not [f for f in found if f.rule == "T11-shot-count-pinned"]


def test_no_pin_no_rule():
    """`auto` is the writer's freedom; one shot where the heuristic guessed three is not a defect."""
    found = validate(_text(1), _ctx())
    assert not [f for f in found if f.rule == "T11-shot-count-pinned"]


# --------------------------------------------------------------------------- the fix ask

class _Recorder:
    def __init__(self):
        self.asks = []

    def chat(self, messages, **kw):
        self.asks.append(messages[-1]["content"])
        return SimpleNamespace(content="fixed")


def test_the_fix_ask_licenses_the_restructure_when_the_count_is_the_finding():
    """'Keep your shots' and 'write three shots instead of one' cannot ride in the same ask."""
    b = _Recorder()
    fix_with_findings(b, "text", [Finding("T11-shot-count-pinned", "ERROR", "3 asked, 1 written")],
                      labels=(), sections=())
    assert "Keep your shots" not in b.asks[0]


def test_the_fix_ask_still_protects_the_shots_otherwise():
    b = _Recorder()
    fix_with_findings(b, "text", [Finding("T4-missing-cut-time", "ERROR", "[Shot 2] has no time")],
                      labels=(), sections=())
    assert "Keep your shots" in b.asks[0]
