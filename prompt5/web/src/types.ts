export type ApiMode = "demo" | "remote";
export type TaskState = "rubric_pending" | "running" | "succeeded" | "failed" | "cancelled";
export type EvidenceLevel = "L1" | "L2" | "L3";
export type ReproductionTier = "T1" | "T2" | "T3";
export type GateLabel = "optimizing" | "compatible" | "rejected";

export interface ModelCard {
  target: string;
  provider: string;
  model: string;
  tier: ReproductionTier;
  label: GateLabel;
  primary: boolean;
}

export interface ProtectEntry {
  loc: string;
  cls: "safety" | "hard_format" | "user_pinned";
  state: "proposed" | "enacted";
  by?: string;
  at?: string;
  review_by?: string;
}

export interface PromptIR {
  schema_version: "3";
  ir_id: string;
  version: number;
  parent_ir_version: number | null;
  lineage_id: string;
  checksum: string;
  created: Record<string, unknown>;
  slots: {
    role: string;
    goal: {
      outcome: string;
      done_criteria: string[];
      non_goals: string[];
    };
    inputs: Array<{
      ref: string;
      type: "text" | "json" | "image" | "pdf";
      note: string;
      trust: "user" | "derived";
    }>;
    output: {
      format: string;
      schema: Record<string, unknown> | null;
      length_budget: string;
    };
    constraints: {
      must: string[];
      must_not: string[];
      style: string[];
    };
    examples: Array<{ input: string; expected: string }>;
    workflow: string[];
    feedback_protocol: Record<string, unknown>;
  };
  freeform_extras: Array<{
    id: string;
    text: string;
    note: string;
    provenance: Record<string, unknown>;
  }>;
  provenance_map: Record<string, Record<string, unknown>>;
  protect_registry: ProtectEntry[];
  item_ids: Record<string, string[]>;
}

export interface L1Finding {
  severity: string;
  code: string;
  message: string;
  loc?: string | null;
}

export interface L1Report {
  passed: boolean;
  score: number;
  token_estimate: number;
  findings: L1Finding[];
}

export interface Evidence {
  level: EvidenceLevel;
  rubric_version: string;
  metrics: Record<string, unknown>;
  reproduction_tier: ReproductionTier;
  model_snapshot: string;
  decode: Record<string, unknown>;
  renderer_version: string;
  baseline_id: string | null;
  label: GateLabel | null;
  expires_at: string | null;
}

export interface TaskEnvelope {
  task_id: string;
  tenant_id?: string;
  connector_id?: string;
  state: TaskState;
  result_class: "pending" | "full";
  model: string;
  draft?: { text: string; rubric_policy: "draft_then_confirm" };
  rubric?: RubricDraft;
  ir?: PromptIR;
  rendered?: { text: string; cache_key: string };
  l1?: L1Report;
  evidence?: Evidence;
  execution?: { kind: "mock" | "live"; label?: string };
}

export interface RubricDraft {
  version: string;
  criteria: string[];
  source: "backend" | "demo";
  note?: string;
}

export interface CreateTaskInput {
  text: string;
  targetModel: string;
  materials: Array<{ blob_id: string }>;
  idempotencyKey: string;
  requestId: string;
}

export interface BlobMeta {
  blob_id: string;
  content_hash: string;
  size: number;
  mime: string;
  expires_at: string;
}

export interface PatchOperation {
  op: "ADD" | "DELETE" | "REWRITE" | "MOVE";
  loc: string;
  content?: unknown;
  reason: string;
  evidence_refs: string[];
  to?: { before?: string; after?: string } | null;
}

export interface PatchResult {
  patch: {
    patch_id: string;
    base: { ir_id: string; version: number; checksum: string };
    intent: "improve" | "simplify" | "fix" | "protect";
    ops: PatchOperation[];
    patch_hash?: string;
  };
  ir: PromptIR;
  rendered: { text: string; cache_key: string; model: string };
  persisted: boolean;
}

export interface EvalTaskRow {
  task_id: string;
  brief: string;
  split: "calibration" | "confirmatory" | "hidden";
  critical: boolean;
  champion: number;
  baseline: number;
}

export interface EvaluationReport {
  report_id: string;
  benchmark: string;
  bench_version: string;
  model: string;
  executor: "scripted" | "live";
  simulated: boolean;
  created_at: string;
  candidate: string;
  baseline_id: "b1-oss";
  baseline_label: string;
  label: GateLabel;
  reason: string;
  mean_diff: number;
  ci: [number, number];
  p_value: number;
  n_tasks: number;
  critical_failures: number;
  champion_rate: number;
  baseline_rate: number;
  rows: EvalTaskRow[];
  source: "backend" | "demo";
}

