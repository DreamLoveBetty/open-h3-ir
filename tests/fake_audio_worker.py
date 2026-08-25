"""Shared fakes for the audio tests.

`FakeWorker` stands in for AudioWorkerClient behind the same duck-typed seam
(`health()` / `analyse()`) that observe_audio consumes, so the observer, the cache and the
degraded path are all tested without a socket. The client itself is tested against httpx's
MockTransport in test_audio_worker_client.py -- the wire shape and the object shape are
different tests and both exist.
"""
from __future__ import annotations

from h3ir.audio.client import WorkerInfo
from h3ir.audio.models import (AudioObservation, AudioRhythm, AudioSignalFacts, TimedSpeech)


def sample_observation(sha256: str = "a" * 64) -> AudioObservation:
    return AudioObservation(
        sha256=sha256,
        signal=AudioSignalFacts(duration_s=3.0, sample_rate=48000, channels=1),
        speech=[TimedSpeech(start_s=0.5, end_s=2.4, text="We close at six, not half past.",
                            language="en", speaker_id="SPK_0", confidence=0.93)],
        rhythm=AudioRhythm(tempo_bpm=128.0, confidence=0.94,
                           beat_times_s=[0.47, 0.94, 1.41]),
    )


class FakeWorker:
    """In-memory AudioWorkerClient. Counts its calls so cache tests can prove what ran."""

    def __init__(self, observation: AudioObservation | None = None, *,
                 version: str = "audio-worker-1",
                 models: dict[str, str] | None = None):
        self.info = WorkerInfo(version=version, models=models or {
            "sensevoice": "SenseVoiceSmall", "cam++": "iic/speech_campplus_sv_zh_en_16k"})
        self._observation = observation or sample_observation()
        self.health_calls = 0
        self.analyse_calls = 0

    def health(self) -> WorkerInfo:
        self.health_calls += 1
        return self.info

    def analyse(self, path, *, diarization: bool = True, clap: bool = True,
                dsp: bool = True) -> tuple[AudioObservation, WorkerInfo]:
        self.analyse_calls += 1
        # A fresh object per call: the observer stamps its own sha256 onto what it gets back,
        # and handing out the same instance twice would alias one request's bytes into
        # another's identity.
        return AudioObservation.from_dict(self._observation.to_dict()), self.info


class UnreachableWorker(FakeWorker):
    """health() and analyse() both fail the way a dead worker does."""

    def __init__(self):
        super().__init__()

    def health(self) -> WorkerInfo:
        from h3ir.audio.client import AudioWorkerUnavailable
        raise AudioWorkerUnavailable("audio worker at http://worker.test did not answer: "
                                     "[Errno 61] Connection refused")

    def analyse(self, path, **kw):
        raise AssertionError("analyse() must not be reached when health() failed")
