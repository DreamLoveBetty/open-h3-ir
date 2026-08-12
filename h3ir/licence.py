"""Who governs each attribute: the reference plate, or the request.

**The owner's rule, and it replaces my earlier one.** The reference plate governs any attribute
the request does not explicitly speak to. Where the request explicitly specifies an attribute,
the request governs. **A loose adjective is not an explicit specification.**

His reason is drift, and it is the better argument than mine. If a throwaway style word can
override an observed plate, the same character drifts between shots according to how carelessly
each request happened to be worded. A reference exists to be preserved; departing from it has to
be *asked for*, not inferred. I had argued the opposite — that obeying a stated word is safer
because ignoring an instruction is undiagnosable — and that reasoning is sound only if the word
was deliberate, which "anime" demonstrably was not.

One rule covers both cases that came up, with no special-casing:

  * "the man walks forward down the corridor toward the camera" **is** explicit about what his
    body does, so it governs over the plate's stance.
  * "Anime style, cinematic" is **not** an explicit instruction to depart from the plate's look,
    so the plate keeps the medium.

**Where the transformation intent travels, corrected (§43).** An earlier version of this docstring
claimed "Reimagine as", "restyle to", "in the style of" is exactly `attribute_transfer` — identity
carried, look replaced — and routed the intent into the plate's retention marker. That was a
misreading of the spec's own table. `ref-en.txt` §4.1: *"`attribute_transfer` | Referenced
characteristics are transferred to a **different identifiable target subject**"*. Restyling the same
man keeps the same identifiable subject, so the marker never applied, and it was a legal value from
the correct closed set carrying the wrong meaning — which validates cleanly and is therefore silent.

The intent travels through the **style opening of `detailed_description`**, which is what the spec
uses for the target video's look and what the writing model does unprompted (five of five live runs).
`resolve_style` produces that phrase; `R23-transformation-not-in-style-opening` checks the prose
obeyed it. The retention markers describe identity retention per label and are the writer's to choose.

Resolution is per ATTRIBUTE, not per brief: a request is routinely explicit about the action and
silent about wardrobe, lighting and framing.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .models import AssetCard, AssetKind, Brief

# --------------------------------------------------------------------------- attributes

ACTION = "action"
MEDIUM = "medium"
WARDROBE = "wardrobe"
LIGHTING = "lighting"
FRAMING = "framing"
PALETTE = "palette"
ATTRIBUTES = (ACTION, MEDIUM, WARDROBE, LIGHTING, FRAMING, PALETTE)

# A transformation is the ONLY thing that makes the medium the request's business. A bare
# adjective is a description of what the caller thinks they attached, not an instruction to
# change it -- which is exactly the ambiguity that failing safe resolves toward preservation.
# The transforming verb and its preposition may be separated by an object ("reimagine THE MAN
# as anime"), so the gap is allowed but bounded -- an unbounded gap would match half a sentence.
#
# The verbs carry their INFLECTIONS. Written in the bare infinitive, `\breimagine\b` cannot match
# the `d` in "reimagined" -- and the past participle is the natural way to write the instruction, so
# "reimagined as anime" fell through to preservation without a single finding. The caller asked for a
# departure and silently got the reference's style back. `redrawn`/`redrew` are irregular, which is
# why this is an explicit list rather than a suffix bolted onto each stem.
TRANSFORM_PATTERNS = tuple(re.compile(p, re.I) for p in (
    r"\b(?:reimagin(?:e|es|ed|ing)|restyl(?:e|es|ed|ing)|redraw(?:s|n|ing)?|redrew"
    r"|re-?render(?:s|ed|ing)?|convert(?:s|ed|ing)?|transform(?:s|ed|ing)?)"
    r"\b[^.;]{0,40}?\b(?:as|to|into|in)\b",
    r"\bin\s+the\s+style\s+of\b",
    r"\bturn\s+(?:it|this|them|the\s+\w+)\s+into\b",
    r"\bmake\s+(?:it|this|them|the\s+\w+)\s+(?:look\s+)?like\s+a?\b",
    r"\bas\s+(?:a|an)\s+\w+\s+(?:version|render|drawing|painting|animation|adaptation)\b",
    r"\binstead\s+of\s+the\s+reference\b",
    r"\bnot\s+the\s+reference'?s?\s+style\b",
    r"\bstyle\s+transfer\b",
))

# --------------------------------------------------------------------------- the matcher
#
# **A word, not a substring.** The original matcher was `word in text.lower()`, so every entry also
# matched every longer word containing it -- and the collisions land on the commonest words in
# English. `"hat"` matched **"that"** and **"what"**; `"lit"` matched **"quality"**, **"military"**,
# **"little"** and **"elite"**; `"cap"` matched "landscape", `"dress"` matched "addresses", `"suit"`
# matched "pursuit".
#
# That direction of the error is the dangerous one. A miss withholds an attribute from the request,
# which is the fail-safe direction the owner asked for. A false HIT hands the attribute to the
# request on a brief that never mentioned it -- the drift the rule exists to prevent, arriving
# through the matcher instead of through the policy -- and for wardrobe it silently switched off
# `R15`'s garment hold on any brief containing the word "that".
#
# Separators are flexible so one entry covers the ways a phrase is really written: `close-up`,
# `close up` and `closeup` are one entry, as are `over the shoulder` and `over-the-shoulder`. A
# trailing `s?` keeps the plural without listing it.
def _word_pattern(words: tuple[str, ...]) -> re.Pattern[str]:
    alts = "|".join(r"[\s-]*".join(re.escape(p) for p in re.split(r"[^0-9a-z']+", w) if p) + "s?"
                    for w in words)
    return re.compile(rf"\b(?:{alts})\b", re.I)


# --------------------------------------------------------------------------- action
#
# Explicit statements about the subject's body. A request naming what someone DOES governs the
# pose, which is how the pose question resolves under the same rule.
#
# **The verb space here is genuinely open, and that is the difference from `TRANSFORM_PATTERNS`.**
# There are about eight ways in English to say "restyle this", so that list can be complete and its
# incompleteness was a real defect (§41). There are thousands of action verbs, so this list can never
# be complete -- and it does not need to be, because `governs[ACTION]` reaches nothing but one
# sentence in the writer's ask. No mechanism reads it. So: the common verbs, correctly inflected,
# and no chase. See §42 for why that is a ranking and not a shrug.
#
# The inflections are GENERATED. Written by hand, half the entries got a participle and half did not
# -- `swims?` had no "swimming", `stands? up` needed a preposition to fire at all, and
# `crouch(?:es|ing)?` had no past tense. One rule plus an exception table is fewer lines than sixty
# hand-written alternations and cannot go half-done.
_IRREGULAR_VERBS = {
    "run": ("run", "runs", "ran", "running"),
    "sit": ("sit", "sits", "sat", "sitting"),
    "stand": ("stand", "stands", "stood", "standing"),
    "swim": ("swim", "swims", "swam", "swimming"),
    "fall": ("fall", "falls", "fell", "falling"),
    "throw": ("throw", "throws", "threw", "thrown", "throwing"),
    "speak": ("speak", "speaks", "spoke", "spoken", "speaking"),
    "say": ("say", "says", "said", "saying"),
    "stride": ("stride", "strides", "strode", "striding"),
    "kneel": ("kneel", "kneels", "knelt", "kneeled", "kneeling"),
    "swing": ("swing", "swings", "swung", "swinging"),
    "spin": ("spin", "spins", "spun", "spinning"),
    "ride": ("ride", "rides", "rode", "ridden", "riding"),
    "rise": ("rise", "rises", "rose", "risen", "rising"),
    "shake": ("shake", "shakes", "shook", "shaken", "shaking"),
    "fight": ("fight", "fights", "fought", "fighting"),
    "catch": ("catch", "catches", "caught", "catching"),
    "bend": ("bend", "bends", "bent", "bending"),
}
# Final consonant doubles before -ed/-ing. Listed rather than detected: the CVC rule needs stress to
# be applied correctly ("enter" does not double, "prefer" does), and guessing it would be a third
# thing that silently half-works.
_DOUBLING_VERBS = ("drop", "step", "grab", "stop", "nod", "shrug", "hug", "slam", "grip", "slip",
                   "jog", "tap", "clap", "drag", "stab", "trip")


def _verb_forms(base: str) -> tuple[str, ...]:
    """Every inflection of one verb: bare, third person, past, participle."""
    if base in _IRREGULAR_VERBS:
        return _IRREGULAR_VERBS[base]
    if base in _DOUBLING_VERBS:
        stem = base + base[-1]
        return (base, base + "s", stem + "ed", stem + "ing")
    if base.endswith("e"):
        return (base, base + "s", base[:-1] + "ed", base[:-1] + "ing")
    if base.endswith("y") and base[-2] not in "aeiou":
        return (base, base[:-1] + "ies", base[:-1] + "ied", base[:-1] + "ying")
    if base.endswith(("s", "sh", "ch", "x", "z")):
        return (base, base + "es", base + "ed", base + "ing")
    return (base, base + "s", base + "ed", base + "ing")


ACTION_VERBS = (
    "walk", "run", "sprint", "jog", "dash", "stride", "step", "march", "crawl", "climb", "jump",
    "leap", "fall", "collapse", "stumble", "trip", "slide", "roll", "swim", "ride", "dance",
    "turn", "spin", "sit", "stand", "rise", "kneel", "crouch", "lean", "bend", "stretch", "shake",
    "nod", "shrug", "wave", "point", "reach", "lift", "carry", "throw", "toss", "drop", "grab",
    "catch", "hold", "press", "push", "pull", "open", "close", "knock", "slam", "kick", "punch",
    "fight", "swing", "block", "dodge", "duck", "hug", "kiss", "look", "glance", "stare", "watch",
    "smile", "frown", "laugh", "cry", "scream", "shout", "whisper", "speak", "say", "sigh",
    "breathe", "wait", "enter", "approach", "follow", "pick", "hand",
)
ACTION_PATTERNS = (_word_pattern(tuple(f for v in ACTION_VERBS for f in _verb_forms(v))),)

# --------------------------------------------------------------------------- wardrobe
#
# **The one attribute where a miss has a mechanism behind it.** `governs[WARDROBE] == "request"`
# suppresses `compile._wardrobe_terms`, so a miss makes the compiler go on insisting the prose
# restate the plate's t-shirt against a request whose purpose is to replace it -- the exact `R15`
# collision §36 recorded, still open for every garment outside this list. `blazer` was not in it.
#
# The garment noun space is unbounded, so the nouns alone cannot close it; the CONSTRUCTIONS do most
# of the work. And the two errors are not equally expensive: a false hit costs one WARN on a drift
# claim `validate.py` itself records as unverified, while a miss costs a compiler that contradicts
# the brief. So this detector is deliberately tuned to be liberal -- which is not a departure from
# failing safe. Failing safe is a rule about what the compiler ASSERTS; for a check that asserts
# preservation, the safe direction is NOT firing.
GARMENT_WORDS = ("shirt", "t-shirt", "tee", "jeans", "trousers", "pants", "shorts", "jacket",
                 "blazer", "coat", "overcoat", "hoodie", "sweater", "jumper", "cardigan", "vest",
                 "waistcoat", "blouse", "dress", "skirt", "leggings", "tights", "armour", "armor",
                 "suit", "uniform", "robe", "kimono", "sari", "cloak", "cape", "poncho", "apron",
                 "tracksuit", "overalls", "sneakers", "trainers", "boots", "shoes", "sandals",
                 "high heels", "hat", "cap", "beanie", "helmet", "hood", "headscarf", "scarf",
                 "gloves", "belt", "sunglasses", "glasses", "goggles", "mask", "veil", "hijab",
                 "necktie", "bow tie")
WARDROBE_PATTERNS = tuple(re.compile(p, re.I) for p in (
    r"\b(?:wear(?:s|ing)?|wore|worn)\b",
    r"\bdress(?:ed|es|ing)\s+(?:in|as|up)\b",
    r"\b(?:outfit|costume|clothing|clothes|wardrobe|attire|garment)s?\b",
))

# --------------------------------------------------------------------------- lighting, framing, palette
#
# These three reach ONE sentence in the ask and nothing else -- no marker, no rule, no gate. Widened
# because the wrong emphasis is still wrong, ranked below wardrobe because being wrong costs a hint.
#
# Framing is anchored on a camera word, never on a bare direction, and that is load-bearing rather
# than fussy: "from above" is how LIGHTING gets written ("harsh light from above") and "shot" alone
# is how a treatment word rides ("a cinematic shot of the man"). So the signal is `shot from`,
# `seen from`, or a named angle. Colour NAMES are likewise absent from the palette list -- "a red
# jacket" is wardrobe, not a grade.
LIGHTING_WORDS = ("lighting", "lit", "backlit", "underlit", "backlighting", "sunlight", "sunlit",
                  "torchlight", "moonlight", "moonlit", "candlelight", "candlelit", "firelight",
                  "lamplight", "lamp", "streetlamp", "streetlight", "fluorescent", "incandescent",
                  "neon", "floodlight", "spotlight", "searchlight", "headlight", "daylight",
                  "golden hour", "blue hour", "overcast", "shadow", "silhouette", "silhouetted",
                  "key light", "fill light", "rim light", "hard light", "soft light",
                  "harsh light", "bounce light", "practical light", "light from", "chiaroscuro",
                  "dim", "dimly", "glow", "glowing")
FRAMING_WORDS = ("close-up", "medium shot", "wide shot", "wide angle", "two shot",
                 "over the shoulder", "reverse angle", "shot from", "seen from", "viewed from",
                 "filmed from", "framed on", "tight on", "aerial", "drone shot", "overhead shot",
                 "establishing shot", "tracking shot", "static shot", "insert shot", "macro shot",
                 "profile shot", "low angle", "high angle", "eye level", "dutch angle",
                 "bird's eye", "worm's eye", "crane shot", "dolly", "zoom", "handheld", "pov",
                 "point of view", "portrait", "full body")
PALETTE_WORDS = ("palette", "monochrome", "monochromatic", "black and white", "greyscale",
                 "grayscale", "desaturated", "saturated", "muted", "vivid", "vibrant", "pastel",
                 "warm tones", "cool tones", "cold tones", "neutral tones", "earth tones",
                 "earthy tones", "sepia", "colour grade", "color grade", "colour grading",
                 "color grading", "graded", "high contrast", "low contrast", "contrasty",
                 "teal and orange", "tinted", "tint", "hue", "colour cast", "crushed blacks",
                 "lifted blacks")

_WORD_PATTERNS: dict[tuple[str, ...], re.Pattern[str]] = {}


def _mentions(text: str, words: tuple[str, ...]) -> bool:
    """Whether the text names one of these words. Whole words, never substrings -- see `_word_pattern`."""
    pat = _WORD_PATTERNS.get(words)
    if pat is None:
        pat = _WORD_PATTERNS[words] = _word_pattern(words)
    return bool(pat.search(text or ""))


def transformation_intent(brief: Brief) -> str | None:
    """The phrase that asks for a departure from the reference's look, or None."""
    for pat in TRANSFORM_PATTERNS:
        m = pat.search(brief.intent or "")
        if m:
            return m.group(0)
    return None


