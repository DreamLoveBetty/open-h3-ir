"""What the nodes look like on a canvas, checked without a canvas.

`comfyui/nodes.py` imports ComfyUI's node API at module scope, so it cannot be imported here. The
alternative to giving up on these checks was to write a fake `comfy_api` and assert against that,
which would have tested the fake. So this reads the source instead: it parses each schema declaration
and asserts on what it actually says. Crude, and it cannot prove ComfyUI draws it correctly, but it
does prove the declaration says what it is supposed to say, and it runs anywhere.

The live half of this pair is running ComfyUI and reading `/object_info`, which is how the real drawn
schema was verified. That needs a GPU box with the model files, so it is not something CI can do.

Every rule below exists because a version of these nodes got it wrong. Three of them are measurements
rather than opinions, and they are worth restating because they are the reason the labels are terse:

  * A label shares one widget row with its value and the row holds about 38 characters, so a long
    label makes both unreadable. Measured on the owner's own screenshot.
  * On a multiline STRING the placeholder is the only label there is, and with no placeholder the
    frontend prints the input's id (`createMultilineInputElement(default, placeholder || name)`).
  * `advanced` collapses widgets only under Nodes 2.0 with `Comfy.Node.AlwaysShowAdvancedWidgets`
    false. It is not a hide, so every rule here assumes every input is visible.
"""
from __future__ import annotations

import ast
import pathlib

SRC = pathlib.Path(__file__).resolve().parent.parent / "comfyui" / "nodes.py"
TEXT = SRC.read_text(encoding="utf-8")
TREE = ast.parse(TEXT)

# Input kinds whose label alone cannot explain them, so they must carry a tooltip too.
NEEDS_TOOLTIP = {"String", "Float", "Int", "Combo", "Boolean"}

# A label spends the pixels the value needs. The measured row is about 38 characters and a filename
# is most of that, so nothing here gets to be a sentence.
MAX_LABEL = 30


def _str(node: ast.AST | None) -> str:
    """Join a literal or an implicitly concatenated literal back into one string."""
    if node is None:
        return ""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(v.value for v in node.values if isinstance(v, ast.Constant))
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _str(node.left) + _str(node.right)
    return ""


def _is_input_call(node: ast.AST) -> bool:
    return (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr == "Input")


def _kind(call: ast.Call) -> str:
    """`io.Image.Input` -> "Image"; `Footage.Input` -> "Footage"."""
    owner = call.func.value
    if isinstance(owner, ast.Attribute):
        return owner.attr
    if isinstance(owner, ast.Name):
        return owner.id
    return ""


def _inputs_in(subtree: ast.AST) -> list[tuple[str, str, dict[str, ast.AST]]]:
    """Every `<Kind>.Input(...)` under one node, in declaration order, as (kind, id, keywords)."""
    found = []
    for node in ast.walk(subtree):
        if not _is_input_call(node):
            continue
        ident = node.args[0].value if node.args and isinstance(node.args[0], ast.Constant) else ""
        found.append((_kind(node), ident, {k.arg: k.value for k in node.keywords if k.arg}))
    return found


def _schemas() -> dict[str, ast.Call]:
    """Every `io.Schema(...)` call in the file, keyed by its node_id."""
    out: dict[str, ast.Call] = {}
    for node in ast.walk(TREE):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "Schema"):
            kw = {k.arg: k.value for k in node.keywords if k.arg}
            out[_str(kw.get("node_id"))] = node
    return out


def _template_input_ids() -> set[str]:
    """The ids declared inside an autogrow template.

    They are a special case in both directions: the frontend overwrites a template's display_name
    with `names[ordinal]`, so setting one is dead weight that a reader of this source would believe.
    """
    out = set()
    for node in ast.walk(TREE):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr in ("TemplateNames", "TemplatePrefix")):
            for inner in ast.walk(node):
                if _is_input_call(inner) and inner.args:
                    out.add(inner.args[0].value)
    return out


SCHEMAS = _schemas()
TEMPLATE_IDS = _template_input_ids()
# The compile node's own inputs, which is where "how many boxes is this" is decided.
COMPILE = _inputs_in(SCHEMAS["OpenH3IRCompile"])
SETUP = _inputs_in(SCHEMAS["OpenH3IRSetup"])
FOOTAGE = _inputs_in(SCHEMAS["OpenH3IRFootage"])
SOUND = _inputs_in(SCHEMAS["OpenH3IRSound"])
ALL = [(node_id, *rest) for node_id, call in SCHEMAS.items() for rest in _inputs_in(call)]


def _kw(call: ast.Call, name: str) -> ast.AST | None:
    for k in call.keywords:
        if k.arg == name:
            return k.value
    return None


def _multiline(kw: dict[str, ast.AST]) -> bool:
    node = kw.get("multiline")
    return isinstance(node, ast.Constant) and node.value is True


def _ids(inputs) -> list[str]:
    return [i for _k, i, _kw in inputs]


