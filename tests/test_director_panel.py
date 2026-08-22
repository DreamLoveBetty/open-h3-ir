"""The seven directors are written down twice, and this is what makes that one list rather than two.

`h3ir/director.py` is the authority: it is what the compiler sends to the writer, what the CLI
prints, and what `GET /v1/directors` publishes. `comfyui/web/director.js` carries a copy, because
the pack imports nothing from `h3ir`, the compiler may be on another machine, and a text box that
needs a running service before it can show you a paragraph is a text box that is empty exactly when
somebody is trying to write in it. The panel writes that copy straight into the node's field, so a
drift between the two is not cosmetic: it is a graph that compiles a different director from the one
the canvas said it loaded, with nothing anywhere to say so.

No node and no browser. The JavaScript is read as text, which is the only thing this suite can do,
and every scan asserts that it found something first -- a regex that quietly stops matching is a
test that passes forever.
"""
from __future__ import annotations

import pathlib
import re

from h3ir import director as D

JS = (pathlib.Path(__file__).resolve().parents[1]
      / "comfyui" / "web" / "director.js").read_text(encoding="utf-8")


def _strings(src: str) -> str:
    """The value of a JavaScript expression that is double-quoted string literals joined by `+`.

    That is exactly the shape the file uses and nothing else, so this needs no parser: take every
    double-quoted run, unescape the two escapes the file can contain, and concatenate.
    """
    parts = re.findall(r'"((?:[^"\\]|\\.)*)"', src)
    return "".join(p.replace('\\n', "\n").replace('\\"', '"').replace("\\\\", "\\") for p in parts)


def panel_directors() -> list[dict]:
    """Every entry of the panel's `DIRECTORS`, in order, as {id, name, notes}."""
    start = JS.index("const DIRECTORS = [")
    end = JS.index("\n];", start)
    body = JS[start:end]
    out = []
    for block in re.split(r"\n  \{\n", body)[1:]:
        head = re.search(r'id: "([^"]+)", name: "([^"]+)",', block)
        assert head, f"an entry has no id/name line: {block[:120]!r}"
        notes = block[block.index("notes:") + len("notes:"):]
        out.append({"id": head.group(1), "name": head.group(2),
                    "notes": _strings(notes).strip()})
    assert out, "the panel's DIRECTORS list was not found, so this whole file is blind"
    return out


def test_the_panel_offers_exactly_what_the_compiler_ships():
    panel = panel_directors()
    assert [d["id"] for d in panel] == [d.id for d in D.DIRECTORS]
    assert [d["name"] for d in panel] == [d.name for d in D.DIRECTORS]


def test_every_panel_profile_is_the_compilers_own_text_word_for_word():
    """The one that matters. A near-copy is worse than a divergent one: it looks right on the canvas
    and writes something else into the graph."""
    for shown, real in zip(panel_directors(), D.DIRECTORS):
        assert shown["notes"] == real.notes.strip(), (
            f"{real.id}: the panel's text and the compiler's have drifted apart. "
            f"panel {len(shown['notes'])} chars, compiler {len(real.notes.strip())}.")


def test_the_seven_are_seeded_into_the_store_as_ordinary_directions():
    """The owner's shape: "just preload the list with them, they should be able to be removed too."

    So the seven are not a category the list draws differently, they are seven files written on
    first use under their own full names. Everything else follows from that -- one kind of row, one
    delete path, and a rename that works on a shipped one exactly as it works on yours.
    """
    seed = JS[JS.index("  async seed() {"):]
    seed = seed[:seed.index("\n  }")]
    assert "for (const d of DIRECTORS)" in seed, "the seed no longer writes the shipped seven"
    assert "this.path(d.name)" in seed, \
        "a seeded direction is filed under something other than its own name"
    assert "JSON.stringify({ name: d.name, notes: d.notes })" in seed, \
        "a seeded direction no longer holds the compiler's own text"
    assert "overwrite=false" in seed, \
        "the seed may overwrite something already in the store, which would eat a user's own work"


