# HANDOFF · 可视化开发交接说明

> 本仓库包含**后端框架**（Python）和已接入的 **React 本地单用户工作台**（`web/`）。
> 后端核心契约不变；UI 通过新增的 `connector/ui_api.py` 适配层调用既有能力。
> 请不要重写后端核心，也不要绕过下面「交互约束」里的规则——它们是这套系统的正确性前提。

## 1. 它是什么

面向文本/系统提示词的「生成—迭代—评测」系统：

- 把用户意图解析成结构化 **Prompt IR**（不是纯文本）；
- 用补丁（Patch）对 IR 做可审计的增量修改（ADD/DELETE/REWRITE/MOVE）；
- 逐模型渲染、逐模型评测，输出含统计区间的证据；
- 有在线会话改进（建议四元组 + 幂等）与外部 Agent 连接器（HTTP + MCP 18 工具）。

## 2. 十分钟跑起来

```bash
cd prompt5
python -m venv .venv
.venv/Scripts/python -m pip install -i https://mirrors.aliyun.com/pypi/simple/ -e ".[dev]"
cp config.example.yaml config.yaml          # 填 providers 的 base_url / api_key_env
.venv/Scripts/python -m prompt5.api --serve --port 8765   # 已有：/v1/capabilities, /v1/blobs
```

连接器完整 API（20 个资源）由下面入口提供（建议用它作为 UI 的后端）：

```bash
.venv/Scripts/python -c "
from prompt5.config import load_config
from prompt5.connector.api import build_connector_app
import uvicorn
uvicorn.run(build_connector_app(load_config('config.yaml').data, db_path='prompt5.db'),
            host='127.0.0.1', port=8765)
"
```

前端开发期请自行加 CORS（`CORSMiddleware`），生产按部署域名收紧。

鉴权：`Authorization: Bearer <connector.id>`（示例配置里是 `host-agent-alpha`），
如需多租户再带 `X-Tenant-Id`（必须与 token 的 tenant 一致，否则 401）。

## 3. 后端能力（建议 UI 直接对接）

| 能力 | 方法/路径 | 说明 |
|---|---|---|
| 能力协商 | `GET /v1/capabilities` | 9 项能力 + scope 状态 |
| Schema | `GET /v1/schema` | IR/Patch/TaskRequest/EvalEvidence 的 JSON Schema（可直接生成表单） |
| 模型卡 | `GET /v1/model-cards` | 6 个目标模型，含 `primary` / `tier` / `label` |
| 材料上传 | `POST /v1/blobs`（raw body + `X-Blob-Mime`） | 服务端算 SHA-256，返回 `blob_id` |
| 创建生成任务 | `POST /v1/tasks` → 202 | 返回 `task_id`，状态 `rubric_pending` |
| 确认 rubric | `POST /v1/tasks/{id}/rubric:confirm` | **人工锚点，不可自动跳过** |
| 任务状态 | `GET /v1/tasks/{id}` | 成功后含 `ir` / `rendered` / `l1` / `evidence` |
| 取消 | `POST /v1/tasks/{id}/cancel` | 终态返回 409（幂等语义） |
| 证据 | `GET /v1/tasks/{id}/evidence` | 复现层级 T1/T2/T3、渲染器版本 |
| 静态评分 | `POST /v1/score` | 传 `{"ir": {...}}`，返回 L1 报告 |
| 渲染 | `POST /v1/render` | 传 `{"ir": {...}, "model": "deepseek"}` |
| 开会话 | `POST /v1/sessions` | 绑定 `ir_id`，返回 `session_id` + `epoch` |
| 记一轮 | `POST /v1/sessions/{id}/events` | 服务端做语义门控，返回 `seq`/`kind`/`invalidates` |
| 拉事件 | `GET /v1/sessions/{id}/events?after_event_seq=N` | 游标拉取（推送失败时自愈） |
| 应用建议 | `POST /v1/sessions/{id}/patches` | 只传 `suggestion_id` + 四元组，服务端取原 Patch |
| 预算 | `GET /v1/budget` | 上限与用量 |
| 治理请求 | `POST /v1/protection-requests` · `POST /v1/model-card-requests` | 只提交，不批准 |

