/**
 * What went wrong, as something you can catch.
 *
 * The API speaks RFC 7807, so every error body carries `title` and `detail`.
 * Those are surfaced rather than a bare status line, because "memory limit
 * reached for the free plan (25,000 memories)" is actionable and
 * `Error: 402` is not.
 *
 * The hierarchy is shallow on purpose. Callers branch on maybe three of these
 * — retry on RateLimitError, prompt for a key on AuthenticationError, show the
 * message for everything else — and a deeper tree would only be more names to
 * learn for no extra decision.
 */

/** Base for everything this package throws. Catch this to catch all. */
export class KortexError extends Error {
  constructor(message: string) {
    super(message);
    this.name = new.target.name;
  }
}

/** The server answered, and the answer was an error. */
export class APIError extends KortexError {
  readonly status: number;
  readonly title: string;
  readonly detail: string;
  readonly body: Record<string, unknown>;
  /** Seconds the server asked us to wait, when it said. Only 429/503 set it. */
  readonly retryAfter: number | undefined;

  constructor(
    message: string,
    opts: {
      status: number;
      title?: string;
      detail?: string;
      body?: Record<string, unknown>;
      retryAfter?: number | undefined;
    },
  ) {
    super(message);
    this.status = opts.status;
    this.title = opts.title ?? "";
    this.detail = opts.detail ?? "";
    this.body = opts.body ?? {};
    this.retryAfter = opts.retryAfter;
  }
}

/** 401/403 — missing, expired, or insufficient credentials. */
export class AuthenticationError extends APIError {}

/** 404. */
export class NotFoundError extends APIError {}

/** 409 — most often a slug or email already taken. */
export class ConflictError extends APIError {}

/** 400/422 — rejected before it reached the domain. */
export class ValidationError extends APIError {}

/** 402 — the org is at its plan's cap. Not retryable; upgrade or delete. */
export class PlanLimitError extends APIError {}

/** 429. Retried automatically first; you see it once the retries run out. */
export class RateLimitError extends APIError {}

/** 5xx. Also retried before you ever see it. */
export class InternalServerError extends APIError {}

/** The request never got an answer — DNS, TLS, timeout, refused, aborted. */
export class APIConnectionError extends KortexError {}

const BY_STATUS: Record<number, new (m: string, o: never) => APIError> = {
  400: ValidationError,
  401: AuthenticationError,
  402: PlanLimitError,
  403: AuthenticationError,
  404: NotFoundError,
  409: ConflictError,
  422: ValidationError,
  429: RateLimitError,
};

/** Map an error response onto the narrowest error class that fits. */
export function errorFor(
  status: number,
  body: unknown,
  text: string,
  retryAfter?: number | undefined,
): APIError {
  const record: Record<string, unknown> =
    body !== null && typeof body === "object" ? (body as Record<string, unknown>) : {};
  const title = typeof record["title"] === "string" ? record["title"] : "";
  const detail = typeof record["detail"] === "string" ? record["detail"] : "";
  const message = detail || title || text.trim() || `HTTP ${status}`;
  const Cls = BY_STATUS[status] ?? (status >= 500 ? InternalServerError : APIError);
  return new Cls(message, { status, title, detail, body: record, retryAfter } as never);
}
