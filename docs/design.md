# Design: why OpenH3-IR is built this way

This is the design reference for the compiler: what MiniMax H3's conditioning encoder actually
sees, what a reference label costs, the contract between stages, and the grounding for every rule
the validator enforces. It is the document to read before changing a rule, a prompt or a stage
boundary.

Every claim carries its provenance: **[SPEC]** means mandated by MiniMax's published guides or by
the shipped runtime code, **[INFER]** means deduced from the three published Context-IR outputs or
from two sources converging, **[MINE]** means a judgement call that is open to being overturned.
Figures came from live measurement against a running endpoint, not from estimation.

Two things to know before you trust a sentence here. This document was written **before** the
compiler was built, so where it says "will" the code has since decided; and where it disagrees
with the code, **the code wins and this file is the bug**. What the build actually found, including
the positions this document got wrong, is in [build-log.md](build-log.md), where five findings
reversed a decision made here.

## 0. Verdict

**The layer is worth building, and the largest part of the win is not the part the release post
advertises.** Two findings decide the design:

1. **The reference labels are the only binding between the prompt text and the attached assets,
   and they are emitted by the runtime, not by the prompt.** ComfyUI's H3 tokenizer literally
   writes `"<Picture 1>: "` into the token stream immediately before each image's vision block,
   `"<Video 1>: "` before each video's frame blocks, `"<Audio 1>: "` for each audio (label only —
   see §4.1), and then appends the prompt text *after all of them*
   (`comfy/text_encoders/minimax.py:141-186`). A prompt that says `<Image 1>` is addressing a name
   that does not exist in the presentation. The maintainer's working prompt does exactly this. This is
   not a style problem; it is a broken pointer, and it is free to fix.

2. **IR text is nearly free; references are what cost.** H3 is a single-stream packed transformer:
   the IR tokens are concatenated into the *same* sequence as the video latents, audio latents and
   reference latents, and the whole pack runs through every DiT block on every sampling step
   (`comfy/ldm/minimax/model.py:513-644`). Measured: a published-length IR is **0.5–1.6 %** of the
   packed sequence, while one reference image at `ref_image_size=max` is **7,296 rows** and a 5 s
   reference video is **37,296 rows — as much as generating the video itself**. So the correct
   posture is the opposite of prompt-thrift: *write long, precise IR; be ruthless about how many
   assets you attach and at what resolution.*

What I do **not** claim: that hosted-style 700-word verbosity beats a disciplined 400-word IR. That
is unproven and I give a falsifiable test for it (§10, E2). The claim I will defend is that
**structure** — grounded labels, defined subjects, an explicit retention contract, a legal
timeline — is the part that is specified, cheap, and currently absent.

One correction to the brief's framing, and it matters for the build: MiniMax's release note says
*"We add several special tokens, such as `<d>`, to the tokenizer configuration."* **The shipped
tokenizer does not.** H3's own `Ref2VA/tokenizer/tokenizer_config.json` and `tokenizer.json`
contain exactly the same 26 added tokens as stock Qwen2.5 — no `<d>`, `</d>`, `<scenetrans>`,
`<cutoff>` — and H3's `vocab.json` is byte-identical to the one ComfyUI already bundles (git blob
sha1 `4783fe10ac3adce15ac8f358ef5462739852c569` matches the HF etag; FL2VA and Ref2VA tokenizer
configs are the same blob, etag `204d76f7…`). So `<d>` is **literal text** that BPE-splits into
`['<d', '>']`, and ComfyUI's tokenization is already faithful. Consequence for the design: the
markers must be byte-exact — `<D>`, `< d >`, or a typographic bracket produces a different token
sequence and loses whatever `<d>` means to the model. There is no tokenizer patch to write. I went
looking for that bug and it isn't there.

**On the expanded scope** (modes invisible to the user, an API an unskilled agent can drive): these
do not bolt onto the layer, they fall out of it. Mode selection is decided by the wiring and the asset
roles — the two things this layer already owns — so it belongs at the front of the compiler (§12), and
it fails safe because Ref2VA is *strictly more expressive* than FL2VA rather than because I picked a
favourite. And the two callers need no separate treatment, because the design already forbids
caller-supplied structure: the compiler owns labels, numbering, timeline and section order, so a
one-sentence brief from an agent and a fully-specified brief from the UI enter the same pipeline at
the same point (§13). The invariant that makes both true: **there is no quality-bearing field only the
UI can set, and no path that skips the validator.**

**On style LoRAs** (§14): a trigger token is just text in the IR, so it inherits the discipline §1
already establishes — right bytes, right slot, or it silently does nothing at full compute cost. The
spec's per-mode style slot is where it goes, and in base modes it drops into an existing
comma-separated style list without bending the format. One change of framing: the agent should
*discover* triggers but never be *responsible* for typing them, exactly as it never types
`<Picture 1>`. It selects a LoRA by id; the compiler owns the string.

**On the inference host:** verified live, and it overturns the text-only assumption — the model has a working
vision tower (§5), so one model on one host does analysis, planning and prose, with no hybrid split
and no cross-model drift. It also has two silent failure modes I measured rather than guessed (F15,
F16), and they change the build order: the backend wrapper has to be hardened before any stage
depends on it.

---

## 1. What the encoder actually sees (verified, not assumed)

`comfy/text_encoders/minimax.py` builds the token stream by hand. **No chat template, no special
tokens, `add_special_tokens=False`.** The presentation is:

```
t2va    : <prompt>
fl2va   : "<Picture 1>: " <vision> [ "<Picture 2>: " <vision> ] <prompt>
ref2va  : for each attached item, in the runtime's order:
            image -> "<Picture i>: " <vision block>
            audio -> "<Audio j>: "                      (no content enters Qwen)
            video -> "<Video k>: " then, per 2-frame block, "<T.T seconds>" <vision block>
          then <prompt>
```

Conditioning is the **unnormalized hidden state after layer 50** of Qwen3-VL-32B; the on-disk
checkpoint is truncated there (`model.embed_tokens.weight [151936, 5120]`, layers 0–49, no
`lm_head`, no final norm — verified by reading the safetensors header). Text positions carry adaLN
tag 1, vision-pad positions tag 0.

Three consequences that drive everything below.

### 1.1 Two classes of label: grounded and ungrounded  **[SPEC, from runtime]**

| label | grounded? | how it acquires meaning |
|---|---|---|
| `<Picture N>` | **yes** | runtime emits the string immediately before the image's vision block |
| `<Video N>` | **yes** | ditto, before the frame blocks |
| `<Audio N>` | **name only** | runtime emits the label; the audio content never enters Qwen (§4.1) |
| `<Subject N>` | **no** | exists *only* because `subject_definitions` defines it in text |
| `(SN)`, `[Shot N]` | **no** | pure text conventions |

This is the mechanism that makes the six-section Ref2VA format do real work rather than decorate:
`subject_definitions` is the sentence that binds an abstract, reusable identity to one or more
grounded labels, and `retention_analysis` is the sentence that states what must survive. Nothing
else in the pipeline expresses either.

### 1.2 The runtime owns the numbering, so the IR cannot be authored alone  **[SPEC, from runtime]**

`MiniMaxH3ReferenceToVideo.execute` emits in this fixed order
(`comfy_extras/nodes_minimax_h3.py:210-280`): **all ref images**, then **for each ref video: its
paired soundtrack's `<Audio j>` label first, then `<Video k>`**, then **standalone audios**.
Ordinals are 1-based per type in emission order.

The published hosted Ref2VA IR numbers its labels *exactly this way* — `<Audio 1>` = the
synchronized track of `<Video 1>`, `<Audio 2>` = the standalone voice reference. **[INFER, strong:
two independent sources converge]** Hosted Context-IR and the local ComfyUI node agree on the
numbering convention, which means an IR written against the local emission order is also
hosted-compatible.

Therefore: **the compiler's output is not a string. It is an IR document that contains the prompt
*and* the ordered asset→label→wiring manifest**, because a label is only correct relative to a
wiring. Ship them together, hash them together, validate one against the other. This single
decision structurally prevents the `<Image 1>` class of bug — a dangling label becomes a build
error, not a silent quality loss.

### 1.3 IR length is not semantically neutral  **[SPEC, from runtime]**

In `PackedLayout.__init__`, text occupies temporal RoPE positions `0 … text_len-1`, and then
`cursor = float(text_len)` — the reference blocks, keyframe cond rows and the target video all take
their positional origin *after the text*. Changing IR length translates the positional frame of
every conditioning block.

Practical effect: **you cannot A/B two IRs of different lengths and attribute the difference to
wording.** Length is a confound, like a seed. The eval harness in §10 holds token count in a band
when testing wording, and tests length as its own axis.

### 1.4 The eight other MiniMax skills: a clean negative, and it argues *for* this layer

I mined all eight style skills (~3,000 lines, excluding the Chinese twins) for format knowledge the
two guides leave implicit. **They contain none.** Grepping every one of them for
`integrated_multimodal_description`, `overall_soundscape`, `non_diegetic_music`,
`subject_definitions`, `retention_analysis`, `<d>`, `<Picture`, `<Subject`, `(S1)`, `[Shot ` returns
**zero hits outside `h3-prompt-writing` itself**. They are Hub orchestration workflows — shot tables,
palette systems, QC checklists, approval gates.

The one file that looks like it should help, `co-op-game-intro-generator/references/`
`h3-video-prompt-template.md`, is a **Chinese timeline template with `[0秒–2秒]` beat sections**, a
fixed UI event framework and a trailing negative-constraint list. It is not in H3 IR format at all:
no `[Shot N] At MM:SS.mmm`, no reference labels, no section names.

That is informative rather than disappointing. **MiniMax's own production skills emit loose,
mixed-language creative prose and rely on Context-IR to normalise it into IR.** Their house style
*is* the pre-Context-IR side of the pipeline. That is direct evidence, from MiniMax's own shipped
artifacts, for what the closed stage is actually for — loose brief in, strict IR out — and for why a
local pipeline that skips it is feeding H3-Base something the model never saw in training. It also
means an implementer should not spend time mining those eight skills; this section is the result.

---

## 2. The cost model (measured)

Packed-sequence rows at 24 fps on the legal frame grid (`n % 17 == 5`), video rows =
`latent_t × (W/32) × (H/32)`, audio rows = `round(frames/24 × 40) × 2`:

| duration | frames | true seconds | video rows | audio rows | IR=600 tok | IR share |
|---|---|---|---|---|---|---|
| 5 s | 124 | 5.167 | 37,296 | 414 | 38,310 | **1.57 %** |
| 10 s | 243 | 10.125 | 72,576 | 810 | 73,986 | **0.81 %** |
| 15 s | 362 | 15.083 | 107,856 | 1,206 | 109,662 | **0.55 %** |

(1344×768; 9:16 and 1:1 are within 3 % of these.)

Reference cost, **added to every sampling step**:

| asset | rows |
|---|---|
| ref image, `ref_image_size=match` (scaled to the generation's pixel area) | **1,008** |
| ref image, `max` (2048 short edge → 3648×2048) | **7,296** |
| 9 ref images at `max` | **65,664** (1.8× an entire 5 s video) |
| 2 s ref video @1344×768 | **17,136** |
| 5 s ref video | **37,296** |
| 15 s ref video | **107,856** |
| keyframe (fl2va first/last) | 1,008 each |

Measured IR sizes with the exact tokenizer H3 uses (`scratchpad/h3tok.py`, built from ComfyUI's
`qwen25_tokenizer` vocab/merges):

| artifact | total words | main description field | tokens |
|---|---|---|---|
| published T2VA IR | 380 | 249 (2 shots, 10 s) | **537** |
| published I2VA IR | 726 | 533 (1 static shot, 8 s) | **919** |
| published Ref2VA IR | 562 | 238 (1 shot, 5 s, editing) | **803** |
| `base-en.txt` (the base guide) | 2,499 | **3,582** |
| `ref-en.txt` (the Ref2VA guide) | 3,676 | **5,277** |

**Reading the published usage numbers.** T2VA reports `prompt_tokens 5,650`. The base guide is
3,582 tokens and its SKILL.md 493 — so the hosted T2VA call is, to within ~1.5 K of harness and
brief, **the published guide used as a system prompt**. **[INFER]** But `completion_tokens 2,915`
against a 537-token artifact (≈5.4×), and I2VA's `10,022` against 919 (≈11×), mean the completion
count is **not** the emitted IR: the usage is a rollup over a multi-stage workflow with internal
reasoning. Ref2VA's `33,323` prompt tokens likewise exceed both guides (8,859) plus any plausible
single encoding of one 5 s video. **Do not use the hosted numbers as a per-call local budget.**
Separately, the "~100 K distilled to ~4 K" figure in the brief does not match any of the three
published artifacts (537–919 tokens); I have not been able to source it and I do not build on it.

**Authoring cost — measured on the inference host**, `LLM_HOST:8000`,
`Huihui-Qwen3.6-27B-abliterated-AWQ-MTP`, vLLM 0.21.0, 2×3090. All figures from live calls with
thinking disabled:

| what | measured |
|---|---|
| generation throughput | **80–107 tok/s** |
| `ref-en.txt` as system prompt | 5,456 prompt tokens, **3.25 s cold prefill**, ~1.8 s warm (prefix cache active) |
| reference image 1344×768 | **1,024 prompt tokens**, 0.77 s |
| reference image 768×768 / 1536×1536 | 592 / 2,320 tokens |
| 550-word prose pass (718 tok out) | **9.0 s** |
| schema-constrained AssetCard (94 tok out) | **1.0 s** |
| 3 images + cross-image reasoning | 388 prompt tokens, 0.6 s |

A full Ref2VA IR with three references therefore costs roughly **25–40 s**: ~7 s per asset card,
~3 s of guide prefill (cached after the first call), ~11 s of prose. Against H3 sampling times in
minutes, **IR authoring is not the bottleneck and does not need to be cheap.** Nine references at
~1 K tokens each is ~9 K — trivial against the endpoint's 262 K context.

---

## 3. The contract: `IRDocument` v1

The compiler emits one JSON document. `prompt` is a **pure deterministic function** of the rest;
re-rendering the same document must produce a byte-identical string (the validator asserts this).

```jsonc
{
  "ir_version": "1",
  "profile": "h3ir/2026-08-a",              // versioned policy bundle, see §8
  "mode": "t2va|i2va|fl2va|l2va|ref2va",

  "target": {
    "requested_seconds": 10,
    "frames": 243,                          // snapped up to n % 17 == 5
    "effective_seconds": 10.125,            // frames/24 — the ONLY source of S.SS
    "canvas": [1344, 768],
    "fps": 24
  },

  // ORDERED exactly as the runtime emits. Slot order IS the label numbering.
  // `provenance` is present when the app generated the asset (§14.8): a PRIOR for the
  // analyser, never a substitute for describing the actual pixels.
  "manifest": [
    {"slot":0,"label":"<Picture 1>","kind":"image","sha256":"…","wiring":"ref_image_1",
     "px":[1824,1024],"sizing":"max","rows":1824,
     "composition":"bare_plate|composed_scene|unknown",
     "provenance":{"generator":"qwen-image-edit","model":"…","source_prompt":"…",
                   "parent_asset_sha256":"…","edit_instruction":"…","intended_role":"subject"}},
    {"slot":1,"label":"<Audio 1>","kind":"audio","sha256":"…","wiring":"ref_video_audio_1",
     "paired_with":"<Video 1>","seconds":5.0},
    {"slot":2,"label":"<Video 1>","kind":"video","sha256":"…","wiring":"ref_video_1",
     "frames":124,"seconds":5.167,"rows":37296}
  ],

  "subjects": [
    {"label":"<Subject 1>","kind":"person|environment|object|style|action",
     "from":["<Picture 1>"],                // grounded labels this subject is drawn from
     "attributes":["short wavy blonde hair","bright pink suit jacket", …],
     "retention":"fully_preserved|partially_preserved|attribute_transfer|weak_reference",
     "retention_note":"…","appears_in":[1,2]}
  ],

  "speakers": [
    {"id":"(S1)","subject":"<Subject 1>","onscreen":true,"voice_ref":"<Audio 2>",
     "voice":"calm male, measured delivery","first_event":{"shot":1,"order":0}}
  ],

  "shots": [
    {"n":1,"cut_ms":null,                   // shot 1 has no timestamp  [SPEC]
     "framing":"…","camera":{"type":"Push In","amplitude":"small","speed":"slow"},
     "body":"…prose…",
     "dialogue":[{"speaker":"(S1)","language":"English","text":"Follow the wind, live free.",
                  "voiceover":false,"crosses_cut":false,"truncated":false}],
     "onscreen_text":["営業中"]}
  ],

  "audio": {
    "soundscape":"…", "non_diegetic_music":"…|N/A",
    "audio_relations":[{"label":"<Audio 1>","marker":"fully_copy|partially_copy|reference|weak_reference",
                        "note":"…","layer":"soundscape|music|dialogue"}]
  },

  "task_types": ["video editing","audio reuse"],   // ref2va only, enum in §6 R30

  "prompt": "…the exact string handed to the node…",
  "prompt_tokens": 803,
  "hashes": {"request":"…","cards":"…","plan":"…","prompt":"…","render":"…"},

  // §14: resolved before planning; the compiler owns the trigger strings, not the caller
  "loras": [
    {"id":"handpainted-anim-v2","version":2,"file_sha256":"9f2c…",
     "strength_requested":0.9,"strength_applied":0.9,
     "triggers_injected":[{"text":"hndpntd_anim_v2","slot":"style","count":1}],
     "registry_revision":"reg-2026-08-10T14:22Z"}
  ],

  "mode_decision": {"mode":"ref2va","confidence":0.91,"rule_fired":"12.2#1",
                    "signals":["two subjects named from two images"],
                    "alternatives":["fl2va"],"asked":false},

  "provenance": {"analyzer_model":"…","analyzer_version":"…","prose_model":"…","seed":12345,
                 "card_ids":["…"]},
  "diagnostics": [{"rule":"R41","severity":"warn","message":"…"}]
}
```

### 3.1 Rendering rules — per mode, byte-exact  **[SPEC]**

The two modes render differently and this is verified in both the guides and the published
artifacts. Getting it wrong is a silent format error.

**Base modes (t2va / i2va / fl2va / l2va)** — field name and content on the *same* line:

```
integrated_multimodal_description: [Shot 1] …

overall_soundscape: …

non_diegetic_music: …
```

**Ref2VA** — six sections, name on its *own* line, content following:

```
subject_definitions:
<Subject 1> is …

summary:
[video editing + audio reuse] …

retention_analysis:
<Subject 1> (appears in [Shot 1]): fully_preserved - …

detailed_description:
The target video is in realistic photographic style.
[Shot 1] …

overall_soundscape:
…

non_diegetic_music:
…
```

Instruction lines, reproduced **verbatim including the em dash (U+2014) and the per-mode bracket
convention** — which is inconsistent in the spec, and I preserve the inconsistency rather than
tidying it:

| mode | first line |
|---|---|
| t2va | *(none — begins with the first field)* |
| i2va | `For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced.` |
| fl2va | `How the reference pictures align with the target video — Picture 1 (from Shot 1) aligns with the 0.00-second mark of the target video; Picture 2 (from Shot N) aligns with the S.SS-second mark of the target video.` |
| l2va | `How the reference pictures align with the target video — <Picture 1> (from [Shot N]) aligns with the S.SS-second mark of the target video.` |

Note fl2va uses **bare** `Picture 1` / `Shot 1`; i2va and l2va use **bracketed** forms. Followed by
exactly one blank line **[SPEC]**.

`S.SS` = the **nominal** requested seconds to two decimals (`10.00`), *not* the snapped
`effective_seconds` **[MINE, reversed after checking]**. Reasoning: the hosted API takes an integer
duration, so H3-Base's training distribution contains integer `S.SS` values — and the guide's own
L2VA example uses `6.00`, which is **not on the local `n % 17 == 5` grid** at all (the neighbours are
5.875 and 6.583). Writing `10.13` would be accurate about the local render and out of distribution
for the model. So: the instruction line follows nominal; **shot cut times still validate against
`effective_seconds`** (R23), because a cut the render cannot reach is a different and real error.
The two are deliberately decoupled. `s_ss_policy` is a profile field and E3 measures which one lands
the last frame better.

Separator between fields: one blank line **[MINE]**. The guide renders blank lines and the published
I2VA artifact uses `\n\n`, but the published T2VA artifact uses a single `\n`. Both are in H3's
training distribution; blank line is the majority form.

Style opening placement **[SPEC, §5.2 of `ref-en.txt`]**: base modes put the style *inside*
`[Shot 1]`; Ref2VA puts one or two style sentences on their own line *before* `[Shot 1]`.

### 3.2 The legal duration grid  **[SPEC, from runtime]**

`align_frame_count` snaps up to `n % 17 == 5`. That leaves exactly **15 legal durations** in the
node's stated trained range of ~124–362 frames:

```
124=5.167  141=5.875  158=6.583  175=7.292  192=8.000  209=8.708  226=9.417  243=10.125
260=10.833 277=11.542 294=12.250 311=12.958 328=13.667 345=14.375 362=15.083
```

**192 frames is the only integer second in the trained range (8.000 s)** — which is why the guide's
FL2VA example is an eight-second video. A "10 second" request really renders 10.125 s, so **every
shot cut time must be `< 10.125`**, and the guide's own L2VA example (`6.00`, between the legal
5.875 and 6.583) shows the hosted stage does *not* write grid-exact durations. Hence the split in
§3.1: cut times validate against the real grid, the instruction line's `S.SS` follows the nominal
request.

