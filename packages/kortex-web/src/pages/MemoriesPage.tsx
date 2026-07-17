import { useMemo, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "../lib/api";
import { useScope } from "../lib/scope";
import { KIND_COLOR } from "../lib/analytics";
import type { Memory, MemoryKind, Sensitivity } from "../lib/types";
import {
  Banner,
  Button,
  Card,
  DecayMeter,
  Eyebrow,
  EmptyState,
  Input,
  Label,
  MonoId,
  Select,
  SensitivityChip,
  Spinner,
  Textarea,
  TierChip,
  formatDate,
} from "../components/ui";

const KINDS: MemoryKind[] = [
  "fact",
  "preference",
  "decision",
  "procedure",
  "code_artifact",
  "event",
  "summary",
];
const SENSITIVITIES: Sensitivity[] = ["public", "internal", "confidential", "secret"];

type SortKey = "recent" | "accessed" | "retention" | "title";
const SORTS: { key: SortKey; label: string; cmp: (a: Memory, b: Memory) => number }[] = [
  { key: "recent", label: "Newest", cmp: (a, b) => b.created_at.localeCompare(a.created_at) },
  { key: "accessed", label: "Most recalled", cmp: (a, b) => b.access_count - a.access_count },
  { key: "retention", label: "Strongest", cmp: (a, b) => b.decay_score - a.decay_score },
  { key: "title", label: "Title A–Z", cmp: (a, b) => (a.title || "").localeCompare(b.title || "") },
];

export default function MemoriesPage() {
  const { active } = useScope();
  const qc = useQueryClient();
  const [composing, setComposing] = useState(false);

  const [limit, setLimit] = useState(50);
  const [filter, setFilter] = useState("");
  const [kindFilter, setKindFilter] = useState<MemoryKind | "">("");
  const [sort, setSort] = useState<SortKey>("recent");
  const [pinnedOnly, setPinnedOnly] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());

  function toggle(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  const bulk = useMutation({
    mutationFn: (action: "pin" | "unpin" | "delete") =>
      api<{ affected: number }>("/v1/memories/bulk", {
        method: "POST",
        body: JSON.stringify({ action, public_ids: [...selected] }),
      }),
    onSuccess: () => {
      setSelected(new Set());
      void qc.invalidateQueries({ queryKey: ["memories"] });
      void qc.invalidateQueries({ queryKey: ["dashboard-analytics"] });
    },
  });

  function runBulk(action: "pin" | "unpin" | "delete") {
    if (action === "delete" && !window.confirm(`Delete ${selected.size} selected memories?`)) return;
    bulk.mutate(action);
  }

  const scopeKey = active ? `${active.scope_type}:${active.scope_id}` : "all";
  const { data: memories, isLoading, error } = useQuery({
    queryKey: ["memories", scopeKey, limit],
    queryFn: () => {
      const params = new URLSearchParams({ limit: String(limit) });
      if (active) {
        params.set("scope_type", active.scope_type);
        params.set("scope_id", String(active.scope_id));
      }
      return api<Memory[]>(`/v1/memories?${params}`);
    },
  });
  const canLoadMore = !!memories && memories.length === limit && limit < 200;

  const visible = useMemo(() => {
    if (!memories) return [];
    const q = filter.trim().toLowerCase();
    const cmp = SORTS.find((s) => s.key === sort)!.cmp;
    return memories
      .filter((m) => !kindFilter || m.kind === kindFilter)
      .filter((m) => !pinnedOnly || m.pinned)
      .filter((m) => !q || (m.title + " " + m.body).toLowerCase().includes(q))
      .sort(cmp);
  }, [memories, filter, kindFilter, sort, pinnedOnly]);

  return (
    <div className="space-y-6">
      <header className="flex items-end justify-between gap-4">
        <div>
          <Eyebrow>Memories</Eyebrow>
          <h1 className="mt-2 text-2xl font-semibold text-ink">
            {active ? active.label : "All memories"}
          </h1>
        </div>
        <Button onClick={() => setComposing((v) => !v)} disabled={!active} variant={composing ? "ghost" : "primary"}>
          {composing ? "Cancel" : "New memory"}
        </Button>
      </header>

      {!active && (
        <Banner tone="ok">Pick a workspace or project in the top bar to add memories.</Banner>
      )}

      {composing && active && (
        <ComposeMemory
          onDone={() => {
            setComposing(false);
            void qc.invalidateQueries({ queryKey: ["memories"] });
          }}
        />
      )}

      {isLoading && <Spinner />}
      {error && <Banner>{(error as ApiError).message}</Banner>}

      {memories && memories.length > 0 && (
        <div className="flex flex-wrap items-center gap-2">
          <Input
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder="Filter loaded memories…"
            className="min-w-40 flex-1"
            aria-label="Filter memories"
          />
          <Select
            value={kindFilter}
            onChange={(e) => setKindFilter(e.target.value as MemoryKind | "")}
            className="w-auto"
            aria-label="Filter by kind"
          >
            <option value="">All kinds</option>
            {KINDS.map((k) => (
              <option key={k} value={k}>
                {k.replace("_", " ")}
              </option>
            ))}
          </Select>
          <Select
            value={sort}
            onChange={(e) => setSort(e.target.value as SortKey)}
            className="w-auto"
            aria-label="Sort memories"
          >
            {SORTS.map((s) => (
              <option key={s.key} value={s.key}>
                {s.label}
              </option>
            ))}
          </Select>
          <button
            onClick={() => setPinnedOnly((v) => !v)}
            className={`rounded-md border px-3 py-2 text-xs transition-colors ${
              pinnedOnly ? "border-copper text-copper" : "border-line text-muted hover:text-ink"
            }`}
          >
            ● Pinned
          </button>
        </div>
      )}

      {memories && memories.length === 0 && (
        <EmptyState
          title="No memories here yet."
          hint="Memories accumulate as your agents work, or you can write one by hand."
          action={active && <Button onClick={() => setComposing(true)}>Write the first one</Button>}
        />
      )}

      {memories && memories.length > 0 && visible.length === 0 && (
        <p className="py-8 text-center text-sm text-faint">Nothing matches those filters.</p>
      )}

      {visible.length > 0 && (
        <div className="flex items-center gap-3 text-xs text-muted">
          <label className="flex cursor-pointer items-center gap-2">
            <input
              type="checkbox"
              className="accent-copper"
              checked={selected.size > 0 && visible.every((m) => selected.has(m.public_id))}
              ref={(el) => {
                if (el)
                  el.indeterminate =
                    selected.size > 0 && !visible.every((m) => selected.has(m.public_id));
              }}
              onChange={(e) =>
                setSelected(e.target.checked ? new Set(visible.map((m) => m.public_id)) : new Set())
              }
            />
            Select all ({visible.length})
          </label>
          {selected.size > 0 && (
            <div className="flex items-center gap-2">
              <span className="text-copper">{selected.size} selected</span>
              <Button variant="ghost" onClick={() => runBulk("pin")} disabled={bulk.isPending}>
                Pin
              </Button>
              <Button variant="ghost" onClick={() => runBulk("unpin")} disabled={bulk.isPending}>
                Unpin
              </Button>
              <Button variant="ghost" onClick={() => runBulk("delete")} disabled={bulk.isPending}>
                Delete
              </Button>
            </div>
          )}
        </div>
      )}

      {bulk.error && <Banner>{(bulk.error as ApiError).message}</Banner>}

      <div className="space-y-2.5">
        {visible.map((m) => (
          <MemoryRow
            key={m.public_id}
            memory={m}
            selected={selected.has(m.public_id)}
            onToggle={() => toggle(m.public_id)}
          />
        ))}
      </div>

      {canLoadMore && (
        <div className="flex justify-center">
          <Button variant="ghost" onClick={() => setLimit((l) => Math.min(200, l + 50))}>
            Load more
          </Button>
        </div>
      )}
    </div>
  );
}

function MemoryRow({
  memory: m,
  selected,
  onToggle,
}: {
  memory: Memory;
  selected: boolean;
  onToggle: () => void;
}) {
  const qc = useQueryClient();
  const pin = useMutation({
    mutationFn: (next: boolean) =>
      api<Memory>(`/v1/memories/${m.public_id}/pin`, { method: next ? "POST" : "DELETE" }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["memories"] }),
  });

  return (
    <Card className={`panel panel-hover p-4 ${selected ? "ring-1 ring-copper" : ""}`}>
      <div className="flex items-center gap-2">
        <input
          type="checkbox"
          className="accent-copper"
          checked={selected}
          onChange={onToggle}
          aria-label="Select memory"
        />
        <TierChip tier={m.tier} />
        <SensitivityChip level={m.sensitivity} />
        <span
          className="font-mono text-[10px] uppercase tracking-wider"
          style={{ color: KIND_COLOR[m.kind] ?? "var(--color-faint)" }}
        >
          {m.kind.replace("_", " ")}
        </span>
        <button
          onClick={() => pin.mutate(!m.pinned)}
          disabled={pin.isPending}
          title={m.pinned ? "Unpin" : "Pin"}
          aria-pressed={m.pinned}
          className={`ml-auto text-xs transition-colors disabled:opacity-40 ${
            m.pinned ? "text-copper" : "text-faint hover:text-copper"
          }`}
        >
          {m.pinned ? "● pinned" : "○ pin"}
        </button>
        <span className="text-xs text-faint">{formatDate(m.created_at)}</span>
      </div>
      <Link to={`/app/memories/${m.public_id}`} className="mt-2 block">
        <p className="text-sm font-medium text-ink">{m.title || "Untitled"}</p>
        <p className="mt-1 line-clamp-2 text-sm text-muted">{m.body}</p>
      </Link>
      <div className="mt-3 flex items-center gap-4">
        <div className="w-32">
          <DecayMeter value={m.decay_score} />
        </div>
        <span className="font-mono text-[10px] text-faint">accessed {m.access_count}×</span>
        <MonoId id={m.public_id} />
      </div>
    </Card>
  );
}

