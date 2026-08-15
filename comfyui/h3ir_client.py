"""Talking to an OpenH3-IR service, with no ComfyUI and no third-party packages involved.

Everything in this module is a pure function or a thin call over the standard library, so the whole
integration can be tested without ComfyUI, without torch, and without a running server. The nodes in
`nodes.py` own the parts that can only exist inside ComfyUI: tensors, temp directories, model
loaders, and the schema the canvas draws.

Two deliberate choices worth knowing about before changing anything here.

Only the standard library. ComfyUI installs are other people's machines: embedded Pythons, frozen
requirement sets, five year old forks. A node that adds a dependency can break an install that was
working, so this speaks HTTP with `urllib` and accepts the slightly longer code.

Errors are written for the person on the canvas. A ComfyUI user sees one toast and a console
traceback, and that message is the only documentation they are guaranteed to read. So every failure
this module raises names what went wrong, what it was talking to, and the next action. None of them
say "check your configuration".
"""
from __future__ import annotations

import hashlib
import json
import socket
import textwrap
import urllib.error
import urllib.request
from typing import Any

# The port `h3ir serve` binds by default. Kept here as the node's default so the common case is
# "start the server, drop the node in, it works".
DEFAULT_PORT = 8420
DEFAULT_SERVER = f"http://127.0.0.1:{DEFAULT_PORT}"

CREATIVITY = ("restrained", "balanced", "bold", "extreme")
EFFORT = ("fast", "standard", "max")
# Reported by GET /v1/capabilities. Duplicated as a widget list because a combo has to be populated
# before any server has been contacted.
ASPECTS = ("16:9", "21:9", "4:3", "1:1", "3:4", "9:16")
SIZING = ("match", "max")
WEIGHT_DTYPES = ("default", "fp8_e4m3fn", "fp8_e4m3fn_fast", "fp8_e5m2")
# The languages GET /v1/capabilities publishes for dialogue, duplicated for the same reason ASPECTS
# is: a combo has to be populated before any server has been contacted. It is the service's own
# published list and not a limit the compiler enforces -- it writes whatever language it is given
# into the `[tag]` H3 reads -- so the field's own tooltip says what to do about a language that is
# not here rather than the surface pretending none exists.
DIALOGUE_LANGUAGES = ("English", "Spanish", "Portuguese", "French", "German", "Italian", "Russian",
                      "Arabic", "Chinese", "Japanese", "Korean")

FPS = 24
# h3ir/shots.py MAX_SHOTS. The compiler clamps to this, so offering more would promise a cut count
# the engine drops without saying so.
MAX_SHOTS = 10   # the service's PINNED_SHOTS_MAX; auto has its own lower heuristic ceiling
SHOTS = ("auto", *(str(i) for i in range(1, MAX_SHOTS + 1)))
# h3ir/grid.py TRAINED_MIN_FRAMES / TRAINED_MAX_FRAMES. Outside this band a render still happens;
# the report says so rather than the surface forbidding it.
TRAINED_MIN_FRAMES = 124
TRAINED_MAX_FRAMES = 362

# H3's own ceilings and the vocabulary of what a file can be live in `tray`, beside the slot they
# describe. This module is the service protocol and nothing else: what a user may say about their
# own media is the tray's business, and it changed once when the sockets became slots.

# Which loader owns a file, decided by its extension because that is the one fact the file itself
# carries. Names as ComfyUI shows them, so the report names something the user can find.
LOADER_NATIVE_UNET = "UNETLoader"
LOADER_GGUF_UNET = "Unet Loader (GGUF)"
LOADER_NATIVE_CLIP = "CLIPLoader"
LOADER_GGUF_CLIP = "CLIPLoader (GGUF)"


class ServiceError(RuntimeError):
    """Raised for every failure a node user can act on. The message is the user interface.

    `code` exists so callers can react to a class of failure without reading the prose. Sniffing the
    message would break the moment the wording improved, and the wording is meant to keep improving.
    """

    def __init__(self, message: str, code: str = ""):
        super().__init__(message)
        self.code = code


# The marker for the one failure another spelling of the path could fix: the service could not
# RESOLVE the file. Deliberately not called `asset-unreadable`, which is the service's own code for
# a file it resolved, opened and could not decode. That one is not retryable, and a name that
# suggested otherwise would earn somebody three times the wait for the same answer.
PATH_MAY_BE_WRONG = "path-may-be-wrong"


