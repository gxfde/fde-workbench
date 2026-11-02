# V3 风险登记册

- 来源：① Workbench 自身审计发现（WB-DEF-*，证据=附录 C/D/F）；② fde-v2 审计发现（FV-*，仅作借鉴/避免重蹈，**不构成 Workbench 现网风险**）；③ V3 方案实施风险（V3-*，PROPOSED）。
- 严重度：高/中/低。处置状态：待办（进 backlog）/已记录/不适用。

## A. Workbench 现状缺陷（VERIFIED）

| 编号 | 严重度 | 风险 | 证据 | 缓解/处置 | 状态 |
|---|---|---|---|---|---|
| WB-DEF-1 | 高 | signoff 死锁：agent_assisted 方案经 generate-agent 正常 completed（无 handoff）时无 pending checkpoint，signoff 与 export-sow 双 409，SOW 永久导不出 | agents/service.py:907-916 唯一创建点；test_solution_signoff.py:35-42 用直插库绕过 | T-P0-1：_finalize 成功路径补建 checkpoint（或 export 前兜底）+ 端到端测试 | 待办（P0） |
| WB-DEF-2 | 中 | signoff 拍板权=AI 访问档位而非项目角色（项目侧仅 can_view）：viewer 成员持高 AI 档可拍板方案终审 | solutions/service.py:319-400 | T-P1-4：can_manage + 档位双闸 | 待办 |
| WB-DEF-3 | 低 | 过期审批懒翻转，无后台清扫（无越权窗口，run 已停等且 execute 拒） | control/service.py:708/770 | T-P1-5：scheduler 每轮清扫 | 待办 |
| WB-DEF-4 | 中 | DSH 降级直连 chat 用量只进 metrics_json 不落 ai_call_audits → 月度 token 预算失真 | 附录 C R4 | T-OBS1：统一走 auditing.record | 待办 |
| WB-DEF-5 | 低 | gates.template_hash 存量（f52afe88…）与现行 gates.json（180c4809…）漂移，无比对呈现 | 附录 F 风险 2 | T-G2：门禁序列化时比对并在响应中标注 outdated_template | 待办 |
| WB-DEF-6 | 中 | ai_call_audits.request_id 不落 project_document_versions → 文档血缘断链 | ai_content.py:98 | T-D1 | 待办 |
| WB-DEF-7 | 低 | 文档快照 confirmed_research_values 不存 revision_id | snapshots.py:78-117 | T-D1 | 待办 |
| WB-DEF-8 | 低 | 任务级证据（ProjectTask.gate/evidence_uri）与门禁清单双口径脱钩 | 附录 F 风险 5 | T-G1：任务完成→证据候选 | 待办 |
| WB-DEF-9 | 低 | outbox_events 无 completed/failed 写入点，状态不闭环 | outbox.py:77-81 | T-J1 | 待办 |
| WB-DEF-10 | 低 | api_catalog 未给 export_sow/documents.generate 标 confirmation：AI 可无确认排队文档生成（触发 worker 内模型调用） | api_catalog.py:57,61,123-126 | T-R2：结构化 effect/confirmation 元数据 | 待办 |
| WB-DEF-11 | 低 | 预算审计设施故障 fail-open（显式取舍） | 附录 C R7 | 维持（记录）；文档化 | 已记录 |
| WB-DEF-12 | 低 | run 工具面发起时刻冻结，运行中撤销不重算（run 内只读+断网沙箱，窗口有限） | agents/tools.py:28-29 | 维持（记录）；P3 评估运行中复查 | 已记录 |
| WB-DEF-13 | 低 | sandbox iptables 真实生效性未实测（argv 层已 CI 断言） | sandbox.py 注释 | 试点联调项（既有台账） | 已记录 |
| WB-DEF-14 | 低 | 提示注入防护=标记+纪律+确认流（无指令隔离编码），危害上限=授权内误操作 | 附录 C R2 | 维持；V3 在 workflow agent 节点沿用 context sanitization | 已记录 |

## B. fde-v2 审计发现（对 Workbench 仅作教训借鉴；FV-* 不适用于 WB 现网）

