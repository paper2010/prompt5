import type { GateLabel, PromptIR } from "../types";

export function cn(...values: Array<string | false | null | undefined>): string {
  return values.filter(Boolean).join(" ");
}

export function formatDate(value?: string | null): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(date);
}

export function formatPercent(value: number, digits = 1): string {
  return `${(value * 100).toFixed(digits)}%`;
}

export function signed(value: number, digits = 3): string {
  return `${value >= 0 ? "+" : ""}${value.toFixed(digits)}`;
}

export function shortHash(value?: string, length = 10): string {
  if (!value) return "—";
  return value.length > length ? `${value.slice(0, length)}…` : value;
}

export const gateLabels: Record<GateLabel, { label: string; description: string; tone: "success" | "info" | "danger" }> = {
  optimizing: { label: "optimizing · 达改善门槛", description: "仅在当前任务集、模型快照和预算口径内成立。", tone: "success" },
  compatible: { label: "compatible · 非劣", description: "只表示非劣，不得宣称更优。", tone: "info" },
  rejected: { label: "rejected · 未通过", description: "低于非劣门槛或关键任务失败。", tone: "danger" },
};

export const turnKindLabels: Record<string, string> = {
  chitchat: "寒暄",
  progress: "进展",
  material: "材料变化",
  goal: "目标变化",
  constraint: "约束变化",
  correction: "纠正",
  uncertain: "语义不确定",
};

export const pathLabels: Record<string, string> = {
  "slots.role": "角色",
  "slots.goal.outcome": "目标",
  "slots.goal.done_criteria": "完成标准",
  "slots.goal.non_goals": "非目标",
  "slots.inputs": "输入材料",
  "slots.output.format": "输出格式",
  "slots.output.length_budget": "篇幅预算",
  "slots.constraints.must": "必须遵守",
  "slots.constraints.must_not": "禁止事项",
  "slots.constraints.style": "表达风格",
  "slots.workflow": "工作流",
  "slots.examples": "示例",
  freeform_extras: "补充说明",
};

export function pathLabel(path: string): string {
  const direct = pathLabels[path];
  if (direct) return direct;
  const container = Object.keys(pathLabels).find((key) => path.startsWith(`${key}[`) || path.startsWith(`${key}.`));
  return container ? pathLabels[container] : path;
}

export function protectedLocs(ir: PromptIR): Set<string> {
  return new Set(ir.protect_registry.filter((entry) => entry.state === "enacted").map((entry) => entry.loc));
}

export function isProtected(ir: PromptIR, loc: string): boolean {
  return [...protectedLocs(ir)].some((protectedLoc) => protectedLoc === loc || protectedLoc.startsWith(`${loc}.`) || protectedLoc.startsWith(`${loc}[`));
}

export function fileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}