def retranslate(error: Exception) -> bool:
    """True when the failure was the service being unable to find an attachment.

    That is the only failure a different spelling of the path could fix, so it is the only one worth
    retrying. Retrying anything else would hide a real problem behind repeated attempts: a corrupt
    clip is corrupt under every spelling, and a machine with no ffmpeg still has none on the third
    attempt.
    """
    return getattr(error, "code", "") == PATH_MAY_BE_WRONG


def path_candidates(comfy_root: str) -> list[str]:
    r"""Spellings of ComfyUI's folder to offer the service, best guess first.

    ComfyUI's own location is known from ComfyUI, so nobody types it. What cannot be known is how a
    service on another view of the same disk spells it, and the common case by far is ComfyUI on
    Windows with the service in WSL or a container, where C:\ComfyUI becomes /mnt/c/ComfyUI. So that
    form is offered and the service is asked to confirm it by actually opening the file. Nothing is
    assumed: a candidate that does not work produces the next attempt, and running out produces an
    error that lists what was tried.

    There is no hand-typed override, because there was nothing anyone could usefully type: every
    spelling that can work is a spelling of a folder ComfyUI already named, and the one case a box
    could not fix is a service on another machine, which cannot open these files under any spelling.
    """
    if not comfy_root:
        return [""]
    out = [comfy_root]
    norm = comfy_root.replace("\\", "/")
    if len(norm) > 2 and norm[1] == ":":
        drive, rest = norm[0].lower(), norm[2:].lstrip("/")
        out.append(f"/mnt/{drive}/{rest}")
        out.append(f"/{drive}/{rest}")
    return out


def _url(server: str, path: str) -> str:
    return f"{server.rstrip('/')}{path}"


def _request(server: str, path: str, *, payload: dict[str, Any] | None = None,
             timeout: float = 600.0) -> tuple[int, Any]:
    """One HTTP call. Returns (status, decoded body) and lets 4xx and 5xx come back as values.

    An error status is data here rather than an exception, because the caller needs the body to say
    anything useful: the service reports which rule failed and which asset it could not read, and
    throwing that away would leave the node saying "HTTP 422".
    """
    url = _url(server, path)
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers,
                                 method="POST" if payload is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read().decode("utf-8", "replace")
            return r.status, _decode(body)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        return e.code, _decode(body)
    except socket.timeout as e:
        raise ServiceError(
            f"the OpenH3-IR service at {server} did not answer within {timeout:.0f}s. Writing a "
            "brief is one call to a language model, so it takes as long as that model takes. Raise "
            "the timeout on an OpenH3-IR Setup node, or point it at a faster endpoint.") from e
    except urllib.error.URLError as e:
        raise ServiceError(
            f"cannot reach an OpenH3-IR service at {server} ({e.reason}). Start one from the repo "
            f"with: h3ir serve --port {DEFAULT_PORT}. If it runs on another machine or another "
            "port, add an OpenH3-IR Setup node and put that address in its service field. The "
            "service also needs H3IR_LLM_URL pointing at your own OpenAI-compatible endpoint.") \
            from e


def _decode(body: str) -> Any:
    try:
        return json.loads(body) if body else None
    except json.JSONDecodeError:
        return body


def shot_count(shots: Any) -> int:
    """The `shots` widget as a number, with `auto` meaning 0: let the compiler decide.

    A combo of `auto` and 1..4 rather than an integer with a magic 0, because a magic value
    explained in its own label is the label doing the code's job. Integers still parse, so a
    workflow saved against the older surface keeps working.
    """
    if shots is None:
        return 0
    text = str(shots).strip().lower()
    if text in ("", "auto", "0"):
        return 0
    try:
        n = int(text)
    except ValueError:
        raise ServiceError(
            f"shots is {shots!r}, which is neither auto nor a number of shots. Pick auto, or 1 to "
            f"{MAX_SHOTS}.") from None
    if not 1 <= n <= MAX_SHOTS:
        raise ServiceError(
            f"{n} shots was asked for and the compiler's ceiling is {MAX_SHOTS}, so the extra cuts "
            "would be dropped without saying so. Pick auto, or 1 to "
            f"{MAX_SHOTS}.")
    return n


