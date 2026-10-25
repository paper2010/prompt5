# prompt5 — 自适应提示词生成器系统

面向文本 / 系统提示词的「生成—迭代—评测」系统：把用户意图解析为结构化 IR，经多策略生成、三级评估、逐模型渲染，产出各目标模型上的最优提示词；支持会话内动态改进与外部 Agent 连接器接入。

> **一句话目标（D-0）**：以各目标模型的**实际任务产出**为主验收；提示词文本质量仅为辅助指标。「最佳」= 固定模型版本 + 任务集 + 环境 + 预算下的统计验收结果。

---

## 仓库结构

```
.
├── README.md                 ← 本文件（项目总览 + 进度 + 产出位置）
├── .gitignore
├── docs/                     ← 设计文档与过程记录
│   ├── 提示词生成器原理解析.html
│   ├── 自适应提示词生成器系统设计方案.html          （v0.1 初稿）
│   ├── 自适应提示词生成器系统设计方案-v0.2.html
│   ├── 自适应提示词生成器系统设计方案-v0.3.html
│   ├── 自适应提示词生成器系统设计方案-v0.4.html
│   ├── 自适应提示词生成器系统设计方案-v0.5.html
│   ├── 自适应提示词生成器系统设计方案-v1.0-合并版.html  ← 设计定稿
│   ├── 外部Agent连接器接口规范-v1.0.html
│   ├── 提示词生成器系统-搭建执行方案.md              ← 唯一搭建依据（BUILD PLAN v1.0）
│   └── DeepSeek-V4.1-Flash-搭建执行提示词.md         ← 执行 AI 系统提示词
└── prompt5/                  ← 源码与工程产出（Python 包）
    ├── README.md             ← 环境 / 命令 / 模块说明
    ├── NOTES.md              ← 未覆盖场景与降级台账（工程过程记录）
    ├── pyproject.toml
    ├── config.example.yaml   ← 配置样例（密钥只走环境变量）
    ├── src/prompt5/          ← 实现（40 个 Python 文件）
    ├── tests/                ← 测试（14 个文件，266 项全绿）
    ├── specs/                ← 导出的 4 份 JSON Schema（M1 产出）
    ├── benchmarks/           ← 金标任务集（M3 pilot / M7）
    ├── reports/              ← 里程碑报告
    └── data/                 ← 运行时材料（blob 上传，不入库）
```

---

## 已完成进度

| 里程碑 | 状态 | 内容 | 验收 |
|---|---|---|---|
| **M0** | ✅ | 基础设施：RFC 8785 JCS、ULID、SQLite 14 表 + 迁移、配置加载、9 能力/18 MCP 工具/32 错误码、API `--dry`/`--serve` | `--dry` 打印 capabilities；HTTP 200 |
| **M1** | ✅ | IR v3 + Patch 契约 + 两阶段应用器 + 版本台账（CAS/墓碑/审计哈希链）+ 4 份 JSON Schema | 属性测试 339 例全绿；Schema Draft2020-12 合法 |
| **M2** | ✅ | 从零生成闭环：意图抽取（M1）→ 骨架策略生成（M4）→ 模型卡渲染（M3）→ L1 规则评估；Mock LLM 端到端 | `demo-zero` EXIT=0，IR checksum 通过 |
| **M3** | ✅ | 评测引擎：EvalCase、L2 交换双裁、L3 执行判定、Wilcoxon/McNemar/TOST/bootstrap、评测缓存隔离、blob 上传、pilot 报告 | 266 项测试全绿；`pilot` 产出含 CI 报告 |
| **M4** | ⏳ 待开工 | 种子反解 + 补丁链 + 回归保护 + Overlay 重基 + 意图门禁 | — |
| **M5–M7** | ⏳ | 会话改进 / 连接器 TCK / 金标基准与验收 | — |

**当前代码规模**：`src` + `tests` 约 6100+ 行 Python；测试 **266 passed / 30 subtests**（含 hypothesis 属性用例）。

---

## 产出位置速查

