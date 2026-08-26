"""Qwen2.5-Omni-3B as the compiler's semantic fallback (spec §11, §31).

The compiler talks to the fallback over the OpenAI-compatible chat route with an
`input_audio` part (the shape vLLM's audio-capable endpoint accepts), so this shim serves
exactly that shape: one POST /v1/chat/completions, audio in as a base64 wav, the §11 JSON
out as the message content. Only the THINKER half is loaded -- the fallback describes audio,
it never speaks, so the talker weights stay on disk.

On-demand per spec §31: this service is started when a deployment wants the fallback, and the
compiler's router only calls it when the deterministic chain cannot explain the audio.

Run (from the repository's services/ directory):

    .venv-audio/bin/python -m omni_fallback.app

Env: OMNI_MODEL_PATH (default: the project-local ModelScope snapshot), OMNI_HOST,
OMNI_PORT (8001, matching the compiler's H3IR_AUDIO_FALLBACK_URL default), OMNI_DEVICE
(cpu default; mps on Apple Silicon if the ops you need are covered), OMNI_MAX_NEW_TOKENS.
"""
from __future__ import annotations

import base64
import io
import logging
import os
import wave

import numpy as np
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

log = logging.getLogger("omni_fallback")

_ROOT = os.path.dirname(os.path.abspath(__file__))
_DEFAULT_MODEL = os.path.normpath(os.path.join(
    _ROOT, "..", "..", "models", "modelscope", "models",
    "Qwen--Qwen2.5-Omni-3B", "snapshots", "master"))

MODEL_PATH = os.environ.get("OMNI_MODEL_PATH", "").strip() or _DEFAULT_MODEL
HOST = os.environ.get("OMNI_HOST", "127.0.0.1")
PORT = int(os.environ.get("OMNI_PORT", "8001"))
DEVICE = os.environ.get("OMNI_DEVICE", "cpu")
MAX_NEW = int(os.environ.get("OMNI_MAX_NEW_TOKENS", "512"))

_model = None
_processor = None


def _load():
    """Lazy: the process answers /health before the weights are warm, and model load takes
    long enough that doing it at import would look like a hang."""
    global _model, _processor
    if _model is not None:
        return
    import torch
    from transformers import (Qwen2_5OmniProcessor,
                              Qwen2_5OmniThinkerForConditionalGeneration)
    log.info("loading thinker from %s on %s", MODEL_PATH, DEVICE)
    dtype = torch.float32 if DEVICE == "cpu" else torch.bfloat16
    _processor = Qwen2_5OmniProcessor.from_pretrained(MODEL_PATH)
    _model = Qwen2_5OmniThinkerForConditionalGeneration.from_pretrained(
        MODEL_PATH, dtype=dtype).to(DEVICE)
    _model.eval()


def _wav_bytes_to_float32(data: bytes) -> np.ndarray:
    """The compiler ships the observer's 16 kHz mono wav; stdlib wave reads it directly."""
    with wave.open(io.BytesIO(data)) as w:
        frames = w.readframes(w.getnframes())
        pcm = np.frombuffer(frames, dtype=np.int16)
        if w.getnchannels() > 1:
            pcm = pcm.reshape(-1, w.getnchannels()).mean(axis=1).astype(np.int16)
    return pcm.astype(np.float32) / 32768.0


def _extract_parts(messages: list) -> tuple[str, np.ndarray | None, str]:
    """-> (system text, audio samples, user text). The audio part accepts both the bare
    base64 the compiler's FallbackClient sends and a full data: URL."""
    system = ""
    user_text = ""
    audio = None
    for m in messages:
        content = m.get("content")
        if isinstance(content, str):
            if m.get("role") == "system":
                system += content
            else:
                user_text += content
            continue
        for part in content or []:
            t = part.get("type")
            if t == "text":
                if m.get("role") == "system":
                    system += part.get("text", "")
                else:
                    user_text += part.get("text", "")
            elif t == "input_audio":
                raw = part.get("input_audio", {}).get("data", "")
                if "," in raw[:80]:  # a data: URL prefix, if any, is not the payload
                    raw = raw.split(",", 1)[1]
                audio = _wav_bytes_to_float32(base64.b64decode(raw))
    return system, audio, user_text


app = FastAPI(title="h3ir omni fallback")


@app.get("/health")
def health() -> dict:
    return {"model": os.path.basename(MODEL_PATH.rstrip("/")), "device": DEVICE,
            "warm": _model is not None}


@app.post("/v1/chat/completions")
async def chat_completions(request: Request) -> JSONResponse:
    body = await request.json()
    messages = body.get("messages") or []
    try:
        system, audio, user_text = _extract_parts(messages)
    except Exception as e:
        return JSONResponse({"error": f"bad audio payload: {e}"}, status_code=400)
    if audio is None:
        return JSONResponse({"error": "no input_audio part in the request"}, status_code=400)

    _load()
    conversation = [
        {"role": "system", "content": [{"type": "text", "text": system}]},
        {"role": "user", "content": [{"type": "audio", "audio": audio},
                                     {"type": "text", "text": user_text}]},
    ]
    text = _processor.apply_chat_template(conversation, add_generation_prompt=True,
                                          tokenize=False)
    inputs = _processor(text=text, audio=[audio], sampling_rate=16000,
                        return_tensors="pt").to(DEVICE)
    import torch
    # The thinker's generation_config ships no eos_token_id, and without one generate runs
    # straight past <|im_end|> into training-data bleed (seen at bring-up: the JSON answer
    # followed by an unrelated story). Stop tokens are stated explicitly instead.
    eos_ids = [_processor.tokenizer.eos_token_id]
    eot = _processor.tokenizer.convert_tokens_to_ids("<|endoftext|>")
    if isinstance(eot, int) and eot not in eos_ids:
        eos_ids.append(eot)
    with torch.inference_mode():
        out = _model.generate(**inputs, max_new_tokens=int(body.get("max_tokens") or MAX_NEW),
                              do_sample=False, eos_token_id=eos_ids)
    reply = _processor.batch_decode(out[:, inputs.input_ids.shape[1]:],
                                    skip_special_tokens=True)[0]
    return JSONResponse({
        "id": "omni-fallback-1", "object": "chat.completion",
        "choices": [{"index": 0, "finish_reason": "stop",
                     "message": {"role": "assistant", "content": reply.strip()}}],
        "usage": {}})


if __name__ == "__main__":
    uvicorn.run(app, host=HOST, port=PORT, log_level="info")
