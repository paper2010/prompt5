import { useEffect, useMemo, useState } from "react";
import {
  Check,
  CircleDot,
  Clock3,
  GitBranch,
  History,
  MessageSquareText,
  Pause,
  Play,
  RefreshCw,
  Search,
  Send,
  ShieldAlert,
} from "lucide-react";
import {
  Badge,
  Button,
  Card,
  CardHeader,
  EmptyState,
  ErrorNotice,
  Notice,
  PageHeader,
  Tabs,
} from "../components/ui";
import { API_MODE, api } from "../lib/api";
import { cn, formatDate, shortHash, turnKindLabels } from "../lib/utils";
import type { SessionReplay } from "../types";

export function SessionsPage() {
  const [sessionId, setSessionId] = useState(API_MODE === "demo" ? "s-demo-replay" : "");
  const [loadedId, setLoadedId] = useState("");
  const [replay, setReplay] = useState<SessionReplay | null>(null);
  const [filter, setFilter] = useState("all");
  const [loading, setLoading] = useState(false);
  const [recording, setRecording] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [polling, setPolling] = useState(true);
  const [draft, setDraft] = useState("");

  async function load(id = sessionId, quiet = false) {
    if (!id.trim()) {
      setError(new Error("请输入 session_id。演示模式已提供预置会话。"));
      return;
    }
    if (!quiet) setLoading(true);
    setError(null);
    try {
      const data = await api.getSessionReplay(id.trim());
      setReplay(data);
      setLoadedId(id.trim());
    } catch (loadError) {
      if (!quiet) setError(loadError);
    } finally {
      if (!quiet) setLoading(false);
    }
  }

  useEffect(() => {
    if (API_MODE === "demo") void load("s-demo-replay");
  }, []);

  useEffect(() => {
    if (!polling || !loadedId || replay?.session.state !== "open") return;
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible" && !recording) void load(loadedId, true);
    }, 5000);
    return () => window.clearInterval(timer);
  }, [polling, loadedId, replay?.session.state, recording]);

  async function recordTurn() {
    if (!loadedId || !draft.trim()) return;
    setRecording(true);
    setError(null);
    try {
      const next = await api.recordTurn(loadedId, draft.trim());
      setReplay(next);
      setDraft("");
    } catch (recordError) {
      setError(recordError);
    } finally {
      setRecording(false);
    }
  }

  const timeline = useMemo(() => {
    if (!replay) return [];
    const turns = replay.turns.map((turn) => ({
      id: `turn-${turn.seq}`,
      type: "turn",
      time: turn.created_at,
      seq: turn.seq,
      title: `第 ${turn.seq} 轮 · ${turnKindLabels[turn.kind] || turn.kind}`,
      text: turn.text,
      invalidates: turn.invalidates,
      role: turn.role,
    }));
    const events = replay.events.map((event) => ({
      id: `event-${event.event_seq}`,
      type: "event",
      time: event.created_at || "",
      seq: event.event_seq,
      title: event.event_type,
      text: event.payload ? JSON.stringify(event.payload) : "—",
      state: event.state,
      attempts: event.attempts,
    }));
    const suggestions = replay.suggestions.map((suggestion) => ({
      id: suggestion.suggestion_id,
      type: "suggestion",
      time: suggestion.created_at,
      seq: 0,
      title: suggestion.summary,
      text: suggestion.suggestion_id,
      state: suggestion.state,
      epoch: suggestion.epoch,
      checksum: suggestion.base_checksum,
    }));
    return [...turns, ...events, ...suggestions]
      .filter((item) => filter === "all" || (filter === "turn" ? item.type === "turn" : filter === "event" ? item.type === "event" : item.type === "suggestion"))
      .sort((a, b) => a.time.localeCompare(b.time) || a.seq - b.seq);
  }, [replay, filter]);

  return (
    <div className="sessions-page">
      <PageHeader eyebrow="05 · Session Replay" title="每次反馈，都有迹可循" description="在同一时间轴查看对话轮次、语义门控、事件投递、修改建议和 epoch 变化。推送不可用时以游标拉取自愈。" actions={replay && <Badge tone={replay.source === "demo" ? "warning" : "info"}>{replay.source === "demo" ? "演示回放" : "后端回放"}</Badge>} />
      <Card className="session-loader">
        <div className="session-search"><Search size={17} /><input aria-label="会话 ID" value={sessionId} onChange={(event) => setSessionId(event.target.value)} placeholder="输入 session_id，例如 s-01…" onKeyDown={(event) => { if (event.key === "Enter") void load(); }} /><Button loading={loading} onClick={() => load()}><History size={16} />加载回放</Button></div>
        {replay && <div className="session-live-row"><span><CircleDot size={13} />{replay.session.state === "open" ? "会话开放中" : "会话已关闭"} · 每 5 秒增量拉取</span><Button variant="ghost" size="sm" onClick={() => setPolling((value) => !value)}>{polling ? <Pause size={14} /> : <Play size={14} />}{polling ? "暂停刷新" : "恢复刷新"}</Button><Button variant="ghost" size="sm" loading={loading} onClick={() => load(loadedId)}><RefreshCw size={14} />立即刷新</Button></div>}
      </Card>
      {error !== null && <div className="page-notice"><ErrorNotice error={error} onRetry={loadedId ? () => load(loadedId) : undefined} /></div>}
      {!replay && !loading && <Card><EmptyState icon={<History size={24} />} title="加载一个会话开始回放">真实模式需要已有 session_id；演示模式会自动打开预置会话。</EmptyState></Card>}
      {replay && (
        <>
          <div className="session-stat-grid">
            <Card><span>当前 epoch</span><strong>{replay.session.epoch}</strong><small>建议应用成功后 +1</small></Card>
            <Card><span>对话轮次</span><strong>{replay.turns.length}</strong><small>last_turn_seq = {replay.session.last_turn_seq}</small></Card>
            <Card><span>事件</span><strong>{replay.events.length}</strong><small>最新游标 {Math.max(0, ...replay.events.map((event) => event.event_seq))}</small></Card>
            <Card><span>修改建议</span><strong>{replay.suggestions.length}</strong><small>{replay.suggestions.filter((item) => item.state === "proposed").length} 项待处理</small></Card>
          </div>
          <div className="session-layout">
            <div className="session-main">
              <Card>
                <CardHeader title="统一时间轴" description={`${replay.session.session_id} · ${replay.session.ir_id}`} actions={<Badge tone="neutral">epoch {replay.session.epoch}</Badge>} />
                <div className="session-filter"><Tabs label="时间轴筛选" active={filter} onChange={setFilter} items={[{ id: "all", label: "全部" }, { id: "turn", label: "对话轮次", count: replay.turns.length }, { id: "event", label: "系统事件", count: replay.events.length }, { id: "suggestion", label: "修改建议", count: replay.suggestions.length }]} /></div>
                <div className="timeline">
                  {timeline.map((item) => (
                    <article className={cn("timeline-item", `timeline-${item.type}`)} key={`${item.type}-${item.id}`}>
                      <div className="timeline-marker">{item.type === "turn" ? <MessageSquareText size={15} /> : item.type === "suggestion" ? <GitBranch size={15} /> : <Clock3 size={15} />}</div>
                      <div className="timeline-content">
                        <div className="timeline-heading"><div><Badge tone={item.type === "turn" ? "info" : item.type === "suggestion" ? "purple" : "neutral"}>{item.type === "turn" ? "Turn" : item.type === "suggestion" ? "Suggestion" : "Event"}</Badge><h3>{item.title}</h3></div><time>{formatDate(item.time)}</time></div>
                        <pre className={cn(item.type !== "event" && "timeline-text")}>{item.text}</pre>
                        <div className="timeline-tags">
                          {"invalidates" in item && <Badge tone={item.invalidates ? "warning" : "success"}>{item.invalidates ? "会作废在途建议" : "不作废建议"}</Badge>}
                          {"state" in item && item.state && <Badge tone={item.state === "applied" || item.state === "delivered" ? "success" : item.state === "invalidated" ? "warning" : "neutral"}>{item.state}</Badge>}
                          {"attempts" in item && <span>attempts: {item.attempts || 0}</span>}
                          {"epoch" in item && <span>epoch: {item.epoch}</span>}
                          {"checksum" in item && <code>base: {item.checksum}</code>}
                        </div>
                      </div>
                    </article>
                  ))}
                  {!timeline.length && <div className="table-empty">当前筛选下没有记录。</div>}
                </div>
              </Card>
              <Card className="record-turn-card">
                <CardHeader title="记录一轮新反馈" description="由服务端做语义分类，不在前端自行判断门控结果" />
                <div className="record-turn-body">
                  <textarea className="textarea" rows={3} value={draft} onChange={(event) => setDraft(event.target.value)} placeholder="例如：补充一条约束，不要编造缺失数据……" disabled={replay.session.state !== "open" || recording} />
                  <div className="record-turn-footer"><p>寒暄/进展不作废建议；材料/目标/约束/纠正会作废；不确定时保守作废。</p><Button disabled={!draft.trim() || replay.session.state !== "open"} loading={recording} onClick={recordTurn}><Send size={15} />记录反馈</Button></div>
                </div>
              </Card>
            </div>
            <aside className="session-aside">
              <Card><CardHeader title="会话事实" description="来自 SessionStore，而非 UI 推断" /><div className="session-facts">
                <div><span>Session</span><code>{replay.session.session_id}</code></div><div><span>IR</span><code>{replay.session.ir_id}</code></div><div><span>状态</span><Badge tone={replay.session.state === "open" ? "success" : "neutral"}>{replay.session.state}</Badge></div><div><span>空闲截止</span><strong>{formatDate(replay.session.idle_deadline)}</strong></div>
              </div></Card>
              <Card><CardHeader title="建议状态" description="只读回放，不提供伪造应用操作" /><div className="suggestion-list">{replay.suggestions.map((suggestion) => <div className="suggestion-card" key={suggestion.suggestion_id}><div><Badge tone={suggestion.state === "applied" ? "success" : suggestion.state === "invalidated" ? "warning" : "info"}>{suggestion.state}</Badge><code>{shortHash(suggestion.suggestion_id, 16)}</code></div><h3>{suggestion.summary}</h3><p>epoch {suggestion.epoch} · base {suggestion.base_checksum}</p>{suggestion.state === "invalidated" && <small><ShieldAlert size={12} />后续语义变化使其失效</small>}{suggestion.state === "applied" && <small><Check size={12} />已应用，epoch 已前进</small>}</div>)}</div></Card>
              <Notice tone="info" title="CAS 与 fencing">应用建议必须同时匹配 epoch、base_checksum、intent_hash 和 context_hash。过期建议会返回明确错误码，而不是覆盖新版本。</Notice>
              <Notice tone="warning" title="接口边界">suggestion 的产生与应用属于独立工作流；本页只回放已有记录，不假装支持尚未闭环的 HTTP 能力。</Notice>
            </aside>
          </div>
        </>
      )}
    </div>
  );
}
