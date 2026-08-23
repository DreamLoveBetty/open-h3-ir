"""One endpoint is not the family.

Everything in `backend.py` was written against a single vLLM server, and "OpenAI-compatible" turns
out to name the chat route and almost nothing around it. The first outside bug report was three
symptoms of that one fact, so these are the properties that keep it from happening again.

The replicas below are built from each server's own published surface, not from an idea of it:

- Ollama's `server/routes.go` registers `/`, `/api/version`, `/v1/models` and the inference paths,
  and nothing named health; its `openai.Model` struct is `id`, `object`, `created`, `owned_by`.
- Cross-checked by running `ollama/ollama:latest` (0.32.15) in a container: `GET /health` answered
  404, `GET /v1/models` answered 200, and with no models pulled `data` came back **null** rather
  than an empty list.
- vLLM 0.21.0 on the machine this was developed against: `/health` 200, `/version` 200, and two
  ids in `/v1/models` sharing one `root`, which is what `--served-model-name` produces.

Every request in these tests is served by a mock, so nothing here needs a network. What the mocks
are allowed to claim is fixed by the two paragraphs above.
"""
from __future__ import annotations

import json
import struct
import zlib

import httpx
import pytest

from h3ir.backend import (VISION_PROBE_DIGITS, Backend, BackendError, BackendUnavailable,
                          EndpointRefused, _DIGIT_GLYPHS, digits_png, probe, vision_check)
from h3ir.config import Config, LLMConfig

BASE = "http://endpoint:11434/v1"

# Measured on the owner's vLLM 0.21.0: one set of weights, published under two ids.
VLLM_ALIASES = [
    {"id": "philbert440/Qwen3.8-27B-Uncensored-Aggressive-W4A16-AWQ", "object": "model",
     "root": "philbert440/Qwen3.8-27B-Uncensored-Aggressive-W4A16-AWQ", "max_model_len": 262144},
    {"id": "qwen3.8u", "object": "model",
     "root": "philbert440/Qwen3.8-27B-Uncensored-Aggressive-W4A16-AWQ", "max_model_len": 262144},
]

# Captured from ollama/ollama 0.32.15 with two models pulled. No `root`, no `max_model_len`, and
# the order is by modification time, so "the first one" is whichever was touched last.
OLLAMA_MODELS = [
    {"id": "smollm2:135m", "object": "model", "created": 1787416180, "owned_by": "library"},
    {"id": "all-minilm:22m", "object": "model", "created": 1787416174, "owned_by": "library"},
]

# Captured from the same container, asking a text-only model to read a picture. Ollama nests a
# whole JSON document inside `error.message` as a string.
OLLAMA_NO_VISION_BODY = json.dumps({"error": {
    "message": json.dumps({"error": {
        "code": 400,
        "message": "Multimodal data provided, but model does not support multimodal requests.",
        "type": "invalid_request_error"}}),
    "type": "invalid_request_error", "param": None, "code": None}})


def _backend(handler, **llm) -> Backend:
    cfg = Config(llm=LLMConfig(**{"base_url": BASE, "model": "", **llm}))
    return Backend(cfg, client=httpx.Client(transport=httpx.MockTransport(handler)))


def _server(*, models: list | None, health: bool, seen: list | None = None):
    """A server that serves a model list, a `/health`, both, or neither."""
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request.url.path)
        if request.url.path == "/v1/models" and models is not None:
            return httpx.Response(200, json={"object": "list", "data": models})
        if request.url.path == "/health" and health:
            return httpx.Response(200, text="")
        return httpx.Response(404, text="404 page not found")
    return handler


# ------------------------------------------------------------------ liveness


def test_an_endpoint_that_serves_no_health_path_is_not_called_unreachable():
    """The reported bug. Ollama has no `/health`, so asking only there said a working server was
    down, and `h3ir doctor` sent its reader off to debug a server that was answering fine."""
    b = _backend(_server(models=OLLAMA_MODELS, health=False))
    hp = b.health_probe()
    assert hp.ok is True, f"a live Ollama was reported unreachable: {hp.attempts}"
    assert hp.via.endswith("/v1/models")


