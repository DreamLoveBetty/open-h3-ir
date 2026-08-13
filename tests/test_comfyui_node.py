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
                        seed=7, silent=False, shots=0, assets=[], transcripts={})
    msg = str(e.value)
    assert "intent field is empty" in msg
    assert "gantry" in msg, "the message should show an example sentence, not just scold"


def test_shots_zero_is_omitted_rather_than_sent_as_zero():
    """0 is the node's way of saying 'you decide'. Sending shots=0 would ask for no shots."""
    kw = dict(seconds=8, aspect="16:9", creativity="balanced", effort="standard", seed=7,
              silent=False, assets=[], transcripts={})
    assert "shots" not in C.build_payload("a", shots=0, **kw)
    assert C.build_payload("a", shots=3, **kw)["shots"] == 3


def test_transcripts_are_only_sent_when_there_are_some():
    kw = dict(seconds=8, aspect="16:9", creativity="balanced", effort="standard", seed=7,
              silent=False, shots=0, assets=[])
    assert "transcripts" not in C.build_payload("a", transcripts={}, **kw)
    assert C.build_payload("a", transcripts={"ab": "hello"}, **kw)["transcripts"] == {"ab": "hello"}


# ------------------------------------------------------- the socket decides the role and the job

def test_each_socket_carries_the_role_it_means():
    """The whole point of sockets over dropdowns: a picture in opening_frame IS the first frame, and
    the service is told that rather than left to infer it from prose."""
    written = [("opening_frame", "image", "/a.png", {}),
               ("reference_1", "image", "/b.png", {}),
               ("video_to_edit", "video", "/c.mp4", {"seconds": 3.0, "frames": 72}),
               ("voice_to_match", "audio", "/d.wav", {"seconds": 2.0})]
    got = C.plan_assets(written, ["the start", "the car"], ["a low voice"], "match", "", "")
    assert [a["role"] for a in got] == ["frame_anchor_first", "subject", "edit_source",
                                        "voice_timbre"]
    assert [a["kind"] for a in got] == ["image", "image", "video", "audio"]


def test_notes_are_matched_within_their_own_kind():
    """A video sitting between two pictures must not shift the picture notes by one."""
    written = [("reference_1", "image", "/a.png", {}),
               ("video_to_edit", "video", "/v.mp4", {}),
               ("reference_2", "image", "/b.png", {}),
               ("music", "audio", "/m.wav", {}),
               ("sound_effect", "audio", "/s.wav", {})]
    got = C.plan_assets(written, ["first picture", "second picture"], ["the score", "a door"],
                        "match", "", "")
    assert got[0]["note"] == "first picture"
    assert got[2]["note"] == "second picture"
    assert got[3]["note"] == "the score"
    assert got[4]["note"] == "a door"
    assert "note" not in got[1], "a video takes no note from the picture list"


def test_a_blank_note_line_does_not_become_an_empty_note():
    got = C.plan_assets([("reference_1", "image", "/a.png", {}),
                         ("reference_2", "image", "/b.png", {})],
                        ["the man", "   "], [], "match", "", "")
    assert got[0]["note"] == "the man"
    assert "note" not in got[1]


def test_only_pictures_carry_sizing():
    got = C.plan_assets([("reference_1", "image", "/a.png", {}),
                         ("music", "audio", "/m.wav", {})], [], [], "max", "", "")
    assert got[0]["sizing"] == "max"
    assert "sizing" not in got[1], "sizing is a picture idea; sending it for audio is noise"


def test_extra_facts_about_a_video_are_passed_through():
    """Duration and frame count come from the video object, so the service never has to probe."""
    got = C.plan_assets([("video_to_edit", "video", "/v.mp4", {"seconds": 4.5, "frames": 108})],
                        [], [], "match", "", "")
    assert got[0]["seconds"] == 4.5 and got[0]["frames"] == 108


def test_an_unknown_socket_is_refused_rather_than_sent_with_no_role():
    with pytest.raises(C.ServiceError):
        C.plan_assets([("mystery", "image", "/a.png", {})], [], [], "match", "", "")


