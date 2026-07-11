import { useMemo, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { api, ApiError } from "../lib/api";
import { useScope } from "../lib/scope";
import type { Sensitivity } from "../lib/types";
import { Banner, Button, Card, Eyebrow, Label, Select, Spinner, Textarea } from "../components/ui";

type Commit = { sha: string; author?: string; date?: string; message: string };

// Parse `git log --pretty=format:'%H%x09%an%x09%ad%x09%s'` (tab-separated).
// Falls back to "first token = sha, rest = message" for looser pastes.
function parseLog(text: string): Commit[] {
  return text
    .split("\n")
    .map((l) => l.trim())
    .filter(Boolean)
    .map((line) => {
      const parts = line.split("\t");
      if (parts.length >= 4) {
        const [sha, author, date, ...msg] = parts;
        return { sha, author, date, message: msg.join("\t") };
      }
      const sp = line.indexOf(" ");
      return sp > 0
        ? { sha: line.slice(0, sp), message: line.slice(sp + 1) }
        : { sha: line, message: line };
    })
    .filter((c) => c.sha.length >= 4 && c.message.length > 0);
}

export default function IngestPage() {
  const { active } = useScope();
  const [raw, setRaw] = useState("");
  const [sensitivity, setSensitivity] = useState<Sensitivity>("internal");
  const commits = useMemo(() => parseLog(raw), [raw]);

  const ingest = useMutation({
    mutationFn: () =>
      api<{ memories_created: number }>("/v1/ingest/git-log", {
        method: "POST",
        body: JSON.stringify({
          scope_type: active!.scope_type,
          scope_id: active!.scope_id,
          sensitivity,
          commits: commits.slice(0, 1000),
        }),
      }),
  });

  return (
    <div className="max-w-2xl space-y-6">
      <header>
        <Eyebrow>Ingest</Eyebrow>
        <h1 className="mt-2 text-2xl font-semibold text-ink">Import commit history</h1>
        <p className="mt-2 text-sm text-muted">
          Each commit becomes a memory in{" "}
          {active ? <span className="text-copper">{active.label}</span> : "your active scope"}. Paste the
          output of{" "}
          <code className="rounded bg-surface-2 px-1.5 py-0.5 font-mono text-xs text-ink">
            git log --pretty=format:'%H%x09%an%x09%ad%x09%s'
          </code>
          .
        </p>
      </header>

      {!active && <Banner tone="ok">Choose a workspace or project in the top bar first.</Banner>}

      <Card className="p-5">
        <div className="space-y-4">
          <div>
            <Label>Git log</Label>
            <Textarea
              rows={10}
              value={raw}
              onChange={(e) => setRaw(e.target.value)}
              placeholder="a1b2c3d…	Ada	2026-07-01	Fix rate limiter off-by-one"
            />
          </div>
          <div className="flex items-end justify-between gap-4">
            <div className="w-44">
              <Label>Sensitivity</Label>
              <Select value={sensitivity} onChange={(e) => setSensitivity(e.target.value as Sensitivity)}>
                {(["public", "internal", "confidential", "secret"] as Sensitivity[]).map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </Select>
            </div>
            <div className="flex items-center gap-3">
              <span className="font-mono text-xs text-faint">{commits.length} commits parsed</span>
              <Button
                onClick={() => ingest.mutate()}
                disabled={!active || commits.length === 0 || ingest.isPending}
              >
                {ingest.isPending ? <Spinner /> : "Ingest"}
              </Button>
            </div>
          </div>
        </div>
      </Card>

      {ingest.error && <Banner>{(ingest.error as ApiError).message}</Banner>}
      {ingest.data && (
        <Banner tone="ok">Created {ingest.data.memories_created} memories from commit history.</Banner>
      )}

      {commits.length > 0 && !ingest.data && (
        <Card className="p-4">
          <Eyebrow>Preview</Eyebrow>
          <ul className="mt-3 space-y-1.5">
            {commits.slice(0, 6).map((c, i) => (
              <li key={i} className="flex gap-3 font-mono text-xs">
                <span className="text-copper">{c.sha.slice(0, 7)}</span>
                <span className="truncate text-muted">{c.message}</span>
              </li>
            ))}
            {commits.length > 6 && <li className="text-xs text-faint">+{commits.length - 6} more</li>}
          </ul>
        </Card>
      )}
    </div>
  );
}
