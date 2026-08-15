# Row 5. Reference mode

**The claim.** Pictures dropped as references — one a subject, one an environment — produce the
six-section full-reference document in the guide's order, with each file becoming a labelled,
tracked thing, and a render that preserves both.

**Verdict: green.** Rendered and watched.

## The graph

`row-05-reference-mode.api.json`, byte for byte the executed graph, embedded in the rendered mp4.
Two tray slots: `Man1.jpg` as a subject named `theman` (note: "the man"), the clean showroom as an
environment named `showroom` (note: "the empty showroom he walks into"). The sentence mentions both
by name:

> @theman walks into @showroom and stops on the lit circle on the floor

Settings: 8.0s · 16:9 · balanced · sound on · shots auto · seed 7.

## What came back

All six sections, in the prescribed order: subject_definitions, summary, retention_analysis,
detailed_description, overall_soundscape, non_diegetic_music. The definitions:

> `<Subject 1>` is the man in `<Picture 1>`, with short dark brown hair, brown eyes, light skin
> tone, short stubble beard, white collared shirt, unbuttoned collar, visible neck.
>
> `<Subject 2>` is a spacious, empty interior room with dark grey paneled walls on the left and
> floor-to-ceiling glass windows on the right … in `<Picture 2>` …

The second line matters beyond this row: the environment came back as **one environment subject**,
the exact construct the guide's own example uses — not decomposed into props. That is the tray's
`the setting` role reaching the compiler (row 17 examines this on its own).

The report maps both labels and shows the @-mentions resolving:

```
mode           ref2va
attachments
  theman         ->  <Picture 1>  ref_image_1  fully_preserved  sizing=match
  showroom       ->  <Picture 2>  ref_image_2  fully_preserved  sizing=match
@theman        became 'the man' in the sentence
@showroom      became 'the empty showroom he walks into' in the sentence
```

## The render, verified

1344x768, 192 frames, 8.000s, with audio (room tone, footsteps on the polished tiles, a restrained
synth swell — as the soundscape sections wrote). Frames against the sources: the showroom is
preserved to the fixture — ring light, circular stage with orange base glow, dark panels left,
glass and skyline right — and the man enters in the white collared shirt, walks the room, and
faces camera at the end with the portrait's dark hair and stubble.

## Reproduce

Drag the rendered mp4 (or the api.json) onto the canvas and press Run.
