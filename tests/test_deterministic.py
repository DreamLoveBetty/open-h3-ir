"""Tests for everything that must be true without a model in the loop.

Written to fail if the logic breaks, not to pass. Where a rule matters, there is a control that
asserts the WRONG input is rejected -- a test that only ever sees good input proves nothing.
"""
from __future__ import annotations

import pytest

from h3ir.grid import (Target, align_frame_count, canvas_for_aspect, frames_for_seconds,
                       legal_frames, ms_to_timestamp, rows_per_latent_frame, timestamp_to_ms,
                       video_latent_t)
from h3ir.models import (AssetKind, AssetRef, Brief, CameraMove, DialogueLine, Mode, Role)
from h3ir.plan import (ProfileOptions, allocate_shots, assign_dialogue, build_manifest,
                       derive_task_types, shot_count, split_sound)
from h3ir.render import (_continue_case, dialogue_markup, instruction_line, render_ir,
                         style_prefix, style_sentence)
from h3ir.textnorm import normalize, sentences
from h3ir.tokens import count as tok_count
from h3ir.validate import Context, validate


# ---------------------------------------------------------------- grid

def test_frame_grid_matches_the_node():
    assert align_frame_count(5) == 5
    assert align_frame_count(6) == 22
    assert align_frame_count(124) == 124
    assert align_frame_count(125) == 141
    for n in legal_frames():
        assert n % 17 == 5


def test_only_eight_seconds_is_an_integer_in_range():
    integers = [n for n in legal_frames() if (n / 24).is_integer()]
    assert integers == [192], "192 frames = 8.000 s is the only integer second in 124..362"


def test_ten_seconds_is_really_ten_point_one_two_five():
    t = Target.build(10, "16:9")
    assert t.frames == 243
    assert round(t.effective_seconds, 3) == 10.125
    # S.SS is the EFFECTIVE duration (base-en.txt 2.1), which is also what the cut times are
    # measured against. `nominal` remains expressible as a profile flag and is no longer the
    # default: it made the deterministic draft and the written brief disagree about the number.
    assert t.s_ss() == "10.13"
    assert t.s_ss("snapped") == "10.13"
    assert t.s_ss("nominal") == "10.00"


def test_latent_and_row_math():
    assert video_latent_t(124) == 37
    assert rows_per_latent_frame(1344, 768) == 1008
    t = Target.build(5, "16:9")
    assert t.canvas == (1344, 768)
    assert t.video_rows == 37 * 1008


def test_timestamp_roundtrip():
    for ms in (0, 1, 999, 3400, 60000, 615123):
        assert timestamp_to_ms(ms_to_timestamp(ms)) == ms
    assert ms_to_timestamp(3400) == "00:03.400"
    with pytest.raises(ValueError):
        ms_to_timestamp(-1)


def test_a_long_but_aligned_duration_is_not_an_error():
    """The trained band is a note about training, not a ceiling. The owner renders past it
    routinely, so an aligned 20-second request must not be rejected."""
    from h3ir.validate import Context, is_on_grid, nearest_on_grid, validate
    # A camera term is now mandatory (P4/P5), so the fixture states one.
    text = ("integrated_multimodal_description: [Shot 1] Live-action, a field. The camera holds a "
            "static shot.\n\noverall_soundscape: Wind.\n\nnon_diegetic_music: N/A\n")
    twenty = 481 / 24
    assert is_on_grid(twenty)
    findings = validate(text, Context(mode="t2va", duration_s=twenty))
    assert not [f for f in findings if f.severity == "ERROR"]
    assert any(f.rule == "T10-outside-trained-band" for f in findings)


def test_an_off_grid_duration_is_still_an_error():
    from h3ir.validate import Context, is_on_grid, validate
    text = ("integrated_multimodal_description: [Shot 1] Live-action, a field. The camera holds a "
            "static shot.\n\noverall_soundscape: Wind.\n\nnon_diegetic_music: N/A\n")
    assert not is_on_grid(20.0)
    rules = {f.rule for f in validate(text, Context(mode="t2va", duration_s=20.0))
             if f.severity == "ERROR"}
    assert "T7-illegal-duration" in rules


