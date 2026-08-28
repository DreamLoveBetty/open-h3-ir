// H3·IR Console control API — zero-dependency node:http server.
//
// Owns three things the browser cannot do:
//   1. start/stop the three local services (audio worker, omni fallback, h3ir serve)
//   2. receive asset bytes, hash them, and PUT them to the h3ir content-addressed store
//   3. proxy POST /v1/briefs so the page never talks cross-origin
//
// Every service child is spawned in its own process group with output appended to
// logs/<name>.log; stopping sends SIGTERM to the group. Services already running
// (started outside this console) are reported as {up, managed:false}; stopping one of
// those kills the port listener only when its command line provably belongs to this
// repo, so a foreign process holding the port is left alone.
import { createServer } from "node:http";
import { spawn, execSync } from "node:child_process";
import { createHash } from "node:crypto";
import { createReadStream, createWriteStream } from "node:fs";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { request as httpRequest } from "node:http";

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
    signatures: ["audio_worker"],
    cwd: path.join(REPO, "services"),
    cmd: [path.join(REPO, "services", ".venv-audio", "bin", "python"), "-m", "audio_worker.app"],
    env: { ...MODEL_ENV },
  },
  omni: {
    label: "OMNI FALLBACK",
    port: 8001,
    signatures: ["llama-server"],
    cwd: REPO,
    // Qwen2.5-Omni-3B Q8_0 through llama-server instead of the transformers shim: the same
    // OpenAI chat shape with input_audio at ~8GB resident (mmap'd, largely reclaimable)
    // instead of ~12GB fp32. -ngl 0 pins it to CPU so it never competes with LM Studio
    // for the GPU pool. The Python shim in services/omni_fallback/ stays as the portable
    // alternative for machines without llama.cpp.
    cmd: ["llama-server",
          "-m", path.join(REPO, "models", "gguf", "Qwen2.5-Omni-3B", "Qwen2.5-Omni-3B-Q8_0.gguf"),
          "--mmproj", path.join(REPO, "models", "gguf", "Qwen2.5-Omni-3B", "mmproj-Qwen2.5-Omni-3B-Q8_0.gguf"),
          "--host", "127.0.0.1", "--port", "8001",
          "-ngl", "0", "-c", "8192"],
    env: { ...MODEL_ENV, PATH: `/opt/homebrew/bin:${process.env.PATH || ""}` },
  },
  h3ir: {
    label: "H3IR COMPILER",
    port: 8420,
    signatures: ["h3ir.cli"],
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
function healthUrl(svc) { return `http://127.0.0.1:${svc.port}/health`; }

async function probe(name) {
  const svc = SERVICES[name];
  const child = children.get(name);
  const managedAlive = !!child && child.exitCode === null && !child.killed;
  // h3ir's /health runs the LLM liveness check, which re-fetches the endpoint's model list
  // on every call. The console polls status every 3s, and the owner asked for NO timed
  // probing of the LLM endpoint at all -- detection is the CFG panel's manual button only.
  // So h3ir liveness reads the static /v1/contract and its detail block stays empty.
  const livenessUrl = name === "h3ir"
    ? `http://127.0.0.1:${svc.port}/v1/contract` : healthUrl(svc);
  try {
    const ctrl = new AbortController();
    const t = setTimeout(() => ctrl.abort(), 4000);
    const r = await fetch(livenessUrl, { signal: ctrl.signal });
    clearTimeout(t);
    let detail = null;
    if (name !== "h3ir") {
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
  if (child && child.exitCode === null) {
    try { process.kill(-child.pid, "SIGTERM"); } catch { try { child.kill("SIGTERM"); } catch { } }
    children.delete(name);
    return { stopped: true };
  }
  // Not managed here: a service started outside the console still answers on its port,
  // and leaving it running leaks whatever it holds in memory (the omni llama-server
  // keeps ~8GB of model weights resident). Take it down only when the port listener's
  // command line provably belongs to this project.
  return stopForeignListener(SERVICES[name]);
}

function stopForeignListener(svc) {
  let pids;
  try {
    pids = execSync(`lsof -tiTCP:${svc.port} -sTCP:LISTEN`, { encoding: "utf8" })
      .trim().split("\n").filter(Boolean).map(Number);
  } catch { return { stopped: false, reason: "not running" }; }
  const ours = [];
  for (const pid of pids) {
    let cmdline = "";
    try { cmdline = execSync(`ps -p ${pid} -o command=`, { encoding: "utf8" }); } catch { continue; }
    // An absolute path containing the repo, or the service's own module/binary signature —
    // a launch from inside the repo shows up as `.venv/bin/python -m h3ir.cli`, with no
    // absolute path in it at all.
    if (cmdline.includes(REPO) || svc.signatures.some((s) => cmdline.includes(s))) ours.push(pid);
  }
  if (!ours.length) return { stopped: false, reason: `port ${svc.port} held by a foreign process, left alone` };
  for (const pid of ours) { try { process.kill(pid, "SIGTERM"); } catch { } }
  return { stopped: true, killed: ours };
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

// Long-timeout POST for the compile proxy. Global fetch (undici) enforces a default
// 300s headersTimeout no matter what AbortSignal you pass, and a local 27B compile
// legitimately runs past that; node:http has no such hidden ceiling.
function postWithTimeout(url, body, timeoutMs) {
  return new Promise((resolve, reject) => {
    const u = new URL(url);
    const req = httpRequest(
      {
        hostname: u.hostname,
        port: u.port,
        path: u.pathname + u.search,
        method: "POST",
        headers: { "content-type": "application/json", "content-length": Buffer.byteLength(body) },
        timeout: timeoutMs,
      },
      (res) => {
        const chunks = [];
        res.on("data", (c) => chunks.push(c));
        res.on("end", () => resolve({ status: res.statusCode, text: Buffer.concat(chunks).toString("utf8") }));
        res.on("error", reject);
      },
    );
    req.on("timeout", () => { req.destroy(new Error("upstream timeout")); });
    req.on("error", reject);
    req.end(body);
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

// ------------------------------------------------------- output translation
// Display-only Chinese rendering of the compiled IR, for the ResultPanel's EN/中 toggle.
// The translation is never fed back anywhere: COPY and every downstream consumer keep the
// canonical English document. Cached by content hash so toggling costs nothing the second
// time, and keyed on text rather than result id because the same IR can come back from a
// re-run.
const zhCache = new Map(); // sha256(text) -> zh string

async function translateToZh(text) {
  const s = readSettings();
  if (!s.llm_url || !s.llm_model) throw new Error("no LLM endpoint configured in CFG");
  const headers = { "content-type": "application/json" };
  if (s.llm_key) headers.authorization = `Bearer ${s.llm_key}`;
  const r = await fetch(s.llm_url.replace(/\/+$/, "") + "/chat/completions", {
    method: "POST",
    headers,
    signal: AbortSignal.timeout(180_000),
    body: JSON.stringify({
      model: s.llm_model,
      messages: [
        { role: "system", content: "Translate the user's video-generation IR document into Simplified Chinese, for reading only. Preserve EXACTLY as-is: every structural label and section name, every tag such as <Subject 1>, <Picture 1>, <Video 1>, <0.5 seconds>, every shot label like [Shot 1], and every timecode. Output the translation only, no commentary." },
        { role: "user", content: text },
      ],
      temperature: 0.1,
    }),
  });
  if (!r.ok) throw new Error(`translator endpoint said HTTP ${r.status}`);
  const body = await r.json();
  const zh = body?.choices?.[0]?.message?.content;
  if (!zh) throw new Error("translator returned no content");
  return zh;
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

    // Probe the well-known local LLM servers (plus any URL the caller is typing, local or
    // remote) for their /v1/models list, so the CFG panel can offer click-to-fill instead of
    // hand-typed ids. Gateways that serve a web UI at /models are distinguished from the real
    // API by whether the body parses as a model list. A server that publishes no model list is
    // reported without one; which model has a vision tower is never guessed from metadata
    // (repo rule) — that is what doctor is for.
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
        const headers = key ? { authorization: `Bearer ${key}` } : {};
        // Loopback answers in milliseconds or not at all; a remote endpoint across a LAN
        // or the internet needs real patience, especially through TLS.
        const host = new URL(base).hostname;
        const local = ["127.0.0.1", "localhost", "::1", "[::1]"].includes(host);
        const timeoutMs = local ? 1500 : 8000;
        // Gateways (New API / One API and friends) serve a WEB PAGE at /models and the real
        // API at /v1/models, so a bare host:port has to try both -- and a 200 that does not
        // parse as a model list is the web UI, not an answer.
        const stem = base.replace(/\/+$/, "");
        const paths = /\/v\d+\w*$/.test(stem) ? ["/models"] : ["/v1/models", "/models"];
        for (const suffix of paths) {
          const apiRoot = stem + suffix.replace(/\/models$/, "");
          try {
            const r = await fetch(stem + suffix, { headers, signal: AbortSignal.timeout(timeoutMs) });
            if (r.status === 401 || r.status === 403)
              return { source, url: apiRoot || stem, models: [], needsAuth: true };
            if (!r.ok) continue;
            const body = await r.json().catch(() => null);
            if (!body || !Array.isArray(body.data)) continue; // web UI page, not the API
            const models = body.data.map((m) => m?.id).filter(Boolean);
            return { source, url: apiRoot || stem, models };
          } catch { /* try the next path */ }
        }
        return null;
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
      // give up while the service is still legitimately working. This goes through
      // node:http directly because the global fetch (undici) has a default
      // headersTimeout of 300s that fires before any signal we can pass it.
      const r = await postWithTimeout(`${H3IR}/v1/briefs`, body, 1_200_000);
      let json;
      try { json = JSON.parse(r.text); } catch { json = { raw: r.text }; }
      return send(res, r.status, { ...json, _elapsed_ms: Date.now() - t0 });
    }

    if (p === "/api/translate-zh" && req.method === "POST") {
      const { text } = JSON.parse((await readBody(req, 4 * 1024 * 1024)).toString() || "{}");
      if (!text) return send(res, 400, { error: "nothing to translate" });
      const key = createHash("sha256").update(text).digest("hex");
      if (zhCache.has(key)) return send(res, 200, { zh: zhCache.get(key), cached: true });
      try {
        const zh = await translateToZh(text);
        zhCache.set(key, zh);
        return send(res, 200, { zh });
      } catch (e) {
        return send(res, 502, { error: `translation failed: ${e.message}` });
      }
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