错误统一为 `{"error_code": "E_*", "detail": "..."}`，HTTP 状态码见 `src/prompt5/capabilities.py` 的 `ERROR_CODES`。

## 4. 核心数据模型（UI 必须理解的三件事）

1. **IR 是唯一事实源**：文本只是渲染结果。编辑要走补丁，接口返回的 `ir` 自带 `checksum`，**任何改动后 checksum 必须变**。
2. **列表项有稳定 ID**：`ir.item_ids` 里每个列表（must/workflow/done_criteria/…）与条目 ID 一一对应，删除/移动请用 ID，不要用下标。
3. **评测结论带层级**：`evidence.reproduction_tier` 是 T1/T2/T3；`L1` 只能证明结构合法，不能宣称效果。UI 上请把层级标签显示出来，不要合并成单一「分数」。

## 5. 建议做的六个页面（按优先级）

1. **任务工作台**：输入任务 → 选目标模型（默认 primary）→ 创建任务 → 展示 `rubric_pending` 与待确认要点 → 确认 → 轮询结果；三栏：对话 / IR 预览 / 渲染文本。
2. **IR 编辑器 + Diff 视图**：按 JSON Schema 生成表单（slots 分组），指令列表显示 `id`、`provenance`、保护状态；改动以 Patch 呈现（加了什么、删了什么、为什么、证据引用）。
3. **评测面板**：选择基准（`benchmarks/tasks_m7.jsonl`）、候选（champion vs b1-oss）、执行器（scripted/live）；展示逐任务通过率、均值差与 95% CI、McNemar p、门禁标签（optimizing/compatible/rejected）。
4. **模型与端点配置**：providers / roles（generator、reflector、裁判池）/ targets 三个表单；保存后调用 `config check` 的等价校验；「探针」按钮对应 `cli probe`（最小请求 + 耗时）。
5. **会话回放**：时间轴展示 turns（含语义分类）、events（含 state/attempts）、suggestions（proposed/applied/invalidated）与 epoch 变化。
6. **基准与预注册**：30 任务列表（split 标色：calibration/confirmatory/hidden）、隐藏集隔离提示、预注册文件的 `frozen_at` 只读展示。

## 6. 交互约束（硬性，违反即数据不可信）

- **rubric 必须由人确认**：不要在前端自动调用 `rubric:confirm`，也不要隐藏该步骤。
- **保护类只读**：`protect` 中 `enacted` 的 loc 不能在前端直接改，只能发起 `ProtectionChange`（当前用 `protection-requests` 提交建议）。
- **幂等键**：创建任务时每次用户操作生成唯一 `idempotency_key`，重试必须复用同一个键（后端会返回首次结果）。
- **不改 checksum**：前端不得自行构造/篡改 IR 的 `checksum`；编辑一律走 Patch 接口。
- **声明标签**：scripted 结果必须显示「模拟执行器·不构成效果证据」；B1-OSS 基线必须标注「开源专家模板基线，非人工盲写基线」。
- **不承诺**：不要说「超过人工专家」「全面最佳」「任意模型可用」。

## 7. 示例请求

```bash
TOKEN="Bearer host-agent-alpha"

curl -s localhost:8765/v1/model-cards -H "Authorization: $TOKEN"

curl -s -X POST localhost:8765/v1/tasks -H "Authorization: $TOKEN" \
  -H "Content-Type: application/json" -d '{
  "api_version":"1","request_id":"r1","idempotency_key":"ui-001",
  "connector_id":"host-agent-alpha","tenant_id":"t-001","op":"generate.v1",
  "input":{"mode":"zero","dialogue":[{"turn":1,"role":"user","text":"把这份 CSV 做成分析报告"}],
           "materials":[],"target_model":"deepseek","rubric_policy":"draft_then_confirm"}}'

curl -s -X POST localhost:8765/v1/tasks/<task_id>/rubric:confirm -H "Authorization: $TOKEN"
curl -s localhost:8765/v1/tasks/<task_id> -H "Authorization: $TOKEN"
```