def test_the_probe_names_the_path_that_answered():
    """`doctor` exists to tell somebody the truth about their setup, and "healthy" without saying
    where it came from is a claim they cannot check. A gateway can serve `/health` and no model
    list, so the answer must not be hardcoded to either path."""
    b = _backend(_server(models=None, health=True))
    hp = b.health_probe()
    assert hp.ok is True
    assert hp.via.endswith("/health"), hp.via


def test_the_usual_case_costs_one_request():
    """Two paths must not mean two round trips every time. `/v1/models` is tried first precisely
    because every server in the table serves it, so the second path is only ever a fallback."""
    seen: list[str] = []
    b = _backend(_server(models=VLLM_ALIASES, health=True, seen=seen))
    assert b.health_probe().ok is True
    assert seen == ["/v1/models"], f"the fallback path was requested needlessly: {seen}"


def test_nothing_answering_records_every_path_it_tried():
    b = _backend(_server(models=None, health=False))
    hp = b.health_probe()
    assert hp.ok is False
    assert [u for u, _ in hp.attempts] == [f"{BASE}/models", "http://endpoint:11434/health"]
    assert all("HTTP 404" in what for _, what in hp.attempts), hp.attempts


def test_the_refusal_to_run_says_what_it_tried():
    """The message a user meets when the endpoint is wrong. Naming the URLs turns "not reachable"
    into something they can paste into curl."""
    b = _backend(_server(models=None, health=False))
    with pytest.raises(BackendUnavailable) as e:
        b.require_available()
    assert "not reachable" in str(e.value)
    assert f"{BASE}/models" in str(e.value)
    assert "/health" in str(e.value)


def test_the_server_root_is_not_treated_as_a_liveness_path():
    """Ollama answers `/` with "Ollama is running", and so does every unrelated web server on that
    port. A liveness check that passes against the wrong port is worse than one that fails."""
    def only_root(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/":
            return httpx.Response(200, text="Ollama is running")
        return httpx.Response(404)
    b = _backend(only_root)
    assert b.health_probe().ok is False


def test_a_trailing_slash_in_the_url_does_not_double_up():
    """`H3IR_LLM_URL=http://host:11434/v1/` is an ordinary thing to paste out of a browser, and
    unhandled it sends every call to `/v1//chat/completions` for a 404 that names nothing."""
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path.endswith("models"):
            return httpx.Response(200, json={"data": OLLAMA_MODELS[:1]})
        return httpx.Response(200, json={
            "choices": [{"finish_reason": "stop", "message": {"content": "ready"}}]})

    b = _backend(handler, base_url="http://endpoint:11434/v1/")
    assert b.liveness_urls() == ("http://endpoint:11434/v1/models",
                                 "http://endpoint:11434/health")
    b.require_available()
    b.chat([{"role": "user", "content": "hi"}])
    assert "//" not in "".join(paths), paths
    assert "/v1/chat/completions" in paths


def test_a_gateway_that_mounts_the_api_under_a_path_keeps_its_path():
    """Cutting at the last `/v1` anywhere in the string leaves `http://gw`, so the liveness check
    goes off and asks an unrelated service whether the model is up."""
    b = _backend(_server(models=OLLAMA_MODELS, health=False), base_url="http://gw/v1/openai")
    assert b.liveness_urls() == ("http://gw/v1/openai/models", "http://gw/v1/openai/health")


# ------------------------------------------------------------------ which model


def test_several_models_are_refused_rather_than_guessed():
    """"The first one" is a guess about vision, and the model list carries no such field on any
    server. On the reporter's Ollama the first id was a text-only coding model."""
    b = _backend(_server(models=OLLAMA_MODELS, health=False))
    with pytest.raises(BackendUnavailable) as e:
        b.require_available()
    msg = str(e.value)
    assert "H3IR_LLM_MODEL" in msg
    for m in OLLAMA_MODELS:
        assert m["id"] in msg, f"the refusal must name what it found: {msg}"
    assert b.model_id() == "", "a refusal must not leave a model half-selected"


def test_one_model_is_taken_because_there_is_no_choice_in_it():
    """A server with one model on it is the common local case, and requiring its full name there
    would be configuration with nothing in it."""
    b = _backend(_server(models=OLLAMA_MODELS[:1], health=False))
    b.require_available()
    assert b.model_id() == "smollm2:135m"


def test_aliases_of_one_model_are_not_a_choice():
    """vLLM's `--served-model-name` publishes one set of weights under several ids, each carrying
    the same `root`. Counting ids rather than models would refuse a machine that has no ambiguity
    on it at all, which is the endpoint this project was built against."""
    b = _backend(_server(models=VLLM_ALIASES, health=True))
    b.require_available()
    assert b.model_id() == VLLM_ALIASES[0]["id"]


def test_two_genuinely_different_models_are_refused_even_when_both_declare_a_root():
    b = _backend(_server(models=[{"id": "a", "root": "weights-a"},
                                 {"id": "b", "root": "weights-b"}], health=False))
    with pytest.raises(BackendUnavailable):
        b.require_available()


def test_an_endpoint_serving_nothing_is_named_rather_than_crashing():
    """A fresh Ollama with no models pulled answers `{"object": "list", "data": null}`. Iterating
    that raised a TypeError, which arrived as "could not be read to discover it" and pointed at the
    network instead of at an empty install."""
    def empty(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"object": "list", "data": None})
        return httpx.Response(404)
    b = _backend(empty)
    with pytest.raises(BackendUnavailable) as e:
        b.require_available()
    assert "named no models" in str(e.value), str(e.value)


