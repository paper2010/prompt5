import type { ButtonHTMLAttributes, HTMLAttributes, ReactNode } from "react";
import { useState } from "react";
import {
  AlertCircle,
  AlertTriangle,
  Check,
  CheckCircle2,
  Clipboard,
  Info,
  LoaderCircle,
} from "lucide-react";
import { ApiError } from "../lib/api";
import { cn } from "../lib/utils";

export function Button({
  className,
  variant = "primary",
  size = "md",
  loading = false,
  children,
  disabled,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "ghost" | "danger";
  size?: "sm" | "md" | "lg";
  loading?: boolean;
}) {
  return (
    <button
      className={cn("button", `button-${variant}`, `button-${size}`, className)}
      disabled={disabled || loading}
      {...props}
    >
      {loading && <LoaderCircle className="spin" size={16} aria-hidden="true" />}
      {children}
    </button>
  );
}

export function Badge({
  children,
  tone = "neutral",
  dot = false,
  className,
}: {
  children: ReactNode;
  tone?: "neutral" | "info" | "success" | "warning" | "danger" | "purple";
  dot?: boolean;
  className?: string;
}) {
  return (
    <span className={cn("badge", `badge-${tone}`, className)}>
      {dot && <span className="badge-dot" aria-hidden="true" />}
      {children}
    </span>
  );
}

export function PageHeader({
  eyebrow,
  title,
  description,
  actions,
}: {
  eyebrow?: string;
  title: string;
  description: string;
  actions?: ReactNode;
}) {
  return (
    <header className="page-header">
      <div className="page-heading">
        {eyebrow && <div className="eyebrow">{eyebrow}</div>}
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
      {actions && <div className="page-actions">{actions}</div>}
    </header>
  );
}

export function Notice({
  tone = "info",
  title,
  children,
  className,
}: {
  tone?: "info" | "warning" | "danger" | "success";
  title?: string;
  children: ReactNode;
  className?: string;
}) {
  const Icon = tone === "danger" ? AlertCircle : tone === "warning" ? AlertTriangle : tone === "success" ? CheckCircle2 : Info;
  return (
    <div className={cn("notice", `notice-${tone}`, className)} role={tone === "danger" ? "alert" : "note"}>
      <Icon size={18} aria-hidden="true" />
      <div className="notice-content">
        {title && <strong>{title}</strong>}
        <div>{children}</div>
      </div>
    </div>
  );
}

export function ErrorNotice({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const code = error instanceof ApiError ? error.code : "E_UI_UNEXPECTED";
  const detail = error instanceof Error ? error.message : String(error);
  return (
    <Notice tone="danger" title="操作未完成">
      <p>{detail}</p>
      <div className="error-footer">
        <code>{code}</code>
        {onRetry && <Button size="sm" variant="secondary" onClick={onRetry}>重试</Button>}
      </div>
    </Notice>
  );
}

export function CopyButton({ text, label = "复制" }: { text: string; label?: string }) {
  const [copied, setCopied] = useState(false);
  async function copy() {
    await navigator.clipboard.writeText(text);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1600);
  }
  return (
    <Button variant="ghost" size="sm" onClick={copy} aria-label={`${label}到剪贴板`}>
      {copied ? <Check size={15} /> : <Clipboard size={15} />}
      {copied ? "已复制" : label}
    </Button>
  );
}

export function EmptyState({ icon, title, children, action }: { icon?: ReactNode; title: string; children: ReactNode; action?: ReactNode }) {
  return (
    <div className="empty-state">
      {icon && <div className="empty-icon">{icon}</div>}
      <h3>{title}</h3>
      <p>{children}</p>
      {action}
    </div>
  );
}

export function Card({ className, children, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("card", className)} {...props}>{children}</div>;
}

export function CardHeader({ title, description, actions }: { title: string; description?: string; actions?: ReactNode }) {
  return (
    <div className="card-header">
      <div>
        <h2>{title}</h2>
        {description && <p>{description}</p>}
      </div>
      {actions && <div className="card-actions">{actions}</div>}
    </div>
  );
}

export function Steps({ current }: { current: number }) {
  const steps = ["描述需求", "确认标准", "查看结果"];
  return (
    <ol className="steps" aria-label="任务进度">
      {steps.map((step, index) => {
        const number = index + 1;
        const state = number < current ? "done" : number === current ? "current" : "upcoming";
        return (
          <li key={step} className={`step-${state}`} aria-current={state === "current" ? "step" : undefined}>
            <span className="step-number">{state === "done" ? <Check size={14} /> : number}</span>
            <span>{step}</span>
          </li>
        );
      })}
    </ol>
  );
}

export function Tabs({
  items,
  active,
  onChange,
  label,
}: {
  items: Array<{ id: string; label: string; count?: number }>;
  active: string;
  onChange: (id: string) => void;
  label: string;
}) {
  return (
    <div className="tabs" role="tablist" aria-label={label}>
      {items.map((item) => (
        <button
          key={item.id}
          type="button"
          role="tab"
          aria-selected={active === item.id}
          className={cn("tab", active === item.id && "tab-active")}
          onClick={() => onChange(item.id)}
        >
          {item.label}
          {item.count !== undefined && <span className="tab-count">{item.count}</span>}
        </button>
      ))}
    </div>
  );
}

export function Skeleton({ lines = 3 }: { lines?: number }) {
  return (
    <div className="skeleton-stack" aria-label="正在加载" aria-busy="true">
      {Array.from({ length: lines }, (_, index) => <span className="skeleton" key={index} style={{ width: `${92 - index * 9}%` }} />)}
    </div>
  );
}
