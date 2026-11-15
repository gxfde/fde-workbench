# goal-crv 任务书：全仓全面代码审查（十域 · 只审不修）· v2

> 循环名：goal-crv ｜ 写书：2026-11-13，同日经五人评审会修订（纪要：`docs/goal-crv-评审会纪要-2026-11-13.md`）｜ 写书时 fork/main 顶：`7ac00eb`（#409，现测）｜ 性质：审查循环，审查轮零生产代码改动，修复另起轮待拍板

## 0 你是谁、这活为什么干

你是本仓（fde-workbench）goal 循环 crv 线的执行者。这份文档是你唯一的任务来源；中途没人可问，拿不准的写 `docs/goal-crv-BLOCKED.md`（待裁决清单），跳过继续做别的，最后随交付提交。断了、换新会话：先读 `docs/goal-crv-PROGRESS.md` 接着做，别重做；每做完一项立刻更新。

为什么干：2026-11-05 goal-c1–c8 全循环（CR 系列）之后，仓库合入了大量未经全面审查的新面——多客户 M 线（M1–M8）、获客诊断 T-10～T-16、AI 原生化 N3a/b/c/N4/N5/N6、F 线分账 T1–T8、案例学习 L 线、注册面 M2 等。本次做一次全覆盖代码审查，产出分级审查报告＋可核销发现台账（新前缀 **QR-**），供蔡工拍修复批次。**本循环只审不修**：审查轮零生产 diff——「只审不修」约束的是代码改动，不是通报（见 §5 规矩 3 的 P0 升级通路）；修复是否立项、怎么分批，全留报告出齐后蔡工拍板。两个要求打架时的让步顺序：**审得准 > 覆得全 > 推得快**——错报一条 P1 比漏覆盖一个角落严重。

「只允许／不许」违反算失败；「建议」有更好的路可以走，在 PROGRESS.md 记一句为什么。

## 1 我替领导拍的板（蔡工发出前可改，默认即执行）

- 范围=全仓全量十域（十域框架不变，覆盖闭合靠 §3 分配表兜底），goal-c 冻结区复扫抽查不跳过 ｜ 猜的；代价：周期长（预计 11–14 轮）
- 审查与修复分离，本循环零生产 diff ｜ 猜的；代价：高危项多等几轮才修
- 每域一轮＝一个 PR（文档轮）｜ 猜的；**域轮不落 CHANGELOG 节**（评审会修订：防台账分类闸转红），台账由轮记录＋总报告承载，收口轮统一落一节 ｜ 评审会拍板
- 发现编号用新前缀 **QR-**（不续 CR、不续夜审 CR-0xx）｜ 猜的
- r10 测试质量轮只做**静态判别力评估**（只读不执行被审测试），变异演练归修复批轮 ｜ 猜的
- 止损 ≤14 轮＋收口轮不计轮次预算（第 15 轮语义）｜ 猜的
- 基线数字一律任务 0 现测，不承袭 AGENTS「当前状态」行 ｜ 非猜，仓库口径纪律

## 2 任务 0：开工前置与基线现测

1. 调用 `fde-delivery-flow` 技能：查在途 PR，确认本线不与在途轮撞车。
2. `git fetch fork`，记基点＝fetch 到的 fork/main 顶（写书时现测为 `7ac00eb`，以你的现测为准）。
3. **施工面**：隔离 worktree `D:/test/fde-wt-crv`（从基点建，分支 `goal-crv-rN` 按轮递增）；**绝不在共享主树起分支**（主树可能停在别人分支上）。远端分工：只 push `fork`，`origin` 永不 push。
4. 基线现测（数字进总报告「基线」节，逐条带命令＋日期；**本地全量跑测全循环只此一次**，后续一律以 CI run 号为准）：
   - **结构口径**：读 `docs/audit/v3-workbench-inventory.json`（路由/蓝图/表/迁移 rev），注明生成日期；**不重跑** `extract_workbench_inventory.py`、**不重生成** `docs/audit/v3-*` 与 archify——零结构变化轮口径纪律。
   - **pytest 收集数**：`npm run test:server` 全量一轮（**约 60 分钟，只跑这一次**），记 passed＋skipped。注：本循环提交均为纯文档，pre-commit 的全量 pytest 钩子按文件类型过滤会自动跳过——但此说法以当轮实测为准，若钩子仍挂起按 §9 防作弊规矩走 `--no-verify`＋CI 权威（本仓既有配方）。
   - **mypy**：`python scripts/check-python-types.py`（官方闸，核对基线 279/104 是否仍不变）。
   - **桌面**：`npm run typecheck`；vitest 总数以最近 CI 为准并记 run 号。
