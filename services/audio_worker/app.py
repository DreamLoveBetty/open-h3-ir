"""The Audio Worker HTTP service.

Owns every heavy dependency so the compiler doesn't have to: SenseVoice + FSMN-VAD + CAM++ +
DSP here, torch never in `open-h3-ir`. Two endpoints and no other surface:

    GET  /health              -> who this worker is (version + model ids), for cache keys
    POST /v1/audio/analyze    -> multipart audio in, AudioObservation-shaped JSON out

Failure discipline (spec §32): a stage that fails never produces a fabricated empty success.
If every stage fails, the request fails (500). If some stages succeed, the response carries
what they produced and `incomplete: true` -- partial facts are facts, laundered facts are not.
Temporary decode files are always removed, size limits are enforced on bytes actually
received, and ffmpeg is invoked as an argv list, never a shell string.

Run:  python -m audio_worker.app            (from the services/ directory)
      uvicorn audio_worker.app:app --port 50000
"""
from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .clap_backend import CLAPBackend
from .dsp_backend import AnalysisError, BackendUnavailable, DSPBackend
from .models import build_response
from .sensevoice_backend import SenseVoiceBackend
from .settings import WorkerSettings, get_settings

log = logging.getLogger("audio_worker.app")


def default_backends(settings: WorkerSettings) -> dict[str, Any]:
    return {"dsp": DSPBackend(settings), "speech": SenseVoiceBackend(settings),
            "clap": CLAPBackend(settings)}


def create_app(backends: dict[str, Any] | None = None,
               settings: WorkerSettings | None = None) -> FastAPI:
    """The backend dict is a parameter rather than a global so tests can inject fakes and a
    deployment can swap one stage without forking the app."""
    settings = settings or get_settings()
    backends = backends if backends is not None else default_backends(settings)
    app = FastAPI(title="h3ir audio worker", version=settings.version)
    app.state.backends = backends
    app.state.settings = settings

    @app.get("/health")
    def health() -> dict[str, Any]:
        # A stage that cannot run is reported, not hidden: the compiler keys its observation
        # cache on this answer, and a cached observation must not survive a model swap.
        caps = {}
        for name, be in backends.items():
            ok, why = be.available()
            caps[name] = "ok" if ok else f"unavailable: {why}"
        return {"version": settings.version, "models": _model_ids(backends),
                "capabilities": caps}

    @app.post("/v1/audio/analyze")
    async def analyze(request: Request) -> JSONResponse:
        form = await request.form()
        upload = form.get("file")
        if upload is None or not getattr(upload, "filename", None):
            return JSONResponse({"error": "multipart field 'file' is required"}, status_code=400)
        enable = lambda name, default=True: (  # noqa: E731 - one-liner, used three times
            str(form.get(name, "true" if default else "false")).lower() in ("1", "true", "yes"))

        data = await upload.read()
        if len(data) > settings.max_upload_bytes:
            # Enforced on bytes actually received -- the header is a claim, this is a fact.
            return JSONResponse(
                {"error": f"upload is {len(data)} bytes; the limit is "
                          f"{settings.max_upload_bytes}"}, status_code=413)

        tmp = tempfile.NamedTemporaryFile(
            prefix="h3ir_audio_", suffix=Path(upload.filename).suffix or ".bin", delete=False)
        try:
            tmp.write(data)
            tmp.close()
            return _analyze_path(Path(tmp.name), settings, backends,
                                 dsp_on=enable("enable_dsp"),
                                 diarization=enable("enable_diarization"),
                                 clap_on=enable("enable_clap"))
        finally:
            Path(tmp.name).unlink(missing_ok=True)

    return app


