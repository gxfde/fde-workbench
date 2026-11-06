# Changelog

本文件记录 FDE Workbench 开源版本的主要变化。版本号遵循语义化版本规范；首次公开源码版本为 `v0.1.0`。

## [未发布] — CR-032 写路径清偿：调研注册对象类型接入创建/导入/表单面（2026-11-07）

### 行为变更（纯桌面零服务端零迁移零路由；桌面变更 ⇒ 便携版重打包挂账）

- **注册对象类型可新建**：项目调研对象树的「新增」区为 T-O2 注册表登记的对象类型（`kind=subject_type ∧ status=active`）提供「新增X（根级）」入口——注册类型无父级规则，创建为根级对象（不带上级）；内置五类的父子层级流程零变化。
- **导入与表单承接**：调研对象批量导入对话框的「对象类型」与调研表构建器的「调研主体」下拉补注册类型选项（标注「注册类型」）；顺带修复注册类型主体下「调研主体」下拉空白显示的问题（选中值无匹配选项）。
- **数据源与降级**：选项来自既有只读路由 `GET /api/v1/projects/{id}/ontology/relation-types`（客户端过滤 active 行，draft/retired 不出现）；注册面拉取失败静默降级为仅内置五类——值域权威始终在服务端创建闸门。
- **边界（偏差注记）**：调研定义编辑器与行业模板编辑器本轮未接——全局注册类型没有项目内只读路由可消费，随服务端路由补口后再接。
- 测试：vitest +4（根级创建流不带上级／非 active 行过滤／导入与构建器选项／树按钮两态）。
## [未发布] — V3 两级注入全链路：契约 references 组 + 消费面两层接线（#8，2026-11-06）

### 契约扩组（技能结构化契约 v1 §2.6，零迁移零路由零新表）

- NEW `references` 必读引用组：`required_reading`（执行前必读，硬前置）＋ `authoritative_sources`（冲突裁决，软引用）。语义锚＝`fde-package-verify` 手写规则「README 冲突以 README 为准」——把「权威在技能正文之外」的约束从散文升级为机器可读引用。
- 键空间闭合枚举同步扩组（`test_skill_contract` `CONTRACT_GROUPS` +references），B#37 静态闸验证通过。

### 消费面两级接线（mcp_gateway）

| 级 | 工具 | 内容 |
|---|---|---|
| **第一级**（选技能前） | `skill_list` | item 带 `when_to_use` 摘要（取自 `use_boundaries` 组；未填不带键——缺省＝不误导） |
| **第二级**（读正文前） | `skill_read` 首页（offset=0） | 带 `required_reading`/`authoritative_sources` 引用清单；**续页不带**（同一正文延续，重复是噪音）；良构校验（list[str] 全非空才出，不猜不放宽） |

- **引用不携带内容、不产生新读取权限**：引用是仓库内相对路径，消费方用既有只读工具自行读取；`skill_list`/`skill_read` 工具 schema 静态钉住不变。
- **T-S2 计数语义不变**：首页带引用不改变「仅首读计一次」。
- 4 个 runbook 按「平铺点路径 + JSON 数组字面量」回填 `use_boundaries`+`references`（**种子 13 条维持 B#36「不回填」裁决不动**）。

### 测试

NEW `server/tests/test_skill_readbefore.py` 5 例；**变异三连逐一转红**：列表不带摘要／续页也带引用／坏引用透传。技能域回归 25 passed。

### 口径

pytest **2056 收集 = 2050 passed + 6 skipped**（+5）／vitest **858**（零桌面改动，校正自 B#30-A 基线 839——main CI run 42251482875 实测 858，其间 #163/#164 并发 +19）／mypy **279**（不变）／蓝图路由 **304**（不变）／业务表 **105**（不变）／api_catalog ENTRIES **94**（不变）／迁移头 `b2e8f4a6c9d3`（36 rev，不变）。

> 口径基线取 main HEAD `5b47c07` CI run 42251482875 实测 2045 passed＋6 skipped＝2051 收集；本地 collect 2056＝2051+5 交叉对齐。

### 同轮核销

- 借鉴总览 #36/#37 四处「✅ 已实施 · 未提交（b36b37 轮）」过时状态核销为「✅ 已实施 · #140」（#140 已于 fork/main 合入）。

## [未发布] — V3 B#30-A 门禁证据漂移呈现：同源换版只读复核（2026-11-06）

### 行为变更（零迁移零路由零新表；server 变更 ⇒ 合并后 rebuild 三镜像；桌面变更 ⇒ 便携版重打包挂账）

- **清单项级「前置复核」**：门禁清单项引用的证据（`evidence_id`）若被**同一 `source_uri` 上更新的 hash 行**（T-G1 换指纹并存语义）超越，门禁视图序列化对该项输出 `evidence_superseded: true`。检测有界——只比该 uri 的证据登记行集，不扫全表。
- **呈现即提示，四不动**：状态机、claim_status、拍板有效性、AI 权限一律不变；不携带新行指针（跳转走证据登记簿面）；重核与否永远由人决定。
- 三调用点接线：门禁列表、提交证据响应、拍板响应均携带该标记；桌面 `GateBoard` 对旧服务端载荷（无该键）保持兼容，换版项呈现「证据已换版」警示 badge（title 说明四不动边界）。
- 测试：pytest +2（同源换版翻转／无重采不误报；变异摘检测红→还原绿）＋ vitest +1（badge 呈现／旧载荷无键不受影响）。
- 顺带修复：#155 合并在 AGENTS.md 遗留的冲突标记残渣（`=======` 段＋commit 尾巴＋#85 条目丢换行）。
## [未发布] — V3 只读技能中心（B#32 A 面）＋ 借鉴总览台账漂移校正（2026-11-06）

### 只读技能中心（B#32 A 面——交互拍板⑤A，零迁移零新表零依赖）

- NEW `server/src/fde_api/control/skill_center.py`——**DB 权威只读浏览面**（取内容域、弃文件目录形态：技能权威已在 `skill_definitions`/`skill_versions`，另起文件系统 provider 会出现两个权威且漂移不可测 ⇒ 不引文件目录、不引依赖 ⇒ 无供应链闸）。
- 新增 2 条只读路由：`GET /api/v1/skills`（可选 `?scope=public|personal`，非法值按空处理——不猜不放宽）、`GET /api/v1/skills/<skill_id>/document`。
- **权限面与既有 `mcp_gateway._skills` 同尺**：`status=published`（draft/in_review 未过发布闸不外泄）＋ `scope=public` 或 `owner=当前用户`；不可见即 **404**（不区分「不存在」与「无权」，避免探测）。
- **不消费计数**：`skill_read` 读出指南才计一次消费（T-S2 语义），本面是治理浏览面（人看目录、下载文件）——浏览一次就写一条 `skill_used_*` 会虚增「已消费」记录。
- 有界返回：列表 200 条上限＋正文 512KB 上限（超限拒绝，不截断）。
- NEW `server/tests/test_skill_center.py` 5 例；**变异四连逐一转红**：去 `status` 过滤（draft 泄露）／去 `owner` 限制（他人个人技能泄露）／浏览写消费计数（计数 +1）／正文面返回空正文。

### 借鉴总览台账漂移校正（v1.10）

- `docs/audit/开源项目借鉴总览-2026-11-05.md` §1 P1 段**状态列九条按 `fork/main` 实况回写**（#7=#150／#12+#31=#154+#157／#13=#153+#158／#14=#159／#8+#32=#138＋本轮 A 面／#11 落点设计已落／#30 立项 #144）——此前六条仍标「⬜ 待实施」而实际全部已落地。
- §5.1 已兑现表补五条缺项；§5.2 标注顺位 1/2/3 **已全部兑现**；§5.4 标注剩余可排期项（#30 A 面／#8 两级注入 `readBefore`／#11 随 #23 解封）。

### 口径

pytest **2049 收集 = 2043 passed + 6 skipped**（+5）／vitest **838**（不变）／mypy **279**（不变）／蓝图路由 **304**（+2）／业务表 **105**（不变）／api_catalog ENTRIES **94**（不变）／迁移头 `b2e8f4a6c9d3`（36 rev，不变）。

> **口径校正**：前值「2014 收集」系 #159 轮本地推算、未计 #158＋#160 并发增量——本轮基线取 main HEAD `d467fac` CI run **42241563180** 实测 2038 passed＋6 skipped＝2044 收集，再加本轮 +5 ＝ 2049。**并发轮期间本地推算不可作基线**（#129/#131/#157 之后第四次同类校正）。

## [未发布] — V3 到期治理收口：B#13-C API confirmation 主动超时 + B#13-D 跨域只读投影（2026-11-06）

### B#13-C（零迁移零路由零新依赖；server 变更 ⇒ 合并后 rebuild 三镜像）

- **derived state 裁决落地**：`OperationEvent` append-only 完整保留——到期不追加 expiry event、不 UPDATE/DELETE 原 request 行、不建后台 sweep（该域无清理副作用，持久化过期事实零行为收益，反而引入系统 actor 与事件生命周期两个新语义面）。
- `control/api_actions.py` 新增唯一窗口常量 `CONFIRMATION_WINDOW`（15 分钟）与到期谓词 `confirmation_expired`；pending 列表 / `action_status` / `decide_action` 三处此前各自手写的 `timedelta(minutes=15)` 全部收敛到该原语。
- **边界统一**：从严格 `<`（恰等于 15 分钟仍有效）对齐为 `deadline <= now`（恰等于即过期），与立项合同 §3.3 / B#13-B 上传会话 / 审批域同拍。
- 到期行为：过期确认从 pending 列表筛除、status 返回 `expired`、迟到 decision 409 `action_expired` 且**零事件/目标副作用**（不落 started/finished、不触碰目标对象）；started-but-uncertain 防重放保护**优先于到期**（不报 expired、绝不重放），finished replay 越窗仍有效；auth_version/fingerprint/password 防线原位不动。
- NEW `server/tests/test_api_confirmation_expiry.py` 7 例（常量值钉/谓词边界/窗口内全待/过期全拒+零副作用/uncertain 优先/越窗 replay/窗口常量放大变异证明三路径+投影同源）。

### B#13-D（零 DDL；+1 路由）

- **NEW `fde_api/expirations.py`**：跨域到期只读投影——服务层只读 union + admin-only `GET /api/v1/expirations`，输出立项合同 §2 六字段逻辑视图（`domain`/`object_id`/`deadline_at`/`state`/`due`/`expiry_action`）。不建 SQL view 的决定性理由：api_confirmation 截止时刻是派生值，SQL view 会把窗口规则复制成第二权威；服务层直接复用 B#13-C 同一常量与谓词。
- 四域接入：automation_approval（pending）/ upload_session（uploading）/ api_confirmation（awaiting_confirmation，derived）/ dispatch_offer（offered，`offer_deadline` 派生）；`due` 统一按 `deadline_at <= now`；dispatch 原生转换器保留严格边界（边界瞬间读数先行一拍，只读不写回）。
- 权限与面：admin-only（运营看板视角；触发条件=用户明确指示实施）；`limit` 默认 100 上限 500，排序 `(deadline_at, domain, object_id)` 稳定升序，`domain`/`due` 过滤；只投影元数据（不外泄确认 body/审批 arguments/对象键/客户资料）；`expiry_action` 只是符号名指针不执行；**不进 api_catalog**。
- NEW `server/tests/test_expirations_projection.py` 8 例；审计清单重生成：route **302**（+1）/ blueprint **40**（+1）；105 表、迁移头 `b2e8f4a6c9d3`（36 rev）不变。

### 口径

pytest **2029 收集 = 2023 passed + 6 skipped**（CI 实测；本地专项 15 例 + 邻域 89 例全绿）／mypy 基线 **279** 不变／蓝图路由 **302**（+1）／业务表 **105**（不变）／迁移头 `b2e8f4a6c9d3`（36 rev，零迁移）。

## [未发布] — V3 B#14 executor 对抗性测试直补（2026-11-06）

### 对抗钉（纯测试轮，零迁移零路由零业务代码）

拍板盘点五夹具族：①固定种子模拟／③迟到拍板／④双 definition_version 并存 **已由现有 39 例覆盖**；②强杀不丢已确认／⑤节点独立事务失败恢复 **为缺口**。按拍板 opt A「直补对抗钉」实施（不做 2–3 周决策逻辑纯函数重构，与总览「先攒真实故障史」裁决一致）。

- **NEW `server/tests/test_workflow_executor_adversarial.py` 4 例**：
  - **强杀族**：进程级死亡（worker_lost 收口）**不得抹掉已 succeeded 节点的产物**（逐位相等）；resume **不重跑已确认读面**（外呼次数只 +1）。
  - **tx B 崩溃族**：settle 落表自身崩溃 → 节点悬 running → 恢复重跑时**幂等键不变**（同 action id ⇒ api_actions 层去重 ⇒ 不二次外呼）＋**attempt 保留**（「本次尝试已发生」的事实不被恢复路径抹掉）。
  - **恢复底座钉**：`_recover_interrupted` 只把 running 放回 pending，**不动 succeeded**。
- **变异双红**：恢复路径抹掉 succeeded 产物（2 例转红）／去幂等键守卫 + 派生含 attempt（tx B 族转红）——等价变异（单改派生式因守卫短路）已识别并改用可辨组合。

### 口径

pytest **2014 收集 = 2008 passed + 6 skipped**（+4）／mypy **279** 不变／ruff F401,F841 全绿／蓝图路由 **301**（不变）／业务表 **105**（不变）／迁移头 `b2e8f4a6c9d3`（36 rev，不变）／vitest 不变（零桌面改动）。

## [未发布] — V3 拍板收口：B#30-B=opt1 + 提示词卫生差距②静态钉（2026-11-06）

### 交互拍板收口（①零代码 + ②纯测试轮，零迁移零路由）

- **B#30-B 门禁终态回退语义＝opt1 维持现状**（交互拍板）：passed/conditional_pass 终态不可逆维持（重交 409 现状不变），**零代码零迁移**——回退通道引入状态机新分支+桌面回退 UI（≈1–2 人日），当前无真实场景推动，错误拍板走线下 OperationEvent 留痕追溯；opt2/opt3 保留候选、真实诉求出现时重开。backlog B#30 行与状态段已回写。
- **提示词卫生契约差距②＝补静态钉**（交互拍板）：NEW `server/tests/test_prompt_entrypoint_gate.py` 3 例——受闸入口（`execute_ai_prompt`/`direct_tool_completion`/`direct_provider_completion`/`_degraded_direct_result`）的 `system_prompt` 实参来源 AST 允许名单（字面常量／形参直传链变量／`_workbench_system_prompt()` 白名单组装函数），域外形态即红；附钉定义落点锚（防定义漂移出受闸文件面）＋ **kwargs 透传禁令（防绕过 AST 形态判定）。**变异双红**验证：chat 接 `prompt` 变量进 system_prompt／structured 改 `**payload_kw` 展开——逐一转红。
- 同日另三项拍板（T-A2 分层失败语义／T-A2 词典=种子文件／T-A7 谈判稿=复用 solution 版本行）由并发会话回写于主树，与本轮不重叠。

### 口径

pytest **2010 收集 = 2004 passed + 6 skipped**（+3；**口径校正**：前值 2013 为本地推算重复计并发轮增量，CI run 42223701893 实测为准）／mypy **279** 不变／蓝图路由 **301**（不变）／业务表 **105**（不变）／迁移头 `b2e8f4a6c9d3`（36 rev，不变）。

## [未发布] — 桌面实施轮②：CR-032 桌面调研 subject_type 读路径承接 T-O2b 注册类型（2026-11-06）

### 桌面（零迁移零路由零服务端改动；无需 rebuild / alembic / 重打包）

- **读路径守卫放宽（CR-032 核心）**：桌面调研 DTO 守卫此前把 `subject_type` 钉死内置五类枚举（`RESEARCH_SUBJECT_TYPES`），而服务端 T-O2b（#83）已把物理边界放宽为码格式 `^[a-z][a-z0-9_]{0,59}$`（迁移 `b5d9e3f7a1c6`）＋注册表 active 行——**注册类型（如 `vendor`）落库后，桌面 `ResearchWorkspace` 读路径校验即失败 → 整个调研 tab「数据格式异常」、项目正常数据全不可读**。修法：`ResearchSubjectType` 放宽为 `string`，新增 `isResearchSubjectType`（与 DB CHECK 同尺码格式守卫）承接读路径（`isResearchSubjectDto`／`isResearchFormDto`／`isResearchImportPreviewDto` 三处五类守卫改走同尺）；内置五类仍由 `RESEARCH_SUBJECT_TYPES` 承载写路径（创建/下拉/父子树，**写路径注册类型选项＝后续轮**——须接 ontology 只读 API＋父子约束，本轮不扩张功能面）；展示走新增 `researchSubjectLabel`（内置取中文标签、注册码原样回显，杜绝缺标签拒载/乱显示）。
- **测试 +2 例**：注册类型码（`customer`/`supplier_x`）读路径承接＋非法规码（`9Bad`/`Customer`/超长/连字符）仍拒；既有用例同步（`"nonsense"` → `"9Bad"`）。

### 口径

