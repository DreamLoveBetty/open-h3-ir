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


# ---------------------------------------------------- finding the path without asking anyone to type it

def test_comfyuis_own_folder_is_offered_first_and_the_wsl_spelling_second():
    """ComfyUI's location comes from ComfyUI. What cannot be known is how a service on another view
    of the same disk spells it, so the usual forms are offered and the service confirms one."""
    got = C.path_candidates(r"C:\ComfyUI-Production")
    assert got[0] == r"C:\ComfyUI-Production", "try it as-is first, which is right when they share a disk"
    assert "/mnt/c/ComfyUI-Production" in got, "the ComfyUI-on-Windows, service-in-WSL case"


def test_a_posix_root_offers_only_itself():
    """No drive letter means nothing to translate, and inventing candidates would just slow the
    failure down."""
    assert C.path_candidates("/opt/ComfyUI") == ["/opt/ComfyUI"]


def test_an_override_replaces_the_guesses_rather_than_joining_them():
    assert C.path_candidates(r"C:\X", "/srv/shared") == ["/srv/shared"]
    assert C.path_candidates(r"C:\X", "   ") != ["   "], "blank is not an override"


def test_only_an_unreadable_attachment_is_worth_another_spelling():
    """Retrying anything else would hide a real problem behind repeated attempts, and retrying a
    dead model endpoint three times is three times the wait for the same answer."""
    assert C.retranslate(C.ServiceError("nope", C.ASSET_UNREADABLE)) is True
    assert C.retranslate(C.ServiceError("llm is down")) is False
    assert C.retranslate(ValueError("something else")) is False


def test_the_asset_failure_actually_carries_that_code(monkeypatch):
    """The retry is worthless if the error it looks for is never raised. This is the wire between
    the two."""
    _fake(monkeypatch, (422, {"detail": {"code": "asset-missing", "message": "no such file"}}))
    with pytest.raises(C.ServiceError) as e:
        C.compile_brief("http://x", {"intent": "a"})
    assert C.retranslate(e.value) is True
