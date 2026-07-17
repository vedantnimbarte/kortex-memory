// Runnable self-check for fromApi(). No framework: `npx tsx src/lib/analytics.check.ts`.
// Aggregation is server-side now; this only covers the colorize/order/filter shaping.
import assert from "node:assert/strict";
import { fromApi } from "./analytics";
import type { Analytics } from "./types";

const api: Analytics = {
  count: 6,
  pinned: 1,
  avg_decay: 0.5,
  total_access: 14,
  by_tier: [
    { label: "long", value: 2 },
    { label: "short", value: 1 },
  ], // mid absent → must appear as 0, in fixed order
  by_kind: [
    { label: "decision", value: 1 },
    { label: "fact", value: 3 },
  ],
  by_sensitivity: [{ label: "internal", value: 6 }],
  decay_health: { healthy: 1, aging: 2, faded: 1 },
  top_accessed: [],
  timeline: new Array(14).fill(0),
};

const s = fromApi(api);

// Passthrough.
assert.equal(s.count, 6);
assert.equal(s.pinned, 1);
assert.equal(s.totalAccess, 14);
assert.equal(s.timeline.length, 14);

// Tiers: fixed short/mid/long order, missing mid filled with 0, all colored.
assert.deepEqual(
  s.byTier.map((t) => [t.label, t.value]),
  [["short", 1], ["mid", 0], ["long", 2]],
);
assert.ok(s.byTier.every((t) => typeof t.color === "string" && t.color.length > 0));

// Kinds: sorted desc, fact first; zero-valued kinds dropped.
assert.equal(s.byKind[0].label, "fact");
assert.equal(s.byKind[0].value, 3);
assert.equal(s.byKind.length, 2);

// Sensitivity: only present ones kept.
assert.deepEqual(
  s.bySensitivity.map((x) => x.label),
  ["internal"],
);

console.log("analytics.check: OK");
