# h3ir

**Write one sentence. Get a complete, structurally verified MiniMax H3 video brief — and the exact
asset wiring that brief is true for.**

H3 does not want a prompt. It wants a document: named sections in a fixed order, subjects bound to
numbered reference labels, cut times on a legal frame grid, retention markers that agree with what
you actually attached. Get one field wrong and the model does not error — it quietly renders
something adjacent to what you asked for. This compiles the document for you and checks every field
a machine can check.

```console
$ pip install -e .
$ h3ir compile "a woman steps off a night bus in the rain and realises she has left her bag on board" --seconds 8

mode=t2va  tokens=271  timings={'analyse_s': 0.0, 'mode_s': 0.0, 'draft_s': 0.15, 'compose_s': 6.03}
==========================================================================
t2va IR
  -> PASS (with warnings)   0 error(s), 1 warning(s), 2 info
==========================================================================
  [WARN] H3-token-band: prompt is 271 tokens, outside the 350-1400 band (published hosted IRs are 537-919) — distribution drift, not a cost problem
  [INFO] X12-brief-repaired: normalised curly quotes / non-breaking spaces outside verbatim spans
  [INFO] A5-music-no-tempo: non_diegetic_music should state instrumentation, tempo and dynamics

integrated_multimodal_description: [Shot 1] Live-action, cinematic, a medium shot frames a woman in
a dark trench coat stepping off a city bus onto a rain-slicked sidewalk at night. The camera holds a
static shot as she lands on the wet pavement, her heels clicking sharply, and she turns back toward
the open bus doors. […] The camera pushes in with small amplitude at slow speed toward her face as
she watches the bus pull away into the rainy night, leaving her standing alone on the curb.

overall_soundscape: Heavy rain hammers against the pavement and the bus roof, creating a steady,
loud backdrop. The bus engine idles with a low rumble before cutting out as the doors close with a
pneumatic hiss. Footsteps splash on the wet concrete, and the woman's sharp intake of breath is
audible as she realizes her mistake.

non_diegetic_music: A solitary, melancholic cello melody begins softly, swelling slightly as the bus
doors close, then fading into silence as the bus drives away.
```

That is a real run, lightly elided at `[…]`. Note the warning: it is not an error, it is the
compiler telling you this brief came out shorter than the hosted service's own output usually does.
It reports that rather than padding the prose to hit a number.

You need one thing running: an OpenAI-compatible LLM endpoint with a vision tower. Anything —
vLLM, llama.cpp's server, LM Studio, Ollama. Nothing here calls MiniMax, and nothing here needs a
GPU of its own.

## Attach a reference and it changes mode by itself

You never pick a mode. T2VA, I2VA, FL2VA, L2VA and Ref2VA are decided by what you attached, because
the wiring is the only thing that can decide them correctly.

```console
$ h3ir compile "he reads a letter by the window and decides to leave" --seconds 8 --image character.png:"the man"

mode=ref2va  tokens=688  timings={'analyse_s': 4.87, 'mode_s': 1.2, 'draft_s': 0.15, 'compose_s': 13.45}
  -> PASS (with warnings)   0 error(s), 2 warning(s), 1 info
  [WARN] P2-too-short: detailed_description is 294 words; spec guidance 350-500, official example 336
  [WARN] R15-wardrobe-not-restated: [Shot 2] names the subject but not the garments (sweater);
         wardrobe drifts between shots when it is only stated once

subject_definitions:
<Subject 1> is the man in <Picture 1>, with young adult male, wavy reddish-brown hair, medium length
hair, light skin tone, brown eyes, straight nose, clean-shaven face, rust-colored crew neck sweater.

retention_analysis:
<Subject 1> (appears in [Shot 1], [Shot 2], [Shot 3]): fully_preserved - the character's wavy
reddish-brown hair, light skin, brown eyes, and rust-colored crew neck sweater are retained
throughout the sequence.

detailed_description:
The target video is rendered in a high-fidelity digital illustration style, featuring soft,
directional lighting and a muted, contemplative color palette.
[Shot 1] A medium shot establishes <Subject 1> standing in profile by a window, bathed in soft
natural light that highlights the texture of his rust-colored crew neck sweater […]
[Shot 2] At 00:03.000, the shot cuts to a close-up of <Subject 1>'s face from a 3/4 angle. The
camera pushes in slowly with small amplitude […]
[Shot 3] At 00:05.500, the shot cuts to a medium shot from behind <Subject 1> […] He folds the
letter decisively and places it into the pocket of his rust-colored sweater.
```

Nobody typed `<Subject 1>`, `<Picture 1>`, `00:03.000`, `fully_preserved`, or the section names. The
image was read by the vision model, the subject was defined from what it saw, and the retention
contract was written to match. The second warning is the compiler noticing that shot 2 names the man
but not his sweater — the exact omission that lets wardrobe drift between cuts.

Ref2VA briefs have six sections; the `summary`, `overall_soundscape` and `non_diegetic_music` that
follow are cut from the excerpt above. The base modes have three, which is why the first example is
shorter — the format is not one shape, and you do not choose which one you get.

