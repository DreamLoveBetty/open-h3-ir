"""One node that turns a sentence into a ready-to-sample MiniMax H3 job, and three that hold the
things which are not about this shot.

The compile node replaces the text box, the resolution picker, the frame-count arithmetic, the
model, encoder and VAE loaders, and the H3 conditioning node. Out comes the model, the conditioning,
the latent and both VAEs, which is everything the rest of the graph needs.

Five ideas hold it together.

The socket you plug into is the job. A picture in the first-frame socket IS the opening frame of the
video. A picture in `picture 1` is something the shot should contain. Those are different tasks with
different H3 checkpoints behind them, so reading the answer off the sockets means the brief and the
graph cannot disagree. Nothing is inferred and there are no role dropdowns to get wrong.

Length lives in one place. One seconds field, used for both the brief and the latent. Two dials that
both claim to set the duration is how eight seconds of a ten second script gets rendered.

The lists grow as they are filled, and they are labelled `picture 1` and `clip 1`, one-based and in
the brief's own words, so a note that says "line one describes picture 1" needs no further
explaining.

Nothing that is not shot-scoped stays on the node. A machine's address, its five model files and its
VRAM setting are one Setup socket. A clip is frames plus a soundtrack plus what it is for, which is
one optional Footage node per clip. Three sounds with three notes and a transcript are one optional
Sound node. The satellites are absent until you need them; Setup is the one that is always there,
because the five files it carries are picked by a person and nothing here invents them.

Which file to load is a question only the user can answer. There is no search by name, no preferred
build and no sentinel that means "work it out": a filename says what a file is called, not what
somebody intended it to be, and a node that answers that question anyway is choosing for the user
without telling them. So the picks are visible on the node, they are trivial to change, and the
report names every file that was loaded and the loader that read it.

The file is the format. A `.gguf` checkpoint or encoder loads through ComfyUI-GGUF's loader and a
`.safetensors` one loads natively, decided per file from the extension, with no toggle anywhere. A
boolean beside a filename would be two controls describing one fact, and two of its four states
would be wrong with nothing on the canvas to resolve them.

This uses ComfyUI's current node schema, the same one the stock H3 nodes use, so any ComfyUI that can
render H3 can load this. Heavy imports stay inside the functions that need them: an exception while
ComfyUI imports a custom node takes the whole pack off the menu with a traceback nobody can act on.
"""
from __future__ import annotations

import os
import tempfile
from typing import Any

from comfy_api.latest import ComfyExtension, io

from .media import digest, sha256_file, write_footage, write_picture, write_sound
from .h3ir_client import (ASPECTS, CLIP_NAMES, CREATIVITY, DEFAULT_SERVER, DIALOGUE_LANGUAGES,
                          EFFORT, FOOTAGE_JOBS, FPS, MUSIC_JOBS, PICTURE_NAMES, SHOTS, SIZING,
                          SOUND_PARTS, WEIGHT_DTYPES,
                          ServiceError, bindings_by_content, build_payload, check_mode,
                          clip_loader_for, compile_brief, expected_mode, family_warning,
                          footage_bundle, images_in_numbering_order, inputs_fingerprint, is_gguf,
                          length_notes, line,
                          merge_model_options, ordered, path_candidates, plan_assets,
                          precision_ignored_note, render_fields, report, retranslate, setup_bundle,
                          sound_bundle, unet_loader_for)

# One socket carrying eight facts about a machine, one carrying a clip's three, one carrying the
# sounds. Custom io types, so a plain IMAGE cannot be dropped into a socket that needs a bundle and
# the refusal happens on the canvas rather than after a queue.
Setup = io.Custom("H3IR_SETUP")
Footage = io.Custom("H3IR_FOOTAGE")
Sound = io.Custom("H3IR_SOUND")


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


def _files(kind: str) -> list[str]:
    """Whatever this install actually has, so the dropdowns are real rather than a guess about
    someone's disk.

    An unregistered key comes back empty rather than raising, which is how the GGUF lists behave on
    an install without ComfyUI-GGUF: nothing is offered, so nothing can be selected that has no
    loader behind it.
    """
    try:
        import folder_paths
        return list(folder_paths.get_filename_list(kind))
    except Exception:  # noqa: BLE001 - an absent folder key is a fact, not a failure
        return []


def _model_options(native_kind: str, gguf_kind: str = "") -> list[str]:
    """A model combo: both builds of the same folder, merged into one list.

    No sentinel and no default, so the combo behaves like every loader in ComfyUI: it opens on a real
    filename, the filename is what the node shows, and changing it is one click.

    The GGUF half comes only from ComfyUI-GGUF's own registered list. It is never globbed off the
    disk, because a file offered with no loader behind it is exactly the plausible-and-wrong option
    this pack exists to prevent.
    """
    native = _files(native_kind)
    gguf = _files(gguf_kind) if gguf_kind else []
    return merge_model_options(native, gguf)


