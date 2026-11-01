# goal-d7 · 交付工作台升级轮次报告（2026-11-01）

> 输入：goal-d6 报告（fork/main `6101dce`）+ PRD 定稿 §4/§6/§7/§10 + 总纲 §2.2/§5 + PartyMode §2/§4/§7/§8 + 自动交付 §3/§6 + D10 蒸馏准备稿 + 代码实测（隔离 worktree，基线 6101dce）。

## 〇、预检（只读）

- 基线：fork/main = `6101dce`（goal-d6 squash 合并后），本地 main 仍在 r3（755e429，并发会话未提交改动阻塞 ff，顺延不碰现场——红线纪律）。
- 并发会话痕迹：主树 M 文件（dispatch/api_catalog/seeds/台账 + r12 相关）仍在，全部与本轮隔离 worktree 无交集；本轮从 fork/main 干净基线起步。
- 迁移预检：head `f6a9c3e1d7b4`（17 revision）；本轮**确需新迁移**（O-3 额度台账表 + agent_runs.difficulty 列——T4 门槛需要 run 侧难度事实，见 §二 决议 2），为 d3 以来首个迁移轮，双跑验证入 §三。

## 一、差距清单（本轮覆盖项）

| 能力项 | 目标（出处） | 现状（代码证据，6101dce） | 定级 | 行动 |
|---|---|---|---|---|
| M1 S1–S5 模板可配置可开会 | PartyMode §2.1/§8 | 仅 T2-lite/T3-adhoc 两个门模板；场景模板 S1–S6 全缺 | P2 核心 | 注册 S1–S6 场景模板（班底/议题/D10 蒸馏源标注，trigger=manual 不作门证据）+ T1-lite/T5-lite 门模板 |
| T1 计划评审强制门 | 总纲 §2.2 T1 + U2 | 无——start_run 带 solution_id 无前置计划门 | P2 核心 | start_run 前置闸：无已封存 T1 纪要侧链该 solution → 409 `t1_gate_open`（状态机级，非 prompt） |
| T4 高难度加座（U10） | 总纲 §2.2 T4 + UM-1 gate_tier | `min_difficulty` 列已预留（d5 落列），无升档机制 | P2 核心 | run 声明 difficulty（standard/high）；高难度 run 召集强制门会自动升 full 档 + 角色卡加座；门判定要求满档纪要 |
| T5 降级恢复补审 | 总纲 §2.2 T5 + 自动交付 §3.3 | L1 产物已强制人工（d6），但补审会无门语义 | P2 核心 | 家族含 L1 run 时，T2 门只认 T5 模板已封存纪要 |
| 角色卡 kind='persona' | PartyMode §4.2 + 架构 §9 | kind 枚举已含 'persona'（d3 落），零种子、零发言通道、零防火墙 | P2 核心 | 种子三角色卡（模拟财务/法务/客户IT）+ 编排中枢到场表鉴权 + PM-2 三层防火墙 |
| PM-2 三层防火墙 | PRD §4 F5 + PartyMode §4.2 | 无任何实现 | P2 核心 | ①徽标：persona 发言系统注入「AI 模拟视角，非专业意见」②禁令：处方话术 denylist 拒收（422）③专业结论只进待办段：persona 来源条目入共识/分歧 → 拒封存；入待办 → 服务端固定文案前缀 |
| Killjoy 自动收敛 | PartyMode §7 + d5 挂账 | M6 话轮硬墙已有（超限 409），重复论点检测无 | P2 核心 | add_turn 重复论点检测 → 主持人强制收敛：自动封存未完成纪要（auto 标记）+ 事件 |
| M5 同项目二次开会引用上次纪要 | PartyMode §8 | 无 memlog 连续性 | P2 核心 | create_meeting/dispatch convene 自动带 `topic_refs["prior_minutes"]`（≤3 条最近已封存纪要） |
| M7 中断恢复 ≤24h | PartyMode §5.2/§8 | 会议只有 live→closed，无暂停/恢复/超时收场 | P2 核心 | pause/resume 路由（恢复 ≤24h）+ 24h 无活动自动收场出未完成纪要（auto 标记，懒收场） |
| M8 降级 checklist 模式可用 | PartyMode §7/§8 | U9 checklist 端点已有（d6），无降级建会通道 | P2 补齐 | create_meeting `mode="checklist"`：人工降级建会 + 即封 checklist 纪要（auto+degraded） |
| M9 成本按会议归集可查 | PartyMode §8 + 自动交付 §5.1 | 会议计费落触发 run（d5），无会议视角查询 | P2 补齐 | `GET /meetings/{id}/cost`（只读，进 api_catalog） |
| M10 评审产出作 Stage A/B 门证据 | PartyMode §8 | 工作台侧：已封存强制纪要已作 T2 门证据（d5）；派单联动缺 | 挂账 | 派单 Stage A/B 联动随 d8/d9（用户挂账清单确认顺延） |
| O-3 额度 100 次/月 seat 归集 | 自动交付 §6 + PRD §7 | cost_owner_type 枚举骨架（d3），零计量 | P2 核心 | `seat_action_ledger` 新表（agent_run/meeting_convene/ai_chat 三类动作）+ `GET /agents/quota`（自席；admin 可查任意席） |
| O-3 加油包 + UI 透明化 | 自动交付 §6 透明化硬规则 | 无 | P2 核心 | 配额响应含加油包计价（Settings 价签）+ 消耗显示 + ≤20% 提醒 + 超额不断供（0 拦截，只标注）+ 桌面 QuotaMeter |
| O-3 30 天重校钩子 | 自动交付 §6 重校条款 | 无 | P2 补齐 | 配额响应 `review` 块：窗口起点推导 + `review_due` 标记（回写人工） |
| 模块智能体挂编排中枢 | 技术文档 §55/§155 | agent 注册零种子、发言无到场表校验 | P2 核心 | `seeds/agents.json` + 懒初始化装载（沿 gates.json 先例）+ add_turn 到场表鉴权（能力腿匹配） |

