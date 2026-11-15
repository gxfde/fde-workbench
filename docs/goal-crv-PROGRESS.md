# goal-crv PROGRESS（全仓全面代码审查 · 十域 · 只审不修）

> 任务书：`docs/goal-crv-全面代码审查-任务书.md` v2（评审会纪要：`docs/goal-crv-评审会纪要-2026-11-13.md`）
> 断了换会话：先读本文件接着做，别重做；每做完一项立刻更新。

## 0 任务 0 状态（2026-11-13）

- [x] `fde-delivery-flow` 已调；在途 open PR＝**0**（gh pr list 实测 2026-11-13，无撞车）。
- [x] `git fetch fork`：基点＝**`35ffbea7861476e5ea197487623bd5fb75219b43`**（fork/main 顶；任务书写书时为 `7ac00eb`，其后 #410 d3 文档轮合并推进——以现测为准）。
- [x] 施工面：隔离 worktree `D:/test/fde-wt-crv`（分支 `goal-crv-r1` @ 基点）。**主树实测停在已合并分支 `docs/d3-release-n1-n2-n3`（`4f6c448`，其 squash 即 #410 `35ffbea`；`git diff 35ffbea..4f6c448` 为空＝内容逐字节一致）——绝不在主树起分支，评审会预警坐实。**
- [x] 结构口径：`docs/audit/v3-workbench-inventory.json`（生成于 `3f9a9ce` 2026-11-12 N4 轮，未重跑提取器）：**route 485 / blueprint 52 / table 153 / revision 73**。heads 单头（`b5d9e2f4a7c1`）。零结构变化轮纪律：不重生成。
- [x] mypy：`python scripts/check-python-types.py` → **`OK: no new type errors (baseline 279 occurrences / 104 distinct, current 279)`**（2026-11-13，基线 279/104 不变）。
- [x] typecheck：`npm run typecheck` → exit 0 无报错（2026-11-13）。
- [x] pytest 全量：**本地尝试 1＝环境失败如实登记**（2026-11-13，`npm run test:server` 主树执行——主树内容与基点逐字节一致故对基点有效；collected 3481；59 分钟后段出现 327 errors＋100 failed，根因＝`psycopg.errors.DeadlockDetected` on `UPDATE projects SET org_id = NULL` fixture 清理段两 PG 会话互锁，33% 起自增强恶化；CI 同提交 server-tests **success** ⇒ 归因本地共享 PG 环境非代码）。**基线取 CI 权威**＝main run `43283859901` @ `35ffbea`：**3473 passed + 8 skipped**（773s，isolated PG；与 AGENTS N5 口径逐位一致）。全循环后续一律以 CI run 号为准（任务书 §2.4 既有口径）。
- [x] vitest 总数：**96 文件 / 1100 例 passed**（CI run `43269972808` @ `7ac00eb` 最近绿 desktop job）。注：`35ffbea` 的 main run `43283859901` desktop job 红＝`ai-server-chat.test.tsx`「does not pull history readers down on polling」计时敏感 flake（expected 700 to be 1000；纯文档提交未触该面）——按 §7 归因闸不计连败，本线 PR 撞同测试即重跑。
- [x] AGENTS.md 全文已读；`docs/goal-c8-代码审查.md` §4 已读（冻结区：dispatch 8 态机/package_access/match_breakdown/三隔离/api_catalog；open P2：CR-006/013/021/022/027/028/032；CR-016 failure hooks 挂账；P0 零）。

## 1 开工回执（§2.7，≤10 行）

1. 目标＝全仓十域只审不修代码审查：十域各一轮一 PR（域轮零生产 diff、不落 CHANGELOG），QR- 编号发现入总报告（单一真身），收口轮 E0 终扫＋核锚＋反向验证＋台账回填；止损 14 域轮。
2. 分配表（§2.5）：`fde_api/` 现测 **45 条目**（任务书口径 46 系含 `__pycache__` 之差，以下表为准）全闭合分配，唯一主域＋副域，无「部分覆盖」预留。
3. 轮次顺序＝任务书 r1→r10 不变（高危→低危）；r1 主读面 14 条目最重，拆工作流分片消化。
4. 最大风险＝①并发插队导致锚点漂移（对策：每条 QR 带审查时点 commit SHA）；②r1 权限域凑数压力（防作弊官下注点——宁缺毋滥）；③本地基线跑测与并发会话共库（对策：单进程不加 -n，失败如实登记）。
5. 环境观察（非任务书事项，仅登记）：主树有 4 个未跟踪 docs（goal-crv 任务书/纪要、goal-ks1、goal-sprint 任务书）——非本线白名单文件，不动不提交，归属各自书写线。

