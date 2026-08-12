"""LLM client, with the endpoint's measured failure modes handled once, here.

Three things were measured against the live endpoint and each one fails SILENTLY if you
don't handle it. They are handled in this wrapper so no stage has to remember:

  F15  It is a thinking model and vLLM returns the thinking in a separate `reasoning`
       field. With a small budget, reasoning consumes it all and `content` comes back
       None with finish_reason 'length' and NO error. -> we raise.
       Only `chat_template_kwargs: {"enable_thinking": false}` suppresses it;
       `{"thinking": false}` is accepted and silently ignored.

  F16  `response_format: json_schema` with strict:true is NOT APPLIED while thinking is
       enabled. A strict AssetCard schema came back as an ASCII-art table, finish_reason
       'stop', no error. -> structured calls force thinking off.

  F17  Even with thinking off the grammar constrains shape, not completion or sense: a
       string can run to max_tokens and return unterminated, unparseable JSON. -> we
       check finish_reason, parse, and re-validate required keys ourselves.
"""
from __future__ import annotations

import base64
import json
import logging
import mimetypes
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from .config import get_config

log = logging.getLogger("h3ir.backend")

# Ceiling for the truncation-retry ladder, so a looping model cannot multiply the wait.
MAX_GROWTH_BASE = 16000


class BackendError(RuntimeError):
    """Raised loudly. We never quietly downgrade: a caller cannot tell a good IR from a
    bad one, so silently halving quality is the failure nobody notices."""


class BackendUnavailable(BackendError):
    pass


class TruncatedResponse(BackendError):
    pass


@dataclass
class Reply:
    content: str
    reasoning: str
    prompt_tokens: int
    completion_tokens: int
    finish_reason: str
    wall_s: float
    model: str

    @property
    def reasoning_share(self) -> float:
        if not self.completion_tokens:
            return 0.0
        # crude but useful: reasoning chars vs content chars
        total = len(self.reasoning) + len(self.content)
        return len(self.reasoning) / total if total else 0.0


def image_data_url(path: str | Path) -> str:
    p = Path(path)
    mime = mimetypes.guess_type(p.name)[0] or "image/png"
    return f"data:{mime};base64,{base64.b64encode(p.read_bytes()).decode()}"


def user_message(text: str, images: list[str | Path] | None = None) -> dict[str, Any]:
    """Multipart user turn. Verified: this endpoint reads images and can attribute several
    of them correctly within one request."""
    if not images:
        return {"role": "user", "content": text}
    parts: list[dict[str, Any]] = [{"type": "text", "text": text}]
    for i, img in enumerate(images, 1):
        parts.append({"type": "text", "text": f"Image {i}:"})
        parts.append({"type": "image_url", "image_url": {"url": image_data_url(img)}})
    return {"role": "user", "content": parts}


