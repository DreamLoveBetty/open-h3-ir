# Row 1. Text to video and sound

**The claim.** A sentence typed on the OpenH3-IR Main node, with nothing else — no picture, no
clip, no sound, no Media node in the graph — becomes a rendered video with a real soundtrack:
staging, speech, ambience and score, all from the text.

**Verdict: green.** Rendered, heard, and watched.

## The graph

`row-01-text-to-video-and-sound.api.json` beside this file, byte for byte the graph that was
submitted and rendered. The same graph is embedded in the rendered video itself: drag the mp4 onto
the ComfyUI canvas and the whole wiring appears, runnable. Every class_type and input name in the
embedded copy was checked against the live `/object_info` before this file was written.

The sentence, three spoken lines locked with `@speaks`, one line of on-screen text in plain quotes:

> the courier stops at the guard desk in the rain and says @speaks("The gate stays shut
> tonight."), the guard answers @speaks("Not for me."), and then both of them shout
> @speaks("Move!") together as the barrier light starts flashing under a sign that reads
> "NO ENTRY"

Settings: 10.0s · 16:9 · bold · sound on · shots 3 · seed 7. No media input connected.

## What came back

The document arrived in the three-field form the first guide prescribes for a text job, with no
picture alignment line. All three spoken lines sit in dialogue blocks, letter for letter, each with
a speaker number — S1, S2, then the shared shout (S1,S2):

> `<d>[English] The gate stays shut tonight.</d>` … `<d>[English] Not for me.</d>` …
> `<d>[English] Move!</d>`

`overall_soundscape` wrote the rain and the barrier motor; `non_diegetic_music` wrote a percussive
electronic build synced to the flashing light. The report:

```
mode           t2va
length         243 frames, 10.125s at 24 fps
asked for      10.0s, snapped up onto the frame grid
canvas         1344x768
weights        minimax_h3_ref2va_pruned_int8_convrot.safetensors  via UNETLoader
```

The right checkpoint for a text job, said out loud.

## The render, verified

`ffprobe`: h264, 1344x768, exactly 243 frames at 24 fps, 10.125s, stereo AAC. The frame count and
duration match the report to the frame.

**Heard.** Whisper (large-v3-turbo) on the rendered audio: all three lines are spoken, in order, at
sensible times — line one at 0.0–2.5s, the reply at 4.1–4.8s, the shared shout at 8.9–10.1s. The
performance adds a small lead-in breath-phrase before line one; whether locked lines survive letter
for letter in the *performance* is row 9's measurement, made there.

**Watched.** Twelve full-resolution frames across the clip, including the last second: two men at a
rain-slicked guard desk under heavy rain, the sign reading exactly "NO ENTRY", the barrier light
dark through the dialogue and flashing red from the shout onward, both mouths open on the shared
"Move!", and the final frames pushing in hard onto the flashing light under the sign — the camera
move the document wrote.

## Noted, not row 1's claim

- `shots 3` was asked; the service's plan layer carries three timed shots, and the writer merged
  them into one continuous `[Shot 1]`. This is the shot-count caveat the matrix measures at row 6.
- The "courier" renders as a second uniformed officer; the two men are near-twins. Casting
  divergence from prose is a model-side matter, not a compiler or node failure.

## Reproduce

Drag the rendered mp4 onto the canvas — the graph is inside it — and press Run. The service must be
reachable at the address on the Setup node.