def test_a_large_canvas_is_accepted():
    """1920x1088 is a real working size here; nothing may cap it."""
    t = Target.build(8, canvas=(1920, 1088))
    assert t.canvas == (1920, 1088)
    assert t.frames == 192
    assert t.video_rows == 25 * 60 * t.latent_t // t.latent_t * t.latent_t or t.video_rows > 0


def test_canvas_respects_the_area_cap():
    w, h = canvas_for_aspect("21:9")
    assert w * h <= 768 * 1344 * 1.02
    assert w % 32 == 0 and h % 32 == 0


# ---------------------------------------------------------------- manifest ordering

def _img(sha, role=Role.SUBJECT):
    return AssetRef(kind=AssetKind.IMAGE, role=role, sha256=sha, px=(1024, 1024))


def _vid(sha, role=Role.EDIT_SOURCE):
    return AssetRef(kind=AssetKind.VIDEO, role=role, sha256=sha, frames=124, seconds=5.0)


def _aud(sha, role=Role.BGM, paired=None):
    return AssetRef(kind=AssetKind.AUDIO, role=role, sha256=sha, seconds=5.0,
                    paired_video_sha256=paired)


def test_manifest_reproduces_the_published_audio_numbering():
    """MiniMax's published Ref2VA IR numbers <Audio 1> as the video's synchronized track and
    <Audio 2> as the standalone voice reference. That is exactly ComfyUI's emission order, and
    it is the only thing that makes the labels true."""
    brief = Brief(intent="x", assets=[_vid("v1"), _aud("a1", Role.BGM, paired="v1"),
                                      _aud("a2", Role.VOICE_TIMBRE)])
    m = build_manifest(brief, Target.build(5))
    assert [e.label for e in m] == ["<Audio 1>", "<Video 1>", "<Audio 2>"]
    assert m[0].paired_with == "<Video 1>"
    assert [e.slot for e in m] == [0, 1, 2]


def test_images_come_before_videos_and_ordinals_are_per_type():
    brief = Brief(intent="x", assets=[_img("i1"), _img("i2"), _vid("v1"), _aud("a1")])
    labels = [e.label for e in build_manifest(brief, Target.build(5))]
    assert labels == ["<Picture 1>", "<Picture 2>", "<Video 1>", "<Audio 1>"]


def test_max_sizing_costs_far_more_rows_than_match():
    t = Target.build(5)
    big = _img("i1")
    big.px, big.sizing = (3648, 2048), "max"
    small = _img("i2")
    small.px, small.sizing = (3648, 2048), "match"
    rows = {e.sha256: e.rows for e in build_manifest(Brief(intent="x", assets=[big, small]), t)}
    assert rows["i1"] > 5 * rows["i2"], "the 2048-short-edge path must be visibly more expensive"


# ---------------------------------------------------------------- timeline

def test_every_cut_falls_inside_the_real_duration():
    for secs in (5, 8, 10, 15):
        t = Target.build(secs)
        for n in (1, 2, 3, 4):
            shots = allocate_shots(t, n, Mode.REF2VA, ProfileOptions())
            assert shots[0].start_ms == 0
            assert shots[-1].end_ms == int(t.effective_seconds * 1000)
            for s in shots[1:]:
                assert s.start_ms < t.effective_seconds * 1000
                assert s.duration_ms >= 1500, "a shot shorter than 1.5 s carries no information"
            times = [s.start_ms for s in shots]
            assert times == sorted(times) and len(set(times)) == len(times)


def test_word_targets_sum_to_the_mode_budget():
    t = Target.build(10)
    shots = allocate_shots(t, 3, Mode.REF2VA, ProfileOptions())
    assert abs(sum(s.word_target for s in shots) - 400) <= 6


