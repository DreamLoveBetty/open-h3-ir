/* OpenH3-IR Media: the tray's panel, second construction.
 *
 * The first construction sized itself fluidly against whatever the host gave it, and the host's
 * layout system overrode every declaration: rows painted outside the node at some zooms and inside
 * at others. This one follows the reference loader's principle instead, which the owner spotted:
 * PIN the space for every possible slot beforehand, a fixed 476px board with all nine picture
 * cells, three clip rows and three sound rows drawn from the start, and populate cells as files
 * land. Nothing negotiates for room, so nothing can lose the negotiation.
 *
 * Everything here is rendering. The node's one real field is the `tray` string (JSON slots) and
 * this panel is an editor for it: delete this file and the node still works, still API-drives, and
 * still restores from a saved workflow. The role words MIRROR comfyui/tray.py, the authority.
 *
 * Board geometry, slot styling and upload idioms follow
 * ComfyUI-Fantastic-MiniMaxH3-PromptBuilder's medialoader.js (MIT), credited in README.md.
 */
import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

const VERSION = "tray v9";
console.log("[OpenH3-IR]", VERSION);
const NODE = "OpenH3IRMedia";
const NODE_W = 578;
const NODE_H_EXTRA = 84;
const PANEL_H = 476;
const CAPACITY = { picture: 9, video: 3, sound: 3 };
const MAX_FILES = 12;
const PREFIX = { picture: "picture", video: "video", sound: "audio" };
const ROLES = {
  picture: ["something in the shot", "the setting", "a style to copy",
            "first frame", "last frame", "staging sketch"],
  video: ["copy what is in it", "edit it", "carry on from it"],
  sound: ["play it", "match its style", "cut to its beat", "sound effect", "voice to match"],
};
const ROLE_TOKEN = {
  "something in the shot": "subject", "the setting": "environment", "a style to copy": "style",
  "first frame": "frame_anchor_first", "last frame": "frame_anchor_last",
  "staging sketch": "storyboard",
  "copy what is in it": "subject", "edit it": "edit_source",
  "carry on from it": "continuation_source",
  "play it": "bgm", "match its style": "music_style", "cut to its beat": "beat_reference",
  "sound effect": "sfx", "voice to match": "voice_timbre",
};
const SOUNDTRACKS = ["off", "paired", "alone"];
// What a filled cell wears so its settings are visible without opening the editor. Every slot
// wears its role in the same style: which role matters more is the user's business, not the
// panel's.
const BADGE_BY_KIND = {
  picture: { subject: "in shot", environment: "setting", style: "style",
             frame_anchor_first: "first", frame_anchor_last: "last", storyboard: "sketch" },
  video: { subject: "copy", edit_source: "edit", continuation_source: "continue" },
  sound: { bgm: "play", music_style: "style", beat_reference: "beat", sfx: "sfx",
           voice_timbre: "voice" },
};
const DEFAULT_ROLE = { picture: "subject", video: "subject", sound: "bgm" };

function el(tag, props = {}, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (k === "style") Object.assign(e.style, v);
    else if (k === "class") e.className = v;
    else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else e[k] = v;
  }
  for (const kid of kids) e.append(kid);
  return e;
}

function viewUrl(annotated) {
  const name = annotated.replace(/ \[(input|output|temp)\]$/, "");
  const type = (annotated.match(/\[(input|output|temp)\]$/) || [, "input"])[1];
  const i = name.lastIndexOf("/");
  const params = new URLSearchParams({
    filename: i < 0 ? name : name.slice(i + 1),
    subfolder: i < 0 ? "" : name.slice(0, i),
    type,
  });
  return api.apiURL("/view?" + params);
}

function autoLabel(kind, taken) {
  const used = new Set(taken.map((t) => String(t).toLowerCase()));
  for (let n = 1; n <= CAPACITY[kind] + 1; n++) {
    if (!used.has(`${PREFIX[kind]}${n}`)) return `${PREFIX[kind]}${n}`;
  }
  return `${PREFIX[kind]}${CAPACITY[kind] + 1}`;
}

