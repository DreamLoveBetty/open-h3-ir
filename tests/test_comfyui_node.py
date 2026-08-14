"""The ComfyUI nodes, tested with no ComfyUI, no torch and no server in the process.

The nodes' value is entirely in what they do on a bad day, so most of what follows asserts on the
sentence a user reads rather than on an exception type. A node that raises the right class with a
useless message has failed at the only job that matters when something is wrong.

Several of these are falsification controls: they fail if the code starts guessing. `render_fields`
inventing a frame count, a model file being resolved from its name instead of being picked, or a
mapping key being renamed would each leave the node looking like it works while quietly producing the
wrong render or breaking every saved workflow in the world.
"""
from __future__ import annotations

import pytest

from comfyui import h3ir_client as C


# --------------------------------------------------------------------------- payload construction

def test_an_empty_intent_says_what_to_type_instead_of_posting_nothing():
    with pytest.raises(C.ServiceError) as e:
        C.build_payload("   ", seconds=8, aspect="16:9", creativity="balanced", effort="standard",
                        seed=7, silent=False, shots="auto", assets=[], transcripts={})
    msg = str(e.value)
    assert "intent field is empty" in msg
    assert "gantry" in msg, "the message should show an example sentence, not just scold"


def test_auto_shots_is_omitted_rather_than_sent_as_zero():
    """`auto` is the widget's way of saying 'you decide', which is the service's own default when the
    field is absent. Sending 0 would ask for no shots."""
    kw = dict(seconds=8, aspect="16:9", creativity="balanced", effort="standard", seed=7,
              silent=False, assets=[], transcripts={})
    assert "shots" not in C.build_payload("a", shots="auto", **kw)
    assert C.build_payload("a", shots="3", **kw)["shots"] == 3


def test_a_workflow_saved_against_the_old_integer_shots_still_compiles():
    """The widget changed from an INT with a magic 0 to a combo. A saved workflow hands back what it
    saved, so 0 and 3 have to keep meaning what they meant."""
    kw = dict(seconds=8, aspect="16:9", creativity="balanced", effort="standard", seed=7,
              silent=False, assets=[], transcripts={})
    assert "shots" not in C.build_payload("a", shots=0, **kw)
    assert C.build_payload("a", shots=3, **kw)["shots"] == 3


def test_more_shots_than_the_compiler_can_cut_is_refused_rather_than_clamped():
    """`shots.py` MAX_SHOTS is 4 and `plan.py` clamps the caller's number to it, so asking for 6 used
    to silently get 4. A number the engine drops is the surface lying about what it will do."""
    from h3ir.shots import MAX_SHOTS

    with pytest.raises(C.ServiceError) as e:
        C.shot_count(MAX_SHOTS + 2)
    assert str(MAX_SHOTS) in str(e.value) and "dropped" in str(e.value)


def test_a_shots_value_that_is_neither_auto_nor_a_number_is_refused():
    with pytest.raises(C.ServiceError) as e:
        C.shot_count("lots")
    assert "auto" in str(e.value)


def test_transcripts_are_only_sent_when_there_are_some():
    kw = dict(seconds=8, aspect="16:9", creativity="balanced", effort="standard", seed=7,
              silent=False, shots="auto", assets=[])
    assert "transcripts" not in C.build_payload("a", transcripts={}, **kw)
    assert C.build_payload("a", transcripts={"ab": "hello"}, **kw)["transcripts"] == {"ab": "hello"}


# ------------------------------------------------------- the socket decides the role and the job

def test_each_socket_carries_the_role_it_means():
    """The whole point of sockets over dropdowns: a picture in `first frame` IS the first frame, and
    the service is told that rather than left to infer it from prose."""
    written = [("first frame", "image", "/a.png", {}),
               ("picture 1", "image", "/b.png", {}),
               ("clip 1", "video", "/c.mp4", {"role": "edit_source", "seconds": 3.0, "frames": 72}),
               ("voice to match", "audio", "/d.wav", {"seconds": 2.0})]
    got = C.plan_assets(written, ["the car"], "match", "", "")
    assert [a["role"] for a in got] == ["frame_anchor_first", "subject", "edit_source",
                                        "voice_timbre"]
    assert [a["kind"] for a in got] == ["image", "image", "video", "audio"]


def test_a_picture_note_binds_to_a_picture_socket_and_never_to_a_frame_anchor():
    """This is the bug the design was written to close. `plan_assets` walked images in written order
    with one counter, which is opening frame, closing frame, then references, so with a first frame
    plus two pictures line 1 described the first frame. Nobody would guess that, and the canvas now
    says `picture 1` for the socket the brief calls <Picture 1>."""
    written = [("first frame", "image", "/f.png", {}),
               ("picture 1", "image", "/a.png", {}),
               ("picture 2", "image", "/b.png", {})]
    got = C.plan_assets(written, ["the man", "the red car"], "match", "", "")
    assert "note" not in got[0], "the frame anchor takes no line from the picture notes"
    assert got[1]["note"] == "the man"
    assert got[2]["note"] == "the red car"


