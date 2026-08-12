# OpenH3-IR build log

A dated record of what the build found, in the order it found it, from the first end-to-end run
onward. It is kept for one reason: it is the evidence that the rules in the validator are not
arbitrary. Every section is a position that was measured, and several are positions this project
held, tested, and reversed, including one rule that was deleted after an audit found it had no
source, and one metric that reported a plausible number about an artifact that had been thrown
away.

**This is a log, not documentation.** Its figures are true as of the date on the section and
nowhere else. Early sections cite counts (tests, controls) that have since grown. For what is
true now, run the commands in the [README](../README.md); for the reasoning behind a rule, read
[design.md](design.md).

## 16. Build outcome (2026-08-10)

Built. 45 tests, 18 static controls, an eval gate, an HTTP service, a CLI. Six
suite briefs compile with **zero validator errors and zero warnings**.

### The four open problems, measured

The harness runs left four problems that prompting had not moved. Three of them stopped being
prompting problems under the staged design; the fourth became arithmetic.

| problem | harness v1 | harness v2 | h3ir | how |
|---|---|---|---|---|
| under-length | 234 words | 171 words | **467 mean** | total word budget split across shots; length is a sum, not a request |
| no timed beats | 0 cuts | 0 cuts | **1.5 cuts mean, 2-4 shots** | cut times exist before any prose; one generation call per shot |
| sound duplicated | present | present | **0.024 overlap** | every sound event assigned to exactly one of sync/ambient; the renderers get disjoint lists |
| camera off-vocabulary | yes | yes | **level 3/3 on every brief** | chosen from the closed enum as data, rendered canonically by template |
| validator errors | 0 | 2 | **0** | structure is compiled, so most error classes are unreachable |

