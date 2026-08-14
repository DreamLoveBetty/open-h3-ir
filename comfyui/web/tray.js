/* OpenH3-IR Media: the tray's panel.
 *
 * Everything here is rendering. The node's one real field is the `tray` string, a JSON list of
 * slots, and this panel is an editor for that string: delete this file and the node still works,
 * still API-drives, and still restores from a saved workflow, with the string visible as itself.
 * The role words and the label rules MIRROR comfyui/tray.py, which is the authority; a mismatch
 * here shows the user words the run will refuse, so change them together.
 *
 * Panel idioms (DOM widget mount, FormData upload, node sizing guard) follow
 * ComfyUI-Fantastic-MiniMaxH3-PromptBuilder's medialoader.js (MIT), credited in README.md.
 */
import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

const NODE = "OpenH3IRMedia";
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
const WORDS = Object.fromEntries(Object.entries(ROLE_TOKEN).map(([w, t]) => [t, w]));
const SOUNDTRACKS = ["off", "paired", "alone"];
const NODE_W = 380;
const PANEL_H = 460;

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
  const used = new Set(taken.map((t) => t.toLowerCase()));
  for (let n = 1; n <= CAPACITY[kind] + 1; n++) {
    if (!used.has(`${PREFIX[kind]}${n}`)) return `${PREFIX[kind]}${n}`;
  }
  return `${PREFIX[kind]}${CAPACITY[kind] + 1}`;
}

class Tray {
  constructor(node, widget) {
    this.node = node;
    this.widget = widget;
    this.msg = el("div", { class: "oh3-msg" });
    this.sections = {};
    this.root = el("div", { class: "oh3-tray" });
    const drop = el("div", { class: "oh3-drop", textContent:
      "drop files here, or click to add — pictures, clips, sounds" });
    drop.addEventListener("click", () => this.pick());
    drop.addEventListener("dragover", (e) => { e.preventDefault(); drop.classList.add("oh3-over"); });
    drop.addEventListener("dragleave", () => drop.classList.remove("oh3-over"));
    drop.addEventListener("drop", (e) => {
      e.preventDefault(); drop.classList.remove("oh3-over");
      this.addFiles([...(e.dataTransfer?.files || [])]);
    });
    this.root.append(drop);
    for (const kind of ["picture", "video", "sound"]) {
      const body = el("div", { class: "oh3-slots" });
      const head = el("div", { class: "oh3-head" });
      this.sections[kind] = { body, head };
      this.root.append(head, body);
    }
    this.root.append(this.msg);
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
    const ofKind = slots.filter((s) => s.kind === kind);
    if (ofKind.length >= CAPACITY[kind])
      throw new Error(`the tray takes at most ${CAPACITY[kind]} ${kind}s, and they are full.`);
    if (slots.length >= MAX_FILES)
      throw new Error(`the tray takes at most ${MAX_FILES} files, and it is full.`);
    const slot = { kind, label: autoLabel(kind, slots.map((s) => s.label)), file: data.file,
                   role: ROLE_TOKEN[ROLES[kind][0]], note: "" };
    if (kind === "video") slot.soundtrack = data.has_audio ? "paired" : "off";
    if (kind === "sound") slot.transcript = "";
    slot._info = data;
    this.say(`${data.original || data.name} → @${slot.label}`);
    this.write([...slots, slot]);
  }

  card(slot, index) {
    const kind = slot.kind;
    const card = el("div", { class: "oh3-card" });
    const preview = el("div", { class: "oh3-thumb" });
    if (kind === "picture") preview.append(el("img", { src: viewUrl(slot.file), loading: "lazy" }));
    else if (kind === "video") preview.append(el("video", { src: viewUrl(slot.file),
      muted: true, loop: true, preload: "metadata", onmouseenter(e) { e.target.play?.(); },
      onmouseleave(e) { e.target.pause?.(); } }));
    else preview.append(el("audio", { src: viewUrl(slot.file), controls: true }));

    const label = el("input", { class: "oh3-label", value: slot.label, title:
      "the name @ mentions this file by, letters, digits and dashes" });
    label.addEventListener("change", () => this.update(index, { label: label.value.trim() }));

    const role = el("select", { class: "oh3-role", title: "what this file is to the piece" });
    for (const words of ROLES[kind]) role.append(el("option", {
      value: ROLE_TOKEN[words], textContent: words,
      selected: ROLE_TOKEN[words] === (slot.role || ROLE_TOKEN[ROLES[kind][0]]) }));
    role.addEventListener("change", () => this.update(index, { role: role.value }));

    const note = el("input", { class: "oh3-note", value: slot.note || "", placeholder:
      kind === "sound" ? "what it sounds like — the only description the model gets"
                       : "what it is, in a few words" });
    note.addEventListener("change", () => this.update(index, { note: note.value }));

    const row = el("div", { class: "oh3-row" }, label, role);
    if (kind === "video") {
      const st = el("select", { class: "oh3-role", title:
        "its own soundtrack: off sends none, paired sends it as this clip's sound, alone sends it as a sound in its own right" });
      for (const v of SOUNDTRACKS) st.append(el("option", { value: v, textContent: `sound: ${v}`,
        selected: v === (slot.soundtrack || "off") }));
      st.addEventListener("change", () => this.update(index, { soundtrack: st.value }));
      row.append(st);
    }
    const kill = el("button", { class: "oh3-x", textContent: "×",
      title: "remove this slot", onclick: () => {
        const slots = this.slots(); slots.splice(index, 1); this.write(slots);
      } });
    row.append(kill);
    card.append(preview, row, note);

    if (kind === "sound" && (slot.role === "voice_timbre" || slot.transcript)) {
      const words = el("textarea", { class: "oh3-words", value: slot.transcript || "",
        placeholder: "the words in this recording, exactly as spoken — nothing here can hear" });
      words.addEventListener("change", () => this.update(index, { transcript: words.value }));
      card.append(words);
    }
    return card;
  }