5. **覆盖分配表（评审会新增，闭合性要求）**：`ls server/src/fde_api/` 现测（写书时为 46 个条目），把**每个条目**（含 app.py/config.py/errors.py 等根级单文件）分配到十域之一，落 `PROGRESS.md` 分配表：每条目**唯一主域**＋可选副域。参考归属（语义不符可调，但闭合不可破）：`control/auth/users/orgs`→r1；`agents`→r5 主（编排执行）＋r2 副（AI 原语）；`quality/plans/ontology`→r2；`diagnostics/registration`→r3；`commercial`→r4；`dispatch/workflows/solutions/handover`→r5；`jobs/mailing/expirations/extensions`→r6；`storage/files/documents/transcripts/meetings/evidence/metrics`→r8；`simulation/research/discovery/translator`→r9；`templates/guidance/modules/workbench` 等语义不明者按实际代码语义定。分配后若单域主读面 >20 文件，拆 CreateWorkflow 分片消化，**不新增轮**；真装不下（闭合性与十域框架冲突）→ BLOCKED.md 顶部上抛，等裁决期间先审不受影响的域。
6. 读 AGENTS.md 全文（红线节与「工作流与陷阱」）；读 `docs/goal-c8-代码审查.md` §4（冻结区＋P2/P3 遗留清单）。
7. 开工回执 ≤10 行（理解的目标／分配表摘要／轮次顺序／最大风险）写进 PROGRESS.md，再动工。

## 3 十域轮次（每域一轮＝一个 PR）

| 轮 | 域 | 审读面（入口锚点，非穷举；闭合以 §2.5 分配表为准） |
|---|---|---|
| r1 | 权限、身份与平台控制 | `projects/permissions.py`（可见性单一权威）、`orgs/`（isolation/access）、`auth/`、`users/`、`control/`、`is_platform_operator`、共享事件记录器 `projects/events.py::record_event` 跨 org 前缀、`test_cross_tenant_isolation.py` xfail(strict) 销号态、`app.py` 蓝图注册面、api_catalog 治理面进出 |
| r2 | AI 链路与起草域 | `ai/`（execute_ai_prompt 单一入口、prompt_registry 版本指纹耦合、model_routing 四道闸 fail-safe）、`quality/`、`plans/`、`ontology/`（业务面＋各自 AI 起草通道）、其余域 AI 调用点横扫、预算闸 `subject_budget_exceeded`（**主审域**）、J-1 提示词白名单、输出端脱敏、ai_call_audits 归因完整性 |
| r3 | 公网免注册写面 | `diagnostics/`（会话/认领/报告/渠道链接/示例面）＋`registration/` 四入口＋G6 legacy：部署闸 404 语义、令牌只存 sha256、限流 fail 模式差异（诊断 fail-closed vs 注册 fail-open）、T-A2 脱敏管线、零外键指向 projects、consent 硬闸 |
| r4 | 资金敏感面 | `commercial/`（计量/席位费/结算/税/票/累计预扣/认证/陪跑）、诊断转化费 ratio 配置面（越界即炸；**主审 r4**，r2 只交叉核对 AI 调用侧）、首单扣费闸、AI 预算闸计量-拦截语义（副审交叉）、按量付费 key 红线 |
| r5 | dispatch、workflow 与 agents 编排执行 | `dispatch/`（8 态机复扫、match_package/match-ai 并列双来源、offers 落库闸、package_access）、`workflows/`（compile_plan_workflow、DAG 校验、human_approval 闸、executor 恢复/取消/写副作用——CR 旧修面回归确认）、`agents/`（run 编排、host_channel 宿主代理、artifact_content）、`solutions/`、`handover/` |
| r6 | 后台作业与队列 | outbox（subject_org keyword-only 调用点全量）、`jobs/`、background_jobs.org_id、worker/scheduler、RECOVERABLE 重试幂等、failure hooks 覆盖面（CR-016 遗留 4 类现核）、`mailing/`（外发面）、`expirations.py`、`extensions.py` |
| r7 | 桌面端 | `desktop/src`：**主进程安全面（评审会新增）——CSP 构建（build-csp）、preload、contextIsolation、协议注册、lcsc-runner spawn**、shared/api-safety.ts 双桥校验面、api-ipc/web 桥、AgentsConsole 终审队列、公开诊断页（consent 客户端硬闸）、brand.ts 单点、contracts、状态管理与回执呈现纪律 |
| r8 | 迁移、存储与数据模型 | `server/migrations/versions/`（单头、CHECK、外键方向、down_revision 链完整性）、models.py 热点（尺寸预算名单）、`storage/layout.py` 五状态机、`files/`、`documents/`、`transcripts/`、`meetings/`、`evidence/`、`metrics/`、org 归属三列回填一致性 |
| r9 | 评测、模拟与知识面 | `simulation/`（服务端全包）、`research/`、`discovery/`、`translator/`、`server/seeds/`（lessons.json 污染阀、诊断答案隔离七钉）、`scripts/bridge-poll.mjs` 只读纪律、`scripts/diagnostic_eval/`、`scripts/simulation/`、⑦出站闸两键与白名单 |
| r10 | 测试质量与口径文档 | 关键钉**静态**判别力评估（选 5–8 个安全/资金/隔离钉，读断言附三段链：变异向量→命中断言→其余为何不拦；**只读不执行**）、xdist 隔离、已知 flake 清点（**仅从 CI run 历史取证，零执行**）、AGENTS/CHANGELOG/README/图纸口径 vs 现测（防陈旧闸现状） |

