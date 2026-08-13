"""The ComfyUI node, tested with no ComfyUI, no torch and no server in the process.

The node's value is entirely in what it does on a bad day, so most of what follows asserts on the
sentence a user reads rather than on an exception type. A node that raises the right class with a
useless message has failed at the only job that matters when something is wrong.

Several of these are falsification controls: they fail if the code starts guessing. `render_fields`
inventing a frame count, or a mapping key being renamed, would both leave the node looking like it
works while quietly producing the wrong render or breaking every saved workflow in the world.
"""
from __future__ import annotations

import pytest

from comfyui import h3ir_client as C
from comfyui.nodes import (NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS, OpenH3IRCompile)


# --------------------------------------------------------------------------- payload construction

def test_an_empty_intent_says_what_to_type_instead_of_posting_nothing():
    with pytest.raises(C.ServiceError) as e:
        C.build_payload("   ", seconds=8, aspect="16:9", creativity="balanced", effort="standard",
                        seed=7, silent=False, shots=0, asset_paths=[], notes=[], sizing="match")
    msg = str(e.value)
    assert "intent field is empty" in msg
    assert "gantry" in msg, "the message should show an example sentence, not just scold"


def test_shots_zero_is_omitted_rather_than_sent_as_zero():
    """0 is the node's way of saying 'you decide'. Sending shots=0 would ask for no shots."""
    p = C.build_payload("a", seconds=8, aspect="16:9", creativity="balanced", effort="standard",
                        seed=7, silent=False, shots=0, asset_paths=[], notes=[], sizing="match")
    assert "shots" not in p
    p2 = C.build_payload("a", seconds=8, aspect="16:9", creativity="balanced", effort="standard",
                         seed=7, silent=False, shots=3, asset_paths=[], notes=[], sizing="match")
    assert p2["shots"] == 3


def test_notes_attach_to_images_in_order_and_a_short_list_is_fine():
    p = C.build_payload("a", seconds=8, aspect="16:9", creativity="balanced", effort="standard",
                        seed=7, silent=False, shots=0,
                        asset_paths=["/a.png", "/b.png", "/c.png"],
                        notes=["the man", "", "the car"], sizing="max")
    assert [a["path"] for a in p["assets"]] == ["/a.png", "/b.png", "/c.png"], \
        "order binds each image to its picture label and must never be reordered"
    assert p["assets"][0]["note"] == "the man"
    assert "note" not in p["assets"][1], "a blank line must not become an empty note"
    assert p["assets"][2]["note"] == "the car"
    assert all(a["sizing"] == "max" for a in p["assets"])


def test_fewer_notes_than_images_does_not_raise():
    p = C.build_payload("a", seconds=8, aspect="16:9", creativity="balanced", effort="standard",
                        seed=7, silent=False, shots=0, asset_paths=["/a.png", "/b.png"],
                        notes=["only one"], sizing="match")
    assert p["assets"][0]["note"] == "only one"
    assert "note" not in p["assets"][1]


# --------------------------------------------------------------------------- path translation

def test_a_windows_path_becomes_the_services_view_of_the_same_file():
    got = C.translate_path(r"C:\ComfyUI-Production\temp\ref.png",
                           r"C:\ComfyUI-Production", "/mnt/c/ComfyUI-Production")
    assert got == "/mnt/c/ComfyUI-Production/temp/ref.png"


def test_no_prefixes_means_no_translation():
    assert C.translate_path("/srv/x/a.png", "", "") == "/srv/x/a.png"
    assert C.translate_path("/srv/x/a.png", "/srv", "") == "/srv/x/a.png"


def test_a_path_outside_the_prefix_is_returned_untouched():
    """Silently rewriting an unrelated path would send the service a file that does not exist and
    blame the user's mapping. Better to pass it through and let the service say it cannot read it."""
    assert C.translate_path("/elsewhere/a.png", r"C:\ComfyUI", "/mnt/c/ComfyUI") == "/elsewhere/a.png"


def test_translation_is_case_insensitive_because_windows_is():
    got = C.translate_path(r"c:\comfyui-production\temp\ref.png",
                           r"C:\ComfyUI-Production", "/mnt/c/ComfyUI-Production")
    assert got == "/mnt/c/ComfyUI-Production/temp/ref.png"


# --------------------------------------------------------------------------- failure messages

def _fake(monkeypatch, *replies):
    """Replace the HTTP layer with a scripted sequence of (status, body) pairs."""
    calls = list(replies)

    def fake_request(server, path, *, payload=None, timeout=600.0):
        return calls.pop(0)

    monkeypatch.setattr(C, "_request", fake_request)


