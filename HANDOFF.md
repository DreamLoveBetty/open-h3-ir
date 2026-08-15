# Install and run OpenH3-IR

**This document installs the project, configures it, and verifies it end to end.** Work top to
bottom. Every step has a command, the output that means it worked, and what to do when it does not.
It assumes no prior knowledge of H3 and no human interpreting anything on the way.

Two neighbours, so you are in the right place:

| you want to | read |
|---|---|
| install it and make it run (you are here) | this file |
| change the compiler | [AGENTS.md](AGENTS.md) |
| call the service from an application | [docs/calling-the-api.md](docs/calling-the-api.md) |

## What this needs

| requirement | why | if missing |
|---|---|---|
| Python 3.10, 3.11 or 3.12 | tested on all three in CI | install one; 3.13 is untested |
| An OpenAI-compatible LLM endpoint **with vision** | writes the prose and reads reference images | steps 1 and 2 still pass without it |
| `ffmpeg` | video references only, nothing else | install only if you attach video |

Proven against **Qwen3.6 27B**, 4-bit, served by vLLM at 262K context on two RTX 3090s. A 27B-class
local model with a vision tower is the bar. The compiler itself needs no GPU: the weights live behind
the endpoint.

Nothing here calls MiniMax, downloads a checkpoint, or renders video.

## Step 1: install

```bash
git clone https://github.com/ruashots/open-h3-ir.git
cd open-h3-ir
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

Check, and note the distribution is `open-h3-ir` while the command is `h3ir`:

```bash
.venv/bin/h3ir --help
```

Anything other than the command listing means the install did not complete. Do not continue.

## Step 2: verify before configuring anything

These three need no model, no GPU and no network. Run all three. They are the honest test of whether
the install is sound, because nothing in them can be broken by a misconfigured endpoint.

```bash
.venv/bin/h3ir controls        # -> "22 controls, 0 failing", exit 0
.venv/bin/python -m pytest -q  # -> all tests passing, exit 0
.venv/bin/h3ir budget --seconds 10   # -> "243 frames = 10.125s", exit 0
```

If `h3ir controls` reports any failing control, stop. The validator is the product, and a failing
control means this checkout is not sound. Do not work around it.

At this point the project is installed and correct. Everything after this is about reaching a model.

## Step 3: point it at a model

```bash
export H3IR_LLM_URL=http://your-endpoint:8000/v1
.venv/bin/h3ir doctor
```

**`h3ir doctor` exits 0 even when nothing is reachable.** Do not test its exit code. Read these
fields:

| field | wanted | what a bad value means |
|---|---|---|
| `health` | `True` | `False`: nothing is answering at that URL. Wrong host, wrong port, or the server is down. |
| `chat_ok` | `True` | `False`: it answers but cannot complete. Usually no model loaded, or the wrong path (the URL must end in `/v1`). |
| `model_ids` | your model listed | empty: the endpoint serves nothing. |
| `max_model_len` | 32000 or more | much smaller and reference-heavy briefs will not fit. |

`H3IR_LLM_MODEL` can stay unset: the endpoint's first model is used, which is what you want for a
local server. Set it only if the endpoint serves several.

The `comfyui` block is optional and reported for information. Every command works with ComfyUI off,
and nothing here submits a render.

Every other setting, with the reason for each default, is in [`.env.example`](.env.example). Note that
nothing auto-loads a `.env` file; the process reads plain environment variables.

## Step 4: the first real call

This is the acceptance test for the whole install. The reference image ships in the repo, so it runs
as written:

```bash
.venv/bin/h3ir compile "she walks out onto the wet gantry in the rain and stops when she sees the city below" \
  --seconds 10 --image h3ir/golden/assets/ref1.png
```

It worked if the report line says **`0 error(s)`** and a brief follows with `subject_definitions`,
`summary`, `retention_analysis`, `detailed_description`, `overall_soundscape` and
`non_diegetic_music`. Expect `mode=ref2va`, chosen because an image was attached.

**Warnings are not failures.** `-> PASS (with warnings)` is a pass. The compiler reports things worth
knowing (a brief shorter than the spec's guidance, a shot that names a subject without restating the
wardrobe) instead of hiding them. Only `error(s)` above zero is a failure.

The HTTP service, if the caller is an application rather than a shell:

```bash
.venv/bin/h3ir serve --port 8420 &
curl -s localhost:8420/health          # -> {"ok":true,"llm":true,...}
curl -s localhost:8420/v1/briefs -H 'content-type: application/json' \
  -d '{"intent":"a lighthouse keeper lights the lamp in a storm","seconds":10}'
```

`201` with a brief is success. `intent` is the only required field.

## When something fails

| what you see | what it is | what to do |
|---|---|---|
| `h3ir: command not found` | the venv is not on PATH | call `.venv/bin/h3ir`, or activate the venv first |
| `the reasoning model at ... is not reachable. Start it, or set H3IR_LLM_URL` (exit 1) | the endpoint is down or the URL is wrong | fix the URL or start the server. This is the correct behaviour: it refuses to produce a worse brief silently |
| `the model returned the schema document instead of an instance of it (...); retrying at a higher temperature` | **expected and self-healing.** A known endpoint quirk on the analysis call, measured and documented in `backend.py`. It retries at a higher temperature and recovers | nothing. Only treat it as a failure if the command itself exits non-zero |
| `structured output requires thinking=False on this endpoint` | a structured call was made with reasoning on, which this endpoint silently ignores | a bug in calling code, not a configuration problem. See [AGENTS.md](AGENTS.md) |
| `ffmpeg is not installed, and video references need it` | exactly that, and only for video references | install ffmpeg, which provides both `ffmpeg` and `ffprobe` |
| `422` from `POST /v1/briefs` | the request cannot be honoured as stated, such as an unreadable asset path or a declared mode that contradicts what was attached | fix the request. An under-specified request is never a 422: it gets defaults |
| a compile that takes 30 seconds or more | normal on a first run. Reference images are analysed through the vision model, and that result is cached | nothing. Re-running the same image is much faster |

## What not to conclude

- **A warning is not a broken install.** See step 4.
- **A single run does not tell you the quality is good.** The prose model is not deterministic enough
  for one output to prove anything. `h3ir eval` scores a suite and gates against a stored baseline.
- **`h3ir doctor` exiting 0 does not mean the endpoint works.** Read the fields.
- **This does not render video.** It produces a brief plus the asset wiring that brief is true for.
  Submitting a render is the caller's job.
