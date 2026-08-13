"""The ComfyUI-facing half: the node schema, tensors, and temp files.

Everything that can be tested without ComfyUI lives in `h3ir_client.py`. What is left here is what
genuinely cannot: the schema the canvas draws, converting an IMAGE tensor into a file on disk, and
finding a directory ComfyUI considers its own.

Imports of numpy and PIL happen inside the function that needs them rather than at module scope. An
exception while ComfyUI is importing a custom node takes the whole pack off the menu with a traceback
the user cannot act on, and this node is useful for text-only prompts even in an install where
something is wrong with the imaging stack.

On why references are separate sockets rather than one batch. Combining images into a batch requires
them to share dimensions, so ComfyUI's batch nodes resize whatever does not fit. Reference plates are
rarely the same shape, and a silently resized reference is a changed reference. The stock H3 node
keeps each one separate and sizes them individually for the same reason, so this node matches it.
"""
from __future__ import annotations

import hashlib
import os
import tempfile
from typing import Any

from .h3ir_client import (ASPECTS, CREATIVITY, DEFAULT_SERVER, EFFORT, SIZING, ServiceError,
                          build_payload, compile_brief, inputs_fingerprint, render_fields, report,
                          translate_path)

# H3 itself accepts up to nine reference images. Four sockets is what this node exposes, because
# that covers reference work people actually do and nine permanent sockets makes the node unreadable
# on the canvas. This is a stated limit rather than a silent one: if you need more, the service takes
# them, and the node should grow a dynamic input list.
MAX_REFERENCES = 4
IMAGE_SOCKETS = tuple(f"image_{i}" for i in range(1, MAX_REFERENCES + 1))


def _temp_dir() -> str:
    """A directory ComfyUI owns, falling back to the system temp when running outside it.

    Never a path next to this source file: a custom node that writes into its own directory turns a
    git checkout dirty and survives no update.
    """
    try:
        import folder_paths  # provided by ComfyUI at runtime
        d = folder_paths.get_temp_directory()
    except Exception:  # noqa: BLE001 - running outside ComfyUI is a supported case
        d = os.path.join(tempfile.gettempdir(), "openh3ir")
    os.makedirs(d, exist_ok=True)
    return d


def _to_uint8_rgb(image: Any, socket: str) -> Any:
    """One image tensor to an HxWx3 uint8 array, refusing anything ambiguous.

    A socket carrying several images is an error rather than a silent choice of the first. Which
    reference the user meant is not something to guess at, and picture order decides which subject
    gets bound to which plate.
    """
    import numpy as np

    arr = image.detach().cpu().numpy() if hasattr(image, "detach") else np.asarray(image)
    if arr.ndim == 4:
        if arr.shape[0] != 1:
            raise ServiceError(
                f"{socket} carries {arr.shape[0]} images in one batch, and this socket holds one "
                "reference. Connect each reference to its own image socket, in the order you want "
                "them numbered, so nothing gets resized to match anything else.")
        arr = arr[0]
    if arr.ndim != 3:
        raise ServiceError(f"{socket} is not an image (array shape {arr.shape}).")
    arr = np.clip(arr, 0.0, 1.0)
    arr = (arr * 255.0 + 0.5).astype(np.uint8)
    if arr.shape[2] == 4:
        arr = arr[:, :, :3]
    if arr.shape[2] != 3:
        raise ServiceError(f"{socket} has {arr.shape[2]} channels, which is not an RGB image.")
    return arr


def _write_reference(image: Any, socket: str) -> str:
    """Write one reference out as a PNG and return its path.

    The filename is a content hash, so an unchanged image keeps its path between runs and the
    service's own sha256 of the file stays stable. That is what makes the render hash comparable
    across two runs of the same graph.
    """
    from PIL import Image

    arr = _to_uint8_rgb(image, socket)
    digest = hashlib.sha256(arr.tobytes()).hexdigest()[:16]
    path = os.path.join(_temp_dir(), f"openh3ir_ref_{digest}.png")
    if not os.path.exists(path):
        Image.fromarray(arr, "RGB").save(path, format="PNG")
    return path


def _digest(image: Any) -> str:
    """Content hash of one image, so IS_CHANGED reacts to pixels rather than object identity."""
    if image is None:
        return "none"
    try:
        import numpy as np
        arr = image.detach().cpu().numpy() if hasattr(image, "detach") else np.asarray(image)
        return hashlib.sha256(np.ascontiguousarray(arr).tobytes()).hexdigest()
    except Exception:  # noqa: BLE001 - a hash we cannot take must not break the graph
        return "unhashable"


