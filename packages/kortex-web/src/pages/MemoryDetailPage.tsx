import { useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "../lib/api";
import { useToast } from "../lib/toast";
import type { LinkedMemory, Memory, MemoryKind, Sensitivity } from "../lib/types";
import {
  Banner,
  Button,
  Card,
  Eyebrow,
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

export default function MemoryDetailPage() {
  const { id = "" } = useParams();
  const nav = useNavigate();
  const qc = useQueryClient();
  const toast = useToast();
  const [editing, setEditing] = useState(false);

  const { data: m, isLoading, error } = useQuery({
    queryKey: ["memory", id],
    queryFn: () => api<Memory>(`/v1/memories/${id}`),
  });

  const pin = useMutation({
    mutationFn: (next: boolean) => api<Memory>(`/v1/memories/${id}/pin`, { method: next ? "POST" : "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["memory", id] }),
  });

  const remove = useMutation({
    mutationFn: () => api<void>(`/v1/memories/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["memories"] });
      toast("Memory deleted", "ok");
      nav("/app/memories");
    },
  });

  if (isLoading) return <Spinner />;
  if (error) return <Banner>{(error as ApiError).message}</Banner>;
  if (!m) return null;

  if (editing) return <EditMemory memory={m} onDone={() => { setEditing(false); void qc.invalidateQueries({ queryKey: ["memory", id] }); }} />;

  const stats: [string, string][] = [
    ["Importance", m.importance.toFixed(2)],
    ["Decay", m.decay_score.toFixed(2)],
    ["Accessed", `${m.access_count}×`],
    ["Created", formatDate(m.created_at)],
    ["Updated", formatDate(m.updated_at)],
    ["Last read", formatDate(m.last_accessed_at)],
  ];

  return (
    <div className="space-y-6">
      <Link to="/app/memories" className="text-xs text-muted transition-colors hover:text-copper">
        ← Memories
      </Link>

      <div className="flex items-center gap-2">
        <TierChip tier={m.tier} />
        <SensitivityChip level={m.sensitivity} />
        <span className="font-mono text-[10px] uppercase tracking-wider text-faint">{m.kind}</span>
        <div className="ml-auto flex gap-2">
          <Button size="sm" variant="outline" onClick={() => setEditing(true)}>
            Edit
          </Button>
          <Button size="sm" variant="outline" onClick={() => pin.mutate(!m.pinned)} disabled={pin.isPending}>
            {m.pinned ? "Unpin" : "Pin"}
          </Button>
          <Button
            size="sm"
            variant="danger"
            onClick={() => confirm("Delete this memory?") && remove.mutate()}
            disabled={remove.isPending}
          >
            Delete
          </Button>
        </div>
      </div>

      <div>
        <h1 className="text-2xl font-semibold text-ink">{m.title || "Untitled"}</h1>
        <div className="mt-1">
          <MonoId id={m.public_id} full />
        </div>
      </div>

      <Card className="p-5">
        <p className="whitespace-pre-wrap text-sm leading-relaxed text-ink">{m.body}</p>
      </Card>

      <div className="grid grid-cols-2 gap-px overflow-hidden rounded-xl border border-line bg-line sm:grid-cols-3">
        {stats.map(([k, v]) => (
          <div key={k} className="bg-surface px-4 py-3">
            <p className="font-mono text-[10px] uppercase tracking-wider text-faint">{k}</p>
            <p className="mt-1 font-mono text-sm text-ink">{v}</p>
          </div>
        ))}
      </div>

      <LinksSection memoryId={id} />
    </div>
  );
}

function EditMemory({ memory, onDone }: { memory: Memory; onDone: () => void }) {
  const [title, setTitle] = useState(memory.title);
  const [body, setBody] = useState(memory.body);
  const [kind, setKind] = useState<MemoryKind>(memory.kind);
  const [sensitivity, setSensitivity] = useState<Sensitivity>(memory.sensitivity);
  const [importance, setImportance] = useState(memory.importance);
  const toast = useToast();

  const save = useMutation({
    mutationFn: () =>
      api<Memory>(`/v1/memories/${memory.public_id}`, {
        method: "PATCH",
        body: JSON.stringify({ title, body, kind, sensitivity, importance }),
      }),
    onSuccess: () => {
      toast("Memory updated", "ok");
      onDone();
    },
  });

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-semibold text-ink">Edit memory</h1>
      <Card className="p-5">
        <form
          onSubmit={(e: FormEvent) => {
            e.preventDefault();
            save.mutate();
          }}
          className="space-y-4"
        >
          <div>
            <Label>Title</Label>
            <Input value={title} onChange={(e) => setTitle(e.target.value)} />
          </div>
          <div>
            <Label>Body</Label>
            <Textarea required rows={6} value={body} onChange={(e) => setBody(e.target.value)} />
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
          <div>
            <Label>Importance — {importance.toFixed(2)}</Label>
            <input
              type="range"
              min={0}
              max={1}
              step={0.05}
              value={importance}
              onChange={(e) => setImportance(Number(e.target.value))}
              className="w-full accent-copper"
            />
          </div>
          {save.error && <Banner>{(save.error as ApiError).message}</Banner>}
          <div className="flex justify-end gap-2">
            <Button type="button" variant="ghost" onClick={onDone}>
              Cancel
            </Button>
            <Button type="submit" disabled={save.isPending || !body.trim()}>
              {save.isPending ? <Spinner /> : "Save changes"}
            </Button>
          </div>
        </form>
      </Card>
    </div>
  );
}

function LinksSection({ memoryId }: { memoryId: string }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [target, setTarget] = useState("");

  const { data: links } = useQuery({
    queryKey: ["links", memoryId],
    queryFn: () => api<LinkedMemory[]>(`/v1/memories/${memoryId}/links`),
  });

  const add = useMutation({
    mutationFn: () =>
      api(`/v1/memories/${memoryId}/links`, {
        method: "POST",
        body: JSON.stringify({ to_public_id: target.trim(), link_type: "related", weight: 1.0 }),
      }),
    onSuccess: () => {
      setTarget("");
      void qc.invalidateQueries({ queryKey: ["links", memoryId] });
      toast("Linked", "ok");
    },
  });

  const removeLink = useMutation({
    mutationFn: (toId: string) =>
      api(`/v1/memories/${memoryId}/links/${toId}`, {
        method: "DELETE",
        body: JSON.stringify({ to_public_id: toId, link_type: "related" }),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["links", memoryId] }),
  });

  return (
    <Card className="p-5">
      <Eyebrow>Linked memories</Eyebrow>
      <div className="mt-3 space-y-2">
        {links?.length === 0 && <p className="text-xs text-faint">No links yet.</p>}
        {links?.map((l) => (
          <div key={l.public_id} className="flex items-center gap-3">
            <TierChip tier={l.tier} />
            <Link to={`/app/memories/${l.public_id}`} className="min-w-0 flex-1 truncate text-sm text-ink hover:text-copper">
              {l.title || "Untitled"}
            </Link>
            <span className="font-mono text-[10px] uppercase tracking-wider text-faint">{l.link_type}</span>
            <button
              onClick={() => removeLink.mutate(l.public_id)}
              className="text-xs text-muted hover:text-danger"
              aria-label="Remove link"
            >
              ✕
            </button>
          </div>
        ))}
      </div>
      <form
        onSubmit={(e: FormEvent) => {
          e.preventDefault();
          if (target.trim()) add.mutate();
        }}
        className="mt-4 flex gap-2"
      >
        <Input
          value={target}
          onChange={(e) => setTarget(e.target.value)}
          placeholder="Paste a memory ID to link"
          className="flex-1 font-mono text-xs"
        />
        <Button type="submit" size="sm" disabled={add.isPending || !target.trim()}>
          Link
        </Button>
      </form>
      {add.error && <div className="mt-2"><Banner>{(add.error as ApiError).message}</Banner></div>}
    </Card>
  );
}