class OpenH3IRCompile(io.ComfyNode):
    """Sentence in; model, conditioning, latent and both VAEs out."""

    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="OpenH3IRCompile",
            display_name="H3 from a Sentence",
            category="OpenH3-IR",
            search_aliases=["minimax", "h3", "openh3", "ir", "brief", "prompt", "ref2va", "fl2va",
                            "t2va"],
            description=("One sentence to a ready H3 job: writes the brief H3 wants, picks the right "
                         "weights, loads the encoder and VAEs, and outputs model, conditioning and "
                         "latent."),
            inputs=[
                # --------------------------------------------------------- this is what I want
                # No display name: on a multiline widget the placeholder is the only label there is,
                # and a display name would spend the row this box does not have.
                io.String.Input(
                    "intent", multiline=True, default="",
                    placeholder="one plain sentence, what happens\nshe walks onto the wet gantry in "
                                "the rain and stops when she sees the city below",
                    tooltip="One plain sentence. Not a tag list and not a shot breakdown, because "
                            "the compiler writes those. Say the action and the beat you care "
                            "about."),
                io.Float.Input(
                    "seconds", display_name="seconds", default=8.0, min=1.0, max=149.0, step=0.1,
                    tooltip="The only place length is set, used for both the brief and the latent. "
                            "H3 renders on a 17 frame grid so this snaps up: ask for 10 and you get "
                            "10.125. 8.0 is the only whole second on the grid. H3's trained band is "
                            "5.167 to 15.083 seconds. Outside it a render still happens, untested "
                            "and slower, and the report says so."),
                io.Combo.Input(
                    "aspect", display_name="frame shape", options=list(ASPECTS), default="16:9",
                    tooltip="The canvas is sized from this, 768 on the short edge, so there is no "
                            "resolution box to keep in step with anything."),
                io.Combo.Input(
                    "creativity", display_name="invention", options=list(CREATIVITY),
                    default="balanced",
                    tooltip="How much the writer may add where your sentence is silent, which is "
                            "three things: a score, a spoken line, text in the frame. restrained "
                            "adds none of them. balanced may add a score. bold may also put words "
                            "in a mouth and text on screen. extreme adds nothing beyond bold, it "
                            "pushes every choice harder. Shot count is never on this dial, and "
                            "saying no dialogue in your sentence still means no dialogue at every "
                            "position."),
                io.Boolean.Input(
                    "silent", display_name="no music", default=False,
                    tooltip="H3 writes sound in the same pass as the picture, so silence is a "
                            "decision rather than an absence. This turns off the score only. "
                            "Ambient and physical sound still get written, and speech is governed "
                            "by your sentence and by invention."),
                io.Combo.Input(
                    "shots", display_name="shots", options=list(SHOTS), default="auto",
                    tooltip="auto is usually right: cut times have to land on the frame grid too, "
                            "and the compiler knows where they can go. Set a number when the piece "
                            "has to be one continuous take, or exactly two. Four is the compiler's "
                            "ceiling."),
                # The machine, and the only required socket. It sits here because ComfyUI groups every
                # required input ahead of every optional one when it publishes the schema, so a
                # declaration order that read better in this file would be a different node from the
                # one people are looking at.
                Setup.Input(
                    "setup", display_name="setup",
                    tooltip="Required. The service address and the five H3 files to load, from an "
                            "OpenH3-IR Setup node. Which files those are is your choice, so there is "
                            "one node that holds it and the report names every file that was "
                            "loaded."),

                # --------------------------------------------------------- and these are the words
                # Still the ask, and it reads with the ask on the canvas, but it is declared here
                # because ComfyUI publishes every required input ahead of every optional one and this
                # one has to stay optional: a required input is missing from every API-format graph
                # that was written before it existed, and that is a hard refusal at /prompt.
                io.String.Input(
                    "spoken_lines", multiline=True, optional=True, default="",
                    placeholder="one line per spoken line, exactly as it should be said\nThe gate "
                                "stays shut tonight.\nNot for me.",
                    tooltip="The words themselves, one line per spoken line, in the order they are "
                            "said. A line typed here comes back in the brief word for word and mark "
                            "for mark, because a brief that reworded one is refused; words quoted "
                            "inside your sentence get no such check. Who says it, and whether a line "
                            "is heard off screen, still belong in the sentence. Empty asks for "
                            "nothing, exactly as before this box existed."),
                io.Combo.Input(
                    "spoken_language", display_name="spoken in",
                    options=list(DIALOGUE_LANGUAGES), default=DIALOGUE_LANGUAGES[0], optional=True,
                    tooltip="The language the lines above are spoken in. It becomes the language tag "
                            "in the brief, which is what H3 reads, so Spanish words tagged English "
                            "are spoken wrong. It decides nothing while the box is empty. For a "
                            "language that is not listed, quote the line in the sentence instead and "
                            "name the language there."),

                # --------------------------------------------------------- this is what it looks at
                io.Image.Input(
                    "first_frame", display_name="first frame", optional=True,
                    tooltip="The video STARTS on this picture. A different job from a picture "
                            "reference, on H3's first-and-last-frame weights, which this node loads "
                            "for you. Cannot be combined with the picture sockets."),
                io.Image.Input(
                    "last_frame", display_name="last frame", optional=True,
                    tooltip="The video ENDS on this picture. Cannot be combined with the picture "
                            "sockets."),
                io.Autogrow.Input(
                    "pictures", display_name="pictures", optional=True,
                    template=io.Autogrow.TemplateNames(
                        input=io.Image.Input(
                            "picture",
                            tooltip="Something the shot should contain: a person, a car, a room. "
                                    "The socket's number is the picture's number in the brief and "
                                    "in the notes below. The next socket appears once this one is "
                                    "filled."),
                        names=list(PICTURE_NAMES), min=0)),
                io.String.Input(
                    "picture_notes", multiline=True, optional=True, default="",
                    placeholder="one line per picture, in order\nthe man\nthe red car",
                    tooltip="Optional, and often the difference between the right subject being "
                            "described and the wrong one. Line one describes picture 1. The first "
                            "frame, last frame and storyboard sockets need no line here."),
                io.Image.Input(
                    "storyboard", display_name="storyboard", optional=True,
                    tooltip="A sketch or a panel board showing how the shots are laid out: the "
                            "viewpoint, where things sit, and the order they come in. It plans the "
                            "shots and does not appear in the video, so it is neither a frame of it "
                            "nor something the shot should contain. It is numbered after the "
                            "pictures, so picture 1 stays picture 1 in the brief."),
                io.Autogrow.Input(
                    "footage", display_name="footage", optional=True,
                    template=io.Autogrow.TemplateNames(
                        input=Footage.Input(
                            "clip",
                            tooltip="Reference footage from an OpenH3-IR Footage node, up to "
                                    "three."),
                        names=list(CLIP_NAMES), min=0)),
                Sound.Input(
                    "sound", display_name="sound", optional=True,
                    tooltip="Music, an effect, or a voice to match, from an OpenH3-IR Sound node."),

                # --------------------------------------------------------- rarely touched
                io.Combo.Input(
                    "sizing", display_name="reference size", options=list(SIZING), default="match",
                    optional=True, advanced=True,
                    tooltip="match fits each picture to the render's pixel area. max keeps the "
                            "picture's own size for stronger identity and is slower, because "
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
                    tooltip="max asks the writer for reasoning prose and is slower."),
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
                                         "which socket became which picture, and every file "
                                         "loaded."),
            ],
        )

    @classmethod
    def fingerprint_inputs(cls, **kwargs: Any) -> Any:
        """Re-run when something changed and never otherwise. The compiler is seeded, so an unchanged
        graph re-queued would spend a model call to produce the same brief.

        The bundles are hashed by content along with the pictures, because a Setup, Footage or Sound
        node hands over a dict whose `repr` is a memory address: hashing that would make a swapped
        reference image or a re-typed note look like no change at all.
        """
        media = [digest(kwargs.pop("pictures", None)), digest(kwargs.pop("footage", None))]
        for key in ("first_frame", "last_frame", "storyboard", "sound", "setup"):
            media.append(digest(kwargs.pop(key, None)))
        return inputs_fingerprint(sorted((k, repr(v)) for k, v in kwargs.items()), media)

    # ------------------------------------------------------------------ the work

    @classmethod
    def execute(cls, intent: str, seconds: float, aspect: str, creativity: str, silent: bool,
                shots: str, spoken_lines: str = "",
                spoken_language: str = DIALOGUE_LANGUAGES[0], first_frame=None, last_frame=None,
                pictures=None, picture_notes: str = "", storyboard=None, footage=None, sound=None,
                setup=None, sizing: str = "match", seed: int = 7,
                effort: str = "standard") -> io.NodeOutput:
        # The socket is required, so ComfyUI refuses an unconnected graph before this runs. This is
        # the same refusal in this pack's own words, for the graph that arrives over /prompt with the
        # socket present and empty: without the five picks there is nothing to load, and the node
        # will not choose five files on somebody's behalf.
        if not setup:
            raise ServiceError(
                "this node has no setup. Add an OpenH3-IR Setup node, pick the five H3 files it "
                "asks for (the reference weights, the frame weights, the text encoder, the picture "
                "VAE and the sound VAE) and wire its setup output into this node's setup socket. "
                "Which files those are cannot be worked out from their names, so they are your "
                "choice rather than a guess this node makes for you.")
        machine = setup
        pics = ordered(pictures, PICTURE_NAMES)
        clips = ordered(footage, CLIP_NAMES)
        sounds = cls._sounds_from(sound)

        anchored = first_frame is not None or last_frame is not None
        if anchored and (pics or clips):
            raise ServiceError(
                "this is two different jobs at once. The first and last frame sockets say a picture "
                "is a frame of the video; the picture and clip sockets say a file is something the "
                "shot should contain. H3 does one or the other, so unplug whichever you did not "
                "mean.")
        if anchored and storyboard is not None:
            # Refused here rather than sent, and this one is about the graph and not about the brief:
            # a first or last frame job runs through ComfyUI's own H3 image-to-video node, which has
            # sockets for the two frames and none for a reference picture. So the board would be
            # described in the brief, numbered in the report, and never handed to H3 at all.
            raise ServiceError(
                "a storyboard cannot ride along with a first or last frame. Those sockets run the "
                "job on H3's frame weights, whose node takes the two frames and no reference picture "
                "at all, so the brief would lay the shots out from your board and H3 would never "
                "receive it. Unplug the frame sockets and let the board plan the shots, or unplug "
                "the board.")
        if anchored and sounds:
            raise ServiceError(
                "a first or last frame job runs on H3's frame weights, and that path takes no "
                "reference sound at all: the brief would name your clip and H3 would never receive "
                "it. Unplug the sound, or use the picture sockets instead of the frame sockets.")

        declared = expected_mode(first_frame is not None, last_frame is not None, len(pics),
                                 len(clips), len(sounds), storyboard is not None)
        frames_job = declared in ("i2va", "l2va", "fl2va")

        # One ordered list of pictures, read by the half that tells the service and by the half that
        # fills H3's sockets, so the two cannot disagree about which picture is <Picture 1>.
        images = images_in_numbering_order(first_frame, last_frame, pics, storyboard)
        written, transcripts, clip_frames, clip_sounds = cls._write_everything(
            images, clips, sounds, (sound or {}).get("voice_words", ""))
        bindings = bindings_by_content(written, sha256_file)

        body, used_prefix = cls._compile_where_the_service_can_read(
            server=machine["server"], written=written, picture_notes=picture_notes, sizing=sizing,
            transcripts=transcripts, timeout=float(machine["timeout_s"]),
            brief=dict(intent=intent, seconds=seconds, aspect=aspect, creativity=creativity,
                       effort=effort, seed=seed, silent=silent, shots=shots,
                       spoken_lines=spoken_lines, spoken_language=spoken_language))

        prompt, width, height, length, ref_sizing = render_fields(body)
        warning = check_mode(declared, str(body.get("mode", "")))

        # Which file, decided on the Setup node and read straight off it. The socket the user filled
        # decides which of the two checkpoints this job needs, which is the one question a graph can
        # answer on its own.
        checkpoint = machine["frames_model" if frames_job else "reference_model"]
        encoder = machine["text_encoder"]
        video_vae = machine["video_vae"]
        audio_vae = machine["audio_vae"]

        model = cls._load_model(checkpoint, machine["weight_dtype"])
        clip = cls._load_clip(encoder)
        vae = cls._load_vae(video_vae)
        avae = cls._load_vae(audio_vae)

        positive, latent = cls._condition(
            declared=declared, clip=clip, vae=vae, audio_vae=avae, prompt=prompt, width=width,
            height=height, length=length, ref_image_size=ref_sizing, first=first_frame,
            last=last_frame, images=images, clip_frames=clip_frames, clip_sounds=clip_sounds,
            sounds=sounds)

        wiring = body.get("wiring") or []
        conflict = len({w.get("sizing") for w in wiring if w.get("sizing")}) > 1
        text = report(body, server=machine["server"], sizing_conflict=conflict,
                      asked_seconds=seconds, bindings=bindings)
        text += "\n" + line("job", declared)
        text += "\n" + line("weights", f"{checkpoint}  via {unet_loader_for(checkpoint)}")
        text += "\n" + line("encoder", f"{encoder}  via {clip_loader_for(encoder)}")
        text += "\n" + line("vaes", f"{video_vae}  +  {audio_vae}")
        if used_prefix:
            text += "\n" + line("paths", f"the service reads ComfyUI's folder at {used_prefix}")
        if is_gguf(checkpoint) and machine["weight_dtype"] != "default":
            text += "\n" + precision_ignored_note()
        # Both warnings go to the report and to the console. Nothing obliges anyone to wire the
        # report output to a node that shows it, and a warning nobody can see is not a warning.
        for said in (warning, family_warning(checkpoint, frames_job=frames_job)):
            if said:
                text += "\n" + line("WARNING", said)
                print("[OpenH3-IR] " + said)
        # A length outside the trained band is a choice, not a fault, so it stays in the `note`
        # register. It also goes to the console, because nothing obliges anyone to wire the report
        # output to a node that shows it.
        for note in length_notes(seconds, length):
            if note.startswith("note"):
                print("[OpenH3-IR] " + " ".join(note.split()[1:]))
        print(f"[OpenH3-IR] {declared}: {length} frames ({length / FPS:.3f}s), {width}x{height}")
        return io.NodeOutput(model, positive, latent, vae, avae, prompt, text)

    # ------------------------------------------------------------------ helpers

    @classmethod
    def _sounds_from(cls, sound: dict[str, Any] | None) -> list[tuple[str, Any, str, str]]:
        """The Sound node's filled sockets as (canvas name, clip, note, role), in numbering order.

        The role is empty for the two sockets whose name says what they are, and carries the user's
        choice for the music socket, which answers three different questions about one file.
        """
        if not sound:
            return []
        return [(shown, sound[key], sound.get(note_key, ""),
                 str(sound.get(role_key, "")) if role_key else "")
                for key, shown, note_key, role_key in SOUND_PARTS if sound.get(key) is not None]

    @classmethod
    def _write_everything(cls, images, clips, sounds, voice_words):
        """Put every attachment on disk. Only the socket-to-file mapping lives here; the conversion
        itself is in `media`, and ordering, roles and notes are decided in `h3ir_client`, all of
        which can be tested without a canvas.

        `images` arrives already in numbering order from `images_in_numbering_order`, which is the
        one place that order is decided.
        """
        written: list[tuple[str, str, str, dict[str, Any]]] = []
        clip_frames: list[Any] = []
        clip_sounds: list[Any] = []
        transcripts: dict[str, str] = {}
        temp = _temp_dir()

        for socket, img in images:
            written.append((socket, "image", write_picture(img, socket, temp), {}))

        for socket, bundle in clips:
            path, dur, n = write_footage(bundle["frames"], bundle.get("its_sound"), socket, temp)
            written.append((socket, "video", path,
                            {"role": bundle["role"], "seconds": round(dur, 3), "frames": n}))
            clip_frames.append(bundle["frames"])
            clip_sounds.append(bundle.get("its_sound"))
            if bundle.get("its_sound") is not None:
                # The soundtrack goes in as its own asset pointing back at this clip, which is what
                # makes the service's <Audio j> ordering the same one H3 receives: the runtime emits
                # a paired soundtrack's label immediately before its video's.
                snd_path, snd_dur = write_sound(bundle["its_sound"], f"{socket} sound", temp)
                written.append((f"{socket} sound", "audio", snd_path,
                                {"role": "bgm", "seconds": round(snd_dur, 3),
                                 "paired_video_path": path}))

        for socket, snd, note, role in sounds:
            path, dur = write_sound(snd, socket, temp)
            extra: dict[str, Any] = {"seconds": round(dur, 3), "note": note}
            if role:
                extra["role"] = role
            written.append((socket, "audio", path, extra))
            if socket == "voice to match" and (voice_words or "").strip():
                # The service keys transcripts by the file's own hash, computed here from the very
                # bytes the service will read.
                transcripts[sha256_file(path)] = voice_words.strip()

        return written, transcripts, clip_frames, clip_sounds

    @classmethod
    def _compile_where_the_service_can_read(cls, *, server, written, picture_notes, sizing,
                                           transcripts, timeout, brief):
        r"""Compile, working the path mapping out by trying rather than by asking anyone to type it.

        The service opens attachments from disk, and it may see the disk differently than ComfyUI
        does: ComfyUI on Windows writes C:\ComfyUI\temp\ref.png while a service in WSL or a container
        sees /mnt/c/ComfyUI/temp/ref.png. Neither program can work out the other's spelling, so the
        plausible ones are offered in turn and the service itself confirms which is right by opening
        the file. A guess that is never checked is the silent-failure trap; this one is checked on
        every run, and running out of candidates produces an error listing what was tried.
        """
        root = _comfy_root()
        candidates = path_candidates(root)
        last: ServiceError | None = None
        for prefix in candidates:
            assets = plan_assets(written, list((picture_notes or "").splitlines()), sizing, root,
                                 prefix)
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
              "only text-only prompts will work. If it runs beside ComfyUI, it needs read access to "
              "the folder above, under a spelling it can open.")

    @classmethod
    def _node(cls, class_name: str, missing: str):
        import nodes
        cls_ = nodes.NODE_CLASS_MAPPINGS.get(class_name)
        if cls_ is None:
            raise ServiceError(missing)
        return cls_()

    @classmethod
    def _load_model(cls, name: str, weight_dtype: str):
        if is_gguf(name):
            loader = cls._node("UnetLoaderGGUF",
                               f"{name} is a GGUF checkpoint, and the ComfyUI-GGUF pack that reads "
                               "one is not installed. Install ComfyUI-GGUF, or pick a .safetensors "
                               "checkpoint on the Setup node.")
            return loader.load_unet(name)[0]
        return cls._node("UNETLoader", "ComfyUI's own UNETLoader is missing from this install, "
                                       "which no custom node can work around.") \
            .load_unet(name, weight_dtype)[0]

    @classmethod
    def _load_clip(cls, name: str):
        """H3's encoder, loaded as H3's family and never as whatever the loader defaults to.

        Both loaders resolve the CLIP type by name, and ComfyUI-GGUF's does it with a getattr whose
        default is STABLE_DIFFUSION: an unknown name there loads H3's encoder as the wrong family
        silently, and the render comes out plausible and wrong. So the member is asserted first.
        """
        import comfy.sd
        if not hasattr(comfy.sd.CLIPType, "MINIMAX"):
            raise ServiceError(
                "this ComfyUI does not know MiniMax H3's text encoder family (comfy.sd.CLIPType "
                "has no MINIMAX member), so the encoder would be loaded as the wrong family and "
                "the render would be wrong with nothing on screen to say so. Update ComfyUI to a "
                "version whose own MiniMax H3 nodes work.")
        if is_gguf(name):
            loader = cls._node("CLIPLoaderGGUF",
                               f"{name} is a GGUF text encoder, and the ComfyUI-GGUF pack that "
                               "reads one is not installed. Install ComfyUI-GGUF, or pick a "
                               ".safetensors encoder on the Setup node.")
            return loader.load_clip(name, "minimax")[0]
        loader = cls._node("CLIPLoader", "ComfyUI's own CLIPLoader is missing from this install, "
                                         "which no custom node can work around.")
        try:
            return loader.load_clip(name, "minimax", "default")[0]
        except TypeError:
            return loader.load_clip(name, "minimax")[0]

    @classmethod
    def _load_vae(cls, name: str):
        return cls._node("VAELoader", "ComfyUI's own VAELoader is missing from this install, which "
                                      "no custom node can work around.").load_vae(name)[0]

    @classmethod
    def _condition(cls, *, declared, clip, vae, audio_vae, prompt, width, height, length,
                   ref_image_size, first, last, images, clip_frames, clip_sounds, sounds):
        """Hand the conditioning to ComfyUI's own H3 nodes rather than reimplementing it. They own
        how references are tokenised and how the latent is packed, and a copy of that here would be
        the version that rots."""
        from comfy_extras.nodes_minimax_h3 import (MiniMaxH3ImageToVideo,
                                                  MiniMaxH3ReferenceToVideo)

        if declared in ("i2va", "l2va", "fl2va"):
            out = MiniMaxH3ImageToVideo.execute(
                clip=clip, vae=vae, prompt=prompt, width=width, height=height, length=length,
                first_frame=first, last_frame=last)
            return tuple(out.result)

        # Index-paired, exactly as the stock node reads them: ref_video_audio_N belongs to
        # ref_video_N. This is the pairing the service was told about, so the labels it computed and
        # the labels H3 receives are the same labels.
        # `images` is the very list `_write_everything` described to the service, in that order, so
        # <Picture N> in the brief and ref_image_N in the graph are the same N for every picture, the
        # storyboard included.
        ref_images = {f"ref_image_{i}": img for i, (_s, img) in enumerate(images, 1)}
        ref_videos = {f"ref_video_{i}": f for i, f in enumerate(clip_frames, 1)}
        ref_video_audios = {f"ref_video_audio_{i}": s for i, s in enumerate(clip_sounds, 1)
                            if s is not None}
        ref_audios = {f"ref_audio_{i}": snd for i, (_s, snd, _n, _r) in enumerate(sounds, 1)}
        out = MiniMaxH3ReferenceToVideo.execute(
            clip=clip, vae=vae, audio_vae=audio_vae, prompt=prompt, width=width, height=height,
            length=length, ref_image_size=ref_image_size, ref_images=ref_images or None,
            ref_videos=ref_videos or None, ref_video_audios=ref_video_audios or None,
            ref_audios=ref_audios or None)
        return tuple(out.result)