class Tray {
  constructor(node, widget) {
    this.node = node;
    this.widget = widget;
    this.selected = null; // label of the slot the editor strip is showing

    this.counts = el("span", { class: "oh3-counts" });
    this.msg = el("span", { class: "oh3-msg" });
    const top = el("div", { class: "oh3-top" },
      this.counts, this.msg);

    this.picGrid = el("div", { class: "oh3-pics" });
    this.vidRows = el("div", { class: "oh3-vids" });
    this.sndRows = el("div", { class: "oh3-auds" });
    const right = el("div", { class: "oh3-col" },
      el("div", { class: "oh3-sec", textContent: "clips" }), this.vidRows,
      el("div", { class: "oh3-sec", textContent: "sounds" }), this.sndRows);
    const cols = el("div", { class: "oh3-cols" },
      el("div", { class: "oh3-col" },
        el("div", { class: "oh3-sec", textContent: "pictures" }), this.picGrid),
      right);

    this.editor = el("div", { class: "oh3-edit" });

    this.root = el("div", { class: "oh3-panel" }, top, cols, this.editor);
    this.root.addEventListener("dragover", (e) => { e.preventDefault(); this.root.classList.add("oh3-hot"); });
    this.root.addEventListener("dragleave", () => this.root.classList.remove("oh3-hot"));
    this.root.addEventListener("drop", (e) => {
      e.preventDefault(); this.root.classList.remove("oh3-hot");
      this.addFiles([...(e.dataTransfer?.files || [])]);
    });
    this.render();
  }

  slots() {
    try { const v = JSON.parse(this.widget.value || "[]"); return Array.isArray(v) ? v : []; }
    catch { return []; }
  }

  write(slots) {
    this.widget.value = JSON.stringify(slots);
    this.node.setDirtyCanvas?.(true, true);
    this.render();
  }

  say(text, bad = false) {
    this.msg.textContent = text || "";
    this.msg.classList.toggle("oh3-bad", !!bad);
  }

  pick() {
    const input = el("input", { type: "file", multiple: true });
    input.addEventListener("change", () => this.addFiles([...input.files]));
    input.click();
  }

  async addFiles(files) {
    for (const f of files) {
      try { await this.addOne(f); } catch (err) { this.say(String(err.message || err), true); }
    }
  }