export interface ProviderConfig {
  display: string;
  base_url: string;
  api_key_env: string;
  api_style?: string;
  timeout?: number;
  api_key_required?: boolean;
  key_configured?: boolean;
}

export interface RoleBinding {
  provider: string;
  model: string;
}

export interface TargetConfig extends RoleBinding {
  tier: ReproductionTier;
  label: GateLabel;
  primary?: boolean;
}

export interface Prompt5Config {
  providers: Record<string, ProviderConfig>;
  roles: {
    generator: RoleBinding;
    reflector: RoleBinding;
    judges: RoleBinding[];
  };
  targets: Record<string, TargetConfig>;
}

export interface ConfigIssue {
  level: "error" | "warn";
  code: string;
  field: string;
  message: string;
}

export interface ConfigCheckResult {
  ok: boolean;
  issues: ConfigIssue[];
  missing_env: string[];
  source: "backend" | "demo";
}

export interface ProbeResult {
  target: string;
  ok: boolean;
  latency_ms?: number;
  detail: string;
  checked_at: string;
  source: "backend" | "demo";
}

export interface SessionTurn {
  seq: number;
  role: "user" | "assistant" | "system";
  text: string;
  kind: "chitchat" | "progress" | "material" | "goal" | "constraint" | "correction" | "uncertain";
  invalidates: boolean;
  created_at: string;
}

export interface SessionEvent {
  event_seq: number;
  event_type: string;
  state?: string;
  attempts?: number;
  payload?: Record<string, unknown>;
  created_at?: string;
}

export interface SessionSuggestion {
  suggestion_id: string;
  state: "proposed" | "applied" | "invalidated";
  summary: string;
  epoch: number;
  base_checksum: string;
  created_at: string;
}

export interface SessionReplay {
  session: {
    session_id: string;
    ir_id: string;
    epoch: number;
    last_turn_seq: number;
    idle_deadline: string;
    state: "open" | "closed";
  };
  turns: SessionTurn[];
  events: SessionEvent[];
  suggestions: SessionSuggestion[];
  source: "backend" | "demo";
}

export interface BenchmarkTask {
  task_id: string;
  type: string;
  judge: string;
  prompt_brief: string;
  done_criteria: string[];
  critical: boolean;
  split: "calibration" | "confirmatory" | "hidden";
}

export interface Preregistration {
  version: string;
  frozen_at: string;
  bench_version: string;
  bench_path: string;
  hidden_path: string;
  split: {
    total: number;
    calibration: number;
    confirmatory: number;
    machine_judgeable: number;
    critical: number;
  };
  primary_endpoint: {
    metric: string;
    test: string;
    alpha: number;
    note: string;
  };
  thresholds: { delta_imp: number; eps_ni: number; mde: number };
  baseline: {
    id: string;
    tier: string;
    human_blind_eval: boolean;
    caveat: string;
    sources: Array<{ id: string; url: string; license: string; usage: string }>;
  };
  models: string[];
  labels: Record<GateLabel, string>;
}

export interface BenchmarkData {
  tasks: BenchmarkTask[];
  preregistration: Preregistration;
  hidden: { declared: boolean; content_exposed: false; note: string };
  source: "backend" | "demo";
}

export interface Prompt5Api {
  getIRSchema(): Promise<Record<string, any>>;
  getModelCards(): Promise<ModelCard[]>;
  uploadBlob(file: File): Promise<BlobMeta>;
  createTask(input: CreateTaskInput): Promise<TaskEnvelope>;
  getTask(taskId: string): Promise<TaskEnvelope>;
  getRubric(taskId: string): Promise<RubricDraft>;
  confirmRubric(taskId: string): Promise<TaskEnvelope>;
  cancelTask(taskId: string): Promise<TaskEnvelope>;
  applyPatch(ir: PromptIR, ops: PatchOperation[], model: string, reason: string): Promise<PatchResult>;
  requestProtection(loc: string, cls: ProtectEntry["cls"]): Promise<{ loc: string; state: string }>;
  getEvaluation(): Promise<EvaluationReport>;
  runEvaluation(executor: "scripted" | "live", target: string): Promise<EvaluationReport>;
  getConfig(): Promise<Prompt5Config>;
  checkConfig(config: Prompt5Config): Promise<ConfigCheckResult>;
  saveConfig(config: Prompt5Config): Promise<ConfigCheckResult>;
  probeTarget(target: string): Promise<ProbeResult>;
  getSessionReplay(sessionId?: string): Promise<SessionReplay>;
  recordTurn(sessionId: string, text: string): Promise<SessionReplay>;
  getBenchmark(): Promise<BenchmarkData>;
}
