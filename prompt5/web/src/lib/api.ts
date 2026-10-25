import irSchemaJson from "../demo-data/vendor/ir.v3.schema.json";
import {
  demoBenchmark,
  demoConfig,
  demoEvaluation,
  demoModels,
  demoRubric,
  demoSession,
  demoTask,
} from "../demo-data/demo";
import type {
  ApiMode,
  BenchmarkData,
  BlobMeta,
  ConfigCheckResult,
  EvaluationReport,
  ModelCard,
  PatchOperation,
  Prompt5Api,
  Prompt5Config,
  PromptIR,
  ProbeResult,
  SessionReplay,
  TaskEnvelope,
} from "../types";

export const API_MODE: ApiMode = import.meta.env.VITE_API_MODE === "remote" ? "remote" : "demo";
export const CONNECTOR_ID = import.meta.env.VITE_CONNECTOR_ID || "host-agent-alpha";
export const TENANT_ID = import.meta.env.VITE_TENANT_ID || "t-001";
const TOKEN = import.meta.env.VITE_CONNECTOR_TOKEN || "";
export const DEMO_TASK_TEXT = "把每周销售 CSV 变成给管理层看的中文周报。先给关键结论，再展示指标表和异常解释；不要编造缺失数据。";

export class ApiError extends Error {
  code: string;
  status: number;
  detail: string;

  constructor(code: string, detail: string, status = 0) {
    super(detail || code);
    this.name = "ApiError";
    this.code = code;
    this.status = status;
    this.detail = detail;
  }
}

function clone<T>(value: T): T {
  return structuredClone(value);
}

function wait(ms = 240): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("Accept", "application/json");
  if (TOKEN) headers.set("Authorization", `Bearer ${TOKEN}`);
  if (TENANT_ID) headers.set("X-Tenant-Id", TENANT_ID);
  if (init.body && !(init.body instanceof File) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  let response: Response;
  try {
    response = await fetch(path, { ...init, headers });
  } catch (error) {
    throw new ApiError("E_NETWORK", `无法连接本地后端：${error instanceof Error ? error.message : "网络不可用"}`);
  }

  const contentType = response.headers.get("content-type") || "";
  const payload = contentType.includes("application/json") ? await response.json() : await response.text();
  if (!response.ok) {
    const data = typeof payload === "object" && payload !== null ? payload as Record<string, unknown> : {};
    throw new ApiError(
      String(data.error_code || `E_HTTP_${response.status}`),
      String(data.detail || (typeof payload === "string" ? payload : response.statusText)),
      response.status,
    );
  }
  return payload as T;
}

function jsonBody(value: unknown): string {
  return JSON.stringify(value);
}

function validateDemoConfig(config: Prompt5Config): ConfigCheckResult {
  const issues: ConfigCheckResult["issues"] = [];
  const missing = new Set<string>();
  const providers = config.providers;
  const referenced = new Set<string>([
    config.roles.generator.provider,
    config.roles.reflector.provider,
    ...config.roles.judges.map((judge) => judge.provider),
    ...Object.values(config.targets).map((target) => target.provider),
  ]);

  referenced.forEach((name) => {
    const provider = providers[name];
    if (!provider) {
      issues.push({ level: "error", code: "E_CONFIG_PROVIDER_UNKNOWN", field: `providers.${name}`, message: "角色或目标引用了不存在的供应商。" });
      return;
    }
    if (!provider.base_url.trim()) {
      issues.push({ level: "error", code: "E_CONFIG_ENDPOINT_MISSING", field: `providers.${name}.base_url`, message: `${provider.display || name} 缺少服务端点。` });
    }
    if (provider.api_key_required !== false && !provider.key_configured) {
      issues.push({ level: "error", code: "E_CONFIG_KEY_MISSING", field: `providers.${name}.api_key_env`, message: `请在服务端设置环境变量 ${provider.api_key_env}。` });
      missing.add(provider.api_key_env);
    }
  });

  if (config.roles.judges.length < 2) {
    issues.push({ level: "error", code: "E_CONFIG_JUDGE_POOL", field: "roles.judges", message: "裁判池至少需要 2 个异族模型。" });
  }
  const primaryCount = Object.values(config.targets).filter((target) => target.primary).length;
  if (primaryCount !== 1) {
    issues.push({ level: "error", code: "E_CONFIG_PRIMARY", field: "targets", message: "必须且只能设置一个 primary 目标。" });
  }
  return { ok: !issues.some((issue) => issue.level === "error"), issues, missing_env: [...missing], source: "demo" };
}