def test_a_clip_between_two_pictures_does_not_shift_the_picture_notes():
    written = [("picture 1", "image", "/a.png", {}),
               ("clip 1", "video", "/v.mp4", {"role": "subject"}),
               ("picture 2", "image", "/b.png", {})]
    got = C.plan_assets(written, ["first picture", "second picture"], "match", "", "")
    assert got[0]["note"] == "first picture"
    assert got[2]["note"] == "second picture"
    assert "note" not in got[1], "a clip takes no note from the picture list"


def test_a_sound_note_arrives_with_its_own_socket_rather_than_by_position():
    """The old block matched lines by position across three differently named roles, so filling only
    the effect attached line one to it and adding music later shifted everything."""
    written = [("sound effect", "audio", "/s.wav", {"note": "a heavy door slamming"}),
               ("music", "audio", "/m.wav", {"note": "slow synth score, no drums"})]
    got = C.plan_assets(written, [], "match", "", "")
    assert got[0]["note"] == "a heavy door slamming" and got[0]["role"] == "sfx"
    assert got[1]["note"] == "slow synth score, no drums" and got[1]["role"] == "bgm"


def test_a_blank_note_line_does_not_become_an_empty_note():
    got = C.plan_assets([("picture 1", "image", "/a.png", {}),
                         ("picture 2", "image", "/b.png", {})],
                        ["the man", "   "], "match", "", "")
    assert got[0]["note"] == "the man"
    assert "note" not in got[1]


def test_only_pictures_carry_sizing():
    got = C.plan_assets([("picture 1", "image", "/a.png", {}),
                         ("music", "audio", "/m.wav", {})], [], "max", "", "")
    assert got[0]["sizing"] == "max"
    assert "sizing" not in got[1], "sizing is a picture idea; sending it for audio is noise"


def test_extra_facts_about_a_clip_are_passed_through():
    """Duration and frame count come from the frames themselves, so the service never has to probe
    for what the node already knows."""
    got = C.plan_assets([("clip 1", "video", "/v.mp4",
                          {"role": "subject", "seconds": 4.5, "frames": 108})], [], "match", "", "")
    assert got[0]["seconds"] == 4.5 and got[0]["frames"] == 108


def test_a_clips_soundtrack_points_back_at_its_own_clip():
    """`plan.py:build_manifest` emits a paired soundtrack's <Audio j> label BEFORE its <Video k>, and
    the stock node pairs `ref_video_audio_N` with `ref_video_N`. Without the pointer the service
    numbers the soundtrack as a standalone audio and the two sides disagree about which label is
    which, which is the plausible-and-wrong failure this pack exists to prevent."""
    got = C.plan_assets([("clip 1", "video", "/v.mp4", {"role": "subject"}),
                         ("clip 1 sound", "audio", "/v.wav",
                          {"role": "bgm", "paired_video_path": "/v.mp4"})], [], "match", "", "")
    assert got[1]["paired_video_path"] == "/v.mp4"


def test_the_pointer_to_the_paired_clip_is_translated_like_any_other_path():
    """FOUND BY RENDERING. The pointer was sent in ComfyUI's spelling while every other path was
    translated, so on a split install the service could not open it, stopped treating the pair as a
    pair, and numbered the soundtrack as a standalone <Audio 1> while H3 received it as
    ref_video_audio_1. Two labels for one file, and only the report block showed it."""
    got = C.plan_assets(
        [("clip 1", "video", r"C:\ComfyUI\temp\v.mp4", {"role": "subject"}),
         ("clip 1 sound", "audio", r"C:\ComfyUI\temp\v.wav",
          {"role": "bgm", "paired_video_path": r"C:\ComfyUI\temp\v.mp4"})],
        [], "match", r"C:\ComfyUI", "/mnt/c/ComfyUI")
    assert got[0]["path"] == "/mnt/c/ComfyUI/temp/v.mp4"
    assert got[1]["paired_video_path"] == got[0]["path"], \
        "the pointer has to name the file by the same spelling the clip was sent under"


def test_an_unknown_socket_is_refused_rather_than_sent_with_no_role():
    with pytest.raises(C.ServiceError):
        C.plan_assets([("mystery", "image", "/a.png", {})], [], "match", "", "")


def test_grown_sockets_are_read_in_socket_order_and_not_in_dict_order():
    """The order decides which picture becomes <Picture 1>. A prompt that serialised its inputs in
    another order must not renumber them."""
    got = C.ordered({"picture 3": "c", "picture 1": "a", "picture 2": "b"}, C.PICTURE_NAMES)
    assert got == [("picture 1", "a"), ("picture 2", "b"), ("picture 3", "c")]


