# Row 10. Singing

**The claim.** Sung words go in a `<d>` block like spoken ones, the singer gets a speaker number,
and the delivery is described outside the block.

**Verdict: green.**

## The graph

`row-10-singing.api.json`:

> the busker sings @speaks("Hold the line, hold the line") and the same sung line keeps going
> without a break while the shot cuts from her face to the crowd watching

## What came back

> she sings with intense focus, her eyes closed, as the camera pushes in … The busker **(S1)
> sings:** `<d>[English] Hold the line, hold the line</d>`

And a detail worth noticing: `non_diegetic_music: N/A` — the busker's song is in the scene, not
laid over it for the audience, and the document keeps the two channels straight.

## Reproduce

Drag the api.json onto the canvas and press Run.
