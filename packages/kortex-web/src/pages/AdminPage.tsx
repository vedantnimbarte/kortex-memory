import { useMutation } from "@tanstack/react-query";
import { api, ApiError } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useToast } from "../lib/toast";
import type { AdminTask } from "../lib/types";
import { Banner, Button, Card, Eyebrow, EmptyState, Spinner } from "../components/ui";

const TASKS: { path: string; title: string; detail: string; body?: unknown }[] = [
  {
    path: "/v1/admin/force_decay_tick",
    title: "Run decay tick",
    detail: "Recompute decay scores and demote/promote memories across tiers now.",
  },
  {
    path: "/v1/admin/reindex_embeddings",
    title: "Reindex embeddings",
    detail: "Clear all embeddings and re-embed incrementally in the background.",
    body: { batch_size: 64 },
  },
  {
    path: "/v1/admin/consolidate_tier",
    title: "Consolidate tiers",
    detail: "Run HDBSCAN consolidation to merge redundant long-term memories.",
  },
];

export default function AdminPage() {
  const { user } = useAuth();
  const toast = useToast();

  const run = useMutation({
    mutationFn: (t: (typeof TASKS)[number]) =>
      api<AdminTask>(t.path, { method: "POST", body: t.body ? JSON.stringify(t.body) : undefined }),
    onSuccess: (res: AdminTask) =>
      toast(res.dispatched ? `Dispatched ${res.task}` : `Not dispatched: ${res.detail}`, res.dispatched ? "ok" : "error"),
    onError: (e) => toast((e as ApiError).message, "error"),
  });

  if (!user?.is_superuser) {
    return (
      <div className="space-y-6">
        <header>
          <Eyebrow>Admin</Eyebrow>
          <h1 className="mt-2 text-2xl font-semibold text-ink">Operations</h1>
        </header>
        <EmptyState title="Superuser only." hint="These maintenance tasks require a superuser account." />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <header>
        <Eyebrow>Admin</Eyebrow>
        <h1 className="mt-2 text-2xl font-semibold text-ink">Operations</h1>
        <p className="mt-2 text-sm text-muted">
          Dispatch background maintenance tasks to the worker queue. These run asynchronously.
        </p>
      </header>

      <Banner tone="ok">Tasks are queued on the worker — they return a task id, not a result.</Banner>

      <div className="space-y-3">
        {TASKS.map((t) => (
          <Card key={t.path} className="flex items-center justify-between gap-4 p-5">
            <div>
              <p className="text-sm font-medium text-ink">{t.title}</p>
              <p className="mt-0.5 text-xs text-faint">{t.detail}</p>
            </div>
            <Button
              variant="outline"
              onClick={() => run.mutate(t)}
              disabled={run.isPending}
            >
              {run.isPending && run.variables?.path === t.path ? <Spinner /> : "Run"}
            </Button>
          </Card>
        ))}
      </div>
    </div>
  );
}