# ------------------------------------------------------------------ credentials


def _auth_seen(api_key: str) -> list[str | None]:
    seen: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers.get("authorization"))
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"data": OLLAMA_MODELS[:1]})
        return httpx.Response(200, json={
            "choices": [{"finish_reason": "stop", "message": {"content": "ready"}}]})

    b = _backend(handler, api_key=api_key)
    b.require_available()
    b.chat([{"role": "user", "content": "hi"}])
    return seen


def test_a_configured_key_reaches_every_request():
    """`H3IR_LLM_KEY` was a setting that went nowhere. Invisible against a local server that wants
    no credential, and a 401 against every endpoint that does."""
    seen = _auth_seen("sk-real-key")
    assert seen, "no requests were made"
    assert all(h == "Bearer sk-real-key" for h in seen), seen


def test_the_placeholder_is_not_sent_as_a_credential():
    """`.env.example` ships the literal `not-needed`. Sending that to a server with auth on would
    be rejected as a bad key rather than a missing one, and the user would debug the wrong thing."""
    assert all(h is None for h in _auth_seen("not-needed"))
    assert all(h is None for h in _auth_seen(""))


# ------------------------------------------------------------------ version and error bodies


def test_the_version_is_found_wherever_the_server_puts_it():
    """vLLM answers `/version`, Ollama answers `/api/version`. Provenance that reads `?` on every
    run is provenance nobody can use."""
    def ollama(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/version":
            return httpx.Response(200, json={"version": "0.32.15"})
        return httpx.Response(404)

    def vllm(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/version":
            return httpx.Response(200, json={"version": "0.21.0"})
        return httpx.Response(404)

    assert _backend(ollama).server_version() == "0.32.15"
    assert _backend(vllm).server_version() == "0.21.0"
    assert _backend(_server(models=None, health=False)).server_version() == "?"


def test_a_doubly_wrapped_error_is_reduced_to_its_sentence():
    """The body Ollama actually returns for a picture sent to a text-only model. Printed raw it is
    two layers of escaped JSON, and the one sentence that answers the user's question is buried."""
    def refuse(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text=OLLAMA_NO_VISION_BODY)
    with pytest.raises(EndpointRefused) as e:
        _backend(refuse).chat([{"role": "user", "content": "hi"}])
    assert str(e.value) == (
        "HTTP 400: Multimodal data provided, but model does not support multimodal requests.")
    assert e.value.status == 400


def test_an_error_body_that_is_not_json_survives_untouched():
    """A wrong guess about the shape must never lose the evidence."""
    def refuse(request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, text="<html>502 Bad Gateway</html>")
    with pytest.raises(EndpointRefused) as e:
        _backend(refuse).chat([{"role": "user", "content": "hi"}])
    assert "<html>502 Bad Gateway</html>" in str(e.value)


# ------------------------------------------------------------------ the vision self-test


def _decode_grey_png(data: bytes) -> tuple[int, int, list[bytearray]]:
    """Just enough PNG reader to look at the picture the probe draws."""
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    pos, idat, w, h = 8, b"", 0, 0
    while pos < len(data):
        n = struct.unpack(">I", data[pos:pos + 4])[0]
        tag, body = data[pos + 4:pos + 8], data[pos + 8:pos + 8 + n]
        if tag == b"IHDR":
            w, h, depth, colour = (*struct.unpack(">II", body[:8]), body[8], body[9])
            assert (depth, colour) == (8, 0), "expected 8-bit greyscale"
        elif tag == b"IDAT":
            idat += body
        pos += n + 12
    raw = zlib.decompress(idat)
    rows = []
    for y in range(h):
        start = y * (w + 1)
        assert raw[start] == 0, "expected filter type 0 on every row"
        rows.append(bytearray(raw[start + 1:start + 1 + w]))
    return w, h, rows


def test_the_probe_picture_really_draws_the_digits_it_claims():
    """A picture that renders nothing is the fixture failure this project has already been bitten
    by: the assertion passes, and it is comparing blanks. So the glyph grid is read back out of the
    encoded bytes rather than trusted."""
    scale, pad = 16, 16
    png = digits_png(VISION_PROBE_DIGITS, scale=scale, pad=pad)
    w, h, rows = _decode_grey_png(png)
    assert h == 2 * pad + 7 * scale
    for i, digit in enumerate(VISION_PROBE_DIGITS):
        x0 = pad + i * (5 * scale + scale)
        for gy, line in enumerate(_DIGIT_GLYPHS[digit]):
            for gx, cell in enumerate(line):
                # the centre of the cell, so a one-pixel drawing slip cannot hide behind an edge
                px = rows[pad + gy * scale + scale // 2][x0 + gx * scale + scale // 2]
                assert px == (0 if cell == "1" else 255), (
                    f"digit {digit!r} cell ({gy},{gx}) is {px}, expected {cell}")


def test_a_different_number_draws_a_different_picture():
    assert digits_png("473") != digits_png("372")


def test_the_vision_check_sends_a_real_picture_through_the_production_path():
    """The check has to exercise `user_message` and the mime sniff, or it is proving that a
    shortcut written for the check works."""
    bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={
            "choices": [{"finish_reason": "stop", "message": {"content": VISION_PROBE_DIGITS}}]})

    ok, said = vision_check(_backend(handler, model="m"))
    assert ok is True and said == VISION_PROBE_DIGITS
    parts = bodies[0]["messages"][0]["content"]
    urls = [p["image_url"]["url"] for p in parts if p.get("type") == "image_url"]
    assert len(urls) == 1, f"no picture was attached: {parts}"
    assert urls[0].startswith("data:image/png;base64,"), urls[0][:40]
    import base64
    assert base64.b64decode(urls[0].split(",", 1)[1])[:8] == b"\x89PNG\r\n\x1a\n"


def test_a_model_that_answers_with_prose_instead_of_the_digits_does_not_pass():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {
            "content": "I am a language model and cannot view images."}}]})
    ok, said = vision_check(_backend(handler, model="m"))
    assert ok is False
    assert "cannot view images" in said, "the reply must be reported, not swallowed"