def dialogue_lines(said: list[str] | tuple[str, ...], language: str) -> list[dict[str, Any]]:
    """The prompt's locked lines as the service's `dialogue` list, one entry per line.

    Nothing here rewrites a word. These exist because the service checks them against the document it
    wrote -- the exact text has to come back inside `<d>`, word for word and mark for mark, or the
    brief is refused -- so a field that trimmed a quote mark or fixed a capital would break the one
    guarantee they are for. The lines arrive from `tray.parse_intent`, which takes what is between
    the quotes and edits none of it.

    The language is per line in the service's model and one control on the node, because it becomes
    the `[tag]` H3 reads and a Spanish line tagged English is spoken wrong. Mixed languages in one
    piece stay reachable the way they always were, by quoting inside the sentence, which is what the
    field's tooltip says.
    """
    said = [s for s in (said or ()) if s.strip()]
    # Checked where it is used and not before: with no lines in the prompt the language decides
    # nothing, and a combo cannot be mistyped from the canvas anyway. This is for the graph that
    # arrives over /prompt with a language nobody offered, which would otherwise be written into the
    # brief as H3's tag exactly as spelled.
    if said and language not in DIALOGUE_LANGUAGES:
        raise ServiceError(
            f"{language!r} is not one of the languages this field offers, and it would be written "
            "into the brief as H3's language tag exactly as spelled, so the lines would be spoken "
            "wrong. Pick one of: " + ", ".join(DIALOGUE_LANGUAGES) + ". For a language that is not "
            "there, quote the line in the sentence instead and name the language there.")
    return [{"text": t, "language": language} for t in said]


def build_payload(intent: str, *, seconds: float, aspect: str, creativity: str, effort: str,
                  megapixels: float = 0.0,
                  seed: int, silent: bool, shots: Any, assets: list[dict[str, Any]],
                  transcripts: dict[str, str], spoken: list[str] | tuple[str, ...] = (),
                  spoken_language: str = DIALOGUE_LANGUAGES[0]) -> dict[str, Any]:
    """Turn the node's state into the service's BriefIn.

    Assets arrive already shaped, with their role named, because the node knows the role from the
    socket the user plugged into. Nothing here infers a role: an inferred role can disagree with how
    the graph is wired, and a graph that disagrees with its own brief renders something plausible
    and wrong.

    `auto` shots means "the compiler decides", which is the service's own default when the field is
    absent, so the key is dropped rather than sent as a shot count of zero.
    """
    intent = (intent or "").strip()
    if not intent:
        raise ServiceError(
            "nothing to compile: the intent field is empty. Type what should happen in the shot, "
            "in one ordinary sentence, for example: she walks out onto the wet gantry in the rain "
            "and stops when she sees the city below.")

    payload: dict[str, Any] = {
        "intent": intent,
        "assets": list(assets),
        "seconds": float(seconds),
        "aspect": aspect,
        "creativity": creativity,
        "effort": effort,
        "seed": int(seed),
        "silent": bool(silent),
    }
    n = shot_count(shots)
    if n > 0:
        payload["shots"] = n
    if transcripts:
        payload["transcripts"] = dict(transcripts)
    # 0 is the node's "H3 decides": the field is omitted and the service renders at the model's
    # native 768 short edge, exactly as every graph before the knob existed. A stated value is the
    # caller stating the budget, and the report's canvas line shows what it bought.
    if megapixels and float(megapixels) > 0:
        payload["megapixels"] = round(float(megapixels), 2)
    # Empty means absent. No lines in the prompt is not "no lines were asked for" stated in a field,
    # it is the same request this node made before a line could be locked, so the key is dropped
    # rather than sent as an empty list: the writer is then free to put a line in a mouth exactly as
    # far as `invention` allows, which is the behaviour every saved workflow has.
    dialogue = dialogue_lines(spoken, spoken_language)
    if dialogue:
        payload["dialogue"] = dialogue
    return payload


