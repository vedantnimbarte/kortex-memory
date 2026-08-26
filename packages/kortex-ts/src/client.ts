/**
 * The client.
 *
 * The verbs match the ones the MCP tools already use (`remember`, `search`,
 * `recall`, `forget`), because an integrator who has seen Kortex through Claude
 * Code should not have to learn a second vocabulary for the same operations.
 *
 * Only the calls an integrator actually makes are typed here. The other
 * fifty-odd endpoints — billing, admin, tenancy, attachments — stay reachable
 * through `request()` rather than being hand-wrapped, because a method that
 * exists only so the surface looks complete is a method someone has to keep in
 * step with the server for no one's benefit.
 *
 * Zero runtime dependencies: global `fetch`, which Node has had since 18.
 */

import { APIConnectionError, APIError, errorFor } from "./errors.js";
import {
  type Memory,
  type MemoryToolResult,
  type Recall,
  type Scope,
  type SearchResult,
  type Tokens,
  toMemory,
  toMemoryToolResult,
  toRecall,
  toSearchResult,
  toTokens,
} from "./types.js";

export const VERSION = "0.1.0";
const USER_AGENT = `kortex-ts/${VERSION}`;
const DEFAULT_BASE_URL = "http://localhost:8000";

/** No 4xx but 429: retrying a rejected request just gets it rejected again. */
const RETRY_STATUSES = new Set([429, 500, 502, 503, 504]);

export interface KortexOptions {
  /** Falls back to `KORTEX_API_KEY`. */
  apiKey?: string;
  /** Falls back to `KORTEX_API_URL`, then `http://localhost:8000`. */
  baseUrl?: string;
  /** A user JWT, used when no API key is given. */
  token?: string;
  /** The scope every call uses when none is named. Set it once, not at fifty call sites. */
  scope?: Scope;
  /** Per-request timeout in milliseconds. */
  timeoutMs?: number;
  maxRetries?: number;
  /** Base for exponential backoff, in milliseconds. */
  backoffMs?: number;
  /** Swap in for tests, or to route through a proxy. */
  fetch?: typeof fetch;
}

export interface RememberOptions {
  scope?: Scope;
  title?: string;
  kind?: string;
  sensitivity?: string;
  importance?: number;
  pinned?: boolean;
  metadata?: Record<string, unknown>;
  confidence?: number;
  expiresAt?: Date;
  sourceType?: string;
  /** Wait for the vector instead of queueing it: slower, but searchable on return. */
  embedInline?: boolean;
  /** Store even if an identical memory exists, instead of folding into it. */
  force?: boolean;
}

export interface SearchOptions {
  scopes?: Scope[];
  limit?: number;
  embedQuery?: boolean;
}

export interface RecallOptions {
  scopes?: Scope[];
  synthesize?: boolean;
  maxTokens?: number;
  perItemMax?: number;
  latencyBudgetMs?: number;
  tokenBudget?: number;
}

export interface ListOptions {
  scope?: Scope;
  tier?: string;
  kind?: string;
  limit?: number;
  offset?: number;
}

export interface UpdateOptions {
  title?: string;
  body?: string;
  kind?: string;
  sensitivity?: string;
  importance?: number;
  metadata?: Record<string, unknown>;
}

/**
 * Omit unset options so the server's own defaults apply.
 *
 * Sending `null` for a field with a non-null default overrides that default
 * with a validation error, which is a confusing way to learn you left an
 * argument out.
 */
function compact(source: Record<string, unknown>): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(source)) {
    if (value !== undefined && value !== null) out[key] = value;
  }
  return out;
}

function wireScopes(scopes: Scope[] | undefined): unknown {
  if (!scopes?.length) return undefined;
  return scopes.map((s) => ({ scope_type: s.type, scope_id: s.id }));
}

function env(name: string): string | undefined {
  // `process` is absent in a browser or a worker; the client still works there,
  // it just cannot pick up defaults from an environment that does not exist.
  const proc = (globalThis as { process?: { env?: Record<string, string | undefined> } }).process;
  return proc?.env?.[name];
}