class Backend:
    def __init__(self, cfg=None, client: httpx.Client | None = None):
        self.cfg = (cfg or get_config()).llm
        self._client = client
        self._owns_client = client is None
        self._resolved_model: str | None = None

    def model_id(self) -> str:
        """The model id to send. Set by config, or discovered by `require_available`."""
        return self.cfg.model or self._resolved_model or ""

    def _discover_model(self) -> None:
        """Ask the endpoint what it serves and take the first id.

        Only called from `require_available`, i.e. only on a path that is about to talk to a real
        server. A local server almost always serves exactly one model, so making its full name a
        required setting is a configuration step with no decision in it — and getting it wrong
        returns a 400 that reads like a malformed request rather than a typo in an env var.
        """
        try:
            data = self._http().get(f"{self.cfg.base_url}/models", timeout=10.0).json()
            ids = [m.get("id") for m in data.get("data", []) if m.get("id")]
        except Exception as e:  # noqa: BLE001 - re-raised as a BackendError below
            raise BackendUnavailable(
                f"H3IR_LLM_MODEL is not set and {self.cfg.base_url}/models could not be read to "
                f"discover it: {e}") from e
        if not ids:
            raise BackendUnavailable(
                f"H3IR_LLM_MODEL is not set and {self.cfg.base_url}/models named no models. "
                "Set H3IR_LLM_MODEL to the id your endpoint serves.")
        self._resolved_model = ids[0]

    def _http(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(timeout=self.cfg.timeout_s)
        return self._client

    def close(self) -> None:
        if self._client is not None and self._owns_client:
            self._client.close()
            self._client = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # ------------------------------------------------------------------ health

    def health(self) -> bool:
        try:
            r = self._http().get(self.cfg.base_url.rsplit("/v1", 1)[0] + "/health", timeout=5.0)
            return r.status_code == 200
        except httpx.HTTPError:
            return False

    def server_version(self) -> str:
        """Recorded with every render. This bug family is version-dependent, so an upgrade
        invalidates the assumptions in this file."""
        try:
            r = self._http().get(self.cfg.base_url.rsplit("/v1", 1)[0] + "/version", timeout=5.0)
            return str(r.json().get("version", "?"))
        except Exception:  # noqa: BLE001 - provenance only
            return "?"

    def require_available(self) -> None:
        if not self.health():
            raise BackendUnavailable(
                f"the reasoning model at {self.cfg.base_url} is not reachable. "
                "Start it, or set H3IR_LLM_URL. Refusing to produce a lower-quality IR silently.")
        if not self.cfg.model and self._resolved_model is None:
            self._discover_model()

    # ------------------------------------------------------------------ calls

    def chat(self, messages: list[dict[str, Any]], *, thinking: bool | None = None,
             max_tokens: int | None = None, temperature: float = 0.7,
             seed: int | None = None, response_format: dict[str, Any] | None = None,
             stop: list[str] | None = None, retries: int = 2) -> Reply:
        if thinking is None:
            thinking = self.cfg.default_thinking
        # F16: a schema is only honoured with thinking off. Refuse the unsafe combination
        # rather than returning prose that looks like a schema failure nobody notices.
        if response_format is not None and thinking:
            raise BackendError(
                "structured output requires thinking=False on this endpoint "
                "(json_schema is silently not applied while reasoning is enabled)")

        body: dict[str, Any] = {
            "model": self.model_id(),
            "messages": messages,
            "max_tokens": max_tokens or self.cfg.max_tokens,
            "temperature": temperature,
        }
        if seed is not None:
            body["seed"] = seed
        if stop:
            body["stop"] = stop
        if response_format is not None:
            body["response_format"] = response_format
        if not thinking:
            # The ONLY spelling that works. {"thinking": False} is silently ignored.
            body["chat_template_kwargs"] = {"enable_thinking": False}

        last: Exception | None = None
        for attempt in range(retries + 1):
            try:
                return self._once(body)
            except (TruncatedResponse, httpx.HTTPError) as e:
                last = e
                if attempt < retries:
                    # Growing the budget is right when reasoning ate it, and wrong when the
                    # model is looping -- there, each retry multiplies the wasted time. So the
                    # ladder is capped rather than open-ended.
                    if isinstance(e, TruncatedResponse):
                        grown = int(body["max_tokens"] * 1.75)
                        ceiling = max(self.cfg.max_tokens, 2 * MAX_GROWTH_BASE)
                        if grown > ceiling:
                            log.warning("truncated at %s tokens and the ceiling is %s; not "
                                        "growing further", body["max_tokens"], ceiling)
                            break
                        body["max_tokens"] = grown
                        log.warning("truncated; retrying with max_tokens=%s", body["max_tokens"])
                    else:
                        time.sleep(1.5 * (attempt + 1))
                    continue
                break
        # Re-raise the original so callers can still see WHY it failed. TruncatedResponse is a
        # BackendError, so `except BackendError` in the compiler still catches it and falls back.
        if isinstance(last, BackendError):
            raise last
        raise BackendError(f"chat failed after {retries + 1} attempt(s): {last}") from last

    def _once(self, body: dict[str, Any]) -> Reply:
        t0 = time.time()
        r = self._http().post(f"{self.cfg.base_url}/chat/completions", json=body)
        wall = time.time() - t0
        if r.status_code >= 400:
            raise BackendError(f"HTTP {r.status_code}: {r.text[:400]}")
        data = r.json()
        choice = (data.get("choices") or [{}])[0]
        msg = choice.get("message") or {}
        content = msg.get("content")
        reasoning = msg.get("reasoning") or msg.get("reasoning_content") or ""
        usage = data.get("usage") or {}
        finish = choice.get("finish_reason") or "?"

        # F15: reasoning ate the budget. Loud, not empty-string.
        if content is None or not str(content).strip():
            raise TruncatedResponse(
                f"model returned no content (finish_reason={finish}, "
                f"completion_tokens={usage.get('completion_tokens')}, "
                f"reasoning_chars={len(reasoning)}) — the reasoning budget was consumed "
                "before any answer was emitted")
        if finish == "length":
            raise TruncatedResponse(
                f"response hit max_tokens ({body['max_tokens']}); output is incomplete")

        # vLLM #35221: when generation truncates before `</think>`, the Qwen3 reasoning parser
        # cannot tell "thinking off" from "thinking unfinished" and puts raw in-progress
        # reasoning into `content`. An unclosed marker means this reply is reasoning, not an
        # answer, so trust the marker rather than the field split.
        text = str(content)
        if "<think>" in text and "</think>" not in text:
            raise TruncatedResponse(
                "content carries an unclosed <think> — this is leaked in-progress reasoning, "
                "not an answer (vLLM #35221)")

        return Reply(content=str(content).strip(), reasoning=reasoning,
                     prompt_tokens=usage.get("prompt_tokens", 0),
                     completion_tokens=usage.get("completion_tokens", 0),
                     finish_reason=finish, wall_s=wall, model=data.get("model", ""))

    # ------------------------------------------------------------------ structured

    def json_call(self, messages: list[dict[str, Any]], schema: dict[str, Any], *,
                  required: tuple[str, ...] = (), max_tokens: int | None = None,
                  seed: int | None = None, temperature: float = 0.0,
                  thinking: bool | None = None, retries: int = 2) -> dict[str, Any]:
        """A structured call that never trusts the grammar.

        Two modes, and the default is the one without grammar. With guided decoding off we ask
        for JSON in the prompt and extract it, which also allows thinking=True -- and thinking
        is what the planning call wants (arXiv:2606.09662: +5.3pp on planning constraints).
        With it on, the schema is a hint only; the shape is still checked here, because the
        grammar constrains shape but neither completion nor sense.
        """
        use_grammar = self.cfg.guided_decoding
        if thinking is None:
            # OFF unless a caller asks. arXiv:2505.11423's effective mitigation is
            # classifier-selective reasoning -- think for the PLANNING call, not for emission or
            # extraction calls, where thinking measurably hurts precision constraints (-8.5pp)
            # and costs a budget these small calls do not have.
            thinking = False
        rf = None
        msgs = list(messages)
        if use_grammar:
            thinking = False        # grammar + reasoning parser is the unsafe combination
            rf = {"type": "json_schema",
                  "json_schema": {"name": schema.get("title", "Result"), "schema": schema,
                                  "strict": True}}
        else:
            msgs[-1] = dict(msgs[-1])
            msgs[-1]["content"] = _append_text(msgs[-1]["content"], _schema_ask(schema))
        last: Exception | None = None
        for attempt in range(retries + 1):
            # A retry has to ask a DIFFERENT question, and at temperature 0 with a fixed seed it
            # cannot: the decode is deterministic, so re-sending identical messages returns the
            # identical reply. Measured, not theorised -- three attempts produced three
            # byte-identical 524-token replies in which the model echoed the schema instead of
            # filling it, on a vision call whose only unusual feature was an appended caller note.
            # Temperature demonstrably breaks that tie where the seed does not, because at
            # temperature 0 the seed changes nothing. So attempt 0 keeps the caller's temperature,
            # which keeps the common path reproducible and cacheable, and only the retries move.
            temp = temperature if attempt == 0 else temperature + 0.4 * attempt
            reply = self.chat(msgs, thinking=thinking, response_format=rf,
                              max_tokens=max_tokens, temperature=temp, seed=seed,
                              retries=1)
            try:
                obj = json.loads(_extract_json(reply.content))
            except json.JSONDecodeError as e:
                last = BackendError(f"schema-shaped output did not parse: {e}: "
                                    f"{reply.content[:200]!r}")
                log.warning("%s", last)
                continue
            if not isinstance(obj, dict):
                last = BackendError(f"expected a JSON object, got {type(obj).__name__}")
                continue
            missing = [k for k in required if k not in obj]
            if missing:
                if _is_the_schema_itself(obj):
                    last = BackendError(
                        f"the model returned the schema document instead of an instance of it "
                        f"(missing {missing}); retrying at a higher temperature")
                else:
                    how = ("strict schema" if use_grammar
                           else "schema asked for in the prompt, not enforced by a grammar")
                    last = BackendError(f"required key(s) absent, {how}: {missing}")
                log.warning("%s", last)
                continue
            return obj
        raise BackendError(f"structured call failed after {retries + 1} attempt(s): {last}")


def _is_the_schema_itself(obj: dict[str, Any]) -> bool:
    """True when the reply is the schema document rather than an instance of it.

    A valid-JSON failure, which is why it survives parsing and shows up as absent keys. Seen on a
    vision call where an appended caller note tipped a greedy decode into copying the schema back:
    the object's keys were `title`, `type`, `properties`, `required`, `additionalProperties`.
    Naming it turns a confusing "required key absent" into a message that says what happened.
    """
    return obj.get("type") == "object" and isinstance(obj.get("properties"), dict)


def _schema_ask(schema: dict[str, Any]) -> str:
    return ("\n\nReturn ONE JSON object and nothing else — no prose before or after it, "
            "no code fence. It must match this schema:\n" + json.dumps(schema, indent=1))


def _append_text(content: Any, extra: str) -> Any:
    """Append an instruction without destroying a multimodal message.

    A multipart `content` is a LIST of parts, one of which holds a base64 data URL. Coercing it
    with str() stringifies the whole list -- including the entire image as literal text -- which
    silently explodes the prompt by orders of magnitude and looks like the endpoint hanging. It
    is not a hypothetical: it cost ten minutes of a stalled acceptance run to find.
    """
    if isinstance(content, list):
        return list(content) + [{"type": "text", "text": extra}]
    return str(content) + extra


def _extract_json(text: str) -> str:
    """Pull the object out of a reply that may carry a fence or a sentence around it."""
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z]*\s*", "", t)
        t = re.sub(r"\s*```$", "", t).strip()
    if t.startswith("{"):
        return t
    start = t.find("{")
    end = t.rfind("}")
    if start >= 0 and end > start:
        return t[start:end + 1]
    return t


def probe(cfg=None) -> dict[str, Any]:
    """Report what the endpoint is and what it supports. Used by `h3ir doctor`."""
    c = cfg or get_config()
    out: dict[str, Any] = {"url": c.llm.base_url,
                           "model": c.llm.model or "(unset — will use the endpoint's first)"}
    with Backend(c) as b:
        out["health"] = b.health()
        if not out["health"]:
            return out
        try:
            r = b._http().get(f"{c.llm.base_url}/models", timeout=10.0).json()
            ids = [m.get("id") for m in r.get("data", [])]
            out["model_ids"] = ids
            out["max_model_len"] = next(
                (m.get("max_model_len") for m in r.get("data", []) if m.get("max_model_len")), None)
        except Exception as e:  # noqa: BLE001 - diagnostics only
            out["models_error"] = str(e)
        try:
            reply = b.chat([{"role": "user", "content": "Reply with the single word: ready"}],
                           thinking=False, max_tokens=32, temperature=0.0)
            out["chat_ok"] = "ready" in reply.content.lower()
            out["latency_s"] = round(reply.wall_s, 2)
        except BackendError as e:
            out["chat_error"] = str(e)
    return out
