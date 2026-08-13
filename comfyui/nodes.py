"""One node that turns a sentence into a ready-to-sample MiniMax H3 job.

It replaces the text box, the resolution picker, the frame-count arithmetic, the model, encoder and
VAE loaders, and the H3 conditioning node. Out comes the model, the conditioning, the latent and both
VAEs, which is everything the rest of the graph needs.

Four ideas hold it together.

The socket you plug into is the job. A picture in the first-frame socket IS the opening frame of the
video. A picture in a reference socket is something the shot should contain. Those are different tasks
with different H3 checkpoints behind them, so reading the answer off the sockets means the brief and
the graph cannot disagree. Nothing is inferred and there are no role dropdowns to get wrong.

Length lives in one place. One seconds field, snapped once to H3's frame grid, used for both the brief
and the latent. Two dials that both claim to set the duration is how eight seconds of a ten second
script gets rendered.

The reference list grows as it is filled, so an idle node shows one socket rather than nine.

What people actually tune stays on the canvas: LoRAs, sigma shift, steps, sampler, decode, save. Only
the plumbing nobody chooses between got swallowed.

This uses ComfyUI's current node schema, the same one the stock H3 nodes use, so any ComfyUI that can
render H3 can load this. Heavy imports stay inside the functions that need them: an exception while
ComfyUI imports a custom node takes the whole pack off the menu with a traceback nobody can act on.
"""
from __future__ import annotations

import hashlib
import os
import tempfile
from typing import Any

from comfy_api.latest import ComfyExtension, io

from .h3ir_client import (ASPECTS, CREATIVITY, DEFAULT_SERVER, EFFORT, SIZING, SOUND_SOCKETS,
                          VIDEO_SOCKETS, ServiceError, build_payload, check_mode, compile_brief,
                          expected_mode, inputs_fingerprint, path_candidates, plan_assets,
                          render_fields, report, retranslate)

FPS = 24
# H3 takes nine reference pictures. The list grows one socket at a time, so the node stays small until
# the work needs the room.
MAX_REFERENCES = 9


def frames_for(seconds: float) -> int:
    """H3's grid: 17k+5 at 24 fps. Computed here as well as server-side so one number feeds both the
    brief and the latent."""
    n = max(5, round(float(seconds) * FPS))
    return n + (5 - (n % 17)) % 17


def _temp_dir() -> str:
    """A directory ComfyUI owns, falling back to the system temp outside it. Never beside this
    source: a node that writes into its own folder dirties a checkout and survives no update."""
    try:
        import folder_paths
        d = folder_paths.get_temp_directory()
    except Exception:  # noqa: BLE001 - importable outside ComfyUI is a supported case
        d = os.path.join(tempfile.gettempdir(), "openh3ir")
    os.makedirs(d, exist_ok=True)
    return d


def _comfy_root() -> str:
    """Where ComfyUI lives, asked of ComfyUI rather than typed by hand."""
    try:
        import folder_paths
        return str(folder_paths.base_path)
    except Exception:  # noqa: BLE001
        return ""


def _model_choices(kind: str) -> list[str]:
    """Whatever this install actually has, so the dropdowns are real rather than a guess about
    someone's disk."""
    try:
        import folder_paths
        return list(folder_paths.get_filename_list(kind))
    except Exception:  # noqa: BLE001
        return []


def _default_like(options: list[str], *candidates: tuple[str, ...]) -> str:
    """Pre-select a sensible file, trying each set of needles in order.

    Ordered rather than combined because "video" alone matched an LTX VAE on a box that also had
    H3's, and a plausible default from the wrong family is worse than none: it loads, and then the
    render is wrong for a reason nobody can see. Family first, loose match only as a fallback.
    """
    for needles in candidates:
        for o in options:
            low = o.lower()
            if all(n in low for n in needles):
                return o
    return options[0] if options else ""


