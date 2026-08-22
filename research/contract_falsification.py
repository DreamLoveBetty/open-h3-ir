#!/usr/bin/env python
"""Break each thing the contract guards, one at a time, and confirm the guard goes red.

A test that has never been seen failing is a test nobody has verified, and this suite has already
shipped one that was green for its whole life while the field it guarded was being dropped in
transit. So every check added for the compiler/pack contract has a defect written for it here: the
defect is planted, the test that claims to catch it is run, and the file is put back.

    .venv/bin/python research/contract_falsification.py

It edits the working tree and restores it, so run it on a clean tree and check `git status` after.

**Three outcomes, and the third one is the whole point of this file's second draft.**

    RED      the defect was planted, proved live, and the guard failed. What you want.
    GREEN    the defect was planted, proved live, and the guard passed anyway. A guard that
             does not guard.
    BROKEN   the case did not run. The anchor moved, the write did not land, the interpreter
             would not have seen it, or the test it names does not exist.

**GREEN and BROKEN used to print the same thing, and that is how a case hid.** An earlier draft
reported "the guard did not fire" whenever pytest exited non-zero -- so a case whose defect never
reached the file, and a guard that genuinely failed to catch a live defect, were indistinguishable.
Anything that plants defects has to prove it planted them before it is allowed an opinion about the
guard.

Every way this file was found to be able to lie, and what closes it:

  * **A missing anchor under `-O`.** The old draft checked its anchor with `assert`, and `python -O`
    strips asserts. A moved anchor then became a silent no-op: the file was never edited, the test
    passed on unmodified source, and the case printed GREEN. Measured, not supposed. Nothing here
    uses `assert` any more; every check raises `CaseBroken` explicitly.
  * **A write that does not land.** The bytes on disk are read back and compared to what was meant.
  * **Source the interpreter would not load.** A shadowing install, or a stale `.pyc`, and the test
    runs against code nobody edited. The module is imported in a subprocess and asked which file it
    came from and what is in it.
  * **A test id that does not exist.** pytest exits 4 for an unknown node id and 5 when nothing is
    collected, and the old draft counted both as RED, so a renamed test looked like a guard firing.
    Exit codes are now read for what they mean, and every id is collected before anything is
    planted.
  * **A case that proves nothing because its test was already failing.** Every named test is run on
    the clean tree first and must pass, or the RED that follows means nothing.

**The `__pycache__` wipe is load-bearing.** Python validates a cached `.pyc` on (mtime, size) and
mtime has one-second resolution. Several defects here are exactly as long as what they replace --
`9` for `6`, `ASSETS` for `BRIEFS`, `snapshot()` for `contract()` -- and land in the same second as
the restore before them, so the interpreter serves the OLD bytecode. Five cases lied that way before
the wipe existed. Note what the wipe does NOT cover on its own: a same-length edit is invisible to
the size check, which is why the liveness probe reads the source the interpreter actually resolved
rather than trusting the wipe.
"""
from __future__ import annotations

import hashlib
import pathlib
import shutil
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
PY = str(REPO / ".venv" / "bin" / "python")

# What pytest's exit codes mean. Only 1 is a test that ran and failed; everything else above 0 is
# this harness failing to ask the question, which is a different fact and must not read as RED.
TESTS_PASSED, TESTS_FAILED = 0, 1
CANNOT_ASK = {2: "pytest was interrupted", 3: "an internal pytest error",
              4: "pytest usage error, which is what an unknown test id looks like",
              5: "no tests were collected"}


TOUCHES = ["pyproject.toml", "h3ir/compile.py", "h3ir/director.py", "h3ir/service.py",
           "h3ir/models.py", "h3ir/contract.py", "h3ir/cli.py", "comfyui/tray.py",
           "comfyui/h3ir_client.py", "comfyui/nodes.py", "comfyui/contract.py",
           "comfyui/web/director.js", "comfyui/web/contract.data.js", "tests/test_contract.py"]


class CaseBroken(RuntimeError):
    """This case did not run. Never reported as a guard that failed to fire."""


_IMPORTABLE: set[str] | None = None


