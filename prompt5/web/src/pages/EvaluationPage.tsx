import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  AlertTriangle,
  BarChart3,
  Check,
  ChevronRight,
  Download,
  Play,
  Search,
  ShieldCheck,
  X,
} from "lucide-react";
import { useApp } from "../components/AppContext";
import {
  Badge,
  Button,
  Card,
  CardHeader,
  CopyButton,
  EmptyState,
  ErrorNotice,
  Notice,
  PageHeader,
  Skeleton,
  Tabs,
} from "../components/ui";
import { api } from "../lib/api";
import { cn, formatDate, formatPercent, gateLabels, signed } from "../lib/utils";
import type { EvaluationReport } from "../types";

function RateValue({ value }: { value: number }) {
  return <span className={value >= 0.5 ? "pass-label" : "fail-label"} title="任务内 repeats 聚合通过率">{value === 1 ? <Check size={14} /> : value === 0 ? <X size={14} /> : <span aria-hidden="true">±</span>}{formatPercent(value, 0)}</span>;
}

function ConfidenceInterval({ report }: { report: EvaluationReport }) {
  const toX = (value: number) => 20 + ((value + 1) / 2) * 460;
  const low = toX(report.ci[0]);
  const high = toX(report.ci[1]);
  const mean = toX(report.mean_diff);
  const zero = toX(0);
  return (
    <div className="ci-chart">
      <svg viewBox="0 0 500 86" role="img" aria-label={`均值差 ${signed(report.mean_diff)}，95% 置信区间 ${signed(report.ci[0])} 到 ${signed(report.ci[1])}`}>
        <line x1="20" x2="480" y1="44" y2="44" stroke="#e4e7ec" strokeWidth="2" />
        <line x1={zero} x2={zero} y1="19" y2="66" stroke="#98a2b3" strokeDasharray="3 3" />
        <line x1={low} x2={high} y1="44" y2="44" stroke="#2f6fed" strokeWidth="6" strokeLinecap="round" />
        <line x1={low} x2={low} y1="33" y2="55" stroke="#2f6fed" strokeWidth="2" />
        <line x1={high} x2={high} y1="33" y2="55" stroke="#2f6fed" strokeWidth="2" />
        <circle cx={mean} cy="44" r="7" fill="#2f6fed" stroke="white" strokeWidth="3" />
        <text x={zero} y="80" textAnchor="middle" fill="#667085" fontSize="10">0</text>
        <text x={low} y="23" textAnchor="middle" fill="#475467" fontSize="10">{signed(report.ci[0])}</text>
        <text x={high} y="23" textAnchor="middle" fill="#475467" fontSize="10">{signed(report.ci[1])}</text>
      </svg>
    </div>
  );
}

