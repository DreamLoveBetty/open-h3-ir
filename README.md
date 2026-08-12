# OpenH3-IR

**Write one sentence. Get a complete, structurally verified MiniMax H3 video brief, plus the exact
asset wiring that brief is true for.**

MiniMax open-sourced H3 and kept its Context-IR stage closed, while saying that stage is "critical
to the quality of the final output". This is an open implementation of it, running locally.

H3 does not want a prompt. It wants a document: named sections in a fixed order, subjects bound to
numbered reference labels, cut times that land on a legal frame grid, retention markers that agree
with what you actually attached. Get one field wrong and the model does not error. It quietly
renders something adjacent to what you asked for. This compiles the document and checks every field
a machine can check.

```console
$ h3ir compile "a woman steps off a night bus in the rain and realises she has left her bag on board" --seconds 10

mode=t2va  tokens=275  timings={'analyse_s': 0.0, 'mode_s': 0.0, 'draft_s': 0.14, 'compose_s': 4.42}
==========================================================================
t2va IR
  -> PASS (with warnings)   0 error(s), 1 warning(s), 1 info
==========================================================================
  [WARN] H3-token-band: prompt is 275 tokens, outside the 350-1400 band (published hosted IRs are 537-919); distribution drift, not a cost problem
  [INFO] A5-music-no-tempo: non_diegetic_music should state instrumentation, tempo and dynamics

integrated_multimodal_description: [Shot 1] Live-action, cinematic, a medium shot frames a woman in
a dark trench coat stepping off a city bus onto a rain-slicked sidewalk at night. The camera holds a
static shot as she closes the bus door behind her, the heavy thud of the mechanism sealing the
scene. She takes two steps forward, her heels clicking on the wet pavement, then stops abruptly. […]
The camera pushes in with small amplitude at slow speed toward her face as she turns her head
sharply back toward the open bus doors, her eyes widening in realization.

overall_soundscape: Heavy rain hammers against the bus roof and the pavement, creating a steady,
loud white noise. The bus engine idles with a low, diesel rumble that cuts out abruptly as the doors
close. Wet footsteps click on the concrete, followed by the rustle of her coat and the sharp intake
of her breath as she realizes her mistake.

non_diegetic_music: A sparse, melancholic piano melody begins softly under the rain, swelling
slightly as she turns back to the bus, then fading to silence as the video ends.
```

A real run, elided at `[…]`. The warning is worth reading rather than dismissing: it is not an
error, it is the compiler saying this brief came out shorter than the hosted service's own output
usually does. It reports that instead of padding the prose to hit a number.

You need one thing running: an OpenAI-compatible LLM endpoint with a vision tower. vLLM,
llama.cpp's server, LM Studio and Ollama all work. Nothing here calls MiniMax, and nothing here
needs a GPU of its own.

## Why this exists

I needed it for another application I am building, and hand-writing H3 briefs for that application
was the slowest and least reliable part of the job. So the shape of this is opinionated: it does
what that application needs, correctly, rather than being a general framework for prompt
construction. **Expect a few changes as I go.** If you build on it, pin a commit.

## Ask for ten seconds, get 10.125

```console
$ h3ir budget --seconds 10
requested 10.0s -> 243 frames = 10.125s (nominal S.SS 10.00)
canvas 1344x768, latent_t 72
video rows 72,576  audio rows 810
ref image at 'match' ~1,008 rows; at 'max' (2048 short edge) ~7,296 rows
an 800-token IR is 1.08% of the pack
```

That number is the whole idea in one line. H3 only makes clips whose frame count fits a fixed grid,
so there are exactly fifteen legal lengths between 5.167 s and 15.083 s, and **only one of the
fifteen is a whole number of seconds** (8.0 s, at 192 frames). Ten seconds is not on the grid. The
nearest lengths are 9.417 s and 10.833 s, so 243 frames at 10.125 s is as close to ten as the model
can get.

Ask for a round number and you get something else. Nothing warns you. It matters the moment you cut
to music, and it matters for every cut time inside the clip, which is why the compiler owns those
and the model never writes one.

The same output shows the other thing worth knowing before you attach anything. Prompt text is
nearly free and references are what cost, because H3 is a single-stream packed transformer: your
brief's tokens sit in the same sequence as the video and reference latents, and pass through every
DiT block on every step. An 800-token brief is about 1% of a ten-second pack. One reference image at
maximum sizing is 7,296 rows, and a five-second reference video is 37,296, roughly as much as
generating the video itself. So write long and precise, and be ruthless about how many assets you
attach.

## Attach a reference and it changes mode by itself

