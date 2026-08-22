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

**And a test that has never been seen failing is a test nobody has verified.** This suite shipped one
that was green for its whole life while the field it guarded was dropped in transit, so every check
holding the compiler and the pack together has a defect written for it in
`research/contract_falsification.py`: it plants the defect, proves the defect is live, runs the test
that claims to catch it, and puts the file back. Run it on a clean tree; 13 cases here, all of which
must go red. The other 36 are the node pack's, in its own copy of that file, and neither list is
complete on its own: a guard over there is falsified over there, against the compiler it has
installed.

**It reports three outcomes, not two, and that distinction is the file's second draft.** RED is a
guard that fired. GREEN is a guard that did not. BROKEN is a case that never ran -- the anchor
moved, the write did not land, the edit made the module unimportable, or the test it names no
longer exists. The first draft printed the same thing for GREEN and BROKEN, and two cases hid in
that: one named a test that had been renamed, and one planted an unbalanced parenthesis. pytest
exits non-zero for a `SyntaxError` and for an unknown node id exactly as it does for a failing
assertion, so both printed RED for months of nothing. **Anything that plants defects has to prove it
planted them before it is allowed an opinion about the guard.**

Two traps it records rather than works around, because anything editing source in a loop will hit
them:

  * **Python validates a cached `.pyc` on (mtime, size) and mtime has one-second resolution.** A
    defect exactly as long as what it replaces, planted within a second of the restore before it,
    runs against the OLD bytecode. Five cases reported a guard that does not fire before
    `__pycache__` was wiped between them.
  * **`python -O` strips `assert`.** The first draft checked its anchors with one, so under `-O` a
    moved anchor became a silent no-op: nothing was edited, the test passed on untouched source,
    and the case printed GREEN. Nothing in that file uses `assert` any more.

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
| `contract.py` | everything that crosses to a client: the wire field names, the roles per kind, every refusal code, the seven directions, the camera table and the limits. Built from the authorities, never restating them. Published by `GET /v1/contract`, by `h3ir contract`, and by import. |
| `service.py` | the HTTP surface and the three response layers. |
| `uploads.py` | the content-addressed store behind `PUT /v1/assets/{sha256}`: the digest is computed as the bytes arrive, the ceilings and the age limit come from `config.py`, and eviction is least-recently-used. Write-only by design, so every other method on an asset is a 405. |
| `comfy.py` | ComfyUI over HTTP; graph prompt substitution that refuses to guess. |
| `acceptance.py` | the five-arm comparison, built without touching the GPU. |

The ComfyUI node pack is its own repository, [ComfyUI-OpenH3-IR][pack]. It depends on the published
`open-h3-ir` package, it carries no copy of the compiler, and nothing in this repository imports it
or reads its files. What used to be written out here -- the pack's own file table, the store its
directions live in, the ComfyUI frontend behaviour measured rather than assumed, and how to prove a
change is live in a running ComfyUI -- moved with it, into `AGENTS.md` there.

What stayed is the half this side owns: `h3ir/contract.py`, what it publishes, and why every literal
in it is pinned by `tests/test_contract.py`. Read on.

[pack]: https://github.com/ruashots/ComfyUI-OpenH3-IR

### What crosses to a client, and how drift is made loud

`h3ir/contract.py` is the compiler's statement of everything a client has to agree with it about,
and it is the answer to a problem the two halves of this repository are about to have: they ship to
two audiences, they are becoming two repositories, and a test that opens the other half's source
file and reads it as text cannot exist after that.

**The pack becomes an all-in-one, so IN-PROCESS is the ordinary case.** A ComfyUI user installs the
pack, points it at their own language model, and works: no service to start, no port, no second
process. The compiler runs in the same Python ComfyUI runs, out of the installed `open-h3-ir`. HTTP
stays for a compiler on another machine and stops being the normal way in. The two are still
installed separately and still drift, which is exactly why the contract is not an HTTP thing --
in-process there is no round trip to reveal a mismatch at all.

**Read off the authority wherever there is one.** The roles come from `Role`, the profiles and the
camera table from `director.py`, the ceilings from `grid.py` and `shots.py`. Two lists are literals
and both are pinned by `tests/test_contract.py` from this side, where the thing they describe is
importable: the wire field names, which live on pydantic models `contract.py` may not import because
a client runs it inside ComfyUI's Python; and the refusal codes, which are raised across two files.

**`CONTRACT_VERSION` is not the package version**, and `test_the_version_moves_when_any_part_of_the_contract_moves`
holds a digest of every section against it. Changing a director's prose without bumping it is a red
test. That is the whole ceremony and it is what stops the number becoming one nobody maintains.

**An unknown field is refused, never dropped.** `AssetIn` and `BriefIn` set `extra="forbid"` and a
handler turns that into `code: unknown-field` naming the key. pydantic's default is to ignore it,
and that default cost this project a real bug: see below.

#### The seven directors are still written down twice, and the copy is now generated

`h3ir/director.py` is the authority. The pack's `web/contract.data.js` carries the copy, for the reason
it always did -- the pack may be talking to another machine, and a text box that needs a running
service before it can show you a paragraph is empty exactly when somebody is trying to write in it.

