# V3.1 阶段状态

- 基线 SHA：P0-0 审计=`65db88c`；P0-1 批A 开发基线=fork/main `9aaa4ef`（含 #197 本线 P0-0 与 #198–201 V3.2 模拟训练场并发并入）；P0-4 开发基线=fork/main `889f964`
- 当前分支：`feat/v31-p2-pilot`（隔离 worktree `D:/test/fde-wt-v31p2`）；P2 开发基线=fork/main `2d14d85`
- 当前阶段：P2 试点 Runbook 与最终验收勾稽（completed 本 PR——纯文档）；**试点执行已完成（2026-11-09 somwyn，复盘=`pilot-复盘-somwyn-2026-11-09.md`）**
- 状态：**V3.1 实施全部收口**（九阶段：P0-0~P0-4、P1-2、P1-1、P1-3、P2；PR #197/#203/#205/#207/#209/#211/#213/#215/#221/#本 PR）
- P2 遗留（业务闸）：①~~E2E 试点执行~~ ✅ **已完成（2026-11-09 somwyn 十步全链+复盘落盘；偏差注记=审阅动作 admin 代执行待蔡工复核）** ②ZCode 真实联调：**业务侧已拍板**（2026-11-09 D-1：通道＝宿主侧 zcode 代理／审阅人＝蔡工本人经第二账号／确认 C5·C6）⇒ 状态由「待拍板」转为「**待前置核验 + 待真实联调执行**」——12 条安全前置现测 **8 过**（③票据已接线且在首跑/重跑二两度真实行使）／**2 部分**（⑧cancel 与进程树回收待实测、⑪危险操作二次确认以 H1–H13 承载）／**2 未过**（①商用条款书面确认未取得＝外部依赖、⑦宿主网络无代码级限制面＝结构缺口），逐条锚点见 AI 原生化任务书 §6.1；**抽取腿复测已消解**（2026-11-09 晚 V31-P1c 全量 rerun 实证，任务书 §13 记录 #10）；由 N1 真实订单首跑承接
- 开始/完成时间：P0-0=2026-11-07（#197 `14d2b62`）；P0-1=2026-11-08（#203 `92ca0bd`）；P0-2=2026-11-08（#205 `858e090`）；P0-3=2026-11-08（#207 `889f964`）；P0-4=2026-11-08（#209 `b196074`）；P1-2=2026-11-08 交付

## P0-0（completed，已合并）

四报告+任务书入库+复用/扩展/新建裁决（详见 `00-baseline-audit.md` 等），PR #197 squash 合并为 `14d2b62`，CI 4 job 全绿。遗留：拍板项 D-1~D-4 待蔡工确认（不阻塞 P0-1 批A——批A 不踩跨项目别名/发布权限/锚点粒度三议题；D-3 宿主通道对齐已由 #195 落地自动消解大半）。

## P0-1 批A（服务端，completed——已合并 PR #203 `92ca0bd`）

- **交付**：NEW `discovery/` 五文件（models/contract/prompt/jobs/routes）+ 迁移 `c3d5e7f9a1b4`（挂上游 V3.2 G6 头 `e8b1d5f9a3c7`）+ 8 路由 + 14 例测试；7 处注册点（app 蓝图/jobs handler+失败钩子/reconcile RECOVERABLE/env.py/conftest 清理序/test_migrations HEAD/extract 脚本 BLUEPRINTS）+ 提示词卫生闸登记（`_ALLOWED_PROMPT_CONSTANTS`）。
- **设计裁决**（00-gap-register P0-1 全部落地）：七组示例收敛 facts[].fact_type 十值+requirements 独立组；classification 对齐 guidance 五分类；抽取行 status 四值（accepted/rejected=派生态不物化，B#13-C 先例）；requirements 结构化 acceptance_criteria 列表；requirement_sources 关系表（任务书原文）。
- **红线对齐**：整批失败零写入；推断/开放问题强制待澄清；无来源需求不得自动接受；输出端 T-A2 兜底脱敏+复核事件；重跑仅 failed（审阅痕迹不可覆盖）；全部路由不进 api_catalog。
- **测试**：14 例全绿+回归簇 46 passed+邻域 37+上游 simulation 14；mypy 279 不变；测试库外来戳重建（教训：版本戳骗过 upgrade——重建必须清全表）。

## P0-1 批B（桌面，completed 随批A PR 同窗交付）

