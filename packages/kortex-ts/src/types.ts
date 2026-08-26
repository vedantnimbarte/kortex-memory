/**
 * Typed views over the JSON the API returns.
 *
 * Every `from*` **ignores keys it does not know**. That is the forward-compat
 * contract: a server that grows a field does not break clients that have not
 * been upgraded. The raw payload stays on `.raw` so a new field is reachable
 * before this package catches up.
 */

type Json = Record<string, unknown>;

function obj(value: unknown): Json {
  return value !== null && typeof value === "object" ? (value as Json) : {};
}

function str(value: unknown, fallback = ""): string {
  return typeof value === "string" ? value : fallback;
}

function num(value: unknown, fallback = 0): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function bool(value: unknown): boolean {
  return value === true;
}

function list(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

/** A scope filter. Types are `org` | `workspace` | `project` | `session`. */
export type Scope = { type: string; id: number };

/**
 * Another memory that disagrees with the one carrying this note.
 *
 * `relation` is stated from the annotated memory's point of view:
 * `superseded_by` means *this* memory is the stale side.
 */
export interface ConflictNote {
  publicId: string;
  title: string;
  relation: string;
  createdAt: string;
}

export interface Memory {
  /** The `public_id`. Everything that takes a memory takes this. */
  id: string;
  title: string;
  body: string;
  kind: string;
  scopeType: string;
  scopeId: number;
  sensitivity: string;
  tier: string;
  importance: number;
  pinned: boolean;
  metadata: Json;
  trust: string;
  /** Only `approved` is retrievable; `pending` is waiting on a human. */
  reviewStatus: string;
  reviewReason: string | null;
  /** True when `reviewStatus === "pending"`. Stored, but invisible to recall. */
  pendingReview: boolean;
  /** `pending`/`failed` mean this is not in vector search yet. Keyword search still finds it. */
  embeddingState: string;
  /** True when a write folded into an existing identical memory. Create responses only. */
  deduped: boolean;
  createdAt: string;
  updatedAt: string;
  raw: Json;
}

export interface SearchHit {
  id: string;
  title: string;
  body: string;
  score: number;
  tier: string;
  sensitivity: string;
  importance: number;
  decayScore: number;
  pinned: boolean;
  /** Non-empty means something in the corpus contradicts this hit. */
  conflicts: ConflictNote[];
  raw: Json;
}

export interface SearchResult {
  hits: SearchHit[];
  /**
   * False means the embedder was unavailable and this was keyword-only. The
   * results are still real, just ranked without semantics — worth logging.
   */
  usedVector: boolean;
}

export interface Citation {
  id: string;
  title: string;
  score: number;
}

/** What a recall cost. */
export interface Usage {
  mode: string;
  tokensIn: number;
  tokensOut: number;
  totalTokens: number;
  llmCalls: number;
  hops: number;
  latencyMs: number;
  /** `null` means the model has no configured price, not that it was free. */
  costUsd: number | null;
  budgetExhausted: boolean;
}

/** A context bundle: what to put in the prompt, and what it cost to pick. */
export interface Recall {
  query: string;
  /** Only set when `synthesize: true` was asked for. */
  answer: string | null;
  citations: Citation[];
  candidates: SearchHit[];
  usedTokens: number;
  planTrace: string[];
  planRationale: string;
  hops: number;
  stoppedReason: string;
  usage: Usage;
  raw: Json;
}

export interface Tokens {
  accessToken: string;
  refreshToken: string;
  expiresIn: number;
}

// --- parsers ---------------------------------------------------------------

export function toConflictNote(value: unknown): ConflictNote {
  const d = obj(value);
  return {
    publicId: str(d["public_id"]),
    title: str(d["title"]),
    relation: str(d["relation"]),
    createdAt: str(d["created_at"]),
  };
}

export function toMemory(value: unknown): Memory {
  const d = obj(value);
  const reviewStatus = str(d["review_status"], "approved");
  return {
    id: str(d["public_id"]),
    title: str(d["title"]),
    body: str(d["body"]),
    kind: str(d["kind"]),
    scopeType: str(d["scope_type"]),
    scopeId: num(d["scope_id"]),
    sensitivity: str(d["sensitivity"]),
    tier: str(d["tier"]),
    importance: num(d["importance"]),
    pinned: bool(d["pinned"]),
    metadata: obj(d["metadata"]),
    trust: str(d["trust"], "medium"),
    reviewStatus,
    reviewReason: typeof d["review_reason"] === "string" ? d["review_reason"] : null,
    pendingReview: reviewStatus === "pending",
    embeddingState: str(d["embedding_state"], "pending"),
    deduped: bool(d["deduped"]),
    createdAt: str(d["created_at"]),
    updatedAt: str(d["updated_at"]),
    raw: d,
  };
}

export function toSearchHit(value: unknown): SearchHit {
  const d = obj(value);
  return {
    id: str(d["public_id"]),
    title: str(d["title"]),
    body: str(d["body"]),
    score: num(d["score"], num(d["final_score"])),
    tier: str(d["tier"]),
    sensitivity: str(d["sensitivity"]),
    importance: num(d["importance"]),
    decayScore: num(d["decay_score"]),
    pinned: bool(d["pinned"]),
    conflicts: list(d["conflicts"]).map(toConflictNote),
    raw: d,
  };
}

export function toSearchResult(value: unknown): SearchResult {
  const d = obj(value);
  return {
    hits: list(d["hits"]).map(toSearchHit),
    usedVector: bool(d["used_vector"]),
  };
}

export function toUsage(value: unknown): Usage {
  const d = obj(value);
  return {
    mode: str(d["mode"]),
    tokensIn: num(d["tokens_in"]),
    tokensOut: num(d["tokens_out"]),
    totalTokens: num(d["total_tokens"]),
    llmCalls: num(d["llm_calls"]),
    hops: num(d["hops"]),
    latencyMs: num(d["latency_ms"]),
    costUsd: typeof d["cost_usd"] === "number" ? d["cost_usd"] : null,
    budgetExhausted: bool(d["budget_exhausted"]),
  };
}

export function toRecall(value: unknown): Recall {
  const d = obj(value);
  return {
    query: str(d["query"]),
    answer: typeof d["answer"] === "string" ? d["answer"] : null,
    citations: list(d["citations"]).map((c) => {
      const h = obj(c);
      return { id: str(h["public_id"]), title: str(h["title"]), score: num(h["score"]) };
    }),
    candidates: list(d["candidates"]).map(toSearchHit),
    usedTokens: num(d["used_tokens"]),
    planTrace: list(d["plan_trace"]).map((s) => str(s)),
    planRationale: str(d["plan_rationale"]),
    hops: num(d["hops"]),
    stoppedReason: str(d["stopped_reason"]),
    usage: toUsage(d["usage"]),
    raw: d,
  };
}

export function toTokens(value: unknown): Tokens {
  const d = obj(value);
  return {
    accessToken: str(d["access_token"]),
    refreshToken: str(d["refresh_token"]),
    expiresIn: num(d["expires_in"]),
  };
}

/**
 * The candidates as one block of text, ready to drop into a prompt.
 *
 * The single most common thing anyone does with a recall, so it ships here
 * instead of being rewritten in every integration.
 */
export function asPrompt(bundle: Recall, separator = "\n\n"): string {
  return bundle.candidates
    .map((c) => (c.title ? `${c.title}\n${c.body}`.trim() : c.body))
    .join(separator);
}

/**
 * The answer to one of Claude's `memory_20250818` commands.
 *
 * Both fields go straight onto the `tool_result` block. Claude reads the text
 * and corrects itself, so a failed command is a normal return rather than a
 * thrown error: throwing would force every integration to catch it and turn it
 * back into a string anyway.
 */
export interface MemoryToolResult {
  content: string;
  isError: boolean;
}

export function toMemoryToolResult(value: unknown): MemoryToolResult {
  const d = obj(value);
  return { content: str(d["content"]), isError: bool(d["is_error"]) };
}