## 8. 已知缺口（不要在前端假装已支持）

- 任务执行目前是**同步**（`rubric:confirm` 内完成），尚无后台 worker；前端按异步状态机写即可，后端会补齐。
- 回调推送未接 HTTP；只有「拉取」通道。签名与 SSRF 守卫已实现，等真实端点接入。
- MCP 目前是 18 工具注册表 + 调度器（`list_tools`/`call_tool`），传输层未接。
- 无用户体系/登录页；鉴权目前是 connector token。做多用户需要在网关层补。
- 无 i18n、无图表库选型约束——你可自选（建议 ECharts / Recharts）。

## 9. 前端验收建议（Definition of Done）

- 能完成一次「创建任务 → 人确认 rubric → 查看 IR + 渲染 + L1」全流程；
- 能展示一次评测的报告（逐任务表 + CI + p 值 + 门禁标签）且标签正确；
- 配置页能显示 `config check` 的错误（缺端点/缺密钥/裁判池不足）并阻止保存；
- 任何写操作失败时展示 `error_code` 而非「未知错误」；
- 所有声明性文案通过第 6 节检查（无越界表述）。

## 10. UI 交付状态（v0.1）

### 六页

1. `/` 任务工作台：创建任务 → 后端返回版本化 Rubric 草案 → 显式勾选并点击确认 → 查看 IR / 渲染 / L1 / Evidence。
2. `/editor` IR 编辑 + Diff：Schema 驱动字段、稳定 item ID、保护项只读、Patch Diff、删除必须填写 evidence_refs。
3. `/evaluation` 评测面板：scripted/live、逐任务通过率、95% CI、McNemar p、预注册门禁标签与声明。
4. `/settings` 配置：providers / roles / targets，校验错误阻止保存，密钥只显示环境变量状态，探针读取服务端生效配置。
5. `/sessions` 会话回放：turns、events、suggestions、epoch、增量拉取；suggestion 产生/应用链路未闭环处不做假按钮。
6. `/benchmark` 基准与预注册：30 任务、split、frozen_at 只读；隐藏集只显示隔离状态，不返回 simulation/gold。

### UI 命令

```bash
cd prompt5/web
npm install
npm run test                 # 5 个关键行为测试
npm run build                # tsc --noEmit + vite build
npm run test:browser         # 六页 / 移动端 / 人工确认浏览器 smoke
npm run start                # 启动 python -m prompt5.ui --port 8765
```

### 新增 UI 适配 API

| 能力 | 方法/路径 | 状态 |
|---|---|---|
| Rubric 草案 | `GET /v1/ui/tasks/{id}/rubric` | ✅ 与确认后 evidence 版本一致 |
| Patch 应用 | `POST /v1/ui/ir/patch` | ✅ 复用 Ledger，version+1，checksum 由服务端重算 |
| 评测报告 | `GET /v1/ui/evaluations/latest` / `POST /v1/ui/evaluations/run` | ✅ scripted 离线；live 需真实端点 |
| 配置 | `GET/PUT /v1/ui/config` · `POST /v1/ui/config/check` · `POST /v1/ui/config/probe` | ✅ 白名单字段，密钥不回显 |
| 会话回放 | `GET /v1/ui/sessions/{id}/replay` | ✅ turns/events/suggestions |
| 基准 | `GET /v1/ui/benchmark` | ✅ 脱敏任务字段，隐藏集不暴露 |

### 已验证

- 后端：`pytest tests -q` → **407 passed / 30 subtests**。
- 前端：`npm run test` → **5 passed**；`npm run build` → **tsc + vite 通过**。
- 浏览器：六页加载、移动端 `scrollWidth=390`、无横向溢出、“创建 → 人工确认 → 结果”完整通过。
- 生成结果当前仍使用 `MockLLM`，UI 会显示「Mock 生成 · 不代表目标模型真实输出」。
- 本地 UI 是单用户边界；公开多用户部署前仍需网关层补真实用户体系和密钥注入。
