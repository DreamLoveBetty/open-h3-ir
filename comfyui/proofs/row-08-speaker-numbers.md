# Row 8. Speaker numbers, single and shared

**The claim.** Each speaker gets a stable `(SN)` number, and a line two people say together gets
the shared form `(S1,S2)` on one dialogue block.

**Verdict: green — upgraded from the socket era, which never reached the shared form in three
attempts.**

## The graph

`row-08-speaker-numbers.api.json`:

> the two children run to the fence and shout @speaks("Wait for us!") together at the same moment,
> one line said by both voices at once

## What came back

The construct the old matrix could not reach, exactly as the guide writes it:

> The two children **(S1,S2)** shout together, `<d>[English] Wait for us!</d>`

One line, one block, one shared number. Single-speaker stability is proven across this campaign's
other documents (rows 1, 9, 10, 11: S1/S2 assigned once and never drifting between shots).

## A bug this row caught

The first firing of this graph crashed the compiler: the deterministic draft echoed the sentence's
own quoted line and the proportionality rule read it as added lettering (Q2), a false positive
that killed four briefs. Fixed at the root — the caller's own quoted words are never an addition —
with the control kept: invented lettering still fails at `balanced`. Commit d4f4baa.

## Reproduce

Drag the api.json onto the canvas and press Run.
