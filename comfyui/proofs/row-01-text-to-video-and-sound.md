# Row 1. Text to video and sound

**The claim.** A sentence typed on the OpenH3-IR Main node, with nothing else — no picture, no
clip, no sound, no Media node in the graph — becomes a rendered video with a real soundtrack:
staging, speech, ambience and score, all from the text.

**Verdict: green.** Rendered, heard, and watched.

## The graph

`row-01-text-to-video-and-sound.api.json` beside this file, byte for byte the graph that was
submitted and rendered. The same graph is embedded in the rendered video itself: drag the mp4 onto
the ComfyUI canvas and the whole wiring appears, runnable. Every class_type and input name in the
embedded copy was checked against the live `/object_info`, and every input value in it matches the
committed file exactly.

The sentence, one spoken line locked with `@speaks`:

> a street musician plays saxophone under a bridge at night while rain pours past the streetlight,
> and a woman walking by stops, listens, and finally says @speaks("You should be famous.")

Settings: 10.0s · 16:9 · bold · sound on · shots auto · seed 7. No media input connected.

## What came back

The document arrived in the three-field form the first guide prescribes for a text job, with no
picture alignment line. The locked line sits in a dialogue block, letter for letter, on the right
speaker:

> The woman (S2), with a warm, clear voice, steps closer and says:
> `<d>[English] You should be famous.</d>`

`integrated_multimodal_description` cast the two people distinctly — the musician in a dark trench
coat (S1), the woman in a red raincoat (S2) — staged her entrance, her stop, the line, and his
pause and grateful smile. `overall_soundscape` wrote the rain, the saxophone's metallic resonance
and the footsteps; `non_diegetic_music` a quiet synth pad under the sax. The report:

```
mode           t2va
length         243 frames, 10.125s at 24 fps
asked for      10.0s, snapped up onto the frame grid
canvas         1344x768
weights        minimax_h3_ref2va_pruned_int8_convrot.safetensors  via UNETLoader
```

The right checkpoint for a text job, said out loud.

## The render, verified

`ffprobe`: h264, 1344x768, exactly 243 frames at 24 fps, 10.125s, stereo AAC. Frame count and
duration match the report to the frame.

**Heard.** Whisper (large-v3-turbo) on the rendered audio: the only speech in the clip is
"You should be famous." — the locked line, letter for letter, nothing added.

**Watched.** Twelve full-resolution frames across the clip, including the last second: the musician
alone under the bridge in the opening, rain past the streetlight on wet pavement, the woman in the
red raincoat entering from the left exactly as written, stopping to listen, and the final frames
holding his pause and small smile toward her — the closing beat the document wrote.

## Reproduce

Drag the rendered mp4 onto the canvas — the graph is inside it — and press Run. The service must be
reachable at the address on the Setup node.