def _importable() -> set[str]:
    """Which of the modules these cases touch can be imported here AT ALL, measured on the clean
    tree once.

    Two files in the pack cannot: `comfyui/nodes.py` and the package `__init__` reach for ComfyUI's
    node API at module scope. Their tests read them as source instead, so an import probe on them
    would report BROKEN for a reason that has nothing to do with the defect -- which is the same
    class of lie this whole draft exists to remove, arriving from the other side.
    """
    global _IMPORTABLE
    if _IMPORTABLE is None:
        names = sorted({f[:-3].replace("/", ".") for f in TOUCHES
                        if f.endswith(".py") and not f.startswith("tests/")})
        probe = subprocess.run(
            [PY, "-B", "-c", "import importlib\n"
             f"for n in {names!r}:\n"
             "    try:\n        importlib.import_module(n)\n        print(n)\n"
             "    except Exception:\n        pass"],
            cwd=REPO, capture_output=True, text=True)
        _IMPORTABLE = set(probe.stdout.split())
    return _IMPORTABLE


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


class Defect:
    """One planted defect, and everything needed to prove it was really planted.

    `plant` refuses rather than returns on every way the edit can fail to happen, because a defect
    that is not in the file is a case that did not run and the two must never print the same thing.
    """

    def __init__(self, rel: str, old: str, new: str):
        self.rel, self.old, self.new = rel, old, new

    @property
    def path(self) -> pathlib.Path:
        return REPO / self.rel

    def plant(self) -> None:
        before = self.path.read_text(encoding="utf-8")
        found = before.count(self.old)
        if found != 1:
            raise CaseBroken(f"the anchor appears {found} times in {self.rel}, not once. It has "
                             "moved or been edited; fix the case, it is testing nothing.")
        wanted = before.replace(self.old, self.new)
        if wanted == before:
            raise CaseBroken(f"replacing the anchor in {self.rel} changes nothing")
        self.path.write_text(wanted, encoding="utf-8")
        on_disk = self.path.read_text(encoding="utf-8")
        if on_disk != wanted:
            raise CaseBroken(f"{self.rel} on disk is not what was written to it "
                             f"({_digest(on_disk)} against {_digest(wanted)})")

    @property
    def module(self) -> str | None:
        """The importable name of this file, or None when a test cannot be consuming it that way.

        `comfyui/nodes.py` imports ComfyUI's node API at module scope and cannot be imported
        outside a canvas at all, which is why `tests/test_comfyui_schema.py` reads it as source.
        Whether that is true is MEASURED at startup rather than listed here, so a file that becomes
        importable later stops being an exception on its own.
        """
        if self.path.suffix != ".py" or self.rel.startswith("tests/"):
            return None
        name = self.rel[:-3].replace("/", ".")
        return name if name in _importable() else None

    def prove_live(self) -> str:
        """Confirm the tests would really see the edit, proved the way the tests consume the file.

        A module a test imports can be shadowed by an install or served from a stale cache, and
        neither shows up in a read-back, so it is imported in a subprocess and asked which file it
        came from and what is in it. A file a test reads as text -- every `.js`, the JSON, and the
        Python that cannot be imported here -- is already fully proved by the read-back in `plant`,
        and importing it would fail for reasons that have nothing to do with the defect.
        """
        module = self.module
        if module is None:
            return f"{self.rel} read from disk"
        wanted = _digest(self.path.read_text(encoding="utf-8"))
        probe = subprocess.run(
            [PY, "-B", "-c",
             "import importlib,hashlib;"
             f"m=importlib.import_module({module!r});"
             "src=open(m.__file__,encoding='utf-8').read();"
             "print(m.__file__);"
             "print(hashlib.sha256(src.encode()).hexdigest()[:16])"],
            cwd=REPO, capture_output=True, text=True)
        if probe.returncode != 0:
            raise CaseBroken(f"{module} imports on the clean tree and not with this defect in "
                             f"place, so the test below ran against nothing: "
                             f"{probe.stderr.strip()[-300:]}")
        loaded, got = (probe.stdout.strip().splitlines() + ["", ""])[:2]
        if pathlib.Path(loaded).resolve() != self.path.resolve():
            raise CaseBroken(f"{module} loads from {loaded}, not from the file this case edited. "
                             "Something on the path is shadowing the checkout.")
        if got != wanted:
            raise CaseBroken(f"{module} reads as {got} and the file on disk is {wanted}")
        return f"{module} loads {wanted} from the edited file"


