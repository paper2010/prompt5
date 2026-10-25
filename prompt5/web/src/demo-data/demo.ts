import benchmarkRaw from "./vendor/tasks_m7.jsonl?raw";
import preregistrationJson from "./vendor/preregistration.json";
import type {
  BenchmarkData,
  BenchmarkTask,
  EvaluationReport,
  ModelCard,
  Preregistration,
  Prompt5Config,
  PromptIR,
  SessionReplay,
  TaskEnvelope,
} from "../types";

export const demoModels: ModelCard[] = [
  { target: "deepseek", provider: "deepseek", model: "deepseek-chat", tier: "T2", label: "optimizing", primary: true },
  { target: "zhipu", provider: "zhipu", model: "glm-4.6", tier: "T2", label: "compatible", primary: false },
  { target: "kimi", provider: "kimi", model: "kimi-k2", tier: "T2", label: "compatible", primary: false },
  { target: "minimax", provider: "minimax", model: "MiniMax-M2", tier: "T2", label: "compatible", primary: false },
  { target: "mimo", provider: "mimo", model: "mimo-7b-rl", tier: "T2", label: "compatible", primary: false },
  { target: "qwen_oss", provider: "local", model: "qwen-oss-14b", tier: "T1", label: "compatible", primary: false },
];

export const demoIR: PromptIR = {
  schema_version: "3",
  ir_id: "ir-demo-weekly-report",
  version: 3,
  parent_ir_version: 2,
  lineage_id: "ln-demo-weekly-report",
  checksum: "9f27bb90f0ed3640aa8b1a1130b5f9b24c5b304f32de08f720bc665dd0256f6a",
  created: { strategy_id: "demo.readable_workbench", actor: "demo" },
  slots: {
    role: "你是一名严谨的数据分析助手，擅长将销售数据整理为管理层周报。",
    goal: {
      outcome: "把每周销售 CSV 转化为面向管理层的中文周报，突出结论、指标变化和异常。",
      done_criteria: ["先给出不超过 3 条关键结论", "包含核心指标表与异常说明", "所有数字均可追溯到输入数据"],
      non_goals: ["不编造缺失数据", "不输出与周报无关的背景知识"],
    },
    inputs: [{ ref: "weekly-sales.csv", type: "text", note: "用户上传的每周销售 CSV", trust: "user" }],
    output: { format: "Markdown 周报", schema: null, length_budget: "800 字以内" },
    constraints: {
      must: ["结论先行", "指标变化同时给出绝对值与百分比", "异常数据单独说明"],
      must_not: ["不得编造输入中不存在的数据或原因"],
      style: ["简洁、专业、面向管理层"],
    },
    examples: [],
    workflow: ["检查字段、缺失值与统计口径", "计算核心指标及环比变化", "提炼关键结论与异常", "按固定结构输出周报"],
    feedback_protocol: { on_missing: "标记数据不足并停止推断" },
  },
  freeform_extras: [],
  provenance_map: {
    "0a1b2c3d4e": { source: "user", note: "用户要求结论先行" },
    "10abcdef01": { source: "system", note: "数据可信性约束" },
  },
  protect_registry: [
    { loc: "slots.constraints.must_not[10abcdef01]", cls: "safety", state: "enacted", by: "system" },
  ],
  item_ids: {
    "slots.goal.done_criteria": ["aa00000001", "aa00000002", "aa00000003"],
    "slots.goal.non_goals": ["bb00000001", "bb00000002"],
    "slots.inputs": ["cc00000001"],
    "slots.constraints.must": ["0a1b2c3d4e", "dd00000002", "dd00000003"],
    "slots.constraints.must_not": ["10abcdef01"],
    "slots.constraints.style": ["ee00000001"],
    "slots.workflow": ["ff00000001", "ff00000002", "ff00000003", "ff00000004"],
    "slots.examples": [],
    freeform_extras: [],
  },
};

export const demoRubric = {
  version: "demo-rubric-v1",
  source: "demo" as const,
  criteria: ["覆盖周报的核心目标与读者", "包含结论、指标表和异常说明", "不得编造缺失数据", "输出为 800 字以内的 Markdown"],
  note: "这是演示验收标准；真实任务由后端返回对应草案。",
};

