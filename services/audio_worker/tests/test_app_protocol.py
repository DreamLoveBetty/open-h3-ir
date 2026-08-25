"""The protocol test that matters: the compiler's REAL client against this app.

Not a re-assertion of shapes on the worker side -- the wire is where the two halves meet, and
the failure this guards is "each side's tests pass, the pair disagrees" (the swap-roles bug's
lesson, applied to the new boundary). So the app runs through httpx's ASGI transport and the
answer is parsed by `h3ir.audio.client.AudioWorkerClient` itself. If the worker ever emits a
key the compiler does not know, or stops emitting one it needs, this file goes red.
"""
from __future__ import annotations

import httpx
import pytest

from audio_worker.app import create_app
from audio_worker.dsp_backend import DSPResult
from audio_worker.settings import WorkerSettings

from sync_asgi import SyncASGITransport
from audio_worker.sensevoice_backend import SpeechResult

from h3ir.audio.client import AudioWorkerBadResponse, AudioWorkerClient
from h3ir.config import AudioConfig


class FakeDSP:
    name = "dsp"
    calls: list[str]

    def __init__(self):
        self.calls = []

    def available(self):
        return True, ""

    def probe(self, path):
        return {"duration_s": 3.0, "sample_rate": 48000, "channels": 2}

    def analyse(self, path):
        self.calls.append(str(path))
        return DSPResult(
            signal={"duration_s": 3.0, "sample_rate": 48000, "channels": 2,
                    "avg_loudness_db": -18.7, "peak_time_s": 1.2,
                    "dynamic_range_db": 11.3, "silence_regions": []},
            rhythm={"tempo_bpm": 128.0, "confidence": 0.9, "beat_times_s": [0.47, 0.94],
                    "downbeat_times_s": [], "strong_onsets_s": [0.47]},
        )


class FakeSpeech:
    name = "speech"
    model_id = "iic/SenseVoiceSmall"

    def available(self):
        return True, ""

    def analyse(self, path, *, diarization=True):
        return SpeechResult(
            speech=[{"start_s": 0.5, "end_s": 2.4, "text": "We close at six.",
                     "language": "en", "speaker_id": "SPK_0", "emotion": "neutral",
                     "confidence": None}],
            voice={"speaker_count": 1, "emotions": ["neutral"]} if diarization else {},
        )


class FakeCLAP:
    name = "clap"

    def available(self):
        return False, "CLAP lands with Phase D"

    def classify_windows(self, path, *, onsets=None):
        raise AssertionError("unavailable backends must not be called")


def _client(app, **cfg_kw) -> AudioWorkerClient:
    cfg = AudioConfig(enabled=True, base_url="http://worker.test", **cfg_kw)
    return AudioWorkerClient(cfg, transport=SyncASGITransport(app))


@pytest.fixture
def wav(tmp_path):
    p = tmp_path / "clip.wav"
    p.write_bytes(b"RIFF" + b"\x00" * 128)
    return p


def test_the_compiler_client_parses_this_workers_answer(wav):
    app = create_app(backends={"dsp": FakeDSP(), "speech": FakeSpeech(), "clap": FakeCLAP()},
                     settings=WorkerSettings())
    obs, info = _client(app).analyse(wav, diarization=True, clap=False, dsp=True)

    assert obs.signal.duration_s == 3.0
    assert obs.signal.channels == 2
    assert obs.speech[0].text == "We close at six."
    assert obs.speech[0].speaker_id == "SPK_0"
    assert obs.voice.speaker_count == 1
    assert obs.rhythm.tempo_bpm == 128.0
    assert info.version == "audio-worker-1"
    assert "speech" in info.models


def test_health_identifies_the_worker_and_its_stages():
    app = create_app(backends={"dsp": FakeDSP(), "speech": FakeSpeech(), "clap": FakeCLAP()},
                     settings=WorkerSettings())
    info = _client(app).health()
    assert info.version == "audio-worker-1"
    assert info.models.get("speech") == "iic/SenseVoiceSmall"
    assert "clap" not in info.models, "an unavailable stage is not part of the identity"


def test_an_unavailable_requested_stage_marks_the_response_incomplete(wav):
    """CLAP asked for and absent must surface as `incomplete`, not as silence. The compiler's
    fallback router reads exactly this flag (spec §10 rule 6)."""
    app = create_app(backends={"dsp": FakeDSP(), "speech": FakeSpeech(), "clap": FakeCLAP()},
                     settings=WorkerSettings())
    obs, _ = _client(app).analyse(wav, clap=True)
    assert obs.partial is True