/**
 * How long to wait before the next attempt, in milliseconds.
 *
 * The server's `Retry-After` wins when it sent one — it knows when the
 * rate-limit window rolls over and we are guessing. Otherwise exponential with
 * jitter, because a fleet of clients backing off in lockstep just reconverges
 * on the same instant.
 */
export function retryDelayMs(
  response: Response | null,
  attempt: number,
  backoffMs: number,
): number {
  const header = response?.headers.get("Retry-After");
  if (header) {
    const seconds = Number(header);
    // An HTTP-date form parses as NaN; fall through to our own backoff.
    if (Number.isFinite(seconds)) return Math.max(0, seconds * 1000);
  }
  return backoffMs * 2 ** (attempt - 1) * (0.5 + Math.random());
}

export function shouldRetry(
  response: Response | null,
  attempt: number,
  maxRetries: number,
): boolean {
  if (attempt > maxRetries) return false;
  return response === null || RETRY_STATUSES.has(response.status);
}

const sleep = (ms: number): Promise<void> => new Promise((r) => setTimeout(r, ms));

export class Kortex {
  readonly #baseUrl: string;
  readonly #headers: Record<string, string>;
  readonly #scope: Scope | undefined;
  readonly #timeoutMs: number;
  readonly #maxRetries: number;
  readonly #backoffMs: number;
  readonly #fetch: typeof fetch;

  /**
   * ```ts
   * const kx = new Kortex({ scope: { type: "project", id: 7 } });
   * await kx.remember("We settled on Postgres over DynamoDB for the ledger.");
   * ```
   *
   * With no `apiKey`/`baseUrl` it reads `KORTEX_API_KEY` and `KORTEX_API_URL`.
   */
  constructor(options: KortexOptions = {}) {
    this.#baseUrl = (options.baseUrl ?? env("KORTEX_API_URL") ?? DEFAULT_BASE_URL).replace(
      /\/+$/,
      "",
    );
    this.#scope = options.scope;
    this.#timeoutMs = options.timeoutMs ?? 30_000;
    this.#maxRetries = options.maxRetries ?? 3;
    this.#backoffMs = options.backoffMs ?? 500;
    this.#fetch = options.fetch ?? globalThis.fetch.bind(globalThis);

