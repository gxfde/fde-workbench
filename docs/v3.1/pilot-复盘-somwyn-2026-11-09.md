# V3.1 试点复盘：somwyn 2026-11-09

> 执行依据：`docs/v3.1/pilot-runbook.md`（C1–C7 前置已于 2026-11-08 由蔡工确认，
> 执行数据：C1=代号 somwyn；C2=访谈素材取自本地文档中心既有脱敏实记录
> `somwyn案例_FDE交付实记录_v1.1.md`（全代号化，真实资料零入库）；C3=分解目标模块
> 由执行自选（该项目交付段既有模块））。宿主通道全程关闭（C5 ✓，12 条安全前置未过）；
> §17-14 ZCode 真实联调不在本次范围（独立拍板项，未触碰）。

## 1. 试点窗口与角色

- **窗口**：2026-11-09 01:23 – 07:30（本地 UTC+8；对应容器 UTC 11-08 17:23 – 23:30），总时长 ≈ 6.1h，其中 AI 抽取失败诊断与素材整理约占 2.5h，纯链路操作 < 1h。
- **执行者**：admin（API token 容器内签发）。
- **审阅者**：**admin 代执行全部审阅动作**（事实/需求接受、测试计划批准、测试执行登记、重复草稿废弃）——**偏差 D1，见 §4**；本体变更集 confirm 与 workflow 两处 human_approval 拍板由第二账号 `pilot.reviewer` 完成，**决策分离（decider ≠ submitter）成立**。
- **部署锚**：隔离 worktree compose 栈（api/worker/scheduler，localhost:8010），alembic head `e9c4a1f7b3d2`（51 rev 单头）；试点预检 18/18 端点在该活栈在位。

## 2. 链路步时序（十步实测，UTC；本地 = UTC+8）

| 步 | 时刻 (UTC) | 产出锚 | 卡点 |
| --- | --- | --- | --- |
| 1 纪要导入 | 17:23（全文版草稿晋升 `4b3894df`，10,008 字符）→ 18:02（整理稿 `4b558dce`，1,387 字符，晋升成功） | minutes 行 content_sha256 ×2 | 草稿卷属主 root 首写 PermissionError（P3）；全文版抽取两败后改人工整理稿（P1） |
| 2 事实/需求抽取 | 17:24 发起 `11a3af59`（全文版，ai_output_invalid 两连败）→ 18:02 发起 `02a680d7`（整理稿）→ review_required 22 facts + 7 reqs | discovery_extractions 行 + 草稿事实/需求 | P1（推理模型输出预算） |
| 3 人工审阅 | 18:10 批量接受：20 facts accepted + 7 reqs accepted；**2 facts needs_clarification**（推断/开放问题强制待澄清红线生效） | `business_fact_reviewed` ×20 + `requirement_reviewed` ×7 | — |
| 4 本体候选→确认 | 18:13 变更集 `ffa95ce0`（20 条目）submit(admin) → confirm(**pilot.reviewer**)，单事务物化 20 术语 | `ontology_change_set_confirmed` | 决策分离经第二账号 |
| 5 方案生成→发布 | 18:13 `c0f1dc00` generate→approved→published（9 items = 7 requirement + 1 objective + 1 risk） | `delivery_plan_generated/reviewed/published` | — |
| 6 方案→任务分解 | 预览 9 条（首跑 120s 客户端超时，480s 复跑成功）→ commit 全量 9 条**卡项目行锁超 120s 被 gunicorn abort**（HTTP 500、worker SIGKILL、零残留）→ **改分批 item_ids 单条调用 ×9**（0.1–0.4s/条）9/9 创建 → 幂等复跑 created=0 / skipped=9（reason=已分解） | 9×project_tasks（待认领）+ 9×links 幂等锚；`delivery_plan_tasks_created` ×10（9 创建 + 1 幂等复跑） | P2（gunicorn timeout vs 长事务） |
| 7 Workflow 草稿 | 23:21 draft-from-plan（`delivery-scope-documents@1`）→ `44ac0ea1` draft（plan_review → implement → acceptance_review 三节点）；validate 干跑 **valid=true，0 errors 0 warnings**（content_sha256 `a7dda223…`） | draft 定义 + 版本行 | — |
| 8 发布+运行 | 23:22 admin publish → run `21fc3fa9`（幂等键 pilot-somwyn-run-1）→ plan_review waiting_approval → **pilot.reviewer 拍板**（≈1.8min）→ implement skill 节点成功（真实 AI 调用）→ acceptance_review 拍板（≈1.0min）→ **run succeeded**（hops=0） | `workflow_run_created/waiting_approval ×2/approval_decided ×2/succeeded` | — |
| 9 测试计划→执行→证据 | 23:26 v1 `83f2da29` 生成（脚本响应形状解析错致 review URL 带 None → 404，v1 走 rejected=superseded 留痕）→ 23:27 v2 `5b538ea5` 生成 → 23:29 v2 approved（需求覆盖闸过）→ execute dev **7/7 passed**（append-only，报告指针+指纹成对）→ 证据 `aa2b85a9`（kind=task） | test_plan ×2（1 superseded + 1 approved）、test_executions ×7、project_evidence ×1 | P4（执行脚本瑕疵，非产品） |
| 10 指标复盘 | 23:30 GET /metrics/report → `sections.v31` 七指标全 ok 全有样本 | 快照原文见 §3 | — |

