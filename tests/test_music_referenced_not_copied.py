"""A track whose style or beat is matched, with none of its signal used. No model and no GPU.

ref-en.txt 2.4 lists five uses for an `<Audio N>` and three of them had a role: copying the signal
(`bgm`), a speaker's timbre and delivery (`voice_timbre`), sound-effect texture (`sfx`). "Referencing
a background-music style" and "Referencing beat, rhythm, or audio continuity" had none, so a caller
who wanted either had to attach the track as `bgm`, whose derived bookkeeping says the signal is
copied -- and the writer then had to contradict the derivation in the right direction, from the
request alone.

Measured on the live service before this, at five seeds each, with the track attached as `bgm`
because there was nothing else to attach it as:

  S6-beat-rhythm  ("Cut the shots on the beat of this track")            fully_copy 5/5
  X9              ("nothing from the recording is used, only a loose      fully_copy 5/5
                   family resemblance")

Both documents shipped `ready`. The X9 one is the sharp case: the request says in as many words that
none of the recording is used and the brief promised H3 it would be the complete final audio track.

Two roles rather than one, because the retention note and the definition line are DERIVED from the
role and the two cases need different true sentences -- a style reference says the score is new music
in that style, a beat reference says the cutting follows the hits. One role could only write a
sentence vague enough to be true of either, and that sentence is what ships when the writer fails.

Three rules, because the recorded failures put the copy claim in three different places: the retention
marker (R22), the task-type prefix (M15) and plain prose in a section no marker rule reads (R27) --
`non_diegetic_music: <Audio 1> is directly reused as the complete audience-only score`.
"""
from __future__ import annotations

import pytest

from h3ir.draft import deterministic_draft
from h3ir.grid import Target
from h3ir.models import AssetCard, AssetKind, AssetRef, Brief, Mode, Role
from h3ir.plan import ProfileOptions, audio_relations, build_manifest, derive_task_types
from h3ir.prose import audio_task_facts
from h3ir.render import render_ir
from h3ir.validate import Context, validate

NEW_ROLES = [Role.MUSIC_STYLE, Role.BEAT_REFERENCE]


def _audio_brief(role: Role, *, note: str = "a steady 120 bpm kick pattern, four to the bar",
                 intent: str = "a bricklayer lays a course, one brick per hit") -> tuple:
    ref = AssetRef(kind=AssetKind.AUDIO, role=role, sha256="aud", seconds=6.0, note=note,
                   role_stated=True)
    cards = {"aud": AssetCard(sha256="aud", kind=AssetKind.AUDIO,
                              summary="a rhythmic reference supplying beat and tempo.",
                              characterisation=note)}
    return Brief(intent=intent, seconds=8.0, assets=[ref]), cards


def _plan(role: Role):
    brief, cards = _audio_brief(role)
    return brief, deterministic_draft(brief, Mode.REF2VA, cards, opts=ProfileOptions())


# ---------------------------------------------------------------- what the wiring derives

@pytest.mark.parametrize("role", NEW_ROLES, ids=[r.value for r in NEW_ROLES])
def test_a_referenced_track_derives_the_reference_marker(role):
    """ref-en.txt 4.2's `reference` row is "only timbre, rhythm, music style, dialogue content, or
    sound texture is referenced" -- a music style and a rhythm are named in it outright."""
    brief, plan = _plan(role)
    assert audio_relations(plan)[0][1] == "reference"


@pytest.mark.parametrize("role", NEW_ROLES, ids=[r.value for r in NEW_ROLES])
def test_a_referenced_track_derives_the_reference_task_type(role):
    """The other half of the same sentence. ref-en.txt 3 defines the two audio types against each
    other, so a marker saying `reference` under a prefix claiming reuse is self-contradictory."""
    brief, plan = _plan(role)
    assert derive_task_types(plan.manifest, brief) == ["audio reference"]
    assert "[audio reference]" in render_ir(plan, ProfileOptions()).prompt


@pytest.mark.parametrize("role", NEW_ROLES, ids=[r.value for r in NEW_ROLES])
def test_the_rendered_lines_say_the_signal_is_not_copied(role):
    """Both lines the role owns. The definition introduces the label and the retention line records
    what survives, and each one has to be true on its own: the draft is what ships when the writer
    fails verification, so a vague note there is what the caller reads."""
    brief, plan = _plan(role)
    text = render_ir(plan, ProfileOptions()).prompt
    assert "without copying the original signal" in text
    assert "fully_copy" not in text and "partially_copy" not in text