class Rewrite(Defect):
    """A defect that cannot be expressed as one substitution: a block that moves rather than
    changes. Same obligations, its own edit."""

    def __init__(self, rel: str, edit):
        super().__init__(rel, "", "")
        self.edit = edit

    def plant(self) -> None:
        before = self.path.read_text(encoding="utf-8")
        wanted = self.edit(before)
        if wanted == before:
            raise CaseBroken(f"the rewrite of {self.rel} changed nothing")
        self.path.write_text(wanted, encoding="utf-8")
        if self.path.read_text(encoding="utf-8") != wanted:
            raise CaseBroken(f"{self.rel} on disk is not what was written to it")


def patch(rel: str, old: str, new: str) -> Defect:
    return Defect(rel, old, new)


def _move_the_check_later(source: str) -> str:
    """Somebody moves the contract check below the compile, so the media travels first.

    A real move rather than a deletion: the claim under test is the ORDER, and deleting the call
    would prove only that it exists.
    """
    start = source.index("        # Are the two halves talking about the same thing?")
    end = source.index("        body, handoff = compile_with_media(")
    block = source[start:end]
    if "fetch_contract" not in block:
        raise CaseBroken("the check block was not found; this case is testing nothing")
    after = source.index("\n", source.index("            brief=brief)", end)) + 1
    return source[:start] + source[end:after] + block + source[after:]


move_the_check_later = Rewrite("comfyui/nodes.py", _move_the_check_later)


