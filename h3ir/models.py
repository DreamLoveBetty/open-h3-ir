"""The contract. Everything that crosses a stage boundary is one of these.

The invariant the whole service rests on: `IRDocument.prompt` is a pure function of the
rest of the document. Re-rendering must reproduce it byte-for-byte (validator rule
X1-render-determinism), so an IR can always be explained by the plan that produced it.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any

from .grid import Target, ms_to_timestamp


class Mode(str, Enum):
    T2VA = "t2va"
    I2VA = "i2va"
    FL2VA = "fl2va"
    L2VA = "l2va"
    REF2VA = "ref2va"

    @property
    def checkpoint(self) -> str:
        return "ref2va" if self is Mode.REF2VA else "fl2va"

    @property
    def is_base(self) -> bool:
        return self is not Mode.REF2VA


class AssetKind(str, Enum):
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"


class Role(str, Enum):
    """Why an asset is attached. Task types and retention markers are DERIVED from this,
    so it must be explicit rather than inferred from prose later."""

    FRAME_ANCHOR_FIRST = "frame_anchor_first"
    FRAME_ANCHOR_LAST = "frame_anchor_last"
    SUBJECT = "subject"
    ENVIRONMENT = "environment"
    STYLE = "style"
    STORYBOARD = "storyboard"
    EDIT_SOURCE = "edit_source"
    CONTINUATION_SOURCE = "continuation_source"
    VOICE_TIMBRE = "voice_timbre"
    BGM = "bgm"
    SFX = "sfx"


VISUAL_MARKERS = ("fully_preserved", "partially_preserved", "attribute_transfer", "weak_reference")
AUDIO_MARKERS = ("fully_copy", "partially_copy", "reference", "weak_reference")

TASK_TYPES = ("keyframe completion", "reference generation", "video editing",
              "video continuation", "audio reuse", "audio reference")

# The closed camera vocabulary from base-en.txt §4.3. 12 motion types + amplitude + speed.
CAMERA_TYPES = ("Zoom In", "Zoom Out", "Push In", "Pull Out", "Pan Left", "Pan Right",
                "Truck Left", "Truck Right", "Tilt Up", "Tilt Down", "Pedestal Up",
                "Pedestal Down", "Arc Shot", "Tracking Shot", "Static Shot",
                "Shake Slightly", "Shake Strongly", "POV", "Roll Clockwise",
                "Roll Counterclockwise")
AMPLITUDES = ("small", "large")
SPEEDS = ("slow", "fast")

# STABLE_LANGUAGES removed by the source audit: the claim that these eleven are H3's "stably
# supported" languages appears in neither spec document nor in any measurement, and D6 -- the only
# rule that used it -- went with it. If a real list turns up, it needs a citation before it comes back.


def _sha(obj: Any) -> str:
    return hashlib.sha256(
        json.dumps(obj, sort_keys=True, default=str, ensure_ascii=False).encode()).hexdigest()[:16]


# --------------------------------------------------------------------------- inputs

@dataclass
class AssetRef:
    """One attached file, before the runtime has assigned it a label."""

    kind: AssetKind
    role: Role
    sha256: str
    path: str | None = None
    url: str | None = None
    note: str | None = None
    px: tuple[int, int] | None = None
    seconds: float | None = None
    frames: int | None = None
    sizing: str = "match"            # match | max
    composition: str = "unknown"     # bare_plate | composed_scene | unknown
    provenance: dict[str, Any] | None = None
    paired_video_sha256: str | None = None   # a soundtrack points at its video


@dataclass
class DialogueLine:
    """User-supplied speech. `text` is pasted verbatim and never passes through a model."""

    text: str
    language: str = "English"
    speaker_hint: str | None = None
    voiceover: bool = False


@dataclass
class Brief:
    """What a caller sends. One sentence and some files is a complete request."""

    intent: str
    assets: list[AssetRef] = field(default_factory=list)
    seconds: float = 5.0
    aspect: str = "16:9"
    canvas: tuple[int, int] | None = None   # pin the exact canvas; else derived from aspect
    dialogue: list[DialogueLine] = field(default_factory=list)
    onscreen_text: list[str] = field(default_factory=list)
    shots: int | None = None          # caller constraint, not the plan
    loras: list[dict[str, Any]] = field(default_factory=list)
    mode: Mode | None = None          # caller override; normally inferred
    effort: str = "standard"          # fast | standard | max
    constraints: list[str] = field(default_factory=list)
    silent: bool = False
    # restrained | balanced | bold -- how much the writer may add beyond what was asked. An explicit
    # input, never inferred from the request; see creativity.py for why inference was rejected.
    creativity: str = "balanced"

    def hash(self) -> str:
        return _sha(asdict(self))


# --------------------------------------------------------------------------- stage B

@dataclass
class AssetCard:
    """What one asset actually contains. Cached on content hash; the expensive, reusable part."""

    sha256: str
    kind: AssetKind
    summary: str = ""
    subjects: list[dict[str, Any]] = field(default_factory=list)
    environment: str = ""
    lighting: str = ""
    palette: list[str] = field(default_factory=list)
    framing: str = ""
    style: str = ""
    visible_text: list[str] = field(default_factory=list)
    motion: str = ""
    # How many frames a video card was built from. 0 on an image or audio card. Recorded because a
    # card built from three frames must not read as one built from the whole clip.
    frames_seen: int = 0
    # The caller's own words about what an asset SOUNDS like, verbatim, with no role prefix and no
    # duration bolted on. Kept separate from `summary` because the summary is provenance about the
    # asset and this is a fact about the video's content -- they belong in different sections, and
    # folding them together is what put "described by the caller as: ... (6.00s)" into
    # overall_soundscape, where the spec wants the target video's ambience.
    characterisation: str = ""
    composition: str = "unknown"
    # A character sheet / turnaround: ONE subject across several panels. Its grid, labels and
    # studio backdrop belong to the sheet and must never reach the brief.
    is_reference_sheet: bool = False
    # audio only
    transcript: str = ""
    language: str = ""
    timbre: str = ""
    music: str = ""
    analyzer_version: str = "1"
    model_id: str = ""

    def hash(self) -> str:
        return _sha(asdict(self))


# --------------------------------------------------------------------------- stage C

@dataclass
class ManifestEntry:
    """An asset with its runtime-assigned label. Slot order IS the label numbering."""

    slot: int
    label: str
    kind: AssetKind
    sha256: str
    wiring: str
    role: Role
    px: tuple[int, int] | None = None
    seconds: float | None = None
    frames: int | None = None
    sizing: str = "match"
    rows: int = 0
    paired_with: str | None = None
    # The caller's own words about the asset. Reaches the renderer this way because
    # render_subject_definitions sees the plan and not the cards, and for audio it is the ONLY thing
    # that can describe the sound -- nothing in this system can hear.
    characterisation: str = ""
    composition: str = "unknown"


@dataclass
class SubjectPlan:
    label: str                       # "<Subject 1>"
    kind: str                        # person | environment | object | style | action
    sources: list[str]               # grounded labels it is drawn from
    descriptor: str                  # "the young man"
    # IDENTITY only. What is true of the subject in any photograph of them.
    attributes: list[str] = field(default_factory=list)
    # TRANSIENT: recorded so we know what the plate showed, and asserted in the IR only when the
    # plate IS a frame of the video (a frame anchor). Otherwise the request owns the action.
    pose: list[str] = field(default_factory=list)
    pose_licensed: bool = False
    retention: str = "fully_preserved"
    retention_note: str = ""
    appears_in: list[int] = field(default_factory=list)


@dataclass
class SpeakerPlan:
    sid: str                         # "(S1)"
    subject: str | None              # "<Subject 1>" or None
    voice: str = ""
    voice_ref: str | None = None     # "<Audio 2>"
    onscreen: bool = True
    descriptor: str = ""


@dataclass
class CameraMove:
    """Chosen from the closed vocabulary by the planner, rendered canonically. The model
    never writes camera prose, which is what makes the vocabulary A/B a template flag."""

    type: str
    amplitude: str | None = None
    speed: str | None = None

    def phrase(self, style: str = "canonical") -> str:
        if style == "prose":
            return ""
        verb = {
            "Zoom In": "zooms in", "Zoom Out": "zooms out",
            "Push In": "pushes in", "Pull Out": "pulls out",
            "Pan Left": "pans left", "Pan Right": "pans right",
            "Truck Left": "trucks left", "Truck Right": "trucks right",
            "Tilt Up": "tilts up", "Tilt Down": "tilts down",
            "Pedestal Up": "rises on a pedestal move", "Pedestal Down": "lowers on a pedestal move",
            "Arc Shot": "arcs around the subject", "Tracking Shot": "tracks with the subject",
            "Static Shot": "holds a static shot",
            "Shake Slightly": "shakes slightly", "Shake Strongly": "shakes strongly",
            "POV": "takes the subject's point of view",
            "Roll Clockwise": "rolls clockwise", "Roll Counterclockwise": "rolls counterclockwise",
        }.get(self.type, self.type.lower())
        out = f"The camera {verb}"
        if self.amplitude:
            out += f" with {self.amplitude} amplitude"
        if self.speed:
            out += f" at {self.speed} speed"
        return out


@dataclass
class SoundEvent:
    """`sync` events belong in the shot body, `ambient` in overall_soundscape. The split is
    made here so the two sections cannot describe the same sound twice."""

    text: str
    layer: str = "sync"              # sync | ambient


@dataclass
class ShotPlan:
    n: int
    start_ms: int
    end_ms: int
    beat: str = ""                   # what changes in this shot — the thing that makes it a shot
    camera: CameraMove | None = None
    subjects: list[str] = field(default_factory=list)
    dialogue: list[DialogueLine] = field(default_factory=list)
    sync_sound: list[str] = field(default_factory=list)
    onscreen_text: list[str] = field(default_factory=list)
    word_target: int = 120
    body: str = ""                   # generated prose, filled at render

    @property
    def cut_timestamp(self) -> str | None:
        return None if self.n == 1 else ms_to_timestamp(self.start_ms)

    @property
    def duration_ms(self) -> int:
        return self.end_ms - self.start_ms


@dataclass
class LoraChoice:
    id: str
    version: int
    file_sha256: str
    strength_requested: float
    strength_applied: float
    triggers: list[dict[str, Any]] = field(default_factory=list)
    registry_revision: str = ""


@dataclass
class ModeDecision:
    mode: Mode
    confidence: float
    rule_fired: str
    signals: list[str] = field(default_factory=list)
    alternatives: list[str] = field(default_factory=list)
    asked: bool = False


@dataclass
class Plan:
    """Everything structural, decided deterministically. The model only fills prose slots."""

    mode: Mode
    target: Target
    manifest: list[ManifestEntry]
    subjects: list[SubjectPlan]
    speakers: list[SpeakerPlan]
    shots: list[ShotPlan]
    task_types: list[str]
    style_phrase: str = ""            # comma-form medium+look; rendered per mode
    summary: str = ""                 # generated prose; the [task type] prefix is templated
    ambient_sound: list[str] = field(default_factory=list)
    music: str = ""
    loras: list[LoraChoice] = field(default_factory=list)
    mode_decision: ModeDecision | None = None
    planner_version: str = "1"

    def label_counts(self) -> dict[str, int]:
        out = {"Picture": 0, "Video": 0, "Audio": 0}
        for e in self.manifest:
            kind = {"image": "Picture", "video": "Video", "audio": "Audio"}[e.kind.value]
            out[kind] += 1
        return out

    def total_word_target(self) -> int:
        return sum(s.word_target for s in self.shots)

    def hash(self) -> str:
        return _sha({
            "mode": self.mode.value,
            "target": [self.target.nominal_seconds, self.target.frames, list(self.target.canvas)],
            "manifest": [asdict(m) for m in self.manifest],
            "subjects": [asdict(s) for s in self.subjects],
            "speakers": [asdict(s) for s in self.speakers],
            "shots": [{k: v for k, v in asdict(s).items() if k != "body"} for s in self.shots],
            "task_types": self.task_types,
            "ambient": self.ambient_sound,
            "loras": [asdict(l) for l in self.loras],
            "planner_version": self.planner_version,
        })


# --------------------------------------------------------------------------- stage E

@dataclass
class Finding:
    rule: str
    severity: str                    # ERROR | WARN | INFO
    msg: str

    def __repr__(self) -> str:
        return f"[{self.severity}] {self.rule}: {self.msg}"


@dataclass
class IRDocument:
    ir_version: str
    profile: str
    mode: Mode
    prompt: str
    plan: Plan
    sections: dict[str, str]
    prompt_tokens: int = 0
    findings: list[Finding] = field(default_factory=list)
    provenance: dict[str, Any] = field(default_factory=dict)
    # First-class, not a log line. A silent fallback produced three generations of identical output
    # and cost hours: the caller could not see that the model's work had been discarded.
    source: str = "written"          # written | enriched | draft
    fallback_reason: str | None = None

    @property
    def fell_back(self) -> bool:
        return self.source == "draft" and bool(self.fallback_reason)

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "ERROR"]

    @property
    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "WARN"]

    @property
    def ok(self) -> bool:
        return not self.errors

    def render_hash(self) -> str:
        """Sampling identity. A LoRA reaches the output through two channels — its trigger
        changes this text, its weights change the render — so the weights must be keyed too."""
        return _sha({
            "prompt": self.prompt,
            "loras": [(l.id, l.file_sha256, l.strength_applied) for l in self.plan.loras],
            "canvas": list(self.plan.target.canvas),
            "frames": self.plan.target.frames,
        })

    def presentation(self) -> dict[str, Any]:
        """User-facing layer. No mode names, no frame counts, no node names.

        A fallback shows here too. The user does not need to hear "draft", but they must not be
        told a directed brief was produced when it was not.
        """
        t = self.plan.target
        shape = {"16:9": "widescreen", "9:16": "vertical", "1:1": "square"}
        ratio = f"{t.canvas[0]}:{t.canvas[1]}"
        w, h = t.canvas
        label = shape.get("16:9" if abs(w / h - 16 / 9) < 0.06 else
                          ("9:16" if abs(w / h - 9 / 16) < 0.06 else
                           ("1:1" if abs(w / h - 1) < 0.06 else ratio)), ratio)
        bits = [f"{t.nominal_seconds:g} seconds", label]
        if len(self.plan.shots) > 1:
            bits.append(f"{len(self.plan.shots)} shots")
        if any(s.dialogue for s in self.plan.shots):
            bits.append("with dialogue")
        if self.plan.music and self.plan.music != "N/A":
            bits.append("with music")
        for l in self.plan.loras:
            bits.append(f"styled with {l.id}")
        out = {"headline": _headline(self.plan), "details": bits}
        if self.fell_back:
            out["notice"] = ("Built from a simple description rather than a directed one — "
                             "the detailed pass did not pass checks.")
            out["degraded"] = True
        return out


def _headline(plan: Plan) -> str:
    anchors = [m for m in plan.manifest if m.role in
               (Role.FRAME_ANCHOR_FIRST, Role.FRAME_ANCHOR_LAST)]
    if plan.mode in (Mode.I2VA, Mode.FL2VA, Mode.L2VA) or anchors:
        return "Animating your image"
    if any(m.role is Role.EDIT_SOURCE for m in plan.manifest):
        return "Editing your clip"
    if any(m.role is Role.CONTINUATION_SOURCE for m in plan.manifest):
        return "Continuing your clip"
    if plan.manifest:
        return "Building a scene from your references"
    return "Building your scene"
