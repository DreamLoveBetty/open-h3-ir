"""Stage B: AssetCards. The expensive, reusable, cached part.

This is where the hosted stage's apparent magic actually lives. Its verbosity tracks how
much reference material there is to inventory: MiniMax's published T2VA description is 249
words with no references, their Ref2VA edit is 238, but their I2VA is 533 words for a single
STATIC shot -- because that one had an image to catalogue. That is an asset inventory
rendered into prose, and it is exactly reproducible locally.

Cached on content hash + analyzer version + model, so swapping one reference re-analyses one
asset and re-uses everything else.
"""
from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

from .backend import Backend, user_message
from .config import get_config
from .models import AssetCard, AssetKind, AssetRef, Role

log = logging.getLogger("h3ir.analyse")

# 2: subjects split into `attributes` (identity) and `pose` (transient). Bumping this is not
# optional when the card's CONTRACT changes -- version 1 cards fold pose into attributes, and
# reusing one silently reintroduces the contamination the split exists to prevent. That is how
# this bump was found: R12 kept firing on a regenerated artifact because the card was cached.
# 3: video cards are built from SAMPLED FRAMES. Version 2 video cards were produced by handing the
# model the .mp4 itself in an `image_url` field -- so it received a base64 video blob where an image
# belongs and returned a card describing nothing in particular. Those cards must not be reused, which
# is the whole reason this constant exists.
# 4: `characterisation` split out of an audio card's `summary`. Version 3 audio cards fold the role
# prefix and the duration into the summary, and the draft appended that whole string to the
# soundscape -- so reusing one puts asset provenance back into a content section.
ANALYZER_VERSION = "4"

# Enough to see a change without paying for a filmstrip. Sampled at 10/50/90% rather than at the ends
# because the first and last frames of a real clip are routinely black or mid-fade.
VIDEO_FRAME_FRACTIONS = (0.1, 0.5, 0.9)