You never pick a mode. T2VA, I2VA, FL2VA, L2VA and Ref2VA are decided by what you attached, because
the wiring is the only thing that can decide them correctly.

```console
$ h3ir compile "the woman climbs onto the creature's back and they take off into the storm" \
    --seconds 10 \
    --image h3ir/golden/assets/ref1.png \
    --image h3ir/golden/assets/ref2.png

mode=ref2va  tokens=821  timings={'analyse_s': 12.32, 'mode_s': 1.24, 'draft_s': 0.15, 'compose_s': 10.44}
  -> PASS (with warnings)   0 error(s), 1 warning(s), 2 info
  [WARN] R15-wardrobe-not-restated: [Shot 2] names the subject but not the garments (jacket, shirt,
         t-shirt); wardrobe drifts between shots when it is only stated once
  [INFO] P5b-camera-no-amplitude: a motion type appears but without the 'with <small|large> amplitude
         at <slow|fast> speed' idiom the spec defines

subject_definitions:
<Subject 1> is the woman in <Picture 1>, with short dark hair with shaved sides and a small top knot,
dark complexion, black tactical jacket with shoulder straps and buckles, black t-shirt, black cargo
trousers, black lace-up combat boots, slender build.
<Subject 2> is the black dragon in <Picture 2>, with large reptilian creature, dark charcoal scales
with subtle blue iridescence, large leathery wings with visible membrane and bone structure, long
tail with dorsal spikes, multiple horns protruding from the head and snout […]

retention_analysis:
<Subject 1> (appears in [Shot 1], [Shot 2], [Shot 3]): fully_preserved - the woman's tactical gear,
hairstyle, and physical build are retained throughout the action.
<Subject 2> (appears in [Shot 1], [Shot 2], [Shot 3]): fully_preserved - the dragon's scale texture,
horn structure, wing membrane, and color palette are retained as it moves.

detailed_description:
The target video is a cinematic, realistic 3D animation with high-contrast lighting, emphasizing the
texture of wet scales and tactical fabric against a dark, stormy backdrop.
[Shot 1] The scene opens with a low-angle medium shot of <Subject 2>, the massive black dragon,
crouching on a wet, rocky surface amidst a heavy downpour. […] The camera tracks slightly to the
right as <Subject 1> swings her leg over the dragon's back, settling into a seated position.
[Shot 2] At 00:04.500, the shot cuts to a wider side profile view as <Subject 2> begins to move. The
dragon's powerful hind legs push against the ground, kicking up spray and debris. The camera pulls
back slowly with medium amplitude to capture the full extension of the dragon's wings as they
unfurl, revealing the intricate membrane and bone structure. […]
[Shot 3] At 00:07.500, the shot cuts to a dynamic low-angle view looking up as <Subject 2> launches
into the air. The camera tilts up rapidly, following the dragon as it breaks the surface of the
storm. […] The shot ends as they ascend higher into the clouds, becoming smaller in the frame.
```

Nobody typed `<Subject 1>`, `<Picture 2>`, `00:04.500`, `fully_preserved`, or the section names. Two
image paths went in, with no description of what was in them. Two subjects came out bound to the two
labels the runtime will actually emit, each with its own retention contract, cited in every shot they
appear in. The woman's jacket and the dragon's horn count were read off the pixels by the vision
model. Both sheets are in this repo under `h3ir/golden/assets/`, so this run is reproducible.

The R15 warning is the interesting part. Shot 2 names the woman but not her jacket, which is the
exact omission that lets wardrobe drift between cuts. A legality check cannot see that, so it is a
named rule with a reason attached.

You can tell it what a reference is instead of leaving it to the vision model, with
`--image path.png:"the pilot"`. Worth doing when an image is ambiguous about which of several things
in it you care about. It is not worth doing here, which is the point of the example.

Ref2VA briefs have six sections. Three are cut from the excerpt above: `summary`, which sits between
the two shown at the top, and `overall_soundscape` and `non_diegetic_music` at the end. The base
modes have three sections, which is why the first example is shorter. The format is not one shape,
and you do not choose which one you get.

## Structure is compiled, prose is generated

The model never decides a label number, a speaker ID, a cut time, a retention marker, a task-type
prefix or a section order. It writes prose into slots whose shape is already fixed. Your dialogue
never passes through it at all: the renderer substitutes placeholders with your exact words, so what
you typed is what ships, byte for byte.

Underneath, the order is inverted from the usual retry-until-valid loop.

1. A **deterministic draft** is built first, a complete and valid brief with no prose model
   involved. Thin but honest, saying only what the wiring and the asset analysis support.