def test_the_style_reference_line_says_the_score_is_newly_generated():
    brief, plan = _plan(Role.MUSIC_STYLE)
    text = render_ir(plan, ProfileOptions()).prompt
    assert "<Audio 1> is a music-style reference for the target video's newly generated score" in text
    assert "instrumentation and tempo" in text


def test_the_beat_reference_line_says_the_rhythm_sets_the_cuts():
    brief, plan = _plan(Role.BEAT_REFERENCE)
    text = render_ir(plan, ProfileOptions()).prompt
    assert ("<Audio 1> is a beat reference whose rhythm sets the timing of the target video's cuts "
            "and action" in text)
    assert "beat sets the timing of the cuts and the action" in text


def test_the_caller_s_own_words_reach_the_definition():
    """H3's tokenizer emits `"<Audio j>: "` and never the signal, so this text is the only channel
    the encoder has for what the track is -- and nothing here can hear it."""
    brief, plan = _plan(Role.BEAT_REFERENCE)
    assert "a steady 120 bpm kick pattern, four to the bar" in render_ir(
        plan, ProfileOptions()).prompt


def test_an_uncharacterised_reference_is_still_reported():
    """The role claims a sonic property; with no note nothing states it, and a reference carrying no
    information is worse than useless because it costs rows on every sampling step."""
    from h3ir.compile import wiring_findings

    brief, cards = _audio_brief(Role.BEAT_REFERENCE, note="")
    plan = deterministic_draft(brief, Mode.REF2VA, cards, opts=ProfileOptions())
    plan.manifest[0].characterisation = ""
    rules = {f.rule: f.msg for f in wiring_findings(plan, brief)}
    assert "X15-audio-uncharacterised" in rules
    assert "the beat" in rules["X15-audio-uncharacterised"]


# ---------------------------------------------------------------- the API boundary

@pytest.mark.parametrize("role", NEW_ROLES, ids=[r.value for r in NEW_ROLES])
def test_the_service_accepts_the_role_on_an_audio_asset(role):
    """A role the service rejects is a role no caller can reach. `role_stated` has to come back True
    as well: it is how the rest of the layer tells a caller's declaration from a kind default."""
    from h3ir.service import AssetIn, BriefIn, _to_brief

    brief = _to_brief(BriefIn(intent="cut on the beat", assets=[
        AssetIn(path="docs/media/off-vs-on.mp4", kind="audio", role=role.value,
                note="a steady kick pattern")]))
    assert brief.assets[0].role is role
    assert brief.assets[0].role_stated is True


def test_the_roles_offered_for_a_wav_name_both_new_ones():
    """The 422 lists the roles that fit the kind, and a role missing from that list is invisible."""
    from starlette.testclient import TestClient

    from h3ir import service

    client = TestClient(service.app, raise_server_exceptions=False)
    r = client.post("/v1/briefs", json={
        "intent": "A drum loop drives the cut.",
        "assets": [{"path": "docs/media/off-vs-on.mp4", "kind": "audio", "role": "beat"}]})
    assert r.status_code == 422, r.text
    msg = r.json()["detail"]["message"]
    assert "music_style" in msg and "beat_reference" in msg
    assert "bgm" in msg, "the copy role stays offered beside them"


# ---------------------------------------------------------------- what the writer is told

@pytest.mark.parametrize("role,name,phrase", [
    (Role.MUSIC_STYLE, "a music-style reference", "musical style, instrumentation and tempo"),
    (Role.BEAT_REFERENCE, "a beat reference", "beat and tempo, which set the timing of the cuts"),
], ids=["music_style", "beat_reference"])
def test_the_ask_states_what_the_declared_role_settles(role, name, phrase):
    """The half that stops the fix loop being needed. `video_task_facts` exists for the same reason:
    the writer reads the intent and answers the question it seems to ask, so the fact the wiring holds
    has to be in the ask beside it."""
    fact = audio_task_facts(("<Audio 1>",), ("audio reference",),
                            (("<Audio 1>", role.value),))
    assert phrase in fact
    assert f"<Audio 1> is attached as {name}" in fact
    assert "signal is NOT used in the target video" in fact
    assert "never `fully_copy` or `partially_copy`" in fact


@pytest.mark.parametrize("role", NEW_ROLES, ids=[r.value for r in NEW_ROLES])
def test_the_ask_never_hands_the_writer_the_role_s_own_token(role):
    """Measured on the first live run of this fact: told the role was `beat_reference`, the writer
    wrote "<Audio 1> is the beat_reference for the target video" into subject_definitions. A
    snake_case wiring token is prose H3 was never trained on, and the spec's own line is hyphenated
    English -- "<Audio 1> is the voice-timbre reference for <Subject 1> (S1)"."""
    fact = audio_task_facts(("<Audio 1>",), ("audio reference",), (("<Audio 1>", role.value),))
    assert role.value not in fact


