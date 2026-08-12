"""Stage A': mode inference. The caller never picks a mode.

The five modes are not five creative intents. They are two checkpoints and a count, plus one
genuinely hard semantic question:

    is this image a FRAME of the video, or a THING THAT APPEARS IN it?

Everything else routes off the wiring with no model involved. "Animate this photo" and "put
this man in a battle" are the same attachment count and the same file type; only that question
separates them.

Failing safe has a principled direction rather than a coin flip: Ref2VA is strictly more
expressive. Its `keyframe completion` task type can say "this image is the first frame", so a
misrouted anchor is still expressible; FL2VA has no way to say "this thing appears but is not a
frame". So ambiguity resolves to Ref2VA.

The cost of that default is recorded rather than hidden: FL2VA injects the keyframe as a cond
latent pinned to frame 0 (or frame_count-1) that is never denoised -- an exact-frame guarantee
Ref2VA only softly promises.
"""
from __future__ import annotations

from typing import Any

from .backend import Backend, BackendError
from .models import AssetCard, AssetKind, Brief, Mode, ModeDecision, Role

ANCHOR_PHRASES = (
    "animate this", "animate the", "make this move", "bring this to life", "bring it to life",
    "start from this", "starting from this", "from this frame", "end on this", "ends on this",
    "opening frame", "first frame", "last frame", "this photo moving", "make it move",
)
REFERENCE_PHRASES = (
    "using this", "use this character", "this person", "this product", "in this style",
    "like this", "put him", "put her", "put them", "put the", "combine", "insert",
    "same character", "keep the character", "wearing", "riding",
)

CLASSIFY_SCHEMA = {
    "title": "AnchorOrReference",
    "type": "object",
    "additionalProperties": False,
    "required": ["intent", "which", "confidence", "signals"],
    "properties": {
        "intent": {"type": "string", "enum": ["frame_anchor", "content_reference"]},
        "which": {"type": "string", "enum": ["first", "last", "both", "none"]},
        "confidence": {"type": "number"},
        "signals": {"type": "array", "items": {"type": "string"}},
    },
}

CLASSIFY_INSTRUCTIONS = """Decide one thing about the attached image(s) in a video request.

Either the image IS a frame of the video that will be produced -- the video literally starts
from it, or ends on it -- which is "frame_anchor".

Or the image shows something that will APPEAR in the video, redrawn into a new scene: a person,
an animal, a product, a place, a style. That is "content_reference".

Two images described as a start and an end are frame_anchor with which="both". Two images
showing two different things that must appear together are content_reference.

Be decisive but honest about confidence. Return JSON only."""


def _text_signals(intent: str) -> tuple[list[str], list[str]]:
    low = intent.lower()
    return ([p for p in ANCHOR_PHRASES if p in low],
            [p for p in REFERENCE_PHRASES if p in low])