2. The model pass is additive prose enrichment over a bounded surface.
3. The result is parsed back, reconstructed, and diffed against the plan. Findings go back to the
   model to fix.
4. If that does not converge, whether from a validator error, leaked reasoning, or an endpoint
   outage, the draft ships. You always get something valid, and the response says which path
   produced it.

The one thing that raises instead of falling back is the draft failing its own validator. That is
deterministic, so it would be a bug here, and there would be nothing left to fall back to.

`compile_brief(..., llm=False)` gives you the draft alone, which is a free A/B baseline. If the
enriched brief cannot beat its own no-model draft, the prose pass is not earning its cost.

## The checks are the product, so they are checked too

A rule that cannot be made to fire is not a rule. Every rule is proved in both directions before it
counts.

```console
$ h3ir controls
  [ok  ] MUST PASS: MiniMax official Ref2VA example (P5 exempt, see note)
  [ok  ] MUST FAIL: missing (appears in [Shot N])
  [ok  ] MUST FAIL: <Image N> instead of <Picture N>
  [ok  ] MUST FAIL: invented retention marker
  [ok  ] MUST FAIL: sections out of order
  … 15 more …
20 controls, 0 failing
```

MiniMax's own published example must validate with zero findings, and fourteen mutants of it, each
carrying exactly one defect, must each trip a named rule. There are eighty-four named rules. This
gate runs in under a tenth of a second and needs no model.

Legality is not quality, so there is a scored suite as well. A prompt change can improve one and
wreck the other.

```console
$ h3ir eval
  t2va_battle          clean fix=0 mode=t2va   words= 126 (x0.38) shots=2 cuts=1 cam=3 restate=0.08 dup=0.04 E0/W1
  t2va_silent          clean fix=0 mode=t2va   words= 103 (x0.31) shots=1 cuts=0 cam=2 restate=0.00 dup=0.09 E0/W1
  ref2va_two_subjects  clean fix=0 mode=ref2va words= 254 (x0.64) shots=3 cuts=2 cam=2 restate=0.12 dup=0.05 E0/W1
  … 3 more …

means over 6 brief(s), 35.7s wall:
  errors           0.0
  restatement      0.075
  sound_overlap    0.061
  fallback_rate    0.0
  clean_rate       1.0
  … 10 more …
-- gate --
  restatement         0.070 ->    0.075  (+0.005)  same
  sound_overlap       0.051 ->    0.061  (+0.010)  same
  …
SHIP-ABLE
```

Six briefs, each one a failure that actually happened rather than a spread chosen to look broad.
Errors gate absolutely, trends gate within a tolerance. A first run has no stored baseline yet, so
you get the scores with no comparison; `h3ir eval --set-baseline` records one to measure the next
change against.

Prompt templates live in `h3ir/prompts/*.txt` as versioned files, so changing one is an artifact you
can score instead of an opinion you can hold. This gate has already blocked a change that improved
the metric it was aiming at while introducing validator errors, and the root cause turned out to be
a latent bug rather than the prompt.

## Install

Needs Python 3.10 or newer and an OpenAI-compatible LLM endpoint with vision. Verified on 3.12.

```bash
git clone https://github.com/Ruashots/open-h3-ir.git && cd open-h3-ir
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"

export H3IR_LLM_URL=http://your-endpoint:8000/v1   # the only setting most people change
h3ir doctor
```

The project is `open-h3-ir`; the command and the import are both `h3ir`, which is what you type.

`h3ir doctor` tells you what is actually answering before you debug anything else: the endpoint, the
model it serves, its context length, whether ComfyUI is reachable and which H3 nodes are installed,
and a tokenizer self-test.

Two commands need nothing running at all, if you want to see it work before configuring anything:
`h3ir controls` and `h3ir budget`. Every setting, with the reason for each default, is in
[`.env.example`](.env.example).

## The HTTP API

The API is the product and the CLI is one of its clients. There is no quality-bearing field that
only a UI could set, and no path that skips the validator.

```bash
h3ir serve --port 8420
curl -s localhost:8420/v1/briefs -H 'content-type: application/json' \
  -d '{"intent":"a lighthouse keeper lights the lamp in a storm","seconds":10}'
```

The minimum viable request is one sentence. No mode, no checkpoint, no canvas maths, no section
names. Every response carries three layers, and a UI should read the first two.

| layer | what it is |
|---|---|
| `presentation` | plain language: the shots, who speaks, the sound. No labels, no markers, no field names, no mode names ever. |
| `plan` | the creative decisions, refinable |
| `ir` | the full document plus the asset manifest, for whoever wires the graph |