| 编号 | fde-v2 严重度 | 发现 | 对 V3 的借鉴 |
|---|---|---|---|
| FV-R1 | 高 | 管理守卫返回值被丢弃（agent_admin.py:187-218），任意登录用户可审批 skill | V3 的 skill 发布/回滚端点必须走 WB 既有 require_role+密码确认统一收口；测试断言非 admin 403 |
| FV-R2 | 高 | integration endpoints 任意 URL + test 回显 = SSRF 面 | WB 不新增"用户可配任意 URL 的外呼"类工具；workflow call 节点仅指向 api_catalog 白名单 |
| FV-R3 | 中 | run_as_user 伪造审计身份 | WB 全链 actor=g.current_user/签名 token，不提供身份参数（保持） |
| FV-R4 | 中 | 无 CSRF | WB 桌面端+Bearer token 模型天然免疫（保持） |
| FV-R5/R6/R7/R8 | 中 | admin/admin 复活、密钥入镜像、明文降级、root 容器 | WB 已达标项（保持，作为回归检查清单） |
| FV-F1 | 高 | flow 环依赖静默"done" | workflow 验证器必须显式环检测且断链=error 而非 done（T-W2 测试项） |
| FV-F2 | 高 | flow/scheduler 路径绕过 HITL（bridge.execute 无 dangerous 判定） | workflow call 节点执行=api_execute 同闸；effect=external 一律确认/审批（域 9） |
| FV-F3 | 高 | flow 无幂等（重跑重复建单） | workflow_runs.idempotency_key 唯一 + 节点级幂等键（域 5） |
| FV-S1 | 中 | skill version 原地改写非不可变 | WB 已有 content_sha256 不可变版本链（REUSE，勿仿） |
| FV-K1 | 中 | KG 无时效守护（文档变更不重索引） | V3 ontology 变更走 change_sets 人工确认，快照 content_sha256 寻址（无索引漂移问题） |
| FV-O1 | 中 | 覆盖度=生成者自报告 | V3 质量门禁=pytest 代码断言（非 LLM 自评）；LLM 裁判仅 rubric 且失效即 SKIP |

## C. V3 实施风险（PROPOSED）

| 编号 | 严重度 | 风险 | 缓解 |
|---|---|---|---|
| V3-R1 | 高 | workflow 引擎引入新的死循环/资源占用面（DAG 大/环误判/节点雪崩） | 定义校验纯函数入 CI；run 级 max_duration_ms+超时熔断（复用 agent run 熔断器模式）；首批仅允许只读 call+skill 节点 |
| V3-R2 | 高 | Ontology Registry 与既有 research 域双轨并存导致口径分裂 | 不建平行实体表：ontology_terms 只管术语/别名/关系类型注册，实体仍走 project_research_subjects；change_sets 只引用既有表行 |
| V3-R3 | 中 | 新表迁移与 96 表存量库的兼容（发布列车纪律） | 全部走 Alembic 单链新增（无列改写）；迁移含 downgrade；test_migrations 扩展 |
| V3-R4 | 中 | 权限模型扩展（tool_groups/skill 发布）引入越权回归 | "只收窄"原则代码化：resolve=交集；新增越权负向用例（viewer/撤销/过期审批复用） |
| V3-R5 | 中 | 证据一等表迁移期新旧指针双轨不一致 | evidence_id 可空列+读时合并视图；旧列保留只读；迁移脚本回填不改语义 |
| V3-R6 | 低 | 桌面端新页面（workflow/ontology）增加打包回归面 | 沿用 fde-package-verify asar 字节验证流程；vitest 组件用例先于页面 |
| V3-R7 | 低 | 审计文档与实现漂移（本报告 PROPOSED 部分与最终实现偏差） | 每轮 goal 结束更新本登记册与 backlog 状态列；实现 PR 引用任务 ID |
| V3-R8 | 低 | 与既有 goal 循环（dispatch/翻译/试点线）争用发布列车 | V3 任务排队进既有 goal-d 循环节奏，不并行开第二个实施线（记忆：no-parallel-mutation） |

## D. 明确不做（DEFER 记录）

| 项 | 理由 |
|---|---|
| 搬运 fde-v2 agentscope 多 Agent 团队 | 引入第二套 Agent 运行时+内网服务面；DSH 已承担编排（域 6） |
| 搬运 fde-v2 flow.py 执行器 | 可靠性五件套全缺+两处安全取舍；仅吸收 YAML 形态与节点类型三分法（域 5） |
| 搬运 fde-v2 运行时 DDL reconcile / SQLite 优先 | 与 WB 迁移纪律冲突（域 13） |
| 搬运 fde-v2 隐式页面授权（X-Fde-Page 派生服务放行） | 前端声明=权限面扩大，违背 WB 服务端中心原则（域 16） |
| 搬运 fde-v2 verify 脚本体系 | WB 已有更强 CI+pytest 体系；仅借鉴 known-issues 基线法与变异自检纪律（已有） |
| LightRAG 知识图谱检索 | WB 当前无全文检索需求闭环（知识快照已覆盖 DSH 输入）；待本体层稳定后评估（P3） |