Restatement between shot bodies (the metric for "one static description restated in different
words") sits at 0.19 mean — cuts carry new information rather than rephrasing.

### The gate earned its place on the first real change

I wrote a prompt revision that added a hard word maximum. It **improved** the metric I was
targeting (word_ratio 1.426 -> 1.316) and the gate **blocked** it anyway: 0.5 mean validator
errors, where the baseline had none.

The root cause was not the prompt. It was a latent bug in my own code: the prose stage was told
to refer to content by `<Subject N>` in every mode, but `<Subject N>` only means anything because
`subject_definitions` defines it — and base modes have no such section. So in a base mode it is a
label that names nothing, the same defect class as `<Image 1>`. The baseline had simply got lucky.
Fixed by making the label policy mode-derived; the change then went from BLOCKED to SHIP-ABLE with
word_ratio improved and warnings down to zero.

That is the argument for the loop, twice over: it caught a regression I would have shipped, and
the regression was a symptom of a bug the passing baseline was hiding.

### Two design claims that survived contact

- **Grounded vs ungrounded labels (§1.1)** turned out to be the load-bearing idea, and not only
  for `<Image 1>`. It is the same rule that catches the base-mode `<Subject N>` bug above, and it
  is what makes `subject_definitions` templated rather than generated — which in turn makes the
  redundant-source-line defect (the one a "fixed facts" list provokes) structurally impossible.
- **Structure compiled, prose generated (§4)** is what made three of the four problems dissolve.
  None of them was fixed by better instructions.

### One claim corrected by the build

`S.SS` rounding: the design said a 10 s request yields `10.13` under a snapped policy. Python's
default formatting is round-half-even, so `f"{10.125:.2f}"` is `10.12`. Now rounded half-up
explicitly. The default policy remains nominal (`10.00`) for the reasons in §3.1.

### Where the design is implemented vs still paper

| design section | state |
|---|---|
| §1-§3 contract, labels, grid, IRDocument | implemented |
| §4 five stages | implemented |
| §5 backend + the two hard rules | implemented, with F15/F16/F17 handled in the client |
| §6 validator | implemented; ~50 rules, proved by 18 controls in both directions |
| §8 profiles + cache keys | AssetCard cache implemented; render key implemented; prose-body cache not yet |
| §10 experiments | E0 authoring half measured; E7 packaged as `h3ir acceptance`; E1-E6, E8, E9 not run |
| §12 mode inference | implemented, including the provenance short-circuit |
| §13 two callers | implemented |
| §14 LoRA registry | implemented; ingest-time trigger validation, injection, R47/R48 equivalents |

Known gaps are listed honestly in `AGENT_HANDOFF.md` — the two that matter are that whisper is
not wired for audio references (and the IR text is the encoder's only channel for audio, so that
gap is bigger than it looks) and that video cards are built from one frame.

### Acceptance comparison

`h3ir acceptance` writes four arms with their wiring and submits nothing:

| arm | validator errors |
|---|---|
| A — maintainer's prose verbatim, `<Image 1>` / `<Image 2>` | 11 |
| B — same prose, labels corrected | 10 |
| C — compiled Ref2VA IR | **0** |
| D — arm B with the two references swapped in the wiring only | 10 |

The single-error gap between A and B is `L1-unknown-label`: the quantified cost of the broken
pointer, holding everything else identical. Arm D is the control that decides whether the labels
bind or the position does, and it is the arm that makes the other three interpretable.

---

## 17. What the prior-art sweep changed (2026-08-10, after the build)

Someone had already built this architecture — `ethanfel/ComfyUI-MiniMax-H3-Guide`, GPL-3.0,
8,723 lines, 13 `_validate_*` functions. Read, not vendored. Six changes came out of it and out
of the thinking-mode research; all six are implemented.

### 17.1 Deterministic-first, LLM-additive — the one idea I did not have

Their `_base_package()` recompiles the locked plan into **a complete valid H3 prompt with no LLM
at all**, and the fallback payload is *the deterministic compiler's own prose, serialised in the
exact shape a successful LLM reply would take*. Downstream never branches on "did the model
work".

**Adopted as `draft.py`.** The consequence is a different product, not a nicer error path: the
draft is the **floor**, the model is **additive**, and a leaked reasoning block is a fallback
rather than an outage. My design had retry-until-valid, which is strictly worse — it has no
answer for a model that fails the same way three times.

It also hands over a free measurement: **arm 0 of the acceptance test is now "LLM off"**. If the
compiled brief cannot beat its own no-LLM draft, the prose pass is not earning its cost. That arm
did not exist in §10 and it should have.

### 17.2 Thinking mode: the architecture is what makes it safe **[SPEC-adjacent, measured]**

arXiv:2606.09662 ran Qwen3's real `enable_thinking` toggle across IFEval: **planning constraints
+5.3pp, precision constraints −8.5pp**, with 10–20% of individual prompts flipping between modes.

That taxonomy is the exact line §4 already draws. Precision-like fields are the ones code owns;
planning-like work is what the beat sheet does. So **thinking is ON for planning, and that is
recorded as contingent on code owning every machine-checkable field** — if anyone lets the model
emit a timecode, thinking must be off for that call. The contingency is written into
`compile.py` where the decision is made, not only here.

### 17.3 Guided decoding is off, deliberately

Four dated issues, one naming this model family. vLLM #39130: with a reasoning parser active,
grammar enforcement is gated on `is_reasoning_end()`, which for some configs never becomes true —
**grammar silently never applied**. llama.cpp #20345 (2026-05-30): on `qwen3.6-27B` with thinking
+ format, grammar can block `</think>` from ever being emitted, looping to the token cap.

`H3IR_GUIDED_DECODING` defaults to off. We validate in Python regardless, so the grammar bought
nothing we relied on and cost two known failure modes. Turning it back on is one env var, for
comparison.

### 17.4 Reasoning leakage is expected input, not an exception

vLLM #35221 puts in-progress reasoning into `content` when generation truncates before `</think>`
— **that is the mechanism behind the `content: None` symptom**, now understood rather than
worked around. #39697 injects the reasoning-end string mid-content, producing self-narration
inside the deliverable.

New rules: **G1** rejects `<think>` / `</think>` / `assistantfinal` anywhere in the prompt; **G2**
rejects first-person planning and meta-commentary inside the description, exempting verbatim
spans so a character may still say "I". An unclosed `<think>` is treated as truncation in the
backend. All three fall back to the draft.

### 17.5 Audio: never ask a deaf model **[hard rule]**

My `analyse_audio` was asking the model to characterise timbre and instrumentation. The endpoint
has no audio tower; ethanfel hit the same wall; a deaf model invents rather than abstains. Now
there is **no audio model call at all** — audio facts are typed metadata from the wiring plus a
transcript from a real recogniser, and the beat sheet is told not to embellish them.

This compounds with §4.1: `"<Audio j>: "` carries no content into the encoder, so the IR text is
the only channel by which it learns what the audio is. An invented timbre is not a harmless
guess; it is the only thing the model will ever be told.

### 17.6 Under-writing wants a floor, not a ceiling

`h3-studio`'s own comment: models *"reliably under-write against a system-prompt-only instruction
and land near 180 words… Under-specifying is the documented failure mode."* Both prior-art
projects enforce a 350–500 floor with retry.

My v2 prompt change had added a hard **maximum** — the opposite lever. Corrected: the floor is
enforced per shot with one expansion retry that hands the short draft back and asks for *more
observation*, not more length. The ceiling stays, because it is what made the word target
honest, but the floor is the safety net.

### 17.7 Six invariants I had not named, plus the gap nobody filled

From their validator inventory: paired-audio duration cover, at most one `fully_copy`, the
shot-citation cross-check, Ref2VA/FL2VA role contamination, first-shot-at-zero, and the
image-use↔retention coupling. All implemented (**A6, R9, R11/X7, R10, T9, R6/R7/R8**).

The unclaimed gap was **marker legality against the declared role** — the enum check everyone has,
the role check nobody did. Implemented: a frame anchor must be `fully_preserved`, a Picture role
cannot carry `attribute_transfer`, an edit source cannot be marked with an incoherent claim.

One of those, the shot-citation check, **fired on MiniMax's own example** when I first wrote it as
a WARN: their coffee-shop environment is scoped to all three shots and re-cited in none, which is
correct writing. Downgraded to INFO, and the case that *is* a real contradiction — an actor the
plan placed in a shot whose prose never names them — moved to the compiler, where the subject's
kind is known. Text alone cannot tell a setting from an actor.

### 17.8 A validator needs adversarial review too

The harness validator flagged standalone `<Picture N>` lines unconditionally; the spec forbids
them only when the label *"will not be analyzed or used separately later"*. **I had inherited that
rule verbatim.** It passed the official control while carrying a false positive, which is the
sharpest available demonstration that a passing control is not proof of correctness.

Fixed: the test is now whether `retention_analysis` carries an entry for the label. Both
directions are tested — a source line **with** an entry must pass, one **without** must fail.

Two of my own bugs were found the same way, by tests rather than by reading: the base-mode
`<Subject N>` leak (twice — once in the prose path, once in the draft, because I fixed the
instruction and forgot the template) and a doubled full stop where placeholder substitution abuts
an existing one.

### 17.9 Model lineage, confirmed

The sweep asked which abliterated build the inference host actually serves, since the §11 findings are
build-specific. Answered from the HF API: `base_model` is
`["huihui-ai/Huihui-Qwen3.6-27B-abliterated", "Qwen/Qwen3.6-27B"]` — so it is the **huihui-ai**
lineage (the crude `remove-refusals-with-transformers` method), AWQ-quantised with MTP preserved.
Not a heretic-style build. HF also tags it `image-text-to-text`, which independently confirms the
vision tower I measured.

So if format adherence proves weak, swapping to `Youssofal/Qwen3.6-27B-Abliterated-Heretic-*` is
the cheap lever, and the abliteration arm of the A/B is worth running. One counter-finding worth
holding onto: arXiv:2607.17427 tested a huihui abliterated Qwen3 across 21,600 structured
decisions and found JSON validity stayed at 100% — pointing *against* the format-cost worry.


---

## 18. Two classes of rule, and the audit that separated them (2026-08-10, after the repair loop)

The maintainer asked how a validator can mechanically know what is wrong inside a discretionary field.
It cannot. That question exposed rules in §6 that were flagging **discretion** while presenting
themselves as **mechanics** — and one of them had been promoted to ERROR, which after the repair
inversion means it was being sent back to the model as a fault to correct.

**The test for every rule, applied from now on: could a competent director disagree with this?
If they could, it is not a check.**

### Class A — decidable facts (the validator's actual job)

A fact about the artifact that is true or false independent of taste. These are the **silent** class:
they never error at render time, they quietly cost quality, and nobody notices them by eye.

- a label that binds to nothing (`<Image 1>`, an undefined `<Subject 3>`, a phantom `<Video 2>`)
- a duration off the 17k+5 frame grid, a cut past the end of the clip, non-increasing timestamps
- dialogue that is not byte-exact against what the caller supplied
- a section missing, out of order, or wrapped in a code fence
- a retention marker illegal for the role the wiring actually declared
- a unicode character that changes tokenization
- **an unstated camera** — absence of a required field, see below
- a LoRA trigger absent, mis-counted, or in the wrong slot

Class A rules may be ERROR. ERROR is what reaches the model in the fix loop, so nothing enters that
loop unless a fact is decidably wrong.

### Class B — judgements (the maintainer's, never the validator's)

Shot count. Prose quality. Whether an edit is good. Whether a beat lands. Whether a description
ends on an event or on a wardrobe note. Whether a push-in beats a cut. Whether the writing is flat.

These are **not rules at any severity**. Where a spec sentence genuinely constrains one of them, the
rule must be narrowed until only the decidable residue remains, and held at WARN — because WARN is
reported and never sent to the model.

### What the audit changed

| rule | was | now | why |
|---|---|---|---|
| `R17-shots-not-distinct` | ERROR on coarse framing/action/camera similarity | **`R17-cut-states-nothing-new`, WARN** | The old test was "these two shots look alike to a taxonomy I wrote". Rewritten to the spec's own sentence (`base-en.txt` §4.2: a cut should introduce new information about subject, space, state, viewpoint or time) in its only decidable form: same framing, same camera, same labels, same dialogue state, and **not one content word of its own**. Fires on degenerate repetition, abstains on every judgement call. WARN because the spec says *should*, and because ERROR would send it to the model. |
| `shots.validate_proposal` similarity rejection | rejected the whole plan | **deleted** | Same rule in the structured domain. Replaced by the decidable version: the planner states the new information in `what_changes`, so an empty or literally-repeated `what_changes` is a fact about the proposal. Two similar shots with different stated changes now pass. |
| `shot_distinctness` (eval gate) | gated at 0.01 | **reported, never gated** | A taste heuristic that could turn the suite red. Same reason `n_shots` and `n_timed_cuts` were always ungated. |
| `A1-soundscape-length` | WARN, "spec says 1-4 sentences" | ~~deleted~~ → **RESTORED, see §35** | I deleted it having searched only `ref-en.txt`, and wrote that the number was mine. **It is stated in `base-en.txt` §4.6.** `ref-en.txt` §6 does not restate it because it explicitly defers to that guide. The deletion, and the confession attached to it, were both wrong. |
| `R20-camera-contradiction` | ERROR, regex spanning the actor boundary | **ERROR, narrowed** | It fired on *"the camera pushes in as he steps backward"* — a push-in on a retreating subject, which is a real shot — and on *"holds static, then pans right"*, which is a sequence. Now requires the contradicted motion to be the camera's (no intervening actor) and simultaneous (no intervening temporal connective). |
| `P2-too-short` / `P3-too-long` | WARN | **WARN, pinned** | Spec-backed (`ref-en.txt` §7: "normally 350-500") but soft by the spec's own words — "prioritizes fitting the complete spoken timeline rather than mechanically reaching a word count", "a single shot does not automatically justify a shorter description" — and MiniMax's own example is 336 against their own floor. Never promote, never a repair trigger. Locally: a 274-word brief directed well; a 636-word one did not. |
| `P4` / `P5` camera | ERROR on an unverified premise | **ERROR, re-grounded** | The stated basis was "H3 drifts and reframes when the camera is unspecified". That claim traces to one community author's sysprompt line and **this project's own prior-art sweep recorded it as UNVERIFIED, single-source**. The rule survives on the spec alone: §4.3 defines a closed camera vocabulary and its idiom; all five of `base-en.txt`'s worked examples state a camera motion; `Static Shot` is itself in the vocabulary, so there is no shot with no camera state — silence is an unstated variable, not stillness. `ref-en.txt`'s Ref2VA example omits it, which is the spec disagreeing with itself and is recorded as the one documented control exception. |
| `R15-wardrobe-not-restated` | WARN, "the community warns and our material demonstrates" | **WARN, honestly labelled** | Drift between *generations* is locally observed (an H3 render came back in olive-grey trousers against a blue-jeans sheet, and every later test inherited it). Drift between *shots of one clip*, which is what this rule guards, traces to the same single author and is unmeasured here. Restating garments every shot is also a real prose cost. |
| `A2`'s 65% containment | WARN | **WARN, labelled** | The partition it proxies is the spec's (§6 keeps synchronized events in `detailed_description`); the threshold is mine. |

### Deliberately NOT rules

Recorded so they are not re-added: shot count · ending on a wardrobe description rather than an
event · flat prose · restating the environment · preferring a cut to a push-in · sentence counts in
any section · word counts as anything stronger than a note.

### The control that had to be inverted

`golden/shipped_repeated_shot.txt` is the arm the maintainer rejected by eye. Its control used to assert
that `R17` fires on it. It now asserts the opposite — that the file is **mechanically clean** — with
the message explaining that the defect in it is a judgement the validator cannot make. If a
similarity rule is ever re-added, that control goes red and says why.

This is the honest cost of the audit and it is worth stating plainly: **the validator cannot catch
the defect the maintainer caught.** It was only ever catching it by a heuristic that would equally have
condemned good work. The maintainer is the judge on anything visual; the validator's value is the silent
class.

---

## 19. Proportionality: the creativity dial (2026-08-10, the maintainer's design)

The maintainer stated the bar the service is judged against, and it has four parts:

> "is it actually directed — is there a reason behind each choice, and does it comply with the
> minimalistic short prompt it may have been given, and outputs what minimax h3 expects, in full, and
> valid… Cuz if I ask for simple, I want simple, if I say go crazy, I want crazy"

1. **Directed** — a reason behind every choice. Not a shot count, not a quota of camera terms.
2. **Proportionate** — a plain ask gets a plain result; an ambitious ask gets an ambitious result.
3. **Complete** — everything H3 expects, populated meaningfully.
4. **Valid** — mechanically correct.

Part 4 was already built. Part 1 is craft and lives in the prompt. **Parts 2 and 3 are this section.**

### Why a dial and not inference

An earlier plan was to read the ambition level out of the request — its length, its specificity,
whether it used words like "epic" versus "simple". That was dropped on the maintainer's call: *"on 'how
hard it directs', I'm thinking we don't have to marry a setting, can become a 'creativity slider'"*.
Inference would be wrong often and, decisively, **there would be no way to overrule it**. A dial is
honest, and it lets the *same* short request produce either answer — which is exactly what
proportionality needs and what inference could never deliver reliably.

Named positions, not a float: `restrained | balanced | bold`, default **balanced**. A person
understands those words; `0.0–1.0` is a machine setting, and the standing requirement is no
comfy-talk in the interface. An unrecognised value falls back to the default rather than failing a
render — the caller may be an agent that has never read the source — and the compiler records what it
actually used.

### The axis is ADDITION, not effort

The trap here is the one the rule audit just removed: "bolder" must not mean "more shots". That would
put shot count back into the system through a side door, one layer above the validator where nothing
would catch it. So the dial governs exactly one thing: **whether the writer may introduce content the
request never supplied.**

Three elements, and each is on the list because its source can only be the model:

| element | present when | requested when |
|---|---|---|
| `speech` | a `<d>` block exists | the caller supplied a line, an `<Audio N>` is attached, or the request asks for speech in prose |
| `score` | `non_diegetic_music` is not `N/A` | the request mentions music/score/soundtrack |
| `on-screen text` | a quoted span in the description that is not dialogue | the caller supplied `onscreen_text` |

| position | licenses |
|---|---|
| `restrained` | nothing beyond the request |
| `balanced` (default) | a score — the one addition that serves a request without inventing anything a character does or says |
| `bold` | a score, a spoken line, on-screen text |

The positions are **nested** (a test asserts it): each licenses everything the one below it does.

**Deliberately NOT on the dial, at any position:** shot count and where the cuts fall; the camera
(H3 requires a stated camera at every setting, and `Static Shot` is in the vocabulary, so *restrained*
means the plainest move the request supports, never an unstated one); a performance beat, which is
description of what was asked rather than new content; and how good the prose is.

### Prohibitions outrank the dial

`Q1-forbidden-element-present` (ERROR) fires when the request explicitly ruled an element out and it
is there anyway. No setting overrides it — `bold` on a request that says "No dialogue" licenses no
dialogue. This is the direction the failure is likeliest to run in now that `bold` exists.

`Q2-unlicensed-addition` (ERROR) fires when an element is present that the position does not license
and the request did not ask for.

Both are ERROR, and that is deliberate after the taste audit: this is a **parameter violation**, not
a judgement. The setting *is* the definition of legitimate here, so the rule cannot fire on a
legitimate choice, and "remove the score" is a precise instruction to send back through the fix loop.

Precedence, in order, all tested:

1. **A prohibition beats a mention of the same word.** "No background music" contains *music*;
   reading that as a request for a score inverts the instruction.
2. **Content the caller actually supplied beats a prohibition.** A filled-in dialogue line plus a
   stale "no dialogue" is a contradiction, and the concrete line is the better evidence of intent.
3. **An adjective is not a prohibition.** "Quiet", "understated", "minimal" are moods. This is the
   same reasoning that says a loose adjective cannot override a reference plate.

The detectors are conservative in the safe direction: a false positive silently strips something the
caller wanted, so a missing prohibition is the cheaper error.

### Completeness — `S9-section-empty`

An empty `overall_soundscape` validated **clean** before this rule, and H3 is a model that generates
audio. A present-but-empty section is purely mechanical and now an ERROR.
`non_diegetic_music: N/A` is exempt: N/A is the value the spec *defines* for a scoreless video, so it
is an answer, not an omission — and the dial, not this rule, decides whether it is the right one.

### One contradiction this design already produced and fixed

The writer's instruction is **generated from the licence**, never hardcoded per position. The first
version wrote bold's latitude as fixed prose ("you may add a spoken line, a score…") and appended the
prohibitions underneath, so a request forbidding music produced *"you may add a score"* followed by
*"a score is ruled out"* — a contradiction we authored, which the model would have spent a fix round
resolving. Caught by a test that asserts `licensed` excludes forbidden elements, written only because
falsifying the suite showed that breaking `licensed` failed **nothing**: `permits()` checks
prohibitions independently, so the validator stayed correct while the *instruction* went wrong.

### The ask ships beside the result

A brief alone is unjudgeable — nobody can tell whether an output matched a plain request or overshot
it while looking only at the output. Every arm now writes a `<name>.ask.md` carrying the request
verbatim, the references, the settings, what the scope decided, and the brief. The API returns the
same two fields (`asked_for`, `creativity`) in its plain-language plan layer.

---

## 20. First end-to-end run of the write→verify→fix loop (2026-08-10)

The loop had never been run across the suite. The maintainer's resend-the-findings design landed four
minutes after the one good arm was written, so nothing had ever been through it. The question was
narrow: **does it fire, and does it help?**

### Run 1 — it fires, and it cannot help

    clean 0.167  |  repaired 0.000  |  fell_back 0.833      6 briefs, 114.6 s

| brief | mode | outcome | fix rounds | surviving |
|---|---|---|---|---|
| t2va_battle | t2va | fell_back | 2 | L2-undefined-subject |
| t2va_silent | t2va | fell_back | 2 | L2-undefined-subject |
| t2va_dialogue_dense | t2va | fell_back | 2 | L2-undefined-subject |
| t2va_long | t2va | fell_back | 2 | L2-undefined-subject |
| ref2va_two_subjects | ref2va | **clean** | 0 | — |
| i2va_animate | i2va | fell_back | 2 | L2, L3-phantom-media |

The correlation with mode is total, and that is the finding. **The write-first composer carries
`ref-en.txt` — the Full-Reference Mode guide, which names `<Subject N>` eleven times — and it was
used for every mode.** Base modes have no subject labels at all. The model was handed a specification
that teaches a label, used the label, and was failed for using it. No number of correction passes can
repair a brief written against the wrong format, so the loop was being blamed for a fault two stages
upstream of it.

It also explains why nobody had seen it: every brief tested by hand, and every acceptance arm, is
Ref2VA — two images attached. The one mode that worked was the only one being looked at.

### Three defects behind it, all ours

1. **No base-mode composer.** Fixed: `compose_base.v1.txt`, built from `base-en.txt` the way
   `compose.v2.txt` was built from `ref-en.txt`. Three sections, no subject labels, no task-type
   prefix, no retention markers, and the same direction/camera/performance/sound craft — that part is
   mode-neutral. Selected by mode; `compose_prompt=None` means "pick correctly".
2. **The fix ask had no label inventory.** *"`<Subject 3>` is used but never defined"* is satisfiable
   by deleting the reference **or** by inventing a definition for it, and nothing in the ask said
   which labels are real. A binding fault was being sent back with the binding table removed. The
   inventory is *wiring*, not specification, so resending it does not reopen the "the spec is not
   resent" decision — withholding it was an accident of where the split fell.
3. **The fix ask said "output the corrected six sections" unconditionally** — pushing a three-section
   base brief toward the full-reference shape during the pass meant to correct it.

### Run 2 — the fallbacks became repairs, and exposed a silent data loss

    fell_back 0.833 → 0.167      only i2va still falling back

All four t2va briefs went `fell_back` → **`repaired` at one round**. But they scored `words=0`,
`cam=0`, `cuts=0` while reporting no errors — impossible for a brief that had just passed validation.

`SECTION_NAMES` in `repair.py` was the six-section tuple **only**, so `_split_written` searched for
`detailed_description`, never found `integrated_multimodal_description`, and returned a sections dict
**with the entire description missing** for every base-mode written brief. Silent in both directions:
the validator reads the prompt text rather than that dict, and until the base composer landed, every
base-mode brief fell back to the draft, which builds its sections another way. The service's API
would have returned a brief with no description in it.

A fourth defect surfaced with it: an i2va brief has a real `<Picture 1>` and *no* definition lines, so
keying the "no labels" message off the definition lines announced **"nothing is attached"** over a
live reference.

### What this says about the maintainer's design

The resend loop is sound and it is not what was broken. Its one real gap was informational — it was
withholding a fact the model needed — and the loop's own instrumentation is what localised the
problem: *"a finding that survives a retry is a signal about the finding"* is exactly what happened,
four times over, on the same rule. A code repairer would have silently deleted the offending label
and shipped a brief written to the wrong specification.

---

## 21. `extreme`, and the second axis (2026-08-11)

The maintainer judged the two dial renders — *"Both shots done, and yeah, there's a difference, even with
some room for 'extreme' direction in the slider, you'll instantly spot it in the prompts"* — and asked
for a fourth position above `bold`.

**The axis topped out by construction.** There are exactly three addable elements and `bold` licenses
all three, so a fourth position could only be a longer list if the list grew. A proposal to grow it —
`extreme` licenses *events*: something enters frame, a state changes, a situation turns — was put to
the maintainer and rejected outright: *"no no, not hallucination extreme, more like 'go over instead of
under on every decision'"*. Then sharpened: *"lean extremely bold on everything, 'extreme' is key"*.

That rejection matters beyond the naming. Licensing invented events would have re-opened the
fabrication risk the design has forbidden from the start, and it would have done so by consensus —
the proposal was reasonable and I would probably have built it.

### Two axes, one control

| position | `licensed` (what may be added) | `magnitude` (how far each decision goes) |
|---|---|---|
| `restrained` | nothing | plain |
| `balanced` (default) | score | measured |
| `bold` | score, speech, on-screen text | assertive |
| `extreme` | **same as bold** | **maximal** |

`extreme` licensing nothing new is deliberate, not an omission, and the code says so — it is the
first thing a reader will mistake for a bug.

They are kept as separate properties on `Scope`. They move together under one control because the
interface takes no clutter, and separating them into two controls is then a change in one file and
nowhere else. The composition is real: *restrained content at maximal magnitude* is a coherent thing
to want — the requested scene and nothing else, played as hard as the format allows.

### The line: magnitude governs VALUES, never COUNTS

Amplitude, speed, motion type, framing, contrast, how completely a beat resolves — all values, all
"how hard is this one shot played". How many shots, and where the cuts fall — counts.

So *"at extreme, where it is choosing between N and N+1 shots, take N+1"* was **declined**. The moment
a setting licenses more cuts, shot count is a rule again, one layer above the validator where nothing
catches it — the exact failure §18 removed. **Framing is in scope**: it is how hard a single shot is
played, not how many there are, and the spec's own vocabulary runs to extremes.

**Two statements, and both are needed — an earlier version of this section said only the first.**
*Nothing in the code licenses shot count at any setting*: no instruction asks for more shots, no rule
counts them, and a test asserts one shot and four shots both pass clean at all four positions. *And it
correlates anyway.* On the plain request with references bound the model chose 2 / 1 / 1 / 3 shots
across the settings — so "shot count tracks the request, not the dial" was true of the text-only grid
and is **not** true of observed output generally. The maintainer was shown this and chose to leave it as the
model's judgement rather than pin it with a rule, consistently with §18. Do not add that rule.

### Why this position can be checked, when the taste rules could not

The axis is the spec's own closed vocabulary. `base-en.txt` §4.3 defines camera motion as motion type
+ **amplitude** + **speed**, with `with small|large amplitude` and `at slow|fast speed` as the values.
So "is this brief at the far end" is **countable**, and — the part that makes it legitimate — **the
setting itself defines what correct means**. A director who wanted a slow push would have asked for
`bold`; at `extreme` they asked for the boldest value available. That is the one thing every purged
taste rule lacked: an author-supplied definition of correct.

`Q3-extreme-not-honoured` (ERROR): at `extreme`, no `with large amplitude` and no `at fast speed`
anywhere in the description. **Silence fails it too**, by the spec's own rule that omitting amplitude
and speed *means* medium and normal — so a brief that states neither is played at the middle.

**Wholesale only.** "None of the maximal values appears" is a fact. "Not enough of them appear" would
be a threshold, and a threshold is where taste re-enters. The honest cost: at `extreme` a deliberately
slow beat among fast ones is not expressible. That is what the setting means, and a caller who wants
that contrast asks for `bold`.

### What does not change at `extreme`

- It invents nothing. Magnitude on decisions the writer is already making.
- **Prohibitions win absolutely**, and this is the position where it matters most: `extreme` plus
  "no dialogue" is still no dialogue.
- Shot count is still never a finding.

## 22. What may gate a run, after the length ruling

- **`word_ratio` no longer gates.** It measures distance from `plan.total_word_target()` — a number
  the writer is never given in the write-first path. In the mode being measured, it is distance from a
  target that does not exist in the pipeline. Even if it existed, a length gate is the class §18
  purged: a 274-word brief directed well, a 636-word one did not.
- **`warnings` no longer gates.** A single count summed "this brief is 143 words" with a real content
  finding, so a move in it could never say which moved. The rules stay in `warn_rules`, where they can
  be read.
- **`X13-written-rejected` left the warnings pool.** It *is* the fallback event and `fallback_rate`
  already carries it, so one event was moving two numbers.
- **Errors still gate, absolutely.** Ungating trends must not ungate faults.

## 23. The coverage failure behind the mode bug

Worth writing down because it will recur and it is not a code defect: **every brief either of us
tested by hand, and every acceptance arm, is Ref2VA.** The one mode that worked was the only one being
looked at. Five of six suite briefs were falling back and no amount of care on the examples we had
chosen could have shown it — the examples were the blind spot.

The eval suite found it the first time it was ever run end-to-end on the write-first path. That is
what a fixed brief set is *for*, and it is a stronger argument for keeping it than any regression it
has caught.

---

## 24. Standing rule: measure the artifact that ships

**Not a lesson learned. A rule to check against before adding any metric.**

Three fields were caught in one evening reporting confidently on an object the write-first path
throws away:

| field | read | should have read | what it reported |
|---|---|---|---|
| `restatement` | `plan.shots[].body` | the shipped description | **1.00** on briefs whose shots are visibly different |
| `n_shots` | `len(plan.shots)` | `[Shot N]` markers in the shipped text | **4 shots against 0 timed cuts**, on a brief with no errors |
| `doc.sections` | six-section names only | both namespaces | the **entire description missing** on every base-mode brief |

In the write-first path `doc.plan` is the *deterministic draft's* plan. The model's prose never goes
back into it. So any metric reading the plan is measuring a discarded intermediate, and it fails
silently — the number is plausible, the code has no bug, nothing raises.

**The rule has two halves, and both were learned the hard way.**

**First: a metric reads the artifact that SHIPS.** If it reads an intermediate, it is measuring
something the user will never see.

**Second: it reads that artifact in the CONFIGURATION that ships.** A harness knob whose default is
anything other than what production does turns every run into a truthful report about a pipeline
nobody uses. `RunConfig.compose_prompt` defaulted to an explicit composer name, which overrode the
mode selection and produced a reported `clean_rate` of 0.167 where the shipping configuration is
1.000 — full account in §26. The second half is harder to catch than the first, because a
wrong-configuration run is internally consistent: every field agrees with every other field, so the
pair-check below finds nothing.

The instructive part is not the bug. **The warning about that exact override was written into
`AGENT_HANDOFF.md` in the same sitting the explicit default was left in the harness.** Knowing a rule
and applying it are separate acts, and the gap between them is where this class lives — which is why
both halves are now assertions in the test suite rather than advice in a document.

**Two detection techniques, both cheap, both of which have now worked repeatedly.**

**(a) Compare two fields that must agree.** Every wrong-object instance was caught this way and none
was caught by a test.

**(b) An aggregate over a multi-valued field must say which value it took.** Third failure mode, and
distinct from the other two: not the wrong object and not the wrong configuration, but the **right
artifact measured over the wrong part of itself**. The framing column took the *first* match in a
description, so `plain/extreme` was reported as `medium shot` while that brief also contains an extreme
close-up — a three-shot brief has three framings, and the instrument hid the single signal it existed
to show. Report the set, or the count, or name the slice; never silently take one.

**(c) Read the artifact back; never trust the code that wrote it.** This has caught four separate
faults, and the sharpest was the provenance record itself: `commit` existed on the `Run` dataclass and
was absent from `Run.dict()`, while `note` was a `Run` field the CLI assigned *after* `run_suite` had
already saved. So the artifact created specifically to record which pipeline produced a result
recorded neither — and the writing code read perfectly. Printing the stored JSON is what found it.
The same technique found the empty `overall_soundscape`, the missing description in `doc.sections`,
and the baseline's stale reference values.
- `n_shots` = 4 with `n_timed_cuts` = 0 is impossible, because `T4-missing-cut-time` requires a cut
  time on every shot after the first. Two fields disagreeing meant one was reading a different
  object. (T4 was verified innocent by testing it directly rather than by inference.)
- `restatement` = 1.00 against `shot_distinctness` = 1.00 is a contradiction: identical shots cannot
  be perfectly distinct.
- `words` = 0 with `errors` = 0 is impossible, because `S9-section-empty` and `T1-no-shot` would both
  fire on an empty description.

So: **"the number moved" is not evidence until you can name the artifact that produced it.** And when
adding a metric, name a second field it must agree with, then check the pair.

A fourth instance landed the same evening in `proportionality.py` — a script written *after* the other
three were fixed, which read `len(doc.plan.shots)` and reported 2 shots on all six cells while four
contained one. Knowing about the hazard is not protection from it; the pair-check is.

## 25. The draft over-reaches; the writer does not

This inverts the assumption the build started from — that the model needed pushing toward more and
code needed to hold it back.

Measured, on identical inputs:

| brief | draft planned | writer chose |
|---|---|---|
| `t2va_long` (15 s, lighthouse) | 4 shots | **1** |
| `t2va_battle` (10 s) | 3 shots | **2** |
| `t2va_silent` (5 s) | 2 shots | **1** |
| plain corridor request, all three dial positions | 2 shots | **1 at every position** |

And it corroborates the maintainer independently. On the rendered arms he said: *"didn't have much to work
with, and wasn't really asked to come up with unrealistic stuff, did 2 easy shots."* The writer's
restraint on a plain ask is real and repeated — it shows up in the suite, in the acceptance arms, and
in the proportionality grid, from three different directions.

**The component that over-reaches is the deterministic draft**, whose `shot_count()` divides duration
by 3.4. That arithmetic is what produced the repeated shot the maintainer rejected in the first place, and
it is still the thing generating more shots than anyone asked for — it is simply no longer what ships
when the model is available.

Consequence for the dial: **a narrow restrained-to-extreme spread on a plain request is not a failure
of the dial.** The writer is already plain there by default. The burden of demonstrating the dial
falls on the ambitious request, which is why the proportionality grid needs both.

---

## 26. The harness must run the shipping configuration

§24's rule — measure the artifact that ships — has a second half, and it cost a whole reported
result before anyone noticed.

`RunConfig.compose_prompt` was given an explicit default of `"compose.v2.txt"`. `compile_brief`
selects the composer by mode **only when that argument is `None`**, so the explicit name overrode the
mode split and forced the six-section full-reference composer onto every base-mode brief — the exact
defect §20 had just fixed. The harness added to verify the fix reintroduced it.

    reported   clean 0.167 | repaired 0.667 | fell_back 0.167    65.6 s
    actual     clean 1.000 | repaired 0.000 | fell_back 0.000    35.5 s

**Why the §24 pair-check could not catch this one.** The previous four instances measured the wrong
*object*, and that shows up as two fields contradicting each other. This measured the right object in
the wrong *configuration*, so every field was internally consistent and mutually agreeing — the run
was a truthful report about a pipeline nobody ships.

**What catches it: the harness runs production's configuration by default, and any override is an
explicit A/B lever.** Now asserted by a test (`RunConfig().compose_prompt is None`,
`RunConfig().creativity is None`). When adding a knob to a measurement harness, the default must be
whatever production does — not the value that happens to be convenient while writing it.

**And what actually surfaced it: two harnesses disagreeing.** `flakiness.py` passes no
`compose_prompt`, so it exercised the shipping path and returned 35/35 clean minutes after the eval
reported 83% fallback. Neither number was noise; they were compiling different things. **A second,
independently-written harness over the same pipeline is worth more than another test over the first
one.**

## 27. Reproducibility: there is none of the problem we thought

`i2va_animate` falling back twice in suite runs and passing alone at the same seed looked like
endpoint nondeterminism under batching, and a retry policy was nearly designed around it. Measured
properly — five repeats of the full suite plus five solo repeats, fixed seed:

| mode | n | fell_back | outcome |
|---|---|---|---|
| t2va | 20 | 0 (0%) | clean ×20 |
| i2va | 5 | 0 (0%) | clean ×5 |
| ref2va | 5 | 0 (0%) | clean ×5 |

`i2va_animate` batched: clean ×5. Alone: clean ×5. **0/6 briefs varied across identical runs.**

The flake was the wrong composer, not the endpoint. Recorded because the wrong conclusion was
one step from becoming product behaviour — a retry policy, and a UI that explains to users that
their result may vary between identical requests, both built on an artifact of a harness default.

---

## 28. The compose-ablation (2026-08-11)

Does each block in the composing ask earn its place? Four arms, each dropping one block, against the
shipping baseline. Six briefs per arm, one run each, `clean_rate 1.000` baseline.

| arm | briefs it touches | clean_rate | fallback | fix_rounds | wall | verdict |
|---|---|---|---|---|---|---|
| baseline | — | **1.000** | 0.000 | 0.000 | 35 s | — |
| `--omit facts` | 6/6 | 0.833 | 0.000 | 0.000 | 77 s | earns its place |
| `--omit style` | 6/6 | **0.667** | 0.000 | 0.333 | 123 s | earns it most |
| `--omit licence` | **2/6** | 1.000 | 0.000 | 0.000 | 75 s | **under-powered, see below** |
| `--omit scope` | 6/6 | **0.667** | **0.167** | 0.333 | 58 s | earns its place |

**Not one arm produced a validator error.** Every degradation showed up as a repair or a fallback —
which is the loop doing its job, and incidentally the clearest evidence of its value: without it,
three of these four arms would have shipped drafts instead.

**`style` is the most load-bearing**, and the shape of its cost is not what it looked like. The arm
took 123 s against 35 s, which looked like a hang, then looked like two extra generation rounds, then
turned out to be neither. Per-brief timings:

| brief | baseline `compose_s` | no-style `compose_s` | baseline words | no-style words |
|---|---|---|---|---|
| t2va_battle | 4.5 | **24.3** | 141 | 140 |
| t2va_dialogue_dense | 4.2 | **23.2** | 155 | 123 |
| i2va_animate | 3.9 | **20.5** | 97 | 115 |
| ref2va_two_subjects | 13.1 | **30.0** | 255 | 310 |

**The composing call itself is ~5x slower while the briefs stay the same size** (mean 164 words
against 157). The fix rounds are cheap by comparison — 1.8 s and 8.3 s. So the style block bounds
generation *time*, not output *length*: without it the model generates far more to arrive at a brief
of the same size.

The mechanism is **unknown** and is left unknown here rather than guessed at. My first theory was the
truncation-retry ladder; the timings rule that out, since a retry would show as a second `compose_s`
attempt rather than one long one. Answering the "are the long runs producing usable briefs or just
long ones" question directly: **same-size briefs, zero validator errors, no fallbacks** — the output
is fine, the generation is expensive.

**`scope` is the only arm that produced a fallback.** Dropping the dial's instruction cost a brief
outright — so the block that carries proportionality is also carrying compliance.

**`facts` earns its place as a label-binding aid, not as an ambition suppressant.** The original
hypothesis for this ablation was that these blocks *cost* density and ambition. That is not what the
numbers say: removing them costs *compliance*, and `desc_words` moved 144–165 across every arm
including the baseline's 157 — inside the noise for a single run.

### The `licence` arm is a null result, not a negative one

**It touched 2 of 6 briefs.** The licence sentence only appears when references exist *and* the
request is silent about an attribute the plate governs, which is true for the two asset-bearing
briefs and false for the four text-only ones. So `--omit licence` was the baseline configuration for
two thirds of the run, and "clean_rate unchanged" is not evidence that the block costs nothing.

Caught by measuring the arm's coverage rather than reporting its number — and the first attempt at
that check was itself wrong, because it resolved the licence with empty cards and reported 0/6. The
correct measurement captures the real ask with real cached cards through a mock transport.

**Standing consequence: an ablation arm must report how many briefs it actually changed.** An arm
that touches nothing produces a confident null, which is the same failure as a metric reading the
wrong object — a truthful number about something that did not happen.

### What this cannot support

Outcome metrics are stable across repeats (§27), so a `clean_rate` move of 0.167–0.333 is real.
**Word counts have unmeasured run-to-run variance**, so nothing here speaks to length, and any future
claim that a block changes brief length needs repeats per arm.

---

## 29. Video references: real frames, or a loud failure (2026-08-11)

`analyse_video` took a frame list and **every caller passed none**, so it fell through to
`[ref.path]` — handing a vision model the `.mp4` itself. `image_data_url` guesses the mime from the
extension, so the request carried `data:video/mp4;base64,…` inside an `image_url` field: an entire
video in a field for a picture. The endpoint returned a card with the right shape describing nothing
in particular, and the compiler was perfectly willing to build a brief on it.

Silent in every direction. No exception, no validator error, a populated card, and — because a card
is cached on content hash — permanent once written.

**Fixed in two halves, because either alone leaves the failure mode open:**

1. **Sample real frames.** `sample_frames()` extracts at 10/50/90% of the probed duration; the ends
   are avoided because the first and last frames of a real clip are routinely black or mid-fade.
   Duration comes from `ffprobe` on the file, since a caller's `seconds` is a claim.
2. **Raise, never degrade.** No path, no readable duration, or zero extracted frames all raise
   `AssetAnalysisError`. A card describing nothing is indistinguishable from a card describing
   something dull.

`ANALYZER_VERSION` → **3**, which is what stops a v2 video card — one built from the unreadable blob —
being served from cache. Same reasoning as the 1→2 bump.

The ask also changed: three frames of one subject read as three subjects unless told otherwise, and
the format has a label namespace that would happily bind all three. The system message now says they
are the same clip, sampled in order, and asks for the subject once plus what changes between them.

Verified on real output: three distinct frames (different bytes, different hashes) and a card whose
summary describes the change *across* them.

### Two test failures worth keeping

**The first test clip was a solid colour.** A `drawbox` expression that did not render left three
identical 1604-byte frames, and the model duly reported "no visible subjects or changes". It would
have passed a distinctness check that compared nothing. Replaced with `testsrc`, ffmpeg's own animated
pattern, where consecutive frames must differ.

**The cache answered instead of the sampler.** Breaking `VIDEO_FRAME_FRACTIONS` to `(0.5, 0.5, 0.5)`
on purpose — which must make the frames identical — left the test **passing**, because frames from an
earlier correct run were already cached under that content hash. Two consequences, both fixed:

- the frame cache is now keyed on the fractions as well as the content, because changing what the
  artifact *means* must invalidate a cached one — the `ANALYZER_VERSION` lesson in a second place;
- the distinctness test uses its own cache key, so the sampler is what answers it.

**This is the second time tonight a falsification run passed when it should have failed** (the first
being a broken `licensed` that `permits()` covered for). Falsifying a test is not optional ceremony —
it is the only thing that distinguishes a test from a comment.

---

## 30. Reference-mode grid: identity holds, and three of four positions are indistinguishable

The text-only grid answered proportionality but not identity — the maintainer judges by looking, and a
stranger walking down the corridor says nothing about whether *his* character survives the dial. So:
same two requests, all four settings, sheet bound as a subject reference and corridor as environment.
Eight briefs, all `ref2va`, all six-section, **zero errors, zero repairs, zero fallbacks**.

| request | setting | framings used | large/fast | small/slow | shots | binds Subject 1 | retention |
|---|---|---|---|---|---|---|---|
| plain | restrained | close-up, medium-wide | 0 | 1 | 2 | 2/2 | fully_preserved |
| plain | balanced | unstated | 0 | 1 | 1 | 1/1 | fully_preserved |
| plain | bold | close-up | 0 | 1 | 1 | 1/1 | fully_preserved |
| plain | **extreme** | **extreme close-up**, medium shot | **4** | **0** | 3 | 3/3 | fully_preserved |
| ambitious | restrained | medium shot, wide shot | 0 | 0 | 3 | 3/3 | fully_preserved |
| ambitious | balanced | close-up, medium shot | 0 | 1 | 3 | 3/3 | fully_preserved |
| ambitious | bold | close-up | 0 | 1 | 3 | 3/3 | fully_preserved |
| ambitious | **extreme** | **extreme close-up**, wide shot | **6** | **0** | 3 | 3/3 | fully_preserved |

**Identity holds mechanically at every setting**, including at `extreme`: every brief binds
`<Subject 1>` in every shot and claims `fully_preserved`. Whether he *looks* like himself in the render
is the maintainer's call, and `extreme` is where it is hardest — it is the only setting that reaches an
extreme close-up, and identity is hardest to hold in a frame filled by a face.

### `extreme` is a step change, not the top of a gradient

Large/fast reads 0, 0, 0, 4 and 0, 0, 0, 6. Small/slow drops to zero only at `extreme`. Only `extreme`
reaches an extreme close-up. **Restrained, balanced and bold are indistinguishable on the camera axis.**

That is a finding against this design rather than for it. `MAGNITUDE` assigns four values —
plain / measured / assertive / maximal — but **only `extreme` has an instruction concrete enough to act
on** (`with large amplitude`, `at fast speed`, the most extreme framing) and only `extreme` has a check
behind it (`Q3`). Bold's *"where a decision could go either way, take the more assertive one"* produced
no measurable difference. So the magnitude axis currently has two states, not four.

**And balanced vs bold is currently distinguished by nothing measurable.** Both added a score and
nothing else; both stayed timid on camera. Bold is meant to license a spoken line and on-screen text,
and on these two requests the model used neither — a licence it declined to exercise is
indistinguishable from a licence it does not have.

### Shot count correlates with the dial, though nothing licenses it

On the plain request the model chose 2 / 1 / 1 / 3 shots across the settings. Nothing in the
instruction or the validator asks for more shots at a higher setting — §21's line holds in the code —
but the model correlates them anyway. In the text-only grid it did not (flat at 1 shot on the plain
request), so this appeared once references were bound. Reported as an observation for the maintainer: the
dial is not asking for it, and he may or may not want it.

### A fourth measurement reporting a real value about the wrong slice

The framing column originally took the **first** match in the description, so `plain/extreme` was
reported as `medium shot` while the brief also contains an extreme close-up — a three-shot brief has
three framings. The instrument hid exactly the signal it existed to show, and the numbers above were
re-derived from the saved briefs rather than by recompiling, because the output was never wrong.

Same family as §24, in a new position: not the wrong object and not the wrong configuration, but the
right artifact measured over the wrong *slice* of itself. Fixed to report the whole set plus counts of
maximal and timid camera phrases.

---

## 31. Audio: a transcript closes half of it (2026-08-11)

The transcript source was never missing. A local **transcription service exposing `transcribe_audio` (Whisper)** already
existed. So `analyse_audio`'s `transcripts` parameter needed a *caller*, not
a component, and this layer must not grow a transcriber: nothing here can hear, and a model asked
about a waveform invents a plausible answer rather than abstaining.

**The split follows the manifest ruling.** The app owns the Whisper call and passes the result in,
exactly as it owns wiring the graph from the manifest. That keeps the service caller-agnostic, which is
the property that settled the manifest question, and it keeps MCP knowledge out of the one component
whose value is not having any.

### Three things were actually wrong, and none of them was the transcript

**1. The parameter was unreachable.** `compile_brief(transcripts=…)` existed and no caller could reach
it — not the HTTP API, not the CLI. The app that owns the Whisper call had nowhere to put the result.
Now a field on `BriefIn`, documented with what it does and does not buy.

**2. The caller's characterisation was landing in `overall_soundscape`.** An audio card's `summary` is
provenance — *"a spoken vocal reference supplying voice timbre and delivery, described by the caller
as: his own voice, calm and low (6.00s)"* — and the draft appended that whole string to the ambient
list. The spec reserves that section for the target video's ambience and physical sound, so the brief
told H3 that its soundscape contained a sentence about a reference asset, duration parenthetical
included. `characterisation` is now its own field on the card and the manifest entry, and it goes to
`subject_definitions`, where the label is defined.

**3. The definition line described nothing.** It read *"`<Audio 1>` is the voice-timbre reference for
(S1), containing a spoken vocal layer."* — content-free, ungrammatical when no subject is known, and
the **only** channel the conditioning encoder has for that audio, since H3's tokenizer emits
`"<Audio j>: "` and never the signal. It now carries the caller's words.

### A transcript is not a description of the audio

`timbre` and `music` stay empty however good the transcript is, and a test asserts it. A transcript
gives the **words**; it says nothing about delivery, tempo, or whether the thing is music at all. So a
`voice_timbre` or `bgm` role still cannot be characterised without the caller saying so.

Made visible rather than left silent: **`X15-audio-uncharacterised`** (WARN) fires when an audio
reference's role claims a sonic property and nothing describes it, and it names what to supply —
*"the voice — 'his own voice, calm and low'"*. WARN because it is the caller's omission and they may
still want the render; visible because the alternative is a reference that contributes nothing and
nobody noticing.

`ANALYZER_VERSION` → **4**, since the card contract changed again. Fourth bump, fourth time for the
same reason: a cached card whose contract has moved is served silently and looks correct.


---

## 32. Bold with teeth, measured (2026-08-11)

The maintainer chose giving `bold` a real position over collapsing the dial to two, and accepted that the
middle of the dial would stop matching clips he had already judged. Re-ran the reference grid, all four
settings, both requests:

| request | setting | maximal / timid camera | framings used | shots |
|---|---|---|---|---|
| plain | restrained | 0 / 1 | unstated | 1 |
| plain | balanced | 0 / 1 | unstated | 1 |
| plain | **bold** | **2** / 0 | close-up | 2 |
| plain | **extreme** | **6** / 0 | extreme close-up, extreme wide, medium shot | 3 |
| ambitious | restrained | 0 / 0 | medium shot, wide shot | 3 |
| ambitious | balanced | 0 / 1 | close-up, medium shot | 3 |
| ambitious | **bold** | **3** / 0 | medium shot | 3 |
| ambitious | **extreme** | **9** / 0 | extreme close-up | 3 |

**Four positions, ordered, on both requests.** 0 → 0 → 2 → 6 and 0 → 0 → 3 → 9. Where the axis
previously had two states it now has four, and each step is a countable fact about the text rather
than an adjective.

All eight briefs: `written`, `fix_rounds` 0, zero errors, `<Subject 1>` bound in every shot,
`fully_preserved`. **Nothing needed a repair** — the model satisfied the new checks from the
instruction alone, so `Q3` and `Q4` never had to bite. A check that never fires because the
instruction works is the outcome to want; it is there for when the instruction stops working.

### The refusal, and why

The alternative offered was making `bold` **oblige** the model to spend its content licence — a
spoken line, on-screen text, or an explanation of why the request does not support one. **Declined.**

- It turns the dial from *permitting* content into *pushing* it, which is what the maintainer rejected when
  he rejected "hallucination extreme". An obligation to add a line whether or not the piece wants one
  is the over-directing failure the proportionality bar exists to prevent — it would make `bold` worse
  on a plain request, not better.
- The constraint was that the gradient be real *on the same axis*. A content obligation solves a
  magnitude problem on a different axis, and the magnitude fix above is sufficient on its own.
- *"A licence declined is indistinguishable from a licence not granted"* is a **measurement**
  limitation, not a product defect. It only mattered while `bold` needed the content axis to prove it
  differed from `balanced`; it no longer does.
- `Q2` catching only *unlicensed* additions is the right asymmetry. The validator's job is to catch
  what should not be there, never to demand what might be.

If a setting that pushes content is wanted, that is a separate product decision and belongs in its own
control rather than folded into `bold`.


---

## 33. The dial is asymmetric on purpose (2026-08-11)

§32 recorded `bold` being given a check and a measured 0 → 0 → 2 → 6 gradient. **That check has been
removed.** The maintainer narrowed the position:

> "bold just means if a little nudge can do it, don't mechanically enforce it"

So the shape below is the design, and it is asymmetric deliberately:

| position | held to | by |
|---|---|---|
| `restrained` | **enforced** — no addition the setting does not license | `Q2` |
| `balanced` | soft. An instruction that leans, nothing that verifies | — |
| `bold` | soft. An instruction that leans harder, nothing that verifies | — |
| `extreme` | **enforced** — a maximal value must appear. A quiet one stays legal | `Q3` |

A hard floor, a hard ceiling, and two unverified positions between them.

**`balanced` and `bold` will keep measuring as near-duplicates, and that is not a defect.** The finding
in §30 stands — zero maximal camera values at restrained, balanced and bold alike — but the answer to it
is the narrowing, not enforcement. **A nudge that sometimes moves nothing is still a nudge, and a model
declining it on a given request is an acceptable outcome rather than a failure.** Anyone measuring this
dial will find the middle indistinct; the note lives in `creativity.py` beside the code so it is read
before a rule gets added.

This also settles the question flagged as possibly unanswerable — whether `bold` could be made
distinguishable without pushing content. The answer is that it does not need to be.

### `Q4` is gone, the draft rotation stays, and the route there is worth the space

Both were removed alongside the bold check and flagged as my own call. One was reinstated and then
removed again by the maintainer; the other was reinstated for good. The sequence matters more than the
endpoint.

**`Q4-extreme-not-committed`: REMOVED.** Put to the maintainer as a straight choice — everything maxed with
no exceptions, versus mostly maxed with contrast allowed — and he chose contrast. His reason is the
thing that would make someone re-add the rule, so it lives in `creativity.py` beside the code:

> **hold, hold, then hit is how a lot of real direction works.** A setting that forbids the hold cannot
> express the hit.

`extreme` still has to **reach** for big and fast — `Q3` enforces that, and an all-quiet brief still
fails there. It simply is not obliged to be uniformly loud.

**And I over-retracted on the way.** When the removal was first reversed I wrote that my justification
had been *"simply false"*. Half right: the literal claim — *"inexpressible at every position"* — was
wrong, because a mixed clip is legal at the three positions that do not check the camera. But the
concern underneath it was correct and is what the maintainer acted on: **`extreme` could not express a hold.**
Retracting the whole argument because its strongest phrasing was inaccurate nearly buried the valid
part. Correcting an overstatement is not the same as abandoning the point.

**The draft's `assertive` rotation: KEPT.** I argued the floor need only satisfy what the product
*enforces*; the better argument is that **a fallback ignoring the setting the caller asked for is
silent degradation** — the thing this service refuses everywhere else. Enforcement is not the reason the
floor is faithful; being the floor is. So `bold` keeps a committed rotation with nothing checking it.

### Two inferences that skipped a step, and both sounded sound

The durable output of this exchange is not the dial's shape. It is that **two separate arguments in it
were one unjustified step long, and neither looked like it.**

**Mine, on the draft rotation:** *"nothing verifies this"* → *"this does not matter."* **Enforcement and
correctness are not the same property.** A fallback is faithful because it is the fallback, not because
something checks it.

**Mine again, on `Q4`, and this one travelled:** *"the nudge won't reach for a maximal value"* → *"a
mixed clip is therefore unavailable."* Legality and likelihood are not the same property either. The
brief was legal at three positions the whole time. The lead relayed that inference to the maintainer as the
argument for removing the rule, so **his first decision rested on a premise I had overstated** — and
when the correction surfaced, he was re-asked on the accurate framing (banning gentle moves at `extreme`
costs almost nothing, because contrast is fully available one position down) and **chose the same way.**

That re-ask is the part worth keeping. The decision survives its correction, so it is now his call on
accurate facts instead of on my error — and the cost of *not* correcting it would have been a settled
product decision resting on a claim nobody had checked.

Both errors share the shape: **an inference one step too long, in the direction the arguer already
wanted.** Neither reads as sloppy. That is what makes it worth a section instead of a footnote.

### The remaining lever is wording

The whole scope of `bold` is now how likely its nudge is to land. It names the vocabulary — *"if a nudge
would carry the shot, take it; `with large amplitude` and `at fast speed` are the words for it"* — and
explicitly permits declining: *"where a request is genuinely quiet, a quiet camera is the right answer
and nothing here overrides that."* Concrete rather than encouraging, and an invitation rather than an
obligation. A test asserts the words are named, that the permission to decline is present, and that
`must` / `COMMIT` / `at least one` are absent.

---

## 34. The first video-plus-audio brief, and the three defects it found (2026-08-11)

Video and audio references were modelled, plumbed, frame-sampling fixed — and **never once exercised.**
No brief anyone had looked at contained either. Same coverage shape as the mode bug: the case nobody
was looking at. So: one `ref2va` brief, a real video reference (a slow push across the corridor plate,
so the vision model sees an actual location) plus a standalone audio asset, compiled end to end.

**The path works.** `ref2va` via rule 12.2#1, `written`, `fix_rounds` 0, zero errors. `<Video 1>` at
32,256 packed rows. The card built from sampled frames describes the real plate — *"metal construction,
dark grey colour, cage-style grate, flared base"*, *"irregular stone blocks, grey and brown tones,
rough texture, green ivy vines"* — so frames → vision → card → `subject_definitions` is sound.

### Defect 1: `L4-unused-media` could not see a wholly-unused kind

The brief **never referenced `<Audio 1>` at all**, and nothing complained. The rule was guarded by
`and used[kind]`, which skips the check whenever a kind is used **zero** times — the worst case, not an
exempt one. `n_have` already handles "nothing attached", so that guard only ever hid the total miss.

The consequence is the arm5/arm6 failure in reverse: **the manifest published an entry the app would
wire into the render, against text that never mentions the asset.** Inert conditioning plus
contradictory context, silently. Now ERROR when a kind is entirely unbound, WARN when partially.

### Defect 2: the ask never named the audio label

`_definition_lines` walks `subjects`, so an `<Audio N>` — and a bare `<Video N>` — appeared **nowhere in
the composing ask**. A model cannot bind a label it was not told exists. The ask now names every label
in the wiring that its own fact sheet did not, and says they must be referenced.

### Defect 3: the model invented the audio's provenance and its content

With the label named, the re-compile bound it — and wrote *"`<Audio 1>` is the ambient sound track from
`<Video 1>`"* for an asset wired **standalone** (`ref_audio_1`, not `ref_video_audio_1`). It guessed
from both assets existing. It also described *"the crackling of the torch flame"* in a file that is a
110 Hz sine tone, overriding the caller's note (*"a low room hum with no voices in it"*) with an
inference from the video.

**The provenance half is checkable** — the runtime pairing is a fact this layer holds — and is now
`R21-audio-provenance-invented`. **The content half is not**, and the honest response is the ask rather
than a rule: the model is told it has not heard the asset, must say only what the note states, and must
never claim it came from a `<Video N>`.

### And R21's first version was a false positive on the spec's own example

It keyed off `ctx.paired_audio` being **empty**, which conflates *"the wiring says these are not
paired"* with *"nobody told us"* — and it failed the `MUST PASS: published ref2va.ir.txt` control, whose
context declares no pairing while the example's audio genuinely is that video's track.

**Exactly the L5 mistake again: absence of information read as a negative claim.** Fixed with
`standalone_audio`, a field where the compiler asserts which labels it *knows* are unpaired. A caller
who states nothing now gets no finding. Falsified both ways — the absence-keyed version fails the golden
control, and removing the rule fails the defect test.

That control has now caught three wrong rules (the 350-word floor, the camera vocabulary, L5) plus this
one. **MiniMax's own example earning its place as a control is the most reliable single check here.**

---

## 35. The source audit: A1 was real and I deleted it (2026-08-11)

The maintainer unparked the audit once `extreme` was built and settled. The standard he set widens the
admissible set beyond a quotation:

> "some can be derived by logic instead of just read in the docs"

**Three tiers, and a derivation counts only if the derivation is written down:**

- **Stated** — a line in `ref-en.txt` or `base-en.txt` you can quote.
- **Derived** — follows necessarily from a stated rule, with the reasoning recorded. `Static Shot`
  being *in* the vocabulary implying that silence is an unset variable rather than stillness is the
  model case: sound reasoning, trustworthy only because it is written out.
- **Measured** — a fact about the model somebody established, with the run named.

### The first thing the audit found was my own deletion, and it was wrong

`A1-soundscape-length` was removed in §18 with this reasoning recorded in the doc: *"`ref-en.txt` §6
states no length for the section. The number was invented and then enforced as the spec's."*

**The number is stated.** `base-en.txt` §4.6: *"Use **1–4 English sentences** in one continuous
paragraph to summarize the ambient sound…"*. And §4.7, for a rule that never existed at all: *"Use
**1–3 English sentences** to describe background music…"*.

`ref-en.txt` §6 does not restate them because it **defers**: *"The definitions of these two sound
categories follow the Video Prompt Writing Guide (T2VA / I2VA / FL2VA / L2VA)."* I searched the
Ref2VA document, found silence, and read it as the specification's silence — in a section whose first
line says to look elsewhere.

So the taste audit's own founding example was a legitimate rule, deleted on a false confession. Both
are now corrected: `A1` restored with its citation, and `A7-music-length` added for §4.7.

**Third instance tonight of the same error**, and the pattern is worth naming because it has now
produced a deleted rule, a false positive on the spec's own example, and an inherited bug:

| | what was read as absence | what it actually was |
|---|---|---|
| `L5` | a standalone source line appearing at all | forbidden **only** when the label is not analysed separately |
| `R21` | an empty `paired_audio` | "nobody told us", not "the wiring says unpaired" |
| `A1` | `ref-en.txt` saying nothing about length | a section that explicitly defers to the other document |

**Absence of a statement is not a statement of absence.** Before deleting a rule for lacking a source,
check whether the document you searched delegates — and check the other document.

### Citations the sweep recovered

Rules that were carrying no source in the code and turn out to be **Stated**, now cited in place:

- `A2-sound-duplicated` — `base-en.txt` §4.6: *"Dialogue, singing, and diegetic music already belong in
  the multimodal description and should not be repeated here."* The partition is the spec's; only the
  65% containment threshold is mine, and it stays WARN for that reason.
- `S9-section-empty`'s N/A exemption — §4.6: *"Use `N/A` **only** when the user explicitly requests
  complete silence"*, versus §4.7's unconditional *"Use `N/A` when there is no non-diegetic music."*
  So the asymmetry the rule already had is the spec's own.
- `T5-non-increasing` — §4.2: *"begin each one with a strictly increasing timestamp."*
- `P1-no-style-opening` — `ref-en.txt` §7: *"Established in one or two English sentences before
  `[Shot 1]`."*
- `M1-task-prefix` — `ref-en.txt` §3: the summary *"begins with a square-bracketed task-type prefix."*
- `R4-speaker-in-retention` — `ref-en.txt` §5.4: *"Do not write `(Sx)` in `retention_analysis`."*
- `D3-speaker-numbering` — §5.4: *"Assign `(Sx)` once according to the order of actual vocal events."*

### The classification, by family

107 rule ids after the sweep (`D6` removed). Every one has a named source in one of the three tiers,
and the ones that changed are called out.

**Stated — a line you can quote.** These carry citations in the code now, where they were mostly
implicit before:

| family | citation |
|---|---|
| `S1`–`S5` sections, order, no preamble, no fence | `ref-en.txt` §1 table; `base-en.txt` §2 section list |
| `S9-section-empty` + its N/A asymmetry | §4.6 *"Use `N/A` **only** when the user explicitly requests complete silence"* vs §4.7's unconditional *"Use `N/A` when there is no non-diegetic music"* |
| `L1`, `L2`, `L3` label namespace and binding | `ref-en.txt` §2: four label types, each defined before use |
| `L4-unused-media` | §2: `subject_definitions` defines *"each piece of referenced content that must be tracked separately"* — a wired asset the text never names is untracked |
| `L5-redundant-source-line` | §2.2: *"If an image is used only to define a character… do not create a standalone picture entry"* |
| `M1`–`M3` task prefix, vocabulary, no repeats | §3 *"begins with a square-bracketed task-type prefix"*; §3 *"combine the task types with ` + ` and do not repeat a type"* |
| `M5`–`M7` task type vs attached assets | §3 *"The mere presence of video or audio does not automatically create a corresponding task type"*; *"When editing a source video, use `audio reuse` as well if its original audio remains audible"* |
| `M6-editing-opening` | §3 *"For video-editing tasks, begin the summary after the task-type prefix with:"* |
| `R1`–`R3` retention line shape | §4: one line per label, marker plus scope |
| `R2-illegal-marker` | §4 marker tables — *"These markers are fixed English strings"* |
| `R5-unanalysed-subject` | §4 *"describes how **each** piece of referenced content is preserved…"* |
| `R6`–`R8`, `R10` marker legality vs role | §4 *"Choose each relationship marker **only within the reference role already defined** for that label in `subject_definitions`"* — this was recorded earlier as an unclaimed gap and is in fact stated |
| `R9-multiple-full-copies` | §4 audio markers: `fully_copy` is the complete final track, so two is a contradiction |
| `R17-cut-states-nothing-new` | `base-en.txt` §4.2 *"A cut should introduce new information about the subject, space, state, viewpoint, or time"* |
| `R18-camera-as-label-stack` | §4.3 *"Camera motion should be written as a natural English action within the shot, rather than stacked as separate labels"* |
| `R21-audio-provenance-invented` | `ref-en.txt` §2.5 *"An `<Audio N>` definition primarily states the audio's role and **does not have to name the `<Video N>` it comes from**. State the shared source only when needed to remove provenance ambiguity"* |
| `T2`–`T5` timestamps | §4.2 *"Do not add a timestamp to the first shot… begin each one with a strictly increasing timestamp"* |
| `T3-timestamp-format`, `T7-illegal-duration` | §2 *"`S.SS` is the effective video duration formatted to exactly two decimals"* + the 17k+5 grid (Measured, below) |
| `D1`, `D2`, `D5` `<d>` shape | §7 *"Write dialogue and lyrics as `<d>[Language] ...</d>"* |
| `D3-speaker-numbering`, `D8` | §5.4 *"Assign `(Sx)` once according to the order of actual vocal events"* |
| `D4-dialogue-not-verbatim` | §5.3 *"preserve the exact source words and original language inside `<d>`"* |
| `D7-decorative-punctuation` | §5.3 *"remove repeated tildes, emoji, bullets, and repeated or decorative punctuation"* |
| `D9-voiceover-no-lips-clause` | `base-en.txt` §4.4 *"For voiceover, use the exact phrase `says in an off-screen voiceover`. Immediately after every voiceover `<d>` block…"* |
| `R4-speaker-in-retention` | §5.4 *"Do not write `(Sx)` in `retention_analysis`"* |
| `A1`, `A7` sound-section lengths | `base-en.txt` §4.6 (1–4 sentences), §4.7 (1–3) |
| `A2-sound-duplicated` | §4.6 *"Dialogue, singing, and diegetic music already belong in the multimodal description and should not be repeated here"* (the partition is the spec's; the 65% threshold is mine, which is why it stays WARN) |
| `A3-dialogue-outside-desc` | `ref-en.txt` §6 *"Write complete dialogue and lyrics only inside `<d>` in `detailed_description`; do not repeat them in these two sections"* |
| `A4-music-should-be-na` | §4.7 *"Use `N/A` when there is no non-diegetic music"* |
| `P1-no-style-opening` | `ref-en.txt` §7 *"Established in one or two English sentences before `[Shot 1]`"* |
| `P2`, `P3` word band | §7 *"normally 350-500 English words"* — with the spec's own escape clauses, which is why neither gates |
| `P4`, `P5` camera stated | §4.3's closed vocabulary, plus **Derived**: `Static Shot` is *in* it, so silence is an unset variable rather than stillness |
| `H2-onscreen-text-unquoted` | `base-en.txt` §4.5 *"Place any banner, sign, label, subtitle, or neon text that is actually visible on screen in English double quotation marks"* |
| `W2`–`W4` LoRA trigger placement | the LoRA's own `howtouse.md` contract |

**Derived — follows necessarily, and the derivation is written down** (each is recorded at the rule):

- `R19-bare-subject-name` — labels bind through the angle brackets (§2), so `Subject 1` as prose
  references nothing. The `<Image 1>` failure in another shape.
- `R20-camera-contradiction` — §4.3's table fixes what each motion type does; a clause asserting both
  directions leaves the model to pick one and nothing states which.
- `R11-scope-not-cited` (INFO) — a label scoped to a shot that the shot never cites makes the retention
  contract and the description disagree. INFO because a persistent environment legitimately is not
  re-cited, which MiniMax's own example demonstrates.
- `A6-paired-audio-short` — a soundtrack shorter than the video it is paired to leaves the remainder
  unaccounted for.
- `P6-no-style-in-shot1` — base modes establish style inside `[Shot 1]`; nothing after the marker means
  the style was never established.
- `Q1`, `Q2`, `Q3` — the creativity setting is an **author-supplied definition of correct**, which is
  what makes these checkable at all. §21 and §33 carry the reasoning. **Do not read "derived" as
  "weaker" here: this is a stronger footing than most Stated rules have.** A Stated rule can still fire
  on a legitimate choice if the spec's wording is looser than the check — that is how the 350-word floor
  and the camera vocabulary both had to be softened. A rule derived from a setting cannot, because the
  setting *defines* what correct means for that request.
- `X1`–`X16` compiler invariants — a deterministic path must be reproducible (`X1`), a fallback must be
  loud (`X13`), a manifest must not publish what the text cannot bind (`X16`).

**Measured — a fact somebody established, with the run named:**

- `T7`/`T10` the 17k+5 frame grid and the node's trained band — from the plumbing audit's render ladder.
- `G1`, `G2` reasoning leakage — vLLM #35221 and #39697, named at the rule.
- `H1-unicode-hazard` — the vendored Qwen tokenizer, which splits on the typographic variants.
- `H3-token-band` — the packed-sequence measurements in the plumbing audit.
- `R12-pose-as-identity`, `R13-sheet-artefact`, `R14-inferred-attribute` — the maintainer's judgements on
  real artifacts (a walking posture arriving as *"fists clenched in a fighting stance"*; a turnaround's
  grid and studio grey; *"describe observables not intent"*).
- `R15-wardrobe-not-restated` — drift between generations observed locally (olive-grey trousers against
  a blue-jeans sheet). The per-shot claim remains unverified and is labelled as such at the rule.
- `R16-style-opening-malformed` — three grammar faults this pipeline actually emitted, each listed.

### Removed for want of a source

- **`D6-unusual-language`** (INFO) — reported that a `[Language]` tag was *"outside H3's 11
  stably-supported languages"*. **That list has no traceable source**: not in either spec, not in the
  plumbing audit, not in the prior-art sweep. The only thing behind it was a comment asserting it. An
  INFO that states a fact about the model is still stating a fact about the model. `STABLE_LANGUAGES`
  went with it. The language *tag* requirement stays — `D2` is stated.

Nothing else failed the standard. **The sweep's real yield was not deletions but citations**: 30-odd
rules that were visibly-from-the-spec and did not say so now quote the line, `R6`–`R8`'s role/marker
coupling turned out to be stated where the notes had called it an unclaimed gap, and one deletion had
to be reversed.

---

## 36. Who owns the attribute — and "the request" is only sometimes the answer

> **Where a mechanism decides the answer, the mechanism owns it. Where nothing does, the request owns
> it.**

That is the general rule, and "the request wins" is a special case of it. Both halves were learned from
the same question asked twice, with opposite answers.

### A third axis: grounded, and still wrong (2026-08-11)

The two failure families catalogued so far are both about **sources** — a rule with no grounding, or
grounding misread. `R15` is neither. It is correctly grounded and still wrong, because **it contradicts
the request's own intent.** A rule that tells a shirt-swap brief to keep restating the original shirt is
right about the spec and wrong about the job.

**The exposure generalises: any rule asserting an attribute must be *preserved* can collide with a
request whose point is to *change* it.** So the two nearest neighbours were checked.

**`R9-multiple-full-copies` — not exposed.** It constrains a *combination* of markers rather than the
preservation of a caller-owned attribute: two audio tracks both claiming to be the complete final track
is a logical impossibility, not a preference anyone can hold. Different shape entirely.

**`R6`/`R7` — exposed, and the resolution runs the OPPOSITE way from `R15`'s.** A frame anchor plus a
transformation request ("start from this frame and reimagine the rest as anime") made
`licence.marker_for_plate` return `attribute_transfer` for the anchor, which trips `R6` (an anchor must
be `fully_preserved`) *and* `R7` (a Picture cannot transfer). Both fired on a perfectly coherent
request, so **the compiler contradicted itself and the model had no way to fix it.**

Here the rules were right and the licence was wrong. A frame anchor is a conditioning latent **that is
never denoised**, so its own pixels cannot be transformed — the transformation applies to the rest of
the video. `marker_for_plate` now exempts the anchor roles.

**The direction is the lesson.** `R15` was fixed by deferring to the **request**, because the caller
owns wardrobe. This one is fixed by deferring to the **mechanism**, because nothing owns a latent that
is never denoised. So the general rule is not "the request wins" — it is:

> **Where a mechanism decides the answer, the mechanism owns it. Where nothing does, the request owns
> it. "Who owns this attribute" is the question; "the request" is only sometimes the answer.**

## 37. What the modality's hardest shape did on the second run

*"Change the shirt on the man in this video, using this reference image"* — video editing, an image
supplying one attribute, a voice reference, and a spoken line. First run **fell back** after `R21`
survived both correction rounds. With `R21` saying what to write instead:

    source: written    fix_rounds: 2    errors: 0    unfixable: []

**It converges.** So the maintainer's resend loop earned its place on the hardest shape the tool supports —
which is the strongest evidence available for it, and better than the earlier proof because this one is
on the shipping path rather than under a broken configuration.

The retention section says what it has never had to say, and says it correctly:

> `<Subject 3>` (appears in [Shot 1]): **partially_preserved** — the man's identity, hair, beard, jeans
> and sneakers are preserved, **but his shirt color is changed from navy blue to a mossy grey-green
> matching the stone.**

And the audio definition dropped the invented provenance: *"`<Audio 1>` is the attached audio track for
the target video."*

### It also demonstrated a missing rule

`<Audio 1>` came back as **`fully_copy`** for a `voice_timbre` reference — claiming the clip becomes the
target's final audio track when its declared role is "only the timbre is referenced". **Visual markers
have been checked against their role since `R6`–`R8`; audio never was**, and it is the same citation:
`ref-en.txt` §4, *"Choose each relationship marker only within the reference role already defined for
that label"*, read against the marker table's own definitions. Now `R22-audio-marker-role`, narrow to
the two roles whose definition *is* "a property is referenced, not the signal" — `bgm` and paired
soundtracks legitimately copy and are not legislated.

Worth noting the earlier run of the same brief produced `reference` here, correctly. **The model was
inconsistent and nothing checked it** — which is the whole argument for the rule, and an instance of
something that deserves its own line:

> **One clean run is never evidence a path is sound.** Nothing about the writing model is deterministic
> enough for a single output to prove anything. This is the counterweight to every "it worked when I
> tried it" in this project, including several of mine — the flakiness measurement (§27) needed five
> repeats to say anything, the reference grid needed both requests, and `R22` exists because two runs of
> one brief disagreed.

## 38. A convention without a test is a comment

Ten rule ids carried two meanings, invisible until someone counted, and **two were introduced that same
evening by the person who knew about the namespace.** That is the fourth time a hygiene rule existed and
the same sitting violated it — the first being the `AGENT_HANDOFF.md` warning about harness overrides,
written beside the harness default that caused §26.

The lesson is not "be careful". It is that **a convention recorded in prose does not constrain anybody,
including its author, twenty minutes later.** `test_no_rule_id_carries_two_meanings` is the correct
response, and the same reasoning is why the dial's asymmetry is pinned by
`test_bold_is_not_enforced_and_must_not_become_so` rather than by a comment.

Every durable rule in this project that has actually held was held by a test.


---

## 39. The mirror image: reading our own novelty into a spec we hadn't finished

§35 catalogued three confident negatives drawn from partial reads — a deleted rule, a false positive on
the spec's own example, an inherited bug. **`R6`–`R8` is the same cause pointing the other way.**

Marker legality against the declared role was recorded — in the notes and in the ecosystem sweep — as an
**unclaimed gap**, a thing nobody in the ecosystem had built. It is `ref-en.txt` §4, quotable:

> *"Choose each relationship marker **only within the reference role already defined** for that label in
> `subject_definitions`."*

So the rule was built believing it was white space, and the white space was documented. `R21` and `H2`
turned out the same way — derived from first principles, then found nearly verbatim in §2.5 and §4.5.

**Both failures share one cause: a partial read producing a confident conclusion.** They differ only in
direction, and the pair is more useful than either:

| | the partial read produced | the cost |
|---|---|---|
| §35 | *"the spec doesn't say this"* | a real rule deleted, a false positive shipped, a bug inherited |
| here | *"the spec doesn't say this **yet** — we're first"* | credit claimed for documented work, and a claim about the ecosystem that was wrong |

**A specification split across documents makes silence ambiguous by construction.** Both documents have
to be read before either "it isn't stated" or "nobody has stated it" is safe to say. The standing
procedure from §35 covers the first direction; this is the second, and the check is the same one.

The consolation is the one worth keeping: **the rules built on this misreading were correct anyway.**
Deriving them from the format's own logic reached the same place the spec had. That is evidence the
derivations are sound — which is exactly what the *Derived* tier is supposed to establish, arrived at by
accident.

---

## 40. Severity: what the fix loop can repair

`G2-model-self-narration` is **WARN**, demoted from ERROR, and the reasoning generalises into the
sharpest severity test found in this project:

> **A check whose false positive is unfixable by the thing being checked must not be an ERROR.**

`ERROR` does not mean "serious". In this pipeline it means **"the model can repair this"** — ERRORs are
what `fix_with_findings` sends back. So the question is not *how confident is the detection* but *what
happens when the detection is wrong*:

- **`G2` right** → the model removes the leaked planning language. Converges.
- **`G2` wrong** → there is nothing wrong in the text. The model cannot converge, the loop exhausts both
  rounds, and **the entire written brief is lost to the fallback.** A phrase blacklist over free prose
  costs the whole artifact when it misfires.
- **`G2` as WARN** → a false positive costs nothing, and the true positive is still reported. Leaked
  self-narration is the kind of defect a person spots instantly in the text.

**Four narrowings are their own evidence.** A rule that needs repeated tightening is a rule whose
detection does not match its concept — that history is a signal about the rule, exactly as a finding
surviving a fix round is a signal about the finding.

**`G1-reasoning-leaked` stays ERROR** for the reason that completes the test: an explicit `<think>`
marker *cannot* be a false positive. Where the detection cannot be wrong, the cost of being wrong is
irrelevant.

This also explains, retroactively, why the taste audit's demotions were right for a second reason
beyond taste. `R17` as an ERROR did not merely encode a preference — it sent an unfixable instruction,
because a model asked to make two legitimately-similar shots "different" has nothing decidable to
change. Both arguments point the same way and the severity one is easier to check.

## 41. Two defects the green suite could not see (2026-08-11)

Found by running `h3ir compile` against the live endpoint **after** 273 tests and 20 controls were
green, on the plainest brief imaginable: *"a woman steps off a night bus in the rain and realises
she's left her bag on board."* The IR was valid. The findings list was not:

```
[INFO] S7-transformation-intent: the request asks for a transformation (None), so the reference's
identity is carried and its rendering style is replaced; the plate's retention marker is
attribute_transfer
```

There is no reference in that brief, no plate, and no transformation. Three false claims and a
`None` printed where a phrase should be, on the happy path, in the shipping configuration.

**The cause is a conflation.** `resolve_licence` assigns every attribute to `"request"` when no
visual reference is attached — correct, and there is a test asserting it, because with nothing to
defer to the request does govern. But `medium_transferred` was *defined* as
`governs[MEDIUM] == "request"`, so it read True for two unrelated reasons: *you asked to transform
the reference*, and *there is no reference*. Only the first is a transformation.

The note was the visible half. The other consumer is `marker_for_plate`, and it is worse: an
**audio-only** reference makes `has_visual_ref` false, so it was handed back `attribute_transfer` —
a marker from the **visual** vocabulary — for an asset with no image in it. Not reachable today
because audio may not be a sole input, so no manifest entry survives to ask; reachable the moment
that changes. Fixed at the definition rather than at either call site: a transformation requires
both a phrase and something to depart from.

**And underneath it, a silent one that matters more.** The verb alternation was written in the bare
infinitive:

```
\b(?:reimagine|restyle|redraw|re-?render|convert|transform)\b
```

`\breimagine\b` cannot match the `d` in *reimagined* — the boundary needs a non-word character and
finds `d`. So six of ten natural phrasings were invisible: *reimagined as anime*, *restyled as
claymation*, *redrawn as a woodcut print*, *converted to black and white film*, *transformed into an
oil painting*. Each fell through to preservation **with no finding at all** — the caller asked for a
departure and silently got the reference's style back. The past participle is the *normal* way to
write the instruction, and this is the one exception the maintainer named in his own words: *"unless the
prompt states it like 'reimagine as'."* The base form worked; every inflection of it did not.
`redrawn`/`redrew` are irregular, which is why the fix is an explicit list rather than a suffix.

**Why the suite could not see either.** Every transformation test was written with the infinitive,
because the same author wrote the pattern and the tests from the same mental sentence. The tests
agreed with the code about what a transformation looks like, so they confirmed each other and
covered exactly one sixth of the input space. This is §38's lesson from a new angle: a test only
constrains the cases someone thought to write, and an author who has just written a regex is the
person least likely to think of the phrasing it misses.

**What actually caught them:** running the real thing on an ordinary request and *reading the output*
rather than the exit code. Same technique as the six measurement bugs — read the artifact back,
never trust the layer that produced it. It cost one compile.

Fourteen tests added, all falsified against the unfixed code (13 red). The fifteenth is a control —
three bare style adjectives that must **not** count — and it was falsified the other way, by
over-widening the pattern until it flagged all three, since a control that passes no matter what the
code does is not a control.

---

## 42. "Explicitly speaks to" was wrong in both directions, and only one of them mattered (2026-08-11)

The reported defect was narrowness: sixteen ordinary phrasings that each name an attribute, and the
attribute reached the request in **3**. It is real — it is now **16 of 16** — but it was the smaller
half of the finding, and the ranking is the substance of this entry.

### The direction nobody was looking at

`_mentions` tested `word in text.lower()`. Substring, not word. So every entry also matched every
longer word containing it, and the collisions land on the commonest words in English:

| listed word | also matched |
|---|---|
| `hat` | **that**, **what** |
| `lit` | **quality**, **military**, **little**, **elite**, splits |
| `cap` | landscape, escape, capture |
| `dress` | addresses |
| `suit` | pursuit |

So *"the man walks down the corridor **that** leads to the door"* resolved **wardrobe → request**, on
the grounds that the request names a garment. It does not name a garment. It contains the word "that".

**This is the serious half, and the reason is direction.** A miss withholds an attribute from the
request, which is the fail-safe direction the maintainer asked for — it costs an ignored instruction. A
false *hit* hands the attribute to the request on a brief that never mentioned it, which is the drift
his rule exists to prevent, arriving through the **matcher** instead of through the policy. And
`governs[WARDROBE] == "request"` is what suppresses `_wardrobe_terms`, so the garment hold — `R15`'s
entire input — **switched itself off on any brief containing "that" or "what", silently.** The
suite never saw it because no test brief in the file happened to contain either word.

> **A detector has two failure directions and they are rarely equally expensive. Widening one is not
> the same work as tightening the other, and a report of the first is not evidence about the second.**

### Severity is set by the consumer, not by the attribute

Six attributes share one mechanism, and tracing each to what actually reads it collapses the problem
by most of its size:

| attribute | who reads `governs[attr]` | cost of a miss |
|---|---|---|
| `WARDROBE` | `compile._wardrobe_terms` → `R15`, **and** the ask | the compiler re-asserts the plate's shirt against a request to replace it |
| `MEDIUM` | `style.resolve_style`, `marker_for_plate` | not in question — narrowness here **is** the maintainer's rule |
| `ACTION`, `LIGHTING`, `FRAMING`, `PALETTE` | one sentence in the ask, nothing else | wrong emphasis in a hint |

That is §40's test applied to a detector rather than to a rule: ask what happens when it is wrong,
not how confident it is. Four of the six have no mechanism behind them at all.

### The fix for the ask does not involve the detector

The sentence read *"The request is silent about {attrs} — the references govern those."* On a miss
that is **a false statement about the caller's own request**, handed to the model beside the request
text. §35's line is *"absence of a statement is not a statement of absence"*; asserting silence is
that mistake made **positively**, and it is the same shape as §41's `attribute_transfer` note naming
a plate that did not exist.

It now states the **rule** instead of a claim of fact:

> Where the request does not specify them, the references govern *action, lighting, framing, palette*
> — read those off the references rather than inventing them; where the request does specify one, the
> request governs it. Anything neither the request nor the references settles is yours.

That is true under a hit **and** under a miss, so a detector miss degrades from a contradiction to a
weaker hint, and the disambiguating is done by the one reader holding both the request text and the
reference description. **This is the durable fix; widening the lists only shrinks a miss rate.**

Two consequences worth naming. First, `MEDIUM` is now excluded from that sentence — the style block
already states it *with the bare-adjective rule attached* (*"the request did not ask to change the
medium, so keep it"*), and listing it here as well would have told the model the request governs the
medium wherever the request says "anime", which is exactly what the maintainer's rule refuses. Second, the
two ask sites had already drifted apart once, so a structural test asserts both carry the wording.

### Wardrobe is tuned liberally, and that is not a departure from failing safe

The garment noun space is unbounded — `blazer`, `waistcoat`, `cardigan`, `kimono`, `sunglasses` were
all absent — so nouns alone cannot close it. The **constructions** do most of the work
(`wearing`/`wore`/`worn`, `dressed in|as|up`, `outfit`/`costume`/`clothes`/`wardrobe`/`attire`).

The tuning is deliberately generous, because the two errors are not equally expensive: a false hit
costs one `WARN` on a drift claim `validate.py` itself records as *unverified and inherited*, while a
miss costs a compiler that contradicts the brief.

> **Failing safe is a rule about what the compiler ASSERTS, not a polarity every boolean inherits.
> For a check that asserts preservation, the safe direction is NOT firing.**

The generalisation of that: two consumers wanted **opposite tunings from one boolean**. Splitting it
in two would have created a pair that drifts. Making the tuning-sensitive consumer the only one that
cares — by fixing the ask so it is correct either way — was the cheaper structure.

### Deliberately not fixed

- **`MEDIUM`'s narrowness.** Not a defect. A bare adjective must not count; that is the maintainer's rule
  and the control that keeps it honest stays green.
- **`ACTION`'s incompleteness.** Bounded on purpose. `TRANSFORM_PATTERNS` can be complete because
  English has about eight ways to say "restyle this" — which is why §41's gap there was a real defect.
  There are thousands of action verbs, and `governs[ACTION]` reaches no mechanism. So: the common
  verbs, correctly inflected, and no chase. The inflections are now **generated** from one rule plus
  an explicit irregular/doubling table, because hand-inflected alternations went half-done exactly as
  §41 predicted — `swims?` had no "swimming", `stands? up` needed a preposition to fire at all,
  `crouch(?:es|ing)?` had no past tense.
- **Per-term wardrobe holding** (drop the garment the request speaks to, keep the rest — hold `jeans`
  while the shirt changes). Better in principle, and declined: it overturns §36's settled
  all-or-nothing ruling for marginal value, and the value it buys is more of the same unverified
  per-shot drift claim. *My decision, revisitable.*
- **A model call to judge "does the request speak to X".** Would end determinism in a pure function
  that the validator, the writer and the record all read. Refused.

### For the maintainer, not for me

**Whether `R15-wardrobe-not-restated` earns its place at all.** Its own comment says the per-shot
drift it guards *"traces to the same single community author as the camera claim and is unverified
here"* — the locally observed drift was **between generations**, which this rule does not address. It
is a `WARN` whose suppression gate is not reliably decidable by any regex, guarding an inherited
claim. That is a measurement or a ruling, not a refactor, and it is the one question here I have left
open rather than answered.

### Falsification record

61 tests added. All 47 behavioural assertions were **shown red** against `e234035` before the fix;
the 14 that already passed did so accidentally, through the substring bug (`dress` inside "dressed",
`coat` inside "waistcoat") and would have gone red on the word-boundary fix alone. Every control was
falsified in the direction it guards:

| control | broken by | went red on |
|---|---|---|
| ordinary description keeps every attribute | adding bare `shot` to framing, bare `in a` to wardrobe | *"a cinematic, moody shot of the man walking"*, *"he waits in a stone corridor"* |
| a substring is not a word | restoring `word in text` against the **new** longer lists | 10 tests, including the `R15` hold |
| every verb in every inflection | deleting the consonant-doubling branch | `drop`, `step`, `grab` |
| both ask sites state the rule | (already red before the fix) | the phrase count |

The inflection test's form table is **hand-written from the dictionary, not generated by the expander
it tests** — §41's trap was an author whose regex and tests came out of one mental sentence, so they
agreed with each other and covered a sixth of the input space. A generated expectation would have
reproduced that exactly.

348 tests, 20 golden controls, all green.

---

## 43. `attribute_transfer` never meant what we built on it (2026-08-11)

A live compile of *"the man from the sheet walks down a stone corridor lit by a wall torch, reimagined
as a 1990s cel animation"* announced `attribute_transfer` in the findings and the model wrote
`fully_preserved`, with nothing reporting the disagreement. The question brought to me was whether a
check was missing. **It was not. The compiler was wrong and the model was right.**

`ref-en.txt` §4.1, which is the authority and was not read closely enough two entries ago:

| marker | the spec's own words |
|---|---|
| `fully_preserved` | *The defined **role** of the referenced content is fully preserved* |
| `partially_preserved` | *The referenced content is still used, but some defined characteristics are changed* |
| `attribute_transfer` | *Referenced characteristics are transferred to **a different identifiable target subject*** |
| `weak_reference` | *Only broad similarity in style, category, composition, or atmosphere is retained* |

A **different target subject.** §36 read `attribute_transfer` as *"identity carried, look replaced"*
and routed transformation intent into it. Restyling the same man keeps the same identifiable subject,
so the marker never applied. The sheet's defined role is to supply his identity; his identity *is*
fully preserved; the rendering medium is not a retention relationship at all.

**The worst property of this bug is that it validated.** It was a legal value from the correct closed
set, carrying the wrong meaning — so no rule could catch it, and the only visible symptom was a model
that "disagreed". This is the enum-drift failure mode, and it is the quietest one there is.

### What the model does when left alone, measured

Five compiles of the same brief, five different seeds:

| | `<Subject 1>` marker | style opening carries the requested medium |
|---|---|---|
| 5 / 5 | `fully_preserved` | yes |

One of them reconciled both in the retention line by itself, listing the subject's appearance and
then closing with *"… are retained **and animated in a 1990s cel style**"*. So the writer reads §4.1
correctly and puts the medium in the **style opening of `detailed_description`**, which is where the
spec puts the target video's look. The channel was never the marker.

`marker_for_plate` is therefore **deleted**, not narrowed — with it, the licence's whole involvement in
retention markers, and the `licence` parameter that had been threaded through `build_subjects`,
`_collapse_sheet`, `_collapse_environment` and `build_plan` to carry it. Markers come from
`_ROLE_MARKER`, which is role-derived and grounded in the spec's own role/marker coupling (`R6`–`R8`).
The frame-anchor exemption from §36 is **moot**: it existed only to stop an override that no longer
exists, so nothing we emit can trip `R6` or `R7` any more. Its test survives with the assertion
inverted, and it is now the guard against the override returning at all.

> **§36's ruling stands where it was about the maintainer's rule and falls where it was about the format.**
> "The reference governs any attribute the request does not explicitly speak to" is untouched;
> `transformation_intent`, `governs[MEDIUM]` and `style.py` all keep working exactly as before. What
> fell is a mapping the maintainer never asked for and the spec defines differently.

### The check that *was* missing, and where

`R16` checks the style opening's grammar; `P1` checks it exists; **nothing checked what it says.** With
the marker no longer carrying the intent, that opening is the *only* channel — and §41 already records
this exact failure once: the caller asked for a departure and silently got the reference's style back.

`R23-transformation-not-in-style-opening`, `WARN`. It compares **medium buckets, and detects the
failure rather than confirming the success.** That asymmetry is measured, not cautious:
`classify_medium("1990s cel animation")` is `None`, because the targets a transformation names are
routinely outside the closed vocabulary — which is why `transform_target` reads them from the request
in the first place. A rule demanding the opening *match* the requested medium would fire on precisely
the requests it exists to serve. What is decidable is the one bad outcome: the opening came back in the
**reference's** bucket.

`WARN` by §40's test, applied *before* shipping rather than after four narrowings. Right: the model
rewrites one sentence, decidable, converges. Wrong: the opening is already correct and the classifier
misbucketed it, the model has nothing to change, both rounds exhaust and the entire written brief is
lost to the fallback. Same shape as the phrase blacklist that demoted `G2`.

### The rule's own false positive, caught by its own guard test

The first arming condition was `observed_medium != requested_medium`. On the live artifact that is
`"2d-animation" != None` → armed → **and it fired on output that was right.** The plate is "Digital
illustration" (`2d-animation`) and the target is a 1990s cel animation (`None`): both media are in fact
2D, so the correct opening lands in the reference's own bucket.

`None` means *the classifier could not place it*, not *it is different*.

> **§35's line, one layer down, made by the author who had written it into §42 an hour earlier:
> absence of a statement is not a statement of absence.** Three entries now. It does not present itself
> as that mistake — each time it looks like an ordinary inequality.

Arming now requires **both** media to be classifiable and different, and the cost is stated rather
than hidden: **`R23` only covers transformations that cross a bucket the classifier knows** —
live-action to animation, animation to stop-motion. A restyle *within* one family is invisible to it,
and no bucket comparison can see that one. That is the honest limit of a deterministic check here, and
the extension point if it ever needs to be better.

What caught it was insisting the false-positive guard run against **real model output through the real
arming decision**. A hand-built `Context` would have passed forever.

### One common cause, and it is not the one proposed

The proposal was that the licence never reaches the validator. The truer statement:

> **The licence layer asserted things it had never checked against the source of truth.** §42 was a
> false claim about the *request* ("the request is silent about X"). This is a false claim about the
> *format* (`attribute_transfer`). Both are the compiler **stating** where it should have been
> **checking** — and both were silent because a false assertion validates perfectly.

That is why the fixes run in opposite directions and are still one fix: §42 stopped asserting and
started stating the rule conditionally; this deletes an assertion and adds the one check that is
actually decidable.

### Verification

Both cases re-run live after the change:

| case | request | armed? | opening the model wrote | `R23` |
|---|---|---|---|---|
| A | reimagined as a 1990s cel animation | no — target unclassifiable | *"a 1990s cel animation style, … flat color shading, distinct black outlines"* | silent |
| B | reimagined as claymation puppets | **yes**, on `2d-animation` | *"a tactile claymation style, with visible surface textures"* → `stop-motion` | silent |

Case B is the load-bearing one: the rule is genuinely watching and still silent, because the model got
it right. Case A alone could not distinguish a correct rule from a sleeping one. Both artifacts are
frozen as fixtures, and B's retention line reconciled the two channels unprompted again — *"retained
**and rendered in a claymation style**"*.

Nine tests added. Falsified: the arming re-broadened → the two real-artifact guards go red; the rule
ignoring its flag → the armed guard and the no-transformation control go red; the spec row edited →
the citation test goes red; the override re-introduced → the anchor test goes red. The spec citation is
now **machine-checked**, because this whole reversal rests on one sentence and §38's lesson is that a
convention in prose constrains nobody — including the person who read it.

357 tests, 20 golden controls, all green.
