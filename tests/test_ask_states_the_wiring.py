"""What the writer is TOLD, checked by capturing the real ask. No model and no GPU.

Two modes degraded at a high, reproducible rate on rules that were not wrong:

  i2va, one anchor image, 3 of 7 degraded, always `L2-undefined-subject` plus `L4-unused-media`.
  The writer used `<Subject 1>`, defined it inline, and never cited `<Picture 1>`.

  ref2va, one image, 3 of 7 degraded (4 of 7 with anchor wording in the request), always
  `R10-mode-role-contamination`. The writer wrote "<Picture 1> is the first frame of [Shot 1]".

Neither is the model being careless. In the i2va case the ask handed it `<Subject 1> is the black
car in <Picture 1>` -- a definition line for a format with no subject_definitions section, while
that mode's own system prompt says subject labels do not exist here. In the ref2va case the system
prompt is the spec, and the spec teaches the standalone `<Picture N>` line for a picture that IS a
frame; nothing said which case this was.

Both are facts the wiring holds and the ask did not state. So these tests capture the ask a real
brief produces and assert the facts are in it. Nothing here hand-writes an ask.
"""
from __future__ import annotations

import pytest

from h3ir.compile import compile_brief
from h3ir.draft import deterministic_draft
from h3ir.models import AssetCard, AssetKind, AssetRef, Brief, Mode, Role
from h3ir.plan import ProfileOptions
from h3ir.prose import compose_brief


class CapturingBackend:
    """Captures the ask and returns a reply the caller will discard. Not a stub of the compiler:
    the ask under test is built by the real `compose_brief` from a real plan."""

    def __init__(self) -> None:
        self.asks: list[str] = []

    class _Cfg:
        model = "capture"

    cfg = _Cfg()

    class _Reply:
        content = "integrated_multimodal_description: [Shot 1] ...\n"

    def chat(self, messages, **kw):
        self.asks.append(messages[-1]["content"] if isinstance(messages[-1]["content"], str)
                         else messages[-1]["content"][0]["text"])
        return self._Reply()


def _plate(role: Role, sha: str = "plate") -> tuple[AssetRef, dict[str, AssetCard]]:
    ref = AssetRef(kind=AssetKind.IMAGE, role=role, sha256=sha, px=(1024, 576),
                   note="the black supercar")
    card = AssetCard(sha256=sha, kind=AssetKind.IMAGE, style="Live-action, cinematic",
                     summary="a black supercar in a dark showroom",
                     subjects=[{"kind": "object", "descriptor": "the black supercar",
                                "attributes": ["carbon fibre body", "orange underglow"]}])
    return ref, {sha: card}


def _ask(mode: Mode, role: Role, intent: str) -> str:
    """One real compose call, with the model replaced by a capture. The plan, the labels, the
    picture roles and the task types all come from the same code the service runs."""
    ref, cards = _plate(role)
    brief = Brief(intent=intent, seconds=5.0, assets=[ref])
    plan = deterministic_draft(brief, mode, cards, opts=ProfileOptions())
    backend = CapturingBackend()
    compose_brief(backend, brief, plan.subjects, cards, plan.target,
                  tuple(m.label for m in plan.manifest),
                  prompt_name=("compose.v2.txt" if mode is Mode.REF2VA else "compose_base.v1.txt"),
                  mode=mode, task_types=tuple(plan.task_types),
                  picture_roles=tuple((m.label, m.role.value) for m in plan.manifest
                                      if m.kind is AssetKind.IMAGE))
    return backend.asks[0]


# ---------------------------------------------------------------- base modes: no subject labels

def test_a_base_mode_is_never_handed_a_subject_definition_line():
    """The cause of L2 in i2va. `<Subject 1> is ...` is a sentence with nowhere to live in a
    three-section document, and a fact sheet that looks like output gets used as output."""
    import re

    ask = _ask(Mode.I2VA, Role.FRAME_ANCHOR_FIRST, "Animate this photo: the car pulls forward.")
    # `<Subject N>` appears once, in the sentence forbidding it. A NUMBERED one does not appear at
    # all: that is the shape the model copied into a document with nowhere to put it.
    assert not re.search(r"<Subject\s+\d+>", ask), ask


def test_a_base_mode_is_told_the_label_does_not_exist_in_its_format():
    ask = _ask(Mode.I2VA, Role.FRAME_ANCHOR_FIRST, "Animate this photo: the car pulls forward.")
    assert "NO subject_definitions section" in ask
    assert "`<Subject N>` does not exist in it" in ask


