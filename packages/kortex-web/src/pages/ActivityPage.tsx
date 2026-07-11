import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "../lib/api";
import { useScope } from "../lib/scope";
import { useToast } from "../lib/toast";
import type { AgentKind, Conversation, Message, Session } from "../lib/types";
import {
  Button,
  Card,
  Eyebrow,
  EmptyState,
  Input,
  Select,
  Spinner,
  formatDate,
} from "../components/ui";

const AGENTS: AgentKind[] = ["claude_code", "codex", "opencode", "web", "api", "other"];

export default function ActivityPage() {
  const { project } = useScope();
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [convId, setConvId] = useState<string | null>(null);

  if (!project) {
    return (
      <div className="space-y-6">
        <header>
          <Eyebrow>Activity</Eyebrow>
          <h1 className="mt-2 text-2xl font-semibold text-ink">Sessions</h1>
        </header>
        <EmptyState
          title="Pick a project to see its activity."
          hint="Sessions are recorded per project. Choose one in the top bar."
        />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <header>
        <Eyebrow>Activity</Eyebrow>
        <h1 className="mt-2 text-2xl font-semibold text-ink">{project.name} · sessions</h1>
      </header>
      <div className="grid gap-6 lg:grid-cols-[300px_1fr]">
        <SessionList
          projectId={project.public_id}
          selected={sessionId}
          onSelect={(id) => {
            setSessionId(id);
            setConvId(null);
          }}
        />
        <div className="min-w-0">
          {!sessionId ? (
            <Card className="p-8 text-center text-sm text-faint">Select a session to view its threads.</Card>
          ) : convId ? (
            <MessageThread convId={convId} onBack={() => setConvId(null)} />
          ) : (
            <ConversationList sessionId={sessionId} onOpen={setConvId} />
          )}
        </div>
      </div>
    </div>
  );
}

function SessionList({
  projectId,
  selected,
  onSelect,
}: {
  projectId: string;
  selected: string | null;
  onSelect: (id: string) => void;
}) {
  const qc = useQueryClient();
  const { project } = useScope();
  const [agent, setAgent] = useState<AgentKind>("web");

  const { data: sessions, isLoading } = useQuery({
    queryKey: ["sessions", projectId],
    queryFn: () => api<Session[]>(`/v1/sessions?project_public_id=${projectId}`),
  });

  const start = useMutation({
    mutationFn: () =>
      api<Session>("/v1/sessions", {
        method: "POST",
        body: JSON.stringify({ project_public_id: project!.public_id, agent_kind: agent, title: "" }),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["sessions", projectId] }),
  });

  const end = useMutation({
    mutationFn: (id: string) => api<Session>(`/v1/sessions/${id}/end`, { method: "POST" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["sessions", projectId] }),
  });

  return (
    <Card className="p-4">
      <div className="flex items-center gap-2">
        <Select value={agent} onChange={(e) => setAgent(e.target.value as AgentKind)} className="flex-1">
          {AGENTS.map((a) => (
            <option key={a} value={a}>
              {a}
            </option>
          ))}
        </Select>
        <Button size="sm" onClick={() => start.mutate()} disabled={start.isPending}>
          Start
        </Button>
      </div>
      {isLoading && <div className="mt-4"><Spinner /></div>}
      <ul className="mt-3 space-y-1.5">
        {sessions?.length === 0 && <li className="text-xs text-faint">No sessions yet.</li>}
        {sessions?.map((s) => (
          <li key={s.public_id}>
            <button
              onClick={() => onSelect(s.public_id)}
              className={`w-full rounded-lg border px-3 py-2 text-left transition-colors ${
                selected === s.public_id ? "border-copper bg-surface-2" : "border-line hover:border-line-bright"
              }`}
            >
              <div className="flex items-center gap-2">
                <span className="font-mono text-[10px] uppercase tracking-wider text-copper">{s.agent_kind}</span>
                <span className="ml-auto text-[11px] text-faint">{formatDate(s.started_at)}</span>
              </div>
              <p className="mt-1 truncate text-sm text-ink">{s.title || "Untitled session"}</p>
              <div className="mt-1 flex items-center gap-2">
                <span className={`h-1.5 w-1.5 rounded-full ${s.ended_at ? "bg-faint" : "bg-ok"}`} />
                <span className="text-[11px] text-faint">{s.ended_at ? "ended" : "active"}</span>
                {!s.ended_at && (
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      end.mutate(s.public_id);
                    }}
                    className="ml-auto text-[11px] text-muted hover:text-danger"
                  >
                    End
                  </button>
                )}
              </div>
            </button>
          </li>
        ))}
      </ul>
    </Card>
  );
}