---

## 4. Stage architecture

Five stages. The load-bearing decision: **structure is compiled, prose is generated.** The LLM never
decides a label number, a speaker ID, a timestamp, a retention marker, a task-type prefix or a
section order — those are computed. The LLM writes only prose bodies inside slots whose shape is
already fixed. That is what makes the layer testable, cacheable and reworkable.

```
A   Intake      brief + assets + wiring   ->  Request      (deterministic)
A'  Mode        Request + AssetCards      ->  mode_decision (§12; deterministic where the
                                                             wiring decides, one call otherwise)
A'' LoRA        proposed ids + registry   ->  injection plan (§14.4; deterministic)
B   Analyse     each asset                ->  AssetCard    (VLM / whisper, cached per asset)
C   Plan        Request + cards + plans   ->  Plan         (deterministic: labels, speakers,
                                                            timeline, markers, task types)
D   Render      Plan                      ->  prose + prompt (LLM writes bodies; template emits)
E   Validate    IRDocument                ->  pass | repair | fail   (§6)
```

Note the ordering wrinkle: **mode inference needs the AssetCards** (the anchor-vs-reference call reads
what the images actually are), so B runs before A′ completes for the 1–2-image case. The clean way to
express it: B is a pure per-asset cache lookup with no dependencies, so it can always run first; A′
and A″ then consume it. Everything after C is deterministic given those three.

**A — Intake.** Normalises: mode from the wiring (not from the user), `requested_seconds` → frame
grid, canvas, per-asset role (`frame_anchor | subject | environment | style | storyboard |
edit_source | continuation_source | voice_timbre | bgm | music_style | beat_reference | sfx |
transcript_source`), dialogue lines with explicit language tags, on-screen text strings, hard
constraints. Roles are the input from which task types and retention markers are *derived*, so they
must be explicit, not inferred from prose.

**B — Analyse (the expensive, reusable stage).** One `AssetCard` per asset, cached on content hash.
This is where the hosted stage's apparent magic actually lives. Its verbosity is not a house style —
it tracks *how much reference material there is to inventory*: 249 words for a two-shot T2VA with no
references, 238 for a one-shot Ref2VA edit, but **533 words for a single static I2VA shot**, because
that one had an image to catalogue — bowl pattern, broth colour, two chashu slices with spiral
marbling, nori at the right edge, seven family members with individual wardrobe. Nothing moves in
that shot except steam and a focus pull. That is an asset inventory rendered into prose, not creative
writing, and it is the part a local layer can reproduce exactly. **[INFER]**

Card contents, per kind:
- *image*: subjects (identity attributes, wardrobe, accessories), environment, props with positions,
  lighting and colour, framing/lens, style, all legible text verbatim, notable defects.
- *video*: the image card for a representative frame, plus shot structure, cut times, camera motion
  per shot, subject motion, and duration on the frame grid.
- *audio*: **transcript with language ID (whisper), timbre description, tempo/instrumentation,
  diegetic-vs-score judgement.** Non-optional — see §4.1 below.

**§4.1 — the audio blind spot (this is easy to miss).** The tokenizer emits `"<Audio j>: "` **and
nothing else**; audio content never enters Qwen at all (`minimax.py:161-163` — the audio branch adds
a text label and no vision entry). The audio latents reach the DiT separately. So **for an audio
reference, the IR text is the only channel by which the conditioning encoder learns what that audio
is.** An image gets described *and* seen; an audio only gets described. Audio lines in
`subject_definitions` / `retention_analysis` / `overall_soundscape` are therefore load-bearing in a
way image lines are not, and a local whisper pass is a hard dependency of the layer, not a nicety.
The box already has whisper via the toolbox MCP and a local whisper.cpp build.

**C — Plan (all-deterministic).** Computes, in this order:
1. `manifest` from the wiring, using the runtime's emission order (§1.2). Labels assigned here and
   nowhere else.
2. `subjects` — one per reusable visible unit, each pointing at grounded labels. Spec rule: an image
   used *only* to define a character/scene/style gets **no** standalone `<Picture N>` entry in
   `subject_definitions`; it is cited inside the subject's definition. A standalone `<Picture N>`
   entry means the image is a concrete frame or composition anchor **[SPEC, `ref-en.txt` §2.2]**.
3. `speakers` — `(SN)` in order of first actual vocal event in the *target* video **[SPEC, `ref-en.txt` §5.4]**.
4. Timeline — shot cut times strictly increasing, all `< effective_seconds`, `MM:SS.mmm`, none on
   shot 1.
5. Retention markers per subject/label from its role + whether the plan modifies it.
6. Task types from asset roles, `+`-joined, deduplicated, in the spec's listed order.

**D — Render.** The LLM receives the Plan plus the *relevant slice* of the official guide and writes
only: shot bodies, `overall_soundscape`, `non_diegetic_music`, subject-definition attribute phrasing,
retention notes. Everything structural is emitted by the template. Dialogue text is **pasted, never
generated** — the spec requires verbatim preservation of user-supplied words and punctuation, so it
must not pass through the model at all.

**E — Validate + repair.** §6. On an ERROR, re-ask the model for the specific failing span (bounded,
2 attempts), re-validate, then fail loudly. **An invalid IR is never handed to the sampler** — that
is the whole point of having a compiler.

---

## 5. Model and backend — the inference host does both jobs (verified)

**The brain is the inference host, and the hybrid split the brief anticipated turns out to be unnecessary.** I
was asked to verify the text-only assumption rather than inherit it. **It is wrong:
`Huihui-Qwen3.6-27B-abliterated-AWQ-MTP` has a working vision tower.** Evidence, from live calls:

- Two 4-quadrant colour-layout images read correctly in full order — 1/24 each, 1/576 for both.
- Then **three different images in one request, 12/12 quadrant colours correct and correctly
  attributed per image** (388 prompt tokens, 0.6 s). Cross-image reasoning, not just captioning —
  which is precisely what Stage C needs to assign subjects to `<Picture N>` slots.
- Image token cost scales like a Qwen-style ViT at patch 16 / merge 2: 1344×768 → 1,024 tokens
  ≈ (1344/32)×(768/32) = 1,008 plus vision delimiters. That is a real vision encoder, not a caption
  side-channel.

So **one model on one host covers analysis, planning and prose.** No cross-model drift between the
stage that sees the assets and the stage that writes about them, and the render box's VRAM stays
free for sampling. This is a better architecture than the hybrid I was prepared to design, and it is
better because of a measurement, not a preference.

**Endpoint contract my layer depends on** (all verified): OpenAI-compatible
`http://LLM_HOST:8000/v1`, `max_model_len` 262,144, image input via `image_url` content parts,
`response_format: json_schema`, prefix caching, `seed`, and the alias ids `gpt-4.1` / `gpt-5.2`
resolving to the same weights. Abliterated, so creative briefs will not be refused — relevant, since
a rewrite layer that refuses half of a user's material is worse than no layer.

### 5.1 Two hard operational rules, both discovered by measurement

**Rule 1 — thinking must be OFF for every structured stage.** This is a reasoning model whose
chain-of-thought lands in `message.reasoning`, and `content` stays `null` until it finishes. Measured:

| call | result |
|---|---|
| default, `max_tokens=2000` | `finish=length`, 9,290 chars of reasoning, **`content: null`** — nothing usable |
| `chat_template_kwargs: {"enable_thinking": false}` | `finish=stop`, 0 reasoning, 3,562 chars of content in **9.0 s** |
| `chat_template_kwargs: {"thinking": false}` | **silently ignored** — reasoning ran anyway |

Only the first spelling works. Get it wrong and the stage returns `null` with no error.

**Rule 2 — never trust `json_schema`.** Measured behaviour:

- **With thinking ON, the grammar is not applied at all.** A `strict: true` AssetCard schema returned
  an ASCII-art box-drawing table, `finish=stop`, no error. Silent, complete violation.
- With thinking OFF the *shape* is enforced (adversarial "reply with ASCII art only" and "add a
  top-level key called extra_notes" both still produced schema-conforming JSON with exactly the
  declared keys) —
- but enforcement is structural only. It does **not** guarantee parseable output: "answer in one
  plain English sentence, no braces" produced a schema-shaped object whose string ran until
  `max_tokens` and came back as **unterminated, unparseable JSON**.
- And it does not guarantee sense: one arm filled `subjects` with `["Math","Science","History"]`,
  another with an encyclopedia entry on knighthood. Schema-valid nonsense.

Consequences, all now non-negotiable: thinking off for Stages B/C/D; generous `max_tokens` with an
explicit `finish_reason == "length"` check treated as a hard failure; every model output re-validated
against the schema *and* against semantic rules on our side. The design already validates rather
than trusts — this is the measurement that makes that mandatory rather than tidy.

### 5.2 The local vision path is a fallback for availability, not capability

The inference host is a deliberately always-on appliance with a watchdog, but it is still one host on one
network. The `Backend` interface stays, with fallbacks in this order:

1. **The inference host** — `LLM_HOST:8000` (primary; the maintainer's choice, and now the measured best fit).
2. **ComfyUI-QwenVL on the render box** — installed; HF/GGUF backends, image and video-frame input. Costs
   VRAM contention with the sampler.
3. **`qwen_2.5_vl_7b_fp8_scaled`, already on disk** — verified to have both `lm_head [152064, 3584]`
   and a vision tower, so it can generate. Zero-download smoke-test path.

`qwen3vl_8b_fp8_scaled` has `lm_head` but **no visual tower** — text-only, so t2va only. And on the
elegant option: ComfyUI core already has a working generation loop for these encoders
(`Qwen3VLClipModel.generate()`, `comfy/text_encoders/llama.py:863-941`), so H3's own layer-50 encoder
plus the published ~7 GiB tail would author with the *exact* weights that then encode. Now that
the inference host demonstrably sees, that property buys much less: it costs a download, a custom node, and the
sampler's VRAM, to remove a drift that a single-model pipeline does not have. **Demoted to
experiment E5** — worth running once, not worth building on. **[MINE]**

**Availability policy:** if the inference host is unreachable, the layer must **fail loudly with a clear
message**, not silently downgrade to a weaker model — a caller cannot tell a good IR from a bad one,
and quietly halving quality is the failure mode the maintainer would notice last. Degrading to a fallback
is an explicit, logged, opt-in flag.
## 6. Validator

Two severities. **ERROR** blocks the render (repair or fail). **WARN** is recorded in
`diagnostics` and surfaced. Rules marked ⚑ are the ones that catch the failures I actually expect.

### Binding and labels
| id | sev | rule | detection |
|---|---|---|---|
| R01 ⚑ | ERROR | every `<Picture N>` / `<Video N>` / `<Audio N>` in the prompt exists in `manifest` | regex extract ∩ manifest |
| R02 ⚑ | ERROR | no label outside the four namespaces: reject `<Image N>`, `<Ref N>`, `<Frame N>`, `<Img N>`, `<Clip N>` | regex `<\s*(?!Picture|Video|Audio|Subject|d|/d|scenetrans|cutoff)[A-Za-z]+\s*\d*\s*>` |
| R03 ⚑ | ERROR | every manifest entry's label appears ≥1× in the prompt (no orphan asset paying rows for nothing) | manifest − extracted |
| R04 | ERROR | manifest order equals the runtime emission order: images, then per video (paired audio label, video), then standalone audio | recompute from wiring, compare |
| R05 | ERROR | counts within limits: ≤9 images, ≤3 videos, ≤3 audio, ≤12 files total; audio never the sole reference | manifest census |
| R06 | ERROR | every `<Subject N>` used anywhere is defined in `subject_definitions` | set difference |
| R07 | WARN | every defined `<Subject N>` is used in `detailed_description` | set difference |
| R08 | ERROR | subject label numbering is contiguous from 1 | sort |
| R09 | ERROR | an image used only to define a subject/style has no standalone `<Picture N>` line in `subject_definitions` | role vs section |
| R10 | ERROR | a frame-anchor claim (`the shot begins from <Picture N>`, `ends on`, `keyframe corresponds to`) only for assets whose role is `frame_anchor` | phrase match vs role |

### Speakers and dialogue
| id | sev | rule | detection |
|---|---|---|---|
| R11 | ERROR | `(SN)` assigned in order of first vocal event; contiguous from 1 | scan order of `<d>` blocks |
| R12 | ERROR | **no `(SN)` in `retention_analysis`** (explicitly forbidden, `ref-en.txt` §5.4) | section scan |
| R13 ⚑ | ERROR | `<d>` / `</d>` balanced and byte-exact (`<d>`, `</d>`; no `<D>`, no spaces, no typographic brackets) | tokenizer-level scan |
| R14 | ERROR | every `<d>` opens with `[Language] ` from H3's 11 stable languages (Arabic, Chinese, English, French, German, Italian, Japanese, Korean, Portuguese, Russian, Spanish) or an explicitly-allowed extra | prefix match |
| R15 ⚑ | ERROR | dialogue text is a byte-exact substring of the user-supplied line — never translated, paraphrased or re-punctuated | exact compare against Request |
| R16 | ERROR | inside `<d>`: no emoji, tildes, bullets, repeated/decorative punctuation; ends `.`/`?`/`!` for complete statements | charset + terminal check |
| R17 | ERROR | voiceover uses the exact phrase `says in an off-screen voiceover` **and** is immediately followed by a lips-remain-closed clause | phrase adjacency |
| R18 | ERROR | compound IDs `(S1,S2)` reference already-numbered speakers only | membership |
| R19 | WARN | a declared speaker with no `<d>` block, or a `<d>` with no speaker | join |
| R20 | ERROR | `<scenetrans>` appears at both connecting points of a cut-crossing line, with an explicit continuity phrase | pair + phrase |
| R21 | ERROR | `<cutoff>` only on the final shot's last dialogue | position |

### Timeline and duration
| id | sev | rule | detection |
|---|---|---|---|
| R22 ⚑ | ERROR | `[Shot 1]` carries no timestamp | regex |
| R23 ⚑ | ERROR | cut times strictly increasing and all `< effective_seconds` | parse `MM:SS.mmm` |
| R24 | ERROR | timestamp format exactly `MM:SS.mmm` | regex |
| R25 ⚑ | ERROR | `frames` is on the `n % 17 == 5` grid; `effective_seconds == frames/24`; `S.SS` matches `s_ss_policy` (default: nominal seconds, 2 dp) | arithmetic |
| R26 | ERROR | shot numbers contiguous from 1; the last-frame anchor lands in the final shot (fl2va/l2va) | sequence |
| R27 | WARN | fl2va with >1 shot (spec: "generally favors a single shot") unless explicitly requested | count vs Request |
| R28 | WARN | shot count vs duration outside 1 shot per ~1.5 s..8 s | ratio |

### Sections, markers, task types
| id | sev | rule | detection |
|---|---|---|---|
| R29 | ERROR | exact section set and order for the mode; per-mode field names (`integrated_multimodal_description` for base, `detailed_description` for ref2va — never crossed) | parse |
| R30 | ERROR | task-type prefix bracketed, `+`-joined, no duplicates, all from {`keyframe completion`, `reference generation`, `video editing`, `video continuation`, `audio reuse`, `audio reference`} | enum |
| R31 ⚑ | ERROR | `video editing` only with a `<Video N>` whose role is `edit_source`; `video continuation` only with `continuation_source`; `audio reuse` only with attached audio | role cross-check |
| R32 | ERROR | for `video editing`, `summary` begins after the prefix with `The target video is an edited version of <Video 1>.` | prefix match |
| R33 | ERROR | visual retention markers ∈ {`fully_preserved`, `partially_preserved`, `attribute_transfer`, `weak_reference`}; audio ∈ {`fully_copy`, `partially_copy`, `reference`, `weak_reference`}; never crossed | enum by label kind |
| R34 | ERROR | `retention_analysis` has exactly one line per defined label, using `label (role): marker - note` | line parse |
| R35 | ERROR | no new labels introduced in `summary` | set ⊆ subject_definitions |
| R36 | ERROR | dialogue/lyrics text does not reappear in `overall_soundscape` or `non_diegetic_music` | substring |
| R37 | ERROR | `N/A` used for absent non-diegetic music; `overall_soundscape: N/A` only when total silence was requested | value vs Request |
| R38 | WARN | `non_diegetic_music` names instrumentation/tempo/dynamics and avoids abstract mood words ("emotional", "epic", "atmosphere of") | lexicon |
| R39 | ERROR | Ref2VA style sentence precedes `[Shot 1]`; base-mode style sits inside `[Shot 1]` | position |
| R40 | WARN | Ref2VA `detailed_description` 350–500 words for generation tasks | count |

### Text hygiene and budget
| id | sev | rule | detection |
|---|---|---|---|
| R41 ⚑ | ERROR | no smart quotes/dashes/NBSP/full-width brackets anywhere structural; on-screen text in straight `"` and verbatim | unicode scan |
| R42 | ERROR | all sections English except inside `<d>` and quoted on-screen text | script detection per span |
| R43 | WARN | prompt token count outside 350–1,400 (published band 537–919) — distribution drift, not cost | tokenizer |
| R44 | WARN | camera motion outside the spec's 12 motion types (+ `with small/large amplitude`, `at slow/fast speed`), or stacked as trailing labels rather than natural prose | lexicon |
| R45 | ERROR | re-rendering the IRDocument reproduces `prompt` byte-for-byte | render + compare |
| R46 | WARN | quoted on-screen text in a wide shot at 768p (unreadable at output resolution — see §11) | framing heuristic |

---

## 7. Failure taxonomy

| # | failure | why it happens | detected by | consequence |
|---|---|---|---|---|
| F1 | **Dangling label** — prompt names `<Image 1>`, runtime emitted `<Picture 1>` | hand-written prompts; no compiler | R02, R01 | references are textually unaddressed; with ≥2 refs the model must guess which is which. **This is the maintainer's current prompt.** |
| F2 | **Orphan asset** — attached but never named | wiring drift | R03 | pays 1,008–37,296 rows/step for nothing |
| F3 | **Numbering desync** — IR written against a different asset order | IR and wiring authored separately | R04 | every label points at the wrong asset |
| F4 | **Undefined subject** | prose invents `<Subject 3>` | R06 | ungrounded pointer, no binding at all |
| F5 | **Speaker drift** — IDs out of event order, or `(SN)` in retention | LLM free-writing structure | R11, R12 | voice/identity assignment breaks across shots |
| F6 | **Dialogue mutation** — translated, re-punctuated, emoji kept | model "improves" the line | R15, R16 | the spoken words are not the user's words |
| F7 | **Illegal timeline** — cut at/after the true end, timestamp on shot 1 | assuming 10 s means 10.000 s | R22–R25 | shots the model cannot reach; drift against the frame grid |
| F8 | **Grid mismatch** — `S.SS` disagrees with the policy, or cut times exceed the true render length | nominal vs snapped duration conflated | R25, R23 | last-frame anchor lands at the wrong time; unreachable shots |
| F9 | **Mode/format crossing** — `detailed_description` in t2va, or Ref2VA sections on one line | one template for all modes | R29, R39 | out-of-distribution presentation |
| F10 | **Marker misuse** — audio marker on a subject, invented marker | free-text retention | R33, R34 | the retention contract stops parsing as one |
| F11 | **False task type** — `video editing` with no source video | prefix copied from an example | R31, R32 | asserts a relationship the pack does not contain |
| F12 | **Byte-level marker corruption** — `<D>`, smart quotes, NBSP | copy-paste through an editor or chat UI | R13, R41 | different token sequence; the marker's learned meaning is lost |
| F13 | **Audio described nowhere** | audio treated like an image (assumed "seen") | R03 + card completeness | the encoder learns nothing about the audio at all (§4.1) |
| F14 | **Silent verbosity confound** — comparing IRs of different lengths | not knowing text_len shifts RoPE | harness, §10 | wrong conclusions from every A/B you run |

Three more, all **measured on the live the inference host endpoint** (§5.1) rather than anticipated — they are
backend failure modes, and they are silent, which makes them the dangerous kind:

| # | failure | why it happens | detected by | consequence |
|---|---|---|---|---|
| F15 ⚑ | **Thinking swallows the answer** — `content: null`, no error | reasoning model; the chain-of-thought consumed `max_tokens` before any content | assert `content is not None` **and** `finish_reason != "length"` on every call | the stage returns nothing and a naive caller treats it as an empty description |
| F16 ⚑ | **Schema silently not enforced** — `strict: true` returned an ASCII-art table, `finish=stop` | `json_schema` is not applied while reasoning is enabled | thinking off for all structured stages; re-validate every payload against the schema our side | structured stages appear to work and return prose; nothing raises |
| F17 | **Schema-valid nonsense / truncated JSON** — `subjects: ["Math","Science","History"]`; or a string that runs to the token cap and comes back unterminated | grammar constrains shape, not sense or completion | semantic checks per card field + `finish_reason` check + JSON parse | a well-formed AssetCard describing the wrong thing propagates into the IR unnoticed |

The common lesson: **the model's structured-output guarantee is weaker than its documentation
implies, in both directions.** The layer must parse, validate and sanity-check everything it gets
back — which the design already does for the IR, and must equally do for every intermediate card.

Five more — F18–F22, the style-LoRA failures — are in §14.7, kept with the feature they belong to.
F18 (a LoRA patched into the graph whose trigger never reached the text) is the same shape as F1: a
pointer that names nothing, at full compute cost.

---

## 8. Reworkability: profiles and cache keys

**Profiles.** Every genuinely-unknown behaviour is a field in a versioned `profile` object, never a
branch in code: `sections_included`, `verbosity_band`, `s_ss_policy` (`snapped` | `nominal`),
`fl2va_bracket_style`, `field_separator`, `style_opening_placement`, `camera_prose_style`,
`analysis_depth`, `trigger_repeat_default`, `unknown_turbo_stacking` (`allow_flag` | `block`),
`composed_retention_style`. Changing a belief = publishing `h3ir/2026-09-b`, not editing the compiler.
Every IRDocument records the profile that produced it, so a regression is attributable.

**Cache keys** (content-addressed, so a change re-does exactly one stage):

| artifact | key |
|---|---|
| `AssetCard` | `sha256(asset bytes)` + `analyzer_version` + `model_id` + frame-sampling policy |
| `Plan` | `hash(canonical Request)` + all card hashes + `planner_version` + LoRA injection plan |
| prose bodies | `hash(Plan)` + `renderer_version` + `prose_model_id` + `prose_seed` + `profile` |
| `prompt` | `hash(prose bodies + Plan + profile)` |
| **render** | `hash(prompt)` + **`lora_set` + strengths** + `seed` + sampler/steps/shifts + canvas |

Effect: reword one shot → re-render only. Swap one reference image → re-analyse one asset, replan,
re-render. Change duration → replan and re-render, cards untouched. Upgrade the analyser → all cards
invalidate, everything downstream rebuilds. ComfyUI's own node caching then avoids re-encoding an
unchanged prompt.

The **render** key is separate from the prompt key on purpose (§14.5): a LoRA reaches the output
through two independent channels — its trigger changes the IR *text*, and its weights change the
*sampling*. A prompt hash cannot see the second one, so keying renders on the prompt alone produces
the worst available cache hit: right text, wrong weights, and nothing in the artifact to reveal it.

**Version everything in the artifact**: `ir_version`, `profile`, `analyzer_version`,
`planner_version`, `renderer_version`, model ids, seed. An IR you cannot attribute is an IR you
cannot improve.

---

## 9. Specified / inferred / unknown

### Specified — build to these, they will not move
Section names and order per mode; per-mode field names; the four label namespaces and their
semantics; retention-marker enums (visual and audio, distinct); the six task types and the `+` rule;
speaker-ID rules including the ban on `(SN)` in `retention_analysis`; `<d>[Language] …</d>`,
`<scenetrans>`, `<cutoff>`, the exact voiceover phrase and the lips-closed clause; `[Shot N] At
MM:SS.mmm`; no timestamp on shot 1; the 12 camera motion types plus amplitude and speed; the three
instruction lines verbatim; on-screen text in straight double quotes, verbatim, untranslated;
English body with original-language dialogue; 350–500 words for Ref2VA generation tasks; `N/A`
conventions. From the runtime, which is stronger than documentation: the exact emitted label
strings, the emission order, the 1-based per-type ordinals, the `n % 17 == 5` frame grid, the
768-short-edge canvas with a 768×1344 area cap, ≤9 images / ≤3 videos / ≤3 audio / ≤12 files, audio
never sole input, and the fact that nothing truncates the prompt.

### Inferred from the published outputs — safe to build on, worth re-checking
- **I1** Hosted `<Audio N>` numbering matches the runtime's emission order exactly (soundtrack of
  `<Video 1>` is `<Audio 1>`; standalone voice ref is `<Audio 2>`). Two independent sources agree.
