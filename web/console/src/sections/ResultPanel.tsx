import { useState } from "react";
import type { CompileResult } from "../lib/api";

type Tab = "prompt" | "plan" | "json";

export default function ResultPanel({ result }: { result: CompileResult | null }) {
  const [tab, setTab] = useState<Tab>("prompt");
  const [copied, setCopied] = useState(false);

  const copy = async (text: string) => {
    try { await navigator.clipboard.writeText(text); setCopied(true); setTimeout(() => setCopied(false), 1500); } catch { }
  };

  const statusChip = (s?: string) => {
    const map: Record<string, string> = {
      ready: "border-cyan-300/50 text-cyan-300",
      degraded: "border-amber-300/50 text-amber-300",
      needs_input: "border-fuchsia-300/50 text-fuchsia-300",
    };
    return (
      <span className={`border px-2 py-0.5 font-mono text-[10px] tracking-[0.2em] ${map[s || ""] || "border-line text-dim"}`}>
        {(s || "—").toUpperCase()}
      </span>
    );
  };

  let body: React.ReactNode = (
    <div className="flex h-full items-center justify-center font-mono text-[11px] text-dim">
      NO OUTPUT — 编译结果会出现在这里
    </div>
  );

  if (result?.error) {
    body = (
      <pre className="whitespace-pre-wrap p-4 font-mono text-[11px] leading-relaxed text-red-300">{result.error}</pre>
    );
  } else if (result) {
    if (tab === "prompt") {
      body = (
        <pre className="whitespace-pre-wrap p-4 font-mono text-[11px] leading-relaxed text-cyan-50/90">
          {result.ir?.prompt || "(no prompt field)"}
        </pre>
      );
    } else if (tab === "plan") {
      body = (
        <pre className="whitespace-pre-wrap p-4 font-mono text-[11px] leading-relaxed text-ink">
          {JSON.stringify(result.plan ?? {}, null, 2)}
        </pre>
      );
    } else {
      body = (
        <pre className="whitespace-pre-wrap p-4 font-mono text-[10px] leading-relaxed text-dim">
          {JSON.stringify(result, null, 2)}
        </pre>
      );
    }
  }

  return (
    <section className="flex min-h-[420px] flex-col border border-line bg-panel">
      <header className="flex flex-wrap items-center gap-3 border-b border-line px-4 py-2.5">
        <span className="text-[10px] tracking-[0.3em] text-dim">OUTPUT · 编译产物</span>
        {result && !result.error && (
          <>
            {statusChip(result.status)}
            {result.ir?.prompt_tokens != null && (
              <span className="font-mono text-[10px] text-dim">{result.ir.prompt_tokens} tok</span>
            )}
            {result._elapsed_ms != null && (
              <span className="font-mono text-[10px] text-dim">{(result._elapsed_ms / 1000).toFixed(1)}s</span>
            )}
            {result.id && <span className="font-mono text-[10px] text-dim">id {result.id}</span>}
          </>
        )}
        <div className="ml-auto flex items-center gap-1">
          {(["prompt", "plan", "json"] as Tab[]).map((t) => (
            <button key={t} onClick={() => setTab(t)}
              className={`px-3 py-1 font-mono text-[10px] tracking-[0.2em] transition-colors
                ${tab === t ? "bg-cyan-400/10 text-cyan-300" : "text-dim hover:text-ink"}`}>
              {t.toUpperCase()}
            </button>
          ))}
          <button
            onClick={() => copy(tab === "prompt" ? result?.ir?.prompt || "" : JSON.stringify(tab === "plan" ? result?.plan : result, null, 2))}
            disabled={!result}
            className="ml-2 border border-line px-3 py-1 font-mono text-[10px] tracking-[0.2em] text-dim hover:text-cyan-300 disabled:opacity-40">
            {copied ? "已复制" : "COPY"}
          </button>
        </div>
      </header>

      {result?.status === "needs_input" && result.question && (
        <div className="border-b border-fuchsia-300/20 bg-fuchsia-400/5 px-4 py-2 font-mono text-[11px] text-fuchsia-200">
          编译器提问：{(result.question as any).text || JSON.stringify(result.question)}
        </div>
      )}

      <div className="min-h-0 flex-1 overflow-auto">{body}</div>

      {result?.ir?.diagnostics?.length ? (
        <footer className="max-h-28 overflow-auto border-t border-line px-4 py-2">
          {result.ir.diagnostics.map((d: any, i: number) => (
            <div key={i} className="font-mono text-[10px] leading-relaxed text-amber-200/70">
              [{d.severity}] {d.rule} — {d.message}
            </div>
          ))}
        </footer>
      ) : null}
    </section>
  );
}
