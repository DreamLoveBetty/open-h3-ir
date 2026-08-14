"""Two things the guides state about writing and nothing acted on.

base-en.txt 4.7, about `non_diegetic_music`: "Focus on instrumentation, speed, rhythm, and dynamic
changes; do not use abstract mood words or explain the emotional function of the score." 25 of 167
music sections in the corpus carried one, and the only rule in the area (`A5-music-no-tempo`, INFO)
checks the opposite thing.

ref-en.txt 5.2: "For generation tasks, `detailed_description` is normally 350-500 English words."
Of the 103 ready, written, non-editing ref2va documents in the corpus, 3 landed in the band: minimum
74, median 218, maximum 570. `P2-too-short` fired on 90 of them and nothing downstream acted on it.

The 300-word floor at WARN stays exactly as it is, and the reasoning above it in validate.py stays
true: MiniMax's own published Ref2VA example is 336 words, so a hard gate at 350 would reject the
spec's own artifact, and length correlates with quality in neither direction. What the measurement
adds is that this is not an argument about the last 50 words. A median of 218 against a stated 350 is
the writer not being asked, and the ask is where that is fixed.
"""
from __future__ import annotations

from h3ir.draft import deterministic_draft
from h3ir.models import AssetCard, AssetKind, AssetRef, Brief, Mode, Role
from h3ir.plan import ProfileOptions
from h3ir.prose import compose_brief
from h3ir.validate import Context, validate


def _doc(music: str) -> str:
    return ("integrated_multimodal_description: [Shot 1] Live-action, cinematic, a busker plays in "
            "a tunnel. The camera pushes in with small amplitude at slow speed.\n\n"
            "overall_soundscape: A train passes behind her and the echo fades.\n\n"
            f"non_diegetic_music: {music}\n")


def _found(music: str):
    return validate(_doc(music), Context(mode="t2va", n_pictures=0, duration_s=8.0))


# ---------------------------------------------------------------- the score's own words

def test_an_abstract_mood_word_in_the_score_is_reported():
    """`out/*.json`, verbatim: "A sparse, melancholic piano melody at a slow tempo, with soft string
    pads"."""
    found = [f for f in _found("A sparse, melancholic piano melody at a slow tempo, with soft "
                               "string pads underneath.")
             if f.rule == "A8-music-mood-word"]
    assert found and found[0].severity == "WARN", found
    assert "melancholic" in found[0].msg


def test_explaining_the_emotional_function_is_reported():
    """The second half of the sentence, and the other shape it arrived in: "A minimal, atmospheric
    electronic score with a slow tempo ... creating a sleek and modern mood."."""
    found = [f for f in _found("A minimal electronic score at a slow tempo, creating a sleek and "
                              "modern mood.")
             if f.rule == "A8-music-mood-word"]
    assert found, [str(f) for f in _found("x")]


def test_instrumentation_tempo_and_dynamics_pass():
    """base-en.txt 4.7's own example, and ref-en.txt 6's. A rule that fired on either is wrong."""
    for music in ("Sparse piano notes at a slow tempo, joined by sustained low strings that "
                  "gradually increase in volume before fading out.",
                  "A restrained solo-piano score at a slow tempo, with sustained low cello "
                  "underneath and no swell."):
        found = [f for f in _found(music) if f.rule == "A8-music-mood-word"]
        assert not found, (music, [str(f) for f in found])


def test_na_is_not_a_mood_word():
    assert not [f for f in _found("N/A") if f.rule == "A8-music-mood-word"]


def test_the_soundscape_is_not_policed_for_mood_words():
    """4.7's sentence is about the score. `overall_soundscape` is physical sound and is governed by
    4.6, which says nothing of the kind, so the rule must not leak into it."""
    text = _doc("N/A").replace("A train passes behind her and the echo fades.",
                               "A train passes with an ominous rumble and the echo fades.")
    found = [f for f in validate(text, Context(mode="t2va", n_pictures=0, duration_s=8.0))
             if f.rule == "A8-music-mood-word"]
    assert not found, [str(f) for f in found]


def test_the_spec_written_examples_are_clean():
    from pathlib import Path
    golden = Path(__file__).resolve().parents[1] / "h3ir/golden"
    for name, ctx in (("t2va.ir.txt", Context(mode="t2va", n_pictures=0, duration_s=10.125)),
                      ("official_ref2va_example.txt",
                       Context(mode="ref2va", n_pictures=4, n_videos=2, n_audios=1))):
        found = [f for f in validate((golden / name).read_text(encoding="utf-8"), ctx)
                 if f.rule == "A8-music-mood-word"]
        assert not found, (name, [str(f) for f in found])


