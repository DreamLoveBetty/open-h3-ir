"""The size knob: a pixel-area ask that reaches the canvas, and a default that moves nothing.

The gap it closes was found by the owner in one question: "Where's the quality knob in the node".
There was none, anywhere. The compiler pinned every render to 768 on the short edge, the API had no
field to ask for more, so the node had nothing to offer, and the owner's own habit of rendering at
1.5 megapixels could not be expressed. H3's capabilities line has said all along that any multiple
of 32 renders fine.

No model and no GPU anywhere in this file.
"""
from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from h3ir.grid import canvas_for_aspect
from h3ir import service


def test_omitted_means_exactly_what_every_render_before_the_field_used():
    for aspect in ("16:9", "21:9", "4:3", "1:1", "3:4", "9:16"):
        assert canvas_for_aspect(aspect) == canvas_for_aspect(aspect, None)
    assert canvas_for_aspect("16:9") == (1344, 768)


def test_a_stated_area_is_hit_at_the_stated_aspect():
    w, h = canvas_for_aspect("16:9", 1.5)
    assert w % 32 == 0 and h % 32 == 0
    assert abs(w * h - 1_500_000) / 1_500_000 < 0.06, (w, h, w * h)
    assert abs((w / h) - (16 / 9)) < 0.08, (w, h)


def test_the_default_area_cap_does_not_gag_an_explicit_ask():
    """The 768-era cap keeps the DEFAULT inside the trained budget. A caller stating 1.5 has
    stated the budget, so the cap must not silently shrink it back."""
    w, h = canvas_for_aspect("16:9", 1.5)
    assert w * h > 1344 * 768


def test_one_is_not_a_silent_synonym_for_default():
    """1.0 MP at 1:1 is 992x992-ish; the default 1:1 is 768x768. The knob must actually turn."""
    assert canvas_for_aspect("1:1", 1.0) != canvas_for_aspect("1:1", None)


def test_the_service_carries_it_to_the_reported_canvas(monkeypatch):
    client = TestClient(service.app)
    # compile would need the model; the request model's own validation is what this checks
    r = client.post("/v1/briefs", json={"intent": "x", "megapixels": 9.0})
    assert r.status_code == 422, r.text
    r = client.post("/v1/briefs", json={"intent": "x", "megapixels": 0.01})
    assert r.status_code == 422, r.text


def test_brief_carries_it_into_the_target():
    from h3ir.grid import Target
    t = Target.build(8.0, "16:9", None, 1.5)
    assert t.canvas == canvas_for_aspect("16:9", 1.5)
    t0 = Target.build(8.0, "16:9")
    assert t0.canvas == (1344, 768)
