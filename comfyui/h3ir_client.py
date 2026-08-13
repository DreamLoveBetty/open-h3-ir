"""Talking to an OpenH3-IR service, with no ComfyUI and no third-party packages involved.

Everything in this module is a pure function or a thin call over the standard library, so the whole
integration can be tested without ComfyUI, without torch, and without a running server. The node in
`nodes.py` owns the parts that can only exist inside ComfyUI: tensors, temp directories, and the
schema the canvas draws.

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


class ServiceError(RuntimeError):
    """Raised for every failure a node user can act on. The message is the user interface."""


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
            "the node's timeout_s, or point it at a faster endpoint.") from e
    except urllib.error.URLError as e:
        raise ServiceError(
            f"cannot reach an OpenH3-IR service at {server} ({e.reason}). Start one from the repo "
            f"with: h3ir serve --port {DEFAULT_PORT}. If it runs on another machine, set this "
            "node's server field to that address, and remember the service needs H3IR_LLM_URL "
            "pointing at your own OpenAI-compatible endpoint.") from e


def _decode(body: str) -> Any:
    try:
        return json.loads(body) if body else None
    except json.JSONDecodeError:
        return body


def build_payload(intent: str, *, seconds: float, aspect: str, creativity: str, effort: str,
                  seed: int, silent: bool, shots: int, assets: list[dict[str, Any]],
                  transcripts: dict[str, str]) -> dict[str, Any]:
    """Turn the node's state into the service's BriefIn.

    Assets arrive already shaped, with their role named, because the node knows the role from the
    socket the user plugged into. Nothing here infers a role: an inferred role can disagree with how
    the graph is wired, and a graph that disagrees with its own brief renders something plausible
    and wrong.

    `shots` of 0 means "the compiler decides", which is the service's own default when the field is
    absent, so 0 is dropped rather than sent as a shot count of zero.
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
    if int(shots) > 0:
        payload["shots"] = int(shots)
    if transcripts:
        payload["transcripts"] = dict(transcripts)
    return payload


# Sockets, in the order their contents get numbered, and the role each one means. The role is named
# here rather than inferred by the service, because an inferred role can disagree with how the graph
# is wired and nothing would say so.
PICTURE_SOCKETS = ("reference_1", "reference_2", "reference_3", "reference_4")
VIDEO_SOCKETS = ("video_to_edit", "video_to_continue")
SOUND_SOCKETS = ("music", "sound_effect", "voice_to_match")
ROLE_BY_SOCKET = {
    "opening_frame": "frame_anchor_first",
    "closing_frame": "frame_anchor_last",
    "reference_1": "subject", "reference_2": "subject",
    "reference_3": "subject", "reference_4": "subject",
    "video_to_edit": "edit_source",
    "video_to_continue": "continuation_source",
    "music": "bgm",
    "sound_effect": "sfx",
    "voice_to_match": "voice_timbre",
}


def plan_assets(written: list[tuple[str, str, str, dict[str, Any]]], picture_notes: list[str],
                sound_notes: list[str], sizing: str, from_prefix: str,
                to_prefix: str) -> list[dict[str, Any]]:
    """Describe every attached file for the service, in the order it should be numbered.

    `written` is already on disk: a list of (socket, kind, path, extra). Notes are matched by
    position within their own kind, so the second line of picture_notes describes the second picture
    and is not thrown off by a video sitting between them.
    """
    assets: list[dict[str, Any]] = []
    pic_i = snd_i = 0
    for socket, kind, path, extra in written:
        if socket not in ROLE_BY_SOCKET:
            raise ServiceError(f"internal: no role recorded for socket {socket!r}")
        a: dict[str, Any] = {"path": translate_path(path, from_prefix, to_prefix),
                             "kind": kind, "role": ROLE_BY_SOCKET[socket]}
        note = ""
        if kind == "image":
            a["sizing"] = sizing
            note = picture_notes[pic_i] if pic_i < len(picture_notes) else ""
            pic_i += 1
        elif kind == "audio":
            note = sound_notes[snd_i] if snd_i < len(sound_notes) else ""
            snd_i += 1
        if note.strip():
            a["note"] = note.strip()
        a.update(extra)
        assets.append(a)
    return assets


def expected_mode(has_opening: bool, has_closing: bool, n_references: int,
                  n_videos: int) -> str:
    """Which H3 task the wiring describes, decided by the sockets rather than by prose.

    The user plugged a picture into `opening_frame` or into `reference_1`, and those are different
    jobs with different model weights behind them. Reading the answer off the sockets means the
    graph and the brief cannot disagree, which is the failure this replaced: the compiler deciding
    an image was an opening frame while the graph fed it as a reference, with nothing to say so.
    """
    if has_opening and has_closing:
        return "fl2va"
    if has_closing:
        return "l2va"
    if has_opening:
        return "i2va"
    if n_references or n_videos:
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
            "looks like a model problem. Check which sockets you filled: a picture in "
            "opening_frame is the first frame of the video, and a picture in reference_1 is "
            "something the shot should contain.")


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


def _detail(body: Any) -> dict[str, Any]:
    d = body.get("detail") if isinstance(body, dict) else None
    return d if isinstance(d, dict) else {}


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
                f"the service could not read a reference image: {det.get('message', code)}. "
                "ComfyUI and the service are looking at the same file through different paths. "
                "Fill in this node's comfy_path_prefix and service_path_prefix so the path can be "
                "translated, for example C:\\ComfyUI-Production and /mnt/c/ComfyUI-Production. If "
                "the service runs on another machine entirely it cannot open ComfyUI's files at "
                "all, and only text-only prompts will work.")
        problems = body.get("errors") if isinstance(body, dict) else None
        if problems:
            lines = "\n  ".join(f"{p.get('rule')}: {p.get('message')}" for p in problems)
            raise ServiceError(
                "the request contradicts itself, so no brief was written:\n  " + lines)
        raise ServiceError(f"the service rejected the request: {det.get('message') or body}")

    if status == 503:
        raise ServiceError(
            f"the OpenH3-IR service at {server} is running, but the language model endpoint it "
            f"writes with is not answering: {_detail(body).get('message', '')}. That endpoint is "
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


def report(prompt_body: dict[str, Any], *, server: str, sizing_conflict: bool) -> str:
    """A short human-readable account of what came back, for a preview node or the console.

    It exists because the interesting facts are the ones a user cannot see in a STRING socket: which
    mode was inferred, whether the length they asked for was moved, and which image became which
    picture label.
    """
    frames = prompt_body.get("frames") or 0
    canvas = prompt_body.get("canvas") or [0, 0]
    lines = [
        f"mode           {prompt_body.get('mode', '?')}",
        f"length         {frames} frames, {frames / 24:.3f}s at 24 fps",
        f"canvas         {canvas[0]}x{canvas[1]}",
        f"render hash    {str(prompt_body.get('render_hash', ''))[:16]}",
        f"brief id       {prompt_body.get('brief_id', '')}   on {server}",
    ]
    wiring = prompt_body.get("wiring") or []
    if wiring:
        lines.append("references")
        for w in wiring:
            lines.append(f"  {w.get('label')}  {w.get('wiring')}  sizing={w.get('sizing')}  "
                         f"sha256={str(w.get('sha256', ''))[:12]}")
    if sizing_conflict:
        lines.append("note           the references do not all want the same sizing. The H3 node "
                     "has one ref_image_size for all of them, so pick per the list above.")
    if prompt_body.get("degraded"):
        lines.append(f"note           the brief is a fallback, not a written one: "
                     f"{prompt_body.get('fallback_reason')}")
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
