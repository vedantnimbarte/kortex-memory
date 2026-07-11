import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "../lib/api";
import type { ApiKey, ApiKeyMint } from "../lib/types";
import {
  Banner,
  Button,
  Card,
  Eyebrow,
  EmptyState,
  Input,
  Label,
  Spinner,
  formatDate,
} from "../components/ui";

const SCOPE_PRESETS = ["read:memory", "write:memory", "read:search", "admin"];

export default function KeysPage() {
  const qc = useQueryClient();
  const [minted, setMinted] = useState<ApiKeyMint | null>(null);
  const [copied, setCopied] = useState(false);

  const { data: keys, isLoading, error } = useQuery({
    queryKey: ["api_keys"],
    queryFn: () => api<ApiKey[]>("/v1/api_keys"),
  });

  const revoke = useMutation({
    mutationFn: (publicId: string) => api<void>(`/v1/api_keys/${publicId}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["api_keys"] }),
  });

  return (
    <div className="space-y-6">
      <header>
        <Eyebrow>API keys</Eyebrow>
        <h1 className="mt-2 text-2xl font-semibold text-ink">Keys</h1>
        <p className="mt-2 text-sm text-muted">
          Programmatic access for agents and the MCP server. Secrets are shown once at creation.
        </p>
      </header>

      {minted && (
        <Card className="border-copper/40 p-5">
          <Eyebrow>New key — copy it now</Eyebrow>
          <p className="mt-2 text-xs text-muted">This secret won't be shown again.</p>
          <div className="mt-3 flex items-center gap-2">
            <code className="flex-1 overflow-x-auto rounded-md border border-line bg-bg px-3 py-2 font-mono text-sm text-copper">
              {minted.plaintext}
            </code>
            <Button
              variant="outline"
              onClick={() => {
                void navigator.clipboard.writeText(minted.plaintext);
                setCopied(true);
              }}
            >
              {copied ? "Copied" : "Copy"}
            </Button>
          </div>
          <button
            onClick={() => {
              setMinted(null);
              setCopied(false);
            }}
            className="mt-3 text-xs text-muted hover:text-ink"
          >
            I've saved it — dismiss
          </button>
        </Card>
      )}

      <MintForm
        onMinted={(k) => {
          setMinted(k);
          setCopied(false);
          void qc.invalidateQueries({ queryKey: ["api_keys"] });
        }}
      />

      {isLoading && <Spinner />}
      {error && <Banner>{(error as ApiError).message}</Banner>}
      {keys && keys.length === 0 && <EmptyState title="No keys yet." hint="Mint one above to connect an agent." />}

      <div className="space-y-2">
        {keys?.map((k) => {
          const revoked = !!k.revoked_at;
          return (
            <Card key={k.public_id} className="flex items-center gap-4 p-4">
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="truncate text-sm font-medium text-ink">{k.name}</span>
                  {revoked && (
                    <span className="font-mono text-[10px] uppercase tracking-wider text-danger">revoked</span>
                  )}
                </div>
                <p className="mt-0.5 font-mono text-xs text-faint">
                  {k.prefix}··· · {k.scopes.join(", ") || "no scopes"}
                </p>
              </div>
              <div className="text-right font-mono text-[11px] text-faint">
                <p>created {formatDate(k.created_at)}</p>
                <p>last used {formatDate(k.last_used_at)}</p>
              </div>
              {!revoked && (
                <Button size="sm" variant="danger" onClick={() => revoke.mutate(k.public_id)}>
                  Revoke
                </Button>
              )}
            </Card>
          );
        })}
      </div>
    </div>
  );
}

function MintForm({ onMinted }: { onMinted: (k: ApiKeyMint) => void }) {
  const [name, setName] = useState("");
  const [scopes, setScopes] = useState<string[]>(["read:memory", "read:search"]);

  const mint = useMutation({
    mutationFn: () =>
      api<ApiKeyMint>("/v1/api_keys", {
        method: "POST",
        body: JSON.stringify({ name, scopes }),
      }),
    onSuccess: (k) => {
      onMinted(k);
      setName("");
    },
  });

  function submit(e: FormEvent) {
    e.preventDefault();
    mint.mutate();
  }

  function toggle(scope: string) {
    setScopes((cur) => (cur.includes(scope) ? cur.filter((s) => s !== scope) : [...cur, scope]));
  }

  return (
    <Card className="p-5">
      <form onSubmit={submit} className="space-y-4">
        <div>
          <Label>Key name</Label>
          <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="claude-code-laptop" required />
        </div>
        <div>
          <Label>Scopes</Label>
          <div className="flex flex-wrap gap-2">
            {SCOPE_PRESETS.map((s) => (
              <button
                key={s}
                type="button"
                onClick={() => toggle(s)}
                className={`rounded-full border px-3 py-1 font-mono text-xs transition-colors ${
                  scopes.includes(s)
                    ? "border-copper bg-copper/10 text-copper"
                    : "border-line text-muted hover:border-line-bright"
                }`}
              >
                {s}
              </button>
            ))}
          </div>
        </div>
        {mint.error && <Banner>{(mint.error as ApiError).message}</Banner>}
        <div className="flex justify-end">
          <Button type="submit" disabled={mint.isPending || !name.trim()}>
            {mint.isPending ? <Spinner /> : "Mint key"}
          </Button>
        </div>
      </form>
    </Card>
  );
}
