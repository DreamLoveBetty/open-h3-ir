# Working on OpenH3-IR

**This document is for changing the compiler.** Read it before changing anything. It is the set of
rules that are not preferences, a map of which file owns what, and an honest list of what is missing.
There is no install path here, on purpose.

Two neighbours, if one of them is the job instead:

- **Installing it and making it run:** [HANDOFF.md](HANDOFF.md).
- **Calling the service from an application:** [docs/calling-the-api.md](docs/calling-the-api.md).

The project is `open-h3-ir`; the import package and the command are both `h3ir`.

The checks to hold your work against, both reproducible with no model and no GPU: `h3ir controls` is
23/23 in under a tenth of a second, and `pytest -q` is green. The control count is a gate and should
only move when you deliberately add or remove a control. The test count is not pinned here, because it
moves every time anyone adds a test and a stale number reads as a regression.

## What this is and where it runs

A local rebuild of MiniMax H3's closed Context-IR stage. Brief in, validated H3 prompt plus the
asset wiring it is true for, out.

- **Assume the compiler and the GPU are on different machines.** No path or URL is hardcoded
  outside `config.py`, and ComfyUI is always reached over HTTP, never through the filesystem. Keep
  it that way. A filesystem shortcut works on a single box and fails silently everywhere else.
- Reasoning and vision run on whatever `H3IR_LLM_URL` points at. Nothing calls MiniMax.
- `h3ir doctor` tells you what is actually reachable before you debug anything else, which liveness
  path answered, which model it will send to and why, and whether that model can read a picture.

## The rules that are not preferences

1. **Never let a model decide structure.** Labels, label order, speaker IDs, cut times, retention
   markers, task-type prefixes and section order are computed in `plan.py` and emitted by
   `render.py`. If you find yourself adding a structural instruction to a prompt file, the fix
   belongs in the planner instead. On the write-first path the model types the whole document, so
   the two structural things it can still get wrong are corrected in `repair.py` before anything
   validates it: the label ordinals, and the task-type prefix. Both are re-derived, not checked,
   and `M16` sits behind the prefix in case there was none to replace.
2. **The user's words never pass through a model.** Dialogue reaches the output through
   `{{D1}}` placeholder substitution in `render.py`. If you change that path, `D4` will catch you.
3. **Never trust the endpoint's structured output.** It is documented in `backend.py` with the
   measurements: `json_schema` is silently not applied while reasoning is on, and even with it off
   the grammar constrains shape but not completion or sense. Parse and re-check everything.
4. **Never degrade silently.** If the model is unreachable the service raises. A caller cannot
   tell a good IR from a bad one, so quietly producing a worse one is the failure nobody notices.
5. **Nothing ships on judgement.** See below.
6. **The deterministic draft is the product floor, not a degraded mode.** `draft.py` builds a
   complete valid IR with no prose model. The LLM pass is additive. Any validator error, leaked
   reasoning, or model outage falls back to the draft, so the caller always gets something valid.
   The draft failing its own validator is the one thing that raises, because it is deterministic
   and there would be nothing to fall back to. Do not turn this back into retry-until-valid.
7. **Thinking is per call, not global.** ON for the beat sheet (planning: measured +5.3pp), OFF
   for extraction, classification and prose (precision: measured −8.5pp). This is contingent on
   code owning every machine-checkable field. If you ever let the model emit a timecode, turn
   thinking off for that call.
8. **Never enable guided decoding without re-reading why it is off.** vLLM #39130 can skip grammar
   enforcement silently with a reasoning parser active; llama.cpp #20345 reports the converse on
   this model family. `H3IR_GUIDED_DECODING=1` exists for comparison, not for production.
9. **The model is deaf. Never ask it about audio.** `analyse_audio` makes no model call. Audio
   facts are typed metadata plus a real transcript. An invented timbre is worse than none because
   `<Audio N>` carries no content into the encoder, so the IR text is its only channel.
10. **Proportionality is part of the bar, and it is an explicit input.** "If I ask for simple, I want
    simple, if I say go crazy, I want crazy." `brief.creativity` is `restrained | balanced | bold`,
    default balanced, and it governs exactly one thing: whether the writer may add **content the
    request never supplied**: a spoken line, a score, on-screen text. It does NOT mean "more shots"
    or "more camera moves"; putting effort on this dial would be shot-count-as-a-rule one layer above
    the validator, where nothing catches it. Never infer the setting from the request. That was
    considered and rejected, because it would be wrong often and the maintainer could not overrule it. An
    explicit prohibition in the request outranks every position: `bold` on "No dialogue" licenses no
    dialogue. See `creativity.py` and design doc section 19.