def _outputs_of(node_id: str) -> list[tuple[str, str]]:
    out = []
    for node in ast.walk(SCHEMAS[node_id]):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "Output"):
            kw = {k.arg: k.value for k in node.keywords if k.arg}
            out.append((_kind(node) if False else node.func.value.attr
                        if isinstance(node.func.value, ast.Attribute)
                        else node.func.value.id, _str(kw.get("display_name"))))
    return out


# --------------------------------------------------------------------------- labels a person reads

def test_every_input_a_person_can_see_carries_a_label_or_a_placeholder():
    """The widget id is what shows on the canvas when nothing else does, and an id like `sound_notes`
    on screen is the node talking to itself. Measured: it shipped like that.

    A multiline box is the exception, and not a lenient one: it has no room for a label beside its
    value, so its placeholder IS its label and the placeholder is therefore required.
    """
    nameless = []
    for node_id, kind, ident, kw in ALL:
        if not ident or ident in TEMPLATE_IDS:
            continue
        label, ph = _str(kw.get("display_name")), _str(kw.get("placeholder"))
        if _multiline(kw):
            if not ph:
                nameless.append(f"{node_id}.{ident} (multiline with no placeholder prints its id)")
        elif not label:
            nameless.append(f"{node_id}.{ident}")
    assert not nameless, f"inputs with nothing readable on them: {nameless}"


def test_a_grown_sockets_template_does_not_pretend_to_set_its_own_label():
    """`autogrowOrdinalToName` returns `{name: ..., display_name: s}` and overwrites whatever the
    template declared, so a `display_name` on a template input is a claim the canvas ignores. The old
    node set one to "a thing in the shot" and the sockets still read `reference_0`."""
    claimed = [f"{n}.{i}" for n, _k, i, kw in ALL
               if i in TEMPLATE_IDS and _str(kw.get("display_name"))]
    assert not claimed, f"template display names the frontend overwrites: {claimed}"


def test_a_multiline_box_does_not_also_carry_a_display_name():
    """Two labels for one box, one of which the canvas will not draw. The placeholder is the label
    there, so a display name is a second thing to keep in step for no gain."""
    doubled = [f"{n}.{i}" for n, _k, i, kw in ALL if _multiline(kw) and _str(kw.get("display_name"))]
    assert not doubled, f"multiline inputs with a redundant display name: {doubled}"


def test_the_first_line_of_a_placeholder_stands_alone():
    """A short box shows one line, so line one has to be the whole instruction. `the man` on its own
    teaches nothing about what the box is for."""
    for node_id, _k, ident, kw in ALL:
        ph = _str(kw.get("placeholder"))
        if not ph:
            continue
        first = ph.splitlines()[0].strip()
        assert len(first.split()) >= 4, f"{node_id}.{ident}: placeholder line one is {first!r}"


def test_no_label_is_an_identifier():
    """An underscore in a label means the identifier leaked onto the canvas, which is what happened:
    `sound_notes` and `spoken_words` were showing as-is."""
    offenders = [f"{n}.{i} -> {_str(kw.get('display_name'))!r}" for n, _k, i, kw in ALL
                 if "_" in _str(kw.get("display_name"))]
    assert not offenders, f"identifiers used as labels: {offenders}"


def test_no_label_is_long_enough_to_hide_its_own_value():
    """The measurement behind every terse label in this pack: a label and its value share one row of
    about 38 characters, so `H3 weights for reference and text jobs` left no room for the filename it
    was labelling and neither could be read."""
    long = [f"{n}.{i} -> {_str(kw.get('display_name'))!r}" for n, _k, i, kw in ALL
            if len(_str(kw.get("display_name"))) > MAX_LABEL]
    assert not long, f"labels that will eat their own value: {long}"


def test_a_placeholder_shows_an_example_rather_than_the_field_name():
    """A placeholder is the one piece of guidance someone reads before typing, so it shows what an
    answer looks like. Repeating the label there teaches nothing."""
    offenders = []
    for node_id, _kind, ident, kw in ALL:
        ph = _str(kw.get("placeholder"))
        if not ph:
            continue
        label = _str(kw.get("display_name"))
        if ph.strip().lower() in (ident.lower(), label.strip().lower()):
            offenders.append(f"{node_id}.{ident}: {ph!r}")
    assert not offenders, f"placeholders that just repeat the name: {offenders}"


def test_no_placeholder_is_dev_talk():
    """`usually blank, worked out automatically` was on the node, and on a single-line widget the
    legacy canvas never draws a placeholder at all, so it was invisible dev talk. Single-line
    placeholders are therefore not used: the display name carries it."""
    single = [f"{n}.{i}" for n, k, i, kw in ALL
              if k == "String" and not _multiline(kw) and _str(kw.get("placeholder"))]
    assert not single, f"single-line placeholders are never drawn on the legacy canvas: {single}"


def test_every_text_number_and_choice_input_explains_itself():
    missing = [f"{n}.{i}" for n, kind, i, kw in ALL
               if kind in NEEDS_TOOLTIP and i and not _str(kw.get("tooltip"))]
    assert not missing, f"inputs with no explanation: {missing}"


