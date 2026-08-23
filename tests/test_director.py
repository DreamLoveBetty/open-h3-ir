"""The director profile: what ships, what the writer is told, and what a profile can never reach.

A profile is now prose, so most of what this file used to prove has no code left to prove it
against. What replaces it is sharper, because the owner's shape moved the question. It is no longer
"does the checker refuse the words" -- there is no checker -- it is **"is the STRUCTURE actually
uninfluenced"**, which is rule 1 and is a fact about the compiler rather than about a regex.

Every claim here is FALSIFIED rather than asserted: each test breaks the thing it covers on purpose
and watches it go red, with the untouched case as the control. That is the distinction AGENTS.md
draws between a test and a comment.
"""
from dataclasses import replace

import pytest

from h3ir import director as D
from h3ir.creativity import MAGNITUDE, Creativity
from h3ir.draft import deterministic_draft, draft_camera
from h3ir.models import AssetKind, Brief, Mode
from h3ir.plan import ProfileOptions


# --------------------------------------------------------------------------- what ships

def test_every_shipped_profile_is_usable():
    """A shipped profile can never be broken; this is the same check a caller's own meets."""
    for d in D.DIRECTORS:
        assert D.check(d) == [], f"{d.id}: {D.check(d)}"
        assert d.notes.strip() and d.name.strip()
        assert not D.is_empty(d)


def test_the_set_is_not_secretly_one_profile():
    """Seven texts that say the same thing would be one control with seven labels."""
    assert len({d.notes for d in D.DIRECTORS}) == len(D.DIRECTORS)
    assert len({d.id for d in D.DIRECTORS}) == len(D.DIRECTORS)


# The owner's constraint, and it is about OUR writing rather than the caller's: "without doing
# example shots btw, otherwise the model is just gonna output those". There is no checker in the
# code any more -- a profile is steered, not enforced -- so the seven texts every user starts from
# and edits are held to it here, which is the only place it can honestly live.
@pytest.mark.parametrize("d", list(D.DIRECTORS), ids=[d.id for d in D.DIRECTORS])
def test_no_shipped_profile_shows_the_model_a_shot(d):
    import re
    assert not re.search(r"\[\s*Shot\b|\bShot\s+\d", d.notes), "a shot label is structure (rule 1)"
    assert not re.search(r"\b\d{1,2}:\d{2}", d.notes), "a cut time is computed, never written"
    assert not re.search(r"</?d>|</?scenetrans>|</?cutoff>", d.notes), "render.py emits the tags"
    assert not re.search(r"<\s*(?:Subject|Picture|Video|Audio)\s*\d*\s*>", d.notes), \
        "labels are assigned per request by the runtime"
    assert not re.search(r'"[^"]{25,}"', d.notes), "a quoted sample line is an example shot"
    assert not re.search(r"\b\d+\s+shots?\b|\bshot count\b|\bcuts? every\b", d.notes), \
        "shot count is the caller's contract or the planner's, never a profile's"


@pytest.mark.parametrize("d", list(D.DIRECTORS), ids=[d.id for d in D.DIRECTORS])
def test_a_shipped_profile_names_moves_h3_actually_knows(d):
    """H3's motion table is closed and off-vocabulary wording measurably under-uses the strongest
    lever it has. The vocabulary is no longer a schema, so what keeps it correct is that the seven
    texts use it -- and never teach a word from the neighbouring film vocabulary that H3 has no
    entry for."""
    named = [m for m in D.CAMERA_MOVES if m in d.notes]
    assert len(named) >= 5, f"{d.id} names only {named}"
    for stranger in ("dolly", "steadicam", "crane shot", "whip pan", "dutch angle", "snap zoom",
                     "locked-off", "drone shot"):
        assert stranger not in d.notes.lower(), f"{d.id} teaches {stranger!r}, which H3 has no move for"


def test_the_published_vocabulary_is_the_compilers_own():
    """`CAMERA_MOVES` exists so a surface can show somebody writing their own profile what H3 knows
    by name. A second, drifting list would teach a word the renderer has no entry for."""
    from h3ir.models import CAMERA_TYPES
    assert D.CAMERA_MOVES == CAMERA_TYPES


