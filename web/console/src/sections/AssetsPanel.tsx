import { useRef, useState } from "react";
import { api, fmtBytes, type AssetRow } from "../lib/api";

const KIND_TAG: Record<string, string> = { image: "IMG", video: "VID", audio: "AUD" };

export default function AssetsPanel({
  assets, selected, onToggle, onChanged, h3irUp,
}: {
  assets: AssetRow[];
  selected: Set<string>;
  onToggle: (sha: string) => void;
  onChanged: () => void;
  h3irUp: boolean;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [drag, setDrag] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  const send = async (files: FileList | null) => {
    if (!files?.length) return;
    setBusy(true); setErr("");
    try {
      for (const f of Array.from(files)) {
        const r = await api.upload(f);
        if ((r as any).error) { setErr((r as any).error); break; }
      }
      onChanged();
    } catch (e: any) {
      setErr(String(e?.message || e));
    } finally {
      setBusy(false);
      if (inputRef.current) inputRef.current.value = "";
    }
  };

  return (
    <section className="flex flex-col border border-line bg-panel">
      <header className="flex items-center justify-between border-b border-line px-4 py-2.5">
        <span className="text-[10px] tracking-[0.3em] text-dim">ASSETS · 资产库</span>
        <span className="font-mono text-[10px] text-dim">{assets.length} 项 · 选中 {selected.size}</span>
      </header>

      <div
        onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
        onDragLeave={() => setDrag(false)}
        onDrop={(e) => { e.preventDefault(); setDrag(false); send(e.dataTransfer.files); }}
        onClick={() => inputRef.current?.click()}
        className={`m-3 cursor-pointer border border-dashed px-4 py-6 text-center transition-colors
          ${drag ? "border-cyan-300 bg-cyan-400/5" : "border-line hover:border-cyan-400/40"}`}
      >
        <div className="text-[11px] tracking-[0.2em] text-ink">{busy ? "上传中…" : "拖入或点击上传"}</div>
        <div className="mt-1 font-mono text-[10px] text-dim">
          {h3irUp ? "图片 / 视频 / 音频 · 按内容哈希入库存" : "需先启动 H3IR COMPILER 服务"}
        </div>
        <input ref={inputRef} type="file" multiple className="hidden"
          accept="image/*,video/*,audio/*"
          onChange={(e) => send(e.target.files)} />
      </div>
      {err && <div className="mx-3 mb-2 border border-red-400/30 bg-red-400/5 px-3 py-2 font-mono text-[10px] text-red-300">{err}</div>}

      <div className="max-h-72 flex-1 divide-y divide-line overflow-auto">
        {assets.length === 0 && (
          <div className="px-4 py-6 text-center font-mono text-[10px] text-dim">EMPTY — 还没有资产</div>
        )}
        {assets.map((a) => {
          const on = selected.has(a.sha256);
          return (
            <div key={a.sha256}
              onClick={() => onToggle(a.sha256)}
              className={`flex cursor-pointer items-center gap-3 px-4 py-2.5 transition-colors
                ${on ? "bg-cyan-400/5" : "hover:bg-white/[0.02]"}`}>
              <span className={`w-9 border px-1 py-0.5 text-center font-mono text-[9px] tracking-widest
                ${on ? "border-cyan-300/60 text-cyan-300" : "border-line text-dim"}`}>
                {KIND_TAG[a.kind] || "IMG"}
              </span>
              <div className="min-w-0 flex-1">
                <div className="truncate text-[11px] text-ink">{a.name}</div>
                <div className="font-mono text-[9px] text-dim">{a.sha256.slice(0, 16)}… · {fmtBytes(a.bytes)}</div>
              </div>
              <button
                onClick={async (e) => { e.stopPropagation(); await api.forget(a.sha256); onChanged(); }}
                className="px-1 font-mono text-[10px] text-dim hover:text-red-300">✕</button>
            </div>
          );
        })}
      </div>

      <footer className="mt-auto border-t border-line px-4 py-2 font-mono text-[10px] text-dim">
        点击行选中参与编译 · ✕ 仅从列表移除
      </footer>
    </section>
  );
}