def plan_assets(written: list[tuple[str, str, str, dict[str, Any]]],
                sizing: str, from_prefix: str, to_prefix: str) -> list[dict[str, Any]]:
    """Describe every attached file for the service, in the order it should be numbered.

    `written` is already on disk: a list of (name, kind, path, extra), where the name is the tray
    slot's own label and is what the report puts back onto the service's labels. `extra` carries
    everything the slot knows and this function cannot: its role, its note, the clip a soundtrack
    belongs to, a duration and a frame count.

    Nothing here infers a role. Every slot states what it is, so a missing role is an internal error
    rather than a quiet `subject`: an inferred role can disagree with what the tray says, and a
    request that disagrees with itself renders something plausible and wrong.
    """
    assets: list[dict[str, Any]] = []
    for name, kind, path, extra in written:
        role = extra.get("role")
        if not role:
            raise ServiceError(f"internal: no role recorded for {name!r}")
        a: dict[str, Any] = {"path": translate_path(path, from_prefix, to_prefix),
                             "kind": kind, "role": role}
        if kind == "image":
            a["sizing"] = sizing
        note = str(extra.get("note") or "")
        if note.strip():
            a["note"] = note.strip()
        for key in ("seconds", "frames"):
            if extra.get(key) is not None:
                a[key] = extra[key]
        # The pointer from a soundtrack back to its own clip is a path like any other, so it needs
        # the same translation. Sent untranslated it named a file the service could not open, the
        # service quietly stopped treating the pair as a pair, and the soundtrack was numbered as a
        # standalone <Audio 1> while H3 received it as ref_video_audio_1. Two different labels for
        # one file, and only the report said so.
        if extra.get("paired_video_path"):
            a["paired_video_path"] = translate_path(extra["paired_video_path"], from_prefix,
                                                    to_prefix)
        assets.append(a)
    return assets


def expected_mode(has_first: bool, has_last: bool, n_pictures: int, n_clips: int,
                  n_sounds: int = 0, has_storyboard: bool = False) -> str:
    """Which H3 task the tray describes, decided by what each slot says it is rather than by prose.

    The user set a picture to `first frame` or to `something in the shot`, and those are different
    jobs with different model weights behind them. Reading the answer off the tray means the graph
    and the brief cannot disagree, which is the failure this replaced: the compiler deciding an image
    was an opening frame while the graph fed it as a reference, with nothing to say so.

    A sound counts as a reference. FOUND BY RENDERING: it did not, so a graph with only a music clip
    attached declared t2va while the service correctly wrote ref2va, and the node then printed a
    warning saying the render would come out wrong. It would not have. The service's own rule is
    explicit that an attached video or audio forces ref2va, because H3's frame checkpoint cannot
    accept either, and a warning that fires on a correct graph teaches people to ignore warnings.
    """
    if has_first and has_last:
        return "fl2va"
    if has_last:
        return "l2va"
    if has_first:
        return "i2va"
    # A storyboard counts as a reference for the same reason a sound does: it is an attached file the
    # reference route carries and the frame route cannot, so a graph holding nothing but a board is a
    # ref2va job and saying t2va here would print a warning about a correct graph.
    if n_pictures or n_clips or n_sounds or has_storyboard:
        return "ref2va"
    return "t2va"


def check_mode(declared: str, reported: str) -> str | None:
    """Compare what the graph asked for with what the service says it wrote.

    Returns a sentence when they disagree, or None. The service can still reach a different
    conclusion, and when it does the render is about to be wrong in a way no error would otherwise
    reveal.
    """
    if declared == reported:
        return None
    return (f"the graph is wired for a {declared} job, but the service wrote a {reported} brief. "
            "The brief and the wiring disagree, so the render would come out wrong in a way that "
            "looks like a model problem. Check which sockets you filled: a picture in first frame "
            "is the first frame of the video, and a picture in picture 1 is something the shot "
            "should contain.")


def translate_path(path: str, from_prefix: str, to_prefix: str) -> str:
    """Rewrite a path from ComfyUI's view of the filesystem to the service's view.

    This exists because a path is not a file. ComfyUI on Windows writes a reference to
    C:\\ComfyUI\\temp\\ref.png; a service running in WSL or a container looks at the very same bytes
    through /mnt/c/ComfyUI/temp/ref.png and cannot open the Windows spelling. Both are correct and
    neither program can work the other one out, so the mapping is stated once by whoever set the two
    of them up.

    Empty prefixes mean no translation, which is right whenever both halves see one filesystem.
    """
    if not from_prefix or not to_prefix:
        return path
    norm = path.replace("\\", "/")
    src = from_prefix.replace("\\", "/").rstrip("/")
    if not norm.lower().startswith(src.lower()):
        return path
    return to_prefix.rstrip("/") + norm[len(src):]