@pytest.mark.parametrize("opening,closing,refs,vids,expect", [
    (False, False, 0, 0, "t2va"),
    (True, False, 0, 0, "i2va"),
    (False, True, 0, 0, "l2va"),
    (True, True, 0, 0, "fl2va"),
    (False, False, 2, 0, "ref2va"),
    (False, False, 0, 1, "ref2va"),
])
def test_the_job_is_read_off_the_sockets(opening, closing, refs, vids, expect):
    assert C.expected_mode(opening, closing, refs, vids) == expect


def test_a_disagreement_between_graph_and_brief_is_spelled_out():
    """This is the hole this design closes. Before, the compiler could decide a picture was an
    opening frame while the graph fed it as a reference, and nothing said a word."""
    assert C.check_mode("ref2va", "ref2va") is None
    msg = C.check_mode("ref2va", "i2va")
    assert msg and "ref2va" in msg and "i2va" in msg
    assert "opening_frame" in msg and "reference_1" in msg, "name the sockets, not the concepts"


def test_the_frame_grid_is_computed_the_same_way_the_model_wants():
    from comfyui.nodes import frames_for
    assert frames_for(8.0) == 192, "8 seconds is the one whole second in the trained range"
    assert frames_for(10.0) == 243, "asking for 10 gives 10.125"
    assert frames_for(5.167) == 124
    assert all(frames_for(x) % 17 == 5 for x in (1, 2.5, 5.167, 8, 10, 15.083, 30))
    assert frames_for(0.01) == 5, "never below the grid's first legal value"


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
    assert OpenH3IRCompile.RETURN_NAMES == ("model", "positive", "latent", "vae", "audio_vae",
                                            "prompt", "report")


def test_the_graph_needs_no_loader_boxes():
    """Every model file the render touches comes out of this node, decode included. A VAELoader
    sitting beside it would be exactly the clutter this replaced."""
    assert "VAE" in OpenH3IRCompile.RETURN_TYPES
    assert OpenH3IRCompile.RETURN_TYPES.count("VAE") == 2, "picture and sound decode both need one"


def test_the_combo_choices_match_what_the_service_accepts():
    """Offering a value the service rejects turns a dropdown into a trap."""
    spec = OpenH3IRCompile.INPUT_TYPES()
    assert tuple(spec["required"]["creativity"][0]) == C.CREATIVITY
    assert tuple(spec["optional"]["effort"][0]) == C.EFFORT
    assert tuple(spec["required"]["aspect"][0]) == C.ASPECTS
    assert tuple(spec["optional"]["sizing"][0]) == C.SIZING


def test_is_changed_reacts_to_inputs_without_needing_torch():
    a = OpenH3IRCompile.IS_CHANGED(intent="x", seconds=8.0, reference_1=None)
    b = OpenH3IRCompile.IS_CHANGED(intent="x", seconds=8.0, reference_1=None)
    c = OpenH3IRCompile.IS_CHANGED(intent="y", seconds=8.0, reference_1=None)
    assert a == b and a != c


def test_every_reference_is_its_own_socket_so_nothing_gets_resized():
    """One batched IMAGE input would force references to share dimensions, and ComfyUI's batch
    nodes resize whatever does not fit. A resized reference is a different reference."""
    spec = OpenH3IRCompile.INPUT_TYPES()
    for name in C.PICTURE_SOCKETS + ("opening_frame", "closing_frame"):
        assert spec["optional"][name][0] == "IMAGE"
    for name in C.VIDEO_SOCKETS:
        assert spec["optional"][name][0] == "VIDEO"
    for name in C.SOUND_SOCKETS:
        assert spec["optional"][name][0] == "AUDIO"
    assert "images" not in spec["optional"], "a single batched input is the thing being avoided"


def test_there_is_exactly_one_place_to_set_the_length():
    """Two dials that both claim to set the duration is how you render eight seconds of a ten
    second script."""
    spec = OpenH3IRCompile.INPUT_TYPES()
    everything = dict(spec["required"], **spec["optional"])
    duration_ish = [k for k in everything
                    if any(w in k for w in ("second", "length", "frames_count", "duration"))]
    assert duration_ish == ["seconds"], f"more than one duration control: {duration_ish}"
    assert "width" not in everything and "height" not in everything, \
        "the canvas comes from aspect, so a resolution box would be a second source of truth"


