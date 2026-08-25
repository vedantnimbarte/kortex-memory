// The review inbox.
//
// Competing memory products ship dashboards that are read-only telemetry —
// charts of how much you stored. The complaint that keeps coming up is the
// opposite one: "expose what memories have been stored so that humans can
// review and verify it over time". This is that surface, and it is the reason
// Kortex having a real console is worth something.
//
// Two things put a memory here: a low-trust write that reads as instructions
// to a model, or a write the project decided to gate. One queue either way —
// two inboxes would mean one nobody checks.
import { useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "../lib/api";
import type { Memory } from "../lib/types";
import {
  Banner,
  Button,
  Card,
  Eyebrow,
  EmptyState,
  MonoId,
  SensitivityChip,
  Spinner,
  formatDate,
  relativeTime,
} from "../components/ui";

type ReviewItem = {
  memory: Memory;
  reason: string;
  similar: Memory[];
};

type ReviewQueue = { total: number; items: ReviewItem[] };

export default function ReviewPage() {
  const queryClient = useQueryClient();
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [error, setError] = useState<string | null>(null);

  const { data, isLoading } = useQuery({
    queryKey: ["review-queue"],
    queryFn: () => api<ReviewQueue>("/v1/review?limit=50"),
  });

  const refresh = () => {
    setSelected(new Set());
    void queryClient.invalidateQueries({ queryKey: ["review-queue"] });
    // The queue count sits in the nav and the dashboard; both go stale the
    // moment something is decided here.
    void queryClient.invalidateQueries({ queryKey: ["memories"] });
  };

  const decide = useMutation({
    mutationFn: ({ id, approve }: { id: string; approve: boolean }) =>
      api<Memory>(`/v1/review/${id}/${approve ? "approve" : "reject"}`, { method: "POST" }),
    onSuccess: refresh,
    onError: (e) => setError(e instanceof ApiError ? e.message : String(e)),
  });

  const decideMany = useMutation({
    mutationFn: (approve: boolean) =>
      api<{ reviewed: number; skipped: number }>("/v1/review/bulk", {
        method: "POST",
        body: JSON.stringify({ public_ids: [...selected], approve }),
      }),
    onSuccess: refresh,
    onError: (e) => setError(e instanceof ApiError ? e.message : String(e)),
  });

  const toggle = (id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  if (isLoading) return <Spinner />;

  const items = data?.items ?? [];

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <Eyebrow>Review</Eyebrow>
          <h1 className="text-2xl font-semibold">Held for review</h1>
          <p className="mt-1 max-w-2xl text-sm text-slate-500">
            These memories are stored but invisible to recall. Nothing here reaches an agent
            until it is approved.
          </p>
        </div>
        {data && data.total > 0 && (
          <span className="rounded-full bg-amber-100 px-3 py-1 text-sm font-medium text-amber-800">
            {data.total} waiting
          </span>
        )}
      </div>

      {error && <Banner tone="error">{error}</Banner>}

      {selected.size > 0 && (
        <Card className="flex items-center justify-between gap-4">
          <span className="text-sm text-slate-600">{selected.size} selected</span>
          <div className="flex gap-2">
            <Button variant="ghost" onClick={() => setSelected(new Set())}>
              Clear
            </Button>
            <Button variant="danger" onClick={() => decideMany.mutate(false)}>
              Reject selected
            </Button>
            <Button onClick={() => decideMany.mutate(true)}>Approve selected</Button>
          </div>
        </Card>
      )}

      {items.length === 0 ? (
        <EmptyState
          title="Nothing waiting"
          hint="Memories appear here when a project gates writes, or when content from an untrusted source reads as instructions to a model."
        />
      ) : (
        <div className="space-y-4">
          {items.map(({ memory, reason, similar }) => (
            <Card key={memory.public_id} className="space-y-3">
              <div className="flex items-start gap-3">
                <input
                  type="checkbox"
                  className="mt-1.5"
                  checked={selected.has(memory.public_id)}
                  onChange={() => toggle(memory.public_id)}
                  aria-label={`Select ${memory.title || memory.public_id}`}
                />
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <Link
                      to={`/app/memories/${memory.public_id}`}
                      className="font-medium hover:underline"
                    >
                      {memory.title || "(untitled)"}
                    </Link>
                    <SensitivityChip level={memory.sensitivity} />
                    <span className="rounded bg-slate-100 px-1.5 py-0.5 text-xs text-slate-600">
                      {memory.kind}
                    </span>
                    {memory.trust && memory.trust !== "high" && (
                      <span className="rounded bg-slate-100 px-1.5 py-0.5 text-xs text-slate-600">
                        {memory.trust} trust
                      </span>
                    )}
                  </div>
                  <p className="mt-1 whitespace-pre-wrap text-sm text-slate-700">{memory.body}</p>
                  <div className="mt-2 flex flex-wrap items-center gap-3 text-xs text-slate-500">
                    <MonoId id={memory.public_id} />
                    <span>{relativeTime(memory.created_at)}</span>
                    <span>{formatDate(memory.created_at)}</span>
                  </div>
                </div>
              </div>

              {reason && (
                <div className="rounded border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">
                  <span className="font-medium">Held because:</span> {reason}
                </div>
              )}

              {/* The decision a reviewer actually has to make is usually "is
                  this new, or the fourth restatement of something already
                  stored" — so show what it resembles rather than making them
                  go and search. */}
              {similar.length > 0 && (
                <details className="rounded border border-slate-200 bg-slate-50 px-3 py-2">
                  <summary className="cursor-pointer text-sm text-slate-600">
                    {similar.length} similar memor{similar.length === 1 ? "y" : "ies"} already
                    approved
                  </summary>
                  <ul className="mt-2 space-y-2">
                    {similar.map((other) => (
                      <li key={other.public_id} className="text-sm text-slate-600">
                        <Link
                          to={`/app/memories/${other.public_id}`}
                          className="font-medium hover:underline"
                        >
                          {other.title || "(untitled)"}
                        </Link>
                        <p className="text-slate-500">{other.body.slice(0, 200)}</p>
                      </li>
                    ))}
                  </ul>
                </details>
              )}

              <div className="flex justify-end gap-2">
                <Button
                  variant="danger"
                  onClick={() => decide.mutate({ id: memory.public_id, approve: false })}
                >
                  Reject
                </Button>
                <Button onClick={() => decide.mutate({ id: memory.public_id, approve: true })}>
                  Approve
                </Button>
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