export function EvaluationPage() {
  const { currentModel, setCurrentModel } = useApp();
  const [report, setReport] = useState<EvaluationReport | null>(null);
  const [executor, setExecutor] = useState<"scripted" | "live">("scripted");
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [tab, setTab] = useState("tasks");
  const [filter, setFilter] = useState("all");
  const [query, setQuery] = useState("");

  async function loadReport() {
    setLoading(true);
    setError(null);
    try {
      setReport(await api.getEvaluation());
    } catch (loadError) {
      setError(loadError);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { void loadReport(); }, []);

  async function run() {
    setRunning(true);
    setError(null);
    try {
      const next = await api.runEvaluation(executor, currentModel);
      setReport(next);
      setTab("tasks");
    } catch (runError) {
      setError(runError);
    } finally {
      setRunning(false);
    }
  }

  function exportReport() {
    if (!report) return;
    const url = URL.createObjectURL(new Blob([JSON.stringify(report, null, 2)], { type: "application/json" }));
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `${report.report_id}.json`;
    anchor.click();
    URL.revokeObjectURL(url);
  }

  const rows = useMemo(() => {
    if (!report) return [];
    return report.rows.filter((row) => {
      if (query && !`${row.task_id} ${row.brief}`.toLowerCase().includes(query.toLowerCase())) return false;
      if (filter === "different") return row.champion !== row.baseline;
      if (filter === "failed") return row.champion < 1;
      if (filter === "critical") return row.critical;
      return true;
    });
  }, [report, filter, query]);

  const gate = report ? gateLabels[report.label] : null;

  return (
    <div className="evaluation-page">
      <PageHeader
        eyebrow="03 · Evaluation"
        title="用证据判断，而不是凭感觉"
        description="比较当前候选与 B1-OSS 基线，保留逐任务结果、统计区间和门禁口径。L1 结构分不会在这里冒充效果分。"
        actions={report && <Button variant="secondary" onClick={exportReport}><Download size={16} />导出报告</Button>}
      />
      <Card className="eval-controls-card">
        <div className="eval-controls">
          <div className="field"><label htmlFor="eval-benchmark">基准任务集</label><select id="eval-benchmark" className="select" disabled={running}><option value="m7">M7 · 30 任务（确证集 20）</option></select></div>
          <div className="field"><label htmlFor="eval-candidate">候选与基线</label><select id="eval-candidate" className="select" disabled={running}><option>champion vs b1-oss</option></select></div>
          <div className="field"><label htmlFor="eval-target">目标模型</label><select id="eval-target" className="select" value={currentModel} onChange={(event) => setCurrentModel(event.target.value)} disabled={running}><option value="deepseek">deepseek</option><option value="zhipu">zhipu</option><option value="kimi">kimi</option><option value="qwen_oss">qwen_oss</option></select></div>
          <div className="field"><label htmlFor="eval-executor">执行器</label><select id="eval-executor" className="select" value={executor} onChange={(event) => setExecutor(event.target.value as "scripted" | "live")} disabled={running}><option value="scripted">scripted · 模拟</option><option value="live">live · 真实端点</option></select></div>
          <Button className="eval-run-button" loading={running} onClick={run}><Play size={16} />{running ? "正在运行" : "运行评测"}</Button>
        </div>
        <div className="eval-control-note"><ShieldCheck size={14} />live 需要已配置的真实端点；运行期间不显示没有数据依据的进度百分比。</div>
      </Card>
      {error !== null && <div className="page-notice"><ErrorNotice error={error} onRetry={report ? run : loadReport} /></div>}
      {loading && <Card><Skeleton lines={6} /></Card>}
      {!loading && !report && !error && <Card><EmptyState icon={<BarChart3 size={24} />} title="还没有评测报告">选择执行器并运行一次评测。</EmptyState></Card>}
      {!loading && report && gate && (
        <div className="eval-report">
          {report.simulated && <Notice tone="warning" title="模拟执行器·不构成效果证据">本次为 scripted 结果，仅验证评测与门禁链路；不能据此宣称真实模型效果。</Notice>}
          <Notice tone="info" title="基线口径">开源专家模板基线，非人工盲写基线。结论仅限当前机器可判定任务子集，不能外推到未测模型或未测任务。</Notice>
          <Card className={cn("gate-card", `gate-${report.label}`)}>
            <div className="gate-main">
              <div className="gate-icon">{report.label === "rejected" ? <AlertTriangle size={25} /> : <Check size={25} />}</div>
              <div><span className="gate-eyebrow">预注册门禁结果</span><h2>{gate.label}</h2><p>{gate.description}</p></div>
              <Badge tone={gate.tone}>{report.model}</Badge>
            </div>
            <div className="gate-reason">{report.reason}</div>
            <div className="report-meta-row"><span>报告 {report.report_id}</span><span>{formatDate(report.created_at)}</span><span>n={report.n_tasks} 个确证任务</span><Badge tone={report.source === "demo" ? "warning" : "neutral"}>{report.source === "demo" ? "演示快照" : "后端报告"}</Badge></div>
          </Card>
          <div className="metric-grid">
            <Card className="metric-card"><span>Champion 通过率</span><strong>{formatPercent(report.champion_rate)}</strong><small>当前候选 · {report.n_tasks} 任务</small></Card>
            <Card className="metric-card"><span>B1-OSS 通过率</span><strong>{formatPercent(report.baseline_rate)}</strong><small>开源专家模板基线</small></Card>
            <Card className="metric-card metric-primary"><span>均值差</span><strong>{signed(report.mean_diff)}</strong><small>95% CI [{signed(report.ci[0])}, {signed(report.ci[1])}]</small></Card>
            <Card className="metric-card"><span>McNemar p</span><strong>{report.p_value.toFixed(4)}</strong><small>任务层配对检验 · α=0.05</small></Card>
          </div>
          <Card className="ci-card">
            <CardHeader title="均值差与 95% 置信区间" description="点估计只是中心，区间与配对检验必须一起解读" actions={<Badge tone="neutral">bootstrap 95% CI</Badge>} />
            <div className="ci-body"><ConfidenceInterval report={report} /><div className="ci-labels"><span>-1 · 候选更差</span><span>0 · 无差异</span><span>+1 · 候选更好</span></div></div>
          </Card>
          <div className="report-tabs-row"><Tabs label="评测报告视图" active={tab} onChange={setTab} items={[{ id: "tasks", label: "逐任务结果", count: report.rows.length }, { id: "method", label: "统计口径" }, { id: "evidence", label: "证据信息" }]} /></div>
          {tab === "tasks" && (
            <Card className="eval-table-card">
              <div className="table-toolbar">
                <div className="search-box"><Search size={15} /><input aria-label="搜索任务" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索任务 ID 或内容" />{query && <button aria-label="清空搜索" onClick={() => setQuery("")}><X size={14} /></button>}</div>
                <Tabs label="任务筛选" active={filter} onChange={setFilter} items={[{ id: "all", label: "全部" }, { id: "different", label: "结果不同" }, { id: "failed", label: "候选未通过" }, { id: "critical", label: "关键任务" }]} />
              </div>
              <div className="table-wrap eval-table-wrap">
                <table>
                  <thead><tr><th>任务</th><th>类型</th><th>Champion</th><th>B1-OSS</th><th>差值</th><th><span className="sr-only">详情</span></th></tr></thead>
                  <tbody>
                    {rows.map((row) => (
                      <tr key={row.task_id}>
                        <td><div className="task-cell"><code>{row.task_id}</code>{row.critical && <Badge tone="warning">关键</Badge>}<span>{row.brief}</span></div></td>
                        <td><Badge tone="neutral">{row.split}</Badge></td>
                        <td><RateValue value={row.champion} /></td>
                        <td><RateValue value={row.baseline} /></td>
                        <td><code className={row.champion - row.baseline > 0 ? "text-success" : row.champion - row.baseline < 0 ? "text-danger" : "text-muted"}>{signed(row.champion - row.baseline, 0)}</code></td>
                        <td><Link className="icon-button" aria-label={`在基准页查看 ${row.task_id}`} title="在基准页查看" to={`/benchmark?task=${encodeURIComponent(row.task_id)}`}><ChevronRight size={15} /></Link></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {!rows.length && <div className="table-empty">没有符合当前筛选条件的任务。</div>}
              </div>
              <div className="table-footer">显示 {rows.length} / {report.rows.length} 个任务 · 通过率为任务内 repeats 聚合后的结果</div>
            </Card>
          )}
          {tab === "method" && (
            <Card><CardHeader title="统计口径" description="本报告可以支持什么结论，以及不能支持什么结论" /><div className="method-grid">
              <section><span>主端点</span><h3>机器可判定任务成功率</h3><p>只统计机器可判定任务；repeats 先在任务内聚合，不以重复次数虚增样本量。</p></section>
              <section><span>配对检验</span><h3>McNemar exact</h3><p>在当前 20 个确证任务上比较候选与基线的离散结果，显著性阈值为 0.05。</p></section>
              <section><span>改善门槛</span><h3>delta_imp = 0.10</h3><p>p 值、CI 下限和均值差需要联合满足预注册条件，不能只看其中一个。</p></section>
              <section><span>非劣门槛</span><h3>eps_ni = 0.05</h3><p>compatible 仅表示非劣。证据不足时显示证据不足，不包装成“效果更好”。</p></section>
              <section><span>关键任务闸门</span><h3>{report.critical_failures} 个失败</h3><p>关键任务失败会直接导致 rejected，不被整体平均通过率抵消。</p></section>
              <section><span>人工评价</span><h3>未启用</h3><p>本报告没有人工盲评预算，也不是人工专家对比实验。</p></section>
            </div></Card>
          )}
          {tab === "evidence" && (
            <Card><CardHeader title="证据与复现信息" description="执行器、模型快照、基线与报告原文" actions={<CopyButton label="复制 JSON" text={JSON.stringify(report, null, 2)} />} /><div className="report-evidence">
              <div className="evidence-grid"><div><span>执行器</span><strong>{report.executor}</strong></div><div><span>模型快照</span><code>{report.model}</code></div><div><span>基准版本</span><code>{report.bench_version}</code></div><div><span>候选</span><code>{report.candidate}</code></div><div><span>基线</span><code>{report.baseline_id}</code></div><div><span>证据来源</span><strong>{report.source === "demo" ? "固定演示快照" : "后端运行报告"}</strong></div></div>
              <Notice tone={report.simulated ? "warning" : "success"} title={report.simulated ? "模拟执行器·不构成效果证据" : "live 执行器"}>{report.baseline_label}。模型快照、任务集和统计口径必须随报告一起引用。</Notice>
              <pre className="json-view">{JSON.stringify({ ...report, rows: `[${report.rows.length} rows]` }, null, 2)}</pre>
            </div></Card>
          )}
        </div>
      )}
    </div>
  );
}
