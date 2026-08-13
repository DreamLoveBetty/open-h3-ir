"""A retry must ask a different question, or it is not a retry.

`json_call` re-sends the request when the reply is the wrong shape. At `temperature=0.0` with a
fixed seed the decode is deterministic, so identical messages return an identical reply and the
loop burns three attempts on the same wrong answer.

This is measured, not hypothetical. A vision call on a reference image with an appended caller note
("The caller says this reference is: the woman") tipped a greedy decode into returning the JSON
*schema* rather than an instance of it — valid JSON, so it parsed, with keys `title`, `type`,
`properties`, `required`, `additionalProperties`. All three attempts produced byte-identical
524-token replies, 8 cold runs out of 8, deterministic. Dropping the note fixed it; changing the
seed did not, because at temperature 0 the seed changes nothing; raising the temperature did.

So attempt 0 keeps whatever the caller asked for, which keeps the common path reproducible, and
only the retries move.
"""
from __future__ import annotations

import httpx
import pytest

from h3ir.backend import Backend, BackendError
from h3ir.backend import _is_the_schema_itself

SCHEMA = {
    "title": "AssetCard",
    "type": "object",
    "additionalProperties": False,
    "required": ["summary", "subjects"],
    "properties": {"summary": {"type": "string"}, "subjects": {"type": "array"}},
}


def _recording_backend(replies: list[str]) -> tuple[Backend, list[float | None]]:
    """A backend that returns `replies` in order and records the temperature of every call."""
    seen: list[float | None] = []
    box = {"i": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        import json as _json
        body = _json.loads(request.content)
        seen.append(body.get("temperature"))
        i = min(box["i"], len(replies) - 1)
        box["i"] += 1
        return httpx.Response(200, json={
            "choices": [{"finish_reason": "stop", "message": {"content": replies[i]}}]})

    return Backend(client=httpx.Client(transport=httpx.MockTransport(handler))), seen


def test_the_first_attempt_uses_exactly_what_the_caller_asked_for():
    """Reproducibility of the common path is the reason the escalation starts at attempt 1."""
    good = '{"summary": "a woman on a walkway", "subjects": []}'
    b, seen = _recording_backend([good])
    b.json_call([{"role": "user", "content": "describe it"}], SCHEMA,
                required=("summary", "subjects"), temperature=0.0, seed=7)
    assert seen == [0.0], f"the first call must not be perturbed: {seen}"


def test_a_retry_raises_the_temperature_so_the_decode_can_differ():
    schema_echo = (
        '{"title": "AssetCard", "type": "object", "additionalProperties": false, '
        '"required": ["summary", "subjects"], "properties": {"summary": {"type": "string"}}}')
    good = '{"summary": "a woman on a walkway", "subjects": []}'
    b, seen = _recording_backend([schema_echo, good])
    out = b.json_call([{"role": "user", "content": "describe it"}], SCHEMA,
                      required=("summary", "subjects"), temperature=0.0, seed=7)
    assert out["summary"] == "a woman on a walkway"
    assert len(seen) == 2, f"expected one retry, saw {len(seen)} call(s)"
    assert seen[0] == 0.0
    assert seen[1] > seen[0], (
        f"the retry re-asked at the same temperature ({seen}), which at temperature 0 with a "
        "fixed seed is the same question and returns the same wrong answer")


def test_every_attempt_differs_when_the_model_keeps_echoing():
    """The failure that motivated this: three attempts, three identical replies. Whatever else
    happens, no two attempts may be sent at the same temperature."""
    schema_echo = '{"title": "AssetCard", "type": "object", "properties": {}}'
    b, seen = _recording_backend([schema_echo])
    with pytest.raises(BackendError):
        b.json_call([{"role": "user", "content": "describe it"}], SCHEMA,
                    required=("summary", "subjects"), temperature=0.0, seed=7, retries=2)
    assert len(seen) == 3, f"expected 3 attempts, saw {len(seen)}"
    assert len(set(seen)) == 3, f"attempts repeated the same question: {seen}"


def test_the_caller_temperature_is_respected_as_the_floor():
    """A caller who asked for 0.7 must not be dropped to 0.4 on retry."""
    schema_echo = '{"title": "AssetCard", "type": "object", "properties": {}}'
    good = '{"summary": "ok", "subjects": []}'
    b, seen = _recording_backend([schema_echo, good])
    b.json_call([{"role": "user", "content": "x"}], SCHEMA,
                required=("summary", "subjects"), temperature=0.7)
    assert seen[0] == 0.7
    assert seen[1] > 0.7, f"retry did not exceed the caller's temperature: {seen}"


def test_a_schema_echo_is_named_rather_than_reported_as_a_missing_key():
    """"required key(s) absent" sent a reader looking for a truncated reply. The reply was
    complete; it was the wrong document."""
    assert _is_the_schema_itself(
        {"title": "AssetCard", "type": "object", "properties": {"summary": {}}}) is True
    # an ordinary instance that happens to be an object is not the schema
    assert _is_the_schema_itself({"summary": "a woman", "subjects": []}) is False
    # neither is a partial instance missing keys
    assert _is_the_schema_itself({"summary": "a woman"}) is False


def test_the_error_does_not_claim_a_schema_was_enforced_when_it_was_not():
    """With guided decoding off, nothing enforces the schema — it is asked for in the prompt. The
    old message said "despite strict schema", which is a false statement about the request that
    was actually made, and it costs the reader a trip through the grammar code path."""
    b, _ = _recording_backend(['{"summary": "no subjects key here"}'])
    assert b.cfg.guided_decoding is False, "this test is about the no-grammar default"
    with pytest.raises(BackendError) as e:
        b.json_call([{"role": "user", "content": "x"}], SCHEMA,
                    required=("summary", "subjects"), retries=0)
    assert "despite strict schema" not in str(e.value)
    assert "not enforced by a grammar" in str(e.value)