def test_minimaxs_own_hosted_i2va_ir_breaks_its_own_rule_and_that_is_why_this_is_a_warn():
    """Recorded rather than exempted, because it decides the severity.

    `i2va.ir.txt` is one of the three published hosted IRs saved verbatim, and its score reads "A
    gentle, heartwarming acoustic guitar melody ... a slow, comforting tempo that enhances the cozy,
    nostalgic, and joyful atmosphere of the family gathering." That is three mood words and an
    explanation of the score's emotional function, from MiniMax's own rewriter, against base-en.txt
    4.7's explicit prohibition.

    So the guide disagrees with the artifact, exactly as it does over P5 and the 350-word floor, and
    an ERROR here would reject the hosted service's own output. The control's contract for these three
    files is zero ERRORs with WARNs expected, and this stays inside it.
    """
    from pathlib import Path
    golden = Path(__file__).resolve().parents[1] / "h3ir/golden/i2va.ir.txt"
    found = validate(golden.read_text(encoding="utf-8"),
                     Context(mode="i2va", n_pictures=1, duration_s=8.0))
    hits = [f for f in found if f.rule == "A8-music-mood-word"]
    assert hits and hits[0].severity == "WARN", [str(f) for f in found]
    assert not [f for f in found if f.severity == "ERROR"], [str(f) for f in found]


# ---------------------------------------------------------------- the length, asked for

class _Capture:
    class _Cfg:
        model = "capture"
    cfg = _Cfg()

    class _Reply:
        content = "subject_definitions:\n"

    def __init__(self) -> None:
        self.asks: list[str] = []

    def chat(self, messages, **kw):
        c = messages[-1]["content"]
        self.asks.append(c if isinstance(c, str) else c[0]["text"])
        return self._Reply()


def _ask(mode: Mode, *, role: Role = Role.SUBJECT, kind: AssetKind = AssetKind.IMAGE) -> str:
    ref = AssetRef(kind=kind, role=role, sha256="plate", px=(1024, 576), note="the black car")
    cards = {"plate": AssetCard(sha256="plate", kind=kind, style="Live-action, cinematic",
                                summary="a black car",
                                subjects=[{"kind": "object", "descriptor": "the black car",
                                           "attributes": ["carbon fibre body"]}])}
    brief = Brief(intent="Put this car on a wet dock road at night.", seconds=8.0, assets=[ref])
    plan = deterministic_draft(brief, mode, cards, opts=ProfileOptions())
    backend = _Capture()
    compose_brief(backend, brief, plan.subjects, cards, plan.target,
                  tuple(m.label for m in plan.manifest),
                  prompt_name=("compose.v2.txt" if mode is Mode.REF2VA
                               else "compose_base.v1.txt"),
                  mode=mode, task_types=tuple(plan.task_types),
                  generation_task="video editing" not in plan.task_types)
    return backend.asks[0]


def test_a_reference_generation_ask_states_the_word_band():
    ask = _ask(Mode.REF2VA)
    assert "350" in ask and "500" in ask, ask
    assert "detailed_description" in ask


def test_the_ask_says_where_the_words_come_from():
    """Asking for length without saying how to reach it is how a brief gets padded. The spec's own
    answer is observation: "clearly establish the current composition, subject appearance and
    position, environment and lighting, actions and state changes, camera movement, current sound"."""
    ask = _ask(Mode.REF2VA)
    assert "observ" in ask.lower() or "in the frame" in ask.lower(), ask
    assert "pad" in ask.lower(), "the failure mode has to be named, or length gets filled with air"


def test_a_base_mode_is_not_given_the_band():
    """The 350-500 range is stated for ref2va `detailed_description` only. MiniMax's own published
    T2VA is 251 words, so handing the range to a base mode would push it away from the spec's own
    artifact -- the same reason P2 is scoped to ref2va."""
    ask = _ask(Mode.I2VA, role=Role.FRAME_ANCHOR_FIRST)
    assert "350" not in ask, ask


def test_an_editing_task_is_not_given_the_band():
    """ref-en.txt 5.2 exempts them: "Video-editing descriptions scale with the complexity of the
    source video and do not have to follow the generation-task range." The validator already scopes
    P2 the same way, off the same fact."""
    ask = _ask(Mode.REF2VA, role=Role.EDIT_SOURCE, kind=AssetKind.VIDEO)
    assert "350" not in ask, ask