def test_the_ask_forbids_the_prose_claim_in_every_section():
    """Dropping the marker while writing "directly reused as the complete audience-only score" in
    non_diegetic_music satisfies every marker rule and keeps the false promise. That is a sentence a
    recorded run actually shipped."""
    fact = audio_task_facts(("<Audio 1>",), ("audio reference",),
                            (("<Audio 1>", "beat_reference"),))
    assert "not in the summary, the definitions, the description or the music section" in fact
    assert "reused, copied, played" in fact


def test_the_ask_is_built_from_the_wiring_a_real_brief_produces():
    """Not from a hand-written tuple: the fact is only worth stating if it agrees with the manifest
    the app will wire, so it comes off the same two functions the manifest does."""
    brief, _ = _audio_brief(Role.MUSIC_STYLE)
    manifest = build_manifest(brief, Target.build(8.0))
    fact = audio_task_facts(tuple(m.label for m in manifest),
                            tuple(derive_task_types(manifest, brief)),
                            tuple((m.label, m.role.value) for m in manifest))
    assert "<Audio 1> is attached as a music-style reference" in fact
    assert "audio reference" in fact
    assert "music_style" not in fact, "the role's token is a wiring name, not prose (P9)"


def test_a_copy_role_is_told_the_two_copy_markers_apart_instead():
    """`bgm` legitimately copies and nothing pins which marker it takes -- `X4` is right to write
    `fully_copy` and `X10` right to write `partially_copy` for the same role, so only the request can
    decide. What the writer lacked is 4.2's own definition: `S2-copy-part`, whose request lays other
    sound over the top, claimed "reused 1:1 as the target video's complete final audio track" 3/3.
    """
    fact = audio_task_facts(("<Audio 1>",), ("audio reuse",), (("<Audio 1>", "bgm"),))
    assert "with nothing added, removed or laid over it" in fact
    assert "the marker is `partially_copy`" in fact
    assert "signal is NOT used" not in fact, "a copy role must not be told it copies nothing"


def test_an_unnamed_role_gets_no_sentence():
    """Roles with no entry abstain, which is what every caller predating the parameter passes."""
    fact = audio_task_facts(("<Audio 1>",), ("audio reference",), ())
    assert "declared role" not in fact


# ---------------------------------------------------------------- the rules

DEFS = ("subject_definitions:\n<Audio 1> is a beat reference whose rhythm sets the timing of the "
        "target video's cuts and action.\n")
DESC = ("detailed_description:\nThe target video is in live-action style.\n"
        "[Shot 1] The camera holds a static shot as the bricklayer sets a brick on the mortar "
        "line.\n\noverall_soundscape:\nA trowel scrapes and a brick knocks into place.\n\n"
        "non_diegetic_music:\nA newly generated kick pattern keeps the same tempo.\n")


def _doc(*, summary: str = "[reference generation + audio reference] The target video shows a "
         "bricklayer, cut to the beat of <Audio 1>.",
         retention: str = "<Audio 1>: reference - <Audio 1>'s beat sets the timing of the cuts.",
         defs: str = DEFS, desc: str = DESC) -> str:
    return f"{defs}\nsummary:\n{summary}\n\nretention_analysis:\n{retention}\n\n{desc}"


def _errs(text: str, role: str = "beat_reference", **kw) -> dict[str, str]:
    ctx = Context(mode="ref2va", n_pictures=0, n_audios=1, duration_s=8.0,
                  declared_roles=(("<Audio 1>", role, ""),), standalone_audio=("<Audio 1>",), **kw)
    return {f.rule: f.msg for f in validate(text, ctx) if f.severity == "ERROR"}


def test_the_correct_document_is_clean():
    """First, so that the rules below are known to be rejecting the defect and not the shape. A rule
    the right document cannot satisfy is worse than no rule: the fix loop has nowhere to converge."""
    assert not _errs(_doc()), _errs(_doc())


@pytest.mark.parametrize("role", ["music_style", "beat_reference"])
@pytest.mark.parametrize("marker", ["fully_copy", "partially_copy"])
def test_a_copy_marker_on_a_referenced_track_is_an_error(role, marker):
    """R22 had exactly two roles in its set and both new ones belong in it for the reason they
    exist. This is the marker `S6-beat-rhythm` shipped 5 of 5."""
    errs = _errs(_doc(retention=f"<Audio 1>: {marker} - <Audio 1> is reused as the track."),
                 role=role)
    assert "R22-audio-marker-role" in errs, errs
    assert role in errs["R22-audio-marker-role"]


