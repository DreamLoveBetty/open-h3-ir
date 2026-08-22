"""The director profile: whose taste fills the space the request and the references leave open.

**It is a name and a paragraph, and that is the whole record.** `licence.py` resolves every
attribute to the request or to the reference, and `compose_brief` ends that block with the sentence
"Anything neither the request nor the references settles is yours." That residual is where a film's
voice actually lives — the lens, the light, what the frame considers important, what the room sounds
like — and until now it was filled by whatever the writing model reached for by default. A profile
puts a name on it, in the caller's own words.

So the ladder is unchanged and gains a floor rather than a rival:

    the request       governs any attribute it explicitly speaks to      (licence.py)
    the references    govern any attribute the request leaves open       (licence.py)
    the director      governs what neither of them settles               (here)

**Steered, not enforced, and that is the owner's shape.** "Why can't we just pass a long-text
profile and let the openh3-ir do its thing with the stuff it can already do, but thinking like a
profile? Not mechanically enforced, just steered?" So there are no axes, no vocabularies, no
checker, and nothing here narrows a rotation or suppresses a sentence. The profile is prose in the
ask, sitting under a head that says it yields, exactly where the licence block has already said in
computed terms which attributes the request took.

**Which leaves exactly one question: can prose in the ask move STRUCTURE?** Rule 1 says it must not,
and the answer is the same one the creativity dial gives. Shot count and cut times are the caller's
contract when they pin `shots` — the ask states the count, `T11-shot-count-pinned` is an ERROR if the
document disagrees, and no profile can reach past that. When `shots` is unset the writer decides the
edit, which is what `auto` means and has always meant, and a profile is one more thing the writer
reads while deciding, like the request itself. That is steering, and it is the setting's own
promise. `tests/test_director.py` holds both halves.

**What it costs to be prose, stated plainly.** A profile that describes a score the creativity dial
will not license would be a contradiction we authored, which the model then spends a fix round on --
`Scope.brief_instruction`'s docstring records that failure from the other direction. So one sentence
is added to the head when no score can exist, saying so. It is a sentence, not a suppression: the
caller's words are never edited, only placed under an instruction that outranks them.

**Naming a director to the model is off, and that is the owner's call rather than a measurement.**
"Without doing example shots btw, otherwise the model is just gonna output those." A name is the
shortest path to that failure. What the measurement supports is only that the traits carry the work
on their own (5.46 signature markers a cell against 0.75 for no profile at all); at n=28 it cannot
show that the name buys nothing, and it does not show harm either. So the profile's `name` reaches
the report and the record, and never the writer.
"""
from __future__ import annotations

from dataclasses import dataclass, fields


@dataclass(frozen=True)
class Director:
    """One profile: what to call it, and what it asks for."""

    id: str
    name: str        # what the canvas and the report show. Never sent to the writer.
    notes: str       # the whole profile, in the caller's own words.
    origin: str = "builtin"     # builtin | custom


# --------------------------------------------------------------------------- what ships
#
# Seven, chosen to SPAN rather than to be a list of favourites. Two are the owner's own ("Imagine
# james cameron and quentin tarantino ... using MiniMax h3, they wouldn't produce the same things,
# right?"); the other five occupy regions neither of the first two reaches -- rigid symmetry,
# enormous stillness, carried immediacy, obstructed intimacy, and the reaction shot.
#
# THERE WAS AN EIGHTH AND IT WAS CUT, recorded here so nobody adds it back as an oversight. A David
# Fincher profile measured as a coin flip: 8/24 on the blind sort against a 12.5% chance line, and
# +4% camera lift where the rest of the set ran +12% to +33%. The cause was not a bad profile -- it
# was that the writer's UNPROMPTED house style is already Fincherish, and the null arm's own camera
# moves score 96% against his list. A name in the menu that changes almost nothing is worse than an
# absent one, because the user cannot tell a subtle profile from a broken one.
#
# **Every sentence is a DISPOSITION, and there is no example shot in this file** -- no [Shot N], no
# timestamp, no <d>, no quoted sample line and no film title. Not because a checker refuses them:
# because showing the model a shot gets that shot back, and these are the seven texts every user
# starts from and edits. They teach what a good profile looks like by being one.
#
# **The camera moves are named in the prose, in H3's own words.** Its motion table is closed
# (base-en.txt 4.3) and off-vocabulary wording measurably under-uses the strongest lever the model
# has, so the names belong in the text where the writer reads them -- not in a schema that would
# refuse a user for spelling one differently. `CAMERA_MOVES` below is the list, published so a
# surface can show it to somebody writing their own.
CAMERA_MOVES: tuple[str, ...] = (
    "Zoom In", "Zoom Out", "Push In", "Pull Out", "Pan Left", "Pan Right", "Truck Left",
    "Truck Right", "Tilt Up", "Tilt Down", "Pedestal Up", "Pedestal Down", "Arc Shot",
    "Tracking Shot", "Static Shot", "Shake Slightly", "Shake Strongly", "POV", "Roll Clockwise",
    "Roll Counterclockwise")