11. **The request beats the references beats the director, and the ladder is COMPUTED where it can
    be and STATED where it cannot.** `licence.py` resolves every attribute to the request or to a
    reference, per attribute, and `compose_brief` states that resolution in the ask. A director
    profile occupies the residual that block ends on -- "anything neither the request nor the
    references settles is yours" -- and it is prose, not a schema: a name and a paragraph the caller
    wrote, placed *underneath* the licence block and the creativity dial with a head that says it
    overrides neither. That is the owner's shape and it is deliberate: **"not mechanically enforced,
    just steered"**. Nothing in `director.py` narrows a rotation, suppresses a sentence or refuses a
    word.

    So the thing to protect is not a checker, it is that **structure stays uninfluenced** (rule 1).
    Shot count and cut times are the caller's contract when they pin `shots` -- stated in the ask,
    `T11-shot-count-pinned` as an ERROR if the document disagrees -- and the writer's when they do
    not, which is what `auto` has always meant. The deterministic floor in `draft.py` never sees a
    profile at all, and `tests/test_director.py` proves it by compiling the same request twice.
    One place the two controls touch: when the dial licenses no score the block says so out loud,
    because a profile describing music that cannot exist is a contradiction *we* placed in the ask
    -- the trap `Scope.brief_instruction`'s docstring records, arriving from the other direction.
12. **A rule asserts a decidable fact, never a preference.** The test: could a competent director
    disagree with it? If they could, it is not a check, at any severity. Shot count is not a
    defect. Prose quality is not a defect. Whether an edit is good is the maintainer's call and the
    validator has no access to it. Where a spec sentence constrains something discretionary, narrow
    the rule to its decidable residue and hold it at **WARN**, because **ERROR is what the fix loop
    sends back to the model** and a rule that can be argued with must never instruct a rewrite.
    Section 18 of the design doc records the audit that established this and every rule it changed.
    Before adding a rule, name its source: a spec line, a measured fact about the model, or a
    decidable property of the text. "It looked wrong to me" is not one of the three.
13. **"OpenAI-compatible" names the chat route and almost nothing around it.** Ollama serves no
    `/health` and its model objects carry four keys; vLLM publishes `max_model_len` and a `root`
    that makes two ids one model; a gateway can serve chat completions and no model list at all. So
    a field read off an endpoint needs the server that publishes it named, and the servers that do
    not publish it handled. The first outside bug report was three symptoms of one fact: this had
    only ever been run against one box. Every place that has to know the difference lives in
    `backend.py`, and `tests/test_endpoint_portability.py` pins each one against replicas of what
    those servers actually return. Nothing above `backend.py` may grow a second such place.

    Two of them generalise past this file. **A capability the model list does not report must not
    be guessed:** no server says which of its models has a vision tower, so an endpoint serving
    several is a refusal that names them, never a pick, and `doctor` answers the question by
    reading a generated picture through the model rather than by inspecting metadata that does not
    exist. **And a setting nobody sends is a setting nobody has:** `H3IR_LLM_KEY` was configuration,
    documentation and dead code at once for as long as the only endpoint here wanted no credential.

## Changing a prompt or a template

Prompt text lives in `h3ir/prompts/*.txt` as versioned files precisely so a change is an artifact you
can score. The loop is:

```bash
h3ir controls                                  # must be 23/23 before anything else
h3ir eval --label my-change --prose prose_shot.v3.txt
# read the gate; if SHIP-ABLE:
h3ir baseline --label my-change
```

This is not ceremony. It has already caught a change of mine that improved the metric I was
aiming at while introducing validator errors, and the root cause turned out to be a latent bug
rather than the prompt. Assume your next confident improvement is the same.

**Do not add a control exception to make a rule pass.** MiniMax's own published example is the
control; if a rule fires on it, the rule is wrong. That is how the 350-word floor and the closed
camera vocabulary became guidance rather than law, and later the shot-citation check, which
fired on their example because a persistent setting legitimately is not re-cited every shot.

