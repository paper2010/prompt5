# Prompt5 — 自适应提示词生成与评测工作台

> **测试状态声明：当前仅为内部测试项目，不能用于生产环境。**
> 功能、接口、数据结构、评测结论和安装包均可能随时变化；请勿用于真实业务、生产数据或对外正式交付。演示模式与 Mock 生成结果不代表真实模型效果。

Prompt5 把提示词工程从“反复改文本”变成可审计的工程流程：自然语言需求 → 结构化 IR → 人工确认验收标准 → 生成/渲染 → 分层评测 → 统计报告。

当前仓库包含完整的 Python 后端、React 六页 Web 工作台和 Windows 桌面客户端。演示模式可完全离线运行；真实模型评测需要配置模型端点与 API Key。

| 项目信息 | 值 |
|---|---|
| 技术栈 | Python 3.11+ · FastAPI · React 19 · TypeScript · Vite · SQLite |
| 桌面端 | Electron 32 · PyInstaller · electron-builder（Windows） |
| 当前阶段 | M0–M6 完成 · M7 骨架完成 · UI0 完成 · Windows Desktop 0.1 完成 |
| 测试 | 后端 407 passed / 30 subtests · 前端 5 passed · 浏览器 smoke 通过 |
| 许可 | MIT |

---

## 项目简介

Prompt5 面向提示词设计、模型输出对比和回归评测。它重点解决三个问题：

1. **标准先于生成**：先返回版本化 Rubric，由人确认后才调用生成流程。
2. **结果可审计**：IR v3、稳定 item ID、Patch checksum、版本台账和审计哈希链。
3. **效果有证据**：L1 规则、L2 裁判、L3 执行评测，结合 CI、McNemar、bootstrap 和预注册门禁。

核心使用场景：

- 提示词模板设计与迭代
- 多模型输出质量对比
- 提示词 A/B 测试和回归评测
- 团队内部提示词资产管理与审计

---

## 主要功能

### 六页 Web 工作台

| 页面 | 路径 | 主要用途 |
|---|---|---|
| 任务工作台 | `/` | 创建任务、确认 Rubric、查看 IR / 渲染 / L1 / Evidence |
| IR 编辑器 | `/editor` | 字段编辑、保护项、Patch Diff、服务端校验应用 |
| 评测面板 | `/evaluation` | 逐任务结果、通过率、95% CI、McNemar p、门禁标签 |
| 模型配置 | `/settings` | providers / roles / targets 校验与保存 |
| 会话回放 | `/sessions` | turns、events、suggestions、epoch |
| 基准与预注册 | `/benchmark` | 30 任务基准、split、冻结时间和隐藏集隔离状态 |

### 生成与评测闭环

- 创建任务后先返回 Rubric 草案，确认前不进入生成
- `rubric:confirm` 完成后展示 IR、渲染文本、L1 结果和 Evidence
- 演示模式明确标注“Mock 生成 · 不代表目标模型真实输出”
- live 评测需要真实模型端点和密钥

### IR v3 与 Patch

- slots 单一事实源，稳定 item ID
- base checksum 并发保护，服务端重新计算新 checksum
- `DELETE` 必须附证据引用，受保护字段只读
- Ledger 记录版本、墓碑、审计哈希链和授权消费

### 分层评测

- L1：确定性规则
- L2：LLM 裁判，可启用交换双裁
- L3：脚本化或真实模型执行评测
- 统计：置信区间、Wilcoxon、McNemar、bootstrap、TOST
- 预注册门禁：先冻结口径，再看结果

### Windows 桌面客户端

- Electron 负责窗口与后端进程管理
- PyInstaller 单文件后端，内置 Python、FastAPI、`web/dist` 和 SQLite schema
- 首次启动自动创建 `%APPDATA%\Prompt5\config.yaml` 和 `prompt5.db`
- 无需安装 Python、Node 或数据库
- 窗口关闭时自动清理后端子进程
- 演示模式完全离线可用

---

## 仓库结构

```text
.
├── README.md                 ← 项目总览
├── docs/                     ← 产品方案、设计文档、搭建执行方案
│   ├── 提示词生成器系统-搭建执行方案.md
│   ├── 自适应提示词生成器系统设计方案-v1.0-合并版.html
│   └── 外部Agent连接器接口规范-v1.0.html
└── prompt5/                  ← 工程实现
    ├── README.md             ← 安装、使用、模块和命令说明
    ├── HANDOFF.md            ← Web / 桌面端交接说明
    ├── NOTES.md              ← 工程决策与降级记录
    ├── src/prompt5/          ← Python 后端
    ├── tests/                ← 后端测试
    ├── specs/                ← 4 份 JSON Schema
    ├── benchmarks/           ← 30 任务基准与预注册
    ├── reports/              ← pilot / M7 报告
    ├── web/                  ← React 19 六页工作台
    └── desktop/              ← Electron + PyInstaller + NSIS
```

