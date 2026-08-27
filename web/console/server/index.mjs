// H3·IR Console control API — zero-dependency node:http server.
//
// Owns three things the browser cannot do:
//   1. start/stop the three local services (audio worker, omni fallback, h3ir serve)
//   2. receive asset bytes, hash them, and PUT them to the h3ir content-addressed store
//   3. proxy POST /v1/briefs so the page never talks cross-origin
//
// Every service child is spawned in its own process group with output appended to
// logs/<name>.log; stopping sends SIGTERM to the group. Services already running
// (started outside this console) are reported as {up, managed:false} and are never killed.
import { createServer } from "node:http";
import { spawn } from "node:child_process";
import { createHash } from "node:crypto";
import { createReadStream, createWriteStream } from "node:fs";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const REPO = path.resolve(HERE, "../../..");
const LOGS = path.join(HERE, "..", "logs");
const DATA = path.join(HERE, "..", "data");
const REGISTRY = path.join(DATA, "assets.json");
const SETTINGS = path.join(DATA, "settings.json");
fs.mkdirSync(LOGS, { recursive: true });
fs.mkdirSync(DATA, { recursive: true });

// User-settable LLM endpoint config, persisted in data/settings.json. Applied to the h3ir
// service's environment when the console starts it; values set here outrank ambient env,
// because an explicit edit in the UI is a stronger statement than whatever the shell had.
function readSettings() {
  try { return JSON.parse(fs.readFileSync(SETTINGS, "utf8")); } catch { return {}; }
}
function h3irLlmEnv() {
  const s = readSettings();
  const env = {};
  if (s.llm_url) env.H3IR_LLM_URL = s.llm_url;
  if (s.llm_model) env.H3IR_LLM_MODEL = s.llm_model;
  if (s.llm_key) env.H3IR_LLM_KEY = s.llm_key;
  return env;
}

const MODEL_ENV = {
  MODELSCOPE_CACHE: path.join(REPO, "models", "modelscope"),
  HF_HOME: path.join(REPO, "models", "hf"),
  NO_PROXY: "127.0.0.1,localhost",
};

const SERVICES = {
  worker: {
    label: "AUDIO WORKER",
    port: 50000,
    cwd: path.join(REPO, "services"),
    cmd: [path.join(REPO, "services", ".venv-audio", "bin", "python"), "-m", "audio_worker.app"],
    env: { ...MODEL_ENV },
  },
  omni: {
    label: "OMNI FALLBACK",
    port: 8001,
    cwd: path.join(REPO, "services"),
    cmd: [path.join(REPO, "services", ".venv-audio", "bin", "python"), "-m", "omni_fallback.app"],
    env: { ...MODEL_ENV },
  },
  h3ir: {
    label: "H3IR COMPILER",
    port: 8420,
    cwd: REPO,
    cmd: [path.join(REPO, ".venv", "bin", "python"), "-m", "h3ir.cli",
          "serve", "--host", "127.0.0.1", "--port", "8420"],
    env: {
      NO_PROXY: "127.0.0.1,localhost",
      H3IR_AUDIO_ENABLED: "1",
      H3IR_AUDIO_URL: "http://127.0.0.1:50000",
      H3IR_AUDIO_FALLBACK: "1",
    },
  },
};
const H3IR = `http://127.0.0.1:${SERVICES.h3ir.port}`;

const children = new Map(); // name -> ChildProcess
let h3irHealthCache = { at: 0, detail: null }; // see probe(): /health is expensive on h3ir

function healthUrl(svc) { return `http://127.0.0.1:${svc.port}/health`; }