    this.#headers = { "User-Agent": USER_AGENT, Accept: "application/json" };
    // An API key goes in X-API-Key rather than Authorization because the rate
    // limiter buckets on the key prefix and only reads that header. In
    // Authorization it would still authenticate, and silently share one
    // anonymous bucket with every other caller.
    const key = options.apiKey ?? env("KORTEX_API_KEY");
    if (key) this.#headers["X-API-Key"] = key;
    else if (options.token) this.#headers["Authorization"] = `Bearer ${options.token}`;
  }

  /**
   * Authenticate as a user from here on. Replaces an API key rather than
   * sitting beside it: two credentials on one request is a question the server
   * should not have to answer.
   */
  setToken(token: string): void {
    delete this.#headers["X-API-Key"];
    this.#headers["Authorization"] = `Bearer ${token}`;
  }

  #resolveScope(scope: Scope | undefined): Scope {
    const chosen = scope ?? this.#scope;
    if (!chosen) {
      throw new TypeError(
        "no scope given and no default set: pass { scope: { type: 'project', id } } " +
          "on the call, or to the constructor once",
      );
    }
    return chosen;
  }

  #defaultScopes(): Scope[] | undefined {
    return this.#scope ? [this.#scope] : undefined;
  }

  async #send(
    method: string,
    path: string,
    init: { body?: unknown; query?: Record<string, unknown> } = {},
  ): Promise<unknown> {
    const url = new URL(this.#baseUrl + path);
    for (const [key, value] of Object.entries(init.query ?? {})) {
      if (value !== undefined && value !== null) url.searchParams.set(key, String(value));
    }

    for (let attempt = 1; ; attempt++) {
      let response: Response | null = null;
      // A controller with a timer we can clear, rather than
      // AbortSignal.timeout(), which leaves one uncancellable timer per request
      // alive for the full timeout even after the response has arrived.
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), this.#timeoutMs);
      try {
        // Built up rather than declared in one literal: exactOptionalPropertyTypes
        // rejects an explicit `body: undefined`, and a GET must not carry one.
        const request: RequestInit = {
          method,
          headers: this.#headers,
          signal: controller.signal,
        };
        if (init.body !== undefined) {
          request.headers = { ...this.#headers, "Content-Type": "application/json" };
          request.body = JSON.stringify(init.body);
        }
        response = await this.#fetch(url.toString(), request);
        if (!shouldRetry(response, attempt, this.#maxRetries)) return await parse(response);
        // We are about to throw this response away. Discarding one without
        // consuming its body leaks the stream and keeps the connection out of
        // the pool -- which shows up as a process that will not exit, and in a
        // server as sockets that never come back.
        await response.body?.cancel();
      } catch (cause) {
        if (cause instanceof APIError) throw cause;
        if (!shouldRetry(null, attempt, this.#maxRetries)) {
          throw new APIConnectionError(
            `could not reach the Kortex API: ${cause instanceof Error ? cause.message : cause}`,
          );
        }
      } finally {
        clearTimeout(timer);
      }
      await sleep(retryDelayMs(response, attempt, this.#backoffMs));
    }
  }

  /** Any endpoint, decoded but untyped — the escape hatch for the long tail. */
  request(
    method: string,
    path: string,
    init: { body?: unknown; query?: Record<string, unknown> } = {},
  ): Promise<unknown> {
    return this.#send(method.toUpperCase(), path, init);
  }

  // --- auth ---

  /** Create an org and its first user, then authenticate as them. */
  async register(email: string, password: string, orgName: string): Promise<Tokens> {
    const tokens = toTokens(
      await this.#send("POST", "/v1/auth/register", {
        body: { email, password, org_name: orgName },
      }),
    );
    this.setToken(tokens.accessToken);
    return tokens;
  }

  async login(email: string, password: string): Promise<Tokens> {
    const tokens = toTokens(
      await this.#send("POST", "/v1/auth/login", { body: { email, password } }),
    );
    this.setToken(tokens.accessToken);
    return tokens;
  }

  async whoami(): Promise<Record<string, unknown>> {
    const result = await this.#send("GET", "/v1/auth/whoami");
    return result as Record<string, unknown>;
  }

  // --- memories ---

  /**
   * Store a memory.
   *
   * Writing the same text twice folds into the existing memory rather than
   * storing a rival copy — check `.deduped` if you need to know which
   * happened, or pass `force` to insist.
   */
  async remember(body: string, options: RememberOptions = {}): Promise<Memory> {
    const scope = this.#resolveScope(options.scope);
    return toMemory(
      await this.#send("POST", "/v1/memories", {
        body: compact({
          scope_type: scope.type,
          scope_id: scope.id,
          body,
          title: options.title ?? "",
          kind: options.kind,
          sensitivity: options.sensitivity,
          source_type: options.sourceType,
          importance: options.importance,
          pinned: options.pinned ?? false,
          metadata: options.metadata,
          confidence: options.confidence,
          expires_at: options.expiresAt?.toISOString(),
        }),
        query: { embed_inline: options.embedInline ?? false, force: options.force ?? false },
      }),
    );
  }

  /**
   * Hybrid retrieval: vectors and keywords, fused, decay-weighted.
   *
   * Check `.usedVector` — `false` means the embedder was unavailable and this
   * degraded to keyword-only rather than failing.
   */
  async search(query: string, options: SearchOptions = {}): Promise<SearchResult> {
    return toSearchResult(
      await this.#send("POST", "/v1/search", {
        body: compact({
          query,
          scopes: wireScopes(options.scopes ?? this.#defaultScopes()),
          limit: options.limit ?? 20,
          embed_query: options.embedQuery ?? true,
        }),
      }),
    );
  }

  /**
   * Agentic retrieval: the server plans, searches, and re-ranks.
   *
   * Costs LLM tokens where `search` does not. The budgets are ceilings — one
   * too small to plan within degrades to plain hybrid rather than overshooting.
   */
  async recall(query: string, options: RecallOptions = {}): Promise<Recall> {
    return toRecall(
      await this.#send("POST", "/v1/search/recall", {
        body: compact({
          query,
          scopes: wireScopes(options.scopes ?? this.#defaultScopes()),
          synthesize: options.synthesize ?? false,
          max_tokens: options.maxTokens ?? 0,
          per_item_max: options.perItemMax ?? 800,
          latency_budget_ms: options.latencyBudgetMs ?? 0,
          token_budget: options.tokenBudget ?? 0,
        }),
      }),
    );
  }

  /**
   * Back Claude's native `memory_20250818` tool with this scope.
   *
   * Pass the `tool_use` block's `input` straight in and put the result
   * straight back:
   *
   * ```ts
   * for (const block of response.content) {
   *   if (block.type === "tool_use" && block.name === "memory") {
   *     const answer = await kx.memoryTool(block.input);
   *     results.push({
   *       type: "tool_result",
   *       tool_use_id: block.id,
   *       content: answer.content,
   *       is_error: answer.isError,
   *     });
   *   }
   * }
   * ```
   *
   * Claude's memory files become ordinary Kortex memories: governed by the same
   * review gating and PII scanning, visible to the MCP tools and the console,
   * shared across a team, exportable, and soft-deleted rather than erased.
   */
  async memoryTool(
    command: Record<string, unknown>,
    options: { scope?: Scope; sensitivity?: string } = {},
  ): Promise<MemoryToolResult> {
    const scope = this.#resolveScope(options.scope);
    return toMemoryToolResult(
      await this.#send("POST", "/v1/memory-tool", {
        body: compact({
          command,
          scope_type: scope.type,
          scope_id: scope.id,
          sensitivity: options.sensitivity,
        }),
      }),
    );
  }

  async get(memoryId: string): Promise<Memory> {
    return toMemory(await this.#send("GET", `/v1/memories/${memoryId}`));
  }

  async listMemories(options: ListOptions = {}): Promise<Memory[]> {
    const scope = options.scope ?? this.#scope;
    const rows = await this.#send("GET", "/v1/memories", {
      query: compact({
        scope_type: scope?.type,
        scope_id: scope?.id,
        tier: options.tier,
        kind: options.kind,
        limit: options.limit ?? 50,
        offset: options.offset ?? 0,
      }),
    });
    return (Array.isArray(rows) ? rows : []).map(toMemory);
  }

  async update(memoryId: string, options: UpdateOptions): Promise<Memory> {
    return toMemory(
      await this.#send("PATCH", `/v1/memories/${memoryId}`, {
        body: compact({
          title: options.title,
          body: options.body,
          kind: options.kind,
          sensitivity: options.sensitivity,
          importance: options.importance,
          metadata: options.metadata,
        }),
      }),
    );
  }

  /** Soft-delete. The row survives for export and audit; retrieval stops. */
  async forget(memoryId: string): Promise<void> {
    await this.#send("DELETE", `/v1/memories/${memoryId}`);
  }

  /** Exempt from decay, and floored into every recall that matches it. */
  async pin(memoryId: string): Promise<void> {
    await this.#send("POST", `/v1/memories/${memoryId}/pin`);
  }

  async unpin(memoryId: string): Promise<void> {
    await this.#send("DELETE", `/v1/memories/${memoryId}/pin`);
  }

  /** `pin`, `unpin` or `delete` up to 200 memories. Returns the count affected. */
  async bulk(action: "pin" | "unpin" | "delete", memoryIds: string[]): Promise<number> {
    const result = await this.#send("POST", "/v1/memories/bulk", {
      body: { action, public_ids: memoryIds },
    });
    const record = result !== null && typeof result === "object" ? result : {};
    const affected = (record as Record<string, unknown>)["affected"];
    return typeof affected === "number" ? affected : 0;
  }
}

/** Return the decoded body, or throw the error it describes. */
async function parse(response: Response): Promise<unknown> {
  const text = await response.text();
  let body: unknown = null;
  if (text) {
    try {
      body = JSON.parse(text);
    } catch {
      body = null;
    }
  }
  if (response.ok) return body;

  const header = response.headers.get("Retry-After");
  const seconds = header === null ? Number.NaN : Number(header);
  throw errorFor(
    response.status,
    body,
    text,
    Number.isFinite(seconds) ? seconds : undefined,
  );
}
