#!/usr/bin/env python
"""Break each thing the contract guards, one at a time, and confirm the guard goes red.

A test that has never been seen failing is a test nobody has verified, and this suite has already
shipped one that was green for its whole life while the field it guarded was being dropped in
transit. So every check added for the compiler/pack contract has a defect written for it here: the
defect is planted, the test that claims to catch it is run, and the file is put back.

    .venv/bin/python research/contract_falsification.py

It edits the working tree and restores it, so run it on a clean tree and check `git status` after.

**Half of these cases live in the node pack's repository now.** The compiler and the pack ship to
two audiences and are two repositories, so every case whose defect and guard are both over there
went with them, along with the one that edits this compiler to prove the pack notices. What is left
here is the thirteen whose defect is in this tree and whose guard is `tests/test_contract.py`. Run
both, in their own repositories; neither is complete on its own and neither can reach the other.

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


TOUCHES = ["h3ir/compile.py", "h3ir/director.py", "h3ir/service.py", "h3ir/models.py",
           "h3ir/contract.py", "h3ir/cli.py", "tests/test_contract.py"]


class CaseBroken(RuntimeError):
    """This case did not run. Never reported as a guard that failed to fire."""


_IMPORTABLE: set[str] | None = None


def _importable() -> set[str]:
    """Which of the modules these cases touch can be imported here AT ALL, measured on the clean
    tree once.

    Every module these cases touch is importable here today. It is measured rather than assumed so
    that a file which stops being importable reports BROKEN honestly, instead of a case quietly
    downgrading itself to a read-back and claiming the same confidence.
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

        Whether a file is importable is MEASURED at startup rather than listed here, so a file
        that stops being importable reports BROKEN rather than silently becoming a read-back.
        """
        if self.path.suffix != ".py" or self.rel.startswith("tests/"):
            return None
        name = self.rel[:-3].replace("/", ".")
        return name if name in _importable() else None

    def prove_live(self) -> str:
        """Confirm the tests would really see the edit, proved the way the tests consume the file.

        A module a test imports can be shadowed by an install or served from a stale cache, and
        neither shows up in a read-back, so it is imported in a subprocess and asked which file it
        came from and what is in it. A file a test reads as text is already fully proved by the
        read-back in `plant`, and importing it would fail for reasons that have nothing to do with
        the defect.
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




def patch(rel: str, old: str, new: str) -> Defect:
    return Defect(rel, old, new)



CASES = [
    ("a director's prose is edited and the contract version is not bumped",
     patch("h3ir/director.py", "The camera is mounted and travelling",
           "The camera is bolted down and travelling"),
     "tests/test_contract.py::test_the_version_moves_when_any_part_of_the_contract_moves"),

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

    ("the scan for the compiler's own refusals stops matching",
     patch("tests/test_contract.py", 'refusals = set(re.findall(r\'BriefRefused\\(\\s*\\n?\\s*"([a-z-]+)"\', compiler))',
           'refusals = set()'),
     "tests/test_contract.py::test_the_contract_lists_every_refusal_the_service_can_raise"),

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
