# Prompt5 — 自适应提示词生成与评测工作台

> **测试状态声明：当前仅为内部测试项目，不能用于生产环境。**
> 功能、接口、数据结构、评测结论和安装包均可能随时变化；请勿用于真实业务、生产数据或对外正式交付。演示模式与 Mock 生成结果不代表真实模型效果。

Prompt5 是一个面向提示词工程的可审计工作台。它把自然语言需求转换为结构化 IR，先由人确认验收标准，再执行生成、渲染和分层评测，最终给出带证据链的结果。

当前版本包含完整的 Web 六页工作台和 Windows 桌面客户端，支持离线演示模式。真实模型评测需要用户配置自己的模型端点与 API Key。

| 项目信息 | 值 |
|---|---|
| 技术栈 | Python 3.11+ · FastAPI · React 19 · TypeScript · Vite · SQLite |
| 桌面端 | Electron 32 · PyInstaller · electron-builder（Windows） |
| 当前里程碑 | M0–M6 完成 · M7 骨架完成 · UI0 完成 · Windows Desktop 0.1 完成 |
| 测试状态 | 后端 407 passed / 30 subtests · 前端 5 passed · 浏览器 smoke 通过 |
| 许可证 | MIT |

配套文档：

- [HANDOFF.md](HANDOFF.md)：前端/桌面端交接、UI 适配 API 与交互约束
- [NOTES.md](NOTES.md)：环境、网络和工程决策记录
- [config.example.yaml](config.example.yaml)：完整配置示例
- 仓库根目录 [`docs/`](../docs/)：产品方案与设计文档

---

## 项目简介

提示词工程常见的问题是：需求描述很模糊、生成结果不可解释、不同模型的输出无法横向比较，评测过程也缺少可复核的证据。

Prompt5 把流程拆成三个明确阶段：

1. **生成前确认标准**：后端返回版本化的 Rubric 草案，用户显式确认后才开始生成。
2. **结构化生成与编辑**：结果以 IR v3 表示，支持稳定 item ID、字段保护、Patch Diff 和服务端校验。
3. **分层评测与统计**：L1 规则、L2 裁判、L3 执行评测，结合置信区间、McNemar、bootstrap 和预注册门禁输出报告。

适用场景：

- 提示词模板设计与迭代
- 多模型输出质量对比
- 提示词 A/B 测试与回归评测
- 团队内部的提示词资产管理和审计

---

## 核心功能

### 1. 生成 → 人工确认 → 评测闭环

- 创建任务后先返回 Rubric 草案，确认前不会调用生成流程
- 确认动作与后续 Evidence 版本绑定
- IR、渲染文本、L1 结果和证据在同一页面展示
- 演示模式全程标注“Mock 生成 · 不代表目标模型真实输出”

### 2. IR v3 与可审计 Patch

- slots 作为单一事实源，item ID 稳定可追踪
- Patch 使用 base checksum 做并发保护，服务端重新计算新 checksum
- 支持字段保护申请；`DELETE` 操作必须附证据引用
- Ledger 记录版本、墓碑、审计哈希链和授权消费

### 3. 分层评测

- **L1**：确定性规则检查
- **L2**：LLM 裁判，可启用交换双裁减少位置偏差
- **L3**：脚本化或真实模型执行评测
- 统计：置信区间、Wilcoxon、McNemar、bootstrap、TOST
- 预注册门禁：先冻结口径，再看结果，避免事后挑选指标

### 4. 六页 Web 工作台

| 页面 | 路径 | 主要用途 |
|---|---|---|
| 任务工作台 | `/` | 创建任务、确认 Rubric、查看 IR / 渲染 / L1 / Evidence |
| IR 编辑器 | `/editor` | 查看字段、保护项、提交 Patch、审阅 Diff |
| 评测面板 | `/evaluation` | 展示逐任务结果、通过率、CI、p 值和门禁标签 |
| 模型配置 | `/settings` | 管理 providers / roles / targets，校验后保存 |
| 会话回放 | `/sessions` | 回放 turns、events、suggestions 和 epoch |
| 基准与预注册 | `/benchmark` | 浏览 30 任务基准、split、冻结时间和隐藏集状态 |

### 5. Windows 桌面客户端

- Electron 负责窗口和进程管理
- PyInstaller 将 FastAPI 后端、Python 运行时、`web/dist` 和 SQLite schema 打包为单文件
- 首次启动自动创建配置和数据库，不需要安装 Python、Node 或数据库
- 后端只监听本机随机端口，退出时自动清理子进程
- 演示模式可完全离线使用

### 6. 会话与事件

- 在线会话包含语义门控、建议四元组和 epoch CAS
- 事件 outbox 支持持久化、重试、DLQ 和游标拉取
- 会话回放页面只展示真实存在的数据，不提供未闭环的假按钮

---

## 系统架构