def test_a_gap_in_the_grown_sockets_closes_up_rather_than_leaving_a_hole():
    """Autogrow can leave socket 2 empty while 3 is filled. The brief numbers what arrived."""
    assert C.ordered({"picture 1": "a", "picture 3": "c"}, C.PICTURE_NAMES) == \
        [("picture 1", "a"), ("picture 3", "c")]
    assert C.ordered({"picture 2": None, "picture 1": "a"}, C.PICTURE_NAMES) == [("picture 1", "a")]


def test_an_unexpected_grown_socket_is_refused():
    with pytest.raises(C.ServiceError):
        C.ordered({"picture 99": "x"}, C.PICTURE_NAMES)


@pytest.mark.parametrize("first,last,pics,clips,sounds,expect", [
    (False, False, 0, 0, 0, "t2va"),
    (True, False, 0, 0, 0, "i2va"),
    (False, True, 0, 0, 0, "l2va"),
    (True, True, 0, 0, 0, "fl2va"),
    (False, False, 2, 0, 0, "ref2va"),
    (False, False, 0, 1, 0, "ref2va"),
    (False, False, 0, 0, 1, "ref2va"),
    (False, False, 0, 0, 3, "ref2va"),
])
def test_the_job_is_read_off_the_sockets(first, last, pics, clips, sounds, expect):
    assert C.expected_mode(first, last, pics, clips, sounds) == expect


def test_a_sound_on_its_own_is_a_reference_job_and_not_a_text_only_one():
    """FOUND BY RENDERING. A graph with only a music clip declared t2va while the service correctly
    wrote ref2va, so the node printed a warning saying the render would come out wrong. It would
    not have. A warning that fires on a correct graph teaches people to ignore warnings.

    The service's rule is not a heuristic: an attached video or audio forces ref2va because H3's
    frame checkpoint cannot accept either.
    """
    from h3ir.mode import infer_mode
    from h3ir.models import AssetKind, AssetRef, Brief, Role

    declared = C.expected_mode(False, False, 0, 0, 1)
    reported = infer_mode(Brief(intent="a score over an empty street", assets=[
        AssetRef(kind=AssetKind.AUDIO, role=Role.BGM, sha256="a" * 64)])).mode.value
    assert declared == reported == "ref2va"
    assert C.check_mode(declared, reported) is None, "and therefore no warning"


def test_a_disagreement_between_graph_and_brief_is_spelled_out():
    """This is the hole this design closes. Before, the compiler could decide a picture was an
    opening frame while the graph fed it as a reference, and nothing said a word."""
    assert C.check_mode("ref2va", "ref2va") is None
    msg = C.check_mode("ref2va", "i2va")
    assert msg and "ref2va" in msg and "i2va" in msg
    assert "first frame" in msg and "picture 1" in msg, "name the sockets as the canvas names them"


# --------------------------------------------------------------------------- the bundles

def test_a_transcript_with_no_clip_to_transcribe_is_an_error_and_not_a_no_op():
    """`spoken_words` used to be dropped entirely unless the voice socket was connected, so it was a
    field that could silently do nothing while being labelled `what the voice says`."""
    with pytest.raises(C.ServiceError) as e:
        C.sound_bundle(music=None, music_note="", effect=None, effect_note="", voice=None,
                       voice_note="", voice_words="hello there")
    msg = str(e.value)
    assert "no voice is connected" in msg
    assert "not dialogue for your video" in msg, "say what the field is, since it invites the wrong "\
                                                "thing"


def test_an_empty_sound_node_says_so_rather_than_changing_nothing():
    with pytest.raises(C.ServiceError) as e:
        C.sound_bundle(music=None, music_note="", effect=None, effect_note="", voice=None,
                       voice_note="", voice_words="")
    assert "nothing connected" in str(e.value)


def test_each_sound_keeps_the_note_that_was_typed_beside_it():
    got = C.sound_bundle(music="M", music_note=" slow synth ", effect=None, effect_note="ignored",
                         voice="V", voice_note="hoarse", voice_words=" the words ")
    assert got["music_note"] == "slow synth" and got["voice_note"] == "hoarse"
    assert got["voice_words"] == "the words"
    assert got["effect"] is None


def test_a_clip_carries_the_role_its_job_means():
    for job, role in C.FOOTAGE_JOBS.items():
        assert C.footage_bundle("FRAMES", None, job)["role"] == role


def test_a_clip_with_no_frames_names_the_loader_that_provides_them():
    with pytest.raises(C.ServiceError) as e:
        C.footage_bundle(None, None, "edit it")
    assert "Load Video (Upload)" in str(e.value)


def test_an_unknown_clip_job_is_refused():
    with pytest.raises(C.ServiceError):
        C.footage_bundle("FRAMES", None, "make it better")


