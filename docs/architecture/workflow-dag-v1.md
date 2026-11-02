# Workflow DAG v1 设计（P1）

> 状态：**PROPOSED → 部分 IMPLEMENTED**——§2 workflow_definitions + 版本行两表与 §2「dag_json schema」校验规则 1–8（9 为告警）已于 2026-11-02 实施（T-W1，迁移 `f2a4c6e8b1d3`；偏差见 backlog）；§3 执行器 / §5 路由 / runs 两表仍 PROPOSED（T-W2/T-W3）。现状证据：附录 C 11/13、F Q10——WB jobs 骨架 VERIFIED；fde-v2 flow.py 形态与缺陷 VERIFIED，附录 B 1-6。
> 核心决策（任务书"决策 3"）：**不复制队列**。workflow 是 background_jobs 的一个新 job_type（`workflow.run`），编排 handler 在一个 job 内驱动节点循环，复用 lease/token/续租/reconcile/failure-hook 全套机制。

## 1. 与现有体系的边界（决策 3 落实）

| 问题 | 裁决 |
|---|---|
| 为什么不能复制一套队列 | Redis list+outbox+lease+reconcile+心跳已稳定（F Q10 VERIFIED），第二套队列=双死锁面+双运维面 |
| automation_tasks 与 workflow_definitions 分不分 | **分**。automation_task 是"定时触发器"（schedule+prompt+capability，语义=让 DSH 干活）；workflow_definition 是"确定性编排"（节点图，语义=WB 自己按图执行）。二者正交：automation_task 可选指定 workflow_id（触发器→编排解耦，P2 接线） |
| automation_task_runs 与 workflow_runs 边界 | automation_task_runs 记"DSH 执行会话"（external_execution_id 回调驱动）；workflow_runs 记"节点级确定性执行"。互不替代，外键可互链（automation_task_run.workflow_run_id 可空，PROPOSED P2） |
| background_jobs 复用方式 | 新 handler：`workflow.run(target_id=workflow_run_id)`；RECOVERABLE_JOB_TYPES 增 `workflow.run`（**前提**：节点级幂等键落表，恢复时只重跑未完成节点） |
| 外副作用防重 | ①run 级 idempotency_key 唯一；②每个 effect=external 节点有自己的 node idempotency_key（复用 api_actions sha256 模式）；③节点成功即落 succeeded+output，恢复跳过；④workflow 取消=停未执行节点，不回收已执行外呼（诚实呈现） |

## 2. 表设计（PROPOSED；Alembic 新增）

### workflow_definitions
| 列 | 类型 | 说明 |
|---|---|---|
| id | UUID PK | |
| project_id | UUID FK projects.id NULL | NULL=平台模板（admin only），非 NULL=项目内 |
| name | VARCHAR(120) NOT NULL | |
| description | TEXT | |
| dag_json | JSONB NOT NULL | 见 §3 schema |
| status | VARCHAR(16) CHECK in (draft, published, archived) | published 锁版（沿用 industry_template publish 语义） |
| version | INTEGER NOT NULL DEFAULT 1 | 发布递增，行级唯一 (id, version) 由版本表承接（见下） |
| content_sha256 | CHAR(64) | dag_json 规范化指纹 |
| created_by / published_by / published_at / timestamps | | |

版本化采用 WB 已验证的"定义+版本行"双表（skill_definitions/skill_versions 同构，附录 C 9）：`workflow_definition_versions(id, definition_id, version, dag_json, content_sha256, published_by, published_at)`，**版本行不可变**。

### workflow_runs
| 列 | 类型 | 说明 |
|---|---|---|
| id | UUID PK | |
| definition_id FK / definition_version | INTEGER NOT NULL | **运行固定版本**（fde-v2 教训：跑动中被改即受影响） |
| project_id | UUID FK projects.id NOT NULL | |
| status | VARCHAR(20) CHECK in (queued, running, waiting_approval, paused, succeeded, failed, cancelled) | |
| initiated_by_user_id | FK users.id | |
| idempotency_key | VARCHAR(120) UNIQUE NOT NULL | |
| context_json | JSONB | 运行级入参（占位符源） |
| error / started_at / finished_at / timestamps | | |

### workflow_node_runs
| 列 | 类型 | 说明 |
|---|---|---|
| id | UUID PK | |
| run_id | UUID FK workflow_runs.id CASCADE | |
| node_key | VARCHAR(60) NOT NULL | |
| node_type | VARCHAR(20) CHECK in (call, skill, agent, human_approval) | **没有 condition/wait 节点**——when 表达式与 depends_on 已覆盖既有需求（fde-v2 同款），新节点类型待真实需求（任务书原则） |
| status | VARCHAR(20) CHECK in (pending, ready, running, waiting, succeeded, failed, skipped, cancelled) | |
| attempt | INTEGER DEFAULT 0 | |
| depends_on | JSON | 冗余快照（定义可追溯） |
| idempotency_key | VARCHAR(120) | UNIQUE(run_id, node_key) 之外的业务幂等（外副作用节点必填） |
| input_snapshot | JSONB | 占位符填充后的实际输入 |
| output_json | JSONB | 成功产物（下游引用源） |
| error / started_at / finished_at | | |
| 约束 | UNIQUE(run_id, node_key)；INDEX(run_id, status) | |