def _analyze_path(path: Path, settings: WorkerSettings, backends: dict[str, Any], *,
                  dsp_on: bool, diarization: bool, clap_on: bool) -> JSONResponse:
    degraded: list[str] = []
    signal: dict[str, Any] = {}
    rhythm: dict[str, Any] = {}
    speech: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    voice: dict[str, Any] = {}
    music: dict[str, Any] = {"present": False}
    duration_s = 0.0
    produced_something = False

    # -- DSP first: it owns duration, and the speech pipeline decodes from its output anyway.
    if dsp_on:
        try:
            dsp_result = backends["dsp"].analyse(path)
            signal = dsp_result.signal
            rhythm = dsp_result.rhythm
            degraded.extend(dsp_result.degraded)
            duration_s = signal.get("duration_s") or 0.0
            produced_something = True
        except BackendUnavailable as e:
            degraded.append(f"dsp unavailable: {e}")
        except AnalysisError as e:
            return JSONResponse({"error": str(e)}, status_code=422)
        except Exception as e:  # noqa: BLE001 - a crashed stage degrades, it does not 500 a file the other stages could still read
            log.exception("dsp stage failed")
            degraded.append(f"dsp failed: {e}")
    else:
        degraded.append("dsp disabled by the caller")
        try:
            duration_s = backends["dsp"].probe(path)["duration_s"]
        except Exception:  # noqa: BLE001
            duration_s = 0.0

    if duration_s > settings.max_audio_seconds:
        return JSONResponse(
            {"error": f"audio is {duration_s:.1f}s; the limit is "
                      f"{settings.max_audio_seconds:.0f}s"}, status_code=422)

    # -- Speech: VAD -> SenseVoice -> CAM++, one backend call.
    speech_backend = backends["speech"]
    if speech_backend is not None:
        try:
            result = speech_backend.analyse(path, diarization=diarization)
            speech = result.speech
            events.extend(result.events)
            voice = result.voice
            degraded.extend(result.degraded)
            if result.music_present:
                music["present"] = True
            # A speech stage that RAN counts even when it heard nothing: silence is an
            # authoritative answer, not a missing one. What must never count is a stage that
            # failed -- those land in `degraded` above.
            produced_something = True
        except BackendUnavailable as e:
            degraded.append(f"speech unavailable: {e}")
        except Exception as e:  # noqa: BLE001
            log.exception("speech stage failed")
            degraded.append(f"speech failed: {e}")

    # -- CLAP: requested but absent is a fact about the answer, so it marks the response.
    if clap_on:
        clap = backends.get("clap")
        try:
            if clap is None:
                raise BackendUnavailable("no clap backend configured")
            ok, why = clap.available()
            if not ok:
                raise BackendUnavailable(why)
            events.extend(clap.classify_windows(path, onsets=rhythm.get("strong_onsets_s")))
        except BackendUnavailable as e:
            degraded.append(f"clap unavailable: {e}")
        except Exception as e:  # noqa: BLE001
            log.exception("clap stage failed")
            degraded.append(f"clap failed: {e}")

    if not produced_something:
        # Spec §32: never launder a total failure into a successful-looking empty answer.
        return JSONResponse(
            {"error": "no analyser produced anything", "degraded": degraded}, status_code=500)

    if rhythm.get("tempo_bpm") and music.get("present"):
        music["tempo_bpm"] = rhythm["tempo_bpm"]

    return JSONResponse(build_response(
        version=settings.version,
        models=_model_ids(backends),
        duration_s=duration_s, signal=signal, speech=speech, events=events, voice=voice,
        music=music, rhythm=rhythm,
        incomplete=bool(degraded)))


def _model_ids(backends: dict[str, Any]) -> dict[str, str]:
    ids: dict[str, str] = {}
    for name, be in backends.items():
        ok, _why = be.available()
        if ok:
            ids[name] = getattr(be, "model_id", "") or name
    return ids


def main() -> None:
    import uvicorn
    settings = get_settings()
    uvicorn.run("audio_worker.app:app", host=settings.host, port=settings.port)


app = create_app()

if __name__ == "__main__":
    main()