**A metric reads the artifact that SHIPS, never an intermediate.** In the write-first path `doc.plan`
is the *deterministic draft's* plan (the model's prose never goes back into it), so anything reading
`plan.shots` is scoring an object that was thrown away, and it fails silently: the number is
plausible, nothing raises. Three fields were caught doing it in one evening (`restatement` reporting
1.00 on visibly different shots, `n_shots` reporting 4 against 0 timed cuts, and `_split_written`
dropping the whole description), plus a fourth in a script written *after* the other three were fixed.

**Second half of the same rule: measure it in the CONFIGURATION that ships.** A harness knob whose
default is anything other than production's turns every run into a truthful report about a pipeline
nobody uses. `RunConfig.compose_prompt` defaulted to an explicit composer name, overrode the mode
selection, and reported `clean_rate` 0.167 where the real figure is 1.000. Harder to catch than the
first half, because a wrong-configuration run is internally consistent.

**And read the artifact back; never trust the code that wrote it.** Four faults found this way,
including the provenance record that was written to say which pipeline produced a result and recorded
neither. The field was on the dataclass and missing from the serialiser, and the writing code read
perfectly.

**So: "the number moved" is not evidence until you can name the artifact that produced it.** When you
add a metric, name a second field it must agree with and check the pair. That is what caught all four,
and no test caught any of them. `n_shots` vs `n_timed_cuts` must satisfy `shots = cuts + 1` because T4
enforces it; `restatement` near 1.0 contradicts `shot_distinctness` near 1.0; `words = 0` contradicts
`errors = 0` because S9 and T1 would both fire. Design doc §24.

**Falsify every test you write. It is not ceremony. It is what distinguishes a test from a
comment.** Break the code the test covers, on purpose, and watch it go red. Two tests passed a
deliberate break in one evening, and the two failure modes are different, so know both:

- **A fixture that cannot discriminate.** The video frame-distinctness test used a clip generated from
  a `drawbox` expression that silently rendered nothing, so all three frames were identical 1604-byte
  images. The assertion compared them and passed. Fixed by using `testsrc`, whose frames must differ.
- **A cache short-circuiting the code under test.** Breaking `VIDEO_FRAME_FRACTIONS` to `(0.5,0.5,0.5)`
  left the test green because frames from an earlier correct run were already cached under that key.
  The cache answered, not the sampler. Fixed by keying the cache on the fractions AND giving the test
  its own key.

**A cache keyed on its inputs but not on the logic that transformed them will serve stale results
across a code change and look correct.** That is what `ANALYZER_VERSION` is for, and it has now been
needed three times (pose split, video frames, audio characterisation) plus once for frame fractions.
**If a compiled brief is ever cached, the prompt version belongs in the key**, because the compose prompts are
the transforming logic and they change more often than anything else here.

**A passing control is not proof of correctness.** The rule L5 arrived here as a false positive:
it flagged every standalone `<Picture N>` line, while the spec forbids them only when the label is
not separately analysed. It passed the official control the whole time. When you write a rule, also
write the input that must NOT trip it. `test_hardening.py` has four such cases for G2 alone,
because my first draft of that rule fired on "he gives an okay sign".

## Where things are

| file | what it owns |
|---|---|
| `config.py` | every host-specific value. Nothing else may hardcode one. |
| `grid.py` | the 17k+5 frame grid and all duration maths. `effective_seconds` vs `nominal_seconds` is a real distinction, so read the docstring. |
| `tokens.py` | exact token counts using H3's own vocab (vendored under `h3ir/data/`). |
| `models.py` | the contract. Every stage boundary is a dataclass here. |
| `backend.py` | the LLM client, the three silent endpoint failures, and every difference between one OpenAI-compatible server and the next. |
| `analyse.py` | AssetCards, cached on content hash. Audio needs a transcript, see below. |
| `mode.py` | which of the five modes, and how it fails safe. |
| `lora.py` | the registry, `howtouse.md` parsing, ingest-time trigger validation. |
| `plan.py` | all structure. The four solved problems live here. |
| `prose.py` | the only two places a model writes anything. |
| `render.py` | deterministic rendering. Must be byte-reproducible. |
| `validate.py` | the rules. Proved by `evalloop/controls.py` in both directions. |
| `compile.py` | the orchestrator and the stage order (with the reason for that order). |
| `director.py` | the third authority: whose taste fills what neither the request nor the references settle. A name and a paragraph, the seven that ship, and the one cap. |
| `service.py` | the HTTP surface and the three response layers. |
| `uploads.py` | the content-addressed store behind `PUT /v1/assets/{sha256}`: the digest is computed as the bytes arrive, the ceilings and the age limit come from `config.py`, and eviction is least-recently-used. Write-only by design, so every other method on an asset is a 405. |
| `comfy.py` | ComfyUI over HTTP; graph prompt substitution that refuses to guess. |
| `acceptance.py` | the five-arm comparison, built without touching the GPU. |

