import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import {
  BarChart3,
  Braces,
  FlaskConical,
  History,
  Menu,
  Settings2,
  ShieldCheck,
  Sparkles,
  X,
} from "lucide-react";
import { API_MODE } from "../lib/api";
import { Badge } from "./ui";

const navigation = [
  { to: "/", label: "任务工作台", short: "工作台", icon: Sparkles, end: true },
  { to: "/editor", label: "IR 编辑与 Diff", short: "IR 编辑", icon: Braces },
  { to: "/evaluation", label: "评测面板", short: "评测", icon: BarChart3 },
  { to: "/settings", label: "模型与端点", short: "配置", icon: Settings2 },
  { to: "/sessions", label: "会话回放", short: "会话", icon: History },
  { to: "/benchmark", label: "基准与预注册", short: "基准", icon: FlaskConical },
];

const pageTitles: Record<string, string> = {
  "/": "任务工作台",
  "/editor": "IR 编辑与 Diff",
  "/evaluation": "评测面板",
  "/settings": "模型与端点配置",
  "/sessions": "会话回放",
  "/benchmark": "基准与预注册",
};

export function AppShell() {
  const [open, setOpen] = useState(false);
  const location = useLocation();

  useEffect(() => setOpen(false), [location.pathname]);
  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") setOpen(false);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">跳到主要内容</a>
      {open && <button className="nav-scrim" aria-label="关闭导航" onClick={() => setOpen(false)} />}
      <aside className={`sidebar ${open ? "sidebar-open" : ""}`} aria-label="侧边栏">
        <div className="brand-row">
          <NavLink to="/" className="brand" aria-label="Prompt5 首页">
            <span className="brand-mark">P5</span>
            <span><strong>Prompt5</strong><small>提示词工作台</small></span>
          </NavLink>
          <button className="icon-button sidebar-close" onClick={() => setOpen(false)} aria-label="关闭导航"><X size={20} /></button>
        </div>
        <nav className="nav-list" aria-label="主导航">
          <div className="nav-section-label">工作空间</div>
          {navigation.map((item, index) => {
            const Icon = item.icon;
            return (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                className={({ isActive }) => `nav-item ${isActive ? "nav-item-active" : ""}`}
              >
                <Icon size={18} aria-hidden="true" />
                <span>{item.label}</span>
                <span className="nav-index">0{index + 1}</span>
              </NavLink>
            );
          })}
        </nav>
        <div className="sidebar-footer">
          <div className="sidebar-trust"><ShieldCheck size={16} /><span>IR 唯一事实源<br /><small>所有修改均通过 Patch</small></span></div>
          <div className="version-line">UI v0.1 · IR v3 · Patch v3</div>
        </div>
      </aside>
      <div className="app-main">
        {API_MODE === "demo" && (
          <div className="global-demo-bar"><FlaskConical size={14} />演示模式：使用固定数据快照，不访问真实模型。</div>
        )}
        <header className="topbar">
          <div className="topbar-left">
            <button className="icon-button menu-button" onClick={() => setOpen(true)} aria-label="打开导航"><Menu size={20} /></button>
            <span className="topbar-title">{pageTitles[location.pathname] || "Prompt5"}</span>
          </div>
          <div className="topbar-right">
            <span className="local-label">本地 · 单用户</span>
            <Badge tone={API_MODE === "demo" ? "warning" : "info"} dot>{API_MODE === "demo" ? "演示数据" : "Remote API"}</Badge>
          </div>
        </header>
        <main id="main-content" className="content" tabIndex={-1}>
          <Outlet />
        </main>
      </div>
    </div>
  );
}
