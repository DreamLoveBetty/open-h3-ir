// Dev launcher: the control API on <port+1>, then Vite on the requested port.
// Forwards --host/--port from `npm run dev -- --port 7100` to Vite.
import { spawn } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, "..");

const argv = process.argv.slice(2);
const flag = (name, dflt) => {
  const i = argv.indexOf(name);
  return i >= 0 && argv[i + 1] ? argv[i + 1] : dflt;
};
const port = Number(flag("--port", process.env.PORT || 7100));
const host = flag("--host", "0.0.0.0");
const apiPort = port + 1;

const api = spawn(process.execPath, [path.join(ROOT, "server", "index.mjs")], {
  stdio: "inherit",
  env: { ...process.env, CONSOLE_API_PORT: String(apiPort) },
});

const vite = spawn("npx", ["vite", "--port", String(port), "--host", host, "--strictPort"], {
  cwd: ROOT,
  stdio: "inherit",
  env: { ...process.env, CONSOLE_API_PORT: String(apiPort) },
  shell: process.platform === "win32",
});

function shutdown() {
  api.kill("SIGTERM");
  vite.kill("SIGTERM");
  setTimeout(() => process.exit(0), 300);
}
process.on("SIGINT", shutdown);
process.on("SIGTERM", shutdown);
vite.on("exit", (code) => { api.kill("SIGTERM"); process.exit(code ?? 0); });
api.on("exit", () => { /* vite keeps serving; the API panel will show errors */ });
