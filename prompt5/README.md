# prompt5 — 自适应提示词生成器

> 唯一搭建依据：《提示词生成器系统-搭建执行方案.md》（见仓库根目录 [`docs/`](../docs/)）。
> 本仓库当前进度：**M7 骨架完成**（30 任务基准 + 隐藏集 + B1-OSS 基线 + 预注册 + 门禁判定）；确证运行需真实密钥。
> **UI 交接版已完成**：React 19 + TypeScript + Vite 六页工作台、本地 UI 适配 API、契约测试与浏览器 smoke 已接入。
> 项目总览与产出索引见仓库根目录 [`README.md`](../README.md)。

## 项目公告

### 2026-10-25 · Windows 桌面端 v0.1

本次新增 Windows 本地桌面客户端：

- Electron 桌面壳 + PyInstaller 单文件后端 + `web/dist`
- 一键构建脚本：`desktop/scripts/build-windows.ps1`
- NSIS 安装包：`desktop/release-windows/Prompt5-Setup-0.1.0.exe`
- 首次启动自动创建 `%APPDATA%\Prompt5\config.yaml` 与 SQLite，无需安装 Python/Node
- 已验证安装、启动、页面加载、后端健康检查与关闭后进程清理
- 安装包 SHA-256：`71CA9BD1071E64E6383E48F62C125A76941E0B5F82B7293C386B7696039070FE`
- 当前安装包未签名，SmartScreen 可能提示；macOS 端本次未实现

## 环境

| 项 | 值 |
|---|---|
| Python | 3.13（`.venv` 内解释器由系统 Python 3.13.12 创建） |
| 虚拟环境 | `prompt5/.venv`（必须激活或用 `.venv/Scripts/python` 显式调用） |
| Node | 22 LTS（React 19 + Vite 6 + TypeScript 5.7） |
| 已装依赖 | pytest 9.1.1 · pydantic 2.14.1 · fastapi 0.162.0 · uvicorn 0.54.0 · httpx 0.28.1 · PyYAML · jsonschema |
| 包安装 | `pip install -e . --no-deps`（editable，`python -m prompt5` 免 PYTHONPATH） |

> **网络注意（本机）**：本机唯一出口是会话注入的 `HTTPS_PROXY=http://127.0.0.1:1441`。
> 装包时**不要** `unset` 代理，否则 pip 会报 `from versions: none`。见 `NOTES.md #3`。

## 常用命令

```bash
cd prompt5
.venv/Scripts/python -m pytest tests -q                          # 全量测试（407 项）
.venv/Scripts/python -m pytest tests/test_applier_property.py -q # M1 DoD：339 属性用例
.venv/Scripts/python -m prompt5.export_schema                    # M1 DoD：导出 4 份 Schema 并校验
.venv/Scripts/python -m prompt5.cli demo-zero --task "把这份 CSV 做成分析报告"   # M2 DoD：端到端
.venv/Scripts/python -m prompt5.cli pilot --quiet                                # M3 DoD：pilot 报告（离线模拟）
.venv/Scripts/python -m prompt5.cli config check                                 # 校验端点/密钥/角色/裁判池/目标
.venv/Scripts/python -m prompt5.cli probe --target deepseek                     # 端点探活（真实最小请求）
.venv/Scripts/python -m prompt5.tck                                             # M6 DoD：契约测试套件（12 项）
.venv/Scripts/python -m prompt5.cli m7 init                                     # 生成并冻结预注册
.venv/Scripts/python -m prompt5.cli m7 run --executor live --target deepseek     # 确证集门禁（需密钥）
.venv/Scripts/python -m prompt5.cli pilot --executor live --target deepseek     # 真实 L3 评测（需密钥）
.venv/Scripts/python -m prompt5.cli pilot --judge l2                            # 启用 L2 交换双裁（自动选异族裁判）
.venv/Scripts/python -m prompt5.cli iterate --seed-file examples/seed_report.md \
    --task "请用表格输出，必须给出数据来源" --db :memory:                        # M4 DoD：种子迭代
.venv/Scripts/python -m prompt5.cli demo-zero --task "..." --json              # 输出完整 IR
.venv/Scripts/python -m prompt5.api --dry                        # 打印 capabilities
.venv/Scripts/python -m prompt5.api --serve --port 8765          # FastAPI 服务
```

## UI 快速开始

```powershell
cd prompt5
# 后端测试依赖
python -m venv .venv
.venv/Scripts/python -m pip install -i https://mirrors.aliyun.com/pypi/simple/ -e ".[dev]"

# 前端开发 / 测试 / 构建
cd web
npm install
npm run test          # 5 个关键行为测试
npm run build         # tsc --noEmit + vite build

# 本地联调（可选）
copy .env.example .env.local
# .env.local:
# VITE_API_MODE=remote
# VITE_CONNECTOR_TOKEN=host-agent-alpha   # 本地开发用示例 token；生产应通过网关注入
npm run dev             # http://127.0.0.1:5173

# 生产式本地启动：FastAPI 同时托管 web/dist
cd ..
.venv/Scripts/python -m prompt5.ui --host 127.0.0.1 --port 8765
# 打开 http://127.0.0.1:8765

# 浏览器 smoke：六页加载 + 移动端溢出 + 人工确认全流程
cd web
npm run test:browser
```