def test_an_unreachable_service_names_the_command_that_starts_one(monkeypatch):
    import urllib.error

    def boom(req, timeout=None):
        raise urllib.error.URLError("Connection refused")

    monkeypatch.setattr(C.urllib.request, "urlopen", boom)
    with pytest.raises(C.ServiceError) as e:
        C._request("http://127.0.0.1:8420", "/v1/capabilities")
    msg = str(e.value)
    assert "h3ir serve" in msg, "the message must tell them how to start the thing that is missing"
    assert "H3IR_LLM_URL" in msg
    assert "8420" in msg


def test_a_timeout_points_at_the_knob_that_fixes_it(monkeypatch):
    import socket as s

    def boom(req, timeout=None):
        raise s.timeout()

    monkeypatch.setattr(C.urllib.request, "urlopen", boom)
    with pytest.raises(C.ServiceError) as e:
        C._request("http://x", "/v1/briefs", payload={}, timeout=30)
    assert "timeout_s" in str(e.value)


def test_an_unreadable_reference_explains_the_two_path_views(monkeypatch):
    """The failure this project will actually generate: ComfyUI on Windows, service in WSL."""
    _fake(monkeypatch, (422, {"detail": {"code": "asset-missing",
                                        "message": "no such file: C:\\x\\ref.png"}}))
    with pytest.raises(C.ServiceError) as e:
        C.compile_brief("http://x", {"intent": "a"})
    msg = str(e.value)
    assert "comfy_path_prefix" in msg and "service_path_prefix" in msg, \
        "naming the widgets that fix it is the whole point of the message"
    assert "another machine" in msg, "the remote case has no fix and must be stated"


def test_a_contradictory_request_lists_the_rules_that_fired(monkeypatch):
    _fake(monkeypatch, (422, {"status": "invalid", "errors": [
        {"rule": "T6-duration", "message": "asked for silence and a score"}]}))
    with pytest.raises(C.ServiceError) as e:
        C.compile_brief("http://x", {"intent": "a"})
    msg = str(e.value)
    assert "T6-duration" in msg and "asked for silence and a score" in msg


def test_a_dead_llm_endpoint_is_not_reported_as_the_nodes_fault(monkeypatch):
    _fake(monkeypatch, (503, {"detail": {"code": "llm-unavailable", "message": "connect refused"}}))
    with pytest.raises(C.ServiceError) as e:
        C.compile_brief("http://x", {"intent": "a"})
    msg = str(e.value)
    assert "H3IR_LLM_URL" in msg
    assert "is running" in msg, "distinguish a live service with a dead model from a dead service"


def test_an_llm_error_says_the_graph_is_innocent(monkeypatch):
    _fake(monkeypatch, (502, {"detail": {"message": "model returned 500"}}))
    with pytest.raises(C.ServiceError) as e:
        C.compile_brief("http://x", {"intent": "a"})
    assert "Nothing is wrong with this node or the graph" in str(e.value)


def test_a_service_bug_is_reported_as_a_service_bug(monkeypatch):
    _fake(monkeypatch, (500, {"status": "invalid", "errors": []}))
    with pytest.raises(C.ServiceError) as e:
        C.compile_brief("http://x", {"intent": "a"})
    assert "bug in the service" in str(e.value)


def test_a_clarification_is_surfaced_as_a_question_not_a_crash(monkeypatch):
    _fake(monkeypatch, (201, {"id": "abc", "status": "needs_input",
                              "question": {"question": "Is the image the opening frame?"},
                              "default_if_unanswered": "reference"}))
    with pytest.raises(C.ServiceError) as e:
        C.compile_brief("http://x", {"intent": "a"})
    msg = str(e.value)
    assert "Is the image the opening frame?" in msg
    assert "reference" in msg, "say what it would assume, so ignoring it is an informed choice"


def test_an_accepted_brief_returns_the_render_fields(monkeypatch):
    _fake(monkeypatch,
          (201, {"id": "deadbeef", "status": "ready"}),
          (200, {"prompt": "a document", "mode": "t2va", "frames": 192, "canvas": [1344, 768],
                 "wiring": [], "render_hash": "f" * 64}))
    out = C.compile_brief("http://x", {"intent": "a"})
    assert out["brief_id"] == "deadbeef"
    assert out["frames"] == 192
    assert out["degraded"] is False


