import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import {
  Check,
  ChevronDown,
  ChevronRight,
  Download,
  ExternalLink,
  FileLock2,
  FlaskConical,
  Search,
  ShieldCheck,
  Snowflake,
  X,
} from "lucide-react";
import {
  Badge,
  Button,
  Card,
  CardHeader,
  CopyButton,
  ErrorNotice,
  Notice,
  PageHeader,
  Skeleton,
  Tabs,
} from "../components/ui";
import { api } from "../lib/api";
import { cn, formatDate } from "../lib/utils";
import type { BenchmarkData, BenchmarkTask } from "../types";

export function BenchmarkPage() {
  const [searchParams] = useSearchParams();
  const requestedTask = searchParams.get("task") || "";
  const [data, setData] = useState<BenchmarkData | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [filter, setFilter] = useState("all");
  const [type, setType] = useState("all");
  const [query, setQuery] = useState(requestedTask);
  const [expanded, setExpanded] = useState<string | null>(requestedTask || null);

  async function load() {
    setError(null);
    try {
      setData(await api.getBenchmark());
    } catch (loadError) {
      setError(loadError);
    }
  }
  useEffect(() => { void load(); }, []);
  useEffect(() => {
    if (requestedTask) {
      setQuery(requestedTask);
      setExpanded(requestedTask);
    }
  }, [requestedTask]);

  const tasks = useMemo(() => {
    if (!data) return [];
    return data.tasks.filter((task) => {
      if (filter !== "all" && task.split !== filter) return false;
      if (type !== "all" && task.type !== type) return false;
      if (query && !`${task.task_id} ${task.prompt_brief}`.toLowerCase().includes(query.toLowerCase())) return false;
      return true;
    });
  }, [data, filter, type, query]);

  function exportPrereg() {
    if (!data) return;
    const url = URL.createObjectURL(new Blob([JSON.stringify(data.preregistration, null, 2)], { type: "application/json" }));
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `${data.preregistration.bench_version}-preregistration.json`;
    anchor.click();
    URL.revokeObjectURL(url);
  }

  const prereg = data?.preregistration;
  const types = data ? [...new Set(data.tasks.map((task) => task.type))] : [];

  return (
    <div className="benchmark-page">
      <PageHeader eyebrow="06 · Benchmark & Preregistration" title="先冻结口径，再看结果" description="浏览 30 条基准任务、校准/确证切分与预注册阈值。冻结文件只读，隐藏集内容不进入前端。" actions={<Button variant="secondary" disabled={!prereg} onClick={exportPrereg}><Download size={16} />导出预注册</Button>} />
      {error !== null && <div className="page-notice"><ErrorNotice error={error} onRetry={load} /></div>}
      {!data && !error && <Card><Skeleton lines={6} /></Card>}
      {data && prereg && (
        <>
          <div className="benchmark-stat-grid">
            <button className={cn("benchmark-stat", filter === "all" && "benchmark-stat-active")} onClick={() => setFilter("all")}><span>全部任务</span><strong>{prereg.split.total}</strong><small>100% 机器可判定</small></button>
            <button className={cn("benchmark-stat", filter === "calibration" && "benchmark-stat-active")} onClick={() => setFilter("calibration")}><span>Calibration</span><strong>{prereg.split.calibration}</strong><small>校准集 · 调参与排错</small></button>
            <button className={cn("benchmark-stat", filter === "confirmatory" && "benchmark-stat-active")} onClick={() => setFilter("confirmatory")}><span>Confirmatory</span><strong>{prereg.split.confirmatory}</strong><small>确证集 · 门禁统计</small></button>
            <div className="benchmark-stat benchmark-hidden-stat"><span>Hidden</span><strong><FileLock2 size={23} /></strong><small>内容隔离 · 不展示</small></div>
          </div>
          <Notice tone="warning" title="隐藏集隔离">{data.hidden.note} 声明路径 <code>{prereg.hidden_path}</code> 仅用于说明，不提供文件下载或内容预览。</Notice>
          <div className="benchmark-layout">
            <Card className="benchmark-tasks-card">
              <CardHeader title="基准任务" description={`${data.source === "demo" ? "仓库文件快照" : "后端只读数据"} · ${data.tasks.length} 条可见任务`} actions={<Badge tone="info">{prereg.bench_version}</Badge>} />
              <div className="benchmark-toolbar">
                <Tabs label="任务切分" active={filter} onChange={setFilter} items={[{ id: "all", label: "全部", count: data.tasks.length }, { id: "calibration", label: "校准", count: prereg.split.calibration }, { id: "confirmatory", label: "确证", count: prereg.split.confirmatory }, { id: "hidden", label: "隐藏", count: 0 }]} />
                <div className="benchmark-filters"><div className="search-box"><Search size={15} /><input aria-label="搜索基准任务" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索任务" />{query && <button aria-label="清空搜索" onClick={() => setQuery("")}><X size={14} /></button>}</div><select className="select" aria-label="按任务类型筛选" value={type} onChange={(event) => setType(event.target.value)}><option value="all">全部类型</option>{types.map((item) => <option value={item} key={item}>{item}</option>)}</select></div>
              </div>
              <div className="table-wrap benchmark-table-wrap">
                <table><thead><tr><th>任务</th><th>类型</th><th>Split</th><th>判定</th><th>关键</th><th><span className="sr-only">展开</span></th></tr></thead><tbody>{tasks.map((task) => <TaskRows key={task.task_id} task={task} expanded={expanded === task.task_id} onToggle={() => setExpanded(expanded === task.task_id ? null : task.task_id)} />)}</tbody></table>
                {!tasks.length && <div className="table-empty">{filter === "hidden" ? "隐藏任务按设计不可见；这里显示 0 条是正确行为。" : "没有符合当前筛选条件的任务。"}</div>}
              </div>
              <div className="table-footer">显示 {tasks.length} 条 · split 同时以文字和颜色标识，不依赖颜色单独传达含义</div>
            </Card>
            <aside className="benchmark-aside">
              <Card className="prereg-card"><CardHeader title="预注册" description="冻结后只读" actions={<Badge tone="success"><Snowflake size={12} />已冻结</Badge>} /><div className="prereg-body">
                <div className="frozen-time"><span>frozen_at</span><strong>{formatDate(prereg.frozen_at)}</strong><code>{prereg.frozen_at}</code></div>
                <div className="prereg-facts"><div><span>版本</span><code>{prereg.bench_version}</code></div><div><span>显著性 α</span><strong>{prereg.primary_endpoint.alpha}</strong></div><div><span>主端点</span><code>{prereg.primary_endpoint.metric}</code></div><div><span>检验</span><code>{prereg.primary_endpoint.test}</code></div></div>
                <section className="threshold-section"><h3>预注册阈值</h3><div><span>delta_imp<strong>{prereg.thresholds.delta_imp}</strong></span><span>eps_ni<strong>{prereg.thresholds.eps_ni}</strong></span><span>MDE<strong>{prereg.thresholds.mde}</strong></span></div></section>
                <section className="prereg-note"><h3>统计说明</h3><p>{prereg.primary_endpoint.note}</p></section>
              </div></Card>
              <Card><CardHeader title="门禁标签" description="标签定义随预注册冻结" /><div className="gate-definitions">{(["optimizing", "compatible", "rejected"] as const).map((label) => <div key={label}><Badge tone={label === "optimizing" ? "success" : label === "compatible" ? "info" : "danger"}>{label}</Badge><p>{prereg.labels[label]}</p></div>)}</div></Card>
              <Card><CardHeader title="B1-OSS 基线" description={`${prereg.baseline.id} · ${prereg.baseline.tier}`} /><div className="baseline-body"><Notice tone="info" title="开源专家模板基线，非人工盲写基线">{prereg.baseline.caveat}</Notice><div className="baseline-sources">{prereg.baseline.sources.map((source) => <a key={source.id} href={source.url} target="_blank" rel="noreferrer"><div><strong>{source.id}</strong><Badge tone="neutral">{source.license}</Badge><p>{source.usage}</p></div><ExternalLink size={14} /></a>)}</div></div></Card>
              <Card><div className="prereg-raw"><span>冻结文件内容</span><CopyButton label="复制 JSON" text={JSON.stringify(prereg, null, 2)} /></div></Card>
            </aside>
          </div>
          <div className="benchmark-assurance"><ShieldCheck size={16} /><span>预注册文件不提供编辑入口；隐藏集只显示隔离状态；基准数据与模拟/真实执行结果分开呈现。</span><FlaskConical size={16} /></div>
        </>
      )}
    </div>
  );
}