def test_nothing_treats_a_shipped_name_as_special_any_more():
    """The rule that a saved direction could not be called James Cameron existed because the seven
    lived somewhere else. They live in the store now, so that rule is not just unnecessary, it would
    be wrong: it would refuse to rename the very row it is protecting.

    The check is that no name-comparison against DIRECTORS survives anywhere in the control paths,
    because a leftover one fails in the confusing direction -- a delete or a rename that silently
    does nothing on seven rows out of the list.
    """
    for dead in ("d.name.toLowerCase() === name.toLowerCase()",
                 "never shadows a shipped one",
                 "one of the seven that ship is already called"):
        assert dead not in JS, f"a shipped-name special case survives: {dead!r}"
    # In code, the seven are read in exactly two places: where they are declared and where they are
    # seeded. A third would be a control path that knows a shipped one when it sees it. Comment
    # lines are dropped first, because prose about the seven is not a special case for them.
    code = [ln for ln in JS.split("\n")
            if not ln.lstrip().startswith(("*", "/*", "//"))]
    uses = [ln for ln in code if re.search(r"\bDIRECTORS\b", ln)]
    assert len(uses) == 2, (
        f"DIRECTORS is read in {len(uses)} places and should be two, its declaration and the "
        f"seed: {uses}")


def test_the_panel_shows_the_camera_vocabulary_the_compiler_publishes():
    """The list somebody writing their own profile reads. A drifting copy teaches a word the
    renderer has no move for, which is the failure the closed table exists to prevent."""
    start = JS.index("const CAMERA_MOVES = [")
    moves = re.findall(r'"([^"]+)"', JS[start:JS.index("\n];", start)])
    assert tuple(moves) == D.CAMERA_MOVES


def test_the_panel_states_the_same_cap_the_compiler_refuses_at():
    """The panel says the number while there is still something to do about it; the compiler is what
    refuses. Two statements of one limit is a limit that drifts."""
    m = re.search(r"const MAX_NOTES = (\d+);", JS)
    assert m, "the panel's cap was not found"
    assert int(m.group(1)) == D.MAX_NOTES_CHARS


def test_a_saved_direction_is_stored_as_the_node_field_itself():
    """The whole reason saving needs no new contract: a saved file holds exactly the two keys the
    node's widget holds, so nothing is translated on the way in or out. The moment the file grows a
    third key, or the widget's shape and the file's shape stop being the same object, a saved
    direction becomes a format with a version and this stops being a two-field node."""
    from comfyui.h3ir_client import director_bundle

    assert re.search(r'body: JSON\.stringify\(\{ name, notes \}\)', JS), \
        "the save no longer writes the same object the node's field holds"
    # what it writes back is what the node reads: the same two keys, and nothing else
    assert director_bundle(profile='{"name":"Sodium yard","notes":"Held wide."}') == {
        "name": "Sodium yard", "notes": "Held wide."}


def test_the_saved_store_is_namespaced_to_this_pack():
    """A folder ComfyUI's own user store, and every other pack's, cannot be standing in. `openh3ir/`
    is the same name the tray's uploads already use, so one pack is one folder to inspect or delete."""
    m = re.search(r'const SAVED_DIR = "([^"]+)";', JS)
    assert m, "the saved-directions folder was not found"
    assert m.group(1).startswith("openh3ir/"), \
        f"{m.group(1)!r} is not inside this pack's own folder"


def test_renaming_moves_a_direction_instead_of_leaving_a_copy():
    """The owner asked to rename one without creating a duplicate, and rename is not a button: it is
    what save does when the name changed on the direction you are editing.

    The order is the whole test. Writing the new name first and deleting the old one after means a
    failed write loses nothing; the other order loses the direction. And the delete is guarded by
    `renaming`, or saving an edit under the same name would delete what it just wrote.
    """
    body = JS[JS.index("  async save() {"):]
    body = body[:body.index("\n  async forget()")]
    assert "const renaming = this.on !== null && this.on !== name;" in body, \
        "save no longer notices that the name changed on the direction being edited"
    write_at = body.index('method: "POST"')
    delete_at = body.index('method: "DELETE"')
    assert write_at < delete_at, \
        "the old name is deleted before the new one is written, so a failed write loses the whole "\
        "direction"
    assert body.index("if (renaming) {") < delete_at, \
        "the delete is not guarded by renaming, so saving an edit would delete what it just wrote"


