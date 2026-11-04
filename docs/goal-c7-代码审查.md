# goal-c7-代码审查（桌面端：main, renderer, tests, gui-harness）

> 循环：goal-c ｜ 轮性质：**纯登记轮**（P0/P1 当轮修=0）｜ 日期：2026-11-05 ｜ 基于树：`2dcc61b`（fork/main，#106）｜ 施工面：隔离 worktree `D:/test/fde-wt-c67`（分支 fix/goal-c6-c7-register）

## 1 结论一句话 + 口径数字变化

**桌面全域（main 5 进程模块 / renderer 调研+本体+工作流 / tests 串行口径 / gui-harness 13 页）揪出 1 P2 + 6 P3 登记不修（T-O2b 桌面侧 subject_type 值域滞后服务端开放域→调研 tab 全不可读 CR-032；lcsc 规格书 iframe 检测畸形恒 false 缺件 CR-033；activeMutations 死计数器 CR-034；GlossaryPage 搜索无守卫 CR-035；ResearchWorkspace 导出轮询 stale 回写 CR-036；ResearchOpportunity 零测试 CR-037；new-project 同型 sync-hash CR-038；shots.mjs 缺 T-W6 三面 CR-039；术语状态标签值域漂移 CR-040）；CR-001 五条硬编码复测全在（不新开编号、详情补记）；CR-007 同型残留 1 处登记。零代码改动（纯登记），口径数字不变。**

## 2 审查方法与覆盖面

### 2.1 方法

- 双引擎：`code-review`（主进程 5 模块 + renderer 调研/本体/工作流 + tests 并发/清理 + gui-harness 四子代理分审）+ `intended-vs-implemented`（brand.ts 单一来源红线 + T-O2b 开放域意图锚 + T-W6 三新页覆盖）。
- 主会话对子代理 E1 逐条 E0 升级：grep 桌面五类消费点（`RESEARCH_SUBJECT_TYPES` 7 处）、读 lcsc-runner.ts:147 括号、grep `activeMutations` 零读取点、读 `new-project.test.tsx:279` 同步读——**纠正 1 处**（D-2 activeMutations 初报为「在途写保护未接线缺陷」，实读 index.ts:241 `window-all-closed`/`app.quit` 均不查它=纯 dead code，降级 P3 登记）。
- **红线核查**：品牌名单一来源（`brand.ts`）复测 5 处硬编码（main×3 + index.html + chat.py）全在=CR-001 未修证据，不新开编号；renderer 侧除 brand.ts 外唯一命中 index.html:11（已入 CR-001）。
- 实际覆盖：`main/{index,lcsc-runner,lcsc-finish-dialog,bridge-capture}.ts`、`renderer/research/*`（workspace/definition/form/import/opportunity/types）、`renderer/ontology/GlossaryPage.tsx`、`renderer/workflow/WorkflowConsole`、`tests/renderer/*`（navigation/new-project/project-research）、`gui-harness/shots.mjs`。
- **没看 & 为什么**：桌面文档渲染/模板面（c3 桌面消费面已交付）；主进程 LCSC 查询执行器完整流程（D-1 只审 iframe 检测表达式，下载/保存链路未全审——单用户量级，挂账）。

### 2.2 T-O2b 桌面侧滞后专项（CR-032 P2，E0）

| 面 | 位置 | 语义 |
|---|---|---|
| 值域定义 | types.ts:1 `RESEARCH_SUBJECT_TYPES` 五类 | 服务端=「五类 ∪ 注册表 active − project 根」，桌面仍五类 |
| 读路径守卫 | projectRuntimeValidation.ts:17/66、runtimeValidation.ts:48 | 注册类型对象/表单/import preview 整体校验 false |
| 消费点 | ResearchWorkspace.tsx:222 `loadResearch` 抛 "invalid research dto" | **整个调研 tab 全不可读** |
| 写路径 | ResearchImportDialog:11（四内置类 select）、DefinitionEditor:487/1009、FormBuilder:233、types.ts:21 CHILD_TYPES_BY_PARENT | 注册类型不可建/不可导入 |

## 3 发现清单（台账增删摘要）