## 2 覆盖分配表（§2.5 · 闭合性硬要求 · 2026-11-13 现测 `ls server/src/fde_api/`）

| # | 条目 | 主域 | 副域 |
|---|---|---|---|
| 1 | `__init__.py` | r1 | — |
| 2 | `app.py`（蓝图注册面） | r1 | r10 |
| 3 | `config.py`（Settings 全局） | r1 | r2（AI 键）／r4（费率键） |
| 4 | `errors.py` | r1 | — |
| 5 | `auth/` | r1 | — |
| 6 | `users/` | r1 | — |
| 7 | `orgs/` | r1 | — |
| 8 | `control/` | r1 | — |
| 9 | `projects/`（permissions.py＋events.py） | r1 | r5（成员面写动作） |
| 10 | `health/`（heartbeat/routes） | r1 | — |
| 11 | `system_configuration.py` | r1 | — |
| 12 | `workbench/`（目录/行业模板/调度/种子） | r1 | r5（模块供给 dispatch/plans） |
| 13 | `modules/`（模块目录） | r1 | r5 |
| 14 | `templates/`（行业模板） | r1 | r5 |
| 15 | `ai/` | r2 | — |
| 16 | `quality/` | r2 | — |
| 17 | `plans/` | r2 | r5（编译入 workflow） |
| 18 | `ontology/` | r2 | — |
| 19 | `diagnostics/` | r3 | r4（转化费比例配置交叉） |
| 20 | `registration/` | r3 | — |
| 21 | `commercial/` | r4 | r2（AI 预算闸交叉） |
| 22 | `dispatch/` | r5 | r2（match-ai 交叉） |
| 23 | `workflows/` | r5 | r2（draft_ai 交叉） |
| 24 | `agents/` | r5 | r2（AI 原语） |
| 25 | `solutions/` | r5 | — |
| 26 | `handover/` | r5 | r8（artifacts 存储） |
| 27 | `jobs/` | r6 | — |
| 28 | `mailing/` | r6 | r3（外发面交叉） |
| 29 | `expirations.py` | r6 | — |
| 30 | `extensions.py` | r6 | — |
| 31 | `bridge/` | r6 | r9（只读纪律交叉） |
| 32 | `cli.py`（flask CLI 全集） | r6 | r8（storage-migrate-layout） |
| 33 | `wsgi.py` | r6 | — |
| 34 | `storage/` | r8 | — |
| 35 | `files/` | r8 | — |
| 36 | `documents/` | r8 | — |
| 37 | `transcripts/` | r8 | — |
| 38 | `meetings/` | r8 | — |
| 39 | `evidence/` | r8 | — |
| 40 | `metrics/` | r8 | — |
| 41 | `guidance/`（内嵌使用帮助） | r8 | r2（ai_prompt/redaction 交叉） |
| 42 | `simulation/` | r9 | — |
| 43 | `research/` | r9 | — |
| 44 | `discovery/` | r9 | — |
| 45 | `translator/` | r9 | — |

闭合自检：45/45 分配、每条目唯一主域 ✓；r7＝desktop/src（无服务端条目）、r10＝tests+口径文档（无 fde_api 条目）；单域主读面最大 r1（14 条目）→ CreateWorkflow 分片（≤4 片×≤12 文件）消化，不增轮。桌面侧 `desktop/src` 文件级分配在 r7 轮记录内列全。

## 3 轮次追踪

