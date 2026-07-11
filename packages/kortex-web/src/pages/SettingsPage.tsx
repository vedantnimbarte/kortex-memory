import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useScope } from "../lib/scope";
import { useToast } from "../lib/toast";
import type { OrgMember, Project, Role, Workspace } from "../lib/types";
import {
  Banner,
  Button,
  Card,
  Eyebrow,
  Input,
  Label,
  Modal,
  Select,
  Spinner,
} from "../components/ui";

const ROLES: Role[] = ["viewer", "member", "admin", "owner"];

function slugify(name: string): string {
  const s = name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 60);
  return s.length >= 2 ? s : `ws-${s}`;
}

export default function SettingsPage() {
  return (
    <div className="space-y-8">
      <header>
        <Eyebrow>Settings</Eyebrow>
        <h1 className="mt-2 text-2xl font-semibold text-ink">Organization</h1>
      </header>
      <AccountSection />
      <WorkspacesSection />
      <MembersSection />
    </div>
  );
}

function AccountSection() {
  const { user } = useAuth();
  const toast = useToast();
  const resend = useMutation({
    mutationFn: () => api("/v1/auth/verify-email/send", { method: "POST" }),
  });
  return (
    <Card className="p-5">
      <Eyebrow>Account</Eyebrow>
      <div className="mt-3 flex items-center justify-between">
        <div>
          <p className="text-sm text-ink">Email verification</p>
          <p className="mt-0.5 text-xs text-faint">
            {user?.email_verified ? "Your email is verified." : "Your email isn't verified yet."}
          </p>
        </div>
        {user?.email_verified ? (
          <span className="font-mono text-[11px] uppercase tracking-wider text-ok">verified</span>
        ) : (
          <Button
            size="sm"
            variant="outline"
            onClick={() => resend.mutate(undefined, { onSuccess: () => toast("Verification email sent", "ok") })}
            disabled={resend.isPending}
          >
            Resend email
          </Button>
        )}
      </div>
    </Card>
  );
}

