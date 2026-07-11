import { useRef, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { api, ApiError, downloadFile } from "../lib/api";
import { useScope } from "../lib/scope";
import { useToast } from "../lib/toast";
import { Banner, Button, Card, Eyebrow, EmptyState, Spinner } from "../components/ui";

type ImportResult = { memories: number; links: number; attachments: number };

export default function DataPage() {
  const { active } = useScope();
  const toast = useToast();
  const fileRef = useRef<HTMLInputElement>(null);
  const [importing, setImporting] = useState(false);

  const exportScope = useMutation({
    mutationFn: () =>
      downloadFile(
        `/v1/export?scope_type=${active!.scope_type}&scope_id=${active!.scope_id}&include_attachments=true`,
        `kortex-${active!.scope_type}-${active!.scope_id}.tar`,
      ),
    onSuccess: () => toast("Export downloaded", "ok"),
    onError: (e) => toast((e as ApiError).message, "error"),
  });

  async function runImport(file: File) {
    if (!active) return;
    setImporting(true);
    try {
      const form = new FormData();
      form.append("file", file);
      const result = await api<ImportResult>(
        `/v1/export/import?target_scope_type=${active.scope_type}&target_scope_id=${active.scope_id}`,
        { method: "POST", body: form },
      );
      toast(`Imported ${result.memories} memories, ${result.attachments} files`, "ok");
    } catch (e) {
      toast(e instanceof ApiError ? e.message : "import failed", "error");
    } finally {
      setImporting(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  return (
    <div className="max-w-2xl space-y-6">
      <header>
        <Eyebrow>Data</Eyebrow>
        <h1 className="mt-2 text-2xl font-semibold text-ink">Export & import</h1>
        <p className="mt-2 text-sm text-muted">
          Move a scope's memories, links, and attachments as a portable tar archive.
        </p>
      </header>

      {!active ? (
        <EmptyState title="Pick a scope first." hint="Choose a workspace or project in the top bar." />
      ) : (
        <>
          <Card className="flex items-center justify-between gap-4 p-5">
            <div>
              <p className="text-sm font-medium text-ink">Export {active.label}</p>
              <p className="mt-0.5 text-xs text-faint">Downloads a .tar of everything in this scope.</p>
            </div>
            <Button onClick={() => exportScope.mutate()} disabled={exportScope.isPending}>
              {exportScope.isPending ? <Spinner /> : "Export"}
            </Button>
          </Card>

          <Card className="flex items-center justify-between gap-4 p-5">
            <div>
              <p className="text-sm font-medium text-ink">Import into {active.label}</p>
              <p className="mt-0.5 text-xs text-faint">Upload a Kortex .tar to merge its contents here.</p>
            </div>
            <input
              ref={fileRef}
              type="file"
              accept=".tar"
              className="hidden"
              onChange={(e) => e.target.files?.[0] && runImport(e.target.files[0])}
            />
            <Button variant="outline" onClick={() => fileRef.current?.click()} disabled={importing}>
              {importing ? <Spinner /> : "Import"}
            </Button>
          </Card>

          <Banner tone="ok">Imports merge into the current scope — they never overwrite existing memories.</Banner>
        </>
      )}
    </div>
  );
}
