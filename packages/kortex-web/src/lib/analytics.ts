// Colors + shaping for the dashboard. Aggregation itself now lives server-side
// (`GET /v1/analytics/summary`), which counts the whole live set in SQL — this
// file only attaches colors and fixed orderings to those true totals. The
// color maps are also shared by the memory kind chips.

import type { Analytics, CountSlice, MemoryKind, Memory } from "./types";

// One coherent categorical set, warm-leaning with cool accents, readable on
// the deep-slate chassis.
export const KIND_COLOR: Record<string, string> = {
  fact: "#d98a3d",
  preference: "#6ba3c4",
  decision: "#c9a36b",
  procedure: "#8ca37e",
  code_artifact: "#9a86c4",
  event: "#cf8a6a",
  summary: "#6bc49a",
};

const TIER_COLOR: Record<string, string> = {
  short: "var(--color-tier-short)",
  mid: "var(--color-tier-mid)",
  long: "var(--color-tier-long)",
};

const SENS_COLOR: Record<string, string> = {
  public: "#6ba3c4",
  internal: "#8b97a8",
  confidential: "#c9a36b",
  secret: "#d96a6a",
};

export type Slice = { label: string; value: number; color: string };

export type Summary = {
  count: number;
  pinned: number;
  avgDecay: number;
  totalAccess: number;
  byTier: Slice[];
  byKind: Slice[];
  bySensitivity: Slice[];
  decayHealth: { healthy: number; aging: number; faded: number };
  topAccessed: Memory[];
  /** Per-day new-memory counts, oldest→newest, length === days. */
  timeline: number[];
};

const KINDS: MemoryKind[] = [
  "fact",
  "preference",
  "decision",
  "procedure",
  "code_artifact",
  "event",
  "summary",
];

/** value lookup from the API's present-only count slices. */
function counts(slices: CountSlice[]): Map<string, number> {
  return new Map(slices.map((s) => [s.label, s.value]));
}

/** Fixed-order slices with colors, keeping zeros (for the tier segment bar). */
function ordered(order: string[], byLabel: Map<string, number>, color: Record<string, string>): Slice[] {
  return order.map((label) => ({ label, value: byLabel.get(label) ?? 0, color: color[label] }));
}

/** Shape the API response into the colored summary the dashboard renders. */
export function fromApi(a: Analytics): Summary {
  const kindCounts = counts(a.by_kind);
  const byKind = KINDS.map((k) => ({ label: k, value: kindCounts.get(k) ?? 0, color: KIND_COLOR[k] }))
    .filter((s) => s.value > 0)
    .sort((x, y) => y.value - x.value);

  return {
    count: a.count,
    pinned: a.pinned,
    avgDecay: a.avg_decay,
    totalAccess: a.total_access,
    byTier: ordered(["short", "mid", "long"], counts(a.by_tier), TIER_COLOR),
    byKind,
    bySensitivity: ordered(
      ["public", "internal", "confidential", "secret"],
      counts(a.by_sensitivity),
      SENS_COLOR,
    ).filter((s) => s.value > 0),
    decayHealth: a.decay_health,
    topAccessed: a.top_accessed,
    timeline: a.timeline,
  };
}