  async addOne(file) {
    const body = new FormData();
    body.append("file", file, file.name);
    const resp = await api.fetchApi("/openh3ir/upload", { method: "POST", body });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) throw new Error(data.error || `upload failed (${resp.status})`);
    const slots = this.slots();
    const kind = data.kind;
    if (slots.filter((s) => s.kind === kind).length >= CAPACITY[kind])
      throw new Error(`all ${CAPACITY[kind]} ${kind} slots are full.`);
    if (slots.length >= MAX_FILES)
      throw new Error(`the tray takes at most ${MAX_FILES} files, and it is full.`);
    const slot = { kind, label: autoLabel(kind, slots.map((s) => s.label)), file: data.file,
                   role: ROLE_TOKEN[ROLES[kind][0]], note: "" };
    if (kind === "video") slot.soundtrack = data.has_audio ? "paired" : "off";
    if (kind === "sound") slot.transcript = "";
    this.selected = slot.label;
    this.say(`${data.original || data.name} → @${slot.label}`);
    this.write([...slots, slot]);
  }

  update(label, patch) {
    const slots = this.slots();
    const i = slots.findIndex((s) => s.label === label);
    if (i < 0) return;
    slots[i] = { ...slots[i], ...patch };
    if (patch.label) this.selected = patch.label;
    this.write(slots);
  }

  remove(label) {
    if (this.selected === label) this.selected = null;
    this.write(this.slots().filter((s) => s.label !== label));
  }

  // ---------------------------------------------------------------- the pinned board

  cell(kind, index, slot) {
    if (!slot) {
      return el("div", { class: "oh3-slot", textContent: `${PREFIX[kind]}${index + 1}`,
        onclick: () => this.pick() });
    }
    const cls = { picture: "pic", video: "vid", sound: "aud" }[kind];
    const cell = el("div", { class: `oh3-slot oh3-filled oh3-${cls}`
      + (this.selected === slot.label ? " oh3-sel" : "") });
    cell.addEventListener("click", () => { this.selected = slot.label; this.render(); });

    if (kind === "picture") {
      cell.append(el("img", { class: "oh3-fit", src: viewUrl(slot.file), loading: "lazy" }));
      cell.append(this.badges(slot));
      cell.append(el("div", { class: "oh3-bar" },
        el("span", { class: "oh3-tag", textContent: "@" + slot.label }),
        el("span", { class: "oh3-x", textContent: "×",
          onclick: (e) => { e.stopPropagation(); this.remove(slot.label); } })));
      return cell;
    }

    const row = el("div", { class: "oh3-rowline" });
    if (kind === "video") {
      row.append(el("video", { class: "oh3-vthumb", src: viewUrl(slot.file), muted: true,
        loop: true, preload: "metadata",
        onmouseenter(e) { e.target.play?.(); }, onmouseleave(e) { e.target.pause?.(); } }));
    } else {
      row.append(el("button", { class: "oh3-play", textContent: "♪", title: "play",
        onclick: (e) => {
          e.stopPropagation();
          if (this._audio) { this._audio.pause(); this._audio = null; return; }
          this._audio = new Audio(viewUrl(slot.file));
          this._audio.play();
          this._audio.addEventListener("ended", () => { this._audio = null; });
        } }));
    }
    row.append(el("span", { class: "oh3-tag", textContent: "@" + slot.label }));
    row.append(this.badges(slot, true));
    row.append(el("span", { class: "oh3-x", textContent: "×",
      onclick: (e) => { e.stopPropagation(); this.remove(slot.label); } }));
    cell.append(row);
    return cell;
  }

  badges(slot, inline = false) {
    const wrap = el("span", { class: inline ? "oh3-badges oh3-inlinebadges" : "oh3-badges" });
    const word = (BADGE_BY_KIND[slot.kind] || {})[slot.role];
    if (word) wrap.append(el("span", { class: "oh3-badge oh3-rolebadge",
      textContent: word, title: "what it is: set in the editor below" }));
    if ((slot.note || "").trim()) wrap.append(el("span", { class: "oh3-badge",
      textContent: "✎", title: "described: " + slot.note }));
    if ((slot.transcript || "").trim()) wrap.append(el("span", { class: "oh3-badge",
      textContent: "abc", title: "its words are typed in" }));
    if (slot.kind === "video" && slot.soundtrack && slot.soundtrack !== "paired")
      wrap.append(el("span", { class: "oh3-badge",
        textContent: "sound " + slot.soundtrack,
        title: "its soundtrack: set in the editor below" }));
    return wrap;
  }

  // ---------------------------------------------------------------- the editor strip

  renderEditor() {
    const slot = this.slots().find((s) => s.label === this.selected);
    if (!slot) {
      this.editor.replaceChildren(el("div", { class: "oh3-hint", textContent:
        "drop files anywhere on this panel, or click an empty slot. Click a filled one to name it "
        + "and say what it is." }));
      return;
    }
    const label = el("input", { class: "oh3-in oh3-name", value: slot.label,
      title: "the name @ mentions this file by: letters, digits and dashes" });
    label.addEventListener("change", () => this.update(slot.label, { label: label.value.trim() }));
    const role = el("select", { class: "oh3-in", title: "what this file is to the piece" });
    for (const words of ROLES[slot.kind]) role.append(el("option", {
      value: ROLE_TOKEN[words], textContent: words, selected: ROLE_TOKEN[words] === slot.role }));
    role.addEventListener("change", () => this.update(slot.label, { role: role.value }));
    // The description asks in the words of the chosen role, and fields a role cannot use do not
    // appear: a sound effect has no lyrics, so it gets no words box.
    const NOTE_ASK = {
      voice_timbre: "how the voice sounds: hoarse, unhurried, mid-forties",
      sfx: "what it is: a heavy door slamming, close, no reverb",
      bgm: "timbre, tempo, instruments: slow synth score, no drums",
      music_style: "timbre, tempo, instruments: slow synth score, no drums",
      beat_reference: "the rhythm: a steady 90 bpm pulse, one hit per bar",
    };
    const note = el("input", { class: "oh3-in oh3-wide", value: slot.note || "", placeholder:
      slot.kind === "sound"
        ? (NOTE_ASK[slot.role] || "what it sounds like") +
          " — the only description the model will ever have"
        : "what it is, in a few words" });
    note.addEventListener("change", () => this.update(slot.label, { note: note.value }));

    const first = el("div", { class: "oh3-editrow" },
      el("span", { class: "oh3-at", textContent: "@" }), label, role);
    if (slot.kind === "video") {
      const st = el("select", { class: "oh3-in oh3-st", title:
        "its own soundtrack: off sends none, paired sends it as this clip's sound, alone sends it as a track in its own right" });
      for (const v of SOUNDTRACKS) st.append(el("option", { value: v,
        textContent: "soundtrack " + v, selected: v === (slot.soundtrack || "off") }));
      st.addEventListener("change", () => this.update(slot.label, { soundtrack: st.value }));
      first.append(st);
    }
    const rows = [first, el("div", { class: "oh3-editrow" }, note)];
    // Only the roles for which a recording's own words mean anything: a voice to imitate, or a
    // track played outright whose lyrics must ride along. Style, beat and effects have no words.
    if (slot.kind === "sound" && (slot.role === "voice_timbre" || slot.role === "bgm")) {
      const words = el("input", { class: "oh3-in oh3-wide", value: slot.transcript || "",
        placeholder: "the words in this recording, exactly as spoken — nothing here can hear" });
      words.addEventListener("change", () => this.update(slot.label, { transcript: words.value }));
      rows.push(el("div", { class: "oh3-editrow" }, words));
    }
    this.editor.replaceChildren(...rows);
  }

  render() {
    const slots = this.slots();
    const of = (kind) => slots.filter((s) => s.kind === kind);
    if (this.selected && !slots.some((s) => s.label === this.selected)) this.selected = null;

    this.counts.textContent =
      `${slots.length} / ${MAX_FILES}`;
    this.picGrid.replaceChildren(
      ...Array.from({ length: 9 }, (_, i) => this.cell("picture", i, of("picture")[i])));
    this.vidRows.replaceChildren(
      ...Array.from({ length: 3 }, (_, i) => this.cell("video", i, of("video")[i])));
    this.sndRows.replaceChildren(
      ...Array.from({ length: 3 }, (_, i) => this.cell("sound", i, of("sound")[i])));
    this.renderEditor();
  }
}