function ConversationList({ sessionId, onOpen }: { sessionId: string; onOpen: (id: string) => void }) {
  const qc = useQueryClient();
  const [title, setTitle] = useState("");

  const { data: convos, isLoading } = useQuery({
    queryKey: ["conversations", sessionId],
    queryFn: () => api<Conversation[]>(`/v1/sessions/${sessionId}/conversations`),
  });

  const create = useMutation({
    mutationFn: () =>
      api<Conversation>(`/v1/sessions/${sessionId}/conversations`, {
        method: "POST",
        body: JSON.stringify({ title }),
      }),
    onSuccess: () => {
      setTitle("");
      void qc.invalidateQueries({ queryKey: ["conversations", sessionId] });
    },
  });

  return (
    <Card className="p-5">
      <Eyebrow>Conversations</Eyebrow>
      {isLoading && <div className="mt-3"><Spinner /></div>}
      <ul className="mt-3 space-y-2">
        {convos?.length === 0 && <li className="text-xs text-faint">No conversations yet.</li>}
        {convos?.map((c) => (
          <li key={c.public_id}>
            <button
              onClick={() => onOpen(c.public_id)}
              className="w-full rounded-lg border border-line px-3 py-2 text-left transition-colors hover:border-line-bright"
            >
              <p className="text-sm text-ink">{c.title || "Untitled conversation"}</p>
              {c.summary && <p className="mt-1 line-clamp-1 text-xs text-muted">{c.summary}</p>}
            </button>
          </li>
        ))}
      </ul>
      <form
        onSubmit={(e: FormEvent) => {
          e.preventDefault();
          create.mutate();
        }}
        className="mt-4 flex gap-2"
      >
        <Input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="New conversation title" className="flex-1" />
        <Button type="submit" size="sm" disabled={create.isPending}>
          Add
        </Button>
      </form>
    </Card>
  );
}

function MessageThread({ convId, onBack }: { convId: string; onBack: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [content, setContent] = useState("");
  const [role, setRole] = useState<Message["role"]>("user");

  const { data: messages, isLoading } = useQuery({
    queryKey: ["messages", convId],
    queryFn: () => api<Message[]>(`/v1/conversations/${convId}/messages`),
  });

  const append = useMutation({
    mutationFn: () =>
      api<Message>(`/v1/conversations/${convId}/messages`, {
        method: "POST",
        body: JSON.stringify({ role, content }),
      }),
    onSuccess: () => {
      setContent("");
      void qc.invalidateQueries({ queryKey: ["messages", convId] });
    },
    onError: (e) => toast((e as ApiError).message, "error"),
  });

  const roleColor: Record<string, string> = {
    user: "text-tier-short",
    assistant: "text-copper",
    system: "text-muted",
    tool: "text-tier-mid",
  };

  return (
    <Card className="flex h-[600px] flex-col p-5">
      <button onClick={onBack} className="mb-3 w-fit text-xs text-muted hover:text-copper">
        ← Conversations
      </button>
      <div className="flex-1 space-y-3 overflow-y-auto pr-1">
        {isLoading && <Spinner />}
        {messages?.length === 0 && <p className="text-xs text-faint">No messages yet.</p>}
        {messages?.map((m) => (
          <div key={m.public_id} className="border-l-2 border-line pl-3">
            <div className="flex items-center gap-2">
              <span className={`font-mono text-[10px] uppercase tracking-wider ${roleColor[m.role]}`}>{m.role}</span>
              {m.tool_name && <span className="font-mono text-[10px] text-faint">{m.tool_name}</span>}
              <span className="ml-auto text-[10px] text-faint">{formatDate(m.created_at)}</span>
            </div>
            <p className="mt-1 whitespace-pre-wrap text-sm text-ink">{m.content}</p>
          </div>
        ))}
      </div>
      <form
        onSubmit={(e: FormEvent) => {
          e.preventDefault();
          if (content.trim()) append.mutate();
        }}
        className="mt-4 flex gap-2 border-t border-line pt-4"
      >
        <Select value={role} onChange={(e) => setRole(e.target.value as Message["role"])} className="w-28">
          {(["user", "assistant", "system", "tool"] as Message["role"][]).map((r) => (
            <option key={r} value={r}>
              {r}
            </option>
          ))}
        </Select>
        <Input value={content} onChange={(e) => setContent(e.target.value)} placeholder="Message…" className="flex-1" />
        <Button type="submit" size="sm" disabled={append.isPending || !content.trim()}>
          Send
        </Button>
      </form>
    </Card>
  );
}
