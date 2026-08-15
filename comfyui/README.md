# OpenH3-IR for ComfyUI

Type one sentence. Get a MiniMax H3 job that is ready to sample.

This folder is the ComfyUI half of [OpenH3-IR](../README.md), which is one compiler with two front
doors onto it: these three nodes, and an HTTP service anything else can call. Both doors run the same
service. What the compiler does to a render, shown side by side, is on that page.

One node writes the brief H3 actually wants, loads the weights the job needs plus the encoder and both
VAEs, and hands out the model, the conditioning and the latent. There is no text box to paste into, no
resolution picker, no frame-count arithmetic and no row of loaders.

Three nodes in all: the sentence and its knobs on one, everything the piece looks at or listens to on
the second, the five H3 files on the third. A piece with no media needs only the first and the third.

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

## The three nodes

**OpenH3-IR Main** is the sentence and the knobs. **OpenH3-IR Media** is the tray: everything the
piece looks at or listens to, dropped on one panel. **OpenH3-IR Setup** carries the service address
and the five H3 files. Search for `h3`, `minimax` or `tray` and they come up.

A text-only piece needs Main and Setup. The moment there is a picture, a clip or a sound, add one
Media node and wire its `media` output into Main.

Wire `report` into ComfyUI's own **Preview as Text** node to read what happened on the canvas.

## The knobs on Main

Eight fields, and the first one is the work:

| field | what it decides |
| --- | --- |
| the prompt box | one plain sentence, saying what happens, with `@` for anything in the tray |
| `seconds` | the only length control in the graph, snapped onto H3's frame grid once and used for both the brief and the latent |
| `frame shape` | 16:9, 21:9, 4:3, 1:1, 3:4 or 9:16. The canvas is sized from it, so there is no resolution box to keep in step with anything |
| `invention` | how much the writer may add where your sentence is silent: `restrained`, `balanced`, `bold`, `extreme` |
| `no music` | turns off the score only. Ambient and physical sound are still written, because H3 writes sound in the same pass as the picture |
| `shots` | `auto` leaves the edit to the writer. A number from 1 to 10 is kept exactly, and a count that cannot fit the length is refused with the arithmetic, since every shot needs 1.2 seconds |
| `size, in megapixels` | 0 is H3's native size, 768 on the short edge, which is what it was trained at. A stated size runs from 0.25 to 2.5, and is sharper, slower and hungrier for VRAM in proportion |
| `spoken in` | the language every `@speaks` line is spoken in, which becomes the tag H3 reads. It decides nothing while no line is locked |

