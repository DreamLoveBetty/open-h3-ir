"""Stage A": the style-LoRA registry.

A trigger token is text in the IR, so it inherits the same discipline as `<d>` and
`<Picture N>`: right bytes, right slot, or it silently does nothing at full compute cost.

`howtouse.md` is split strictly by consumer -- YAML front matter for the compiler, prose body
for the planner. The trigger must survive byte-exact and prose read by a model is lossy; "does
this fit the request?" is a judgement that wants prose. So the deterministic side reads only
the front matter and the model side reads only the body.

The agent selects a LoRA by id. It never types a trigger, for the same reason it never types
`<Picture 1>`.
"""
from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import get_config
from .models import Brief, Finding, LoraChoice, Mode

log = logging.getLogger("h3ir.lora")

# A trigger containing any of these cannot be used: it collides with the grammar the
# validator relies on to catch dangling labels, and weakening that would reopen the whole
# `<Image 1>` class of bug. Refused at ingest, not discovered later as a quality loss.
RESERVED_PATTERNS = (
    re.compile(r"<\s*[A-Za-z]+\s*\d*\s*>"),
    re.compile(r"\[\s*Shot", re.I),
    re.compile(r"\(\s*S\d"),
    re.compile(r"</?d>|<scenetrans>|<cutoff>"),
)


@dataclass
class LoraRecord:
    id: str
    name: str
    kind: str
    target: str
    h3_variant: tuple[str, ...]
    file: str
    sha256: str
    version: int
    triggers: tuple[dict[str, Any], ...]
    strength: dict[str, float]
    constrains: dict[str, Any] = field(default_factory=dict)
    conflicts_with: tuple[str, ...] = ()
    body: str = ""
    source_path: str = ""

    def what_for(self) -> str:
        """The prose a planner matches against a request."""
        m = re.search(r"##\s*What it'?s for\s*\n(.+?)(?:\n##|\Z)", self.body, re.S | re.I)
        return (m.group(1).strip() if m else self.body.strip())[:800]

    def when_not(self) -> str:
        m = re.search(r"##\s*When NOT to use it\s*\n(.+?)(?:\n##|\Z)", self.body, re.S | re.I)
        return (m.group(1).strip() if m else "")[:600]

    def public(self) -> dict[str, Any]:
    # NOTE: LoRA findings use the W (weights) prefix, NOT X. `compile.py` owns X for compiler
    # invariants, and the two namespaces silently collided on TEN numbers -- X7 through X16 each
    # meant one thing here and a different thing there, so one rule id carried two meanings
    # depending on which file emitted it. Keep new LoRA ids on W.
        """What GET /v1/loras exposes: everything needed to choose, no byte-exact strings."""
        return {"id": self.id, "name": self.name, "kind": self.kind, "target": self.target,
                "variants": list(self.h3_variant), "strength": self.strength,
                "constrains": {k: v for k, v in self.constrains.items() if v},
                "conflicts_with": list(self.conflicts_with),
                "what_for": self.what_for(), "when_not": self.when_not()}


def _parse_front_matter(text: str) -> tuple[dict[str, Any], str]:
    """Minimal YAML subset: scalars, inline lists, one nesting level of mappings.

    Deliberately not a YAML dependency: the registry is read at startup on a machine we
    control, and the schema is small and fixed.
    """
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end < 0:
        return {}, text
    head, body = text[3:end], text[end + 4:]
    data: dict[str, Any] = {}
    current_key: str | None = None
    list_items: list[Any] = []

    def flush():
        nonlocal current_key, list_items
        if current_key is not None:
            data[current_key] = list_items
        current_key, list_items = None, []

    for raw in head.splitlines():
        line = raw.rstrip()
        if not line.strip() or line.strip().startswith("#"):
            continue
        if re.match(r"^\s*-\s", line) and current_key:
            item = line.strip()[1:].strip()
            if item.startswith("{"):
                list_items.append(_inline_map(item))
            elif ":" in item and not item.split(":", 1)[0].strip().startswith(('"', "'")):
                k, v = item.split(":", 1)
                list_items.append({k.strip(): _scalar(v.strip())})
            else:
                list_items.append(_scalar(item))
            continue
        if re.match(r"^\s+\w+\s*:", line) and current_key:
            k, v = line.strip().split(":", 1)
            if list_items and isinstance(list_items[-1], dict):
                list_items[-1][k.strip()] = _scalar(v.strip())
                continue
            if not isinstance(data.get(current_key), dict):
                data[current_key] = {}
            data[current_key][k.strip()] = _scalar(v.strip())
            continue
        flush()
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        k, v = k.strip(), v.strip()
        if v == "":
            current_key, list_items = k, []
        elif v.startswith("["):
            data[k] = [_scalar(x) for x in v.strip("[]").split(",") if x.strip()]
        elif v.startswith("{"):
            data[k] = _inline_map(v)
        else:
            data[k] = _scalar(v)
    flush()
    for k, val in list(data.items()):
        if isinstance(val, list) and not val:
            data[k] = []
    return data, body