def transform_target(brief: Brief) -> str:
    """The style asked for, read from the request rather than from a term list.

    "in the style of a 1990s cel animation" names a target no closed vocabulary will contain, and
    falling back to the plate there would ignore an explicit transformation -- the one case where
    the request genuinely does govern.
    """
    intent = brief.intent or ""
    for pat in TRANSFORM_PATTERNS:
        m = pat.search(intent)
        if not m:
            continue
        tail = intent[m.end():]
        # Up to the first clause boundary; a target is a short noun phrase, not a sentence.
        target = re.split(r"[.;,]|\band\b|\bwhile\b|\bas\b(?!\s+a)", tail, maxsplit=1)[0]
        target = re.sub(r"^\s*(?:a|an|the)\s+", "", target.strip(), flags=re.I)
        target = re.sub(r"\s+", " ", target).strip(" -–—")
        if target:
            return target[:60]
    return ""


@dataclass
class Licence:
    """Who governs each attribute, and why."""

    governs: dict[str, str] = field(default_factory=dict)   # attribute -> "request" | "reference"
    transform_phrase: str | None = None
    reasons: dict[str, str] = field(default_factory=dict)

    @property
    def medium_transferred(self) -> bool:
        """A transformation was asked for AND there is a reference for it to depart from.

        Deliberately NOT just `governs[MEDIUM] == "request"`. With no visual reference the request
        governs every attribute *by default* -- there is nothing to defer to -- and reading that
        default as a transformation made two different things go wrong at once: a text-only brief
        announced "the request asks for a transformation (None) ... the plate's retention marker is
        attribute_transfer", naming a plate the manifest does not contain; and an audio-only
        reference was handed `attribute_transfer`, a marker from the VISUAL vocabulary, for an asset
        with no image in it.

        Nothing is transferred when there is nothing to transfer from.
        """
        return self.transform_phrase is not None and self.governs.get(MEDIUM) == "request"

    # There was a `marker_for_plate` here, and it is DELETED rather than narrowed. It returned
    # `attribute_transfer` for every visual plate under a transformation, on the reading that the
    # marker means "identity carried, look replaced". `ref-en.txt` §4.1 defines it as:
    #
    #     | `attribute_transfer` | Referenced characteristics are transferred to a different
    #                              identifiable target subject |
    #
    # A different *target subject*. Restyling the same man is not that -- he is the same identifiable
    # subject, so the marker was false, and it validated because it is a legal value from the right
    # closed set used with the wrong meaning. The marker that does cover "still used, some
    # characteristics changed" is `partially_preserved`, and choosing between it and `fully_preserved`
    # depends on what the definition line actually claims, which the writer knows and this code does
    # not. So the licence does not decide a retention marker at all.
    #
    # The medium travels through the STYLE OPENING of `detailed_description`, which is where the spec
    # puts it, where `style.py` already sends it, and where five live runs put it unprompted. `R23`
    # checks that channel. The frame-anchor exemption that used to live here is moot with the override
    # gone: nothing we emit can trip R6 or R7 any more. See §43.

    def note(self) -> str | None:
        if self.medium_transferred:
            return (f"the request asks for a transformation ({self.transform_phrase!r}), so the "
                    "reference's identity is carried and its rendering style is replaced; that "
                    "belongs in the style opening of detailed_description, not in a retention marker")
        return None