function WorkspacesSection() {
  const { workspaces, projects, workspace, reload } = useScope();
  const toast = useToast();
  const [modal, setModal] = useState<null | "workspace" | "project">(null);

  return (
    <Card className="p-5">
      <div className="flex items-center justify-between">
        <Eyebrow>Workspaces & projects</Eyebrow>
        <div className="flex gap-2">
          <Button size="sm" variant="outline" onClick={() => setModal("workspace")}>
            New workspace
          </Button>
          <Button size="sm" variant="outline" onClick={() => setModal("project")} disabled={!workspace}>
            New project
          </Button>
        </div>
      </div>

      <ul className="mt-4 space-y-1.5">
        {workspaces.map((w: Workspace) => (
          <li key={w.public_id} className="flex items-center gap-2 text-sm">
            <span className="text-ink">{w.name}</span>
            <span className="font-mono text-[11px] text-faint">{w.slug}</span>
            {workspace?.public_id === w.public_id && (
              <span className="ml-auto font-mono text-[10px] uppercase tracking-wider text-copper">active</span>
            )}
          </li>
        ))}
      </ul>
      {workspace && projects.length > 0 && (
        <div className="mt-4 border-t border-line pt-3">
          <p className="mb-2 font-mono text-[10px] uppercase tracking-wider text-faint">
            Projects in {workspace.name}
          </p>
          <ul className="space-y-1">
            {projects.map((p: Project) => (
              <li key={p.public_id} className="flex gap-2 text-sm text-muted">
                <span>{p.name}</span>
                <span className="font-mono text-[11px] text-faint">{p.slug}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {modal === "workspace" && (
        <CreateModal
          title="New workspace"
          label="Workspace name"
          onClose={() => setModal(null)}
          onCreate={(name) =>
            api<Workspace>("/v1/workspaces", {
              method: "POST",
              body: JSON.stringify({ slug: slugify(name), name }),
            })
          }
          onDone={async () => {
            await reload();
            toast("Workspace created", "ok");
          }}
        />
      )}
      {modal === "project" && workspace && (
        <CreateModal
          title="New project"
          label="Project name"
          onClose={() => setModal(null)}
          onCreate={(name) =>
            api<Project>(`/v1/workspaces/${workspace.public_id}/projects`, {
              method: "POST",
              body: JSON.stringify({ slug: slugify(name), name }),
            })
          }
          onDone={async () => {
            await reload();
            toast("Project created", "ok");
          }}
        />
      )}
    </Card>
  );
}

function CreateModal({
  title,
  label,
  onClose,
  onCreate,
  onDone,
}: {
  title: string;
  label: string;
  onClose: () => void;
  onCreate: (name: string) => Promise<unknown>;
  onDone: () => Promise<void> | void;
}) {
  const [name, setName] = useState("");
  const m = useMutation({
    mutationFn: () => onCreate(name),
    onSuccess: async () => {
      await onDone();
      onClose();
    },
  });
  return (
    <Modal title={title} onClose={onClose}>
      <form
        onSubmit={(e: FormEvent) => {
          e.preventDefault();
          m.mutate();
        }}
        className="space-y-4"
      >
        <div>
          <Label>{label}</Label>
          <Input autoFocus required value={name} onChange={(e) => setName(e.target.value)} />
        </div>
        {m.error && <Banner>{(m.error as ApiError).message}</Banner>}
        <div className="flex justify-end gap-2">
          <Button type="button" variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" disabled={m.isPending || !name.trim()}>
            {m.isPending ? <Spinner /> : "Create"}
          </Button>
        </div>
      </form>
    </Modal>
  );
}

function MembersSection() {
  const { user } = useAuth();
  const qc = useQueryClient();
  const toast = useToast();
  const orgId = user?.org_id;

  const { data: members, isLoading } = useQuery({
    queryKey: ["members"],
    queryFn: () => api<OrgMember[]>("/v1/users"),
  });

  const setRole = useMutation({
    mutationFn: ({ publicId, role }: { publicId: string; role: Role }) =>
      api(`/v1/users/${publicId}/memberships`, {
        method: "POST",
        body: JSON.stringify({ scope_type: "org", scope_id: orgId, role }),
      }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["members"] });
      toast("Role updated", "ok");
    },
  });

  const remove = useMutation({
    mutationFn: (publicId: string) =>
      api(`/v1/users/${publicId}/memberships`, {
        method: "DELETE",
        body: JSON.stringify({ scope_type: "org", scope_id: orgId, role: "member" }),
      }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["members"] });
      toast("Member removed", "ok");
    },
  });

  return (
    <Card className="p-5">
      <div className="flex items-center justify-between">
        <Eyebrow>Members</Eyebrow>
        <InviteForm onInvited={() => qc.invalidateQueries({ queryKey: ["members"] })} />
      </div>
      {isLoading && <div className="mt-4"><Spinner /></div>}
      <ul className="mt-4 space-y-2">
        {members?.map((m) => {
          const isSelf = m.public_id === user?.public_id;
          return (
            <li key={m.public_id} className="flex items-center gap-3">
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm text-ink">
                  {m.display_name || m.email}
                  {isSelf && <span className="ml-2 text-xs text-faint">(you)</span>}
                </p>
                <p className="truncate font-mono text-xs text-faint">{m.email}</p>
              </div>
              <Select
                value={m.role}
                onChange={(e) => setRole.mutate({ publicId: m.public_id, role: e.target.value as Role })}
                className="w-28"
                aria-label={`Role for ${m.email}`}
              >
                {ROLES.map((r) => (
                  <option key={r} value={r}>
                    {r}
                  </option>
                ))}
              </Select>
              {!isSelf && (
                <Button size="sm" variant="danger" onClick={() => remove.mutate(m.public_id)}>
                  Remove
                </Button>
              )}
            </li>
          );
        })}
      </ul>
    </Card>
  );
}

function InviteForm({ onInvited }: { onInvited: () => void }) {
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<Role>("member");

  const invite = useMutation({
    mutationFn: () => api("/v1/users/invite", { method: "POST", body: JSON.stringify({ email, role }) }),
    onSuccess: () => {
      onInvited();
      setEmail("");
      setOpen(false);
      toast("Invite sent — they'll get an email to set a password", "ok");
    },
  });

  return (
    <>
      <Button size="sm" variant="outline" onClick={() => setOpen(true)}>
        Invite
      </Button>
      {open && (
        <Modal title="Invite a member" onClose={() => setOpen(false)}>
          <form
            onSubmit={(e: FormEvent) => {
              e.preventDefault();
              invite.mutate();
            }}
            className="space-y-4"
          >
            <div>
              <Label>Email</Label>
              <Input type="email" required autoFocus value={email} onChange={(e) => setEmail(e.target.value)} />
            </div>
            <div>
              <Label>Role</Label>
              <Select value={role} onChange={(e) => setRole(e.target.value as Role)}>
                {ROLES.map((r) => (
                  <option key={r} value={r}>
                    {r}
                  </option>
                ))}
              </Select>
            </div>
            {invite.error && <Banner>{(invite.error as ApiError).message}</Banner>}
            <div className="flex justify-end gap-2">
              <Button type="button" variant="ghost" onClick={() => setOpen(false)}>
                Cancel
              </Button>
              <Button type="submit" disabled={invite.isPending || !email.trim()}>
                {invite.isPending ? <Spinner /> : "Send invite"}
              </Button>
            </div>
          </form>
        </Modal>
      )}
    </>
  );
}