轮次顺序即上表（高危→低危）；建议可调，PROGRESS.md 记一句为什么。**审读分工纪律**：分配表标了主/副的面，主域负责登记、副域只交叉核对不重复登记（防双判级分歧）。

## 4 界限

- **白名单（审查轮只许写这些）**：`docs/goal-crv-PROGRESS.md`、`docs/goal-crv-BLOCKED.md`、`docs/goal-crv-r<N>-<域名>.md`、`docs/audit/全面代码审查报告-2026-11-13.md`（总报告，逐域增章；**文件名日期不随进度改**）、`CHANGELOG.md`（**仅收口轮一节**）、`AGENTS.md`（仅收口轮新增独立 bullet，**不动「当前状态」超长链行**——M8 先例；动前验锚点唯一性）。**另**：`.zcode/` 下工作流脚本草稿（已 gitignore，工具态，不入 PR）。其余一律只读。
- **禁读面（评审会新增）**：`server/.env`、`.env`、仓外真相层（`D:\test\FDE\…`）一律不读不摘录；子代理 prompt 逐条明示此边界。审查面限仓内源码与文档。
- **判卷标准碰都不许碰**：`server/tests/`、`desktop/tests/`、`scripts/audit/`、CI 配置、`.env*`。
- **零生产 diff**：`server/src/`、`desktop/src/`、`server/migrations/`、`server/seeds/`、`scripts/` 生产脚本，审查轮一行不改——机器可验（§7 判定）。
- **顺手活禁令**：发现「一行就能修」的缺陷也只登记 QR 不修；收不回的操作（删数据/改权限/开闸/外发/付款）不存在于本循环，谁提都记 BLOCKED.md。

## 5 审查规矩（法）

