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

  // The failure mode this guards is real: an intent that says "参考视频…" with no video
  // mounted compiles fine and comes back unrelated, because the compiler can only use the
  // assets it is handed. Mention-but-not-mounted gets a hint before the request leaves.
  const mounted = assets.filter((a) => selected.has(a.sha256));
  const KIND_WORDS: [AssetRow["kind"], RegExp, string][] = [
    ["video", /视频|video|clip|画面中的|参考.*中/i, "视频"],
    ["image", /图片|图像|照片|image|picture|photo|图中/i, "图片"],
    ["audio", /音频|音乐|声音|audio|music|sound|配乐/i, "音频"],
  ];
  const missingKinds = KIND_WORDS.filter(
    ([kind, re]) => re.test(intent) && !mounted.some((a) => a.kind === kind),
  );

  const field = "w-full border border-line bg-well/40 px-3 py-2 text-[12px] text-ink outline-none placeholder:text-dim/60 focus:border-acc/50";

  return (
    <section className="flex flex-col border border-line bg-panel">
      <header className="flex items-center justify-between border-b border-line px-4 py-2.5">
        <span className="text-[10px] tracking-[0.3em] text-dim">COMPOSE · 编译请求</span>
        <span className="font-mono text-[10px] text-dim">{selected.size} 个资产已挂载</span>
      </header>

      <div className="flex flex-1 flex-col gap-3 p-4">
        {/* mounted assets, named — the count alone once let a brief compile with half its inputs */}
        <div className="flex flex-wrap items-center gap-1.5">
          {mounted.length === 0 && (
            <span className="font-mono text-[10px] text-dim">未挂载资产 — 纯文本编译</span>
          )}
          {mounted.map((a) => (
            <span key={a.sha256}
              className="border border-acc/40 bg-acc/5 px-2 py-0.5 font-mono text-[10px] text-acc">
              {a.kind.toUpperCase()} · {a.name}
            </span>
          ))}
        </div>
        {missingKinds.length > 0 && (
          <div className="border border-warn/40 bg-warn/5 px-3 py-2 font-mono text-[10px] leading-relaxed text-warn">
            意图提到了{missingKinds.map(([, , label]) => label).join("、")}，但没有挂载对应资产
            —— 到左侧资产库点击选中，否则编译器看不到它。
          </div>
        )}
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