def _setup(**over):
    """A Setup bundle with the five picks a person made, since there is no longer any other kind."""
    fields = dict(server=C.DEFAULT_SERVER,
                  reference_model="minimax_h3_ref2va_pruned_int8_convrot.safetensors",
                  frames_model="minimax_h3_fl2va_pruned_int8_convrot.safetensors",
                  text_encoder="qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors",
                  video_vae="minimax_h3_video_vae_fp16.safetensors",
                  audio_vae="minimax_h3_audio_vae_fp32.safetensors",
                  weight_dtype="default", timeout_s=600)
    return C.setup_bundle(**{**fields, **over})


def test_a_service_address_with_no_scheme_is_refused_before_anything_is_requested():
    with pytest.raises(C.ServiceError) as e:
        _setup(server="127.0.0.1:8420")
    assert "no scheme" in str(e.value) and C.DEFAULT_SERVER in str(e.value)


def test_the_bundle_carries_the_five_picks_and_invents_nothing():
    """THE control on the picker. Every file in the bundle is the file the user chose, unchanged and
    unsubstituted, and there is no field left that could mean anything else."""
    d = _setup()
    assert d["reference_model"] == "minimax_h3_ref2va_pruned_int8_convrot.safetensors"
    assert d["frames_model"] == "minimax_h3_fl2va_pruned_int8_convrot.safetensors"
    assert d["text_encoder"] == "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors"
    assert d["video_vae"] == "minimax_h3_video_vae_fp16.safetensors"
    assert d["audio_vae"] == "minimax_h3_audio_vae_fp32.safetensors"
    assert set(d) == {"server", "reference_model", "frames_model", "text_encoder", "video_vae",
                      "audio_vae", "weight_dtype", "timeout_s"}


def test_a_pick_this_pack_would_once_have_overruled_survives_untouched():
    """The old resolver preferred an int8 build over anything else with the same family word in it,
    which on a Blackwell card is the slower file and was nobody's decision. A pick is a pick."""
    d = _setup(reference_model="MiniMax_H3_Ref2VA_pruned_nvfp4.safetensors")
    assert d["reference_model"] == "MiniMax_H3_Ref2VA_pruned_nvfp4.safetensors"


def test_nothing_in_the_pack_searches_for_a_model_file_by_name():
    """The falsification control for the whole change. Auto-resolution answered a question the node
    could not know the answer to ("which of these did you mean?"), so it is gone rather than
    improved, and this fails if it or its sentinel comes back under any name."""
    import pathlib

    assert not hasattr(C, "resolve_model") and not hasattr(C, "setup_defaults")
    assert not hasattr(C, "AUTO"), "a sentinel meaning 'work it out' is the same guess with a label"
    # Read beside the module under test rather than beside the runner, or a cross-tree pytest run
    # asserts about a copy of the pack nobody edited.
    pack = pathlib.Path(C.__file__).parent
    source = "\n".join((pack / name).read_text(encoding="utf-8")
                       for name in ("nodes.py", "h3ir_client.py"))
    assert "found automatically" not in source
    for gone in ("REFERENCE_PATTERNS", "FRAMES_PATTERNS", "ENCODER_PATTERNS", "VIDEO_VAE_PATTERNS",
                 "AUDIO_VAE_PATTERNS"):
        assert gone not in source, f"{gone} is a table for guessing which file was meant"


# ----------------------------------------------- picking the wrong slot is worth saying out loud

def test_a_reference_checkpoint_in_the_frame_slot_is_warned_about():
    """Both files load. A ref2va checkpoint on a frame job renders something plausible that ignores
    the frames, so the filename's own family word is read back to the user."""
    said = C.family_warning("minimax_h3_ref2va_pruned_int8_convrot.safetensors", frames_job=True)
    assert "ref2va" in said and "fl2va" in said, "name what was picked and what the job wants"
    assert "frame weights" in said, "name the field on the node that fixes it"
    assert "render either way" in said, "it is a warning, not a refusal"


def test_a_frame_checkpoint_in_the_reference_slot_is_warned_about():
    said = C.family_warning("minimax_h3_fl2va_pruned_int8_convrot.safetensors", frames_job=False)
    assert "fl2va" in said and "reference weights" in said


def test_the_right_checkpoint_says_nothing_at_all():
    assert C.family_warning("minimax_h3_ref2va_pruned_int8_convrot.safetensors",
                            frames_job=False) == ""
    assert C.family_warning("MiniMax_H3_FL2VA_Q4_K_M.gguf", frames_job=True) == "", \
        "case is not a family, and the format is not either"