def test_every_socket_explains_what_plugging_into_it_means():
    """A socket has no value to show, so its tooltip is the only thing that can say what the job is.
    An IMAGE in `first frame` and an IMAGE in `picture 1` are different H3 checkpoints."""
    missing = [f"{n}.{i}" for n, kind, i, kw in ALL
               if kind in {"Image", "Audio", "Setup", "Footage", "Sound"} and i
               and not _str(kw.get("tooltip"))]
    assert not missing, f"sockets with no explanation: {missing}"


# --------------------------------------------------------------------------- nothing that is false

def test_the_silence_flag_is_labelled_with_what_it_actually_does():
    """`prose.py` sets non-diegetic music to N/A and nothing else: it keeps ambient and sync sound
    and never touches speech. The old label said `no music or speech`, which was simply untrue, and
    a label that is wrong is worse than a label that is terse."""
    label = next(_str(kw.get("display_name")) for _k, i, kw in COMPILE if i == "silent")
    assert label == "no music"
    tip = next(_str(kw.get("tooltip")) for _k, i, kw in COMPILE if i == "silent")
    assert "score only" in tip and "Ambient" in tip, \
        "the tooltip has to say what survives, or the flag reads as a mute button"


def test_the_shot_ceiling_is_the_compilers_own_ceiling():
    """The old field offered 0 to 8 while `shots.py` clamps to MAX_SHOTS = 4, so asking for 6
    silently got 4. Offering what the engine drops is the surface lying."""
    from h3ir.shots import MAX_SHOTS

    from comfyui.h3ir_client import SHOTS

    assert SHOTS == ("auto", *(str(i) for i in range(1, MAX_SHOTS + 1)))
    kw = next(kw for _k, i, kw in COMPILE if i == "shots")
    options = _str(_kw(kw["options"], "x")) if False else kw["options"]
    assert isinstance(options, ast.Call), "the options come from the shared constant, not a literal"


def test_the_shots_widget_is_a_choice_rather_than_a_number_with_a_magic_zero():
    kinds = {i: k for k, i, _kw in COMPILE}
    assert kinds["shots"] == "Combo", "0 meaning auto was a label doing the code's job"


def test_the_creativity_tooltip_does_not_promise_extra_content_at_extreme():
    """`creativity.py` gives extreme exactly what bold has, and the cut count is off the dial at
    every position. The old tooltip implied both."""
    tip = next(_str(kw.get("tooltip")) for _k, i, kw in COMPILE if i == "creativity")
    assert "extreme adds nothing beyond bold" in tip
    assert "Shot count is never on this dial" in tip


def test_the_seconds_range_is_the_one_that_was_decided_and_the_tooltip_admits_it():
    """The range is deliberately wider than H3's trained band, so the tooltip has to say the band
    exists and the report has to say when a render left it. A wide range with a silent surface is how
    someone renders two seconds of nothing and blames the model."""
    kw = next(kw for _k, i, kw in COMPILE if i == "seconds")
    assert kw["min"].value == 1.0 and kw["max"].value == 149.0
    tip = _str(kw.get("tooltip"))
    assert "5.167 to 15.083" in tip and "the report says so" in tip


# --------------------------------------------------------------------------- one source of truth

def test_there_is_exactly_one_place_to_set_the_length():
    """Two dials that both claim to set duration is how eight seconds of a ten second script gets
    rendered. The graph used to have its own seconds and its own frame arithmetic as well."""
    duration_ish = [i for _n, _k, i, _kw in ALL
                    if any(w in i for w in ("second", "length", "duration", "frames"))
                    and i not in ("frames_model", "frames", "timeout_s")]
    assert duration_ish == ["seconds"], f"more than one duration control: {duration_ish}"


def test_the_canvas_size_is_not_a_second_source_of_truth():
    ids = _ids(ALL and [(k, i, kw) for _n, k, i, kw in ALL])
    assert "width" not in ids and "height" not in ids, \
        "the canvas comes from the frame shape; a resolution box would be able to disagree with it"


def test_there_is_no_gguf_toggle_anywhere_in_the_pack():
    """The file is the toggle. A boolean beside a filename is two controls for one fact, with two of
    its four states wrong and nothing on the canvas able to resolve them."""
    offenders = [f"{n}.{i}" for n, _k, i, kw in ALL
                 if "gguf" in i.lower() or "gguf" in _str(kw.get("display_name")).lower()]
    assert not offenders, f"a format control was added: {offenders}"


def test_the_gguf_option_lists_come_from_the_packs_own_registered_lists():
    """Globbing `*.gguf` off the folder would offer files with no loader behind them on an install
    without ComfyUI-GGUF, which is the plausible-and-wrong option this pack exists to prevent."""
    from comfyui import h3ir_client

    assert "unet_gguf" in TEXT and "clip_gguf" in TEXT
    for forbidden in ("glob(", "listdir", "scandir", "iterdir"):
        assert forbidden not in TEXT, f"nodes.py walks the disk with {forbidden}"
    # One predicate owns the extension, so there is one place to look when the rule changes, and the
    # node routes on that predicate rather than carrying its own copy of it. Constants rather than
    # source text, so documenting the rule does not count as re-implementing it.
    owners = sorted(name for name, fn in vars(h3ir_client).items()
                    if getattr(fn, "__module__", "") == h3ir_client.__name__
                    and hasattr(fn, "__code__")
                    and ".gguf" in [c for c in fn.__code__.co_consts if c is not fn.__doc__])
    assert owners == ["is_gguf"], f"the extension is tested in more than one place: {owners}"
    body = TEXT[TEXT.index("class OpenH3IRCompile"):TEXT.index("class OpenH3IRSetup")]
    assert ".gguf" not in body, "the node routes on is_gguf rather than on its own copy of the rule"