# --------------------------------------------------------------------------- the machine's files

def merge_model_options(native: list[str], gguf: list[str]) -> list[str]:
    """One combo listing both builds of the same folder, sorted so a checkpoint's variants land
    next to each other.

    `unet_gguf` and `clip_gguf` are not different places: ComfyUI-GGUF registers them over the very
    same directories with a `.gguf` extension filter, so the GGUF build of a checkpoint sits beside
    the safetensors build and the only thing that tells them apart is the extension. Merging the two
    views is therefore one control describing one fact, and every state of it is valid.

    The GGUF half comes from that pack's own registered list and is never globbed off the disk. A
    file listed with no loader behind it is the plausible-and-wrong option this pack exists to
    prevent, so an install without the pack is offered nothing.
    """
    seen: dict[str, str] = {}
    for name in list(native) + list(gguf):
        seen.setdefault(name.lower(), name)
    return sorted(seen.values(), key=lambda s: (s.lower(), s))


def is_gguf(name: str) -> bool:
    """The file is the toggle. A boolean beside a filename would be a second source of truth for
    one fact, with two of its four states wrong and nothing on the canvas to resolve them."""
    return name.strip().lower().endswith(".gguf")


def unet_loader_for(name: str) -> str:
    return LOADER_GGUF_UNET if is_gguf(name) else LOADER_NATIVE_UNET


def clip_loader_for(name: str) -> str:
    return LOADER_GGUF_CLIP if is_gguf(name) else LOADER_NATIVE_CLIP


# The words H3's own two checkpoint families put in their filenames. Used for one thing only: saying
# out loud that a pick looks like the other family. Never for choosing a file, because which file the
# user meant is not something a filename can answer.
REFERENCE_FAMILY = "ref2va"
FRAMES_FAMILY = "fl2va"


def family_warning(chosen: str, *, frames_job: bool) -> str:
    """A plain warning when the picked checkpoint's own name says it is the other H3 family.

    The two slots are easy to swap and both files load: a reference checkpoint on a first-and-last
    frame job renders something plausible with nothing on screen to say why it ignored the frames.
    So the filename is read, and only where it decides the question. A name carrying the other
    family's word and not this one's is evidence; a name carrying neither is not, and a name carrying
    both cannot be read. Silence in those cases, because a guess dressed as a warning teaches people
    to ignore warnings.

    It never blocks the render. Which file is right is the user's call and a renamed file is still
    the file they meant.
    """
    wanted, other = ((FRAMES_FAMILY, REFERENCE_FAMILY) if frames_job
                     else (REFERENCE_FAMILY, FRAMES_FAMILY))
    name = (chosen or "").lower()
    if other not in name or wanted in name:
        return ""
    job = "a first and last frame job" if frames_job else "a reference or text job"
    slot = "fl2va model" if frames_job else "ref2va model"
    return (f"{chosen} names H3's {other} family, and this graph is {job}, which runs on the "
            f"{wanted} checkpoint. Check the {slot} field on the Setup node: it will render either "
            "way, and it will be wrong in a way nothing on screen explains.")


# --------------------------------------------------------------------------- the bundles

def setup_bundle(*, server: str, reference_model: str, frames_model: str, text_encoder: str,
                 video_vae: str, audio_vae: str, weight_dtype: str,
                 timeout_s: int) -> dict[str, Any]:
    """One socket carrying the eight facts that describe a machine rather than a shot.

    Every file in it was picked by a person. Nothing here searches, prefers a build or fills a gap:
    which file was meant is not a question a filename can answer, and a node that answered it anyway
    was choosing for the user without saying so.
    """
    address = (server or "").strip()
    if not address:
        raise ServiceError(
            "the service field is empty. Put the address the OpenH3-IR service listens on, for "
            f"example {DEFAULT_SERVER}, or delete this node to use that address.")
    if not address.startswith(("http://", "https://")):
        raise ServiceError(
            f"the service address {address!r} has no scheme, so nothing can be requested from it. "
            f"Write it in full, for example {DEFAULT_SERVER}.")
    if weight_dtype not in WEIGHT_DTYPES:
        raise ServiceError(f"weight_dtype {weight_dtype!r} is not one of {WEIGHT_DTYPES}.")
    return {"server": address.rstrip("/"), "reference_model": reference_model,
            "frames_model": frames_model, "text_encoder": text_encoder, "video_vae": video_vae,
            "audio_vae": audio_vae, "weight_dtype": weight_dtype, "timeout_s": int(timeout_s)}