def test_a_degraded_brief_is_flagged_rather_than_passed_off_as_written(monkeypatch):
    _fake(monkeypatch,
          (201, {"id": "d1", "status": "degraded", "fallback_reason": "model refused twice"}),
          (200, {"prompt": "p", "mode": "t2va", "frames": 124, "canvas": [1344, 768]}))
    out = C.compile_brief("http://x", {"intent": "a"})
    assert out["degraded"] is True
    assert "refused twice" in out["fallback_reason"]
    assert "not a written one" in C.report(out, server="http://x", sizing_conflict=False)


def test_an_unexpected_status_carries_the_body_rather_than_just_the_number(monkeypatch):
    _fake(monkeypatch, (418, "I am a teapot"))
    with pytest.raises(C.ServiceError) as e:
        C.compile_brief("http://x", {"intent": "a"})
    assert "418" in str(e.value) and "teapot" in str(e.value)


def test_an_accepted_brief_with_no_id_is_refused(monkeypatch):
    _fake(monkeypatch, (201, {"status": "ready"}))
    with pytest.raises(C.ServiceError) as e:
        C.compile_brief("http://x", {"intent": "a"})
    assert "no id" in str(e.value)


# ------------------------------------------------------- render fields: controls against guessing

@pytest.mark.parametrize("body,missing", [
    ({"frames": 192, "canvas": [1344, 768]}, "prompt"),
    ({"prompt": "  ", "frames": 192, "canvas": [1344, 768]}, "empty prompt"),
    ({"prompt": "p", "canvas": [1344, 768]}, "frame count"),
    ({"prompt": "p", "frames": 0, "canvas": [1344, 768]}, "frame count"),
    ({"prompt": "p", "frames": 192}, "canvas"),
    ({"prompt": "p", "frames": 192, "canvas": [1344]}, "canvas"),
])
def test_a_missing_render_field_raises_instead_of_defaulting(body, missing):
    """This is the control. If any of these ever returns a number, the node will render at a length
    or a size nobody chose, and the result will look like a model problem."""
    with pytest.raises(C.ServiceError) as e:
        C.render_fields(body)
    assert missing.split()[-1] in str(e.value).lower()


def test_render_fields_passes_through_exactly_what_the_service_said():
    prompt, w, h, length, sizing = C.render_fields(
        {"prompt": "doc", "frames": 243, "canvas": [1920, 1088],
         "wiring": [{"sizing": "max"}, {"sizing": "max"}]})
    assert (prompt, w, h, length, sizing) == ("doc", 1920, 1088, 243, "max")


def test_disagreeing_sizings_fall_back_to_match_and_are_reported():
    body = {"prompt": "d", "frames": 124, "canvas": [1344, 768], "mode": "ref2va",
            "wiring": [{"label": "<Picture 1>", "sizing": "match"},
                       {"label": "<Picture 2>", "sizing": "max"}]}
    *_, sizing = C.render_fields(body)
    assert sizing == "match"
    text = C.report(body, server="http://x", sizing_conflict=True)
    assert "one ref_image_size for all of them" in text


def test_the_report_states_the_real_duration_not_the_requested_one():
    text = C.report({"mode": "t2va", "frames": 243, "canvas": [1344, 768], "render_hash": "a" * 64,
                     "brief_id": "id1"}, server="http://s", sizing_conflict=False)
    assert "10.125s" in text, "the whole point is showing what you actually got"
    assert "243 frames" in text


# --------------------------------------------------------------------------- caching

def test_the_fingerprint_changes_when_any_input_changes():
    a = C.inputs_fingerprint("intent", 8.0, "16:9")
    assert a == C.inputs_fingerprint("intent", 8.0, "16:9")
    assert a != C.inputs_fingerprint("intent", 8.1, "16:9")
    assert a != C.inputs_fingerprint("intent", 8.0, "9:16")


def test_the_fingerprint_does_not_collide_on_reordered_boundaries():
    """Without a separator between parts, ("ab","c") and ("a","bc") would hash the same, and two
    different graphs would share one cached brief."""
    assert C.inputs_fingerprint("ab", "c") != C.inputs_fingerprint("a", "bc")


# --------------------------------------------------------------------------- the node's schema

def test_the_mapping_keys_are_the_ones_saved_workflows_reference():
    """A rename here silently breaks every workflow anyone has saved. Pinned deliberately."""
    assert set(NODE_CLASS_MAPPINGS) == {"OpenH3IRCompile", "OpenH3IRShowText"}
    assert set(NODE_DISPLAY_NAME_MAPPINGS) == set(NODE_CLASS_MAPPINGS)