export const demoTask: TaskEnvelope = {
  task_id: "tk-demo-weekly-report",
  state: "succeeded",
  result_class: "full",
  model: "deepseek",
  draft: {
    text: "把每周销售 CSV 变成给管理层看的中文周报。先给关键结论，再展示指标表和异常解释；不要编造缺失数据。",
    rubric_policy: "draft_then_confirm",
  },
  rubric: demoRubric,
  ir: demoIR,
  rendered: {
    cache_key: "demo-render-deepseek-v3",
    text: "# 角色\n你是一名严谨的数据分析助手，擅长将销售数据整理为管理层周报。\n\n# 任务\n把每周销售 CSV 转化为面向管理层的中文周报，突出结论、指标变化和异常。\n\n# 输出要求\n- 先给出不超过 3 条关键结论。\n- 展示核心指标表，变化同时给出绝对值与百分比。\n- 单独解释异常数据；无法解释时明确标记“数据不足”。\n- 全文不超过 800 字，使用 Markdown。\n\n# 工作流\n1. 检查字段、缺失值与统计口径。\n2. 计算核心指标及环比变化。\n3. 提炼关键结论与异常。\n4. 按固定结构输出周报。\n\n# 数据可信性\n不得编造输入中不存在的数据或原因。",
  },
  l1: {
    passed: true,
    score: 0.96,
    token_estimate: 412,
    findings: [{ severity: "info", code: "L1_STRUCTURE_OK", message: "结构完整：目标、约束、工作流与输出格式均已声明。", loc: "" }],
  },
  evidence: {
    level: "L1",
    rubric_version: "demo-rubric-v1",
    metrics: {},
    reproduction_tier: "T2",
    model_snapshot: "deepseek@mock",
    decode: { temperature: 0 },
    renderer_version: "demo-renderer-v1",
    baseline_id: null,
    label: null,
    expires_at: null,
  },
  execution: { kind: "mock", label: "Mock 生成 · 不代表目标模型真实输出" },
};

export const benchmarkTasks = benchmarkRaw
  .split(/\r?\n/)
  .filter(Boolean)
  .map((line) => JSON.parse(line) as BenchmarkTask);

export const demoPreregistration = preregistrationJson as unknown as Preregistration;

const confirmatory = benchmarkTasks.filter((task) => task.split === "confirmatory");
const rows = confirmatory.map((task, index) => {
  const champion = index < 18 ? 1 : 0;
  const baseline = index >= 11 && index < 18 ? 1 : 0;
  return {
    task_id: task.task_id,
    brief: task.prompt_brief,
    split: task.split,
    critical: task.critical,
    champion,
    baseline,
  };
});

export const demoEvaluation: EvaluationReport = {
  report_id: "eval-demo-m7-gate",
  benchmark: "benchmarks/tasks_m7.jsonl",
  bench_version: "m7-v1",
  model: "deepseek@scripted",
  executor: "scripted",
  simulated: true,
  created_at: "2026-10-25T03:23:01+00:00",
  candidate: "champion",
  baseline_id: "b1-oss",
  baseline_label: "开源专家模板基线，非人工盲写基线",
  label: "optimizing",
  reason: "McNemar p=0.0010 < 0.05，CI 下限 +0.350 > 0，均差 +0.550 ≥ delta_imp 0.1。仅说明该模拟任务集内的门禁结果。",
  mean_diff: 0.55,
  ci: [0.35, 0.8],
  p_value: 0.001,
  n_tasks: 20,
  critical_failures: 0,
  champion_rate: 0.9,
  baseline_rate: 0.35,
  rows,
  source: "demo",
};

export const demoConfig: Prompt5Config = {
  providers: {
    deepseek: { display: "DeepSeek", base_url: "https://api.deepseek.com/v1", api_key_env: "DSK_KEY", timeout: 120, key_configured: true },
    zhipu: { display: "智谱 GLM", base_url: "https://open.bigmodel.cn/api/paas/v4", api_key_env: "ZHIPU_KEY", key_configured: true },
    kimi: { display: "Moonshot Kimi", base_url: "https://api.moonshot.cn/v1", api_key_env: "KIMI_KEY", key_configured: true },
    minimax: { display: "MiniMax", base_url: "", api_key_env: "MINIMAX_KEY", key_configured: false },
    mimo: { display: "小米 MiMo", base_url: "", api_key_env: "MIMO_KEY", key_configured: false },
    local: { display: "自托管", base_url: "http://127.0.0.1:8000/v1", api_key_env: "LOCAL_LLM_KEY", api_key_required: false, timeout: 60, key_configured: false },
  },
  roles: {
    generator: { provider: "deepseek", model: "deepseek-chat" },
    reflector: { provider: "deepseek", model: "deepseek-chat" },
    judges: [
      { provider: "zhipu", model: "glm-4.6" },
      { provider: "kimi", model: "kimi-k2" },
    ],
  },
  targets: {
    deepseek: { provider: "deepseek", model: "deepseek-chat", tier: "T2", label: "optimizing", primary: true },
    zhipu: { provider: "zhipu", model: "glm-4.6", tier: "T2", label: "compatible" },
    kimi: { provider: "kimi", model: "kimi-k2", tier: "T2", label: "compatible" },
    qwen_oss: { provider: "local", model: "qwen-oss-14b", tier: "T1", label: "compatible" },
  },
};