CASES = [
    ("a director's prose is edited and the copy is not regenerated",
     patch("h3ir/director.py", "The camera is mounted and travelling",
           "The camera is bolted down and travelling"),
     "tests/test_contract_drift.py::test_the_generated_copies_are_what_this_compiler_publishes"),

    ("a director's prose is edited and the contract version is not bumped",
     patch("h3ir/director.py", "The camera is mounted and travelling",
           "The camera is bolted down and travelling"),
     "tests/test_contract.py::test_the_version_moves_when_any_part_of_the_contract_moves"),

    ("the generated browser copy is hand-edited",
     patch("comfyui/web/contract.data.js", 'name: "James Cameron"', 'name: "J. Cameron"'),
     "tests/test_contract_drift.py::test_the_generated_copies_are_what_this_compiler_publishes"),

    ("an export the panel imports is renamed in the generated copy",
     patch("comfyui/web/contract.data.js", "export const CAMERA_MOVES",
           "export const CAMERA_MOVE_NAMES"),
     "tests/test_director_panel.py::test_the_generated_copy_exports_everything_the_panel_imports"),

    ("the panel declares its own directions again instead of importing them",
     patch("comfyui/web/director.js", "const VERSION = \"director v3\";",
           "const DIRECTORS = [];\nconst VERSION = \"director v3\";"),
     "tests/test_director_panel.py::test_the_panel_reads_the_generated_copy_rather_than_declaring_its_own"),

    ("who a picture replaces stops being copied into the request (the live bug)",
     patch("comfyui/h3ir_client.py",
           '    if str(extra.get("replaces") or "").strip():\n'
           '        a["replaces"] = str(extra["replaces"]).strip()\n',
           ""),
     "tests/test_contract_drift.py::test_who_a_picture_replaces_reaches_the_request "
     "tests/test_swap_roles.py::test_the_words_the_node_collects_reach_the_field_the_compiler_reads"),

    ("an empty replaces field starts travelling as an empty string",
     patch("comfyui/h3ir_client.py", 'if str(extra.get("replaces") or "").strip():',
           'if "replaces" in extra:'),
     "tests/test_contract_drift.py::test_a_picture_that_replaces_nobody_says_nothing_about_it"),

    ("a field is added to the wire model and not to the contract",
     patch("h3ir/service.py", "    provenance: dict[str, Any] | None = None\n",
           "    provenance: dict[str, Any] | None = None\n    grading: str | None = None\n"),
     "tests/test_contract.py::test_the_contract_names_exactly_the_fields_the_wire_models_take"),

    ("the service goes back to dropping a key it does not know",
     patch("h3ir/service.py", '    model_config = ConfigDict(extra="forbid")\n\n    path: str | None',
           "    path: str | None"),
     "tests/test_contract.py::test_a_field_the_model_does_not_take_is_refused_by_name_rather_than_dropped"),

    ("a role is added to the enum and put on no kind",
     patch("h3ir/models.py", '    SFX = "sfx"', '    SFX = "sfx"\n    HOLOGRAM = "hologram"'),
     "tests/test_contract.py::test_every_role_belongs_to_at_least_one_kind"),

    ("a refusal is added to the service and not published",
     patch("h3ir/service.py", '"code": "change-empty"', '"code": "change-was-empty"'),
     "tests/test_contract.py::test_the_contract_lists_every_refusal_the_service_can_raise"),

    ("a published refusal claims the wrong route",
     patch("h3ir/contract.py", '"asset-too-large": {"status": 413, "on": [ASSETS]},',
           '"asset-too-large": {"status": 413, "on": [BRIEFS]},'),
     "tests/test_contract.py::test_the_contract_lists_every_refusal_the_service_can_raise"),

    ("the tray offers a job the compiler does not take",
     patch("comfyui/tray.py", '"storyboard": "storyboard",',
           '"storyboard": "storyboard",\n    "a hologram": "hologram",'),
     "tests/test_contract_drift.py::test_every_job_the_tray_offers_is_a_job_the_compiler_takes"),

    ("the pack offers a shot pin the compiler clamps away",
     patch("comfyui/h3ir_client.py", "MAX_SHOTS = 10   # the service's PINNED_SHOTS_MAX",
           "MAX_SHOTS = 14   # the service's PINNED_SHOTS_MAX"),
     "tests/test_contract_drift.py::test_the_shot_ceiling_the_pack_offers_is_the_one_the_contract_publishes"),

    ("the pack offers a creativity setting the compiler stopped taking",
     patch("comfyui/h3ir_client.py",
           'CREATIVITY = ("restrained", "balanced", "bold", "extreme")',
           'CREATIVITY = ("restrained", "balanced", "bold", "extreme", "unhinged")'),
     "tests/test_contract_drift.py::test_the_option_lists_the_pack_draws_are_the_ones_the_contract_publishes"),

    ("the tray refuses at a capacity that is not H3's",
     patch("comfyui/tray.py", 'CAPACITY = {"picture": 9, "video": 3, "sound": 3}',
           'CAPACITY = {"picture": 6, "video": 3, "sound": 3}'),
     "tests/test_contract_drift.py::test_the_capacity_the_tray_refuses_at_is_the_compilers_own"),

    ("a missing field becomes a note instead of stopping the graph",
     patch("comfyui/contract.py",
           'out.append(Difference(stop=True, message=(\n'
           '                f"this graph says something {where} that the OpenH3-IR service does not "',
           'out.append(Difference(stop=False, message=(\n'
           '                f"this graph says something {where} that the OpenH3-IR service does not "'),
     "tests/test_contract_drift.py::test_a_field_the_service_cannot_take_stops_the_graph_and_names_it "
     "tests/test_contract_drift.py::test_a_brief_setting_the_service_cannot_take_stops_the_graph_too"),

    ("a missing role becomes a note instead of stopping the graph",
     patch("comfyui/contract.py",
           "        out.append(Difference(stop=True, message=(\n"
           "            f'a slot in the tray is set to",
           "        out.append(Difference(stop=False, message=(\n"
           "            f'a slot in the tray is set to"),
     "tests/test_contract_drift.py::test_a_slot_set_to_a_job_the_service_has_no_name_for_stops_the_graph"),

    ("a drifted director copy starts stopping renders it has no business stopping",
     patch("comfyui/contract.py",
           '        out.append(Difference(\n'
           '            "the seven directions this node pack ships are not the ones the OpenH3-IR service "',
           '        out.append(Difference(stop=True, message=\n'
           '            "the seven directions this node pack ships are not the ones the OpenH3-IR service "'),
     "tests/test_contract_drift.py::test_a_drifted_direction_is_reported_and_never_stops_a_render"),

    ("an older service with nothing new in the graph is stopped anyway",
     patch("comfyui/contract.py", "        for field in sending:\n            if field in known:\n                continue",
           "        for field in list(sending) + ['replaces']:\n            if field in known:\n                continue"),
     "tests/test_contract_drift.py::test_the_same_older_service_is_fine_for_a_graph_that_does_not_use_the_new_thing"),

    ("a service too old to publish a contract becomes a failure",
     patch("comfyui/contract.py", '    if live is None:\n        return [Difference(',
           '    if live is None:\n        return [Difference(stop=True, message='),
     "tests/test_contract_drift.py::test_a_service_too_old_to_publish_a_contract_is_a_note_and_never_a_failure"),

    ("a job only the service can do stops being reported",
     patch("comfyui/contract.py", "    out += _what_this_pack_cannot_reach(live)\n", ""),
     "tests/test_contract_drift.py::test_a_job_the_service_takes_and_the_pack_cannot_offer_is_reported_and_never_stops"),

    ("a moved limit stops being reported",
     patch("comfyui/contract.py", "    out += _limits_that_moved(live)\n", ""),
     "tests/test_contract_drift.py::test_a_limit_that_moved_is_reported_in_words_a_user_reads"),

    ("a difference stops naming which service it is about",
     patch("comfyui/contract.py", 'f"this graph says something {where} that the OpenH3-IR service does not "',
           'f"this graph says something {where} that the service does not "'),
     "tests/test_contract_drift.py::test_every_difference_names_the_service_it_is_about"),

    ("the contract is asked for only after the media has been sent", move_the_check_later,
     "tests/test_contract_drift.py::test_the_check_happens_before_the_media_travels"),

    ("a difference that stops the graph stops raising",
     patch("comfyui/nodes.py", "        if stops:\n            raise ServiceError",
           "        if False and stops:\n            raise ServiceError"),
     "tests/test_contract_drift.py::test_the_node_refuses_on_a_stop_and_reports_the_rest"),

    ("the notes never reach the report",
     patch("comfyui/nodes.py",
           '        for gap in gaps:\n            text += "\\n" + line("note", gap.message)\n', ""),
     "tests/test_contract_drift.py::test_the_node_refuses_on_a_stop_and_reports_the_rest"),

    ("an unreachable service raises instead of answering None",
     patch("comfyui/h3ir_client.py", "    try:\n        status, body = _request(server, \"/v1/contract\", timeout=timeout)\n    except ServiceError:\n        return None",
           "    status, body = _request(server, \"/v1/contract\", timeout=timeout)"),
     "tests/test_contract_drift.py::test_asking_an_unreachable_service_is_never_an_exception "
     "tests/test_contract_drift.py::test_a_service_error_while_asking_is_swallowed_rather_than_raised"),

    ("anything with a 200 is treated as a contract",
     patch("comfyui/h3ir_client.py",
           '    if status != 200 or not isinstance(body, dict) or "contract_version" not in body:\n        return None',
           "    if status != 200:\n        return None"),
     "tests/test_contract_drift.py::test_a_service_that_answers_with_something_else_is_treated_as_publishing_nothing"),

    ("the pack starts importing the compiler",
     patch("comfyui/tray.py", "import json\nimport re",
           "import json\nimport re\n\nimport h3ir.contract"),
     "tests/test_contract_drift.py::test_the_pack_never_imports_the_compiler_while_it_is_being_imported"),

    ("the em dash rule loses its reach over the panel",
     patch("comfyui/web/director.js", 'const SAVED_DIR = "openh3ir/directors";',
           'const SAVED_DIR = "openh3ir/directors";\nconst OOPS = "a note — with a machine tell";'),
     "tests/test_director_panel.py::test_no_em_dash_reaches_anything_the_owner_reads"),

    ("the generator mangles a profile on the way into JavaScript",
     patch("h3ir/contract.py", 'parts.append(f"    notes: {json.dumps(d[\'notes\'], ensure_ascii=False)},")',
           'parts.append(f"    notes: {json.dumps(d[\'notes\'][:200], ensure_ascii=False)},")'),
     "tests/test_contract.py::test_the_generated_module_carries_every_profile_word_for_word"),

    ("the command stops printing what the module builds",
     patch("h3ir/cli.py", "print(C.as_js() if getattr(args, \"js\", False) else C.as_json(), end=\"\")",
           "print(C.as_js() if getattr(args, \"js\", False) else C.as_json())"),
     "tests/test_contract.py::test_the_command_prints_what_the_module_builds"),

    ("the written contract starts carrying the installation's own version",
     patch("h3ir/contract.py", "    return json.dumps(snapshot(), indent=2, ensure_ascii=False, sort_keys=False)",
           "    return json.dumps(contract(), indent=2, ensure_ascii=False, sort_keys=False)"),
     "tests/test_contract.py::test_the_endpoint_says_which_build_is_answering_and_the_file_does_not"),

    ("a refusal is added to the compiler and not published",
     patch("h3ir/compile.py", 'raise BriefRefused(\n            "intent-empty"',
           'raise BriefRefused(\n            "intent-was-empty"'),
     "tests/test_contract.py::test_the_contract_lists_every_refusal_the_service_can_raise"),

    ("a published refusal loses its branch in the client",
     patch("comfyui/h3ir_client.py", '"replacement-target-ambiguous", "replacement-target-unnamed",',
           '"replacement-target-unnamed",'),
     "tests/test_comfyui_node.py"),

    ("the client groups a refusal the compiler no longer makes",
     patch("comfyui/h3ir_client.py", '"aspect-invalid", "director-profile-invalid",',
           '"aspect-was-invalid", "director-profile-invalid",'),
     "tests/test_contract_drift.py::test_the_refusals_the_client_groups_are_all_refusals_the_compiler_still_makes"),

    ("the scan for the compiler's own refusals stops matching",
     patch("tests/test_contract.py", 'refusals = set(re.findall(r\'BriefRefused\\(\\s*\\n?\\s*"([a-z-]+)"\', compiler))',
           'refusals = set()'),
     "tests/test_contract.py::test_the_contract_lists_every_refusal_the_service_can_raise"),

    ("a refusal offers the user raw role tokens instead of the words on the dropdown",
     patch("comfyui/contract.py",
           "    return T.WORDS_FOR_ROLE.get(TRAY_KIND.get(kind, \"\"), {}).get(role, role)",
           "    return role"),
     "tests/test_contract_drift.py::test_a_slot_set_to_a_job_the_service_has_no_name_for_stops_the_graph"),

    ("the pack tells people to install a version this tree is not",
     patch("comfyui/contract.py", 'FIRST_PUBLISHING_RELEASE = "0.3.0"',
           'FIRST_PUBLISHING_RELEASE = "0.2.0"'),
     "tests/test_contract_drift.py::test_the_version_the_pack_tells_people_to_install_is_the_one_that_carries_the_contract"),

    ("an optional key is described by a stand-in instead of the real value",
     patch("comfyui/h3ir_client.py",
           "transcripts=dict(transcripts or {}), **brief))",
           "transcripts={}, **brief))"),
     "tests/test_contract_drift.py::test_the_optional_keys_are_described_by_what_the_graph_actually_carries"),

    ("the node stops passing the graph's real transcripts to the check",
     patch("comfyui/nodes.py", "payload_shape(written, brief, transcripts)",
           "payload_shape(written, brief)"),
     "tests/test_contract_drift.py::test_the_node_passes_the_graphs_own_transcripts_to_the_check"),

    ("the pack imports the compiler while ComfyUI is loading it",
     patch("comfyui/contract.py", "from . import tray as T",
           "from . import tray as T\nimport h3ir.contract"),
     "tests/test_contract_drift.py::test_the_pack_never_imports_the_compiler_while_it_is_being_imported"),

    ("a second place in the pack reaches for the compiler",
     patch("comfyui/h3ir_client.py", "def payload_shape(",
           "def _also_imports_it():\n    from h3ir import contract\n    return contract\n\n\ndef payload_shape("),
     "tests/test_contract_drift.py::test_the_one_place_that_does_import_the_compiler_is_the_one_that_must"),

    ("an absent compiler raises instead of answering None",
     patch("comfyui/contract.py",
           "    try:\n        from h3ir.contract import contract\n    except Exception:      # noqa: BLE001 - absent, broken, or half-installed are all \"no contract\"\n        return None",
           "    from h3ir.contract import contract"),
     "tests/test_contract_drift.py::test_no_compiler_in_this_python_is_an_answer_rather_than_a_crash"),

    ("a half-installed compiler's rubbish is taken for a contract",
     patch("comfyui/contract.py",
           '    return got if isinstance(got, dict) and "contract_version" in got else None',
           "    return got"),
     "tests/test_contract_drift.py::test_a_compiler_that_answers_with_rubbish_is_treated_as_absent"),

    ("the node compares a local compiler against the remote one it compiles with",
     patch("comfyui/nodes.py", "            fetch_contract(machine[\"server\"]",
           "            installed_contract() or fetch_contract(machine[\"server\"]"),
     "tests/test_contract_drift.py::test_the_pack_never_reaches_for_the_compiler_while_it_is_talking_to_a_service"),

    ("the contract stops saying which surface its field lists describe",
     patch("h3ir/contract.py", '"field_lists_describe": ROLE_OF_THE_FIELD_LISTS}',
           '"field_lists_describe": "the request"}'),
     "tests/test_contract.py::test_the_document_says_which_surface_its_field_lists_describe"),

    ("capabilities grows its own copy of a list the contract owns",
     patch("h3ir/service.py", '"aspects": list(C.ASPECTS),', '"aspects": ["16:9", "9:16"],'),
     "tests/test_contract.py::test_the_service_publishes_one_statement_of_the_lists_it_shares_with_the_contract"),
]


