"""What the node looks like on a canvas, checked without a canvas.

`comfyui/nodes.py` imports ComfyUI's node API at module scope, so it cannot be imported here. The
alternative to giving up on these checks was to write a fake `comfy_api` and assert against that,
which would have tested the fake. So this reads the source instead: it parses the schema declaration
and asserts on what it actually says. Crude, and it cannot prove ComfyUI draws it correctly, but it
does prove the declaration says what it is supposed to say, and it runs anywhere.

The live half of this pair is running ComfyUI and reading `/object_info`, which is how the real drawn
schema was verified. That needs a GPU box with the model files, so it is not something CI can do.

Every rule below exists because the first version of the node got it wrong.
"""
from __future__ import annotations

import ast
import pathlib

SRC = pathlib.Path(__file__).resolve().parent.parent / "comfyui" / "nodes.py"
TREE = ast.parse(SRC.read_text(encoding="utf-8"))

# Input kinds whose label alone cannot explain them, so they must carry a tooltip too.
NEEDS_TOOLTIP = {"String", "Float", "Int", "Combo", "Boolean"}


def _inputs() -> list[tuple[str, str, dict[str, ast.AST]]]:
    """Every io.<Kind>.Input(...) in declaration order, as (kind, id, keywords)."""
    found = []
    for node in ast.walk(TREE):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr != "Input":
            continue
        owner = node.func.value
        if not (isinstance(owner, ast.Attribute) and isinstance(owner.value, ast.Name)
                and owner.value.id == "io"):
            continue
        kind = owner.attr
        ident = node.args[0].value if node.args and isinstance(node.args[0], ast.Constant) else ""
        kw = {k.arg: k.value for k in node.keywords if k.arg}
        found.append((kind, ident, kw))
    return found


def _str(node: ast.AST | None) -> str:
    """Join a literal or an implicitly concatenated literal back into one string."""
    if node is None:
        return ""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(v.value for v in node.values if isinstance(v, ast.Constant))
    return ""


def _outputs() -> list[tuple[str, str]]:
    out = []
    for node in ast.walk(TREE):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "Output"):
            owner = node.func.value
            if isinstance(owner, ast.Attribute) and isinstance(owner.value, ast.Name) \
                    and owner.value.id == "io":
                kw = {k.arg: k.value for k in node.keywords if k.arg}
                out.append((owner.attr, _str(kw.get("display_name"))))
    return out


def _node_ids() -> list[str]:
    ids = []
    for node in ast.walk(TREE):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr == "Schema":
            for k in node.keywords:
                if k.arg == "node_id":
                    ids.append(_str(k.value))
    return ids


# --------------------------------------------------------------------------- labels a person reads

def test_every_input_has_a_human_label():
    """The widget id is what shows on the canvas when no display name is given, and an id like
    `sound_notes` on screen is the node talking to itself. Measured: it shipped like that."""
    missing = [f"{kind}:{ident}" for kind, ident, kw in _inputs()
               if ident and not _str(kw.get("display_name"))]
    assert not missing, f"inputs with no human label: {missing}"


def test_no_label_is_an_identifier():
    """An underscore in a label means the identifier leaked onto the canvas, which is what happened:
    `sound_notes` and `spoken_words` were showing as-is.

    An earlier version of this test also failed a label that matched its id word for word, which
    wrongly condemned "voice to match" and "text encoder". Those read fine. The defect was never
    labels that agree with their ids, it was labels that are code.
    """
    offenders = [f"{ident} -> {_str(kw.get('display_name'))!r}" for _k, ident, kw in _inputs()
                 if "_" in _str(kw.get("display_name"))]
    assert not offenders, f"identifiers used as labels: {offenders}"


def test_a_placeholder_shows_an_example_rather_than_the_field_name():
    """A placeholder is the one piece of guidance someone reads before typing, so it shows what an
    answer looks like. Repeating the label there teaches nothing."""
    offenders = []
    for _kind, ident, kw in _inputs():
        ph = _str(kw.get("placeholder"))
        if not ph:
            continue
        label = _str(kw.get("display_name"))
        if ph.strip().lower() in (ident.lower(), label.strip().lower()):
            offenders.append(f"{ident}: {ph!r}")
    assert not offenders, f"placeholders that just repeat the name: {offenders}"


def test_every_text_number_and_choice_input_explains_itself():
    missing = [ident for kind, ident, kw in _inputs()
               if kind in NEEDS_TOOLTIP and ident and not _str(kw.get("tooltip"))]
    # A few labels are complete sentences on their own; everything else has to explain itself.
    allowed = {"video_vae", "server"}
    missing = [m for m in missing if m not in allowed]
    assert not missing, f"inputs with no explanation: {missing}"


# --------------------------------------------------------------------------- one source of truth