def test_every_field_the_panel_draws_carries_a_visible_label():
    """The owner's standing rule for panels this pack draws itself, and he had said it before:
    "the placeholder is not enough ... doesn't have a label".

    A placeholder is gone on the first keystroke, so a field labelled only by one is unlabelled for
    everybody who has started. The media tray already labels every field it draws (`name`,
    `what it is`, `about it`); this is the same idiom, not a second one.
    """
    # The rule is that a label EXISTS and survives typing, not what it says. Pinning the words here
    # would make every copy pass fail a test about structure, and the owner writes this copy.
    m = re.search(r'class: "oh3d-nlabel"[^)]*\}\s*,\s*\n\s*el\("span", \{ textContent: "([^"]+)"',
                  JS)
    assert m and m.group(1).strip(), \
        "the writing box lost its visible label and is back to a placeholder alone"
    assert ".oh3d-nlabel{" in JS, "the label has no style, so it is unstyled text"
    # and it is in the panel, above the box, rather than built and never appended
    assert "this.notesLabel, this.notesIn," in JS, \
        "the label is not placed immediately above the box it names"


def test_no_em_dash_reaches_anything_the_owner_reads():
    """He treats an em dash as a machine tell, so none may appear in a string this panel shows.

    The seven director profiles are excluded, and deliberately: they are the COMPILER's prose,
    living in `h3ir/director.py`, mirrored here byte for byte and pinned by the test above. The dash
    is doing grammatical work in them, rewriting them changes what the writing model is sent, and
    it would have to be done on both sides at once. That is a separate decision with its own
    evidence; this rule is about the panel's own chrome.
    """
    start = JS.index("const DIRECTORS = [")
    chrome = JS[:start] + JS[JS.index("\n];", start):]
    offenders = [ln.strip() for ln in chrome.split("\n")
                 if "\u2014" in ln and not ln.lstrip().startswith(("*", "/*", "//"))]
    assert not offenders, "an em dash reached the panel's own text: " + " | ".join(offenders)[:300]


def test_the_over_the_limit_message_describes_a_refusal_and_not_a_degraded_run():
    """`h3ir/director.py` REFUSES a direction over the cap at intake. The panel used to say it would
    "crowd out the request itself", which describes a worse compile rather than no compile, and
    would have somebody queue and wait to learn otherwise."""
    assert "Too long to run. Trim it to ${MAX_NOTES.toLocaleString()} characters." in JS, \
        "the over-the-limit message no longer says it is a hard stop"
    assert "crowds out the request" not in JS
    # and the number lives in the counter, so the sentence can be about what to do
    assert "`${n.toLocaleString()} of ${MAX_NOTES.toLocaleString()} characters`" in JS


def test_the_board_keeps_the_width_of_the_node_it_fills():
    """One line that looks like it could be deleted, and cannot.

    The frontend writes a `width` onto every widget from a node layout pass each time a value
    changes. For a full-bleed DOM board that number is wrong, and the wrapper follows it: measured
    on the canvas, choosing a director set it to 238 on a node still 480 wide, the panel collapsed
    to 218px, and the name field was squeezed to eleven pixels -- `Denis Villeneuve` rendered as
    `De`. It never recovered at any node size, and it predates the guard fix this file was reopened
    for. Unset is the state the widget starts in and the state that renders correctly.

    The media tray does not need this because it pins its node to one size; this node is
    deliberately resizable, so it has to say the board has no width of its own.
    """
    assert 'Object.defineProperty(w, "width", { get: () => null, set: () => {}, configurable: true });' in JS, \
        "the board no longer holds its width against the frontend's per-render layout pass"