def test_no_path_prefix_is_something_people_have_to_type():
    """ComfyUI's own folder is known from ComfyUI, and the service's spelling of it is found by trying
    and checking. Two hand-typed prefix boxes were the first design and one advanced override was the
    second; both asked the user to answer a question the node answers by asking the service to open
    the file. What is left when that fails is a service that cannot reach ComfyUI's disk at all, and
    no box fixes that."""
    ids = [i for _n, _k, i, _kw in ALL]
    for gone in ("comfy_path_prefix", "service_path_prefix", "service_sees_comfy_at"):
        assert gone not in ids, f"{gone} is not a question for the user"
    assert "service sees" not in TEXT, "nor a field named in a message, since it is not on any node"


# --------------------------------------------------------------------------- what is on which node

def test_the_compile_node_holds_no_plumbing_at_all():
    """Its one rule: this is what I want, and this is what it should look at. Nine fields that
    describe a machine were nine of its rows, five of them drawing an unreadable 48-character
    filename against a long label in a 38-character row."""
    for machine in ("server", "reference_model", "frames_model", "text_encoder", "video_vae",
                    "audio_vae", "weight_dtype", "timeout_s"):
        assert machine not in _ids(COMPILE), f"{machine} is a fact about a machine, not a shot"
        assert machine in _ids(SETUP), f"{machine} has to still exist somewhere"


def test_the_compile_node_is_small_enough_to_read_at_rest():
    """Countable rather than a matter of taste: it was 29 inputs, of which a clean queue needed one.
    The satellites are what brought it down to 16, and this is the number that must not creep back.

    It moved to 19 once, by three inputs the owner ruled in by name: the spoken lines and the language
    they are spoken in, which are the only route to a line H3 is checked against, and the storyboard,
    which is the only way to say a picture plans the shots rather than appearing in them. Each ceiling
    below is the count after those three and not a round number with room in it, so the next thing
    that arrives without a ruling behind it fails here.
    """
    rows = [i for k, i, kw in COMPILE if k in NEEDS_TOOLTIP and not _multiline(kw)]
    boxes = [i for k, i, kw in COMPILE if _multiline(kw)]
    sockets = [i for k, i, _kw in COMPILE
               if k not in NEEDS_TOOLTIP and i and i not in TEMPLATE_IDS]
    assert len(rows) <= 9, f"{len(rows)} widget rows on the compile node: {rows}"
    assert boxes == ["intent", "spoken_lines", "picture_notes"], \
        f"the text boxes are the sentence, the lines and the picture notes: {boxes}"
    assert len(sockets) <= 7, f"{len(sockets)} sockets on the compile node: {sockets}"
    declared = [i for _k, i, _kw in COMPILE if i and i not in TEMPLATE_IDS]
    assert len(declared) <= 19, f"{len(declared)} inputs; it was 29 and one of them was needed"


def test_every_satellite_but_setup_is_optional_on_the_compile_node():
    """A satellite that is absent until you need it is not lying around, it is absent, and that is the
    whole argument for moving things off this node."""
    for socket in ("sound", "footage", "first_frame", "last_frame", "pictures"):
        kw = next(kw for _k, i, kw in COMPILE if i == socket)
        assert isinstance(kw.get("optional"), ast.Constant) and kw["optional"].value is True, \
            f"{socket} must be optional"


def test_the_setup_socket_is_required_because_nothing_else_can_choose_the_files():
    """The one satellite that is not optional, and the consequence the picker was worth. Nothing in
    this pack decides which of two H3 checkpoints somebody meant, so a graph with no Setup node has no
    files to load and says so instead of rendering with something it picked itself."""
    kw = next(kw for _k, i, kw in COMPILE if i == "setup")
    assert kw.get("optional") is None, "an optional setup socket is a node that guesses again"
    assert "Required" in _str(kw.get("tooltip")), "and the socket says so where it is read"
    # The same refusal in this pack's own words, for the graph that arrives with the socket empty.
    execute = TEXT[TEXT.index("    def execute(cls, intent"):TEXT.index("helpers", TEXT.index(
        "    def execute(cls, intent"))]
    assert "if not setup:" in execute, "checked before anything is written or loaded"
    for said in ("OpenH3-IR Setup node", "five H3 files", "setup socket"):
        assert said in execute, f"the refusal has to say {said!r}"


def _execute_source() -> str:
    start = TEXT.index("    def execute(cls, intent")
    return TEXT[start:TEXT.index("helpers", start)]