class OpenH3IRSetup(io.ComfyNode):
    """The machine, not the shot: where the service is and which files to load.

    A picker, and only a picker. Every combo lists the files this install actually has, in both
    formats, and opens on one of them the way ComfyUI's own loaders do. Nothing is searched for by
    name, no build is preferred, and there is no option meaning "work it out": which of two H3
    checkpoints somebody meant is not written in either filename, so the answer belongs to the person
    who put the files there. The pick is on the canvas where it can be read and changed, and the
    compile node's report names every file it loaded.
    """

    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="OpenH3IRSetup",
            display_name="OpenH3-IR Setup",
            category="OpenH3-IR",
            search_aliases=["openh3", "h3", "ir", "service", "server", "gguf", "models"],
            description=("Where the OpenH3-IR service is, and which five H3 files to load. Every H3 "
                         "graph needs one: the compile node loads what you pick here."),
            inputs=[
                io.String.Input(
                    "server", display_name="service", default=DEFAULT_SERVER,
                    tooltip="Where the OpenH3-IR service is listening. Start one from the repo with "
                            "h3ir serve. It can be another machine."),
                io.Combo.Input(
                    "reference_model", display_name="reference weights",
                    options=_model_options("diffusion_models", "unet_gguf"),
                    tooltip="H3's checkpoint for reference and text jobs, named ref2va by MiniMax. "
                            "Both formats are in this list: pick a .gguf and it loads through Unet "
                            "Loader (GGUF), pick a .safetensors and it loads natively."),
                io.Combo.Input(
                    "frames_model", display_name="frame weights",
                    options=_model_options("diffusion_models", "unet_gguf"),
                    tooltip="H3's checkpoint for first and last frame jobs, named fl2va by MiniMax. "
                            "The compile node uses this one or the reference weights depending on "
                            "which sockets you filled, and says which in its report. Both formats "
                            "are in this list."),
                io.Combo.Input(
                    "text_encoder", display_name="text encoder",
                    options=_model_options("text_encoders", "clip_gguf"),
                    tooltip="The Qwen3-VL encoder H3 was trained against. Both formats are in this "
                            "list, chosen independently of the checkpoint: a GGUF encoder works "
                            "with safetensors weights and the other way round."),
                io.Combo.Input(
                    "video_vae", display_name="picture VAE", options=_model_options("vae"),
                    tooltip="H3's picture VAE, used for the decode as well."),
                io.Combo.Input(
                    "audio_vae", display_name="sound VAE", options=_model_options("vae"),
                    tooltip="H3's sound VAE, a different file from the picture VAE. Needed even for "
                            "a silent piece, because H3 writes picture and sound together."),
                io.Combo.Input(
                    "weight_dtype", display_name="weight precision", options=list(WEIGHT_DTYPES),
                    default="default", advanced=True,
                    tooltip="The same setting a UNET loader has. Leave alone unless you are short "
                            "of VRAM. It does not apply to a GGUF checkpoint, which carries its own "
                            "quantisation, and the report says when it was ignored."),
                io.Int.Input(
                    "timeout_s", display_name="timeout, seconds", default=600, min=10, max=3600,
                    advanced=True,
                    tooltip="Writing a brief is one call to your language model, so this is as slow "
                            "as that model is."),
            ],
            outputs=[Setup.Output(display_name="setup")],
        )

    @classmethod
    def execute(cls, server: str, reference_model: str, frames_model: str, text_encoder: str,
                video_vae: str, audio_vae: str, weight_dtype: str = "default",
                timeout_s: int = 600) -> io.NodeOutput:
        return io.NodeOutput(setup_bundle(
            server=server, reference_model=reference_model, frames_model=frames_model,
            text_encoder=text_encoder, video_vae=video_vae, audio_vae=audio_vae,
            weight_dtype=weight_dtype, timeout_s=timeout_s))


