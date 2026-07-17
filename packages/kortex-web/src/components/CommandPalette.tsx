import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

type Command = { label: string; hint: string; to: string };

// Kept in sync with the sidebar by hand — it's a short, stable list.
const COMMANDS: Command[] = [
  { label: "Dashboard", hint: "overview", to: "/app" },
  { label: "Recall", hint: "ask the memory", to: "/app/recall" },
  { label: "Search", hint: "hybrid search", to: "/app/search" },
  { label: "Memories", hint: "browse & write", to: "/app/memories" },
  { label: "Activity", hint: "sessions & threads", to: "/app/activity" },
  { label: "Attachments", hint: "files", to: "/app/attachments" },
  { label: "Ingest", hint: "import", to: "/app/ingest" },
  { label: "Data", hint: "export", to: "/app/data" },
  { label: "API keys", hint: "tokens", to: "/app/keys" },
  { label: "Billing", hint: "plan & usage", to: "/app/billing" },
  { label: "Settings", hint: "org & members", to: "/app/settings" },
];

function isTyping(el: EventTarget | null): boolean {
  const t = el as HTMLElement | null;
  return !!t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.isContentEditable);
}

export default function CommandPalette() {
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  // Global open triggers: Cmd/Ctrl-K anywhere, or "/" when not already typing.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen((v) => !v);
      } else if (e.key === "/" && !isTyping(e.target) && !open) {
        e.preventDefault();
        setOpen(true);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  useEffect(() => {
    if (open) {
      setQuery("");
      setActive(0);
      // Focus after the element mounts.
      requestAnimationFrame(() => inputRef.current?.focus());
    }
  }, [open]);

  const results = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return COMMANDS;
    return COMMANDS.filter((c) => (c.label + " " + c.hint).toLowerCase().includes(q));
  }, [query]);

  useEffect(() => {
    setActive((a) => Math.min(a, Math.max(0, results.length - 1)));
  }, [results.length]);

  if (!open) return null;

  function go(cmd: Command | undefined) {
    if (!cmd) return;
    setOpen(false);
    navigate(cmd.to);
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-black/60 px-4 pt-[12vh]"
      onClick={() => setOpen(false)}
      role="presentation"
    >
      <div
        className="fade-up w-full max-w-lg overflow-hidden rounded-xl border border-line-bright bg-surface shadow-2xl shadow-black/50"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label="Command palette"
      >
        <input
          ref={inputRef}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "ArrowDown") {
              e.preventDefault();
              setActive((a) => Math.min(results.length - 1, a + 1));
            } else if (e.key === "ArrowUp") {
              e.preventDefault();
              setActive((a) => Math.max(0, a - 1));
            } else if (e.key === "Enter") {
              e.preventDefault();
              go(results[active]);
            } else if (e.key === "Escape") {
              setOpen(false);
            }
          }}
          placeholder="Jump to…"
          className="w-full border-b border-line bg-transparent px-4 py-3.5 text-sm text-ink placeholder:text-faint focus:outline-none"
          aria-label="Jump to a page"
        />
        <ul className="max-h-80 overflow-y-auto p-1.5">
          {results.length === 0 && (
            <li className="px-3 py-6 text-center text-sm text-faint">No matches.</li>
          )}
          {results.map((cmd, i) => (
            <li key={cmd.to}>
              <button
                onMouseMove={() => setActive(i)}
                onClick={() => go(cmd)}
                className={`flex w-full items-baseline gap-3 rounded-lg px-3 py-2.5 text-left transition-colors ${
                  i === active ? "bg-surface-2" : "hover:bg-surface-2/60"
                }`}
              >
                <span className={`text-sm ${i === active ? "text-copper" : "text-ink"}`}>{cmd.label}</span>
                <span className="ml-auto font-mono text-[11px] text-faint">{cmd.hint}</span>
              </button>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