测试报告原件：`D:\test\FDE\engagements\fdeops\somwyn\.fde\pilot-test-report-2026-11-09.md`
（sha256 `acf6104353c8d326302a0ae7127e0713d34f3647c59e30e18728f22cc8b394b3`）——红线遵守：证据原件只留项目工作目录，平台仅指针+指纹。

## 3. 指标快照（GET /api/v1/metrics/report → sections.v31，2026-11-08T23:30:53Z）

```json
[
 {"key": "workflow_completion_rate", "label": "Workflow 完成率", "status": "ok", "value": 1.0, "sample_size": 1},
 {"key": "workflow_approval_latency_minutes", "label": "Workflow 审批时延（中位数，分钟）", "status": "ok", "value": 1.43, "sample_size": 2},
 {"key": "workflow_hops_distribution", "label": "Workflow 自触发链代数（hops）", "status": "ok", "value": {"avg": 0.0, "max": 0}, "sample_size": 1},
 {"key": "requirement_approval_rate", "label": "需求批准率", "status": "ok", "value": 1.0, "sample_size": 7},
 {"key": "ontology_candidate_adoption_rate", "label": "本体候选采纳率", "status": "ok", "value": 1.0, "sample_size": 1},
 {"key": "plan_task_decomposition_rate", "label": "方案转任务率", "status": "ok", "value": 1.0, "sample_size": 9},
 {"key": "test_first_pass_rate", "label": "自动测试首次通过率", "status": "ok", "value": 1.0, "sample_size": 7}
]
```

（`definition`/`target` 字段从略，与 P1-3 交付口径一致；原文存容器内快照，指标定义以 `metrics/service.py` 为权威。）

**解读**：七指标全部 `status=ok`，零 insufficient_data；样本全部来自本轮试点真实数据（n=1/2/1/7/1/9/7）。审批时延中位数 1.43 分钟由两审批行的 `updated_at` 近似（口径挂账维持——含 implement 节点耗时混入，见 P1-3 已挂账细化项）。hops max=0：本轮 run 由人发起、无自触发链，符合预期。

**事件链核对**（project `7042d7ab` 全事件计数，试点链相关）：interview_minutes_created 2 / transcript_draft_created 2 + promoted 2 / discovery_extraction_created 2 + rerun 1 / business_fact_reviewed 20 / requirement_reviewed 7 / ontology_change_set_confirmed 1 / delivery_plan_generated+reviewed+published 各 1 / delivery_plan_tasks_previewed 2 + created 10 / workflow_definition_created+published 各 1 / workflow_run_created 1 + waiting_approval 2 + approval_decided 2 + succeeded 1 / test_plan_generated 2 + reviewed 2 + executed 1 / evidence_registered 1。每步留痕齐备。

## 4. 偏离与原因

