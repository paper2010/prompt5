# NOTES.md — 未覆盖场景与降级台账（追加式，禁止修改历史条目）

> 规则来源：《搭建执行方案》§硬约束 10：未覆盖场景取最保守行为并登记。

## #1 PyPI 不可达 → M0 依赖降级（2026-10-25）

- **场景**：`pip install pytest pydantic` 在当前环境返回 `Could not find a version that satisfies the requirement pytest (from versions: none)`；`pydantic/fastapi/uvicorn/PyYAML/httpx/pytest` 全部未安装，Python 3.13.14 为裸环境。
- **采取**：
  1. M0 全部模块仅用 stdlib 实现（`canonical/ids/config/store/api --dry` 均不依赖第三方包），技术栈目标不变（见 pyproject）。
  2. 测试以 `unittest.TestCase` 风格编写（pytest 可直接收集），M0 用 `python -m unittest discover` 执行；DoD 中 `pytest ... -q` 的等价命令已在报告中如实标注偏差。
  3. `config.py` 优先 `import yaml`，缺失时启用内置最小 YAML 子集解析器（仅支持本项目 config 结构：嵌套映射、行内 flow map/list、引号/数字/布尔标量、注释、`${ENV}` 展开）。遇到子集外语法直接 `ConfigError`（保守失败，不猜测）。
  4. `api/app.py` 在 FastAPI 缺失时使用 stdlib `http.server` 提供 `/v1/capabilities` 冒烟服务；FastAPI 可用时自动切换（M1 起需要）。
- **影响**：M0 DoD 两条均可验证；M1 起需要 `pydantic`（IR/Patch 模型与 JSON Schema 导出）——已作为 [需要确认] 事项上报，需人工提供离线包或可用镜像。

## #2 `pytest` 缺失 → DoD 命令等价替换

- **场景**：DoD 写作 `pytest tests/test_canonical.py -q`，环境无 pytest。
- **采取**：`PYTHONPATH=src python -m unittest discover -s tests -v`；测试文件同时兼容 pytest（M1 环境恢复后可直接跑原命令）。

## #3 #1/#2 已解除：依赖安装成功，DoD 恢复逐字执行（2026-10-25）

- **根因（重要）**：本机唯一出网通道是会话注入的 `HTTPS_PROXY=http://127.0.0.1:1441`。首次安装失败是因为按旧经验**主动 unset 了代理**，导致 pip 只看到空索引（`from versions: none`）；而 `urllib` 走代理时 pypi.org 与阿里云镜像均返回 200。
- **采取**：
  1. `python -m venv .venv`（不污染 WorkBuddy 自带 Python）；`pip install -i https://mirrors.aliyun.com/pypi/simple/ pytest pydantic fastapi uvicorn httpx PyYAML`（**保留代理**）。
  2. `pip install -e . --no-deps` → `python -m prompt5.api` 不再需要 `PYTHONPATH`。
  3. 主路径切回方案锁定技术栈：config 用 PyYAML、API 用 FastAPI（`/openapi.json` 可访问即证明非兜底）；stdlib 解析器与 stdlib server 保留为离线兜底，测试继续覆盖。
- **版本**：pytest 9.1.1 / pydantic 2.14.1 / fastapi 0.162.0 / uvicorn 0.54.0 / httpx 0.28.1 / PyYAML（安装时最新）。
- **验证**：`pytest tests/test_canonical.py -q` → 14 passed, 19 subtests；`pytest tests -q` → 44 passed, 30 subtests；`--dry` 无 PYTHONPATH 通过；FastAPI `GET /v1/capabilities` 200 且 `/openapi.json` 暴露 2 条路径。
- **剩余 [需要确认]**：三个目标模型端点与密钥（`GLM_URL/DSK_URL/QWEN_URL` + `*_KEY`），M3 前必须提供；M2 用 Mock LLM 不阻塞。


## #4 IR 列表项 ID 的落地决策 + checksum 规范化修复（M1，2026-10-25）

- **场景（计划未覆盖的矛盾）**：§4.1 的 IR 样例中 `constraints.must / workflow / goal.done_criteria` 均为 `list[str]`，没有存放 item_id 的位置；而 §4.3 的 loc 文法要求列表项必须以稳定 ID 寻址（`must[c-xxx]`）。
- **采取**：IR 顶层增加 `item_ids: {list_path: [item_id, ...]}`，与各列表按下标对齐；初始 ID = `sha256(JCS([ir_id, path, index]))[:10]`（确定性、与内容无关）；`freeform_extras[i].id` 由 `build_ir` 注入并与 `item_ids` 保持一致；仅 applier 可修改；`item_ids` 参与 checksum。ADD 新项的 ID 仍按 §4.2 用 `hash(patch_id, op_index)` 派生，冲突时 +2 位扩展。
- **副产物（DELETE 空容器）**：空容器删除不产生任何状态变化，按 no-op 处理（`E_INTENT_MISMATCH`），与"no-op 非法"一致；非空容器删除 → `E_DELETE_NONEMPTY`。
- **实现中发现并修复的真缺陷**：checksum 原在 Pydantic 校验**之前**对原始载荷计算，而校验会补齐默认值，导致同一语义产生两个 checksum —— 后果是 no-op 检测失效、CAS 误判。已改为「先校验 → 基于规范化 payload 计算 checksum」。