def resolve_licence(brief: Brief, cards: dict[str, AssetCard]) -> Licence:
    intent = brief.intent or ""
    has_visual_ref = any(c.kind in (AssetKind.IMAGE, AssetKind.VIDEO) for c in cards.values())
    transform = transformation_intent(brief)

    lic = Licence(transform_phrase=transform)

    def decide(attr: str, explicit: bool, why: str) -> None:
        if not has_visual_ref:
            lic.governs[attr] = "request"
            lic.reasons[attr] = "no visual reference is attached"
            return
        lic.governs[attr] = "request" if explicit else "reference"
        lic.reasons[attr] = why if explicit else (
            f"the request does not explicitly specify {attr}, so the reference governs it")

    decide(ACTION, any(p.search(intent) for p in ACTION_PATTERNS),
           "the request states what the subject does")
    decide(MEDIUM, transform is not None,
           f"the request asks for a transformation ({transform!r})")
    decide(WARDROBE, _mentions(intent, GARMENT_WORDS)
           or any(p.search(intent) for p in WARDROBE_PATTERNS),
           "the request speaks to what the subject wears")
    decide(LIGHTING, _mentions(intent, LIGHTING_WORDS), "the request names the lighting")
    decide(FRAMING, _mentions(intent, FRAMING_WORDS), "the request names the framing")
    decide(PALETTE, _mentions(intent, PALETTE_WORDS), "the request names the palette")
    return lic
