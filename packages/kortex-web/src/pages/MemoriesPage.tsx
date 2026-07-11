import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "../lib/api";
import { useScope } from "../lib/scope";
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

export default function MemoriesPage() {
  const { active } = useScope();
  const qc = useQueryClient();
  const [composing, setComposing] = useState(false);

  const [limit, setLimit] = useState(50);
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

      {memories && memories.length === 0 && (
        <EmptyState
          title="No memories here yet."
          hint="Memories accumulate as your agents work, or you can write one by hand."
          action={active && <Button onClick={() => setComposing(true)}>Write the first one</Button>}
        />
      )}

      <div className="space-y-2.5">
        {memories?.map((m) => (
          <Link key={m.public_id} to={`/app/memories/${m.public_id}`} className="block">
            <Card className="p-4 transition-colors hover:border-line-bright">
              <div className="flex items-center gap-2">
                <TierChip tier={m.tier} />
                <SensitivityChip level={m.sensitivity} />
                <span className="font-mono text-[10px] uppercase tracking-wider text-faint">{m.kind}</span>
                {m.pinned && <span className="text-xs text-copper">● pinned</span>}
                <span className="ml-auto text-xs text-faint">{formatDate(m.created_at)}</span>
              </div>
              <p className="mt-2 text-sm font-medium text-ink">{m.title || "Untitled"}</p>
              <p className="mt-1 line-clamp-2 text-sm text-muted">{m.body}</p>
              <div className="mt-3 flex items-center gap-4">
                <div className="w-32">
                  <DecayMeter value={m.decay_score} />
                </div>
                <span className="font-mono text-[10px] text-faint">accessed {m.access_count}×</span>
                <MonoId id={m.public_id} />
              </div>
            </Card>
          </Link>
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
