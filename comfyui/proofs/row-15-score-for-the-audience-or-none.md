# Row 15. Score for the audience only, or no score

**The claim.** The `silent` switch removes the score and keeps the world's sound: off, the
document writes `non_diegetic_music`; on, that section is `N/A` and `overall_soundscape` stays
filled.

**Verdict: green.**

## The graphs

The same sentence twice — "morning mist drifts through a pine forest as the first light comes
through" — as `row-15-score-for-the-audience-or-none.api.json` (sound on) and
`…-silent.api.json` (`silent: true`).

## What came back

Off: `non_diegetic_music: Sparse, ambient synth pads at a slow tempo, joined by a single,
sustained …`

On: `non_diegetic_music: N/A` — and the ambience stays: the forest's own sound continues in
`overall_soundscape`, exactly what the switch's tooltip promises. The switch also feeds the
validator: with `silent` on, a document that wrote a score anyway would fail (`require_music_na`).

## Reproduce

Drag either api.json onto the canvas and press Run.