---

## 快速开始

### Windows 桌面端

```powershell
cd prompt5
powershell -ExecutionPolicy Bypass -File .\desktop\scripts\build-windows.ps1
```

构建产物：

```text
prompt5/desktop/release-windows/Prompt5-Setup-0.1.0.exe
```

安装后首次启动会自动初始化配置和 SQLite，无需额外安装运行时。安装包未做代码签名，SmartScreen 可能提示。

> 安装包属于本机构建产物，未纳入 Git 仓库；克隆仓库后需执行上述脚本生成。

### 本地 Web 开发

```powershell
cd prompt5
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"

cd web
npm ci
npm run test
npm run build

cd ..
.venv/Scripts/python -m prompt5.ui --host 127.0.0.1 --port 8765
```

打开 <http://127.0.0.1:8765>。

### 后端 CLI

```powershell
cd prompt5

.venv/Scripts/python -m prompt5.cli demo-zero --task "把这份 CSV 做成分析报告"
.venv/Scripts/python -m prompt5.export_schema
.venv/Scripts/python -m prompt5.cli config check
.venv/Scripts/python -m prompt5.tck
```

完整命令和配置说明见 [`prompt5/README.md`](prompt5/README.md)。

---

## 测试与验收

| 范围 | 命令 | 结果 |
|---|---|---|
| 后端 | `cd prompt5 && .venv/Scripts/python -m pytest tests -q` | 407 passed / 30 subtests |
| 前端行为 | `cd prompt5/web && npm run test` | 5 passed |
| 前端构建 | `cd prompt5/web && npm run build` | 通过 |
| 浏览器 smoke | `cd prompt5/web && npm run test:browser` | 六页、移动端、人工确认流程通过 |
| Windows 安装 | `prompt5/desktop/scripts/build-windows.ps1` | 安装、启动、页面加载、退出清理通过 |

---

## 当前进度

| 阶段 | 状态 | 内容 |
|---|---|---|
| M0–M3 | 完成 | 基础设施、IR/Patch/Ledger、从零生成、评测引擎 |
| M4 | 完成 | 种子反解、补丁链、回归保护、意图门禁 |
| M5 | 完成 | 分层评测、统计、缓存与报告 |
| M6 | 完成 | 在线会话、事件 outbox、连接器契约测试 |
| M7 | 骨架完成 | 30 任务基准、隐藏集、B1-OSS 基线、预注册、门禁判定 |
| UI0 | 完成 | 六页 React 工作台、UI 适配 API、行为测试、浏览器 smoke |
| Desktop 0.1 | Windows 完成 | Electron 壳、单文件后端、NSIS 安装包 |

M7 的真实 live 确证运行仍需要可用模型端点与密钥。

---

## 已知边界

- 当前为本地单用户模式，无登录、多租户和权限体系
- live 评测需要用户自行配置模型端点与 API Key
- 演示模式使用固定快照，不构成真实模型效果证据
- MCP 已实现工具注册与调度，传输层尚未接入
- 回调推送尚未接 HTTP，当前使用拉取式事件通道
- macOS / Linux 桌面端未实现
- Windows 安装包未签名，使用 Electron 默认图标
- SQLite + 线程模型适用于单 worker；多 worker 前需切换 PostgreSQL

---

## 文档导航

1. [`prompt5/README.md`](prompt5/README.md) — 安装、使用、目录和测试
2. [`prompt5/HANDOFF.md`](prompt5/HANDOFF.md) — 前端/桌面端交接与 UI API
3. [`prompt5/NOTES.md`](prompt5/NOTES.md) — 工程决策、降级与踩坑记录
4. [`docs/提示词生成器系统-搭建执行方案.md`](docs/提示词生成器系统-搭建执行方案.md) — 搭建依据与里程碑 DoD
5. [`docs/自适应提示词生成器系统设计方案-v1.0-合并版.html`](docs/自适应提示词生成器系统设计方案-v1.0-合并版.html) — 设计定稿

---

## 许可

代码以 [`prompt5/LICENSE`](prompt5/LICENSE) 中的 MIT License 授权。
