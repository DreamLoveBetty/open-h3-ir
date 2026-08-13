# OpenH3-IR nodes for ComfyUI

Type one sentence on the canvas and render it with MiniMax H3, without leaving ComfyUI to run a CLI
and paste a brief back into a text box.

The node calls a running OpenH3-IR service, gets back the structured document H3 actually wants, and
outputs it along with the canvas size and a frame count that is already legal. You wire four links
and the graph you already have keeps working.

## What you need

Two things, and neither of them is a new Python dependency.

An OpenH3-IR service. Start it from the repo with `h3ir serve`, which listens on port 8420. It needs
`H3IR_LLM_URL` pointing at your own OpenAI-compatible endpoint, and it needs no GPU of its own. The
main [README](../README.md) covers that setup.

A ComfyUI with the MiniMax H3 nodes, which ship with ComfyUI itself as
`MiniMaxH3ReferenceToVideo` and `MiniMaxH3ImageToVideo`.

## Install

Copy or link this one directory into ComfyUI's `custom_nodes`, then restart ComfyUI.

```bash
git clone https://github.com/ruashots/open-h3-ir.git
cp -r open-h3-ir/comfyui /path/to/ComfyUI/custom_nodes/openh3ir
```

On Windows, a junction avoids the copy so a `git pull` updates the nodes too:

```
mklink /J "C:\ComfyUI\custom_nodes\openh3ir" "C:\path\to\open-h3-ir\comfyui"
```

The nodes appear under `OpenH3-IR`. They add no packages to ComfyUI's Python: the node speaks HTTP to
the service using nothing but the standard library, so the compiler's dependencies can never collide
with ComfyUI's, and the service is free to run on another machine.

## Wiring it up

Take any working H3 graph. Wherever a text box is feeding the H3 node's `prompt`, put
**OpenH3-IR Compile** there instead, and connect four things:

| From the node | To the H3 node |
| --- | --- |
| `prompt` | `prompt` |
| `width` | `width` |
| `height` | `height` |
| `length` | `length` |

Reference images go into `image_1`, `image_2` and so on, in the order you want them numbered. The
first connected socket becomes `<Picture 1>`, which is how a subject in the brief gets bound to a
plate. Feed the same images to the H3 node's own `ref_images` as usual: the compiler reads them to
write about them, and H3 conditions on them to render.

One thing is manual. The H3 node's `ref_image_size` is a dropdown, and ComfyUI cannot drive a dropdown
from a text socket, so the node reports the sizing it used on its `ref_image_size` output and you set
the H3 node to match. The `report` output, viewed through **OpenH3-IR Show Text**, tells you that
along with the mode it inferred and which image became which picture.

### Why wire `length` rather than type a duration

H3 only renders lengths on a 17k+5 frame grid. There are fifteen legal lengths between 5.167 and
15.083 seconds, and exactly one of them is a whole number of seconds. Ask for 10 seconds and you get
10.125, which matters the first time you cut to a beat. Wiring `length` means the number the model
gets and the number the brief was written against are the same number.

## Reference images and the two views of one disk

The service reads reference images from a filesystem path, so it has to be able to open the file the
node writes. When ComfyUI and the service share one view of the disk, this is automatic and you can
ignore the rest of this section.

When they do not, the path is the problem rather than the file. ComfyUI on Windows writes to
`C:\ComfyUI\temp\ref.png`, and a service in WSL or a container is looking at those same bytes through
`/mnt/c/ComfyUI/temp/ref.png`. Both are right and neither program can work out the other's spelling,
so you state it once: put ComfyUI's spelling of a shared folder in `comfy_path_prefix` and the
service's spelling of the same folder in `service_path_prefix`.

If the service runs on a genuinely different machine it cannot open ComfyUI's files at all. Text-only
prompts still work; reference images do not. The node says so rather than failing obscurely.

## The example graph

`example/openh3ir_ref2va.api.json` is the exact graph used to verify this node, byte for byte as
submitted. It compiles a sentence, renders 8 seconds at 1344x768 with two reference plates through the
H3 Turbo path, and writes an mp4 with H3's own audio.

It is in ComfyUI's API format, which is what the `/prompt` endpoint accepts, because that is the
format that was actually executed. A canvas workflow assembled by hand and never run can display
settings it never used, so there is not one here yet. Loading this graph, saving it from the canvas
and committing that file is the small step still outstanding.

## What these nodes do not do

They do not render. No sampler, no graph submission, no GPU. The compile node produces values that
flow into the H3 nodes you already have.

They do not transcribe audio. Nothing in the pipeline can hear, and a model asked about a waveform
invents a plausible answer rather than admitting it cannot listen.

They expose four reference sockets. H3 accepts up to nine, and the service will take nine, so this is
a limit of the node rather than of the model. Four covers the reference work people actually do and
keeps the node readable on a canvas.

## When something goes wrong

Every failure is raised with a sentence saying what happened and what to do next, so read the toast.
The common ones are the service not running, which names the command that starts one; the language
model endpoint being down, which is distinguished from the service being down; and a reference the
service cannot read, which points at the two path fields above.

Re-queueing an unchanged graph does not spend another model call. The compiler is seeded, so the same
inputs give the same brief, and the node caches on a hash of its inputs including the pixels of every
connected image. Change the seed to get a different take on the same sentence.