The ComfyUI pack in `comfyui/` is six Python files plus a `web/` folder of four JS files, and imports nothing from `h3ir`:

| file | what it owns |
|---|---|
| `h3ir_client.py` | the service protocol, the option lists, the report. No ComfyUI, no torch, no third-party packages. |
| `media.py` | tensors and mappings to files on disk, content-addressed. No ComfyUI at module scope. |
| `nodes.py` | the four node schemas -- Main, Media, Setup and the optional Director -- the model loaders and the socket-to-file mapping. This is the only file that needs a canvas. |
| `web/director.js` | the Director panel, and a verbatim second copy of the seven profiles, the twenty camera moves and the cap. See below. |

**Media and Director each carry a DOM board; Main and Setup are widget nodes** the theme draws, with
`prompt.js` putting an @ picker over Main's sentence. All of it is decoration in the strict sense:
each node's real state is ordinary widget values, and the two boards edit ONE string each -- the
tray's JSON on Media, the direction's on Director. Delete `web/` and every node still works, still
API-drives and still restores from a saved workflow, with the strings visible as themselves.

**The Director's stored directions are the pack's only piece of state outside a graph, and they are
deliberately outside the compiler.** They are files in ComfyUI's own per-user store,
`user/default/openh3ir/directors/<name>.json`, each holding exactly the two keys the node's field
holds, written and deleted through the `/userdata` routes ComfyUI already serves. The compiler's
service was the other candidate and it lost on three counts: it may be on another machine or down,
which would empty the list exactly when somebody is writing in it; it would have needed new write
routes on a service that binds `0.0.0.0`; and none of it buys anything a graph needs, because **a
graph carries the words, never a pointer to a name**. Nothing in `nodes.py`, `h3ir_client.py` or the
service knows the store exists, and that is the property to keep: delete `web/` and every stored
direction becomes irrelevant rather than missing.

**The seven that ship are a SEED, not a menu**, and that is the owner's shape: "just preload the
list with them, they should be able to be removed too." On first use `director.js` writes them into
that store as ordinary directions, and from then on the list is simply what the store holds. There
is no shipped category, no protected name, and no branch anywhere that recognises one — which is
what makes rename and delete work on them with no special case, and `tests/test_director_panel.py`
pins `DIRECTORS` to exactly two readings in the file, its declaration and the seed. **Seeding is
keyed on the FOLDER not existing**, because that is the only state meaning "never used": deleting
every direction leaves the folder, so a removed one stays removed. Deleting the folder by hand is
therefore the documented way to get the seven back, and the only way, on purpose.

`OpenH3IRDirector` takes one input, `profile`, and hands down one `H3IR_DIRECTOR` bundle. Main's
`director` socket is optional, and a graph without the node steers exactly as it always has. **That
absence is the default and it is load-bearing**, so anything that makes the node's presence matter to
a graph that does not have one is a bug. There is no `none` on it for the same reason: the node IS
the choice, and unplugging it is the absence of the only one rather than a third state.

### The seven directors are written down twice, and the copy is checked

`h3ir/director.py` is the authority: it is what the compiler sends to the writer, what
`h3ir directors` prints, and what `GET /v1/directors` publishes. `comfyui/web/director.js` carries a
verbatim copy, because the pack imports nothing from `h3ir`, the compiler is usually on another
machine, and a text box that needs a running service before it can show you a paragraph is a text box
that is empty exactly when somebody is trying to write in it.

The panel writes that copy straight into the node's field, so a drift between the two is not
cosmetic: it is a graph that compiles a different director from the one the canvas said it loaded,
with nothing anywhere to say so. Three things are duplicated and all three are checked -- the seven
texts word for word, the twenty `CAMERA_MOVES`, and `MAX_NOTES_CHARS` against the panel's
`MAX_NOTES`. `tests/test_director_panel.py` fails if any of them moves on one side only, it also
checks that the panel still binds to a widget called `profile`, and every scan in it asserts that it
found something first, because a regex that quietly stops matching is a test that passes forever.