export const demoSession: SessionReplay = {
  session: {
    session_id: "s-demo-replay",
    ir_id: demoIR.ir_id,
    epoch: 2,
    last_turn_seq: 3,
    idle_deadline: "2026-10-26T11:30:00+08:00",
    state: "open",
  },
  turns: [
    { seq: 1, role: "user", text: "请先给结论，再给出数据依据。", kind: "constraint", invalidates: true, created_at: "2026-10-25T11:18:00+08:00" },
    { seq: 2, role: "user", text: "谢谢，整体结构保留。", kind: "chitchat", invalidates: false, created_at: "2026-10-25T11:20:00+08:00" },
    { seq: 3, role: "user", text: "补充：不要编造缺失数据。", kind: "constraint", invalidates: true, created_at: "2026-10-25T11:24:00+08:00" },
  ],
  events: [
    { event_seq: 1, event_type: "session.opened", state: "delivered", attempts: 1, payload: { ir_id: demoIR.ir_id }, created_at: "2026-10-25T11:16:00+08:00" },
    { event_seq: 2, event_type: "turn.recorded", state: "delivered", attempts: 1, payload: { seq: 1, kind: "constraint", invalidated_suggestions: 0 }, created_at: "2026-10-25T11:18:00+08:00" },
    { event_seq: 3, event_type: "suggestion.applied", state: "delivered", attempts: 1, payload: { suggestion_id: "sg-demo-001", new_epoch: 1 }, created_at: "2026-10-25T11:19:00+08:00" },
    { event_seq: 4, event_type: "turn.recorded", state: "delivered", attempts: 1, payload: { seq: 2, kind: "chitchat", invalidated_suggestions: 0 }, created_at: "2026-10-25T11:20:00+08:00" },
    { event_seq: 5, event_type: "suggestion.proposed", state: "delivered", attempts: 1, payload: { suggestion_id: "sg-demo-002", epoch: 1 }, created_at: "2026-10-25T11:22:00+08:00" },
    { event_seq: 6, event_type: "turn.recorded", state: "delivered", attempts: 2, payload: { seq: 3, kind: "constraint", invalidated_suggestions: 1 }, created_at: "2026-10-25T11:24:00+08:00" },
    { event_seq: 7, event_type: "suggestion.applied", state: "delivered", attempts: 1, payload: { suggestion_id: "sg-demo-003", new_epoch: 2 }, created_at: "2026-10-25T11:25:00+08:00" },
  ],
  suggestions: [
    { suggestion_id: "sg-demo-001", state: "applied", summary: "增加“结论先行”约束", epoch: 0, base_checksum: "7a13…c091", created_at: "2026-10-25T11:17:00+08:00" },
    { suggestion_id: "sg-demo-002", state: "invalidated", summary: "将篇幅调整为 1,000 字", epoch: 1, base_checksum: "82bd…f117", created_at: "2026-10-25T11:22:00+08:00" },
    { suggestion_id: "sg-demo-003", state: "applied", summary: "增加“数据不足时停止推断”协议", epoch: 1, base_checksum: "82bd…f117", created_at: "2026-10-25T11:25:00+08:00" },
  ],
  source: "demo",
};

export const demoBenchmark: BenchmarkData = {
  tasks: benchmarkTasks,
  preregistration: demoPreregistration,
  hidden: {
    declared: true,
    content_exposed: false,
    note: "预注册声明了隐藏集路径，但快照未包含隐藏集内容。UI 不请求、不展示、不推断隐藏题目。",
  },
  source: "demo",
};