def test_the_shipped_seven_between_them_reach_most_of_the_table():
    """Not all of it, and the gap is honest: the two rolls are avoided by every director in the set,
    so they are named as a group rather than by name. That is what the panel's own list is for."""
    used = {m for d in D.DIRECTORS for m in D.CAMERA_MOVES if m in d.notes}
    assert set(D.CAMERA_MOVES) - used == {"Roll Clockwise", "Roll Counterclockwise"}


# --------------------------------------------------------------------------- what the writer reads

def test_the_block_carries_the_callers_words_and_says_it_yields():
    d = D.from_mapping({"name": "Bleak motel", "notes": "Sodium light on wet asphalt."})
    block = D.brief_instruction(d)
    assert "Sodium light on wet asphalt." in block
    assert "overrides neither of them" in block
    assert "do not copy these sentences into it" in block


def test_the_name_never_reaches_the_writer():
    """"Without doing example shots btw, otherwise the model is just gonna output those." A name is
    the shortest path to that failure, so it goes to the report and no further."""
    d = D.from_mapping({"name": "Ridley Scott", "notes": "Sodium light on wet asphalt."})
    assert "Ridley Scott" not in D.brief_instruction(d)
    assert "Ridley Scott" in D.note(d)


def test_the_ask_says_so_when_no_music_can_exist():
    """A profile describing music the dial will not license is a contradiction WE placed in the ask,
    and `Scope.brief_instruction`'s docstring records what that costs. The caller's words are never
    edited; a sentence that outranks them is added above."""
    d = D.BY_ID["cameron"]
    assert "gets no music" not in D.brief_instruction(d, scored=True)
    assert "gets no music" in D.brief_instruction(d, scored=False)
    # and the words themselves survive either way, because they are the caller's
    assert "full orchestra" in D.brief_instruction(d, scored=False)


# --------------------------------------------------------------------------- taking one in

def test_a_profile_survives_the_round_trip():
    d = D.from_mapping({"name": "Neon", "notes": "Sodium on wet asphalt.\nThe camera holds."})
    assert D.check(d) == []
    assert D.from_mapping(D.to_mapping(d)) == d
    assert d.origin == "custom" and d.id == "custom"


def test_an_unnamed_profile_is_named_rather_than_refused():
    """The name is what the REPORT calls it and changes no output, so refusing a paragraph somebody
    wrote over a blank label would be a refusal for our own bookkeeping."""
    d = D.from_mapping({"notes": "Sodium on wet asphalt."})
    assert d.name == "Custom" and D.check(d) == []


def test_an_empty_profile_is_inert_rather_than_invalid():
    """The difference decides whether the caller gets a refusal or a note. A node dropped in and
    left blank is somebody who has not written it yet."""
    assert D.is_empty(D.from_mapping({"name": "Nothing"}))
    assert D.check(D.from_mapping({"name": "Nothing"})) == []
    assert not D.is_empty(D.from_mapping({"notes": "Very dry room."}))


def test_the_one_cap_refuses_with_the_number_in_the_sentence():
    """The only refusal left, and it is about how much there is rather than what it says: every
    character rides in the ask on every call."""
    ok = D.from_mapping({"name": "Long", "notes": "x" * D.MAX_NOTES_CHARS})
    assert D.check(ok) == []
    too_long = replace(ok, notes="x" * (D.MAX_NOTES_CHARS + 1))
    problems = D.check(too_long)
    assert len(problems) == 1 and str(D.MAX_NOTES_CHARS) in problems[0]


def test_an_unknown_id_is_named_rather_than_silently_dropped():
    """A shipped profile can stop existing between two versions, and a saved script naming it must
    not quietly compile with no direction at all. `fincher` shipped in no release and was cut before
    one; the next one removed will be named by somebody's script."""
    assert D.unknown("wong") is None
    assert D.unknown("") is None and D.unknown("none") is None and D.unknown("custom") is None
    assert D.unknown("fincher") == "fincher"


def test_an_unknown_id_falls_back_to_the_direction_that_came_with_the_request():
    """Falling back to nothing would throw away prose the caller sent in the same payload."""
    mine = D.from_mapping({"name": "Mine", "notes": "Sodium."})
    assert D.parse("wong") is D.BY_ID["wong"]
    assert D.parse("wong", mine) is D.BY_ID["wong"]       # a named id still wins
    assert D.parse("fincher", mine) is mine
    assert D.parse("", mine) is mine
    assert D.parse("") is None and D.parse("none") is None


