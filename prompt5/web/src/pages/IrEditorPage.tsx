import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  ArrowDown,
  ArrowLeft,
  ArrowUp,
  Braces,
  CheckCircle2,
  ChevronRight,
  FileJson2,
  LockKeyhole,
  Plus,
  RotateCcw,
  Send,
  ShieldAlert,
  Trash2,
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
  Tabs,
} from "../components/ui";
import { API_MODE, api } from "../lib/api";
import { cn, isProtected, pathLabel, shortHash } from "../lib/utils";
import type { PatchOperation, ProtectEntry } from "../types";

type Schema = Record<string, any>;
type DraftOperation = PatchOperation;

const groups = [
  { title: "角色与目标", description: "定义助手身份与要完成的任务", fields: ["slots.role", "slots.goal.outcome"] },
  { title: "完成标准与非目标", description: "告诉模型怎样算完成，以及不要做什么", fields: ["slots.goal.done_criteria", "slots.goal.non_goals"] },
  { title: "输出要求", description: "输出格式与篇幅；schema 保持只读", fields: ["slots.output.format", "slots.output.length_budget", "slots.output.schema"] },
  { title: "约束", description: "必须遵守、禁止事项与表达风格", fields: ["slots.constraints.must", "slots.constraints.must_not", "slots.constraints.style"] },
  { title: "工作流", description: "使用稳定 ID 调整步骤，不依赖数组下标", fields: ["slots.workflow"] },
  { title: "材料与示例", description: "对象列表当前只读，避免构造不兼容 Patch", fields: ["slots.inputs", "slots.examples"] },
];

function resolveSchema(root: Schema, node: Schema): Schema {
  if (!node?.$ref) return node;
  const path = String(node.$ref).replace(/^#\//, "").split("/");
  return path.reduce((current, key) => current?.[key], root);
}

function schemaAt(root: Schema, loc: string): Schema {
  const parts = loc.split(".");
  let node = root;
  for (const part of parts) {
    node = resolveSchema(root, node);
    node = node?.properties?.[part];
  }
  return resolveSchema(root, node || {});
}

function valueAt(ir: any, loc: string): any {
  const match = loc.match(/^(.*)\[([^\]]+)\]$/);
  if (match) {
    const list = valueAt(ir, match[1]);
    const ids = ir.item_ids?.[match[1]] || [];
    const index = ids.indexOf(match[2]);
    return index >= 0 ? list?.[index] : undefined;
  }
  return loc.split(".").reduce((value, part) => value?.[part], ir);
}