DIRECTORS: tuple[Director, ...] = (
    Director(
        id="cameron", name="James Cameron", notes=(
            "The camera is mounted and travelling — it rides with the body or the machine rather "
            "than observing them, and it finishes a move on a different part of the space from the "
            "one it started on. Reach first for Tracking Shot, Push In, Truck Left, Truck Right, "
            "Pull Out, Arc Shot, Pedestal Up, Pedestal Down and Shake Strongly; leave Static Shot "
            "and the rolls alone.\n"
            "Frame wide enough that the space and the hardware in it read as large against the "
            "person, and tighten onto a face only at the moment a decision gets made. Low angles, "
            "letting a structure loom over whoever is under it.\n"
            "Light with hard sources that exist inside the frame — work lamps, flares, screens, "
            "fire — carving figures out of a cold cyan-blue ambient, with atmosphere thick enough "
            "that a beam has a shape in the air, and one warm amber source somewhere against the "
            "blue.\n"
            "Spend the description on the mechanism: what a thing is made of, what is bolted to "
            "what, the readout, the water, the load a surface is taking. Then the face, at the "
            "point where the person decides.\n"
            "Bodies show competence under load. They brace, grip, take weight and keep working, and "
            "the effort shows in the hands and the jaw before it reaches the voice. Delivery is "
            "clipped, functional, and pitched slightly too loud for the room.\n"
            "The room is close mechanical detail over a low pressurised bed — servo, hydraulic, "
            "metal under stress, water moving as mass — with its own hum continuing underneath all "
            "of it. A score is full orchestra with one solo instrument carrying the line above it, "
            "percussion entering under the movement, a wide dynamic range, building across a long "
            "sustained rise instead of arriving already loud.")),
    Director(
        id="tarantino", name="Quentin Tarantino", notes=(
            "The camera sits still and keeps holding after the action in the shot has finished. "
            "When it does move it starts abruptly, travels fast and stops dead instead of easing "
            "out. Reach first for Static Shot, Zoom In, Zoom Out, Pan Left, Pan Right, Truck Left, "
            "Truck Right, Tilt Down and POV; leave Arc Shot, the pedestals and the shakes alone.\n"
            "Frame flat and frontal while people talk, from a lens height that is either eye level "
            "or startlingly low, looking up from below the tabletop. An insert is enormous relative "
            "to the thing it shows.\n"
            "Light from ordinary sources — daylight through a window, tungsten in a room, the flat "
            "fluorescent of a public interior — but the colour off them is rich and heavily "
            "saturated: deep reds, hot yellows, warm browns, blacks that stay warm. Surfaces are "
            "worn, greasy and used, lit so the wear reads as colour rather than as grime.\n"
            "Point the camera at hands, feet and footwear, the object on the table, what somebody is "
            "eating, the thing being carried, the boot of a car — and a face kept in frame after it "
            "has stopped speaking.\n"
            "People talk at length about small unrelated things, relaxed and unhurried, then stop "
            "mid-thought and change tone inside a single beat. Delivery is easy and conversational "
            "until it drops flat and quiet.\n"
            "The room is dry and close — a chair on a hard floor, cutlery, a hard-soled step, the "
            "exact mechanical sound an object makes as it is picked up and set down, very little air "
            "in it. A score is source-flavoured rather than orchestral: reverb-heavy surf guitar, a "
            "soul rhythm section, spaghetti-western brass, an isolated whistled line, holding one "
            "tempo and one volume from start to finish with no swell under the action.")),
    Director(
        id="anderson", name="Wes Anderson", notes=(
            "The camera sits dead centre and moves only along a rigid axis — a fast flat pivot to "
            "the next arrangement, a straight lateral, or a straight advance. It never curves and "
            "never comes off the horizontal. Reach first for Static Shot, Pan Left, Pan Right, "
            "Truck Left, Truck Right, Zoom In, Tilt Down and Push In; leave Arc Shot, Tracking "
            "Shot, the shakes, the rolls and POV alone.\n"
            "Frame in one-point perspective, perfectly symmetrical, the subject centred and square "
            "to the lens looking very nearly down the barrel. An insert is a flat overhead plan view "
            "of objects laid out in a row.\n"
            "Light evenly and almost shadowlessly, high key, with no source doing anything dramatic. "
            "A small closed palette of related saturated colours — buttery yellows, pinks, faded "
            "reds, sage — against a pale ground.\n"
            "Point the camera at things that were arranged on purpose: labelled objects, printed "
            "matter, the contents of a container, a hand presenting an item flat to the lens, an "
            "itemised row of possessions.\n"
            "Performance is deadpan and upright. Bodies are held square and still, heads turn on the "
            "horizontal, and feeling is said out loud instead of shown. Delivery is flat and quick, "
            "evenly paced, with no emphasis on any word.\n"
            "The room is clean and slightly stylised — a small number of specific isolated sounds, "
            "each one distinct, over a quiet and almost neutral room tone. A score is plucked "
            "strings, harpsichord or celesta playing a brisk repeated figure at a fixed tempo held "
            "steady throughout, or one unaccompanied acoustic guitar.")),
    Director(
        id="villeneuve", name="Denis Villeneuve", notes=(
            "The camera stays still for a long time, and when it moves it travels in one continuous "
            "motion at a constant slow rate from the start of the move to the end of it. Reach "
            "first for Static Shot, Push In, Pull Out, Pedestal Up, Pedestal Down, Tilt Up, Arc "
            "Shot and Tracking Shot; leave the zooms, the shakes, the rolls and the pans alone.\n"
            "Frame the extreme wide where a figure is a small mark against the mass of the thing "
            "behind it, cut against a face filling the frame with nothing legible behind it. "
            "Nothing in the middle.\n"
            "Light with one hard directional source through a great deal of atmosphere — dust, fog, "
            "particulate — so the light has volume. Reduce the frame nearly to a single hue at a "
            "time, ochre or slate or near-black, and let figures go to silhouette against a bright "
            "void.\n"
            "Spend the description on mass and scale — the surface of a structure, the distance to a "
            "horizon, how much empty space surrounds a body — and then a face, small in the frame, "
            "with the rest of the frame empty.\n"
            "Performance is withheld. Bodies move slowly and deliberately, hold still for a long "
            "time before acting, and give almost nothing away. Delivery is quiet, low and unhurried, "
            "often barely above the room.\n"
            "The room is enormous low-frequency air: wind across open ground, a long decay on every "
            "impact, and real near-silence between events rather than a bed filling the gaps. A "
            "score is a sustained low drone with brass swelling out of it at a very slow tempo and "
            "no discernible melody, instruments added one at a time, the volume rising continuously "
            "to the end.")),
    Director(
        id="bigelow", name="Kathryn Bigelow", notes=(
            "The camera is carried and reacting rather than planned — it finds the subject a beat "
            "late, corrects, and gets jostled by what is happening beside it. It stands among the "
            "people in the scene rather than apart from them. Reach first for Shake Slightly, Shake "
            "Strongly, Tracking Shot, Truck Left, Truck Right, Pan Left, Pan Right, Push In and "
            "POV; leave Arc Shot, the rolls and Static Shot alone.\n"
            "Frame on a long lens from a real distance, so the frame is cropped tight and partly "
            "blocked by whatever sits between the camera and the subject. The subject falls wherever "
            "it happens to fall, often off-centre and part-cut by the frame edge.\n"
            "Light with whatever the location actually has and nothing added — flat overcast "
            "daylight, dust-bleached sun, one work light, night lit only by what somebody switched "
            "on. The colour is drained rather than rich: greys, dust, washed blue-white, no warmth "
            "put back anywhere and no source arranged to flatter anything.\n"
            "Point the camera at procedure: the sequence of actions a trained person performs, "
            "equipment being used correctly, hands doing a specific technical job, and the periphery "
            "being scanned for what is about to happen.\n"
            "Performance is professional and unglamorous. People do a job under stress, and effort "
            "and fear show as breathing and small errors rather than as expression. Delivery is "
            "terse, overlapping and functional.\n"
            "The room is immediate and unmixed — breathing inside the frame, gear and fabric, sharp "
            "transient impacts with no tail, and a background that keeps intruding on the "
            "foreground. A score is very quiet and very sparse: one low sustained tone, or a dry "
            "percussive pulse at a steady unchanging rate, mixed below the sound of the room.")),
    Director(
        id="wong", name="Wong Kar-wai", notes=(
            "The camera watches from just outside the moment, low and close, drifting slowly "
            "sideways past whatever is in the way, and never repositions for a clear view. Reach "
            "first for Static Shot, Truck Left, Truck Right, Push In, Pan Left, Pan Right and Tilt "
            "Down; leave Arc Shot, the pedestals, Shake Strongly and the rolls alone.\n"
            "Frame tight and obstructed — taken through a doorway, a grille, a mirror or the back of "
            "someone's head, with a foreground object cutting into a third of the frame and the "
            "subject pushed to the edge of it.\n"
            "Light in saturated practical colour at night: neon and signage bleeding into the air, "
            "tungsten pools, jade green and deep red against black, a smear of light around every "
            "source and no even fill anywhere.\n"
            "Point the camera at repeated intimate detail — a cigarette, a clock, a sleeve, steam "
            "coming off food, a hand not quite touching another one — and at the small distance "
            "between two people who are not looking at each other.\n"
            "People stand very close together and do not touch. A hand lifts partway and comes back "
            "down. Movements start late and finish slowly, and delivery is soft, quiet and aimed "
            "slightly away from whoever it was meant for.\n"
            "The room keeps the intimate layer close and the world muffled behind it — a fan, rain "
            "on an awning, distant traffic, crockery in another room, all of it slightly too far "
            "away. A score is one instrument carrying a short melody that repeats without "
            "developing — solo strings, a plucked guitar, a slow Latin waltz — at a fixed unhurried "
            "tempo, the same figure repeating from beginning to end at one volume.")),
    Director(
        id="spielberg", name="Steven Spielberg", notes=(
            "The camera advances steadily onto whoever is seeing something and keeps advancing after "
            "they have registered it — the move ends on a face rather than on the thing that caused "
            "it. Reach first for Push In, Tracking Shot, Truck Left, Truck Right, Pedestal Up, Tilt "
            "Up, Arc Shot and Pull Out; leave Shake Strongly, the rolls and POV alone.\n"
            "Frame at eye level or slightly below, so the world reads at the height of whoever is "
            "smallest in the scene. A clean wide that holds the whole group, then a slow tightening "
            "onto one reaction inside it.\n"
            "Light with a strong warm source from behind or beside the subject, throwing a visible "
            "shaft through haze or dust, edges rimmed bright, faces lifted by a soft bounce, and the "
            "source often flaring straight into the lens.\n"
            "Point the camera at the reaction rather than the cause — what a face does at the moment "
            "it understands, a group turning together, a small object held out on an open palm. The "
            "thing itself is frequently kept out of frame.\n"
            "Performance is readable and unguarded. Wonder, fear and recognition arrive on the face "
            "fully and without irony; bodies lean in, reach out, take a step forward. Delivery is "
            "warm and overlapping, and people talk over each other.\n"
            "The room has layered naturalistic depth — the near sound, the middle-distance activity "
            "and a real horizon behind them — with the specific sound of the thing being reacted to "
            "arriving before it is seen. A score is a full orchestra carrying one clear melodic line "
            "on strings or a solo horn, which plays through in full at least once, rises, and lands "
            "resolved.")),
)

