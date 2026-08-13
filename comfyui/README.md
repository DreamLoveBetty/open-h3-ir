# OpenH3-IR for ComfyUI

Type one sentence. Get a MiniMax H3 job that is ready to sample.

One node writes the brief H3 actually wants, picks the right weights for the job, loads the encoder
and both VAEs, and hands out the model, the conditioning and the latent. There is no text box to
paste into, no resolution picker, no frame-count arithmetic and no row of loaders.

At rest it is a sentence and five widgets. Everything that is not about this shot lives on a node you
only add when you need it.

## What you need

An OpenH3-IR service. Start it from the repo with `h3ir serve`, which listens on port 8420. It needs
`H3IR_LLM_URL` pointing at your own OpenAI-compatible endpoint, and no GPU of its own. The main
[README](../README.md) covers it.

A ComfyUI with the MiniMax H3 nodes, which ship with ComfyUI itself, and H3's model files.

## Install

Copy or link this one directory into `custom_nodes`, then restart ComfyUI.

```bash
git clone https://github.com/ruashots/open-h3-ir.git
cp -r open-h3-ir/comfyui /path/to/ComfyUI/custom_nodes/openh3ir
```

On Windows a junction means a `git pull` updates the node too:

```
mklink /J "C:\ComfyUI\custom_nodes\openh3ir" "C:\path\to\open-h3-ir\comfyui"
```

It adds nothing to ComfyUI's Python. The nodes speak HTTP to the service with the standard library
only, so the compiler's dependencies can never break your install and the service can live on
another machine.

## The five nodes

**H3 from a Sentence** is the one you always add. Search for `h3`, `minimax` or `ref2va` and it comes
up.

The other three are optional and none of them is needed for the node to work.

| Node | When you add it | What it replaces |
| --- | --- | --- |
| **OpenH3-IR Setup** | the service is not on localhost, or you want to pick model files yourself | nine rows about your machine |
| **OpenH3-IR Footage** | you have a reference clip | one node per clip, up to H3's three |
| **OpenH3-IR Sound** | you have reference music, an effect or a voice | seven rows most renders never use |

**OpenH3-IR Show Text** puts a text output on the canvas. Wire `report` into it.

With no Setup node in the graph the service is expected at `127.0.0.1:8420` and the five H3 files are
found by name in your models folders. That is deliberate and it is the reason to leave it out: a
workflow with no Setup node pins no filenames, so it runs on somebody else's disk. A pinned filename
is a workflow that fails on someone else's install.

## The socket you plug into is the job

This is the part worth reading, because it is the difference between a good render and a puzzling one.

A picture in **first frame** is the frame the video starts on. A picture in **picture 1** is something
that should appear in it. Those are two different jobs, they use two different sets of H3 weights, and
they produce two different briefs. So the socket you choose is the answer, and the node tells the
compiler rather than letting it guess.

That matters because guessing can be wrong quietly. Attach one picture with no role and the compiler
may decide it is your opening frame while your graph feeds it as a reference. The brief then describes
a first frame that H3 is never given, the render comes out wrong, and nothing on screen says why. Here
the wiring cannot disagree with the brief, and if the service still reports a different job than the
sockets describe, the node says so in its report and in the console.

| Socket | What it means |
| --- | --- |
| first frame | the video starts on this picture |
| last frame | the video ends on this picture |
| picture 1 … picture 9 | a person, a car, a room. The next socket appears once this one is filled |
| clip 1 … clip 3 | reference footage, from an OpenH3-IR Footage node |
| sound | reference music, an effect or a voice, from an OpenH3-IR Sound node |
| setup | the service address and the model files, from an OpenH3-IR Setup node |

The frame sockets and the picture sockets are different jobs, so filling both is refused before
anything runs rather than after a model call. So is a sound on a frame-anchor job: H3's frame
checkpoint takes no reference audio at all, so the brief would name a clip H3 never receives.

**picture 1** is one-based on purpose. The brief calls it `<Picture 1>`, so the canvas and the brief
say the same words, and the notes box under the sockets needs no explaining: line one describes
picture 1. The frame sockets are visibly outside that count, because they are not called "picture".

## Notes, and the one thing that cannot hear

The picture notes box takes one short line per connected picture, in order. It is never required and
it is often what makes the right subject get described.