class OpenH3IRCompile:
    """Compile one sentence into an H3 brief, and hand a graph the numbers that go with it."""

    @classmethod
    def INPUT_TYPES(cls) -> dict[str, Any]:
        optional: dict[str, Any] = {}
        for i, socket in enumerate(IMAGE_SOCKETS, 1):
            optional[socket] = ("IMAGE", {
                "tooltip": f"Reference image {i}. Connected sockets are numbered in order, so this "
                           f"one becomes <Picture {i}> when the ones before it are connected. That "
                           "label is how a subject in the brief gets bound to a plate. Leave them "
                           "all empty for a text-only prompt."})
        optional.update({
            "image_notes": ("STRING", {
                "multiline": True, "default": "",
                "tooltip": "One short line per connected image, same order, saying what it is: the "
                           "man, the car, the room. Never required, and often the difference "
                           "between the right subject being described and the wrong one."}),
            "sizing": (list(SIZING), {
                "default": "match",
                "tooltip": "How references get scaled. match fits each one to the render's pixel "
                           "area; max keeps the reference's own size. Echoed on the ref_image_size "
                           "output so you can set the H3 node to the same thing."}),
            "seed": ("INT", {
                "default": 7, "min": 0, "max": 0xFFFFFFFFFFFFFF,
                "tooltip": "The compiler is seeded, so the same inputs give the same brief. Change "
                           "this to get a different take on the same sentence."}),
            "effort": (list(EFFORT), {
                "default": "standard",
                "tooltip": "How hard the writer works. max asks for reasoning prose and takes "
                           "longer."}),
            "shots": ("INT", {
                "default": 0, "min": 0, "max": 8,
                "tooltip": "Force a number of shots. 0 lets the compiler decide, which is usually "
                           "right, because the cut times have to land on the frame grid too."}),
            "silent": ("BOOLEAN", {
                "default": False,
                "tooltip": "No score and no dialogue. H3 generates audio in the same pass as the "
                           "picture, so silence is a decision rather than an absence."}),
            "timeout_s": ("INT", {
                "default": 600, "min": 10, "max": 3600,
                "tooltip": "Writing a brief is one call to your language model, so this is as slow "
                           "as that model is. Raise it for a big model on a small box."}),
            "comfy_path_prefix": ("STRING", {
                "default": "",
                "tooltip": "Only needed when ComfyUI and the service see the filesystem "
                           "differently, for example ComfyUI on Windows and the service in WSL or "
                           "a container. Put ComfyUI's spelling of a shared folder here, such as "
                           "C:\\ComfyUI-Production."}),
            "service_path_prefix": ("STRING", {
                "default": "",
                "tooltip": "The same folder as the service spells it, such as "
                           "/mnt/c/ComfyUI-Production. Leave both empty when they share one view "
                           "of the disk."}),
        })
        return {
            "required": {
                "intent": ("STRING", {
                    "multiline": True,
                    "default": "she walks out onto the wet gantry in the rain and stops when she "
                               "sees the city below",
                    "tooltip": "What should happen, in one ordinary sentence. Not a tag list and "
                               "not a shot breakdown: the compiler writes those. Say the action "
                               "and the beat you care about."}),
                "seconds": ("FLOAT", {
                    "default": 8.0, "min": 1.0, "max": 60.0, "step": 0.1,
                    "tooltip": "How long you want it. H3 only renders lengths on a 17k+5 frame "
                               "grid, so this is snapped for you and the length output tells you "
                               "what you actually got. Ask for 10 and you get 10.125. Exactly one "
                               "whole second exists in the trained range, and it is 8.0."}),
                "aspect": (list(ASPECTS), {
                    "default": "16:9",
                    "tooltip": "Frame shape. The width and height outputs come back sized for it."}),
                "creativity": (list(CREATIVITY), {
                    "default": "balanced",
                    "tooltip": "How much the writer may add that you never asked for. restrained "
                               "keeps to your sentence; balanced shapes it and scores it if it "
                               "wants scoring; bold and extreme may introduce a spoken line, "
                               "music, on-screen text or a beat of their own. Saying no dialogue "
                               "in the intent still means no dialogue at every setting."}),
                "server": ("STRING", {
                    "default": DEFAULT_SERVER,
                    "tooltip": "Where an OpenH3-IR service is listening. Start one from the repo "
                               "with h3ir serve. It can be another machine, though reference "
                               "images then need paths that machine can read."}),
            },
            "optional": optional,
        }

    RETURN_TYPES = ("STRING", "INT", "INT", "INT", "STRING", "STRING")
    RETURN_NAMES = ("prompt", "width", "height", "length", "ref_image_size", "report")
    OUTPUT_TOOLTIPS = (
        "The compiled brief. Goes into the prompt input of MiniMaxH3ReferenceToVideo or "
        "MiniMaxH3ImageToVideo, in place of the text box you were typing into by hand.",
        "Canvas width for the H3 node.",
        "Canvas height for the H3 node.",
        "Frame count, already on H3's legal grid. Wire this to length and the model stops rounding "
        "your duration behind your back.",
        "Which sizing the references asked for, as text. The H3 node's ref_image_size is a dropdown "
        "and cannot be driven from a string socket, so set it to this by hand.",
        "What came back, in plain words: the mode it inferred, the real length, and which image "
        "became which picture label.",
    )
    FUNCTION = "compile"
    CATEGORY = "OpenH3-IR"
    DESCRIPTION = ("Turn one sentence into the structured document MiniMax H3 expects, and output "
                   "the prompt, canvas and legal frame count to wire straight into the H3 nodes.")

    @classmethod
    def IS_CHANGED(cls, **kwargs: Any) -> str:
        """Re-compile when an input changed, and never otherwise.

        The compiler is deterministic for a given seed, so an unchanged graph re-queued would spend
        another model call to produce a byte-identical brief. Hashing the inputs, pixels included,
        makes a re-queue free and makes any real edit re-compile.
        """
        images = [_digest(kwargs.pop(s, None)) for s in IMAGE_SOCKETS]
        return inputs_fingerprint(sorted(kwargs.items()), images)

    def compile(self, intent: str, seconds: float, aspect: str, creativity: str, server: str,
                image_notes: str = "", sizing: str = "match", seed: int = 7,
                effort: str = "standard", shots: int = 0, silent: bool = False,
                timeout_s: int = 600, comfy_path_prefix: str = "", service_path_prefix: str = "",
                **images: Any) -> tuple[str, int, int, int, str, str]:
        paths: list[str] = []
        for socket in IMAGE_SOCKETS:
            img = images.get(socket)
            if img is None:
                continue
            written = _write_reference(img, socket)
            paths.append(translate_path(written, comfy_path_prefix, service_path_prefix))

        notes = list((image_notes or "").splitlines())
        payload = build_payload(intent, seconds=seconds, aspect=aspect, creativity=creativity,
                                effort=effort, seed=seed, silent=silent, shots=shots,
                                asset_paths=paths, notes=notes, sizing=sizing)

        body = compile_brief(server, payload, timeout=float(timeout_s))
        prompt, width, height, length, ref_sizing = render_fields(body)

        wiring = body.get("wiring") or []
        conflict = len({w.get("sizing") for w in wiring if w.get("sizing")}) > 1
        text = report(body, server=server, sizing_conflict=conflict)
        print(f"[OpenH3-IR] compiled {body.get('brief_id')}: {length} frames "
              f"({length / 24:.3f}s), {width}x{height}, mode {body.get('mode')}")
        return (prompt, width, height, length, ref_sizing, text)


class OpenH3IRShowText:
    """Display any text output on the canvas. Exists so the report can be read without a detour."""

    @classmethod
    def INPUT_TYPES(cls) -> dict[str, Any]:
        return {"required": {"text": ("STRING", {
            "forceInput": True,
            "tooltip": "Any text output, such as the compile report or the brief itself."})}}

    RETURN_TYPES = ()
    FUNCTION = "show"
    OUTPUT_NODE = True
    CATEGORY = "OpenH3-IR"
    DESCRIPTION = "Show a text output, such as the compile report or the brief itself."

    def show(self, text: str) -> dict[str, Any]:
        return {"ui": {"text": [text if isinstance(text, str) else str(text)]}}


NODE_CLASS_MAPPINGS = {
    "OpenH3IRCompile": OpenH3IRCompile,
    "OpenH3IRShowText": OpenH3IRShowText,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "OpenH3IRCompile": "OpenH3-IR Compile",
    "OpenH3IRShowText": "OpenH3-IR Show Text",
}

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "ServiceError"]
