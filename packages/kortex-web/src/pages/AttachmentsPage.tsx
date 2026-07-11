import { useRef, useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "../lib/api";
import { useScope } from "../lib/scope";
import { useToast } from "../lib/toast";
import type { Attachment, AttachmentPresign, AttachmentSearch } from "../lib/types";
import {
  Banner,
  Button,
  Card,
  Eyebrow,
  EmptyState,
  Input,
  SensitivityChip,
  Spinner,
  formatDate,
} from "../components/ui";

function humanSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

const STATUS_COLOR: Record<string, string> = {
  ready: "text-ok",
  processing: "text-tier-mid",
  pending: "text-faint",
  failed: "text-danger",
};

export default function AttachmentsPage() {
  const { active } = useScope();
  const qc = useQueryClient();
  const toast = useToast();
  const fileRef = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);

  const scopeKey = active ? `${active.scope_type}:${active.scope_id}` : "none";
  const { data: items, isLoading } = useQuery({
    queryKey: ["attachments", scopeKey],
    queryFn: () => {
      const p = new URLSearchParams({ limit: "100" });
      if (active) {
        p.set("scope_type", active.scope_type);
        p.set("scope_id", String(active.scope_id));
      }
      return api<Attachment[]>(`/v1/attachments?${p}`);
    },
    enabled: !!active,
  });

  const del = useMutation({
    mutationFn: (id: string) => api<void>(`/v1/attachments/${id}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["attachments"] }),
  });

  async function upload(file: File) {
    if (!active) return;
    setUploading(true);
    try {
      // 1. presign  2. PUT bytes straight to storage  3. finalize
      const { attachment, upload } = await api<AttachmentPresign>("/v1/attachments/presign", {
        method: "POST",
        body: JSON.stringify({
          scope_type: active.scope_type,
          scope_id: active.scope_id,
          filename: file.name,
          mime: file.type || null,
          size_hint: file.size,
        }),
      });
      const put = await fetch(upload.url, { method: upload.method, headers: upload.headers, body: file });
      if (!put.ok) throw new Error(`upload failed (${put.status}) — check storage CORS`);
      await api(`/v1/attachments/${attachment.public_id}/finalize`, {
        method: "POST",
        body: JSON.stringify({ size_bytes: file.size, mime: file.type || null }),
      });
      toast(`Uploaded ${file.name}`, "ok");
      void qc.invalidateQueries({ queryKey: ["attachments"] });
    } catch (e) {
      toast(e instanceof Error ? e.message : "upload failed", "error");
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  return (
    <div className="space-y-6">
      <header className="flex items-end justify-between gap-4">
        <div>
          <Eyebrow>Attachments</Eyebrow>
          <h1 className="mt-2 text-2xl font-semibold text-ink">{active ? active.label : "Files"}</h1>
        </div>
        <div>
          <input
            ref={fileRef}
            type="file"
            className="hidden"
            onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])}
          />
          <Button onClick={() => fileRef.current?.click()} disabled={!active || uploading}>
            {uploading ? <Spinner /> : "Upload file"}
          </Button>
        </div>
      </header>

      {!active && <Banner tone="ok">Choose a workspace or project in the top bar to manage files.</Banner>}

      <AttachmentSearchBox />

      {isLoading && <Spinner />}
      {items && items.length === 0 && (
        <EmptyState title="No files here yet." hint="Upload documents to make them searchable by your agents." />
      )}

      <div className="space-y-2">
        {items?.map((a) => (
          <Card key={a.public_id} className="flex items-center gap-4 p-4">
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-medium text-ink">{a.filename}</p>
              <p className="mt-0.5 flex items-center gap-2 font-mono text-[11px] text-faint">
                <span className={STATUS_COLOR[a.processing_status]}>{a.processing_status}</span>
                <span>·</span>
                <span>{humanSize(a.size_bytes)}</span>
                <span>·</span>
                <SensitivityChip level={a.sensitivity} />
                {a.processing_error && <span className="text-danger">· {a.processing_error}</span>}
              </p>
            </div>
            <span className="font-mono text-[11px] text-faint">{formatDate(a.created_at)}</span>
            <Button size="sm" variant="danger" onClick={() => del.mutate(a.public_id)}>
              Delete
            </Button>
          </Card>
        ))}
      </div>
    </div>
  );
}

function AttachmentSearchBox() {
  const { active } = useScope();
  const [query, setQuery] = useState("");
  const [result, setResult] = useState<AttachmentSearch | null>(null);
  const search = useMutation({
    mutationFn: () => {
      const body: Record<string, unknown> = { query, limit: 15 };
      if (active) body.scopes = [{ scope_type: active.scope_type, scope_id: active.scope_id }];
      return api<AttachmentSearch>("/v1/attachments/search", { method: "POST", body: JSON.stringify(body) });
    },
    onSuccess: setResult,
  });

  return (
    <Card className="p-4">
      <form
        onSubmit={(e: FormEvent) => {
          e.preventDefault();
          if (query.trim()) search.mutate();
        }}
        className="flex gap-2"
      >
        <Input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search inside documents…" className="flex-1" />
        <Button type="submit" size="sm" disabled={search.isPending || !query.trim()}>
          {search.isPending ? <Spinner /> : "Search"}
        </Button>
      </form>
      {search.error && <div className="mt-3"><Banner>{(search.error as ApiError).message}</Banner></div>}
      {result && (
        <ul className="mt-3 space-y-2">
          {result.hits.length === 0 && <li className="text-xs text-faint">No matches.</li>}
          {result.hits.map((h, i) => (
            <li key={i} className="rounded-lg border border-line bg-bg p-3">
              <div className="flex items-center gap-2">
                <span className="text-sm text-ink">{h.filename}</span>
                <span className="font-mono text-[10px] text-faint">chunk {h.chunk_index}</span>
                <span className="ml-auto font-mono text-[11px] text-copper">{h.score.toFixed(3)}</span>
              </div>
              <p className="mt-1 line-clamp-2 text-xs text-muted">{h.content}</p>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