IMAGE_SCHEMA = {
    "title": "ImageCard",
    "type": "object",
    "additionalProperties": False,
    "required": ["summary", "subjects", "environment", "lighting", "framing", "style",
                 "visible_text", "composition", "is_reference_sheet"],
    "properties": {
        "summary": {"type": "string"},
        "subjects": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["kind", "descriptor", "attributes", "pose"],
                "properties": {
                    "kind": {"type": "string",
                             "enum": ["person", "animal", "object", "environment", "style"]},
                    "descriptor": {"type": "string"},
                    "attributes": {"type": "array", "items": {"type": "string"}},
                    "pose": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
        "environment": {"type": "string"},
        "lighting": {"type": "string"},
        "palette": {"type": "array", "items": {"type": "string"}},
        "framing": {"type": "string"},
        "style": {"type": "string"},
        "visible_text": {"type": "array", "items": {"type": "string"}},
        "composition": {"type": "string", "enum": ["bare_plate", "composed_scene", "unknown"]},
        "is_reference_sheet": {"type": "boolean"},
    },
}

IMAGE_INSTRUCTIONS = """You catalogue a reference image for a video-generation pipeline.

Record only what is actually visible. Never guess a name, a brand, a place or a backstory.

For each distinct person, animal or object that could be reused in a video, give a descriptor
("the young man", "the black lamb") and then split what you see into TWO separate lists. The
split matters more than the detail:

`attributes` — IDENTITY. What is true of this subject in any photograph of them: hair, beard,
build, age, garment by type and colour, accessories, markings, material, wear. These are the
things a generator needs in order to redraw them recognisably. Aim for five to eight.

`pose` — TRANSIENT. What is true only of THIS photograph: stance, what they are doing with their
hands or limbs, gesture, facial expression, gaze direction, where they sit in the frame, the
camera angle. "Arms crossed", "hands in pockets", "seen from a low angle" belong here and NEVER
in attributes.

OBSERVE, NEVER INTERPRET. Write only what is literally visible and never what it means. "Hands
loosely closed at his sides" is an observation. "Fists clenched in a fighting stance" is a
narrative inference about intent, and it is wrong: it turned a walking posture into combat and
filed it under identity, so the character then arrived in a corridor braced to fight. Never name
a stance ("fighting stance", "heroic pose", "power stance"), never name an emotion or intent
("determined", "menacing", "confident", "ready to strike"), never say what someone is about to
do. If you cannot see it, it is not there.

REFERENCE SHEETS. If the image is a character sheet, turnaround, model sheet or contact sheet --
one subject repeated across several panels, usually with labels and a plain studio backdrop --
then set `is_reference_sheet` true and describe **ONE** subject. Eight views of one man is one
man. The grid, the panel borders, any text burned into the image (FRONT, LEFT PROFILE, BACK) and
the studio backdrop are properties of the SHEET, not of the character: never put them in
`attributes`, `environment`, `visible_text` or anywhere else. Use the multiple views to describe
the character more completely -- hair from the back, the shoe from the side -- which is what the
sheet is for.

`composition`: "bare_plate" if the subject sits alone against a plain or empty background;
"composed_scene" if it is already staged as a finished frame with a full setting.

`visible_text`: every legible string, exactly as written, in its original language.

Describe the environment, the lighting, the framing and the visual style separately from the
subjects. Return JSON only."""

# There is no audio schema and no audio model call, deliberately. See analyse_audio.
def _cache_path(key: str) -> Path:
    d = get_config().paths.cache_dir() / "cards"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{key}.json"


def _cache_key(ref: AssetRef, model: str) -> str:
    return hashlib.sha256(
        f"{ref.sha256}|{ANALYZER_VERSION}|{model}|{ref.kind.value}".encode()).hexdigest()[:24]


def load_cached(ref: AssetRef, model: str) -> AssetCard | None:
    p = _cache_path(_cache_key(ref, model))
    if not p.exists():
        return None
    try:
        raw = json.loads(p.read_text())
        raw["kind"] = AssetKind(raw["kind"])
        return AssetCard(**raw)
    except Exception:  # noqa: BLE001 - a bad cache entry is not an error, just a miss
        return None


def save_cached(ref: AssetRef, card: AssetCard, model: str) -> None:
    from dataclasses import asdict
    d = asdict(card)
    d["kind"] = card.kind.value
    _cache_path(_cache_key(ref, model)).write_text(json.dumps(d, indent=1, ensure_ascii=False))


def analyse_image(backend: Backend, ref: AssetRef, *, seed: int | None = None) -> AssetCard:
    hint = ""
    if ref.provenance:
        # A generated asset knows how it was made. That is a PRIOR, never a substitute: the
        # model conditions on pixels, and a generated image routinely misses its own prompt.
        src = ref.provenance.get("source_prompt") or ref.provenance.get("edit_instruction")
        if src:
            hint = ("\n\nThis image was machine-generated from the following instruction. Treat it "
                    "as a hint only and correct it against what you actually see:\n" + str(src))
    if ref.note:
        hint += f"\n\nThe caller says this reference is: {ref.note}"

    obj = backend.json_call(
        [{"role": "system", "content": IMAGE_INSTRUCTIONS},
         user_message("Catalogue this image." + hint, [ref.path] if ref.path else None)],
        IMAGE_SCHEMA, required=("summary", "subjects"), seed=seed, max_tokens=6000)

    return AssetCard(
        sha256=ref.sha256, kind=AssetKind.IMAGE,
        summary=obj.get("summary", ""),
        subjects=obj.get("subjects") or [],
        environment=("" if obj.get("is_reference_sheet") else obj.get("environment", "")),
        lighting=obj.get("lighting", ""),
        palette=obj.get("palette") or [],
        framing=obj.get("framing", ""),
        style=obj.get("style", ""),
        visible_text=([] if obj.get("is_reference_sheet") else (obj.get("visible_text") or [])),
        composition=(ref.composition if ref.composition != "unknown"
                     else obj.get("composition", "unknown")),
        is_reference_sheet=bool(obj.get("is_reference_sheet")),
        analyzer_version=ANALYZER_VERSION,
        model_id=backend.cfg.model,
    )


def analyse_audio(ref: AssetRef, transcript: str = "", *,
                  duration_s: float | None = None) -> AssetCard:
    """Typed metadata only. NO model call -- the model is deaf and must never be asked.

    Three reasons this is a rule and not a preference:

      * The endpoint has a vision tower and no audio tower. Asked about a waveform it cannot
        hear, it does not say so; it invents a plausible description. A confident wrong timbre
        is worse than a missing one, because it reaches the IR as an assertion.
      * The prior-art sweep found the same wall independently ("Qwen3-VL does not inspect saved
        audio waveforms"), and a note that a deaf model gets confused rather than abstaining.
      * H3's own tokenizer emits `"<Audio j>: "` and nothing else -- the audio content never
        enters the conditioning encoder at all. So the IR text is the ONLY channel by which the
        encoder learns what that audio is, which makes an invented description actively harmful
        rather than merely useless.

    What we legitimately know comes from the wiring: the role the caller assigned, the caller's
    note, the duration, and a transcript if one was produced by an actual speech recogniser.
    The prose stage then writes around those facts instead of about the sound.
    """
    role_summary = {
        Role.VOICE_TIMBRE: "a spoken vocal reference supplying voice timbre and delivery",
        Role.BGM: "a background music track",
        Role.SFX: "a sound-effect reference",
    }.get(ref.role, "an audio reference")
    summary = role_summary
    if ref.note:
        summary += f", described by the caller as: {ref.note.strip()}"
    if duration_s or ref.seconds:
        summary += f" ({(duration_s or ref.seconds):.2f}s)"

    language = ""
    if transcript:
        # Only what a recogniser actually reported; never guessed from the filename.
        language = (ref.provenance or {}).get("language", "") if ref.provenance else ""

    return AssetCard(
        sha256=ref.sha256, kind=AssetKind.AUDIO,
        summary=summary + ".",
        # timbre and music stay EMPTY unless something that can hear fills them in. A TRANSCRIPT
        # does not fill them: it gives the words, not the delivery, the tempo, or whether the thing
        # is music at all. So a transcript closes the dialogue half of audio and leaves the sonic
        # half exactly where it was -- only the caller can say "his voice, calm and low".
        timbre="", music="",
        characterisation=(ref.note or "").strip(),
        transcript=transcript, language=language,
        analyzer_version=ANALYZER_VERSION, model_id="none (typed metadata only)")


class AssetAnalysisError(RuntimeError):
    """An asset could not be analysed. Raised rather than returning an empty card: a card that
    describes nothing is indistinguishable from a card describing something dull, and the compiler
    would build a brief on it without noticing."""


def probe_seconds(path: str | Path) -> float:
    """Duration from the file itself, which is ground truth -- a caller's `seconds` is a claim."""
    import subprocess
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, timeout=30)
    if out.returncode != 0 or not out.stdout.strip():
        raise AssetAnalysisError(f"ffprobe could not read {path}: {out.stderr.strip()[:200]}")
    try:
        return float(out.stdout.strip())
    except ValueError as e:
        raise AssetAnalysisError(f"ffprobe returned no duration for {path}") from e