def test_a_filename_that_names_no_family_is_not_guessed_about():
    """THE control on the warning. A renamed or third-party file is not evidence of a mistake, and a
    warning that fires on no evidence teaches people to ignore warnings."""
    for name in ("h3_weights.safetensors", "", "my_favourite_checkpoint.gguf"):
        assert C.family_warning(name, frames_job=True) == ""
        assert C.family_warning(name, frames_job=False) == ""


def test_a_filename_naming_both_families_is_not_read_either():
    assert C.family_warning("minimax_h3_ref2va_and_fl2va_merged.safetensors",
                            frames_job=True) == ""


# --------------------------------------------------------------------------- the file is the format

def test_both_builds_of_a_folder_land_next_to_each_other_in_one_list():
    """`unet_gguf` is not a different place: ComfyUI-GGUF registers it over the same directories with
    a `.gguf` filter, so a checkpoint's two builds sit side by side and the extension is the only
    thing that tells them apart."""
    got = C.merge_model_options(["minimax_h3_ref2va_pruned_int8.safetensors", "Krea2.safetensors"],
                                ["minimax_h3_ref2va_Q4_K_M.gguf"])
    assert got == ["Krea2.safetensors", "minimax_h3_ref2va_pruned_int8.safetensors",
                   "minimax_h3_ref2va_Q4_K_M.gguf"]
    assert got[0] == "Krea2.safetensors", "case-insensitive, or K sorts away from k"


def test_a_file_listed_twice_is_offered_once():
    assert C.merge_model_options(["a.gguf"], ["a.gguf"]) == ["a.gguf"]


def test_the_loader_is_chosen_from_the_extension_per_file():
    assert C.unet_loader_for("m_Q4_K_M.gguf") == "Unet Loader (GGUF)"
    assert C.unet_loader_for("m.safetensors") == "UNETLoader"
    assert C.clip_loader_for("q.GGUF") == "CLIPLoader (GGUF)", "case is not a format"
    assert C.clip_loader_for("q.safetensors") == "CLIPLoader"


def test_a_gguf_checkpoint_and_a_safetensors_encoder_are_both_legal():
    """Separate files with separate loaders, so the combinations are all valid. One boolean would
    either force both or leave the encoder undefined."""
    assert C.is_gguf("weights.gguf") and not C.is_gguf("encoder.safetensors")


def test_both_builds_of_one_file_are_offered_and_neither_is_preferred():
    """The list is what the user chooses from, in one order, with no build promoted over another. The
    old resolver preferred safetensors and reported the GGUF build as an alternative it passed over;
    there is nothing to pass over when the user is the one picking."""
    got = C.merge_model_options(["minimax_h3_ref2va_pruned_int8_convrot.safetensors"],
                                ["minimax_h3_ref2va_Q4_K_M.gguf"])
    assert got == ["minimax_h3_ref2va_pruned_int8_convrot.safetensors",
                   "minimax_h3_ref2va_Q4_K_M.gguf"]
    assert not hasattr(C, "gguf_alternative_note"), \
        "a note about the build that was passed over described a choice nobody makes any more"


def test_the_ignored_precision_note_says_why_it_was_ignored():
    """A setting that silently does nothing is worse than one that is absent."""
    note = " ".join(C.precision_ignored_note().split())
    assert "carries its own quantisation" in note and "it was ignored" in note


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


def test_an_unreachable_service_names_the_command_and_the_node_that_point_elsewhere(monkeypatch):
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
    assert "OpenH3-IR Setup" in msg, \
        "the address left the compile node, so the discovery cost is paid by this message"


def test_a_timeout_points_at_the_node_that_holds_the_knob(monkeypatch):
    import socket as s

    def boom(req, timeout=None):
        raise s.timeout()

    monkeypatch.setattr(C.urllib.request, "urlopen", boom)
    with pytest.raises(C.ServiceError) as e:
        C._request("http://x", "/v1/briefs", payload={}, timeout=30)
    assert "OpenH3-IR Setup" in str(e.value) and "timeout" in str(e.value)


def test_an_unreadable_reference_says_what_is_wrong_and_names_no_field_that_is_gone(monkeypatch):
    """The failure this project will actually generate: ComfyUI on Windows, service in WSL. It used to
    end by naming a widget to fill in, and that widget no longer exists, so the instruction is now
    about the two things a person can actually change."""
    _fake(monkeypatch, (422, {"detail": {"code": "asset-missing",
                                        "message": "no such file: C:\\x\\ref.png"}}))
    with pytest.raises(C.ServiceError) as e:
        C.compile_brief("http://x", {"intent": "a"})
    msg = str(e.value)
    assert "no such file: C:\\x\\ref.png" in msg, "pass the service's own words through"
    assert "different paths" in msg, "say what the failure is"
    assert "another machine" in msg, "the remote case has no fix and must be stated"
    assert "read access" in msg, "and the local case does, so say it"
    assert "as the service sees it" not in msg, \
        "THE control: an instruction to fill in a field nobody can find is worse than no instruction"


