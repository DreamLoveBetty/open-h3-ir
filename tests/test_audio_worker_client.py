"""The worker client against the real HTTP stack (httpx MockTransport, no socket).

The duck-typed FakeWorker tests the observer; this file tests the WIRE: that the request is
the multipart POST the worker's API declares, that the placeholder key is never sent as a
credential, and that every way the HTTP layer can fail lands in the right error family,
because the degraded path keys off the distinction between "nobody answered" and "the answer
was bad".
"""
from __future__ import annotations

import json

import httpx
import pytest

from h3ir.audio.client import (AudioWorkerBadResponse, AudioWorkerClient,
                               AudioWorkerUnavailable, WorkerInfo)
from h3ir.config import AudioConfig


def _cfg(**kw) -> AudioConfig:
    return AudioConfig(enabled=True, base_url="http://worker.test", **kw)


def _body(**over):
    payload = {
        "version": "audio-worker-1",
        "models": {"sensevoice": "SenseVoiceSmall"},
        "duration_s": 3.0,
        "signal": {"duration_s": 3.0, "sample_rate": 48000, "channels": 1},
        "speech": [{"start_s": 0.5, "end_s": 2.4, "text": "We close at six.",
                    "language": "en", "speaker_id": "SPK_0", "confidence": 0.93}],
        "events": [],
        "rhythm": {"tempo_bpm": 128.0, "confidence": 0.94, "beat_times_s": [0.47]},
    }
    payload.update(over)
    return payload


def _client(handler, **cfg_kw) -> AudioWorkerClient:
    return AudioWorkerClient(_cfg(**cfg_kw), transport=httpx.MockTransport(handler))


def test_analyse_posts_the_file_as_multipart_with_the_analyser_switches(tmp_path):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["content_type"] = request.headers["content-type"]
        seen["body"] = request.content
        return httpx.Response(200, json=_body())

    f = tmp_path / "clip.wav"
    f.write_bytes(b"RIFF fake wav bytes")
    obs, info = _client(handler).analyse(f, diarization=True, clap=False, dsp=True)

    assert seen["method"] == "POST" and seen["path"] == "/v1/audio/analyze"
    assert seen["content_type"].startswith("multipart/form-data")
    assert b"RIFF fake wav bytes" in seen["body"]
    assert b'name="enable_diarization"' in seen["body"] and b"true" in seen["body"]
    assert b'name="enable_clap"' in seen["body"]
    assert obs.signal.sample_rate == 48000
    assert obs.speech[0].text == "We close at six."
    assert obs.rhythm.tempo_bpm == 128.0
    assert info.version == "audio-worker-1"
    assert obs.model_ids == {"sensevoice": "SenseVoiceSmall"}


def test_the_placeholder_key_sends_no_credential(tmp_path):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json=_body())

    f = tmp_path / "a.wav"
    f.write_bytes(b"x")
    _client(handler).analyse(f)
    assert seen["auth"] is None, "the placeholder means 'no header', never a credential"


def test_a_real_key_is_sent_as_bearer(tmp_path):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json=_body())

    f = tmp_path / "a.wav"
    f.write_bytes(b"x")
    _client(handler, api_key="real-key").analyse(f)
    assert seen["auth"] == "Bearer real-key"


def test_an_http_error_is_a_bad_response_not_an_unavailable(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="CUDA out of memory")

    f = tmp_path / "a.wav"
    f.write_bytes(b"x")
    with pytest.raises(AudioWorkerBadResponse, match="HTTP 500"):
        _client(handler).analyse(f)


def test_a_transport_failure_is_unavailable(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("[Errno 61] Connection refused")

    f = tmp_path / "a.wav"
    f.write_bytes(b"x")
    with pytest.raises(AudioWorkerUnavailable):
        _client(handler).analyse(f)


def test_a_timeout_is_unavailable(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out")

    f = tmp_path / "a.wav"
    f.write_bytes(b"x")
    with pytest.raises(AudioWorkerUnavailable):
        _client(handler).analyse(f)


def test_malformed_json_is_a_bad_response(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="{ not json")

    f = tmp_path / "a.wav"
    f.write_bytes(b"x")
    with pytest.raises(AudioWorkerBadResponse, match="not JSON"):
        _client(handler).analyse(f)


def test_a_body_that_is_not_an_observation_is_a_bad_response(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"version": "audio-worker-1",
                                         "speech": [{"start_s": "not a number"}]})

    f = tmp_path / "a.wav"
    f.write_bytes(b"x")
    with pytest.raises(AudioWorkerBadResponse):
        _client(handler).analyse(f)


def test_an_incomplete_response_is_marked_not_hidden(tmp_path):
    """The worker saying 'I half-failed' must survive to the router. Laundering it into a
    complete-looking observation is exactly the silent degradation rule 4 forbids."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_body(incomplete=True, events=[]))

    f = tmp_path / "a.wav"
    f.write_bytes(b"x")
    obs, _ = _client(handler).analyse(f)
    assert obs.partial is True


def test_health_returns_the_worker_identity():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET" and request.url.path == "/health"
        return httpx.Response(200, json={"version": "audio-worker-1",
                                         "models": {"sensevoice": "SenseVoiceSmall"}})

    info = _client(handler).health()
    assert info == WorkerInfo(version="audio-worker-1",
                              models={"sensevoice": "SenseVoiceSmall"})


def test_health_failure_modes_match_analyse():
    with pytest.raises(AudioWorkerUnavailable):
        _client(lambda r: (_ for _ in ()).throw(httpx.ConnectError("refused"))).health()
    with pytest.raises(AudioWorkerBadResponse):
        _client(lambda r: httpx.Response(404, text="no such route")).health()


def test_an_unreadable_file_is_not_reported_as_a_worker_failure():
    """The distinction the error families exist for: a missing file is the caller's problem,
    and must not masquerade as the worker being down."""
    from h3ir.audio.client import AudioWorkerError

    with pytest.raises(AudioWorkerError, match="cannot read audio file") as e:
        _client(lambda r: httpx.Response(200, json=_body())).analyse("/no/such/file.wav")
    assert not isinstance(e.value, AudioWorkerUnavailable)