BY_ID = {d.id: d for d in DIRECTORS}


# --------------------------------------------------------------------------- rendering the ask
#
# The block is appended AFTER the creativity dial at every site that takes one, and the order is not
# cosmetic: the dial states its prohibitions absolutely ("no setting overrides that"), and the
# profile has to read as filling what is left rather than as competing with it. Reversed, the
# strongest sentence in the ask would be a taste and the absolute one would trail it.

def brief_instruction(d: Director, *, scored: bool = True) -> str:
    """What the writer is told: one head, then the caller's own words verbatim.

    Two sentences do the work the axes used to do, and they are the only two.

    The first says the profile YIELDS. It stands directly under the licence block, which has already
    named in computed terms which attributes the request took and which the references keep, so a
    profile that talks about framing on a request that stated the framing is subordinate by
    placement as well as by sentence.

    The second says APPLY, DO NOT COPY, and it is measured rather than precautionary. Without it the
    writer quoted the notes back into the description as though they were scene content -- "letting
    the moment run past the point of comfort" is a note about how to CHOOSE and describes nothing
    anyone can see or hear, which base-en.txt 4.1 rules out in as many words: "Every detail should
    correspond to something visible or audible."

    `scored` is false when the dial licenses no score. Then a third sentence says so, because a
    profile describing music that cannot exist is a contradiction WE placed in the ask -- see the
    module docstring. The caller's words are never edited; they are placed under an instruction that
    outranks them.
    """
    head = ("Direction. This is the taste that fills whatever the request and the references leave "
            "open, and it overrides neither of them. Apply it to this scene; do not copy these "
            "sentences into it.")
    if not scored:
        head += (" This piece gets no score, so ignore anything below about music — that decision "
                 "is already made and the direction does not reopen it.")
    return head + "\n" + (d.notes or "").strip()