def test_a_base_mode_is_told_to_cite_the_picture():
    """The other half of the pair: L4 fired because `<Picture 1>` was never named at all."""
    ask = _ask(Mode.I2VA, Role.FRAME_ANCHOR_FIRST, "Animate this photo: the car pulls forward.")
    assert "Cite each picture above by its label" in ask
    assert "costs rows on every sampling step" in ask


def test_the_first_frame_anchor_is_stated_as_the_first_frame():
    ask = _ask(Mode.I2VA, Role.FRAME_ANCHOR_FIRST, "Animate this photo: the car pulls forward.")
    assert "<Picture 1> IS the target video's first frame, at 0.00 seconds" in ask
    assert "shows the black supercar (carbon fibre body, orange underglow)" in ask


def test_the_last_frame_anchor_is_stated_as_the_last_frame():
    """l2va's picture is the END. The spec is explicit that it does not belong to [Shot 1], and a
    fact sheet that got this backwards would be worse than none."""
    ask = _ask(Mode.L2VA, Role.FRAME_ANCHOR_LAST, "End on this photo of the car.")
    assert "IS the target video's last frame" in ask
    assert "does not belong to [Shot 1]" in ask


def test_a_base_mode_is_not_told_about_task_types_it_does_not_have():
    """A three-section document has no summary and no task-type prefix, so instructions about the
    prefix are noise at best and a push toward the other format at worst."""
    ask = _ask(Mode.I2VA, Role.FRAME_ANCHOR_FIRST, "Animate this photo: the car pulls forward.")
    assert "task-type prefix" not in ask
    assert "audio reuse" not in ask


# ---------------------------------------------------------------- ref2va: not a frame

def test_a_reference_brief_is_told_its_pictures_are_not_frames():
    """The cause of R10. The rule is right -- this checkpoint has no exact-frame mechanism, which is
    also why an anchor role arriving here is downgraded with X10 -- and the model had no way to know
    which case it was in, because the spec in its system prompt teaches both."""
    ask = _ask(Mode.REF2VA, Role.SUBJECT, "Put this car in a night race through a tunnel.")
    assert "None of the pictures here is a frame of the target video." in ask
    assert "is the first frame of" in ask, "the forbidden phrase is quoted so it is unmistakable"
    assert "never claim `keyframe completion`" in ask


def test_the_statement_is_read_off_the_wiring_and_not_asserted():
    """If a picture really does carry an anchor role, saying "none of these is a frame" would be a
    lie. ref2va downgrades anchor roles before this point, so the wiring is the honest source."""
    from h3ir.prose import reference_picture_facts

    assert reference_picture_facts((("<Picture 1>", "subject"),))
    assert reference_picture_facts((("<Picture 1>", "frame_anchor_first"),)) == ""


def test_a_reference_brief_still_gets_its_definition_lines():
    """The ref2va path is unchanged where it was right: the definition lines are the format's own
    shape and the model is meant to use or reword them."""
    ask = _ask(Mode.REF2VA, Role.SUBJECT, "Put this car in a night race through a tunnel.")
    assert "<Subject 1> is the black supercar in <Picture 1>" in ask


# ---------------------------------------------------------------- the compiler passes it through

def test_the_compiler_hands_the_writer_the_mode_it_is_writing_for(monkeypatch):
    """A test on the plumbing, not on the helper: the facts are only worth anything if the real
    compile passes them. Captured from `compile_brief` itself with the model replaced."""
    seen: dict[str, object] = {}

    def spy(backend, brief, subjects, cards, target, labels, **kw):
        seen.update(kw)
        raise RuntimeError("stop here; the ask is what this test is about")

    import h3ir.compile as C
    monkeypatch.setattr(C, "compose_brief", spy)

    ref, cards = _plate(Role.FRAME_ANCHOR_FIRST)
    brief = Brief(intent="Animate this photo: the car pulls forward.", seconds=5.0, assets=[ref])

    class _Backend:
        class cfg:
            model = "capture"
        def require_available(self): pass
        def server_version(self): return "test"
        def close(self): pass

    monkeypatch.setattr(C, "analyse_all", lambda *a, **k: cards)
    monkeypatch.setattr(C, "infer_mode", lambda *a, **k: __import__(
        "h3ir.models", fromlist=["ModeDecision"]).ModeDecision(
        mode=Mode.I2VA, confidence=1.0, rule_fired="explicit-role", signals=[]))
    with pytest.raises(RuntimeError):
        compile_brief(brief, backend=_Backend(), opts=ProfileOptions())
    assert seen["mode"] is Mode.I2VA
    assert seen["picture_roles"] == (("<Picture 1>", "frame_anchor_first"),)