def test_there_is_exactly_one_place_to_set_the_length():
    """Two dials that both claim to set duration is how eight seconds of a ten second script gets
    rendered. The graph used to have its own seconds and its own frame arithmetic as well."""
    ids = [ident for _k, ident, _kw in _inputs()]
    duration_ish = [i for i in ids
                    if any(w in i for w in ("second", "length", "duration", "frames"))
                    and not i.endswith("_model")]  # frames_model picks weights, not a duration
    assert duration_ish == ["seconds"], f"more than one duration control: {duration_ish}"


def test_the_canvas_size_is_not_a_second_source_of_truth():
    ids = [ident for _k, ident, _kw in _inputs()]
    assert "width" not in ids and "height" not in ids, \
        "the canvas comes from the frame shape; a resolution box would be able to disagree with it"


def test_the_path_prefixes_are_not_something_people_have_to_type():
    """ComfyUI's own folder is known from ComfyUI, and the service's spelling of it is found by
    trying and checking. Two hand-typed prefix boxes were the earlier design."""
    ids = [ident for _k, ident, _kw in _inputs()]
    assert "comfy_path_prefix" not in ids, "ComfyUI's own location is not a question for the user"
    assert "service_path_prefix" not in ids
    override = [(i, kw) for _k, i, kw in _inputs() if i == "service_sees_comfy_at"]
    assert override, "an override has to exist for setups that cannot be worked out"
    assert override[0][1].get("advanced") is not None, "and it belongs out of the way"


# --------------------------------------------------------------------------- order and grouping

def _index(ident: str) -> int:
    ids = [i for _k, i, _kw in _inputs()]
    return ids.index(ident)


def test_silence_sits_with_the_rest_of_what_you_are_asking_for():
    """It was buried among the advanced settings. Silence is a creative decision, not a tuning knob:
    H3 writes sound in the same pass as the picture, so asking for none is part of the request."""
    assert _index("silent") < _index("opening_frame"), \
        "silent belongs in the group with what happens, how long and how much it may invent"
    for earlier in ("intent", "seconds", "aspect", "creativity"):
        assert _index(earlier) < _index("silent")


def test_the_request_comes_before_the_plumbing():
    """What you are asking for reads first; the service address and the model files sit below it."""
    for plumbing in ("server", "reference_model", "text_encoder", "video_vae", "audio_vae"):
        assert _index("intent") < _index(plumbing)
        assert _index("creativity") < _index(plumbing)


def test_the_rarely_touched_settings_are_marked_as_such():
    advanced = {i for _k, i, kw in _inputs() if kw.get("advanced") is not None}
    for expected in ("seed", "effort", "weight_dtype", "timeout_s", "service_sees_comfy_at",
                     "sizing"):
        assert expected in advanced, f"{expected} should not be in the way of ordinary use"
    for never in ("intent", "seconds", "aspect", "creativity", "silent"):
        assert never not in advanced


# --------------------------------------------------------------------------- the sockets

def test_the_reference_list_grows_instead_of_showing_nine_empty_sockets():
    """Four fixed sockets was both too few, since H3 takes nine, and too many to look at when the
    graph is idle."""
    grow = [(ident, kw) for kind, ident, kw in _inputs() if kind == "Autogrow"]
    assert [i for i, _ in grow] == ["references"], "references is the one list that grows"
    src = SRC.read_text(encoding="utf-8")
    assert "prefix=\"reference_\"" in src
    assert "max=MAX_REFERENCES" in src
    assert "MAX_REFERENCES = 9" in src, "H3's own limit, not an invented one"


def test_the_frame_sockets_are_pictures_and_the_media_sockets_are_their_own_types():
    kinds = {ident: kind for kind, ident, _kw in _inputs()}
    assert kinds["opening_frame"] == "Image" and kinds["closing_frame"] == "Image"
    assert kinds["video_to_edit"] == "Video" and kinds["video_to_continue"] == "Video"
    for s in ("music", "sound_effect", "voice_to_match"):
        assert kinds[s] == "Audio"


def test_the_socket_names_say_the_job_rather_than_the_mechanism():
    """The whole point of sockets over a role dropdown: the name tells you what plugging in means."""
    ids = [i for _k, i, _kw in _inputs()]
    for readable in ("opening_frame", "closing_frame", "video_to_edit", "video_to_continue",
                     "music", "sound_effect", "voice_to_match"):
        assert readable in ids
    for mechanism in ("ref_image_1", "first_frame", "last_frame", "role_1", "asset_1"):
        assert mechanism not in ids, f"{mechanism} names the API, not the job"


# --------------------------------------------------------------------------- identity and outputs

def test_the_node_ids_are_the_ones_saved_workflows_reference():
    """A rename silently breaks every workflow anyone saved. Pinned deliberately."""
    assert sorted(_node_ids()) == ["OpenH3IRCompile", "OpenH3IRShowText"]


def test_the_graph_needs_no_loader_boxes():
    """Every model file the render touches comes out of this node, decode included."""
    kinds = [k for k, _label in _outputs()]
    assert kinds == ["Model", "Conditioning", "Latent", "Vae", "Vae", "String", "String"]
    labels = [label for _k, label in _outputs()]
    assert labels == ["model", "positive", "latent", "vae", "audio_vae", "prompt", "report"]