- **I2** The hosted T2VA call is approximately *the published guide as a system prompt + the brief*
  (3,582 + 493 measured vs 5,650 reported).
- **I3** Reported `completion_tokens` are 5–11× the emitted artifact ⇒ the hosted stage is a
  multi-stage workflow with internal reasoning, and its usage numbers are rollups. Do not budget
  against them.
- **I4** Verbosity scales with reference material, not with ambition: 249 words (T2VA, no refs), 238
  (Ref2VA edit), **533 (I2VA, one image, static camera)**. The long one is long because it inventories
  its reference image. Also: the published Ref2VA `detailed_description` is 238 words, *below* the
  guide's 350–500 range — legitimately, because the guide exempts editing tasks from that range. So
  R40 must apply to generation tasks only.
- **I5** Style may be a stacked prefix ("Cinematic, medium wide shot, pushing in slowly.") despite
  `base-en.txt` §4.3's preference for natural prose ⇒ that rule is a preference, not a constraint (hence WARN, not
  ERROR, in R44).
- **I6** Cross-shot identity is re-established in plain prose ("the captain from Shot 1"); square
  brackets are only for the `[Shot N]` markers themselves.
- **I7** Retention lines may carry a free-text role parenthetical ("(source video editing)") beyond
  the guide's examples.
- **I8** Field separators vary in real hosted output (`\n` in T2VA, `\n\n` in I2VA) ⇒ H3-Base
  tolerates both.

### Genuinely unknown — isolate behind a profile, close by experiment
- **U1 ⚑** Do `summary` and `retention_analysis` contribute to H3-Base at all, or are they
  scaffolding for the hosted LLM? They are ~40 % of a Ref2VA IR's tokens. *My prior: they matter,
  because H3-Base was trained on Context-IR outputs that always contained them — omitting them is
  out-of-distribution regardless of their semantic content.* Highest-value unknown. → E1.