function TaskRows({ task, expanded, onToggle }: { task: BenchmarkTask; expanded: boolean; onToggle: () => void }) {
  return (
    <>
      <tr className={expanded ? "task-row-expanded" : ""}>
        <td><div className="benchmark-task-name"><code>{task.task_id}</code><span>{task.prompt_brief}</span></div></td>
        <td><Badge tone="neutral">{task.type}</Badge></td>
        <td><Badge tone={task.split === "calibration" ? "purple" : "info"}>{task.split}</Badge></td>
        <td>{task.judge}</td>
        <td>{task.critical ? <Badge tone="warning">关键</Badge> : <span className="text-muted">—</span>}</td>
        <td><button className="icon-button" aria-label={`${expanded ? "收起" : "展开"} ${task.task_id}`} aria-expanded={expanded} onClick={onToggle}>{expanded ? <ChevronDown size={15} /> : <ChevronRight size={15} />}</button></td>
      </tr>
      {expanded && <tr className="task-detail-row"><td colSpan={6}><div className="benchmark-task-detail"><section><h3>任务说明</h3><p>{task.prompt_brief}</p></section><section><h3>完成标准</h3><ul>{task.done_criteria.map((criterion, index) => <li key={index}><Check size={13} />{criterion}</li>)}</ul></section><div><Badge tone="neutral">{task.task_id}</Badge><Badge tone={task.split === "calibration" ? "purple" : "info"}>{task.split}</Badge>{task.critical && <Badge tone="warning">critical = true</Badge>}</div></div></td></tr>}
    </>
  );
}