`PATCH /v1/briefs/{id}` takes plain language. `{"change":"make it darker"}` returns 200 with a new
version and the fields it touched. `GET /v1/capabilities` reports the legal durations, aspects, asset
limits and dialogue languages, so a caller never has to hardcode them. `GET /v1/loras` lists
available styles by id and prose, never by trigger string.

Under-specification never fails. `{"intent":"make a video of my dog"}` and nothing else returns 201
with a complete, valid, zero-error brief: five seconds, widescreen, two shots, all chosen for you.
What returns 422 is a request the service cannot honour as stated, such as an asset path it cannot
read, or a caller-stated mode that contradicts what was attached. Impossible creative asks are not
rejected, they are overruled. Ask for a first cut at twelve seconds inside a ten-second clip and you
get a legal timeline, because the compiler owns cut times and will not emit one past the end.

Route list and request shapes: [`docs/calling-the-api.md`](docs/calling-the-api.md).

## What it does not do

Stated plainly, because these are the assumptions most likely to be made wrongly.

- **It does not judge whether the writing is good.** The validator has no access to that. It can
  tell you a shot names a subject without restating the wardrobe. It cannot tell you the edit is
  dull.
- **It does not enforce length.** The spec's 350 to 500 word guidance is a warning and never an
  error, deliberately: a 274-word brief directed well beat a 636-word one that was not. Briefs come
  out under that band more often than in it, and the warning tells you when.
- **It does not guarantee that a person's identity survives the render.** The brief binds the
  reference and states what must be preserved. Whether the model delivers is a render outcome.
- **It does not render anything.** No sampler, no graph submission, no GPU. It reports what ComfyUI
  has installed; wiring the render is the caller's job.
- **It cannot hear.** There is a vision tower and no audio tower, and a model asked about a waveform
  invents a plausible answer instead of abstaining. Audio references are described from typed
  metadata plus a transcript you supply. Nothing here transcribes, and nothing here will guess a
  timbre.
- **It is H3-only, all the way down.** The validator rules, the frame grid, the vendored vocabulary
  and the section names are H3's. This is not a general video-prompt library with an H3 backend, and
  retargeting it at another model would be a rewrite rather than a config change.
- **A single run is not a measurement.** The prose model is not deterministic enough for one output
  to prove anything, which is what `h3ir eval` is for.

## Where to look next

| file | what it is for |
|---|---|
| [`docs/calling-the-api.md`](docs/calling-the-api.md) | driving the service: what it guarantees, what it only attempts, what comes back |
| [`docs/design.md`](docs/design.md) | why every rule exists: what the encoder actually sees, the cost model, the contract between stages |
| [`docs/build-log.md`](docs/build-log.md) | a dated record of what the build measured, including the positions this project reversed |
| [`AGENTS.md`](AGENTS.md) | working on the compiler: the rules that are not preferences, where things live, the known gaps |
| [`loras/handpainted-anim-v2/`](loras/handpainted-anim-v2/) | a worked example of the style-LoRA registry format |

The tokenizer under `h3ir/data/qwen25_tokenizer/` is vendored on purpose. Token counts have to be
what H3's own encoder sees, and H3's shipped `vocab.json` is byte-identical to the one ComfyUI
bundles (git blob `4783fe10ac3adce15ac8f358ef5462739852c569`), so `h3ir budget` is exact, offline,
with nothing to download.

## Tests

```console
$ pytest -q
359 passed in 0.86s
```

No model, no GPU, no network.

## Licence

Apache 2.0. See [LICENSE](LICENSE), and [NOTICE](NOTICE) for what belongs to whom. The Qwen2.5
tokenizer vocabulary vendored under `h3ir/data/` is Apache 2.0 as well, so it adds nothing this
licence does not already carry.

**Apache 2.0 covers this compiler. It does not cover the model you point it at, and H3's own licence
is more restrictive than you might assume.** Three terms from it that are worth knowing before you
build on this, because none of them is guessable:

- **H3 is not licensed for use in the European Union, the United Kingdom, the Republic of Korea or
  the United States of America.** Those are its "Excluded Territories", and the grant is worldwide
  except for them. MiniMax invites people there to contact them for a licence.
- A commercial product or service using H3 **shall prominently display "MiniMax H3" in its user
  interface** (section IV.2).
- Commercial products earning **more than 20 million USD a year need separate written authorization**
  from MiniMax first (section IV.1).

Read the [MiniMax H3 Community License Agreement](https://huggingface.co/MiniMaxAI/MiniMax-H3/blob/main/LICENSE)
yourself rather than trusting this summary. Nothing in this repository is a MiniMax work: there is no
model code, no weights, and no checkpoint here.