| 轮 | 域 | 状态 | PR | CI run | QR 增量 | 备注 |
|---|---|---|---|---|---|---|
| r1 | 权限·身份·平台控制 | **完成**（PR #412 squash `45bfaf9`＝main 顶；四 CI 绿；分支双删） | #412 | 43294805436/43294819605 | QR-001～023 | 99 文件逐行；轮记录终稿 |
| r2 | AI 链路与起草 | **完成**（PR #413 squash `1640c75`＝main 顶；四 CI 绿；分支双删） | #413 | 43302689213/43302703278 | QR-024～040 | 73 文件逐行＋横扫 |
| r3 | 公网免注册写面 | **完成**（PR #415 squash `9b26133`＝main 顶；四 CI 绿；分支双删） | #415 | 4331~（双 run 绿） | QR-041～054 | 17 文件逐行＋红线横扫 |
| r4 | 资金敏感面 | **完成**（PR #416 squash `466766c`＝main 顶；四 CI 绿；分支双删） | #416 | 双 run 绿 | QR-055～070 | 16 文件逐行 |
| r5 | dispatch·workflow·agents | **完成**（PR #417 squash `86722e6`＝main 顶；四 CI 绿；分支双删） | #417 | 双 run 绿 | QR-071～098 | 72 文件全域逐行 |
| r6 | 后台作业与队列 | **完成**（PR #418 squash `11a01f6f`＝main 顶；server-tests 三连红后第 4 次重跑绿＝两枚既有 flake 家族轮番〔`test_ai_run_proposal`×2＋`test_task_decomposition`×1，r5/r4 合并 main run 同窗同红佐证非本 PR 引入〕；分支双删） | #418 | 43321731962（重跑 4） | QR-099～108（P2×7/P3×3 合并 11 锚） | 23 文件全域入工作流＋横扫；详见轮记录 |
| r7 | 桌面端（部分覆盖域） | **完成**（PR #421 squash `32aa4182`＝main 顶；tip run 43337038375 四绿〔旧 run 撞 flake 重跑——窗口性〕；分支双删） | #421 | 43337038375 | QR-109～116（P2×5/P3×3 合并 17 锚） | 工作流 4 片 19 文件＋renderer 业务页 ~169 文件部分覆盖申报（BLOCKED §1.1）；run `dwfrun-bc68ec74` |
| r8 | 迁移·存储·数据模型 | **完成**（PR #423 squash `979eeed`＝main 顶；run 43340966362 四绿；分支双删） | #423 | 43340966362 | QR-117～134（P1×2/P2×13/P3×3 合并 ~20 锚） | 工作流 4 片 27＋直审 23（含 guidance 主域补审自纠闭合）＋迁移链脚本核全绿；run `dwfrun-11a05b48` |
| r9 | 评测·模拟·知识 | **完成**（PR #425 squash `14f8b36`＝main 顶；run 43343658556 四绿一次过；分支双删） | #425 | 43343658556 | QR-135～144（P2×7/P3×3 合并 16 锚） | 工作流 4 片 45（run `dwfrun-16ce5af5`，18 条 E1）＋直审 19（translator 6/seeds 11/bridge-poll/research models） |
| r10 | 测试质量与口径文档 | **完成**（PR #427 squash `4634a8d`＝main 顶；head run 43347188448 四绿；分支双删；号段连续化＋P1 统计修正两次自纠随轮） | #427 | 43347188448 | QR-145～147（P2×1/P3×2；6 钉判别力 A/A-/A/C 级） | 主会话直审（无 fde_api 条目）；CI run 链终审 #412~#423 |
| 收口 | 台账回填 | **完成**（PR #429 squash `8e5b1bb`＝main 顶；head run 43350033443 四绿；分支双删；fixup 本行＋收口章自指文本修正随最终小轮） | #429 | 43350033443 | 台账定稿 147 条＝P1×18/P2×100/P3×29、P0×0 | 核锚 147/147 GREEN＋反向验证红→绿＋逐 PR 白名单断言 10/10；不计预算 |

## 4 基线数字（总报告「基线」节同源 · 逐条带命令＋日期）

| 项 | 值 | 命令/来源 | 日期 |
|---|---|---|---|
| 结构口径 | 485 路由 / 52 蓝图 / 153 表 / 73 rev 单头 `b5d9e2f4a7c1` | `docs/audit/v3-workbench-inventory.json`（生成于 `3f9a9ce`） | 2026-11-13 读 |
| mypy | 279 occurrences / 104 distinct（不变） | `python scripts/check-python-types.py` | 2026-11-13 |
| typecheck | exit 0 | `npm run typecheck` | 2026-11-13 |
| pytest 全量 | 本地尝试 1＝环境失败（DeadlockDetected，59 分钟）；**CI 权威＝3508 passed + 8 skipped**（PR #418 run 43321731962 重跑绿，r6 树） | 本地 1 次＋CI run 号 | 2026-11-13 |
| vitest 总数 | 96 文件 / 1100 例 passed | CI run 43269972808（§0 同源）；main run 43332619868 @ 18a4337e desktop 绿维持 | 2026-11-13 |
| 逐 PR 白名单断言 | 10/10 PASS（零越界零生产文件） | gh api pulls/{412,413,415,416,417,418,421,423,425,427}/files vs 任务书 §4 白名单 | 2026-11-13 |