def test_a_board_on_a_frame_anchor_job_is_refused_before_the_call_rather_than_after_it():
    """H3's frame node takes the two frames and no reference picture, so a board on that route would
    be described in the brief, numbered in the report, and never handed to H3: the sound refusal
    beside it exists for the same reason. Refused before the files are written and before the model
    call is spent."""
    execute = _execute_source()
    assert "if anchored and storyboard is not None:" in execute
    for said in ("storyboard cannot ride along", "no reference picture",
                 "Unplug the frame sockets"):
        assert said in execute, f"the refusal has to say {said!r}"


def test_which_picture_is_picture_1_is_decided_in_exactly_one_place():
    """THE control on the board. The order is read twice: once to tell the service what to number, and
    once to fill H3's ref_image sockets. Two derivations of it is how <Picture 3> in the brief becomes
    ref_image_1 in the graph, which describes one picture while handing the model another."""
    assert TEXT.count("images_in_numbering_order(") == 1, \
        "one call site, because a second one is a second answer"
    execute = _execute_source()
    assert "images = images_in_numbering_order(first_frame, last_frame, pics, storyboard)" in execute
    assert "images=images" in execute, "and the same list is what the conditioning is built from"
    # Unparsed rather than read as text, so the rule is about the code and not about a comment that
    # happens to name the socket.
    condition = next(n for n in ast.walk(TREE)
                     if isinstance(n, ast.FunctionDef) and n.name == "_condition")
    code = ast.unparse(condition)
    assert "enumerate(images, 1)" in code
    assert "storyboard" not in code, "the conditioning must not re-derive where the board goes"


def test_a_clips_three_facts_travel_together():
    """A clip is frames plus a soundtrack plus what it is for. An autogrow item holds exactly one
    input, so the pairing has to be structural on its own node or it goes back to being positional
    and silently wrong."""
    assert _ids(FOOTAGE) == ["frames", "its_sound", "job"]
    kinds = {i: k for k, i, _kw in FOOTAGE}
    assert kinds == {"frames": "Image", "its_sound": "Audio", "job": "Combo"}


def test_each_sound_note_sits_with_its_own_socket():
    """One positional block across three differently named roles was silently wrong the moment a
    socket was skipped: fill only the effect and line one described the music."""
    assert _ids(SOUND) == ["music", "music_note", "music_job", "effect", "effect_note", "voice",
                           "voice_note", "voice_words"]
    for clip, note in (("music", "music_note"), ("effect", "effect_note"), ("voice", "voice_note")):
        assert _ids(SOUND).index(note) == _ids(SOUND).index(clip) + 1, \
            f"{note} has to read as belonging to {clip}"


def test_what_the_music_is_for_reads_as_part_of_the_music_block():
    """The third row of the music block and never further down the node: it is the row that decides
    whether the brief claims the recording is the finished soundtrack, and a control that changes what
    a document says about the socket above it has to be read next to that socket. Last within its own
    block, which is where the Footage node puts the same question about a clip."""
    ids = _ids(SOUND)
    assert ids.index("music_job") == ids.index("music_note") + 1
    assert ids.index("music_job") < ids.index("effect"), \
        "it describes the music, so it cannot sit past the next socket"
    job = next(kw for _k, i, kw in SOUND if i == "music_job")
    footage_job = next(kw for _k, i, kw in FOOTAGE if i == "job")
    assert _str(job.get("display_name")) == _str(footage_job.get("display_name")) == \
        "what it is for", "one label for one question, whatever the attachment is"


def test_the_music_job_is_a_choice_in_the_users_words_with_no_role_token_on_it():
    """The whole point of the row: three roles the service knows by name, offered as three things a
    person would say about their own track. A dropdown of `bgm`, `music_style`, `beat_reference` would
    have been the same feature with the service's vocabulary on the canvas."""
    from comfyui.h3ir_client import MUSIC_JOBS

    assert list(MUSIC_JOBS) == ["play this track", "match its style", "cut to its beat"]
    assert list(MUSIC_JOBS.values()) == ["bgm", "music_style", "beat_reference"]
    kw = next(kw for _k, i, kw in SOUND if i == "music_job")
    assert isinstance(kw["options"], ast.Call), "the options come from the shared table"
    assert _str(kw.get("default")) == "" and isinstance(kw.get("default"), ast.Call), \
        "the default is the table's first entry rather than a second copy of the string"


def test_no_role_token_the_service_uses_is_printed_on_the_canvas():
    """`P9-role-token-in-prose` is the service's own rule against this: a snake_case wiring token is
    not language anybody was trained on, on a canvas or in a brief. Only the underscore-bearing role
    values are checked, which is what keeps the ordinary words a tooltip needs -- subject, style,
    storyboard -- out of it."""
    from h3ir.models import Role

    tokens = sorted(r.value for r in Role if "_" in r.value)
    assert tokens, "the guard is worthless if the set is empty"
    shown = []
    for node_id, _k, ident, kw in ALL:
        for field in ("display_name", "placeholder", "tooltip"):
            text = _str(kw.get(field))
            shown.extend(f"{node_id}.{ident}.{field} says {t!r}" for t in tokens if t in text)
    assert not shown, f"service vocabulary on the canvas: {shown}"


