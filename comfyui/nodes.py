"""One node that turns a sentence into a ready-to-sample H3 job.

It replaces a row of boxes that were all saying the same thing twice: the text node, the resolution
picker, the frame-count arithmetic, the model and VAE and text encoder loaders, and the H3
conditioning node itself. What comes out is the model, the conditioning and the latent, which is
everything a sampler needs.

Three ideas hold it together.

The socket you plug into is the job. A picture in `opening_frame` is the first frame of the video. A
picture in `reference_1` is something the shot should contain. Those are different tasks with
different weights behind them, so reading the answer off the sockets means the brief and the graph
cannot disagree. Nothing is inferred and there are no role dropdowns to get wrong.

The duration lives in one place. There is one seconds field, and the frame count it becomes is
computed once and used for both the brief and the latent. Two dials that both claim to set the length
is how you render eight seconds of a ten second script.

What people actually tune stays outside. The Turbo LoRA, the sigma shift, the step count, the
sampler, the decode and the save are all knobs with opinions attached, so they stay on the canvas
where you can reach them. What got swallowed is the plumbing nobody chooses.

Heavy imports happen inside functions. An exception while ComfyUI imports a custom node takes the
whole pack off the menu with a traceback nobody can act on.
"""
from __future__ import annotations

import hashlib
import os
import tempfile
from typing import Any

from .h3ir_client import (ASPECTS, CREATIVITY, DEFAULT_SERVER, EFFORT, PICTURE_SOCKETS,
                          ROLE_BY_SOCKET, SIZING, SOUND_SOCKETS, VIDEO_SOCKETS, ServiceError,
                          build_payload, check_mode, compile_brief, expected_mode,
                          inputs_fingerprint, plan_assets, render_fields, report, translate_path)

# H3 accepts nine pictures, three videos and three sounds. The sockets below are what this node
# exposes, which is a limit of the node and not of the model: the service will take more.

# H3's frame grid: 17k+5 at 24 fps. Computed here so the brief and the latent are built from one
# number, and so the node can say what it did before the service is even reached.
FPS = 24


def frames_for(seconds: float) -> int:
    n = max(5, round(float(seconds) * FPS))
    return n + (5 - (n % 17)) % 17


def _temp_dir() -> str:
    """A directory ComfyUI owns, falling back to the system temp outside it. Never next to this
    source: a node that writes into its own directory dirties a checkout and survives no update."""
    try:
        import folder_paths
        d = folder_paths.get_temp_directory()
    except Exception:  # noqa: BLE001 - running outside ComfyUI is a supported case
        d = os.path.join(tempfile.gettempdir(), "openh3ir")
    os.makedirs(d, exist_ok=True)
    return d


def _model_choices(kind: str) -> list[str]:
    """Whatever this ComfyUI has, so the dropdowns are real rather than a guess about someone's
    disk. Empty outside ComfyUI, which is fine: the schema is only drawn inside it."""
    try:
        import folder_paths
        return list(folder_paths.get_filename_list(kind))
    except Exception:  # noqa: BLE001
        return []


def _default_like(options: list[str], *candidates: tuple[str, ...]) -> str:
    """Pre-select a sensible file, trying each candidate set of needles in order.

    Candidates are ordered rather than combined because "video" alone matched an LTX VAE on a box
    that also had H3's, and a plausible default from the wrong model family is worse than no default:
    it loads, and then the render is wrong for a reason nobody can see. So the family is matched
    first, and the loose match is only a fallback.

    Falling back to the first option keeps the dropdown valid on an install with none of these
    files. It can still be the wrong family, which is why the report names every file it loaded.
    """
    for needles in candidates:
        for o in options:
            low = o.lower()
            if all(n in low for n in needles):
                return o
    return options[0] if options else ""


def _to_uint8_rgb(image: Any, socket: str) -> Any:
    """One image tensor to HxWx3 uint8, refusing anything ambiguous.

    A socket carrying several pictures is an error rather than a silent choice of the first. Which
    reference was meant is not guessable, and the order decides which subject binds to which plate.
    """
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


