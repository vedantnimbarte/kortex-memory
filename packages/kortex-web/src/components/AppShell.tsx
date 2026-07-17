import { useMutation } from "@tanstack/react-query";
import { NavLink, Outlet } from "react-router-dom";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useScope } from "../lib/scope";
import { useToast } from "../lib/toast";
import { Select } from "./ui";
import CommandPalette from "./CommandPalette";

const NAV: { to: string; label: string; end?: boolean }[] = [
  { to: "/app", label: "Dashboard", end: true },
  { to: "/app/recall", label: "Recall" },
  { to: "/app/search", label: "Search" },
  { to: "/app/memories", label: "Memories" },
  { to: "/app/activity", label: "Activity" },
  { to: "/app/attachments", label: "Attachments" },
  { to: "/app/ingest", label: "Ingest" },
  { to: "/app/data", label: "Data" },
  { to: "/app/keys", label: "API keys" },
  { to: "/app/billing", label: "Billing" },
  { to: "/app/settings", label: "Settings" },
];
const ADMIN_NAV: { to: string; label: string; end?: boolean } = { to: "/app/admin", label: "Admin" };

function Mark() {
  // Ferrite core: a copper ring threaded through the chassis.
  return (
    <svg width="22" height="22" viewBox="0 0 22 22" fill="none" aria-hidden>
      <circle cx="11" cy="11" r="6.5" stroke="var(--color-copper)" strokeWidth="1.5" />
      <path d="M3 3l6 6M19 19l-6-6M19 3l-6 6M3 19l6-6" stroke="var(--color-line-bright)" strokeWidth="1.2" />
    </svg>
  );
}

function VerifyBanner() {
  const { user } = useAuth();
  const toast = useToast();
  const resend = useMutation({
    mutationFn: () => api("/v1/auth/verify-email/send", { method: "POST" }),
    onSuccess: () => toast("Verification email sent", "ok"),
  });
  if (user?.email_verified) return null;
  return (
    <div className="flex flex-wrap items-center gap-3 border-b border-copper/30 bg-copper/10 px-6 py-2.5 text-sm text-copper">
      <span>Verify your email to secure your account.</span>
      <button
        onClick={() => resend.mutate()}
        disabled={resend.isPending}
        className="font-medium underline underline-offset-2 hover:text-copper-bright disabled:opacity-50"
      >
        Resend link
      </button>
    </div>
  );
}

export default function AppShell() {
  const { user, logout } = useAuth();
  const { workspaces, projects, workspace, project, selectWorkspace, selectProject } = useScope();
  const nav = user?.is_superuser ? [...NAV, ADMIN_NAV] : NAV;

  return (
    <div className="min-h-screen lg:grid lg:grid-cols-[236px_1fr]">
      <CommandPalette />
      {/* Sidebar */}
      <aside className="flex flex-col border-b border-line bg-surface lg:border-b-0 lg:border-r">
        <div className="flex items-center gap-2.5 px-5 py-4">
          <Mark />
          <span className="font-mono text-sm font-semibold tracking-[0.2em] text-ink">KORTEX</span>
        </div>
        <nav className="flex gap-1 overflow-x-auto px-3 pb-3 lg:flex-col lg:overflow-visible lg:pb-0">
          {nav.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                `rounded-md px-3 py-2 text-sm transition-colors ${
                  isActive
                    ? "bg-surface-2 text-copper"
                    : "text-muted hover:bg-surface-2 hover:text-ink"
                }`
              }
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
        <div className="mt-auto hidden border-t border-line px-4 py-3 lg:block">
          <p className="truncate font-mono text-[11px] text-faint">org #{user?.org_id}</p>
          <button
            onClick={() => void logout()}
            className="mt-1 text-xs text-muted transition-colors hover:text-copper"
          >
            Sign out
          </button>
        </div>
      </aside>

      {/* Main */}
      <div className="flex min-w-0 flex-col">
        <VerifyBanner />
        <header className="flex flex-wrap items-center gap-3 border-b border-line bg-bg/80 px-6 py-3 backdrop-blur">
          <div className="flex items-center gap-2">
            <span className="font-mono text-[11px] uppercase tracking-wider text-faint">scope</span>
            <Select
              value={workspace?.public_id ?? ""}
              onChange={(e) => selectWorkspace(e.target.value)}
              className="max-w-[180px]"
              aria-label="Workspace"
            >
              {workspaces.length === 0 && <option value="">No workspaces</option>}
              {workspaces.map((w) => (
                <option key={w.public_id} value={w.public_id}>
                  {w.name}
                </option>
              ))}
            </Select>
            <span className="text-faint">/</span>
            <Select
              value={project?.public_id ?? ""}
              onChange={(e) => selectProject(e.target.value || null)}
              className="max-w-[180px]"
              aria-label="Project"
            >
              <option value="">All projects</option>
              {projects.map((p) => (
                <option key={p.public_id} value={p.public_id}>
                  {p.name}
                </option>
              ))}
            </Select>
          </div>
          <button
            onClick={() => window.dispatchEvent(new KeyboardEvent("keydown", { key: "k", ctrlKey: true }))}
            className="ml-auto hidden items-center gap-2 rounded-md border border-line px-2.5 py-1.5 text-xs text-muted transition-colors hover:border-line-bright hover:text-ink sm:inline-flex"
            aria-label="Open command palette"
          >
            Jump to
            <kbd className="rounded border border-line-bright px-1.5 py-0.5 font-mono text-[10px] text-faint">⌘K</kbd>
          </button>
        </header>
        <main className="min-w-0 flex-1 px-6 py-8">
          <div className="mx-auto max-w-5xl">
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  );
}
