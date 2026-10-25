import { useEffect, useMemo, useState } from "react";
import {
  Activity,
  Check,
  CheckCircle2,
  ChevronRight,
  CircleAlert,
  KeyRound,
  Plus,
  Save,
  Server,
  ShieldCheck,
  Trash2,
} from "lucide-react";
import {
  Badge,
  Button,
  Card,
  CardHeader,
  ErrorNotice,
  Notice,
  PageHeader,
  Skeleton,
  Tabs,
} from "../components/ui";
import { API_MODE, api } from "../lib/api";
import { cn, formatDate } from "../lib/utils";
import type { ConfigCheckResult, Prompt5Config, ProbeResult, RoleBinding } from "../types";

export function SettingsPage() {
  const [config, setConfig] = useState<Prompt5Config | null>(null);
  const [tab, setTab] = useState("providers");
  const [selectedProvider, setSelectedProvider] = useState("deepseek");
  const [dirty, setDirty] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<"check" | "save" | string | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [check, setCheck] = useState<ConfigCheckResult | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [probes, setProbes] = useState<Record<string, ProbeResult>>({});

  async function loadConfig() {
    setLoading(true);
    setError(null);
    try {
      const data = await api.getConfig();
      setConfig(data);
      const first = Object.keys(data.providers)[0];
      if (first && !data.providers[selectedProvider]) setSelectedProvider(first);
      setDirty(false);
      setCheck(null);
    } catch (loadError) {
      setError(loadError);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { void loadConfig(); }, []);
  useEffect(() => {
    function warn(event: BeforeUnloadEvent) {
      if (dirty) event.preventDefault();
    }
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  function update(next: Prompt5Config) {
    setConfig(next);
    setDirty(true);
    setCheck(null);
    setSuccess(null);
  }

  function updateProvider(name: string, field: string, value: string | number | boolean) {
    if (!config) return;
    update({ ...config, providers: { ...config.providers, [name]: { ...config.providers[name], [field]: value } } });
  }

  function updateRole(role: "generator" | "reflector", field: keyof RoleBinding, value: string) {
    if (!config) return;
    update({ ...config, roles: { ...config.roles, [role]: { ...config.roles[role], [field]: value } } });
  }

  function updateJudge(index: number, field: keyof RoleBinding, value: string) {
    if (!config) return;
    update({ ...config, roles: { ...config.roles, judges: config.roles.judges.map((judge, itemIndex) => itemIndex === index ? { ...judge, [field]: value } : judge) } });
  }

  function updateTarget(name: string, field: string, value: string | boolean) {
    if (!config) return;
    if (field === "primary" && value === true) {
      update({ ...config, targets: Object.fromEntries(Object.entries(config.targets).map(([key, target]) => [key, { ...target, primary: key === name }])) });
      return;
    }
    update({ ...config, targets: { ...config.targets, [name]: { ...config.targets[name], [field]: value } } });
  }

  async function checkConfig() {
    if (!config) return;
    setBusy("check");
    setError(null);
    setSuccess(null);
    try {
      const result = await api.checkConfig(config);
      setCheck(result);
      if (result.ok) setSuccess("配置校验通过。密钥仍只保留在服务端环境变量中。");
    } catch (checkError) {
      setError(checkError);
    } finally {
      setBusy(null);
    }
  }

  async function saveConfig() {
    if (!config) return;
    setBusy("save");
    setError(null);
    setSuccess(null);
    try {
      const result = await api.saveConfig(config);
      setCheck(result);
      if (result.ok) {
        setDirty(false);
        setSuccess(API_MODE === "demo" ? "演示配置校验通过，已保存到本次页面内存；未写入磁盘。" : "配置校验通过并已保存到服务端 config.yaml。");
      }
    } catch (saveError) {
      setError(saveError);
    } finally {
      setBusy(null);
    }
  }

  async function probe(target: string) {
    setBusy(`probe:${target}`);
    setError(null);
    try {
      const result = await api.probeTarget(target);
      setProbes((existing) => ({ ...existing, [target]: result }));
    } catch (probeError) {
      setError(probeError);
    } finally {
      setBusy(null);
    }
  }

  const errorCount = useMemo(() => check?.issues.filter((issue) => issue.level === "error").length || 0, [check]);
  const selected = config?.providers[selectedProvider];

  return (
    <div className="settings-page">
      <PageHeader
        eyebrow="04 · Providers & Targets"
        title="模型配置，集中一处完成"
        description="分别管理供应商、生成/裁判角色和执行目标。配置不合法会阻止保存；密钥永不回显。"
        actions={<><Button variant="secondary" loading={busy === "check"} disabled={!config || busy === "save"} onClick={checkConfig}><ShieldCheck size={16} />校验配置</Button><Button loading={busy === "save"} disabled={!config || !dirty || busy === "check"} onClick={saveConfig}><Save size={16} />保存配置</Button></>}
      />
      <Notice tone={API_MODE === "demo" ? "warning" : "info"} title={API_MODE === "demo" ? "演示配置" : "服务端配置"}>
        {API_MODE === "demo" ? "当前保存只影响本次页面内存，不写入 config.yaml，也不会发送真实模型请求。" : "页面只提交非密钥配置；api_key_env 只是环境变量名，真实密钥由后端进程读取。"}
      </Notice>
      {error !== null && <div className="page-notice"><ErrorNotice error={error} onRetry={!config ? loadConfig : undefined} /></div>}
      {success && <div className="page-notice"><Notice tone="success" title="操作完成">{success}</Notice></div>}
      {check && (
        <Card className={cn("config-check-card", errorCount ? "config-check-error" : "config-check-ok")}>
          <div className="config-check-summary">
            {errorCount ? <CircleAlert size={20} /> : <CheckCircle2 size={20} />}
            <div><strong>{errorCount ? `${errorCount} 个错误阻止保存` : "配置检查通过"}</strong><p>{check.issues.length ? "请按字段逐项处理；警告不会替代人工判断。" : "端点、密钥引用、角色和目标均通过当前校验。"}</p></div>
            <Badge tone={check.source === "demo" ? "warning" : "neutral"}>{check.source === "demo" ? "演示校验" : "config check"}</Badge>
          </div>
          {check.issues.length > 0 && <div className="config-issues">{check.issues.map((issue, index) => <button key={`${issue.code}-${issue.field}-${index}`} onClick={() => setTab(issue.field.startsWith("roles") ? "roles" : issue.field.startsWith("targets") ? "targets" : "providers")}><Badge tone={issue.level === "error" ? "danger" : "warning"}>{issue.level}</Badge><span><code>{issue.code}</code><small>{issue.field}</small></span><p>{issue.message}</p><ChevronRight size={15} /></button>)}</div>}
        </Card>
      )}
      {loading && <Card><Skeleton lines={6} /></Card>}
      {!loading && config && (
        <>
          <div className="settings-tabs-row"><Tabs label="配置类别" active={tab} onChange={setTab} items={[{ id: "providers", label: "供应商", count: Object.keys(config.providers).length }, { id: "roles", label: "角色与裁判", count: config.roles.judges.length + 2 }, { id: "targets", label: "执行目标", count: Object.keys(config.targets).length }]} />{dirty && <Badge tone="warning" dot>有未保存修改</Badge>}</div>
          {tab === "providers" && (
            <div className="settings-master-detail">
              <Card className="settings-list-card"><div className="settings-list">{Object.entries(config.providers).map(([name, provider]) => <button key={name} className={cn("settings-list-item", selectedProvider === name && "settings-list-item-active")} onClick={() => setSelectedProvider(name)}><span className="provider-icon"><Server size={16} /></span><span><strong>{provider.display || name}</strong><small>{name}</small></span><Badge tone={provider.key_configured || provider.api_key_required === false ? "success" : "neutral"}>{provider.api_key_required === false ? "免密钥" : provider.key_configured ? "密钥已配置" : "密钥未配置"}</Badge><ChevronRight size={15} /></button>)}</div></Card>
              {selected && <Card><CardHeader title={selected.display || selectedProvider} description={`providers.${selectedProvider}`} actions={<Badge tone="info">{selected.api_style || "openai"}</Badge>} /><div className="settings-form-body">
                <div className="field-row"><div className="field"><label htmlFor="provider-display">显示名称</label><input id="provider-display" className="input" value={selected.display} onChange={(event) => updateProvider(selectedProvider, "display", event.target.value)} /></div><div className="field"><label htmlFor="provider-timeout">超时（秒）</label><input id="provider-timeout" className="input" type="number" min={1} max={600} value={selected.timeout || 120} onChange={(event) => updateProvider(selectedProvider, "timeout", Number(event.target.value))} /></div></div>
                <div className="field"><label htmlFor="provider-url">OpenAI 兼容服务端点</label><input id="provider-url" className="input mono" value={selected.base_url} onChange={(event) => updateProvider(selectedProvider, "base_url", event.target.value)} placeholder="https://api.example.com/v1" /><span className="field-hint">服务端会请求其 /chat/completions 路径；不要填写前端代理地址。</span></div>
                <div className="field"><label htmlFor="provider-key-env">密钥环境变量名</label><div className="key-input-row"><KeyRound size={17} /><input id="provider-key-env" className="input mono" value={selected.api_key_env} onChange={(event) => updateProvider(selectedProvider, "api_key_env", event.target.value)} /><Badge tone={selected.key_configured ? "success" : "warning"}>{selected.key_configured ? "已配置" : "未配置"}</Badge></div><span className="field-hint">这里只保存变量名，例如 DSK_KEY；不能在此输入或读取真实密钥。</span></div>
                <label className="checkbox-row"><input type="checkbox" checked={selected.api_key_required === false} onChange={(event) => updateProvider(selectedProvider, "api_key_required", !event.target.checked)} /><span>这是无需密钥的本地端点</span></label>
                <Notice tone="info" title="如何设置密钥">在启动 FastAPI 的服务端终端设置 <code>{selected.api_key_env || "API_KEY"}</code> 环境变量并重启。不要把密钥粘贴到此页面或提交到仓库。</Notice>
              </div></Card>}
            </div>
          )}
          {tab === "roles" && (
            <div className="roles-layout">
              <div className="role-primary-grid">{(["generator", "reflector"] as const).map((role) => <Card key={role}><CardHeader title={role === "generator" ? "Generator · 生成器" : "Reflector · 反思器"} description={role === "generator" ? "负责生成提示词的主角色" : "低频离线反思与改进"} /><div className="settings-form-body"><RoleFields binding={config.roles[role]} providers={Object.keys(config.providers)} idPrefix={role} onChange={(field, value) => updateRole(role, field, value)} /></div></Card>)}</div>
              <Card><CardHeader title="L2 裁判池" description="至少 2 个；系统按不同于被测族且不同于生成器族的规则选择" actions={<Button size="sm" variant="secondary" onClick={() => update({ ...config, roles: { ...config.roles, judges: [...config.roles.judges, { provider: Object.keys(config.providers)[0], model: "" }] } })}><Plus size={14} />添加裁判</Button>} /><div className="judge-list">{config.roles.judges.map((judge, index) => <div className="judge-row" key={index}><span className="judge-index">J{index + 1}</span><RoleFields binding={judge} providers={Object.keys(config.providers)} idPrefix={`judge-${index}`} onChange={(field, value) => updateJudge(index, field, value)} /><button className="icon-button danger-icon" aria-label={`移除裁判 ${index + 1}`} onClick={() => update({ ...config, roles: { ...config.roles, judges: config.roles.judges.filter((_, itemIndex) => itemIndex !== index) } })}><Trash2 size={16} /></button></div>)}</div></Card>
            </div>
          )}
          {tab === "targets" && (
            <div className="target-grid">{Object.entries(config.targets).map(([name, target]) => {
              const probeResult = probes[name];
              return <Card key={name} className={cn(target.primary && "target-primary")}><CardHeader title={name} description={`${target.tier} · ${target.label}`} actions={target.primary ? <Badge tone="info">Primary</Badge> : <Badge tone="neutral">Target</Badge>} /><div className="settings-form-body">
                <RoleFields binding={target} providers={Object.keys(config.providers)} idPrefix={`target-${name}`} onChange={(field, value) => updateTarget(name, field, value)} />
                <div className="field-row"><div className="field"><label htmlFor={`tier-${name}`}>复现层级</label><select id={`tier-${name}`} className="select" value={target.tier} onChange={(event) => updateTarget(name, "tier", event.target.value)}><option value="T1">T1</option><option value="T2">T2</option><option value="T3">T3</option></select></div><div className="field"><label htmlFor={`label-${name}`}>门禁标签</label><select id={`label-${name}`} className="select" value={target.label} onChange={(event) => updateTarget(name, "label", event.target.value)}><option value="compatible">compatible</option><option value="optimizing">optimizing</option><option value="rejected">rejected</option></select></div></div>
                <label className="checkbox-row"><input type="radio" name="primary-target" checked={Boolean(target.primary)} onChange={() => updateTarget(name, "primary", true)} /><span>设为默认目标模型</span></label>
                <div className="probe-row"><Button variant="secondary" size="sm" loading={busy === `probe:${name}`} disabled={dirty} title={dirty ? "请先保存配置，再探测服务端生效端点" : "发送最小真实请求"} onClick={() => probe(name)}><Activity size={14} />探针</Button><span>{dirty ? "先保存修改，再运行探针" : "读取服务端已保存配置"}</span></div>
                {probeResult && <div className={cn("probe-result", probeResult.ok ? "probe-ok" : "probe-failed")}><span>{probeResult.ok ? <Check size={15} /> : <CircleAlert size={15} />}</span><div><strong>{probeResult.ok ? "探针可用" : "探针未通过"}</strong><p>{probeResult.detail}</p><small>{probeResult.source === "demo" ? "演示探针 · 未发请求" : `${probeResult.latency_ms ?? "—"} ms`} · {formatDate(probeResult.checked_at)}</small></div></div>}
              </div></Card>;
            })}</div>
          )}
        </>
      )}
    </div>
  );
}

function RoleFields({ binding, providers, idPrefix, onChange }: { binding: RoleBinding; providers: string[]; idPrefix: string; onChange: (field: keyof RoleBinding, value: string) => void }) {
  return <div className="role-fields"><div className="field"><label htmlFor={`${idPrefix}-provider`}>供应商</label><select id={`${idPrefix}-provider`} className="select" value={binding.provider} onChange={(event) => onChange("provider", event.target.value)}>{providers.map((provider) => <option key={provider} value={provider}>{provider}</option>)}</select></div><div className="field"><label htmlFor={`${idPrefix}-model`}>模型 ID</label><input id={`${idPrefix}-model`} className="input mono" value={binding.model} onChange={(event) => onChange("model", event.target.value)} placeholder="provider-model-id" /></div></div>;
}