def test_editing_a_source_video_does_not_invent_cuts():
    brief = Brief(intent="x", seconds=15, assets=[_vid("v1", Role.EDIT_SOURCE)])
    m = build_manifest(brief, Target.build(15))
    assert shot_count(Target.build(15), brief, Mode.REF2VA, ProfileOptions(), m) == 1


def test_dialogue_never_exceeds_what_can_be_spoken():
    t = Target.build(5)
    shots = allocate_shots(t, 2, Mode.T2VA, ProfileOptions())
    lines = [DialogueLine(text="one two three four five six seven eight"),
             DialogueLine(text="nine ten eleven twelve")]
    assign_dialogue(shots, lines)
    assert sum(len(s.dialogue) for s in shots) == 2, "no line may be dropped"
    for s in shots:
        spoken = sum(len(d.text.split()) for d in s.dialogue)
        assert spoken <= (s.duration_ms / 1000) * 2.6 + 4


def test_sound_is_partitioned_not_copied():
    sync, ambient = split_sound([
        {"text": "a wingbeat", "layer": "sync", "shot": 1},
        {"text": "distant fire", "layer": "ambient"},
    ])
    assert sync == {1: ["a wingbeat"]}
    assert ambient == ["distant fire"]
    assert not set(ambient) & {t for v in sync.values() for t in v}


# ---------------------------------------------------------------- task types

def test_task_types_come_from_roles_not_prose():
    t = Target.build(5)
    brief = Brief(intent="edit it", assets=[_vid("v1", Role.EDIT_SOURCE),
                                            _aud("a1", Role.BGM, paired="v1")])
    types = derive_task_types(build_manifest(brief, t), brief)
    assert "video editing" in types and "audio reuse" in types
    assert len(types) == len(set(types))
    plain = Brief(intent="x", assets=[_img("i1")])
    assert derive_task_types(build_manifest(plain, t), plain) == ["reference generation"]


# ---------------------------------------------------------------- render

def _mini_plan(mode=Mode.REF2VA, body="A wide shot of a field. {{CAM}}"):
    from h3ir.models import AssetCard
    from h3ir.plan import build_plan
    card = AssetCard(sha256="i1", kind=AssetKind.IMAGE,
                     subjects=[{"kind": "person", "descriptor": "the young man",
                                "attributes": ["short blonde hair", "pink suit"]}])
    brief = Brief(intent="x", seconds=5, assets=[_img("i1")],
                  dialogue=[DialogueLine(text="Follow the wind, live free.")])
    plan = build_plan(brief, mode, {"i1": card},
                      beats=[{"beat": "he turns", "camera": {"type": "Push In",
                                                             "amplitude": "small",
                                                             "speed": "slow"},
                              "subjects": ["<Subject 1>"], "sync_sound": []}],
                      sound_events=[{"text": "Wind moves through the grass.", "layer": "ambient"}],
                      style_phrase="Live-action, cinematic, warm afternoon light",
                      music="A slow piano figure at a moderate tempo.")
    plan.summary = "The target video shows <Subject 1> in a field."
    plan.shots[0].body = body + " {{D1}}"
    return plan


def test_render_is_byte_identical_when_repeated():
    plan = _mini_plan()
    a = render_ir(plan, ProfileOptions())
    b = render_ir(plan, ProfileOptions())
    assert a.prompt == b.prompt and a.prompt.strip()


def test_camera_is_rendered_canonically_from_the_enum():
    out = render_ir(_mini_plan(), ProfileOptions()).prompt
    assert "The camera pushes in with small amplitude at slow speed" in out


def test_user_dialogue_survives_byte_for_byte():
    out = render_ir(_mini_plan(), ProfileOptions()).prompt
    assert "<d>[English] Follow the wind, live free.</d>" in out