class OpenH3IRFootage(io.ComfyNode):
    """One reference clip: its frames, its soundtrack, and what it is for.

    Its own node because those three facts have to travel together and an autogrow item holds
    exactly one input. As a satellite the pairing is structural rather than positional, and the
    per-clip job becomes expressible at all.
    """

    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="OpenH3IRFootage",
            display_name="OpenH3-IR Footage",
            category="OpenH3-IR",
            search_aliases=["openh3", "h3", "ir", "video", "clip", "footage", "edit", "continue"],
            description="One reference clip for H3: its frames, its soundtrack, and its job.",
            inputs=[
                io.Image.Input(
                    "frames", display_name="frames",
                    tooltip="The clip's frames, from Load Video (Upload) or any loader with an "
                            "IMAGE output. H3 reads 24 fps, 2 to 15 seconds."),
                io.Audio.Input(
                    "its_sound", display_name="its sound", optional=True,
                    tooltip="The same clip's soundtrack, from the loader's audio output. It stays "
                            "paired with these frames, which is how H3 labels it."),
                io.Combo.Input(
                    "job", display_name="what it is for", options=list(FOOTAGE_JOBS),
                    default="copy what is in it",
                    tooltip="copy what is in it puts what the clip contains into a new shot. edit "
                            "it says the piece is a changed version of this footage. carry on from "
                            "it says the piece continues where this footage stopped. These are "
                            "three different jobs in the brief, so the wrong one renders something "
                            "plausible and wrong."),
            ],
            outputs=[Footage.Output(display_name="clip")],
        )

    @classmethod
    def execute(cls, frames, job: str, its_sound=None) -> io.NodeOutput:
        return io.NodeOutput(footage_bundle(frames, its_sound, job))