def test_a_contradictory_request_lists_the_rules_that_fired(monkeypatch):
    _fake(monkeypatch, (422, {"status": "invalid", "errors": [
        {"rule": "T6-duration", "message": "asked for silence and a score"}]}))
    with pytest.raises(C.ServiceError) as e:
        C.compile_brief("http://x", {"intent": "a"})
    msg = str(e.value)
    assert "T6-duration" in msg and "asked for silence and a score" in msg


def test_a_file_that_opened_and_could_not_be_decoded_is_not_a_path_problem(monkeypatch):
    """The service resolved it, opened it and could not use it. A different spelling would fail the
    same way, so this must not enter the path-retry loop, and the analyser's own sentence, which
    already names the file and what is wrong with it, has to survive."""
    _fake(monkeypatch, (422, {"detail": {
        "code": "asset-unreadable",
        "message": "clip.mp4 is declared kind: video but its bytes are a PNG."}}))
    with pytest.raises(C.ServiceError) as e:
        C.compile_brief("http://x", {"intent": "a"})
    msg = str(e.value)
    assert "declared kind: video but its bytes are a PNG" in msg, "pass the analyser's words through"
    assert "a different path would fail the same way" in msg
    assert C.retranslate(e.value) is False, "THE control: retrying this is three waits for one answer"


def test_a_missing_ffmpeg_is_not_reported_as_a_dead_language_model(monkeypatch):
    """Both are 503. Reading the status alone and printing the LLM message would send someone to fix
    an endpoint that is working, which is the wrong-message failure this pack exists to avoid."""
    _fake(monkeypatch, (503, {"detail": {
        "code": "analysis-tool-missing",
        "message": "ffprobe is not installed, and video references need it. Install ffmpeg."}}))
    with pytest.raises(C.ServiceError) as e:
        C.compile_brief("http://x", {"intent": "a"})
    msg = str(e.value)
    assert "Install ffmpeg" in msg, "the analyser already says what to install"
    assert "H3IR_LLM_URL" not in msg, "do not blame a language model for a missing binary"
    assert "not about your graph" in msg
    assert "text-only prompt still works" in msg, "say what does work"


def test_more_references_than_h3_has_sockets_for_names_the_ceilings(monkeypatch):
    """Refused rather than truncated: ten pictures used to compile to `ready` with a manifest
    publishing <Picture 10> and wiring ref_image_10, a socket that does not exist. Which reference
    matters is the user's call."""
    _fake(monkeypatch, (422, {"detail": {
        "code": "over-capacity", "message": "10 images attached; H3 has 9 image sockets."}}))
    with pytest.raises(C.ServiceError) as e:
        C.compile_brief("http://x", {"intent": "a"})
    msg = str(e.value)
    assert "10 images attached" in msg
    assert "nine pictures, three clips and three standalone sounds" in msg
    assert "Nothing was silently dropped" in msg


def _service_failures() -> set[tuple[int, str]]:
    """Every (status, code) pair `h3ir/service.py` can raise, read out of the service's own source.

    Read rather than listed, so adding a failure over there and no branch over here fails this test
    instead of shipping a caller that shrugs at something it could have explained.
    """
    import pathlib
    import re

    repo = pathlib.Path(__file__).resolve().parents[1]
    src = (repo / "h3ir" / "service.py").read_text()
    found = set(re.findall(r'HTTPException\((\d+),\s*detail=\{\s*\n?\s*"code": "([a-z-]+)"', src))
    found |= set(re.findall(r'HTTPException\((\d+), detail=\{"code": "([a-z-]+)"', src))
    # `except BriefRefused` re-raises the exception's OWN code, so the literal is in compile.py and
    # a scan of service.py alone would miss every one of them. That blind spot is the reason this
    # helper reads two files: `over-capacity` was invisible to the first version of it.
    refusals = re.findall(r'super\(\)\.__init__\("([a-z-]+)"', (repo / "h3ir" / "compile.py").read_text())
    assert refusals, "BriefRefused subclasses stopped declaring literal codes; this scan is now blind"
    return found | {("422", code) for code in refusals}


@pytest.mark.parametrize("status,code", sorted(
    (int(s), c) for s, c in _service_failures()
    # Raised before any request this node makes, or about a brief id it never invents: the node's
    # roles come from a fixed map, it never PATCHes, and it never asks for a brief it was not given.
    if c not in {"unknown-brief", "change-empty", "unknown-role"}))
