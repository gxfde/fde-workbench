# Workflow 节点产物 → 门禁证据候选 v1（立项草案）

> 状态：**PROPOSED（2026-11-05 立项，待排期实施）**。来源：T-C1 轮遗留的「workflow 产物候选（待 schema 立项）」挂账；WB-DEF-8 的 workflow 腿。任务侧（T-G1）已随 `gate_service.attach_task_evidence_candidate`（gate_service.py:708，ca30aae）落地，本草案只裁决 workflow 节点产物这一侧的合同。上游：workflow-dag-v1 §4 草案标记 + 验收 12（claim_status=None，人工采纳后才 claimed/accepted——语义已随 T-G1 钉死，本草案不触碰）。
> 现状锚点（E0，2026-11-05 @ ca30aae）：`workflows/executor.py:724-725`（call/skill 节点成功写 `output_json`）、`:1192-1194`（agent 节点成功）；`gates.evidence_candidates` JSON 候选列 + `MAX_EVIDENCE_CANDIDATES` 上限 + `ensure_project_gates` 懒初始化（attach_task_evidence_candidate 既有行为）；T-E3 通道前缀校验**已预留 `workflow_node:`**。

## 1. 裁决 D1：标记位置 = 运行时保留键，不是定义层声明

节点 `output_json` 顶层保留键 `gate_evidence`，executor 在节点 succeeded 后读取并挂候选。本裁决正面回答 T-G1 实施记录（backlog T-G1 §实现偏差回写）的挂起问题——「`output_json` 是任意 JSON、无 source_uri + sha256 形状，强行当证据会踩红线」：**产物要成为候选，必须由生产方（API 响应 / skill / agent 产物）在保留键里自带指针+指纹；平台永不自动派生指纹**（对任意 payload 自动哈希并复制入库正是红线本身）。形状不齐 = 不是证据，跳过不发明。

- **否决「定义层声明 + JSON 路径抽取」**：表达力强但校验面/失败语义翻倍（路径取不到值算节点失败还是跳过？），且没有任何现实需求（首批 workflow 全是只读 call + skill；产物形状由被调 API/skill 决定，平台不应发明约束）。任务书原则：不为想象的需求加形状。
- 与任务侧对称：任务行自带 `evidence_uri + evidence_hash` 双字段齐备即登记（T-E3 同构）——节点产物自带标记即登记，双字段不齐 = 不构成指纹 = 跳过。
- 定义层/`validate_dag` 零改动：候选是运行时旁路，不进 DAG 合同。

## 2. D2：载荷合同与坏标记语义

```json
"gate_evidence": {"gate": "G5", "label": "验收报告", "source_uri": "…", "content_sha256": "<64hex>"}
```

| 键 | 校验 | 说明 |
|---|---|---|
| `gate` | ∈ {G1..G9} | 门禁键，与清单项文本无关（候选按门禁行挂） |
| `label` | ≤120 字符，可选 | 候选呈现文本（GateBoard 徽标旁）；缺省用节点 key |
| `source_uri` | ≤1024，仅指针 | 红线：证据原件永不进仓库/DB，只存指针 |
| `content_sha256` | 64 hex，归一小写 | 指纹；与 source_uri 构成证据指纹对 |

**坏标记不炸节点**：gate 非法 / sha 非 64hex / 超长 / 双字段缺一 → 节点照常 `succeeded`，登记跳过 + 事件 `gate_evidence_candidate_skipped`（details 点名坏键）。理由：候选是建议性旁路，不改变工作流语义（FV-F1 断链只看业务成败）；与 T-E3 桥侧「指纹不齐整跳过不炸」同构。

## 3. D3：写入路径与幂等

- **同事务**：executor 节点成功事务内（`node.status="succeeded"` + `output_json` 落表同一事务）调用 gate_service 新原语
  `attach_workflow_evidence_candidate(session, *, actor=run 发起人, project, run_id, node_key, gate_key, source_uri, content_hash, label) -> bool`
  ——事务回滚则节点成功与候选一并回滚，原子（executor §3「每步独立事务提交」锚点内完成，无需 T-S2 式微事务）。
- **dedup = (source_uri, content_hash, `wf:{run_id}:{node_key}`)**：同位同指纹唯一。
  - attempt 重试产出同指纹 → 幂等跳过（attempt 代际语义见 goal-c CR-019）；
  - 重试/恢复产出**不同**指纹 → 新候选并存（两代产物诚实呈现，由人工取舍）；
  - 上限沿 `MAX_EVIDENCE_CANDIDATES`（与任务候选共享同一列表与裁剪）。
- `captured_from = workflow_node:{run_id}:{node_key}`（T-E3 已预留前缀）；事件 `gate_evidence_candidate_attached`（沿任务侧，details 带 run/node 溯源）。

## 4. D4：红线

1. **工作流产物永不等于门禁通过**：候选只提示「可能可作为证据」，`claim_status` 恒 None；采纳唯一入口 = `submit_gate_evidence` 真人提交闸（命中指纹即剪除候选——T-G1 已实现，零改动）。
2. **只存指针 + 指纹**：`output_json` 里的大 payload 不复制进候选、更不进一等证据表。
3. **对 workflow-dag-v1 §4 草案的一处偏差（回写注记）**：v1 **只挂 `gates.evidence_candidates` 候选，不预写 `project_evidence` 一等表**——一等证据仍只在人工提交闸落库（「检索结果当业务事实」防线的同构延伸：工作流产物 ≠ 已采集证据），与 T-G1 任务侧行为一致。

## 5. D5：候选行 shape 与桌面呈现

候选 JSON 行（workflow 侧）：

```json
{"source_uri": "…", "content_hash": "…", "source_kind": "workflow",
 "workflow_run_id": "…", "workflow_node_key": "…", "label": "…",
 "proposed_by_user_id": "…", "proposed_at": "…"}
```

- `source_kind: "task" | "workflow"`；**旧行缺键读时缺省 `"task"`**（`_serialize_gate` 读时合并，沿 T-E2 evidence_id 先例）——任务侧行不回填。
- 桌面 GateBoard 候选组加来源徽标（任务/工作流）：**S，随实现另开桌面轮**；本轮零桌面改动。

## 6. D6：验收用例（映射 workflow-dag-v1 验收 12）

1. skill/call 节点 output 带 `gate_evidence` → 候选出现且 `claim_status=None`；
2. 同指纹重试/恢复 → 幂等不重复挂；
3. 换指纹 → 新候选并存（旧行不动）；
4. 坏 gate / 坏 sha / 双字段缺一 / 超长 → 跳过 + `gate_evidence_candidate_skipped`，节点仍 succeeded；
5. 无标记节点 → 零副作用；
6. 节点 failed/cancelled → 不登记（失败路径无 output）；
7. 采纳（submit 同指纹）→ 候选剪除（T-G1 既有行为回归钉）；
8. `source_kind` 读时缺省 task（旧候选行兼容）。

## 7. 实施范围与复杂度

- server：executor 两处成功点（call/skill :725、agent :1194）读标记 + 同事务挂候选；gate_service 新原语（≈40 行，复用 ensure_project_gates/上限/事件）；事件两枚（attached 沿用 / skipped 新增）。测试：test_workflow_executor 扩展 + 候选面扩展（+6~8 例）。**零 DDL / 零迁移 / 零路由**（改 server ⇒ rebuild 三镜像，alembic 幂等校验）。
- 桌面：GateBoard 来源徽标（S，另轮）。
- 复杂度 **M**；前置 T-G1 / T-W3 / T-W4（均已落地）。