def test_the_panel_works_out_which_stored_direction_the_box_is_before_deciding_anything():
    """What a workflow carries is words and a name, never a pointer into the store, so `render()`
    clears the panel's idea of which direction it is holding. Everything that has to know then gets
    it wrong at once: `forget` disappears for a direction sitting in its own list, the button offers
    to `rename` a direction to the name it already has, no row is marked, and save reads its own
    direction as somebody else's and asks to overwrite it.

    That last one is the same false question the owner already hit once, moved onto a button. So the
    reconciliation is not a nicety for the highlight -- it is the fact four other decisions read.

    It is a byte-for-byte comparison of the words, keyed on the name, which is one request rather
    than one per row. Same name and different words is a real edit and must NOT resolve, or saving
    it would silently overwrite the stored one.
    """
    rec = JS[JS.index("  async reconcile() {"):]
    rec = rec[:rec.index("\n  }")]
    assert 'if (String(stored?.notes ?? "") !== notes) return;' in rec, \
        "the reconciliation no longer compares the words, so an edit reads as the stored direction"
    assert "this.on = name;" in rec.split('!== notes) return;')[1], \
        "the reconciliation sets the row before it has confirmed the words match"
    # the four things that read it
    assert "this.forgetBtn.style.display = this.on === null" in JS, "forget stopped reading it"
    assert "const renaming = this.on !== null && this.on !== this.nameIn.value.trim()" in JS, \
        "the rename label stopped reading it"
    assert "name !== this.on;" in JS, "save's overwrite question stopped reading it"
    assert "this.on === name ?" in JS, "the list highlight stopped reading it"
    # reachable from both places the panel repaints from the graph, in either order
    assert "await this.reconcile();" in JS and re.search(r"\n    this\.reconcile\(\);\n  \}", JS), \
        "the reconciliation is not reached from both refreshLibrary and render"

def test_the_button_says_rename_when_it_is_about_to_rename():
    """One button does two things, and the one it is about to do is readable before the click.

    Renaming is the only move on this panel that can surprise somebody: start from a shipped
    direction, give it your own name, press save, and the shipped one is what you renamed. That is
    the behaviour that was asked for -- rename without leaving a duplicate -- so the fix is not to
    change it but to stop it being a surprise, which costs a word and no control.
    """
    assert re.search(r'renaming \? "rename" : "save"', JS), \
        "the button no longer says rename when a click on it would rename"
    assert 'const renaming = this.on !== null && this.on !== this.nameIn.value.trim()' in JS, \
        "the label no longer tracks the same condition the save path acts on"
    # and the tooltip names what would be renamed, rather than describing saving in general
    assert "`Renames ${this.on} to what is in the field" in JS


def test_the_panel_wide_pointer_handler_leaves_the_caret_alone():
    """One handler on the panel puts down a half-pressed question and closes the open list, and it
    runs BEFORE the click handler of whatever was pressed. So every control that owns one of those
    two decisions has to be excluded from it, or the decision is taken twice and cancels out.

    Both exclusions are here because the canvas found them, and neither is visible by reading:

      * without the caret excluded, this closed the list and the caret's toggle reopened it in the
        same click, so the one control that opens the list could never close it.

    A second exclusion used to be needed for the list, back when choosing a row asked a question.
    Rows answer nothing now, so a click in the list is a click elsewhere and putting the question
    down is the right thing to do with it.
    """
    body = JS[JS.index('this.root.addEventListener("pointerdown"'):]
    body = body[:body.index("\n    });")]
    assert 'const inList = Boolean(e.target.closest?.(".oh3d-list"));' in body, \
        "the handler no longer knows whether the click was inside the list"
    assert "const onCaret = e.target === this.openBtn;" in body, \
        "the handler no longer knows whether the click was on the caret"
    assert "if (this.armed && !answering)" in body, \
        "the handler no longer puts down a half-pressed question"
    assert "if (this.listOpen && !inList && !onCaret)" in body, \
        "the caret cannot close the list it opens"