def test_every_failure_the_service_can_send_gets_a_specific_message(status, code, monkeypatch):
    """A falsification control on the node's error UI as a whole.

    Two ways to fail it, and both have happened in this pack: saying nothing useful, and saying
    something confidently wrong. `analysis-tool-missing` shares its 503 with an LLM outage and used
    to be reported as one, which sent people to fix an endpoint that was working.
    """
    _fake(monkeypatch, (status, {"detail": {"code": code, "message": "SERVICE SAID THIS"}}))
    with pytest.raises(C.ServiceError) as e:
        C.compile_brief("http://x", {"intent": "a"})
    msg = str(e.value)
    assert "the service rejected the request" not in msg, \
        f"{code} reaches the generic branch and the user is told nothing about it"
    assert "SERVICE SAID THIS" in msg, f"{code} discards the message the service wrote"
    if code != "llm-unavailable":
        assert "H3IR_LLM_URL" not in msg, f"{code} is blamed on the language model endpoint"


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


# --------------------------------------------------------------------------- what the report says

def test_the_length_the_user_asked_for_is_printed_when_snapping_moved_it():
    """H3's grid is 17k+5 at 24 fps, so almost every request moves. Silently rendering 10.125 seconds
    for a 10 second script is how a mismatch gets blamed on the model."""
    notes = C.length_notes(10.0, 243)
    assert any("10.0s, snapped up onto the frame grid" in n for n in notes)


def test_a_length_inside_the_trained_band_says_nothing_extra():
    assert C.length_notes(8.0, 192) == [], "8.0 is the one whole second on the grid"


def test_a_long_render_is_reported_as_a_choice_rather_than_a_fault():
    """The range opens past H3's trained band deliberately, so the report carries the fact the
    surface no longer refuses."""
    notes = C.length_notes(20.0, 481)
    text = " ".join(" ".join(n.split()) for n in notes)
    assert "past H3's trained band" in text and "362 frames, 15.083s" in text
    assert "it is untested" in text and "VRAM and time" in text
    assert "note" in notes[-1].split()[0], "a choice belongs in the note register, not as a warning"


def test_a_short_render_is_reported_too():
    notes = C.length_notes(1.0, 39)
    text = " ".join(" ".join(n.split()) for n in notes)
    assert "below H3's trained band" in text and "124 frames, 5.167s" in text


def test_the_report_puts_the_users_own_socket_names_back_on_the_services_labels():
    """The only defence against the plausible-and-wrong case, and it is checkable because both sides
    hash the same bytes: the service's manifest, with the socket each file was plugged into."""
    body = {"mode": "ref2va", "frames": 243, "canvas": [1344, 768], "render_hash": "f" * 64,
            "wiring": [{"label": "<Picture 1>", "wiring": "ref_image_1", "sha256": "a" * 64,
                        "sizing": "match", "retention": "fully_preserved"},
                       {"label": "<Audio 1>", "wiring": "ref_video_audio_1", "sha256": "b" * 64}]}
    text = C.report(body, server="http://x", sizing_conflict=False, asked_seconds=10.0,
                    bindings={"a" * 64: ["picture 1"], "b" * 64: ["clip 1 sound"]})
    assert "picture 1" in text and "<Picture 1>" in text and "ref_image_1" in text
    assert "fully_preserved" in text
    assert "clip 1 sound" in text and "<Audio 1>" in text


def test_the_same_file_on_two_sockets_gets_both_of_its_labels():
    """FOUND BY RENDERING. Files are content-addressed, so plugging one clip into two sockets sends
    one file twice, and a hash-keyed binding map lost the first socket: one label printed as `?`. Both
    sockets are real, and they take their labels in the order the service numbered them."""
    written = [("sound effect", "audio", "/same.wav", {}),
               ("voice to match", "audio", "/same.wav", {})]
    bindings = C.bindings_by_content(written, lambda _p: "s" * 64)
    assert bindings == {"s" * 64: ["sound effect", "voice to match"]}
    body = {"mode": "ref2va", "frames": 192, "canvas": [1344, 768], "wiring": [
        {"label": "<Audio 1>", "wiring": "ref_audio_1", "sha256": "s" * 64, "kind": "audio"},
        {"label": "<Audio 2>", "wiring": "ref_audio_2", "sha256": "s" * 64, "kind": "audio"}]}
    text = C.report(body, server="http://x", sizing_conflict=False, bindings=bindings)
    assert "?" not in text, text
    assert "sound effect" in text and "voice to match" in text
    lines = [ln for ln in text.splitlines() if "<Audio" in ln]
    assert "sound effect" in lines[0] and "voice to match" in lines[1], \
        "in numbering order, so the first socket sent takes the first label"


def test_a_socket_whose_file_never_reached_the_brief_is_still_reported_when_it_shares_a_hash():
    """One of two sockets carrying the same file appearing in the brief, and the other not, is still
    an attachment that was left out."""
    body = {"mode": "ref2va", "frames": 192, "canvas": [1344, 768], "wiring": [
        {"label": "<Audio 1>", "wiring": "ref_audio_1", "sha256": "s" * 64, "kind": "audio"}]}
    text = " ".join(C.report(body, server="http://x", sizing_conflict=False,
                             bindings={"s" * 64: ["music", "voice to match"]}).split())
    assert "does not mention what you plugged into voice to match" in text


