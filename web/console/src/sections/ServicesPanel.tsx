import { useEffect, useState } from "react";
import { api, type ServiceStatus } from "../lib/api";

function Led({ up, busy }: { up: boolean; busy?: boolean }) {
  const cls = busy
    ? "bg-warn shadow-[0_0_10px_2px_rgba(252,211,77,.45)] animate-pulse"
    : up
      ? "bg-acc shadow-[0_0_10px_2px_rgba(103,232,249,.5)]"
      : "bg-zinc-700";
  return <span className={`inline-block h-1.5 w-1.5 rounded-full ${cls}`} />;
}

function capsOf(detail: any): string {
  const c = detail?.capabilities;
  if (!c) return "";
  return Object.entries(c).map(([k, v]) => `${k}:${v === "ok" ? "ok" : "—"}`).join("  ");
}

/** What the running h3ir service says about its reasoning model, when it is up. */
function llmLine(detail: any): string {
  const l = detail?.llm;
  if (!l || typeof l !== "object") return "";
  const bits = [l.model || l.model_id, l.health_via, l.vision_ok === true ? "vision ok" : null]
    .filter(Boolean);
  return bits.join(" · ");
}

function LlmConfig({ h3ir, onChanged }: { h3ir: ServiceStatus; onChanged: () => void }) {
  const [url, setUrl] = useState("");
  const [model, setModel] = useState("");
  const [key, setKey] = useState("");
  const [keySet, setKeySet] = useState(false);
  const [msg, setMsg] = useState("");
  const [probing, setProbing] = useState(false);
  const [found, setFound] = useState<{ source: string; url: string; models: string[] }[] | null>(null);

  useEffect(() => {
    api.settings().then((s) => {
      setUrl(s.llm_url); setModel(s.llm_model); setKeySet(!!s.llm_key_set);
    }).catch(() => { });
  }, []);

  const detect = async () => {
    setProbing(true);
    try {
      const r = await api.detectLlm(url.trim() || undefined);
      setFound(r.endpoints || []);
      // one endpoint serving one model is an unambiguous answer; fill it directly
      if (r.endpoints?.length === 1 && r.endpoints[0].models.length === 1) {
        setUrl(r.endpoints[0].url);
        setModel(r.endpoints[0].models[0]);
      }
    } catch { setFound([]); }
    finally { setProbing(false); }
  };

  const save = async () => {
    const r = await api.saveSettings({
      llm_url: url, llm_model: model,
      ...(key ? { llm_key: key } : {}),
    });
    setKey("");
    setMsg(r.restart_needed ? "已保存 — 重启 H3IR 服务后生效" : "已保存，下次启动生效");
    setTimeout(() => setMsg(""), 5000);
  };

  const restart = async () => {
    await api.stop("h3ir");
    await new Promise((r) => setTimeout(r, 800));
    await api.start("h3ir");
    setMsg("重启中…");
    setTimeout(() => { setMsg(""); onChanged(); }, 6000);
  };

  const field = "w-full border border-line bg-well/40 px-2 py-1.5 font-mono text-[11px] text-ink outline-none placeholder:text-dim/50 focus:border-acc/50";

  return (
    <div className="mt-2 space-y-2 border border-line bg-well/30 p-3">
      <div className="text-[9px] tracking-[0.25em] text-dim">LLM ENDPOINT · 推理模型端点</div>
      <button onClick={detect} disabled={probing}
        className="w-full border border-acc/40 px-2 py-1.5 text-[10px] tracking-[0.2em] text-acc transition-colors hover:bg-acc/10 disabled:opacity-50">
        {probing ? "探测中…" : "⟳ 自动探测本地端点（LM Studio / Ollama / vLLM）"}
      </button>
      {found !== null && (
        <div className="space-y-1 border border-line/60 p-2">
          {found.length === 0 && (
            <div className="font-mono text-[10px] text-warn">
              未发现本地端点 — 确认 LM Studio 已启动并在 Developer 页 serve 了模型
            </div>
          )}
          {found.map((e) => (
            <div key={e.url}>
              <div className="font-mono text-[10px] text-dim">{e.source} · {e.url}</div>
              <div className="mt-0.5 flex flex-wrap gap-1">
                {e.models.map((m) => (
                  <button key={m}
                    onClick={() => { setUrl(e.url); setModel(m); }}
                    className={`border px-2 py-0.5 font-mono text-[10px] transition-colors
                      ${model === m && url === e.url
                        ? "border-acc/60 bg-acc/10 text-acc"
                        : "border-line text-dim hover:border-acc/40 hover:text-acc"}`}>
                    {m}
                  </button>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
      <input value={url} onChange={(e) => setUrl(e.target.value)}
        placeholder="http://127.0.0.1:1234/v1  (LM Studio 默认)" className={field} />
      <input value={model} onChange={(e) => setModel(e.target.value)}
        placeholder="模型 id（单模型端点可留空）" className={field} />
      <input value={key} onChange={(e) => setKey(e.target.value)} type="password"
        placeholder={keySet ? "API Key 已设置（输入以更换）" : "API Key（可选）"} className={field} />
      <div className="flex items-center gap-2">
        <button onClick={save}
          className="border border-acc/40 px-3 py-1 text-[10px] tracking-[0.15em] text-acc hover:bg-acc/10">
          保存
        </button>
        {h3ir.up && h3ir.managed && (
          <button onClick={restart}
            className="border border-warn/40 px-3 py-1 text-[10px] tracking-[0.15em] text-warn hover:bg-warn/10">
            保存并重启
          </button>
        )}
        {msg && <span className="font-mono text-[10px] text-warn/80">{msg}</span>}
      </div>
      <div className="font-mono text-[9px] leading-relaxed text-dim/70">
        需要带视觉塔的 27B 级本地模型；纯文本 brief 无视觉也能编译。
        改完用 h3ir doctor 验证连通性。
      </div>
    </div>
  );
}

export default function ServicesPanel({
  services,
  onChanged,
}: {
  services: Record<string, ServiceStatus>;
  onChanged: () => void;
}) {
  const [busy, setBusy] = useState<string>("");
  const [logFor, setLogFor] = useState<string>("");
  const [log, setLog] = useState<string>("");
  const [cfgOpen, setCfgOpen] = useState(false);

  const act = async (name: string, action: "start" | "stop") => {
    setBusy(name);
    try {
      if (action === "start") await api.start(name); else await api.stop(name);
    } finally {
      // model load takes seconds; poll a few times so the LED reflects reality
      setTimeout(onChanged, 1200);
      setTimeout(onChanged, 4000);
      setTimeout(() => { setBusy(""); onChanged(); }, 9000);
    }
  };

  const toggleLog = async (name: string) => {
    if (logFor === name) { setLogFor(""); return; }
    const r = await api.logs(name);
    setLog(r.log || "(no log yet)");
    setLogFor(name);
  };

  const allUp = Object.values(services).every((s) => s.up);

  return (
    <section className="flex flex-col border border-line bg-panel">
      <header className="flex items-center justify-between border-b border-line px-4 py-2.5">
        <span className="text-[10px] tracking-[0.3em] text-dim">SERVICES · 服务矩阵</span>
        <button
          onClick={async () => { setBusy("*"); await api.startAll(); setTimeout(onChanged, 1500); setTimeout(() => { setBusy(""); onChanged(); }, 9000); }}
          className="border border-acc/40 px-3 py-1 text-[10px] tracking-[0.2em] text-acc transition-colors hover:bg-acc/10"
        >
          全部启动
        </button>
      </header>

      <div className="divide-y divide-line">
        {Object.values(services).map((s) => (
          <div key={s.name} className="px-4 py-3">
            <div className="flex items-center gap-3">
              <Led up={s.up} busy={busy === s.name || busy === "*"} />
              <div className="min-w-0 flex-1">
                <div className="text-[11px] tracking-[0.18em] text-ink">{s.label}</div>
                <div className="mt-0.5 font-mono text-[10px] text-dim">
                  127.0.0.1:{s.port}
                  {s.up && s.pid ? ` · pid ${s.pid}` : ""}
                  {s.up && !s.managed ? " · external" : ""}
                </div>
              </div>
              {s.name === "h3ir" && (
                <button onClick={() => setCfgOpen(!cfgOpen)}
                  className={`px-2 py-1 text-[10px] tracking-[0.15em] transition-colors ${cfgOpen ? "text-acc" : "text-dim hover:text-ink"}`}>
                  CFG
                </button>
              )}
              <button onClick={() => toggleLog(s.name)}
                className="px-2 py-1 text-[10px] tracking-[0.15em] text-dim hover:text-ink">LOG</button>
              {s.up ? (
                s.managed ? (
                  <button onClick={() => act(s.name, "stop")}
                    className="border border-line px-3 py-1 text-[10px] tracking-[0.15em] text-err hover:bg-err/10">停止</button>
                ) : (
                  <span className="px-2 py-1 text-[10px] text-dim">运行中</span>
                )
              ) : (
                <button onClick={() => act(s.name, "start")}
                  className="border border-acc/40 px-3 py-1 text-[10px] tracking-[0.15em] text-acc hover:bg-acc/10">启动</button>
              )}
            </div>
            {s.up && capsOf(s.detail) && (
              <div className="mt-1.5 font-mono text-[10px] text-acc/50">{capsOf(s.detail)}</div>
            )}
            {s.name === "h3ir" && s.up && llmLine(s.detail) && (
              <div className="mt-1.5 font-mono text-[10px] text-acc/50">{llmLine(s.detail)}</div>
            )}
            {s.name === "h3ir" && cfgOpen && <LlmConfig h3ir={s} onChanged={onChanged} />}
            {logFor === s.name && (
              <pre className="mt-2 max-h-40 overflow-auto border border-line bg-well/40 p-2 font-mono text-[10px] leading-relaxed text-dim">{log}</pre>
            )}
          </div>
        ))}
      </div>

      <footer className="mt-auto border-t border-line px-4 py-2 font-mono text-[10px] text-dim">
        {allUp ? "ALL SYSTEMS NOMINAL" : "SOME SYSTEMS OFFLINE"}
      </footer>
    </section>
  );
}