def note(d: Director | None) -> str:
    """The provenance line, beside `Scope.note()` in the record.

    The NAME, not the id: a custom profile's id is always `custom` and the name is the only thing
    that tells two of them apart in a report.
    """
    return f"director: {d.name}" if d is not None else "director: none"


# --------------------------------------------------------------------------- taking one in

# One cap, and it is the only refusal left. Not a rule about what a profile may SAY -- the owner
# settled that: steered, not enforced -- but about how much of it there is, because every character
# rides in the ask on every call and a pasted document would come back as an unactionable context
# error from somebody's endpoint rather than as a sentence. The longest thing that ships is Cameron
# at ~1600 characters, so this is roughly three of him.
MAX_NOTES_CHARS = 5000


def check(d: Director) -> list[str]:
    """Every reason this profile cannot be used, in the words the caller should read.

    One rule, which is the whole list. A missing name is not on it: the name is what the REPORT
    calls the profile, it changes no output, and refusing a paragraph somebody wrote over a blank
    label would be a refusal for our own bookkeeping. `from_mapping` names an unnamed one instead.
    """
    n = len(d.notes or "")
    if n > MAX_NOTES_CHARS:
        return [f"the direction is {n} characters and the cap is {MAX_NOTES_CHARS}. All of it is "
                "sent with every brief, so a long one crowds out the request itself. Say the habits "
                "and cut the examples"]
    return []