## Why a compiler and not a prompt template

Three facts about H3, each verified against the shipped runtime rather than assumed.

**The reference labels are emitted by the runtime, not by your prompt.** ComfyUI's H3 tokenizer
writes `"<Picture 1>: "` into the token stream immediately before each image's vision block, then
appends your prompt text after all of them. A prompt that says `<Image 1>` is addressing a name that
does not exist. So a label is only correct *relative to a wiring* — which means the prompt and the
wiring have to be produced together, and a dangling label should be a build error rather than a
silent quality loss.

**`<Subject 1>` means nothing on its own.** It is grounded only because `subject_definitions`
defines it in text. That is the real work the six-section Ref2VA format does: it is the one place an
identity gets bound to a label and told what has to survive.

**Prompt text is nearly free; references are what cost.** H3 is a single-stream packed transformer —
your brief's tokens sit in the same sequence as the video and reference latents and pass through
every DiT block on every step. An 800-token brief is about 1% of a ten-second pack. One reference
image at maximum sizing is 7,296 rows, and a five-second reference video is 37,296 — roughly as much
as generating the video itself. So write long and precise, and be ruthless about how many assets you
attach. `h3ir budget` prints the arithmetic for any duration:

```console
$ h3ir budget --seconds 10
requested 10.0s -> 243 frames = 10.125s (nominal S.SS 10.00)
canvas 1344x768, latent_t 72
video rows 72,576  audio rows 810
ref image at 'match' ~1,008 rows; at 'max' (2048 short edge) ~7,296 rows
an 800-token IR is 1.08% of the pack
```

## How it stays valid: structure is compiled, prose is generated

The model never decides a label number, a speaker ID, a cut time, a retention marker, a task-type
prefix or a section order. It writes prose into slots whose shape is already fixed. Your dialogue
never passes through it at all — the renderer substitutes placeholders with your exact words, so
what you typed is what ships, byte for byte.

Underneath, the order is inverted from the usual retry-until-valid loop:

1. A **deterministic draft** is built first — a complete, valid brief with no prose model involved.
   Thin but honest: it says only what the wiring and the asset analysis support.
2. The model pass is **additive** prose enrichment over a bounded surface.
3. The result is parsed back, reconstructed, and diffed against the plan. Findings go back to the
   model to fix.
4. If that does not converge — a validator error, leaked reasoning, an endpoint outage — the draft
   ships. You always get something valid, and the response says which path produced it.

The one thing that raises instead of falling back is the draft failing its own validator. That is
deterministic, so it would be a bug here, and there would be nothing left to fall back to.

`compile_brief(..., llm=False)` gives you the draft alone, which is a free A/B baseline: if the
enriched brief cannot beat its own no-model draft, the prose pass is not earning its cost.

## The checks are the product, so they are checked too

A rule that cannot be made to fire is not a rule. Every rule in the validator is proved in both
directions before it counts:

```console
$ h3ir controls
  [ok  ] MUST PASS: MiniMax official Ref2VA example (P5 exempt, see note)
  [ok  ] MUST FAIL: <Image N> instead of <Picture N>
  [ok  ] MUST FAIL: missing (appears in [Shot N])
  [ok  ] MUST FAIL: invented retention marker
  [ok  ] MUST FAIL: sections out of order
  … 15 more …
20 controls, 0 failing
```

MiniMax's own published example must validate with **zero** findings, and fourteen mutants of it —
each carrying exactly one defect — must each trip a **named** rule. There are more than eighty named
rules; this gate runs in 0.08 seconds and needs no model.

Beyond legality there is a scored suite, because "is it legal" and "is it any good" are different
questions and a prompt change can improve one while wrecking the other:

```console
$ h3ir eval
  t2va_battle          clean fix=0 mode=t2va   words= 126 (x0.38) shots=2 cuts=1 cam=3 restate=0.08 dup=0.04 E0/W1
  t2va_silent          clean fix=0 mode=t2va   words= 103 (x0.31) shots=1 cuts=0 cam=2 restate=0.00 dup=0.09 E0/W1
  ref2va_two_subjects  clean fix=0 mode=ref2va words= 285 (x0.71) shots=3 cuts=2 cam=2 restate=0.09 dup=0.03 E0/W1
  … 3 more …

means over 6 brief(s), 40.7s wall:
  errors 0.0   fallback_rate 0.0   clean_rate 1.0   restatement 0.069   sound_overlap 0.054
-- gate --
  restatement         0.070 ->    0.069  (-0.001)  same
  sound_overlap       0.051 ->    0.054  (+0.003)  same
  …
SHIP-ABLE
```

Six briefs, chosen because each one is a failure that actually happened rather than to be broad.
Errors gate absolutely; trends gate within a tolerance. On a first run there is no stored baseline
yet, so you get the scores with no comparison — `h3ir eval --set-baseline` records one to measure the
next change against.

