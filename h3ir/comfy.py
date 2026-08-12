"""ComfyUI over HTTP. No filesystem assumptions anywhere.

Assume the compiler and ComfyUI are on different machines, because eventually they will be. This
module must never read or write ComfyUI's directories directly: references are uploaded over
/upload/image and results are fetched over /view. That also means a wrong path fails at the
boundary with a clear error instead of silently producing an empty render.

This module does not own the graph. The plumbing specialist owns it; we take their exported
API-format workflow and substitute the prompt text. That is what makes the acceptance test
honest -- same graph, same seed, one field different.
"""
from __future__ import annotations

import copy
import json
import time
from pathlib import Path
from typing import Any

import httpx

from .config import get_config

H3_NODE_CLASSES = ("MiniMaxH3ReferenceToVideo", "MiniMaxH3ImageToVideo")


class ComfyError(RuntimeError):
    pass


class Comfy:
    def __init__(self, cfg=None, client: httpx.Client | None = None):
        c = cfg or get_config()
        self.base = c.comfy.base_url.rstrip("/")
        self.timeout = c.comfy.timeout_s
        self._client = client
        self._owns = client is None

    def _http(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(timeout=self.timeout)
        return self._client

    def close(self) -> None:
        if self._client is not None and self._owns:
            self._client.close()
            self._client = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # ------------------------------------------------------------------ status

    def stats(self) -> dict[str, Any]:
        r = self._http().get(f"{self.base}/system_stats")
        r.raise_for_status()
        return r.json()

    def has_h3_nodes(self) -> dict[str, bool]:
        r = self._http().get(f"{self.base}/object_info", timeout=max(self.timeout, 60.0))
        r.raise_for_status()
        info = r.json()
        return {k: k in info for k in H3_NODE_CLASSES}

    # ------------------------------------------------------------------ assets

    def upload_image(self, path: str | Path, subfolder: str = "h3ir",
                     overwrite: bool = True) -> str:
        """Returns the name ComfyUI will accept in a LoadImage node."""
        p = Path(path)
        if not p.exists():
            raise ComfyError(f"no such file: {p}")
        files = {"image": (p.name, p.read_bytes())}
        data = {"subfolder": subfolder, "overwrite": "true" if overwrite else "false"}
        r = self._http().post(f"{self.base}/upload/image", files=files, data=data)
        if r.status_code >= 400:
            raise ComfyError(f"upload failed: HTTP {r.status_code}: {r.text[:200]}")
        body = r.json()
        name = body.get("name") or p.name
        sub = body.get("subfolder") or subfolder
        return f"{sub}/{name}" if sub else name

    def view(self, filename: str, subfolder: str = "", kind: str = "output") -> bytes:
        r = self._http().get(f"{self.base}/view",
                             params={"filename": filename, "subfolder": subfolder, "type": kind})
        r.raise_for_status()
        return r.content

    # ------------------------------------------------------------------ jobs

    def submit(self, graph: dict[str, Any], client_id: str = "h3ir") -> str:
        r = self._http().post(f"{self.base}/prompt",
                              json={"prompt": graph, "client_id": client_id})
        if r.status_code >= 400:
            raise ComfyError(f"submit rejected: HTTP {r.status_code}: {r.text[:600]}")
        pid = r.json().get("prompt_id")
        if not pid:
            raise ComfyError(f"no prompt_id in response: {r.text[:200]}")
        return pid

    def history(self, prompt_id: str) -> dict[str, Any]:
        r = self._http().get(f"{self.base}/history/{prompt_id}")
        r.raise_for_status()
        return r.json().get(prompt_id) or {}

    def wait(self, prompt_id: str, *, poll_s: float = 2.0,
             timeout_s: float = 3600.0) -> dict[str, Any]:
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            h = self.history(prompt_id)
            status = (h.get("status") or {})
            if status.get("completed"):
                return h
            if status.get("status_str") == "error":
                raise ComfyError(f"job failed: {json.dumps(status)[:600]}")
            time.sleep(poll_s)
        raise ComfyError(f"job {prompt_id} did not finish within {timeout_s}s")

    @staticmethod
    def outputs(history: dict[str, Any]) -> list[dict[str, Any]]:
        out = []
        for node_id, payload in (history.get("outputs") or {}).items():
            for key in ("images", "gifs", "videos", "audio"):
                for item in payload.get(key) or []:
                    out.append({"node": node_id, "kind": key, **item})
        return out


# --------------------------------------------------------------------------- graph editing

def find_h3_nodes(graph: dict[str, Any]) -> list[str]:
    return [nid for nid, node in graph.items()
            if isinstance(node, dict) and node.get("class_type") in H3_NODE_CLASSES]


def set_prompt(graph: dict[str, Any], text: str, *, node_id: str | None = None) -> dict[str, Any]:
    """Return a copy of the graph with the H3 node's prompt replaced.

    Refuses rather than guesses when the graph has no H3 node or several: silently editing the
    wrong node would produce a render that looks like a prompt-quality result.
    """
    g = copy.deepcopy(graph)
    ids = [node_id] if node_id else find_h3_nodes(g)
    if not ids:
        raise ComfyError("no MiniMaxH3 conditioning node in this graph; "
                         f"looked for {H3_NODE_CLASSES}")
    if len(ids) > 1:
        raise ComfyError(f"graph has several H3 nodes ({ids}); pass node_id to choose one")
    node = g[ids[0]]
    if "prompt" not in (node.get("inputs") or {}):
        raise ComfyError(f"node {ids[0]} ({node.get('class_type')}) has no `prompt` input")
    node["inputs"]["prompt"] = text
    return g


def set_seed(graph: dict[str, Any], seed: int) -> dict[str, Any]:
    """Pin every sampler seed so an A/B differs only by the prompt."""
    g = copy.deepcopy(graph)
    for node in g.values():
        if not isinstance(node, dict):
            continue
        inputs = node.get("inputs") or {}
        for key in ("seed", "noise_seed"):
            if key in inputs and isinstance(inputs[key], (int, float)):
                inputs[key] = seed
    return g


def describe_graph(graph: dict[str, Any]) -> dict[str, Any]:
    """What the graph will actually do, for the record kept beside a render."""
    h3 = find_h3_nodes(graph)
    loras = [n.get("inputs", {}) for n in graph.values()
             if isinstance(n, dict) and "Lora" in str(n.get("class_type", ""))]
    seeds = sorted({v for n in graph.values() if isinstance(n, dict)
                    for k, v in (n.get("inputs") or {}).items()
                    if k in ("seed", "noise_seed") and isinstance(v, (int, float))})
    return {"nodes": len(graph), "h3_nodes": h3, "seeds": seeds,
            "lora_nodes": len(loras),
            "classes": sorted({n.get("class_type") for n in graph.values()
                               if isinstance(n, dict) and n.get("class_type")})}


def probe(cfg=None) -> dict[str, Any]:
    c = cfg or get_config()
    out: dict[str, Any] = {"url": c.comfy.base_url}
    try:
        with Comfy(c) as comfy:
            st = comfy.stats()
            sysinfo = st.get("system") or {}
            devices = st.get("devices") or []
            out["reachable"] = True
            out["comfyui"] = sysinfo.get("comfyui_version")
            out["python"] = sysinfo.get("python_version", "")[:12]
            if devices:
                d = devices[0]
                out["device"] = d.get("name")
                out["vram_total_gib"] = round((d.get("vram_total") or 0) / 2**30, 2)
                out["vram_free_gib"] = round((d.get("vram_free") or 0) / 2**30, 2)
            out["h3_nodes"] = comfy.has_h3_nodes()
    except Exception as e:  # noqa: BLE001 - diagnostics
        out["reachable"] = False
        out["error"] = f"{type(e).__name__}: {e}"
    return out