def _inline_map(s: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for part in s.strip("{}").split(","):
        if ":" in part:
            k, v = part.split(":", 1)
            out[k.strip()] = _scalar(v.strip())
    return out


def _scalar(v: str) -> Any:
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        return v[1:-1]              # quoted: casing and spacing are load-bearing
    low = v.lower()
    if low in ("null", "none", "~", ""):
        return None
    if low in ("true", "yes"):
        return True
    if low in ("false", "no"):
        return False
    try:
        return int(v)
    except ValueError:
        pass
    try:
        return float(v)
    except ValueError:
        return v


def trigger_problem(text: str) -> str | None:
    """Ingest-time validation. Returns why a trigger is unusable, or None."""
    if not text or not text.strip():
        return "empty trigger"
    if text != text.strip():
        return "leading or trailing whitespace would not survive placement"
    for pat in RESERVED_PATTERNS:
        if pat.search(text):
            return (f"collides with H3's reserved grammar ({pat.pattern}); this cannot be used "
                    "inside the IR format and cannot be aliased without retraining")
    return None


def load_record(path: Path) -> tuple[LoraRecord | None, list[Finding]]:
    findings: list[Finding] = []
    fm, body = _parse_front_matter(path.read_text(encoding="utf-8"))
    if not fm.get("id"):
        return None, [Finding("W6-lora-no-id", "ERROR", f"{path}: front matter has no `id`")]

    raw_triggers = fm.get("triggers") or []
    triggers: list[dict[str, Any]] = []
    for t in raw_triggers:
        if not isinstance(t, dict):
            t = {"text": t}
        text = str(t.get("text", ""))
        why = trigger_problem(text)
        if why:
            findings.append(Finding("W7-lora-bad-trigger", "ERROR",
                                    f"{fm['id']}: trigger {text!r} {why}"))
            continue
        triggers.append({"text": text,
                         "required": bool(t.get("required", True)),
                         "placement": t.get("placement", "style"),
                         "count": int(t.get("count", t.get("repeat", 1)) or 1)})

    strength = fm.get("strength") or {}
    if not isinstance(strength, dict):
        strength = {}
    rec = LoraRecord(
        id=str(fm["id"]), name=str(fm.get("name", fm["id"])), kind=str(fm.get("kind", "style")),
        target=str(fm.get("target", "minimax_h3")),
        h3_variant=tuple(str(v) for v in (fm.get("h3_variant") or ["ref2va", "fl2va"])),
        file=str(fm.get("file", "")), sha256=str(fm.get("sha256", "")),
        version=int(fm.get("version", 1) or 1), triggers=tuple(triggers),
        strength={"default": float(strength.get("default", 0.8)),
                  "min": float(strength.get("min", 0.0)),
                  "max": float(strength.get("max", 1.5))},
        constrains=fm.get("constrains") if isinstance(fm.get("constrains"), dict) else {},
        conflicts_with=tuple(str(x) for x in (fm.get("conflicts_with") or [])),
        body=body, source_path=str(path))
    if not rec.triggers:
        findings.append(Finding("W8-lora-no-trigger", "WARN",
                                f"{rec.id}: no usable trigger; it will be loaded but nothing in "
                                "the prompt will activate it"))
    return rec, findings


def load_registry() -> tuple[dict[str, LoraRecord], list[Finding], str]:
    """Scan the configured folders. Revision is a hash of what was found, so a swapped file
    changes the revision recorded with every render."""
    records: dict[str, LoraRecord] = {}
    findings: list[Finding] = []
    seen: list[str] = []
    for d in get_config().paths.lora_dirs:
        if not d.exists():
            continue
        for md in sorted(d.rglob("howtouse.md")):
            rec, f = load_record(md)
            findings += f
            if rec is None:
                continue
            if rec.id in records:
                findings.append(Finding("W9-lora-duplicate-id", "ERROR",
                                        f"duplicate LoRA id {rec.id!r} at {md}"))
                continue
            records[rec.id] = rec
            seen.append(f"{rec.id}:{rec.version}:{rec.sha256}")
    revision = hashlib.sha256("|".join(sorted(seen)).encode()).hexdigest()[:12]
    return records, findings, revision


def resolve_loras(requested: list[dict[str, Any]], mode: Mode,
                  brief: Brief) -> tuple[list[LoraChoice], list[Finding]]:
    """Validate the caller's choice against the request, clamp strength, plan the injection."""
    if not requested:
        return [], []
    records, findings, revision = load_registry()
    chosen: list[LoraChoice] = []
    picked: list[LoraRecord] = []

    for req in requested:
        lid = str(req.get("id", "")).strip()
        rec = records.get(lid)
        if rec is None:
            findings.append(Finding("W10-lora-unknown", "ERROR",
                                    f"no LoRA registered with id {lid!r}; "
                                    f"known: {sorted(records) or 'none'}"))
            continue
        if mode.checkpoint not in rec.h3_variant:
            findings.append(Finding("W11-lora-variant", "ERROR",
                                    f"{rec.id} is trained for {list(rec.h3_variant)} but this "
                                    f"request routes to the {mode.checkpoint} checkpoint"))
            continue
        bad = _constraint_violation(rec, brief)
        if bad:
            findings.append(Finding("W12-lora-constraint", "ERROR", f"{rec.id}: {bad}"))
            continue
        if rec.file:
            path = Path(rec.source_path).parent / rec.file
            if not path.exists():
                findings.append(Finding("W13-lora-file-missing", "ERROR",
                                        f"{rec.id}: weights not found at {path}"))
                continue
            if set(rec.sha256) <= {"0"} or not rec.sha256:
                findings.append(Finding("W16-lora-sha-unverified", "WARN",
                                        f"{rec.id}: sha256 is a placeholder, so a swapped file "
                                        "would not be detected in the render record"))
            elif _file_sha(path) != rec.sha256:
                findings.append(Finding("W17-lora-sha-mismatch", "ERROR",
                                        f"{rec.id}: the file at {path} does not match the "
                                        "recorded sha256; yesterday's render is not reproducible"))
                continue
        picked.append(rec)

        want = float(req.get("strength", rec.strength["default"]))
        applied = min(rec.strength["max"], max(rec.strength["min"], want))
        if abs(applied - want) > 1e-9:
            findings.append(Finding("W14-lora-strength-clamped", "WARN",
                                    f"{rec.id}: strength {want} clamped to {applied} "
                                    f"(declared range {rec.strength['min']}-{rec.strength['max']})"))
        chosen.append(LoraChoice(id=rec.id, version=rec.version, file_sha256=rec.sha256,
                                 strength_requested=want, strength_applied=applied,
                                 triggers=[dict(t) for t in rec.triggers],
                                 registry_revision=revision))

    for i, a in enumerate(picked):
        for b in picked[i + 1:]:
            if b.id in a.conflicts_with or a.id in b.conflicts_with:
                findings.append(Finding("W15-lora-conflict", "ERROR",
                                        f"{a.id} and {b.id} declare each other incompatible"))
    return chosen, findings


def _file_sha(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _constraint_violation(rec: LoraRecord, brief: Brief) -> str | None:
    c = rec.constrains or {}
    if c.get("aspect") and str(c["aspect"]) != brief.aspect:
        return f"requires aspect {c['aspect']}, request is {brief.aspect}"
    frames = c.get("duration_frames")
    if frames:
        from .grid import frames_for_seconds
        want = frames_for_seconds(brief.seconds)
        allowed = frames if isinstance(frames, list) else [frames]
        if want not in [int(x) for x in allowed]:
            return f"requires {allowed} frames, request snaps to {want}"
    return None
