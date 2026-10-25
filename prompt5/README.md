# prompt5 — 自适应提示词生成器

> 唯一搭建依据：《提示词生成器系统-搭建执行方案.md》（见仓库根目录 [`docs/`](../docs/)）。
> 本仓库当前进度：**M3 完成**（评测引擎：EvalCase + 交换双裁 + Wilcoxon/McNemar/TOST + 含 CI 报告 + blob 上传）。
> 项目总览与产出索引见仓库根目录 [`README.md`](../README.md)。

## 环境

| 项 | 值 |
|---|---|
| Python | 3.13（`.venv` 内解释器由系统 Python 3.13.12 创建） |
| 虚拟环境 | `prompt5/.venv`（必须激活或用 `.venv/Scripts/python` 显式调用） |
| 已装依赖 | pytest 9.1.1 · pydantic 2.14.1 · fastapi 0.162.0 · uvicorn 0.54.0 · httpx 0.28.1 · PyYAML |
| 包安装 | `pip install -e . --no-deps`（editable，`python -m prompt5` 免 PYTHONPATH） |

> **网络注意（本机）**：本机唯一出口是会话注入的 `HTTPS_PROXY=http://127.0.0.1:1441`。
> 装包时**不要** `unset` 代理，否则 pip 会报 `from versions: none`。见 `NOTES.md #3`。

## 常用命令

```bash
cd prompt5
.venv/Scripts/python -m pytest tests -q                          # 全量测试（179 项）
.venv/Scripts/python -m pytest tests/test_applier_property.py -q # M1 DoD：339 属性用例
.venv/Scripts/python -m prompt5.export_schema                    # M1 DoD：导出 4 份 Schema 并校验
.venv/Scripts/python -m prompt5.cli demo-zero --task "把这份 CSV 做成分析报告"   # M2 DoD：端到端
.venv/Scripts/python -m prompt5.cli pilot --quiet                                # M3 DoD：pilot 报告（离线模拟）
.venv/Scripts/python -m prompt5.cli demo-zero --task "..." --json              # 输出完整 IR
.venv/Scripts/python -m prompt5.api --dry                        # 打印 capabilities
.venv/Scripts/python -m prompt5.api --serve --port 8765          # FastAPI 服务
```

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
│   └── m5_eval/      l1_rules / l2_judge（交换双裁）/ l3_exec（执行+机器判定）
│                     evalcase（单元与聚合）/ stats（Wilcoxon/McNemar/bootstrap/TOST）
│                     cache（键隔离）/ runner（流程+报告）
├── blobs.py          材料上传（服务端算哈希/白名单/配额/TTL/租户隔离）
├── engine/           flow_zero（流程 A 编排）+ pilot（M3 评测编排）
├── store/            schema.sql（14 表）+ 迁移（PRAGMA user_version）
└── api/              --dry / --serve（FastAPI；缺失时 stdlib 兜底）
specs/                 JSON Schema 导出产物（M1）
benchmarks/            金标任务与基线（M7）
```

## 里程碑状态

M0 ✅ → M1 ✅ → M2 ✅ → M3 ✅ → M4（迭代：种子反解 + 补丁链 + 回归保护 + 意图门禁）待开工。
