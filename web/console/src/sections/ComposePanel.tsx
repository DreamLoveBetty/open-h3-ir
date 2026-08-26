import { useEffect, useState } from "react";
import { api, type AssetRow, type CompileResult } from "../lib/api";

const CREATIVITY = ["restrained", "balanced", "bold", "extreme"] as const;
const ASPECTS = ["16:9", "9:16", "1:1"] as const;

export default function ComposePanel({
  assets, selected, h3irUp, onResult,
}: {
  assets: AssetRow[];
  selected: Set<string>;
  h3irUp: boolean;
  onResult: (r: CompileResult) => void;
}) {
  const [intent, setIntent] = useState("");
  const [seconds, setSeconds] = useState(5);
  const [aspect, setAspect] = useState<string>("16:9");
  const [creativity, setCreativity] = useState<string>("balanced");
  const [director, setDirector] = useState("");
  const [directors, setDirectors] = useState<any[]>([]);
  const [silent, setSilent] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!h3irUp) return;
    api.directors().then((r) => {
      const d = (r as any).directors;
      if (Array.isArray(d)) setDirectors(d);
    }).catch(() => { });
  }, [h3irUp]);

  const compile = async () => {
    if (!intent.trim() || busy) return;
    setBusy(true);
    try {
      const chosen = assets.filter((a) => selected.has(a.sha256));
      const r = await api.compile({
        intent: intent.trim(),
        seconds,
        aspect,
        creativity,
        silent,
        ...(director ? { director } : {}),
        assets: chosen.map((a) => ({ sha256: a.sha256, kind: a.kind, ...(a.note ? { note: a.note } : {}) })),
      });
      onResult(r);
    } catch (e: any) {
      onResult({ error: String(e?.message || e) });
    } finally {
      setBusy(false);
    }
  };

  const field = "w-full border border-line bg-well/40 px-3 py-2 text-[12px] text-ink outline-none placeholder:text-dim/60 focus:border-acc/50";

  return (
    <section className="flex flex-col border border-line bg-panel">
      <header className="flex items-center justify-between border-b border-line px-4 py-2.5">
        <span className="text-[10px] tracking-[0.3em] text-dim">COMPOSE · 编译请求</span>
        <span className="font-mono text-[10px] text-dim">{selected.size} 个资产已挂载</span>
      </header>

      <div className="flex flex-1 flex-col gap-3 p-4">
        <textarea
          value={intent}
          onChange={(e) => setIntent(e.target.value)}
          rows={5}
          placeholder="描述你要的视频 — intent, e.g. a drummer plays a solo as the crowd roars"
          className={`${field} resize-none font-mono leading-relaxed`}
        />

        <div className="grid grid-cols-2 gap-3">
          <label className="block">
            <span className="mb-1 block text-[9px] tracking-[0.25em] text-dim">时长 · {seconds}s</span>
            <input type="range" min={1} max={12} step={0.5} value={seconds}
              onChange={(e) => setSeconds(Number(e.target.value))}
              className="w-full accent-acc" />
          </label>
          <label className="block">
            <span className="mb-1 block text-[9px] tracking-[0.25em] text-dim">画幅</span>
            <select value={aspect} onChange={(e) => setAspect(e.target.value)} className={field}>
              {ASPECTS.map((a) => <option key={a} value={a}>{a}</option>)}
            </select>
          </label>
          <label className="block">
            <span className="mb-1 block text-[9px] tracking-[0.25em] text-dim">创造力 · CREATIVITY</span>
            <select value={creativity} onChange={(e) => setCreativity(e.target.value)} className={field}>
              {CREATIVITY.map((c) => <option key={c} value={c}>{c}</option>)}
            </select>
          </label>
          <label className="block">
            <span className="mb-1 block text-[9px] tracking-[0.25em] text-dim">导演 · DIRECTOR</span>
            <select value={director} onChange={(e) => setDirector(e.target.value)} className={field}>
              <option value="">（无 — nobody's taste）</option>
              {directors.map((d) => (
                <option key={d.id || d.name} value={d.id || d.name}>{d.id || d.name}</option>
              ))}
            </select>
          </label>
        </div>

        <label className="flex cursor-pointer items-center gap-2 text-[11px] text-dim">
          <input type="checkbox" checked={silent} onChange={(e) => setSilent(e.target.checked)}
            className="accent-acc" />
          静音片（不写音乐与音效）
        </label>

        <button
          onClick={compile}
          disabled={busy || !h3irUp || !intent.trim()}
          className={`mt-auto border px-4 py-3 text-[11px] tracking-[0.35em] transition-colors
            ${busy || !h3irUp || !intent.trim()
              ? "cursor-not-allowed border-line text-dim"
              : "border-acc/60 text-acc hover:bg-acc/10 hover:shadow-[0_0_24px_rgba(103,232,249,0.15)]"}`}
        >
          {busy ? "COMPILING…" : h3irUp ? "编 译 ⟶" : "等待 H3IR 服务"}
        </button>
      </div>
    </section>
  );
}
