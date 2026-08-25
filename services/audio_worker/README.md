# h3ir Audio Worker

The heavy half of OpenH3-IR's local audio understanding. The compiler
(`h3ir`, the `open-h3-ir` package) stays light — HTTP and JSON — and talks to this process;

this process owns torch, FunASR, and the model weights.

```text
audio bytes ──▶ POST /v1/audio/analyze (multipart)
                   │
                   ├─ DSP tier      ffmpeg decode → loudness / silence / onsets / tempo
                   ├─ Speech tier   FSMN-VAD → SenseVoiceSmall → CAM++ speaker clusters
                   └─ CLAP tier     sliding + onset windows → zero-shot labels, located
                   │
                   ▼
        AudioObservation-shaped JSON  (+ `incomplete: true` when a stage is missing)
```

## Running

```bash
cd services
python -m venv .venv-audio && . .venv-audio/bin/activate
pip install -r audio_worker/requirements.txt

# The speech stack, when you want it (pick the torch build for your platform first):
pip install torch torchaudio funasr modelscope

# The CLAP tier, when you want it (needs torch from the line above):
pip install transformers

python -m audio_worker.app          # serves http://127.0.0.1:50000
```

Point the compiler at it:

```bash
export H3IR_AUDIO_ENABLED=1
export H3IR_AUDIO_URL=http://127.0.0.1:50000
```

## Endpoints

### `GET /health`

```json
{
  "version": "audio-worker-1",
  "models": {"dsp": "dsp", "speech": "speech"},
  "capabilities": {
    "dsp": "ok",
    "speech": "ok",
    "clap": "unavailable: transformers/torch not installed (...)"  // until the stack below is
  }
}
```

`version` + `models` are the worker's identity; the compiler mixes them into its observation
cache key, so **bump `version` in `settings.py` when the wire contract or the analysis logic
changes** — a cached observation must not survive a change in how it was produced.

### `POST /v1/audio/analyze`

`multipart/form-data`:

| field                | meaning                                  |
|----------------------|------------------------------------------|
| `file`               | the audio, any container ffmpeg reads    |
| `enable_diarization` | `true`/`false` (default true)            |
| `enable_clap`        | `true`/`false` (default true)            |
| `enable_dsp`         | `true`/`false` (default true)            |

The response is the compiler's `AudioObservation` wire shape (spec §8) plus `version`,
`models`, and `incomplete`. **A stage that fails never produces a fabricated empty success**:
total failure is a 500, partial success is the facts that exist with `incomplete: true`, and a
file ffmpeg cannot read is a 422.

## Settings

All `AUDIO_WORKER_*`, read once in `settings.py`: `HOST`, `PORT`, `MAX_UPLOAD_BYTES`
(200 MiB), `MAX_AUDIO_SECONDS` (600), `SENSEVOICE_MODEL`, `VAD_MODEL`, `SPEAKER_MODEL`,
`CLAP_MODEL`, `MODEL_DIR`, `DEVICE`, `SPEAKER_THRESHOLD` (cosine, default 0.65).

## What is verified and what is not

The wire contract is tested end to end against the compiler's real client
(`tests/test_app_protocol.py` drives this app through httpx's ASGI transport and parses the
answer with `h3ir.audio.client.AudioWorkerClient`). The DSP tier is tested against real
synthesised WAVs through real ffmpeg. The CLAP tier's windowing and event merging are
unit-tested with a fake scorer; the FunASR and CLAP model calls are written against the
documented interfaces (`AutoModel`, `ClapModel`/`ClapProcessor`) and get their live
verification at first bring-up on real weights.

## Tests

```bash
python -m pytest services/audio_worker/tests   # from the repository root
```

They need the compiler's dev environment (fastapi, httpx, numpy, python-multipart) but no
model weights and no GPU.