def test_the_prefix_may_not_claim_reuse_when_every_track_is_a_reference():
    """The prefix half, which R22 cannot see. `[reference generation + audio reuse]` is what
    `S6-beat-rhythm` shipped 5 of 5, and M7 only ever fired when NO audio was attached at all."""
    errs = _errs(_doc(summary="[reference generation + audio reuse] The target video shows a "
                              "bricklayer cut to <Audio 1>."))
    assert "M15-audio-reuse-without-a-copy-role" in errs, errs
    assert "audio reference" in errs["M15-audio-reuse-without-a-copy-role"]
    assert "ref-en.txt 3" in errs["M15-audio-reuse-without-a-copy-role"]


def test_one_copied_track_alongside_makes_the_reuse_claim_correct_again():
    """The rule reads the wiring, so a mixed brief -- one track copied, another referenced for its
    beat -- is exactly the case where both types belong. ref-en.txt 3 combines them with ` + `."""
    text = _doc(defs=DEFS.rstrip("\n") + "\n<Audio 2> is the synchronized audio track, providing "
                "the background music.\n",
                summary="[reference generation + audio reuse + audio reference] The target video "
                        "shows a bricklayer cut to <Audio 1> over <Audio 2>.",
                retention="<Audio 1>: reference - <Audio 1>'s beat sets the timing of the cuts.\n"
                          "<Audio 2>: partially_copy - the background music is kept under the new "
                          "mix.",
                desc=DESC.replace("on the mortar line", "on the mortar line while <Audio 2> plays"))
    ctx = Context(mode="ref2va", n_pictures=0, n_audios=2, duration_s=8.0,
                  declared_roles=(("<Audio 1>", "beat_reference", ""), ("<Audio 2>", "bgm", "")),
                  standalone_audio=("<Audio 1>", "<Audio 2>"))
    errs = [f for f in validate(text, ctx) if f.severity == "ERROR"]
    assert not errs, [str(f) for f in errs]


def test_with_no_declared_role_the_rules_abstain():
    """What the golden controls and the independent validator pass. An empty `declared_roles` means
    "nobody said", never "nothing is referenced" -- the same distinction R21 was corrected for."""
    text = _doc(summary="[reference generation + audio reuse] The target video shows a bricklayer "
                        "cut to <Audio 1>.",
                retention="<Audio 1>: fully_copy - <Audio 1> is reused 1:1 as the target video's "
                          "complete final audio track.")
    errs = {f.rule for f in validate(text, Context(mode="ref2va", n_pictures=0, n_audios=1,
                                                   duration_s=8.0)) if f.severity == "ERROR"}
    assert "M15-audio-reuse-without-a-copy-role" not in errs, errs
    assert "R27-reference-audio-claimed-as-copied" not in errs, errs


def test_prose_calling_the_referenced_track_reused_is_an_error():
    """The third place the claim appeared, in a section no marker rule reads. Recorded verbatim:
    `non_diegetic_music: <Audio 1> is directly reused as the complete audience-only score`."""
    errs = _errs(_doc(desc=DESC.replace("A newly generated kick pattern keeps the same tempo.",
                                        "<Audio 1> is directly reused as the complete "
                                        "audience-only score.")))
    assert "R27-reference-audio-claimed-as-copied" in errs, errs
    assert "beat and tempo" in errs["R27-reference-audio-claimed-as-copied"]


def test_the_prose_rule_reads_the_whole_document_and_not_one_section():
    """The same sentence in subject_definitions has to be caught too, or the rule only covers the
    place the last failure happened to put it."""
    errs = _errs(_doc(defs="subject_definitions:\n<Audio 1> is played as the target video's "
                           "soundtrack.\n"))
    assert "R27-reference-audio-claimed-as-copied" in errs, errs


def test_a_property_being_reused_is_not_a_copy_claim():
    """The false positive the rule is anchored to avoid. "The tempo of <Audio 1> is reused in the new
    score" is a property being referenced, which is exactly what the role licenses, and a rule that
    rejected it would be fighting correct output."""
    errs = _errs(_doc(desc=DESC.replace(
        "A newly generated kick pattern keeps the same tempo.",
        "The tempo of <Audio 1> is reused in a newly generated kick pattern.")))
    assert "R27-reference-audio-claimed-as-copied" not in errs, errs