**So editing `h3ir/director.py` is not finished until `director.js` says the same words.**

## ComfyUI frontend mechanics, measured rather than assumed

Four of these cost a rebuild of the node surface to discover. They are recorded so nobody re-derives
them, and each has a test in `tests/test_comfyui_schema.py` that fails if the surface stops respecting
it. Measured against `comfyui_frontend_package 1.48.7` and `comfy_api/latest/_io.py`.

- **`advanced` is not a hide.** The per-node expander exists only under Nodes 2.0 and is gated on the
  setting `Comfy.Node.AlwaysShowAdvancedWidgets`. Under the legacy canvas renderer it does nothing at
  all. Design as if every input is visible; treat the collapse as a bonus.
- **A label and its value share one row of about 38 characters.** So a long display name makes both
  unreadable. This is why every label in the pack is one or two words.
- **A multiline STRING with no placeholder prints its own input id** on the canvas:
  `addMultilineWidget` calls `createMultilineInputElement(default, placeholder || name)`. On a
  multiline widget the placeholder is the only label there is, so it has to be the label and the
  example at once and its first line has to stand alone under truncation. A **single-line** STRING's
  placeholder is not drawn at all on the legacy canvas, so there the display name carries everything.
- **Autogrow socket labels come from `names[ordinal]`, or from `prefix + ordinal` zero-based, and they
  overwrite whatever the template declared.** `autogrowOrdinalToName` returns
  `{name, display_name: s}` and `s` wins. So `TemplatePrefix` gives you `reference_0` on the canvas no
  matter what the template's `display_name` says, and `TemplateNames` is the only way to get one-based
  readable labels. Ids with a space in them (`pictures.picture 1`) round-trip through the API format
  and the workflow save without trouble; verified by running one.
- **The frontend already supports several inputs per grown item** (`inputSpecs` is a list and
  `ensureWidgetForInput` runs when its length is not 1), but the Python side takes a single template
  input and `_expand_schema_for_dynamic` reads only the first. That is the mechanical reason the
  picture notes are one positional block and a clip's role lives on a satellite node, not a preference.
- **An AUDIO is a Mapping, not necessarily a dict.** Load Video (Upload) hands out a `LazyAudioMap`
  that shells out to ffmpeg on first key access. `isinstance(audio, dict)` refuses it.
- **A DOM widget's wrapper follows `widget.width`, and the frontend rewrites that on every value
  change.** The Vue side patches the wrapper's inline style each render from a node layout pass, and
  what that pass computes is the node's *content* width, not the node box. Measured: choosing a
  director set `width` to 238 on a node that was still 480 wide, the panel's wrapper went to 218px,
  and the name field was squeezed to eleven pixels -- `Denis Villeneuve` drawn as `De`. It never
  recovered at any node size, and no `computeSize` on either the widget or the node changes it,
  because neither is what the wrapper reads. `width` unset is the state a widget starts in and the
  one that renders full-bleed, so a board that fills its node holds it there:
  `Object.defineProperty(w, "width", { get: () => null, set: () => {} })`. The media tray never hit
  this because it pins its node to one size; anything resizable has to say it.

## Proving a change is live in a running ComfyUI

**A ComfyUI install holds a COPY of this pack, not this checkout.** `custom_nodes/openh3ir` is a
directory somebody copied there; nothing links it to the tree you are editing unless somebody made a
link, and `dir /AL` (or `ls -l`) is how you find out rather than assuming. So a change you make here
is live in a running ComfyUI only after you have put it there.

The two halves fail differently, and the difference is what makes this a trap rather than an
inconvenience:

- **`web/*.js` is served from that copy on every page load.** So fetching
  `/extensions/openh3ir/tray.js` and diffing it against the tree is a real check of what the browser
  is running -- but a match proves only that the two files are equal right now, which is also what
  you see when somebody synced it an hour ago. It is evidence about the file, never about a link.
- **The `.py` files are imported once, at ComfyUI startup.** A copied-in change does nothing until
  the server restarts. This is the half that goes stale silently: the panel offers a new option
  because the JavaScript is current, the user picks it, and the queue refuses it because the Python
  is five days old.

Measured on 2026-08-20: the served `tray.js` matched this checkout byte for byte while `tray.py` in
the same install was five days behind, and the conclusion drawn from the first fact was that the
whole pack was live.