```text
┌──────────────────────────────┐
│ Electron 桌面壳（Windows）    │
│  - 选择本机空闲端口           │
│  - 启动/停止后端进程          │
│  - 打开本地窗口               │
└──────────────┬───────────────┘
               │ spawn
┌──────────────▼───────────────┐
│ prompt5-backend.exe           │
│  - FastAPI /v1 + UI 适配 API  │
│  - web/dist 静态托管          │
│  - SQLite                     │
└──────────────┬───────────────┘
               │
       %APPDATA%\Prompt5\
       ├── config.yaml
       └── prompt5.db
```

Web 开发模式可使用 Vite 独立运行前端，通过 `VITE_API_MODE=remote` 连接本地 FastAPI。

---

## 快速开始

### 方式一：Windows 桌面端（推荐给最终用户）

#### 构建要求

- Windows 10/11 x64
- Python 3.11+
- Node.js 22+
- PowerShell

#### 一键构建

```powershell
cd prompt5
powershell -ExecutionPolicy Bypass -File .\desktop\scripts\build-windows.ps1
```

脚本会依次完成：

1. 构建 `web/dist`
2. 安装 PyInstaller
3. 生成 `prompt5/dist/prompt5-backend.exe`
4. 生成 NSIS 安装包

产物：

```text
desktop/release-windows/Prompt5-Setup-0.1.0.exe
```

> 构建产物不纳入 Git 仓库，克隆后需在本地执行上述脚本生成安装包。

#### 安装与使用

1. 双击 `Prompt5-Setup-0.1.0.exe`
2. 按向导选择安装目录
3. 安装完成后双击桌面 `Prompt5`
4. 首次启动会自动创建：
   - `%APPDATA%\Prompt5\config.yaml`
   - `%APPDATA%\Prompt5\prompt5.db`
5. 直接进入演示模式工作台，无需安装 Python/Node 或手动配置

当前安装包未做代码签名，Windows SmartScreen 可能提示。选择“更多信息 → 仍要运行”即可。

#### 卸载

在 Windows“设置 → 应用”中找到 Prompt5 卸载。用户数据目录默认不会删除，避免误删本地会话和评测记录。

---

### 方式二：本地 Web 开发

#### 1. 准备后端

```powershell
cd prompt5
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"
```

#### 2. 构建并测试前端

```powershell
cd web
npm ci
npm run test
npm run build
```

#### 3. 启动本地统一服务

```powershell
cd ..
.venv/Scripts/python -m prompt5.ui --host 127.0.0.1 --port 8765
```

打开 <http://127.0.0.1:8765>。

#### 4. 前端独立开发（可选）

```powershell
cd web
copy .env.example .env.local
npm run dev
```

`.env.local` 示例：

```dotenv
VITE_API_MODE=remote
VITE_CONNECTOR_TOKEN=host-agent-alpha
```

`VITE_CONNECTOR_TOKEN` 仅用于本地开发。生产环境应由网关注入真实 token，不要把密钥提交到仓库。

---

### 方式三：仅使用后端 CLI

```powershell
cd prompt5

# 端到端生成
.venv/Scripts/python -m prompt5.cli demo-zero --task "把这份 CSV 做成分析报告"

# 导出并校验 JSON Schema
.venv/Scripts/python -m prompt5.export_schema

# 校验配置：端点、密钥、角色、裁判池、目标
.venv/Scripts/python -m prompt5.cli config check

# 运行契约测试套件
.venv/Scripts/python -m prompt5.tck

# 冻结 M7 预注册
.venv/Scripts/python -m prompt5.cli m7 init
```

真实模型评测需要先配置端点与密钥：

```powershell
.venv/Scripts/python -m prompt5.cli probe --target deepseek
.venv/Scripts/python -m prompt5.cli pilot --executor live --target deepseek
```

---

## 配置说明

### 演示模式

默认使用 `demo mode`，页面使用固定快照数据，不访问外部模型。演示结果会明确标注，用便于体验和前端联调，但不会被当作真实评测结论。

### 真实模型模式

1. 打开“模型与端点配置”页面
2. 填写 provider、endpoint、model、API Key 环境变量名
3. 点击校验，确认端点、角色和裁判池满足要求
4. 保存后运行 probe 或 live 评测

配置文件中的密钥采用 `${ENV_VAR}` 形式引用。UI 不会回显密钥明文，服务端只返回配置状态。

### 关键环境变量

| 变量 | 作用 |
|---|---|
| `VITE_API_MODE` | `demo` 或 `remote` |
| `VITE_CONNECTOR_TOKEN` | 本地开发用 connector token |
| `PROMPT5_DATA_DIR` | 覆盖桌面端/冻结版的数据目录 |
| `PROMPT5_*` | 配置文件中引用的模型密钥与环境变量 |

---

## 常用命令