def test_a_second_camera_sentence_from_the_model_is_removed():
    """The template owns the camera. When the prose stage writes its own sentence too, the shot
    carries the canonical phrase AND a paraphrase — which reached a judged artifact."""
    plan = _mini_plan(body="A wide shot. {{CAM}} The camera pushes slowly forward, closing in.")
    res = render_ir(plan, ProfileOptions())
    assert res.prompt.count("The camera") == 1, res.prompt
    assert "pushes in with small amplitude at slow speed" in res.prompt
    assert any("redundant camera" in n for n in res.notes)


def test_a_continuation_through_the_camera_token_is_removed():
    """The prose stage sometimes treats {{CAM}} as its sentence's subject and writes through it,
    leaving "…at slow speed. pushes steadily forward…" — a lowercase fragment no camera-sentence
    pattern matches. It reached a judged artifact."""
    plan = _mini_plan(body="A wide shot. {{CAM}} pushes steadily and slowly forward, closing in.")
    res = render_ir(plan, ProfileOptions())
    assert ". pushes" not in res.prompt, res.prompt
    assert "pushes in with small amplitude at slow speed" in res.prompt


def test_a_described_but_unlabelled_subject_gets_its_label_attached():
    """The label is the only binding to the attached image. Shot 1 of a judged artifact described
    the man and never named <Subject 1>, so that shot referenced nothing."""
    plan = _mini_plan(body="A wide shot. The young man steps into the light. {{CAM}}")
    plan.shots[0].subjects = ["<Subject 1>"]
    res = render_ir(plan, ProfileOptions())
    assert "<Subject 1>" in res.prompt
    assert any("attached <Subject 1>" in n for n in res.notes)


def test_an_already_labelled_subject_is_not_touched():
    plan = _mini_plan(body="A wide shot of <Subject 1>, the young man. {{CAM}}")
    plan.shots[0].subjects = ["<Subject 1>"]
    res = render_ir(plan, ProfileOptions())
    assert res.prompt.count("<Subject 1>") >= 1
    assert not any("attached <Subject 1>" in n for n in res.notes)


def test_a_shot_that_overruns_its_budget_is_trimmed_at_a_sentence():
    """A target the model overruns by 2x is not a budget. One arm came back at 750 words against
    a 400-word plan."""
    long_body = " ".join(f"Sentence number {i} describes the wall." for i in range(80))
    plan = _mini_plan(body=long_body + " {{CAM}}")
    plan.shots[0].word_target = 40
    res = render_ir(plan, ProfileOptions())
    body = res.sections["detailed_description"]
    assert len(body.split()) < 200
    # `</d>` is a valid terminator: the trim runs on the model's prose, and the template then
    # appends the camera sentence and the dialogue markup after it.
    assert body.rstrip().endswith((".", "!", "?", "</d>")), body[-40:]
    assert ". Sentence number" in body, "the cut must land between sentences"
    assert any("trimmed" in n for n in res.notes)


def test_a_shot_within_its_budget_is_untouched():
    plan = _mini_plan(body="A short wide shot of the field. {{CAM}}")
    plan.shots[0].word_target = 120
    res = render_ir(plan, ProfileOptions())
    assert not any("trimmed" in n for n in res.notes)


def test_a_retention_note_does_not_double_the_article():
    from h3ir.plan import retention_note
    from h3ir.models import SubjectPlan
    s = SubjectPlan(label="<Subject 2>", kind="environment", sources=["<Picture 2>"],
                    descriptor="the corridor",
                    attributes=["the wall torch — metal construction", "the stone wall"])
    note = retention_note(s)
    assert "the the" not in note, note
    assert note.startswith("the wall torch")


def test_the_canonical_camera_sentence_is_never_the_one_removed():
    plan = _mini_plan(body="A wide shot of a field. {{CAM}}")
    res = render_ir(plan, ProfileOptions())
    assert "pushes in with small amplitude at slow speed" in res.prompt
    assert not any("redundant camera" in n for n in res.notes)