**不做边界（本轮明确不做，进台账）**：①std/full 档独立门模板（试点期 UM-1 一律 lite；T4 升档机制以 gate_tier=full 承载，试点升级后落地）②U6 全量成本归集（话轮/收敛计费——挂账顺延）③M10 派单 Stage A/B 联动（d8/d9）④checkpoint 人工拍板桌面页 / pilot-report 桌面报表页（挂账）⑤插件能力登记种子（挂账）⑥真实 iptables + CLI 钉定人工联调（试点前）⑦T6 高成本 run 前评审（PRD 可配置项，挂账）⑧报价卡数值禁区边界等 D10 五项待蔡工拍板（审定交接文档随轮交付）。

## 二、行动说明（含设计决议）

**分支** `feat/goal-d7-s2-orchestration`（fork/main 6101dce 基线）；**迁移 1 个**（新 revision：`seat_action_ledger` 表 + `agent_runs.difficulty` 列）；文件改动聚焦 `agents/`（models/service/quota 新模块/seeds/routes）、`meetings/`（templates/service/routes）、`guidance/`（ai_chat 计量）、`control/`（api_catalog +2、access +8 能力键）、`config.py`（O-3/防火墙/收场 Settings 族）、桌面 `solutions/`（QuotaMeter）。

**d7 设计决议（六条，登记备查）**：

1. **T1 前置闸落点**：start_run（retry 不复闸——家族首 run 已被闸，重试沿 d4 语义）。T1 纪要经 `topic_refs.solution_id` 侧链匹配（pre-run 无 run 家族可言；agent 自动召集 T1 走「规划 run 先行」路径：规划 run 用工具面召集并声明 solution_id）。场景模板（S1–S6）trigger=manual 不作门证据，门语义独占于 T 系模板——两套 S 编号争议（PartyMode 场景矩阵 vs D10 蒸馏稿）以 PartyMode（M 系列判定细则源）为准，D10 编号映射进审定交接文档待蔡工拍板。
2. **T4 difficulty 来源**：发起人在 start_run 声明（`difficulty` ∈ standard/high，默认 standard，落 `agent_runs.difficulty` 列）——发起人即责任人（架构 §6.4），系统按声明强制门档（lite 纪要放不高难度的 run）；派单引擎订单难度自动带入随 d8（挂账）。升档 = gate_tier→full + turn_budget→12 + 模板 `persona_addons` 三角色卡自动入座（T1/T2/T5 门模板 min_difficulty="high"）。
3. **T5 门语义**：家族（同幂等键）含 fallback_level='L1' 的 run ⇒ 满足门的纪要必须出自 gate='T5' 模板（T2 复审不覆盖恢复补审）。正常家族零条件触发，d5/d6 语料零回归。
4. **自动纪要排除门证据**：Killjoy 收敛/M7 超时收场/M8 checklist 建会三类自动封存纪要，todos 条目带 `auto: true` 标记；t2_gate_satisfied/U4 修订回路输入均排除 auto 纪要（未完成评审 ≠ 评审完成）。人工对被守卫拒封存后补正重封的会议不受影响（degraded 标注语义沿 d5 不动）。
5. **到场表鉴权（编排中枢 authority）**：add_turn 发言 agent 必须匹配会议到场表：`module:<key>`/`quality_guard` 精确能力腿（capability_tier）；`persona:<key>` 仅角色卡；既有泛标签（module_agent/quality_guard）对非 persona 可执行 agent 保持兼容（d5 语料零适配），**persona 永不落入泛标签**（防火墙边界）；S6 空到场表 = 自由席。
6. **O-3 计量口径**：一次动作=一条 ledger 行——agent_run（非演练，发起时刻计）、meeting_convene（工具面召集；人工开会免费——「人工不占 agent 限额」）、ai_chat（预调研分析 worker 成功就绪时计，失败不计）；`seat_action_quota_monthly=100`、0=不限；**超额只标注不拦截**（绝不断供，`over_quota=true` + 加油包计价入口）；演练 run（rehearsal: 前缀）与人工路径零计量。seat 归集键=动作发起人（run.initiated_by_user_id / convene 触发 run 的发起人 / 分析创建人）。