| 命令 | 说明 |
|---|---|
| `.venv/Scripts/python -m pytest tests -q` | 后端全量测试 |
| `.venv/Scripts/python -m prompt5.ui --port 8765` | 本地统一 Web 服务 |
| `.venv/Scripts/python -m prompt5.api --serve --port 8765` | 仅启动 FastAPI API |
| `.venv/Scripts/python -m prompt5.cli demo-zero --task "..."` | 端到端生成 |
| `.venv/Scripts/python -m prompt5.cli config check` | 配置校验 |
| `.venv/Scripts/python -m prompt5.cli m7 run --executor live --target deepseek` | 真实 M7 门禁评测 |
| `cd web && npm run test` | 前端行为测试 |
| `cd web && npm run test:browser` | 六页 / 移动端 / 人工确认浏览器 smoke |

---

## 目录结构

```text
prompt5/
├── src/prompt5/
│   ├── canonical.py        RFC 8785 JCS + sha256 + tuple_hash
│   ├── ir.py               IR v3、稳定 item ID、checksum
│   ├── patch.py            Patch 契约、loc 文法、兼容矩阵
│   ├── applier.py          两阶段执行、零部分应用
│   ├── ledger.py           版本台账、墓碑、CAS、审计哈希链
│   ├── config.py           YAML 配置加载与环境变量展开
│   ├── capabilities.py     9 能力 / 18 MCP 工具 / 32 错误码
│   ├── blobs.py            材料上传、哈希、配额、租户隔离
│   ├── engine/             生成、迭代、pilot、渲染流水线
│   ├── modules/
│   │   ├── m1_extractor.py 意图抽取
│   │   ├── m3_cards.py     模型卡与渲染
│   │   ├── m4_generator.py 提示词骨架策略
│   │   ├── m5_eval/        L1 / L2 / L3 评测、统计、缓存
│   │   ├── m6_sessions.py 在线会话与建议
│   │   ├── m6_events.py    事件 outbox
│   │   └── m7_bench.py     30 任务基准、预注册、门禁
│   ├── connector/
│   │   ├── api.py          服务层与 HTTP 资源
│   │   ├── ui_api.py       UI 适配接口
│   │   ├── rubric.py       Rubric 草案版本化
│   │   └── mcp_adapter.py  MCP 工具注册表
│   ├── store/              schema.sql / schema_v2.sql / 迁移
│   ├── security/           SSRF 守卫、HMAC 签名
│   ├── tck/                契约测试套件
│   ├── ui.py               本地统一启动入口
│   └── api/                FastAPI 启动与 dry-run
├── web/                    React 19 六页工作台
├── desktop/                Electron + PyInstaller + NSIS
├── tests/                  后端测试
├── specs/                  JSON Schema 产物
├── benchmarks/             30 任务基准与预注册
├── examples/               示例材料
└── reports/                pilot / M7 报告
```

---

## 测试与验收

| 范围 | 命令 | 本次结果 |
|---|---|---|
| 后端 | `.venv/Scripts/python -m pytest tests -q` | 407 passed / 30 subtests |
| 前端行为 | `cd web && npm run test` | 5 passed |
| 前端类型检查 | `cd web && npm run build` | 通过 |
| 浏览器 smoke | `cd web && npm run test:browser` | 六页、移动端、人工确认流程通过 |
| Windows 安装 | `desktop/scripts/build-windows.ps1` | 安装、启动、页面加载、退出清理通过 |

桌面端验收覆盖：

- 安装包静默安装
- 启动后主窗口标题为 `Prompt5 · 提示词工作台`
- 后端 `/healthz` 返回正常
- 六页路由可访问
- 创建任务 → 确认 Rubric → 生成结果流程可完成
- 关闭窗口后 Electron 与后端进程均被清理

---

## 里程碑与限制

### 里程碑

- M0–M6：后端骨架、IR/Patch/Ledger、评测、会话、事件完成
- M7：30 任务基准、隐藏集、B1-OSS 基线、预注册和门禁判定完成骨架；live 确证待真实密钥
- UI0：六页 React 工作台、UI 适配 API、行为测试和浏览器 smoke 完成
- Desktop 0.1：Windows Electron 客户端、PyInstaller 后端、NSIS 安装包完成

### 当前限制

- 当前是本地单用户模式，无登录、多租户和权限体系
- 真实 live 评测需要用户提供可用模型端点与 API Key
- M7 的 live 确证运行仍需真实密钥；演示和 scripted 评测可离线运行
- MCP 目前是工具注册表与调度器，传输层尚未接入
- 回调推送尚未接 HTTP；已有拉取式事件通道
- macOS/Linux 桌面端本次未实现
- Windows 安装包未签名，使用 Electron 默认图标
- 安装包不纳入 Git 仓库，需要本地构建或后续通过 Release 分发

---

## 贡献与开发约束

1. 不提交密钥、生产配置或 `.env.local`
2. 演示数据必须继续标注为演示，不能冒充真实模型输出
3. 生成前必须保留人工 Rubric 确认步骤
4. 隐藏集任务只展示隔离状态，不返回 simulation/gold 内容
5. 写操作失败时返回具体 `error_code`，不返回“未知错误”
6. IR 写操作必须走服务端 Patch 校验，前端不自行计算 checksum

---

## License

[MIT](LICENSE)
