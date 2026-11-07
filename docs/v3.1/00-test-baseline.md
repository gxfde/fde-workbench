# V3.1 测试基线（00-test-baseline）

- 基线：fork/main `65db88c`；执行环境见 §1；全部命令在隔离 worktree `D:/test/fde-wt-v31p0` 干净树执行（`.env` 从主树拷入、node_modules/.venv 经 junction 复用，不入库）
- 执行日期：2026-11-07

## 1. 环境

| 项 | 值 |
|---|---|
| OS | Windows 11 10.0.26300（Git Bash） |
| Python | 3.13.14（server/.venv，`pip install -e .[test,dev]` 体系） |
| Node | v24.14.1 |
| 测试 DB | 共享本地 Postgres（root `.env` FDE_DB_PASSWORD@15432 体系，advisory lock 串行化并发会话） |
| 桌面 | Electron·Vite·React，vitest + jsdom |

## 2. 命令与结果（按 AGENTS.md 真实命令）

| 命令 | 结果 |
|---|---|
| `node scripts/run-server-tests.mjs`（= server/.venv python -m pytest，PYTHONPATH=src） | **2136 收集 = 2130 passed + 6 skipped**，0 failed 0 error，耗时 1960.40s（0:32:40），EXIT=0 |
| `npm --workspace desktop test`（vitest） | **932/932 passed（78 文件），0 失败 0 跳过**，耗时 478.79s，EXIT=0 |
| `npm run typecheck`（tsc node+web 双工程） | EXIT=0 零错误 |
| `server/.venv/Scripts/python.exe scripts/check-python-types.py`（mypy 官方闸） | `OK: no new type errors (baseline 279 occurrences / 104 distinct, current 279)`，EXIT=0 |

本地全量实测与 fork/main `65db88c` CI 实测（goal-tb 收口轮：2130+6s / 932）**逐位一致**（CI 对账见 §4）。

## 3. 测试资产盘点

- 服务端测试文件 **209** 个（`server/tests/test_*.py`），含 conftest 迁移夹具（外来戳自愈+CR-002 回滚纪律）。
- 桌面测试 78 文件 932 例。
- 与 V3.1 各阶段直接相关的既有钉子（P0 各阶段实施时的回归面）：
  - **P0-1**：test_transcript_drafts、test_guidance_ai_schema、test_guidance_confirm_review_gate、test_guidance_redaction_worker、test_meetings_service/orchestration
  - **P0-2**：test_ontology_*（change-set 竞态钉 test_change_set_transition_races_serialize_on_row_lock、impact 三面）
  - **P0-3/P0-4**：test_delivery_compiler、test_workflow_executor（+adversarial 对抗钉）、test_workflow_lifecycle、test_catalog_effect_risk_invariants
  - **P1-1**：test_zcode_contract（fixture 回放+适配器监听环集成）、test_receipt_dsl、test_agent_service*（sandbox/预算/signoff 族）
  - **P1-2**：test_gate_*（候选/漂移/CAS）、test_execution_fact_chain、test_storage_contract
  - **横切**：test_route_inventory_sync（路由清单↔url_map 逐行对账）、test_architecture_purity（workflows 内核纯度）、test_prompt_entrypoint_gate/test_prompt_hygiene_jseries（提示词卫生）、test_state_ownership_reconciliation（状态归属对账六钉）

## 4. CI 口径对账

fork/main `65db88c` 对应 goal-tb 收口轮 CI 实测：pytest **2136 收集=2130 passed+6 skipped**、vitest **932**、路由 323、表 109、39 rev——与本轮本地现测（§2 + data-model-map §口）逐位一致。V3.1 各阶段实施后按「口径四层记账」纪律同步推进（AGENTS 口径行/CHANGELOG/AGENTS bullet/审计 CSV）。

## 5. 测试纪律（任务书 §13 逐条对齐现状）

- 新增服务端逻辑必有测试、新路由必有权限测试、迁移必有升级/兼容测试——既有 CI 4 job（desktop/server-tests/secrets-scan/pseudonymization）+ 本节钉子体系承接。
- CI 跑 Ubuntu：Windows-only 路径（schtasks/wsl/盘符）必须可注入/mock（既有纪律）。
- 变异验证纪律：apply→红→restore→绿（AGENTS 工作流惯例），P0 各阶段新增断言沿用。
- 未解释 skip 禁止；现有 6 skipped 为既知基线（fixtures/skip 台账在案）。