What changed is that nobody types the copy. `h3ir contract --js` writes that file, `director.js`
imports `DIRECTORS`, `CAMERA_MOVES` and `MAX_NOTES` from it, and
`tests/test_contract_drift.py::test_the_generated_copies_are_what_this_compiler_publishes`
regenerates both copies and compares them byte for byte. So the instruction that used to be here --
*editing `h3ir/director.py` is not finished until `director.js` says the same words* -- is now:

```bash
h3ir contract       > contract.json          # run in the node pack's repository
h3ir contract --js  > web/contract.data.js
```

Eleven thousand characters of prose maintained by hand in two languages is drift with a schedule.
After the split that test runs in the pack's repository against the `open-h3-ir` it depends on,
which is a better comparison than a sibling working tree: it holds the pack against the released
compiler.

#### Assert about the payload, never about the source text

Two of the three cross-boundary tests were guarding the wrong hop, and one of them had been wrong
for its whole life. `tests/test_swap_roles.py` asserted that `nodes.py` contains the line
`extra["replaces"] = slot.replaces` and that `AssetIn` declares a field called `replaces`. Both were
true. In between them, `h3ir_client._asset_facts` copied four keys out of `extra` into the request
and this was not one of them.

So the words a user typed to say who a picture takes over from never left the machine. The panel
collected them, `check_swaps` refused a swap that named nobody, the service declared the field, and
the compiler knew what to do with it -- and what the user got was the compiler refusing a question
they had already answered, or a swap bound to whoever the analyser happened to find in three sampled
frames. The test was green throughout, because it compared two pieces of source text and never
looked at the request.

`h3ir_client.payload_shape` runs the very functions that build the request and reports what comes
out. Anything asserting about what crosses uses that. A description of a payload taken from anywhere
else can be true while the payload is wrong.

#### Asking the compiler that is actually going to do the work

Two ways to get the live contract, and the choice is the caller's:

| where the compile happens | how to ask |
|---|---|
| the same Python, from the installed package | the pack's `contract.installed_contract()` |
| a service on another machine | `h3ir_client.fetch_contract(server)` |

**Never merge them or fall back from one to the other.** Reading the local package's contract while
compiling against a remote service compares this machine's version to another machine's work, and
refuses graphs that are fine. The compile node talks HTTP today, so it asks over HTTP, and a test
fails if it starts reading the local one.

**The compiler import is lazy, and stays lazy.** The old rule was "the pack imports nothing from
`h3ir`", which was right while the nodes only spoke HTTP and is wrong for an all-in-one. What
replaces it is narrower and still load-bearing: no `h3ir` import at module scope anywhere in the
pack, and exactly one function that does it at all. ComfyUI takes a pack whose import raises off the
menu entirely; a pack driving a remote compiler needs no local package; and the compiler brings
fastapi, uvicorn, pydantic and tiktoken, which have no business being pulled into ComfyUI's Python
on every start for a graph that may never compile. `installed_contract` answers None for absent,
broken and half-installed alike, because a client never fails on the CHECK.

#### What an in-process caller does NOT get for free

Measured, with fastapi and pydantic blocked: every compiler module imports except `service.py`.
That one holds `_to_brief`, the only conversion from a request into a `Brief`, and the eleven
refusals it raises along the way -- role resolution, the unknown-role message, the soundtrack
pairing, the upload checks.

So an in-process caller has two options and both cost something. Reuse that conversion and fastapi
comes into ComfyUI's Python with it. Build `models.Brief` and `models.AssetRef` directly and the
field names are checked by Python at call time, which is loud and free, but `role_stated` and the
pairing rules become the caller's to get right -- and `role_stated` is silent when it is wrong,
because mode inference reads it.

This pack is well placed for the second option: it states every role explicitly and never infers
one, so `role_stated` is always true for it and the unknown-role refusal is pre-empted by the
contract check. A caller that under-specifies is not. **`ROLE_OF_THE_FIELD_LISTS` is published in
the contract for this reason**: the field lists describe a `POST /v1/briefs` request and NOT the
dataclasses, and the two are similar enough to be mistaken for each other by somebody building the
all-in-one.

#### Two halves at different versions have to keep working

The pack's `contract.py` decides what a difference costs, and it decides it against **what this graph is
sending**, not against everything the pack can do. A pack that knows about `replaces` talking to a
compiler that does not is perfectly good for every brief that replaces nobody, and refusing those
would be breaking working setups to protect a feature they are not using.

    stop      the compiler cannot do what this graph is asking. Refused before any media travels,
              naming the field or the slot and which half to update.
    note      something differs and this graph does not depend on it. One line in the report.
    silence   nothing differs, or nothing either half can see.

A drifted director copy is never a stop: the Director node sends the prose in its box, so what
compiles is always what the canvas showed. A service too old to publish a contract is one note, not
a failure.

#### The scan that saw one refusal out of twelve

`compile.py` raises twelve refusal codes as a `BriefRefused`. The test that was supposed to prove
every refusal reaches the node pack with a sentence attached scanned for `super().__init__("...")`,
which is how exactly one of them is raised. The other eleven -- every refusal about a contradictory
request, including all four about who a picture replaces -- were invisible to it, and reached the
user through a branch that says "the service rejected the request".

They are published now, `h3ir_client.REFUSED_AS_ASKED` gives the class one branch, and
the pack's `tests/test_comfyui_node.py` reads its list from the shipped contract instead of from
this repository's source, which is what carried it across the split.

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