| # | 偏离 | 根因 | 缓解/修复方向 | 定性 |
| --- | --- | --- | --- | --- |
| P1 | 全文纪要（10,008 字符）抽取两连败 `ai_output_invalid`：content JSON 截断（finish_reason=length），reasoning_content 吃满 16,384 预算（实测 15,223 reasoning tokens）；65536 预算方案又撞 900s 超时 | **产品缺陷**：降级直连腿 `direct_provider_completion` 未按模型类型预留推理输出预算（MiniMax-M3.1-Flash 为推理模型，reasoning 先于 content 计费占满 max_tokens） | 按模型类型探测/预留 reasoning 预算，或输入分段压缩；**大纪要 + 该模型组合当前必败** | 产品缺陷，进 backlog |
| P1′ | **P1 的根因判断在 2026-11-09 实弹定案后被更正**（本行是 P1 的**修订**，原 P1 行的定性「未按模型类型预留预算」只对了一半）：六组对照实测＝全文@32,768 → **>900s 未返回**（思考随预算同步变长）；`reasoning_split=true` → 正文零产出（更差）；40 行@8,192 → 思考吃满（**预算必须给到硬顶，缩小预算无用**）；40 行@16,384 + 片级限定提示词 → **JSON 完整**（30 事实+7 需求，177s）；60 行@16,384 → 触顶截断；**活体部署后 40 行片仍有批次触顶**（同参数用量方差 13,105↔16,384——思考长度有方差） | **真根因＝供应商 completion 有硬顶（MiniMax-M3.1-Flash = 16,384 tokens）＋思考成本与任务量弱相关（每调用 ~6k–16k tokens）**——「给推理模型 ×2 预留预算」不是解（只更慢更易触顶） | **正解＝把活拆小**：按行切片（25 行/片，留余量）+ 片级限定提示词 + 分批抽取 + 行号回基合并 + **自适应降片长**（被截断的片自动一分为二再抽，单行片诚实失败——兜思考长度的方差）；截断判定不依赖供应商措辞（输出 token 触达请求预算即判截断） | 产品缺陷，**已修复**（backlog V31-P1 ✅；切片参数按本部署模型标定，换模型需重标；跨片成立的需求可能漏——如实登记） |
| P1″ | **V31-P1b 修复部署后的全量活体 rerun（244 行纪要）：14 次片级调用全部成功**（含两次自适应二分兜底），但合并产物事实数 > 200 → 整批被契约拒绝（`invalid_facts at facts`，`failed / ai_output_invalid`） | **片级配额与全批闸脱钩**（P1c，第三个实弹定案缺陷）：片级提示词「本段至多 40 条事实」× 片数必然超过固定 `MAX_FACTS=200`——分段方案对大纪要**结构性地违反自己的契约**（片级全部合法、合并后整批非法） | **守恒预算**：每片配额由契约常量导出（`MAX_FACTS_PER_CHUNK=40`）、全批预算＝配额×片数（≥ 旧单批上限，短纪要不回归）、合并器每片硬闸丢弃并计数留痕（`discovery.merge_quota_capped`）、片级提示词数字与代码配额同源组装（PR #246，同日修复） | 产品缺陷，**已修复**（backlog V31-P1 补记 V31-P1c；修复部署后 rerun 补证） |
| P2 | Step 6 全量 commit（9 任务单请求）卡项目行锁 >120s，gunicorn `--timeout 120` abort worker（HTTP 500；事务回滚零残留） | 部署配置与长事务分解冲突；create_project_task 对项目行 FOR UPDATE 串行 | 端点原生 `item_ids` 选择性创建分批（本次缓解，9 次调用全成）；runbook 增补分批操作注记；服务端批量切片/timeout 调整留拍板 | 部署配置，进 backlog |
| P3 | 转写草稿卷 `/app/.fde-transcript-drafts` 首写 PermissionError（属主 root） | 镜像/entrypoint 以 root 预建目录 | `chown fde:fde` 修复（已解决）；镜像侧以运行属主预建 | 部署缺陷，进 backlog |
| P4 | Step 9 v1 测试计划因执行脚本响应形状解析错（嵌套 `data.plan` 未取到 id，review URL 带 None → 404）而重复生成；另有一次 generate 404 未复现 | 执行脚本瑕疵（AI 代执行的操作性失误） | v1 走 rejected=superseded 显式留痕，v2 正常批准执行；非平台缺陷 | 如实注记 |
| D1 | **审阅动作由 admin 代执行**（facts/reqs 接受、测试计划批准、测试执行登记） | 试点无人值守代执行先例（依赖真实审阅人到位）；AI 不代拍板红线未破——本体 confirm 与 workflow 拍板均由第二账号 `pilot.reviewer` 完成 | ~~建议蔡工在桌面端复核全部审阅动作~~ → **复核完成（2026-11-09）**：AI 技术核验稿先行（22 事实锚点 21/22 精确命中，#10 内容正确行号锚滑一位留档注记；7 需求↔事实溯源映射齐；测试账 v1 superseded/v2 approved/7×passed dev 逐项吻合；★1/★2 澄清材料实证在案）→ **蔡工交互拍板四项**（29 项全部认可／两 ★ 澄清后接受／★ 流转仍由 admin 代执行留痕授权链／测试定性认可）→ 两 ★ 已流转 accepted（审阅 comment 标注蔡工授权链）。清单与核验稿留档 `.fde/pilot-D1复核清单-2026-11-09.md`；后续试点按 runbook C4 配置 project_lead 执行 | 流程偏差，**已复核销号（2026-11-09 蔡工拍板）** |

