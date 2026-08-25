// Mirrors the Kortex API response schemas (packages/kortex-api/schemas).

export type ScopeType = "org" | "workspace" | "project" | "session";
export type MemoryTier = "short" | "mid" | "long";
export type Sensitivity = "public" | "internal" | "confidential" | "secret";
export type MemoryKind =
  | "fact"
  | "preference"
  | "decision"
  | "procedure"
  | "code_artifact"
  | "event"
  | "summary";

export type Whoami = {
  user_id: number;
  public_id: string;
  is_superuser: boolean;
  org_id: number;
  email_verified: boolean;
};

export type Role = "viewer" | "member" | "admin" | "owner";

export type OrgMember = {
  public_id: string;
  email: string;
  display_name: string;
  role: Role;
  email_verified: boolean;
};

export type LinkedMemory = {
  public_id: string;
  title: string;
  tier: MemoryTier;
  link_type: string;
};

export type Org = { id: number; public_id: string; slug: string; name: string; plan: string };
export type Workspace = { id: number; public_id: string; slug: string; name: string };
export type Project = { id: number; public_id: string; slug: string; name: string };

export type Memory = {
  public_id: string;
  scope_type: ScopeType;
  scope_id: number;
  title: string;
  body: string;
  kind: MemoryKind;
  sensitivity: Sensitivity;
  tier: MemoryTier;
  importance: number;
  pinned: boolean;
  access_count: number;
  decay_score: number;
  created_at: string;
  updated_at: string;
  last_accessed_at: string | null;
  expires_at: string | null;
  metadata: Record<string, unknown>;
  // Governance (WU-2.3 / WU-2.4). Optional so the type still describes a
  // response from an older API without every call site guarding.
  trust?: "high" | "medium" | "low";
  review_status?: "approved" | "pending" | "rejected";
  review_reason?: string | null;
  confidence?: number | null;
  pii_flags?: Record<string, number>;
  embedding_state?: "ok" | "pending" | "failed";
};

export type CountSlice = { label: string; value: number };
export type Analytics = {
  count: number;
  pinned: number;
  avg_decay: number;
  total_access: number;
  by_tier: CountSlice[];
  by_kind: CountSlice[];
  by_sensitivity: CountSlice[];
  decay_health: { healthy: number; aging: number; faded: number };
  top_accessed: Memory[];
  timeline: number[];
};

export type SearchHit = {
  public_id: string;
  title: string;
  body: string;
  tier: string;
  sensitivity: string;
  importance: number;
  decay_score: number;
  pinned: boolean;
  score: number;
};
export type SearchOut = { hits: SearchHit[]; used_vector: boolean };

export type Citation = { public_id: string; title: string; score: number };
export type RecallCandidate = {
  public_id: string;
  title: string;
  body: string;
  tier: string;
  sensitivity: string;
  final_score: number;
  rerank_score: number;
};
export type ContextBundle = {
  query: string;
  answer: string | null;
  citations: Citation[];
  candidates: RecallCandidate[];
  used_tokens: number;
  plan_trace: string[];
  plan_rationale: string;
  hops: number;
  stopped_reason: string;
};

export type ApiKey = {
  public_id: string;
  created_at: string;
  updated_at: string;
  prefix: string;
  name: string;
  scopes: string[];
  scope_type: ScopeType | null;
  scope_id: number | null;
  expires_at: string | null;
  last_used_at: string | null;
  revoked_at: string | null;
};
export type ApiKeyMint = ApiKey & { plaintext: string };

export type AgentKind = "claude_code" | "codex" | "opencode" | "web" | "api" | "other";
export type MessageRole = "user" | "assistant" | "system" | "tool";
export type AttachmentStatus = "pending" | "processing" | "ready" | "failed";

export type Session = {
  public_id: string;
  created_at: string;
  updated_at: string;
  agent_kind: AgentKind;
  title: string;
  client_metadata: Record<string, unknown>;
  started_at: string;
  ended_at: string | null;
};

export type Conversation = {
  public_id: string;
  created_at: string;
  updated_at: string;
  title: string;
  summary: string | null;
};

export type Message = {
  public_id: string;
  role: MessageRole;
  content: string;
  tool_name: string | null;
  tool_input: Record<string, unknown> | null;
  tool_output: Record<string, unknown> | null;
  created_at: string;
};

export type Attachment = {
  public_id: string;
  scope_type: ScopeType;
  scope_id: number;
  filename: string;
  mime: string | null;
  size_bytes: number;
  sha256: string | null;
  sensitivity: Sensitivity;
  processing_status: AttachmentStatus;
  processing_error: string | null;
  processed_at: string | null;
  s3_bucket: string;
  s3_key: string;
  created_at: string;
  updated_at: string;
  metadata: Record<string, unknown>;
};

export type PresignedUpload = {
  url: string;
  method: string;
  headers: Record<string, string>;
  expires_in: number;
};
export type AttachmentPresign = { attachment: Attachment; upload: PresignedUpload };

export type AttachmentChunkHit = {
  attachment_public_id: string;
  filename: string;
  chunk_index: number;
  content: string;
  score: number;
};
export type AttachmentSearch = { hits: AttachmentChunkHit[]; used_vector: boolean };

export type AdminTask = {
  task: string;
  task_id: string | null;
  dispatched: boolean;
  detail: string | null;
};

export type Plan = { id: string; name: string; price_usd: number; features: string[] };
export type Usage = {
  memories: number;
  max_memories: number;
  workspaces: number;
  max_workspaces: number;
};

export type Subscription = {
  plan: string;
  status: string;
  current_period_end: number | null;
  billing_enabled: boolean;
  usage: Usage | null;
};