/* The board: every dimension pinned, nothing negotiated with the host. */
const CSS = `
.oh3-panel{font-family:system-ui,sans-serif;color:#d7dbe2;font-size:11px;
  background:#191c22;border:1px solid #2a2f3a;border-radius:8px;padding:7px;
  display:flex;flex-direction:column;gap:6px;box-sizing:border-box;
  width:100%;max-width:546px;height:${PANEL_H}px;min-height:${PANEL_H}px;overflow:hidden;}
.oh3-panel *{box-sizing:border-box;min-width:0;}
.oh3-panel.oh3-hot{border-color:#e8873a;}
.oh3-top{flex:0 0 auto;display:flex;align-items:center;gap:8px;overflow:hidden;}
.oh3-counts{font-family:ui-monospace,monospace;font-size:10px;color:#8a93a3;flex:0 0 auto;}
.oh3-msg{flex:1;min-width:0;font-size:10px;color:#8a93a3;overflow:hidden;
  text-overflow:ellipsis;white-space:nowrap;}
.oh3-msg.oh3-bad{color:#f07070;}
.oh3-ver{flex:0 0 auto;font-size:8px;color:#4d5563;font-family:ui-monospace,monospace;}
.oh3-cols{flex:1;min-height:0;display:grid;grid-template-columns:1fr 1fr;gap:8px;}
.oh3-col{display:flex;flex-direction:column;gap:4px;min-width:0;min-height:0;}
.oh3-sec{flex:0 0 auto;font-size:9px;letter-spacing:.08em;text-transform:uppercase;color:#6b7484;}
.oh3-pics{flex:1;min-height:0;display:grid;gap:5px;
  grid-template-columns:repeat(3,minmax(0,1fr));grid-template-rows:repeat(3,minmax(0,1fr));}
.oh3-vids{flex:1;min-height:0;display:grid;grid-template-rows:repeat(3,minmax(0,1fr));gap:5px;
  grid-template-columns:minmax(0,1fr);}
.oh3-auds{flex:1;min-height:0;display:grid;grid-template-rows:repeat(3,minmax(0,1fr));gap:5px;
  grid-template-columns:minmax(0,1fr);}
.oh3-slot{border:1px dashed #2b313d;border-radius:6px;background:#141820;
  display:flex;align-items:center;justify-content:center;color:#4d5563;font-size:10px;
  cursor:pointer;overflow:hidden;min-width:0;min-height:0;}
.oh3-slot:hover{border-color:#59637a;color:#8a93a3;}
.oh3-filled{border-style:solid;border-color:#2e3440;background:#12151b;cursor:pointer;
  display:block;position:relative;}
.oh3-filled.oh3-pic{border-color:#6d5527;}
.oh3-filled.oh3-vid{border-color:#255c6b;}
.oh3-filled.oh3-aud{border-color:#4c3d6e;}
.oh3-sel{outline:1px solid #e8873a;outline-offset:1px;}
.oh3-fit{position:absolute;inset:0;width:100%;height:100%;object-fit:contain;display:block;
  background:#0d1015;}
.oh3-bar{position:absolute;left:0;right:0;bottom:0;display:flex;align-items:center;gap:4px;
  padding:1px 4px;background:rgba(10,12,16,.82);overflow:hidden;}
.oh3-tag{flex:1 1 auto;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;
  font-family:ui-monospace,monospace;font-size:9px;color:#e0a94c;text-align:left;}
.oh3-vid .oh3-tag{color:#4cc3e0;} .oh3-aud .oh3-tag{color:#b48ce8;}
.oh3-x{flex:0 0 auto;cursor:pointer;color:#7a8393;font-size:11px;line-height:1;}
.oh3-x:hover{color:#e05a5a;}
.oh3-rowline{display:flex;align-items:center;gap:6px;padding:0 6px;height:100%;overflow:hidden;}
.oh3-vthumb{width:56px;height:32px;min-width:56px;border-radius:4px;object-fit:contain;
  background:#0d1015;flex:0 0 auto;}
.oh3-play{width:20px;height:20px;border-radius:50%;border:1px solid #3a4252;background:#20242d;
  color:#c9cfda;font-size:10px;line-height:1;cursor:pointer;flex:0 0 auto;padding:0;}
.oh3-seg{flex:0 0 auto;width:96px;background:#12151b;border:1px solid #2e3440;color:#c9cfda;
  border-radius:4px;font-size:10px;padding:2px;}
.oh3-edit{flex:0 0 auto;height:88px;border-top:1px solid #2a2f3a;padding-top:6px;
  display:flex;flex-direction:column;gap:5px;overflow:hidden;}
.oh3-editrow{display:flex;align-items:center;gap:5px;overflow:hidden;}
.oh3-at{flex:0 0 auto;color:#e8873a;font-family:ui-monospace,monospace;}
.oh3-in{background:#12151b;border:1px solid #2e3440;color:#d7dbe2;border-radius:4px;
  padding:3px 6px;font-size:11px;}
.oh3-name{flex:0 0 110px;}
select.oh3-in{flex:1;}
.oh3-st{flex:0 0 132px;}
.oh3-wide{flex:1;width:100%;}
.oh3-hint{color:#6b7484;font-size:10px;padding-top:14px;text-align:center;}
.oh3-badges{position:absolute;top:3px;right:3px;display:flex;gap:3px;z-index:1;}
.oh3-inlinebadges{position:static;flex:0 0 auto;}
.oh3-badge{background:rgba(10,12,16,.85);border:1px solid #333a46;border-radius:3px;
  color:#7d8695;font-size:8px;padding:0 3px;line-height:1.5;font-family:ui-monospace,monospace;}
.oh3-rolebadge{color:#e8873a;border-color:#6d5527;}
`;