def test_the_wrong_digits_do_not_pass():
    """Three digits, so a model that guesses cannot land on them."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop",
                                                      "message": {"content": "128"}}]})
    assert vision_check(_backend(handler, model="m"))[0] is False


# ------------------------------------------------------------------ what doctor reports


def _doctor(handler, **llm) -> dict:
    cfg = Config(llm=LLMConfig(**{"base_url": BASE, "model": "", **llm}))
    import h3ir.backend as B
    real = B.Backend

    class Wired(real):                       # the probe builds its own Backend
        def __init__(self, c=None, client=None):
            super().__init__(c, httpx.Client(transport=httpx.MockTransport(handler)))

    B.Backend = Wired
    try:
        return probe(cfg)
    finally:
        B.Backend = real


def _full_server(*, models, vision: bool, chat: str = "ready"):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"object": "list", "data": models})
        if request.url.path == "/v1/chat/completions":
            body = json.loads(request.content)
            content = body["messages"][0]["content"]
            has_image = isinstance(content, list) and any(
                p.get("type") == "image_url" for p in content)
            if has_image and not vision:
                return httpx.Response(400, text=OLLAMA_NO_VISION_BODY)
            return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {
                "content": VISION_PROBE_DIGITS if has_image else chat}}]})
        return httpx.Response(404)
    return handler


def test_doctor_reports_a_text_only_model_as_the_reason_nothing_works():
    """The reporter's actual situation: the endpoint was up, the model answered, and it could not
    read a single reference. Everything `doctor` printed was green."""
    out = _doctor(_full_server(models=OLLAMA_MODELS, vision=False), model="smollm2:135m")
    assert out["health"] is True
    assert out["chat_ok"] is True, "the text probe passes on a text-only model, which is the trap"
    assert out["vision_ok"] is False
    assert "multimodal" in out["vision_reply"].lower()
    assert "H3IR_LLM_MODEL" in out["vision_note"]


def test_doctor_reports_a_model_that_can_see():
    out = _doctor(_full_server(models=VLLM_ALIASES, vision=True), model="qwen3.8u")
    assert out["vision_ok"] is True
    assert out["max_model_len"] == 262144


def test_doctor_says_a_missing_context_length_is_missing_rather_than_printing_none():
    """HANDOFF tells the reader that a small `max_model_len` means references will not fit. Ollama
    does not report one at all, and `None` reads as "very small" rather than "not published"."""
    out = _doctor(_full_server(models=OLLAMA_MODELS, vision=True), model="smollm2:135m")
    assert isinstance(out["max_model_len"], str) and "not report" in out["max_model_len"]


def test_doctor_names_a_model_id_the_endpoint_does_not_list():
    """A typo in `H3IR_LLM_MODEL` used to arrive as a 404 about a malformed request."""
    out = _doctor(_full_server(models=OLLAMA_MODELS, vision=True), model="smollm:135m")
    assert "does not list it" in out["model_warning"]


def test_doctor_explains_the_refusal_instead_of_leaving_the_field_blank():
    out = _doctor(_full_server(models=OLLAMA_MODELS, vision=True))
    assert out["model_ids"] == [m["id"] for m in OLLAMA_MODELS]
    assert "H3IR_LLM_MODEL" in out["model_from"]
    assert "chat_ok" not in out, "nothing should be claimed about a model that was never chosen"


def test_doctor_says_which_path_answered():
    out = _doctor(_full_server(models=OLLAMA_MODELS, vision=True), model="smollm2:135m")
    assert out["health_via"].endswith("/v1/models")
    assert "/v1/models -> HTTP 200" in out["health_tried"]


def test_a_transport_failure_during_the_vision_check_is_not_read_as_a_verdict():
    """A timeout says nothing about whether the model can see, so no verdict is recorded."""
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"data": VLLM_ALIASES})
        body = json.loads(request.content)
        if isinstance(body["messages"][0]["content"], list):
            raise httpx.ConnectTimeout("timed out")
        return httpx.Response(200, json={
            "choices": [{"finish_reason": "stop", "message": {"content": "ready"}}]})

    out = _doctor(handler, model="qwen3.8u")
    assert "vision_ok" not in out, "a timeout must not be reported as a model that cannot see"
    assert "vision_error" in out


def _refuses_the_picture_with(status: int, body: str):
    """A server that lists a model, answers the word probe, and refuses the PICTURE with `status`.

    Everything before the picture succeeds on purpose. That is the shape of the bug: a reader gets
    green all the way down and then one wrong verdict at the bottom.
    """
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"data": VLLM_ALIASES})
        body_in = json.loads(request.content)
        content = body_in["messages"][0]["content"]
        if isinstance(content, list) and any(p.get("type") == "image_url" for p in content):
            return httpx.Response(status, text=body)
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop",
                                                      "message": {"content": "ready"}}]})
    return handler


@pytest.mark.parametrize("status", [400, 415, 422])
def test_a_server_that_rejects_the_picture_is_a_verdict_about_the_model(status):
    """The one refusal that IS an answer. The server read the request and would not take a picture,
    which is exactly what a text-only model on a strict server does."""
    out = _doctor(_refuses_the_picture_with(status, OLLAMA_NO_VISION_BODY), model="qwen3.8u")
    assert out["vision_ok"] is False
    assert "H3IR_LLM_MODEL" in out["vision_note"]


@pytest.mark.parametrize("status,says", [
    (404, "no model called"),
    (401, "credential"),
    (403, "credential"),
    (500, "about the server"),
    (502, "about the server"),
])
def test_a_refusal_that_judged_nothing_is_never_reported_as_a_model_that_cannot_see(status, says):
    """MEASURED against a live vLLM: a model id the endpoint does not serve answers
    `HTTP 404: The model does not exist`, and `doctor` reported it as a model with no vision tower.
    Somebody reading that goes hunting for a vision model to replace one that was never there.

    A missing model, a rejected credential and a broken server each have their own fix, so each gets
    its own sentence, and none of them gets a verdict.
    """
    body = '{"error": {"message": "The model `qwen3.8u` does not exist."}}'
    out = _doctor(_refuses_the_picture_with(status, body), model="qwen3.8u")
    assert "vision_ok" not in out, (
        f"HTTP {status} judged nothing about the picture and was reported as a verdict anyway")
    assert "vision_error" in out, "the refusal itself is not reported at all"
    assert says in out["vision_note"], out["vision_note"]
    assert "vision tower" not in out["vision_note"], (
        "the reader is sent looking for a model that can see, over a request nobody judged")


def test_which_statuses_judge_a_picture_is_stated_once():
    """The rule lives in one predicate rather than in the branch that happens to need it, because
    the ComfyUI node pack makes the same decision and the two have to agree."""
    from h3ir.backend import judges_the_picture

    assert [s for s in (400, 415, 422) if not judges_the_picture(s)] == []
    assert [s for s in (401, 403, 404, 408, 429, 500, 502, 503) if judges_the_picture(s)] == []


def test_the_vision_check_failure_is_a_backend_error_callers_already_catch():
    """Nothing outside `doctor` calls it, but if it ever grows a caller, the exception has to be
    one the compiler's existing `except BackendError` already handles."""
    assert issubclass(EndpointRefused, BackendError)