def sample_frames(path: str | Path, sha256: str,
                  fractions: tuple[float, ...] = VIDEO_FRAME_FRACTIONS) -> list[str]:
    """Extract representative frames, cached beside the cards on the asset's content hash.

    Nothing produced frames before this: `analyse_video` accepted a frame list and every caller
    passed none, so it fell through to handing the model the video file as an image.
    """
    import subprocess

    p = Path(path)
    if not p.exists():
        raise AssetAnalysisError(f"video reference does not exist: {p}")
    # Keyed on the FRACTIONS as well as the content, for the same reason cards are keyed on
    # ANALYZER_VERSION: change what the artifact means and a cached one must not be reused. Without
    # this, editing VIDEO_FRAME_FRACTIONS silently reuses frames taken at the old timestamps -- which
    # is exactly how a falsification run passed when it should have failed, the cache quietly serving
    # correct frames to a sampler that had been broken on purpose.
    key = hashlib.sha256(repr(tuple(fractions)).encode()).hexdigest()[:8]
    out_dir = get_config().paths.cache_dir() / "frames" / f"{sha256[:16]}-{key}"
    out_dir.mkdir(parents=True, exist_ok=True)
    seconds = probe_seconds(p)
    made: list[str] = []
    for i, frac in enumerate(fractions):
        dest = out_dir / f"f{i}.jpg"
        if not dest.exists():
            at = max(0.0, min(seconds * frac, max(0.0, seconds - 0.05)))
            r = subprocess.run(
                ["ffmpeg", "-nostdin", "-y", "-ss", f"{at:.3f}", "-i", str(p),
                 "-frames:v", "1", "-q:v", "3", str(dest)],
                capture_output=True, text=True, timeout=120)
            if r.returncode != 0 or not dest.exists() or dest.stat().st_size == 0:
                log.warning("frame at %.2fs failed for %s: %s", at, p.name,
                            r.stderr.strip()[-200:])
                continue
        made.append(str(dest))
    if not made:
        raise AssetAnalysisError(
            f"could not sample a single frame from {p.name}. A video card built without frames "
            "describes nothing, so this raises instead of returning one.")
    return made