- NEW `desktop/src/renderer/src/discovery/DiscoveryPanel.tsx`（挂项目 overview tab、转写面板之后——访谈区聚合）：抽取发起（纪要下拉+幂等 created 双文案）/抽取记录表（状态徽标+失败码+脱敏复核条目 tooltip+重跑仅 failed）/事实清单（审阅状态过滤+三动作接受/拒绝/澄清+**批量接受本页待审**〔逐条 PATCH、失败计数如实汇报〕+锚点三形态呈现 line/transcript_segment/char_span）/需求清单（批准/否决/澄清+验收条数+来源计数）。写操作 canManage 显隐。
- NEW `desktop/tests/renderer/discovery-panel.test.tsx` 7 例（三列表加载+复核呈现/锚点三形态/POST 形状+幂等提示/重跑显隐/PATCH 形状/批量只打 pending/viewer 全隐）。
- 口径：vitest 944→951（+7）；typecheck 0 错；零服务端改动。

## 遗留问题

1. 拍板项 D-1（跨项目别名冲突）/D-2（发布权限）待蔡工确认——分别阻塞 P0-2 部分/不阻塞。
2. D-4（锚点粒度）已在批A 以三形态闭合枚举（line/transcript_segment/char_span）落地，契约层收敛，批B UI 按此呈现。
3. 任务书 §16 其余文档（architecture/api-contracts/data-model/security-review/pilot-runbook）随对应阶段交付。

## P0-2（completed，本 PR）

- **交付**：ADR-002（decisions/）+ 候选桥（`generate_discovery_candidates`：accepted 事实→create_term 条目→既有 change-set 管线；幂等/确定性/占用跳过）+ 稳定 ID 试点（subjects+term_id 迁移 `d6f2a8b4c9e1`；confirmed 落定自动链接同名 subject=回填；合并不改写）+ D-1 只读告警。+2 路由 365/46 rev/表 122。
- **ADR 摘要**：control/ontology.py=AI 阅读语义快照（MCP 契约冻结）；ontology/=唯一治理权威；业务表写面关联逐步走 term_id（试点：research subjects），读面/影响分析仍以名字域为权威。

## P0-3（completed，已合并 PR #207 `889f964`）

- **交付**：NEW plans/ 模块（models/service/routes）+ 迁移 `a9c1e5f7b3d8`（48 rev）+ 6 路由 + 5 例测试。生成器=确定性拼装（accepted 需求逐条成目/confirmed 术语范围/needs_clarification 风险聚合，无输入 409）；审阅流 approved/rejected+发布+旧 published 退位 superseded；任务分解 dry_run 预览+选择性创建+幂等（每条目至多一任务，待认领不指派）。
- **实施修正**：风险素材双重过滤恒空（accepted×open）→独立查 needs_clarification；ProjectTask 无 project_id（经模块间接挂）。

## P0-4（completed，本 PR）

- **交付**（00-gap-register 4.4~4.10 全落地）：①种子通道——NEW `seeds/workflow-templates.json` 三套首批模板（任务书 §8：需求发现/方案实施/自动化交付，全部用既有四类节点表达）+ NEW `workflows/templates.py`（fail-fast 装载+`seed_workflow_templates` 幂等落库〔沿 seed_public_skills 先例：active admin actor、落库即 publish 锁版；幂等锚=平台定义 name，已存在绝不覆盖〕+`list_published_templates` 只读投影）+ CLI `seed-workflow-templates`（部署顺序：先 seed-public-skills）；②节点契约扩展——`validate_dag` 白名单 +5 草稿期字段（`timeout_seconds` 1..86400/`input_schema`/`output_schema`/`failure_class` 三值闭集/`plan_ref`），执行器消费随 P1 执行通道轮（补偿动作需设计轮拍板，不建字段）；③draft-from-plan——`compile_plan_workflow` 纯函数（只收 approved/published；三节点形 plan_review→implement〔skill 注入制+契约字段首发〕→acceptance_review；标题剔除 `{{}}` 防占位符误判）+ `POST /api/v1/projects/{id}/workflows/draft-from-plan`（落库走既有 create_definition 通道，不建平行入口）；④validate 干跑——`POST /api/v1/projects/{id}/workflows/{def_id}/validate`（can_view 零副作用，errors/warnings/order 明细）；⑤模板只读面——`GET /api/v1/workflow-templates`（已认证可见 published 平台模板，dag 全文携带）。**D-2 拍板执行**：发布权限维持 admin-only（零代码，publish 路由不动；留痕可推翻）。
- **口径**：路由 374→**377**（+3，全不进 api_catalog）；蓝图 46 不变（新路由挂既有 workflows_blueprint，BLUEPRINTS 无需同步）；**零迁移**（48 rev 单头不变）；表 125 不变；pytest 2321→**2331**（+10 NEW `test_workflow_templates.py`：种子对账/fail-fast/字段校验/纯函数确定性/路由全闸/干跑/模板只读面）；mypy 279 不变；vitest 951 不变（零桌面）。
- **测试纪律**：三变异验证全红→还原→绿（幂等跳过摘除/`failure_class` 校验摘除/plan 状态闸摘除）；种子↔DB 对账钉（行名+dag 逐字节一致）。
- **顺带修复（#209 CI 实红）**：P0-2 候选组序非确定性（单事务 created_at 全同+uuid4 id 无序）→分组迭代改 subject 字典序；测试期望同步。
- **Gate 纪律（4.11）**：现状维持——workflow 产物只能经 `output_json.gate_evidence` 挂候选，采纳唯一入口=真人提交闸；模板③证据段文案如实表述该边界。