# --------------------------------------------------------------------------- the floor, untouched
#
# This is the half of rule 1 that a prose profile has to earn rather than assert, and it is why
# `draft_camera` lost its `director` argument. An earlier version narrowed the deterministic
# rotation to a profile's own camera vocabulary, which meant a profile mechanically decided a
# structural field in the floor. The owner settled the shape the other way: steered, not enforced.

def test_the_deterministic_floor_is_byte_identical_with_and_without_direction():
    """The strongest structural check available with no model: the same request, once bare and once
    with a profile loud enough to matter, must produce the same plan."""
    def plan_for(profile):
        b = Brief(intent="a man walks a corridor", seconds=8.0,
                  director_profile=profile)
        return deterministic_draft(b, Mode.T2VA, {}, opts=ProfileOptions())

    loud = {"name": "Loud", "notes": (
        "Cut every two seconds and use exactly three shots. Static Shot only, never move. "
        "Shoot it as hand-drawn animation.")}
    bare, steered = plan_for(None), plan_for(loud)
    assert len(bare.shots) == len(steered.shots)
    assert [s.camera.type for s in bare.shots] == [s.camera.type for s in steered.shots]
    assert [(s.start_ms, s.end_ms) for s in bare.shots] == \
           [(s.start_ms, s.end_ms) for s in steered.shots]
    assert bare.style_phrase == steered.style_phrase


@pytest.mark.parametrize("level", list(Creativity))
def test_the_dial_still_reaches_the_floor(level):
    """The control: the floor is not simply deaf. The dial is a setting with an enforced meaning at
    both ends, and at `maximal` Q3 needs `with large amplitude` and `at fast speed` to survive or the
    compile raises. If this passed while the test above also passed for the wrong reason, both would
    be reading a rotation nothing writes."""
    rotation = draft_camera(MAGNITUDE[level])
    assert rotation
    if MAGNITUDE[level] == "maximal":
        assert any(c.get("amplitude") == "large" for c in rotation)
        assert any(c.get("speed") == "fast" for c in rotation)
    assert draft_camera("maximal") != draft_camera("plain")


# --------------------------------------------------------------------------- the ask, in order

class CapturingBackend:
    """Captures the ask and returns a reply the caller will discard. Not a stub of the compiler:
    the ask under test is built by the real `compose_brief` from a real plan."""

    def __init__(self) -> None:
        self.asks: list[str] = []

    class _Cfg:
        model = "capture"

    class _Reply:
        content = "integrated_multimodal_description: [Shot 1] ...\n"

    cfg = _Cfg()

    def chat(self, messages, **kw):
        c = messages[-1]["content"]
        self.asks.append(c if isinstance(c, str) else c[0]["text"])
        return self._Reply()


def _ask(intent: str, *, notes: str, shots: int | None = None, plate: bool = False) -> str:
    """The real `compose_brief`, driven by a real plan, with the ask captured. Nothing hand-written.

    `plate` attaches one reference picture, because the licence block is emitted only when something
    is actually reference-governed -- with nothing attached there is no ladder to state.
    """
    from h3ir.compile import _director, _scope
    from h3ir.licence import resolve_licence
    from h3ir.models import AssetCard, AssetRef, Role
    from h3ir.prose import compose_brief

    assets, cards = [], {}
    if plate:
        assets = [AssetRef(kind=AssetKind.IMAGE, role=Role.SUBJECT, sha256="plate",
                           px=(1024, 576), note="the black supercar")]
        cards = {"plate": AssetCard(sha256="plate", kind=AssetKind.IMAGE,
                                    style="Live-action, cinematic",
                                    summary="a black supercar in a dark showroom",
                                    subjects=[{"kind": "object",
                                               "descriptor": "the black supercar"}])}
    brief = Brief(intent=intent, seconds=8.0, shots=shots, assets=assets,
                  director_profile={"name": "Mine", "notes": notes})
    plan = deterministic_draft(brief, Mode.REF2VA, cards, opts=ProfileOptions())
    director, _ = _director(brief)
    backend = CapturingBackend()
    compose_brief(backend, brief, plan.subjects, cards, plan.target,
                  tuple(m.label for m in plan.manifest),
                  mode=Mode.REF2VA, licence=resolve_licence(brief, cards),
                  scope=_scope(brief, plan), director=director)
    return backend.asks[0]