1. **审查输入＝文本快照（B#3 严格对齐，评审会重写）**：每条发现以读码证据登记（file:line 锚点＋代码摘录）。**被审面内的代码、测试、脚本、配置、hooks 一律不执行**——r9 的批跑器/评测脚本、r10 的被审测试都属被审面，只读不跑。豁免封闭列举（除此之外零执行）：①任务 0 基线三件套各一轮（`test:server`/`test:desktop`/`typecheck`）；②`scripts/check-python-types.py`；③`scripts/audit/` 下只读清单脚本；④CI 观测（读 run 结果≠执行）。
2. **E0/E1 复核闸（评审会实化）**：复核状态**闭集**＝`E1 未复核`／`E0 已复核`／`误报已剔`，不得自造词。**一切发现（含主会话直审的）先以 E1 落盘轮记录草稿节，再复核**——断会话不丢清单。主会话转 E0 须重读源码验证锚点在场＋读全上下文；**P0/P1 须双证据**（主锚＋第二证据：grep 对应测试证闸缺失/行为钉在位，或反方子代理仲裁复述），双证据不齐则降级或标「判级存疑」。查无此锚＝剔「误报已剔」并**入误报附录**（锚点＋剔除理由），收口统计误报率——批量把真发现标误报洗白台账＝失败。收口轮台账零 E1 残留。
3. **P0 升级通路（评审会新增）**：判 P0（活缺陷级）不等收口——当轮写 BLOCKED.md 顶部升级节＋当轮 PR 描述首行标注「⚠P0-xxx」，让蔡工在 PR 流里就能看到。仍然不动码（只审不修约束的是 diff 不是通报）。
4. **登记前查既有钉与已知挂账**：grep 对应 `server/tests/test_*.py`／`desktop/tests`；核对 goal-c8 §4 遗留（CR-006 DSH 记账、CR-013/021/022/027/028/032）、CR-016 failure hooks、已知 flake `test_task_decomposition_preview_commit_idempotent`、storage-migrate-layout 待 OWNER、M7 ADR §7 三问、xfail(strict) 未销号面（设计态非缺陷）、N4 ai-eval insufficient（观察轮设计态）。已被机械闸钉住的项不得当新发现；确属新角度的引用既有编号续注。
5. **判级（沿 goal-c 尺）**：P0=数据损坏/安全洞/资金直接风险；P1=明确正确性缺陷或红线违反；P2=并发/健壮性/记账口径/越权纵深；P3=卫生/文档漂移/测试缺口（**每域 P3 上限 3 条**，超出合并同类项；文档口径漂移 ≤P3，误导性数字除外）。零发现＝清白声明，合法（附「为什么零发现」一段＋锚点抽验记录）。
6. **登记格式**：`QR-nnn ｜ P级 ｜ 域 ｜ 锚点 file:line ｜ **审查时点 commit SHA**（评审会新增——锚点随插队漂移，无时点则收口不可复核）｜ 证据摘录（≤10 行，脱敏）｜ 影响 ｜ 建议修复（P0/P1 具体到改哪个函数/加哪个闸）｜ 复核状态（闭集）｜ 处置建议（fix 候选/needs-decision/登记维持）`。**总报告为 QR 单一真身**，轮记录只留「本轮新增 QR 区间」指针，不得双写正文（防漂移家族坑）。
7. **口径数字现测**：报告引用的每个数字带「命令/来源＋日期」；不许把任务书或 AGENTS 的数字当现值抄。
8. **每轮开工必 `git fetch fork`＋PR 前补查在途 PR**：tip 前进了先 rebase 并在轮记录登记插队；PR 前再查一次在途防撞车。CHANGELOG 合并冲突按仓库教训处置（节体错位/口径行整行漂移是家族性坑——合并后按内容锚终扫，别只看无冲突标记）。
9. **代号化与脱敏**：涉客户只用代号（somwyn 等）；摘录出现密钥/token 值一律截断；证据原件不搬进仓（指针＋sha256 纪律照旧）；gitleaks 会扫每个提交。
10. **编排（评审会加上界）**：每域用 CreateWorkflow 起工作流分片审读，**上界＝每域 ≤4 片、单片读面 ≤12 文件**；工作流只出**文本报告**回主会话（发现一律 E1 文本形态），**工作流不直接写仓内任何文件**，落盘由主会话执行；小域主会话直审需在轮记录注明理由（直审发现同标 E1）。等 CI 期间可开下一域审读（流水线），但合并保持串行。

## 6 防作弊

- **不得虚构实测**：报告每条实测数字必须真跑命令；抽查复现要对得上。
- **不得把「已审读」写成没读**：每域报告附**覆盖声明**三档如实列（逐行读／抽查／没读），且**逐行读档 ⊇ §2.5 分配表该域主读面全集**（评审会新增——覆盖下限）。列了不存在的文件或与本域无关的文件＝覆盖造假，失败。
- **不得靠降级躲审查**：「部分覆盖」域全循环 ≤2 且须 BLOCKED 留痕；十域全降级＝循环失败（不管报告出没出章）。
- **不得凑数**：风格偏好当 P1、既有钉钉住项当新发现、同问题拆多条充数，都算凑数。宁收 5 条实的，不收 20 条凑的。
- **不得放松判级**：为让报告好看把疑似 P0 降 P2，失败。拿不准判级时从严登记、处置建议里写「判级存疑」。
- **不得玩弄复核状态**：改词绕「零 E1 残留」、批量标误报洗台账，都算失败（§5 规矩 2 闭集与附录机制是防这道的手筋）。