  update(index, patch) {
    const slots = this.slots();
    slots[index] = { ...slots[index], ...patch };
    this.write(slots);
  }

  render() {
    const slots = this.slots();
    for (const kind of ["picture", "video", "sound"]) {
      const of = slots.map((s, i) => [s, i]).filter(([s]) => s.kind === kind);
      const { head, body } = this.sections[kind];
      head.textContent = `${kind === "sound" ? "sounds" : kind + "s"}  ${of.length}/${CAPACITY[kind]}`;
      body.replaceChildren(...of.map(([s, i]) => this.card(s, i)));
    }
  }
}

const CSS = `
.oh3-tray{display:flex;flex-direction:column;gap:6px;padding:6px;font-family:system-ui,sans-serif;
  font-size:11px;color:#dde2ea;width:100%;max-width:100%;height:460px;min-height:460px;
  overflow:hidden;overflow-y:auto;box-sizing:border-box;position:relative;contain:content;}
.oh3-tray *{box-sizing:border-box;min-width:0;max-width:100%;}
.oh3-drop{border:1px dashed #4a5262;border-radius:6px;padding:10px;text-align:center;color:#8b93a5;
  cursor:pointer;}
.oh3-drop.oh3-over{border-color:#e8873a;color:#e8873a;}
.oh3-head{color:#8b93a5;font-size:10px;letter-spacing:.08em;text-transform:uppercase;margin-top:2px;}
.oh3-slots{display:flex;flex-direction:column;gap:6px;}
.oh3-card{border:1px solid #2e3440;border-radius:6px;padding:6px;display:flex;flex-direction:column;
  gap:5px;background:rgba(16,18,24,.6);}
.oh3-thumb img,.oh3-thumb video{max-width:100%;max-height:96px;border-radius:4px;display:block;}
.oh3-thumb audio{width:100%;height:26px;}
.oh3-row{display:flex;gap:5px;align-items:center;}
.oh3-label{flex:0 0 88px;min-width:0;background:#14161c;border:1px solid #2e3440;color:#dde2ea;
  border-radius:4px;padding:3px 5px;font-size:11px;}
.oh3-role{flex:1;min-width:0;background:#14161c;border:1px solid #2e3440;color:#dde2ea;
  border-radius:4px;padding:3px;font-size:11px;}
.oh3-note{width:100%;box-sizing:border-box;background:#14161c;border:1px solid #2e3440;
  color:#dde2ea;border-radius:4px;padding:3px 5px;font-size:11px;}
.oh3-words{width:100%;box-sizing:border-box;background:#14161c;border:1px solid #2e3440;
  color:#dde2ea;border-radius:4px;padding:3px 5px;font-size:11px;min-height:34px;resize:vertical;}
.oh3-x{flex:0 0 auto;background:none;border:1px solid #2e3440;color:#8b93a5;border-radius:4px;
  cursor:pointer;width:20px;height:20px;line-height:1;}
.oh3-x:hover{color:#f07070;border-color:#f07070;}
.oh3-msg{min-height:13px;font-size:10px;color:#8b93a5;}
.oh3-msg.oh3-bad{color:#f07070;}
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
      // The string stays the node's real field; the panel is its editor, so the raw text row
      // shrinks out of the way rather than showing the same fact twice.
      state.computeSize = () => [0, -4];
      state.hidden = true;
      if (state.options) state.options.hidden = true;
      const tray = new Tray(this, state);
      this._oh3Tray = tray;
      const panel = this.addDOMWidget("oh3_panel", "div", tray.root, { serialize: false });
      // The canvas reserves room only for what computeSize declares, and a DOM widget declares
      // nothing by default: without these two lines the panel gets zero rows and its content piles
      // over the node's other widgets. The recipe follows the reference loader verbatim.
      panel.computedHeight = PANEL_H;
      panel.computeSize = (w) => [w || this.size?.[0] || NODE_W, PANEL_H];
      const min = this.computeSize?.();
      this.size[0] = Math.max(NODE_W, this.size?.[0] || 0);
      this.size[1] = Math.max(min?.[1] || 0, PANEL_H + 130, this.size?.[1] || 0);
      // A workflow load writes widget values after onNodeCreated, so re-render when it lands.
      requestAnimationFrame(() => tray.render());
      return r;
    };
    const onResize = nodeType.prototype.onResize;
    nodeType.prototype.onResize = function (size) {
      try {
        size[0] = Math.max(NODE_W, size[0]);
        size[1] = Math.max(PANEL_H + 130, size[1]);
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
