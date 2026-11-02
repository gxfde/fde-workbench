# V3 测试与安全验收计划

> 覆盖任务书第十节全部四族测试要求。分两层：①**基线层**（既有套件，实跑记录见 docs/audit/v3-test-inventory.md）；②**新增层**（随 V3 各任务交付，PROPOSED，文件名与用例均已指定于 backlog）。
> 纪律：新用例与实现同一 PR；变异校验法沿用 d11 方法论（old 串带函数锚定、红判定 selftest）；本地全量 pytest 必设 FDE_TEST_DATABASE_URL。

## 0. 基线层（既有，先跑绿再动工）

| 套件 | 命令 | 本轮实跑结果 |
|---|---|---|
| 服务端 pytest | npm run test:server | 见 v3-test-inventory.md §实跑 |
| 桌面端 vitest | npm run test:desktop | 730/730 passed（60 文件，exit 0，2026-11-02 实跑） |
| 运维脚本 | npm run test:operations | 见同上 |
| fde-v2 verify 套件 | **不执行**（不受信外部快照，零执行纪律；结构审计已覆盖） | N/A（UNKNOWN 是否全绿，已如实记录） |

## 1. 本体族（test_ontology_registry.py + test_evidence_registry.py，随 T-E*/T-O*）

| # | 用例 | 断言要点 |
|---|---|---|
| O-1 | 候选不自动成为发布本体 | AI 产 change_set（captured_from=agent_run）→ confirm 前 ontology_terms 无新行；terms.status 只能经 confirm 变 confirmed |
| O-2 | 跨项目读写拒绝 | 用户 B 对项目 A：GET/POST terms、change-sets、evidence → 404（project_access 掩护）或 403；服务层单测直接断言异常 |
| O-3 | 发布版本不可原地修改 | PATCH confirmed term definition → 409 immutable；变更须走 change_set（supersede 语义） |
| O-4 | 术语合并保留来源 | merge 后被并行 status=merged+canonical 指向、aliases 写入、operation_events 逐项留痕、后续查询按 canonical 展开 |
| O-5 | 证据删除/替换不改历史引用 | gate 证据二次提交（不同 sha256）→ 新 evidence 行 + 旧指针留存于 operation_events.changes；gates 已决行不变 |
| O-6 | 变更影响分析 | impact_of_term(term) 返回引用它的 subjects/links/forms（T-I1） |
| O-7 | relation_type 注册 | 新 link_type 建边成功；retired 后新边 409、存量边只读 |
| O-8 | 导入去重 | 同名不同 key 导入 → 产出 merge 候选 change_set，不静默新建（T-O4） |

## 2. Workflow 族（test_workflow_definition.py + test_workflow_executor.py，随 T-W*）

| # | 用例 | 断言要点 |
|---|---|---|
| W-1 | DAG 环检测 | A→B→A 定义 → 422 且错误体指明环节点链 |
| W-2 | 未知节点/依赖/操作拒绝 | depends_on 指空、type 非四类、call.ref 不在 api_catalog、skill.ref 非 published → 422 |
| W-3 | 非法 I/O schema 拒绝 | 占位符引用未声明 output；skill input_schema 校验失败 → 422 |
| W-4 | 节点失败重试/暂停/恢复/取消 | 失败节点按 max_retries 退避；run paused；resume 只跑未完成节点（已完成节点 output 复用，计数器断言不重复执行）；cancel → 未启动节点 cancelled |
| W-5 | 幂等键阻止重复副作用 | 同 run idempotency_key 二次 → 409/返回同 run；外副作用节点崩溃恢复不二次执行（node idempotency_key 断言） |
| W-6 | 已完成节点不重复执行 | 恢复后 succeeded 节点 attempt 不变、output 原样 |
| W-7 | 运行固定版本 | 定义发布 v2 后，v1 run 的展示与恢复仍按 v1 dag_json |
| W-8 | 断链不静默 done | 存在 failed 且无 when 豁免 → run failed（fde-v2 FV-F1 回归锚） |
| W-9 | 权限撤销即时生效 | run 进行中撤销 capability → 后续 call 节点 403 permission_revoked |
| W-10 | workflow→gate 证据候选 | 产物只产生 claim_status=None 候选；采纳走人工闸 |