def test_the_sound_notes_say_they_are_the_only_description_there_will_be():
    """`analyse.py` makes no model call for audio by design, because nothing in the chain can hear
    and H3's tokenizer emits only `<Audio j>: `. A picture gets looked at; a sound does not."""
    tip = next(_str(kw.get("tooltip")) for _k, i, kw in SOUND if i == "music_note")
    assert "cannot hear" in tip or "can hear" in tip
    assert "only thing the model will ever learn" in tip


def test_the_transcript_field_says_it_is_not_dialogue():
    """It was labelled `what the voice says`, which invites someone to type the lines they want in
    their video. It is a transcript of an attached recording, and typing it into the wrong box used
    to do nothing at all."""
    kw = next(kw for _k, i, kw in SOUND if i == "voice_words")
    tip = _str(kw.get("tooltip"))
    assert "not dialogue for your video" in tip
    # It has to name where the lines DO go, and there are two places now. Naming only the sentence
    # would send someone past the box that is checked to the one that is not.
    assert "spoken lines box on the compile node" in tip and "sentence" in tip
    box = next(kw for _k, i, kw in COMPILE if i == "spoken_lines")
    assert "spoken line" in _str(box.get("placeholder")), \
        "and the box it points at has to be findable by the words that point at it"


# --------------------------------------------------------------------------- order and grouping

def _index(ident: str) -> int:
    return _ids(COMPILE).index(ident)


def test_silence_sits_with_the_rest_of_what_you_are_asking_for():
    """It was buried among the advanced settings. Silence is a creative decision, not a tuning knob:
    H3 writes sound in the same pass as the picture, so asking for none is part of the request."""
    assert _index("silent") < _index("first_frame"), \
        "silent belongs in the group with what happens, how long and how much it may invent"
    for earlier in ("intent", "seconds", "aspect", "creativity"):
        assert _index(earlier) < _index("silent")


def test_the_ask_comes_first_and_then_what_it_looks_at():
    """Nodes 2.0 honours schema order exactly; the legacy canvas draws all sockets above all widgets.
    The order is chosen to read correctly under both: the ask first, then the machine it runs on, then
    the attachments."""
    for attachment in ("first_frame", "last_frame", "pictures", "footage", "sound"):
        assert _index("intent") < _index(attachment)
    for advanced in ("sizing", "seed", "effort"):
        assert _index("silent") < _index(advanced)


def test_the_words_read_with_the_ask_and_not_with_the_attachments():
    """The lines are part of what you are asking for, so they read before the sockets that say what to
    look at. They cannot be declared beside the sentence, because they have to stay optional -- a
    required input is missing from every API-format graph written before it existed, and /prompt
    refuses that outright -- and ComfyUI publishes every required input ahead of every optional one."""
    for attachment in ("first_frame", "last_frame", "pictures", "storyboard", "footage", "sound"):
        assert _index("spoken_lines") < _index(attachment)
    assert _index("setup") < _index("spoken_lines"), "which is where the optional half begins"
    assert _index("spoken_language") == _index("spoken_lines") + 1, \
        "the language describes the box above it and has to be read with it"
    for advanced in ("sizing", "seed", "effort"):
        assert _index("spoken_lines") < _index(advanced)


def test_the_language_list_is_the_one_the_service_publishes():
    """Duplicated for the same reason ASPECTS is: a combo has to be populated before any server has
    been contacted. Duplicated means it can drift, so it is checked against the endpoint that
    publishes it."""
    from h3ir.service import capabilities

    from comfyui.h3ir_client import DIALOGUE_LANGUAGES

    assert set(DIALOGUE_LANGUAGES) == set(capabilities()["dialogue_languages"])
    assert DIALOGUE_LANGUAGES[0] == "English", "the default opens on the service's own default"
    kw = next(kw for _k, i, kw in COMPILE if i == "spoken_language")
    assert isinstance(kw["options"], ast.Call), "the options come from the shared constant"


def test_the_spoken_lines_box_says_which_of_the_two_routes_is_checked():
    """It is not a second sentence, and the difference is not cosmetic: a line in this box is enforced
    verbatim by the compiler and a line quoted in the sentence reaches no rule at all. If the box
    stopped saying that, the two would look interchangeable."""
    kw = next(kw for _k, i, kw in COMPILE if i == "spoken_lines")
    tip = _str(kw.get("tooltip"))
    assert "word for word" in tip and "refused" in tip
    assert "sentence" in tip, "and it has to say what the sentence is still for"
    assert "off screen" in tip, "the two fields it does NOT replace are named rather than implied"


def test_the_board_socket_says_it_does_not_appear_in_the_video():
    """The one claim that makes the socket safe to plug into. Its role is `weak_reference`: the
    planning information is followed and the drawing itself is never reproduced, so a socket that did
    not say so would read as one more picture reference."""
    kw = next(kw for _k, i, kw in COMPILE if i == "storyboard")
    tip = _str(kw.get("tooltip"))
    assert "does not appear in the video" in tip
    assert "order" in tip and "viewpoint" in tip, "and what it DOES decide"


