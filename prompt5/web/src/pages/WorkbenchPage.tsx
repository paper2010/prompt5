import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  ArrowRight,
  Braces,
  Check,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Circle,
  FileText,
  Paperclip,
  Plus,
  RotateCcw,
  ShieldCheck,
  Sparkles,
  Trash2,
  X,
} from "lucide-react";
import { useApp } from "../components/AppContext";
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
  Steps,
  Tabs,
} from "../components/ui";
import { API_MODE, api, DEMO_TASK_TEXT } from "../lib/api";
import { cn, fileSize, shortHash } from "../lib/utils";
import type { BlobMeta, ModelCard, RubricDraft } from "../types";

interface PendingFile {
  file: File;
  blob?: BlobMeta;
}

const examples = [
  DEMO_TASK_TEXT,
  "把每周销售 CSV 变成给管理层看的中文周报。先给关键结论，再展示指标表和异常解释；不要编造缺失数据。",
];

export function WorkbenchPage() {
  const { currentTask, setCurrentTask, setCurrentIR, currentModel, setCurrentModel } = useApp();
  const [text, setText] = useState(API_MODE === "demo" ? DEMO_TASK_TEXT : "");
  const [models, setModels] = useState<ModelCard[]>([]);
  const [modelError, setModelError] = useState<unknown>(null);
  const [files, setFiles] = useState<PendingFile[]>([]);
  const [rubric, setRubric] = useState<RubricDraft | null>(null);
  const [rubricAccepted, setRubricAccepted] = useState(false);
  const [busy, setBusy] = useState<"create" | "confirm" | "cancel" | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [resultTab, setResultTab] = useState("rendered");
  const [showEvidence, setShowEvidence] = useState(false);
  const requestRef = useRef<{ fingerprint: string; key: string; requestId: string } | null>(null);

  async function loadModels() {
    setModelError(null);
    try {
      const cards = await api.getModelCards();
      setModels(cards);
      const primary = cards.find((card) => card.primary) || cards[0];
      if (primary && !cards.some((card) => card.target === currentModel)) setCurrentModel(primary.target);
    } catch (loadError) {
      setModelError(loadError);
    }
  }

  useEffect(() => { void loadModels(); }, []);

  useEffect(() => {
    if (currentTask?.state !== "rubric_pending") return;
    setRubricAccepted(false);
    setError(null);
    api.getRubric(currentTask.task_id).then(setRubric).catch(setError);
  }, [currentTask?.task_id, currentTask?.state]);

  const fingerprint = JSON.stringify({
    text: text.trim(),
    model: currentModel,
    files: files.map(({ file, blob }) => ({ name: file.name, size: file.size, blob: blob?.blob_id })),
  });

  async function createTask() {
    setError(null);
    if (!text.trim()) {
      setError(new Error("请先描述你希望模型完成的任务。"));
      return;
    }
    if (!currentModel) {
      setError(new Error("请选择一个目标模型。"));
      return;
    }
    setBusy("create");
    try {
      const uploaded = await Promise.all(files.map(async (entry) => {
        if (entry.blob) return entry;
        const blob = await api.uploadBlob(entry.file);
        return { ...entry, blob };
      }));
      setFiles(uploaded);
      if (!requestRef.current || requestRef.current.fingerprint !== fingerprint) {
        requestRef.current = { fingerprint, key: crypto.randomUUID(), requestId: crypto.randomUUID() };
      }
      const task = await api.createTask({
        text: text.trim(),
        targetModel: currentModel,
        materials: uploaded.flatMap((entry) => entry.blob ? [{ blob_id: entry.blob.blob_id }] : []),
        idempotencyKey: requestRef.current.key,
        requestId: requestRef.current.requestId,
      });
      setCurrentTask(task);
      setRubric(null);
    } catch (createError) {
      setError(createError);
    } finally {
      setBusy(null);
    }
  }

  async function confirmTask() {
    if (!currentTask || !rubricAccepted || busy) return;
    setBusy("confirm");
    setError(null);
    try {
      let latest = await api.confirmRubric(currentTask.task_id);
      let attempts = 0;
      while (latest.state === "running" && attempts < 90) {
        await new Promise((resolve) => window.setTimeout(resolve, 1000));
        latest = await api.getTask(currentTask.task_id);
        attempts += 1;
      }
      if (latest.state === "running") throw new Error("任务仍在执行，请稍后刷新状态；不要重复确认。");
      setCurrentTask(latest);
      if (latest.ir) setCurrentIR(latest.ir);
    } catch (confirmError) {
      try {
        const latest = await api.getTask(currentTask.task_id);
        if (latest.state === "succeeded") {
          setCurrentTask(latest);
          return;
        }
      } catch {
        // 保留原始确认错误，避免用二次网络错误覆盖真正原因。
      }
      setError(confirmError);
    } finally {
      setBusy(null);
    }
  }

  async function cancelAndEdit() {
    if (!currentTask) return;
    setBusy("cancel");
    setError(null);
    try {
      await api.cancelTask(currentTask.task_id);
      setCurrentTask(null);
      setRubric(null);
      requestRef.current = null;
    } catch (cancelError) {
      setError(cancelError);
    } finally {
      setBusy(null);
    }
  }

  function newTask() {
    setCurrentTask(null);
    setCurrentIR(API_MODE === "demo" ? currentTask?.ir || null : null);
    setRubric(null);
    setFiles([]);
    setError(null);
    setShowEvidence(false);
    setRubricAccepted(false);
    requestRef.current = null;
  }

  function addFiles(selected: FileList | null) {
    if (!selected) return;
    const next = Array.from(selected).filter((file) => file.size <= 10 * 1024 * 1024);
    setFiles((existing) => [...existing, ...next.map((file) => ({ file }))].slice(0, 20));
  }

  const step = currentTask?.state === "succeeded" ? 3 : currentTask?.state === "rubric_pending" || currentTask?.state === "running" ? 2 : 1;
  const isMock = currentTask?.execution?.kind === "mock" || currentTask?.evidence?.model_snapshot.includes("@mock");

  return (
    <div className="workbench-page">
      <PageHeader
        eyebrow="Generate → Confirm → Evaluate"
        title={step === 1 ? "把想法变成可用的提示词" : step === 2 ? "先确认标准，再开始生成" : "你的提示词已生成"}
        description={step === 1 ? "只需描述任务并选择目标模型。系统会先整理验收标准，由你确认后才生成。" : step === 2 ? "这是必须的人工锚点。请核对验收标准，确认前不会调用生成流程。" : "渲染文本可直接使用；IR、L1 与证据保留完整的结构和复现信息。"}
        actions={currentTask?.state === "succeeded" && <Button variant="secondary" onClick={newTask}><Plus size={16} />新建任务</Button>}
      />
      <Steps current={step} />
      {error !== null && <div className="page-notice"><ErrorNotice error={error} onRetry={step === 1 ? createTask : undefined} /></div>}

      {step === 1 && (
        <div className="composer-layout">
          <Card className="composer-card">
            <div className="composer-body">
              <div className="field">
                <div className="field-label-row">
                  <label htmlFor="task-input">你想完成什么？</label>
                  <span className="field-hint">{text.length} 字</span>
                </div>
                <textarea
                  id="task-input"
                  className="textarea task-textarea"
                  value={text}
                  onChange={(event) => setText(event.target.value)}
                  placeholder="例如：把这份 CSV 做成面向管理层的中文分析报告，先给结论，并标注数据缺口……"
                  rows={7}
                />
                <div className="example-row">
                  <span>试试示例</span>
                  <button type="button" onClick={() => setText(examples[0])}>销售数据周报</button>
                </div>
              </div>
              <div className="composer-options">
                <div className="field">
                  <label htmlFor="target-model">目标模型</label>
                  <select id="target-model" className="select" value={currentModel} onChange={(event) => setCurrentModel(event.target.value)} disabled={!models.length}>
                    {!models.length && <option value="">正在读取模型卡…</option>}
                    {models.map((card) => <option key={card.target} value={card.target}>{card.target}{card.primary ? " · 默认" : ""}（{card.model}）</option>)}
                  </select>
                  <span className="field-hint">按所选模型卡渲染，不代表已在该模型上实测。</span>
                </div>
                <div className="field">
                  <span className="field-label">参考材料 <span className="optional">可选</span></span>
                  <label className="upload-button" htmlFor="material-input"><Paperclip size={16} />添加文件</label>
                  <input id="material-input" className="sr-only" type="file" multiple accept=".csv,.txt,.md,.json,.pdf" onChange={(event) => addFiles(event.target.files)} />
                  <span className="field-hint">单个文件不超过 10 MB，服务端计算内容哈希。</span>
                </div>
              </div>
              {files.length > 0 && (
                <ul className="file-list" aria-label="待上传材料">
                  {files.map((entry, index) => (
                    <li key={`${entry.file.name}-${entry.file.lastModified}`}>
                      <FileText size={16} />
                      <span className="grow">{entry.file.name}<small>{fileSize(entry.file.size)}{entry.blob ? " · 已上传" : " · 待上传"}</small></span>
                      <button className="icon-button" aria-label={`移除 ${entry.file.name}`} onClick={() => setFiles((items) => items.filter((_, itemIndex) => itemIndex !== index))}><X size={15} /></button>
                    </li>
                  ))}
                </ul>
              )}
              {modelError !== null && <ErrorNotice error={modelError} onRetry={loadModels} />}
              <div className="composer-footer">
                <span className="composer-assurance"><ShieldCheck size={16} />创建后仍需你确认验收标准</span>
                <Button size="lg" loading={busy === "create"} onClick={createTask}>
                  {busy === "create" ? "正在创建" : "创建任务"}{busy !== "create" && <ArrowRight size={17} />}
                </Button>
              </div>
            </div>
          </Card>
          <aside className="composer-aside">
            <Card>
              <CardHeader title="这次会怎样进行？" />
              <div className="how-it-works">
                <div><span>1</span><p><strong>整理需求</strong><small>提取目标、约束与输出格式</small></p></div>
                <div><span>2</span><p><strong>你来确认</strong><small>没有自动跳过或自动确认</small></p></div>
                <div><span>3</span><p><strong>生成并检查</strong><small>查看 IR、渲染文本与 L1 结构检查</small></p></div>
              </div>
            </Card>
            <Notice tone="info" title="简单模式">
              高级字段默认收起。需要精细调整时，再进入 IR 编辑器查看 Patch 和 Diff。
            </Notice>
          </aside>
        </div>
      )}

      {step === 2 && currentTask && (
        <div className="rubric-layout">
          <Card>
            <CardHeader
              title="验收标准（Rubric）"
              description={`任务 ${currentTask.task_id} · ${currentTask.model}`}
              actions={<Badge tone="warning" dot>等待人工确认</Badge>}
            />
            <div className="rubric-body">
              <div className="task-recap">
                <span className="field-label">你的任务</span>
                <p>{currentTask.draft?.text || text}</p>
              </div>
              {!rubric && !error && <Skeleton lines={4} />}
              {rubric && (
                <>
                  <div className="rubric-list-heading">
                    <div><h3>请确认以下验收要点</h3><p>版本 <code>{rubric.version}</code> · 当前为只读草案</p></div>
                    <Badge tone="info">{rubric.criteria.length} 项</Badge>
                  </div>
                  <ol className="rubric-list">
                    {rubric.criteria.map((criterion, index) => (
                      <li key={criterion}><span>{index + 1}</span><p>{criterion}</p></li>
                    ))}
                  </ol>
                  {rubric.note && <p className="rubric-note">{rubric.note}</p>}
                </>
              )}
              {busy === "confirm" && <Notice tone="info">后端正在同步执行生成。没有真实进度数据时，界面不会显示百分比或假装流式输出。</Notice>}
              <div className="rubric-confirm-box">
                <label className="checkbox-row">
                  <input type="checkbox" checked={rubricAccepted} onChange={(event) => setRubricAccepted(event.target.checked)} disabled={!rubric || busy === "confirm"} />
                  <span>我已阅读并确认这些验收标准，可以用于本次任务。</span>
                </label>
                <div className="rubric-actions">
                  <Button variant="secondary" loading={busy === "cancel"} disabled={busy === "confirm"} onClick={cancelAndEdit}><RotateCcw size={16} />返回修改</Button>
                  <Button size="lg" disabled={!rubricAccepted || !rubric} loading={busy === "confirm"} onClick={confirmTask}>
                    {busy === "confirm" ? "正在生成" : "确认并生成"}{busy !== "confirm" && <Sparkles size={17} />}
                  </Button>
                </div>
              </div>
            </div>
          </Card>
          <aside className="rubric-aside">
            <Notice tone="warning" title="不能妥协的人工锚点">
              只有上方的明确点击会调用 <code>rubric:confirm</code>。刷新页面、打开页面或勾选复选框本身都不会触发确认。
            </Notice>
            <Card>
              <div className="status-card-body">
                <span className="status-icon"><Circle size={12} fill="currentColor" /></span>
                <h3>rubric_pending</h3>
                <p>生成流程尚未开始。你可以返回修改任务，或确认后等待结果。</p>
              </div>
            </Card>
          </aside>
        </div>
      )}

      {step === 3 && currentTask?.ir && currentTask.rendered && currentTask.l1 && (
        <div className="result-stack">
          {isMock && <Notice tone="warning" title="结果来源需要区分">Mock 生成 · 不代表目标模型真实输出。L1 只证明结构检查结果，不构成任务效果证据。</Notice>}
          <div className="result-summary-bar">
            <div className="result-status"><span className="success-icon"><Check size={18} /></span><div><strong>生成与 L1 检查已完成</strong><small>{currentTask.model} · {currentTask.task_id}</small></div></div>
            <div className="cluster">
              <Badge tone="info">{currentTask.evidence?.level || "L1"}</Badge>
              <Badge tone="neutral">{currentTask.evidence?.reproduction_tier || "T2"}</Badge>
              <Link className="button button-secondary button-sm" to="/editor"><Braces size={15} />打开 IR 编辑器</Link>
            </div>
          </div>
          <div className="result-mobile-tabs">
            <Tabs label="结果面板" active={resultTab} onChange={setResultTab} items={[{ id: "dialogue", label: "对话" }, { id: "ir", label: "IR 预览" }, { id: "rendered", label: "渲染文本" }]} />
          </div>
          <div className="result-grid">
            <Card className={cn("result-panel", resultTab !== "dialogue" && "mobile-hidden")}>
              <CardHeader title="对话与任务" description="本次生成的输入与确认记录" />
              <div className="result-panel-body dialogue-panel">
                <div className="message-bubble">{currentTask.draft?.text || text}</div>
                <div className="task-meta-list">
                  <div><span>目标模型</span><strong>{currentTask.model}</strong></div>
                  <div><span>Rubric</span><Badge tone="success">已人工确认</Badge></div>
                  <div><span>任务 ID</span><code>{shortHash(currentTask.task_id, 20)}</code></div>
                </div>
                <div className="mini-timeline">
                  <div className="done"><CheckCircle2 size={15} /><span>任务已创建</span></div>
                  <div className="done"><CheckCircle2 size={15} /><span>验收标准已由人确认</span></div>
                  <div className="done"><CheckCircle2 size={15} /><span>IR 与渲染结果已生成</span></div>
                </div>
              </div>
            </Card>
            <Card className={cn("result-panel", resultTab !== "ir" && "mobile-hidden")}>
              <CardHeader title="结构化提示词（IR）" description={`v${currentTask.ir.version} · ${shortHash(currentTask.ir.checksum, 12)}`} actions={<Link to="/editor" className="text-link">编辑<ArrowRight size={13} /></Link>} />
              <div className="result-panel-body ir-preview">
                <section><h3>角色</h3><p>{currentTask.ir.slots.role}</p></section>
                <section><h3>目标</h3><p>{currentTask.ir.slots.goal.outcome}</p></section>
                <section><h3>必须遵守</h3><ul className="compact-list">{currentTask.ir.slots.constraints.must.map((item) => <li key={item}>{item}</li>)}</ul></section>
                <section><h3>工作流</h3><ol className="compact-list numbered">{currentTask.ir.slots.workflow.map((item) => <li key={item}>{item}</li>)}</ol></section>
              </div>
            </Card>
            <Card className={cn("result-panel", resultTab !== "rendered" && "mobile-hidden")}>
              <CardHeader title="渲染文本" description={`${currentTask.model} · 可直接复制`} actions={<CopyButton text={currentTask.rendered.text} />} />
              <div className="result-panel-body rendered-panel"><pre>{currentTask.rendered.text}</pre></div>
            </Card>
          </div>
          <Card className="l1-card">
            <button className="l1-toggle" onClick={() => setShowEvidence((value) => !value)} aria-expanded={showEvidence}>
              <span className="l1-score"><CheckCircle2 size={20} /><span><strong>L1 结构检查{currentTask.l1.passed ? "通过" : "未通过"}</strong><small>仅检查结构，不等同于实际任务效果</small></span></span>
              <span className="cluster"><Badge tone={currentTask.l1.passed ? "success" : "danger"}>{currentTask.l1.score.toFixed(2)}</Badge>{showEvidence ? <ChevronUp size={18} /> : <ChevronDown size={18} />}</span>
            </button>
            {showEvidence && (
              <div className="evidence-body">
                <div className="evidence-grid">
                  <div><span>证据层级</span><strong>{currentTask.evidence?.level}</strong></div>
                  <div><span>复现层级</span><strong>{currentTask.evidence?.reproduction_tier}</strong></div>
                  <div><span>模型快照</span><code>{currentTask.evidence?.model_snapshot}</code></div>
                  <div><span>渲染器</span><code>{currentTask.evidence?.renderer_version}</code></div>
                  <div><span>Token 估算</span><strong>{currentTask.l1.token_estimate}</strong></div>
                  <div><span>Rubric 版本</span><code>{currentTask.evidence?.rubric_version}</code></div>
                </div>
                <div className="findings-list">
                  {currentTask.l1.findings.map((finding, index) => <div key={`${finding.code}-${index}`}><Badge tone="info">{finding.code}</Badge><p>{finding.message}</p>{finding.loc && <code>{finding.loc}</code>}</div>)}
                </div>
                <div className="evidence-footer"><Link to="/evaluation" className="button button-secondary button-sm">查看真实评测口径<ArrowRight size={14} /></Link><CopyButton label="复制证据" text={JSON.stringify(currentTask.evidence, null, 2)} /></div>
              </div>
            )}
          </Card>
        </div>
      )}

      {currentTask?.state === "cancelled" && (
        <Card><div className="empty-state"><Trash2 size={28} /><h3>任务已取消</h3><p>可以返回编辑并重新创建任务。</p><Button onClick={newTask}>返回工作台</Button></div></Card>
      )}
    </div>
  );
}