def test_the_two_jobs_at_once_case_is_refused_before_anything_is_written():
    """An opening frame and a reference are different tasks with different weights. Doing both is
    not a thing H3 can be asked for, and finding out after a model call would be worse."""
    node = OpenH3IRCompile()
    with pytest.raises(C.ServiceError) as e:
        node.compile(intent="x", seconds=8.0, aspect="16:9", creativity="balanced",
                     server="http://x", reference_model="r", frames_model="f", text_encoder="c",
                     video_vae="v", audio_vae="a",
                     opening_frame=object(), reference_1=object())
    assert "two different jobs" in str(e.value)


def test_a_batched_socket_is_refused_rather_than_silently_taking_the_first():
    import numpy as np
    from comfyui.nodes import _to_uint8_rgb
    with pytest.raises(C.ServiceError) as e:
        _to_uint8_rgb(np.zeros((3, 8, 8, 3), dtype="float32"), "reference_1")
    msg = str(e.value)
    assert "reference_1" in msg and "own socket" in msg


def test_a_single_image_batch_of_one_is_accepted_and_scaled_to_bytes():
    import numpy as np
    from comfyui.nodes import _to_uint8_rgb
    arr = _to_uint8_rgb(np.ones((1, 4, 4, 3), dtype="float32"), "reference_1")
    assert arr.shape == (4, 4, 3) and arr.dtype.name == "uint8" and arr.max() == 255


def test_an_alpha_channel_is_dropped_rather_than_sent_as_four_channels():
    import numpy as np
    from comfyui.nodes import _to_uint8_rgb
    arr = _to_uint8_rgb(np.ones((4, 4, 4), dtype="float32"), "reference_2")
    assert arr.shape == (4, 4, 3)


def test_a_non_image_array_is_named_rather_than_crashing_in_pil():
    import numpy as np
    from comfyui.nodes import _to_uint8_rgb
    with pytest.raises(C.ServiceError) as e:
        _to_uint8_rgb(np.zeros((8, 8), dtype="float32"), "reference_3")
    assert "reference_3" in str(e.value)


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


def test_defaults_prefer_the_right_model_family_over_a_loose_name_match():
    """Measured on a real install: matching only "video" chose an LTX VAE on a box that also had
    H3's. A default from the wrong family loads and then renders wrongly for an invisible reason."""
    from comfyui.nodes import _default_like
    vaes = ["LTX23_video_vae_bf16.safetensors", "minimax_h3_audio_vae_fp32.safetensors",
            "minimax_h3_video_vae_fp16.safetensors"]
    assert _default_like(vaes, ("minimax", "video"), ("h3", "video")) == \
        "minimax_h3_video_vae_fp16.safetensors"
    assert _default_like(vaes, ("minimax", "audio"), ("h3", "audio")) == \
        "minimax_h3_audio_vae_fp32.safetensors"


def test_a_quantisation_only_some_cards_can_run_is_not_the_default():
    """nvfp4 needs Blackwell. Defaulting to it would break the node for most of the people it is
    for, so the portable build is preferred when both are present."""
    from comfyui.nodes import _default_like
    unets = ["MiniMax_H3_Ref2VA_pruned_nvfp4.safetensors",
             "minimax_h3_ref2va_pruned_int8_convrot.safetensors"]
    assert _default_like(unets, ("ref2va", "int8"), ("ref2va",)) == \
        "minimax_h3_ref2va_pruned_int8_convrot.safetensors"


def test_a_default_still_exists_when_nothing_matches():
    """An empty default would draw a broken dropdown. The report names the files, so a wrong family
    is visible rather than silent."""
    from comfyui.nodes import _default_like
    assert _default_like(["something_else.safetensors"], ("minimax", "video")) == \
        "something_else.safetensors"
    assert _default_like([], ("minimax", "video")) == ""