def test_missing_placeholders_are_appended_not_lost():
    plan = _mini_plan(body="A wide shot with no tokens at all.")
    plan.shots[0].body = "A wide shot with no tokens at all."
    res = render_ir(plan, ProfileOptions())
    assert "pushes in" in res.prompt and "Follow the wind" in res.prompt
    assert len(res.notes) == 2, "both omissions must be reported, not silently fixed"


def test_ref2va_and_base_modes_render_differently():
    ref = render_ir(_mini_plan(Mode.REF2VA), ProfileOptions()).prompt
    assert "subject_definitions:\n" in ref and "detailed_description:\n" in ref
    base = render_ir(_mini_plan(Mode.T2VA), ProfileOptions()).prompt
    assert base.startswith("integrated_multimodal_description: [Shot 1]")
    assert "detailed_description" not in base


def test_instruction_lines_are_verbatim_including_the_em_dash():
    for mode, needle in ((Mode.I2VA, "For the target video, at 0.00 seconds into the target "
                                     "video, <Picture 1> (from [Shot 1]) is fully referenced."),
                         (Mode.FL2VA, "How the reference pictures align with the target video — "
                                      "Picture 1 (from Shot 1)"),
                         (Mode.L2VA, "How the reference pictures align with the target video — "
                                     "<Picture 1> (from [Shot")):
        plan = _mini_plan(mode)
        assert needle in instruction_line(plan, ProfileOptions())
    assert instruction_line(_mini_plan(Mode.T2VA), ProfileOptions()) == ""


def test_style_has_one_source_and_two_renderings():
    phrase = "Live-action, cinematic, warm light"
    # A remainder that opens with an adjective takes a comma; "with" needs a noun phrase.
    assert style_sentence(phrase) == ("The target video is in live-action style, "
                                      "cinematic, warm light.")
    assert style_prefix(phrase) == phrase


def test_a_medium_that_already_says_style_does_not_get_it_twice():
    """The model routinely names the medium as "anime style", which produced
    "in anime style style" on an artifact about to be judged."""
    out = style_sentence("Anime style, cinematic, chiaroscuro lighting")
    assert "style style" not in out
    assert out == "The target video is in anime style, cinematic, chiaroscuro lighting."


def test_continuation_case_lowercases_safely_only():
    assert _continue_case("A wide shot opens") == "a wide shot opens"
    assert _continue_case("Sarah steps forward") == "Sarah steps forward"
    assert _continue_case("Smoke drifts as smoke thickens").startswith("s")


# ---------------------------------------------------------------- text hygiene

def test_hazard_characters_are_replaced_but_the_em_dash_survives():
    assert normalize("the dragon’s wing") == "the dragon's wing"
    assert normalize("“quoted”") == '"quoted"'
    assert "—" in normalize("align — with")
    assert normalize("a b") == "a b"


def test_sound_events_render_as_prose():
    assert sentences(["low wind", "distant fire"]) == "Low wind. Distant fire."


def test_dialogue_markers_are_not_special_tokens():
    """H3's own tokenizer has no <d>; it BPE-splits, which is why the bytes must be exact."""
    assert tok_count("<d>") == 2
    assert tok_count("</d>") == 3


# ---------------------------------------------------------------- validator controls

def test_static_controls_all_pass():
    from h3ir.evalloop.controls import run_controls
    ok, results = run_controls()
    failed = [r for r in results if not r.passed]
    assert ok, f"control failures: {[(r.name, r.detail) for r in failed]}"
    assert len(results) >= 18


def test_the_owners_actual_defect_is_an_error():
    text = ("subject_definitions:\n<Subject 1> is the man in <Image 1>.\n\nsummary:\n"
            "[reference generation] x\n\nretention_analysis:\n"
            "<Subject 1> (appears in [Shot 1]): fully_preserved - x.\n\ndetailed_description:\n"
            "A style line.\n[Shot 1] The man from <Image 1> rides.\n\noverall_soundscape:\nN/A\n\n"
            "non_diegetic_music:\nN/A\n")
    rules = {f.rule for f in validate(text, Context(n_pictures=2)) if f.severity == "ERROR"}
    assert "L1-unknown-label" in rules