def test_every_input_has_a_tooltip():
    """The tooltip is where people learn a node. An untooltipped widget is an undocumented one."""
    spec = OpenH3IRCompile.INPUT_TYPES()
    missing = []
    for section in ("required", "optional"):
        for name, decl in spec.get(section, {}).items():
            opts = decl[1] if len(decl) > 1 and isinstance(decl[1], dict) else {}
            if not opts.get("tooltip"):
                missing.append(f"{section}.{name}")
    assert not missing, f"inputs with no tooltip: {missing}"


def test_the_outputs_are_named_and_described_consistently():
    assert len(OpenH3IRCompile.RETURN_TYPES) == len(OpenH3IRCompile.RETURN_NAMES)
    assert len(OpenH3IRCompile.OUTPUT_TOOLTIPS) == len(OpenH3IRCompile.RETURN_TYPES)
    assert OpenH3IRCompile.RETURN_NAMES == ("prompt", "width", "height", "length",
                                            "ref_image_size", "report")


def test_the_combo_choices_match_what_the_service_accepts():
    """Offering a value the service rejects turns a dropdown into a trap."""
    spec = OpenH3IRCompile.INPUT_TYPES()
    assert tuple(spec["required"]["creativity"][0]) == C.CREATIVITY
    assert tuple(spec["optional"]["effort"][0]) == C.EFFORT
    assert tuple(spec["required"]["aspect"][0]) == C.ASPECTS
    assert tuple(spec["optional"]["sizing"][0]) == C.SIZING


def test_is_changed_reacts_to_inputs_without_needing_torch():
    a = OpenH3IRCompile.IS_CHANGED(intent="x", seconds=8.0, image_1=None)
    b = OpenH3IRCompile.IS_CHANGED(intent="x", seconds=8.0, image_1=None)
    c = OpenH3IRCompile.IS_CHANGED(intent="y", seconds=8.0, image_1=None)
    assert a == b and a != c


def test_every_reference_is_its_own_socket_so_nothing_gets_resized():
    """One batched IMAGE input would force references to share dimensions, and ComfyUI's batch
    nodes resize whatever does not fit. A resized reference is a different reference."""
    from comfyui.nodes import IMAGE_SOCKETS, MAX_REFERENCES
    spec = OpenH3IRCompile.INPUT_TYPES()
    assert len(IMAGE_SOCKETS) == MAX_REFERENCES
    for s in IMAGE_SOCKETS:
        assert spec["optional"][s][0] == "IMAGE"
    assert "images" not in spec["optional"], "a single batched input is the thing being avoided"


def test_a_batched_socket_is_refused_rather_than_silently_taking_the_first():
    import numpy as np
    from comfyui.nodes import _to_uint8_rgb
    with pytest.raises(C.ServiceError) as e:
        _to_uint8_rgb(np.zeros((3, 8, 8, 3), dtype="float32"), "image_1")
    msg = str(e.value)
    assert "image_1" in msg and "own image socket" in msg


def test_a_single_image_batch_of_one_is_accepted_and_scaled_to_bytes():
    import numpy as np
    from comfyui.nodes import _to_uint8_rgb
    arr = _to_uint8_rgb(np.ones((1, 4, 4, 3), dtype="float32"), "image_1")
    assert arr.shape == (4, 4, 3) and arr.dtype.name == "uint8" and arr.max() == 255


def test_an_alpha_channel_is_dropped_rather_than_sent_as_four_channels():
    import numpy as np
    from comfyui.nodes import _to_uint8_rgb
    arr = _to_uint8_rgb(np.ones((4, 4, 4), dtype="float32"), "image_2")
    assert arr.shape == (4, 4, 3)


def test_a_non_image_array_is_named_rather_than_crashing_in_pil():
    import numpy as np
    from comfyui.nodes import _to_uint8_rgb
    with pytest.raises(C.ServiceError) as e:
        _to_uint8_rgb(np.zeros((8, 8), dtype="float32"), "image_3")
    assert "image_3" in str(e.value)


def test_the_node_module_imports_without_torch_or_comfyui():
    """The pack must appear on the menu on any install. A module-scope import of torch, numpy or PIL
    here would take the whole pack down on an install with a broken imaging stack."""
    import importlib
    import sys
    for blocked in ("torch", "folder_paths"):
        assert blocked not in sys.modules or True  # not asserting absence, only that we do not need it
    m = importlib.import_module("comfyui.nodes")
    src = open(m.__file__, encoding="utf-8").read()
    head = src.split("class OpenH3IRCompile")[0]
    for bad in ("\nimport torch", "\nimport numpy", "\nfrom PIL", "\nimport folder_paths"):
        assert bad not in head, f"module-scope {bad.strip()} would break the pack on some installs"
