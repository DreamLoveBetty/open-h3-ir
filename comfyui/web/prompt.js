/* OpenH3-IR Main: the @ picker on the prompt.
 *
 * Sugar only. The prompt is plain text carrying @label and @speaks("...") and works untouched with
 * this file absent; what this adds is the popup that makes the labels findable: type @ and the
 * tray's slots appear, filtered as you type, Enter or click to insert. The first entry is always
 * the spoken-line form, so @speaks is discoverable in the same motion.
 *
 * Editor state idioms follow ComfyUI-MiniMaxH3-Easy's ui (MIT), credited in README.md.
 */
import { app } from "../../scripts/app.js";

const NODE = "OpenH3IRCompile";

function trayOf(node) {
  // The media input's origin node, walked live so the popup always shows the tray as it is now.
  try {
    const input = (node.inputs || []).find((i) => i.name === "media");
    if (!input || input.link == null) return null;
    const link = node.graph.links[input.link];
    const origin = node.graph.getNodeById(link.origin_id);
    const state = (origin?.widgets || []).find((w) => w.name === "tray");
    const slots = JSON.parse(state?.value || "[]");
    return Array.isArray(slots) ? slots : null;
  } catch {
    return null;
  }
}

function viewUrl(annotated) {
  const name = annotated.replace(/ \[(input|output|temp)\]$/, "");
  const i = name.lastIndexOf("/");
  const params = new URLSearchParams({
    filename: i < 0 ? name : name.slice(i + 1),
    subfolder: i < 0 ? "" : name.slice(0, i),
    type: "input",
  });
  return "/api/view?" + params;
}

class Picker {
  constructor(textarea, node) {
    this.ta = textarea;
    this.node = node;
    this.box = document.createElement("div");
    this.box.className = "oh3-pick";
    this.box.style.display = "none";
    document.body.append(this.box);
    this.at = -1;
    this.items = [];
    this.sel = 0;
    textarea.addEventListener("input", () => this.consider());
    textarea.addEventListener("keydown", (e) => this.keys(e));
    textarea.addEventListener("blur", () => setTimeout(() => this.hide(), 150));
  }

  consider() {
    const pos = this.ta.selectionStart;
    const text = this.ta.value.slice(0, pos);
    const at = text.lastIndexOf("@");
    if (at < 0 || /\s/.test(text.slice(at + 1))) return this.hide();
    const typed = text.slice(at + 1).toLowerCase();
    const slots = trayOf(this.node) || [];
    this.items = [{ label: 'speaks("…")', insert: 'speaks("")', kind: "say" }];
    for (const s of slots) {
      if (!typed || s.label.toLowerCase().startsWith(typed))
        this.items.push({ label: s.label, insert: s.label, kind: s.kind, file: s.file,
                          note: s.note || "" });
    }
    if (typed && !"speaks".startsWith(typed)) this.items = this.items.slice(1);
    if (!this.items.length) return this.hide();
    this.at = at;
    this.sel = 0;
    this.show();
  }

  show() {
    this.box.replaceChildren(...this.items.map((it, i) => {
      const row = document.createElement("div");
      row.className = "oh3-pickrow" + (i === this.sel ? " oh3-picksel" : "");
      if (it.kind === "picture" || it.kind === "video") {
        const img = document.createElement(it.kind === "picture" ? "img" : "video");
        img.src = viewUrl(it.file);
        img.className = "oh3-pickthumb";
        row.append(img);
      } else {
        const dot = document.createElement("span");
        dot.className = "oh3-pickdot";
        dot.textContent = it.kind === "say" ? "❝" : "♪";
        row.append(dot);
      }
      const name = document.createElement("span");
      name.textContent = "@" + it.label + (it.note ? `  —  ${it.note}` : "");
      row.append(name);
      row.addEventListener("mousedown", (e) => { e.preventDefault(); this.take(i); });
      return row;
    }));
    const r = this.ta.getBoundingClientRect();
    this.box.style.left = `${r.left}px`;
    this.box.style.top = `${r.bottom + 2}px`;
    this.box.style.minWidth = `${Math.max(180, r.width * 0.6)}px`;
    this.box.style.display = "block";
  }

  hide() {
    this.box.style.display = "none";
    this.at = -1;
  }

  keys(e) {
    if (this.box.style.display === "none") return;
    if (e.key === "ArrowDown") { this.sel = (this.sel + 1) % this.items.length; this.show(); e.preventDefault(); }
    else if (e.key === "ArrowUp") { this.sel = (this.sel + this.items.length - 1) % this.items.length; this.show(); e.preventDefault(); }
    else if (e.key === "Enter" || e.key === "Tab") { this.take(this.sel); e.preventDefault(); }
    else if (e.key === "Escape") this.hide();
  }

  take(i) {
    const it = this.items[i];
    if (!it) return this.hide();
    const pos = this.ta.selectionStart;
    const before = this.ta.value.slice(0, this.at + 1);
    const after = this.ta.value.slice(pos);
    this.ta.value = before + it.insert + after;
    const cursor = it.kind === "say"
      ? before.length + it.insert.length - 2   // inside the empty quotes
      : before.length + it.insert.length;
    this.ta.setSelectionRange(cursor, cursor);
    this.ta.dispatchEvent(new Event("input", { bubbles: true }));
    if (it.kind !== "say") this.hide();
    this.ta.focus();
  }
}

const CSS = `
.oh3-pick{position:fixed;z-index:10000;background:#14161c;border:1px solid #2e3440;border-radius:6px;
  padding:3px;font-family:system-ui,sans-serif;font-size:12px;color:#dde2ea;max-height:240px;
  overflow-y:auto;box-shadow:0 12px 32px rgba(0,0,0,.5);}
.oh3-pickrow{display:flex;align-items:center;gap:7px;padding:4px 7px;border-radius:4px;cursor:pointer;}
.oh3-pickrow:hover,.oh3-picksel{background:#232735;}
.oh3-pickthumb{width:28px;height:20px;object-fit:cover;border-radius:3px;flex:0 0 auto;}
.oh3-pickdot{width:28px;text-align:center;color:#e8873a;flex:0 0 auto;}
`;

app.registerExtension({
  name: "openh3ir.prompt",
  init() {
    const style = document.createElement("style");
    style.textContent = CSS;
    document.head.append(style);
  },
  beforeRegisterNodeDef(nodeType, nodeData) {
    if (nodeData?.name !== NODE) return;
    const onCreated = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function () {
      const r = onCreated?.apply(this, arguments);
      // The multiline widget's element appears after creation; attach when it exists.
      requestAnimationFrame(() => {
        const w = (this.widgets || []).find((x) => x.name === "intent");
        const ta = w?.inputEl || w?.element?.querySelector?.("textarea");
        if (ta && !ta._oh3Picker) ta._oh3Picker = new Picker(ta, this);
      });
      return r;
    };
  },
});