def test_saying_the_signal_is_not_copied_is_not_a_copy_claim():
    """The negated form, which is the wording the role's own retention note uses. A rule that fired
    on "<Audio 1> is not copied" would reject every correct document."""
    errs = _errs(_doc(retention="<Audio 1>: reference - <Audio 1> is not copied; only its beat and "
                                "tempo set the timing of the cuts."))
    assert "R27-reference-audio-claimed-as-copied" not in errs, errs


def test_the_role_s_own_token_written_as_prose_is_reported():
    """The sentence a live run actually shipped, verbatim. WARN rather than ERROR: the fix belongs in
    the ask, and spending a correction round on a hyphen risks losing the written brief over
    cosmetics. It is a rule so that a regression in the ask is visible instead of silent."""
    text = _doc(defs="subject_definitions:\n<Audio 1> is the beat_reference for the target video, "
                     "providing the tempo that dictates the timing of the cuts.\n")
    ctx = Context(mode="ref2va", n_pictures=0, n_audios=1, duration_s=8.0,
                  declared_roles=(("<Audio 1>", "beat_reference", ""),),
                  standalone_audio=("<Audio 1>",))
    found = {f.rule: f for f in validate(text, ctx)}
    assert "P9-role-token-in-prose" in found
    assert found["P9-role-token-in-prose"].severity == "WARN"
    assert "write it in words" in found["P9-role-token-in-prose"].msg
    assert "a beat reference" in found["P9-role-token-in-prose"].msg, "hand over the replacement"


def test_the_words_a_brief_needs_are_not_treated_as_tokens():
    """`subject`, `style` and `environment` are role values AND ordinary English. The rule reads only
    the underscore-bearing tokens, which is what makes it free of false positives -- and the spec's
    own snake_case marker vocabulary (`fully_copy`) is deliberately outside the set."""
    from h3ir.validate import ROLE_TOKENS_NEVER_IN_PROSE

    assert "subject" not in ROLE_TOKENS_NEVER_IN_PROSE
    assert "style" not in ROLE_TOKENS_NEVER_IN_PROSE
    assert "bgm" not in ROLE_TOKENS_NEVER_IN_PROSE, "no underscore, and never seen in prose"
    assert "beat_reference" in ROLE_TOKENS_NEVER_IN_PROSE
    text = _doc(defs="subject_definitions:\n<Audio 1> is a beat reference for the target video; the "
                     "subject, the environment and the style all follow the request.\n")
    ctx = Context(mode="ref2va", n_pictures=0, n_audios=1, duration_s=8.0,
                  declared_roles=(("<Audio 1>", "beat_reference", ""),),
                  standalone_audio=("<Audio 1>",))
    assert "P9-role-token-in-prose" not in {f.rule for f in validate(text, ctx)}


def test_a_marker_is_not_a_wiring_token():
    """`fully_copy` is snake_case and is the spec's own vocabulary, so a correct copy document must
    not trip the rule. This is the false positive that would have made P9 unusable."""
    text = _doc(defs="subject_definitions:\n<Audio 1> is the synchronized audio track, providing "
                     "the background music.\n",
                summary="[audio reuse] The target video shows a ferry with <Audio 1> as its audio.",
                retention="<Audio 1>: fully_copy - <Audio 1> is reused 1:1 as the target video's "
                          "complete final audio track.")
    ctx = Context(mode="ref2va", n_pictures=0, n_audios=1, duration_s=8.0,
                  declared_roles=(("<Audio 1>", "bgm", ""),), standalone_audio=("<Audio 1>",))
    assert "P9-role-token-in-prose" not in {f.rule for f in validate(text, ctx)}


def test_a_copied_track_may_still_say_it_is_reused():
    """The narrowness, stated as a test. `bgm` copies, so none of the three rules may touch it --
    `X4`'s `fully_copy` and "reused 1:1 as the target video's complete final audio track" is correct
    output for a request that asks for exactly that."""
    text = _doc(defs="subject_definitions:\n<Audio 1> is the synchronized audio track, providing "
                     "the background music.\n",
                summary="[audio reuse] The target video shows a ferry leaving a jetty with "
                        "<Audio 1> as its complete audio.",
                retention="<Audio 1>: fully_copy - <Audio 1> is reused 1:1 as the target video's "
                          "complete final audio track.",
                desc=DESC.replace("A newly generated kick pattern keeps the same tempo.",
                                  "<Audio 1> is reused as the complete audience-only score."))
    errs = _errs(text, role="bgm")
    assert not errs, errs