class OpenH3IRSound(io.ComfyNode):
    """Up to three reference sounds, each with the note that is the only thing describing it.

    The notes are prominent here and modest on the compile node for a measurable reason: the service
    never asks a model to listen, because nothing in the chain can, and H3's tokenizer emits only
    `<Audio j>: `. A picture gets looked at; a sound does not. So the caller's note is the only
    channel by which anything learns what a sound is.

    The music socket also carries what the track is FOR, because one attached track answers three
    different questions and only the person who attached it knows which: play it, write new music in
    its style, or cut to its beat. The last two take nothing from the recording, and asking for either
    while the brief claims the file is the finished soundtrack is a document that contradicts its own
    wiring.
    """

    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="OpenH3IRSound",
            display_name="OpenH3-IR Sound",
            category="OpenH3-IR",
            search_aliases=["openh3", "h3", "ir", "audio", "music", "voice", "sfx", "sound", "beat",
                            "style"],
            description="Reference music, a sound effect and a voice to match, each with the note "
                        "that describes it, and what the music is for: played, matched, or cut to.",
            inputs=[
                io.Audio.Input("music", display_name="music", optional=True,
                               tooltip="A music track. What is done with it is the choice two rows "
                                       "below: it can be played, matched, or cut to."),
                io.String.Input(
                    "music_note", display_name="what the music is", default="", optional=True,
                    tooltip="Nothing in this chain can hear. This line is the only thing the model "
                            "will ever learn about the track, so timbre, tempo and instruments "
                            "belong here: slow synth score, no drums."),
                io.Combo.Input(
                    "music_job", display_name="what it is for", options=list(MUSIC_JOBS),
                    default=next(iter(MUSIC_JOBS)), optional=True,
                    tooltip="play this track puts the recording itself in the video as its score. "
                            "match its style asks for new music that sounds like it, and nothing of "
                            "the recording is used. cut to its beat times the cuts and the action to "
                            "its rhythm, and nothing of the recording is used. These are three "
                            "different jobs in the brief, and the wrong one has the brief promise H3 "
                            "your file is the finished soundtrack."),
                io.Audio.Input("effect", display_name="sound effect", optional=True,
                               tooltip="A sound effect to reuse or match."),
                io.String.Input(
                    "effect_note", display_name="what the effect is", default="", optional=True,
                    tooltip="The only description the model gets: a heavy door slamming, close, no "
                            "reverb."),
                io.Audio.Input("voice", display_name="voice to match", optional=True,
                               tooltip="A voice whose timbre and delivery should be matched."),
                io.String.Input(
                    "voice_note", display_name="how the voice sounds", default="", optional=True,
                    tooltip="Delivery, age, accent, pace: hoarse, unhurried, mid-forties."),
                io.String.Input(
                    "voice_words", multiline=True, default="", optional=True,
                    placeholder="the words in the voice clip, exactly as spoken",
                    tooltip="A model asked about a waveform invents a plausible answer instead of "
                            "admitting it cannot listen, so the words are typed here or run through "
                            "a real recogniser. This is a transcript of the clip, not dialogue for "
                            "your video. Lines you want spoken go in the spoken lines box on the "
                            "compile node, or quoted in its sentence."),
            ],
            outputs=[Sound.Output(display_name="sound")],
        )

    @classmethod
    def execute(cls, music=None, music_note: str = "", music_job: str = next(iter(MUSIC_JOBS)),
                effect=None, effect_note: str = "", voice=None, voice_note: str = "",
                voice_words: str = "") -> io.NodeOutput:
        return io.NodeOutput(sound_bundle(
            music=music, music_note=music_note, music_job=music_job, effect=effect,
            effect_note=effect_note, voice=voice, voice_note=voice_note, voice_words=voice_words))


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
        return [OpenH3IRCompile, OpenH3IRSetup, OpenH3IRFootage, OpenH3IRSound, OpenH3IRShowText]


async def comfy_entrypoint() -> OpenH3IRExtension:
    return OpenH3IRExtension()


__all__ = ["OpenH3IRCompile", "OpenH3IRSetup", "OpenH3IRFootage", "OpenH3IRSound",
           "OpenH3IRShowText", "OpenH3IRExtension", "comfy_entrypoint", "ServiceError"]
