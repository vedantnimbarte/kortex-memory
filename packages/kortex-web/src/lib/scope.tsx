import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { api } from "./api";
import type { Project, ScopeType, Workspace } from "./types";

const WS_KEY = "kortex.workspace";
const PROJ_KEY = "kortex.project";

export type ActiveScope = { scope_type: ScopeType; scope_id: number; label: string };

type ScopeState = {
  workspaces: Workspace[];
  projects: Project[];
  workspace: Workspace | null;
  project: Project | null;
  active: ActiveScope | null;
  selectWorkspace: (publicId: string) => void;
  selectProject: (publicId: string | null) => void;
  reload: () => Promise<void>;
};

const ScopeContext = createContext<ScopeState | null>(null);

export function ScopeProvider({ children }: { children: ReactNode }) {
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [wsId, setWsId] = useState<string | null>(() => localStorage.getItem(WS_KEY));
  const [projId, setProjId] = useState<string | null>(() => localStorage.getItem(PROJ_KEY));

  const loadWorkspaces = useCallback(async () => {
    const ws = await api<Workspace[]>("/v1/workspaces");
    setWorkspaces(ws);
    setWsId((cur) => (cur && ws.some((w) => w.public_id === cur) ? cur : (ws[0]?.public_id ?? null)));
  }, []);

  useEffect(() => {
    void loadWorkspaces();
  }, [loadWorkspaces]);

  const workspace = useMemo(
    () => workspaces.find((w) => w.public_id === wsId) ?? null,
    [workspaces, wsId],
  );

  useEffect(() => {
    if (!workspace) {
      setProjects([]);
      return;
    }
    void api<Project[]>(`/v1/workspaces/${workspace.public_id}/projects`).then((ps) => {
      setProjects(ps);
      setProjId((cur) => (cur && ps.some((p) => p.public_id === cur) ? cur : null));
    });
  }, [workspace]);

  const project = useMemo(
    () => projects.find((p) => p.public_id === projId) ?? null,
    [projects, projId],
  );

  const active: ActiveScope | null = useMemo(() => {
    if (project) return { scope_type: "project", scope_id: project.id, label: project.name };
    if (workspace) return { scope_type: "workspace", scope_id: workspace.id, label: workspace.name };
    return null;
  }, [workspace, project]);

  const value: ScopeState = {
    workspaces,
    projects,
    workspace,
    project,
    active,
    selectWorkspace(publicId) {
      localStorage.setItem(WS_KEY, publicId);
      localStorage.removeItem(PROJ_KEY);
      setWsId(publicId);
      setProjId(null);
    },
    selectProject(publicId) {
      if (publicId) localStorage.setItem(PROJ_KEY, publicId);
      else localStorage.removeItem(PROJ_KEY);
      setProjId(publicId);
    },
    reload: loadWorkspaces,
  };

  return <ScopeContext.Provider value={value}>{children}</ScopeContext.Provider>;
}

export function useScope(): ScopeState {
  const ctx = useContext(ScopeContext);
  if (!ctx) throw new Error("useScope must be used within ScopeProvider");
  return ctx;
}