def _to_uint8_rgb(image: Any, socket: str) -> Any:
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


def _write_picture(image: Any, socket: str) -> str:
    """Write one picture as a PNG named by its content, so an unchanged picture keeps its path and
    the service's own hash of the file stays stable."""
    from PIL import Image

    arr = _to_uint8_rgb(image, socket)
    digest = hashlib.sha256(arr.tobytes()).hexdigest()[:16]
    path = os.path.join(_temp_dir(), f"openh3ir_{socket}_{digest}.png")
    if not os.path.exists(path):
        Image.fromarray(arr, "RGB").save(path, format="PNG")
    return path


def _write_sound(audio: Any, socket: str) -> tuple[str, float]:
    """Write a ComfyUI AUDIO as a 16-bit wav using the standard library, so no install is asked for
    an encoder it might not have."""
    import wave

    import numpy as np

    wf = audio.get("waveform") if isinstance(audio, dict) else None
    sr = int((audio or {}).get("sample_rate") or 0) if isinstance(audio, dict) else 0
    if wf is None or not sr:
        raise ServiceError(f"{socket} is not a sound this node can read (no waveform or no rate).")
    arr = wf.detach().cpu().numpy() if hasattr(wf, "detach") else np.asarray(wf)
    while arr.ndim > 2:
        arr = arr[0]
    if arr.ndim == 1:
        arr = arr[None, :]
    channels, samples = arr.shape
    pcm = (np.clip(arr.T, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()
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
    """Write a ComfyUI VIDEO to a real file and hand back its frames, both taken from the video
    object, so the service and H3 are looking at the same footage."""
    digest = hashlib.sha256(f"{socket}:{id(video)}".encode()).hexdigest()[:16]
    path = os.path.join(_temp_dir(), f"openh3ir_{socket}_{digest}.mp4")
    try:
        video.save_to(path)
        comp = video.get_components()
        duration = float(video.get_duration())
        frames = int(video.get_frame_count())
    except Exception as e:  # noqa: BLE001 - an unreadable video must say so, not half-work
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
        if isinstance(obj, dict):
            obj = obj.get("waveform")
        if obj is None:
            return "none"
        arr = obj.detach().cpu().numpy() if hasattr(obj, "detach") else np.asarray(obj)
        return hashlib.sha256(np.ascontiguousarray(arr).tobytes()).hexdigest()
    except Exception:  # noqa: BLE001 - a hash we cannot take must not break the graph
        return "unhashable"


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class OpenH3IRCompile(io.ComfyNode):
    """Sentence in; model, conditioning, latent and both VAEs out."""

    @classmethod
    def define_schema(cls) -> io.Schema:
        unets = _model_choices("diffusion_models")
        clips = _model_choices("text_encoders")
        vaes = _model_choices("vae")
        return io.Schema(
            node_id="OpenH3IRCompile",
            display_name="OpenH3-IR",
            category="OpenH3-IR",
            description=("One sentence to a ready H3 job: writes the brief H3 wants, picks the right "
                         "weights, loads the encoder and VAEs, and outputs model, conditioning and "
                         "latent."),
            inputs=[
                # ------------------------------------------------- what you are asking for
                io.String.Input(
                    "intent", display_name="what happens", multiline=True, default="",
                    placeholder="she walks out onto the wet gantry in the rain and stops when she "
                                "sees the city below",
                    tooltip="One ordinary sentence. Not a tag list and not a shot breakdown, "
                            "because the compiler writes those. Say the action and the beat you "
                            "care about."),
                io.Float.Input(
                    "seconds", display_name="how long, in seconds", default=8.0, min=1.0, max=60.0,
                    step=0.1,
                    tooltip="The only place length is set. H3 renders on a 17k+5 frame grid, so this "
                            "is snapped once and used for both the brief and the latent. Ask for 10 "
                            "and you get 10.125. Exactly one whole second exists in the trained "
                            "range, and it is 8."),
                io.Combo.Input(
                    "aspect", display_name="frame shape", options=list(ASPECTS), default="16:9",
                    tooltip="The canvas is sized from this, so there is no resolution box to keep "
                            "in step with anything."),
                io.Combo.Input(
                    "creativity", display_name="how much it may invent", options=list(CREATIVITY),
                    default="balanced",
                    tooltip="restrained keeps to your sentence. balanced shapes it, and scores it if "
                            "it wants scoring. bold and extreme may add a spoken line, music, "
                            "on-screen text or a beat of their own. Saying no dialogue in your "
                            "sentence still means no dialogue at every setting."),
                io.Boolean.Input(
                    "silent", display_name="no music or speech", default=False,
                    tooltip="H3 writes sound in the same pass as the picture, so silence is a "
                            "decision rather than an absence. It belongs with the rest of what you "
                            "are asking for, which is why it sits here."),
                io.Int.Input(
                    "shots", display_name="how many shots, 0 to decide for me", default=0, min=0,
                    max=8,
                    tooltip="0 is usually right: cut times have to land on the frame grid too, and "
                            "the compiler knows where they can go."),

                # ------------------------------------------------- what it should look at
                io.Image.Input(
                    "opening_frame", display_name="first frame of the video", optional=True,
                    tooltip="The video STARTS on this picture. That is a different job from a "
                            "reference, and it uses H3's first-and-last-frame weights, which this "
                            "node loads for you."),
                io.Image.Input(
                    "closing_frame", display_name="last frame of the video", optional=True,
                    tooltip="The video ENDS on this picture."),
                io.Autogrow.Input(
                    "references", display_name="things the shot should contain", optional=True,
                    template=io.Autogrow.TemplatePrefix(
                        input=io.Image.Input(
                            "reference", display_name="a thing in the shot",
                            tooltip="A person, a car, a room. The first becomes <Picture 1>, which "
                                    "is how a subject in the brief binds to it. Another socket "
                                    "appears once this one is filled."),
                        prefix="reference_", min=0, max=MAX_REFERENCES)),
                io.String.Input(
                    "picture_notes", display_name="what each picture is", multiline=True,
                    optional=True, default="",
                    placeholder="one short line per picture, in order\nthe man\nthe car\nthe empty "
                                "showroom",
                    tooltip="Never required, and often the difference between the right subject "
                            "being described and the wrong one."),
                io.Video.Input(
                    "video_to_edit", display_name="footage this changes", optional=True,
                    tooltip="Footage the piece is an edit of. Its soundtrack comes along with it."),
                io.Video.Input(
                    "video_to_continue", display_name="footage this carries on from", optional=True,
                    tooltip="Footage the piece continues from."),
                io.Audio.Input(
                    "music", display_name="music to reuse or match", optional=True),
                io.Audio.Input(
                    "sound_effect", display_name="sound effect to reuse or match", optional=True),
                io.Audio.Input(
                    "voice_to_match", display_name="voice to match", optional=True,
                    tooltip="A voice whose timbre should be matched. Type what it says below."),
                io.String.Input(
                    "sound_notes", display_name="how the sounds should feel", multiline=True,
                    optional=True, default="",
                    placeholder="one line per sound, in order\na slow synth score, no drums\na "
                                "heavy door slamming",
                    tooltip="Timbre, delivery, tempo. A transcript gives the words only, so "
                            "everything else about a sound has to be said here."),
                io.String.Input(
                    "spoken_words", display_name="what the voice says", multiline=True,
                    optional=True, default="",
                    placeholder="type the words in the voice clip, exactly as spoken",
                    tooltip="Nothing in this chain can hear. A model asked about a waveform invents "
                            "a plausible answer instead of admitting it cannot listen, so the words "
                            "are typed or run through a real recogniser."),

                # ------------------------------------------------- where, and with what
                io.String.Input(
                    "server", display_name="OpenH3-IR service address", default=DEFAULT_SERVER,
                    tooltip="Where the service is listening. Start one from the repo with h3ir "
                            "serve. It can be another machine."),
                io.Combo.Input(
                    "reference_model", display_name="H3 weights for reference and text jobs",
                    options=unets, default=_default_like(unets, ("ref2va", "int8"), ("ref2va",)),
                    tooltip="Set once and forget."),
                io.Combo.Input(
                    "frames_model", display_name="H3 weights for first and last frame jobs",
                    options=unets, default=_default_like(unets, ("fl2va", "int8"), ("fl2va",)),
                    tooltip="Frame work has its own checkpoint, and the node chooses between the two "
                            "from which sockets you filled."),
                io.Combo.Input(
                    "text_encoder", display_name="text encoder", options=clips,
                    default=_default_like(clips, ("minimax",)),
                    tooltip="The Qwen3-VL encoder H3 was trained against."),
                io.Combo.Input(
                    "video_vae", display_name="picture VAE", options=vaes,
                    default=_default_like(vaes, ("minimax", "video"), ("h3", "video"))),
                io.Combo.Input(
                    "audio_vae", display_name="sound VAE", options=vaes,
                    default=_default_like(vaes, ("minimax", "audio"), ("h3", "audio")),
                    tooltip="Needed even for a silent piece, because H3 writes picture and sound "
                            "together."),

                # ------------------------------------------------- rarely touched
                io.Combo.Input(
                    "sizing", display_name="reference scaling", options=list(SIZING),
                    default="match", optional=True, advanced=True,
                    tooltip="match fits each reference to the render's pixel area. max keeps the "
                            "reference's own size for stronger identity and is slower, because "
                            "reference tokens ride every sampling step."),
                io.Int.Input(
                    "seed", display_name="brief seed", default=7, min=0, max=0xFFFFFFFFFFFFFF,
                    optional=True, advanced=True,
                    tooltip="The compiler is seeded, so the same inputs give the same brief. Change "
                            "this for a different take on the same sentence. This is not the "
                            "sampler's seed."),
                io.Combo.Input(
                    "effort", display_name="writing effort", options=list(EFFORT),
                    default="standard", optional=True, advanced=True,
                    tooltip="max asks for reasoning prose and is slower."),
                io.Combo.Input(
                    "weight_dtype", display_name="weight precision",
                    options=["default", "fp8_e4m3fn", "fp8_e4m3fn_fast", "fp8_e5m2"],
                    default="default", optional=True, advanced=True,
                    tooltip="The same setting a UNET loader has. Leave alone unless you are short "
                            "of VRAM."),
                io.Int.Input(
                    "timeout_s", display_name="give up after, in seconds", default=600, min=10,
                    max=3600, optional=True, advanced=True,
                    tooltip="Writing a brief is one call to your language model, so this is as slow "
                            "as that model is."),
                io.String.Input(
                    "service_sees_comfy_at", display_name="where the service sees ComfyUI's folder",
                    default="", optional=True, advanced=True,
                    placeholder="usually blank, worked out automatically",
                    tooltip="For setups the node cannot work out alone. ComfyUI's own folder is "
                            "found automatically, and when the service reads the disk differently, "
                            "for example ComfyUI on Windows with the service in WSL, the usual "
                            "spellings are tried and checked. Fill this only if it reports that it "
                            "could not find one that works."),
            ],
            outputs=[
                io.Model.Output(display_name="model",
                                tooltip="Already the right H3 checkpoint for the job. Feed your "
                                        "LoRAs and sigma shift from here."),
                io.Conditioning.Output(display_name="positive"),
                io.Latent.Output(display_name="latent",
                                 tooltip="Empty picture and sound latent, already the length the "
                                         "brief was written for."),
                io.Vae.Output(display_name="vae",
                              tooltip="H3's picture VAE for the decode, so the graph needs no "
                                      "loader boxes."),
                io.Vae.Output(display_name="audio_vae", tooltip="H3's sound VAE."),
                io.String.Output(display_name="prompt",
                                 tooltip="The compiled brief, to read or to keep."),
                io.String.Output(display_name="report",
                                 tooltip="What happened in plain words: the job, the real length, "
                                         "which picture became which, and every file loaded."),
            ],
        )

    @classmethod
    def fingerprint_inputs(cls, **kwargs: Any) -> Any:
        """Re-run when something changed and never otherwise. The compiler is seeded, so an unchanged
        graph re-queued would spend a model call to produce the same brief."""
        refs = kwargs.pop("references", None) or {}
        media = [_digest(v) for _k, v in sorted(refs.items())]
        for key in ("opening_frame", "closing_frame", *VIDEO_SOCKETS, *SOUND_SOCKETS):
            media.append(_digest(kwargs.pop(key, None)))
        return inputs_fingerprint(sorted((k, repr(v)) for k, v in kwargs.items()), media)

    # ------------------------------------------------------------------ the work

    @classmethod
    def execute(cls, intent: str, seconds: float, aspect: str, creativity: str, silent: bool,
                shots: int, server: str, reference_model: str, frames_model: str,
                text_encoder: str, video_vae: str, audio_vae: str, opening_frame=None,
                closing_frame=None, references=None, picture_notes: str = "", video_to_edit=None,
                video_to_continue=None, music=None, sound_effect=None, voice_to_match=None,
                sound_notes: str = "", spoken_words: str = "", sizing: str = "match",
                seed: int = 7, effort: str = "standard", weight_dtype: str = "default",
                timeout_s: int = 600, service_sees_comfy_at: str = "") -> io.NodeOutput:
        refs = [(k, v) for k, v in sorted((references or {}).items()) if v is not None]
        videos = [(s, v) for s, v in (("video_to_edit", video_to_edit),
                                      ("video_to_continue", video_to_continue)) if v is not None]
        sounds = [(s, v) for s, v in (("music", music), ("sound_effect", sound_effect),
                                      ("voice_to_match", voice_to_match)) if v is not None]

        if (opening_frame is not None or closing_frame is not None) and (refs or videos):
            raise ServiceError(
                "this is two different jobs at once. The first and last frame sockets say a picture "
                "is a frame of the video; the reference sockets say a picture is something the shot "
                "should contain. H3 does one or the other, so unplug whichever you did not mean.")

        declared = expected_mode(opening_frame is not None, closing_frame is not None, len(refs),
                                 len(videos))

        written, transcripts, video_frames = cls._write_everything(
            opening_frame, closing_frame, refs, videos, sounds, spoken_words)

        body, used_prefix = cls._compile_where_the_service_can_read(
            server=server, written=written, picture_notes=picture_notes, sound_notes=sound_notes,
            sizing=sizing, transcripts=transcripts, override=service_sees_comfy_at,
            timeout=float(timeout_s),
            brief=dict(intent=intent, seconds=seconds, aspect=aspect, creativity=creativity,
                       effort=effort, seed=seed, silent=silent, shots=shots))

        prompt, width, height, length, ref_sizing = render_fields(body)
        warning = check_mode(declared, str(body.get("mode", "")))
        frames_job = declared in ("i2va", "l2va", "fl2va")

        model = cls._load_model(frames_model if frames_job else reference_model, weight_dtype)
        clip = cls._load_clip(text_encoder)
        vae = cls._load_vae(video_vae)
        avae = cls._load_vae(audio_vae)

        positive, latent = cls._condition(
            declared=declared, clip=clip, vae=vae, audio_vae=avae, prompt=prompt, width=width,
            height=height, length=length, ref_image_size=ref_sizing, opening=opening_frame,
            closing=closing_frame, refs=refs, video_frames=video_frames, sounds=sounds)

        wiring = body.get("wiring") or []
        conflict = len({w.get("sizing") for w in wiring if w.get("sizing")}) > 1
        text = report(body, server=server, sizing_conflict=conflict)
        text += f"\njob            {declared}"
        text += f"\nweights        {frames_model if frames_job else reference_model}"
        text += f"\nencoder        {text_encoder}"
        text += f"\nvaes           {video_vae}  +  {audio_vae}"
        if used_prefix:
            text += f"\npaths          the service reads ComfyUI's folder at {used_prefix}"
        if warning:
            text += "\nWARNING        " + warning
            print("[OpenH3-IR] " + warning)
        print(f"[OpenH3-IR] {declared}: {length} frames ({length / FPS:.3f}s), {width}x{height}")
        return io.NodeOutput(model, positive, latent, vae, avae, prompt, text)

    # ------------------------------------------------------------------ helpers

    @classmethod
    def _write_everything(cls, opening, closing, refs, videos, sounds, spoken_words):
        """Put every attachment on disk. Only the writing lives here, because only the writing needs
        ComfyUI; ordering, roles and notes are decided in h3ir_client where they can be tested."""
        written: list[tuple[str, str, str, dict[str, Any]]] = []
        video_frames: list[Any] = []
        transcripts: dict[str, str] = {}

        ordered = ([("opening_frame", opening)] if opening is not None else []) \
            + ([("closing_frame", closing)] if closing is not None else [])
        for i, (_socket, img) in enumerate(refs, 1):
            ordered.append((f"reference_{min(i, MAX_REFERENCES)}", img))
        for socket, img in ordered:
            written.append((socket, "image", _write_picture(img, socket), {}))

        for socket, vid in videos:
            path, dur, frames, imgs = _write_video(vid, socket)
            written.append((socket, "video", path, {"seconds": round(dur, 3), "frames": frames}))
            if imgs is not None:
                video_frames.append(imgs)

        for socket, snd in sounds:
            path, dur = _write_sound(snd, socket)
            written.append((socket, "audio", path, {"seconds": round(dur, 3)}))
            if socket == "voice_to_match" and (spoken_words or "").strip():
                # The service keys transcripts by the file's own hash, computed here from the very
                # bytes the service will read.
                transcripts[_sha256_file(path)] = spoken_words.strip()

        return written, transcripts, video_frames

    @classmethod
    def _compile_where_the_service_can_read(cls, *, server, written, picture_notes, sound_notes,
                                           sizing, transcripts, override, timeout, brief):
        r"""Compile, working the path mapping out by trying rather than by asking anyone to type it.

        The service opens attachments from disk, and it may see the disk differently than ComfyUI
        does: ComfyUI on Windows writes C:\ComfyUI\temp\ref.png while a service in WSL or a container
        sees /mnt/c/ComfyUI/temp/ref.png. Neither program can work out the other's spelling, so the
        plausible ones are offered in turn and the service itself confirms which is right by opening
        the file. A guess that is never checked is the silent-failure trap; this one is checked on
        every run, and running out of candidates produces an error listing what was tried.
        """
        root = _comfy_root()
        candidates = path_candidates(root, override)
        last: ServiceError | None = None
        for prefix in candidates:
            assets = plan_assets(written, list((picture_notes or "").splitlines()),
                                 list((sound_notes or "").splitlines()), sizing, root, prefix)
            payload = build_payload(assets=assets, transcripts=transcripts, **brief)
            try:
                body = compile_brief(server, payload, timeout=timeout)
                return body, (prefix if prefix and prefix != root else "")
            except ServiceError as e:
                if not retranslate(e):
                    raise
                last = e
        raise ServiceError(
            (str(last) if last else "the service could not read the attachments.")
            + "\n\nTried these spellings of ComfyUI's folder: " + ", ".join(repr(c) for c in
                                                                           candidates)
            + ". If the service runs on a different machine it cannot open these files at all, and "
              "only text-only prompts will work. If it can reach them by some other path, put that "
              "path in this node's 'where the service sees ComfyUI's folder' field.")

    @classmethod
    def _load_model(cls, name: str, weight_dtype: str):
        if not name:
            raise ServiceError("no H3 weights selected. Pick a checkpoint for reference jobs, and "
                               "one for frame jobs if you use the first or last frame sockets.")
        import nodes
        return nodes.NODE_CLASS_MAPPINGS["UNETLoader"]().load_unet(name, weight_dtype)[0]

    @classmethod
    def _load_clip(cls, name: str):
        if not name:
            raise ServiceError("no text encoder selected. H3 needs its Qwen3-VL encoder.")
        import nodes
        loader = nodes.NODE_CLASS_MAPPINGS["CLIPLoader"]()
        try:
            return loader.load_clip(name, "minimax", "default")[0]
        except TypeError:
            return loader.load_clip(name, "minimax")[0]

    @classmethod
    def _load_vae(cls, name: str):
        if not name:
            raise ServiceError("both VAEs have to be selected. H3 writes picture and sound "
                               "together, so it needs each one.")
        import nodes
        return nodes.NODE_CLASS_MAPPINGS["VAELoader"]().load_vae(name)[0]

    @classmethod
    def _condition(cls, *, declared, clip, vae, audio_vae, prompt, width, height, length,
                   ref_image_size, opening, closing, refs, video_frames, sounds):
        """Hand the conditioning to ComfyUI's own H3 nodes rather than reimplementing it. They own
        how references are tokenised and how the latent is packed, and a copy of that here would be
        the version that rots."""
        from comfy_extras.nodes_minimax_h3 import (MiniMaxH3ImageToVideo,
                                                  MiniMaxH3ReferenceToVideo)

        if declared in ("i2va", "l2va", "fl2va"):
            out = MiniMaxH3ImageToVideo.execute(
                clip=clip, vae=vae, prompt=prompt, width=width, height=height, length=length,
                first_frame=opening, last_frame=closing)
            return tuple(out.result)

        ref_images = {f"ref_image_{i}": img for i, (_s, img) in enumerate(refs, 1)}
        ref_videos = {f"ref_video_{i}": f for i, f in enumerate(video_frames, 1)}
        ref_audios = {f"ref_audio_{i}": snd for i, (_s, snd) in enumerate(sounds, 1)}
        out = MiniMaxH3ReferenceToVideo.execute(
            clip=clip, vae=vae, audio_vae=audio_vae, prompt=prompt, width=width, height=height,
            length=length, ref_image_size=ref_image_size, ref_images=ref_images or None,
            ref_videos=ref_videos or None, ref_audios=ref_audios or None)
        return tuple(out.result)


class OpenH3IRShowText(io.ComfyNode):
    """Show a text output on the canvas, so the report can be read without a detour."""

    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="OpenH3IRShowText",
            display_name="OpenH3-IR Show Text",
            category="OpenH3-IR",
            description="Show a text output, such as the report or the brief itself.",
            inputs=[io.String.Input(
                "text", display_name="text to show", force_input=True,
                tooltip="Any text output. Wire the report here to read what the compile did.")],
            outputs=[],
            is_output_node=True,
        )

    @classmethod
    def execute(cls, text: str) -> io.NodeOutput:
        return io.NodeOutput(ui={"text": [text if isinstance(text, str) else str(text)]})


class OpenH3IRExtension(ComfyExtension):
    async def get_node_list(self):
        return [OpenH3IRCompile, OpenH3IRShowText]


async def comfy_entrypoint() -> OpenH3IRExtension:
    return OpenH3IRExtension()


__all__ = ["OpenH3IRCompile", "OpenH3IRShowText", "OpenH3IRExtension", "comfy_entrypoint",
           "ServiceError"]