**The cheap read-out is the pack's own refusal.** Set the tray to whatever the change makes possible
and queue the graph. If the running Python predates the change, the node refuses it with the OLD
table's own sentence, naming the options it still believes in, and the failure lands on the Media
node before a model is loaded, so it costs no GPU and no minutes. A refusal quoting the state you
just left is the running process telling you which file it is holding, which is the same discipline
as reading the artifact back instead of trusting the code that wrote it.

**And there is one that costs no queue at all: ask the server for its own node table.**
`GET /object_info/<NodeId>` is built from the `.py` the process imported at startup, so it is the
schema the canvas is actually drawing. Diff it against `define_schema` in the tree and a stale import
is one read away, before anybody opens a browser.

Measured on 2026-08-21, and it is the same trap from the other end: `comfyui/nodes.py` in the install
was byte-identical to this checkout -- every file was, `web/` included -- while
`/object_info/OpenH3IRDirector` answered with a twelve-field schema from an earlier session, a
`director` combo with `none` in it plus `moves`, `avoids` and a save/load `library`, none of which
exist in the file either copy holds. Equal files on both sides of a copy and a running process three
hours behind them. The `.pyc` timestamps under `custom_nodes/openh3ir/__pycache__` said the same
thing and are the other cheap tell: older than the `.py` beside them means the import is stale.

## Known gaps, honestly

- **The committed sample media cannot be rebuilt.** The two comparisons in `docs/media/` were
  produced by hand. Deferred on purpose, to be done only when the compiler improves enough to be
  worth re-shooting the samples, and only if it is. The risk being accepted is that the clips
  silently become evidence of an older version while the front page still claims a difference.

  The recipe survives without a script, which is why deferring is safe: both compiled briefs ship
  beside the clips, both reference plates ship, the dial command is in the README, and the seed and
  render settings are in the commit that added them.

  If it is ever written it cannot live in CI, because it needs ComfyUI with H3 loaded and a live
  endpoint. And it would not reproduce the same clips: renders are not identical across model or
  driver versions, so the check is whether the claim still holds, not whether the pixels match.

- **The style-LoRA registry is read but not usable end to end. `--lora` crashes, both ways.** TODO,
  deliberately deferred: proving this out needs the application that consumes it to exist first, so
  it can be tested against real weights and a real render rather than against a placeholder.

  What works: the registry loads a folder correctly and `h3ir loras` reports id, triggers, strength
  bounds, variants, conflicts and the author prose. `GET /v1/loras` serves it.

  Two separate defects behind that, and they fail differently:

  ```
  # variant mismatch, raised as an internal invariant instead of told to the caller
  h3ir compile "a fox in tall grass" --lora handpainted-anim-v2
  -> CompilerInvariantError: W11-lora-variant: handpainted-anim-v2 is trained for
     ['ref2va'] but this request routes to the fl2va checkpoint

  # variant matches, and the trigger splice produces text the validator rejects
  h3ir compile "the car rolls in" --image plate.jpg --lora handpainted-anim-v2
  -> CompilerInvariantError: R16-style-opening-malformed: a spliced clause keeps its
     capital mid-sentence ('with Hi'):
     'The target video is in hndpntd_anim_v2 style with High-contrast automotive...'
  ```

  The first is the validator being **right** and the handling being wrong: asking for a ref2va-only
  style on a request that routes elsewhere is a real user error and deserves a sentence saying so,
  not an invariant crash. The second is a genuine text bug: the trigger is spliced into the style
  opening without lowercasing what follows.

  And the part nobody has built at all: **nothing matches a request's own words to a registered
  style.** The owner's intent was that mentioning a look in plain language pulls the LoRA in and says
  so. Today only an explicit id does anything, and `"hand-painted animation look"` in the request
  text is ignored. `docs/design.md` and `docs/calling-the-api.md` both expose the surface, so an
  agent will discover styles and try to use them before this is fixed.