## 是否允许进入下一阶段

P0-4 合并并部署后（部署义务：三镜像 rebuild + `alembic upgrade head`〔幂等 no-op，零迁移〕+ **`seed-workflow-templates` 幂等落库** + `/api/v1/health/ready` 活体）→ **P1-2 自动测试与证据**（任务书 §13：测试计划→用例→执行→证据落证；复用 gate evidence 登记簿与任务产物候选挂接，00-gap-register §6 裁决待精读）。D-2 已按建议拍板执行（admin-only 维持）；D-1 已随 P0-2 以只读告警落地。

## P1-2（completed，本 PR）

- **交付**（00-gap-register 6.3/6.4/6.5 全落地；6.1/6.2 复用零代码）：NEW `quality/` 模块（models/service/routes）+ 迁移 `d5a8c2f4b7e1`（49 rev）+ 6 路由（全不进 api_catalog，蓝图 47）+ 7 例测试。三表 test_plans/test_cases/test_executions（requirement_key 强制追溯、append-only 执行〔失败不可改写=无更新路径+静态钉〕、production 服务层硬闸、报告指针+sha256 成对）；生成器=确定性拼装（字典序条目序，#209 教训）；需求覆盖闸（approved 时点名缺失键 409）；evidence/validate 五维只读校验（零写入零事件+可选 gate_key 类型范围）。**evidence_links 第四表不建**（登记簿+追溯已承载，冗余拒绝）。
- **实施修正**：审核戳先于退位循环落（autoflush 抢跑撞 review_stamp CHECK）；双点退位语义（同一时刻至多一个 approved）约束测试设计（不能并行批准两计划做跨计划用例）。
- **口径**：路由 377→**384**（+6）；蓝图 46→**47**（quality 新蓝图，BLUEPRINTS 已同步）；表 125→**128**（+3）；**49 rev 单头 `d5a8c2f4b7e1`**；pytest 2331→**2338**（+7 本地；CI 融合树实测 2339=2333+6s 含并发 #210 +1，main run 全绿收口）；mypy 279 不变；vitest 951 不变（零桌面）；CSV 重生成（385/129 行 wc 核对）。

## 是否允许进入下一阶段（P1-2 后）

P1-2 合并并部署后（部署义务：三镜像 rebuild + `alembic upgrade head`〔新迁移 d5a8c2f4b7e1〕+ ready 活体）→ **P1-1 ZCode 宿主执行通道**（任务书 §9；12 条安全前置未过前通道保持关闭——实施面以 #195 host_channel.py + 00-gap-register 5.1~5.7 裁决为基，先对齐在途宿主线成果再动工）。之后 P1-3 指标与经验沉淀（7.1 复用 metrics 报表、7.2 事件补齐、7.3 workflow 域指标、7.4/7.5 暂缓）。E2E「完整脱敏项目从访谈到交付验收」（任务书 §13.5）属 P2 试点验收面，随 P2 落地。

## P1-1（completed，本 PR；通道保持关闭）