Sounds are different, and it is worth knowing why. The service never asks a model what a sound is,
because nothing in the chain can hear and a model asked about a waveform invents a plausible answer
instead of admitting it cannot listen. H3's own tokenizer emits nothing but `<Audio j>: `. So the note
you type beside a sound is the **only** thing that will ever learn what that sound is: timbre, tempo
and instruments belong there. A picture gets looked at. A sound does not.

That is why each sound socket on the Footage and Sound nodes has its own note field rather than one
shared block. A block matched lines by position across three differently named roles, and skipping one
socket silently moved every line onto the wrong sound.

**the words in the voice clip** is a transcript of the recording you attached, not dialogue for your
video. Lines you want spoken go in the sentence on the compile node. Typing words with no voice clip
connected is an error rather than a no-op, because it used to be silently discarded.

## Wiring the graph

Five sockets out, and no loaders anywhere.

| Out | Into |
| --- | --- |
| `model` | your Turbo LoRA, sigma shift, then the guider and scheduler |
| `positive` | the guider's conditioning |
| `latent` | the sampler's latent |
| `vae` | VAE Decode |
| `audio_vae` | VAE Decode Audio |

`prompt` is the brief if you want to read or keep it, and `report` is what happened in plain words.
Feed `report` into **OpenH3-IR Show Text** to see it on the canvas: the job it ran, the real length,
which socket became which picture label, which loader read which file, and every choice it made that
you cannot otherwise check.

What stays on your canvas is what you actually tune: the Turbo LoRA, the sigma shift, the step count,
the sampler, the decode and the save.

### The attachment block is the thing to read

```
attachments
  clip 1 sound   ->  <Audio 1>  ref_video_audio_1  sha256=ce1a96cc9b89
  clip 1         ->  <Video 1>  ref_video_1  fully_preserved  sha256=d4920a666e25
```

Your socket name, the label the brief uses for it, the input slot on H3's own node that it rides, and
the marker the brief asserts about it. The service hashes the same bytes the node wrote, so this is not
a restatement of what the node intended: it is the service's own manifest with your socket names put
back on it. If a label ever lands on the wrong socket, that is where you see it.

## Length lives in one place

There is one `seconds` field. H3 only renders on a 17k+5 frame grid, so it is snapped once and that
one number is used for both the brief and the latent. Ask for 10 seconds and you get 10.125, which
matters the first time you cut to a beat. 8.0 is the only whole second on the grid. A second duration
control somewhere else in the graph is how you render eight seconds of a ten second script, so there
isn't one.

The range is 1.0 to 149.0 seconds, which is wider than H3's trained band of 5.167 to 15.083. Outside
the band a render still happens, untested and slower, and the report says so:

```
length         39 frames, 1.625s at 24 fps
asked for      1.0s, snapped up onto the frame grid
note           1.625s is below H3's trained band, which starts at 124 frames, 5.167s. It still
               renders, and it is untested.
```

## GGUF, and why there is no toggle for it

Pick a `.gguf` file and it loads through ComfyUI-GGUF's loader. Pick a `.safetensors` file and it loads
natively. Both are in the same dropdown, sorted so a checkpoint's two builds sit next to each other,
and the report names the loader that ran.

There is no toggle, on any node, and that is the design rather than an omission. A boolean beside a
filename is two controls describing one fact, and two of its four states are wrong: toggle on with a
`.safetensors` selected, toggle off with a `.gguf` selected. Nothing on the canvas could resolve the
disagreement. The extension already carries the fact, `unet_gguf` is the same folder as
`diffusion_models` seen through an extension filter, and ComfyUI-GGUF's own `CLIPLoaderGGUF` merges the
two lists exactly this way. So GGUF support adds no new input anywhere: the lists you were already
choosing from grow, and if you have no `.gguf` files you never learn the feature exists.

The GGUF entries come only from ComfyUI-GGUF's own registered file lists, never from globbing the
folder, so an install without the pack is never offered a file it cannot load.

The checkpoint and the encoder are chosen independently, because they are separate files with separate
loaders and every combination is legal. Auto-resolution prefers `.safetensors`, since it needs no
third-party pack, and the report says when a GGUF build was there and not used.

## Attachments and the two views of one disk

There is nothing to configure here, but it is worth knowing what the node is doing.