| 产出 | 路径 |
|---|---|
| 系统设计方案（定稿） | [`docs/自适应提示词生成器系统设计方案-v1.0-合并版.html`](docs/自适应提示词生成器系统设计方案-v1.0-合并版.html) |
| 搭建执行方案（唯一搭建依据） | [`docs/提示词生成器系统-搭建执行方案.md`](docs/提示词生成器系统-搭建执行方案.md) |
| 外部 Agent 连接器接口规范 | [`docs/外部Agent连接器接口规范-v1.0.html`](docs/外部Agent连接器接口规范-v1.0.html) |
| 源码 | [`prompt5/src/prompt5/`](prompt5/src/prompt5/) |
| 测试 | [`prompt5/tests/`](prompt5/tests/) |
| JSON Schema（IR v3 / Patch v3 / TaskRequest v1 / EvalEvidence v1） | [`prompt5/specs/`](prompt5/specs/) |
| M3 pilot 评测报告 | [`prompt5/reports/m3-pilot.md`](prompt5/reports/m3-pilot.md) |
| 金标任务集 | [`prompt5/benchmarks/tasks.jsonl`](prompt5/benchmarks/tasks.jsonl) |
| 工程过程台账（降级 / 决策 / 缺陷修复） | [`prompt5/NOTES.md`](prompt5/NOTES.md) |
| 配置样例（密钥只走环境变量） | [`prompt5/config.example.yaml`](prompt5/config.example.yaml) |

---

## 快速开始

```bash
cd prompt5
python -m venv .venv
.venv/Scripts/python -m pip install -i https://mirrors.aliyun.com/pypi/simple/ \
    pytest pydantic fastapi uvicorn httpx PyYAML hypothesis
.venv/Scripts/python -m pip install -e . --no-deps

# 全量测试
.venv/Scripts/python -m pytest tests -q

# 端到端演示（从零生成）
.venv/Scripts/python -m prompt5.cli demo-zero --task "把这份 CSV 做成分析报告"

# M3 pilot 评测（离线模拟执行器）
.venv/Scripts/python -m prompt5.cli pilot --quiet

# API
.venv/Scripts/python -m prompt5.api --dry
.venv/Scripts/python -m prompt5.api --serve --port 8765
```

更完整的模块说明与命令清单见 [`prompt5/README.md`](prompt5/README.md)。

---

## 设计要点（速览）

1. **IR 单一事实源**：`slots` + `item_ids` 稳定 ID 映射 + checksum（先校验后规范化计算）。
2. **两阶段应用器**：纯函数执行、零部分应用；唯一写者是 `applier.py`，禁止绕过直接写库。
3. **版本台账**：CAS（version/checksum 双校验）、墓碑、审计哈希链（篡改可检出）。
4. **三级评估**：L1 规则 → L2 交换双裁（裁判 ≠ 被测族）→ L3 实际执行 + 机器判定。
5. **统计验收纪律**：Wilcoxon / McNemar / TOST / bootstrap CI；功效不足时不得宣称有效。
6. **fail-closed**：LLM 供应商故障不静默换模型；评测缓存按 `model_snapshot` / 环境分量 / 裁判隔离。
7. **保护字段递归扫描**：`protect_class / provenance / created / meta` 任意深度拒绝写入。

---

## 已知边界与待办

- **真实模型端点未接入**：`GLM_URL / DSK_URL / QWEN_URL` + 对应 `*_KEY` 尚未提供；M3 pilot 使用**模拟执行器（scripted）**，报告已标注「不构成效果证据」。
- **单进程边界**：SQLite + 线程模型仅适用于单 worker；多 worker 前必须切换 PostgreSQL（`NOTES.md #5`）。
- **M4 起**：种子反解、补丁链、回归保护、意图门禁尚未开工。
- **L3 权重蒸馏冻结**：法务评估前不实现（方案 §14 D-14）。

---

## 文档阅读顺序建议

1. [`docs/提示词生成器原理解析.html`](docs/提示词生成器原理解析.html) — 为什么这样设计  
2. [`docs/自适应提示词生成器系统设计方案-v1.0-合并版.html`](docs/自适应提示词生成器系统设计方案-v1.0-合并版.html) — 系统设计定稿  
3. [`docs/提示词生成器系统-搭建执行方案.md`](docs/提示词生成器系统-搭建执行方案.md) — 如何搭建（里程碑 / DoD / 硬约束）  
4. [`prompt5/NOTES.md`](prompt5/NOTES.md) — 实现中踩过的坑与决策  

---

## 许可

未指定开源许可。若需公开发布，请先确认文档与代码的归属与授权范围。
