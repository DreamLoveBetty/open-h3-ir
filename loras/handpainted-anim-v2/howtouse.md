---
id: handpainted-anim-v2
name: Hand-Painted Animation
kind: style
target: minimax_h3
h3_variant: [ref2va]
file: handpainted_anim_v2.safetensors
sha256: "0000000000000000000000000000000000000000000000000000000000000000"
version: 2
triggers:
  - text: "hndpntd_anim_v2"
    required: true
    placement: style
    count: 1
strength: {default: 0.8, min: 0.4, max: 1.0}
constrains: {aspect: null, duration_frames: null, steps: null, canvas: null}
conflicts_with: [photoreal-v1]
stacks_with_turbo: unknown
license: "personal use only"
---

## What it's for

Soft hand-painted animation: visible brush texture, watercolour backgrounds with bloomed edges,
warm daylight, gentle character motion with follow-through. Good for pastoral scenes, weather,
food, quiet character moments, anything where the appeal is in the painted surface rather than
in detail density.

## When NOT to use it

Not for anything that needs photographic skin, legible small text, hard mechanical edges, or
fast action — the painted texture smears under speed and the model loses fine geometry. Do not
stack it with a photoreal style LoRA; the two fight and the result reads as neither.

## Strength guidance

0.4–0.6 keeps recognisable faces and adds only the surface treatment. 0.7–0.9 is the intended
look. Above 0.9 backgrounds start to dissolve into wash and thin objects disappear.

## Known failure modes

Small on-screen text becomes unreadable — which matters more here than it would at 2K, because
local output is 768p on the short edge and there is no regeneration stage to recover glyphs.
Hands at rest are fine; hands manipulating small objects lose finger separation.

## Example style openings

Ref2VA, as the first item of the style line:

    The target video is in hndpntd_anim_v2 hand-painted animation style with soft watercolour
    backgrounds and warm afternoon light.