- **U2** Is `S.SS` the nominal request or the snapped duration (`frames/24`)? Evidence leans nominal
  (the guide's own `6.00` is off-grid; the hosted API takes integer durations), but the local render
  really is 0.125 s longer than it claims. → E3.
- **U3** Does fl2va's bare `Picture 1` vs bracketed `<Picture 1>` matter? → E4.
- **U4** Does verbosity beyond ~600 tokens help, once the text_len confound is controlled? → E2.
- **U5** Effect size of getting `<d>` byte-wrong. → E6.
- **U6** Does H3-Base use the `[task type]` prefix? → E1 variant.
- **U7** How the hosted stage selects/compresses when material exceeds 9 images or 15 s. No local
  visibility; treat as a product decision (the compiler should *refuse* and ask, not silently drop).
- **U9** Mode-inference accuracy on real briefs, and specifically the anchor-vs-reference call — the
  one decision in §12 that a model makes rather than the wiring. → E8.
- **U11** Composed vs decomposed references (a production account reports composed keyframes give
  unreliable motion). Not designed for; the seam is `AssetCard.composition`, already populated. My
  mechanistic hypothesis and the third test arm that distinguishes the two possible causes are in
  §14.8 — **[MINE, falsifiable]**.
- **U12** Whether style LoRAs compose safely over the Turbo distillation LoRA, the safe strength band,
  and whether stacking disturbs the step band. Being measured by the pipeline engineer; lands in
  `stacks_with_turbo` and `constrains.steps` per LoRA (§14.3), no redesign either way.
- **U10** Whether abliteration has cost this model any format-following precision. The IR is a strict
  format and abliterated checkpoints are tuned for compliance in a different direction. Cheap probe:
  score N renders against the validator and track the ERROR rate before repair — a high pre-repair
  error rate is the signal, and the fallback is a non-abliterated model for the *structured* stages
  only (a second host exists for this) while the inference host keeps the creative prose.
- **U8** Whether the released CFG-distilled Ref2VA checkpoint retains any in-context-regeneration
  behaviour. → §11.

### Decided by me — revisable, and each one is a profile field
Blank-line field separator; `S.SS` from the snapped duration; the IRDocument schema and the
manifest-with-the-prompt contract; the compile-structure/generate-prose split; the five-stage
pipeline; cache-key composition; the backend preference order; WARN-vs-ERROR severities; the
350–1,400 token band; treating audio analysis as a hard dependency.

---

## 10. Experiment suite (all falsifiable, fixed seed, one variable)

Run every experiment on the installed `minimax_h3_ref2va_pruned_int8_convrot` at 5 s / 1344×768
(124 frames) — the cheapest legal config — with identical seed, sampler, steps and shifts.

- **E0 — baselines. Half done.** The authoring half is **measured** (§2: 80–107 tok/s, 3.25 s guide
  prefill, 1,024 tokens per 1344×768 reference, 25–40 s per full Ref2VA IR). What remains is the
  sampling half: seconds/step vs packed rows, sweeping `ref_image_size` match/max across 1/3/9 refs,
  to confirm the §2 row table converts to wall time as predicted.
- **E1 ⚑ — section ablation (U1, U6).** Same subjects, same `detailed_description`; four arms: full
  six-section / minus `retention_analysis` / minus `summary`+`retention_analysis` / prose-only.
  **Hold `prompt_tokens` constant to ±2 % by padding the description**, or the RoPE-offset confound
  (§1.3) invalidates the result. Score: identity preservation against the reference, blind.
- **E2 — verbosity (U4).** Three IRs of the same plan at ~400 / ~700 / ~1,100 tokens. Report both
  raw and token-matched arms, and state plainly that length and content cannot be fully separated.
- **E3 — `S.SS` policy (U2).** fl2va at 243 frames (10.125 s real) with `10.00` vs `10.13`; measure
  last-frame landing error in frames against the supplied last frame.
- **E4 — bracket convention (U3).** fl2va instruction line bare vs bracketed.
- **E5 — same-weights authoring (§5).** IR from H3's own encoder + tail vs from a stronger different
  VLM, same plan. Decides whether the elegant path earns production status.
- **E6 — marker corruption (U5).** `<d>` vs `<D>` vs `< d >`; measure lip-sync and whether the words
  are spoken at all.
- **E7 ⚑ — the maintainer's actual prompt, and the control that makes it conclusive.** Four arms on his
  two references (armoured man + dragon):
  - (a) his prose verbatim, `<Image 1>` / `<Image 2>`
  - (b) identical prose, labels corrected to `<Picture 1>` / `<Picture 2>`
  - (c) full compiled Ref2VA IR (subjects, retention contract, timeline)
  - (d) **control:** arm (b) with the two images swapped **in the wiring only**, prompt text
    untouched — so the text now says the *dragon* image is the man.

  What (d) decides: if the output follows the labels (a man-shaped dragon, or an armoured dragon
  rider that is visibly the wrong subject), then labels genuinely bind and F1 is a real defect. If
  the output ignores the swap and still renders man-rides-dragon, then **position** binds and the
  labels are decorative — F1 shrinks to cosmetic and I am wrong about its size. Either result is
  worth knowing before building on §1.1; the structural case for the six sections then rests
  independently on (c) vs (b).
- **E8 — mode-inference accuracy (§12).** A labelled set of ~40 briefs (mine plus real ones from the
  maintainer's history), each with attachments and a known-correct mode, scored for accuracy and, more
  importantly, for **error direction**: routing a content reference to FL2VA is a hard failure (the
  mode cannot express it), routing an anchor to Ref2VA is a soft one (expressible, weaker guarantee).
  Target: zero hard failures, and the ambiguous-question rate low enough that an agent caller is not
  interrogated — I would treat >1 question per 10 briefs as a design failure, not a tuning problem.
- **E9 — the two callers get the same result.** Drive the same 10 briefs through the HTTP API as a
  bare agent would (one sentence + files, no options) and as the UI would (with every field the UI
  can set), and diff the IRs. Any craft-relevant divergence is a violation of §13's central rule and
  a bug in the API surface, not in the models.

---

## 11. Where the closed `H3-Regenerate-2K` leaves local output

**What it is:** not a super-resolution network. H3-Base regenerating its own 768p result
*in context*, with the original multimodal context re-attached, so it can recover small text and
fine detail that an upscaler would have to invent. MiniMax withholds it "due to the complexity of
the system", which implies machinery beyond a prompt trick.

**Can it be reproduced locally? No — and the blocker is arithmetic, not access.** A 2K canvas
(2048 short edge, 16:9 → 3648×2048) costs `(3648/32)×(2048/32) = 7,296` rows per latent frame. Five
seconds is `37 × 7,296 = 269,952` rows, plus ~37,296 more for the 768p result attached as a
reference video. The open release ships **full attention only** (sparse attention is explicitly
deferred), so that is a quarter-million-row sequence at O(n²) through every block on a single consumer GPU.
Fifteen seconds at 2K is ~832,000 rows. Even if the released CFG-distilled Ref2VA checkpoint does
retain the in-context regeneration behaviour (**U8**, cheap to probe at a small canvas), this
hardware cannot run it. Sparse attention landing upstream would change the arithmetic, not the
verdict.

**So the practical ceiling is 768p short edge**, and the gap is exactly where MiniMax says it is:
small on-screen text, distant faces, fine texture. The local fallback is a conventional video
upscaler (`seedvr2_videoupscaler` is already installed) or a tiled diffusion pass — both of which
*guess* the detail that Regenerate-2K would have *recovered*. Say that out loud rather than calling
an upscaled 768p render "2K".

**What the IR design should do about it — four things, all cheap now:**
1. **Keep the IR document and its manifest as a durable, replayable, content-hashed artifact.**
   Regenerate-2K's input *is* the original context; the only way to use it later — API or local — is
   to still have that context byte-exact. This is the single most important hedge and it costs
   nothing.
2. **Record the frame grid, canvas, seed, sampler and shifts alongside the IR**, so a regeneration
   is reproducible rather than approximate.
3. **Make `regenerate` a mode of the same compiler, not a second pipeline** — a Ref2VA plan whose
   first reference is the previous output (`role: continuation_source` / `edit_source`), with the
   original subjects and retention contract carried forward unchanged. If a local stage ever ships,
   or the maintainer decides one API call per hero shot is acceptable, it is a plan variant, not a
   rewrite.
4. **Exploit the one place 2K detail *can* enter locally:** `ref_image_size=max` puts references in
   at a 2048 short edge even though output is 768p. Spend those 7,296 rows on the identity that
   matters and leave the rest at `match` (1,008). And warn (R46) when the plan puts quoted on-screen
   text into a framing that 768p cannot hold — at 768p that text will be mush, and no local stage
   will rescue it.

---

## 12. Mode inference — the user never picks a mode

If checkpoints and modes are invisible, something has to decide, before any rewriting, which of the
five modes is being asked for. That decision belongs at the front of this layer, because it is
determined by exactly the two things the layer already owns: **the wiring and the asset roles.**

### 12.1 What actually distinguishes the modes  **[SPEC]**

From the release table: `H3-Base-FL2VA` takes 0 images (T2VA), 1 image (first-*or*-last frame), or 2
images (first-and-last). `H3-Base-Ref2VA` takes the omni-reference set. So the modes are not five
creative intents — they are **two checkpoints and a count**, plus one genuinely hard semantic
question:

> Is this image a **frame** of the video, or a **thing that appears in** the video?

That is the whole difficulty. "Animate this photo" (the photo *is* frame 0 → I2VA) and "put this man
in a battle" (the man appears, redrawn → Ref2VA) are the same attachment count and the same file
type. Everything else routes deterministically.

### 12.2 The routing procedure

**Deterministic rules first — no model involved:**

| # | condition | mode |
|---|---|---|
| 1 | any video or audio reference attached | **Ref2VA** (the FL2VA checkpoint cannot accept them) |
| 2 | more than 2 images | **Ref2VA** |
| 3 | 0 images | **T2VA** |
| 4 | 1–2 images | → 12.3, the only real decision |

**12.3 Anchor vs reference, for 1–2 images.** One classification call (thinking off, tiny enum
schema, per §5.1) over the brief text plus the AssetCards, returning
`{intent: frame_anchor | content_reference, which: first | last | both, confidence, signals[]}`.
Signals it is told to weigh:

- *Anchor language*: "animate this", "make this move", "bring this to life", "start from this",
  "end on this", "from this frame", "this is the opening shot".
- *Reference language*: "using this character", "this person/product", "in this style", "like this",
  "put X in", "combine", and decisively **two subjects named from two different images** ("the man
  from X rides the dragon from Y") — that is Ref2VA and nothing else can express it.
- *Geometry*: a first-frame anchor is stretched to the target canvas by the node
  (`_resize(..., "disabled")`), so an image whose aspect differs materially from the requested output
  aspect is a poor anchor candidate. Weak signal, real mechanism.
- *Pairing*: two images described as "start and end" → FL2VA; two images described as two different
  things → Ref2VA.

Then: 1 image + anchor + `first` → **I2VA**; + `last` → **L2VA**; 2 images + anchor + `both` →
**FL2VA**; anything + `content_reference` → **Ref2VA**.

### 12.4 How it fails safe

**Default on ambiguity: Ref2VA** — and for a principled reason, not a coin flip. **Ref2VA is
strictly more expressive.** The spec's `keyframe completion` task type exists precisely so a Ref2VA
IR can say "this image serves as the target video's first frame, keyframe, or last frame", so a
misrouted anchor is still expressible. The reverse is not true: FL2VA has no way to say "this thing
appears but is not a frame". Asymmetric expressiveness gives a safe default. It is also the only
installed checkpoint today.

The cost of that default is real and should be recorded, not hidden: FL2VA injects the keyframe as a
**cond latent pinned to frame 0 (or `frame_count - 1`) that is never denoised**, an exact-frame
guarantee; Ref2VA's `keyframe completion` is a softer promise. So:

- confidence high + geometry consistent → route FL2VA and take the exact-frame guarantee;
- confidence low **and** the brief contains anchor language → **ask one question** (§13.4) rather
  than silently choosing the weaker guarantee, because this is the one case where the wrong default
  is visible in the output;
- confidence low with no anchor language → Ref2VA, no question, no ceremony.

**Every decision is recorded** as `mode_decision {mode, confidence, rule_fired, signals[],
alternatives, asked: bool}`. The UI shows "Animating your photo"; the record keeps the audit. Hiding
mode names from users must not mean hiding the decision from whoever debugs it.

**Refusals, not guesses, for over-capacity requests:** >9 images, >3 videos, >3 audio, >12 files, or
>15 s of source material has no defined local behaviour (**U7**) — the hosted stage compresses in
ways we cannot see. The layer returns a clear, actionable error naming what to drop. Silently
dropping a reference the user attached is the worst available outcome.

---

## 13. Two callers, one contract

> *"Full API so it can be driven by an unskilled in X/Y/Z agent"* · *"don't want 'comfy-talk' in the
> UI, proper user-friendliness"*

Both requirements are the same requirement: **the API is the product and the UI is one of its
clients.** If the UI ever needs a field the API does not expose, or the API needs craft the UI
supplies, the two callers get different quality. So the rule is structural:

> **There is no quality-bearing field that only the UI can set, and no path that skips the
> validator.** One code path, one validator, no privileged client.

### 13.1 The minimum viable request is one sentence and some files

```http
POST /v1/briefs
{ "intent": "the man in armour rides the dragon into a huge battle, cinematic",
  "assets": [ {"url": "...", "note": "the man"}, {"url": "...", "note": "the dragon"} ] }
```

No mode. No checkpoint. No canvas, frame grid, section names, camera vocabulary or label syntax. Every
other field is optional with a good default. That single property is what makes the layer drivable by
an agent that has no idea what FL2VA is — which is the stated reason it exists.

`note` is optional free text per asset; it is a *hint* to Stage C, never a requirement. An agent that
attaches two unlabelled images still gets a correct result, because the AssetCards describe them.

The full surface is small: `POST /v1/briefs`, `PATCH /v1/briefs/{id}`, `GET /v1/briefs/{id}`, and
`GET /v1/loras` for style discovery (§14.4). A brief may carry `"loras": [{"id": "…"}]` — ids only,
never trigger strings, for the same reason it never carries `<Picture 1>`.

### 13.2 The craft lives server-side, and caller input is constraints — never the plan

A caller *may* supply more: duration, aspect, a shot count, dialogue lines, "no camera movement". All
of it enters as **constraints on the plan**, not as the plan. The compiler still owns structure,
labels, speaker IDs, timestamps, retention markers and section order. Expressed as a contract:

> **Anything the caller omits, the layer decides well. Anything the caller specifies, the layer
> honours — or refuses with a reason.** Never silently overrides, never silently obeys something
> illegal.

This is the direct answer to *"a coding-heavy agent can't realistically step back and go creative"*:
the caller is not asked to be an art director, and is not permitted to half-be one.

### 13.3 Never fail on under-specification; fail on contradiction

- "make a video of my dog" → a complete, on-spec, validated IR. No questions, no error.
- "10 seconds, 4 shots, first cut at 12s" → `422` naming the contradiction (R23: a cut past the
  render's true 10.125 s end) with a concrete fix.

That asymmetry is the difference between a tool an unskilled agent can drive and one it cannot.

### 13.4 One clarification, with the default already applied

For the single genuinely ambiguous, high-cost decision (§12.4), the response is:

```jsonc
{ "status": "needs_input",
  "question": { "id": "anchor_or_reference",
    "ask": "Should your photo be the video's opening frame, or should the person in it appear in a new scene?",
    "options": [ {"id":"opening_frame","label":"Use it as the opening frame"},
                 {"id":"appears_in","label":"Put the person in a new scene"} ],
    "recommended": "appears_in" },
  "default_if_unanswered": "appears_in",
  "expires_in": 900,
  "result": { /* a complete, usable IR built with the default */ } }
```

The important property: **the default is already applied and the result is already valid.** An agent
that ignores the question still gets a good video; a human sees a plain-language chooser; an agent
that wants to answer sends one field. At most one question per brief — a tool that interrogates its
caller is not "unskilled-agent drivable".

### 13.5 Three layers in every response, so nobody has to see "ref2va"

| layer | audience | content |
|---|---|---|
| `presentation` | end user / UI | "Animating your photo · 10 seconds · widescreen · with sound". No mode names, no frame counts, no node names. |
| `plan` | reviewer, refiner | the creative decisions in plain language: shots, subjects, dialogue, sound. Editable. |
| `ir` | debugger, reproducer | the full `IRDocument` (§3) plus `mode_decision` and `diagnostics`. |

The UI renders `presentation` + `plan` and never mentions a checkpoint. Developers still get
everything. "No comfy-talk" is met by *layering*, not by withholding.

### 13.6 Refinement is a verb, not a re-run

```http
PATCH /v1/briefs/{id}   { "change": "make it darker and have him say it slower" }
```

This maps straight onto the §8 cache keys: prose-only changes re-render (~11 s); a duration change
replans; swapping one asset re-analyses one card. `POST` takes an idempotency key so a retrying agent
does not duplicate work. Every revision is a new immutable version with its own hashes, so
"the third one was best" is recoverable — that is Higgsfield's refinable-by-reply behaviour, and the
cache design already supports it.

### 13.7 Validator rules are the public error vocabulary

Each rule id (R01–R46) is a stable, documented error code with a human message and a machine `fix`
hint. Most can never reach a caller — the compiler owns labels, so R01/R02/R04 are internal
invariants, and if one ever fires it is our bug, not the caller's. The rules that *are* caller-facing
are only the contradiction ones (R23 illegal cut time, R25 illegal duration, R31 claimed edit with no
source video, R05 over capacity). A small, documented, actionable surface.

### 13.8 Where this layer stops

The "supercomputer" orchestrator — plain brief in, plans, picks models, generates, returns in chat —
is a **caller** of this API, not part of it. Its job: whether to make a video at all, H3 vs LTX vs
something else, and stitching sequences beyond 15 s. This layer's job: **brief → validated IR +
wiring, or a clear refusal.** Keeping that boundary is what keeps both halves testable, and it is
what lets the orchestrator be rewritten without touching the part that knows H3's format.

---

## 14. Style LoRAs: the registry, and where a trigger actually goes

> *"each lora should have an accompanying `howtouse.md`, which the app's 'supercomputer' should be
> able to reach … 'oh ok for this clip I'll also include the lora, plumbing's ready and I know
> exactly the triggers for it'"*

This extends the contract rather than changing it, because a trigger token is **text in the IR**, and
§1 already established exactly what happens to text: it is tokenized byte-exact, appended after every
reference block, and never truncated. A LoRA's trigger is therefore subject to the same discipline as
`<d>` and `<Picture N>` — right bytes, right slot, or it silently does nothing.

**One change to the framing, and it makes the feature safer.** The agent should absolutely be able to
*discover* triggers, but it should not be *responsible* for them. It selects a LoRA by id; the
compiler owns the trigger strings, their casing, their count and their placement — exactly as it owns
`<Picture N>` rather than trusting a caller to type it. Same principle, same reason: a byte-exact
token typed by a caller is a byte-exact token that can be typed wrong. So the agent's job becomes
"this clip wants the Ghibli look" and the plumbing genuinely is ready.

### 14.1 Where the trigger goes, per mode  **[SPEC slot, MINE placement]**

The spec already reserves a style-declaration slot in each mode, and it is the correct home:

| mode | slot | rendered |
|---|---|---|
| ref2va | the style sentence on its own line **before** `[Shot 1]` | `The target video is in hndpntd_anim_v2 hand-painted animation style with soft watercolour backgrounds.` |
| t2va / i2va / fl2va / l2va | the comma-separated style prefix **inside** `[Shot 1]` | `[Shot 1] hndpntd_anim_v2, hand-painted 2D animation, a medium-wide shot frames…` |

The base-mode placement fits without bending anything: the spec's own examples open with a
comma-separated style list (`[Shot 1] Live-action, cinematic, a medium-wide shot…`) and the published
T2VA artifact opens `Cinematic, medium wide shot, pushing in slowly.` — so **the style prefix is
already a list, and the trigger drops in as item one.** **[INFER, from the published artifact]**

Three placement rules, all **[MINE]** and all in the profile:

1. **Once, by default.** Repeating a trigger is a community habit, not a spec, and every extra
   occurrence adds text rows that shift the RoPE origin of every conditioning block (§1.3). `repeat`
   in the registry overrides it when a LoRA genuinely needs it.
2. **Never inside content prose.** A trigger belongs to the clip's style, not to a noun in it.
3. **Never inside `<d>` spans or quoted on-screen text.** Those are verbatim user content (R15) and
   must not be counted as a trigger occurrence or edited to create one.

### 14.2 Collisions — five real ones, with resolutions

**(a) Trigger collides with H3's reserved grammar.** A LoRA whose trigger is `<painted>` matches the
shape R02 exists to reject, and weakening R02 to admit it would reopen the entire dangling-label class
of bug (§7 F1). Resolution: **validate the trigger string at registry ingest**, and refuse the LoRA
with a plain explanation. A trigger containing `<…>`, `[Shot`, `(S1)`, `<d>`, `<scenetrans>` or
`<cutoff>` is genuinely unusable inside this format and cannot be aliased without retraining. That is
a real constraint; better surfaced at ingest than discovered as a silent quality loss.

**(b) Common-word trigger leaks into content prose.** Trigger `watercolor` plus a subject described as
"a watercolor painting on the wall" → the trigger fires twice, once attached to a prop. Detection is
exact: count occurrences outside `<d>` and quoted text; more than declared is R50. The repair is to
instruct the prose stage to avoid the word in content descriptions, which is a solvable instruction
because the prose stage is already constrained.

**(c) Trigger appears in user dialogue.** Excluded from counting by rule 3 above, and never rewritten.
Worth stating because the naive implementation — `ir.count(trigger)` — gets this wrong and both fails
open (thinks the trigger is present when it is only in speech) and risks mutating dialogue.

**(d) Two LoRAs that contradict.** `conflicts_with` in the registry; the resolution stage rejects the
pair with both names.

**(e) Non-English trigger vs the English-body rule (R42).** A registered trigger string is exempt —
it is an opaque token, not prose. **Only registered ones.** That keeps the exemption narrow and makes
the registry the gate, rather than punching a general hole in R42.

### 14.3 `howtouse.md` — front-matter for the compiler, prose for the planner

**My call: both, split strictly by consumer.** Same principle as §4 — *structure is parsed, judgement
is read*. The trigger must survive byte-exact, and prose read by a model is lossy; a planner's
"does this fit the request?" is a judgement and genuinely wants prose. So the deterministic compiler
reads **only** the front-matter, and the planning model reads **only** the body. Never the reverse.

```yaml
---
id: handpainted-anim-v2               # stable identity, independent of filename
name: Ghibli Animation           # label for the presentation layer
kind: style                      # style | subject | motion | quality
target: minimax_h3               # minimax_h3 | krea2 — which model it patches
h3_variant: [ref2va]             # WHICH CHECKPOINT — see 14.4
file: handpainted_anim_v2.safetensors
sha256: "9f2c…"                  # identity of the weights, not the path
version: 2
triggers:
  - text: "hndpntd_anim_v2"      # quoted: casing, underscores, spacing are load-bearing
    required: true
    placement: style             # style | none
    repeat: 1
strength: { default: 0.8, min: 0.4, max: 1.0 }
constrains:                      # null = no constraint
  aspect: null
  duration_frames: null          # or an explicit subset of the legal grid (§3.2)
  steps: null
  canvas: null
conflicts_with: [photoreal-v1]
stacks_with_turbo: unknown       # unknown | yes | no  <- the pipeline engineer fills this in
license: "…"
---
```

Prose body, in this order, because it is read by a model doing semantic matching:

- **What it's for** — in the user's language, not the trainer's: "Studio-Ghibli-like hand-painted
  animation, soft watercolour backgrounds, gentle character motion." This is the text matched against
  a request like *"make it Ghibli-ish"*.
- **When NOT to use it** — negative matching is what stops over-triggering, and it is the section most
  registries omit.
- **Strength guidance** — what actually changes across the range.
- **Known failure modes** — what it breaks (faces, legible text, fast motion). These become planner
  warnings, and at 768p output (§11) a LoRA that damages small text matters more than it would at 2K.
- **Example style openings** — one or two, in IR shape, showing the trigger in its slot.

`stacks_with_turbo: unknown` is how the contract absorbs the pipeline engineer's pending measurement
without waiting for it: the field exists now with an explicit third state, and a profile setting says
whether `unknown` means *allow and flag* or *block*. When the numbers land, they fill a field; nothing
is redesigned. The same is true of `constrains.steps` — if stacking disturbs the step band, that is
where it gets recorded, per-LoRA.

### 14.4 Selection is a compiler stage, and the checkpoint constraint is real

FL2VA and Ref2VA are **two different task-specific checkpoints with their own Omni Transformer
weights** — so a LoRA trained against one is not automatically valid against the other. Hence
`h3_variant`. This couples LoRA selection to mode inference (§12), and the resolution order matters:

> **Capability first, availability second.** The mode is chosen by what the request *needs* (§12).
> If the selected LoRA is not valid for that mode's checkpoint, the layer **surfaces the conflict** —
> it never silently re-routes the mode to make a LoRA fit, and never silently drops the LoRA.

A new stage sits between intake and planning:

```
A   Intake              brief + assets + wiring + proposed lora ids
A'  LoRA resolution     ids -> registry records; legality vs the request; strength clamp;
                        trigger injection plan   (deterministic)
B   Analyse             AssetCards
C   Plan                receives the injection plan as a hard constraint
D   Render              places the triggers in the mode's style slot
E   Validate            proves every required trigger is present, in slot, byte-exact
```

**Discovery for the agent:** `GET /v1/loras` returns id, name, kind, target, variant, constraints and
the *"what it's for" / "when not to use"* prose — everything needed to choose, and nothing that has to
be retyped byte-exact. Selection is then `POST /v1/briefs {"loras": [{"id": "handpainted-anim-v2"}]}`,
strength optional. An agent that omits `loras` gets a good video; an agent that names a LoRA that does
not fit gets a specific refusal.

### 14.5 What the registry records for reproducibility

In `IRDocument.provenance`, returned with the result alongside the seed:

```jsonc
"loras": [
  {"id":"handpainted-anim-v2","version":2,"file_sha256":"9f2c…",
   "strength_requested":0.9,"strength_applied":0.9,
   "triggers_injected":[{"text":"hndpntd_anim_v2","slot":"style","count":1}],
   "registry_revision":"reg-2026-08-10T14:22Z"}
]
```

And it must enter **two** cache keys, not one, because a LoRA affects the render through two
independent channels: the trigger changes the IR *text* (so it is already inside the `prompt` hash),
and the weights change the *sampling* (which the prompt hash cannot see). So the render identity is
`hash(prompt) + lora_set + strengths + seed`. Getting this wrong produces the worst kind of cache
hit — the right text, the wrong weights, and no way to tell from the artifact.

### 14.6 New validator rules

| id | sev | rule |
|---|---|---|
| R47 ⚑ | ERROR | every `required` trigger appears in the rendered IR, byte-exact, the declared number of times, counted **outside** `<d>` spans and quoted on-screen text |
| R48 ⚑ | ERROR | each trigger sits in its declared slot (ref2va style line / base-mode `[Shot 1]` prefix), not buried in shot prose |
| R49 | ERROR | no trigger string collides with H3's reserved grammar — checked at registry ingest *and* at compile |
| R50 | WARN | trigger occurs more often than declared (common-word leak into content prose) |
| R51 | ERROR | the LoRA's `h3_variant` includes the routed mode's checkpoint |
| R52 | ERROR | every non-null `constrains` field is satisfied by the request (names the specific violation) |
| R53 | ERROR | no selected pair appears in each other's `conflicts_with` |
| R54 | WARN | strength was clamped into the declared range (records requested and applied) |
| R55 | ERROR | `stacks_with_turbo: no` while the Turbo distillation LoRA is active; `unknown` is profile-gated |
| R56 | ERROR | the on-disk file's sha256 matches the registry record |
| R57 | WARN | a registered trigger is exempt from R42's English-body rule; an *unregistered* non-English token in the style slot still errors |

### 14.7 New failure modes

| # | failure | why | detected by | consequence |
|---|---|---|---|---|
| F18 ⚑ | **Silent no-op LoRA** — patched into the graph, trigger never reached the text, or reached it with wrong casing, or only inside a `<d>` span | the trigger and the weights are wired by different parts of the system | R47, R48 | full LoRA compute cost, zero stylistic effect, and the output looks merely "a bit off" rather than broken — the hardest failure to notice |
| F19 | **Trigger leak** — a common-word trigger styles a prop instead of the clip | prose stage unaware of the trigger vocabulary | R50 | style applied to the wrong scope |
| F20 | **Variant mismatch** — an FL2VA-trained LoRA on the Ref2VA checkpoint | two checkpoints, one folder | R51 | unpredictable degradation that reads as a bad LoRA |
| F21 | **Silent clamp or silent drop** — strength quietly limited, or a conflicting LoRA quietly ignored | helpfulness | R54, R53 | the user believes a style is at full strength when it is not |
| F22 | **File swapped under a stable id** | same filename, different weights | R56 | yesterday's reproducible render is not reproducible, with nothing in the record to show why |

F18 is the one this whole section exists to prevent, and it is the same shape as F1 (`<Image 1>`): a
pointer that names nothing, costing full compute for no effect.

### 14.8 Two smaller items

**Provenance on machine-generated references — worth a field, and for a better reason than reuse.**
Qwen Image Edit and Krea 2 stills becoming H3 references means the app often *knows* how a reference
was made. Add `asset.provenance {generator, model, source_prompt, parent_asset_sha256,
edit_instruction}`. But the tempting use is the wrong one: **never substitute the generating prompt
for an AssetCard.** H3 conditions on pixels, and a generated image routinely fails to match its
prompt — reusing the prompt is grading the render against its own intention. The prompt goes to the
analyser as a *prior* ("this was generated from: …; correct it against what you actually see").

The real wins are elsewhere: (1) it records the chain, so a render is reproducible end to end;
(2) it carries `composition` (bare plate vs composed scene) for free, which the composed-vs-decomposed
question below needs; and
(3) **it collapses the hardest decision in §12** — when the app generated the still, it *knows*
whether it was made to be the opening frame or a subject plate. That is ground truth where §12.3 was
using language heuristics, and it should short-circuit the anchor-vs-reference call whenever present.

**Composed vs decomposed — not designed, but the seam is prepared, and I have a mechanism to offer.**
`AssetCard.composition: bare_plate | composed_scene | unknown` is recorded now (from provenance when
known, from the analyser otherwise), so when the measurement lands the retention language can branch
on a populated field rather than a new one.

And a falsifiable prediction, **[MINE]**, in case it helps the test: §1.1 predicts *why* decomposed
references would win. A composed keyframe invites a single `fully_preserved` retention line over an
entire frame — which over-constrains everything in it, including the parts that need to move. Bare
plates let each `<Subject N>` carry its own marker, so identity can be `fully_preserved` while the
arrangement stays free. If that mechanism is right, the effect should **disappear when the composed
arm's retention language is loosened** (`partially_preserved` on the scene, per-subject markers on the
subjects) — which is a cheap third arm worth adding to the test, and it distinguishes "composed
references are worse" from "composed references invite over-constraining retention language". Those
have completely different fixes: the first means change the assets, the second means change one line
of the IR. Registered as **U11**.

---

## 15. Build order

Ordered so that each step is independently verifiable and the earliest steps already deliver the
defect prevention that motivates the layer.

1. **Tokenizer + budget utilities, the frame grid, `IRDocument`/`Plan` schemas.** Golden fixtures: the
   three published IRs, saved verbatim to `scratchpad/golden/{t2va,i2va,ref2va}.ir.txt` — the parser
   must round-trip all three byte-for-byte, and the validator must report **zero ERRORs** on all
   three (WARNs expected; exact token counter is `scratchpad/h3tok.py`).
2. **Validator (§6)** against those fixtures **plus deliberately-broken mutants of each** — a rule
   that cannot fail on a mutant is not a rule. Include the maintainer's real prompt as a fixture that must
   fail R02.
3. **Deterministic Plan + Render for Ref2VA** (the only installed checkpoint), template-only, prose
   stubbed. At this point the layer already prevents F1–F12 with no model in the loop.
4. **`Backend` for the inference host** — with the two hard rules from §5.1 baked into the client itself
   (`enable_thinking: false`, and every response checked for `content is None`, `finish_reason ==
   "length"`, JSON parse, and schema conformance). F15–F17 are backend bugs, so they get caught in
   the backend wrapper, once, rather than in each stage.
5. **`AssetCard` for images** (the inference host), then **whisper for audio** (§4.1 — audio's only channel into
   the encoder is text, so this is not optional).
6. **Mode inference (§12)** with its decision record, plus E8's labelled brief set.
7. **LoRA registry (§14)** — `howtouse.md` parsing with ingest-time trigger validation (R49, R56),
   resolution stage, injection into the mode's style slot, and R47/R48 in the validator. Build it in
   this order deliberately: **the validator rule before the injection**, so the first LoRA ever wired
   is proven to have reached the text rather than assumed to have. F18 is invisible otherwise.
8. **The HTTP surface (§13)** — `POST/PATCH /v1/briefs`, `GET /v1/loras`, the three response layers,
   the single clarification with its default pre-applied. Then E9 to prove the agent caller and the UI
   caller get identical IRs.
9. **E7 and E1** — the two experiments that decide whether further verbosity work is justified at
   all. Worth running before investing in prose tuning.
10. **t2va / i2va / fl2va / l2va** once FL2VA weights are installed.

The UI is deliberately last and is not in this list: by §13 it is a client of step 7, and if building
it requires changing step 7, that is the signal that the API was wrong.
