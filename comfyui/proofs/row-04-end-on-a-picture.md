# Row 4. End on a picture

**The claim.** A single tray slot marked "last frame" makes the video land on that exact picture:
the compiler writes the l2va alignment line and the document invents a plausible earlier state to
arrive from, which is what the guide asks of a last-frame job.

**Verdict: green.** Document-level proof; the landing itself is rendered and watched in row 3.

## The graph

`row-04-end-on-a-picture.api.json`, byte for byte the executed graph. One tray slot: the lit
showroom plate as `last frame`. The sentence:

> the showroom lights come up one by one and the room ends up empty and lit exactly as in the
> picture

Settings: 8.0s · 16:9 · balanced · sound on · shots 1 · seed 7.

## What came back

The mandated alignment line, in l2va's bracketed notation:

> How the reference pictures align with the target video — `<Picture 1>` (from [Shot 1]) aligns
> with the 8.00-second mark of the target video.

And the body does the job's defining move — it invents the earlier state and plays toward the
plate: the room opens **dim**, only the city light through the windows, then the pendant ring
flickers on and the lighting sequence builds to the picture's fully-lit state at the mark.

```
mode           l2va
length         192 frames, 8.000s at 24 fps
attachments
  showroom       ->  <Picture 1>  ref_image_1  fully_preserved  sizing=match
weights        minimax_h3_fl2va_pruned_int8_convrot.safetensors  via UNETLoader
```

The frame checkpoint loaded unasked, and the report's note names where the un-mentioned picture
went (last frame) and how to place it by name (`@showroom`).

## Reproduce

Drag the api.json beside this file onto the canvas and press Run.