**既有测试适配（单列）**：test_run_review_gates.py 与 test_solution_agent_wiring.py 因 T1 前置闸需补 T1 纪要种子（helper 注入，既有断言逻辑零改动）；其余既有用例零改动。

**回滚**：迁移 downgrade -1 即回 6101dce 形态；服务层纯代码回滚。

## 三、验收判据（逐条，全部本包实测）

| 判据 | 用例/断言 | 结果 |
|---|---|---|
| M1 | S1–S6 场景模板注册（班底/D10 蒸馏源标注/manual 不作门证据）+ S1 实际开会走通（召集→在册发言→封存） | ✅ test_m1_scenario_templates_registered / test_m1_scenario_meeting_convenable |
| 编排中枢 authority | S1 到场表外智能体发言 403 speaker_not_in_roster；persona 只经 persona:<key> 入场（S1 拒/S3 放） | ✅ test_roster_authority_blocks_stranger / test_persona_only_enters_via_persona_label |
| PM-2 L1 | persona 发言系统注入常驻徽标「AI 模拟视角，非专业意见」+ persona/speaker_ref 标注 | ✅ 同上（content 断言） |
| PM-2 L2 | 处方话术（你应该签/必须签…denylist）→ 422 persona_prescription_blocked | ✅ test_pm2_layer2_prescription_blocked |
| PM-2 L3 | persona 来源条目入共识/分歧 → 422 persona_conclusion_misplaced；入待办段 → 固定文案前缀进 sealed_sha256 | ✅ test_pm2_layer3_conclusion_only_into_todos |
| Killjoy | 逐字复读（agent/人同规则）→ 强制收题 + auto 纪要 + 会议 closed + 二次收敛 409 | ✅ test_killjoy_duplicate_turn_auto_converges |
| auto 纪要排除 | auto 纪要不作 T2 门证据（t2_gate_satisfied False）+ U4 修订回路输入排除 | ✅ test_auto_minutes_not_gate_evidence + U4 代码路径 |
| M5 | 同项目二次开会 topic_refs.prior_minutes 引用最近已封存纪要 | ✅ test_m5_second_meeting_references_prior_minutes |
| M7 | pause/resume 窗口内复活；超窗 409 meeting_resume_expired + 自动收场出未完成纪要；live 超 24h 懒收场 | ✅ test_m7_pause_resume_within_window / resume_expired / stale_live_reaped |
| M8 | mode=checklist 建会即封 auto 纪要（degraded + checklist 步骤化待办）；非法 mode 400 | ✅ test_m8_checklist_mode_meeting |
| M9 | GET /meetings/{id}/cost：工具面召集 2 单位 + 触发 run 累计；人工开会 0 | ✅ test_m9_meeting_cost_endpoint |
| T1（U2 同族） | 无 T1 纪要 → start_run 409 t1_gate_open 零 run 落库；T1 封存后放行创建且 T2 仍拦（门语义分离）；retry 不复闸；探索 run 不受 T1 | ✅ test_t1_gate_blocks / passes_then_t2_still_open / retry_does_not_regate |
| T4（U10） | high 召集强制门模板自动升 full（12 轮）+ 三角色卡入座；lite 侧链纪要放不高难度 run；满档纪要放行；standard 零影响 | ✅ test_t4_high_difficulty_auto_upgrades / lite_insufficient / full_satisfy / standard_unaffected |
| T5 | 家族含 L1 run：T2 纪要不再满足门（服务层 False→True 只认 T5）；T5 封存后 retry 放行 | ✅ test_t5_t2_minutes_insufficient / minutes_satisfy_recovery_retry |
| 角色卡/种子 | persona 发起 run 409 persona_not_executable；种子懒装载幂等（守卫+六模块+三角色卡、模拟前缀）；difficulty 枚举校验 | ✅ test_persona_not_executable / test_agent_seeds_loaded / test_difficulty_enum_validated |
| O-3 计量 | run=1 动作；演练/人工开会零计量；工具面召集=1（seat=run 发起人）；ai_chat 分析就绪时计 | ✅ test_run_counts_one_action / rehearsal_manual_free / toolface_convene / ai_chat_counted |
| O-3 透明化 | 配额快照（消耗/余量/pack 价签/window）；超额只标注不拦截（第 2 run 201 + over_quota 落账）；quota=0 不限额；他席 admin-only；30 天重校窗口推导 | ✅ test_quota_endpoint / over_quota_never_blocks / zero_unlimited / scope_permissions / review_window |
| 迁移 | 新 head `a7b4d9e2c6f1`（18 revision）：+seat_action_ledger +agent_runs.difficulty；upgrade→downgrade -1→upgrade 双跑干净 | ✅ 测试库实测 |
| 口径 | 蓝图路由 **262**（258+4）；api_catalog ENTRIES **89**（+2 只读：meetings.cost / agents.quota） | ✅ create_app 实测 |
| pytest | **1627 收集 = 1621 passed / 6 skipped / 0 failed**（基线 1592 = 1586+6，+35 新用例；全量 24:34 正规口径单跑零漂移）+ 既有适配 6 处（断言逻辑零改动，见 §二） | ✅ |
| vitest / typecheck | **704/704 全绿（57 文件）**（699 基线 + 5 QuotaMeter）；typecheck 零错误 | ✅ |
| ruff / mypy | All checks passed（触碰文件零错）；基线检查 OK no new type errors（289 基线 / 279 现值） | ✅ |

