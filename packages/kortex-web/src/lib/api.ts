// Authed fetch client for the Kortex API.
//
// Token storage decision: tokens live in localStorage. The API is a Bearer-token
// API shared by the SPA and programmatic agents/MCP, so httpOnly cookies would
// fork the auth path and add CSRF handling for marginal gain. The XSS-theft risk
// is mitigated instead by: short access-token TTL, single-use refresh rotation,
// and a server-side jti denylist (logout + rotation revoke). Revisit cookies only
// if the app starts rendering untrusted third-party markup.

const BASE = import.meta.env.VITE_API_BASE_URL ?? "";
const ACCESS_KEY = "kortex.access";
const REFRESH_KEY = "kortex.refresh";

export type Tokens = { access_token: string; refresh_token: string };

export const tokens = {
  get access() {
    return localStorage.getItem(ACCESS_KEY);
  },
  get refresh() {
    return localStorage.getItem(REFRESH_KEY);
  },
  set({ access_token, refresh_token }: Tokens) {
    localStorage.setItem(ACCESS_KEY, access_token);
    localStorage.setItem(REFRESH_KEY, refresh_token);
  },
  clear() {
    localStorage.removeItem(ACCESS_KEY);
    localStorage.removeItem(REFRESH_KEY);
  },
};

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

async function rawFetch(path: string, init: RequestInit, auth: boolean): Promise<Response> {
  const headers = new Headers(init.headers);
  // Only default to JSON for string bodies; let the browser set the boundary
  // for FormData (file uploads) and send nothing for GETs.
  if (typeof init.body === "string" && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  if (auth && tokens.access) {
    headers.set("Authorization", `Bearer ${tokens.access}`);
  }
  return fetch(`${BASE}${path}`, { ...init, headers });
}

// Single-flight refresh so a burst of 401s triggers only one refresh call.
let refreshing: Promise<boolean> | null = null;

async function tryRefresh(): Promise<boolean> {
  if (!tokens.refresh) return false;
  if (!refreshing) {
    refreshing = rawFetch(
      "/v1/auth/refresh",
      { method: "POST", body: JSON.stringify({ refresh_token: tokens.refresh }) },
      false,
    )
      .then(async (res) => {
        if (!res.ok) return false;
        tokens.set(await res.json());
        return true;
      })
      .catch(() => false)
      .finally(() => {
        refreshing = null;
      });
  }
  return refreshing;
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  let res = await rawFetch(path, init, true);
  if (res.status === 401 && (await tryRefresh())) {
    res = await rawFetch(path, init, true);
  }
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    const err = new ApiError(res.status, detail.detail ?? res.statusText);
    // Rate-limit isn't surfaced per-page; broadcast so the toast layer shows it.
    if (res.status === 429) {
      window.dispatchEvent(
        new CustomEvent("kortex:ratelimited", { detail: "Rate limited — slow down for a moment." }),
      );
    }
    throw err;
  }
  return res.status === 204 ? (undefined as T) : res.json();
}

/** Authed binary download (with refresh-on-401), triggers a browser save. */
export async function downloadFile(path: string, filename: string): Promise<void> {
  let res = await rawFetch(path, {}, true);
  if (res.status === 401 && (await tryRefresh())) res = await rawFetch(path, {}, true);
  if (!res.ok) throw new ApiError(res.status, res.statusText);
  const url = URL.createObjectURL(await res.blob());
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

async function tokenCall(path: string, body: unknown, fallback: string): Promise<void> {
  const res = await rawFetch(path, { method: "POST", body: JSON.stringify(body) }, false);
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new ApiError(res.status, detail.detail ?? fallback);
  }
  tokens.set(await res.json());
}

export function login(email: string, password: string): Promise<void> {
  return tokenCall("/v1/auth/login", { email, password }, "login failed");
}

export function register(
  email: string,
  password: string,
  org_name: string,
  display_name?: string,
): Promise<void> {
  return tokenCall(
    "/v1/auth/register",
    { email, password, org_name, display_name: display_name ?? "" },
    "sign up failed",
  );
}

export async function logout(): Promise<void> {
  const refresh_token = tokens.refresh;
  if (refresh_token) {
    // Best-effort server-side revocation; clear locally regardless.
    try {
      await rawFetch("/v1/auth/logout", { method: "POST", body: JSON.stringify({ refresh_token }) }, false);
    } catch {
      /* ignore */
    }
  }
  tokens.clear();
}
