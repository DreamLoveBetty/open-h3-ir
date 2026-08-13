# open-h3-ir

[![tests](https://github.com/Ruashots/open-h3-ir/actions/workflows/ci.yml/badge.svg)](https://github.com/Ruashots/open-h3-ir/actions/workflows/ci.yml)

**Type one sentence. Get better video out of MiniMax H3.**

H3 does not want a prompt. It wants a structured document: named sections in a fixed order, every
subject bound to a numbered picture label, cut times that land on a legal frame grid. MiniMax
open-sourced the model but not the stage that writes that document, saying only that
["H3-Context-IR is critical to the quality of the final output"](https://huggingface.co/MiniMaxAI/MiniMax-H3)
and that you should call their hosted service for it.

This is an open one, running on your own machine, with a dial on top of it.

## Same model, same seed, same reference image. The only difference is the words.

![The same request, sent raw on the left and compiled on the right](docs/media/off-vs-on.webp)

Both halves are the same request: *"she walks out onto the wet gantry in the rain and stops when she
sees the city below."* On the left that sentence goes to H3 as typed. On the right it goes through
`h3ir` first. Nothing else moved between the two runs: same reference image, same seed, same 10.125
seconds, same settings.

The right side does what the sentence asked. She walks out along the gantry, and at five seconds it
cuts to a low-angle close-up of her looking down at the city.

The left side is a good-looking clip that never arrives. It cannot decide where she is going, walking
toward camera for the first half and away from it in the second, and the railing and the skyline
behind her change into a different place along the way. She never looks down, so the beat the whole
sentence was built around is missing. Nothing on that side is badly rendered, and that is the point:
the model was fine, the words were the problem.

**Watch it with sound:** [off-vs-on.mp4](docs/media/off-vs-on.mp4). H3 generates the rain and the
score in the same pass as the picture. GitHub cannot play a repo-hosted mp4 inline, so the animation
above is the silent version and the file is the one with audio. The brief that produced the right
half is committed beside it:
[`off-vs-on.compiled-brief.txt`](docs/media/off-vs-on.compiled-brief.txt).

## And a dial, for how far it goes

![the same request at restrained on the left and extreme on the right](docs/media/dial-restrained-vs-extreme.webp)

*"the car rolls into the showroom and stops under the lights."* Run twice, changing one flag.

`restrained` keeps the whole showroom in a steady wide and cuts once. `extreme` opens on an extreme
wide, cuts to a fast push-in on the front wheel, lands on a locked hero shot, and scores the whole
thing. Two shots became three, and the camera stopped being polite.

```bash
h3ir compile "the car rolls into the showroom and stops under the lights" --creativity extreme
```

Four positions: `restrained`, `balanced` (the default), `bold`, `extreme`. What changes is how much
the writer may introduce that you never asked for, and an explicit "no dialogue" at `extreme` still
means no dialogue.

**Watch it with sound:** [dial-restrained-vs-extreme.mp4](docs/media/dial-restrained-vs-extreme.mp4).
Both briefs are committed, so you can read exactly what the flag did:
[restrained](docs/media/dial-restrained.brief.txt) and
[extreme](docs/media/dial-extreme.brief.txt). Both reference images are committed too, so you can
run the whole thing yourself:

```bash
h3ir compile "the car rolls into the showroom and stops under the lights" \
  --image docs/media/plate-car.jpg:"the car" \
  --image docs/media/plate-showroom.jpg:"the empty showroom floor it drives across" \
  --seconds 10 --creativity extreme
```

## Install

Python 3.10 or newer, and an OpenAI-compatible LLM endpoint with vision. vLLM, llama.cpp's server,
LM Studio and Ollama all speak it. Nothing here calls MiniMax, and nothing here needs a GPU of its
own.

```bash
git clone https://github.com/Ruashots/open-h3-ir.git
cd open-h3-ir
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"

export H3IR_LLM_URL=http://your-endpoint:8000/v1   # the only setting most people change
h3ir doctor
```

The project is called `open-h3-ir`. The command and the import are both `h3ir`, which is what you
type.

`h3ir doctor` tells you what is actually answering before you debug anything else: the endpoint, the
model it serves, its context length, whether ComfyUI is reachable and which H3 nodes it has, and a
tokenizer self-test. Two commands need nothing running at all if you want to poke at it before
configuring anything: `h3ir controls` and `h3ir budget --seconds 10`.

Every setting, with the reason for each default, is in [`.env.example`](.env.example). This is
version 0.1.0 and it still moves, so pin a commit if you build on it.

## Your first brief

This is the exact command that produced the right-hand side of the first video, and `ref1.png` ships
in the repo, so you can run it now.

```console
$ h3ir compile "she walks out onto the wet gantry in the rain and stops when she sees the city below" \
    --seconds 10 --image h3ir/golden/assets/ref1.png

mode=ref2va  tokens=708  timings={…}
==========================================================================
ref2va IR
  -> PASS (with warnings)   0 error(s), 2 warning(s), 0 info
==========================================================================
  [WARN] P2-too-short: detailed_description is 265 words; spec guidance 350-500, official example 336
  [WARN] R15-wardrobe-not-restated: [Shot 2] names the subject but not the garments (jacket, shirt,
         t-shirt); wardrobe drifts between shots when it is only stated once

subject_definitions:
<Subject 1> is the woman in <Picture 1>, with short dark hair with shaved sides and a small top knot,
dark complexion, black tactical jacket with shoulder straps and buckles, black t-shirt, black cargo
trousers, black lace-up combat boots, slender build.
[…]
detailed_description:
The target video is in a cinematic, high-contrast style with realistic 3D character design, featuring
cool blue tones and wet, reflective surfaces.
[Shot 1] A medium-long tracking shot follows <Subject 1> from behind as she walks out onto a wet,
metallic gantry in the rain. The camera tracks slowly with small amplitude, keeping her centered in
the frame as she moves away from the viewer. […]
[Shot 2] At 00:05.000, the shot cuts to a close-up of <Subject 1> from a slightly low angle as she
stops at the edge of the gantry. The camera is static, focusing on her face and upper body. She looks
down, her expression shifting to one of quiet contemplation as she sees the city below. […]
```

A real run, cut at `[…]`. Nobody typed `<Subject 1>`, `<Picture 1>`, `00:05.000`, or any section
name. One image path went in with no description of what was in it, and the tactical jacket, the
shaved sides and the combat boots were read off the pixels.

Both findings are warnings rather than errors, so it compiled. The second one is the interesting
kind: Shot 2 names the woman but not her clothes, which is the exact omission that lets wardrobe
drift between cuts. No legality check can see that, so it is a named rule with a reason attached.

## Your dialogue ships exactly as you typed it

```bash
h3ir compile "two engineers argue in a server room while an alarm blinks" --seconds 10 \
  --say "The backup never ran, Mei." \
  --say "Then we tell them tonight."
```

From what came back:

```
[…] The camera holds a static shot as the woman with a sharp, urgent voice (S1) says:
<d>[English] The backup never ran, Mei.</d> The man turns his head slightly toward her, his
expression serious, and replies with a calm, steady tone (S2): <d>[English] Then we tell them
tonight.</d> The red alarm continues to flash in the background […]
```

Your lines never pass through the writing model. It decides who speaks, casts a voice for each of
them, places the lines in the scene, and the renderer substitutes your words back byte for byte.

## Ask for ten seconds and H3 gives you 10.125

```console
$ h3ir budget --seconds 10
requested 10.0s -> 243 frames = 10.125s (nominal S.SS 10.00)
canvas 1344x768, latent_t 72
video rows 72,576  audio rows 810
ref image at 'match' ~1,008 rows; at 'max' (2048 short edge) ~7,296 rows
an 800-token IR is 1.08% of the pack
```

H3 only makes clips whose frame count fits a fixed grid. There are exactly fifteen legal lengths
between 5.167s and 15.083s, and **only one of them is a whole number of seconds** (8.0s, at 192
frames). Ten is not on the grid, so 243 frames at 10.125s is the closest the model can get.

Ask for a round number and you quietly get something else. It matters the first time you cut to
music, and it matters for every cut time inside the clip, which is why the compiler owns those and
the writing model never picks one.

The same output prices your references. Prompt text is nearly free and attachments are what cost: one
reference image at maximum sizing runs about nine times the cost of an 800-token brief. Write long,
attach few. The arithmetic is in [`docs/design.md`](docs/design.md).

## Attach an image and it picks the mode for you

T2VA, I2VA, FL2VA, L2VA and Ref2VA are decided by what you attached, because the wiring is the only
thing that can decide them correctly. You never pick one, and no screen built on this should ask.

Attach two images and two subjects come back, bound to the labels the runtime will actually emit, each
one carrying its own retention contract and cited in every shot it appears in. If an image is
ambiguous about which of several things in it you care about, say so with
`--image path.png:"the pilot"` instead of leaving it to the vision model.

## Drive it over HTTP

The API is the product and the CLI is one of its clients. No quality-bearing field is reachable only
from a UI, and no path skips the validator.

```bash
h3ir serve --port 8420
curl -s localhost:8420/v1/briefs -H 'content-type: application/json' \
  -d '{"intent":"a lighthouse keeper lights the lamp in a storm","seconds":10}'
```

`intent` is the only required field. Every response comes back in three layers: `presentation` for a
screen to show, `plan` for the creative decisions someone might want to change, and `ir` for whoever
wires the graph. `GET /v1/capabilities` reports the legal durations, aspects and asset limits, so a
caller never hardcodes them.

Under-specification never fails. `{"intent":"make a video of my dog"}` and nothing else comes back
`201` with a complete, zero-error brief: five seconds, widescreen, two shots, all picked for you.
Routes and request shapes: [`docs/calling-the-api.md`](docs/calling-the-api.md).

## What it will not do

- **It does not render.** No sampler, no graph submission, no GPU. It reports which H3 nodes ComfyUI
  has installed; wiring the render is yours.
- **It does not judge whether the writing is good.** It can tell you a shot dropped the wardrobe. It
  cannot tell you the edit is dull.
- **It cannot hear.** There is a vision tower and no audio tower, and a model asked about a waveform
  invents a plausible answer rather than admitting it cannot listen. Audio references are described
  from typed metadata plus a transcript you supply.
- **It does not guarantee a face survives the render.** The brief binds the reference and states what
  must be preserved. Whether the model delivers is a render outcome.
- **It is H3-only, all the way down.** The rules, the frame grid and the section names are H3's.
  Pointing it at another video model would be a rewrite, not a config change.

## How it keeps itself honest

A rule that cannot be made to fire is not a rule, so every one is proved in both directions.

```console
$ h3ir controls
20 controls, 0 failing
```

MiniMax's own published briefs have to validate clean, because a rule that fires on the spec's own
artifact is a wrong rule. That direction has already caught two rules here and demoted them to
guidance. There is one documented exemption, where MiniMax's example omits a camera motion type.

Going the other way, fourteen mutants of that example each carry exactly one defect and each has to
trip a rule by name, out of the eighty-four the validator knows. The whole gate runs in under a second
and needs no model.

Legality is not quality, so `h3ir eval` separately scores six briefs and gates a change against a
stored baseline, because a prompt change can improve one and wreck the other.

```console
$ pytest -q
370 passed in 1.37s
```

No model, no GPU, no network.

## Where to look next

| file | what it is for |
|---|---|
| [`docs/calling-the-api.md`](docs/calling-the-api.md) | driving the service: what it guarantees, what it only attempts, what comes back |
| [`docs/design.md`](docs/design.md) | why every rule exists: what the encoder sees, the cost model, the contract between stages |
| [`docs/build-log.md`](docs/build-log.md) | a dated record of what the build measured, including the positions it reversed |
| [`AGENTS.md`](AGENTS.md) | working on the compiler itself: the rules that are not preferences, and the known gaps |
| [`loras/handpainted-anim-v2/`](loras/handpainted-anim-v2/) | a worked example of the style-LoRA registry format (the weights there are a labelled placeholder) |

## Licence

Apache 2.0. See [LICENSE](LICENSE), and [NOTICE](NOTICE) for what belongs to whom.

**That covers this compiler. It does not cover the model you point it at, and H3's own licence is
more restrictive than you might assume.** Three terms worth knowing before you build on this, because
none of them is guessable:

- **H3 is not licensed for use in the European Union, the United Kingdom, the Republic of Korea or
  the United States of America.** Those are its Excluded Territories, and the grant is worldwide
  except for them. MiniMax invites people there to contact them for a licence.
- A commercial product or service using H3 **shall prominently display "MiniMax H3" in its user
  interface** (section IV.2).
- Commercial products earning **more than 20 million USD a year need separate written authorization**
  from MiniMax first (section IV.1).

Read the [MiniMax H3 Community License Agreement](https://huggingface.co/MiniMaxAI/MiniMax-H3/blob/main/LICENSE)
rather than trusting this summary. Nothing in this repository is a MiniMax work: no model code, no
weights, no checkpoint.