def test_what_asks_is_exactly_what_cannot_be_got_back():
    """Which actions confirm, decided by whether anything can undo them.

    Measured, and it settled the question in the opposite direction to my first guess. ComfyUI's
    undo restores a whole direction that a CHOICE replaced -- ctrl+Z brings the name and the prose
    straight back. It does NOT restore what somebody TYPED: after typing eighty characters and
    choosing a row, ctrl+Z returned an empty object rather than the words, however long the undo
    stack was left to settle. So typing that was never saved is unrecoverable, and it is the one
    thing in the box worth a question.

    The rest is the store, which undo never reaches at all.

    **This is asserted as STATE, not as clicks.** The owner's bug was a guard firing on a state that
    had nothing to protect, and both a click-count test and a "does it ask" test would have passed
    on it. What matters is the condition each guard reads.
    """
    def body_of(fn, until):
        i = JS.index(fn)
        return JS[i:JS.index(until, i)]

    # 1. unsaved typing, and NOT a direction the panel knows is stored -- that is what `this.on` is
    choose = body_of("  choose(name) {", "\n  }")
    assert "const unsaved = this.notesIn.value.trim() && this.on === null;" in choose, \
        "choosing a row no longer distinguishes unsaved typing from a stored direction, which is " \
        "the bug the owner reported: it asked about a director sitting in its own list"
    assert "if (unsaved && this.armed !== `pick:${name}`) {" in choose
    # an empty box is not writing, and a stored one is not unsaved: neither may ask
    assert ".trim() &&" in choose, "an empty box would arm the guard"

    # 2. and 3. the store: overwriting a DIFFERENT direction, and deleting one
    save = body_of("  async save() {", "\n  async forget()")
    assert "const overwriting = this.saved.includes(name) && name !== this.on;" in save, \
        "save either stopped asking, or asks about overwriting the direction you are already editing"
    assert 'if (overwriting && this.armed !== "save") {' in save
    forget = body_of("  async forget() {", "\n  //")
    assert 'if (this.armed !== "forget") {' in forget, "forget deletes a file without asking"

    # every one of them stops before doing the thing it just asked about
    for what, fn in (("choosing", choose), ("save", save), ("forget", forget)):
        after = fn[fn.index("this.armed = "):][:400]
        assert "return;" in after, f"{what} arms and then does the thing anyway"

    # and the question appears ON what was clicked, never only in the message line: a control that
    # looks unchanged after a press is indistinguishable from a broken one, which is how the owner
    # read it -- "reads as 'button didn't work'"
    assert 'this.saveBtn.textContent = this.armed === "save" ? "overwrite?"' in JS
    assert 'this.forgetBtn.textContent = this.armed === "forget" ? "delete?"' in JS
    assert "armed(name) ? `${label}: this replaces what you wrote. Click again.` : label" in JS, \
        "the row that is asking no longer says so where the pointer is"
    assert ".oh3d-lrow.oh3d-larm,.oh3d-lrow.oh3d-larm:hover{" in JS, \
        "the asking row is not written against hover, so it paints in the ordinary hover grey"

    # nothing on screen may claim a stored direction is unsaved
    assert "and it is not saved" not in JS

def test_the_node_field_the_panel_writes_is_the_one_the_node_declares():
    """The panel edits a widget by name. A rename on either side leaves the node with a visible
    panel that writes into nothing, which looks exactly like a panel that works."""
    from comfyui.h3ir_client import director_bundle

    assert re.search(r'\(w\) => w\.name === "profile"', JS), \
        "the panel no longer binds to a widget called 'profile'"
    # and the shape it writes is the shape the node reads back
    assert director_bundle(profile='{"name":"Mine","notes":"Sodium."}') == {"name": "Mine",
                                                                           "notes": "Sodium."}
    assert director_bundle(profile="{}") is None