def _detail(body: Any) -> dict[str, Any]:
    d = body.get("detail") if isinstance(body, dict) else None
    return d if isinstance(d, dict) else {}


def _sentence(text: str) -> str:
    """Somebody else's message, closed off so the next sentence does not run into it.

    The service's messages are written for a person and most of them end in a full stop, but not all,
    and `...reports it in its own terms rather than yours That is about the file` is the sort of seam
    that makes a careful message read like a generated one.
    """
    text = str(text).strip()
    return text if not text or text[-1] in ".!?:" else text + "."


def compile_brief(server: str, payload: dict[str, Any], *, timeout: float = 600.0) -> dict[str, Any]:
    """POST the brief, then fetch the render fields. Returns the /prompt body plus the brief id.

    Every branch below is a failure a user hit or can hit, turned into a sentence that says what to
    do next. The status codes and payload shapes come from the service's own route handlers.
    """
    status, body = _request(server, "/v1/briefs", payload=payload, timeout=timeout)

    if status == 422:
        det = _detail(body)
        code = det.get("code", "")
        if code in ("asset-no-path", "asset-missing"):
            raise ServiceError(
                f"the service could not read an attachment: {det.get('message', code)}. "
                "ComfyUI and the service are looking at the same file through different paths, for "
                "example /mnt/c/ComfyUI-Production where ComfyUI itself says C:\\ComfyUI-Production. "
                "The node tries the plausible spellings itself and this is what is left when none of "
                "them opened. If the service runs on another machine entirely it cannot open "
                "ComfyUI's files at all, and only text-only prompts will work; if it runs beside "
                "ComfyUI, give it read access to ComfyUI's folder.", PATH_MAY_BE_WRONG)
        if code == "asset-unreadable":
            # The file was found and opened, and could not be used. A different spelling of the path
            # cannot help, so this must NOT carry the retry marker. The analyser writes these for a
            # person to read and already names the file and what is wrong with it, so it is passed
            # through whole and only the socket-side action is added.
            raise ServiceError(
                f"the service opened your attachment and could not use it: "
                f"{_sentence(det.get('message', code))} That is about the file rather than about the wiring: a "
                "different path would fail the same way. Check what the socket is fed from, and that "
                "a clip goes to a Footage node and a sound to a Sound node.")
        if code == "over-capacity":
            raise ServiceError(
                f"more references than H3 has sockets for: {_sentence(det.get('message', code))} Nothing "
                "was silently dropped, because which reference matters is your call. Unplug what you can "
                "spare: H3 takes nine pictures, three clips and three standalone sounds.")
        problems = body.get("errors") if isinstance(body, dict) else None
        if problems:
            lines = "\n  ".join(f"{p.get('rule')}: {p.get('message')}" for p in problems)
            raise ServiceError(
                "the request contradicts itself, so no brief was written:\n  " + lines)
        raise ServiceError(f"the service rejected the request: {det.get('message') or body}")

    if status == 503:
        det = _detail(body)
        if det.get("code") == "analysis-tool-missing":
            # A missing binary is the service host's problem and shares the 503 shape with an LLM
            # outage. Reading the shape alone and printing the LLM message would send someone to fix
            # an endpoint that is working, which is the wrong-message failure this pack exists to
            # avoid. The analyser already names the tool and how to install it, so it is passed
            # through and only the location is added.
            raise ServiceError(
                f"the OpenH3-IR service at {server} cannot read your attachment because a tool it "
                f"needs is not installed where it runs: {_sentence(det.get('message', ''))} This is about the "
                "machine running the service, not about your graph. A text-only prompt still works.")
        raise ServiceError(
            f"the OpenH3-IR service at {server} is running, but the language model endpoint it "
            f"writes with is not answering: {det.get('message', '')}. That endpoint is "
            "yours, set as H3IR_LLM_URL where the service runs. Bring it up and queue again.")

    if status == 502:
        raise ServiceError(
            "the language model endpoint answered with an error rather than a brief: "
            f"{_detail(body).get('message', '')}. Nothing is wrong with this node or the graph.")

    if status == 500:
        raise ServiceError(
            "the service failed internally while writing the brief, which is a bug in the service "
            "rather than in your request. Its console output has the detail.")

    if status != 201:
        raise ServiceError(f"unexpected reply from {server}: HTTP {status}: "
                           f"{str(body)[:400]}")

    if not isinstance(body, dict) or not body.get("id"):
        raise ServiceError(f"the service accepted the brief but returned no id: {str(body)[:300]}")

    brief_id = body["id"]

    if body.get("status") == "needs_input":
        q = body.get("question") or {}
        asked = q.get("question") or "it needs one decision from you"
        default = body.get("default_if_unanswered")
        raise ServiceError(
            f"the compiler needs one thing settled before it can write this brief: {asked} "
            + (f"It would otherwise assume: {default}. " if default else "")
            + "State it in the intent text, for example by saying whether an attached image is the "
              "opening frame or a reference for how something looks.")

    status2, prompt_body = _request(server, f"/v1/briefs/{brief_id}/prompt", timeout=timeout)
    if status2 != 200 or not isinstance(prompt_body, dict):
        raise ServiceError(
            f"the brief compiled as {brief_id}, but reading its render fields failed with HTTP "
            f"{status2}. The service may have restarted between the two calls; queue again.")

    out = dict(prompt_body)
    out["brief_id"] = brief_id
    out["degraded"] = body.get("status") == "degraded"
    out["fallback_reason"] = body.get("fallback_reason") or ""
    return out