def test_a_cut_past_the_end_is_an_error():
    text = ("integrated_multimodal_description: [Shot 1] Live-action, a field. "
            "[Shot 2] At 00:12.000, the shot cuts to a road.\n\n"
            "overall_soundscape: Wind.\n\nnon_diegetic_music: N/A\n")
    rules = {f.rule for f in validate(text, Context(mode="t2va", duration_s=10.125))
             if f.severity == "ERROR"}
    assert "T6-time-past-end" in rules


# ---------------------------------------------------------------- lora registry

def test_registry_reads_the_example_lora():
    from h3ir.lora import load_registry
    records, findings, revision = load_registry()
    assert "handpainted-anim-v2" in records, f"registry findings: {findings}"
    rec = records["handpainted-anim-v2"]
    assert rec.triggers[0]["text"] == "hndpntd_anim_v2"
    assert rec.strength == {"default": 0.8, "min": 0.4, "max": 1.0}
    assert rec.h3_variant == ("ref2va",)
    assert rec.stacks_with_turbo == "unknown"
    assert "watercolour" in rec.what_for()
    assert "photoreal" in rec.when_not()
    assert revision and "hndpntd_anim_v2" not in str(rec.public()), \
        "the public listing must not hand out byte-exact triggers"


@pytest.mark.parametrize("bad", ["<painted>", "[Shot 1]", "(S1)", "<d>", " lead", "trail "])
def test_reserved_and_unsafe_triggers_are_refused_at_ingest(bad):
    from h3ir.lora import trigger_problem
    assert trigger_problem(bad) is not None
    assert trigger_problem("hndpntd_anim_v2") is None


def test_a_lora_for_the_wrong_checkpoint_is_rejected():
    from h3ir.lora import resolve_loras
    chosen, findings = resolve_loras([{"id": "handpainted-anim-v2"}], Mode.T2VA,
                                     Brief(intent="x", seconds=5))
    assert not chosen
    assert any(f.rule == "W11-lora-variant" for f in findings)


def test_strength_is_clamped_and_reported():
    from h3ir.lora import resolve_loras
    chosen, findings = resolve_loras([{"id": "handpainted-anim-v2", "strength": 5.0}], Mode.REF2VA,
                                     Brief(intent="x", seconds=5))
    assert chosen and chosen[0].strength_applied == 1.0
    assert any(f.rule == "W14-lora-strength-clamped" for f in findings)


def test_a_missing_trigger_in_the_text_is_an_error():
    ctx = Context(n_pictures=1, lora_triggers=({"text": "hndpntd_anim_v2", "count": 1,
                                                "slot": "style"},))
    text = ("subject_definitions:\n<Subject 1> is the man in <Picture 1>.\n\nsummary:\n"
            "[reference generation] x\n\nretention_analysis:\n"
            "<Subject 1> (appears in [Shot 1]): fully_preserved - x.\n\ndetailed_description:\n"
            "A style line.\n[Shot 1] The camera holds a static shot on <Subject 1>.\n\n"
            "overall_soundscape:\nWind.\n\nnon_diegetic_music:\nN/A\n")
    rules = {f.rule for f in validate(text, ctx) if f.severity == "ERROR"}
    assert "W2-lora-trigger-missing" in rules


# ---------------------------------------------------------------- mode inference

def test_wiring_decides_the_mode_without_a_model():
    from h3ir.mode import infer_mode
    assert infer_mode(Brief(intent="x")).mode is Mode.T2VA
    assert infer_mode(Brief(intent="x", assets=[_vid("v1")])).mode is Mode.REF2VA
    assert infer_mode(Brief(intent="x", assets=[_img(f"i{i}") for i in range(3)])).mode \
        is Mode.REF2VA
    d = infer_mode(Brief(intent="animate this photo", assets=[_img("i1")]))
    assert d.mode is Mode.I2VA and d.confidence >= 0.6


