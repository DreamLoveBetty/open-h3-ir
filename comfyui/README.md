# OpenH3-IR for ComfyUI

Type one sentence. Get a MiniMax H3 job that is ready to sample.

One node writes the brief H3 actually wants, loads the weights the job needs plus the encoder and both
VAEs, and hands out the model, the conditioning and the latent. There is no text box to paste into, no
resolution picker, no frame-count arithmetic and no row of loaders.

Two nodes, then: a sentence and five widgets on one, the five H3 files on the other. Everything else
is a node that stays out of the graph until you need it.

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

**OpenH3-IR Main** is the one you always add, and **OpenH3-IR Setup** is the one it needs: it
carries the service address and the five H3 files to load. Search for `h3`, `minimax` or `ref2va` and
both come up.

The other two are optional and neither is needed for a render.

| Node | When you add it | What it replaces |
| --- | --- | --- |
| **OpenH3-IR Setup** | always, once per graph | the service address and five loader boxes |
| **OpenH3-IR Footage** | you have a reference clip | one node per clip, up to H3's three |
| **OpenH3-IR Sound** | you have reference music, an effect or a voice | seven rows most renders never use |

Wire `report` into ComfyUI's own **Preview as Text** node to read it on the canvas.

## The five files are yours to pick

The Setup node is a picker and nothing else. Each combo lists what your install actually has, in both
formats, and the file you choose is the file that loads. Nothing here searches by name, prefers a
build, or offers an option meaning "work it out".

That is deliberate, and it is worth saying why, because the node used to do the opposite. A filename
tells you what a file is called. It does not tell you which of two H3 checkpoints you meant, or which
of three encoders you keep for H3, or which build you want today. Answering that question from the
name means the render used a file the canvas never showed, and the one thing this pack will not do is
choose for you quietly. So the pick is on the node where you can read it, changing it is one click,
and the `report` output names every file that was loaded and the loader that read it.

Two of those files are easy to swap, because H3 ships two checkpoints and the socket you filled
decides which one this job needs: `ref2va` for reference and text jobs, `fl2va` for a first or last
frame. Both load happily in either slot, so if the filename says one family and the graph is the
other, the report says so in plain words and the render still happens:

```
weights        minimax_h3_fl2va_pruned_int8_convrot.safetensors  via UNETLoader
WARNING        minimax_h3_fl2va_pruned_int8_convrot.safetensors names H3's fl2va family, and
               this graph is a reference or text job, which runs on the ref2va checkpoint.
               Check the reference weights field on the Setup node: it will render either way,
               and it will be wrong in a way nothing on screen explains.
```

It is read from the filename and only where the filename decides the question. A file whose name says
neither family, or both, gets no warning: a renamed file is not evidence of a mistake, and a warning
that fires on no evidence is one people learn to ignore.

Because nothing invents the five files, a graph with no Setup node has nothing to load and says so
before it writes a file or calls anything:

```
Required input is missing: setup
```

That is ComfyUI refusing the graph at validation. Queue one with the socket connected to nothing and
the node says it in its own words: add an OpenH3-IR Setup node, pick the five files, wire it in.

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
| storyboard | a sketch showing how the shots are laid out. It plans the shots and never appears in the video |
| clip 1 … clip 3 | reference footage, from an OpenH3-IR Footage node |
| sound | reference music, an effect or a voice, from an OpenH3-IR Sound node |
| setup | the service address and the five model files, from an OpenH3-IR Setup node. Required |

The frame sockets and the picture sockets are different jobs, so filling both is refused before
anything runs rather than after a model call. So is a sound on a frame-anchor job: H3's frame
checkpoint takes no reference audio at all, so the brief would name a clip H3 never receives. A
storyboard on a frame-anchor job is refused for the same reason: the frame checkpoint takes no
reference picture, so the brief would lay the shots out from a board H3 never sees.

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
video. Lines you want spoken go in the spoken lines box on the compile node, or quoted in its
sentence. Typing words with no voice clip connected is an error rather than a no-op, because it used
to be silently discarded.

## Exact spoken lines

