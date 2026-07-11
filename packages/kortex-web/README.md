# kortex-web

The Kortex web console — a Vite + React + TypeScript SPA for the memory layer.
Design system: "core memory" (IBM Plex, ferrite-copper on deep slate).

## Run

```bash
npm install
npm run dev        # http://localhost:5173, proxies /v1 -> http://localhost:8000
```

The dev server proxies API calls to `localhost:8000`, so run the API alongside
it (`kortex-api`). No CORS config needed in dev.

## Build

```bash
npm run build      # tsc -b && vite build -> dist/
npm run preview    # serve the production build
```

## Config

`VITE_API_BASE_URL` — API origin in production (blank in dev; the proxy handles
it). See `.env.example`.

## What's here

- **Public**: landing/pricing (`/`), login (`/login`), signup (`/signup`).
- **App** (`/app`, authed): Recall (agentic retrieval), Memories (browse +
  create + detail), Ingest (git-log import), API keys, Billing.
- Auth: JWT access/refresh in `localStorage`, single-flight auto-refresh on 401
  (`src/lib/api.ts`). Scope (workspace/project) selection in `src/lib/scope.tsx`.

## Security notes

- **Token storage**: access/refresh JWTs are kept in `localStorage`, not httpOnly
  cookies. The API is Bearer-token based (shared with agents/MCP), so cookies
  would fork the auth path and add CSRF handling. XSS-theft risk is mitigated by
  a short access-TTL, **single-use refresh rotation**, and a **server-side jti
  denylist** (logout and rotation both revoke). Reconsider cookies only if the UI
  begins rendering untrusted third-party markup.
- **Deploy**: `docker/web.Dockerfile` builds the SPA and serves it via nginx. In
  compose, nginx proxies `/v1` to the api service; in k8s the ingress routes API
  paths to the api service and everything else to this SPA.