## #5 M3 API 线程模型边界（2026-10-25）

- **场景**：FastAPI/TestClient 在工作线程执行路由，而 SQLite 连接默认 `check_same_thread=True` → `ProgrammingError`。
- **采取**：`store.connect(...)` 增加 `check_same_thread` 参数（默认 True 保持安全），仅 API 构建路径传 False 复用单连接。
- **已知边界**：该方案只适用于单进程（TestClient / uvicorn 单 worker）。**多 worker 前必须切 PostgreSQL**（M6 连接器阶段一并处理），不允许用「多进程 + SQLite」硬撑。

## #6 种子反解的保证边界（M4，2026-10-25）

- **场景**：计划要求「种子反解」（既有提示词 → IR），但外部提示词格式无穷。
- **采取**：只承诺对本项目渲染器（`m3_cards`，template `tpl1`）的输出可**往返**（测试锁定 roundtrip）；对无结构文本退化为「整段作为 goal.outcome」并写入 `created.assumptions`；不猜测未出现的槽位、不臆造约束。
- **未覆盖**：任意第三方提示词模板的结构识别属后续能力，需先补模板库再扩展，不在当前承诺范围。

## #7 schema v2：在线会话新增 turns / suggestions（M5，2026-10-25）

- **场景**：M0 的 DDL 来自方案 §5（14 表），在线模式需要「轮次记录」与「不可变建议（四元组）」两类数据，原表无法承载。
- **采取**：新增迁移 `schema_v2.sql`（`turns`、`suggestions`），`PRAGMA user_version` 1→2，迁移幂等；`migrate()` 支持链式升级。未改动 v1 任何表结构（向后兼容）。
- **口径补充**：`context_hash` 只由「语义类轮」（invalidates=1）参与，寒暄/进展不计入——避免每条寒暄都让在途建议失效（补丁饥饿）。
- **边界**：`turns` 目前存明文对话（仅本地/测试库）；生产启用前必须接入方案 §5.3 的数据最小化（默认只存哈希/引用 + opt-in 全文）。

## #8 L2/L3 端点开放与裁判池回避规则（2026-10-25）

- **场景**：L2 裁判与 L3 执行端点原为固定角色名（judge_glm 等），无法适配用户自选厂商。
- **采取**：`roles.judges` 改为可填列表（provider+model），运行时按「裁判族 ≠ 被测族 且 ≠ 生成器族」自动挑选；池内无可用项时**显式报错**，不降级到同族裁判。`targets.*` 增加 `primary` 标记（唯一），L3 执行器 `OpenAICompatExecutor` 从 targets 读取端点/密钥。
- **验证入口**：`prompt5.cli config check`（端点/密钥/角色/裁判池/目标全量状态）+ `prompt5.cli probe [--target]`（真实最小请求探活，失败退出 1）。

## #9 M6 范围与契约偏差（2026-10-25）

- **任务执行时序**：`POST /v1/tasks` 返回 202 并置 `rubric_pending`；`rubric:confirm` 内**同步**完成生成。状态机保留异步语义（queued→rubric_pending→succeeded），但执行未真正后台化——P1 接入 worker 后替换，不改变对外状态机。
- **iterate 同步**：`pg_iterate` 同步返回最终 IR（无任务状态机）。属于 P0 简化，接口字段已预留 `state/ir_version`。
- **回调投递未启用**：签名（HMAC + 时间戳容差）与 SSRF 守卫已实现并纳入 TCK，但因无外部端点，`deliver_pending` 未接 HTTP 投递；推拉双通道中的「拉」已可用（`GET /sessions/{id}/events?after_event_seq=`）。
- **MCP 适配器**：当前是「18 工具注册表 + 调度器」（`list_tools` / `call_tool`），传输层（stdio/SSE）待 M6 之后接入；等价性由「HTTP 与 MCP 共用同一 ConnectorService」构造保证，TCK 另断言读接口输出完全相等。
- **判定**：以上均为显式边界，不是静默降级；TCK 对任一偏离都会失败。

## #10 人工预算替代：B1-OSS 开源专家模板基线（M7，2026-10-25）

- **场景**：M7 原计划需要 B1 人工盲写基线 + 3 人产出盲评（估 25–45 人时），实际无人力预算。
- **采取**：
  1. **主端点不变**：仍为「机器可判定任务成功率」，30 条基准全部机器判定（≥24 的硬要求已满足），因此**不需要人工盲评**；
  2. **B1 降级为 B1-OSS**：由开源专家提示词模板 + 任务 brief 填充构成，`human_blind_eval=false` 写入预注册；
     来源与许可：`f/prompts.chat`（提示词 CC0-1.0，act-as 范式）、`bigscience-workshop/promptsource`（Apache-2.0，input/target 分离思路）；
  3. **口径收窄**：结论只能表述为「相对开源专家模板基线的机器可判定任务成功率」，禁止表述为「超过人工专家」或「全面最佳」。
- **何时可恢复人工基线**：一旦有预算，按 `prereg` 的 `baseline` 段把 `human_blind_eval` 置 true、补 B1 盲写与评审池即可；门禁代码无需改动（只读预注册阈值）。
- **残余偏差**：B1-OSS 的模板较通用、可能弱于真人专家，因此「optimizing」标签的强度低于人工基线版本；这是显式接受的偏差，写进预注册而不是隐藏。