function EditableText({
  value,
  label,
  loc,
  protectedField,
  multiline = true,
  onCommit,
}: {
  value: string;
  label: string;
  loc: string;
  protectedField: boolean;
  multiline?: boolean;
  onCommit: (loc: string, value: string) => void;
}) {
  const [draft, setDraft] = useState(value);
  useEffect(() => setDraft(value), [value]);
  const shared = {
    id: `field-${loc}`,
    value: draft,
    disabled: protectedField,
    onChange: (event: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => setDraft(event.target.value),
    onBlur: () => { if (draft !== value) onCommit(loc, draft); },
    "aria-label": label,
  };
  return (
    <div className="editor-field">
      <div className="editor-field-label">
        <label htmlFor={`field-${loc}`}>{label}</label>
        {protectedField ? <Badge tone="warning"><LockKeyhole size={11} />已保护</Badge> : <code>{loc}</code>}
      </div>
      {multiline ? <textarea className="textarea editor-textarea" rows={3} {...shared} /> : <input className="input" {...shared} />}
    </div>
  );
}

function InstructionList({
  loc,
  values,
  ir,
  onOperation,
  onProtection,
}: {
  loc: string;
  values: string[];
  ir: NonNullable<ReturnType<typeof useApp>["currentIR"]>;
  onOperation: (operation: DraftOperation) => void;
  onProtection: (loc: string) => void;
}) {
  const [adding, setAdding] = useState(false);
  const [newValue, setNewValue] = useState("");
  const ids = ir.item_ids[loc] || [];
  const aligned = ids.length === values.length;

  function add() {
    if (!newValue.trim()) return;
    onOperation({ op: "ADD", loc, content: newValue.trim(), reason: "", evidence_refs: [] });
    setNewValue("");
    setAdding(false);
  }

  return (
    <div className="instruction-editor">
      <div className="editor-field-label"><span>{pathLabel(loc)}</span><Badge tone="neutral">{values.length} 项</Badge></div>
      {!aligned && <Notice tone="danger" title="E_ITEM_ID_MISALIGNED">列表与 item_ids 未对齐，已阻止编辑。</Notice>}
      <ul className="instruction-list">
        {values.map((value, index) => {
          const id = ids[index];
          const itemLoc = `${loc}[${id}]`;
          const locked = isProtected(ir, itemLoc);
          const provenance = ir.provenance_map[id];
          return (
            <li key={id || index} className={cn(locked && "instruction-protected")}>
              <div className="instruction-meta">
                <code title={id}>{id || "missing-id"}</code>
                {typeof provenance?.source === "string" && <Badge tone="purple">{provenance.source}</Badge>}
                {locked && <Badge tone="warning"><LockKeyhole size={11} />{ir.protect_registry.find((entry) => entry.loc === itemLoc)?.cls || "protected"}</Badge>}
                <span className="instruction-tools">
                  <button className="icon-button" disabled={!aligned || locked || index === 0} title="上移" aria-label={`上移 ${id}`} onClick={() => onOperation({ op: "MOVE", loc: itemLoc, to: { before: ids[index - 1] }, reason: "", evidence_refs: [] })}><ArrowUp size={14} /></button>
                  <button className="icon-button" disabled={!aligned || locked || index === values.length - 1} title="下移" aria-label={`下移 ${id}`} onClick={() => onOperation({ op: "MOVE", loc: itemLoc, to: { after: ids[index + 1] }, reason: "", evidence_refs: [] })}><ArrowDown size={14} /></button>
                  <button className="icon-button danger-icon" disabled={!aligned || locked} title={locked ? "已保护，不能直接删除" : "暂存删除"} aria-label={`删除 ${id}`} onClick={() => onOperation({ op: "DELETE", loc: itemLoc, reason: "", evidence_refs: [] })}><Trash2 size={14} /></button>
                </span>
              </div>
              <EditableText value={value} label={`${pathLabel(loc)} ${index + 1}`} loc={itemLoc} protectedField={!aligned || locked} onCommit={(target, content) => onOperation({ op: "REWRITE", loc: target, content, reason: "", evidence_refs: [] })} />
              {locked && <button className="protection-link" onClick={() => onProtection(itemLoc)}><ShieldAlert size={13} />申请保护变更<ChevronRight size={13} /></button>}
            </li>
          );
        })}
      </ul>
      {adding ? (
        <div className="add-instruction">
          <textarea className="textarea" rows={2} value={newValue} onChange={(event) => setNewValue(event.target.value)} placeholder={`添加一条${pathLabel(loc)}`} autoFocus />
          <div className="cluster"><Button size="sm" onClick={add} disabled={!newValue.trim()}>暂存新增</Button><Button size="sm" variant="ghost" onClick={() => setAdding(false)}>取消</Button></div>
        </div>
      ) : (
        <Button variant="ghost" size="sm" onClick={() => setAdding(true)} disabled={!aligned || isProtected(ir, loc)}><Plus size={14} />添加{pathLabel(loc)}</Button>
      )}
    </div>
  );
}

export function IrEditorPage() {
  const { currentIR, setCurrentIR, currentModel } = useApp();
  const [schema, setSchema] = useState<Schema | null>(null);
  const [schemaError, setSchemaError] = useState<unknown>(null);
  const [ops, setOps] = useState<DraftOperation[]>([]);
  const [reason, setReason] = useState("通过可视化编辑器调整提示词");
  const [evidenceRefs, setEvidenceRefs] = useState("");
  const [diffView, setDiffView] = useState("readable");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [protectionLoc, setProtectionLoc] = useState<string | null>(null);
  const [protectionClass, setProtectionClass] = useState<ProtectEntry["cls"]>("user_pinned");
  const reasonRef = useRef(reason);
  const deleteNeedsEvidence = ops.some((op) => op.op === "DELETE") && !evidenceRefs.trim();

  useEffect(() => {
    api.getIRSchema().then(setSchema).catch(setSchemaError);
  }, []);

  useEffect(() => {
    setOps([]);
  }, [currentIR?.checksum]);

  function addOperation(operation: DraftOperation) {
    if (!currentIR || isProtected(currentIR, operation.loc)) return;
    const complete = { ...operation, reason: reasonRef.current, evidence_refs: evidenceRefs.split(",").map((item) => item.trim()).filter(Boolean) };
    setOps((existing) => {
      const duplicateIndex = existing.findIndex((item) => item.loc === complete.loc && item.op === complete.op);
      if (duplicateIndex < 0) return [...existing, complete];
      return existing.map((item, index) => index === duplicateIndex ? complete : item);
    });
    setSuccess(null);
  }

  function updateReason(value: string) {
    setReason(value);
    reasonRef.current = value;
    setOps((existing) => existing.map((op) => ({ ...op, reason: value })));
  }

  function updateEvidenceRefs(value: string) {
    setEvidenceRefs(value);
    const refs = value.split(",").map((item) => item.trim()).filter(Boolean);
    setOps((existing) => existing.map((op) => ({ ...op, evidence_refs: refs })));
  }

  async function applyOperations() {
    if (!currentIR || !ops.length || !reason.trim() || deleteNeedsEvidence) return;
    setBusy(true);
    setError(null);
    setSuccess(null);
    try {
      const result = await api.applyPatch(currentIR, ops, currentModel, reason.trim());
      setCurrentIR(result.ir);
      setSuccess(result.persisted ? "Patch 已应用并写入版本台账。" : "Patch 已由服务端应用并返回新 IR；本次未写入版本台账。");
    } catch (applyError) {
      setError(applyError);
    } finally {
      setBusy(false);
    }
  }

  async function submitProtection() {
    if (!protectionLoc) return;
    setBusy(true);
    setError(null);
    try {
      const result = await api.requestProtection(protectionLoc, protectionClass);
      setSuccess(`保护变更 ${result.loc} 已提交为 ${result.state}；尚未批准，也未直接生效。`);
      setProtectionLoc(null);
    } catch (requestError) {
      setError(requestError);
    } finally {
      setBusy(false);
    }
  }

  const patchDraft = useMemo(() => currentIR ? {
    schema_version: "3",
    base: { ir_id: currentIR.ir_id, version: currentIR.version, checksum: currentIR.checksum },
    intent: ops.every((op) => op.op === "DELETE" || op.op === "MOVE") ? "simplify" : "improve",
    ops,
  } : null, [currentIR, ops]);

  if (!currentIR) {
    return (
      <div>
        <PageHeader eyebrow="02 · IR + Patch" title="看清每一次修改" description="IR 是唯一事实源，渲染文本只是结果。" />
        <Card><EmptyState icon={<Braces size={24} />} title="还没有可编辑的 IR" action={<Link to="/" className="button button-primary button-md"><ArrowLeft size={16} />返回任务工作台</Link>}>先完成一次“创建任务 → 人工确认 Rubric → 生成”，结果会自动带入编辑器。</EmptyState></Card>
      </div>
    );
  }

  return (
    <div className="editor-page">
      <PageHeader
        eyebrow="02 · IR + Patch"
        title="看清每一次修改"
        description="左侧按 Schema 编辑，右侧先审阅 Patch Diff。checksum 只由服务端更新，保护字段不能直接修改。"
        actions={<><Badge tone="info">IR v{currentIR.version}</Badge><Badge tone="neutral">{currentModel}</Badge></>}
      />
      {API_MODE === "demo" && <div className="page-notice"><Notice tone="info" title="演示编辑">可以暂存修改并查看 Diff；应用 Patch 需要真实后端，演示模式不会伪造新 checksum。</Notice></div>}
      {schemaError !== null && <div className="page-notice"><ErrorNotice error={schemaError} /></div>}
      {error !== null && <div className="page-notice"><ErrorNotice error={error} /></div>}
      {success && <div className="page-notice"><Notice tone="success" title="操作完成">{success}</Notice></div>}
      <div className="ir-metadata">
        <div><span>IR ID</span><code>{currentIR.ir_id}</code></div>
        <div><span>Lineage</span><code>{currentIR.lineage_id}</code></div>
        <div><span>Checksum</span><code title={currentIR.checksum}>{shortHash(currentIR.checksum, 18)}</code></div>
        <div><span>Schema</span><strong>{schema ? `${schema.title || "IR"} · v${currentIR.schema_version}` : "正在读取…"}</strong></div>
      </div>
      <div className="editor-layout">
        <div className="editor-sections">
          {groups.map((group) => (
            <Card key={group.title}>
              <CardHeader title={group.title} description={group.description} />
              <div className="editor-group-body">
                {group.fields.map((loc) => {
                  const value = valueAt(currentIR, loc);
                  const fieldSchema = schema ? schemaAt(schema, loc) : {};
                  const locked = isProtected(currentIR, loc);
                  if (schema && Array.isArray(value) && fieldSchema?.items?.type === "string") {
                    return <InstructionList key={loc} loc={loc} values={value} ir={currentIR} onOperation={addOperation} onProtection={setProtectionLoc} />;
                  }
                  if (typeof value === "string") {
                    return <EditableText key={`${loc}-${currentIR.checksum}`} value={value} label={pathLabel(loc)} loc={loc} protectedField={locked || !schema} multiline={loc !== "slots.output.format" && loc !== "slots.output.length_budget"} onCommit={(target, content) => addOperation({ op: "REWRITE", loc: target, content, reason: "", evidence_refs: [] })} />;
                  }
                  return (
                    <div className="readonly-schema-field" key={loc}>
                      <div className="editor-field-label"><span>{pathLabel(loc)}</span><Badge tone="neutral"><LockKeyhole size={11} />只读</Badge></div>
                      <pre>{JSON.stringify(value, null, 2)}</pre>
                    </div>
                  );
                })}
              </div>
            </Card>
          ))}
        </div>
        <aside className="diff-column">
          <Card className="diff-card">
            <CardHeader title="Patch Diff" description={`${ops.length} 项暂存变更`} actions={<Badge tone={ops.length ? "info" : "neutral"}>{ops.length ? "待提交" : "无变更"}</Badge>} />
            <div className="diff-controls">
              <Tabs label="Diff 展示方式" active={diffView} onChange={setDiffView} items={[{ id: "readable", label: "可读 Diff" }, { id: "json", label: "Patch JSON" }]} />
            </div>
            <div className="diff-body">
              {!ops.length ? (
                <div className="diff-empty"><FileJson2 size={26} /><h3>修改会在这里汇总</h3><p>新增、删除、改写和移动都会先形成 Patch 草案，不会立即写入 IR。</p></div>
              ) : diffView === "json" ? (
                <div className="patch-json"><CopyButton text={JSON.stringify(patchDraft, null, 2)} label="复制草案" /><pre>{JSON.stringify(patchDraft, null, 2)}</pre></div>
              ) : (
                <div className="diff-list">
                  {ops.map((op, index) => {
                    const before = valueAt(currentIR, op.loc);
                    return (
                      <article className={`diff-item diff-${op.op.toLowerCase()}`} key={`${op.op}-${op.loc}-${index}`}>
                        <div className="diff-item-heading"><Badge tone={op.op === "ADD" ? "success" : op.op === "DELETE" ? "danger" : "info"}>{op.op}</Badge><strong>{pathLabel(op.loc)}</strong></div>
                        <code className="diff-loc">{op.loc}</code>
                        {op.op !== "ADD" && before !== undefined && <del>{typeof before === "string" ? before : JSON.stringify(before)}</del>}
                        {(op.op === "ADD" || op.op === "REWRITE") && <ins>{typeof op.content === "string" ? op.content : JSON.stringify(op.content)}</ins>}
                        {op.op === "MOVE" && <p className="move-target">{JSON.stringify(op.to)}</p>}
                        <div className="diff-reason"><span>原因</span>{op.reason || "未填写"}{op.evidence_refs.length > 0 && <small>证据：{op.evidence_refs.join(", ")}</small>}</div>
                      </article>
                    );
                  })}
                </div>
              )}
              <div className="patch-settings">
                <div className="field"><label htmlFor="patch-reason">修改原因 <span className="required">必填</span></label><input id="patch-reason" className="input" value={reason} onChange={(event) => updateReason(event.target.value)} /></div>
                <div className="field"><label htmlFor="patch-evidence">证据引用 <span className="optional">可选，逗号分隔</span></label><input id="patch-evidence" className="input" value={evidenceRefs} onChange={(event) => updateEvidenceRefs(event.target.value)} placeholder="evidence-id-1, user-feedback-3" /></div>
              </div>
              <div className="diff-actions">
                <Button variant="ghost" size="sm" disabled={!ops.length || busy} onClick={() => setOps([])}><RotateCcw size={14} />清空</Button>
                <Button disabled={!ops.length || !reason.trim() || deleteNeedsEvidence || API_MODE === "demo"} loading={busy} title={API_MODE === "demo" ? "演示模式不执行 IR 写操作" : deleteNeedsEvidence ? "DELETE 必须先填写证据引用" : "由服务端校验并应用 Patch"} onClick={applyOperations}><CheckCircle2 size={16} />应用 Patch</Button>
              </div>
              {deleteNeedsEvidence ? <p className="form-error">DELETE 操作必须填写证据引用，符合 Patch v3 后才能提交。</p> : <p className="diff-footnote">提交后由服务端校验 base checksum、保护项与 Patch 契约；前端不计算新 checksum。</p>}
            </div>
          </Card>
          {protectionLoc && (
            <Card className="protection-card">
              <CardHeader title="申请保护变更" description="只提交 proposed，不在前端批准" />
              <div className="protection-form">
                <code>{protectionLoc}</code>
                <div className="field"><label htmlFor="protection-class">保护类别</label><select id="protection-class" className="select" value={protectionClass} onChange={(event) => setProtectionClass(event.target.value as ProtectEntry["cls"])}><option value="user_pinned">user_pinned</option><option value="safety">safety</option><option value="hard_format">hard_format</option></select></div>
                <div className="cluster"><Button variant="ghost" size="sm" onClick={() => setProtectionLoc(null)}>取消</Button><Button size="sm" loading={busy} onClick={submitProtection}><Send size={14} />提交申请</Button></div>
              </div>
            </Card>
          )}
        </aside>
      </div>
    </div>
  );
}