Three more sit under advanced and are rarely touched: `reference size`, `brief seed` (the compiler's
seed, not the sampler's) and `writing effort`.

## The tray

Drop files on the OpenH3-IR Media panel, or click it to pick them. Pictures, clips and sounds sort
themselves into their sections. Nine pictures, three clips and three sounds are H3's own per-kind
ceilings; twelve files in all is the tray's, so you cannot fill every slot at once.

Every slot carries three things:

**A name.** Auto-given (`picture1`, `video1`, `audio1`) and yours to change, letters, digits and
dashes. The name is how the prompt refers to the file.

**What it is.** A choice in plain words, defaulting to the ordinary reading:

| Kind | The choices |
| --- | --- |
| picture | something in the shot · the setting · a style to copy · first frame · last frame · storyboard |
| clip | copy what is in it · copy how it is shot · edit it · carry on from it |
| sound | play it · match its style · cut to its beat · sound effect · voice to match |

These decide the brief mechanically rather than by persuasion. A clip set to "edit it" produces an
editing brief whatever the sentence says; a clip set to "copy how it is shot" lends its structure and
is never cited for anything in it; a track set to "match its style" can never be claimed as copied.
First and last frame switch the job to H3's fl2va model, which takes no references at all, so mixing
frames with reference slots is refused before any model call, with the reason.

**A line about it.** Optional for pictures, which get looked at. Nearly essential for sounds, which
do not: nothing in this chain can hear, so the line you type is the only thing that will ever know
what a track sounds like. A sound set to "voice to match" or to "play it" takes one thing more, the
words already spoken inside the recording, since nothing here can hear those either.

A clip with its own soundtrack gets one more choice: **off** sends none of it, **paired** sends it
as that clip's own sound, **alone** sends it as a track in its own right.

The tray's whole state is one ordinary field on the node, so a saved workflow and a rendered video
carry it: drag the mp4 back onto the canvas and the slots come back, names, roles and notes intact.
The files themselves live in ComfyUI's input folder; a workflow opened on another machine names
them and asks you to drop them again.

## The @ prompt

The sentence on Main is plain prose, and `@` is how it points at the tray. Type `@` and a picker
pops up with every slot, thumbnails included; keep typing to filter, Enter to insert.

*"@carguy walks onto the wet gantry and stops when he sees @the-city"*

A mention becomes that slot's description in the document, bound mechanically to the file, so the
compiler never guesses which words mean which picture. A mention that names no slot is refused
before any model call, listing the names that exist. Files you never mention still get used, the
compiler weaves them in, and the report tells you they went unmentioned.

Dialogue that must be said exactly is locked inline:

*"the guard turns and @speaks("The gate stays shut tonight.")"*

Whatever is inside `@speaks("...")` comes back in the brief word for word and mark for mark, because
a brief that rewords it is refused and rewritten. Words merely quoted in the sentence stay free for
signs and flavor, and the writer may polish them. The `spoken in` choice names the language of every
locked line. There is no other syntax: mentions, locked lines, prose, nothing else.

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

Two of those files are easy to swap, because H3 ships two checkpoints and what the tray says its
pictures are decides which one this job needs: `ref2va` for reference and text jobs, `fl2va` for a
first or last frame. Both load happily in either slot, so if the filename says one family and the
graph is the other, the report says so in plain words and the render still happens:

```
weights        minimax_h3_fl2va_pruned_int8_convrot.safetensors  via UNETLoader
WARNING        minimax_h3_fl2va_pruned_int8_convrot.safetensors names H3's fl2va family, and
               this graph is a reference or text job, which runs on the ref2va checkpoint.
               Check the ref2va model field on the Setup node: it will render either way, and
               it will be wrong in a way nothing on screen explains.
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

## Wiring the graph

Setup into Main's `setup`. Media into Main's `media` when there is media. Then the five outputs that
carry the render:

| Out | Into |
| --- | --- |
| `model` | your Turbo LoRA, sigma shift, then the guider and scheduler |
| `positive` | the guider's conditioning |
| `latent` | the sampler's latent |
| `vae` | VAE Decode |
| `audio_vae` | VAE Decode Audio |

`prompt` is the compiled brief if you want to keep it, and `report` is what happened in plain words:
the job it ran, the real length, every file loaded, what each mention became, and which files went
unmentioned. What stays on your canvas is what you actually tune: the LoRAs, the sigma shift, steps,
the sampler, decode and save.

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

It takes nine pictures, three clips and three standalone sounds, which are H3's own limits, and twelve
files in total, which is the tray's.

A picture made elsewhere in the same graph cannot be fed in. The tray holds files rather than tensors,
and that is deliberate: the service opens the attachment from disk and H3 receives the same file
decoded, so a path and a tensor can never end up describing different pictures. The cost is real
enough to name, though. An `IMAGE` coming out of another node has to be saved to disk first and then
dropped on the tray.

Nothing stops you choosing two roles that cannot coexist. Set one picture to first frame while another
slot holds a reference and the panel accepts it; the refusal comes when the graph runs, naming both
slots and the reason, before a file is written or a model call is spent. A panel that greyed out the
choices a filled slot has already ruled out would be better. Not built.

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

`example/openh3ir_tray.api.json` is the first graph that ever rendered through the tray, byte for
byte as submitted: two named pictures and a sound on the tray, a prompt that mentions them with @
and locks one announcer line with @speaks, the full Turbo chain, and a save. Open it, or drag the
video it produced onto the canvas, and the whole thing comes back.

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

## Borrowed technique

The tray panel's widget and upload idioms follow ComfyUI-Fantastic-MiniMaxH3-PromptBuilder (MIT),
and the prompt editor's state handling follows ComfyUI-MiniMaxH3-Easy (MIT). Both are credited here
because reading working frontends beats inventing broken ones.

## Licence

Apache 2.0, like the rest of the repository: [LICENSE](../LICENSE), and [NOTICE](../NOTICE) for what
belongs to whom.

That covers these nodes. It does not cover the model you point them at, and H3's own licence is more
restrictive than most: it excludes four territories outright, it asks a commercial product to display
"MiniMax H3" in its own interface, and above 20 million USD a year it needs written authorization from
MiniMax. The three terms are spelled out in the [main README](../README.md#licence), and MiniMax's
agreement is the thing to actually read.
