# Row 11. A voice from off screen

**The claim.** A voiceover line gets its block plus the guide's two required statements: that it is
off-screen, and that the visible person's lips stay closed. Speech the video's end cuts off gets
the `<cutoff>` marker.

**Verdict: green — upgraded: `<cutoff>` now arrives from ordinary words, where the socket era
needed the tag named in the sentence.**

## The graph

`row-11-a-voice-from-off-screen.api.json`:

> over a shot of an empty road a man's voice says off screen @speaks("I still remember that road.")
> while his lips stay closed, and right at the end he starts @speaks("and I never") but the video
> stops before he finishes the sentence

## What came back

All three constructs, from plain words:

> off-screen voiceover: `<d>[English] I still remember that road.</d>` … lips remain completely
> closed.

> `<d>[English] and I never</d>` `<cutoff>`

## Reproduce

Drag the api.json onto the canvas and press Run.
