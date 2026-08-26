import { useState } from "react";
import { api, type ServiceStatus } from "../lib/api";

function Led({ up, busy }: { up: boolean; busy?: boolean }) {
  const cls = busy
    ? "bg-amber-300 shadow-[0_0_10px_2px_rgba(252,211,77,.45)] animate-pulse"
    : up
      ? "bg-cyan-300 shadow-[0_0_10px_2px_rgba(103,232,249,.5)]"
      : "bg-zinc-700";
  return <span className={`inline-block h-1.5 w-1.5 rounded-full ${cls}`} />;
}

function capsOf(detail: any): string {
  const c = detail?.capabilities;
  if (!c) return "";
  return Object.entries(c).map(([k, v]) => `${k}:${v === "ok" ? "ok" : "—"}`).join("  ");
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
          className="border border-cyan-400/40 px-3 py-1 text-[10px] tracking-[0.2em] text-cyan-300 transition-colors hover:bg-cyan-400/10"
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
              <button onClick={() => toggleLog(s.name)}
                className="px-2 py-1 text-[10px] tracking-[0.15em] text-dim hover:text-ink">LOG</button>
              {s.up ? (
                s.managed ? (
                  <button onClick={() => act(s.name, "stop")}
                    className="border border-line px-3 py-1 text-[10px] tracking-[0.15em] text-red-300/80 hover:bg-red-400/10">停止</button>
                ) : (
                  <span className="px-2 py-1 text-[10px] text-dim">运行中</span>
                )
              ) : (
                <button onClick={() => act(s.name, "start")}
                  className="border border-cyan-400/40 px-3 py-1 text-[10px] tracking-[0.15em] text-cyan-300 hover:bg-cyan-400/10">启动</button>
              )}
            </div>
            {s.up && capsOf(s.detail) && (
              <div className="mt-1.5 font-mono text-[10px] text-cyan-200/50">{capsOf(s.detail)}</div>
            )}
            {logFor === s.name && (
              <pre className="mt-2 max-h-40 overflow-auto border border-line bg-black/40 p-2 font-mono text-[10px] leading-relaxed text-dim">{log}</pre>
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