def render_fields(prompt_body: dict[str, Any]) -> tuple[str, int, int, int, str]:
    """Pull out the five things a graph needs, refusing to invent any of them.

    A missing field here would otherwise become a plausible default, and a plausible default is how
    someone renders at the wrong length and blames the model.
    """
    prompt = prompt_body.get("prompt")
    frames = prompt_body.get("frames")
    canvas = prompt_body.get("canvas")
    if not isinstance(prompt, str) or not prompt.strip():
        raise ServiceError("the service returned an empty prompt, so there is nothing to render.")
    if not isinstance(frames, int) or frames <= 0:
        raise ServiceError(f"the service returned no usable frame count (got {frames!r}).")
    if not (isinstance(canvas, (list, tuple)) and len(canvas) == 2):
        raise ServiceError(f"the service returned no usable canvas (got {canvas!r}).")
    width, height = int(canvas[0]), int(canvas[1])

    sizings = {w.get("sizing") for w in prompt_body.get("wiring") or [] if w.get("sizing")}
    sizing = sizings.pop() if len(sizings) == 1 else "match"
    return prompt, width, height, int(frames), sizing


# --------------------------------------------------------------------------- the report

# Every report line is `label` in a 15 character column and then the fact, so the facts line up in
# whatever monospace box the user reads them in.
_COL = 15


def line(label: str, text: str) -> str:
    """One report line, wrapped with its continuations under the fact rather than under the label."""
    return textwrap.fill(text, width=94, initial_indent=label.ljust(_COL),
                         subsequent_indent=" " * _COL)


def length_notes(asked_seconds: float, frames: int) -> list[str]:
    """What the length really came out as, and whether it left H3's trained band.

    Neither is a warning. A long render is a choice, not a fault, and `note` is the register this
    report already uses for choices. Both are here because the surface deliberately allows lengths
    the model was never trained on, and a surface that allows something has to say what it did.
    """
    out: list[str] = []
    asked_frames = max(5, round(float(asked_seconds) * FPS))
    if asked_frames != frames:
        out.append(line("asked for", f"{float(asked_seconds):.1f}s, snapped up onto the frame grid"))
    real = frames / FPS
    if frames > TRAINED_MAX_FRAMES:
        out.append(line("note", f"{real:.3f}s is past H3's trained band, which ends at "
                                f"{TRAINED_MAX_FRAMES} frames, "
                                f"{TRAINED_MAX_FRAMES / FPS:.3f}s. It still renders, it is "
                                "untested, and it costs VRAM and time in proportion."))
    elif frames < TRAINED_MIN_FRAMES:
        out.append(line("note", f"{real:.3f}s is below H3's trained band, which starts at "
                                f"{TRAINED_MIN_FRAMES} frames, "
                                f"{TRAINED_MIN_FRAMES / FPS:.3f}s. It still renders, and it is "
                                "untested."))
    return out


def precision_ignored_note() -> str:
    return line("note", "weight_dtype does not apply to a GGUF checkpoint, which carries its "
                        "own quantisation, so it was ignored.")


