import { useCallback, useEffect, useState } from "react";
import { api, type AssetRow, type CompileResult, type ServiceStatus } from "./lib/api";
import ServicesPanel from "./sections/ServicesPanel";
import AssetsPanel from "./sections/AssetsPanel";
import ComposePanel from "./sections/ComposePanel";
import ResultPanel from "./sections/ResultPanel";

const FALLBACK_SERVICES: Record<string, ServiceStatus> = {
  worker: { name: "worker", label: "AUDIO WORKER", port: 50000, up: false, managed: false, pid: null, detail: null },
  omni: { name: "omni", label: "OMNI FALLBACK", port: 8001, up: false, managed: false, pid: null, detail: null },
  h3ir: { name: "h3ir", label: "H3IR COMPILER", port: 8420, up: false, managed: false, pid: null, detail: null },
};

export default function App() {
  const [services, setServices] = useState<Record<string, ServiceStatus>>(FALLBACK_SERVICES);
  const [assets, setAssets] = useState<AssetRow[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [result, setResult] = useState<CompileResult | null>(null);
  const [clock, setClock] = useState("");
  const [theme, setTheme] = useState<string>(
    () => localStorage.getItem("h3ir-theme") || "dark",
  );

  useEffect(() => {
    if (theme === "light") document.documentElement.dataset.theme = "light";
    else delete document.documentElement.dataset.theme;
    localStorage.setItem("h3ir-theme", theme);
  }, [theme]);

  const refreshStatus = useCallback(() => {
    api.status()
      .then((r) => r.services && setServices(r.services))
      .catch(() => { });
  }, []);
  const refreshAssets = useCallback(() => {
    api.assets().then((r) => r.assets && setAssets(r.assets)).catch(() => { });
  }, []);

  useEffect(() => {
    refreshStatus();
    refreshAssets();
    const t = setInterval(refreshStatus, 3000);
    const c = setInterval(() => setClock(new Date().toLocaleTimeString("en-GB")), 1000);
    return () => { clearInterval(t); clearInterval(c); };
  }, [refreshStatus, refreshAssets]);

  const toggle = (sha: string) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(sha)) next.delete(sha); else next.add(sha);
      return next;
    });

  const h3irUp = !!services.h3ir?.up;
  const upCount = Object.values(services).filter((s) => s.up).length;

  return (
    <div className="min-h-screen bg-void text-ink">
      <div className="pointer-events-none fixed inset-0 bg-grid opacity-60" />
      <div className="pointer-events-none fixed inset-0 bg-glow" />

      <div className="relative mx-auto flex min-h-screen max-w-[1440px] flex-col gap-3 p-4">
        <header className="flex items-end justify-between border border-line bg-panel px-4 py-3">
          <div>
            <h1 className="text-[15px] font-light tracking-[0.5em] text-ink">
              H3<span className="text-acc">·</span>IR CONSOLE
            </h1>
            <p className="mt-1 font-mono text-[10px] tracking-[0.15em] text-dim">
              CONTEXT-IR COMPILER CONTROL SURFACE — 本地控制台
            </p>
          </div>
          <div className="flex items-center gap-4">
            <button
              onClick={() => setTheme(theme === "light" ? "dark" : "light")}
              className="border border-line px-3 py-1 font-mono text-[10px] tracking-[0.2em] text-dim transition-colors hover:border-acc/50 hover:text-acc"
              title="切换日间/夜间主题"
            >
              {theme === "light" ? "◐ NIGHT" : "◑ DAY"}
            </button>
            <div className="text-right font-mono text-[10px] leading-relaxed text-dim">
              <div>{clock}</div>
              <div className={upCount === 3 ? "text-acc" : "text-warn/80"}>
                {upCount}/3 ONLINE
              </div>
            </div>
          </div>
        </header>

        <main className="grid flex-1 grid-cols-1 gap-3 lg:grid-cols-12">
          <div className="lg:col-span-3"><ServicesPanel services={services} onChanged={refreshStatus} /></div>
          <div className="lg:col-span-4">
            <AssetsPanel assets={assets} selected={selected} onToggle={toggle}
              onChanged={refreshAssets} h3irUp={h3irUp} />
          </div>
          <div className="lg:col-span-5">
            <ComposePanel assets={assets} selected={selected} h3irUp={h3irUp} onResult={setResult} />
          </div>
        </main>

        <ResultPanel result={result} />

        <footer className="flex items-center justify-between px-1 pb-1 font-mono text-[9px] tracking-[0.2em] text-dim/60">
          <span>OPEN-H3-IR · ENHANCED AUDIO BUILD</span>
          <span>WORKER:50000 · OMNI:8001 · COMPILER:8420</span>
        </footer>
      </div>
    </div>
  );
}