- 桌面 vitest **838/838**（基线 **836**＝CI run 42223701893 实测 ＋2；桌面纯前端轮，零服务端改动）；pytest / mypy / 表 / 迁移 / 路由 / ENTRIES 全部不变。 (docs(v3): 校正桌面实施轮② vitest 口径 833→838（基线随 #156/#157 插队上移，现测为准）)

## [未发布] — V3 提示词卫生 J 系接线：B#12+B#31 判据落地（2026-11-06）

### 契约判据接线（零迁移零路由零新依赖；server 变更 ⇒ 合并后 rebuild 三镜像）

- **NEW `server/tests/test_prompt_hygiene_jseries.py` 5 例**（承接《外部文字禁入与原件派生分离契约-v1.md》§5 可断言判据；组织同 B#4 purity 静态测试）：
  - **J-1 静态钉**：全仓 system role 消息组装点 AST 枚举——content 必须是「常量／常量名／形参直传链／已登记例外」四形态之一，域外新增即红（PR 须对照契约 §2 表登记）；附钉 executor skill 节点 `system_prompt` 仍＝治理面发布 `instructions`（白名单④不旁路）。
  - **J-2 行为钉**：四类「不可信资料」工具结果必须带结果级 `source` 标记——`file_read`/`help_fetch` 既有；**`lcsc_search`/`lcsc_runs_read` 本轮补 `untrusted_storefront_content`（契约 §4 差距①闭合，P-3 标记腿全满足）**；附钉 lcsc run 返回体单一形状源（`_serialize`）。
  - **J-3 静态钉**：`documents/ai_content` 的 system 提示词是纯常量构造——payload/请求内容变量泄漏进构造即红。
- **变异三连**逐一转红：lcsc 标记删除／executor 接 prompt 变量／system 拼接 payload。
- **差距②开放保留**：`direct_tool_completion` 形参面无静态闸（形参直传链上游来源已逐点登记于测试 docstring；封堵须另轮）。

### 口径

pytest **1999 收集 = 1993 passed + 6 skipped**（+5）／mypy **279** 不变／蓝图路由 **301**（不变）／业务表 **105**（不变）／迁移头 `b2e8f4a6c9d3`（36 rev，不变）。

## [未发布] — V3 桌面实施轮①：B#28 门禁 revision CAS 桌面接线（2026-11-06）

### 服务端 + 桌面（零迁移零新路由；server 变更 ⇒ 合并后 rebuild 三镜像 + alembic 幂等）

- **服务端**：门禁视图（`GET …/projects/{id}/gates`）与拍板响应回传 `revision`（≡ 既有 `gates.version`，**零新增列**；与 `lifecycle_version`（语法代际）刻意分离——后者不随拍板推进）。
- **桌面 `GateBoard.tsx`**：拍板请求原样带回 `expected_revision`（B#28 CAS 此前**服务端已就位而桌面从未启用**——桌面不知当前 revision）；409 `gate_revision_conflict` 如实呈现「本次拍板未生效；面板已刷新」并自动刷新面板（人可基于新状态重拍，不静默覆盖前写）；旧服务端载荷缺 `revision` 时不带该键（缺省＝旧客户端兼容）。
- **测试**：服务端 +1 钉（视图 `revision` ≡ 行 `version`，且用视图值拍板可生效、revision 推进 +1）；桌面 +3 例（带入 `expected_revision`／旧载荷不带／409 冲突如实呈现并刷新）。

### 口径

- pytest **1986 收集＝1980 passed＋6 skipped**（+1）／vitest **828/828**（+3）／mypy 基线 **279** 不变／105 表／迁移头 `b2e8f4a6c9d3`（36 rev，零迁移）／蓝图路由 **301**／api_catalog ENTRIES **94**。

## [未发布] — V3 回滚轮落定重核（§三 逐行复测＋审计清单回刷＋CR-003 销号）（2026-11-06）

### 文档与脚本（零业务代码零迁移零路由零桌面功能改动；无需 rebuild / alembic / 重打包）

- **`docs/implementation/v3-迁移进度对照-fde-v2建议-2026-11-04.md` 第七轮同步**：§五-7「并发在途品牌·回滚轮」**结清并翻转**（回滚轮落定为 #132＝155 文件（67 纯增／54 改／33 二进制／1 删）**零 server 改动零迁移改动**；原拟撤的 T-W7/T-I1/T-C1 四件套实测全部存续；fork/main 无任何 revert 提交）→ **§三 全量 DONE 判定逐行复测无一被推翻**；新增 §五-9（审计清单落后 1 条 ＋ 抽取脚本蓝图硬编码漏登）与 §十三（第七轮增量记录）；§二 P1④／§四 C-4 补「skill_read 分页已实施」当前态标注。
- **行号锚修 6 处**（基线 fork/main `d3adf1c`）：`workflows/models.py:157→:163`、`executor.py:694→:701`、`executor.py:1402-1413→:1373-1413`、`definition_service.py:118→:119`、`SkillVersionsPage.tsx 355→356 行`、§三 T-S1/S2 交叉引用 `§五-3→§五-5`——**前三处系第五轮声称「已修正 8 处漂移」而正文未落地**（「声称已修 vs 正文未改」），本轮当场补正。
- **主报告 §20 实施跟踪注记补齐条目 9–19**（此前停更于 T-S1）：T-S2／T-W6／T-O4b·T-O4 桌面／T-G2·T-D1／T-C1·T-I1／T-W7·T-UI1／T-J2／P3 四项定案／P0 先行批 B 系列／五份纯文档／UI-UX 轮·B#9，并附「注记补齐说明」记录挂账前提与消解依据；`docs/goal-c-代码审查台账.md` **CR-003 随之销号**。
- **审计抽取脚本补登 ＋ 三清单回刷**：`scripts/audit/extract_workbench_inventory.py` 的 `BLUEPRINTS` 硬编码列表补 `fact_chain_blueprint`（按 `app.py` 注册序紧随 `evidence_blueprint`）→ 重生成 `docs/audit/v3-route-inventory.csv`（+1 行＝新路由）与 `v3-workbench-inventory.json`；DB CSV 零变化。
- **AGENTS.md**：工作流节新增「审计清单刷新有前置条件（`BLUEPRINTS` 硬编码列表须随蓝图增删同步登记——同一坑两次：T-J2/CR-027、#145 `fact_chain_blueprint`）」；补本轮 bullet；CR-003 挂账措辞更新为已销号。

### 口径（现测，基线 fork/main `d3adf1c`）

- 105 表 / 迁移头 `b2e8f4a6c9d3`（36 rev，#131~#145 全域零迁移）/ api_catalog ENTRIES 94 不变；**蓝图路由 300→301**（#145 +1：GET `…/projects/{id}/execution-facts`，不进 api_catalog）；pytest **1985 收集＝1979 passed＋6 skipped**／vitest **825**／mypy 基线 **279**（后三项取 #145 CI run 42183340134 实测）；审计脚本同源复测＝route 301 / blueprint 39 / table 105 / rev 36 / heads=[b2e8f4a6c9d3]。

## [未发布] — V3 回执 DSL 一期（B#7，2026-11-06）

### 契约层（零迁移零路由零新表零依赖）

- **NEW `server/src/fde_api/agents/receipt.py`**：回执 DSL 是**外部可写结构**，故按白名单逐字段校验——**未知字段一律拒绝**（不静默丢弃、不透传；否则外部多写一个键即绕过闸门）。容量上限对齐既有审批材料 **64KB** 语境（超限拒绝不截断）。
- **两种人工介入动作**：
  - **`ask`**＝请求人工拍板 → 落既有 `automation_approvals`（**零新表零新路由**，密码确认闸现成）：幂等＝`request_key` 由「项目＋能力＋规范化回执」派生并复用既有 pending 审批（崩溃恢复不重复建单）；能力须在 `CAPABILITY_REQUIREMENTS` 白名单且发起人**当下**仍具备；**风险档固定 4**（人工门＝保守高险，诚实标注）；敏感键拒绝入审。
  - **`later`**＝请求延后复查 → 落**最小到期挂点**（`operation_events`，只表达 `due_at` 时点结构）。
- **边界声明**：later **不实现**统一到期表／主动超时扫描／统一 cron 计算——那是 **B#13** 的 `deadlines()` 纯函数职责，本条不越界（B#13 落地时把 `due_at` 纳入其到期表即可，无需改动本条）。
- DSL 不可解析 ⇒ 走 **B#2 降级路径**（业务动作可能已执行，不能重做 ⇒ 落独立终态 `succeeded_but_receipt_invalid`，拒绝同键重跑）。
- **命名隔离**：既有 `AgentResult.receipt_state` 是**产物清单扫描**语义，与本条**人工介入动作**语义正交，两套并存不互相覆盖。
- **实现要点**：`action` 用 **discriminated union**（按 `kind` 判别）——普通联合会逐分支尝试并汇总**所有分支**的错误（含无关分支字段名），错误信息冗长且误导；错误路径取完整 loc（`action.ask.bogus`）而非只报顶层。

### 测试

- NEW `server/tests/test_receipt_dsl.py` 8 例：顶层与 action 双层未知字段拒绝／非对象与未知动作拒绝／容量上限拒绝不截断／指纹顺序无关稳定／ask 建单与幂等复用＋风险档 4＋sha256 指纹／未知能力拒绝／敏感键拒绝／later 挂点字段闭集且无主动扫描器／delay 越界拒绝。
- **变异五连**逐一转红：未知字段改为忽略／容量上限失效／敏感键扫描失效／ask 幂等失效／later 越界校验失效。

### 口径

pytest **1994 收集 = 1988 passed + 6 skipped**（+8）／vitest **828**（不变，回执 DSL 轮零桌面改动）／mypy **279**（不变）／蓝图路由 **301**（不变）／业务表 **105**（不变）／api_catalog ENTRIES **94**（不变）／迁移头 `b2e8f4a6c9d3`（36 rev，不变）。

## [未发布] — V3 门禁前置复核与回退留痕立项（借鉴 B#30 消费）（2026-11-06）

### 文档（零代码零迁移零路由；无需 rebuild / 重打包）

- **NEW `docs/architecture/门禁前置复核与回退留痕立项-v1.md`**：**A 面＝前置清单证据漂移自动复核呈现**（T-G2 同构：同 `source_uri` 新 hash 证据行超越清单项已引用 evidence ⇒ 项级 `evidence_superseded: true` 只读呈现，呈现即提示四不动〔状态机/claim_status/拍板有效性/AI 权限〕，零迁移可实施）＋**B 面＝拍板回退通道与留痕合同**（现状 `passed/conditional_pass` 终态不可逆、`failed` 有重交回环；三选项登记 opt1 维持现状／opt2 受限回退〔仅 conditional_pass 可退、passed 不退、`gate_rolled_back` reason 必填〕／opt3 只读复核队列——**是否开放终态回退＝业务拍板项，本文不预支裁决**）。不做清单：不动 evidence 不可变性／不做定时自动重核／AI 不代拍板不代回退。现状行级锚：状态机 CHECK 五值／重交闸／OperationEvent from→to 留痕。
- backlog B#30 行回写（A 面随下次 gate 轮、B 面须拍板；立项≠实施授权）；AGENTS 补轮次 bullet。

### 口径

- 零代码零迁移——pytest 1981 收集（1975 passed + 6 skipped）/ mypy 279 / vitest 791 / 105 表 / `b2e8f4a6c9d3`（36 rev）/ 路由 300 / ENTRIES 94 全部不变。
## [未发布] — V3 B#13-B UploadSession 主动到期与 multipart 清理（2026-11-06）

- 过期上传会话在 `expires_at <= now` 时由服务端行锁收敛为 `expired`；迟到分片签名/完成返回 `upload_session_expired`，不触碰对象存储、不创建文件版本；分片签名 TTL 不超过会话剩余时间。
- 新增 `file.upload.cleanup` outbox/worker 清理链：scheduler `skip_locked` claim，worker 在数据库事务外执行 multipart abort，再独立事务落 cleanup 账本；`multipart_upload_not_found` 视为幂等成功，其他错误保留稳定错误码并沿 recoverable job 退避。
- 复用既有 `UploadSession.expired/expires_at`，零迁移、零新路由、无人工外呼；B#13-C API confirmation 与 B#13-D 跨域只读投影仍 PROPOSED。
- 测试：新增 B#13-B 专项 8 例，连同上传/worker/reconcile 邻域共 65 passed；PR-head CI 最终全量 1996 passed + 6 skipped（2002 收集）；mypy 279/104、ruff 全绿。

## [未发布] — V3 门禁判据实施落点设计（借鉴 B#11 消费）（2026-11-06）

### 文档（零代码零迁移零路由；无需 rebuild / 重打包）

- **NEW `docs/architecture/门禁判据实施落点-v1.md`**（承接 B#21/B#22 评测协议冻结文本，B#22「实施落点=B#11」清偿）：**裁决＝三锚四反例的宿主＝B#23 夹具的「评测器元验证层」**（验证打分检查器本身：do_nothing≈0/ literal≤0.2/ oracle≥0.95＝检查器认得出参考解）；门禁面落点已随 #131 冻结（G9 `exit_condition` 含「三锚四反例全过」，钉 6 守护）；pytest 模板落点＝四条件解封后 NEW `server/tests/test_eval_criteria_harness.py`。**元验证语义（本文定义）＝评测器可用于「验收线达成」判定前必须先过元验证夹具——锚点不落位/反例漏抓 ⇒ 输出不得作 G9 判定输入（`insufficient_data` 不变）**。含被验证对象诚实盘点（当前仓内无打分型检查器——判据现为算分器预置合同）、逐判据落点表 11 行、阈值校准纪律。判据语义零新增零改写、种子零改动。
- backlog B#11 行回写（落点设计已裁，实施随 B#23 夹具期，设计≠实施授权）；AGENTS 补轮次 bullet。

### 口径

- 零代码零迁移——pytest 1981 收集（1975 passed + 6 skipped）/ mypy 279 / vitest 791 / 105 表 / `b2e8f4a6c9d3`（36 rev）/ 路由 300 / ENTRIES 94 全部不变。

## [未发布] — V3 提示词卫生与工件血缘契约（借鉴 B#12+B#31 消费）（2026-11-06）

### 文档（零代码零迁移零路由；无需 rebuild / 重打包）

- **NEW `docs/architecture/外部文字禁入与原件派生分离契约-v1.md`**：外部文字禁入提示词（B#12）＋原件/派生分离（B#31）两层合一契约。**现状实测＝主干已有机闭合**（全系统恰四处 system 组装点全部落在内部权威白名单内；外部数据一律 user/tool 角色或结构化 JSON payload；原件只存指针＋sha256；`captured_from` 封闭枚举＋`ai_request_id`/`revision_id` 血缘在位）；契约把散落防线收拢为 **P-1~P-5（提示词层）＋A-1~A-5（工件层）**十条规则＋封闭枚举白名单，差距如实登记（lcsc_* 结果无 source 标记／`direct_tool_completion` 形参面无静态闸／「生成默认不视作已审」无统一谓词／个人技能 owner 自治边界），附四条可断言判据（J 系，接线仍 PROPOSED）与触发式复查机制。纯我方独立设计，零第三方正文/结构化表达引用（AGENTS 红线第 8 条履行）。与 B#3／外部模型依赖契约 M 系／W-8 四层分工互不覆盖。
- backlog B#12+B#31 行回写（契约落盘、J 系接线仍 PROPOSED）；AGENTS 当前状态补轮次 bullet。

### 口径

- 零代码零迁移——pytest 1981 收集（1975 passed + 6 skipped）/ mypy 279 / vitest 791 / 105 表 / `b2e8f4a6c9d3`（36 rev）/ 路由 300 / ENTRIES 94 全部不变。

## [未发布] — V3 B#13 到期语义与主动超时治理立项（2026-11-06）

- 新增 `docs/architecture/到期语义与主动超时治理-v1.md`：登记原生到期权威、状态转换、并发幂等、副作用与可观测合同；裁决「统一目录+各域原生转换器+条件触发只读投影」，不建复制 `expires_at` 的通用到期表。
- 审批主动超时标记为既有基线（T-P1-5：`_expire_approval` + scheduler sweep）；UploadSession multipart abort、API confirmation append-only 超时列为独立候选阶段；跨域查询须有明确需求才排期。
- 明确排除 worker lease/retry/outbox due、JWT/签名/Redis TTL、模型/进程 timeout 等异质时钟。本轮仅立项，零运行时代码、零迁移、零路由、零数据操作；B/C/D 仍 PROPOSED，不构成实施授权。
## [未发布] — V3 只读执行事实链面板（B#9，2026-11-06）

### 只读聚合面（+1 路由；server + desktop；零迁移零依赖）

- **服务端**：NEW `GET /api/v1/projects/{id}/execution-facts`（can_view，`fact_chain_blueprint`，**不进 api_catalog**——AI 不经此面读审计原始流，与证据登记同纪律）。三源时间线归并：`project_evidence` ＋ `operation_events`（**项目维度**，过滤下推 SQL）＋ `ai_call_audits`（**账号维度**——该表无项目外键，按 actor 过滤且响应明示 `ai_call_audit_scope="actor"`，不作项目切分假装）。时间倒序、`limit` 1–200 有界＋`truncated`、非法参数 400。
- **「外部完成无真实回执=未知」纪律的落法**：`operation_events.changes` 大载荷不外泄；AI 审计只投影调用事实元数据（模型/耗时/token/状态三值，无明文上下文）；**无回执即无行**，由前端呈现「无记录」，不由模型自述或时间线推断拼装任何「已完成」语义。
- **桌面**：NEW `evidence/ExecutionFactChain.tsx` 只读面板，项目 tab +1「执行事实」（11 tab）：三源筛选、类型徽标、AI 调用「账号维度」明示、空态不编造、CR-035 同型序列守卫（筛选切换只认最新响应）。纯只读——无任何写操作按钮。
- **测试**：NEW `server/tests/test_execution_fact_chain.py` 4 例（三源归并排序＋changes 不泄漏＋AI 字段白名单＋未知不编造／actor 隔离跨账号泄漏钉／过滤与 limit 有界＋非法 400／权限 viewer 200·外人 403·404·不进 api_catalog）＋**变异三连**（actor 过滤失效／changes 泄漏／scope 谎称 project）逐一转红；桌面改 1 处 tab 断言数组（vitest 用例数不变）。
- **口径**：pytest **1985 收集 = 1979 passed + 6 skipped**（+4）／vitest **825**（本条自身不变；含并入的 UI-UX 黑金轮增量 791→825）／mypy **279**（不变）／蓝图路由 **301**（+1）／业务表 **105**（不变）／api_catalog ENTRIES **94**（不变）／迁移头 `b2e8f4a6c9d3`（36 rev，不变）。**server 变更 ⇒ 合并后 rebuild 三镜像 + `alembic upgrade head`**（零迁移，幂等）；桌面便携版重打包挂账（随下次桌面交付轮）。
## [未发布] — V3 技能结构化契约 + 自洽校验（B#36+B#37，2026-11-06）

### 契约与测试（零迁移零路由零桌面；零 src 改动——无需重建镜像）

- **B#36 技能结构化契约 v1**（`docs/architecture/技能结构化契约-v1.md`）：`SkillVersion.manifest_json` 五组**可选**扩展键——`use_boundaries`（适用边界）/`effects`（副作用声明，`read_only`×`write_actions` 自洽律）/`evidence`（证据口径，指针+指纹语义）/`verification`（验证状态**非状态注记**，published=治理通过≠现场验证）/`failure_behavior`（失败诚实）；不设 `additionalProperties:false`、不换状态值、不改发布四闸；`.agents/skills/` 新技能 front matter 建议（name+description 必填+契约键平铺点路径），存量 4 runbook 与内置种子 manifest 均不回填；`instructions_text` 禁拆 YAML 双权威（DB 唯一权威）。字段全部我方独立设计（B#35 红线第 8 条履行，零 fde-skills 正文引用）。
- **B#37 技能自洽校验**（`server/tests/test_skill_contract.py` 四钉，标准库+pytest 零新依赖）：仓库 runbook front matter 契约；内置种子清单静态契约（能力 ⊆ `CAPABILITY_REQUIREMENTS`）；种子 manifest 构造规则独立复算钉；**种子清单 ↔ DB 行对账**（`seed_public_skills` 端到端：全量落库逐位一致+幂等二轮 0+版本行不增殖）。变异四连逐一转红（read_only 推导翻转/name 脱离目录名/域外能力/version 分档漂移）。
- 顺带核实销号 **B#35**：AGENTS 红线第 8 条+backlog 登记已随 #133 合入，修复项产出（PR 合入）达成。
- 顺带卫生修复：移除 #139 合并在 CHANGELOG 遗留的孤立 `=======` 行（冲突标记残留，会污染后续 rebase 标记识别与渲染）。

## [未发布] — V3 报告待办池清欠（代码批）：skill_read 分页 + GlossaryPage 影响分析接线（2026-11-06）

### 行为变更（零迁移零路由；server 变更 ⇒ 一次 rebuild；桌面变更 ⇒ 便携版重打包挂账）

- **skill_read 分页（B#8+B#32 真缺口闭合）**：MCP `skill_read` 加 `offset` 入参——指南长文按 **16k 字符窗口**分页（与 file_read/help_fetch 同尺），响应新增 `offset`/`next_offset`/`total_characters`（`next_offset` 非空时用 offset 续取）；负数/非整数 offset → 400 `invalid_request`。**T-S2 消费计数收敛＝仅首读（offset=0）计一次**，续页是同一消费行为的延续不加计；未知技能 404 不计语义不变。新测试 `server/tests/test_skill_read_pagination.py` 五例（工具面登记形状/短文单页兼容/长文续取拼接无损/偏移形状闸/计数一次）。
- **GlossaryPage 影响分析接线（T-I1 消费面，§六 P0 #1 清偿）**：术语表行内「影响分析」按钮展开 `GET terms/{id}/impact` 三面清单——counts 汇总＋subjects 命中溯源（matched_via 规范名/别名）＋links 邻接边＋forms 修订状态；并入行查询显示「已解析到存活概念」注记；连点不同行按序列号只认最新响应（CR-035 同型守卫）；失败在行内呈现不收行。
- 文档批（PR #136）：六铁律裁决回写主报告 §17/§19、审计三清单全量刷新（补记⑤）、NEW 术语改名SOP-v1.md、AGENTS「口径数字引用前现测」纪律；报告 §十二 记录全轮。

### 口径

- 零迁移零路由：pytest **1972+5=1977 收集**（1971 passed + 6 skipped，CI 复核）/ mypy 279 不变 / vitest **787+4=791** / 105 表 / `b2e8f4a6c9d3`（36 rev）/ 路由 300 / ENTRIES 94 不变。
## [未发布] — V3 外部模型依赖契约 v1（借鉴登记 B#10 文档批）（2026-11-06）

### 文档（零代码零迁移零路由零依赖；无需 rebuild / 重打包）

- **《外部模型依赖契约 v1》**（NEW `docs/architecture/外部模型依赖契约-v1.md`）：**B#10 落地产物**——把「在确定性规则之后插入外部模型阶段」这类改动必须遵守的约定成文化。七条规则 M-1–M-7（**我方自定义编号**，与任何上游编号体系无关）：①开关默认 OFF 且关闭时判定逐字一致、零外部请求；②阈值是「建议值」非判定常数、调用时点读取、覆盖免重启；③失败≠错误而是「下一阶段」且既有路径原样继续；④传输层可注入、测试网络零依赖、地址密钥禁硬编码、客户端禁擅自裁剪请求体；⑤外部响应缺字段取保守值不推测、枚举表外值只留痕不参与判定、保守方向须写明；⑥日志只记哈希与长度禁记原文、必记「哪一阶段作出判定」的 source 标记、不新建存储；⑦调用方签名不破坏、新参数一律可选、显式意图预判顺序不得被新阶段翻转。
- **与既有纪律的分工澄清**：本条管**判定层**（新阶段失败→降级到下一阶段），既有 W-8「断链不静默 done」管**流程层**（真失败须显性化），二者不得互相抵消——避免「新阶段降级」被误用为「静默吞掉真失败」。
- **现状对照与差距清单**（全部 `[已核实]`，行级引用采用**符号名＋行号双锚**防基线漂移）：M-1/M-3/M-4/M-7 已满足；M-2/M-5/M-6 三条缺成文纪律——**纯靠立规闭合，零代码**。
- **八条可断言判据**（供未来 PR 自查）：开关关闭零请求、关闭态判定逐字一致、阈值改动免重启、新阶段失败落到下一阶段且既有结果不变、缺字段取保守值、日志原文子串扫描零命中、日志含合法 source、旧签名零改动可用——全部静态或注入式断言，不依赖真实网络与真实模型。
- **触发式复查**：新增任一外部模型阶段时，同 PR 内须逐条对照 M-1–M-7 给「满足／不满足／不适用」三选一，不满足者不得合入；季度复查会随《触发条件复查记录》一并过。
- **来源与边界**：设计原则取自 GIIP「外部模型阶段插入的设计规则」这一**抽象方法论**；按 `AGENTS.md` 红线第 8 条——**只取抽象原则，不复制上游正文段落、不复制其结构化表达**，表格骨架、判据措辞、编号体系均为我方独立重写。

### 口径

- 零代码零迁移零路由零依赖——pytest 1972 收集（1966 passed + 6 skipped）/ mypy 279 / vitest 787 / 105 表 / 迁移头 `b2e8f4a6c9d3`（36 rev）/ 路由 300 / ENTRIES 94 全部不变（纯文档新增，无口径变更）。

## [未发布] — V3 报告待办池清欠（文档批）：六铁律裁决回写 + 审计清单全量刷新 + 改名 SOP + 数字现测纪律（2026-11-06）

### 文档（零代码零迁移零路由；无需 rebuild / 重打包）

- **六铁律裁决回写（主报告 §17）**：明示「开发轨＝先红后绿+CI 4 绿+单 commit revert+PR 纪律等效（有意裁决）；运行期自动修复轨暂无需求有意不做，若做 agent 落码须补 ①③④⑤」——消除「有意不做 vs 未做」歧义（v3-迁移进度对照报告 §六 #6 清偿）。
- **影子库 / view_watchdog 裁决定性补记（主报告 §19）**：PG `*_test` 硬闸判定等效不照搬（销号后人再评估成本）；view_watchdog 未立项（有意不做），§19 清单维持 7 项。
- **审计清单全量刷新（补记⑤）**：`docs/audit/` 三份清单按 fork/main `dc43a2d` 整体重生成（路由 300 / 表 105 / 迁移 36，与口径行逐位一致）；抽取脚本补登 T-J2/CR-027 两个 admin blueprint——补记③「待本体表落地后整体刷新」欠账清偿（§六 #10 清偿）。
- **术语改名 SOP v1**（NEW `docs/architecture/术语改名SOP-v1.md`）：名字域纽带四步改名流程（先查 impact → change-set rename → 改引用面 → 别名不清理）；代码强制挂后续评估（§五-4 / §六 #7 清偿）。
- **AGENTS.md 新增「口径数字引用前现测」纪律**（工作流与陷阱）：表数/路由/ENTRIES/迁移头/mypy/pytest-vitest 六项测量配方 + 全文同模式终扫要求（#129/#131 两次口径校正的教训制度化）。

### 口径

- 零代码零迁移——pytest 1972 收集（1966 passed + 6 skipped）/ mypy 279 / vitest 787 / 105 表 / 迁移头 `b2e8f4a6c9d3`（36 rev）/ 路由 300 / ENTRIES 94 全部不变（审计清单刷新为重生成既有产物，非口径变更）。

## [未发布] — V3 P0 先行批收官：审批退避提醒 + SLA 统计（2026-11-06）

### 行为变更（零迁移；server 变更 ⇒ 一次 rebuild）

- **B#5 审批退避提醒（复用任务中心，勿新开外发通道）**：新 `scheduler.remind_pending_approvals`（cli scheduler 循环，与派单/过期清扫同拍）——pending 审批按 `created_at` 起算 **10m→1h→4h→24h** 退避序列 catch-up 补发提醒（过夜可直达 4 级），账本=`result_json["approval_reminders"]`；幂等（已发等级不重发）、四级封顶；`skip_locked` 与并发拍板互不阻塞；非 pending 零触碰。红线对齐：不经微信/邮件主动推送，呈现面=任务中心审批列表。
- **SLA 统计**：`_serialize_approval` 新增 `created_at`（此前未暴露）/ `pending_seconds`（仅 pending）/ `reminder_count` / `next_reminder_at`；workflow run 详情（`serialize_run`）在 `waiting_approval` 态带 `waiting_approval_seconds`（锚=`updated_at`），他态无该键。
- 新测试 `server/tests/test_approval_reminder_sla.py` 五例 + 变异五连（红→反向替换还原→绿）。

### 口径

- 服务端 pytest **1972 收集 = 1966 passed + 6 skipped**（+5）；mypy 279/104 不变；vitest 787 / 105 表 / `b2e8f4a6c9d3`（36 rev）/ 路由 300 / ENTRIES 94 不变。

## [未发布] — V3 迁移进度对照报告入库 + 动工前审查证据修正 + backlog 状态声明混合口径（2026-11-06）

### 文档（零代码零迁移零路由；无需 rebuild / 重打包）

- **报告入库**：`docs/implementation/v3-迁移进度对照-fde-v2建议-2026-11-04.md` 首次入版本库（此前为未跟踪工作文件）——第五轮动工前审查同步：七项口径在 fork/main `743a633` 全部复测吻合（pytest 1961 passed + 6 skipped / vitest 787 取 #131 CI run 42110880267 实测；mypy 门 CI 实跑绿＋基线 279 行）；8 处 文件:行号 漂移修正（api_catalog.py:15→19、chat.py:50-72→72-96、mcp_gateway.py:32-51→36-55、workflows/models.py:157→163、ontology/service.py:1295→1304、executor.py:1213-1227→694 起+1402-1413、ontology/models.py:54-247→54-246、§三 交叉引用 §五-5→§五-4）；§七 存档哈希清单与「12 提交」串位 4 处修正（#114~#124 实为 11）；新增 §十一 增量记录；遗留项四条与 11-01 建议清单九项判定全部复核维持。
- **backlog 状态声明滚动更新（报告 §六 P0 #2 清偿）**：头部改混合口径（T-\* 33 节全部 DONE / B#1–B#40 仅 P0 先行批表 10 项 ✅ 已实施（#128~#131）、其余按逐条状态标注 / P3 四项已定案收口）；「开源借鉴清单登记」段标题改写（与 #133 评审补登记合并）；B#1/B#2/B#4 编号 **#129→#130** 校正（#129=知识收尾轮纯文档，#130=P0 代码级子批；B#28 行已由 #133 同向订正，rebase 取其版）。
- **口径**：零代码零迁移——pytest 1967 收集（1961 passed + 6 skipped）/ mypy 279 / vitest 787 / 105 表 / 迁移头 `b2e8f4a6c9d3`（36 rev）/ 路由 300 / ENTRIES 94 全部不变。

## [未发布] — V3 P0 先行批收尾：状态归属与对账框架 + G9 出门口径接线（2026-11-06）

### 行为变更（零迁移；server 变更 ⇒ 一次 rebuild）

- **B#6 状态归属与对账框架**：新增 `docs/architecture/状态归属与对账-v1.md`（四层归属总表 + C1–C10 自检清单）与 `server/tests/test_state_ownership_reconciliation.py` 六条跨层对账钉——候选（任务/workflow 两腿）挂接后 `project_evidence` 零行且清单 claim_status 不动；物化唯一入口 = `submit_gate_evidence` 真人提交闸；已领清单项 (source_uri, content_hash, evidence_id) 与被引证据行逐位一致；workflow 版本行 `dag_sha256(dag_json)` 重算 == 落库 `content_sha256`（二次发布不污染已固定版本，run 固定 (definition_id, version)）；documents 快照剥 `captured_at` 后逐位确定；ontology 变更集 base 指纹不符 confirm 409 零物化。六钉逐一变异验证（红→还原→绿）。
- **B#21 G9 出门口径接线（#128 挂账清偿）**：`server/seeds/gates.json` G9 `exit_condition` 挂接评测协议 §5 冻结公式「验收线达成 ≔ uplift_bounded ≥ 0.8 ∧ incidents = ∅ ∧ 三锚四反例全过」+ 无 oracle → `insufficient_data` 不得出分 + 协议文档指针；原五项出门口径逐字保留。种子重生成覆盖由接线钉守护（红=须重挂）；存量 Gate 行不改，新项目懒实例化即得新口径（模板漂移由 T-G2 `template_outdated` 呈现，属设计行为）。
- **口径校正**：#130 曾漏改 AGENTS 口径行迁移头（pytest 行已推进而迁移头未随），本轮顺带校正为 `b2e8f4a6c9d3`（36 rev）。

### 口径

- 服务端 pytest **1967 收集 = 1961 passed + 6 skipped**（+6）；mypy 基线 279/104 不变；vitest 787 不变；105 表 / 迁移头 `b2e8f4a6c9d3`（36 rev）/ 路由 300 / ENTRIES 94 不变。

## [未发布] — V3 P0 先行批·代码级子批：跳数熔断 + 门禁 revision CAS + 回执终态 + purity 架构测试（2026-11-05）

### 行为变更（合并迁移 `b2e8f4a6c9d3`——一次 rebuild + alembic upgrade head）

- **B#1 跳数熔断**（agent-autoloop 语义）：`workflow_runs.hops` 列 + `MAX_RUN_HOPS=8`——resume_run 拍板重投逐代 +1（继承不清零）、超限 409 `hops_exceeded` 零变更；执行器入口 belt 把在途超限行 honest failed（不再分派任何节点），封顶 workflow 自触发链。
- **B#28 门禁 revision CAS**（FF stage completeX 语义）：`decide_gate` 增可选 `expected_revision`（缺省=旧客户端兼容）——行锁+版本复核，落后即 409 `gate_revision_conflict` 且零变更，多端并发拍板后写不再覆盖前写；拍板生效推进 `gates.version`（复用既有 VersionedMixin 列）并留痕 changes；新列 `gates.lifecycle_version`（门禁语法代际，现役=1）。桌面 expected_revision 接线归主树品牌轮落定后。
- **B#2 回执「写错不重做」**（agent-autoloop worker 语义，收窄面）：`ManifestOutputScanner.receipt_state` 四态回执判定（Protocol 不破）经 `RunResult.receipt_state` 入 `_finalize`——completed + exit 0 + 零声明产物 **且** 回执面损坏（output/ 有文件没写 manifest / manifest 非法 JSON）→ 新终态 `succeeded_but_receipt_invalid`（不进 FAILED_STATUSES ⇒ retry_run 拒同键重跑，业务动作不重执行，消除重复交付尾部风险）；合法零产物任务照旧 completed；声明产物校验失败维持 C-1 failed+retry 合同；`agent_runs.status` 列 String(24)→(40) 加宽 + CHECK 扩（downgrade 归位 failed）。
- **B#4 purity 架构测试**：`test_architecture_purity.py` 四断言——workflows 顶层零 control.service/routes（双向环防线）、control.service 延迟导入惯例固化、workflows 内核零 os.environ/flask、零产品名字面量。
- **口径**：pytest **1961 收集 = 1955 passed + 6 skipped**（+16：hops 2 / gates CAS 4 / receipt 5 / purity 4 / 迁移 roundtrip 1）；mypy 279 不动；vitest 787 不动。变异验证四连（hops 上限/CAS 复核/回执终态/scanner 收窄面）apply→red→reverse-restore→green。

## [未发布] — 知识收尾轮：AGENTS 口径行校正 + README 品牌路径/配置对齐（2026-11-05）

### 文档收尾（零代码零迁移零路由零桌面，口径全不动）

- **AGENTS 口径行校正**：口径行停留在 #124（pytest 1944=1938+6s），#125 W-9 纯测试 +1 起 #125–#128 各轮已按 1945=1939+6s（CI PR-head 实测）报——行内补齐 W-9 +1、实测锚点前移；零代码轮动了测试数同样要同步口径行。
- **README 对齐**：品牌单点路径修正为 `desktop/src/shared/brand.ts`（#109 CR-001 双侧单点后遗留旧路径），并补服务端单点 `server/src/fde_api/config.py`（`FDE_PRODUCT_NAME` 覆写）；配置边界表补 `FDE_PRODUCT_NAME` / `FDE_AI_MONTHLY_TOKEN_BUDGET`（0=不限额、设施故障 fail-open）/ `FDE_AGENT_MONTHLY_BUDGET`；能力表补门禁证据候选（任务/工作流产物建议性候选，采纳仍走人工提交闸）与 AI 用量月度预算/审计账本。
- **`server/.env.example` 补 `FDE_PRODUCT_NAME` 注释示例行**（#109 新增公开配置时漏了示例面）。

## [未发布] — V3 P0 先行批·文档级子批：B#3 红线 + 交付效果评测协议 v0 + DSH 适配层决策记录（2026-11-05）

### 文档级先行批（零代码零迁移零路由零桌面，口径全不动）

- **B#3 红线 +1**：AGENTS 红线节新增「AI 审查不执行被审代码」——审查输入只能是 diff/文本快照，不得检出/运行被审交付的代码、测试、配置、hooks（agent-autoloop delivery 插件语义；未来上 AI 审查时加 CI 断言）。
- **B#21+B#22+B#29 交付效果评测协议 v0**（`docs/architecture/交付效果评测协议-v0.md`，PROPOSED 文档层）：uplift 算分口径 + result 字段清单 + 三锚点四反例门禁判据（阈值须我方数据校准）+ 验收合同契约五点（对齐 G8 conditional_pass / G9 有条件接受）；无 oracle 不得出分（`insufficient_data`）；G9 exit_condition 挂 gates.json + pytest 接线=server 变更归代码级子批同窗口；Q1–Q3 拍板前停文档层。
- **B#27 DSH 适配层决策记录 v1**（`docs/architecture/DSH-适配层决策记录-v1.md`）：`fde-dsh-v1` 自定协议声明 + 官方源码零命中端点证据 + 若启用须自写适配层清单 + lock 八字段/三方合并升级法 + 安全前置四条；**维持「当前不装、不换执行体」裁决**。

## [未发布] — V3 开源借鉴消费登记轮：B#1–B#34 全量登记 PROPOSED + CR-004 销号（2026-11-05）

### 登记轮（零代码零迁移零路由，口径全不动）

- **来源**：调研会话《开源项目借鉴总览-2026-11-05》及八份分报告（横评七项目：fde-v2 已消化完毕 / agent-autoloop 最值得借鉴 / agnes-harness·giip·FDEP 仅参考设计 / fde-gym 战略价值最高但工程性价比第二 / FF-FDE 只借鉴实现不引入运行时）——`docs/audit/` 在途未提交产物，落定回写归调研会话，本登记轮只消费不代提交。
- **登记**：backlog 新节「开源借鉴清单登记」——**B#1–B#34 全量 PROPOSED**（登记≠排期≠默认实施；实施须另开轮走既有流程）。P0 先行批 11 条（B#1 跳数熔断 / B#2 回执写错不重做 / B#3 审查不执行被审代码红线 / B#4 purity 架构测试 / B#5 审批退避+SLA / B#6 状态归属对账 / B#21 评测协议 v0 / B#22 三锚四反例 / B#27 DSH 适配层决策记录 / B#28 门禁 revision CAS / B#29 验收合同契约）；P1 15 条、P2 条件触发 9 条按触发条件挂账；跨项目合并六组防重复立项。
- **拍板闸挂账**：B#1+B#28 合并同一迁移窗口（一次 rebuild+alembic upgrade head）需拍板；Q1–Q6 决策依赖（Q1「交付产物评测」语义、Q2–Q3 验收线/kpi/oracle、Q4–Q6 数据落点/容器/许可证）不预支。
- **红线对照**：B#25 客户资料红线（真相/参考解/隐藏流量永不入库不进 git，落 fdeops 工作目录+全代号化）；B#34 交付进程红线（仅内部自检夹具）；P3 评估报告「写类外呼/发信/付款永不降级」红线上位维持。
- **CR-004 销号**（c1）：AGENTS 口径行已由后续每轮维护+CI PR-head 实测逐位核对（现口径 105 表/`d9f4a7c2e6b1` 35 rev/路由 300/1945=1939+6s/787/279），#88 时代投诉面不复存在——「逐轮维护治愈」销号，台账行+详情段+修复 PR 三处注记。

## [未发布] — V3 P3 评估报告轮：有限自动执行开放评估落盘——八档边界分类学 + 可降级集合=∅ + 取数口径先行（2026-11-05）

### 评估报告（零代码零配置零迁移零闸态变更）

- **轮次定位**：P3-④ 评估报告轮本体（合同 §4，#125 三道闸清偿后解冻）；报告=`docs/implementation/v3-p3-评估报告-有限自动执行-v1.md`。合同 §4.4 末段原文兑现：「本立项不开放任何自动执行；评估报告本身也不开放」——**闸态变更数=0**。
- **①边界梯度分类学（§4.4-1）**：三面目录实测（api_catalog 94 条 effect/risk/confirmation 分面 + MCP 17 工具五元 + A 轨审批执行硬白名单 `service.py:867` 唯一对）→ 八档分类 **G0 只读内查 / G1 只读外呼（lcsc_search 原型）/ G2 产物外呼（forms.export、translator.translate 已处事后审计档）/ G3 产物出具·治理耦合（documents.generate、export_sow 挂 signoff）/ G4 普通内部写（37 条=现役中间地带）/ G5 敏感内部写（不可逆+启发式捕获面）/ G6 发信类红线现役档（`file_send_wechat` 收件域封闭本人+事前密码确认）/ G7 写外呼付款红线空域（构造性零条目）**+ S 系统自主白名单。**现役可降级集合=∅**；「写外呼/发信/付款永不降级」红线逐字维持；未来新类准入=§1.5 五要素模板（全 PROPOSED）。
- **②验收核对表+运行数据要求（§4.4-2）**：32 例核对表引用 #125 §4.1 不复制；**取数口径四条先行**（审批时效 p50/p90 / 人工否决率=误判率代理 / 执行落空检测 / 确认失败锁事件），活库 `automation_approvals=0` 行——首批真实 run 后评估复审轮消费，本轮不设数值门槛。
- **③责任主体数据面证明（§4.4-3）**：#125 §4.3 五链节引用 + **三条断言式回溯 SQL**（审批链双侧人签 / 发起链实名 / 全事件落人，期望恒 0 行）——现有表够，无结构性缺口。
- **④调研衔接（§4.4-4）**：调研会话《自动化运行-DSH替代可行性评估-2026-11-05》已落盘（`docs/audit/` 在途产物，落定回写归调研会话，本报告只消费不代提交）：四链路 A/B/C/D 与分类学面对齐、「真瓶颈=人工拍板红线」互证、P0 维持现状同向、治理风险独立佐证。
- **口径**：零代码轮基线不变——pytest **1945 收集 = 1939 passed + 6 skipped** / mypy 279 / vitest 787（以 CI PR-head 实测行核对）；无需重建镜像 / alembic / 重打包。

## [未发布] — V3 P3 四项状态轮与 §4 闸清偿：①②③定案 + ④三道闸齐备（2026-11-05）

### 状态轮报告（零迁移零路由零生产行为变更）

- **轮次定位**：主报告 §17 P3 行四项「立项不排期」的状态清偿轮——报告 `docs/implementation/v3-p3-四项状态与闸清偿-v1.md`（含 §16 用例族 32 例逐项核对表、责任主体机制化方案、活库数据闸实测）；四项裁决 AskUserQuestion 未获答复，按 #124 委托先例按推荐项执行、逐项留痕可推翻。
- **①多 Agent 自适应编排**：活库实测 `agent_runs=0`/`workflow_runs=0`（演练键亦 0）——真实 run 数据解冻闸未动，维持冻结，零动作。
- **②Skill 运行反馈改进**：裁决=usage 维持「失败不计」对称语义、不新开失败核算维度（活库 skill 消费事件=0 无建议需求；失败证据走 ai_call_audits/operation_events 人工审计面；重审触发器=首个真实改进建议需求）；agent-policy §2.1 效果评估行已回写；双面消费量闸未过，仍冻。
- **③业务规则推理**：ontology_rules 维持不建 PARK 定案（risk≥3 规则已内嵌且被 `test_catalog_effect_risk_invariants` 钉住、T-C1 编译校验无规则输入需求；重开触发器三项写死）；**规则 9 强制化悬置线销号=维持告警**（执行层已硬闸：workflow call external 必 awaiting_confirmation 诚实失败 + DSH agent 节点走审批回调；「P2 enforcement wave」不做）。
- **④有限自动执行**：三道闸齐备——T-J2 ✅（#116）+ **§16 用例族核对表 32 例全绿**（30 直接绿 + W-9 本轮补钉 + W-3 裁决回写，0 红）+ 责任主体机制化方案成形（审批链人签五要素在表、系统自主动作=封闭白名单、验收分离双面钉住，无结构性缺口）→ **评估报告轮解冻可排期**（余项=边界梯度分类学〔写类永不降级红线维持〕+调研会话衔接；写类 external 免事前确认=红线级非目标逐字维持）。
- **W-9 补钉（唯一代码变更，纯测试）**：NEW `test_capability_revocation_mid_run_fails_subsequent_write_call_node`——run 进行中撤销发起人 AI 档位，后续写类 call 节点分派时实时重判命中 `execute_api` workbench.write 硬闸 403 forbidden 诚实失败（零重试）、run failed（FV-F1）；变异验证（档位一次定终身→红→还原→绿）；executor 全文件 37/37 绿。
- **W-3 裁决回写**：skill `input_schema` 为只写元数据（publish 期仅 isinstance(dict)，MCP/chat/workflow 三面零消费）——校验面不补码（无消费方不建空壳），test-plan W-3 行注记「未实现，按需另立」；S-7/S-9/D-5 形态偏差同批注记。
- 口径：pytest 基线 1944=1938+6s 双面一致（干净 `58a54ff` 本地全量实测=#124 CI 口径）+1 → **1945 收集（CI PR-head 复核为准）**；mypy 279 基线不动；桌面零改动（vitest 787 不变）；零迁移零路由 ⇒ 无需重建镜像、无需 alembic、无需重打包便携版。

## [未发布] — goal-c P3 服务端小轮：指标面排除演练 run + 桥投影列水合 + outbox 死信箱销号（2026-11-05）

### 服务端（零迁移零路由零桌面）

- **CR-031 演练 run 排除出指标持续观测面**：降级演练（`rehearse_fallback`，幂等键 `rehearsal:` 前缀、零计费零真实耗时）此前混进四张 run 指标卡——L1 演练（completed+degraded+0ms+0 费）拉低草稿耗时中位数、**抬高降级率（持续 >30% 暂停扩大 agent 授权的红线指标会被演练误触发）**，L2 演练（failed）压低一次通过率，零费行拉低成本中位数。现四个 AgentRun 查询统一挂 `_REAL_RUNS` 过滤（常量复用 `agents/pilot.py::REHEARSAL_KEY_PREFIX` 单点，试点闸口面同款口径先行），四卡 `definition` 文案同步注明排除（口径面=计算面）。测试：NEW 专项 1 例钉 L1/L2 两形态四指标；变异验证（过滤中性化→四断言全红→还原→绿）。
- **CR-030（半 A）桥投影列水合**：4h 采集投影的 `_sync_bridge_evidence` 全表 ORM 水合改三列投影（id/openfde_engagement/fdeops_workspace），行为等价。**半 B 登记失真如实修正**：现场核实 `_city_order_rank` 在 r12 B-④ 重写后已是单次 join+Python 计数，登记描述的「循环 session.get」不存在；真实重复面仅剩仿真工具循环（P4 卫生维持观察）。
- **CR-016 台账销号**：outbox 死信箱经 T-J1（终态写入三落点）+ T-J2（取消/重试双路径终态收口）已彻底闭环，登记前提不复存在；本轮只补台账销号注记，零代码。
- 口径：pytest **1944 收集 = 1938 passed + 6 skipped**（+1；基线 1943 已随 #123 CR-041 核销轮双面实测校正）；105 表 / 迁移头 `d9f4a7c2e6b1`（35 rev）/ 路由 300 / ENTRIES 94 / mypy 279 基线 / vitest 787 全部不变；零迁移（rebuild 幂等校验 `alembic upgrade head`）。

## [未发布] — goal-c CR-041 核销：融合树独立复测 + 口径校正 + 桌面便携包 r16（2026-11-05）

- **核销（零代码轮）**：并发 P3 批清偿（#121）落定后的独立核销——融合树全量实测：服务端 pytest **1943 收集 = 1937 passed + 6 skipped**（本地 Windows 与 CI PR-head 双面一致）、CR-041 专项 2 例绿、mypy 基线 279 全绿、桌面 vitest 774/774、typecheck 零错；**发现并校正融合口径偏 1**（AGENTS 前值 1942/1936 为算术推导；CI 实测 #120 = 1935+6s、#121 = 1937+6s，口径行按实测改写）；「负向日志断言空转绿」担忧实测排除——`not in caplog.text` 全仓 10 处（含 test_auth_api.py:481 密钥不入日志安全断言）在 env.py 解禁后真判零红。部署活体核验：api 镜像 env.py 修在位、300 业务路由、双 admin 路由、`/ready` 200、alembic head `d9f4a7c2e6b1`。
- **桌面便携包 r16**：r15（11-05 11:18）早于 #113 T-UI1 徽标与 #121 CR-035/040——marker「已取代」「source_kind」双 0 命中证实缺口；从 fork/main `7dc620e` 干净树重打包 **蔡工FDE-0.2.0-便携版-r16**：asar sha256 `c62e184b131db53386eb83897c80ca447a57a81b952d6e992cea1bcbcb75027d`，marker「已取代」×2 /「source_kind」×3 命中；r15 旧目录未覆盖。
- 台账同步：CR-041 增核销复核段（含口径校正与 r16 交付记录）。

## [未发布] — goal-c P3 测试补强：AI 机会主链组件 13 例覆盖 + sync-hash 断言加固（2026-11-05）

### 桌面端（纯测试轮：生产代码零变更、服务端零改动）

- **CR-037 ResearchOpportunity.tsx 零 vitest 覆盖清偿**：NEW `desktop/tests/renderer/research-opportunity.test.tsx` 13 例，全部落在新文件——
  - 纯函数 8 例：`validateOpportunityProfile` 全分支（超长 301/1001 与临界 300/1000、状态/优先级/风险等级无效值、三项评分 0/6/小数拦截 + null 放行、负责人不在成员表）；`opportunityProfileInput` 裁剪两端空白并丢弃展示名；`opportunityProfileErrorMessage` 8 个错误码逐一映射 + 未知码兜底；`draftErrorMessage` PoV/SOW 双形全码 + 兜底。
  - `OpportunityDetail` 组件 5 例：非编辑态档案网格中文渲染；canManage 经「更多」菜单删除联动；编辑态保存主链（PATCH 载荷逐字段断言 + 成功回执与提示）；保存失败按码映射 alert 且不回执；脏标记按 `opportunity-profile:<id>` 键置脏、卸载自动清脏。
  - 变异验证：评分上界 5→6 → 评分用例红 → 还原 → 绿（生产代码 `git diff` 零残留）。
- **CR-038 sync-hash 断言加固（CR-007 同型残留收尾）**：`new-project.test.tsx` 创建成功路径的 `location.hash` 同步读改 `await waitFor(...)`，与 `navigation.test.tsx` 已修的 5 处同型对齐；属加固型改动（当前同步写 hash 下两种写法均绿，防未来异步化复发），台账已如实注记无可做的红绿变异。
- 口径：桌面 vitest **787/787**（+13）；typecheck 绿。测试文件不进应用包（asar），**无需重打包便携版**；105 表 / pytest 1943 / 路由 300 / ENTRIES 94 全部不变（pytest 数字承 CR-041 核销轮 CI 实测校正）。

## [未发布] — goal-c P3 批清偿：术语页搜索守卫 + 状态值域 + alembic 日志基建（2026-11-05）

### 桌面端（GlossaryPage 两项 P3；零服务端改动）

- **CR-035 术语搜索序列守卫**：术语表搜索每键入触发一次全量重取且无守卫——后发先至的旧响应会覆盖新结果；且每次按键后整页换成「正在加载术语表…」，**搜索输入框随页面一起被卸载 → 焦点丢失、无法连续输入**（比原登记的「闪空」更重）。现加 `sequence` ref（同仓 `ResearchWorkspace.loadResearch` 范式）：只有最新一次请求的结果可落表，旧响应整包丢弃；首屏加载完成后不再整页 loading，旧内容留在屏上等新结果（输入框不再被卸载）。
- **CR-040 术语状态值域对齐**：桌面 `TERM_STATUS_LABEL` 写的是服务端不存在的 `candidate/retired`，又缺 `draft/superseded` → 状态列回显英文原值、中文标签永不显示。现对齐服务端 `ontology/models.py::TERM_STATUSES`（draft→草稿 / confirmed→已确认 / superseded→已取代 / merged→已合并），并加注释钉住「值域唯一权威＝服务端」。
- 测试：vitest +3（值域中文标签且旧标签不再出现 / 乱序响应取新弃旧 / 在途搜索不闪空且旧内容不消失）；typecheck 绿。

### 服务端（测试基建一行；零迁移零路由零契约）

- **CR-041 alembic 日志基建**：迁移脚本 `fileConfig` 默认 `disable_existing_loggers=True`，而测试夹具每例都跑迁移 → 导入期创建的模块级 logger（`logging.getLogger(__name__)`）在整场会话内全量 `disabled=True` → caplog / `log_cli` 对这些 logger 永远空捕（此前只能逐测试显式解禁）。现显式 `disable_existing_loggers=False`：只重配 alembic 自身的 logger，不动已存在的模块级 logger。生产面零影响——迁移是独立进程，跑完即退，仅「测试进程内迁移与应用共存」才踩中。
- 测试：NEW `server/tests/test_migrations_logging.py` 2 例（迁移跑完后导入期 logger 仍 `disabled=False`；caplog 能捕获模块级 logger 记录）。变异验证：撤 env.py 那一行 → 两例全红；恢复 → 绿。

### 文档

- **CR-011 三包意图锚集中指针**：V3 主报告 §13 表格补「意图锚指针（不改造）」行——mailing → `docs/SES发信模块-G9.md`；translator → `docs/goal-d13·goal-d14-交付工作台.md`；guidance → `docs/goal-d1·goal-d2-交付工作台.md`。只补可查位置，三包实现面零改动。
- 台账同步：CR-035 / CR-040 / CR-041 / CR-011 → fixed；**CR-003（主报告 §20 实施跟踪注记）挂账**——并发会话在途回滚轮正在撤 T-W7/T-I1 等轮次，此刻补注记即写即错，待回滚轮落定后一次性补。
- 口径：pytest **1942 收集 = 1936 passed + 6 skipped**（本轮 +2）；桌面 vitest **774/774**（本轮 +3）；105 表 / 迁移头 `d9f4a7c2e6b1`（35 rev）/ 路由 300 / ENTRIES 94 不变——零迁移零路由，无需 rebuild。

## [未发布] — goal-c CR-027 规则版本显式管理：撮合不再永久停在降级态（2026-11-05）

### 服务端（零迁移零桌面；路由 +2；用户拍板「显式管理动作」）

- **修复（CR-027）**：`dispatch/rules.py` 的 `create_rule_version`（发布）与 `activate_due_versions`（激活）此前**两者都只有测试引用、零生产入口**——规则版本永不 published→active，`active_rule_version` 恒 None，`match_package` 恒 422 `rule_version_required`（§11.1 降级态变永久态）。NEW `dispatch/admin_routes.py`（blueprint `/api/v1/admin/dispatch`，T-J2 admin 蓝图同款）：`POST /rules/versions` 发布新版本（admin 门在服务层 role 判；快照缺省取当前默认规则投影＝发布「当前口径」而非手抄正文）、`POST /rules/activate` 激活到点版本（幂等，无到期版本零变更；同事务留痕 `operation_events dispatch_rule_activated`，changes 只落版本号/数量/激活时刻，**不落规则正文**）。**公示窗不绕过**：发布端强制 `effective_at ≥ published_at + 30 天`（§6.2），激活端只激活已到生效日者——人工也加速不了公示期。**不做请求路径惰性触发、不做 scheduler 自动激活**：激活节奏由人控制，与「名单≠开闸」裁决一致。
- 测试与口径：NEW `test_dispatch_admin_rules.py` 5 例（非 admin 双路由 403 / 公示窗 <30 天 422 `notice_window_required` + 版本冲突 409 / **激活后撮合不再 422**（解冻证明）+ 重复激活幂等 + 事件留痕只落元数据 / api_catalog 钉子 / 缺省快照取默认投影）。业务路由 298→**300**；全仓 pytest **+5**；台账 CR-027 → fixed、**CR-028 裁决「维持整条挂 B-③ 法务区」**（税率/税法年口径未确认前不动码，解冻条件随法务口径一并修）。

## [未发布] — goal-c CR-022 补呈现通道：取消后在途派发结果不再静默丢弃（2026-11-05）

### 服务端（零迁移零路由零桌面改动；用户拍板「补呈现通道」）

- **修复（CR-022）**：节点在派发后被取消时，在途外呼/AI 调用返回的结果被终态 guard（`node.status∉(pending,ready,running)`）静默丢弃——api_actions 留有成功记录但节点 `output_json=null`，「已执行外呼不回收（诚实呈现）」承诺无展示通道。现 `_settle_node_success`/`_settle_node_failure` 拆分 guard：`node is None` 早退不变；状态不在集合且 **== "cancelled"** 时落诚实记录——**终态不复活**（节点仍 cancelled，FV-F1「断链不静默 done」不破），`output_json = {cancelled_after_dispatch: True, dispatch_outcome: "succeeded"|"failed", action_id, dispatch_result}`（产物真值 + **action_id 指针**——写类操作可回 api_actions 反查）+ `node.error = "cancelled_after_dispatch"` 稳定标记（桌面 WorkflowConsole「错误」列直接可见 ⇒ 零桌面改动即有呈现通道）。取消的 run 不挂 T-W7 门禁证据候选（不进 marker 挂载点）。
- 测试与口径：`test_cancelled_node_records_inflight_dispatch_result`（公开 cancel_run 取消后驱动 settle 点 = 在途返回；断言节点仍 cancelled/未复活 + output_json 三键 + action_id + 序列化面可见）。全仓 pytest **+1**；台账 CR-022 → fixed。

## [未发布] — goal-c CR-021 行锁修复：本体变更集三翻转入口串行化（2026-11-05）

### 服务端（零迁移零路由零桌面改动；用户拍板「修复：CAS 状态翻转」）

- **修复（CR-021）**：`submit_change_set`/`confirm_change_set`/`reject_change_set` 三处状态翻转原为「读 `row.status` 判合法→物化→赋值」的先读后写——两拍板人并发 confirm 会双双物化（幂等键+UNIQUE 兜底不炸数据，但 409 `not_in_review` 语义失守、`ontology_change_set_confirmed` 事件双份）；reject 可翻转已物化的 confirmed 行；双 submit 重复 version。现新增 `_lock_change_set`（`select … with_for_update() + populate_existing`）在三处入口**行锁重读**：并发对手在此串行化，锁在手读到的必是已提交真值；confirm 的 base 指纹复核+逐项物化全程在锁内。
- 测试与口径：`test_change_set_transition_races_serialize_on_row_lock`（裸连接提交并发终态+会话旧实例=并发窗口第二请求的真实内存视图；三段：迟到 confirm 零物化 `not_in_review` / confirmed 终态拒迟到 reject `invalid_transition` / 迟到 submit 409 且 version 只 +1）。变异验证：摘三处行锁→红（迟到 confirm DID NOT RAISE=静默双物化）→还原→绿。全仓 pytest **+1**；台账 CR-021 → fixed。

## [未发布] — V3 T-J2 收官：handler 自动重试 + admin 任务取消 API（2026-11-05，P1 全清）

### 服务端（域 14 最后一块；迁移 +1 纯 CHECK 置换；路由 +1；零桌面）

- **handler 自动重试**：可恢复类型（复用 reconcile `RECOVERABLE_JOB_TYPES` 幂等白名单）handler 抛错不再首败即终——指数退避重投（30s×2 封顶 15 分钟）直至 `attempts` 耗尽；重试期间 outbox 事件保持 `dispatched`（T-J1 红线：只有最终失败才收口 failed），退避到期由 reconcile 新增 due 补投面送回队列（at-least-once，认领侧 `not_due` 守卫消化重复条目）；外副作用类型（automation.execute）维持首败即 failed。candidates 查询补 `populate_existing`（同 session 残留旧实例会让分支判定读内存陈值——实测踩中）。
- **admin 任务取消 API**：`POST /api/v1/admin/jobs/{id}/cancel`（admin，幂等）——**cancelled 成为真状态**（迁移 `d9f4a7c2e6b1` 纯 CHECK 置换，active_key 生成列天然兼容零重建）；重复取消 200 `cancelled=false`、终态 409 `already_terminal`、运行中活租约 409 `job_running` 不强杀（等租约过期后可接管）、过期租约=worker 已死可安全取消（迟到 settle 被终态守卫拒绝）；取消同事务三面收口：job 行 + 同键 outbox 事件（pending+dispatched 一并收口，防下一轮 dispatch 复活）+ `operation_events job_cancelled` 留痕。不进 api_catalog（平台运维面）。
- 测试与口径：pytest +21（worker 重试 7 + reconcile due 面 4 + cancelled CHECK 1 + NEW test_admin_jobs 9）＝**1933 收集 = 1927 passed + 6 skipped**；105 表 / 迁移头 `d9f4a7c2e6b1`（35 rev）/ 路由 298 / ENTRIES 94 / vitest 771 不变。**至此 V3 P1 任务全部交付**（T-J1/T-J2/T-P1-4/T-P1-5/T-OBS1）；CR-016 outbox 死信闭环补齐（取消/重试双路径均以终态收口）。
## [未发布] — V3 P3 立项轮：高级自主化四项立项合同（2026-11-05）

### 文档（零代码零迁移零路由零桌面；口径不变）

- **立项合同 NEW `docs/implementation/v3-p3-高级自主化立项-v1.md`**——backlog §P3 四项逐项展开：①多 Agent 自适应编排（域 6 DEFER 维持，进程内团队拒绝理由=主报告 §19-7 常量，观测=`agent_runs.fallback_level` 分布）；②基于运行反馈的 Skill 改进（T-S2+CR-013 数据面已闭环，失败面维度属语义裁决非补漏）；③业务规则推理 ontology_rules（registry-v1「无消费方不建空壳」维持，候选消费方=risk≥3→human_approval[域 9]+T-C1 编译校验，规则 9 强制化悬置线一并盘）；④有限自动执行开放评估（P0/P2 全 DONE、P1 仅剩 T-J2 在途；解冻=三道闸；写类 external 免事前确认=红线级非目标）。每项含立项依据/已落地基线/评估问题清单/非目标/解冻条件/回写义务；评估报告轮自身也须先过解冻闸。
- 台账同步：backlog §P3 重写挂锚；RAG/LightRAG 维持不立项（主报告 §19 附注）；在途开源借鉴调研（autoloop/agnes/fde-gym/giip/fdep-mcp/DSH 替代可行性）不预支结论，落定后由调研会话自行回写。
- 口径：pytest 1913 收集 = 1907 passed + 6 skipped / 105 表 / head `e2c6a8f4d1b3`（34 rev）/ 路由 297 / ENTRIES 94 / mypy 279 / vitest 771——全不变，无需 rebuild/重打包。

## [未发布] — goal-c CR-013 计数隔离修复：skill 节点计数侧故障不再升级消费侧（2026-11-05）

### 服务端（零迁移零路由零桌面改动）

- **修复（goal-c 台账 c4 遗留 P2，c5 评估未按、本轮单独清偿）**：workflow skill 节点 `_dispatch_skill` 的 `record_skill_usage` 计数调用原为裸调用——计数微事务遇 DB 异常会被 `_execute_node` 兜底 catch 为 `dispatch_crashed(retryable=True)`：已成功的那次 AI 调用被丢弃重跑（双份真实 AI 成本）且节点误标 failed。现包 try/except 记 warning（含 node/skill/error_type）不冒泡——AI 已成功则节点必 succeeded，计数失败只丢一条 `skill_used_workflow` 事件（T-S2「失败不计」对称方向；chat 面 ai_tool_loop 同型守卫，workflow 面补齐最后裸露点）。
- 测试与口径：executor +1（`test_skill_usage_count_failure_does_not_fail_node`——monkeypatch 计数抛 OSError → run succeeded + 恰 1 次 AI 调用（无重投）+ warning 落 caplog；变异验证红→还原绿）。全仓 pytest **1913 收集 = 1907 passed + 6 skipped**（本轮自身 +1；全仓口径随同日 #114 P1 残尾清偿轮 +7 前进）/ 105 表 / 路由 297 / ENTRIES 94 / mypy 279（基线无新增）；**rebuild 后必 `alembic upgrade head`**（零迁移，幂等校验）。
- 台账同步：CR-013 → fixed；**CR-041 登记不修**（测试基建：alembic `env.py` `fileConfig` 默认 `disable_existing_loggers=True`，db_session 每测试跑迁移 → 导入期创建的模块级 logger 测试会话内全量禁用、caplog 空捕；CR-013 测试沿 test_storage_contract oss2 先例显式解禁，根因修复留测试基建轮）。

## [未发布] — V3 P1 残尾清偿：outbox 状态闭环 + 终审双闸 + 审批过期清扫（2026-11-05）

### 服务端（三 S 同轮：T-J1 / T-P1-4 / T-P1-5；T-OBS1 核验销号；零迁移零路由零桌面）

- **T-J1 outbox 状态闭环（WB-DEF-9）**：outbox 事件此前只有 pending→dispatched，终态永无写入点（dispatched 即泄漏）。新增 `outbox.mark_completed/mark_failed`（联动键 `(topic, aggregate_id)==(job_type,target_id)`，只收 dispatched 行、未派发 pending 不动、失败摘要截 2000 字），覆盖**全部三个 job 终态写入点**：`worker._settle`（与 job 终态同事务）、`worker._claim` no_handler（同 claim 事务）、`reconcile._fail_job`（worker 失联终失败）。
- **T-P1-4 resolve_signoff 双闸（WB-DEF-2）**：终审拍板原仅 can_view+AI 档位——viewer 被授予高档后即可代拍。改为项目 `can_manage`（`_require_project_manager`）+ 档位双闸（与 `generate_agent_solution` 权限双层同款）；viewer+`system_operator` 档 → 403 `forbidden`（拦截者显式为项目闸而非档位闸）。
- **T-P1-5 审批过期清扫（WB-DEF-3）**：过期翻转从 decide/状态查询两处内联重复提取为唯一原语 `control/service._expire_approval`（行为零变化），新增 `scheduler.sweep_expired_approvals`（`skip_locked` 与并发拍板互不阻塞）接入 scheduler 循环（与派单同拍）——无人触碰的过期 pending 审批不再永挂任务中心。
- **T-OBS1 降级 chat 落审计（WB-DEF-4）核验销号**：chat 直调 `execute_ai_prompt`，降级直连腿的审计+月账本入账已随 #112（CR-006）落地，本轮零补码销号（`direct-chat-*` 前缀方案由 purpose+used_fallback 取代，区分度更优）。
- 测试与口径：pytest +7（outbox 收口 2 + worker 端到端 3 + viewer 双闸 1 + 清扫 1）；105 表 / 迁移头 `e2c6a8f4d1b3` / 路由 297 / ENTRIES 94 / vitest 771 不变（需 rebuild 三镜像，无迁移）。P1 仅剩 T-J2（重试落地时 outbox failed 只准在最终失败分支翻转——backlog 已留注）。

## [未发布] — V3 实施 T-UI1 三页核销 + GateBoard 候选来源徽标（2026-11-05）

### 桌面端（服务端零改动；T-W7 桌面挂账清偿 + backlog 销号）

- **T-UI1 核销（零补码）**：WorkflowConsole / GlossaryPage / SkillVersionsPage 三页已随 T-W6（#88）同名全量交付（vitest 5/6/7 例 + typecheck 绿，本轮基线复核 767 全绿）——backlog 条目按「已由先导轮兑现」销号。
- **候选来源徽标**：`GateBoard` 候选载荷扩为 `source_kind` 判别联合——task 形（T-G1 旧行，服务端读时缺省）与 workflow 形（T-W7 运行时保留键 `gate_evidence` 的节点产物，带 `workflow_run_id`/`workflow_node_key`/`label`）。**修复潜伏兼容 bug**：T-G1 守卫硬性要求 task 三键，T-W7 workflow 候选行会让整板 isGatesView 拒载；分形守卫后 workflow 缺 run/节点键仍整板拒载（沿「在场必须形状齐全」口径）。workflow 行带「工作流」徽标 + run/节点出处行；采纳走既有提交闸零新入口；同指纹任务/工作流候选并存各占一行（React 键域 `wf:run|node` 分开防撞）；uri>500（人工提交闸上限，与手填表单同限）候选可见但禁采并 title 报因。
- 测试与口径：gate-board +4（徽标呈现+采纳提交体 / 同指纹两形并存 / 超限禁采 / 坏形状整板拒载），vitest **771**；服务端零改动（本轮零增量；全仓 pytest 口径随同日 #112 CR-006 前进至 1905 收集 = 1899 passed + 6 skipped，105 表 / 路由 297 / ENTRIES 94 / mypy 279 不变，无需 rebuild）。

## [未发布] — goal-c CR-006 统一入账+统一闸：DSH 主路径/kimi 本地腿补预算门与 `ai_call_audits` 记账腿（2026-11-05）

### 服务端（用户拍板「统一入账+统一闸」落地；零迁移零路由零桌面改动）

- **缺口（goal-c c2/c8 两轮 E0）**：`dsh_enabled=true` 时 `execute_ai_prompt`——workflow skill 节点/聊天/结构化调用的 DSH 主路径——对 `ai_monthly_token_budget` 恒放行且零记账（skill 花费不入任何账本）；kimi 全路径零预算零审计；预算设施对后台任务存在 flask g 盲区。
- **统一预算门**（`control/ai_server_client.py::execute_ai_prompt`）：`ai_monthly_token_budget` 超限即拒（`ai_budget_exceeded`，retryable=False），先落 `budget_blocked` 审计再拒绝、拦在 MCP token 签发之前（拦截路径零写副作用）；预算 0=不限额、设施故障 fail-open（与 deepseek 直连腿同语义）。**门带显式 user_id——后台任务（workflow skill 节点等无请求上下文场景）同样生效**。
- **统一记账腿**（`_audit_execution`）：DSH 成功按 `provider_usage.calls[]` 聚合精确入账；失败（HTTP 4xx/无效输出/不可达非降级错）各落 `failed`；降级直连腿成功/失败均记账（`used_fallback=True`，token 来自 OpenAI 兼容 usage 块）；provider_usage 无 calls 时 token 记 None 不发明数字。**无双计**：deepseek/kimi 的 DSH 腿经 `structured_completion`→`execute_ai_prompt` 单点入账；deepseek 本地腿沿旧 `_audit` 不动；`direct_tool_completion` 内部零审计（降级腿单点记账）。
- **kimi 本地腿补齐**（`ai/kimi.py`）：入口预算门（拦在文件上传前；actor 取请求上下文，后台无上下文→放行——缺口如实保留）+ 本地腿成功/失败记账（`purpose="kimi_docx"`；流式无 usage，token 记 None）。
- `ai/auditing.py` +`audit_budget_blocked` 统一拦截留痕助手；`execute_ai_prompt` 新增可选 `purpose` 参数（`structured_completion` 传 `"structured"`；chat/executor/dsh_runtime 调用点未触碰）。
- **测试与口径**：pytest **1898 收集 = 1892 passed + 6 skipped（本轮 +7；基线 `b3793d4` 实测 1891；T-W7 同日并轮后总口径 1905 = 1899+6s）**（NEW `test_ai_server_budget_audit.py` 7 例：DSH 拦截零请求+budget_blocked 留痕/成功按 provider_usage 入账+计入月度预算/失败入账不计预算/降级腿 used_fallback 入账/kimi 门拦在上传前/kimi 成功记账 token=None/kimi 失败记账；既有 AI 面 93 例回归全绿）；105 表 / head `e2c6a8f4d1b3`（34 rev）/ 路由 297 / ENTRIES 94 / mypy 基线 279 全不变；改 server（零迁移）⇒ rebuild 三镜像（alembic 幂等校验）。

## [未发布] — V3 实施 T-W7：workflow 节点产物→门禁证据候选——运行时保留键 gate_evidence 同事务挂候选（2026-11-05）

### 服务端（立项合同 `docs/architecture/workflow-gate-evidence-candidates-v1.md`；WB-DEF-8 workflow 腿；零迁移零路由零桌面改动）

- **`gate_service.attach_workflow_evidence_candidate`**：节点产物经 output_json 顶层保留键 `gate_evidence`（`{gate, label?, source_uri, content_sha256}`）挂入 `gates.evidence_candidates`——**产物必须由生产方自带指针+指纹，平台永不自动派生指纹**（立项 D1：对任意 payload 自动哈希入库正是红线本身；形状不齐=不是证据，跳过不发明）。dedup=(source_uri, content_hash, 来源粒度)：同位同指纹幂等（哈希大小写归一）、换指纹两代并存由人取舍；上限沿 MAX_EVIDENCE_CANDIDATES 与任务候选共享列表；与任务候选按来源粒度隔离互不吞并。claim_status 恒不动，采纳唯一入口=真人提交闸（命中指纹即剪除，T-G1 行为零改动复用）。
- **坏标记不炸节点**（D2）：gate 非法 / sha 非 64hex / 超长（uri>1024 / label>120）/ 双字段缺一 → 节点照常 succeeded，登记跳过 + 新事件 `gate_evidence_candidate_skipped`（details 点名坏键 reason；gate 非法挂 project 目标、非对象标记挂 workflow_run 目标；已入 GATE_EVENT_TYPES，feed 可见）。
- **executor 两成功点同事务接线**（D3）：`_settle_node_success`（call/skill/agent 共用）与 `settle_approval_node` 批准分支读标记——事务回滚则节点成功与候选一并回滚（原子）；标记缺失零副作用；失败路径无产物不登记（连门禁行都不懒初始化）。call 节点产物=API 响应 dict 是自然生产方；skill/agent 产物为平台包装形，顶层标记透传留待现实需求（不为想象的需求加形状）。
- **读时缺省 `source_kind`**（D5）：候选行带 `source_kind: "task"|"workflow"`，旧行（T-W7 前任务候选）缺键读时缺省 "task" 不回填（沿 T-E2 evidence_id 先例）；**v1 不预写 project_evidence 一等表**（D4 偏差：工作流产物 ≠ 已采集证据，一等证据仍只在人工提交闸落库——workflow-dag-v1 §4 已注记）。
- **零路由**：候选随既有 `GET /projects/{id}/gates` 的 evidence_candidates 返回；桌面 GateBoard 来源徽标（任务/工作流）另开 S 轮。

### 测试与口径

- pytest **1898 收集（1892 passed + 6 skipped，本轮 +7；新文件 `test_workflow_gate_evidence.py`）**：标记产物挂候选+claim 不动+无标记节点零副作用 / 同指纹幂等（大小写归一）+换指纹并存+与任务候选共享列表互不吞并 / 坏标记 executor 面（节点仍 succeeded+两类 skipped 事件）+service 面八形状裁决 / 失败路径零登记（门禁行未实例化）+resume 后恰好一条 / 采纳剪除回归（submit 同指纹→清单项 claimed+evidence_id）/ source_kind 旧行读时缺省。
- 105 表不变（零 DDL）/ 迁移头 `e2c6a8f4d1b3`（34 rev）不变 / 路由 **297 不变**（零路由）/ ENTRIES 94 不变 / mypy 279·104 不变 / 桌面 vitest 767 不变（零改动无需重打包）；改 server（零迁移）⇒ **rebuild 三镜像**（alembic upgrade head 幂等空跑校验）。

## [未发布] — V3 实施 T-I1：本体变更影响分析——impact_of_term 名字域纽带三面清单 + 只读影响面（2026-11-05）

### 服务端（设计 ontology-registry-v1 §5 用例 6 / 验收 O-6；零迁移零桌面改动，+1 只读路由）

- **`impact_of_term(session, *, project_id, term_id)`**（ontology/service）：给定术语，返回引用它的**研究客体/邻接边/表单**清单——变集拍板前的人工影响面评审。引用合同 = **名字域纽带**：当前实现无 term_id 外键（fde-v2「引用方只引 term_id」未随融合裁决落地），「一个名字一个概念」（UNIQUE(project, term) + UNIQUE(project, alias)）使名字精确等价概念引用——subject.name 精确命中生效名字域即引用（纽带是唯一性不是相似度，子串/大小写变体不算）。
- **生效名字域 = 血缘闭包**：请求行沿 canonical 链到根（merge_terms 保证链一跳化，防御性走到底）+ 全部并入该根的行；名字 = 根规范名（term 绑定）∪ 血缘内别名（alias 绑定——转写来源名归保留行、来源自有别名留在来源行）∪ 非根行历史规范名（alias 绑定兜底）。对并入行发起查询 = 查其存活概念的影响面（请求行原样返回，`resolved.canonical_term_id` 解析到根）。
- **三面清单**（全部确定性排序）：subjects（命中主体含 subject_type/status/merged_into/matched_via/matched_term_id 逐名溯源）→ links（端点命中主体的邻接边，端点名随行补齐）→ forms（命中主体名下表单，含现行修订状态）；附 counts 汇总。**gates 面按验收权威 O-6 落为三面**：门禁清单是 gates.json 冻结模板文本（template_hash 钉死，T-G2），无术语名表面——不发明方法论层没有的引用（偏差回写 backlog）。
- **`GET /projects/{id}/ontology/terms/{term_id}/impact`**（can_view）：影响分析只读面，**有意不进 api_catalog**（沿 T-O3 纪律：本体治理面 AI 不可直达；桌面 T-UI1 GlossaryPage 是预期消费方）。跨项目/未知术语 404 `term_not_found`、无权限 403。
- **前置热修（goal-c8 CR-002 首版回归，fork/main 服务端 CI 必红根因）**：conftest `_current_alembic_stamp` 探测在全新库（CI service container 无 `alembic_version` 表）吞错后把持锁连接留在 aborted 事务——会话末 `pg_advisory_unlock` 撞 InFailedSqlTransaction，server-tests 整列必红（#109 PR-head 即此签名，红仍被合入）。修为探测吞错即回滚 + 会话 fixture 解锁前保险回滚（会话级 advisory 锁不随回滚释放，安全）；回归钉 +1（search_path 复现缺表探测，A/B 验证：无修复红/有修复绿）。

### 测试与口径

- pytest **1884 收集（1878 passed + 6 skipped，本轮 +7；基线 `8f10771` 实测 1877）**：名字域全命中四路（规范名/保留行别名/转写来源名/来源自有别名）+ 子串不命中 + 三面清单与 counts / 并入行查询解析到 canonical（请求行原样+血缘解析）/ 未知与跨项目术语 404 / 零引用空面 / HTTP 面（200 形状+外人 403+未知术语与项目 404）/ 红线钉子（影响面永不进 api_catalog）/ 前置热修回归钉（fresh-DB 缺表探测吞错后连接可用）。
- 105 表不变（零 DDL）/ 迁移头 `e2c6a8f4d1b3`（34 rev）不变 / 业务路由 **296→297**（+1 只读 GET impact，不进 api_catalog）/ ENTRIES 94 不变 / mypy 基线 279 不变（新代码零新增）/ 桌面 vitest 765 不变（零改动，无需重打包）；改 server（零迁移）⇒ **rebuild 三镜像**（`alembic upgrade head` 幂等空跑校验 current）。

## [未发布] — V3 实施 T-C1：Delivery Compiler 最小闭环——confirmed 本体→方案骨架 + workflow 定义草稿纯函数编译预览（2026-11-05）

### 服务端（NEW `workflows/compiler.py` 纯函数；零迁移零路由零桌面改动）

- **`compile_delivery_preview(change_set, *, industry_template, gates, research_skill_ref, approval_capability)`**：confirmed 变更集（serialize_change_set 形状，非 confirmed 一律拒绝）+ 已发布行业模板 + 门禁状态摘要（T-D1 `_serialize_gates` 形状）→ 确定性编译预览（不读时钟/随机源，快照测试钉死）；落库一律走人工确认端点——骨架 → `solutions.create`、定义 → workflow 定义创建路由。
- **① 方案骨架 payload**：与 `solutions.create` 文本合同逐键对齐（TEXT_FIELDS 七键 name+六段、限长同尺 160/40000/16000，`_normalize` 原样可过）；六段布局沿 `/skeleton`「每段保留待补、责任主体永远是人」——本体段（create/update 术语含修订标注，update 以 new_term 为准）、指标术语入验收标准候选、模板模块（sort_order 排序）驱动设想/路径/交付物/排期、门禁摘要与术语合并入风险与依赖；来源行随 design_markdown 头部落档（变更集标题·确认时刻·采集来源）。
- **② workflow 定义草稿**：dag_json 模板化「调研→方案→审阅」三节点——调研 skill（ref 由调用方注入，published 白名单在 DB、纯函数不查库，沿 validate_dag 白名单注入制）→ 方案 call `solutions.create`（携带编译期骨架字段，唯一运行期字段 `opportunity_ids` 留 `{{research_brief.opportunity_ids}}` 占位，执行器整值替换原类型不字符串化）→ 审阅 human_approval（capability 默认 `workbench.write`，system.* 不开放）。产出的 dag 在真实 api_catalog 白名单下全绿零告警（`solutions.create` effect=write_db 不触发 rule 9）。
- **provenance（agent_trace 式来源标注）**：逐字段指认来源（`ontology_change_set:<id>` / `industry_template:<行业>@v<版本>` / `gates` / `delivery-compiler/v1`），落库后可回链编译输入。
- **不做全自动「本体→代码」**（主报告 §12 裁决）：编译器只产草稿，绝不写库、绝不绕过人工确认端点。

### 测试与口径

- pytest **1877 收集（1871 passed + 6 skipped，本轮 +6；基线 `1ef3a42` 实测 1871）**：整树快照（本体段/模板排序/指标入验收/门禁排序/provenance）/ 三节点 dag 真实目录白名单全绿零告警+拓扑序 / 非 confirmed+坏载荷点名拒绝（非数组·非对象项·未知动作·缺必填）/ 无模板无门禁待补回退+坏门禁行跳过 / 坏 skill ref 与坏 capability 拒绝 / 骨架 payload 过 solutions.create `_normalize` 合同。
- 105 表不变 / 迁移头 `e2c6a8f4d1b3`（34 rev）不变 / 业务路由 296 不变 / ENTRIES 94 不变 / mypy 基线 279 不变（新代码零新增）/ 桌面 vitest 765 不变（零改动，无需重打包）；改 server（零迁移）⇒ **rebuild 三镜像**（`alembic upgrade head` 幂等空跑校验 current）。

## [未发布] — V3 实施 T-D1：文档血缘补洞——快照 revision_id + 门禁摘要 + AI 调用 request_id 落库（2026-11-04）

### 服务端（审计 WB-DEF-6/7；1 列级迁移、零路由零桌面改动）

- **WB-DEF-7（调研答案血缘）**：文档快照 `confirmed_research_values` 每表单字典新增 `revision_id` 键，指向被采用的最新 confirmed revision——快照冻结后仍可反查答案出处；扁平布局不变，模板占位符解析零破坏。
- **门禁摘要**：快照新增 `gates` 段（每门 `gate_key/status/decision/submitted_at/decided_at`，按 key 排序）——文档生成时刻的门禁进度随快照冻结；有意不携带清单明细/证据指针（门禁面的数据不进文档镜像）。
- **WB-DEF-6（AI 调用血缘）**：AI 内容生成的 `request_id` 由生成器铸造并传入 `generate_document_fields`，冻结进版本行 `content_snapshot_json["ai_request_id"]` 并落 `document_generation_jobs.ai_request_id` 新列（迁移 `e2c6a8f4d1b3`）——版本行/任务行均可直接反查 `ai_call_audits` 审计记录。资格判定提为 `ai_content_applicable` 单一谓词：只有真正发起供应商调用的生成才铸 id（不产幽灵血缘）；再生成复用首代冻结字段不重铸（血缘恒指首代调用）；失败路径 id 随事务回滚。

### 测试与口径

- pytest **1871 收集（1865 passed + 6 skipped，本轮 +4；基线 `c8aa08a` 实测 1867——#103 goal-c4 +4）**：快照血缘指向最新 confirmed revision + 反查 / gates 摘要形状排序 / AI 血缘闭环（捕获 request_id → 版本冻结 + job 落列 + 审计反查 + 幂等不重铸）/ 非 AI 生成保持 NULL。
- 105 表不变（列级增量）/ 迁移头 `c7e1a9f3b5d8`→**`e2c6a8f4d1b3`（34 rev）**/ 业务路由 296 不变 / ENTRIES 94 不变 / mypy 基线 279 不变 / 桌面 vitest 765 不变（零改动，无需重打包）；改 server + 新迁移 ⇒ **rebuild 三镜像 + `alembic upgrade head`**。

## [未发布] — V3 实施 T-O4 桌面消费面：调研数据导入 UI + 导入结果让位回溯卡片（2026-11-04）

### 桌面端（服务端零改动：零迁移零路由、无需 rebuild 镜像）

- **导入对话框（两段式）**：项目调研标题行新增「导入对象」（可填写时出现）→ 选对象类型（部门/岗位/流程/AI 机会）+ CSV/XLSX 文件（≤10MB）→「解析预览」走 `POST /research/subjects/imports/preview`（桌面结构化 multipart 通道，AI 预调研同源）→ 预览表 + 行错误清单（422 `details.errors` 与内联错误同区，≤8 条点名）→「确认导入」走 `POST …/imports/commit`（30 分钟一次性 token + 期望版本）。
- **导入结果卡片**：导入完成显示新建数量 + 幂等回放标注；`merge_candidates` 让位行逐条回溯——行号、同名既有对象（类型+跟踪码）、文件中说明（T-O4「同名让位不新建」的人工拍板面），「查看 X」跳选既有对象；卡片可关闭。`stale_version` 时自动刷新调研数据并提示重新解析。
- **复用与适配**：T-O4 桌面契约同步轮预置的 `isResearchImportPreviewDto` / `isResearchImportResultDto` / `parseResearchImportErrorDetails` 首次接线（零消费欠账清偿）；15 个导入面错误码映射；jsdom File 无 `arrayBuffer()` → `readFileBytes` 双路径（真环境快路径 + FileReader 兜底），真机与测试同一代码。

### 测试与口径

- vitest **765**（+4：导入主路径含让位卡片回链+multipart 契约断言 / 行错误禁提交零 commit / 预览拒绝映射 / stale 提交刷新；串行口径 `--no-file-parallelism`；基线 `65a40c5` 实测 761）；`npm run typecheck` 绿。
- 服务端零改动：pytest 1863 收集（1857 passed + 6 skipped）不变、105 表/迁移头 `c7e1a9f3b5d8`（33 rev）/业务路由 296/ENTRIES 94/mypy 279 全部不变，**无需 rebuild 三镜像**；桌面改动交付=便携版重打包（r14）+ asar 字节验证。

## [未发布] — V3 实施 T-O4b 桌面合并 UI：subject 合并原语上 UI + 归档行回链（2026-11-04）

### 桌面端（服务端零改动：零迁移零路由、无需 rebuild 镜像）

- **对象树合并入口**：操作栏新增「合并」（选中非根对象且可填写时出现，与既有「停用」同位）→ 对话框内挑选**同类型启用对象**为目标 → 密码确认（危险确认对话框）→ 调用 `POST /research/subjects/{id}/merge`（#91 `dfe91b3` 服务端原语的唯一 UI 面；合并仍有意不进 api_catalog）。
- **归档行「已并入 X」回链**：树底新增「已归档（N）」折叠组——归档行不可选中、不进 treeitem 键盘导航；合并让位行显示「已并入 X」回链（目标仍启用=可点击跳选，已停用=纯文本）；普通停用行也在此一并可见。
- **契约同步**：`ResearchMergeResultDto` + `isResearchMergeResultDto`（subject=并入方序列化 + `merge_summary` 六面搬迁明细，值计数/画像字符串/null）；`subjectMutationError` 补 4 个合并错误码映射（根对象/类型不一致/双方须启用）。
- **实施偏差（记录在案）**：①「导入结果 merge_candidates 卡片一键合并」前置缺失——桌面端调研数据导入 UI 尚未立项（`imports/preview|commit` 端点与桌面 DTO 校验器在、零 UI 消费），留待「调研数据导入 UI」独立轮；②「对象树右键合并」以操作栏行内「合并」按钮替代，避免引入整套右键菜单系统。

### 测试与口径

- vitest **761**（+6：树 3 / 工作区 2 / 契约 1；串行口径 `--no-file-parallelism`；基线 `8340e89` 实测 755）；`npm run typecheck` 绿。
- 服务端零改动：pytest 1863 收集（1857 passed + 6 skipped）不变、105 表/迁移头 `c7e1a9f3b5d8`（33 rev）/业务路由 296/ENTRIES 94/mypy 279 全部不变，**无需 rebuild 三镜像**；桌面改动交付=便携版重打包（r13）+ asar 字节验证。

## [未发布] — V3 实施 T-G2：template_hash 漂移呈现——门禁序列化比对冻结哈希 vs 现行 gates.json（2026-11-04）

### 服务端（零迁移零路由；gap-matrix WB-DEF-5 / 风险册 F-2）

- **`_serialize_gate` 响应新增 `template_outdated: bool`**：比对 Gate 行实例化时冻结的 `template_hash`（seeds/gates.json 文件级 sha256）与现行镜像内文件的哈希，不一致即标注——存量行（迁移 `f7a2c9e4b1d3` 回填 `f52afe88…` ≠ 现行文件）响应即为 true，呈现即修复 WB-DEF-5「存量哈希与现行模板漂移、无比对呈现」；`template_hash=NULL`（未知出处）判 false 不误报。
- list/GET、证据提交、拍板四类响应共用同一序列化器，自动携带；哈希读取走进程级缓存（文件烘进镜像只读）。桌面 GateBoard 类型守卫只验必填键，新增键纯增量（桌面呈现消费留待 UI 轮）。

### 测试与口径

- 服务端 pytest **1863 收集 = 1857 passed + 6 skipped**（本轮 +1：懒实例化首访全不漂移 / 冻结哈希改写 → true / NULL → false 不误报；基线即 fork/main `6cccedb` 实测 1862 = 1856 + 6s——T-R2 记录的 1855 为其自轮 `e1568d6` 运行面，squash 并入 #98 携 +7 测试）。
- 口径：105 表不变、迁移头 `c7e1a9f3b5d8` 不变（零迁移）、路由 296 不变、ENTRIES 94 不变、mypy 基线 279 不变（104 distinct，实测零新增）；桌面端零改动（vitest 755 不变）。

## [未发布] — V3 实施 T-R2：工具目录结构化 effect/risk——目录权威外效判定 + WB-DEF-10 确认面补口（2026-11-04）

### 服务端（零迁移零路由；agent-policy P1-R2 / gap-matrix 域 9 / 风险册 WB-DEF-10）

- **api_catalog 结构化 effect/risk**：`CATALOG` 行新增 `effect`（`read | write_db | external`）与 `risk`（0–4，与 `automation_approvals.risk_level` 同尺度，≥3 = 密码确认/审批类）——ENTRIES 五元行不动，派生在装配层 `_catalog_row`（规则显式：GET=read/0；确认类（DELETE / .archive / .deprecate / 确认补口）=3；其余 external=2；普通写=1；4 留最高危未用）。
- **WB-DEF-10 补口**：`EXTERNAL_EFFECT_KEYS`（forms.export / solutions.export_sow / documents.generate / translator.translate = 异步作业或模型调用类）+ `CONFIRMATION_KEYS`（export_sow / documents.generate）——AI 经 `api_execute` 发起即 `awaiting_confirmation`（密码确认通道后才触发 worker 作业），绝不无确认排队模型调用。
- **TOOLS 五元扩 effect/risk**（17 工具）：(description, capability, properties, effect, risk)；`file_send_wechat`=external/3、`api_execute`=write_db/3、`lcsc_search`=external/2、其余只读=read/0；MCP `tools/list` annotations 改由结构化元数据派生（`readOnlyHint=effect==read`、`destructiveHint=risk>=3`），取代工具名硬编码集合；`api_catalog` 工具描述同步声明「外部副作用与风险分级」。
- **workflow rule 9 消费目录权威**：`validate_dag` 新增 `call_effects` 注入参（生产恒经 `catalog_call_effects()` 注入 CATALOG effect；None 时仅节点自声明生效，纯函数单测兼容）——call 节点目录 effect=external 即触发 `external_effect_without_approval` 告警，节点 effect 声明**只加不减**（不可把目录 external 降级为 read）；P1 仍告警不阻断（P2 转强制随 enforcement wave 另行）。
- **executor 外副作用推断收敛**：`_is_external_call` 由 `write` 字段推断改为结构化 `effect != "read"`（集合等价，清偿 T-W3 挂账「effect 结构化仍待 T-R2」）。

### 测试与口径

- 服务端 pytest **1855 收集 = 1849 passed + 6 skipped**（本轮 +4：目录 effect/risk 全量一致性扫描 / WB-DEF-10 双操作确认流 / tools/list annotations 派生 / rule 9 目录权威+不可降级+装配同域；解包适配为改造非新增）。
- 口径：105 表不变、迁移头 `c7e1a9f3b5d8` 不变（零迁移）、路由 296 不变、ENTRIES 94 不变、mypy 基线 279 不变（104 distinct，实测零新增）；桌面端零改动（vitest 755 不变）。

## [未发布] — V3 实施 T-R1：agent_tool_groups 只读工具组目录——`group:` 引用声明糖，resolve=交集组永不扩大（2026-11-04）

### 服务端（纯种子零新表：`seeds/tool_groups.json`；零迁移零路由）

- **组目录**（agent-policy P1-R1 ToolGroup / gap-matrix 域 7）：种子随代码发布（非用户可写），首批两组只读白名单——`research-readonly`（文件+项目/门禁/报价/本体/API 目录，9 工具）、`ops-readonly`（系统状态/动作留痕/立创运行史/技能只读/帮助，6 工具）；行含 `description`/`is_active`（停用=代码侧空贡献开关）。
- **声明解析**（`agents/tools.py::resolve_tool_groups`）：`agent_registry.allowed_tools` 支持 `"group:<name>"` 引用，解析为组工具集并入声明集（保序去重，直接项与组贡献并集）；**只收窄语义**——组贡献与直接声明同权进入既有三重交集管线（平台 deny ∖ 写类/会议面 ∩ 发起人档位地板 ∩ 插件安装态），组引用绝不绕过任何一腿。未知/停用组贡献为空（只收缩不放宽、运行面不崩溃）。
- **fail-fast 种子校验**：组引用未知工具装载即 `RuntimeError`（校验分母 = 网关 `TOOLS` ∪ 会议面 ∪ 沙箱生态 `read_file`，嵌套 `group:` 引用同拒）；沿 agents.json 种子校验先例，坏种子宁可起不起来不静默缩空。
- **报因补口**（`agents/service.py::_unavailability`）：声明判定改走解析前原样（`declares_run_tools`，组引用也算声明）——纯未知组声明解析为空面时明确报因 `tools_unavailable`，不静默放行空名单 run；空声明/仅会议面声明 agent 行为不变。
- `run_face_declared`/`effective_run_tools` 增 `groups` 注入参（仅测试用，生产恒走种子）；`list_agents` 序列化仍展示原始声明（组引用自描述，运行面解析留 run 时刻）。

### 测试与口径

- 服务端 pytest **1851 收集 = 1845 passed + 6 skipped**（本轮 +4：种子校验+未知工具/嵌套引用 fail-fast / 组不放宽三闸齐验（写类剥除·档位地板·插件安装态）/ 未知组收缩+报因 / 真种子混合声明保序去重）。
- 口径：105 表不变、迁移头 `c7e1a9f3b5d8` 不变（零迁移）、路由 296 不变、ENTRIES 94 不变、mypy 基线 273 不变；桌面端零改动（vitest 755 不变）。

## [未发布] — V3 实施 T-G1：任务产物→门禁证据候选——WB-DEF-8 双口径脱钩的候选闭环（2026-11-04）

### 服务端（迁移 `c7e1a9f3b5d8`：gates +`evidence_candidates` 可空 JSON 列；零新路由）

- **候选挂接**（`gate_service.attach_task_evidence_candidate`）：任务 `status=completed` 且自带门禁挂点（G1–9）+ 证据指针+指纹（T-E3 已把任务证据登记为一等证据行）→ 该产物登记为目标门禁的**候选**（task_id/task_key/task_name、指纹统一小写、提议人、提议时间）。建议性：清单项 claim_status 与门禁状态机一概不动，领用永远由人完成；同 (uri, hash, task_key) 幂等；上限 20 条丢最旧；门禁行未实例化时懒初始化（幂等）。
- **挂接点**（`task_service.update_project_task`）：乐观锁通过后按 effective 值（变更键 ∪ 既有任务字段）判定——三要素任意更新次序凑齐即挂（完成在后/在前皆可）；stale 版本零副作用。create 路径任务恒 not_started，天然不触发。
- **采纳即闭环**（`submit_gate_evidence`）：提交指纹命中候选（hash 忽略大小写）即剪除对应候选，面板不再重复提示；未命中者保留。
- 序列化契约 +`evidence_candidates`（恒输出，旧行 NULL→[] 读时合并）；事件 `gate_evidence_candidate_attached` 挂 gate 行并入门禁事件流（GATE_EVENT_TYPES 扩展）。
- **workflow 产物候选挂起**：run/节点产物（`output_json`）尚无「指针+sha256」形状，待产物 schema 立项后零改挂入（挂接函数已按通用形设计，收 (uri, hash, 来源粒度)）——偏差已回写 backlog T-G1 实施记录。

### 桌面端（GateBoard）

- 清单项下新增「任务产物候选」区：候选出任务键/名与指针+指纹，选目标清单项一键「采纳到清单」（走既有提交闸，服务端命中剪除）；evidence 态也可补采纳（部分采纳流）；viewer 只读；旧载荷无键兼容、非法形状整板拒渲染（fail-loud）。

### 测试与口径

- 服务端 pytest **1847 收集 = 1841 passed + 6 skipped**（本轮 +6：挂接+契约+事件 / 三缺一不挂 / 次序无关+幂等 / 采纳剪除+claimed / 部分采纳保留 / 拍板零感知；上轮口径差 +3 为 #93 skill 两闸用例）+ 迁移往返（HEAD `c7e1a9f3b5d8`，33 rev）。
- 桌面端 vitest **755/755**（+3：候选渲染+采纳流 / viewer 只读+旧载荷兼容 / 非法形状拒收）+ typecheck 通过。
- 口径：105 表不变（列级增量）、路由 296 不变、ENTRIES 94 不变、mypy 基线不变（新代码零新增）。

## [未发布] — docs：archify 整套架构图入库——五视角交互式证据图 + 复跑回执（2026-11-04，纯文档零代码零迁移）

- 新增 `docs/architecture/archify-diagrams/`：用 archify（v3.0.1）从本仓库真实代码取证生成的**五视角**架构图，每张独立 standalone HTML（内联 SVG、暗/亮主题、可导出 PNG/JPEG/WebP/SVG/WebM、路径/透镜视图）：
  - `architecture/` 系统总体架构（14 节点 / 16 连接 / 4 边界）
  - `workflow/` 交付主流程：从项目到回款（13 节点 / 15 边 / 6 车道，含 fail 整改 / 人工免终审 / L1 接管 / 409 闸拦分支）
  - `sequence/` Workflow run 一次执行完整调用链（8 参与者 / 42 消息 / 10 段，四类节点分派）
  - `dataflow/` 集成桥采集 → 服务端投影 → 一等证据登记簿（指针 + sha256 红线）
  - `lifecycle/` Workflow 运行生命周期双层状态机（run 七态 + node 八态，幂等键 / 断链 / cancel / resume）
- 每张同级含 `candidate.json`（生成输入）+ `receipts/`（通过轮 finalize/deliver/check/browser-check 回执）+ `preview.png`（1440×900 亮色截图），`index.html` 汇总入口。
- 文档口径纠偏（以代码为准）：run 起始态 `queued`（非 `pending`）；发起路由 `POST /projects/{pid}/workflows/{def_id}/runs`；桌面控制台可列/详情/取消/恢复、**不能**发起 run。
- README「技术架构」节加一段指向本目录的锚注。
- 口径数字全部不变（105 表 / 路由 296 / ENTRIES 94 / 迁移头不变）；零路由零迁移零桌面改动。

## [未发布] — V3 实施 T-O4b：subject 合并原语——表单/答案/链接/子对象/备忘录/画像单事务搬迁（2026-11-04）

### 服务端（迁移 `d4e6f8a2c7b9`：+`merged_into_subject_id` 可空列；一条人工路由 295→296）

- **合并原语 `merge_subject`**（`research/subject_service.py`，T-O4 遗留候选收口）：source 并入 target（同项目同类型、双方 active、非 project 根，单事务全成全败）。六面搬迁纪律：
  - **表单/答案**：form_key 不撞 → 整表搬迁（修订+答案随外键同行）；撞键且源从未采集过答案 → 让位删除；**撞键且源有答案 → 409 `merge_form_conflict` 点名键**（绝不静默丢采集，人工先处置再重试）。
  - **链接**：边重指到 target；会变自环或与存续边重复的让位删除（唯一边约束永不违反）。
  - **子对象**：随迁（同类型 ⇒ 父类型规则天然成立，含归档子行）；**既有合并链一跳化**（曾并入 source 的行重指 target）。
  - **备忘录**：共享 memo 与个人备忘录均带「（合并自 名字 跟踪码）」头并入（与编辑闸同尺 20 000，超长显式截断标记）；目标无同人个人备忘录则整行重指。
  - **机会画像**：目标无 → 整行迁入；双方都有 → **目标留任**（机会画像创建即有，留任是唯一可行语义），源画像关键字段随事件留档。
  - **跟踪码不回收**：source 归档后永久占号（`merged_into` 指向存续方），新号接既有最大值——`allocate_tracking_codes` 扫全量行天然兼容。
- **DB**：`project_research_subjects` + `merged_into_subject_id`（复合外键 RESTRICT 自引用 + 两条 CHECK：不自指、指向即必归档 + 索引）；归档行保留 subject_key/跟踪码占位（UNIQUE 绝对，语义同 T-O1 merged 术语）。
- **路由**：`POST /projects/{id}/research/subjects/{source_id}/merge`（body `{version, target_subject_id}`，`_require_subject_write` 同档案闸）；**有意不进 api_catalog**（业务对象不走 change_set 双轨，T-O3 裁决维持；钉子测试在位）。
- 事件 `project_research_subject_merged` 挂 source 行，载荷带全部搬迁计数与双跟踪码。
- 序列化契约 +`merged_into_subject_id`（旧载荷无键向后兼容）；根检查先于类型检查（根对象永不参与合并）。

### 桌面端（仅契约同步，零新页面）

- `ResearchSubjectDto` + 可选 `merged_into_subject_id?: string | null`；`isResearchSubjectDto` 运行时校验同步（缺键旧载荷/带键新载荷都收，非法形状拒收）。

### 测试与口径

- 服务端 pytest **1838 收集 = 1832 passed + 6 skipped**（+7：全表面搬迁+占号 / 撞键 409→处置后成功 / 类型·根·自指·stale·归档源目标拒绝 / 链一跳化 / 画像迁入与留任 / 权限（viewer 403、非成员 404））+ 迁移往返 1 例（HEAD `d4e6f8a2c7b9`，32 rev）。
- 桌面端 vitest **752/752**（+2：合并指向键兼容性）+ typecheck 通过。
- 口径：105 表不变、路由 **296**、ENTRIES 94 不变、mypy 基线不变（新代码零新增）。
## [未发布] — 修复 mac 图标管线回写 Windows 图标（2026-11-04）

- `desktop/scripts/generate-icon.sh` 原本把 swift 渲染结果写回 `build/icon.png`——Windows 图标源会在 macOS 构建时被静默覆盖（产品更名轮手工替换的新图标跑一次 `package:mac` 即丢失）。改为渲染只进临时目录：`build/icon.png` / `icon.ico` 由品牌资产独立维护，macOS 管线只产出 `icon.icns`。
- mac 工具链（swift / sips / iconutil）无法在 Windows 上验证，本改动为纯输出路径调整，待下次真实 mac 打包核验；渲染输入源暂仍为 `assets/logo.png`（旧图），mac 图标换新待品牌透明 mark 资产（SVG 转透明 PNG）落定后一行重指。

## [未发布] — 使用帮助三面同步：工作流 / 术语表 / Skill 治理入册（2026-11-04）

- 三面同步（`docs/工作台操作使用手册.md` = 镜像内 `bundled/help_manual.md` = 桌面「使用帮助」）：项目详情 8→**10** 标签页；新增 §3.7 工作流（run 七态/节点八态/取消幂等语义/恢复 failed-only）与 §3.8 术语表（搜索/关系类型只读/变更集评审·否决留痕·拍板人≠提交人 403）；§8.1 补 Skill 卡「版本」治理对话框（版本历史/效果统计/提交评审-发布-回滚-弃用）；任务中心标注工作流人工审批；§11 术语速查补「变更集」；§12 缺口清单补「工作流定义新建无 UI 入口」；手册头部说明改为如实分发口径。
- 桌面 HelpPage 新增「工作流与术语表」章节 + KNOWN_GAPS 同步 + help-page 测试钉新章节与诚实语义。帮助文案与文档改动，零业务逻辑、零迁移、零路由。

## [未发布] — 文档收口：README 能力面与品牌资源同步（2026-11-04）

- 「主要能力」与首段补入已落地的用户可见能力：工作流控制台（T-W6：定义/运行/取消/恢复）、项目术语表（T-O1/T-O3/T-W6）、Skill 治理态与效果统计（T-S1/T-S2）；任务中心标注工作流人工审批（T-W4）。
- 页首改指产品更名后的品牌资源 `logo-caigong-fde.svg`；「更换 Logo 与安装图标」一节按现役管线重写（界面品牌资源清单 / Windows 构建图标 / macOS 图标生成链，`logo.png` 保留为 macOS 图标源）。纯文档改动，零代码。

## [未发布] — V3 实施 T-W6：桌面控制台三面——工作流 / 术语表 / Skill 版本治理（2026-11-04）

### 服务端（零迁移；两条只读列表路由为桌面控制台最小补面）

- **偏差回写**：workflow-dag-v1 §5 设计七条不变；控制台要「run 列表/取消/恢复」就得能枚举，故补两条 can_view 只读挂件——`GET /projects/{id}/workflows`（定义列表，新者在前，项目内定义天然少量无分页）与 `GET /projects/{id}/workflow-runs?limit=`（run 列表，默认 50 上限 200 有界扫描，`truncated=true` 诚实标注）。**列表行不带 nodes**（N+1 不可取），节点树走既有详情路由按需展开。
- 路由总数 293→**295**；ENTRIES 94 不变；迁移头 `b5d9e3f7a1c6` 不变。

### 桌面端（三张新页，页面仅呈现、写操作全走既有服务层闸）

- **WorkflowConsole**（`workflows/WorkflowConsole.tsx`，项目详情新 tab「工作流」）：定义卡片（状态/版本/节点数概览）+ run 列表（七态标签/错误摘要/`truncated` 提示）+ 按需展开节点态树（八态标签/attempt/错误）；**取消**（非终态可点，幂等语义照服务层——终态 409 `already_terminal` 原样呈现）与**恢复**（仅 failed，409 `not_resumable` 同）按钮挂 canManage。
- **GlossaryPage**（`ontology/GlossaryPage.tsx`，项目详情新 tab「术语表」）：术语只读清单（q 搜索按规范名/别名）+ 关系类型只读清单（登记/停用走管理通道，全局行需运维员——lesson 15 口径）+ **变更集评审**：状态过滤五态、载荷展开（动作明细 + base 指纹）、draft→提交评审 / in_review→确认物化 / 否决需理由；服务端「≠提交人」403 原样呈现不吞。
- **SkillVersionsPage**（`extensions/SkillVersionsPage.tsx`，扩展中心每张 Skill 卡新增「版本」按钮的治理对话框）：版本历史（指纹前缀/测试报告有无/当前标记）+ **效果统计**（消费 T-S2 `usage` 块：total/chat/workflow/last_used_at/by_version/truncated——by_version 正是回滚决策依据）+ 治理动作：draft→提交评审、in_review→发布（密码确认+豁免说明）、published→回滚（选目标版本+密码+豁免）/弃用；权限外只读（「只有公共 Skill 运维员或个人 Skill 属主可以执行治理动作」）。
- 项目详情 tab 枚举扩展：`overview/tasks/gates/commercial/research/delivery` + **`workflow` + `ontology`** + `library/management`（路由哈希与 tab 同步，无 legacy 映射需求）。

### 测试与口径

- 服务端 pytest **1831 收集 = 1825 passed + 6 skipped**（+1：定义/run 列表路由权限·排序·截断·400 界）。
- 桌面端 vitest **750/750**（+18：workflow-console 5 / glossary-page 6 / skill-versions-page 7）+ typecheck 通过。
- 用例钉住诚实语义：failed 本就是终态不显示取消；取消竞态 409、自确认 403、错密码 403 全部原样呈现；无密码/无回滚目标客户端侧先拦；无治理权只读提示。

## [未发布] — 产品更名「蔡工FDE智能交付系统」+ 集成桥 stale 标记去重（2026-11-04）

### 品牌统一（产品名口径 + 品牌素材）

- **产品名统一为「蔡工FDE智能交付系统」**：新增 `desktop/src/renderer/src/brand.ts` 作为**产品名的唯一来源**（`PRODUCT_NAME` 全名 / `BRAND_NAME` 短名 / `BRAND_SUBTITLE` 副标题 / `DEVICE_LABEL` 登录设备标签），此前产品名散落在十余处硬编码，改名必然漏改——现全部改为引用常量。
- **落地位置**：侧边栏品牌区（蔡工FDE / 智能交付系统）、登录页主标题、窗口标题（`index.html` 的 `<title>`，Electron 主窗口由此继承）、立创内置浏览器与查询跟踪窗口标题、`desktop/package.json` 的 `productName` / `description` / `author` / DMG 标题、服务端内置助手 system prompt、README 首屏标题与正文。
- **品牌素材换新**：侧边栏与 favicon 换用蔡工FDE 标识（`logo-caigong-fde.svg` / `.png`），应用图标（`build/icon.png` / `.ico`）同步更新。
- **有意未改**：便携版目录命名 `蔡工FDE-<version>-便携版-r<N>`（`fde-package-verify` 技能约定的交付口径，改动会破坏「旧目录永不覆盖」的回退约定）、`package.json` 的 `name` / `appId` / `artifactName`（机器标识与产物文件名口径，非用户可见名）。

### 缺陷修复：集成桥 stale 标记重复

- **根因**：服务端 `bridge/sync.py` 对 openfde 与 fdeops 两条采集轨**各自**判定断连并各 `append("stale")`，双轨同时断连时同一行出现**重复标记**——前端会渲染出**两个同名「采集断连」徽标**，并因 `key={flag}` 重复触发 React 警告（`Encountered two children with the same key`）。
- **修复**：服务端改为「任一轨断连即 stale，只判定一次」（C9 的双轨独立报警语义不变：单轨断连仍照旧报警）；前端新增 `uniqueFlags()` 渲染前按出现顺序去重——`flags` 是可重复的观察项而非互斥枚举，前端不应假设其唯一。**两侧都修**，服务端收敛事实、前端兜底渲染。
- **回归钉子**：服务端新增 `test_both_tracks_stale_yields_single_stale_flag`（双轨同时断连只报一次，且 flags 整体无重复）；桌面端新增「renders a duplicate flag only once」（重复 flag 只渲染一个徽标）。已实测：还原旧实现时新测试**确实失败**，修复后通过。
- **口径**：服务端 pytest **1820 passed + 6 skipped**（+1）/ 桌面端 vitest **732/732**（+1）/ typecheck 通过。
## [未发布] — V3 实施 T-S2：Skill 效果统计 + 治理留痕（回滚已随 T-S1 落地，2026-11-03）

### 服务端（零迁移零新路由 / 零桌面改动）

- **效果统计（agent-policy §2.4「run 面累计 usage，operation_events 已有基础」落地）**：双消费面计数——`skill_used_chat`（MCP `skill_read` 成功读出指南）与 `skill_used_workflow`（工作流 skill 节点按 pinned 版本完成一次确定性 AI 调用）；**失败不计**（AI 异常/重试是噪声不是效果，`skill_ref_unavailable`=内容未被消费），attempt 代际各计一次（resume 重跑每次都真消费了），`skill_list` 只浏览不计数。
- **独立微事务计数**：直连 AI 工具循环每轮 tool 后回滚共享会话（假定工具只读），经 `call_tool` 的消费计数自带已提交事务才能存活——与 `run_lcsc_skill` 自管事务的先例同构，专项测试钉「call_tool 后 rollback 事件仍在」。
- **统计读出（零新路由）**：`GET /extensions/skills/{id}/versions` 响应新增 `usage` 块 `{total, chat, workflow, last_used_at, by_version, truncated}`——有界扫描（最近 1000 条消费事件）Python 侧聚合，触顶 `truncated=true` 诚实标注；`by_version` 供回滚决策（旧版本还在被 workflow pinned 引用吗）；治理事件不进 usage。
- **T-S1 审计缺口顺带收口**（gap-matrix 域 8「回滚留 operation_events」）：补齐四条治理事件 `skill_review_submitted / skill_published（version+waive_reason）/ skill_rolled_back（from_version+to_version+waive_reason）/ skill_deprecated`，与生命周期操作同事务落表；闸失败（错密码/材料缺失）不留事件。
- **实现偏差（backlog 已回写）**：事件不走 `projects/events.py::record_event`——`events.py` 顶层引入 `control.models` 会经重型 `control/__init__` 反转 projects↔control 导入序（实测即环），改用 control 层 `_event` 直落 `OperationEvent` 的既有同构（api_actions 先例）；`target_type="skill_definition"`、`project_id=None`（Skill 不挂项目）。
- **测试**：`test_skill_lifecycle.py` **7→11**（治理事件四类+闸失败零事件 / chat 计数+回滚存活+404 不计数 / usage 汇总+零值+按版本 / truncated 诚实标注）+ `test_workflow_executor.py` 两用例扩展（pinned 版本消费断言 / 失败 attempt 不计）。服务端 pytest **1829 收集 = 1823 passed + 6 skipped**（+4）/ vitest **731 不变**。**零迁移**（head `b5d9e3f7a1c6` 不变）/ **零新路由**（283 不变）/ ENTRIES 94 不变。

## [未发布] — 桌面端视觉统一：设计令牌体系与缺失样式类补齐（2026-11-03）

### 纯 CSS 重构（零功能变更，零 TSX 逻辑改动）

- **修复三处结构性缺陷（根因不是"配色不好看"）**：
  - **① 关键样式类零 CSS 规则**：`.page` / `.card` / `.page-heading` / `.page-subtitle` / `.muted` 在全局样式中**没有任何规则**（提取全部 tsx 的 className 与全部 css 选择器做差集确认），致使翻译器、指标报表、试点报告、派单池、调度台、开闸运维等 **7 个页面整页裸奔**——无卡片容器、无内边距、无层级，输入框挤在一行、标题与正文同字号。**本次补齐全部原语。**
  - **② 六个 CSS 变量从未定义**：`--border` / `--panel` / `--accent` / `--text-muted` / `--border-color` / `--surface-alt` 查无实据，`border: 1px solid var(--border)` 因变量不存在而**整条声明作废**，派单页簇所有卡片**完全没有边框**。**本次在 `:root` 集中定义并保留旧名别名**（旧写法零改动继续可用）。
  - **③ 组件样式表各自为政**：`task-board.css`（12 色）与 `ai-server-chat.css`（45 色）自成色板，与全局令牌脱节。**本次全部改走令牌。**
- **统一设计体系**：`:root` 重写为**九层令牌体系**（品牌色阶 / 中性面 / 文字 / 描边 / 语义色 / 圆角 / 阴影 / 间距梯度 / 字阶）+ 控件尺寸，每层带注释；新增 `pages/pages.css` 承载翻译器 / 指标报表 / 试点报告 / 派单页簇 / 帮助页的版式骨架；按钮统一高度（38px）/ 圆角 / 阴影与悬停·按下·禁用态；徽标语义色、表格行高描边表头、输入框边框聚焦环占位符统一；**4 套并存标签页收敛**为分段式一套（`extension-tabs` 保留下划线式以区分内容层级）。
- **现代感与纵深**：页面底与卡片加入品牌色径向渐变晕染，阴影分六级、圆角五档，卡片悬停浮起；硬编码色值**约 250 处 → 82 处**（余下绝大多数位于 `:root` 定义内）。
- **验证**：`npm run typecheck` 通过；`npm run build` 通过（`pages.css` 已进产物 CSS）；桌面端 **731** 例测试全绿（60 文件）；新增 `desktop/gui-harness/shots.mjs` 逐页视觉走查（13 页，零 console error）。
- **工具**：新增 `scripts/watch-pr-checks.py`——守望 PR 的 CI check-runs 收敛。**只用 `commits/<sha>/check-runs` 索引**（`actions/runs` 的两种索引都不可靠），且**显式区分「空列表」与「已收敛」**（空结果≠收敛，否则索引抖动会造成假绿）；收敛前额外核对 4 个 CI job 齐全。

## [未发布] — V3 实施 T-O4：导入别名去重（同名让位 + 合并候选 change_set，2026-11-03）

### 服务端（零迁移零路由 / 桌面端契约同步）+ 桌面端（验证器/类型/测试）

- **两把尺子裁决（附录 D ⑨ 导入重复根治）**：**文件内同名 = 致命行错误** `duplicate_name`（preview 报且首行干净，commit 同尺复核——文件是用户声明，歧义由人解决，不替人猜）；**文件 vs 项目既有 active 同名（同类型）= 让位**——撞名行不再静默新建合成键对象（`import_<type>_<preview>_<row>` 每行各异的旧路径），改为合并候选。归档/停用行不拦重建，跨类型同名（部门的销售部 vs 角色的销售部）是不同实体不去重。
- **合并候选三面呈现**：①导入结果载荷新键 `merge_candidates`（name/row/description/matched_subject{id,name,tracking_code}——被让位行的说明无损保留供拍板）；②跟踪码只发真正新建的行（让位不占号，新号接既有最大值，不产生空洞）；③**全部让位 = 合法成功**（零新建 + 全量候选 + 版本照常 +1，重复导入幂等友好；收据回放完整带出候选，`idempotent_replay` 语义不变）。
- **合并候选 → change_set 提案（T-O3 闭环的自然落地）**：候选名若无术语行/别名占用（且 ≤TERM_MAX_LENGTH=120），按首现序去重提案 `create_term`（definition=被让位行说明，超长截 120）——**draft** 变更集带 `captured_from="research_import:<preview_id>"`，经既有 submit→confirm 人工拍板坐实「同项目一个名字一个概念」；拍板拒绝无残留（让位已在导入侧完成，术语只是不登记）。**动作域不因 T-O4 开 subject 合并**（T-O3「业务对象不走 change_set 双轨」裁决仍成立；subject 合并原语牵动表单/答案/链接/跟踪码，L 级别另行立项）；候选名已有术语/别名占用时不提案（物化期 409 term_exists 的死路不走）；超 `CHANGE_SET_MAX_ITEMS`=50 截断并在 description 注明。ontology/service 新增占位检查原语 `existing_term_names`。
- **桌面端契约同步（精确键集校验不破）**：`isResearchImportResultDto` 精确键集 +`merge_candidates`（`ResearchImportMergeCandidateDto` 类型 + 验证器 `isResearchMergeCandidateDto` + 测试 2 例）；preview 载荷零变化（`duplicate_name` 走既有 errors 通道直透，`isImportError` 只验形状）。
- **测试**：`test_research_imports.py` **+7**（批内同名致命/让位+提案+跟踪码钉子/全让位+回放带候选/术语占用不提案/confirm 闭环落 confirmed 术语+验收分离/跨类型不去重/超长说明截断）；桌面 `project-runtime-validation.test.ts` +1。服务端 pytest **1825 收集 = 1819 passed + 6 skipped**（+7）/ vitest **731**（+1）。**零迁移**（ontology_change_sets 表 T-O3 已备）/ 零路由（293 不变）/ ENTRIES 94 不变。
- **有界查询不变量**：commit 的同名让位扫描为**恒定 1 次**整行 select（不随行数乘法），既有 bounded-queries 测试上限 1→2（注释钉住）。

## [未发布] — V3 实施 T-O2b：对象类型值域开放（T-O2 注册表的 subject_type 真正可用于新建对象/表单/导入，2026-11-03）

### 服务端（1 个迁移（零新表：三处 CHECK 放宽 + 三列放宽）/ 零路由 / 零桌面改动）

- **值域从枚举到格式**：`project_research_subjects` / `template_research_forms` / `project_research_import_batches` 三处 subject_type CHECK 改码格式 `^[a-z][a-z0-9_]{0,59}$`、列宽 32→60（迁移 **`b5d9e3f7a1c6`**，31 rev；枚举 ⊂ 格式，存量全兼容；downgrade 收窄时超长注册码行被枚举 CHECK 挡下——保护语义）。
- **单原语闸门**：新建调研对象只认「内置五类 ∪ 注册表 active 行（全局∪项目内）− project 根」，把守在 `create_subject_in_transaction`（人工创建与导入 commit 同闸）；retired=禁新建存量只读、draft=未拍板提案，都拦闸外（`usable_subject_type_codes`，与引用解析用的 `known_subject_type_codes` 两把尺子）。错误码新设 400 `unsupported_subject_type`。
- **导入三闸一致**：authorize 带回项目可导入域 → preview/store 前置校验（缺省退回内置四类）→ commit 原语复核（覆盖 preview→commit 30 分钟 TTL 内 retire 窗口）。
- **消费方对齐（防静默丢内容）**：文档快照按行上实际类型分组（注册/退役类型的存量对象不再被丢弃）；表单定义/AI 表单生成/模板四处校验器全部接「内置 ∪ active」；映射校验允许域从已发布 research definition 派生（保持纯函数）。
- **两条基线不放开**：AI 生成表单缺省仍只认内置五类（防幻觉）；行业模板五类内置调研表必备（开放值域 ≠ 放弃底线）。
- **注册类型对象语义**：无父级规则 → 本轮仅允许根级；无跟踪码前缀 → `tracking_code=null`；备忘录/合并功能域白名单（内置四类）冻结不动。
- **测试**：新增 `test_ontology_subject_type_domain.py` **9 例**（usable 域作用域/状态、注册类型 HTTP 全链路+四类拒绝、retire 存量保留+快照、导入三闸、定义/AI/映射/模板域、内置码覆盖钉子）+ 迁移往返 **1 例**（双向列宽/CHECK/数据保留 + 存量行挡降级保护语义）；`HEAD_REVISION` → `b5d9e3f7a1c6`。服务端 **1818 收集 = 1812 passed + 6 skipped**（+10）。改 server + 新迁移 ⇒ rebuild 后必 `alembic upgrade head`（api/worker/scheduler 三镜像）。

## [未发布] — V3 实施 T-O3：变更集 ontology_change_sets（AI 候选唯一入口：propose→submit→confirm 人工拍板闭环，2026-11-03）

### 服务端（1 个迁移（一张新表，唯一 DDL）/ 7 条新路由 / 零桌面改动）

- **变更集**：`ontology_change_sets`（title/description/proposed_json 载荷/diff_summary 人读摘要/status ∈ draft·in_review·confirmed·rejected·superseded/base_snapshot_sha256 并发防护指纹/captured_from 候选来源标记/提交与拍板留痕）。迁移 **`c9e3a7d1b5f8`**（30 rev，additive，含 downgrade）。AI 产物永不直接写术语/类型表——候选载荷进 proposed_json，人工拍板后才逐项物化。
- **状态机与并发防护**：draft →(submit)→ in_review（对受影响行快照取 sha256 指纹）→(confirm)→ confirmed / →(reject)→ rejected（留 reason）；draft 可否决（撤回）。confirm 复核指纹——既有行被并发改写或占位名凭空出现/消失都判漂移，**409 `base_conflict` 零物化**。confirm **单事务全成全败**：任一项物化失败整体回滚（无 partial），错误 `change_set_item_failed` 点名项次；成功落 `ontology_change_set_confirmed` 事件携带逐项结果。
- **物化语义**：`create_term` 直落 confirmed；`update_term` 同名=原行受控改写（旧定义随事件留档；**change-set confirm 是全系统唯一 definition 写路径**）、改名（`new_term`）=新行 confirmed+原行 superseded 指 canonical+原名转别名；`merge_terms` 走 T-O1 原语（合并保留来源）；`register_relation_type` 只登记项目内类型（全局登记留 admin 人工路由）。`create_subject`/`link_subjects` 设计列有、本轮不开放（propose 即点名拒绝）。
- **验收分离（P0-5 纪律移植）**：confirm/reject 均要求拍板人 ≠ 提交人（403 `change_set_decider_conflict`，沿 gate 先例）。
- **HTTP 面（人工路径，不进 api_catalog）**：`GET /projects/{id}/ontology/terms?q=`（T-O1 欠账的术语只读面，别名命中返回属主行）+ change-sets 六条（propose/list/detail/submit/confirm/reject；submit 为设计 §4 表外补充——`not_in_review` 预设评审态、指纹语义锚在提交时刻）。跨项目 404 `change_set_not_found`（不泄露存在性）。事件目标注册表 +`ontology_change_set`。
- **测试**：`test_ontology_registry.py` **8 例**（payload_schema 校验族 / 状态机+HTTP 全链路（含验收分离、重复确认、跨项目、?status= 过滤、confirmed 事件逐项结果）/ base_conflict 双漂移（行改写+占名抢注）/ 单项失败整体回滚 / update_term 同名与改名双分支 / captured_from AI 通道 / merge+register 物化 / 术语 GET 面 + api_catalog 三面钉子）+ `test_migrations.py` 迁移往返 **1 例**（载荷 JSON 落行可读 + 状态 CHECK）；`HEAD_REVISION` → `c9e3a7d1b5f8`。
- **口径**：业务表 **104→105**（+ontology_change_sets）/ 迁移头 **`c9e3a7d1b5f8`（30 revision，+1）** / 路由 **286→293**（+7） / api_catalog ENTRIES **94 不变** / pytest **1808 收集 = 1802 passed + 6 skipped**（本轮 +9：变更集 8 + 迁移往返 1；较 T-O2 记录基线 1798 的 +1 为该轮基线记法偏差，与本轮无关） / vitest 730 沿用（零桌面改动）。
- **部署**：`docker compose build && up -d` 后 **`alembic upgrade head`**（一张新表；**api/worker/scheduler 三个镜像都要 build**）。

## [未发布] — V3 实施 T-O2：关系/对象类型注册表 ontology_relation_types（关系类型不再硬编码，2026-11-03）

### 服务端（1 个迁移（一张新表，唯一 DDL）/ 3 条新路由 / 服务层 ∪ 接入 / 零桌面改动）

- **注册表**：`ontology_relation_types`（`kind` ∈ subject_type/link_type；`code`/`label`/`description`；端点约束 `allowed_source_types`/`allowed_target_types`；`status` ∈ draft/active/retired；`project_id` 为空=全局类型、仅 admin 可建）。迁移 **`b8d3f1a5c7e2`**（29 rev，additive，含 downgrade）。把审计附录 D ②③ 的「对象类型 CheckConstraint 硬编码」「link_type 白名单硬编码 2 种」的扩展面搬进可注册表。
- **∪ 接入（服务层）**：`research/subject_service.py` 的 `_validate_link` 改为「**内置优先** + 注册表」——内置两类关系类型的端点约束是存量语义，注册表**不得覆盖内置码**（注册内置码 409 `duplicate_code`），故「∪ 语义不得放开内置方向校验」由机制保证；注册类型按端点约束判方向（不符仍 422 `invalid_research_subject_link`）；**retired 类型禁新边 409 `link_type_retired`、存量边只读**；未知类型 422 且消息附当前可用类型清单。内置集合与注册表保留名单的一致性由测试钉住（防漂移）。
- **作用域**：项目内类型**遮蔽**同名全局类型（端点约束可按项目定制）；项目内 `UNIQUE(project_id, kind, code)` + 全局部分唯一索引（`project_id IS NULL`）两段实现设计稿的「全局/项目内各自唯一」。
- **HTTP 面（人工路径，不进 api_catalog）**：`GET/POST /projects/{id}/ontology/relation-types`（can_view / can_manage；`scope=global` 另需 admin）+ `POST …/relation-types/{id}/retire`（让「retired 后建边 409」在人工路径上可达）。登记/停用落 `ontology_relation_type_registered`/`_retired` 事件；事件目标注册表 +`ontology_relation_type`。
- **边界（重要）**：`kind=subject_type` 本轮**只落登记不开放使用**——新建调研对象仍只能取内置五类（三处 DB CheckConstraint 按设计兼容边界冻结），放开值域会连带表单定义/文档映射/文档快照/AI 模板 schema 五处消费方，属独立一轮（T-O2b）。`research/models.py` 仅加注释不改约束。
- **测试**：`test_ontology_registry.py` **7 例**（登记校验+内置码保护+作用域遮蔽 / 全局与项目遮蔽 / 内置冻结与漂移钉子 / DB 约束拒非法态 / HTTP 面与建边生命周期（注册→建边→方向不符→停用→禁新边→存量边可读）/ 全局类型登记与停用仅管理员 / api_catalog 钉子）+ `test_migrations.py` 迁移往返 **1 例**（全局部分唯一索引 + 项目内同名共存 + 端点约束 CHECK）；`HEAD_REVISION` → `b8d3f1a5c7e2`。
- **口径**：业务表 **103→104**（+ontology_relation_types）/ 迁移头 **`b8d3f1a5c7e2`（29 revision，+1）** / 路由 **283→286**（+3） / api_catalog ENTRIES **94 不变**（`research.link` 描述同步端点约束口径）/ pytest **1798 收集 = 1792 passed + 6 skipped**（+8） / vitest 730 沿用（零桌面改动）。
- **部署**：`docker compose build && up -d` 后 **`alembic upgrade head`**（一张新表；**api/worker/scheduler 三个镜像都要 build**）。

## [未发布] — V3 实施 T-O1：术语表 ontology_terms+aliases（同项目一个名字一个概念，2026-11-03）

### 服务端（1 个迁移（两张新表，唯一 DDL）/ 零路由 / 零桌面改动）

- **唯一性底座**：`ontology_terms`（UNIQUE(project, term)+状态机 draft/confirmed/superseded/merged+merged 必须指向保留行的 CHECK+乐观锁 version）与 `ontology_term_aliases`（UNIQUE(project, alias)，冗余 project_id 供导入去重点查）——同项目一个名字至多指向一个概念，是「导入同名重复」（审计附录 D ⑨）的根治面。迁移 **`a3e7c1f9b5d2`**（28 rev，additive，含 downgrade）。
- **服务原语**：`ontology/service.py` 的 `create_term`（别名占用先于同名预检；`initial_status="confirmed"` 直落供变更集 confirm 用）/ `confirm_term`（draft→confirmed 拍板；confirmed 409 `term_immutable` 不可原地改——服务层无 definition 编辑路径，修订走 change_set 新版本）/ `merge_terms`（合并保留来源：source 规范名转写为保留行别名、source 既有别名不动走 canonical 链、**链一跳化**重指、逐项 OperationEvent `ontology_term_merged`）。
- **零路由（T-W1 先例）**：术语公开面只有只读 GET；写路径一律经 change_sets propose→confirm（AI 候选永不直接写表）——REST 面随 T-O3 routes.py 开；治理面不进 api_catalog（钉子测试）。事件目标注册表 +`ontology_term`。
- **测试**：NEW `test_ontology_registry.py` **7 例**（生命周期+confirmed 不可变 / 入参归一 / 同名+别名占用唯一 / 合并保留来源链+409 族 / 别名 DB 唯一 / CHECK 拒非法态 / api_catalog 钉子）+ `test_migrations.py` 迁移往返 **1 例**（自引用外键落 canonical/merged 对）；`HEAD_REVISION` → `a3e7c1f9b5d2`。
- **口径**：业务表 **101→103**（+ontology_terms/+ontology_term_aliases）/ 迁移头 **`a3e7c1f9b5d2`（28 revision，+1）** / 路由 **283 不变** / api_catalog ENTRIES **94 不变** / pytest **1790 收集 = 1784 passed + 6 skipped**（+8） / vitest 730 沿用（零桌面改动）。
- **部署**：`docker compose build && up -d` 后 **`alembic upgrade head`**（两张新表；**api/worker/scheduler 三个镜像都要 build**）。

## [未发布] — V3 实施 T-E3：bridge/任务证据统一入口（双通道落一等证据行，2026-11-03）

### 服务端（零迁移零路由零 DDL / task_service + bridge/sync 两处写入点挂接 / 零桌面改动）

- **任务侧**：`evidence_uri` + `evidence_hash` 齐备时，建任务/改任务同事务同步登记一等证据行（kind=`task`、captured_from=`human`、origin=`task:<task_key>`，大写 hash 归一小写）；同指纹幂等不增行，清空指针不动登记簿（证据不可变），只挂指针不落指纹不构成指纹不登记。写入点在乐观锁 rowcount 校验之后——stale 版本零证据副作用。
- **桥侧**：`apply_snapshot` 投影事务内把**已挂接 workbench 项目**的桥接采集登记为一等证据行（kind=`bridge`、captured_from=`bridge_sync:{run_id}` 机器通道、created_by 空）；openfde 按 engagement 指纹逐 slug、fdeops 按工作区级 registry_sha256；指纹不齐整（缺 hash / uri 越界）跳过不炸——投影是 4h 关键路径，证据不构成失败；同指纹幂等（内容不变不增行，内容变化=新指纹=不可变采集史新行）；`BridgeSyncRun.summary` 增 `evidence_created` 计数。
- **契约不动**：任务 DTO 与 engagement_view 均不暴露 evidence_id（沿 T-E2 gates_read 先例）；零新事件（任务侧 event_changes 已含证据字段变更；桥侧无 actor，summary+登记簿即审计）；登记路径仍不进 api_catalog（AI 不可写证据纪律不变）。
- **测试**：`test_project_tasks_api.py` +1（建/幂等/换指纹/清空/只指针 五段）+ `test_bridge_sync_flags.py` +1（挂接登记/未挂跳过/坏指纹跳过/重放幂等）。
- **口径**：业务表 **101 不变** / 迁移头 **`c1e5f9a3d7b2`（27 revision）不变** / 路由 **283 不变** / pytest **1782 收集 = 1776 passed + 6 skipped** / vitest 730 沿用（零桌面改动）。
- **部署**：`docker compose build && up -d`（**api/worker/scheduler 三镜像**；迁移头不变，无需 alembic）。

## [未发布] — V3 实施 T-S1：Skill 治理态（draft/in_review/published/deprecated + 发布四闸，2026-11-03）

### 服务端（1 个迁移（唯一 DDL）/ 5 条新路由 / extensions_service 治理化 / 零桌面改动）

- **治理状态机**：`draft →(submit-review)→ in_review →(publish)→ published →(deprecate)→ deprecated`；编辑已发布公共 Skill 开新版本行并回 draft 重走治理。迁移 **`c1e5f9a3d7b2`**：`skill_definitions.status` 从扩展共用值域（active/disabled）切到治理四态（CHECK 换值域），存量 **active→published**（发布人暂记创建人）、**disabled→deprecated**；skill_definitions 加 published_by/at、skill_versions 加 input/output schema + test_report_json + reviewed_by（全可空，版本行不可变不变）。
- **发布四闸**：admin（system_operator）/ 密码确认（`invalid_password` 403）/ 状态须 in_review / 测试报告或显式 waive（`test_report_required` 409）；发布把版本行 `reviewed_by` 落为发布人（发布即审核背书）。回滚 = published 内改指旧版本行（版本行不可变），同密码+材料闸。
- **个人 Skill 自发布豁免**：保存即 published（owner 自治）；四闸只对公共 Skill。内置种子走服务端内部参数 `initial_status="published"` 直发布（内容可信），`_is_unchanged_builtin` 升级判定同步收敛。
- **消费方收敛（T-W1/T-W3 挂账清偿）**：MCP 工具面（`mcp_gateway._skills`）、工作流 skill.ref 定义期白名单（`published_skill_refs`）、执行器 skill 节点分派三处全部只认 `published`。
- **API 五条（278→283）**：submit-review / publish / rollback / deprecate / versions；content_sha256 指纹扩展覆盖全部发布材料（schema/测试报告变更即新版本）。
- **兼容**：既有 PATCH 启停开关保留旧值域作别名——个人 Skill 自愈发布（幂等）；公共 Skill 发布向 409 `governance_required`（开关不得旁路四闸），停用向照旧。桌面治理 UI（审核/发布按钮）挂后续轮。
- **测试**：NEW `test_skill_lifecycle.py` **7 例** + 修 5 处 active 语义既有用例（chat_mcp/executor/solution_skills/lcsc_other/extension_management PATCH 流）；`test_migrations.HEAD_REVISION` → `c1e5f9a3d7b2`。
- **口径**：业务表 **101 不变** / 迁移头 **`c1e5f9a3d7b2`（27 revision，+1）** / 路由 **283（+5）** / pytest **1780 收集 = 1774 passed + 6 skipped**（全量实跑 1209s） / vitest 730 沿用（零桌面改动）。
- **部署**：`docker compose build && up -d` 后 **`alembic upgrade head`**（skill 两表列变更 + 存量状态迁移；**api/worker/scheduler 三个镜像都要 build**）。

## [未发布] — V3 实施 T-W5：Workflow cancel/resume HTTP 面（服务端编排面收口，2026-11-03）

### 服务端（2 条新路由 / 零新表零迁移 / 零服务层改动 / 零桌面改动）

- **运行生命周期路由两条（276→278）**：POST `/api/v1/projects/{id}/workflow-runs/{rid}/cancel`（can_manage，幂等——重复取消 200 `cancelled=false`；终态 409 `already_terminal`；waiting_approval 可取消，pending 审批行不动）与 POST `…/resume`（can_manage，failed-only——failed/skipped 节点放回 pending 重投 `workflow.run`；其余 409 `not_resumable`）。服务层 `cancel_run`/`resume_run`（T-W3）直挂 HTTP，零服务层改动。
- **reconcile 收敛**：标题项已随 T-W3 落地（RECOVERABLE 增 `workflow.run` + worker-loss 钩子），本任务无残留。
- **测试**：`test_workflow_executor.py` **26→27**（HTTP 面：viewer 403 / 幂等取消 / already_terminal / 跨项目 404 / failed-only 恢复+节点回 pending / not_resumable）。
- **口径**：业务表 **101 不变** / 迁移头 **`d5b8e2f4a7c9`（26 revision）不变** / 路由 **278（+2）** / pytest **1773 收集 = 1767 passed + 6 skipped** / vitest 730 沿用（零桌面改动）。
- **部署**：`docker compose build && up -d`（**api/worker/scheduler 三镜像**；迁移头不变，无需 alembic）。

## [未发布] — V3 实施 T-W4：Workflow 执行器 agent/human_approval 节点（审批复用 automation_approvals，2026-11-03）

### 服务端（1 个迁移（唯一 DDL）/ 零新路由 / 执行器+control 审批链扩展 / 零桌面改动）

- **human_approval 节点 = 复用 automation_approvals（设计 §3 落实）**：迁移 **`d5b8e2f4a7c9`**——`run_id` 放开可空 + 新增可空 `workflow_node_run_id` 反链（审批行=节点等待态的投影，FK CASCADE 随节点走，审计事实由 operation_events 承载）。分派即建审批：request_key=`wfnode:{节点行id}`、arguments_sha256 绑定输入快照、敏感键扫描（`contains_sensitive_argument` 提升为 control/access 公共函数，与 DSH 审批同闸）+ 64KB 上限、risk_level=4、15min 过期（`expires_minutes` 节点字段 1–1440 可调）；审批 id 挂节点幂等键 + pending 查重 ⇒ 崩溃恢复不重复建单。
- **拍板走既有任务中心入口（零新路由）**：`decide_automation_approval` 按 run_id 分支——workflow 审批经 `executor.settle_approval_node` **同事务**落节点终态（批准→succeeded 且 output 携 approval_id/拍板人/理由；拒绝/过期→failed）并**重投 workflow.run** 续跑；`dsh_approval_status` 惰性过期与 `execute_approved_dsh_tool` 同步加 workflow 守卫（审批无执行段）。
- **等待语义**：无 ready 且剩 waiting 节点 → run=`waiting_approval`（handler 正常返回；**有 failed 先断链收敛** FV-F1）；无人拍板则挂起（可取消），过期=拍板时惰性判定（主动清扫随 T-P1-5）；取消时 waiting 节点 cancelled、迟到拍板只落审批行不再驱动节点；resume 保持 failed-only。
- **agent 节点 = agents.start_run 同闸全链**（实时鉴权/月度预算/试点配额/T1/T6/沙箱/产物校验，绝不旁路）：幂等键 `wfnode-{节点行id}:{attempt}`——agents 对失败终态 run 拒绝同键重跑（V8），工作流以 **attempt 代际**表达「显式重试」（resume_run）；分派失败一律不叠加工作流自动重试（agents 自带重试族）；`params.solution_id` 透传使 agent_assisted/T1 方案闸随之生效。
- **定义期**：human_approval.capability 白名单 = 能力登记表去 `system.*`（validate_dag 注入参数，纯函数单测兼容）；四类之外未知类型的 start_run 422 守卫保留为防御（发布后白名单漂移场景）。
- **事件**：新增 `workflow_run_waiting_approval` / `workflow_run_approval_decided`。
- **测试**：`test_workflow_executor.py` **19→26**（审批批准/拒绝/过期/等待中取消+迟到拍板中和/幂等重入不重复建审批 + agent 全闸/能力拒绝不重试/run 失败不叠加重试）+ `test_workflow_definition.py` +1（capability 白名单）；`test_migrations.HEAD_REVISION` → `d5b8e2f4a7c9`。
- **口径**：业务表 **101 不变** / 迁移头 **`d5b8e2f4a7c9`（26 revision，+1）** / 路由 **276 不变**（零新路由）/ pytest **1772 收集 = 1766 passed + 6 skipped**（1764 + 8；实跑口径见 AGENTS.md）/ vitest 730 沿用（零桌面改动）。
- **部署**：`docker compose build && up -d` 后 **`alembic upgrade head`**（automation_approvals 两列变更；**api/worker/scheduler 三个镜像都要 build**）。

## [未发布] — V3 实施 T-W3：Workflow 执行器（call/skill 节点 + §5 路由 + jobs handler，2026-11-03）

### 服务端（零新表零迁移 / 5 条新路由 / 新执行器模块 / 零桌面改动）

- **执行器**（NEW `workflows/executor.py`，设计 workflow-dag-v1 §3）：`workflow.run` 作为 background_jobs 新 job_type（决策 3：复用既有 outbox/lease/续租/reconcile/failure-hook 全套，绝不复制第二套队列）。主循环 = ready 调度（依赖全 succeeded，或 when 真值裁决放行）→ 节点独立事务执行 → 无 ready 全终态收敛 run；**每节点状态迁移独立事务、分派（HTTP/AI）一律在事务外**（产物先落表再前进=崩溃恢复锚点，2026-10-30 事故教训）。
- **call 节点 = api_execute 同闸绝不旁路**：鉴权/确认/项目 scope 每节点实时校验（发起人当下 AI 档位，run 级不冻结）；写类节点命中确认闸 → 节点 failed 携 action_id（诚实呈现未执行，T-W4 接审批前置）。**外副作用幂等（修 fde-v2 FV-F3 执行侧）**：写类（api_catalog write=True）节点分派前强制落节点级 `idempotency_key`（与 api_actions 完全同构 sha256 `[user_id, "wfnode-{节点行id}", data]`）——重试/崩溃恢复同键，api_execute 按 action 去重不二次外呼。
- **skill 节点 = pinned 版本确定性 AI 调用**：`key@版本` 固定版本 `instructions_text` 作 system_prompt、节点输入 JSON 作 prompt、`use_tools=False`（不签发 MCP token，工具面留在 call 节点）；T-S1 前沿用 active 语义（与 T-W1 校验口径一致）。
- **诚实语义**：占位符缺键 → 节点 failed `placeholder_missing`（绝不填空串，fde-v2 缺陷回归用例钉住）；断链 → run **failed** + 下游 skipped（修 FV-F1 不静默 done）；`when` 仅支持整串单占位符真值（表达式引擎待真实需求）；agent/human_approval 节点在 start_run 即 422 `unsupported_node_type`（不留必死 run，T-W4 开放）。
- **§5 路由五条（271→276）**：POST projects/{id}/workflows（can_manage）、POST …/{wid}/publish（admin 锁版）、POST …/{wid}/runs（can_manage，幂等键同 run 返回 200/新建 201，跨项目同键 409）、GET …/workflow-runs/{rid}（can_view 节点按拓扑序）、GET /api/v1/workflows（admin 平台模板）；**cancel/resume 的 HTTP 面随 T-W5**（服务层 cancel_run/resume_run 已可用）。
- **run 生命周期服务**：start_run（published 闸+幂等键先于定义查找） / cancel_run（停未执行节点、已执行外呼不回收、幂等） / resume_run（failed→重置 failed/skipped 节点复用产物）；事件目标新增 `workflow_run`（created/succeeded/failed/cancelled/resumed）。
- **jobs 接线**：`workflow.run` handler + worker-loss 收尾钩子（reconcile 放弃时 run 与悬挂节点推终态）+ RECOVERABLE_JOB_TYPES 增补（节点产物先落表=succeeded 即恢复锚点，重跑只处理未完成节点）；handler 入口恢复 queued→running 与死亡遗留 running 节点。
- **测试**：`test_workflow_executor.py` 新 **19 例**（§6 用例 4/5/6/7/8/11：链路与占位符原类型替换 / 版本钉住跨发布 / skill 钉版本指令 / 重试后成功与耗尽恢复复用产物 / 幂等键同构公式+跨重试恢复稳定 / 取消保留已成功节点 / 断链 failed+skipped / when 假值跳过 / 缺占位符不填空串 / 平台模板路由与项目内实例化 / outbox→worker 全链 / reconcile 钩子）。
- **口径**：业务表 **101 不变** / 迁移头 **`b7d9f1a3c5e2`（25 revision）不变**（零 DDL）/ 路由 **276**（+5）/ pytest **1764 收集 = 1758 passed + 6 skipped**（1745 + 19；实跑口径见 AGENTS.md）/ vitest 730 沿用（零桌面改动）。
- **部署**：`docker compose build && up -d`（server 代码烤进镜像；无迁移，alembic head 不动）。

## [未发布] — V3 实施 T-W2：Workflow 运行层（runs / node_runs 两表，2026-11-03）

### 服务端（2 张新表 / 1 个迁移 / **零新路由、零执行器、零服务逻辑改动** / 零桌面改动）

- **运行 + 节点运行双表**（迁移 **`b7d9f1a3c5e2`**，含 downgrade）：`workflow_runs`（固定 (definition_id, definition_version)——跑动中被改即受影响的 fde-v2 教训；run 级 `idempotency_key` **全局唯一**，修 fde-v2 FV-F3 无幂等重跑重复建单；status 七态 CHECK queued/running/waiting_approval/paused/succeeded/failed/cancelled；context_json=运行级入参占位符源；definition FK **RESTRICT**——执行史在则定义不可静默删，project FK CASCADE 项目隔离）+ `workflow_node_runs`（**UNIQUE(run_id, node_key)**；node_type 四类 CHECK（无 condition/wait，设计钉死）；status 八态 CHECK pending/ready/running/waiting/succeeded/failed/skipped/cancelled；attempt 计数；`depends_on` 定义侧冗余快照可追溯；节点级 `idempotency_key` 可空——外副作用节点必填由 T-W3 执行器强制；input_snapshot 执行前落审计可回放 / output_json 下游占位符解析源；run FK CASCADE）。
- **纯增量零改既有表**：T-W1 定义两表原样；执行器（ready 调度循环、重试、恢复）随 T-W3，路由随 T-W3 一起开。
- **配套**：`conftest` 清理序（node_runs → runs → definition_versions → definitions）、`test_migrations.HEAD_REVISION` → `b7d9f1a3c5e2`；`migrations/env.py` 按模块导入无需改、审计抽取脚本按模块自动发现无需改。
- **测试**：`test_workflow_runs.py`（新 11 例：默认态与版本钉住 / run 幂等键全局唯一（FV-F3 表级保证）/ 节点键 run 内唯一 run 间允许 / run 列守卫参数化 4 例 / 节点类型与状态守卫 / run 删除级联节点 / 定义删除 RESTRICT / 项目删除 CASCADE 带走 runs+nodes 且平台模板不阻拦）+ `test_migrations.py` +1（运行两表迁移往返保留 projects、定义两表共存）。
- **口径**：业务表 **101**（+2）/ 迁移头 **`b7d9f1a3c5e2`（25 revision）** / 路由 **271 不变** / api_catalog ENTRIES 94 不变 / pytest **1745 收集 = 1739 passed + 6 skipped**（1733 + 12；本机全量实跑 1851s）/ vitest 730 沿用（零桌面改动）。
- **部署**：`docker compose build && up -d` 后 **`alembic upgrade head`**（新表）。

## [未发布] — V3 实施 T-W1：Workflow 定义层（两表 + dag_json 校验纯函数，2026-11-02）

### 服务端（2 张新表 / 1 个迁移 / **零新路由、零执行器** / 零桌面改动）

- **定义 + 不可变版本双表**（迁移 **`f2a4c6e8b1d3`**，含 downgrade）：`workflow_definitions`（draft/published/archived；发布递增 version；NULL project_id=平台模板）+ `workflow_definition_versions`（发布快照，(definition_id, version) 唯一，**写后不可变**——运行固定引用版本号，fde-v2 教训）。
- **`validate_dag` 纯函数先入 CI**（零执行器依赖，backlog T-W1 验收）：环检测=Kahn 拓扑并**点名环节点**（修 fde-v2 FV-F1）；未知依赖/自依赖/重复 key/未知类型/未知字段；**call.ref 必须 ∈ api_catalog ENTRIES**（白名单封 SSRF 面）；skill.ref 须为 active skill 的显式 `key@版本号`；agent.ref 须已启用；output 唯一且不遮上下文键；`{{placeholder}}` 须为运行上下文键或**传递上游**节点的 output；外部副作用无审批后继 → **P1 告警不阻断**（effect 结构化在 T-R2，P2 转强制）。违规一律 422 `dag_invalid` 携逐条 issues（code/message/node_key/detail）。
- **定义生命周期服务**（无 HTTP 路由——§5 路由随 T-W3 执行器一起开）：create（draft v1）→ update（已发布则自动 +1 开新草稿版本，版本行原样）→ publish（按**当前**白名单再校验后快照版本行；already_published 409）。事件 `workflow_definition_created/updated/published`（事件目标注册表新增 `workflow_definition`，平台模板 project_id 为 NULL）。
- **配套**：`migrations/env.py` 模型导入、`conftest` 清理序（版本行先于定义行）、`test_migrations.HEAD_REVISION`、审计抽取脚本模型清单。
- **测试**：`test_workflow_definition.py`（新 7 例：合法示例含拓扑序 / 环点名 / 结构与引用 / 三类 ref 白名单 / 占位符上下游 / 规则 9 告警 / 发布锁版本行+事件序）+ `test_migrations.py` +1（两表迁移往返保留 projects）。
- **口径**：业务表 **99**（+2）/ 迁移头 **`f2a4c6e8b1d3`（24 revision）** / 路由 **271 不变**（零新路由）/ pytest **1733 收集 = 1727 passed + 6 skipped**（+8；本机全量实跑期间机器休眠致 2 例连接中断失败，单跑复核绿，CI server-tests 干净复核）/ vitest 730 沿用。
- **部署**：`docker compose build && up -d` 后 **`alembic upgrade head`**（新表）。

## [未发布] — V3 实施 T-E1 + T-E2：一等证据表 project_evidence + 门禁证据挂接（2026-11-02）

### 服务端（1 张新表 / 1 个迁移 / 2 条路由 / 零桌面改动）

- **T-E1 一等证据表**：新模块 `fde_api/evidence/`（models / service / routes）+ 迁移 **`e1f3a5c7b9d2`**（`project_evidence`：UNIQUE(project_id, source_uri, content_sha256) 指纹即幂等键，kind 七类 CHECK，sha256 长度 CHECK，INDEX(project_id, kind)；project FK CASCADE、创建人 FK SET NULL；含 downgrade）。只存指针 + 指纹，不存原件（红线）。
- **API**：`POST /api/v1/projects/{id}/evidence`（can_manage；首次 201 `created=true`，同指纹 200 `created=false`——证据不可变，命中不改写 origin/captured_from）、`GET …/evidence?kind=&referenced_by=gate:Gx`（can_view；referenced_by 反查门禁清单项挂接）。错误码 `invalid_sha256` / `invalid_request` / `forbidden` / `project_not_found`。**有意不进 api_catalog**（AI 不可写证据，用例钉住）。
- **T-E2 门禁挂接**：`submit_gate_evidence` 每项先 `upsert_evidence`（kind=gate、origin=`gate:Gx/<清单项>`、captured_from=human），清单项 JSON 内挂 `evidence_id`，事件 `gate_evidence_submitted.items[]` 携 evidence_id；`_serialize_gate` 读时合并（历史清单项 `evidence_id=null`），**零 DDL**。同指纹二次提交幂等（行数不增、id 不变）。
- **并发安全**：`upsert_evidence` 在保存点内插入，撞唯一指纹回退后读回赢家，不向调用方抛 IntegrityError。
- **配套**：`migrations/env.py`、`conftest` 清理序、`test_migrations.HEAD_REVISION`、审计抽取脚本的 blueprint/模型清单均已登记新模块；`gate_service` 对 `evidence.service` 延迟导入（避免 projects⇄evidence 环）。
- **测试**：`test_evidence_registry.py`（新，6 例：指纹幂等与不可变 / 校验 / 权限与跨项目隔离 / kind 与 referenced_by 过滤 / 服务层入口 / 不进 catalog）+ `test_gates_api.py` +1（T-E2 挂接全链）+ `test_migrations.py` +1（迁移往返保留 projects）。
- **口径**：业务表 **97**（+project_evidence）/ 迁移头 **`e1f3a5c7b9d2`（23 revision）** / 蓝图路由 **271**（+2）/ blueprint 34 / api_catalog ENTRIES **94 不变** / pytest **1725 收集 = 1719 passed + 6 skipped**（+8，921.98s 全量实跑） / vitest 730 沿用。
- **部署**：`docker compose build && up -d` 后**须 `alembic upgrade head`**（新表）。

## [未发布] — V3 实施 T-P0-1：signoff 死锁修复（审计 WB-DEF-1，2026-11-02）

### 服务端修复（零迁移、零新路由、零桌面改动）

- **症状**（审计 WB-DEF-1，P0 功能阻断）：signoff checkpoint 唯一开闸点是 `handoff_run`，而它只收失败 / L1 降级 run；agent_assisted 方案经 generate-agent **正常 completed** 后既不能 handoff 又拿不到 pending → `POST …/signoff` 409 `signoff_not_pending` 与 `POST …/export-sow` 409 `solution_signoff_required` 永久互锁，SOW 一个字节都导不出。包声明 agent_assisted 而方案无 run 的形态同样死锁。
- **修复**：新增 `fde_api/agents/signoff.py::ensure_pending_signoff` 作为唯一幂等开闸入口（同方案至多一个 pending，只补空 run 软链不覆写）；`_finalize` 对非降级 completed 且绑定 solution 的 run 即时开出 pending（L1 维持「人工接管后再开闸」既有语义）；`handoff_run` 改走同一入口；`export_sow` 的 agent_assisted 闸拆成独立事务，拦下且无 pending 时**兜底开闸并先提交再抛 409**（闸本身不放宽），409 `details` 携 `signoff_checkpoint_id / signoff_status / remedy=resolve_pending_signoff / remedy_path`。
- **错误体**：`DocumentDraftServiceError`（= `SolutionServiceError`）新增可选 `detail`，solutions 蓝图错误处理器透传为 `error.details`（与 `AgentsServiceError` 同形；三参调用零改动）。
- **测试**：`test_solution_signoff.py` +5（端到端先红后绿：generate-agent completed → export 409 携指路 → 终审拍板 approved → export 200；无 run 兜底开闸且重复导出不重复开闸；驳回后再导出重开新一轮 pending；L1 降级 completed 不自动开闸仍走 handoff；开闸入口幂等/软链回填）。对旧代码实跑红：completed 后 checkpoint 数 0、409 无 details。
- **口径**：pytest 1717 收集 = 1711 passed + 6 skipped（d14 1712 + 本轮 5）；路由 269 / 表 96 / 迁移 22 不变；桌面零改动（vitest 730 沿用）。审计文档回写：`docs/implementation/v3-backlog.md` T-P0-1 → DONE（含实现偏差），风险登记册 / 差距矩阵 WB-DEF-1 → 已修复。

## [未发布] — V3 融合审计：Workbench × fde-v2 深度代码审计与 V3 升级实施方案（2026-11-02）

### 纯文档 + 审计脚本轮（零业务代码、零迁移、零部署）

- **主报告** `docs/architecture/蔡工FDE_Workbench_fde-v2架构融合审计与V3升级实施方案.md`（20 节 + Mermaid 五层架构图）：对 Workbench @0570384 与外部项目 fde-v2（快照≈上游 master@39e0e62，零执行只读审计）逐模块对照；核心裁决=**不引入 fde-v2 实现，只吸收四件经验证思想**（YAML DAG 形态 / 候选→人工确认闭环 / 证据"出处+源块"粒度 / BR 三要素机器可读纪律），七项 fde-v2 设计明确不搬（flow 执行器、运行时 DDL reconcile、隐式页面授权、exec 角色装配、user=None 全通、全量内省工具面、agentscope 团队）。
- **审计产物** `docs/audit/`：双仓基线、模块清单、路由清单 CSV（385 行=WB 269 url_map 枚举 + fde-v2 116 AST）、数据表清单 CSV（121 行=WB 96 表全字段+首建迁移归属 + fde-v2 17 DDL）、测试盘点与实跑终录、**17 能力域差距矩阵**（REUSE/EXTEND/NEW/DEFER 逐域裁决，含 Workbench 自身 14 项现状缺陷——WB-DEF-1 signoff 死锁为 P0 功能阻断）、风险登记册；`appendix/` 六份行号级原始证据报告。
- **架构设计** `docs/architecture/`：ontology-registry-v1（3 新表 terms+aliases / relation_types / change_sets + project_evidence 底座；6 个候选表经查重不建）、workflow-dag-v1（作为 background_jobs 新 job_type，不建第二套队列；四类节点；校验器纯函数先入 CI）、agent-policy-v1（权限五原则现状 VERIFIED 保持 + ToolGroup 只收窄 + Skill 以既有双表扩治理态）。
- **实施台账** `docs/implementation/`：v3-backlog（24 任务含文件/表/API/测试/回滚/复杂度）、v3-test-plan（本体/Workflow/权限安全/门禁交付物四族验收用例）。建议起手：T-P0-1 死锁修复 → T-E1/E2 一等证据表 → T-W1 DAG 校验器。
- **可复现抽取脚本** `scripts/audit/extract_{workbench,fde_v2}_inventory.py`（裸 Flask 注册全部 blueprint 枚举 url_map + Base.metadata，不调 create_app 零副作用；外部快照 `python -I` + AST/regex 零 import）。
- 实跑基线（本轮真实执行）：pytest 1700 passed + 6 skipped（1706 收集，与 d13 口径一致）/ vitest 730/730 / operations 14/14；fde-v2 verify 套件按不受信零执行纪律未跑（UNKNOWN 如实记录）。口径数字不变：96 表 / head `c3e7a9b1d5f4` / 路由 269 / ENTRIES 94。

## [未发布] — 派单 r12 签字执行：14 条留注归档 + B-③ 销号 + B-① 律师包定稿（2026-11-01）

### 纯文档销号轮（零代码）

- **留注 14 条签字归档**（设计文档 owner 交互签字）：12 条即归档（①②④⑧⑩⑪⑫⑰⑱⑲⑳㉑）+ 附条件 2 条勾选维持（③ 复购约束放宽 / ⑥ onsite 关键词派生）；需变更 5 条去向：⑤已执行（#55）、㉒已销号、⑨⑬随 B-① 等律师、⑦⑭⑮ 登记二期待办（⑭ 前置=行业→大类映射口径待业务给出）。
- **B-③ 拍板销号**：平台公司统一开票 + 预扣率表=税务总局 2025-16 公告口径确认（`WITHHOLDING_BRACKETS` 已是该口径，零改动）；衍生小项挂下次工程轮：`mark_payable` 扩开票方/税率字段必填。
- **B-① AI 法律研究底稿定稿 + 律师包待寄**：底稿（文档中心 06_派单引擎，官方条文抓取核实，**非法律意见**）倾向撮合引擎不落入算法备案义务/LLM 内部使用免大模型备案；用户拍板寄律师包、B-① 维持「需备案」零改动。台账 30.11。

## [未发布] — 派单 r12 拍板执行：B-④ 城市终版 + 留注⑤ 冷启动口径切换（2026-11-01）

### 首批城市名单定稿（全行业口径）

- **B-④ 拍板终版**：首发六城 = 上海/广州/深圳/杭州/成都/武汉（全行业服务口径 + 优先南方和一线城市；原苏锡常制造业走廊建议名单退役）。`seeds/dispatch_cities.json` 换终版（meta 记拍板来源）；**名单定稿≠开闸**——claim_enabled 仍全 false，开闸由 §6.4 三条件 + 城市开关驱动（B-① 备案完成+公示前 claim 维持降级态）。
- **留注⑤ 冷启动口径切换**：`settlements.py:_city_order_rank` 由交付席位 home_city 代理改为**包侧客户城**（企业代号第三段）；`cities.py` 新增公共助手 `package_client_city`/`city_from_enterprise_code`，cities/maintenance/settlements 三处城口径去重为一（maintenance `_client_city_of` 改委托）。
- **拍板销号（零改动）**：B-① 维持「需备案」（律师意见书仍是权威输入）；B-② 维持对公口径；直签豁免维持绝对封堵；P2-2 维持 5 态（留注㉒ 同步归档）；仿真器校准暂无数据继续等待。台账三十节 30.10 执行记录。
- 回归：种子断言/geo 钉子/冷启动夹具对齐新名单（档案城深圳≠包侧城杭州的反向回归钉）；桌面零改动。台账三十节 + 等待清单刷新（30.10）。

## [未发布] — 派单线收尾轮 r12：外部输入到达执行手册（2026-11-01）

### 零功能补码的落点普查轮

- **外部输入到达执行手册**（台账三十节）：八项外部输入（B-①备案/B-②托管/B-③开票与预扣率/B-④城市名单/P2-2 状态集/仿真器校准/留注签字/直签豁免）的"到达即执行"代码与数据落点逐项普查确认——落点全部存在，零补码；每项含分支动作、影响面与回归口径，任一输入到达按节执行即可。
- **C7 核实**：混合模式自动转换 job 已在 goal-r10 落地，8 例于本轮头复跑全绿——零重做。
- **留注编号勘误**：⑯为空号（r5→r6 跳号），实有定义 21 条；签字分类=12 归档 / 2 附条件 / 7 需变更。
- 联合口径不变：94 业务表 / head `f6a9c3e1d7b4` / 路由 252 / ENTRIES 86 / pytest 1563 收集 / vitest 695。

## [未发布] — 派单运维页簇 B3/B5/B6（2026-11-01）

### 争议处理 / 仿真对比 / 开闸运维（零迁移）

- **服务端五路由**（薄包装既有服务层，全部平台侧）：`GET /dispatch/disputes`（L0–L3 全量留痕；对账单只透出 `l0_report_source_uri` 指针——红线字段不内联本体）、`POST /dispatch/disputes`（人工打开仅 L1/L2——L0 由对账自动产；L1 金额 >¥50,000 → 422 `amount_above_l1`；快照锚=打开时包快照 §2.3 规则 2）、`POST /dispatch/disputes/{id}/resolve`（结论必填；close 直关；处罚类动作 100% 人工）、`POST /dispatch/simulator/replay`（历史包只读回放——当前池×当前规则版本再撮合画像，不落 offer；全链路种子化仿真留 CLI 沙箱库，绝不经 HTTP 触发写库）、`GET /dispatch/claim-gates`（§6.4 三条件+种子开关逐城可解释明细；开关在 seeds 文件，只读不翻转）。ENTRIES 74→**79** / 路由 234→**239**。
- **桌面三个平台侧 tab**（九子页簇收官）：「争议处理」（L0–L3 层级/状态标签 + 打开表单 + 裁决表单含直接关闭）、「仿真对比」（执行回放 → 摘要卡片（场景分布/Stage A 通过率/Top1 均分）+ 逐包 Top3 画像；口径=仿真不作真实成绩常驻声明）、「开闸运维」（逐城判定徽章 + 三条件 ✓/✗ + 拒单率；"改走代码流程——本页只读"）。
- 测试：服务端 `test_dispatch_b3ops_pages.py` 8 例（L0 禁人工打开/L1 上限 422/快照锚/裁决 409/回放降级 skipped+只读断言/开闸种子对齐）；桌面 `dispatch-ops.test.tsx` 9 例（路由解析/角色门/裁决流/打开校验/回放摘要/开闸判定）。台账二十八节。

## [未发布] — 派单调度台操作面 B2（2026-11-01）

### 平台侧调度台（零迁移）

- **服务端包留痕路由**：`GET /dispatch/packages/{package_id}/offers`（平台侧 only）——一包全量 offer 留痕（谁被派/接了/拒了、§6.2 窗口 deadline 服务端现算、§4.8 rank/explanation 释明、候选人身份），调度台据此决定代接单/重派。ENTRIES 73→74 / 路由 233→234。
- **桌面「调度台」tab**（第 6 子页，admin/project_lead 可见，动作权限服务端复核）：供给池候选勾选器（复用 `GET /profiles`，勾选即发布授权/指派名单）；包全景列表（draft 也在列）按状态出按钮——draft：等级覆盖（§4.5 必填 reason 留痕）+ 发布（携候选只读授权）；withdrawn/rejected/expired：重新发布（服务端 round+1 新版本对）；published：执行撮合（§4 两段式，结果面板展示场景 A/B/C + Top3 释明 + 资格门淘汰数）/ 指派 offer / 撤回（TRANSITIONS 仅 published 可撤）；offer 留痕面板 + offered 行「代接单」（`POST /accept` 携 delivery_user_id）。时间窗只展示不重算（B1 纪律延续）。
- 测试：服务端 `test_dispatch_b2_console.py` 6 例（全量留痕/claim 15 分钟窗/空留痕/非平台侧 403/未知包 404/轮次倒序）；桌面 `dispatch-console.test.tsx` 10 例（路由解析/状态动作映射/角色门 tab 隐藏/发布携候选/撮合可解释结果/指派/撤回/等级覆盖 reason 闸/留痕+代接单）。台账第二十六节增补 B2 项。

## [未发布] — 派单接单工作台 B1（2026-10-31）

### 交付工程师专区（循环终止后首期派单范围增强，零迁移）

- **服务端三读路由**：`GET /dispatch/offers/mine`（收件箱=候选人本人全量留痕 + §6.2 窗口 deadline 现算 + §4.8 算法释明只回本人）、`GET /dispatch/settlements/mine`（只回本人席位角色与金额，他席存在与金额零出现；预扣税原样透出不算净额——B-③ 未定不发明）、`GET /dispatch/profiles/me`（自助档案 + 在途计数，无档案 404）。ENTRIES 70→73 / 路由 230→233。
- **白名单 payload 增 `id` 支撑列**（资源标识非内容字段；授权方抢单/接包必须持有目标 id）——§9.5 隔离基线②键集测试同步更新并全基线复跑绿。
- **桌面「我的接单」tab**：收件箱 + 待响应倒计时（30s 刷新，窗口判定永不在前端复算）+ 接单/拒单按钮（原因枚举四选一只进留痕）+ 算法释明折叠 + 我的档案卡；**「我的结算」tab**（我的分成/计提基数/预扣税/打款状态）；**派单池抢单按钮**（claim 模式 published/offered 包详情展开内；开闸判定在服务端，claim_closed 可解释信息直显=§11 降级态 UX）。
- 测试：服务端 `test_dispatch_b1_console.py` 7 例 + r3 隔离/r4 回归；桌面 `dispatch-mine.test.tsx` 9 例。企业需求方专区不做（设计 §1.4-3 明确排除：客户不接触派单池）；评估与任务清单见台账第二十五节。

## [未发布] — goal-r11 派单引擎终止复核轮（2026-10-31）

### 循环终止——最终收口报告 v2（零功能改动）

- **§八 八项终止判定全部成立**：更新版收口报告 `docs/goal-r11-派单引擎收口.md` 取代 r8 版本成为唯一凭证（r8 的两项例外已由 r9/r10 消解）。全电池重测：服务端 1456+6s / 桌面 660 / typecheck 0 / 闸④覆盖率 **85%**（3,009 语句含 channel_guard 89% + simulator 81%）/ 负面清单 7 反例 / H5 口径 85 表·15 rev·head `c5d7e9f1a3b7`·路由 228·ENTRIES 68。
- H2/H3 以内测/仿真口径达标（基准原文「内测/仿真先行」）：H2 0.9565 / 工时占比 0.0716 / 毛利率 0.9717（r9 仿真工件，假设表全量回显，真实数据到位后复测校准）。
- 剩余事项全部外部输入依赖（备案/托管/税率/城市名单/P2-2/直签豁免/仿真器校准/留注签字/便携版重打包），逐项登记于台账第二十三节与收口报告第五节。

## [未发布] — goal-r10 派单引擎轮（2026-10-31）

### C7 混合模式自动转换 job（零迁移）

- **混合模式落地**（派单设计 §6.1「先 assign 指派，响应窗内无人接 → 转 claim」）：`dispatch/maintenance.py` 新增 `convert_stale_assign_to_claim` 挂 `run_maintenance` 节拍——assign 死亡（expired/rejected）包 × 城市 claim 开闸（§6.4）→ mode 翻转 + 按 §2.3 重发（round+1 新码新哈希 + §4.7 扩圈推进）+ `dispatch_c7_converted` 事件留痕；幂等（翻转后不再命中）；单包 SAVEPOINT 隔离不炸整批；城市未开闸安全空转（§11 降级态，人工重派路径不变）；零新增时间常数（24h 判死由上游 expire 按 §6.2 执行）。
- 测试：`test_dispatch_p2_r10_c7.py` 8 例（含转换后 claim_package 实抢闭环、幂等、降级空转、单包故障隔离、§6.4 拒单率条件真实生效验证）；r1–r9 回归全绿。口径：85 业务表 / 15 rev / head `c5d7e9f1a3b7`（零迁移）/ 路由 228 / ENTRIES 68 / 服务端 **1456 通过** / 桌面 660。轮次报告 `docs/goal-r10-派单引擎.md`；台账第二十二节。

## [未发布] — goal-r9 派单引擎轮（2026-10-31）

### P2-4 私单封堵 + 撮合仿真器（零迁移）

- **P2-4 私下接单封堵**（派单设计 §8.5）：新增 `dispatch/channel_guard.py` 三服务层钩子——H1 立项入口（`business_line` 随立项显式声明，派单线仅平台侧可立、专属 403 码）、H2 池内企业直签封堵（企业进过派单池后直签立项/报价 → 422 `private_deal_blocked`，复购走派单线放行）、H3 渠道正交（交付包只建在派单线项目上 → 422 `dispatch_line_required`）；封堵留痕走独立事务（主事务回滚后仍存活）。
- **撮合仿真器**（留注⑳）：新增 `dispatch/simulator.py`——历史包只读回放打分（P2-1 仿真对比数据源）+ 种子化全链路仿真（撮合/席位/时间常数走真实引擎，人工环节显式假设表采样）+ CLI `python -m fde_api.dispatch.simulator`（非沙箱库拒绝执行）。报告工件 `docs/dispatch-sim-r9-seed42.json`（H2/H3 内测/仿真口径，假设全量回显）。
- 测试：`test_dispatch_p2_r9_p24.py` 10 例 + `test_dispatch_p1_r9_sim.py` 4 例；r1–r8 回归全绿。口径：**85 业务表**（口径修订：不含 alembic_version）/ 15 rev / head `c5d7e9f1a3b7`（零迁移）/ 路由 228 / ENTRIES 68 / 服务端 1448 通过 / 桌面 660。轮次报告 `docs/goal-r9-派单引擎.md`；台账第二十一节。

## [未发布] — goal-r8 派单收口轮（2026-10-31）

### 派单引擎收口——开池四道闸全绿 + §八终止判定对照（零迁移）

- **C10 新人保护期**（§6.5）：撮合 Stage A 新增「前 5 单只推同城」——完成单数低于 `newcomer_protection_orders` 的候选强制非同城出局（推送范围收紧非资格淘汰），A5 明细带 `newcomer_city_only` 释明标记。
- **B1 防骚扰**（规则表 B1）：同包更早轮次拒过的候选本轮不再**主动推送**，与负面清单 #6「不因拒单限制接单机会」正交并存（本人仍可经 claim 主动抢）；stage_a 契约新增 `B1` 行；同步修正 r5 初版混淆两语义的测试。
- **§4.7 扩圈半径自动推进**：重派发布时 `redispatch_radius_km` 按 25→50→100→0 自动降档。
- **闸④覆盖率出具**：商业模块关键路径（报价/收款/合同/门禁/派单撮合结算）**84.9% ≥ 60%**（分母 2,637 语句），宽口径 71%——开池四道闸**全绿**。
- **收口报告**：`docs/goal-r8-派单引擎收口.md`——§八终止判定逐条对照（1/3/4/5/6/7/8 达成；2、3 带明示例外：P2-4 未立项、H2/H3 待真实数据）+ 附录 B 待签字清单（B-①②③④ + 留注①–㉒ + P2-2）+ 附录 A 修订建议（表 86/15 rev/路由 228/ENTRIES 68 重锚 + 新增冲突 A-⑧–⑪）。
- 测试：`test_dispatch_closeout_r8.py` 3 例；r1–r7 回归 94 例全绿。口径：86 表 / 15 rev / head `c5d7e9f1a3b7`（零迁移）。

## [未发布] — goal-r7 派单引擎轮（2026-10-31）

### 派单引擎 P2 批次（对照派单设计文档 v1.0 §8.5：P2-1/P2-3/P2-6；迁移 `c5d7e9f1a3b7`）

- **P2-1 桌面派单页簇**：`desktop/src/renderer/src/dispatch/` 三页——派单池（§9.2 白名单只读视图 + 详情展开 + 席位金额显示义务，响应体不含报价/收款明细字段断言）、能力档案与产能看板（四域分=晋级评定维度展示、在途/上限负载条）、权重与规则版本（只读 + 版本取值对照，仿真对比二期=留注⑳）；nav 全角色入口（交付方看被授权包，平台侧看全量），hash 路由 `#dispatch[/(pool|profiles|rules)]`；服务端支撑路由 GET `/dispatch/profiles`、`/dispatch/rules`（平台侧，ENTRIES +2）。
- **P2-3**：`projects.business_line` CHECK 放行 `'FDE_DISPATCH'`（§11.1 预留路径；写入入口随派单立项后续轮启用；存量数据零变化）。
- **P2-6**：`dispatch_cities.json` 扩字段钉子（subsidy_scheme 选填 + metro_group 必备断言——schema r4 已含，本轮补 P2-6 语义钉）。
- **P2-2（Project.status 枚举扩展）**：设计/规则表/BP 均未给出目标状态集——**不发明，待拍板**（台账第十九节留注）。
- 测试：服务端 `test_dispatch_p2_r7.py` 4 例 + 桌面 `dispatch-page.test.tsx` 6 例；r1–r6 回归 87 例全绿。
- 口径（goal-r7 实测）：86 表、迁移头 `c5d7e9f1a3b7`（15 revision）、路由 228（+2）、ENTRIES 68（+2）、桌面 660。轮次报告 `docs/goal-r7-派单引擎.md`；台账第十九节。

## [未发布] — goal-r6 派单引擎轮（2026-10-31）

### 派单引擎 P1 收官——§8.4 七项全过 + §8.1 八表齐（迁移 `b2c4d6e8f1a3`）

- **P1-6 报价归属**：`quotes.owner_user_id`（nullable FK users SET NULL + 索引；存量不回填=平台侧台账报价语义），创建即落 owner，归属过滤用例。
- **P1-7 留存策略**：`dispatch/maintenance.py` 留存扫描（撮合流水/评分 3 年、涉税 10 年——**报告只读不删档**，删除须人工合规审批，留注⑰）+ 维护作业 `dispatch.maintenance`（24h 节流）挂 `cli.scheduler` 主循环经 outbox 投递、handler 注册沿 research.export 模式；超时释放（r4 的 expire_stale_offers）一并挂入。
- **disputes 表**（§8.1 第 8 张，§6.6/§7.5）：L0 机器对账（逐包逐键比对结算应计 vs Payment 实收，差异>±¥1 自动草稿、幂等）+ L1 人工打开（48h 人工答复 SLA 字段、¥50,000 上限 422 走 L2）+ 人工裁决（**处罚类动作 100% 人工**，resolution 只能由平台侧写入）+ L0 对账单/依据只存 source_uri 指针 + snapshot_hash 锚定当时版本。
- 测试：`server/tests/test_dispatch_p1_r6.py` 8 例；r1–r5 全量回归 87 例全绿；ruff/mypy 无新错。
- 口径（goal-r6 实测）：86 表、迁移头 `b2c4d6e8f1a3`（14 revision）、路由 226、ENTRIES 66。轮次报告 `docs/goal-r6-派单引擎.md`；台账第十八节。

## [未发布] — goal-r5 派单引擎轮（2026-10-31）

### 派单引擎 P1-2 撮合核心（对照派单设计文档 v1.0 §4/§5 + 规则表 A-6，零迁移）

- **撮合核心**（§4.1–§4.8）：`dispatch/matching.py` + `dispatch/scoring.py`——Stage A 五资格门（等级/模块/行业/负载自动算上限/到场围栏）硬过滤出局不降权；场景裁决三选一：到场型字典序 (geo_tier, -level, -industry, -sla)、远程型加权（权重取 active 规则版本快照，无版本 → 422 `rule_version_required`=§11.1 降级态人工排序）、到场无候选场景 C 不自动派（事件留痕含淘汰明细）；§4.5 `required_level` 由 Quote 系数推导落库 + 发布前人工覆盖必填 reason 留痕；§4.7 扩圈链 geo_tier（同城/同省/邻接都市圈/全国，全国仅旗舰档）；§4.8 Top3 + `match_breakdown` 释明契约（stage_a 五门明细/stage_b/rank/explanation，对被派方展示）。
- **负面清单 A-6 七条逐条反例**（§8.8 开池四道闸之闸③全绿）：软画像零字段 schema 断言 / 排序签名无历史参数+同分不同历史同分 / 全包无轨迹语义静态检查 / 到场型字典序（同城弱者胜同省强者）+ 加权地理仅三档 / settlements 零工时扣减静态检查 / 被拒者下一轮仍可入选 / 全包零货运语义。
- **P1-4 options 枚举**：席位分配 / 场景类型 / 匹配模式 / 拒单原因四组随 /workbench/options 下发。
- 路由 +2（POST packages/{id}/match、packages/{id}/required-level），ENTRIES +2。
- 测试：`server/tests/test_dispatch_p1_r5.py` 12 例；全量 CI 门禁出具；桌面零改动。
- 口径（goal-r5 实测，rebase 到 goal-d1 合并态后）：84 表、13 revision / head `a7f3c1e9d5b2`（本轮零迁移）、路由 226（+2）、ENTRIES 66（+2）。轮次报告 `docs/goal-r5-派单引擎.md`；台账第十七节。

## [未发布] — goal-r4 派单引擎轮（2026-10-31）

### 派单引擎 P1 首批（对照派单设计文档 v1.0 §8.4：P1-1/P1-3/P1-5，零迁移）

- **P1-1 offer_service**（§6.2/§6.3/§6.7）：`dispatch/offer_service.py`——§6.3 乐观锁显式版本比对先行（冲突 409 `stale_version`，禁分布式锁）；同轮互斥（409 `offer_already_accepted`，包行 FOR UPDATE 串行化）+ 落选者自动 expired；claim 15 分钟确认窗 / assign 包响应窗超时批量释放（`expire_stale_offers`）；§6.7 拒单权（原因枚举 档期冲突/能力不匹配/距离/其他 只进 OperationEvent 留痕不进任何分值，**永不因配额拒绝拒单**——负面清单 A-6 #6 防护）；全拒后包 rejected=重派入口；§9.3 交接复用 `handover_accepted_member`（leader 为 actor）。路由 +4（指派发 offer / 接单 / 拒单 / 抢单登记），api_catalog ENTRIES 同步 +4。
- **P1-3 一致性测试**：api_catalog 每条 ENTRIES 逐条在 url_map 可解析（防目录漂移）+ dispatch 每条路由逐条在册（防脱册）——双向钉死。
- **P1-5 seeds 三处**：`gates.json` 加 `applicable_industries`（null=全行业通用；历史迁移回填哈希常量冻结不动，实时哈希由 `_gates_file_hash()` 现算）+ `dispatch_cities.json`（§12 六城建议名单，`claim_enabled` 全 false=§11.1 降级态）+ `acceptance_metrics.json`（BP §11 闸门指标投影）。
- **§6.4/C9 开闸评估**：`dispatch/cities.py`——claim_gate_status 三条件可解释明细（供给=active 档案 / 需求=近 90 天 published 包 / 拒单率<40% / 公示=规则版本存在为代理，留注⑨）+ 种子城市开关 AND；未开闸 403 `claim_closed`。
- 测试：`server/tests/test_dispatch_p1_r4.py` 14 例。全量 1386 passed + 6 skipped；桌面 654 与 typecheck 零改动全绿。
- 口径（goal-r4 实测）：83 表、迁移头 `f4b8c2d6e3a1`（12 revision，零迁移）、路由 224（+4）、ENTRIES 64（+4）。轮次报告 `docs/goal-r4-派单引擎.md`；台账第十六节。

## [未发布] — goal-r3 派单引擎轮（2026-10-31）

### 派单引擎 P0 簇②收尾——P0 8 项全落地（对照派单设计文档 v1.0 §8.3：P0-1/P0-2 + §9.5）

- **P0-1 交付包服务层**（§2.2/§2.3/§2.5）：`dispatch/packages.py`——canonical_json（键字典序/UTF-8 原样/Decimal→str/null/模块先排序）+ sha256 快照**发布时算一次即冻结**（改 solution/quote 不回写；撤回/拒绝/过期后重发 = dispatch_round+1 + 新编码 + 新哈希，版本对 Unique(project_id, round)）；§2.5 八态状态机通用迁移表（每次迁移写 OperationEvent）+ withdraw 的「本轮进行中 offer」防御守卫；发布前置=报价 finalized（422）；`PKG-{项目码尾段}-{轮次}` 编码；§9.3 接单交接以项目管理位（leader）为 actor 复用 `add_project_member(member)`（接单人本人交接前无 can_manage——留注⑧），幂等 + stale_version 重试。
- **P0-2 package_access 第三语义**（§9.1/§9.2）：`package_access` 表（package×user×role 三元组唯一，lead/seller/delivery/audit，可撤销）+ `dispatch/access.py`（无授权 404 不泄露存在性；admin 平台域放行）+ 交付包 API 字段白名单 12 项 + 交付方席位 40% 金额（发布时物化冻结到 `delivery_seat_amount`——禁 join quotes 的代价，留注⑥）+ `dispatch/routes.py` 6 路由（守卫路由层前置；管理动作平台侧 403；接单=平台侧或被指派人本人+delivery 授权双门槛，冒名 403）。api_catalog ENTRIES +6。
- **§9.5 隔离测试基线四条全绿**（开池四道闸之闸①）：跨主体访问 100% 拒绝（4 路由参数化 403/404）；响应体字段断言（键集精确等值、报价/收款/客户真名字段零出现）；静态检查（dispatch 读路径源级禁 Quote/Payment/Contract 引用、全包禁裸 `session.query(`）；渗透用例（越权接单 403、快照篡改无写入口 405、撤销授权重放 404 + 显式 re-grant 才复活）。
- 测试：新增 `server/tests/test_dispatch_p0_r3.py` 15 例；迁移 `f4b8c2d6e3a1`。全量 1372 passed + 6 skipped；桌面 654 与 typecheck 零改动全绿。
- 口径（goal-r3 实测）：83 表、迁移头 `f4b8c2d6e3a1`（12 revision）、路由 218（+6）、ENTRIES 60（+6）。轮次报告 `docs/goal-r3-派单引擎.md`；台账第十五节。

## [未发布] — goal-r2 派单引擎轮（2026-10-31）

### 派单引擎 P0 簇②表建设（对照派单设计文档 v1.0 §8.3：P0-3/P0-4/P0-7/P0-8）

- **P0-3 供给池档案**（§3.2/§3.3）：`fde_profiles`（一人一档：level 标量 L1–L4 + 四大子能力域独立评分轴 + 申报制标签 + 城市围栏 + 产能双列）+ `fde_level_evidence`（等级判定证据链：核验人/时刻/客观计数快照/依据单据只存 source_uri+sha256 指针）+ `dispatch/profiles.py`（L1–L4 晋级判据可复算查询——独立交付/复购/带教/四域短板下限，判据不足 422 `level_evidence_insufficient`，全过写证据链 + 更新档案 + `fde_level_promoted` 审计事件）。
- **P0-4 分成落库**（§7.2/§7.4）：`payments` 只加 `acceptance_passed_at` 一列（唯一约束不动、D+7/15/30/60 催款读时现算零改动）；`delivery_settlements` 席位级结算表（商务四席位 platform/region/city/delivery，与交付包执行四席位不同名不同义）+ `dispatch/settlements.py`（四席位 35/5/20/40、冷启动同城前 3 单 40/5/15/40、平台吸收舍入尾差保证 Σ=实收基数；劳务报酬**累计预扣法**（率表集中一处待法务确认）；状态机 draft→accrued→payable→paid/disputed，accrued 双条件=实收+G8 过门，payable 发票前置 422，paid 凭证指针）。双钩子：收款实收回填 upsert 结算草稿（无交付包项目纯 no-op）；G8 过门打标验收时刻并推进计提（晚到尾款收款即补，幂等）。
- **P0-7 配置常数**（§6.2）：`system_configuration` 增只读 `dispatch_constants` 节（时间常数 9 项 + Top-N + Stage B 权重 + 等级映射分 + 席位份额/冷启动 + 新人保护 + 拒单权，MappingProxyType 源级只读）——不进 PUBLIC_FIELDS（PUT 可写集精确等值校验天然拒改），实现代码唯一引用源，禁散落硬编码。
- **P0-8 规则版本**（§6.2/规则表 B9）：`dispatch_rule_versions` + `dispatch/rules.py`（30 天公示窗强制：生效日 < 发布日+30 天 → 422 `notice_window_required`；到点 published→active、原 active→retired 至多一个 active；快照必备节校验 admin-only；版本切换后旧 offer 的 `match_breakdown.rule_version` 永指当时版本）。
- **schema 调整**：`projects.enterprise_code` 全局唯一约束放宽为普通索引（派单 §3.3 复购判据要求同企业 ≥2 项目可表达；代号红线不动，三段两枚「·」格式校验保留——详见轮次报告留注③）。
- 测试：新增 `server/tests/test_dispatch_p0_r2.py`（12 例：L1/L2 证据链正反例、7 里程碑×四席位+累计预扣链、冷启动、状态机、G8 过门 API 全链路含晚到尾款补计提、配置只读断言、规则版本公示窗/角色/旧 offer 不回写）；`tests/conftest.py` 每用例清理序补派单六模型（FK 安全序）。
- 口径（goal-r2 实测）：82 张表、迁移头 `e3a7c5d9f2b8`（11 revision）、pytest 1357 passed + 6 skipped、桌面 654 用例零改动全绿。轮次报告 `docs/goal-r2-派单引擎.md`；台账新增第十四节。

## [未发布] — goal-r1 派单引擎轮（2026-10-31）

### 派单引擎 P0 双闸门（对照派单设计文档 v1.0 §8.3）

- **P0-5 门禁验收分离**（§9.4，§8.8 开池四道闸之二）：`gates` 加 `submitted_by_user_id` / `decided_by_user_id` / `is_delivery_party` 三列（迁移 `d2f6b4c8a1e9`）；`decide_gate` 双 403 防线——① 拍板人=该门禁证据执行人 → `gate_decider_conflict`（代码强制、先于其余业务校验，不可绕过）；② 交付方执行的 G8/G9 非 admin 拍板 → `gate_decider_role_required`（§11.3 方案①过渡口径）。单租户时代「同一用户提交+拍板」从 200 变 403，是刻意的硬闸门。
- **P0-6 events 白名单**（§2.5 坑 1）：`projects/events.py` 注册 `delivery_package` / `dispatch_offer` 两类 OperationEvent 目标（offer 的 project_id 经交付包反查）；为此按 §8.2 DDL 级约束先行落 `server/src/fde_api/dispatch/` 包两张骨架表（`delivery_packages`：8 态派单状态机 + `Unique(package_code)` + `Unique(project_id, dispatch_round)` + 扩圈半径 Check(25/50/100/0=全城哨兵)；`dispatch_offers`：`Unique(package_id, dispatch_round, candidate_user_id)` + 6 态 Check + VersionedMixin 乐观锁位 + `match_breakdown` JSON）——**服务逻辑零预埋**，发布/快照/匹配随 P0-1/P1 轮落位。
- 测试：新增 `server/tests/test_dispatch_p0.py`（6 例：两类事件目标写入、执行人自拍 403、交付方 G8 平台拍板、服务层防绕过、乐观锁位）；`test_gates_api.py`（5 例）与两个冒烟脚本改双拍板人（执行人=lead、拍板人=admin），门禁冒烟加「执行人拍自己的门 403」钉子。
- 口径（goal-r1 实测）：78 张表、迁移头 `d2f6b4c8a1e9`（10 revision）、pytest 1345 passed + 6 skipped、桌面 654 用例零改动全绿。轮次报告 `docs/goal-r1-派单引擎.md`；台账新增第十三节。

## [未发布] — goal-r3 技能循环（2026-10-30）

### 仓库健康巡检（G10）

- dynamic-workflows 编排只读巡检：**4 个只读子代理并行**（测试覆盖地图新鲜度 / docs 与代码漂移 / 依赖与 TODO / 台账逐节对账）→ **独立复核员**逐条复核 → 结构化报告。43 条原始发现全部坐实（0 驳回 0 存疑），**P1=0 / P2=14 / P3=29**。全程零变更——落盘走本 PR。
- 新增 `docs/仓库健康巡检-G10.md`：四面逐条发现（每条带 file:line 证据与复核状态）+ 下一批 backlog 三批建议（文档新鲜度批 / 依赖卫生批 / 功能欠账批，优先级逐条写明）。
- 关键坐实项：覆盖地图计数漂移 948→1330 collected（桌面 496→512，且 496/api-ipc(7) 写作时即不准）；「SES 未建」两处失效（G9 已预建默认关闭）；变量与密钥缺 8 个 FDE_SES_*；权限矩阵缺 mailing/SNS 例外鉴权行；**ruff/mypy/pre-commit 未入 lock，CI 门禁裸装最新**；台账对账 24 条中 5 条确认已完成、19 条仍待办（含 4 条 P2：research 三态 UI、PATCH-confirm 分叉、analyzing 对账、README 初始化节）。
- 随本 PR 修正自家文档两处（巡检发现）：`docs/SES发信模块-G9.md` §五闸门顺序归因（发信域约束在 service 前置，不在 decide_send）与 §八测试分桶（9+5+12+1=27）。
- 台账新增第十二节（backlog 三批推进）。

### SES 发信模块预建（G9｜WP-E）

- 新增 `server/src/fde_api/mailing/`：**默认整体关闭**（`FDE_SES_ENABLED=false` 时发送路径落 `drop_disabled`、SNS 回调端点一律 403，默认部署零行为影响、零 AWS 依赖——boto3 延迟导入，未启用时不 import AWS 栈）。SES 生产批复下来**只需改配置启用**，不改代码。
- 发送路径 `send_email`（service 函数，**不设 HTTP 路由**——避免未批复时出现可打的发信口）：闸门顺序固定 = 开关 → 发信域约束 → 幂等键 → 收件人抑制 → 当日限额（只数 UTC 当日）→ 打 SESv2；throttle 记事件并返 503（可重试）、拒收返 502（不可重试），失败不占发送台账。
- SNS 回调端点 `POST /api/v1/mailing/sns/events`：**签名即鉴权**（SNS 带不了工作台 JWT）——校验 Signature v1（RSA-SHA256，字段序按 AWS 固定顺序）+ `SigningCertURL` 限 `sns.*.amazonaws.com`（校验不过则**不发起任何外联**）+ `SubscribeURL` 同域限制 + `TopicArn` 白名单；退信/投诉只落地址 + 分类 + 通知 sha256 指纹，**不落通知原文**。
- 新增两表（迁移 `a9c3f1d8e2b4`）：`mailing_sends`（幂等键唯一）、`mailing_events`（`event_key` 唯一——SNS 是 at-least-once 投递，重放不重复计）。bounce/complaint = 地址级死刑（进抑制名单），delivery 不影响地址。
- 发信域口径落到配置校验器：FROM 必须落在 `FDE_SES_SEND_SUBDOMAIN` 子域内，主域 `somwyn.com` 启动即失败（`ses_sender_domain_forbidden`）。DKIM/SPF/DMARC 写 `docs/SES发信模块-G9.md` 不写死代码——**子域**加 SPF，**主域 SPF 不加 SES include**（否则扩大主域邮件面）。
- SNS 主题策略须带 `aws:SourceArn`（配置集 ARN）+ `aws:SourceAccount`——缺 `SourceArn` 即 confused-deputy 洞（任账号 SES 都能往我们主题灌事件）。AWS 凭证走 boto3 默认凭证链，不配进本模块、不进仓库。
- 新增 `server/tests/test_mailing_ses.py`（27 例，**零真实邮件**）：假客户端 + botocore Stubber + 自签证书验签；覆盖闸门顺序、bounce/complaint 抑制、幂等重放、坏签名/错主题/非法 JSON 拒绝、text/plain 报文解析、配置校验器。
- 依赖：`boto3>=1.36,<2`（pyproject + `requirements.lock` 钉 1.43.122/botocore 1.43.122/s3transfer 0.19.3）。

### 后台作业死亡后对账重排队（台账 §八 第 1 条落地，2026-10-30 晚）

- 问题：worker 被杀（OOM/部署/重启）时，它从 redis 队列弹走的作业 id 随进程一起消失——outbox 事件已 `dispatched`（派发器不再看它），`BackgroundJob.max_attempts`/`available_at`/`locked_until` 无人消费，于是作业永远停在 `running`，业务行（指引分析 `analyzing`、会话 turn `running`）永远停在中间态，前端每 2 秒轮询到天荒地老，唯一解法是手工 `RPUSH fde-jobs <id>`。这正是 10-30 登录事故里那笔孤儿作业的成因。
- 修复一（`jobs/worker.py`）：`run_job` 把「认领 + 执行 + 落终态」从**一个事务**拆成三段——认领（`status=running` + 租约 + `attempts+1`）先单独提交，执行期间由守护线程**续租**（默认 60s 一次，租约 5min），终态再单独写回。三个后果：① 在跑的作业对其他进程**可见**（此前全程只有 pending，对账无从分辨「有人在做」与「做的人死了」）；② 行锁只存在于认领那几毫秒，不再被 handler 全程占着（长任务钉着连接正是 10-30 锁雪崩的形状）；③ 租约过期从此是**死亡信号**而非「慢任务」信号。返回语义（not_found / already_terminal / leased / no_handler / failed / succeeded）保持不变。
- 修复二（`jobs/reconcile.py` 新增）：对账扫描捞两种无主作业——① `running` 且租约已过期（worker 死了）；② `pending`/`queued` 且超过 5 分钟无人认领（队列项丢了）。捞到之后：**可恢复类型重排队**（受 `max_attempts` 与 `available_at` 约束，入队前先提交库事务，队列项丢失下一轮按宽限期再捞），否则**落 failed** 并调用业务行收尾钩子，把业务行推到终态（前端停止轮询，用户看到「进程中断，请重试」）。
- 可恢复性按类型显式登记（不默认重跑）：`project.presurvey.analyze`/`ai.chat`/`ai.execute`/`file.scan`/`file.preview`/`document.generate`/`research.export` 可重排队——它们的 handler 都已跳过终态业务行，重跑不会覆盖已有结论；**`automation.execute` 不可重跑**（有对外副作用：发信、MCP 调用），死亡即落 failed 交人工重触发。
- 业务行收尾钩子（`jobs/handlers.py` 注册表 + 四处实现）：指引分析 → `analysis_worker_lost`；AI 会话 turn → `failed`（卡住的 turn 会让整个会话永久 `chat_busy`）；调研导出 → `failed`；自动化 run → `failed`。终态业务行（`ready`/`completed`/`succeeded`）一律不动——对账不许覆盖已有结果。
- 接线：worker 循环每 60s 扫一次（扫不出东西时零 DB 写）；另给运维留了手工口子 `flask reconcile-jobs`（容器被杀后可立即补投，不必等下一个周期）。
- 回归钉子：`tests/test_job_reconcile.py` 新增 15 例——租约过期重排队 / 活租约不动 / **被活 worker 行锁占住的作业被跳过（`FOR UPDATE SKIP LOCKED`）** / 孤儿 pending 重排队 / 新鲜 pending 不动 / 重排队后不热循环 / 次数用尽落 failed / 不可恢复类型落 failed / 指引分析与会话 turn 的收尾与「终态不被覆盖」/ 端到端（孤儿作业经对账后真的跑完）/ **认领状态对其他会话可见** / **执行期租约被续期**。

### AI 工具循环锁泄漏修复（生产事故回补，2026-10-30 晚）

- 事故：worker 跑 AI 聊天时工具调用撞 DB 连接断线，`_run_tools` 兜底吞掉异常继续循环，但共享会话带着未决事务与 `users` 表行锁停在 idle-in-transaction 十余分钟；登录路径的 `FOR UPDATE` 全体排队，gunicorn 超时杀 worker 又留下新的半死连接，锁滚雪球致登录 500。
- 修复：`server/src/fde_api/control/ai_tool_loop.py` 两处——① `_run_tools` except 分支立即 `session.rollback()`，工具异常不再让会话持锁过夜；② 主循环每轮工具执行完也 `db_session.rollback()`——工具循环工具全只读，回滚零损失，却保证下一次 provider 调用（最长 `timeout_seconds` 300 秒、零 DB 流量）不会骑在一个仍持有行锁的 idle-in-transaction 连接上（事故里 13 分钟的持锁窗口正是这个形态）。
- 回归钉子：`tests/test_ai_tool_loop.py` 新增 1 例（`OperationalError` 抛出时 `db.session()` 返回的会话在 with 块内恰被 rollback 两次：崩溃处理器一次 + 主循环每轮清理一次；17 例全绿）。
- 运维侧另两笔（无代码）：`pg_terminate_backend` 清锁 + worker 重启解堵；孤儿 pending 作业（outbox 已 dispatched、redis 队列项随重启丢失）手工 `RPUSH fde-jobs <id>` 补投。关联既有待办：台账 §八 第 1 条（进程死亡后无对账重排队）——已由本文件上一节的「后台作业死亡后对账重排队」落地，手工补投不再是唯一解法。

### 跨库只读验证脚本固化（G8）

- 新增 `scripts/verify/`（sql-queries 方法）：`run-verify.sh` + `verify-twenty-persons.sql` + `verify-n8n-executions.sql`——Twenty persons 总数/新增窗口/ICP 分布/去重命中，n8n 最近执行状态与耗时。连接参数全走环境变量（容器名/用户/库名，无口令：psql 在 db 容器内走本地 socket，脚本不读 .env）；每个会话显式 `BEGIN; SET TRANSACTION READ ONLY; … ROLLBACK;`；SQL 经 stdin 进容器（中文不走 argv）；输出仅计数不含客户明细。
- 口径：ICP 从笔记标题「冷邮件草稿 (ICP N)」提取每人最高分（≥70 培育 / 55–69 留档双层）；去重命中 = 同主邮箱挂多人（期望 0）。
- 宿主实跑一次并记录计数摘要到 `docs/验证脚本-G8.md`：persons 75（7d 新增 64，ICP 记分 9 全在 55–69 留档档）、重复邮箱 0（去重有效）、公共管道 4 成功（均值 27s）、QFhunterFeed01 2 成 3 败（运维信号，仅记录）。

### 意图差距审计（G7）

- 新增 `docs/意图差距审计-G7.md`：以 G2 七份意图文档 + AGENTS.md 红线为基线，逐边界核对代码执行点。**B1–B4 零差距**——门禁证据只收指针+64 位 hex sha256（`gate_service.py:520-548` + `workbench/models.py:544-547`，无 blob、无上传路由）；confirm 只能 canManage（`service.py:174-180` + `api_catalog` 零 guidance 条目，AI 无代拍板面）；bridge-poll 唯一进程出口是两个 openfde 只读子命令（`bridge-poll.mjs:68,101,110`，无写相 CLI、真相层零写面）；.env 不入 VCS 有可校验闭环（`.gitignore:1-5` + 全树仅两个 example 被跟踪 + gitleaks PASS 盲区规则）。
- F1 [P2→已处置]：「origin 永不 push」原本只有文档约束、无本地强制——本机已加 `git remote set-url --push origin FORBIDDEN-origin-is-upstream-use-fork`（push 必失败已实测，fetch 不变）；每台新克隆须重复，建议进 README 初始化节（台账十.1）。
- F2 [P3→已修]：G4 重写 `jobs.py` 使意图文档 4 处行号引用漂移、步骤 4 语义未反映自动重试——《系统意图-关键流程》《系统意图-自动化面》已同步更新。
- 台账新增第十节。

### 真实浏览器 UI 回归 harness（G6）

- 新增 `desktop/gui-harness/`：纯浏览器驱动 renderer 的回归 harness。dev-only Vite 配置（端口 5199）注入 `window.fde` 桥 shim（登录/刷新/`ApiResponse` 信封、deviceLabel→device_label 转换、401 刷新重试；`app.version` 返回裸字符串——三处契约此前只有 Electron 真机能验证），同源 `/api` 代理到 127.0.0.1:8010（浏览器有 CORS 而 Electron IPC 没有），并给生产 CSP 打 dev 补丁（`connect-src 'self'`、`style-src 'unsafe-inline'` 供 Vite 开发样式）。不引新依赖，不进打包产物。
- 新增 `desktop/gui-harness/regression.mjs`：仓库自带 playwright-core + 已装 Chromium 驱动两条链路 11 个断言点——①指引链：登录→项目→查看预调研分析→**只读 draft 态直接出现「确认并用于项目指引」按钮（R11 事故防线，浏览器实测通过）**→弹窗内编辑；②集成桥页：侧栏进入、状态文案、「立即采集」按钮在浏览器 harness 下被平台守卫拦为 `bridge_platform` 错误提示（与真机同代码路径）、采集反馈区可见；截图留本地（已 gitignore，含本机路径与项目代号）。
- 新增仓库技能 `.agents/skills/fde-gui-regression/SKILL.md`：harness 原理、启动/种子/运行命令、fixture 陷阱（enterprise_code 需两个「·」、module_keys 必须命中 ModuleCatalog）、断言口径与已知坑（hash 路由需点侧栏、Vite 单实例、中文经 `\uXXXX` 转义）。
- 回归报告 `docs/GUI回归-G6.md`：11/11 通过表、R11 防线结论、2 条 P3 finding（认领入口失败静默无提示——已记台账第九节；命名约定再次复核，与台账七.3 同源）。

### 代码评审门与回溯评审（G5）

- 新增 `docs/代码评审-G5.md`：PR #24 的参与者约定法评审报告（scope/dimensions/findings/coverage，含 9 条保留 finding 与 6 条驳斥成立的丢弃候选）、PR #17/#18 回溯评审、WP-B Serper 修复说明。
- 评审修复（随 PR #24 提交）：DSH 路径的裸 `JSONDecodeError`/`ControlServiceError` 逃出错误分类 → 结构化输出失败现在落 `ai_output_invalid`（可重试）/配置类不可重试，DSH 部署形态下重试能力不再静默失效；重试耗尽文案只在终态错误可重试时才劝「请重新发起分析」；存储对象缺失归入专用码 `source_object_missing`；限流/超时类瞬时错误重试前退避（契约失败不退避）；本地 DOCX 解析失败按确定性改为不可重试（存储读取 `OSError` 仍可重试，供应商侧提取失败不变）；重复投递不再对已终态分析二次调用 AI；每次尝试用独立请求号（上游去重不会挫败重试）；`python-docx` 声明下限提到 `>=1.2`（样本生成器用了 1.2.0 才有的 `add_comment`）。
- 新增回归钉子：重试语义 +7 例（请求号独立/退避双向/不可重试终态文案/存储缺失分类/终态守卫/任务仍为绿）、DSH 分类 +2 例。
- 回溯评审 PR #17/#18 发现 3 条（台账第七节）：PATCH 成功而 confirm 失败后前端版本与库态分叉致重试必 409（P2）、审核面板内无旧版源警示、认领命名约定无服务端保障。
- WP-B 修复交付（获客引擎 `AI_Find_Customer`，独立分支 `fix/serper-region-iso-codes`，commit 2c51e1a；其 origin 为上游仓库，不推送）：`_REGION_GEO` 由表自身 `gl` 值反查建 ISO-2 索引，ISO 码（US/CA/DE）不再落空致 Serper maps 400；键归一（下划线/连字符→空格）；命中失败打 warning（此前静默降级为全局搜索正是 400 无人察觉的原因）；引擎 +6 例，全量失败集合与改前逐条一致。

### 指引契约失败自动重试加固 + 对抗 DOCX 样本（G4）

- `server/src/fde_api/guidance/jobs.py`：预调研分析任务内自动重试——`GUIDANCE_ANALYSIS_RETRY_LIMIT = 1`（不含首次，测试钉死）。可重试失败（retryable=True 的 KimiError / GuidanceContractError 契约违反，即 MiniMax 概率性不守 JSON 合同的已知现象）先自动重试一次，仍失败才落 failed，failure_message 携带「已自动重试 N 次仍失败」的用户可见提示；不可重试（如 ai_service_not_configured）一次即败不消耗额度；source_missing 在构造 AI 客户端前拦截（零 AI 调用）；新增兜底分类 analysis_unexpected_error——未预期异常不再让分析卡在 analyzing（前端会无限轮询），且消息不携带异常串。每次尝试重新打开文件流。
- 对抗 DOCX 样本生成器 `server/tests/fixtures/presurvey/generate_fixtures.py`（9 种：空文档/空表格/合并单元格/批注/异常样式/缺失章节/超长段落/嵌套表格/非 ZIP 字节流；python-docx 1.2 程序化构建 + document.xml 最小注入），session 级构建到临时目录，二进制不入 git。
- 新增 `tests/test_guidance_adversarial_fixtures.py`（11 例）：两层解析（guidance 块抽取 / 本地全文提取 / Kimi 本地提取分类）对 9 样本的行为契约——畸形输入绝不崩溃、空内容失败为可分类错误（kimi_file_extract_failed retryable=True）、合并单元格全文层按 _tc 去重且块层按格位稳定引用、批注不泄漏进提取文本、异常样式不阻塞提取、嵌套表全文层递归可见（块层不可见，钉住两层差异）、超长段落整体提取。
- 新增 `tests/test_guidance_retry.py`（9 例）：重试语义钉子——契约失败重试一次后成功 / 耗尽后 failed 带 ai_output_invalid 与自动重试提示 / 调用次数恰为上限+1 / 不可重试一次即败 / 真实提取路径吃空表格样本落 kimi_file_extract_failed / source_missing 零 AI 调用 / 未预期异常落 analysis_unexpected_error 且消息无异常串 / 成功路径一遍 ready。
- conftest 清理清单补 `ProjectGuidanceAnalysis`/`ProjectPresurveySource`（此前测试库跨用例残留指引行会顶住 RESTRICT 外键清理）。

### 验收场景矩阵与缺口补测（G3）

- 新增 `docs/验收场景矩阵-G3.md`：指引链 / 集成桥手动采集 / SES 发信策略三链场景表（目标/起始/角色/分步/预期），每条映射钉住它的测试。
- 指引链补测 `desktop/tests/renderer/guidance-chain-scenarios.test.tsx`（8 例）：分析中→ready 自动开审进编辑态、failed 面板 role=alert 可见且无确认按钮、start() 失败 inline 可见、cancelled/queued/extracting 参数化占位展示、confirmed 卡片摘要 + `source_is_stale` 旧版重分析横幅（ProjectGuidanceCard 此前零测试）；集成桥链核对后无缺口（既有 13 例已覆盖全回路，platform 显式注入 win32/linux）。
- SES 策略先行 `server/src/fde_api/mailing/policy.py` + `server/tests/test_mailing_policy.py`（27 例）：四态分类（仅 throttle 可重试）、幂等闸门（同 message_id 判 duplicate 且先于限额/抑制）、每日限额（沙盒默认 10 可配）、总开关（未启用一律 drop_disabled）、发信域约束（仅配置子域，主域 somwyn.com 拒绝）、指数退避封顶——纯逻辑零 AWS 依赖，G9 在其上接客户端与 SNS 回调。
- 发现并记台账：cancelled 终态在审核面板仍显示「分析正在后台继续」占位（文案缺陷）；start() 失败提示不透传 failure_message 明细。

### 系统意图文档基线（G2）

- 新增 7 份意图文档（`docs/系统意图-*.md`，shipping-artifacts 方法，README 仍是部署唯一权威、交叉引用不复制）：架构与信任边界（根文档）、关键流程（预调研指引链/门禁/报价收款三链含鉴权点与 deny 例）、权限矩阵（三套角色体系 × 15 资源域）、变量与密钥（变量名×来源×轮换×风险，只写名不写值）、测试覆盖地图（现有 948+496+14 用例 / 建议 / 缺口三段）、定时任务（worker/scheduler/宿主 FDE-Bridge-Poll）、自动化面（AI 助手工具面/预调研管道/集成桥/任务中心，App 拥有副作用原则）。全部条目引用代码位置，作为 G7 意图比对基线。

### 内置手册与 UI 帮助 parity（PR #19）

- `help_manual.md` 补收「实操示例：证据文件怎么写（somwyn 样板）」整节与 G↔S 阶段映射（此前只在桌面端 HelpPage，help_fetch 检索不到）；新增双手册主题 parity 测试与 G↔S 映射与 `seeds/gates.json` 一致性测试，防两份手册再次分叉。

### 仓库级操作技能（G1）

- 固化 3 个仓库级 Agent 技能到 `.agents/skills/`（skill-creator 规范，随仓库分发）：
  - `fde-package-verify`：便携版打包全流程——electron-builder 产物 → asar sha256 → 中文 marker 字节验证（防控制台编码假阴性）→ 换新目录命名 r N+1 交付。
  - `fde-bridge-capture`：集成桥手动采集 runbook——`schtasks //Run`（Git Bash 双斜杠）或桌面「立即采集」按钮（同一代码路径）、`logs/bridge-poll.log` 验证到站、改 server 必须重建镜像、采集器只读纪律。
  - `fde-delivery-flow`：标准交付流检查单——分支 → push fork（永不 origin）→ PR → 4 CI 全绿 → 合并 → ff 本地 main → 删分支，每步验证点与常见事故对照。

## [未发布] — goal-r2 第二轮（2026-10-28）

安全口子、假绿灯与跨机口径一轮。**版本号未升**（按发布列车统一处理）。

### 安全（批次 G）

- **清除已入库的明文数据库口令**：备份脚本里的三条口令字面量（两条不同口令）已从工作树删除。凭据随 `2f90484` 入库，**视为已泄露，需人工轮换**（见交接清单）。
- **范围外备份管道移出仓库**：与 FDE 交付线无关的 n8n/Mautic/openoutfind 备份脚本迁至 `D:\test\AI外贸获客\scripts\`（副本 sha256 校验一致，仓库内可由 `git show 2f90484:scripts/backup-pipeline.sh` 恢复）。
- **集成桥读接口收敛门禁**：`GET /bridge/engagements`、`GET /bridge/status` 此前只要求登录（任意用户可枚举全部项目名与企业代号），现与写接口同级要求 `project_lead`。
- **登录限流键改为「用户名 + 来源 IP」复合键**：此前单个 IP 连错 5 次即可定向锁死任意用户名（含 admin）。Redis 不可用时记 WARNING（可观测），并可用 `FDE_LOGIN_RATE_FAIL_CLOSED=1` 切为 fail-closed。
- **秘密扫描线自证有效**：实测默认 gitleaks 规则对 `*_PASS=` 形态**整体漏报**（历史口令与随机探针同形态却一个抓一个不抓），新增 `.gitleaks.toml` 兜底规则与 `scripts/check-secret-scan.sh`（含 `--self-test` 哨兵自测）。

### 假绿灯（批次 H）

- **mypy 基线改计数法并纳入 tests**：旧实现按「文件+错误码+归一化消息」去重，实测 45 条基线条目掩盖了 181 次同类新增。
- **代号化检查不再吞错**：grep 退出码 1（无命中）与 ≥2（错误）区分；邮箱策略真正读取 `FDE_PSEUDONYM_EMAIL_POLICY`（缺省 fail）；黑名单提取 0 条即 FAIL；psql 失败不再当 0 行；`projects` 表 0 行即 FAIL（空库扫描等于没扫）。
- **CI 代号化 job 先迁移灌数再扫描**（原为空库扫描）。
- **冒烟脚本补真实断言**：auth 冒烟新增跨用户名隔离断言，commercial 冒烟种子管理员 try/finally 清理并断言归零。

### 跨机口径与运维（批次 I）

- pre-commit 三个钩子改走跨平台 node 入口（不再写死 Windows venv 路径）；README 更正 `.env` 模板来源与 venv 跨平台表述；操作手册路径参数化。
- compose 四服务统一 `restart: unless-stopped`；api healthcheck 改走 `/api/v1/health/ready`（真正校验依赖）；worker/scheduler 新增基于 Redis 心跳的 healthcheck（进程还在 ≠ 还在干活）。

### 打磨（批次 J）

- 业务枚举（价格档位 / 门禁五态 / C 分支 / SOW / 业务阶段）改由服务端 `GET /api/v1/workbench/options` 下发，前端保留本地兜底；存库值一律不变（旧中文标签数据照常可读）。
- 门禁汇总徽标改为按实际状态遍历（此前硬编码五态，服务端新状态会被静默丢弃）。
- 新增交付审计专用表 `document_delivery_records`（+ 迁移 `f3c8d2b7a1e5`），交付记录可按项目维度检索。
- C 分支触发档位收敛为单一常量；B 层分上下界都夹；扩展中心路由加角色门禁；预调研与调研导出的轮询失败对用户可见且失败后继续下一轮。
- **项目指引审核入口补缺**：指引卡片挂载时自动认领「已上传但尚未确认」的预调研源——此前分析/审核入口只在本次会话内上传后才出现，服务端（定时任务/历史会话）跑出的待审核指引在界面上没有任何入口；空状态文案同步提示审核入口。
- **指引审核弹窗只读态可确认**：确认按钮此前只在编辑模式渲染，用户从「查看预调研分析」进入的只读预览没有确认入口（得自己发现右上角「编辑」才能确认）；现在只读草稿底部直接显示「确认并用于项目指引」。

### 智能助手知识（help_fetch）

- 智能助手此前只拿到会话历史，「使用帮助」栏内容它一无所知（手册只在桌面前端渲染，服务端镜像里没有）。本轮把 `docs/工作台操作使用手册.md` 随 `server/` 源码烘进镜像（`fde_api/control/bundled/help_manual.md`），新增只读工具 `help_fetch`（按章节检索手册原文，带目录与分页），任意 AI 级别可用；对话入口注入工作台式 system prompt，引导「先查手册再作答」；新增公共 Skill `workbench-help`（`flask seed-public-skills` 灌入）。桌面「使用帮助」页同步注明智能助手内置同一份手册。

### 口径

- 服务端数据表 **73 → 74**（本轮新增 `document_delivery_records`）；迁移头 `e5b8a1c9d3f7` → `f3c8d2b7a1e5`。

## [v0.2.0] - 2026-10-26

交付流程与安全加固版本；桌面端与服务端版本号同步升至 `0.2.0`。

- 新增**门禁引擎 G1–G9**：pending → evidence → passed/failed 状态机（G9 支持 conditional_pass）；证据仅保存 `source_uri` 指针与 sha256 指纹，真实文件留在项目工作目录；claimed 与 accepted 分离。
- 新增**报价 / 收款（里程碑）/ 合同**商务看板与标准 FDE 项目模板派生。
- 项目工作台新增「门禁」「报价收款」页签；新增集成桥（本地 openfde / fdeops 工作目录的只读投影）与任务中心。
- 集成桥页新增「立即采集」按钮：桌面端一键触发宿主计划任务（与 4 小时周期同一代码路径），新快照到站自动刷新，无需等下一个采集窗口。
- 桌面端新增内嵌「使用帮助」：各模块操作说明、门禁 G1–G9 流程、实操示例与故障排查。
- 安全加固：登录连续失败限流（Redis 计数）、refresh token 轮换与改密即失效、API 容器非 root 运行、门禁证据哈希校验、CI 常驻 gitleaks 秘密扫描。
- 工程卫生：CI 并发取消与四 job 超时上限、pip/npm 缓存、全仓 LF 归一化、测试口令字面量收敛单点。
- README 按当前功能与 Docker Compose 部署路径重写，新增换机迁移清单。

## [v0.1.0] - 2026-09-28

首个开源源码版本。

- 提供 Electron 桌面端、Flask API、数据库迁移、后台 worker 与 scheduler 的源码。
- 提供项目、任务、调研、AI 机会、方案、交付文档、文件和管理员配置等工作台功能。
- 清理历史业务数据、客户资料、运行日志、访问凭据、对象存储文件和发布备份；仓库只保留通用示例与模板。
- 移除客户端自更新功能。升级需由部署者自行部署后端、执行迁移并重新打包客户端。
- 提供 MIT 许可证、安装部署说明、贡献指南和安全报告说明。

当前仅配置 macOS Apple Silicon（arm64）DMG 构建；没有 Windows 客户端。此版本是源码发布，不附带已签名、公证的安装包。公开部署前请更换首次登录密码和所有示例密钥，并阅读 README 的生产部署与安全说明。

本产品采用 vibe coding 方式开发；商用或处理真实数据前，应由部署者独立完成代码、安全、合规及业务适用性核验。