def _write_picture(image: Any, socket: str) -> str:
    """Write one picture out as a PNG. The filename is a content hash, so an unchanged picture keeps
    its path between runs and the service's own hash of the file stays stable."""
    from PIL import Image

    arr = _to_uint8_rgb(image, socket)
    digest = hashlib.sha256(arr.tobytes()).hexdigest()[:16]
    path = os.path.join(_temp_dir(), f"openh3ir_{socket}_{digest}.png")
    if not os.path.exists(path):
        Image.fromarray(arr, "RGB").save(path, format="PNG")
    return path


def _write_sound(audio: dict[str, Any], socket: str) -> tuple[str, float]:
    """Write a ComfyUI AUDIO out as a 16-bit wav, using the standard library only.

    Returns the path and its duration. A real file is needed because the service reads assets from
    disk, and wav via `wave` avoids asking a ComfyUI install for an encoder it may not have.
    """
    import wave

    import numpy as np

    wf = audio.get("waveform")
    sr = int(audio.get("sample_rate") or 0)
    if wf is None or not sr:
        raise ServiceError(f"{socket} is not a sound this node can read (no waveform or no rate).")
    arr = wf.detach().cpu().numpy() if hasattr(wf, "detach") else np.asarray(wf)
    while arr.ndim > 2:            # [batch, channels, samples] -> first item
        arr = arr[0]
    if arr.ndim == 1:
        arr = arr[None, :]
    channels, samples = arr.shape
    inter = np.clip(arr.T, -1.0, 1.0)
    pcm = (inter * 32767.0).astype("<i2").tobytes()
    digest = hashlib.sha256(pcm).hexdigest()[:16]
    path = os.path.join(_temp_dir(), f"openh3ir_{socket}_{digest}.wav")
    if not os.path.exists(path):
        with wave.open(path, "wb") as w:
            w.setnchannels(channels)
            w.setsampwidth(2)
            w.setframerate(sr)
            w.writeframes(pcm)
    return path, samples / float(sr)


def _write_video(video: Any, socket: str) -> tuple[str, float, int, Any]:
    """Write a ComfyUI VIDEO to a real file and hand back its frames too.

    The service needs a file it can open, and the H3 node needs the frames. Both come from the video
    object itself rather than from a re-encode, so the two halves are looking at the same footage.
    """
    digest = hashlib.sha256(f"{socket}:{id(video)}".encode()).hexdigest()[:16]
    path = os.path.join(_temp_dir(), f"openh3ir_{socket}_{digest}.mp4")
    try:
        video.save_to(path)
        comp = video.get_components()
        duration = float(video.get_duration())
        frames = int(video.get_frame_count())
    except Exception as e:  # noqa: BLE001 - a video we cannot read must say so, not half-work
        raise ServiceError(
            f"{socket} could not be written out for the service to read ({type(e).__name__}: {e}). "
            "Feed it from a Load Video node.") from e
    return path, duration, frames, getattr(comp, "images", None)


def _digest(obj: Any) -> str:
    """Content hash of a picture or a sound, so a re-queue reacts to what actually changed."""
    if obj is None:
        return "none"
    try:
        import numpy as np
        wf = obj.get("waveform") if isinstance(obj, dict) else obj
        if wf is None:
            return "none"
        arr = wf.detach().cpu().numpy() if hasattr(wf, "detach") else np.asarray(wf)
        return hashlib.sha256(np.ascontiguousarray(arr).tobytes()).hexdigest()
    except Exception:  # noqa: BLE001
        return "unhashable"