async function probe(name) {
  const svc = SERVICES[name];
  const child = children.get(name);
  const managedAlive = !!child && child.exitCode === null && !child.killed;
  // h3ir's /health runs the LLM liveness check, which re-fetches the endpoint's model list
  // on every call -- at the console's 3s poll cadence that is a needless /v1/models hammer.
  // Liveness here uses the static /v1/contract instead; the LLM detail block is fetched at
  // most once a minute and served from this cache in between.
  const livenessUrl = name === "h3ir"
    ? `http://127.0.0.1:${svc.port}/v1/contract` : healthUrl(svc);
  try {
    const ctrl = new AbortController();
    const t = setTimeout(() => ctrl.abort(), 4000);
    const r = await fetch(livenessUrl, { signal: ctrl.signal });
    clearTimeout(t);
    let detail = null;
    if (name === "h3ir") {
      if (r.ok && Date.now() - h3irHealthCache.at > 60_000) {
        try {
          const hr = await fetch(healthUrl(svc), { signal: AbortSignal.timeout(10_000) });
          h3irHealthCache = { at: Date.now(), detail: hr.ok ? await hr.json() : null };
        } catch { /* keep the stale cache */ }
      }
      detail = r.ok ? h3irHealthCache.detail : null;
    } else {
      try { detail = await r.json(); } catch { /* body optional */ }
    }
    return { name, label: svc.label, port: svc.port, up: r.ok, managed: managedAlive,
             pid: managedAlive ? child.pid : null, detail };
  } catch {
    // A managed child that died on its own must not keep claiming a pid.
    if (child && child.exitCode !== null) children.delete(name);
    return { name, label: svc.label, port: svc.port, up: false,
             managed: managedAlive, pid: managedAlive ? child.pid : null, detail: null };
  }
}

function startService(name) {
  const svc = SERVICES[name];
  const existing = children.get(name);
  if (existing && existing.exitCode === null) return { started: false, reason: "already running" };
  const logFd = fs.openSync(path.join(LOGS, `${name}.log`), "a");
  const child = spawn(svc.cmd[0], svc.cmd.slice(1), {
    cwd: svc.cwd,
    env: { ...process.env, ...svc.env, ...(name === "h3ir" ? h3irLlmEnv() : {}) },
    stdio: ["ignore", logFd, logFd],
    detached: true, // own process group, so stop reaches python's children too
  });
  child.on("exit", () => { if (children.get(name) === child) children.delete(name); });
  children.set(name, child);
  return { started: true, pid: child.pid };
}

function stopService(name) {
  const child = children.get(name);
  if (!child || child.exitCode !== null) return { stopped: false, reason: "not managed here" };
  try { process.kill(-child.pid, "SIGTERM"); } catch { try { child.kill("SIGTERM"); } catch { } }
  children.delete(name);
  return { stopped: true };
}

// ------------------------------------------------------------------ asset registry
function readRegistry() {
  try { return JSON.parse(fs.readFileSync(REGISTRY, "utf8")); } catch { return []; }
}
function writeRegistry(rows) {
  fs.writeFileSync(REGISTRY, JSON.stringify(rows, null, 2));
}
const KIND_OF = {
  png: "image", jpg: "image", jpeg: "image", webp: "image", gif: "image",
  mp4: "video", mov: "video", webm: "video", mkv: "video",
  wav: "audio", mp3: "audio", m4a: "audio", flac: "audio", aac: "audio", ogg: "audio",
};

// ------------------------------------------------------------------ http helpers
function send(res, code, obj) {
  const body = JSON.stringify(obj);
  res.writeHead(code, { "content-type": "application/json", "access-control-allow-origin": "*" });
  res.end(body);
}
function readBody(req, limit = 1024 * 1024 * 1024) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    let n = 0;
    req.on("data", (c) => {
      n += c.length;
      if (n > limit) { reject(new Error("body too large")); req.destroy(); return; }
      chunks.push(c);
    });
    req.on("end", () => resolve(Buffer.concat(chunks)));
    req.on("error", reject);
  });
}

async function h3irUp() {
  try {
    const ctrl = new AbortController();
    const t = setTimeout(() => ctrl.abort(), 2500);
    const r = await fetch(`${H3IR}/v1/contract`, { signal: ctrl.signal });
    clearTimeout(t);
    return r.ok;
  } catch { return false; }
}

