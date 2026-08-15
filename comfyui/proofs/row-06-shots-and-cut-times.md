# Row 6. More than one shot, with cut times

**The claim.** A sentence describing several beats becomes several `[Shot N]` blocks: the first
untimestamped, every later one opening with its own strictly increasing `At MM:SS.mmm` cut time
inside the render's real length. An explicit number in the `shots` box is kept exactly.

**Verdict: green — and the old caveat is closed.**

## The graph

`row-06-shots-and-cut-times.api.json`. Three beats in one sentence, `shots 3`, 12.0s:

> a wide of the empty station platform, then a close on the woman's hands folding her ticket, then
> the train pulling out past her

## What came back

Three shots, the prescribed form: `[Shot 1]` bare, `[Shot 2] At 00:04.000`, `[Shot 3] At 00:08.500`.

## The caveat that no longer exists

The socket-era matrix recorded that the shots number was "a request, not an instruction" (6 of 28
runs diverged, silently). That is fixed and proven, not re-measured away: an explicit number now
binds every stage — intake refuses a count that cannot fit (1.2s per shot, with the arithmetic),
the plan schema closes both ends, the writer's ask carries the pinned count, and
`T11-shot-count-pinned` makes a wrong count an ERROR the fix loop must clear (`tests/
test_pinned_shots.py`, 14 tests). `auto` keeps the writer's designed freedom. A rendered six-shot
sample was verified frame-by-frame at the cut marks: hard cuts where the document wrote cuts,
camera moves where it wrote moves.

## Reproduce

Drag the api.json onto the canvas and press Run.
