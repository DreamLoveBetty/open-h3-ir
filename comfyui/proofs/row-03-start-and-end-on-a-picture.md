# Row 3. Start and end on a picture

**The claim.** Two tray slots, one marked "first frame" and one "last frame", pin both ends of the
video to those exact pictures: the compiler writes the alignment line the guide mandates, loads the
fl2va checkpoint unasked, and the render actually begins and ends on the plates.

**Verdict: green.** Rendered and watched.

## The graph

`row-03-start-and-end-on-a-picture.api.json`, byte for byte the executed graph, and the same graph
rides inside the rendered mp4 (drag it onto the canvas). Two tray slots: the car plate as
`first frame`, the empty-showroom plate as `last frame`. The sentence:

> the car rolls out of the mist and comes to rest in the middle of the empty showroom

Settings: 10.0s · 16:9 · balanced · sound on · shots 1 · seed 7.

## What came back

The mandated alignment line, above the sections, in the spec's own fl2va notation (base-en.txt 2.1
cites fl2va's pictures bare where i2va and l2va bracket them — the compiler preserves the spec's
inconsistency rather than tidying it, and `grid.py` says so beside the string):

> How the reference pictures align with the target video — Picture 1 (from Shot 1) aligns with the
> 0.00-second mark of the target video; Picture 2 (from Shot 1) aligns with the 10.13-second mark
> of the target video.

10.13 is the spec's S.SS rendering of the true 10.125s length, which the report states in full:

```
mode           fl2va
length         243 frames, 10.125s at 24 fps
asked for      10.0s, snapped up onto the frame grid
attachments
  car            ->  <Picture 1>  ref_image_1  fully_preserved  sizing=match
  showroom       ->  <Picture 2>  ref_image_2  fully_preserved  sizing=match
```

One shot was pinned and one shot came back — the shots contract holding on a frame job.

## The render, verified

1344x768, exactly 243 frames, 10.125s, with audio. Frame 0 against the car plate: same car, same
angle, same mist, same underglow. Frame 242 against the showroom plate: same ring light, same floor
circle, same city windows. Both anchors landed on their marks.

One thing worth knowing that the render teaches: the video ends on an **empty** showroom, because
the last-frame plate is empty. The anchor outranks the sentence — "comes to rest in the middle of
the showroom" happens during the travel, and the final frame is the picture you pinned, exactly.
If the car should be visible at the end, the last-frame plate must contain the car.

## Reproduce

Drag the rendered mp4 (or the api.json) onto the canvas and press Run.