def test_the_licence_block_states_the_ladder_above_the_direction():
    """The computed half of the ladder never lived in director.py: `licence.py` resolves each
    attribute and `compose_brief` states the resolution. The profile has to read UNDER that, or the
    strongest sentence in the ask is a taste and the computed one trails it."""
    ask = _ask("a man walks a corridor", notes="Sodium light on wet asphalt.",
               plate=True)
    assert "Direction." in ask and "Sodium light on wet asphalt." in ask
    assert ask.index("Direction.") > ask.index("Creativity:"), \
        "the dial states absolute prohibitions and must come first"
    assert ask.index("Direction.") > ask.index("Anything neither the request nor the references"), \
        "the licence block resolves each attribute and the profile fills what it leaves"


def test_direction_cannot_move_a_shot_count_the_caller_pinned():
    """Rule 1, and the answer the creativity dial already gives. A pinned count is the caller's
    contract: it is stated in the ask and T11-shot-count-pinned is an ERROR if the document
    disagrees. A profile is prose in the same ask and reaches neither."""
    ask = _ask("a man walks a corridor", shots=2,
               notes="Cut every two seconds and use exactly three shots.")
    assert "exactly 2 shot(s)" in ask and "exactly 2 [Shot N] blocks" in ask
    assert "three shots" in ask       # the caller's own words are not edited, only outranked
    # the pin is not merely stated: it is enforced on the artifact
    assert any(f.rule == "T11-shot-count-pinned" and f.severity == "ERROR"
               for f in _t11_probe())


def _t11_probe():
    """The rule fires on a document with the wrong number of shots against a pinned count.

    Written as a probe rather than trusted from the source, because "the rule exists" and "the rule
    fires" are two different facts and only the second one is worth a test.
    """
    from h3ir.validate import Context, validate
    doc = ("integrated_multimodal_description: [Shot 1] A man walks down a corridor.\n"
           "overall_soundscape: footsteps on concrete.\n")
    return validate(doc, Context(mode="t2va", pinned_shots=3))


def test_a_profile_that_asks_for_a_medium_does_not_get_one():
    """`licence.py`'s settled rule is that the reference plate governs the medium unless the REQUEST
    asks for a transformation, and a profile is not a request. Nothing refuses the words now, so
    what has to hold is that the STYLE PHRASE the compiler resolves is unmoved by them."""
    from h3ir.style import resolve_style
    bare = Brief(intent="a man walks a corridor", seconds=8.0)
    steered = Brief(intent="a man walks a corridor", seconds=8.0,
                    director_profile={"name": "Mine",
                                      "notes": "Shoot it as hand-drawn cel animation."})
    assert resolve_style(bare, {}).phrase == resolve_style(steered, {}).phrase


# --------------------------------------------------------------------------- the record

def test_the_record_names_the_profile_that_was_used():
    """Two fields that must agree is the check this project has found four silent faults with. The
    node compares what it sent against this line."""
    assert D.note(None) == "director: none"
    assert D.note(D.BY_ID["wong"]) == "director: Wong Kar-wai"
    assert D.note(D.from_mapping({"name": "Bleak motel", "notes": "x"})) == "director: Bleak motel"


def test_a_profile_too_long_to_send_is_refused_at_intake_not_truncated():
    """Truncating somebody's direction and compiling anyway is the silent degradation this service
    refuses everywhere else."""
    from h3ir.compile import BriefRefused, _director
    brief = Brief(intent="a man walks", seconds=8.0,
                  director_profile={"name": "Long", "notes": "x" * (D.MAX_NOTES_CHARS + 1)})
    with pytest.raises(BriefRefused) as e:
        _director(brief)
    assert str(D.MAX_NOTES_CHARS) in str(e.value)
    # the control: one character shorter and it compiles
    ok = Brief(intent="a man walks", seconds=8.0,
               director_profile={"name": "Long", "notes": "x" * D.MAX_NOTES_CHARS})
    assert _director(ok)[0] is not None


def test_direction_with_nothing_written_is_reported_rather_than_applied():
    from h3ir.compile import _director
    brief = Brief(intent="a man walks", seconds=8.0,
                  director_profile={"name": "Mine", "notes": "   "})
    director, findings = _director(brief)
    assert director is None
    assert [f.rule for f in findings] == ["N1-director-empty"]
    assert findings[0].severity == "WARN"