The sentence can carry dialogue, and the writer may reshape it. The **spoken lines** box on the
compile node cannot be reshaped: one line per spoken line, and each comes back in the brief word for
word and mark for mark, because a brief that rewords one is refused. **spoken in** names their
language, which becomes the tag H3 reads, so Spanish words tagged English are spoken wrong. Who
speaks, and whether a line is heard off screen, still belong in the sentence. An empty box asks for
nothing.

## What an attached music track is for

One track can mean three different things, and only you know which, so the Sound node's **what it is
for** asks: **play this track** puts the recording itself in the video as its score. **match its
style** asks for new music that sounds like it, and nothing of the recording is used. **cut to its
beat** times the cuts and the action to its rhythm, and nothing of the recording is used. The books
follow the choice: the first claims a copy, the other two claim a reference, and the wrong one has
the brief promise H3 that your file is the finished soundtrack.

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
Feed `report` into ComfyUI's own **Preview as Text** to see it on the canvas: the job it ran, the real length,
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
loaders and every combination is legal: a GGUF encoder works with safetensors weights and the other
way round. Neither build is preferred over the other. Both sit in the same list and the one you pick
is the one that loads.

## Attachments and the two views of one disk

There is nothing to configure here, but it is worth knowing what the node is doing.

The service opens attachments from a filesystem path. ComfyUI's own location is asked of ComfyUI, so
nobody types it. What cannot be known is how a service on a different view of the same disk spells
that folder: ComfyUI on Windows writes `C:\ComfyUI\temp\ref.png` and a service in WSL or a container
sees those same bytes at `/mnt/c/ComfyUI/temp/ref.png`. So the node offers the plausible spellings in
turn and the service confirms one by actually opening the file. The report says which one worked.

That is a guess that gets checked every run, rather than a guess that gets trusted. If none of them
work the error lists every spelling it tried.

There is no box to type a path into, because there was nothing useful to type in it: every spelling
that can work is a spelling of a folder ComfyUI already named. What is left when none of them opens is
a service that cannot reach ComfyUI's disk at all. If it runs beside ComfyUI, give it read access to
that folder. If it is on a genuinely different machine it cannot open those files under any spelling.
Text-only prompts still work, attachments do not, and the node says so instead of failing obscurely.

## What it does not do

It does not sample and it does not save. It produces the model, conditioning and latent; the sampler
you already trust does the rest.

It cannot hear. Sounds are described from what you type plus their metadata.

It takes nine pictures, three clips and three standalone sounds, which are H3's own limits.

The frame sockets and the picture list are mutually exclusive, and the schema cannot express that, so
it is an error message after a queue rather than a greyed-out socket. A small frontend extension in a
`web/` folder could grey the other group when one is connected. Not built.

A per-picture role is not offered. The service also has `environment` and `style` roles, but
exposing them would need a wrapper node per picture, and a wrapper node means a plain `IMAGE` from a
Load Image node would refuse to connect to the picture list. That is the worst possible first
impression for a node whose whole pitch is that it removes boxes. Write "the empty showroom" in the
notes line instead. The storyboard role earned its own socket because a staging sketch is a different
job, not a different description: a picture that must never appear in the video cannot ride a socket
that means "put this in the video". The frontend can already grow several inputs per item; the Python
side takes one template input, so per-picture roles stay reachable if that changes.

## When something goes wrong

Read the toast. Every failure names what happened and the next thing to do, and the failures that
look alike are told apart rather than lumped together:

| what happened | what you get |
| --- | --- |
| no service running | the command that starts one, and the node to put another address on |
| service up, your language model down | said as such, so you do not go looking at the graph |
| the attachment could not be found | every path it tried, and what to change where the service runs |
| no Setup node, or one wired to nothing | which files to pick and which socket to wire them into |
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

`example/openh3ir_main.api.json` is a graph that actually ran, byte for byte as submitted. It
renders 8 seconds at 1344x768 from two reference plates and writes an mp4 with H3's own audio.

Its Setup node holds the five filenames from the machine it ran on, which is what a picked file looks
like when it is written down. Yours will be different, so change them: that is the one thing you have
to do to this graph before it runs anywhere else.

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
