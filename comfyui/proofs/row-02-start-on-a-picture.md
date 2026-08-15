# Row 2. Start on a picture

**The claim.** A picture dropped on the tray and marked "first frame" makes the video begin exactly
on it: the compiler writes the frame-anchor instruction line the guide prescribes, and the right
checkpoint for a frame job is loaded without being asked.

**Verdict: green.** Document-level proof; the frame-anchor render is row 3's.

## The graph

`row-02-start-on-a-picture.api.json`, byte for byte the executed graph. One tray slot: the black
car plate, role `first frame`, note "the black sports car". The sentence:

> the car rolls forward out of the mist and its headlights come up

Settings: 8.0s · 16:9 · balanced · sound on · shots 1 · seed 7.

## What came back

The document opens with the exact instruction line the first guide prescribes for a first-frame
job, above the sections:

> For the target video, at 0.00 seconds into the target video, `<Picture 1>` (from [Shot 1]) is
> fully referenced.

The body preserves the plate's own facts (carbon-fibre texture, LED headlights, orange underglow)
and stages the asked action from that exact frame. The report:

```
mode           i2va
length         192 frames, 8.000s at 24 fps
attachments
  car            ->  <Picture 1>  ref_image_1  fully_preserved  sizing=match
weights        minimax_h3_fl2va_pruned_int8_convrot.safetensors  via UNETLoader
```

Two things the report says out loud that no socket-era graph could: the tray label is mapped to its
`<Picture 1>` identity and its wiring name, and — because the sentence never wrote `@car` — a note
explains the picture was sent as the first frame for the compiler to place, and that writing `@car`
in the sentence is how to say where it goes.

Picking `first frame` also switched the job to H3's fl2va checkpoint without anyone asking: a frame
job renders wrong on the ref2va weights, and the report names the file it loaded instead.

## Reproduce

Drag the api.json beside this file onto the canvas and press Run. The service must be reachable at
the address on the Setup node.