## 3. 权限与安全族（扩展既有 test_permissions/test_control_plane_api/test_ai_server_chat_mcp 等）

| # | 用例 | 断言要点 | 状态 |
|---|---|---|---|
| S-1 | 无权用户跨项目访问 | 既有 project_access 用例 + 新表（evidence/ontology/workflow）同口径 | 既有+新增 |
| S-2 | 提示注入不授予额外权限 | 恶意文档（file_read 返回带指令）→ 模型请求越权工具 → 403（权限闸在 call_tool，不依赖模型顺从）；context sanitization 既有用例回归 | 既有+新增 |
| S-3 | 未授权工具不进工具列表 | token claims ∩ 实时档位既有用例；新 effect/risk 元数据目录扫描断言 | 既有+T-R2 |
| S-4 | 运行中撤销 | test_ai_server_chat_mcp:166/197 回归 + W-9 | 既有+新增 |
| S-5 | 过期/异目标审批不复用 | 既有 sha256+15min+一次性用例回归；新：同 run 不同 arguments_sha256 → 新审批必须新建；过期审批 execute → 409 | 既有+新增 |
| S-6 | 文件内容不覆盖系统策略 | file_read 返回 source=untrusted 回归；mcp_gateway 模块红线注释存在性断言（漂移告警） | 既有 |
| S-7 | 日志/审计不泄密 | 既有 credential_limits/redaction 用例回归；新：ai_call_audits/operation_events 序列化断言无密钥模式（复用 context.py 遮蔽正则做扫描器） | 既有+新增 |
| S-8 | skill 发布越权 | 非 admin publish/rollback → 403（fde-v2 R1 教训显式负向用例） | T-S1 |
| S-9 | tool_group 只收窄 | group 引用后工具面 ⊆ 无引用基线；组含未授权工具时被交集裁掉 | T-R1 |

## 4. 门禁与交付物族（扩展 test_gates_api/test_document_snapshots/test_migrations 等）

| # | 用例 | 断言要点 |
|---|---|---|
| D-1 | Agent 文字不能改 G1–G9 | api_catalog 无 gates 写条目断言（grep 级测试既有）+ call_tool("api_execute", gates 路径) → 400 not_in_catalog |
| D-2 | 自动检查与人工批准分开记录 | 证据候选（suggested_by）与人工 accepted 分字段；decide 五道闸回归（拍板人≠执行人/G8G9 admin/conditional 仅 G9） |
| D-3 | 文档生成保存输入快照与版本 | 既有 snapshots 用例回归 + T-D1：版本行可反查 ai_call_audits.request_id 与 research revision_id |
| D-4 | 重新生成不覆盖历史 | 既有 idempotent/frozen 用例回归（sha256 短路、新 version_number） |
| D-5 | 迁移升级与回滚 | test_migrations 扩展：新四族表（evidence/ontology×3/workflow×3/skill 扩列）upgrade→downgrade→upgrade 全绿 |

## 5. 执行与准入门禁

1. 每个 V3 任务合并前：本任务新用例 + 所属族全量 + 全量 pytest/vitest 绿（不并行变异测试——no-parallel-mutation 纪律）。
2. 发布闸依赖（T-S1）上 CI：`test_report_json or waive` 的服务端断言用例必须先于任何 published skill 存在。
3. mypy/门禁每改必跑（verify-before-trust 记忆）；桌面改动走 fde-package-verify。
4. 完成定义（任务书停止条件对齐）：17 域差距全部有结论（本文档体系已达成）+ P0/P1 任务落地后 §1-§5 对应用例全绿 + 审计报告未验证项清单收敛或显式转 P3。