app.registerExtension({
  name: "openh3ir.tray",
  init() {
    document.head.append(el("style", { textContent: CSS }));
  },
  beforeRegisterNodeDef(nodeType, nodeData) {
    if (nodeData?.name !== NODE) return;
    const onCreated = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function () {
      const r = onCreated?.apply(this, arguments);
      const state = (this.widgets || []).find((w) => w.name === "tray");
      if (!state) return r;
      state.computeSize = () => [0, -4];
      state.hidden = true;
      if (state.options) state.options.hidden = true;
      const tray = new Tray(this, state);
      this._oh3Tray = tray;
      const panel = this.addDOMWidget("oh3_panel", "div", tray.root, { serialize: false });
      // Honoured by the canvas renderer; harmless where Vue owns layout, and the board's own
      // pinned CSS is what actually keeps it intact there.
      panel.computedHeight = PANEL_H;
      panel.computeSize = (w) => [w || NODE_W, PANEL_H];
      this.size[0] = NODE_W;
      this.size[1] = PANEL_H + NODE_H_EXTRA;
      requestAnimationFrame(() => tray.render());
      return r;
    };
    nodeType.prototype.computeSize = function () {
      // The node hugs the board exactly: a pinned board inside a fluid node is what left gray
      // slack around the panel. Nothing about this node benefits from being resized.
      return [NODE_W, PANEL_H + NODE_H_EXTRA];
    };

    const onResize = nodeType.prototype.onResize;
    nodeType.prototype.onResize = function (size) {
      try {
        size[0] = NODE_W;
        size[1] = PANEL_H + NODE_H_EXTRA;
      } catch (e) { /* leave the size alone */ }
      return onResize?.apply(this, arguments);
    };
    const onConfigure = nodeType.prototype.onConfigure;
    nodeType.prototype.onConfigure = function () {
      const r = onConfigure?.apply(this, arguments);
      this._oh3Tray?.render();
      return r;
    };
  },
});
