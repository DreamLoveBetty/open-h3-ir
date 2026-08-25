"""The Qwen2.5-Omni fallback client: one narrow call, strictly parsed (spec §11).

Two halves with different failure cultures:

  * `parse_fallback_payload` is pure and is where the discipline lives. The fallback model is
    a free-form model answering over HTTP, so rule 3 of the repository applies in full:
    structured output from an endpoint is a claim, not a fact. The parser accepts exactly the
    §11 protocol shape and nothing else -- extra keys are not ignored, they reject the whole
    payload, because an Omni that answers with a `tempo_bpm` key is an Omni attempting to
    overwrite a deterministic field (A26) and its remaining claims are no more trustworthy.
  * `FallbackClient` is the thinnest possible HTTP wrapper: it ships the audio and the system
    prompt, and every question worth testing lives in the parser instead. That is the same
    split as audio/client.py, for the same reason -- sockets are for fakes in tests.

The prompt is versioned (`FALLBACK_PROTOCOL_VERSION`) and the version is part of the response
cache key, for the reason ANALYZER_VERSION exists: a cached answer must not survive a change
in the logic that produced it.
"""
from __future__ import annotations

import base64
import json
import logging
import re
import urllib.request
from pathlib import Path
from typing import Any

log = logging.getLogger("h3ir.audio.fallback")

FALLBACK_PROTOCOL_VERSION = "audio-fallback-1"

# Spec §11, verbatim in substance: supplement only, never overwrite the deterministic fields,
# omit rather than invent. This text is the entire licence the fallback model operates under.
FALLBACK_SYSTEM_PROMPT = """You are a fallback acoustic observer.

You may supplement semantic descriptions, but you must not overwrite:
- transcript text
- speaker segment boundaries
- BPM
- beat timestamps
- exact event timestamps
- duration
- user-declared role

If you are uncertain, omit the fact.
Do not invent precise timestamps.
Do not infer story or intent.
Return JSON only."""

# The exact key set of the §11 protocol. A payload carrying ANY other key is rejected whole:
# the merge policy's tiering only holds if the fallback physically cannot address a
# deterministic field, and ignoring a stray `duration` key would let the same attempt through
# quieter. Rejection is reported as A26 by the merge stage, which sees the offending keys.
PROTOCOL_KEYS = {"semantic_summary", "voice_delivery", "music_style", "instrumentation",
                 "soundscape", "event_descriptions", "confidence"}


class FallbackPayloadError(ValueError):
    """The fallback answered with something that is not the §11 protocol. Carries the offending
    keys so the caller can report them instead of a generic parse failure."""

    def __init__(self, msg: str, *, extra_keys: tuple[str, ...] = ()):
        super().__init__(msg)
        self.extra_keys = extra_keys


def _str_list(value: Any, key: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
        raise FallbackPayloadError(f"{key} must be a list of strings")
    return [x.strip() for x in value if x.strip()]


def parse_fallback_payload(text: str) -> dict:
    """Parse and validate one fallback reply against the §11 protocol.

    Returns a normalised dict with exactly the protocol keys. Raises FallbackPayloadError on
    anything else: non-JSON, a JSON scalar, unknown keys, or a field of the wrong shape. The
    caller treats every one of those as "no supplement" -- a fallback that cannot follow its
    own protocol contributes nothing, and the deterministic observation is already complete.
    """
    # The model is told to return JSON only; it sometimes wraps it anyway. Accept the wrapper,
    # never the prose: if there is no object here at all, that is a refusal, not a parse.
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        raise FallbackPayloadError("the fallback reply contains no JSON object")
    try:
        raw = json.loads(m.group(0))
    except json.JSONDecodeError as e:
        raise FallbackPayloadError(f"the fallback reply is not valid JSON: {e}") from e
    if not isinstance(raw, dict):
        raise FallbackPayloadError("the fallback reply is not a JSON object")

    extra = tuple(sorted(set(raw) - PROTOCOL_KEYS))
    if extra:
        raise FallbackPayloadError(
            f"the fallback replied with keys outside the protocol: {', '.join(extra)} -- "
            "the whole payload is rejected rather than read selectively",
            extra_keys=extra)

    out = {
        "semantic_summary": raw.get("semantic_summary") or "",
        "voice_delivery": _str_list(raw.get("voice_delivery"), "voice_delivery"),
        "music_style": _str_list(raw.get("music_style"), "music_style"),
        "instrumentation": _str_list(raw.get("instrumentation"), "instrumentation"),
        "soundscape": _str_list(raw.get("soundscape"), "soundscape"),
        "event_descriptions": [],
        "confidence": 0.0,
    }
    if not isinstance(out["semantic_summary"], str):
        raise FallbackPayloadError("semantic_summary must be a string")
    for item in raw.get("event_descriptions") or []:
        if not isinstance(item, dict) or not isinstance(item.get("description"), str):
            raise FallbackPayloadError("event_descriptions entries must be objects with a "
                                       "string description")
        for tkey in ("approx_start_s", "approx_end_s"):
            tval = item.get(tkey)
            if tval is not None and not isinstance(tval, (int, float)):
                raise FallbackPayloadError(f"{tkey} must be a number or null")
        out["event_descriptions"].append({
            "approx_start_s": item.get("approx_start_s"),
            "approx_end_s": item.get("approx_end_s"),
            "description": item["description"].strip(),
        })
    conf = raw.get("confidence")
    if conf is not None:
        if not isinstance(conf, (int, float)) or not 0.0 <= conf <= 1.0:
            raise FallbackPayloadError("confidence must be a number in [0, 1]")
        out["confidence"] = float(conf)
    return out


class FallbackError(RuntimeError):
    pass


class FallbackClient:
    """One POST to an OpenAI-compatible chat endpoint that can hear (Qwen2.5-Omni).

    The audio goes as a base64 data URL, the shape vLLM's audio-capable chat route accepts.
    Kept deliberately separate from backend.py: that client is the reasoning/vision path with
    its own portability scar tissue, and the fallback's failures must never be mistaken for
    the main model's.
    """

    def __init__(self, cfg):
        self.cfg = cfg  # the AudioConfig block; fallback_* fields only

    def observe(self, audio_path: str) -> dict:
        """Return the parsed §11 payload. Raises FallbackError on transport failure and
        FallbackPayloadError on a protocol violation -- the caller degrades on both."""
        cfg = self.cfg
        data = base64.b64encode(Path(audio_path).read_bytes()).decode()
        payload = {
            "model": cfg.fallback_model,
            "messages": [
                {"role": "system", "content": FALLBACK_SYSTEM_PROMPT},
                {"role": "user", "content": [
                    {"type": "input_audio",
                     "input_audio": {"data": data, "format": "wav"}},
                    {"type": "text", "text": "Describe this audio. Return JSON only."},
                ]},
            ],
            "temperature": 0.0,
        }
        req = urllib.request.Request(
            cfg.fallback_base_url.rstrip("/") + "/chat/completions",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {cfg.fallback_api_key}"})
        try:
            with urllib.request.urlopen(req, timeout=cfg.fallback_timeout_s) as resp:
                body = json.loads(resp.read().decode())
        except Exception as e:
            raise FallbackError(f"{type(e).__name__}: {e}") from e
        try:
            text = body["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as e:
            raise FallbackError(f"malformed chat-completion reply: {e}") from e
        return parse_fallback_payload(text)