- **交付**（00-gap-register 5.3/5.4/5.6/5.7 落地；5.10 闸纪律履行）：NEW `agents/execution_policy.py`（根锚定规范化+命令锚定+超时钳制+策略快照 hash，纯函数）+ NEW `agents/execution_authorization.py`（HMAC 短期票据签发/验证，HTTP 发行面随闸开放轮）+ 迁移 `e7c4a9d2f6b8`（50 rev；agent_runs +5/agent_artifacts +4 全可空 additive）+ 接线（宿主分支 root 锚定+命令锚定+快照落列+provider/workspace_ref 补写〔宿主直连此前不写 provider 的缺口〕+产物 size/mime）。**通道默认关闭零改动+双静态钉**（d4_settings 断言+config AST 字面 False）。5.2 容器 spawn 段维持降级现状；5.5 独立代理进程待分级开放拍板不预支。
- **口径**：路由 384/蓝图 47/表 128 不变（零新表零新路由）；**50 rev 单头 `e7c4a9d2f6b8`**；pytest 2338→**2351**（+12 本地〔11 policy+roundtrip 1〕；基线 2339 收集含 #210 +1）；mypy 279 不变；vitest 951 不变；CSV 行数零变化（50 rev 核对）。

## 是否允许进入下一阶段（P1-1 后）

P1-1 合并并部署后（部署义务：三镜像 rebuild + `alembic upgrade head`〔新迁移 e7c4a9d2f6b8〕+ ready 活体）→ **P1-3 指标与经验沉淀**（00-gap-register 7.1 复用 metrics 报表加新指标、7.2 事件补齐随阶段、7.3 workflow 域指标、7.4/7.5 暂缓维持）。之后 **P2 真实项目试点**（任务书 §15/§16；E2E 完整脱敏项目验收面随试点落地）。P1-1 通道开启属**业务拍板项**（12 条安全前置+商用条款书面确认）——不随 P1-3/P2 自动开放。

## P1-3（completed，本 PR）

- **交付**（00-gap-register 7.1/7.3 落地；7.4/7.5 维持暂缓；7.2 零代码=事件名等价映射注记）：metrics 报表 +`v31` 节七指标（workflow 完成率/审批时延/hops 分布 + 需求批准率/本体候选采纳率/方案转任务率/测试首过率），全部进既有报表走 `_metric` insufficient_data 语义。**实施注记**：跨域测试序列曾观察到分解路径 FOR UPDATE 挂起（idle-in-transaction 持 xid，terminate 后前进）——测试改直插链接行绕开（根因不在生产代码，留观察）。
- **口径**：本指标轮零结构零迁移；**rebase 融合 #217（G1）后=路由 391/蓝图 49/表 130/51 rev 单头 `e9c4a1f7b3d2`**；pytest +3（本地 2354=2348+6s EXIT=0；融合树 metrics+commercial+migrations 52 例绿）；mypy 279 不变；vitest 951 不变；CSV 392/131 行。

## 是否允许进入下一阶段（P1-3 后）

P1-3 合并并部署后（部署义务：三镜像 rebuild + `alembic upgrade head`〔幂等 no-op，零迁移〕+ ready 活体）→ **P2 真实项目试点**（任务书 §15/§16 最终阶段：真实脱敏项目 E2E 从访谈到交付验收；试点条件=真实项目数据闸+拍板项逐项确认；通道开启仍属独立业务拍板项）。

## P2（completed——纯文档层；试点执行已于 2026-11-09 完成，见下）

- **交付**：NEW `docs/v3.1/pilot-runbook.md`（试点前置 C1-C7 + E2E 十步操作序 + 复盘模板）+ NEW `docs/v3.1/final-acceptance-checklist.md`（§17 十九项勾稽：16 达成/2 待条件/0 未达成，达成项附 PR/代码锚）。
- **边界如实声明**：试点执行与 ZCode 真实联调属业务闸（真实项目数据+商用条款拍板），本 PR 不预支执行授权；宿主通道保持关闭（默认 False）。
- **口径**：零代码零迁移零路由零桌面零测试增量（2354=2348+6s 维持）；CSV 零变化。

## V3.1 最终状态（九阶段全收口）

P0-0（#197）→P0-1（#203）→P0-2（#205）→P0-3（#207）→P0-4（#209）→P1-2（#211+#213）→P1-1（#215）→P1-3（#221）→P2（本 PR）→**试点执行（2026-11-09，somwyn 十步全链走通+复盘落盘 `pilot-复盘-somwyn-2026-11-09.md`）**。任务书 §17 十九项（试点后）：**17 达成/1 待业务闸（#14 ZCode 联调）/0 未达成**。后续动作：ZCode 联调按拍板推进；试点遗留四项见 `docs/implementation/v3-backlog.md`「V3.1 试点遗留登记」。

## 本阶段目标

按任务书 §2「P0-0 必须先完成的代码核验」十条，只做基线审计不改业务代码；产出四份审计报告并给出复用/扩展/新建/暂缓裁决。

## 真实代码定位