let demoCurrentTask = clone(demoTask);
let demoSavedConfig = clone(demoConfig);
let demoReplay = clone(demoSession);

const demoApi: Prompt5Api = {
  async getIRSchema() {
    await wait(80);
    return clone(irSchemaJson);
  },
  async getModelCards() {
    await wait(120);
    return clone(demoModels);
  },
  async uploadBlob(file) {
    await wait();
    return {
      blob_id: `blob-demo-${file.name}`,
      content_hash: "demo-only-not-a-content-hash",
      size: file.size,
      mime: file.type || "application/octet-stream",
      expires_at: "demo",
    };
  },
  async createTask(input) {
    await wait(420);
    if (input.text.trim() !== DEMO_TASK_TEXT) {
      throw new ApiError("E_DEMO_DYNAMIC_GENERATION_UNAVAILABLE", "演示模式仅运行预置周报任务；连接本地后端后可创建自定义任务。", 422);
    }
    demoCurrentTask = {
      task_id: `tk-demo-${input.idempotencyKey.slice(0, 8)}`,
      state: "rubric_pending",
      result_class: "pending",
      model: input.targetModel,
      draft: { text: input.text, rubric_policy: "draft_then_confirm" },
      rubric: clone(demoRubric),
      execution: { kind: "mock", label: "Mock 生成 · 不代表目标模型真实输出" },
    };
    return clone(demoCurrentTask);
  },
  async getTask() {
    await wait(100);
    return clone(demoCurrentTask);
  },
  async getRubric() {
    await wait(100);
    return clone(demoRubric);
  },
  async confirmRubric() {
    await wait(850);
    if (demoCurrentTask.state === "cancelled") {
      throw new ApiError("E_FENCING_STALE", "任务已取消，不能确认验收标准。", 409);
    }
    demoCurrentTask = {
      ...clone(demoTask),
      task_id: demoCurrentTask.task_id,
      model: demoCurrentTask.model,
      draft: demoCurrentTask.draft,
      rubric: clone(demoRubric),
    };
    return clone(demoCurrentTask);
  },
  async cancelTask() {
    await wait();
    demoCurrentTask = { ...demoCurrentTask, state: "cancelled", result_class: "pending" };
    return clone(demoCurrentTask);
  },
  async applyPatch() {
    throw new ApiError("E_DEMO_WRITE_DISABLED", "演示模式可查看 Patch 和 Diff，但不会改写 IR；连接后端后可由服务端应用 Patch。", 409);
  },
  async requestProtection(loc) {
    await wait();
    return { loc, state: "proposed" };
  },
  async getEvaluation() {
    await wait();
    return clone(demoEvaluation);
  },
  async runEvaluation(executor) {
    await wait(700);
    if (executor === "live") {
      throw new ApiError("E_LIVE_NOT_CONFIGURED", "演示模式不发送真实模型请求。请连接后端并完成端点配置。", 422);
    }
    return clone(demoEvaluation);
  },
  async getConfig() {
    await wait();
    return clone(demoSavedConfig);
  },
  async checkConfig(config) {
    await wait();
    return validateDemoConfig(config);
  },
  async saveConfig(config) {
    await wait(360);
    const result = validateDemoConfig(config);
    if (result.ok) demoSavedConfig = clone(config);
    return result;
  },
  async probeTarget(target) {
    await wait(520);
    const targetConfig = demoSavedConfig.targets[target];
    const provider = targetConfig ? demoSavedConfig.providers[targetConfig.provider] : undefined;
    return {
      target,
      ok: Boolean(provider?.base_url && (provider.key_configured || provider.api_key_required === false)),
      latency_ms: 0,
      detail: "演示探针：未发出网络请求，延迟不计入真实性能。",
      checked_at: new Date().toISOString(),
      source: "demo",
    };
  },
  async getSessionReplay() {
    await wait();
    return clone(demoReplay);
  },
  async recordTurn(_sessionId, text) {
    await wait(300);
    const trimmed = text.trim();
    if (!trimmed) throw new ApiError("E_SCHEMA_INVALID", "请输入一轮反馈。", 422);
    const kind = /谢谢|好的|收到/.test(trimmed) ? "chitchat" : /必须|不要|补充|禁止/.test(trimmed) ? "constraint" : "uncertain";
    const invalidates = kind !== "chitchat";
    const seq = demoReplay.session.last_turn_seq + 1;
    const eventSeq = Math.max(...demoReplay.events.map((event) => event.event_seq)) + 1;
    demoReplay.turns.push({ seq, role: "user", text: trimmed, kind, invalidates, created_at: new Date().toISOString() });
    demoReplay.events.push({ event_seq: eventSeq, event_type: "turn.recorded", state: "delivered", attempts: 1, payload: { seq, kind, invalidates }, created_at: new Date().toISOString() });
    demoReplay.session.last_turn_seq = seq;
    demoReplay.suggestions = demoReplay.suggestions.map((suggestion) => invalidates && suggestion.state === "proposed" ? { ...suggestion, state: "invalidated" } : suggestion);
    return clone(demoReplay);
  },
  async getBenchmark() {
    await wait();
    return clone(demoBenchmark);
  },
};

