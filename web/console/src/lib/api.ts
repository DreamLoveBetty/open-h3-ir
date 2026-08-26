// Thin client for the console control API (same origin, vite proxies /api).

export interface ServiceStatus {
  name: string;
  label: string;
  port: number;
  up: boolean;
  managed: boolean;
  pid: number | null;
  detail: any;
}

export interface AssetRow {
  sha256: string;
  name: string;
  bytes: number;
  kind: "image" | "video" | "audio";
  at: string;
  note?: string;
}

export interface CompileResult {
  id?: string;
  status?: "ready" | "degraded" | "needs_input";
  question?: { text?: string } | null;
  plan?: any;
  ir?: { prompt?: string; prompt_tokens?: number; diagnostics?: any[]; provenance?: any };
  presentation?: any;
  detail?: any;
  error?: string;
  _elapsed_ms?: number;
  [k: string]: any;
}

async function j<T>(r: Response): Promise<T> {
  const text = await r.text();
  let body: any;
  try { body = JSON.parse(text); } catch { body = { raw: text }; }
  if (!r.ok && !body.error) body.error = body?.detail ? JSON.stringify(body.detail) : `HTTP ${r.status}`;
  return body as T;
}

export const api = {
  status: () => fetch("/api/status").then((r) => j<{ services: Record<string, ServiceStatus> }>(r)),
  start: (name: string) => fetch(`/api/services/${name}/start`, { method: "POST" }).then(j),
  stop: (name: string) => fetch(`/api/services/${name}/stop`, { method: "POST" }).then(j),
  startAll: () => fetch("/api/services/start-all", { method: "POST" }).then(j),
  stopAll: () => fetch("/api/services/stop-all", { method: "POST" }).then(j),
  logs: (name: string) => fetch(`/api/logs/${name}`).then((r) => j<{ log: string }>(r)),

  assets: () => fetch("/api/assets").then((r) => j<{ assets: AssetRow[] }>(r)),
  upload: (file: File) =>
    fetch("/api/assets", {
      method: "POST",
      headers: { "x-filename": encodeURIComponent(file.name) },
      body: file,
    }).then((r) => j<AssetRow & { error?: string }>(r)),
  forget: (sha256: string) => fetch(`/api/assets/${sha256}`, { method: "DELETE" }).then(j),

  directors: () => fetch("/api/directors").then((r) => j<{ directors: any[] }>(r)),
  compile: (body: any) =>
    fetch("/api/compile", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    }).then((r) => j<CompileResult>(r)),
};

export function fmtBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}