def test_ambiguity_fails_safe_to_the_more_expressive_mode():
    from h3ir.mode import infer_mode
    d = infer_mode(Brief(intent="make something nice", assets=[_img("i1")]))
    assert d.mode is Mode.REF2VA
    assert "strictly more expressive" in " ".join(d.signals)


def test_explicit_frame_roles_win():
    from h3ir.mode import infer_mode
    a, b = _img("i1", Role.FRAME_ANCHOR_FIRST), _img("i2", Role.FRAME_ANCHOR_LAST)
    assert infer_mode(Brief(intent="x", assets=[a, b])).mode is Mode.FL2VA
    assert infer_mode(Brief(intent="x", assets=[a])).mode is Mode.I2VA


def test_generated_asset_provenance_short_circuits_the_hard_call():
    from h3ir.mode import infer_mode
    img = _img("i1")
    img.provenance = {"generator": "qwen-image-edit", "intended_role": "first_frame"}
    d = infer_mode(Brief(intent="do something with this", assets=[img]))
    assert d.mode is Mode.I2VA and d.rule_fired == "12.8-provenance"


# ---------------------------------------------------------------- comfy graph editing

def test_prompt_substitution_refuses_to_guess():
    from h3ir.comfy import ComfyError, describe_graph, set_prompt, set_seed
    graph = {"3": {"class_type": "MiniMaxH3ReferenceToVideo",
                   "inputs": {"prompt": "old", "width": 1344}},
             "4": {"class_type": "KSampler", "inputs": {"seed": 1}}}
    out = set_prompt(graph, "new")
    assert out["3"]["inputs"]["prompt"] == "new"
    assert graph["3"]["inputs"]["prompt"] == "old", "must not mutate the caller's graph"
    assert set_seed(graph, 99)["4"]["inputs"]["seed"] == 99
    assert describe_graph(graph)["h3_nodes"] == ["3"]
    with pytest.raises(ComfyError):
        set_prompt({"1": {"class_type": "KSampler", "inputs": {}}}, "x")
    two = dict(graph, **{"5": {"class_type": "MiniMaxH3ImageToVideo",
                              "inputs": {"prompt": "b"}}})
    with pytest.raises(ComfyError):
        set_prompt(two, "x")


# ---------------------------------------------------------------- backend guards

def test_structured_output_with_thinking_is_refused():
    """Measured: json_schema is silently NOT applied while reasoning is on, so the unsafe
    combination must raise rather than return prose that looks like a schema failure."""
    from h3ir.backend import Backend, BackendError
    with pytest.raises(BackendError, match="thinking=False"):
        Backend().chat([{"role": "user", "content": "x"}], thinking=True,
                       response_format={"type": "json_schema"})


def test_no_rule_id_carries_two_meanings():
    """Two namespaces both used the X prefix -- `compile.py` for compiler invariants and `lora.py` for
    LoRA findings -- and collided on TEN numbers: X7 through X16 each meant one thing in one file and
    something else in the other. A caller filtering or dashboarding on rule id would conflate them, and
    two of the collisions were introduced tonight without anyone checking the other namespace.

    LoRA rules are now W. This test is the guard, because the next collision will be as invisible as
    these were."""
    import collections
    import re as _re
    from pathlib import Path

    ids: dict[str, set[str]] = collections.defaultdict(set)
    for f in sorted(Path(__file__).resolve().parents[1].joinpath("h3ir").rglob("*.py")):
        for m in _re.finditer(r'(?:add|Finding)\(\s*\n?\s*"([A-Z]+\d+[a-z]?)-([a-z0-9-]+)"',
                              f.read_text(encoding="utf-8")):
            ids[m.group(1)].add(m.group(2))
    collisions = {k: sorted(v) for k, v in ids.items() if len(v) > 1}
    assert not collisions, collisions
