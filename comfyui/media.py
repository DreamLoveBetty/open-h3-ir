"""Turning what arrives on a socket into files the service can open, with no ComfyUI involved.

This is the second half of the pack's ComfyUI-free layer. `h3ir_client` owns the service protocol;
this owns the conversion from a tensor in memory to bytes on a disk, which is where a silent resize,
a dropped channel or a reused file would hide. Both are testable without a canvas, and both are
tested, because a node whose logic can only be exercised by clicking Queue is a node with no tests.

Two facts about ComfyUI's own types shape everything here, and both were learned by running a real
graph rather than by reading a docstring.

An AUDIO is a **mapping** of `waveform` and `sample_rate`, not necessarily a dict. Load Video
(Upload), which is the loader this pack tells people to use, hands out a `LazyAudioMap`: a Mapping
subclass that runs ffmpeg the first time a key is read. Anything here that tested for `dict` refused
that loader and reported the clip as having no soundtrack.

An IMAGE is a batch even when the user is thinking of one picture, so a socket holding several is an
error rather than a silent choice of the first: the order decides which subject binds to which
picture label.

Everything is content-addressed. A file's name is a hash of what is in it, so an unchanged input
keeps its path, the service's own hash of the file stays stable, and two different clips of the same
length can never land on the same path and have the second silently reuse the first.
"""
from __future__ import annotations

import hashlib
import os
import wave
from collections.abc import Mapping
from typing import Any

from .h3ir_client import FPS, ServiceError


def slug(socket: str) -> str:
    """A socket name as a filename fragment. The names have spaces in them deliberately, because the
    canvas says `picture 1` and the brief says `<Picture 1>`, so they are flattened here rather than
    leaking a space into a path some tool will re-split."""
    return "".join(c if c.isalnum() else "_" for c in socket)


def digest(obj: Any) -> str:
    """Content hash of anything that can arrive on a socket.

    The bundles are walked rather than hashed by identity: a Footage or Sound node hands over a
    mapping of tensors, and `repr` of that is a memory address. Hashing the address would make a
    swapped reference image or a re-typed note look like no change at all, and ComfyUI would hand
    back the previous brief.
    """
    if obj is None:
        return "none"
    try:
        import numpy as np
        if isinstance(obj, Mapping):
            if "waveform" in obj:
                return digest(obj.get("waveform")) + f"@{obj.get('sample_rate')}"
            return "{" + ",".join(f"{k}={digest(obj[k])}" for k in sorted(obj)) + "}"
        if isinstance(obj, (list, tuple)):
            return "[" + ",".join(digest(o) for o in obj) + "]"
        if isinstance(obj, (str, int, float, bool)):
            return repr(obj)
        arr = obj.detach().cpu().numpy() if hasattr(obj, "detach") else np.asarray(obj)
        return hashlib.sha256(np.ascontiguousarray(arr).tobytes()).hexdigest()
    except Exception:  # noqa: BLE001 - a hash we cannot take must not break the graph
        return "unhashable"