def test_a_fully_disabled_request_is_not_marked_incomplete(wav):
    app = create_app(backends={"dsp": FakeDSP(), "speech": FakeSpeech(), "clap": FakeCLAP()},
                     settings=WorkerSettings())
    obs, _ = _client(app).analyse(wav, diarization=False, clap=False, dsp=True)
    assert obs.partial is False
    assert obs.voice.speaker_count == 0, "diarization off means speaker count was not measured"


def test_every_stage_failing_is_a_500_not_an_empty_success(wav):
    """Spec §32. An empty 200 would look like 'the audio contains nothing'; the truth here is
    'nothing ran', and the compiler must hear the difference as an error."""

    class DeadDSP(FakeDSP):
        def analyse(self, path):
            raise RuntimeError("decoder exploded")

    class DeadSpeech(FakeSpeech):
        def analyse(self, path, *, diarization=True):
            raise RuntimeError("model exploded")

    app = create_app(backends={"dsp": DeadDSP(), "speech": DeadSpeech(), "clap": FakeCLAP()},
                     settings=WorkerSettings())
    with pytest.raises(AudioWorkerBadResponse, match="HTTP 500"):
        _client(app).analyse(wav, clap=False)


def test_an_undecodable_file_is_a_422_with_a_useful_message(wav):
    from audio_worker.dsp_backend import AnalysisError

    class PickyDSP(FakeDSP):
        def analyse(self, path):
            raise AnalysisError("ffmpeg decoded zero samples -- is there an audio stream?")

    app = create_app(backends={"dsp": PickyDSP(), "speech": FakeSpeech(), "clap": FakeCLAP()},
                     settings=WorkerSettings())
    with pytest.raises(AudioWorkerBadResponse, match="422"):
        _client(app).analyse(wav, clap=False)


def test_oversize_uploads_are_refused_on_bytes_received(wav):
    big = tmp = wav.with_name("big.wav")
    big.write_bytes(b"\x00" * 2048)
    app = create_app(backends={"dsp": FakeDSP(), "speech": FakeSpeech(), "clap": FakeCLAP()},
                     settings=WorkerSettings(max_upload_bytes=1024))
    with pytest.raises(AudioWorkerBadResponse, match="413"):
        _client(app).analyse(big, clap=False)


def test_a_missing_file_field_is_a_400():
    app = create_app(backends={"dsp": FakeDSP(), "speech": FakeSpeech(), "clap": FakeCLAP()},
                     settings=WorkerSettings())
    transport = SyncASGITransport(app)
    with httpx.Client(transport=transport, base_url="http://worker.test") as http:
        resp = http.post("/v1/audio/analyze", data={"enable_dsp": "true"})
    assert resp.status_code == 400


def test_too_long_audio_is_refused_before_the_heavy_stages(wav):
    class LongDSP(FakeDSP):
        def analyse(self, path):
            r = super().analyse(path)
            r.signal["duration_s"] = 999.0
            return r

    speech_called = []

    class CountingSpeech(FakeSpeech):
        def analyse(self, path, *, diarization=True):
            speech_called.append(True)
            return super().analyse(path, diarization=diarization)

    app = create_app(backends={"dsp": LongDSP(), "speech": CountingSpeech(),
                               "clap": FakeCLAP()},
                     settings=WorkerSettings(max_audio_seconds=600))
    with pytest.raises(AudioWorkerBadResponse, match="422"):
        _client(app).analyse(wav, clap=False)
    assert not speech_called, "the limit must bite before the expensive stage runs"


def test_the_wire_keys_stay_within_the_contract(wav):
    """Belt and braces under the round trip above: assert the raw keys directly, so a drift
    report names the key rather than a parse error."""
    from audio_worker.models import WIRE_KEYS

    app = create_app(backends={"dsp": FakeDSP(), "speech": FakeSpeech(), "clap": FakeCLAP()},
                     settings=WorkerSettings())
    transport = SyncASGITransport(app)
    with httpx.Client(transport=transport, base_url="http://worker.test") as http:
        with open(wav, "rb") as fh:
            resp = http.post("/v1/audio/analyze",
                             data={"enable_clap": "false"},
                             files={"file": ("clip.wav", fh, "application/octet-stream")})
    assert resp.status_code == 200
    assert set(resp.json()) <= set(WIRE_KEYS)