The service opens attachments from a filesystem path. ComfyUI's own location is asked of ComfyUI, so
nobody types it. What cannot be known is how a service on a different view of the same disk spells
that folder: ComfyUI on Windows writes `C:\ComfyUI\temp\ref.png` and a service in WSL or a container
sees those same bytes at `/mnt/c/ComfyUI/temp/ref.png`. So the node offers the plausible spellings in
turn and the service confirms one by actually opening the file. The report says which one worked.

That is a guess that gets checked every run, rather than a guess that gets trusted. If none of them
work the error lists what was tried, and the Setup node's advanced field **ComfyUI as the service sees
it** takes an answer for setups nobody could work out.

If the service is on a genuinely different machine it cannot open ComfyUI's files at all. Text-only
prompts still work, attachments do not, and the node says so instead of failing obscurely.

## What it does not do

It does not sample and it does not save. It produces the model, conditioning and latent; the sampler
you already trust does the rest.

It cannot hear. Sounds are described from what you type plus their metadata.

It takes nine pictures, three clips and three standalone sounds, which are H3's own limits.

The frame sockets and the picture list are mutually exclusive, and the schema cannot express that, so
it is an error message after a queue rather than a greyed-out socket. A small frontend extension in a
`web/` folder could grey the other group when one is connected. Not built.

A per-picture role is not offered. The service also has `environment`, `style` and `storyboard` roles,
but exposing them would need a wrapper node per picture, and a wrapper node means a plain `IMAGE` from
a Load Image node would refuse to connect to the picture list. That is the worst possible first
impression for a node whose whole pitch is that it removes boxes. Write "the empty showroom" in the
notes line instead. The frontend can already grow several inputs per item; the Python side takes one
template input, so this is reachable if that changes.

## When something goes wrong

Read the toast. Every failure names what happened and the next thing to do, and the failures that
look alike are told apart rather than lumped together:

| what happened | what you get |
| --- | --- |
| no service running | the command that starts one, and the node to put another address on |
| service up, your language model down | said as such, so you do not go looking at the graph |
| the attachment could not be found | the paths it tried, and the field that takes an answer |
| the attachment opened and could not be used | the analyser's own words about the file, and no retry, because a different path would fail the same way |
| the service host has no ffmpeg | named as the service machine's problem, not your graph's, and it does not blame your language model even though both are a 503 |
| more references than H3 has sockets | which ceilings, and nothing dropped for you |

Re-queueing an unchanged graph costs nothing. The compiler is seeded, so the same inputs give the same
brief, and the node caches on a hash of its inputs including the pixels and samples of everything
connected, satellite nodes included. Change `brief seed` for a different take on the same sentence. It
is not the sampler's seed.

Occasionally a brief comes back as a fallback rather than a written one, when the writer could not
satisfy the validator in two passes. The report says so plainly instead of passing it off as written.
Re-queue with a different `brief seed`.

## The example graph

`example/openh3ir_ref2va.api.json` is a graph that actually ran, byte for byte as submitted. It
renders 8 seconds at 1344x768 from two reference plates and writes an mp4 with H3's own audio.

It is in ComfyUI's API format, which is what the `/prompt` endpoint accepts, because that is the format
that actually ran. A canvas workflow assembled by hand and never executed can display settings it never
used, so there is not one here.

## Known limits of this machine, not of the pack

Two things could not be proven on the box this was built on, and neither is described as working.

**GGUF is unproven end to end.** There are no `.gguf` files of any kind on that machine:
`UnetLoaderGGUF`'s dropdown is empty and `CLIPLoaderGGUF`'s list is identical to `CLIPLoader`'s, which
is the definitive check because both come from ComfyUI-GGUF's own registered lists. The routing, the
merged lists, the loader names in the report and the refusal when the pack is absent are all unit
tested; no `.gguf` file has ever been loaded through this pack.

**ComfyUI-MiniMax-H3-Turbo cannot run a clip with its soundtrack.** With `ref_video_audios` connected
its adaln patch receives three timestep entries where it expects two and raises. This was confirmed on
ComfyUI's own `MiniMaxH3ReferenceToVideo` node with the same inputs, so it is that accelerator's limit
rather than this pack's. Footage renders fine without the Turbo LoRA, and a clip with no soundtrack
renders with it.