四域并行深查（transcripts/guidance/meetings、agents/zcode/control 执行面、workflows/jobs/metrics、ontology/gate/tasks/solutions/evidence/handover），全部结论带 `file:line` 锚，汇总于：

- `00-baseline-audit.md`（十条核验逐项结论+口径现测+活库运行数据）
- `00-data-model-map.md`（109 表按域分组、迁移链、事件/异步底座、API 面）
- `00-test-baseline.md`（环境/命令/结果/209 测试文件/回归面映射）
- `00-gap-register.md`（P0-1~P1-3 逐能力裁决+横切纪律+4 项拍板项）

任务书 §2 表格 25 项路径核验：24 项原路径命中、1 项修正（AgentsConsole 实际在 `agents/` 子目录）。

## 设计决策及理由

1. 审计在隔离 worktree @ fork/main 执行（主树落后 23 提交且有并发会话脏集），不触碰用户未提交修改。
2. 历史台账口径（107 表/38 rev/315 路由/pytest 2116）确认为旧值，全部以本轮现测替代（109/39/e5f1a7c3b9d4/323/pytest 见 test-baseline）。
3. `zcode_contract.py` 纯函数契约层判断成立；发现 `adapter.py` spawn 段为自认虚构契约（与真实 0.17.1 CLI 相悖）——登记为 P1-1 重构靶点而非本轮修复。
4. `control/ontology.py` vs `ontology/` 零代码级重叠（静态字典 vs 治理层），ADR-002 列为 P0-2 文档交付物。
5. 每项「新建」裁决均附负结论核验（grep/表全集证据），满足任务书 §1.3「核验现有能力前不新增」纪律。

## 修改文件

仅文档（零业务代码/零迁移/零路由/零桌面）：

- NEW `docs/v3.1/00-baseline-audit.md`
- NEW `docs/v3.1/00-data-model-map.md`
- NEW `docs/v3.1/00-test-baseline.md`
- NEW `docs/v3.1/00-gap-register.md`
- NEW `docs/v3.1/phase-status.md`（本文件）
- ADD `docs/蔡工_FDE_Workbench_V3.1_智能交付自动化升级路线图与Goal实施任务书.md`（用户提供的任务书原稿，从主树未跟踪状态正式入库，作为 V3.1 唯一权威任务书）
- NEW `docs/v3.1/decisions/`（空目录预留 ADR；git 不跟踪空目录，实际由 P0-2 的 ADR-002 首个文件建立）

## 数据库迁移

无。

## API / 权限 / API Catalog

无变化（审计含 API Catalog↔路由差异核验：323 全路由 vs 94 ENTRIES 为设计性差异，CI 双钉在位）。

## 前端变化

无。

## 测试命令与结果

见 `00-test-baseline.md` §2（pytest 全量/vitest 932/typecheck/mypy 279 基线全绿；零新增测试——纯文档轮）。

## 安全检查

- 未运行被审代码；未执行生产变更；未读取客户资料。
- 活库查询为只读 SELECT（经 api 容器内引擎）。
- 发现类安全注记：P1-1 的 12 条安全前置未过前宿主通道保持关闭（任务书红线原文遵守）；在途会话 `feat/host-zcode-channel` 线需先对齐（gap-register D-3）。

## 数据兼容与回滚

纯文档，无需回滚；合并后如需撤销直接 revert 本 PR 即可。

## 验收证据

- 四报告齐全且十条核验逐项有锚（本文件+00-baseline-audit.md §1-§10 对照表）。
- 复用/扩展/新建/暂缓四档裁决覆盖 P0-1~P1-3 全部条目（00-gap-register.md）。
- 口径现测与 fork/main CI 实测逐位一致（test-baseline §4）。
- CI 4 job 绿（PR 链接见合并记录）。

## 遗留问题

1. 4 项拍板项（gap-register D-1~D-4）待蔡工确认后进入对应阶段。
2. 任务书 §16 建议目录中的 architecture.md / api-contracts.md / data-model.md / security-review.md / pilot-runbook.md 属后续阶段交付物，P0-0 不预支。

## 是否允许进入下一阶段

**允许进入 P0-1（访谈事实与需求结构化）**——前置基线已闭合：transcripts/guidance 域真实代码定位、四表新建论证、脱敏/任务/校验三范式复用清单齐备。P0-1 方案设计须先按任务书 §5 约束出最小改动清单（新表+job_type+契约校验器+审阅 UI），其中锚点粒度（D-4）建议随方案一并呈批。