## 拍板回写与修复批立项（2026-11-13）

- 蔡工交互拍板 needs-decision 7 项＋修复批启动共 8 项，**全部按推荐 A**：逐项结论与归属批＝`docs/goal-crv-BLOCKED.md` §5（留痕可推翻）。
- 修复批 **B（QR-024/025）＋F（QR-117/118）连投立项**，任务书＝`docs/goal-crv-fix-批BF-任务书.md`；批 C 解锁（QR-041/042 已拍板）、QR-067 并入批 D、QR-073 归属批 E、新立批 G＝QR-133/134；SNS 403 例外登记随批 B 带落。
- 总报告 §11 仅作引用续注（定稿 v1.0 不回写台账）；各批销号在各自修复轮记录。

## 修复批 B 收口记录（2026-11-13）

- **范围**：QR-024（P1→CLOSED）＋QR-025（随批裁定 P1→P0→CLOSED）＋拍板 §5-5 SNS 关闭态 403 例外登记随带（CLOSED）。
- **实施**：`ai/deepseek.py` 流式 `stream_options.include_usage`＋SSE `usage` 帧解析（缺失/畸形诚实置 `None` 不写 `0`）；`ai/kimi.py` 移除 `/files` 未脱敏原件上传/拉取/删除分支、统一本地提取后经 `build_messages` 脱敏送模型，`config.py`/`.env.example` `kimi_local_docx_extract` 默认改 `True`（兼容存量 `false`）；`test_kimi_client.py` 上传正例钉换代留痕；`AGENTS.md` 红线区与 `goal-crv-r6-后台作业与队列.md` §5-1 落 SNS 403 例外销号。
- **验证**：NEW `server/tests/test_crv_batch_b.py` 12 例＋邻域 149 passed＋变异 M1–M4 全真红→`try/finally` sha256 逐字节还原→复绿＋ruff 绿＋mypy 277/102 不变；PR #436 squash `8adc8e7b` 已合并入 `fork/main`。

## 修复批 F（QR-117＋QR-118 · 2026-11-13 CLOSED）
- **范围**：QR-117（随批升格 P1→P0：富文本键名契约断裂双向修复）＋QR-118（P1：`complete_upload` 唯一键预检/409 映射/重放与中止恢复）。
- **实施**：`documents/rich_text.py` 优先读 `content`、缺失或 `None` 时回退 `text`；`DocumentEditor.tsx` 导出 `plainToRichText`（产规范 `content` 键）与 `richTextToPlain`（同时支持服务端数组回读与包装对象、`content`/`text` 双键）；`files/service.py` 在 `complete_multipart` 前加 `_preflight_upload_target` 预检 404/409，并发 `IntegrityError` 映射 409 `file_name_conflict`，并补 `head(storage_prefix)` 重放兜底与 `abort_upload` 孤儿对象幂等清理。
- **验证**：NEW `server/tests/test_crv_batch_f.py` 6 例＋`desktop/tests/renderer/project-documents.test.tsx` +1 例＋服务端邻域 68 passed＋桌面全量绿＋变异六连 M1–M6 全真红→`try/finally` sha256 逐字节还原→双端复绿＋ruff 绿＋mypy 277/102 基线不变；`docs/goal-crv-fix-批BF-任务书.md` 批 B＋批 F 全量收官。

---

## 修复批 A/C/D/E/G/R7＋收口（goal-crv-fix2 总循环 · 2026-11-14 全收官）

剩余批次七轮一 PR 全合并（`docs/goal-crv-fix2-PROGRESS.md` 逐轮明细）：批 A `#444`/`a8a2c25c`、批 C `#451`/`f4cb5e9f`、批 D `#456`/`b11b8b3f`（唯一迁移 `d4b8e1f6a9c3` 74→75，后被 #455 续接至 76）、批 E `#462`/`30b433f6`、批 G `#463`/`3fc7ddb6`、批 R7 `#466`/`b65f9167`（桌面五项＋便携版 r49）；收口轮＝总报告销号节＋本行＋AGENTS bullet＋统一活体部署三验。每批变异三连/五连全红→`try/finally` 字节还原核 sha256→复绿在案；QR 台账 147 条中 P1 与拍板项全清零，P2/P3 存量按任务书范围不越界。