function ComposeMemory({ onDone }: { onDone: () => void }) {
  const { active } = useScope();
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [kind, setKind] = useState<MemoryKind>("fact");
  const [sensitivity, setSensitivity] = useState<Sensitivity>("internal");

  const create = useMutation({
    mutationFn: () =>
      api<Memory>("/v1/memories", {
        method: "POST",
        body: JSON.stringify({
          scope_type: active!.scope_type,
          scope_id: active!.scope_id,
          title,
          body,
          kind,
          sensitivity,
        }),
      }),
    onSuccess: onDone,
  });

  function submit(e: FormEvent) {
    e.preventDefault();
    create.mutate();
  }

  return (
    <Card className="p-5">
      <form onSubmit={submit} className="space-y-4">
        <div>
          <Label>Title</Label>
          <Input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Short handle for this memory" />
        </div>
        <div>
          <Label>Body</Label>
          <Textarea
            required
            rows={5}
            value={body}
            onChange={(e) => setBody(e.target.value)}
            placeholder="The thing worth remembering…"
          />
        </div>
        <div className="grid grid-cols-2 gap-4">
          <div>
            <Label>Kind</Label>
            <Select value={kind} onChange={(e) => setKind(e.target.value as MemoryKind)}>
              {KINDS.map((k) => (
                <option key={k} value={k}>
                  {k}
                </option>
              ))}
            </Select>
          </div>
          <div>
            <Label>Sensitivity</Label>
            <Select value={sensitivity} onChange={(e) => setSensitivity(e.target.value as Sensitivity)}>
              {SENSITIVITIES.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </Select>
          </div>
        </div>
        {create.error && <Banner>{(create.error as ApiError).message}</Banner>}
        <div className="flex justify-end gap-2">
          <Button type="submit" disabled={create.isPending || !body.trim()}>
            {create.isPending ? <Spinner /> : "Store memory"}
          </Button>
        </div>
      </form>
    </Card>
  );
}