def bindings_by_content(written: list[tuple[str, str, str, dict[str, Any]]],
                        sha_of: Any) -> dict[str, list[str]]:
    """slot labels per file hash, in the order the slots were numbered.

    A list rather than one name, because two slots can legitimately hold the same file and the
    service addresses files by content, so they are the same file. FOUND BY RENDERING: keyed by hash
    alone, the second slot overwrote the first and one of the two labels printed as `?`. Both are
    real and both get their label, assigned in the order the service numbered them.
    """
    out: dict[str, list[str]] = {}
    for name, _kind, path, _extra in written:
        out.setdefault(sha_of(path), []).append(name)
    return out


def report(prompt_body: dict[str, Any], *, server: str, sizing_conflict: bool,
           asked_seconds: float | None = None,
           bindings: dict[str, list[str]] | None = None) -> str:
    """A short human-readable account of what came back, for a preview node or the console.

    It exists because the interesting facts are the ones a user cannot see in a STRING socket: which
    mode was inferred, whether the length they asked for was moved, and which socket became which
    picture label.

    `bindings` maps a file's sha256 to the tray slots holding it. The service hashes the same bytes,
    so the attachment block below is the service's own manifest with the user's own slot labels put
    back on it: slot, then label, then the input on H3's node it rides. The two sides speak the same
    words, and a label landing on the wrong slot becomes visible instead of becoming a render nobody
    can explain.
    """
    frames = prompt_body.get("frames") or 0
    canvas = prompt_body.get("canvas") or [0, 0]
    lines = [
        line("mode", str(prompt_body.get("mode", "?"))),
        line("length", f"{frames} frames, {frames / FPS:.3f}s at {FPS} fps"),
    ]
    if asked_seconds is not None:
        lines.extend(length_notes(asked_seconds, frames))
    lines.extend([
        line("canvas", f"{canvas[0]}x{canvas[1]}"),
        line("render hash", str(prompt_body.get("render_hash", ""))[:16]),
        line("brief id", f"{prompt_body.get('brief_id', '')}   on {server}"),
    ])

    wiring = prompt_body.get("wiring") or []
    # One label is accepted as well as a list of them, because a bare string is iterable and
    # `list("music")` is five slots called m, u, s, i and c.
    by_sha = {sha: ([names] if isinstance(names, str) else list(names))
              for sha, names in (bindings or {}).items()}
    if wiring:
        lines.append("attachments")
        for w in wiring:
            sha = str(w.get("sha256", ""))
            waiting = by_sha.get(sha) or []
            slot_name = waiting.pop(0) if waiting else "?"
            parts = [f"  {slot_name:<14} ->  {w.get('label')}", str(w.get("wiring"))]
            if w.get("retention"):
                parts.append(str(w["retention"]))
            # Only where it means something. A sound has no pixel area to fit, and the service's own
            # default lands "match" on every entry, so printing it for audio is noise that reads as a
            # setting somebody chose.
            if w.get("sizing") and w.get("kind", "image") == "image":
                parts.append(f"sizing={w['sizing']}")
            parts.append(f"sha256={sha[:12]}")
            lines.append("  ".join(parts))
    for names in by_sha.values():
        for slot_name in names:
            lines.append(line("note", f"the brief does not mention what is in {slot_name}, so it "
                                      "reached the service and was left out. Nothing in the render "
                                      "will refer to it."))
    if sizing_conflict:
        lines.append(line("note", "the references do not all want the same sizing. The H3 node has "
                                  "one ref_image_size for all of them, so pick per the list "
                                  "above."))
    if prompt_body.get("degraded"):
        lines.append(line("note", "the brief is a fallback, not a written one: "
                                  f"{prompt_body.get('fallback_reason')}"))
    return "\n".join(lines)


def inputs_fingerprint(*parts: Any) -> str:
    """Stable hash of everything that can change the brief, for ComfyUI's IS_CHANGED.

    The compiler is seeded, so the same inputs produce the same brief. That makes content hashing
    the honest cache key: re-queueing an unchanged graph should not spend another model call, and
    changing any input, including an image's pixels, must re-compile.
    """
    h = hashlib.sha256()
    for p in parts:
        h.update(repr(p).encode("utf-8", "replace"))
        h.update(b"\x1f")
    return h.hexdigest()
