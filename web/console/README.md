# H3·IR Console

A minimal local control surface for the OpenH3-IR compiler stack: start/stop the three
services, upload image/video/audio assets into the content-addressed store, compose a
brief, and read the compiled IR.

```bash
npm install
npm run dev            # vite on the given --port, control API on port+1
npm run dev -- --port 7100
```

The page talks only to same-origin `/api/*`; the control server (`server/index.mjs`,
zero-dependency node:http) manages the service processes, forwards uploads to
`PUT /v1/assets/{sha256}` on the compiler service, and proxies `POST /v1/briefs`.

The reasoning model is yours to point at: `H3IR_LLM_URL=http://host:port/v1 npm run dev`.
Without it the compiler refuses to compile (rule: never degrade silently) and the
console shows that refusal verbatim.

Services started from the console are tracked and can be stopped from it; services
already running outside it are shown as `external` and are never killed by it.
