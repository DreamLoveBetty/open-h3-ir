# Row 22. An exact frame inside reference mode

**The claim (the guide's).** A picture inside a full-reference document may be a concrete frame.

**Verdict: red — a limit of H3's released weights, and the surface refuses it with the reason
rather than rendering something silently wrong.**

H3's released checkpoints split the two conditionings: fl2va takes frame anchors and no reference
assets; ref2va takes references and no frame anchors. One local pass runs one of them, so "an exact
frame among references" cannot be executed. The tray therefore refuses the combination at the
canvas, before any model call, naming both slots and the consequence:

> this is two different jobs at once. car is set to first frame, which says a picture IS a frame of
> the video, and showroom is set to something in the shot, which says a file is something the shot
> should contain. H3 does one or the other, and its fl2va model takes no reference picture, clip or
> sound at all, so the brief would name your file and H3 would never receive it. Change one of them
> on the OpenH3-IR Media node.

The socket-era matrix proved by direct call that the capability does not exist underneath either:
the same request compiles to a frame job whose document names a picture H3 never receives. The
refusal is the correct behaviour, and `row-22-an-exact-frame-inside-reference-mode.api.json`
reproduces it: drag it in, press Run, and read the message on the node.
