"""The panel restates comfyui/tray.py's naming rule, and these tests fail when the two drift.

What may name a slot is deliberately ONE rule, stated in comfyui/tray.py and enforced there. The
panel now restates it, because a rule that only refuses at queue time cannot stop a name being
typed. Two statements of one rule is a rule that drifts, so the drift is what gets tested: these
read the shipped JavaScript as text and hold it against the Python that governs it.

No node and no browser. The panel's behaviour is proved by driving it; what is proved here is the
narrower and more durable thing -- that the alphabet and the reserved word in the browser are the
ones this package refuses by. Every scan asserts that it found something first, because a regex that
quietly stops matching is a test that passes forever.
"""
from __future__ import annotations

import pathlib
import re

import pytest

from comfyui import tray as T

WEB = pathlib.Path(__file__).resolve().parents[1] / "comfyui" / "web"
TRAY_JS = (WEB / "tray.js").read_text(encoding="utf-8")

# Every class name the panels put on an element, and every one their stylesheets define. The
# stylesheets are template literals, so a stray backtick anywhere inside one -- a class name quoted
# in a comment is the easy way to write one -- ends the literal early, and everything past that
# point stops being CSS. ComfyUI says nothing when that happens: the extension throws on import and
# the whole panel is simply absent, with the node still there and every widget still working. The
# names below are how that is caught from Python, which is the only place this suite runs.
CLASS_USED = re.compile(r"(?<!-)\b(oh3-[a-z0-9-]+)")
CLASS_STYLED = re.compile(r"\.(oh3-[a-z0-9-]+)")


def _stylesheets() -> str:
    """Every `const CSS = ...` template literal in the pack, as the text between its backticks."""
    out = []
    for path in sorted(WEB.glob("*.js")):
        src = path.read_text(encoding="utf-8")
        start = re.search(r"^const CSS = `", src, re.MULTILINE)
        if not start:
            continue
        end = src.find("`", start.end())
        assert end > 0, f"{path.name}'s stylesheet is opened and never closed"
        out.append(src[start.end():end])
    assert out, "no stylesheet was found in the pack, so this scan is blind"
    return "\n".join(out)


def _js(source: str, name: str) -> str:
    """One `const NAME = <literal>;` from a JS file, as the literal's own text."""
    m = re.search(rf"^const {name} = (.+);$", source, re.MULTILINE)
    assert m, f"{name} is no longer declared in the panel, so this comparison is blind"
    return m.group(1).strip()


def _js_string(source: str, name: str) -> str:
    """One declared JavaScript string literal, unquoted but NOT unescaped, so the comparisons below
    read the same characters the browser was handed."""
    raw = _js(source, name)
    assert raw[0] == raw[-1] and raw[0] in "'\"", f"{name} is not a plain string literal: {raw}"
    return raw[1:-1]


# ------------------------------------------------------------- the panel is there at all to judge

def test_every_class_the_panels_put_on_an_element_is_one_they_style():
    """The cheapest proof from here that a stylesheet is whole.

    A panel whose stylesheet was cut short still runs and still puts its classes on its elements, and
    what reaches the canvas is an unstyled pile: rows outside the node, no board, no chips. Nothing
    on the Python side can see that. What it CAN see is a class the pack asks for and never defines,
    which is what a cut-short stylesheet leaves behind in quantity.
    """
    styled = set(CLASS_STYLED.findall(_stylesheets()))
    assert len(styled) > 30, f"only {len(styled)} classes are styled, so a stylesheet is truncated"
    used = set()
    for path in sorted(WEB.glob("*.js")):
        used |= set(CLASS_USED.findall(path.read_text(encoding="utf-8")))
    assert not used - styled, (
        f"these classes are put on elements and never styled: {sorted(used - styled)}. Either the "
        "rule is missing, or a stylesheet was ended early by a backtick inside it.")


# --------------------------------------------------------------- the naming rule, one rule twice