def _wipe_bytecode() -> None:
    """Every `__pycache__` in the checkout, gone. See the module docstring for why this is not
    hygiene.

    Collected before anything is deleted. `rglob` walks the tree lazily, and deleting directories
    out from under a live walk gives undefined coverage of the rest of it.
    """
    caches = [c for c in REPO.rglob("__pycache__") if ".venv" not in c.parts]
    for cache in caches:
        shutil.rmtree(cache, ignore_errors=True)


def _pytest(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([PY, "-m", "pytest", "-q", "--no-header", "-p", "no:cacheprovider",
                           *args], cwd=REPO, capture_output=True, text=True)


def preflight() -> list[str]:
    """Before a single defect is planted: does every test named here exist, and does it pass?

    Both halves matter. A node id that no longer resolves makes pytest exit 4, which an earlier
    draft of this file counted as RED -- so a renamed test read as a guard firing. And a test that
    is already failing makes the RED after it meaningless.
    """
    ids = sorted({i for _n, _d, tests in CASES for i in tests.split()})
    print(f"pre-flight: {len(ids)} distinct tests named by {len(CASES)} cases")
    problems, real = [], list(ids)
    if _pytest("--collect-only", *ids).returncode != 0:
        real = []
        for one in ids:
            if _pytest("--collect-only", one).returncode == 0:
                real.append(one)
            else:
                problems.append(f"{one} does not exist; the case naming it can never mean anything")
    # Only over the ids that resolve. Running the whole batch when one id is bad makes pytest exit
    # on the usage error and report nothing about the rest, which would print as a second, separate
    # problem that is really the first one wearing a different coat.
    if real:
        clean = _pytest(*real)
        if clean.returncode != 0:
            problems.append("these tests do not all pass on the clean tree, so any RED below "
                            f"proves nothing: {clean.stdout.strip().splitlines()[-1]}")
    print("pre-flight: " + ("OK, every named test exists and passes on the clean tree"
                            if not problems else f"{len(problems)} problem(s)"))
    for p in problems:
        print("   ", p)
    return problems


def main() -> int:
    backup = {f: (REPO / f).read_text(encoding="utf-8") for f in TOUCHES}
    _wipe_bytecode()
    if preflight():
        print("\nnothing was planted. Fix the cases above first.")
        return 2
    print()

    red, green, broken = [], [], []
    for name, defect, tests in CASES:
        note = ""
        try:
            defect.plant()
            _wipe_bytecode()
            note = defect.prove_live()
            out = _pytest(*tests.split())
            if out.returncode == TESTS_FAILED:
                red.append(name)
                print(f"RED     {name}")
            elif out.returncode == TESTS_PASSED:
                green.append((name, note, out.stdout.strip().splitlines()[-1]))
                print(f"GREEN   {name}")
                print(f"        the defect WAS live ({note}) and the guard passed anyway")
                print(f"        {out.stdout.strip().splitlines()[-1]}")
            else:
                why = CANNOT_ASK.get(out.returncode, f"pytest exited {out.returncode}")
                broken.append((name, why))
                print(f"BROKEN  {name}")
                print(f"        {why}; this case asked nothing")
        except CaseBroken as e:
            broken.append((name, str(e)))
            print(f"BROKEN  {name}")
            print(f"        {e}")
        finally:
            for f, text in backup.items():
                (REPO / f).write_text(text, encoding="utf-8")
            wrong = [f for f, text in backup.items()
                     if (REPO / f).read_text(encoding="utf-8") != text]
            if wrong:
                print(f"        the tree was NOT restored: {wrong}. Stopping.")
                return 3
    _wipe_bytecode()

    print()
    print(f"{len(red)} red, {len(green)} green, {len(broken)} broken, of {len(CASES)} cases")
    for name, note, tail in green:
        print(f"  GUARD DID NOT FIRE  {name}  ({note}; {tail})")
    for name, why in broken:
        print(f"  CASE DID NOT RUN    {name}  ({why})")
    if green or broken:
        return 1
    print(f"all {len(CASES)} guards fired")
    return 0


if __name__ == "__main__":
    sys.exit(main())