Prompt templates live in `h3ir/prompts/*.txt` as versioned files precisely so that changing one is
an artifact you can score instead of an opinion you can hold. This gate has already blocked a change
that improved the metric it was aiming at while introducing validator errors — and the root cause
turned out to be a latent bug, not the prompt.

## Install

Needs Python 3.10+ and an OpenAI-compatible LLM endpoint with vision. Verified on 3.12.

```bash
git clone <this repo> && cd h3ir
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"

export H3IR_LLM_URL=http://your-endpoint:8000/v1   # the only setting most people change
h3ir doctor
```

`h3ir doctor` tells you what is actually answering before you debug anything else — the endpoint,
the model it serves, its context length, whether ComfyUI is reachable and which H3 nodes are
installed, and a tokenizer self-test.

Two commands need nothing running at all, if you want to see it work before configuring anything:
`h3ir controls` and `h3ir budget`.

Every setting, with the reason for each default, is in [`.env.example`](.env.example).

## The HTTP API

The API is the product and the CLI is one of its clients. There is no quality-bearing field that
only a UI could set, and no path that skips the validator.

```bash
h3ir serve --port 8420
curl -s localhost:8420/v1/briefs -H 'content-type: application/json' \
  -d '{"intent":"a lighthouse keeper lights the lamp in a storm","seconds":10}'
```

The minimum viable request is one sentence. No mode, no checkpoint, no canvas maths, no section
names. Every response carries three layers, and a UI should read the first two:

| layer | what it is |
|---|---|
| `presentation` | plain language — the shots, who speaks, the sound. No labels, no markers, no field names, no mode names ever. |
| `plan` | the creative decisions, refinable |
| `ir` | the full document plus the asset manifest, for whoever wires the graph |

`PATCH /v1/briefs/{id}` takes plain language: `{"change":"make it darker"}` comes back `200` with a
new version and the fields it touched. `GET /v1/capabilities` reports the legal durations, aspects,
asset limits and dialogue languages, so a caller never has to hardcode them. `GET /v1/loras` lists
available styles by id and prose, never by trigger string.

**Under-specification never fails.** `{"intent":"make a video of my dog"}` and nothing else returns
`201` with a complete, valid, zero-error brief — five seconds, widescreen, two shots, all chosen for
you. What returns `422` is a request the service cannot honour as stated: an asset path it cannot
read, or a caller-stated mode that contradicts what was attached. Impossible *creative* asks are not
rejected, they are overruled — ask for a first cut at twelve seconds inside a ten-second clip and you
get a legal timeline, because the compiler owns cut times and will not emit one past the end.

Full route list and the request/response shapes: [`docs/calling-the-api.md`](docs/calling-the-api.md).

## What it does not do

Stated plainly, because these are the assumptions most likely to be made wrongly:

- **It does not judge whether the writing is good.** The validator has no access to that. It can
  tell you a shot names a subject without restating the wardrobe; it cannot tell you the edit is
  dull.
- **It does not enforce length.** The spec's 350–500 word guidance is reported as a warning and
  never made an error, deliberately — a 274-word brief directed well beat a 636-word one that
  wasn't. Briefs currently come out below that band more often than not; the warning tells you when.
- **It does not guarantee that a person's identity survives the render.** The brief binds the
  reference and states what must be preserved. Whether the model delivers is a render outcome.
- **It does not render anything.** No sampler, no graph submission, no GPU. It reports what ComfyUI
  has installed; wiring the render is the caller's job.
- **It cannot hear.** There is a vision tower and no audio tower, and a model asked about a waveform
  invents a plausible answer instead of abstaining. Audio references are described from typed
  metadata plus a transcript you supply. Nothing here transcribes, and nothing here will guess a
  timbre.
- **A single run is not a measurement.** The prose model is not deterministic enough for one output
  to prove anything. That is what `h3ir eval` is for.

## Where to look next

| file | what it is for |
|---|---|
| [`docs/calling-the-api.md`](docs/calling-the-api.md) | driving the service — what it guarantees, what it only attempts, and what comes back |
| [`docs/design.md`](docs/design.md) | why every rule exists: what the encoder actually sees, the cost model, the contract between stages |
| [`docs/build-log.md`](docs/build-log.md) | a dated record of what the build measured, including the positions this project reversed |
| [`AGENTS.md`](AGENTS.md) | working on the compiler: the rules that are not preferences, where things live, and the known gaps |
| [`loras/handpainted-anim-v2/`](loras/handpainted-anim-v2/) | a worked example of the style-LoRA registry format |

The tokenizer under `h3ir/data/qwen25_tokenizer/` is vendored on purpose. Token counts have to be
what H3's own encoder sees, and H3's shipped `vocab.json` is byte-identical to the one ComfyUI
bundles — so `h3ir budget` is exact, offline, with nothing to download.

## Tests

```console
$ pytest -q
357 passed in 0.82s
```

No model, no GPU, no network.

## Licence

Not yet chosen, which means this code is not yet licensed for reuse. If you want to use it, open an
issue and ask.