def test_doctor_still_asks_about_pictures_when_the_word_probe_fails():
    """Measured on moondream through Ollama: it answers "reply with the single word: ready" with
    nothing at all, and reads the picture perfectly. Stopping at the first failure would report a
    dead endpoint for a model whose only real problem is that it does not take instructions."""
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"data": OLLAMA_MODELS[:1]})
        body = json.loads(request.content)
        if isinstance(body["messages"][0]["content"], list):
            return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {
                "content": f"The image shows the number {VISION_PROBE_DIGITS} in pixel art."}}]})
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop",
                                                      "message": {"content": ""}}]})

    out = _doctor(handler, model="smollm2:135m")
    assert "chat_error" in out
    assert out["vision_ok"] is True, "the picture question was never asked"


def test_a_dead_socket_is_not_asked_twice():
    """Two liveness paths must not double the wait for the commonest failure of all, a wrong port.
    A refused connection is about the host, not the path, so the second one would spend another
    timeout learning the same thing."""
    tried: list[str] = []

    def refused(request: httpx.Request) -> httpx.Response:
        tried.append(request.url.path)
        raise httpx.ConnectError("connection refused")

    hp = _backend(refused).health_probe()
    assert hp.ok is False
    assert tried == ["/v1/models"], f"the dead socket was asked twice: {tried}"
    assert "ConnectError" in hp.attempts[0][1]


def test_doctor_says_whether_a_credential_went_out_and_never_what_it_was():
    """A 401 with `none sent` beside it is a different bug from a 401 with a key sent, and the
    difference is the first thing a reader needs. The key itself must never reach a terminal."""
    server = _full_server(models=VLLM_ALIASES, vision=True)
    with_key = _doctor(server, model="qwen3.8u", api_key="sk-secret-value")
    assert with_key["credential"] == "Authorization: Bearer sent"
    assert "sk-secret-value" not in json.dumps(with_key), with_key
    assert _doctor(server, model="qwen3.8u")["credential"] == "none sent"