def infer_mode(brief: Brief, cards: dict[str, AssetCard] | None = None,
               backend: Backend | None = None) -> ModeDecision:
    if brief.mode is not None:
        return ModeDecision(mode=brief.mode, confidence=1.0, rule_fired="caller-override",
                            signals=["caller supplied an explicit mode"])

    images = [a for a in brief.assets if a.kind is AssetKind.IMAGE]
    videos = [a for a in brief.assets if a.kind is AssetKind.VIDEO]
    audios = [a for a in brief.assets if a.kind is AssetKind.AUDIO]

    # --- deterministic rules: the wiring decides, no model needed -------------------
    if videos or audios:
        return ModeDecision(mode=Mode.REF2VA, confidence=1.0, rule_fired="12.2#1",
                            signals=["a video or audio reference is attached; the FL2VA "
                                     "checkpoint cannot accept them"])
    if len(images) > 2:
        return ModeDecision(mode=Mode.REF2VA, confidence=1.0, rule_fired="12.2#2",
                            signals=[f"{len(images)} images attached; more than two cannot be "
                                     "frame anchors"])
    if not images:
        return ModeDecision(mode=Mode.T2VA, confidence=1.0, rule_fired="12.2#3",
                            signals=["no visual references attached"])

    # --- provenance short-circuit: ground truth beats a language heuristic ----------
    intended = [a.provenance.get("intended_role") for a in images
                if a.provenance and a.provenance.get("intended_role")]
    if intended and len(intended) == len(images):
        if all(r in ("first_frame", "frame_anchor", "opening_frame") for r in intended):
            mode = Mode.I2VA if len(images) == 1 else Mode.FL2VA
            return ModeDecision(mode=mode, confidence=1.0, rule_fired="12.8-provenance",
                                signals=["the app generated these stills as frame anchors"])
        if all(r in ("subject", "plate", "reference") for r in intended):
            return ModeDecision(mode=Mode.REF2VA, confidence=1.0, rule_fired="12.8-provenance",
                                signals=["the app generated these stills as subject plates"])

    # --- explicit roles from the caller ---------------------------------------------
    roles = {a.role for a in images}
    if roles & {Role.FRAME_ANCHOR_FIRST, Role.FRAME_ANCHOR_LAST}:
        first = Role.FRAME_ANCHOR_FIRST in roles
        last = Role.FRAME_ANCHOR_LAST in roles
        mode = Mode.FL2VA if (first and last) else (Mode.I2VA if first else Mode.L2VA)
        return ModeDecision(mode=mode, confidence=1.0, rule_fired="explicit-role",
                            signals=["the caller assigned frame-anchor roles"])

    anchor_hits, ref_hits = _text_signals(brief.intent)
    signals = ([f"anchor phrase: {p!r}" for p in anchor_hits]
               + [f"reference phrase: {p!r}" for p in ref_hits])

    # Two images and two named subjects is decisively Ref2VA.
    if len(images) == 2 and len(ref_hits) > len(anchor_hits):
        return ModeDecision(mode=Mode.REF2VA, confidence=0.9, rule_fired="12.3-two-subjects",
                            signals=signals + ["two images described as two different things"],
                            alternatives=["fl2va"])

    if anchor_hits and not ref_hits:
        mode = Mode.I2VA if len(images) == 1 else Mode.FL2VA
        conf = 0.85
        # An anchor is stretched to the target canvas, so a mismatched aspect is a poor anchor.
        for a in images:
            if a.px:
                want = _aspect(brief.aspect)
                got = a.px[0] / a.px[1]
                if abs(got - want) / want > 0.2:
                    conf = 0.6
                    signals.append(f"aspect mismatch: image is {got:.2f}, target {want:.2f}")
        return ModeDecision(mode=mode, confidence=conf, rule_fired="12.3-anchor-language",
                            signals=signals, alternatives=["ref2va"])

    if ref_hits and not anchor_hits:
        return ModeDecision(mode=Mode.REF2VA, confidence=0.85, rule_fired="12.3-reference-language",
                            signals=signals, alternatives=["i2va"])

    # --- genuinely ambiguous: ask the model, then fail safe ------------------------
    if backend is not None and cards:
        try:
            obj = backend.json_call(
                [{"role": "system", "content": CLASSIFY_INSTRUCTIONS},
                 {"role": "user", "content": _classify_ask(brief, images, cards)}],
                CLASSIFY_SCHEMA, required=("intent", "confidence"), max_tokens=3000)
            conf = float(obj.get("confidence") or 0.5)
            signals += [str(s) for s in (obj.get("signals") or [])]
            if obj.get("intent") == "frame_anchor" and conf >= 0.7:
                which = obj.get("which") or ("both" if len(images) == 2 else "first")
                mode = (Mode.FL2VA if which == "both" and len(images) == 2 else
                        (Mode.L2VA if which == "last" else Mode.I2VA))
                return ModeDecision(mode=mode, confidence=conf, rule_fired="12.3-classifier",
                                    signals=signals, alternatives=["ref2va"])
            return ModeDecision(mode=Mode.REF2VA, confidence=conf, rule_fired="12.3-classifier",
                                signals=signals, alternatives=["i2va", "fl2va"])
        except BackendError as e:
            signals.append(f"classifier unavailable: {e}")

    return ModeDecision(mode=Mode.REF2VA, confidence=0.5, rule_fired="12.4-failsafe",
                        signals=signals + ["ambiguous; Ref2VA is strictly more expressive so it "
                                           "is the safe default"],
                        alternatives=["i2va", "fl2va"])


def _classify_ask(brief: Brief, images: list, cards: dict[str, AssetCard]) -> str:
    lines = [f"Request: {brief.intent}", "", f"{len(images)} image(s) attached:"]
    for i, a in enumerate(images, 1):
        c = cards.get(a.sha256)
        desc = c.summary if c else (a.note or "no description")
        comp = f" [{c.composition}]" if c and c.composition != "unknown" else ""
        lines.append(f"  Image {i}{comp}: {desc}")
    return "\n".join(lines)


def _aspect(a: str) -> float:
    sep = ":" if ":" in a else "x"
    w, h = a.split(sep, 1)
    return float(w) / float(h)


def needs_clarification(d: ModeDecision) -> dict[str, Any] | None:
    """Ask at most one question, and only where the wrong default is visible in the output.

    Low confidence WITH anchor language is that case: routing an anchor to Ref2VA loses the
    exact-frame guarantee. Low confidence without anchor language just gets Ref2VA silently.
    """
    if d.confidence >= 0.7 or d.rule_fired.startswith(("12.2", "explicit", "caller", "12.8")):
        return None
    if not any("anchor phrase" in s for s in d.signals):
        return None
    return {
        "id": "anchor_or_reference",
        "ask": "Should your image be the video's opening frame, or should what it shows appear "
               "in a new scene?",
        "options": [
            {"id": "opening_frame", "label": "Use it as the opening frame"},
            {"id": "appears_in", "label": "Put what it shows into a new scene"},
        ],
        "recommended": "appears_in",
        "default_if_unanswered": "appears_in",
    }