## 7 每轮模板（任务 N）

- **施工面**：隔离 worktree `D:/test/fde-wt-crv`，分支 `goal-crv-rN`；push 只推 `fork`，origin 永不 push。
- 目标：完成第 N 域审查，总报告增章＋QR 增量登记，PR 合并进 fork/main。
- 步骤：`git fetch fork` 对齐 → 查在途 PR → CreateWorkflow 分片审读 → E1 落盘 → 主会话 E0 复核（P0/P1 双证据）→ 总报告增章（基线引用＋覆盖声明＋QR 单一真身）→ 轮记录 `docs/goal-crv-r<N>-<域>.md`（结论一句话＋QR 增量区间指针＋口径数字变化；**不落 CHANGELOG 节**）→ feature 分支 → push fork → PR → **4 CI job 全绿**（desktop/server-tests/secrets-scan/pseudonymization）→ squash 合并 → ff 本地 main → 删分支 → PROGRESS.md 回写。等 CI 期间可开下一域审读，合并串行。
- **零 diff 判定（评审会重写，弃区间 diff）**：逐 PR 断言 `git diff $(git merge-base fork/main HEAD)..HEAD --stat` 的 changed-files ⊆ §4 白名单闭集（显式包含 `scripts/`、`server/tests/`、`desktop/tests/` 三条禁改路径——出现即红）；收口轮汇总十个 PR 的清单为全链证据。**不使用**「基点..fork/main」区间口径（插队线生产合并混入必假红）。
- PR 描述模板两行：覆盖声明（三档计数）＋ QR 增量区间；有 P0 加首行「⚠P0-xxx」；贴 CI run 号。
- **CI 红归因闸（评审会新增）**：CI 红先查 fork/main 同窗 CI 状态＋本地复跑归因；fork/main 本身红或 flaky 时不计入连败、不降级，等 main 恢复重跑。本线真因连败 3 次→该域降级「部分覆盖」如实登记转下一域，不静默跳过。

## 8 收口轮（不计 14 轮预算）

- 全台账 E0 状态终扫（闭集 grep，零 E1 残留）；**批量核锚**：每条 E0 的 file:line 在当轮 HEAD 可解析（附审查时点 commit 比对）；**反向验证（评审会新增）**：塞一条假锚点→核锚扫描变红→剔除→还原后复绿，贴红绿输出——核锚没证明过判别力之前不算数。
- 误报率统计（误报附录 ÷ 全部发现）；P0/P1 汇总「修复候选批」建议表（每批给范围＋风险＋预估轮次，**不拍板**）；needs-decision 单列；BLOCKED.md 随收口 PR 提交（空的写「无」）；总报告定稿 v1.0。
- **台账回填（唯一落 CHANGELOG 的轮）**：本线一节；AGENTS.md 新增独立 bullet（不动超长链行，动前验锚唯一性——#355 教训）。

## 9 完成条件（两条硬指标，评审会重写）

1. **十域全出章且审读闭合**：`docs/audit/全面代码审查报告-2026-11-13.md` 含十域各一章，每章覆盖声明满足：逐行读档 ⊇ 分配表该域主读面全集；「部分覆盖」域 ≤2 且 BLOCKED 留痕；台账零 E1 残留（闭集 grep）＋收口批量核锚全过＋假锚点反向验证红→绿证据在案。
2. **守约束（逐 PR 口径）**：全部 PR 的 changed-files ⊆ §4 白名单闭集（收口汇总清单在案），且全部 PR 四 CI job 绿；零「本线生产 diff」由逐 PR 断言链证明，不依赖区间 diff。

每条完成判定都要在对话里贴实际命令输出（CI run 号、逐 PR changed-files 断言输出、台账终扫计数、反向验证红绿输出），只说做完了不算。止损：域轮跑满 14 轮即停（收口轮在外），如实汇报已完成域／未完成域／卡在哪。