def test_a_sound_is_not_labelled_with_a_sizing_it_has_no_use_for():
    """The service's own manifest defaults `sizing` to match on every entry, so printing it for a
    sound reads as a setting somebody chose about a thing that has no pixel area."""
    body = {"mode": "ref2va", "frames": 141, "canvas": [1344, 768], "wiring": [
        {"label": "<Audio 1>", "wiring": "ref_video_audio_1", "sha256": "b" * 64, "kind": "audio",
         "sizing": "match"},
        {"label": "<Video 1>", "wiring": "ref_video_1", "sha256": "a" * 64, "kind": "video",
         "sizing": "match"}]}
    text = C.report(body, server="http://x", sizing_conflict=False,
                    bindings={"a" * 64: "clip 1", "b" * 64: "clip 1 sound"})
    audio_line = next(ln for ln in text.splitlines() if "<Audio 1>" in ln)
    assert "sizing" not in audio_line
    assert "ref_video_audio_1" in audio_line, "the wiring it rides is the fact worth printing"


def test_an_attachment_the_brief_left_out_is_reported_rather_than_dropped():
    """A note on footage used to be discarded in silence. Anything that reached the service and did
    not reach the brief is a fact the user cannot otherwise see."""
    body = {"mode": "ref2va", "frames": 243, "canvas": [1344, 768], "wiring": []}
    text = C.report(body, server="http://x", sizing_conflict=False,
                    bindings={"c" * 64: ["sound effect"]})
    assert "does not mention what you plugged into sound effect" in " ".join(text.split())


def test_one_socket_name_is_not_read_as_five_sockets_called_m_u_s_i_c():
    """A bare string is iterable, so `list("music")` is a list of letters. Accepting either shape
    beats a report that names sockets that do not exist."""
    body = {"mode": "ref2va", "frames": 243, "canvas": [1344, 768], "wiring": []}
    text = " ".join(C.report(body, server="http://x", sizing_conflict=False,
                             bindings={"c" * 64: "music"}).split())
    assert "plugged into music," in text
    assert "plugged into m," not in text


def test_a_label_that_lands_on_no_socket_is_shown_as_unknown_rather_than_guessed():
    body = {"mode": "ref2va", "frames": 243, "canvas": [1344, 768],
            "wiring": [{"label": "<Picture 1>", "wiring": "ref_image_1", "sha256": "z" * 64}]}
    text = C.report(body, server="http://x", sizing_conflict=False, bindings={})
    assert "?" in text and "<Picture 1>" in text


def test_every_report_line_lines_its_facts_up_in_one_column():
    """It is read in a monospace box, and a wrapped sentence whose continuation starts under the
    label reads as a new fact."""
    got = C.line("note", "x " * 80)
    first, second = got.splitlines()[0], got.splitlines()[1]
    assert first.startswith("note") and len(first) <= 94
    assert second.startswith(" " * 15) and second[15] != " "


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


def test_there_is_nothing_to_type_and_no_second_argument_to_type_it_into():
    """The hand-typed override is gone with the field it belonged to. Every spelling that can work is
    a spelling of a folder ComfyUI already named, and the one case a box could not fix is a service on
    another machine, which cannot open these files under any spelling at all."""
    import inspect

    assert list(inspect.signature(C.path_candidates).parameters) == ["comfy_root"]


def test_only_an_unfindable_attachment_is_worth_another_spelling():
    """Retrying anything else would hide a real problem behind repeated attempts, and retrying a
    dead model endpoint three times is three times the wait for the same answer."""
    assert C.retranslate(C.ServiceError("nope", C.PATH_MAY_BE_WRONG)) is True
    assert C.retranslate(C.ServiceError("llm is down")) is False
    assert C.retranslate(ValueError("something else")) is False


def test_the_retry_marker_is_not_named_after_the_one_failure_it_must_not_retry():
    """The service's own code for a file it opened and could not decode is `asset-unreadable`. If the
    retry marker carried that string, the next person to wire the service's code straight into
    `retranslate` would earn three attempts at a corrupt clip for the same answer."""
    assert C.PATH_MAY_BE_WRONG != "asset-unreadable"
    assert C.retranslate(C.ServiceError("corrupt", "asset-unreadable")) is False


def test_the_asset_failure_actually_carries_that_code(monkeypatch):
    """The retry is worthless if the error it looks for is never raised. This is the wire between
    the two."""
    _fake(monkeypatch, (422, {"detail": {"code": "asset-missing", "message": "no such file"}}))
    with pytest.raises(C.ServiceError) as e:
        C.compile_brief("http://x", {"intent": "a"})
    assert C.retranslate(e.value) is True