UI 默认进入 **demo mode**，使用固定快照并全程标注“演示数据”；`VITE_API_MODE=remote` 才调用本地 FastAPI。演示结果不会冒充真实模型输出，scripted/live 与基线口径会随报告一起显示。

## Windows 桌面端快速开始

```powershell
cd prompt5
powershell -ExecutionPolicy Bypass -File .\desktop\scripts\build-windows.ps1
```

脚本会依次完成：

1. 构建 `web/dist`
2. 安装 PyInstaller
3. 打包 FastAPI 后端为 `prompt5/dist/prompt5-backend.exe`
4. 生成 NSIS 安装包到 `desktop/release/`

产物：

```text
desktop/release-windows/Prompt5-Setup-0.1.0.exe
```

安装后无需配置 Python、Node 或数据库；首次运行会自动使用内置默认配置和 SQLite。演示模式完全离线可用。若需真实模型评测，请在界面中的“模型与端点配置”填写 API Key。

## 目录

```
src/prompt5/
├── canonical.py      RFC 8785 JCS + sha256 + tuple_hash（唯一序列化标准）
├── ids.py            patch_id(ULID) / item_id 派生与校验
├── config.py         YAML 加载（PyYAML 优先，内置最小解析器兜底）+ ${ENV} 展开
├── capabilities.py   9 能力 / 18 MCP 工具 / 32 错误码（唯一数据源）
├── ir.py             IR v3（slots 单一事实源 + item_ids 稳定 ID 映射 + checksum）
├── patch.py          Patch 契约 / loc 文法解析 / 16 格兼容矩阵 / 授权模型
├── applier.py        两阶段执行模型（纯函数；零部分应用）
├── ledger.py         版本台账 / 墓碑 / CAS 提交 / 审计哈希链 / 授权消费
├── contracts.py      TaskRequest / EvalEvidence（对外契约）
├── export_schema.py  4 份 JSON Schema 导出与机器校验
├── testing.py        测试工厂（非生产）
├── cli.py            demo-zero / extract 子命令
├── llm/              LLMClient 协议 + MockLLM + OpenAI 兼容客户端
├── modules/          m1_extractor（意图）/ m3_cards（模型卡+渲染）/ m4_generator（骨架策略）
│   ├── m1_seed.py    种子反解（渲染文本 → IR，承诺往返）
│   ├── m6_sessions.py 在线会话：语义门控 + 建议四元组 + epoch CAS
│   ├── m6_events.py   事件 outbox：持久化 / 重试 / DLQ / 游标拉取
│   └── m5_eval/      l1_rules / l2_judge / l3_exec（scripted+live）/ regression
│                     evalcase（单元与聚合）/ stats（Wilcoxon/McNemar/bootstrap/TOST）
│                     cache（键隔离）/ runner（流程+报告）
├── blobs.py          材料上传（服务端算哈希/白名单/配额/TTL/租户隔离）
├── connector/        api.py（服务层+HTTP 20 资源）/ mcp_adapter.py（18 工具）
│   ├── rubric.py     任务级 Rubric 草案版本化
│   └── ui_api.py     UI 专用薄适配 API（Patch / Eval / Config / Replay / Benchmark）
├── ui.py             本地单用户统一启动入口（FastAPI + web/dist 托管）
├── modules/m7_bench.py 30 任务基准 / B1-OSS 基线 / 预注册 / 门禁判定
├── security/         ssrf.py（回调地址守卫）/ signing.py（HMAC 签名）
├── tck/              suite.py + __main__.py（契约测试套件）
├── engine/           flow_zero（A）+ pilot（M3）+ iterate（B）+ render_pipeline（Overlay）
├── store/            schema.sql（14 表）+ 迁移（PRAGMA user_version）
├── api/              --dry / --serve（FastAPI；缺失时 stdlib 兜底）
├── web/              React 19 六页工作台 + 设计 token + UI 行为/浏览器测试
└── desktop/          Electron + PyInstaller + electron-builder（Windows 桌面端）
specs/                 JSON Schema 导出产物（M1）
benchmarks/            金标任务与基线（M7）
```

## 里程碑状态

M0 ✅ → M1 ✅ → M2 ✅ → M3 ✅ → M4 ✅ → M5 ✅ → M6 ✅ → M7 骨架 ✅（确证运行待真实密钥）。
UI0 ✅：六页 React UI + 本地适配 API + 契约/行为/浏览器测试（当前为本地单用户工作台；多用户需网关层补齐）。