def test_the_panel_types_in_the_alphabet_the_tray_accepts():
    """`LABEL_CHAR` in tray.js is the one-character form of `LABEL` in tray.py.

    The panel writes every label that exists, so the set it can emit has to be inside the set the
    enforcer takes. Compared as the character class's own text: `LABEL` is anchored and repeated and
    `LABEL_CHAR` matches one character, and stripping those two differences leaves the same body.
    """
    body = T.LABEL.pattern
    assert body.startswith("^[") and body.endswith("]+$"), (
        "tray.py's LABEL is no longer a plain anchored character class, so comparing it to the "
        "panel's by text no longer means anything. Compare them another way.")
    assert _js(TRAY_JS, "LABEL_CHAR") == f"/[{body[2:-3]}]/", (
        "the panel types names in a different alphabet than the tray accepts. comfyui/tray.py's "
        "LABEL is the authority; tray.js's LABEL_CHAR has to be the same set.")


def test_the_panel_demands_the_letter_or_digit_the_tray_demands():
    """The second half of the rule: `-` alone is not a name. Both sides look for the same thing."""
    demanded = re.search(r'search\(r"(\[[^"]+\])", label\)', pathlib.Path(
        T.__file__).read_text(encoding="utf-8"))
    assert demanded, "tray.py no longer searches a character class for the letter-or-digit rule"
    assert _js(TRAY_JS, "LABEL_ALNUM") == f"/{demanded.group(1)}/"


def test_the_panel_holds_back_exactly_the_names_the_tray_reserves():
    reserved = _js(TRAY_JS, "RESERVED")
    assert reserved == "[" + ", ".join(f'"{w}"' for w in T.RESERVED) + "]", (
        f"tray.py reserves {T.RESERVED} and the panel holds back {reserved}. A word reserved on one "
        "side only is a name the panel offers and the queue refuses.")


# Every character the panel turns into a dash, written the way the JavaScript writes it so the
# declaration can be read as text, beside the character it actually stands for.
SEPARATORS = ((" ", " "), (r"\t", "\t"), (r"\n", "\n"), (r"\r", "\r"), (r"\f", "\f"),
              (r"\v", "\v"), ("_", "_"), (".", "."), ("/", "/"), ("\\\\", "\\"))


@pytest.mark.parametrize("written,character", SEPARATORS)
def test_every_character_the_panel_translates_becomes_a_legal_name(written, character):
    """The panel turns each of these into `-` as it is typed. Nothing it can produce that way may be
    a name the tray then turns away, which is the whole point of translating rather than warning."""
    declared = _js_string(TRAY_JS, "SEPARATORS")
    assert written in declared, (
        f"{character!r} is no longer one of the characters the panel translates, so this case is "
        "testing nothing")
    T.check_label("the-man", {})
    with pytest.raises(Exception) as bad:
        T.check_label(f"the{character}man", {})
    assert "letters, digits and dashes" in str(bad.value), (
        f"{character!r} is refused for some other reason than the alphabet, so translating it to a "
        "dash is not what makes this name legal")


def test_a_name_of_only_translated_separators_is_still_refused_by_both():
    """`___` types through as `---`, which is legal characters and not a name. The panel refuses it
    on commit and so does the tray; neither may let it past."""
    with pytest.raises(Exception) as bad:
        T.check_label("---", {})
    assert "letter or digit" in str(bad.value)
    assert "LABEL_ALNUM.test(name)" in TRAY_JS, (
        "the panel no longer checks for a letter or digit before taking a name, so a slot called "
        "--- can be typed and only refused at queue time")


def test_the_panel_folds_accents_rather_than_dropping_them():
    """A folded name has to be a name. `jose` with an acute becomes `jose`, which the tray takes."""
    assert 'normalize("NFD")' in TRAY_JS and r"\p{M}" in TRAY_JS, (
        "the panel no longer folds accents, so a Spanish name loses its letters instead of keeping "
        "them")
    T.check_label("jose", {})
    T.check_label("pinata", {})
    with pytest.raises(Exception):
        T.check_label("josé", {}), "the fold is needed because the accent itself is refused"