- **What a video EDIT can and cannot hold, measured on the released weights.** Twelve renders on
  a 5090, 20 steps, `res_multistep`, against a 124-frame source clip and the same
  clip as `<Video 1>`. H3's ref2va path takes the reference video as conditioning latents beside a
  fresh empty target latent — it is a re-generation, not an in-place edit — and that is visible in
  the numbers:

  | what survives | how it measures |
  |---|---|
  | the subject's identity, and a requested change to it | the edit lands; a blue shirt asked for is blue |
  | the timing of the action | motion-curve correlation 0.58-0.80 against 0.06 for an unrelated clip |
  | the exact framing over time | NOT held. Nearest-source-frame agreement 0.20-0.27 against 1.00 for the clip against itself and 0.14 for an unrelated clip |

  So "the same clip with one thing changed" is honest about the beats and the subject, and is not a
  frame-locked edit. A brief that promises a frame-for-frame match is promising something these
  weights do not do. The two gauges and their controls are worth rebuilding rather than trusting a
  single number: the first gauge tried here correlated greyscale frames directly and scored 0.90 on
  a SHUFFLED pairing, because the scene barely moves and the background is most of the picture.

- **A video card reads three frames, so it cannot name a camera move.** `camera` on the card is the
  VLM's plain-words reading of how the framing changes across those frames ("the framing tightens
  slightly on the subject"), and never a member of `CAMERA_TYPES`: three stills cannot separate a
  Push In from a Zoom In, or a Pan from a Truck, and a confident wrong answer about a clip the
  writer is told to preserve is worse than none. When it comes back `unknown` the ask says so out
  loud and forbids a camera sentence, because silence measured as "static camera" in 3 of 4 seeds.
  The extension point is a real camera classifier over more frames; the honest floor is here.

- **Audio references have no transcript source wired in.** `analyse_audio` accepts a transcript
  and the plumbing for it exists, but nothing calls whisper yet. Until it does, an attached audio
  reference is described from the caller's note alone. This matters more than it looks: the
  tokenizer emits `"<Audio j>: "` and nothing else, so the IR text is the *only* channel by which
  the conditioning encoder learns what that audio is. Wire whisper before shipping audio refs.
- **Video references now sample real frames**, at 10/50/90% of the clip, cached on content hash
  **and** on the fractions. `ffmpeg`/`ffprobe` are hard runtime dependencies of video references, not
  conveniences. The analyser raises rather than producing a card. Audio still has no transcript
  source wired in, so an attached audio reference is still described from the caller's note alone.
- **`refine()` re-runs the whole compile.** The cache keys make a prose-only refinement cheap in
  principle, but the fast path is not implemented. It re-analyses nothing (cards are cached) but
  does redo the beat sheet and all prose.
- **The eval suite is six briefs.** Enough to catch the regressions we have seen; not a broad
  quality benchmark. Add briefs when a new failure mode appears, not preemptively. It is also the
  only thing that found the mode-split bug below, and it found it the first time it was ever run
  end-to-end on the write-first path. Five of six briefs were falling back and no single-brief test
  could see it, because the one brief anybody had been testing by hand was the ref2va one.
- **One prompt per mode, and check that when you add a stage.** `compose.v2.txt` carries the
  full-reference guide; `compose_base.v1.txt` carries the base guide. `compose_prompt=None` picks by
  mode and that is the right default. Passing an explicit name overrides the choice for BOTH modes,
  which is what you want for an A/B and never what you want in production.
- **Thinking ON costs about 45 s on the planning call** versus ~5 s off. Whether it earns that is
  an open A/B, not a settled question; the eval loop is how to answer it.
- **`camera_style: "prose"` renders no camera sentence at all.** It exists as the A/B arm for
  "does the closed vocabulary matter"; it is not a finished alternative rendering. Do not ship it
  as a user-facing option until the A/B is run and the losing arm is either fixed or removed.
- **LoRA weights are never loaded here.** This layer plans the trigger injection and records what
  was chosen; patching the graph is the graph owner's job.
- **`compose.v3.txt` is written but not the default.** It differs from v2 in exactly one paragraph:
  the "decide the edit" instruction, which in v2 ends *"and it is the worst outcome available"*:
  invented severity on a discretionary call, the same fault the validator audit removed from the
  rules. v3 states the spec's sentence instead. It is not the default because the arm5/arm6 pair
  (same pipeline, direct vs not) was generated against v2 and flipping the default mid-comparison
  changes two variables at once. Switch with `--compose compose.v3.txt`, score it, then promote it.

## The acceptance comparison

```bash
h3ir acceptance --image-a character.png --image-b creature.png --out acceptance/
```

Writes five prompt files, a wiring manifest for each, and a README explaining what each outcome
would mean. It does not submit anything. Arm D is the control that decides whether the labels
bind or the position does. Do not drop it, because without it a difference between arms A and B
has two explanations.