def test_the_notes_box_names_every_picture_socket_that_takes_no_line_from_it():
    """`plan_assets` binds notes to the `picture N` sockets only, so every other IMAGE socket on the
    node is outside that count and has to be named where the rule is stated. Derived from the schema
    rather than typed here, so a fourth picture socket fails this until the box mentions it."""
    tip = _str(next(kw for _k, i, kw in COMPILE if i == "picture_notes").get("tooltip"))
    others = [_str(kw.get("display_name")) for k, i, kw in COMPILE
              if k == "Image" and i and i not in TEMPLATE_IDS]
    assert others, "the guard is worthless if it found no sockets"
    for label in others:
        assert label in tip, f"{label} takes no note line and the box does not say so"


def test_the_declared_order_is_the_order_comfyui_publishes():
    """MEASURED on the live instance: `/object_info` puts every required input ahead of every optional
    one, whatever order they were declared in, and the canvas reads that. So an order that read better
    in the source than on the canvas would be describing a node nobody is looking at. The required
    `setup` socket is what made this visible: declared last, it was published seventh."""
    declared = [i for _k, i, kw in COMPILE if i and i not in TEMPLATE_IDS]
    optional = [bool(isinstance(kw.get("optional"), ast.Constant) and kw["optional"].value)
                for _k, i, kw in COMPILE if i and i not in TEMPLATE_IDS]
    assert optional == sorted(optional), \
        f"required and optional inputs are interleaved in the source: {list(zip(declared, optional))}"
    assert _index("shots") < _index("setup") < _index("first_frame"), \
        "the machine is required, so it reads between the ask and the attachments"


def test_the_rarely_touched_settings_are_marked_as_such():
    """A bonus for Nodes 2.0 users, never a hide: under the legacy renderer `advanced` does nothing
    at all, so the surface is designed to be correct with all of it visible."""
    advanced = {i for _n, _k, i, kw in ALL if kw.get("advanced") is not None}
    for expected in ("seed", "effort", "sizing", "weight_dtype", "timeout_s"):
        assert expected in advanced, f"{expected} should not be in the way of ordinary use"
    for never in ("reference_model", "frames_model", "text_encoder", "video_vae", "audio_vae"):
        assert never not in advanced, "a pick nobody can see is the guess it replaced"
    for never in ("intent", "seconds", "aspect", "creativity", "silent", "shots", "first_frame",
                  "last_frame", "pictures", "footage", "sound", "setup", "spoken_lines",
                  "spoken_language", "storyboard", "music_job"):
        assert never not in advanced


# --------------------------------------------------------------------------- the sockets

def test_the_lists_grow_instead_of_showing_every_empty_socket():
    """Nine fixed picture sockets is too many to look at when the graph is idle, and one was too few
    for what H3 takes. `min=0` yields exactly one socket at rest."""
    grow = [(i, kw) for _n, kind, i, kw in ALL if kind == "Autogrow"]
    assert [i for i, _ in grow] == ["pictures", "footage"]
    for _i, kw in grow:
        template = kw["template"]
        assert isinstance(template, ast.Call) and template.func.attr == "TemplateNames", \
            "TemplatePrefix labels the grown sockets prefix+ordinal, zero-based, and overwrites the "
        assert _kw(template, "min").value == 0


def test_the_grown_sockets_are_named_the_way_the_brief_names_them():
    """`autogrowOrdinalToName` overwrites the template's display_name with `names[ordinal]`, or with
    `prefix + ordinal` zero-based. So the old sockets read `reference_0` while the notes block under
    them said <Picture 1>: raw ids on the canvas and an off-by-one against the text. `TemplateNames`
    is the only way to get one-based readable labels, and one-based is what makes the notes rule
    ("line one describes picture 1") true without explaining anything."""
    from comfyui.h3ir_client import CLIP_NAMES, MAX_CLIPS, MAX_PICTURES, PICTURE_NAMES

    assert PICTURE_NAMES == tuple(f"picture {i}" for i in range(1, MAX_PICTURES + 1))
    assert CLIP_NAMES == tuple(f"clip {i}" for i in range(1, MAX_CLIPS + 1))
    assert PICTURE_NAMES[0] == "picture 1", "one-based, the same number the brief prints"
    assert MAX_PICTURES == 9 and MAX_CLIPS == 3, "H3's own limits, not invented ones"


def test_the_frame_sockets_use_the_stock_h3_nodes_own_names():
    """`first_frame` and `last_frame` are what `MiniMaxH3ImageToVideo` calls them, so they are
    already the vocabulary in the user's head. `opening_frame` was this pack's invention."""
    kinds = {i: k for k, i, _kw in COMPILE}
    assert kinds["first_frame"] == "Image" and kinds["last_frame"] == "Image"
    assert "opening_frame" not in kinds and "closing_frame" not in kinds


