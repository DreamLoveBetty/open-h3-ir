# OpenH3-IR for ComfyUI

Type one sentence. Get a MiniMax H3 job that is ready to sample.

One node writes the brief H3 actually wants, picks the right weights for the job, loads the encoder
and both VAEs, and hands out the model, the conditioning and the latent. There is no text box to
paste into, no resolution picker, no frame-count arithmetic and no row of loaders.

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

It adds nothing to ComfyUI's Python. The node speaks HTTP to the service with the standard library
only, so the compiler's dependencies can never break your install and the service can live on
another machine.

## The socket you plug into is the job

This is the part worth reading, because it is the difference between a good render and a puzzling one.

A picture in **opening_frame** is the first frame of the video. A picture in **reference_1** is
something the shot should contain. Those are two different jobs, they use two different sets of H3
weights, and they produce two different briefs. So the socket you choose is the answer, and the node
tells the compiler rather than letting it guess.

That matters because guessing can be wrong quietly. Attach one picture with no role and the compiler
may decide it is your opening frame while your graph feeds it as a reference. The brief then describes
a first frame that H3 is never given, the render comes out wrong, and nothing on screen says why. Here
the wiring cannot disagree with the brief, and if the service still reports a different job than the
sockets describe, the node says so in its report and in the console.

| Socket | What it means |
| --- | --- |
| `opening_frame` | the first frame of the video |
| `closing_frame` | the last frame |
| `reference_1` to `reference_4` | things the shot should contain, numbered in order |
| `video_to_edit` | footage this is a change to |
| `video_to_continue` | footage this carries on from |
| `music` | a score to reuse or match |
| `sound_effect` | an effect to reuse or match |
| `voice_to_match` | a voice whose timbre to match |

Frame sockets and reference sockets are different jobs, so filling both is refused before anything
runs rather than after a model call.

`picture_notes` takes one short line per connected picture, in order: the man, the car, the room. It
is never required and it is often what makes the right subject get described. `sound_notes` does the
same for sounds. `spoken_words` is what the voice clip says, and it has to be typed or run through a
real recogniser, because nothing in this chain can hear and a model asked about a waveform invents a
plausible answer.

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
which picture became which, and every model file it loaded.

What stays on your canvas is what you actually tune: the Turbo LoRA, the sigma shift, the step count,
the sampler, the decode and the save.

## Length lives in one place

There is one `seconds` field. H3 only renders on a 17k+5 frame grid, so it is snapped once and that
one number is used for both the brief and the latent. Ask for 10 seconds and you get 10.125, which
matters the first time you cut to a beat. Exactly one whole second exists in the trained range and it
is 8.0. A second duration control somewhere else in the graph is how you render eight seconds of a ten
second script, so there isn't one.

## Reference files and the two views of one disk

The service reads attachments from a filesystem path, so it has to be able to open the file the node
writes. When ComfyUI and the service share one view of the disk this is automatic.

When they do not, the path is the problem rather than the file. ComfyUI on Windows writes
`C:\ComfyUI\temp\ref.png`, and a service in WSL or a container sees those same bytes at
`/mnt/c/ComfyUI/temp/ref.png`. Both are right and neither can work out the other's spelling, so state
it once: `comfy_path_prefix` is ComfyUI's spelling of a shared folder, `service_path_prefix` is the
service's spelling of the same folder.

If the service is on a genuinely different machine it cannot open ComfyUI's files at all. Text-only
prompts still work, attachments do not, and the node says so instead of failing obscurely.

## The example graph

`example/openh3ir_ref2va.api.json` is the graph used to verify this, byte for byte as submitted. It
renders 8 seconds at 1344x768 from two reference plates and writes an mp4 with H3's own audio. Sixteen
nodes, where the same render used to take twenty seven.

It is in ComfyUI's API format, which is what the `/prompt` endpoint accepts, because that is the format
that actually ran. A canvas workflow assembled by hand and never executed can display settings it
never used, so there is not one here yet.

## What it does not do

It does not sample and it does not save. It produces the model, conditioning and latent; the sampler
you already trust does the rest.

It cannot hear. Sounds are described from what you type plus their metadata.

It exposes four picture sockets, two video and three sound. H3 takes nine pictures and three of each
of the others, so the picture limit is the node's rather than the model's.

## When something goes wrong

Read the toast. Every failure names what happened and the next thing to do: the service not running
names the command that starts one, a dead language model endpoint is distinguished from a dead
service, and an unreadable attachment points at the two path fields.

Re-queueing an unchanged graph costs nothing. The compiler is seeded, so the same inputs give the same
brief, and the node caches on a hash of its inputs including the pixels and samples of everything
connected. Change `seed` for a different take on the same sentence. It is not the sampler's seed.

Occasionally a brief comes back as a fallback rather than a written one, when the writer could not
satisfy the validator in two passes. The report says so plainly instead of passing it off as written.
Re-queue with a different `seed`.