def from_mapping(data) -> Director | None:
    """Build a profile from a caller's own JSON, tolerantly and without trusting any of it.

    Two keys, and both are strings, so there is nothing here that can be the wrong shape. `check()`
    runs at intake for the one thing that can still be wrong, which is the length.
    """
    if data is None:
        return None
    if isinstance(data, Director):
        return data
    g = data.get
    return Director(
        id="custom",
        name=str(g("name") or "").strip() or "Custom",
        notes=str(g("notes") or "").strip(),
        origin="custom",
    )


def to_mapping(d: Director) -> dict:
    """The shape `from_mapping` reads back, for the record and for the service's own listing."""
    return {f.name: getattr(d, f.name) for f in fields(d)}


def is_empty(d: Director | None) -> bool:
    """A profile with a name and nothing written into it steers nothing.

    Worth its own answer rather than being folded into `check()`: an empty profile is not INVALID,
    it is inert, and the difference decides whether the caller gets a refusal or a note. A node
    dropped in and left blank is somebody who has not written it yet.
    """
    return d is not None and not (d.notes or "").strip()


def unknown(value: str | None) -> str | None:
    """The id a caller named that this build does not have, or None.

    **The half of `creativity.parse`'s contract that is easy to drop.** Its docstring ends "it falls
    back to the default and the compiler records what it used", and the recording is the part that
    makes the fallback honest rather than silent. A director has the sharper version of the problem:
    a dial position is a word somebody might mistype, but a shipped id can stop existing between two
    versions of this package. `fincher` was cut before any release, so nothing in the wild names him
    -- but the next one removed will be named by somebody's saved script, and that script must not
    quietly compile with no direction at all.

    So `compile_brief` raises this as a WARN. Not an ERROR: the request is still perfectly
    renderable, and refusing a whole compile over a menu entry that moved would be worse than the
    honest sentence.
    """
    v = str(value or "").strip().lower()
    if not v or v in ("none", "custom") or v in BY_ID:
        return None
    return v


def parse(value: str | Director | None, custom: Director | None = None) -> Director | None:
    """Accept a shipped profile by id; anything unrecognised falls back, like `creativity.parse`.

    Same reasoning: a caller may be an agent that has never read this file. An unknown word must not
    fail a render -- it falls back, `unknown()` names it, and the compiler records what it used.

    The ComfyUI node never takes this path. It sends the prose, because the prose is what the user
    can see and edit on the canvas; an id is for the CLI and for an agent calling the API.
    """
    if isinstance(value, Director):
        return value
    v = str(value or "").strip().lower()
    if v in BY_ID:
        return BY_ID[v]
    # Nothing shipped was named -- "custom", "none", empty, or a word this build does not have. What
    # is left is the caller's own profile if one came with the request, and nothing if one did not.
    # `unknown()` names the word that missed, so a script pinned to a removed id is told rather than
    # quietly compiled with no direction at all.
    return custom