def analyse_video(backend: Backend, ref: AssetRef, frames: list[str] | None = None,
                  *, seed: int | None = None) -> AssetCard:
    """A video card is an image card for representative frames plus its motion.

    Frames are REQUIRED. Passing the video file to a vision model as an image is what the previous
    version did, and it produced a plausible-looking card from a base64 blob the model could not
    read -- silent, because nothing errored and the card had the right shape.
    """
    frames = frames or (sample_frames(ref.path, ref.sha256) if ref.path else [])
    if not frames:
        raise AssetAnalysisError(
            f"no frames for video {ref.sha256[:12]} and no path to sample from")
    obj = backend.json_call(
        [{"role": "system", "content": IMAGE_INSTRUCTIONS +
          f"\n\nThese {len(frames)} frames are sampled in order from across one video clip: the "
          "first is near the start, the last near the end. They are the SAME clip, not separate "
          "references. Record what changes between them -- movement, position, light -- in the "
          "`summary` sentence, and describe the subject once rather than once per frame."},
         user_message("Catalogue this clip." + (f"\n\nCaller's note: {ref.note}" if ref.note else ""),
                      frames)],
        IMAGE_SCHEMA, required=("summary", "subjects"), seed=seed, max_tokens=6000)
    return AssetCard(sha256=ref.sha256, kind=AssetKind.VIDEO,
                     summary=obj.get("summary", ""), subjects=obj.get("subjects") or [],
                     environment=obj.get("environment", ""), lighting=obj.get("lighting", ""),
                     palette=obj.get("palette") or [], framing=obj.get("framing", ""),
                     style=obj.get("style", ""), visible_text=obj.get("visible_text") or [],
                     motion=obj.get("summary", ""),
                     composition=obj.get("composition", "composed_scene"),
                     frames_seen=len(frames),
                     analyzer_version=ANALYZER_VERSION, model_id=backend.cfg.model)


def analyse_all(backend: Backend, refs: list[AssetRef], *, use_cache: bool = True,
                seed: int | None = None,
                transcripts: dict[str, str] | None = None) -> dict[str, AssetCard]:
    out: dict[str, AssetCard] = {}
    for ref in refs:
        if use_cache:
            hit = load_cached(ref, backend.cfg.model)
            if hit is not None:
                log.info("card cache hit %s", ref.sha256[:12])
                out[ref.sha256] = hit
                continue
        if ref.kind is AssetKind.IMAGE:
            card = analyse_image(backend, ref, seed=seed)
        elif ref.kind is AssetKind.AUDIO:
            card = analyse_audio(ref, (transcripts or {}).get(ref.sha256, ""))
        else:
            card = analyse_video(backend, ref, seed=seed)
        out[ref.sha256] = card
        if use_cache:
            save_cached(ref, card, backend.cfg.model)
    return out


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()