**变异闭环（fail-fast，8 处各红→还原→绿）**：①T1 闸拆除 ②T4 升档拆除 ③T5 家族检查拆除 ④PM-2 徽标注入拆除 ⑤PM-2 第 3 层扫描拆除 ⑥Killjoy 复读检测拆除 ⑦O-3 ledger 写入拆除 ⑧绝不断供反转（超额即拦）——8/8 一轮全红，还原后三测试文件 35/35 复绿。

**还原纪律事故与修正（如实登记）**：本轮 8 处变异中 5 处落在同一文件，顺序备份使后一个 `.bak` 覆盖前一个的干净态——首轮还原写回了带变异的备份（字节级 diff 对污染基线「验证通过」的假象）。抓痕：还原后 5 用例仍红 + grep 残留变异标记。修正：按变异标记逐一剥除 + grep 零残留 + git diff 行数与变异前一致 + 35/35 复绿四重验证。教训（并入隔离纪律记忆）：**同文件多处变异必须逐处「备份→变异→验证→还原」再进下一处，或多处变异共用一份变异前快照**；还原验证必须以 git diff/独立快照为基线，不能以本轮自己的 .bak 为基线。

**反假绿灯自检**：①既有测试适配共 6 处（run_review_gates/_setup 铺 T1、wiring _seed_t1+4 显式、traceability T1 种子、fallback_chain L1 用例 T1 种子、catalog 五条、registry +10 种子、migrations HEAD 常量）——全部是断言面适配，断言逻辑零改动；②全量 vitest 一次过零漂移（串行模式）；③pytest 全量首轮 6 失败中 5 处为盘点断言（本轮合法扩展）+ 1 处为 `-p no:warnings` 旗标 artifact（seed CLI 的 SAWarning 漏进 click 捕获面——正规口径带 warnings 插件时 pytest 记录器收走警告，单测复跑通过），均已处置并复跑绿；④变异还原事故（上段）如实记录并以四重验证收口。

## 四、下一轮建议 + 新登记差距

- **goal-d8（S2 dispatch×agents + P3 预备）**：`agent_assisted` 协同标记（接单人显式声明，8 态机零改动，声明后才启用评审门与溯源联动）+ 集成测试（声明/未声明两态）+ 翻译器门户骨架（引导式表单+实时预览只读版）+ PRD P0/P1 指标报表页；派单订单难度自动带入 run.difficulty（T4 免手报）。
- 新登记差距（进台账节三十二）：①M10 派单 Stage A/B 证据引用联动（工作台侧 d5 已备）②U6 全量成本归集（话轮/收敛计费；M9 当前口径=召集计费+触发 run 累计）③std/full 档独立门模板（试点升级后；T4 升档本轮以 gate_tier=full 承载）④T6 高成本 run 前评审（可配置）⑤checkpoint 人工拍板桌面页 / pilot-report 桌面报表页 / 插件能力登记种子（承 d6）⑥试点前人工联调：真实 iptables + zcode CLI 钉定（承 d6）⑦D10 五项待蔡工拍板（模板内容审定交接：S 编号映射/九卡原句/报价卡数值禁区/G3 会闸关系/审定流程——见 §一 不做边界）⑧seed CLI 断言对 warnings 捕获面敏感（`-p no:warnings` 下 SAWarning 漏进 click 输出——正规口径不受影响，登记为测试基建备忘）。
