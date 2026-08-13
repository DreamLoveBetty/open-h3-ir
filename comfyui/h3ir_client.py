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
                  seed: int, silent: bool, shots: int, asset_paths: list[str],
                  notes: list[str], sizing: str) -> dict[str, Any]:
    """Turn the node's widgets into the service's BriefIn.

    `shots` of 0 means "the compiler decides", which is the service's own default when the field is
    absent, so 0 is dropped rather than sent as a shot count of zero.
    """
    intent = (intent or "").strip()
    if not intent:
        raise ServiceError(
            "nothing to compile: the intent field is empty. Type what should happen in the shot, "
            "in one ordinary sentence, for example: she walks out onto the wet gantry in the rain "
            "and stops when she sees the city below.")

    assets = []
    for i, p in enumerate(asset_paths):
        asset: dict[str, Any] = {"path": p, "kind": "image", "sizing": sizing}
        note = notes[i].strip() if i < len(notes) and notes[i].strip() else ""
        if note:
            asset["note"] = note
        assets.append(asset)

    payload: dict[str, Any] = {
        "intent": intent,
        "assets": assets,
        "seconds": float(seconds),
        "aspect": aspect,
        "creativity": creativity,
        "effort": effort,
        "seed": int(seed),
        "silent": bool(silent),
    }
    if int(shots) > 0:
        payload["shots"] = int(shots)
    return payload


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
