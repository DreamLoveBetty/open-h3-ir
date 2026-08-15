# Row 13. Words on screen kept exactly

**The claim.** Text quoted in the sentence is the mechanism for lettering: it reaches the document
in straight double quotes, unchanged, outside any dialogue block.

**Verdict: green.**

## The graph

`row-13-words-on-screen.api.json`:

> a hand hangs a wooden sign on the shop door that reads "BACK AT NOON" and straightens it

## What came back

The sign text, letter for letter, in straight double quotes, no dialogue block anywhere in the
document:

> … a wooden sign … reads **"BACK AT NOON"** …

Rendered evidence for lettering on this surface: row 1 v1's video shows its quoted sign ("NO
ENTRY") legible and letter-perfect in frame across the clip.

## A bug this row caught

This graph's first firing crashed the compiler: quoted lettering in the sentence licensed nothing,
so the draft echoing it tripped the proportionality rule at `balanced`. Fixed at the root: a quoted
span in the request is the caller supplying the words — the strongest form of a request — so it is
obedience, not addition, when the brief renders it. Commit d4f4baa.

## Reproduce

Drag the api.json onto the canvas and press Run.