### dag_json schema（定义校验纯函数，PROPOSED）
```json
{
  "nodes": [
    {"key": "gather", "type": "call", "ref": "research_subjects.list",
     "depends_on": [], "when": null, "output": "subjects",
     "max_retries": 0, "params": {"project_id": "{{project_id}}"}},
    {"key": "draft", "type": "skill", "ref": "workbench-help@3",
     "depends_on": ["gather"], "output": "hint"},
    {"key": "classify", "type": "agent", "ref": "agent_uuid",
     "depends_on": ["gather"], "max_cost_units": 2},
    {"key": "approve", "type": "human_approval",
     "depends_on": ["classify"], "capability": "workbench.write",
     "expires_minutes": 15}
  ]
}
```
校验规则（`definition_service.validate_dag`，全部可单测）：
1. key 唯一、非空；2. depends_on 引用存在（**环检测=Kahn 拓扑排序，环→422**，修 fde-v2 FV-F1）；3. type ∈ 四类；4. call.ref 必须 ∈ api_catalog ENTRIES（白名单，封 SSRF 面）；5. skill.ref 必须是 published 版本（显式版本号）；6. agent.ref 必须存在且可用；7. output 名不重复；8. {{placeholder}} 引用的 output 必须在上游声明；9. effect=external 的 call 节点必须含 human_approval 后继或自身挂审批（规则引擎式校验，P1 可先告警 P2 强制）。

## 3. 执行器（PROPOSED，server/src/fde_api/workflows/executor.py）

```
run_workflow(run_id):                      # 注册为 jobs handler "workflow.run"
  while True:
    node = 下一个 ready 节点（依赖全 succeeded 且 when 通过；无 ready：
        若存在未终态节点 → waiting 分支等待（approval/paused）返回
        否则 全 succeeded/failed 终结 → run 终态；有 failed 且无 when 绕过 → run failed（**不静默 done**，修 FV-F1））
    标 running，填 input_snapshot（占位符替换；缺键→failed+error，不填空串，修 fde-v2 call 节点缺陷）
    分派：
      call   → mcp_gateway.call_tool("api_execute", …同一鉴权/确认闸)   # 绝不旁路
      skill  → mcp_gateway.skill 语义（published 固定版本）
      agent  → agents.start_run（同全部闸：预算/pilot/T1/T6/沙箱/上下文脱敏）
      human_approval → 建 automation_approvals（复用 run+request_key/15min/sha256/一次性），node=waiting
    失败：attempt<max_retries → 指数退避重试（复用 jobs 重试策略，域 14）；否则节点 failed
    每步独立事务提交（节点产物先落表再前进——崩溃恢复的锚点）
  取消：POST cancel → run=cancelled，未启动节点=cancelled，running 节点由 token 守卫自然收敛
```

权限（每节点实时校验，非 run 级冻结）：call→发起人 capability∩project scope（api_execute 同闸）；agent→start_run 同闸；审批人→automation_approvals 同闸。**工作流无法绕过任何既有闸**（任务书决策 4/5 落实；对照 fde-v2 flow 绕 HITL 的 FV-F2，此为设计红线）。

## 4. 与 G1–G9 的关系（决策 4 落实）

- Workflow 只产**证据候选**：call/agent 节点 output 可标记 `gate_evidence: {gate: "G5", label: "…", source_uri, content_sha256}` → executor 写 project_evidence（域 3）+ gates.evidence_checklist 候选项（claim_status=None）。
- gate_service 仍是唯一状态机；decide 五道闸不感知 workflow；**Agent/工作流输出永不等于门禁通过**（现状 submit 唯一入口=真人会话，保持，F Q4 VERIFIED）。
- human_approval 节点 ≠ 门禁拍板：它批准的是工具执行，不是 G 状态。

## 5. API（PROPOSED）

| Method/Path | 权限 | 说明 |
|---|---|---|
| POST /api/v1/projects/{id}/workflows | can_manage | 建定义（draft） |
| POST …/workflows/{wid}/publish | admin | 发布新版本（锁版） |
| POST …/workflows/{wid}/runs | can_manage | {context, idempotency_key?} → 422 dag_invalid（含环/未知引用明细） |
| GET …/workflow-runs/{rid} | can_view | run+节点态树 |
| POST …/workflow-runs/{rid}/cancel | can_manage | 幂等 |
| GET /api/v1/workflows（平台模板） | admin | |

错误码：422 dag_invalid / 409 idempotency_conflict / 409 already_terminal / 403 permission_revoked（节点执行时）。

## 6. 验收测试（server/tests/test_workflow_definition.py、test_workflow_executor.py，PROPOSED）

1. 环 DAG → 422 且指明环节点；2. depends_on/ref 未知 → 422；3. call.ref 不在 catalog → 422（白名单生效）；4. 节点失败重试 n 次→paused→resume 只跑剩余节点（已完成节点 output 复用，断言不重复执行）；5. 幂等键：同 key 二次 run → 409 或返回同一 run；6. 效果幂等：外副作用节点崩溃后恢复不二次执行（断言 node 幂等键）；7. definition_version 固定：发布 v2 后旧 run 仍按 v1 定义展示与恢复；8. 取消：未启动节点 cancelled、已成功节点保留；9. 权限撤销：run 中途撤销 capability → 后续 call 节点 403 permission_revoked；10. 审批过期：waiting 节点 15min 后 failed（复用审批语义）；11. 断链不静默 done（修 FV-F1 的回归用例）；12. workflow 产物→gate 证据候选：claim_status 仍为 None，人工采纳后才 claimed/accepted。

## 7. 实施任务与复杂度

T-W1 定义表+版本表+校验器（M，纯函数可先行入 CI）；T-W2 runs/node_runs 表+迁移（M）；T-W3 executor call/skill 节点（M）；T-W4 agent 节点+human_approval（M）；T-W5 cancel/resume+reconcile 接入（M）；T-W6 桌面控制台（S）。首批范围：只读 call + skill 节点（T-W3 完成即有业务价值：如"汇总门禁→生成周报草稿→skill 润色"）。
