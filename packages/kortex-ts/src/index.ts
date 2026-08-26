/**
 * Kortex Memory — TypeScript client.
 *
 * ```ts
 * import { Kortex } from "@kortex/client";
 *
 * const kx = new Kortex({ scope: { type: "project", id: 7 } });
 *
 * await kx.remember("We chose Postgres over DynamoDB for the ledger: we need joins.");
 *
 * const { hits } = await kx.search("which database for the ledger");
 * for (const hit of hits) console.log(hit.score, hit.title);
 * ```
 *
 * With no arguments the constructor reads `KORTEX_API_KEY` and `KORTEX_API_URL`.
 */

export { Kortex, VERSION, retryDelayMs, shouldRetry } from "./client.js";
export type {
  KortexOptions,
  ListOptions,
  RecallOptions,
  RememberOptions,
  SearchOptions,
  UpdateOptions,
} from "./client.js";
export {
  APIConnectionError,
  APIError,
  AuthenticationError,
  ConflictError,
  InternalServerError,
  KortexError,
  NotFoundError,
  PlanLimitError,
  RateLimitError,
  ValidationError,
} from "./errors.js";
export { asPrompt } from "./types.js";
export type {
  Citation,
  ConflictNote,
  Memory,
  Recall,
  Scope,
  SearchHit,
  SearchResult,
  Tokens,
  Usage,
} from "./types.js";
