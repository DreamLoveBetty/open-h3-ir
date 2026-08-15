# Row 19. A picture for a style, or for a pose

**The claim.** A picture marked "a style to copy" lends its look — and only its look: the document
carries the guide's standalone style-and-composition entry, and the plate's contents stay out of
the video. A pose travels as a reference onto another subject.

**Verdict: green — and this row killed two compiler defects to get there.**

## The graph

`row-19-a-picture-for-a-style-or-a-pose.api.json`. One slot: a black-outline gnome line drawing as
`a style to copy`, note "the drawing style only: black outlines on plain white, no shading. Do not
put this gnome in the video." The sentence asks for something else entirely:

> a lighthouse on a cliff in a storm, waves breaking below

## What came back, after the fixes

The construct, standalone, with the aesthetic actually read off the plate:

> `<Picture 1>` is the style and composition reference for the target video, defining a clean,
> flat black-and-white line art aesthetic with bold outlines, no shading, and a plain white
> background.

And the word "gnome" appears **zero** times in the document.

## The two defects this row caught

First firing: the role reached the service (manifest: `style`), the report marked it
`weak_reference` — and the written document still cast the gnome as Subject 1, fully_preserved,
standing in the storm, against the note. The storyboard role had this exact disease and was cured
with a stated fact in the writer's ask plus rule R28; style never got the sibling. It has one now
(`style_facts` + `R29-style-cited-as-content`), and R29's first catch was the deterministic draft
doing the same thing — so the draft now skips a style plate's contents and writes the standalone
line, mirroring the storyboard's draft handling. Commits eedd941 and 1e0006e-family; tests in
`tests/test_style_role.py`.

The pose half is proven in row 18: the dancer plate's stance travels onto the kimono woman as
"`<Picture 2>` is the pose reference for `<Subject 1>`", one woman, not two.

## Reproduce

Drag the api.json onto the canvas and press Run.
