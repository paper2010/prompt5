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