| 编号 | 级别 | 状态 | 摘要 |
|---|---|---|---|
| CR-032 | P2 | open（登记，T-O2b 桌面面） | 桌面调研 subject_type 钉死五类，注册类型落库后调研 tab 全不可读 |
| CR-033 | P3 | open（登记） | lcsc 规格书 iframe 检测表达式畸变（`includes(boolean)` 恒 false）→ 勾选 datasheet 必缺件 |
| CR-034 | P3 | open（登记，dead-code） | 主进程 `activeMutations` 计数器零读取点（在途写保护未接线） |
| CR-035 | P3 | open（登记） | GlossaryPage 术语搜索每键入全量重取无守卫（闪空+后发先至） |
| CR-036 | P3 | open（登记） | ResearchWorkspace 导出轮询 effect 无序列守卫（stale 快照回写，下轮自愈） |
| CR-037 | P3 | open（登记） | ResearchOpportunity.tsx（193 行 AI 机会主链）零 vitest 覆盖 |
| CR-038 | P3 | open（登记，CR-007 同型） | new-project.test.tsx:279 同步读 location.hash（异步化即复发） |
| CR-039 | P3 | open（登记） | gui-harness 13 页走查未含 T-W6 三面（子 tab 需 fixture） |
| CR-040 | P3 | open（登记） | GlossaryPage 术语状态标签值域漂移（candidate/retired 误植，draft/superseded 缺失） |

**CR-001 补记（不新开编号）**：本轮复测 `brand.ts` 外 5 处硬编码产品名（main/index.ts:212、lcsc-runner.ts:68、lcsc-finish-dialog.ts:16、index.html:11、chat.py:60）**全在、一处未修**——CR-001（P1 open）维持最强待修项，修法（main/renderer 共享品牌常量模块 + index.html 构建注入 + chat.py config 常量 + 静态检查测试）未落地。

## 4 修复记录

**纯登记轮，零代码改动**（P2/P3 登记不修纪律；CR-001/032 修法挂 T-O2b 桌面面 / 品牌统一轮）。

## 5 未修与移交

- **CR-032（P2）**：T-O2b 桌面同步面——读路径五类守卫放宽到服务端 `usable_subject_type_codes`（或格式尺 `^[a-z][a-z0-9_]{0,59}$`），写路径下拉补注册类型；归 T-O2b 后续桌面轮。
- **CR-033（P3）**：补回内层右括号一行 + 单测；归主进程整理轮。
- **CR-034~040（P3）**：activeMutations 接线/删除、GlossaryPage 序列守卫、导出轮询 sequence、ResearchOpportunity 纯函数单测、new-project waitFor、shots.mjs 三面、术语标签对齐——各归桌面小轮。
- **CR-001（P1，c1 登记）**：仍 open，最强待修项，归品牌统一轮。
- **BLOCKED-EXTERNAL**：无。

## 6 教训（同步沉淀执行者记忆）

1. **「开放了后端值域」不等于「前端守住了」**：T-O2b 服务端把 subject_type 从五类 CHECK 放到格式 `^[a-z]…` + 注册表 active，桌面读路径却仍用五类常量做 DTO 守卫——**增量数据（注册类型）一落库，旧读路径整体校验失败=全 tab 不可读**，比「看不到新类型」严重一个量级；审计开放域改动必追到消费侧最后一环（DTO 校验尺）。
2. **布尔短路 + `includes(boolean)` 是压缩误伤高发点**：`f.src.includes('x'&&f.src.includes('.pdf'))` 外层 `includes` 收到 boolean——`String.prototype.includes` 对布尔参数实查其字符串形态（`"true"`/`"false"`），对真实 URL 恒 false；这类表达式**语法合法、不崩、只在功能面静默缺件**，是主进程内联 JS 注入（`evaluate`/`waitFor`）的专属盲区，靠「下载成功」正向用例测不出（要用非 PDF URL 反证）。

## 7 门禁四件套（本轮收口）

- `npm run typecheck` / `test:server` / `test:desktop` / `check-python-types.py`：本轮**零代码改动**（纯台账+报告），四 job 以 CI 兜底（c5 轮全量 1868 + 桌面 750 为基线，c7 无增量用例）。

**注**：c7 施工面=登记轮，只动 `docs/`（台账+本报告），无 server/desktop 代码路径。

## 8 后记（c8 轮回填）

CR-032 挂 T-O2b 桌面面；CR-033~040 挂桌面小轮；CR-001（P1）复测全在，归品牌统一轮；CR-038 与 CR-007 同型，品牌统一轮顺手改 `waitFor`。