class OpenH3IRCompile:
    """Sentence in; model, conditioning and latent out, ready for a sampler."""

    @classmethod
    def INPUT_TYPES(cls) -> dict[str, Any]:
        unets = _model_choices("diffusion_models")
        clips = _model_choices("text_encoders")
        vaes = _model_choices("vae")
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
                    "tooltip": "How long it should be, and the only place length is set. H3 only "
                               "renders on a 17k+5 frame grid, so this is snapped once and used "
                               "for both the brief and the latent. Ask for 10 and you get 10.125. "
                               "Exactly one whole second exists in the trained range, and it is 8."}),
                "aspect": (list(ASPECTS), {
                    "default": "16:9",
                    "tooltip": "Frame shape. The canvas is sized from this, so there is no "
                               "resolution box to keep in step."}),
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
                               "with h3ir serve."}),
                "reference_model": (unets, {
                    "default": _default_like(unets, ("ref2va", "int8"), ("ref2va",)),
                    "tooltip": "The H3 weights used when the job is references or text only. Set "
                               "once and forget."}),
                "frames_model": (unets, {
                    "default": _default_like(unets, ("fl2va", "int8"), ("fl2va",)),
                    "tooltip": "The H3 weights used when you plug into opening_frame or "
                               "closing_frame. First and last frame work has its own checkpoint, "
                               "and the node picks between the two for you."}),
                "text_encoder": (clips, {
                    "default": _default_like(clips, ("minimax",)),
                    "tooltip": "The Qwen3-VL encoder H3 was trained against."}),
                "video_vae": (vaes, {
                    "default": _default_like(vaes, ("minimax", "video"), ("h3", "video")),
                    "tooltip": "H3's picture VAE."}),
                "audio_vae": (vaes, {
                    "default": _default_like(vaes, ("minimax", "audio"), ("h3", "audio")),
                    "tooltip": "H3's sound VAE. H3 writes picture and sound in one pass, so this "
                               "is needed even for a silent piece."}),
            },
            "optional": {
                "opening_frame": ("IMAGE", {
                    "tooltip": "The first frame of the video. Plugging in here says the picture IS "
                               "the start, which is a different job from a reference and uses the "
                               "first-and-last-frame weights."}),
                "closing_frame": ("IMAGE", {
                    "tooltip": "The last frame of the video."}),
                "reference_1": ("IMAGE", {
                    "tooltip": "Something the shot should contain: a person, a car, a room. Becomes "
                               "<Picture 1>, which is how a subject in the brief binds to it."}),
                "reference_2": ("IMAGE", {"tooltip": "Becomes <Picture 2>."}),
                "reference_3": ("IMAGE", {"tooltip": "Becomes <Picture 3>."}),
                "reference_4": ("IMAGE", {"tooltip": "Becomes <Picture 4>."}),
                "picture_notes": ("STRING", {
                    "multiline": True, "default": "",
                    "tooltip": "One short line per connected picture, same order, saying what it "
                               "is: the man, the car, the room. Never required, and often the "
                               "difference between the right subject being described."}),
                "video_to_edit": ("VIDEO", {
                    "tooltip": "Footage the piece is a change to. Its soundtrack goes along with "
                               "it automatically."}),
                "video_to_continue": ("VIDEO", {
                    "tooltip": "Footage the piece carries on from."}),
                "music": ("AUDIO", {"tooltip": "A score to reuse or match."}),
                "sound_effect": ("AUDIO", {"tooltip": "An effect to reuse or match."}),
                "voice_to_match": ("AUDIO", {
                    "tooltip": "A voice whose timbre should be matched. Put what it says in "
                               "spoken_words, because nothing in this chain can hear."}),
                "sound_notes": ("STRING", {
                    "multiline": True, "default": "",
                    "tooltip": "One line per connected sound, in socket order, describing timbre, "
                               "delivery or tempo. A transcript gives the words only."}),
                "spoken_words": ("STRING", {
                    "multiline": True, "default": "",
                    "tooltip": "Exactly what the voice clip says. Nothing here can listen, and a "
                               "model asked about a waveform invents a plausible answer, so the "
                               "words have to be typed or run through a real recogniser."}),
                "sizing": (list(SIZING), {
                    "default": "match",
                    "tooltip": "How references get scaled. match fits each to the render's pixel "
                               "area; max keeps the reference's own size for stronger identity and "
                               "is slower, because reference tokens ride every sampling step."}),
                "seed": ("INT", {
                    "default": 7, "min": 0, "max": 0xFFFFFFFFFFFFFF,
                    "tooltip": "The compiler is seeded, so the same inputs give the same brief. "
                               "Change this for a different take on the same sentence. It is not "
                               "the sampler's seed."}),
                "effort": (list(EFFORT), {
                    "default": "standard",
                    "tooltip": "How hard the writer works. max asks for reasoning prose and is "
                               "slower."}),
                "shots": ("INT", {
                    "default": 0, "min": 0, "max": 8,
                    "tooltip": "Force a number of shots. 0 lets the compiler decide, which is "
                               "usually right, because the cut times land on the frame grid too."}),
                "silent": ("BOOLEAN", {
                    "default": False,
                    "tooltip": "No score and no dialogue. H3 makes sound in the same pass as the "
                               "picture, so silence is a decision rather than an absence."}),
                "weight_dtype": (["default", "fp8_e4m3fn", "fp8_e4m3fn_fast", "fp8_e5m2"], {
                    "default": "default",
                    "tooltip": "How the weights are loaded, same as on a UNET loader. Leave alone "
                               "unless you are short of VRAM."}),
                "timeout_s": ("INT", {
                    "default": 600, "min": 10, "max": 3600,
                    "tooltip": "Writing a brief is one call to your language model, so this is as "
                               "slow as that model is."}),
                "comfy_path_prefix": ("STRING", {
                    "default": "",
                    "tooltip": "Only needed when ComfyUI and the service see the disk differently, "
                               "for example ComfyUI on Windows and the service in WSL. ComfyUI's "
                               "spelling of a shared folder, such as C:\\ComfyUI."}),
                "service_path_prefix": ("STRING", {
                    "default": "",
                    "tooltip": "The same folder as the service spells it, such as /mnt/c/ComfyUI. "
                               "Leave both empty when they share one view of the disk."}),
            },
        }

    RETURN_TYPES = ("MODEL", "CONDITIONING", "LATENT", "VAE", "VAE", "STRING", "STRING")
    RETURN_NAMES = ("model", "positive", "latent", "vae", "audio_vae", "prompt", "report")
    OUTPUT_TOOLTIPS = (
        "The H3 model, already the right one for the job. Feed your Turbo LoRA and sigma shift from "
        "here.",
        "Conditioning for the guider.",
        "The empty picture and sound latent, already the length the brief was written for.",
        "H3's picture VAE, for the decode. Passed out so the graph needs no loader boxes.",
        "H3's sound VAE, for the audio decode.",
        "The compiled brief, if you want to read or keep it.",
        "What happened, in plain words: the job, the real length, and which picture became which.",
    )
    FUNCTION = "compile"
    CATEGORY = "OpenH3-IR"
    DESCRIPTION = ("One sentence to a ready H3 job: writes the brief, picks the weights, loads the "
                   "encoder and VAEs, and hands out model, conditioning and latent.")

    @classmethod
    def IS_CHANGED(cls, **kwargs: Any) -> str:
        """Re-run when something changed, and never otherwise. The compiler is seeded, so an
        unchanged graph re-queued would spend a model call to produce the same brief."""
        media = {k: _digest(kwargs.pop(k, None))
                 for k in list(ROLE_BY_SOCKET) if k in kwargs or True}
        return inputs_fingerprint(sorted(kwargs.items()), sorted(media.items()))

    # ------------------------------------------------------------------ the work

    def compile(self, intent: str, seconds: float, aspect: str, creativity: str, server: str,
                reference_model: str, frames_model: str, text_encoder: str, video_vae: str,
                audio_vae: str, picture_notes: str = "", sound_notes: str = "",
                spoken_words: str = "", sizing: str = "match", seed: int = 7,
                effort: str = "standard", shots: int = 0, silent: bool = False,
                weight_dtype: str = "default", timeout_s: int = 600,
                comfy_path_prefix: str = "", service_path_prefix: str = "",
                **media: Any) -> tuple[Any, Any, Any, Any, Any, str, str]:
        opening = media.get("opening_frame")
        closing = media.get("closing_frame")
        pictures = [(s, media.get(s)) for s in PICTURE_SOCKETS if media.get(s) is not None]
        videos = [(s, media.get(s)) for s in VIDEO_SOCKETS if media.get(s) is not None]
        sounds = [(s, media.get(s)) for s in SOUND_SOCKETS if media.get(s) is not None]

        if (opening is not None or closing is not None) and (pictures or videos):
            raise ServiceError(
                "this is two different jobs at once. opening_frame and closing_frame say a picture "
                "is a frame of the video; reference sockets say a picture is something the shot "
                "should contain. H3 does one or the other, so unplug whichever you did not mean.")

        declared = expected_mode(opening is not None, closing is not None, len(pictures),
                                 len(videos))

        assets, transcripts, video_frames, paired_sound = self._gather(
            opening, closing, pictures, videos, sounds, picture_notes, sound_notes, spoken_words,
            sizing, comfy_path_prefix, service_path_prefix)

        payload = build_payload(intent, seconds=seconds, aspect=aspect, creativity=creativity,
                                effort=effort, seed=seed, silent=silent, shots=shots,
                                assets=assets, transcripts=transcripts)
        body = compile_brief(server, payload, timeout=float(timeout_s))
        prompt, width, height, length, ref_sizing = render_fields(body)

        warning = check_mode(declared, str(body.get("mode", "")))

        model = self._load_model(frames_model if declared in ("i2va", "l2va", "fl2va")
                                 else reference_model, weight_dtype)
        clip = self._load_clip(text_encoder)
        vae = self._load_vae(video_vae)
        avae = self._load_vae(audio_vae)

        positive, latent = self._condition(
            declared=declared, clip=clip, vae=vae, audio_vae=avae, prompt=prompt,
            width=width, height=height, length=length, ref_image_size=ref_sizing,
            opening=opening, closing=closing, pictures=pictures, video_frames=video_frames,
            paired_sound=paired_sound, sounds=sounds)

        wiring = body.get("wiring") or []
        conflict = len({w.get("sizing") for w in wiring if w.get("sizing")}) > 1
        text = report(body, server=server, sizing_conflict=conflict)
        frames_job = declared in ("i2va", "l2va", "fl2va")
        text += f"\njob            {declared}"
        text += f"\nweights        {frames_model if frames_job else reference_model}"
        text += f"\nencoder        {text_encoder}"
        text += f"\nvaes           {video_vae}  +  {audio_vae}"
        if warning:
            text += "\nWARNING        " + warning
            print("[OpenH3-IR] " + warning)
        print(f"[OpenH3-IR] {declared}: {length} frames ({length / FPS:.3f}s), {width}x{height}")
        return (model, positive, latent, vae, avae, prompt, text)

    # ------------------------------------------------------------------ helpers

    def _gather(self, opening, closing, pictures, videos, sounds, picture_notes, sound_notes,
                spoken_words, sizing, from_prefix, to_prefix):
        """Write every attached thing to disk, then let plan_assets describe it.

        Only the writing lives here, because only the writing needs ComfyUI. Ordering, roles and
        notes are decided in `h3ir_client` where they can be tested without a canvas.
        """
        written: list[tuple[str, str, str, dict[str, Any]]] = []
        video_frames: list[Any] = []

        ordered = ([("opening_frame", opening)] if opening is not None else []) \
            + ([("closing_frame", closing)] if closing is not None else []) \
            + pictures
        for socket, img in ordered:
            written.append((socket, "image", _write_picture(img, socket), {}))

        for socket, vid in videos:
            path, dur, frames, imgs = _write_video(vid, socket)
            written.append((socket, "video", path, {"seconds": round(dur, 3), "frames": frames}))
            if imgs is not None:
                video_frames.append(imgs)

        transcripts: dict[str, str] = {}
        for socket, snd in sounds:
            path, dur = _write_sound(snd, socket)
            written.append((socket, "audio", path, {"seconds": round(dur, 3)}))
            if socket == "voice_to_match" and (spoken_words or "").strip():
                # The service keys transcripts by the file's own hash, computed here from the very
                # bytes the service will read.
                transcripts[_sha256_file(path)] = spoken_words.strip()

        assets = plan_assets(written, list((picture_notes or "").splitlines()),
                             list((sound_notes or "").splitlines()), sizing, from_prefix, to_prefix)
        return assets, transcripts, video_frames, []

    def _load_model(self, name: str, weight_dtype: str):
        if not name:
            raise ServiceError(
                "no H3 weights selected. Pick a checkpoint in reference_model, and in "
                "frames_model if you use opening_frame or closing_frame.")
        import nodes
        return nodes.NODE_CLASS_MAPPINGS["UNETLoader"]().load_unet(name, weight_dtype)[0]

    def _load_clip(self, name: str):
        if not name:
            raise ServiceError("no text encoder selected. H3 needs its Qwen3-VL encoder.")
        import nodes
        loader = nodes.NODE_CLASS_MAPPINGS["CLIPLoader"]()
        try:
            return loader.load_clip(name, "minimax", "default")[0]
        except TypeError:
            return loader.load_clip(name, "minimax")[0]

    def _load_vae(self, name: str):
        if not name:
            raise ServiceError("both VAEs have to be selected. H3 writes picture and sound "
                               "together, so it needs each one.")
        import nodes
        return nodes.NODE_CLASS_MAPPINGS["VAELoader"]().load_vae(name)[0]

    def _condition(self, *, declared, clip, vae, audio_vae, prompt, width, height, length,
                   ref_image_size, opening, closing, pictures, video_frames, paired_sound, sounds):
        """Hand the work to ComfyUI's own H3 nodes rather than reimplementing their conditioning.

        Those nodes own how references are tokenised and how the latent is packed. Copying that here
        would leave two versions of it to keep in step, and the copy would be the one that rots.
        """
        from comfy_extras.nodes_minimax_h3 import (MiniMaxH3ImageToVideo,
                                                  MiniMaxH3ReferenceToVideo)

        if declared in ("i2va", "l2va", "fl2va"):
            out = MiniMaxH3ImageToVideo.execute(
                clip=clip, vae=vae, prompt=prompt, width=width, height=height, length=length,
                first_frame=opening, last_frame=closing)
            return tuple(out.result)

        ref_images = {f"ref_image_{i}": img for i, (_s, img) in enumerate(pictures, 1)}
        ref_videos = {f"ref_video_{i}": f for i, f in enumerate(video_frames, 1)}
        ref_audios = {f"ref_audio_{i}": snd for i, (_s, snd) in enumerate(sounds, 1)}
        out = MiniMaxH3ReferenceToVideo.execute(
            clip=clip, vae=vae, audio_vae=audio_vae, prompt=prompt, width=width, height=height,
            length=length, ref_image_size=ref_image_size,
            ref_images=ref_images or None, ref_videos=ref_videos or None,
            ref_audios=ref_audios or None)
        return tuple(out.result)


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class OpenH3IRShowText:
    """Display any text output on the canvas, so the report can be read without a detour."""

    @classmethod
    def INPUT_TYPES(cls) -> dict[str, Any]:
        return {"required": {"text": ("STRING", {
            "forceInput": True,
            "tooltip": "Any text output, such as the report or the brief itself."})}}

    RETURN_TYPES = ()
    FUNCTION = "show"
    OUTPUT_NODE = True
    CATEGORY = "OpenH3-IR"
    DESCRIPTION = "Show a text output, such as the report or the brief itself."

    def show(self, text: str) -> dict[str, Any]:
        return {"ui": {"text": [text if isinstance(text, str) else str(text)]}}


NODE_CLASS_MAPPINGS = {
    "OpenH3IRCompile": OpenH3IRCompile,
    "OpenH3IRShowText": OpenH3IRShowText,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "OpenH3IRCompile": "OpenH3-IR",
    "OpenH3IRShowText": "OpenH3-IR Show Text",
}

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "ServiceError"]