// ------------------------------------------------------------------ routes
const server = createServer(async (req, res) => {
  const url = new URL(req.url, "http://x");
  const p = url.pathname;
  try {
    if (req.method === "OPTIONS") {
      res.writeHead(204, {
        "access-control-allow-origin": "*",
        "access-control-allow-methods": "GET,POST,DELETE,OPTIONS",
        "access-control-allow-headers": "content-type,x-filename",
      });
      return res.end();
    }

    if (p === "/api/settings" && req.method === "GET") {
      const s = readSettings();
      // the key is reported as set/not-set, never echoed back
      return send(res, 200, { llm_url: s.llm_url || "", llm_model: s.llm_model || "",
                              llm_key_set: !!s.llm_key });
    }
    if (p === "/api/settings" && req.method === "POST") {
      const body = JSON.parse((await readBody(req)).toString() || "{}");
      const prev = readSettings();
      const next = {
        llm_url: String(body.llm_url ?? prev.llm_url ?? "").trim(),
        llm_model: String(body.llm_model ?? prev.llm_model ?? "").trim(),
        // null means "clear it"; undefined means "leave whatever is stored"
        llm_key: body.llm_key === null ? "" : (body.llm_key !== undefined ? String(body.llm_key) : prev.llm_key || ""),
      };
      fs.writeFileSync(SETTINGS, JSON.stringify(next, null, 2));
      const svc = children.get("h3ir");
      return send(res, 200, { ok: true, llm_url: next.llm_url, llm_model: next.llm_model,
                              llm_key_set: !!next.llm_key,
                              restart_needed: !!(svc && svc.exitCode === null) });
    }

    // Probe the well-known local LLM servers (plus any URL the caller is typing) for their
    // /v1/models list, so the CFG panel can offer click-to-fill instead of hand-typed ids.
    // A server that publishes no model list is reported without one; which model has a
    // vision tower is never guessed from metadata (repo rule) — that is what doctor is for.
    if (p === "/api/detect-llm" && req.method === "GET") {
      const KNOWN = [
        ["LM Studio", "http://127.0.0.1:1234/v1"],
        ["Ollama", "http://127.0.0.1:11434/v1"],
        ["vLLM", "http://127.0.0.1:8000/v1"],
      ];
      const saved = readSettings();
      const extra = url.searchParams.get("extra");
      // Auth: the key being typed wins, then the stored one. A 401 is not "absent" — it is
      // a live endpoint that wants a token (LM Studio's API-token requirement), so it is
      // reported as found-but-needs-auth instead of being swallowed as silence.
      const key = url.searchParams.get("key") || saved.llm_key || "";
      const candidates = [...KNOWN.map(([source, u]) => ({ source, url: u }))];
      for (const [source, u] of [["saved", saved.llm_url], ["custom", extra]]) {
        if (u && !candidates.some((c) => c.url === u)) candidates.push({ source, url: u });
      }
      const probeOne = async ({ source, url: base }) => {
        try {
          const headers = key ? { authorization: `Bearer ${key}` } : {};
          const r = await fetch(base.replace(/\/$/, "") + "/models",
                                { headers, signal: AbortSignal.timeout(1500) });
          if (r.status === 401 || r.status === 403)
            return { source, url: base, models: [], needsAuth: true };
          if (!r.ok) return null;
          const body = await r.json();
          const models = Array.isArray(body?.data)
            ? body.data.map((m) => m?.id).filter(Boolean) : [];
          return { source, url: base, models };
        } catch { return null; }
      };
      const found = (await Promise.all(candidates.map(probeOne))).filter(Boolean);
      return send(res, 200, { endpoints: found });
    }

    if (p === "/api/status" && req.method === "GET") {
      const rows = {};
      for (const name of Object.keys(SERVICES)) rows[name] = await probe(name);
      return send(res, 200, { services: rows });
    }

    let m;
    if ((m = p.match(/^\/api\/services\/(worker|omni|h3ir)\/(start|stop)$/)) && req.method === "POST") {
      const [, name, action] = m;
      if (action === "start") {
        const st = await probe(name);
        if (st.up) return send(res, 200, { ok: true, note: "already up", service: st });
        return send(res, 200, { ok: true, ...startService(name) });
      }
      return send(res, 200, { ok: true, ...stopService(name) });
    }

    if (p === "/api/services/start-all" && req.method === "POST") {
      const out = {};
      for (const name of ["worker", "omni", "h3ir"]) {
        const st = await probe(name);
        out[name] = st.up ? { note: "already up" } : startService(name);
      }
      return send(res, 200, { ok: true, results: out });
    }
    if (p === "/api/services/stop-all" && req.method === "POST") {
      const out = {};
      for (const name of Object.keys(SERVICES)) out[name] = stopService(name);
      return send(res, 200, { ok: true, results: out });
    }

    if ((m = p.match(/^\/api\/logs\/(worker|omni|h3ir)$/)) && req.method === "GET") {
      const file = path.join(LOGS, `${m[1]}.log`);
      let text = "";
      try {
        const all = fs.readFileSync(file, "utf8");
        text = all.split("\n").slice(-120).join("\n");
      } catch { /* no log yet */ }
      return send(res, 200, { log: text });
    }

    if (p === "/api/assets" && req.method === "GET") {
      return send(res, 200, { assets: readRegistry() });
    }

    if (p === "/api/assets" && req.method === "POST") {
      if (!(await h3irUp()))
        return send(res, 503, { error: "h3ir service is not running — start it first" });
      const filename = decodeURIComponent(req.headers["x-filename"] || "asset.bin");
      const bytes = await readBody(req);
      const sha256 = createHash("sha256").update(bytes).digest("hex");
      const up = await fetch(`${H3IR}/v1/assets/${sha256}`, {
        method: "PUT",
        headers: { "content-type": "application/octet-stream" },
        body: bytes,
      });
      const text = await up.text();
      if (!up.ok) return send(res, up.status, { error: `h3ir refused the upload: ${text}` });
      const ext = (filename.split(".").pop() || "").toLowerCase();
      const rows = readRegistry();
      if (!rows.some((r) => r.sha256 === sha256)) {
        rows.unshift({ sha256, name: filename, bytes: bytes.length,
                       kind: KIND_OF[ext] || "image", at: new Date().toISOString() });
        writeRegistry(rows);
      }
      return send(res, 201, { sha256, name: filename, bytes: bytes.length,
                              kind: KIND_OF[ext] || "image" });
    }

    if ((m = p.match(/^\/api\/assets\/([0-9a-f]{64})$/)) && req.method === "DELETE") {
      // The h3ir store is write-only by design; this only forgets the registry row.
      writeRegistry(readRegistry().filter((r) => r.sha256 !== m[1]));
      return send(res, 200, { ok: true });
    }

    if (p === "/api/directors" && req.method === "GET") {
      if (!(await h3irUp())) return send(res, 200, { directors: [] });
      const r = await fetch(`${H3IR}/v1/directors`);
      return send(res, r.status, await r.json());
    }

    if (p === "/api/compile" && req.method === "POST") {
      if (!(await h3irUp()))
        return send(res, 503, { error: "h3ir service is not running — start it first" });
      const body = await readBody(req, 16 * 1024 * 1024);
      const t0 = Date.now();
      // 20 minutes: a local 27B doing video analysis plus a long write can pass 5 minutes
      // easily, and the compiler's own LLM timeout is 600s per call -- the proxy must not
      // give up while the service is still legitimately working.
      const r = await fetch(`${H3IR}/v1/briefs`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body,
        signal: AbortSignal.timeout(1_200_000),
      });
      const text = await r.text();
      let json;
      try { json = JSON.parse(text); } catch { json = { raw: text }; }
      return send(res, r.status, { ...json, _elapsed_ms: Date.now() - t0 });
    }

    send(res, 404, { error: `no route ${req.method} ${p}` });
  } catch (e) {
    send(res, 500, { error: `${e.name}: ${e.message}` });
  }
});

const port = Number(process.env.CONSOLE_API_PORT || 7101);
server.listen(port, "127.0.0.1", () => {
  console.log(`[console-api] listening on 127.0.0.1:${port}, repo ${REPO}`);
});

function shutdown() {
  for (const [name, child] of children) {
    try { process.kill(-child.pid, "SIGTERM"); } catch { }
    children.delete(name);
  }
  process.exit(0);
}
process.on("SIGINT", shutdown);
process.on("SIGTERM", shutdown);
