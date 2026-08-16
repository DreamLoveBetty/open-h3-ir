# OpenH3-IR

Open-source local Context-IR for MiniMax H3.

[![tests](https://github.com/ruashots/open-h3-ir/actions/workflows/ci.yml/badge.svg)](https://github.com/ruashots/open-h3-ir/actions/workflows/ci.yml)

**Type one sentence. Get better video out of MiniMax H3.**

![A man sandboarding down a dune with a giant white dragon running alongside him, ending on the title OpenH3-IR](docs/media/openh3ir-title.webp)

*That title card was made by the workflow that ships in this repo: plain prose in, three named
reference pictures, and H3 wrote the score in the same pass as the picture.* **Watch it with sound:**
[openh3ir-title.mp4](docs/media/openh3ir-title.mp4).

## What this is

H3 does not want a prompt. It wants a structured document: named sections in a fixed order, every
subject bound to a numbered picture label, cut times that land on a legal frame grid. That document is
what MiniMax calls the Context-IR, and writing it is the whole job here.

MiniMax open-sourced the model but not the stage that writes that document, saying only that
["H3-Context-IR is critical to the quality of the final output"](https://huggingface.co/MiniMaxAI/MiniMax-H3)
and that you should call their hosted service for it. This is an independent open implementation of
that missing layer, running on your own machine, with a dial on top of it.

It talks to any OpenAI-compatible endpoint you already have up. Ollama, llama.cpp's server, LM Studio
and vLLM all speak that API, so if you already run local models there is nothing new to stand up. The
compiler needs no GPU of its own, because the weights live at the endpoint, and nothing here ever
calls MiniMax.

Three ways to reach it, and none of them is the poor relation:

- **In ComfyUI**, three nodes and a workflow that ships ready to run.
- **Over HTTP**, one API for an application to call.
- **From the command line**, for trying things out and for scripting.

One thing worth saying plainly: this is a young project, built because I need it for another
application I am making, which is why it is shaped the way it is. Expect changes as I go, and pin a
commit if you build on it.

## The difference, a clip of something vs a performance

![The same request, sent raw on the left and compiled on the right](docs/media/off-vs-on.webp)

*Same model, same seed, same reference image. The only difference is the words.*

Both halves are the same request: *"she walks out onto the wet gantry in the rain and stops when she
sees the city below."* On the left the sentence goes to H3 as typed. On the right it goes through
`h3ir` first. Nothing else moved between the two runs: same reference image, same seed, same 10.125
seconds, same settings.

The right side does what the sentence asked. She walks out along the gantry, and at five seconds it
cuts to a low-angle close-up of her looking down at the city.

The left side is a good-looking clip that never arrives. It cannot decide where she is going, walking
toward camera for the first half and away from it in the second. Nothing on that side is badly rendered, and that is the point:
the model was fine, the words were the problem.

That is one pair, but it is the pattern I keep seeing. Run the same sentence again and again at flat
defaults, dial untouched, and the character and the ambience come back the same either way, while the
compiled side keeps arriving with more direction in it: sometimes mild, sometimes a lot, never
overdone. The difference I care about is the one between a clip of the thing and a clip of the thing
that actually means something.

**Watch it with sound:** [off-vs-on.mp4](docs/media/off-vs-on.mp4). H3 generates the rain and the
score in the same pass as the picture, and GitHub cannot play a repo-hosted mp4 inline, so the
animation above is the silent version and the file is the one with audio. The brief that produced the
right half is committed beside it:
[`off-vs-on.compiled-brief.txt`](docs/media/off-vs-on.compiled-brief.txt).

## In ComfyUI: three nodes

![The three OpenH3-IR nodes on a ComfyUI canvas, tray holding three named pictures, wired to a box called Render and a save that is playing the finished title card](docs/media/comfyui-base-workflow.png)

- **OpenH3-IR Main** takes the sentence and hands the render everything it needs to run.
- **OpenH3-IR Media** is the tray: every picture, clip and sound the piece uses, on one panel.
- **OpenH3-IR Setup** holds the service address and the five H3 files to load.

The workflow in the picture ships with the pack:
[`comfyui/example/openh3ir_base_workflow.json`](comfyui/example/openh3ir_base_workflow.json). Seven
boxes on the canvas and that is all of it: those three, one called **Render** with the rendering
machinery folded up inside it, one that saves the video, and two panels showing the brief that got
written and the report of what happened. Nothing in it is set up to be fast or clever, so what comes
out is H3 as it ships.

That is the same workflow making the title card at the top of this page, caught with the finished clip
playing in the save box. The picture is worth reading, because nearly everything the rest of this
section explains is visible in it. The tray holds three named pictures: `@dragon` and `@man` as things
the shot should contain, and `@desert` set to *a style to copy* with the note "a lonely anime desert"
typed under it. The prose on Main mentions all three by name and asks for the title in words. The knobs
are at 21:9, invention `extreme`, five shots and 1.5 megapixels. The two panels along the bottom are
the brief that came back and the report of what happened.

### Quick start

```bash
git clone https://github.com/ruashots/open-h3-ir.git
cd open-h3-ir
python3 -m venv .venv && . .venv/bin/activate
pip install -e .

export H3IR_LLM_URL=http://your-endpoint:8000/v1   # your own OpenAI-compatible endpoint
h3ir doctor                                        # says what is actually answering
cp -r comfyui /path/to/ComfyUI/custom_nodes/openh3ir
h3ir serve --port 8420                             # keeps running while you work
```

Restart ComfyUI and open the workflow. On Windows a junction means a `git pull` updates the pack too:

```
mklink /J "C:\ComfyUI\custom_nodes\openh3ir" "C:\path\to\open-h3-ir\comfyui"
```

**Point Setup at your own five H3 files before you run it.** The shipped workflow carries the
filenames from the machine it was built on, and yours will be named differently. Each field lists what
is actually on your disk, and the file you choose is the file that loads: no search by name, no
preferred build, no option meaning "work it out". The report then names every file that was opened.

The pack adds no packages to ComfyUI's Python. The nodes speak HTTP to `h3ir serve` with the standard
library alone, so the compiler's dependencies can never break a ComfyUI install and the service is
free to sit on another machine. Besides that service, the pack needs what any H3 render needs: a
ComfyUI with the MiniMax H3 nodes, which ship with ComfyUI itself, and H3's model files on disk.

### The sentence points at the tray

The prompt on Main is ordinary prose, and `@` is how it points at a file:

> *@carguy prowls across @showroom and stops under the ring light, and an unseen announcer
> @speaks("Nothing on this floor moves like it.")*

A mention becomes that slot's own description in the document, so the compiler never has to guess
which words mean which file. Whatever sits inside `@speaks("...")` comes back in the brief word for
word and mark for mark, because a brief that rewords a locked line is refused and rewritten. A mention
that names no slot is refused on the canvas, listing the names that do exist, before any model call is
spent. That is the whole syntax: mentions, locked lines, prose, nothing else.

### Media has meaning

Every slot in the tray carries a name, a line about it, and one choice that no amount of wiring could
express: what the file *is* to the piece.

| kind | what it can be |
| --- | --- |
| picture | something in the shot · the setting · a style to copy · first frame · last frame · storyboard |
| clip | copy what is in it · copy how it is shot · edit it · carry on from it |
| sound | play it · match its style · cut to its beat · sound effect · voice to match |

Those choices decide the document mechanically rather than by persuasion. A clip set to *edit it*
produces an editing brief whatever the sentence says, and a track set to *match its style* can never
be claimed as copied. The line you type matters most for sound: nothing in this chain can hear, so it
is the only thing that will ever know what a track sounds like.

Some combinations stay impossible, and the nodes say so instead of rendering something wrong. A
picture that *is* the first frame of the video and a picture that is merely something the shot should
contain are two different jobs, and H3 released a separate model for each. The frame one accepts no
references at all, so setting one slot to *first frame* while another slot holds a reference is two
jobs at once. That is refused on the canvas, in a full sentence naming both slots, before a file is
written or the writing model is called.

Every node, every widget, every failure message and the wiring for building your own graph:
[`comfyui/README.md`](comfyui/README.md).

## A dial, for how far it goes

![the same request at restrained on the left and extreme on the right](docs/media/dial-restrained-vs-extreme.webp)

*"the car rolls into the showroom and stops under the lights."* Run twice, changing one flag.

`restrained` stays on the car and keeps its hands still: one slow low-angle track, one cut at six
seconds to a held medium shot, no music, and the room never really revealed. `extreme` turns the same
sentence into a car commercial. It opens wide on the empty showroom, cuts at three and a half seconds
to a close-up panning along the front wheel, finishes on a low-angle push-in, and puts a score under
all of it. Two shots became three, and the camera stopped being polite.

Both reference plates are committed, so this runs as written:

```bash
h3ir compile "the car rolls into the showroom and stops under the lights" \
  --image docs/media/plate-car.jpg \
  --image docs/media/plate-showroom.jpg \
  --seconds 10 --creativity extreme
```

Swap `extreme` for `restrained` and you get the left half. Four positions in all: `restrained`,
`balanced` (the default), `bold`, `extreme`. What changes is how much the writer may introduce that
you never asked for, and an explicit "no dialogue" at `extreme` still means no dialogue.

**Watch it with sound:** [dial-restrained-vs-extreme.mp4](docs/media/dial-restrained-vs-extreme.mp4).
Both briefs are committed too, so you can read exactly what the flag did:
[restrained](docs/media/dial-restrained.brief.txt) and
[extreme](docs/media/dial-extreme.brief.txt).

## Or call it from anything

The API is the product and the other two doors are its clients. No field that affects the output is
reachable from only one of them, and no path skips the validator. The install is the one in the
[quick start](#quick-start) above, minus the line that copies the pack into ComfyUI.

```bash
h3ir serve --port 8420
curl -s localhost:8420/v1/briefs -H 'content-type: application/json' \
  -d '{"intent":"a lighthouse keeper lights the lamp in a storm","seconds":10}'
```

`intent` is the only required field. Every response comes back in three layers, so a screen never has
to read a format it does not care about: `presentation` is plain language for showing a person, `plan`
is the creative decisions someone might want to change, and `ir` is the document plus the manifest for
whoever wires the render. `GET /v1/capabilities` reports the legal durations, aspects and asset limits,
so a caller never hardcodes them.

Under-specification never fails. `{"intent":"make a video of my dog"}` and nothing else comes back
`201` with a complete, zero-error brief: five seconds, widescreen, the edit and the sound picked for
you. Routes, request shapes, and what the service guarantees against what it only attempts:
[`docs/calling-the-api.md`](docs/calling-the-api.md).

## Why this is a compiler, not a prompt enhancer

A prompt enhancer makes your words prettier and hopes. Every row below is a place where hoping is not
good enough, because the answer is either mechanically right or the render is wrong.

| what goes wrong when words are all you have | what happens here instead |
| --- | --- |
| A reference is described in prose and nothing ties that description to the actual file | Every attachment gets its own numbered label, and the label in the document is the one the render wires |
| You have to know which of H3's tasks you are asking for | The job is derived from what you attached, never from what you typed, so no screen has to ask |
| The duration gets rounded once for the words and again for the render | The length is snapped onto H3's frame grid once and that one number is used for both |
| Cut times land past the end of the clip, or so close together the cut reads as a glitch | Every cut time is checked against the real length of the clip and against the 1.2 seconds a shot needs to hold |
| Your exact line comes back paraphrased | Dialogue never passes through the writing model, and a brief that reworded a locked line is refused |
| Nothing states what has to stay the same about a reference | Each one carries a stated retention in the document, and that statement is validated |
| A model that writes a broken document is simply asked to try again | What is mechanical is corrected in place, what needs judgement is reported, and a document that still fails falls back to a deterministic draft |
| Every front end reimplements the rules slightly differently | One compiler behind all three doors, and no path around the validator |

## Ten seconds is not ten seconds

```console
$ h3ir budget --seconds 10
requested 10.0s -> 243 frames = 10.125s (nominal S.SS 10.13)
[…]
```

H3 only makes clips whose frame count fits a fixed grid. Inside the range the model was trained on,
5.167s to 15.083s, there are exactly fifteen legal lengths, and **only one of them is a whole number
of seconds** (8.0s, at 192 frames). Ten is not on the grid, so 243 frames at 10.125s is the closest
the model can get.

Ask for a round number and you quietly get something else. It matters the first time you cut to music,
and it matters for every cut time inside the clip, which is why the compiler owns those and the writing
model never picks one.

That trained range is a note rather than a wall. Ask for a length outside it and it still renders, and
the report says so plainly instead of the surface pretending the option does not exist.

The lines cut off above price your references, which is the other thing that command is for. Words are
nearly free and attachments are what cost: one reference image at its full size costs roughly ten times
what the entire written brief does. Write long, attach few. The arithmetic is in
[`docs/design.md`](docs/design.md).

## References decide the job

Attach two images and two subjects come back, each with its own numbered label, its own stated promise
about what has to stay the same about it, and a mention in every shot it appears in. If an image is
ambiguous about which of several things in it you care about, `--image path.png:"the pilot"` says which,
straight to the model that looks at it. In ComfyUI the same hint is the slot's own line about the file.

H3 does not have one mode, it has five, and each wants the document written differently. Which one a
request needs is settled by what you attached, because that is the only thing that can settle it
correctly. You never pick one and no screen built on this should ask. The names show up in the report
if you are curious: `t2va`, `i2va`, `fl2va`, `l2va`, `ref2va`.

## Exact dialogue stays exact

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
them, places the lines in the scene, and the renderer substitutes your words back byte for byte. In
ComfyUI the same guarantee is `@speaks("...")` inside the sentence.

## It validates what it writes

More than a hundred named rules, and a rule that cannot be made to fire is not a rule, so every one is
proved in both directions.

```console
$ h3ir controls
  [ok  ] MUST PASS: MiniMax official Ref2VA example (P5 exempt, see note)
  [ok  ] EXPECTED: the official example lacks a motion type
  […]
  [ok  ] MUST FAIL: <Image N> instead of <Picture N>
  […]
22 controls, 0 failing
```

MiniMax's own published examples are in the reference set and have to validate clean, because a rule
that fires on the spec's own artifact is a wrong rule. That direction has already caught two rules here
and demoted them to guidance. There is one documented exemption, where MiniMax's example omits a camera
motion type.

Going the other way, fifteen mutants of that example each carry exactly one defect, and each has to
trip the rule that defect earns, by name. The whole gate runs in under a second and needs no model.

```console
$ pytest -q
[…]
899 passed, 2 skipped, 1 warning in 2.96s
```

That suite needs no model, no GPU and no network, which is the point: everything decidable without a
model is decided without one. The two skips are about this machine rather than holes in the suite: one
wants `torch` installed so it can check the ComfyUI file readers against real image data, the other
wants an `ffprobe` that can measure a webp. Run it with `pip install -e ".[dev]"`.

Legality is not quality, so `h3ir eval` measures the writing separately: it scores six briefs and gates
a change against a stored baseline, because a prompt change can improve one and wreck the other.

## Your first brief from the command line

This is the exact command that produced the right-hand side of the comparison up in
[The difference, a clip of something vs a performance](#the-difference-a-clip-of-something-vs-a-performance),
and `ref1.png` ships in the repo, so you can run it now.

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
[…]
```

A real run, cut at `[…]`, which is the mark every printout on this page uses where something was left
out. Nobody typed `<Subject 1>`, `<Picture 1>`, `00:05.000`, or any section name.
One image path went in with no description of what was in it, and the tactical jacket, the shaved sides
and the combat boots were read off the pixels.

Both findings are warnings rather than errors, so it compiled. The second one is the interesting kind:
Shot 2 names the woman but not her clothes, which is the exact omission that lets wardrobe drift
between cuts. No legality check can see that, so it is a named rule with a reason attached.

## What you need

| requirement | why | if you skip it |
| --- | --- | --- |
| Python 3.10, 3.11 or 3.12 | all three are covered by CI, on main and on every pull request | 3.13 is untested rather than known bad |
| An OpenAI-compatible endpoint | this is where the writing happens | nothing compiles, and `h3ir doctor` says so |
| A model that can also look at images | that is how reference pictures get read | text-only prompts still work, references do not |
| `ffmpeg` | reading reference clips, nothing else | only needed if you attach video |

No GPU for the compiler itself: the weights live behind the endpoint. Run `h3ir doctor` before you
debug anything else, because it says what is actually answering: the endpoint, the model it serves, its
context length, whether ComfyUI is reachable and which H3 nodes it has, and a tokenizer self-test. Two
commands need nothing running at all, if you want to poke at it before configuring anything:
`h3ir controls` and `h3ir budget --seconds 10`.

Every brief on this page was written by Qwen3.6 27B, 4-bit, served by vLLM at 262K context on two RTX
3090s, and H3 rendered the videos from those briefs. That is what the project is proven against and the
bar to size your own box against: a 27B-class local model that can also look at images is enough.
`h3ir eval` is there to measure what a different endpoint does to brief quality rather than guess at it.

Every setting, with the reason for each default, is in [`.env.example`](.env.example).

## What OpenH3-IR does not do

- **It does not make the video itself.** It writes the words and hands over everything the render
  needs. Over HTTP that is a brief plus which file belongs where; in ComfyUI it is the wires that feed
  the Render box, and every box inside there is ComfyUI's own rather than ours.
- **It does not judge whether the writing is good.** It can tell you a shot dropped the wardrobe. It
  cannot tell you the edit is dull.
- **It cannot hear.** The model that reads your files can look and cannot listen, and a model asked
  what a piece of music is like will invent a confident answer rather than admit that. So a sound is
  described from the line you type about it, plus its own file details, plus a transcript if you have
  one. The transcript is the channel for words, and you supply the rest.
- **It cannot guarantee H3 obeys every reference.** The brief binds the reference and states what must
  be preserved. Whether the model delivers is a render outcome, and the hardest case is `extreme`,
  which reaches for extreme close-ups.
- **It is deliberately H3-specific.** The rules, the frame grid and the section names are H3's.
  Pointing it at another video model would be a new compiler target, not a config change.

## Where to go next

| file | what it is for |
| --- | --- |
| [`comfyui/README.md`](comfyui/README.md) | **the node pack in full**: every node and widget, the tray, the `@` prompt, the wiring, every failure message |
| [`comfyui/example/openh3ir_base_workflow.json`](comfyui/example/openh3ir_base_workflow.json) | the ready-to-run ComfyUI workflow in the picture above |
| [`HANDOFF.md`](HANDOFF.md) | **installing it and verifying it works**, top to bottom, with a check on every step and what to do when one fails |
| [`AGENTS.md`](AGENTS.md) | **contributing**: the rules that are not preferences, which file owns what, the known gaps |
| [`docs/calling-the-api.md`](docs/calling-the-api.md) | driving the service from an application: what it guarantees, what it only attempts, what comes back |
| [`docs/design.md`](docs/design.md) | why every rule exists: what the encoder sees, the cost model, the contract between stages |
| [`docs/build-log.md`](docs/build-log.md) | a dated record of what the build measured, including the positions it reversed |

## Licence

Apache 2.0. See [LICENSE](LICENSE), and [NOTICE](NOTICE) for what belongs to whom.

**That covers this compiler and this node pack. It does not cover the model you point them at, and
H3's own licence is more restrictive than you might assume.** Three terms worth knowing before you
build on this, because none of them is guessable:

- **H3 is not licensed for use in the European Union, the United Kingdom, the Republic of Korea or
  the United States of America.** Those are its Excluded Territories, and the grant is worldwide
  except for them. MiniMax invites people there to contact them for a licence.
- A commercial product or service using H3 **shall prominently display "MiniMax H3" in its user
  interface** (section IV.2).
- Commercial products earning **more than 20 million USD a year need separate written authorization**
  from MiniMax first (section IV.1).

Read the [MiniMax H3 Community License Agreement](https://huggingface.co/MiniMaxAI/MiniMax-H3/blob/main/LICENSE)
rather than trusting this summary. This project is independent and unofficial: it is not affiliated
with, endorsed by, or supported by MiniMax, and nothing in this repository is a MiniMax work. No model
code, no weights, no checkpoint.
