# Row 12. A line that crosses a cut

**The claim.** One sung or spoken line that continues across a cut is marked with `<scenetrans>` at
the connecting points, outside the `<d>` blocks, with the continuity stated — reachable from
ordinary words.

**Verdict: green — upgraded twice from the socket era: the marker now arrives without naming the
tag, and it sits outside the dialogue block where the guide keeps it.**

## The graphs

`row-12-a-line-across-a-cut.api.json` asks in ordinary words:

> the singer starts the line @speaks("Hold on to the light, into the night") on her face and the
> same sung line carries on unbroken over the cut to the crowd

`row-12-a-line-across-a-cut-named.api.json` names the tag ("tagged with a scenetrans marker in
both shots").

## What came back

Ordinary words:

> `<d>[English] Hold on to the light, into the night</d>` **`<scenetrans>`** the audio continues
> seamlessly across the cut. [Shot 2] At 00:04.500 … The singer (S1) continues the line:
> `<d>[English] into the night.</d>` `<cutoff>`

Named form: `<scenetrans>` at both connecting points — the guide's textbook both-parts shape.

## Noted

In the ordinary-words run the division overlaps: block one carries the whole locked line and block
two repeats its tail ("into the night"), so the tail would be performed twice. The locked line
itself is intact; the split shape is the wart, recorded for the dialogue-rule family rather than
patched mid-campaign. The `<cutoff>` in that run is the writer's own judgment call at `bold` (the
song runs to the video's end), licensed there.

## Reproduce

Drag either api.json onto the canvas and press Run.