def sha256_file(path: str) -> str:
    """The same hash the service takes of the same bytes, which is what lets the report put the
    user's socket names back onto the labels the service computed."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def to_uint8_rgb(image: Any, socket: str) -> Any:
    """One image tensor to HxWx3 uint8, refusing anything ambiguous. A socket carrying several
    pictures is an error rather than a silent choice of the first, because the order decides which
    subject binds to which picture."""
    import numpy as np

    arr = image.detach().cpu().numpy() if hasattr(image, "detach") else np.asarray(image)
    if arr.ndim == 4:
        if arr.shape[0] != 1:
            raise ServiceError(
                f"{socket} carries {arr.shape[0]} pictures in one batch, and this socket holds one. "
                "Connect each picture to its own socket, in the order you want them numbered, so "
                "nothing gets resized to match anything else.")
        arr = arr[0]
    if arr.ndim != 3:
        raise ServiceError(f"{socket} is not a picture (array shape {arr.shape}).")
    arr = np.clip(arr, 0.0, 1.0)
    arr = (arr * 255.0 + 0.5).astype(np.uint8)
    if arr.shape[2] == 4:
        arr = arr[:, :, :3]
    if arr.shape[2] != 3:
        raise ServiceError(f"{socket} has {arr.shape[2]} channels, which is not an RGB picture.")
    return arr


def write_picture(image: Any, socket: str, into: str) -> str:
    """Write one picture as a PNG named by its content, so an unchanged picture keeps its path."""
    from PIL import Image

    arr = to_uint8_rgb(image, socket)
    path = os.path.join(into, f"openh3ir_{slug(socket)}_"
                              f"{hashlib.sha256(arr.tobytes()).hexdigest()[:16]}.png")
    if not os.path.exists(path):
        Image.fromarray(arr, "RGB").save(path, format="PNG")
    return path


def waveform_of(audio: Any, socket: str) -> tuple[Any, int]:
    """A ComfyUI AUDIO as (channels-by-samples array, sample rate).

    Read through the Mapping interface, which is the actual contract: the stock nodes do
    `audio["waveform"]` and never ask what class it is.
    """
    import numpy as np

    wf = audio.get("waveform") if isinstance(audio, Mapping) else None
    sr = int(audio.get("sample_rate") or 0) if isinstance(audio, Mapping) else 0
    if wf is None or not sr:
        raise ServiceError(
            f"{socket} is not a sound this node can read: an AUDIO carries a waveform and a sample "
            f"rate, and this one has {'no rate' if wf is not None else 'no waveform'}. Feed it from "
            "a Load Audio node, or from a video loader's audio output.")
    arr = wf.detach().cpu().numpy() if hasattr(wf, "detach") else np.asarray(wf)
    while arr.ndim > 2:
        arr = arr[0]
    if arr.ndim == 1:
        arr = arr[None, :]
    return arr, sr


def write_sound(audio: Any, socket: str, into: str) -> tuple[str, float]:
    """Write a ComfyUI AUDIO as a 16-bit wav using the standard library, so no install is asked for
    an encoder it might not have."""
    import numpy as np

    arr, sr = waveform_of(audio, socket)
    channels, samples = arr.shape
    pcm = (np.clip(arr.T, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()
    path = os.path.join(into, f"openh3ir_{slug(socket)}_"
                              f"{hashlib.sha256(pcm).hexdigest()[:16]}.wav")
    if not os.path.exists(path):
        with wave.open(path, "wb") as w:
            w.setnchannels(channels)
            w.setsampwidth(2)
            w.setframerate(sr)
            w.writeframes(pcm)
    return path, samples / float(sr)


def write_footage(frames: Any, audio: Any, socket: str, into: str) -> tuple[str, float, int]:
    """Encode a clip's frames, and its soundtrack when there is one, to a real mp4.

    A file rather than a tensor because the service runs ffprobe and ffmpeg over footage: it probes
    the duration and samples frames to look at them, and neither can be done to something that only
    exists in this process. ComfyUI's own video writer does the encoding, so the container and codec
    are the ones every other video node in the graph produces.

    Written at 24 fps whatever the source was, because that is the rate H3 reads footage at and the
    rate the stock node assumes when it packs the frames. Relabelling is the honest choice here: it
    makes the duration the service probes the same duration H3 will act on.
    """
    from fractions import Fraction

    n = int(frames.shape[0])
    if n < 5:
        raise ServiceError(
            f"{socket} has {n} frames, and H3 reads footage of 2 to 15 seconds at {FPS} fps. Feed a "
            "real clip rather than a still.")
    path = os.path.join(into,
                        f"openh3ir_{slug(socket)}_{digest(frames)[:16]}{digest(audio)[:8]}.mp4")
    if not os.path.exists(path):
        from comfy_api.latest import InputImpl, Types
        try:
            InputImpl.VideoFromComponents(
                Types.VideoComponents(images=frames, audio=audio,
                                      frame_rate=Fraction(FPS, 1))).save_to(path)
        except Exception as e:  # noqa: BLE001 - an unwritable clip must say so, not half-work
            raise ServiceError(
                f"{socket} could not be encoded to a file for the service to read "
                f"({type(e).__name__}: {e}). Its frames came from a loader this node could not "
                "re-encode; try Load Video (Upload).") from e
    return path, n / float(FPS), n
