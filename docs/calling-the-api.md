# Calling the API

This is the document for whoever drives the compiler: an application, a UI, or an agent that knows
nothing about H3. It says what the service promises, what it only attempts, and which of those you
can safely build a screen or a workflow on.

If you are changing the compiler itself, you want [../AGENTS.md](../AGENTS.md) instead. If your caller
is ComfyUI, the client is already written: [../comfyui/README.md](../comfyui/README.md) is the node
pack, and [`../comfyui/h3ir_client.py`](../comfyui/h3ir_client.py) is a worked example of this API
consumed over the standard library alone, with every failure branch below turned into a sentence for a
person to read.

## In one line

You send a plain-language request and some files. You get back a validated H3 brief **and the asset
wiring that brief is true for**. Nothing else in your system has to understand H3's format.

## Routes

| method | path | what it does |
|---|---|---|
| `GET` | `/health` | liveness |
| `GET` | `/v1/capabilities` | legal durations, aspects, asset limits, dialogue languages, output geometry |
| `POST` | `/v1/briefs` | compile. `201` with the brief, `422` if the request cannot be honoured as stated |
| `GET` | `/v1/briefs/{id}` | fetch a compiled brief again |
| `PATCH` | `/v1/briefs/{id}` | refine in plain language: `{"change":"make it darker"}` → `200`, new version |
| `GET` | `/v1/briefs/{id}/prompt` | the prompt text alone |
| `GET` | `/v1/loras` | available styles, by id and prose |

The only required field is `intent`. Everything else has a defensible default.

## Mode selection is never the user's problem

T2VA, I2VA, FL2VA, L2VA and Ref2VA are inferred from what is attached, because the wiring is the
only thing that can decide them correctly. **No screen should ever ask.** It fails safe toward
Ref2VA, and not because Ref2VA is a favourite. It is strictly more expressive than FL2VA, so
choosing it cannot lose a capability the request needed.

## The creativity dial

One control, four named positions, default `balanced`. **A person understands these words; a 0.0 to
1.0 slider does not, which is why it is named rather than numeric.**

| position | what it licenses beyond the request |
|---|---|
| `restrained` | nothing |
| **`balanced`** (default) | a score for the audience |
| `bold` | a score, a spoken line, text visible in the frame |
| `extreme` | the same three, plus every decision played at the far end of what the format supports |

Three things a surface must not get wrong about it:

- **It is content licence, not effort.** A higher setting does not mean more shots or more camera
  moves. It means the writer *may* introduce things the request never mentioned.
- **An explicit prohibition in the request beats every setting.** "No dialogue" at `extreme` still
  means no dialogue.
- **The middle two positions are deliberately soft.** `bold` is a nudge. If it does not visibly
  change an output, that is the design. Do not build a UI that promises a visible difference at
  every step.

## What it guarantees, and is safe to build on

- **The manifest is the contract.** Every label in the brief has an asset behind it, and every asset
  has a label in the brief. An empty manifest means attach nothing.
- **The caller's words are never rewritten.** Dialogue is byte-exact and does not pass through a
  model.
- **Duration lands on H3's frame grid**, and every cut time falls inside the clip.
- **Every section H3 expects is present, in order, and non-empty.**
- **An explicit prohibition is never violated.**
- **You get a valid brief or an error, never a quietly degraded one.** If the writing model is
  unavailable or its output fails verification, the deterministic draft ships and the response says
  so in a field you can read (`source`, `fallback_reason`).
- **Nothing describes audio it has not heard.** No component here can hear. A transcript you supply
  provides the words; you supply the rest.

## What it only attempts, so do not build a promise on these

- **That the writing is good.** The validator has no access to whether a brief is well directed.
- **That length lands in the spec's band.** Reported, never enforced, and in practice briefs come
  out under the band more often than in it. The warning tells you when.
- **That a dial step visibly changes the output.** True at `extreme`, deliberately not guaranteed in
  the middle.
- **That the shot count is anything in particular.** One shot for eight seconds is a legitimate
  answer.
- **That a person's identity survives the render.** The brief binds the reference and states what
  must be preserved; whether the model delivers is a render outcome. The hardest case is `extreme`,
  which reaches for extreme close-ups. **This is the promise most likely to be assumed wrongly by
  someone designing screens.**

## What comes back

Three layers. A UI should read the first two and never the third.

- **`presentation`**: plain language, the request as asked, the setting used, the style, the shots
  with what happens in each, who speaks, the sound. No labels, no markers, no field names, and no
  mode names ever.
- **`findings`**: each severity-tagged. `ERROR` blocks; `WARN` and `INFO` are for display.
- **`ir`**: the brief itself plus the manifest, for whoever wires the render graph.

## Limits worth designing around

- **Audio references need you to describe the sound.** A transcript gives the words only. Timbre,
  delivery and tempo have to be stated, or the reference contributes nothing, and the response says
  so. This matters more than it looks: H3's tokenizer emits `"<Audio j>: "` and no content, so the
  brief's text is the encoder's only channel for what that audio is. An invented timbre is actively
  harmful rather than merely useless, which is why nothing here will invent one.
- **Video references are read from three sampled frames**, at 10/50/90% of the clip, not the whole
  thing. `ffmpeg` and `ffprobe` are hard runtime requirements for video references, not
  conveniences; the analyser raises rather than producing a card it cannot support.
- **A single run is not a measurement.** Nothing about the writing model is deterministic enough
  that one output proves a path is sound.
- **The asset ceilings are the runtime's sockets, not a policy.** Nine images, three videos, three
  standalone audios, and a soundtrack for each of those videos, which is eighteen files at the
  absolute maximum. Over capacity is a `422` naming what to drop, never a manifest that publishes a
  socket the graph does not have. `GET /v1/capabilities` reports all four numbers, so read them rather
  than copying them into your client.