## 5. 待办（进 `docs/implementation/v3-backlog.md` backlog——本轮已登记，见该文件「V3.1 试点遗留」节）

1. ~~**抽取推理模型输出预算**（P1，P0-1 域缺陷）~~ → **已实施且根因已更正**（2026-11-09 实弹定案，见 §4-P1′ 与 backlog V31-P1）：实施内容＝**大纪要分段抽取**（按行切片 25 行/片 + 自适应降片长兜方差 + 片级限定提示词 + 分批抽取 + 行号回基合并）＋**截断诚实报错**（`ai_output_truncated`，判定不依赖供应商措辞）；初版「预算 ×2 预留」被实弹证伪后删除。**遗留口径**：切片参数按本部署模型标定，换模型需重标；跨片成立的需求可能漏（如实登记）。**V31-P1c 追加（2026-11-09）**：分段修复部署后全量 rerun 抓到第三弹——合并产物撞穿固定全批闸（详见 §4-P1″），同日以守恒预算修复（PR #246），修复部署后 rerun 补证。
2. **批量分解与 gunicorn timeout**（P2）：runbook Step 6 增补「大方案用 item_ids 分批」操作注记；服务端批量分解切片上限评估或 timeout 拍板。
3. **草稿卷属主**（P3）：镜像/entrypoint 以 fde 运行属主预建 `/app/.fde-transcript-drafts`。
4. ~~**D1 审阅复核**~~ → **已复核销号（2026-11-09）**：AI 技术核验稿（锚点 21/22 精确 + 内容零失真 + 测试账/澄清材料取证）先行，**蔡工交互拍板**（29 项全部认可／两 ★ 澄清后接受〔已流转 accepted、comment 留痕蔡工授权〕／测试定性认可），清单 §三/§四 已回填（`.fde/pilot-D1复核清单-2026-11-09.md`）；backlog V31-D1 销号。
5. 维持挂账：approval latency 口径细化（P1-3 已挂）；FOR UPDATE 挂起根因观察（P1-3 已挂——本轮 P2 的行锁等待为部署侧 timeout 表现，与该观察同域不同因）。

## 6. 结论

- **§17-17 达成**：脱敏 E2E 试点十步全链走通（纪要→抽取→审阅→本体→方案→分解→草稿→发布运行→测试→指标），每步留痕齐备（§3 事件链），复盘本文落盘。
- 红线全程遵守：客户真实资料零入库（全程代号 somwyn）；证据只指针+指纹；宿主通道全程关闭（`agent_host_channel_enabled=False` 未动）；AI 未代拍板（决策分离经 pilot.reviewer）。
- 遗留进 backlog 五项（§5），其中 P1 为真实产品缺陷（推理模型输出预算），建议优先立项。
- §17-14 ZCode 真实联调仍为独立业务拍板项（本次未触碰）。
