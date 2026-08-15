# Row 9. Spoken lines kept word for word

**The claim.** A line locked with `@speaks("…")` reaches the document letter for letter inside a
`<d>[Language] …</d>` block, speaker material outside the block, and survives into the rendered
audio.

**Verdict: green.** Document proven here; render proven on row 1's video.

## The graph

`row-09-spoken-lines-verbatim.api.json`. Two locked lines:

> the mechanic wipes her hands and says @speaks("It was never the engine."), and the boy replies
> @speaks("Then what do I owe you?")

## What came back

Both lines, letter for letter, punctuation intact, speakers outside the blocks:

> `<d>[English] It was never the engine.</d>` … `<d>[English] Then what do I owe you?</d>`

The lock is service-enforced: a document that reworded a locked line fails validation and is sent
back. The tray-side grammar (`@speaks` parsing, inner quotes kept, unclosed and empty forms
refused) is pinned by `tests/test_tray.py`.

## Heard, on this surface

Row 1 v1's render carried three locked lines; Whisper (large-v3-turbo) heard all three in order at
sensible times, and row 1 v2's render carries its locked line as the only speech in the clip,
letter for letter. Both mp4s embed their graphs.

## Reproduce

Drag the api.json onto the canvas and press Run.