const remoteApi: Prompt5Api = {
  async getIRSchema() {
    const data = await request<Record<string, Record<string, any>>>("/v1/schema");
    return data["ir.v3"];
  },
  async getModelCards(): Promise<ModelCard[]> {
    const data = await request<{ model_cards: ModelCard[] }>("/v1/model-cards");
    return data.model_cards;
  },
  uploadBlob(file: File): Promise<BlobMeta> {
    return request<BlobMeta>("/v1/blobs", { method: "POST", headers: { "X-Blob-Mime": file.type || "application/octet-stream" }, body: file });
  },
  async createTask(input): Promise<TaskEnvelope> {
    return request<TaskEnvelope>("/v1/tasks", {
      method: "POST",
      body: jsonBody({
        api_version: "1",
        request_id: input.requestId,
        idempotency_key: input.idempotencyKey,
        connector_id: CONNECTOR_ID,
        tenant_id: TENANT_ID,
        op: "generate.v1",
        input: {
          mode: "zero",
          dialogue: [{ turn: 1, role: "user", text: input.text }],
          materials: input.materials,
          target_model: input.targetModel,
          rubric_policy: "draft_then_confirm",
        },
      }),
    });
  },
  getTask(taskId): Promise<TaskEnvelope> {
    return request<TaskEnvelope>(`/v1/tasks/${encodeURIComponent(taskId)}`);
  },
  getRubric(taskId) {
    return request(`/v1/ui/tasks/${encodeURIComponent(taskId)}/rubric`);
  },
  async confirmRubric(taskId): Promise<TaskEnvelope> {
    await request(`/v1/tasks/${encodeURIComponent(taskId)}/rubric:confirm`, { method: "POST" });
    return this.getTask(taskId);
  },
  async cancelTask(taskId): Promise<TaskEnvelope> {
    await request(`/v1/tasks/${encodeURIComponent(taskId)}/cancel`, { method: "POST" });
    return this.getTask(taskId);
  },
  applyPatch(ir: PromptIR, ops: PatchOperation[], model: string, reason: string) {
    return request("/v1/ui/ir/patch", { method: "POST", body: jsonBody({ ir, ops, model, reason, idempotency_key: crypto.randomUUID() }) });
  },
  requestProtection(loc, cls) {
    return request("/v1/protection-requests", { method: "POST", body: jsonBody({ loc, cls }) });
  },
  getEvaluation(): Promise<EvaluationReport> {
    return request("/v1/ui/evaluations/latest");
  },
  runEvaluation(executor, target): Promise<EvaluationReport> {
    return request("/v1/ui/evaluations/run", { method: "POST", body: jsonBody({ executor, target }) });
  },
  getConfig(): Promise<Prompt5Config> {
    return request("/v1/ui/config");
  },
  checkConfig(config): Promise<ConfigCheckResult> {
    return request("/v1/ui/config/check", { method: "POST", body: jsonBody(config) });
  },
  saveConfig(config): Promise<ConfigCheckResult> {
    return request("/v1/ui/config", { method: "PUT", body: jsonBody(config) });
  },
  probeTarget(target): Promise<ProbeResult> {
    return request("/v1/ui/config/probe", { method: "POST", body: jsonBody({ target }) });
  },
  getSessionReplay(sessionId): Promise<SessionReplay> {
    if (!sessionId) return Promise.reject(new ApiError("E_SESSION_REQUIRED", "请输入要回放的 session_id。", 422));
    return request(`/v1/ui/sessions/${encodeURIComponent(sessionId)}/replay`);
  },
  async recordTurn(sessionId, text): Promise<SessionReplay> {
    await request(`/v1/sessions/${encodeURIComponent(sessionId)}/events`, { method: "POST", body: jsonBody({ text, role: "user" }) });
    return this.getSessionReplay(sessionId);
  },
  getBenchmark(): Promise<BenchmarkData> {
    return request("/v1/ui/benchmark");
  },
};

export const api: Prompt5Api = API_MODE === "remote" ? remoteApi : demoApi;