def test_footage_arrives_as_a_bundle_rather_than_a_video_object():
    """`VIDEO` was unreachable for the loader people actually use: `VHS_LoadVideo` outputs
    IMAGE + AUDIO, and ComfyUI's own H3 node takes frames and a soundtrack separately. Footage is
    frames plus a soundtrack, not one object."""
    kinds = {i: k for _n, k, i, _kw in ALL}
    assert "Video" not in kinds.values(), "no VIDEO socket can be fed by the normal graph"
    assert "video_to_edit" not in kinds and "video_to_continue" not in kinds
    template = next(kw["template"] for _k, i, kw in COMPILE if i == "footage")
    inner = next(a for a in ast.walk(template) if _is_input_call(a))
    assert _kind(inner) == "Footage", "the grown clip socket takes the bundle, not raw frames"


def test_a_clips_job_is_a_choice_the_user_makes_per_clip():
    """H3 takes three clips and the old node offered one of each of two roles, with the role fixed by
    which socket you found. Three different jobs in the brief, so the wrong one renders something
    plausible and wrong."""
    from comfyui.h3ir_client import FOOTAGE_JOBS

    assert list(FOOTAGE_JOBS) == ["copy what is in it", "edit it", "carry on from it"]
    assert list(FOOTAGE_JOBS.values()) == ["subject", "edit_source", "continuation_source"]
    kw = next(kw for _k, i, kw in FOOTAGE if i == "job")
    assert _str(kw.get("default")) == "copy what is in it", \
        "the default must not claim the render is an edit of the source"


def test_the_model_combos_are_a_picker_and_nothing_else():
    """The five files are a question only the user can answer: a filename says what a file is called,
    not what somebody intended it to be. So each combo lists what this install has and opens on one of
    them, exactly like every loader in ComfyUI, with no sentinel default meaning "work it out" and no
    hidden preference behind it."""
    for model in ("reference_model", "frames_model", "text_encoder", "video_vae", "audio_vae"):
        kw = next(kw for _k, i, kw in SETUP if i == model)
        assert isinstance(kw["options"], ast.Call) and kw["options"].func.id == "_model_options", \
            f"{model} must list what this install actually has"
        assert "default" not in kw, \
            f"{model} carries no default, so the combo opens on a real file the user can read"
        assert "(found" not in _str(kw.get("tooltip")), "no tooltip promises a search either"


def test_the_pick_is_the_file_that_loads_and_no_table_second_guesses_it():
    """THE control on the picker. Auto-resolution matched H3's filenames against a table of expected
    words, with a preference for int8 builds nobody asked for, and the render then used a file the
    canvas never showed. The node reads the five names off the bundle and loads those."""
    execute = TEXT[TEXT.index("    def execute(cls, intent"):TEXT.index("helpers", TEXT.index(
        "    def execute(cls, intent"))]
    for guess in ("PATTERNS", "resolve_model", "int8", "found automatically"):
        assert guess not in TEXT, f"{guess} is how the node used to answer a question it cannot"
    for direct in ('"frames_model" if frames_job else "reference_model"', 'machine["text_encoder"]',
                   'machine["video_vae"]', 'machine["audio_vae"]'):
        assert direct in execute, f"{direct} has to be read straight off the Setup bundle"


# --------------------------------------------------------------------------- identity and outputs

def test_the_node_ids_are_the_ones_saved_workflows_reference():
    """A rename silently breaks every workflow anyone saved. Pinned deliberately."""
    assert sorted(SCHEMAS) == ["OpenH3IRCompile", "OpenH3IRFootage", "OpenH3IRSetup",
                               "OpenH3IRShowText", "OpenH3IRSound"]


def test_the_compile_node_is_findable_by_the_words_a_user_types():
    """`OpenH3-IR` alone tells a stranger nothing, and the siblings they already know are called
    "MiniMax H3 Image to Video" and "MiniMax H3 Reference to Video"."""
    aliases = _kw(SCHEMAS["OpenH3IRCompile"], "search_aliases")
    words = {_str(e) for e in aliases.elts}
    assert {"minimax", "h3", "ref2va", "fl2va", "t2va"} <= words
    assert _str(_kw(SCHEMAS["OpenH3IRCompile"], "display_name")) == "H3 from a Sentence"


def test_every_node_in_the_pack_is_in_one_category():
    for node_id, call in SCHEMAS.items():
        assert _str(_kw(call, "category")) == "OpenH3-IR", node_id


def test_the_graph_needs_no_loader_boxes():
    """Every model file the render touches comes out of the compile node, decode included."""
    kinds = [k for k, _label in _outputs_of("OpenH3IRCompile")]
    assert kinds == ["Model", "Conditioning", "Latent", "Vae", "Vae", "String", "String"]
    labels = [label for _k, label in _outputs_of("OpenH3IRCompile")]
    assert labels == ["model", "positive", "latent", "vae", "audio_vae", "prompt", "report"]


def test_each_satellite_hands_over_exactly_one_bundle():
    for node_id, label in (("OpenH3IRSetup", "setup"), ("OpenH3IRFootage", "clip"),
                           ("OpenH3IRSound", "sound")):
        outs = _outputs_of(node_id)
        assert len(outs) == 1 and outs[0][1] == label, f"{node_id} outputs {outs}"
