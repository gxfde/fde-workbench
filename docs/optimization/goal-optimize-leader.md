# goal-optimize：让交付更稳定、可用、可衡量

执行者以本书及引用规格为任务来源，遵守AGENTS；不确定项写 `docs/optimization/BLOCKED.md`，继续独立任务。续跑先读 `docs/optimization/PROGRESS.md`，逐项登记，不重做。
意图：将功能积累变成独立交付、稳定发布与可证明的AI净收益。
优先序：授权/数据安全＞正确性/实证＞完整性＞速度。只允许/禁止是约束；建议可调整并记理由。

## 1. 我替领导拍的板

默认（执行假设，可改判）：串行R0→R1a，再逐轮细化R1b–R5；OWNER项独立备料，不空等凭据。保持现有技术栈，不迁微服务；代价是延后架构扩张。
不虚构人数、SLO、收益阈值或预算；体验用观察记录，真实用户验收需OWNER。
本轮用户授权建议落盘、leader任务书和逐步实施；不覆盖既有UX线独立授权、严格切换及N1/H1–H13边界。

## 2. 界限

总规格：`docs/optimization/项目优化建议与实施路线-2026-11-18.md`。
R0写白名单：`docs/optimization/`新增文档。R1a另含 `scripts/deploy/release_preflight.py`、`tests/deploy/test_release_preflight.py`、README部署节、CHANGELOG本轮节、AGENTS入口；CI只追加新测试步骤，原job/判据不变。
后续轮先在optimization写白名单、接口、验收、回退。超路线或保留人工动作登记待决。禁止改他树未提交文件、凭据、生产数据、真相层；不外发邀请、开公网、代决门禁/扩权、擅跑生产agent/付费模型。禁止改原断言/阈值/skip过关。

## 3. 现状与任务0

2026-11-18当前基线：fork/main `e8253c55`；在途PR #499/#524；UX #522与仿真 #523已合并，主树已回main。本线复用feat/goal-optimize-delivery工作树，实际路径见PROGRESS。开工重查 `git status --short`、`git worktree list`、`gh pr list -R caishide/fde-workbench --state open`、`git fetch fork main`。新树从fork/main起，不切他人树；复用已登记的适用工作树，先核权限。差异仅阻断受影响项。
读注册/上线BLOCKED、学习闭环报告、UX任务书，禁止重开已关远端核验。11-19关窗已有安排，只核回执不重复建任务。目标/顺序/最大风险≤10行写PROGRESS。

## 4. 分轮任务

R0：落六项建议、证据、依赖、停止条件和试用观察模板；校验相对链接、本书≤4000字符；首个交付只称文档就绪。
R1a：只读CLI `python scripts/deploy/release_preflight.py --tree <root> --expected-commit <40位SHA>`；解析Git/文件/迁移AST，不导入应用、不执行迁移/hooks、不读.env。提交匹配且干净、迁移图无重复/缺父/环/多头才exit0；JSON明确候选通过不等于活体通过。输出发布输入指纹，前后核HEAD/脏态，不声称原子锁。验收 `python -m unittest discover -s tests/deploy -p test_*.py -v`；真实临时Git仓＋CLI验证正反例与不泄密，CI追加检查而非替换门禁。已实现并验证，后续验收仍须在对应提交实跑。
R1b：盘全部部署入口，按实际Docker目标/Compose项目互斥；跨树竞争、父失联子存活、子失败、陈旧锁反例；协作锁不夸成强制全局锁。
R1c：固定镜像/迁移/发布清单，隔离恢复并计时核数据/加密配置；生产不得跳takeover_check与三验。
R2：复用注册核验脚本，使用观察模板、核配置清单。真凭据/开闸/用户未齐保持待验；观察→卡点→小改动。UX线接成果，不重复施工。
R3：复用metrics/审计，设计人工投入/返工/验收率/成本；跨场景族验证，不单点升档。新阈值/费用/真实运行先有授权，标准答案隔离不变。
R4：四条链隔离负载，请求/排队/执行/人工等待分开；先基线后优化实测热点。无环境先备工具，不报容量PASS。
R5：契约/类型/文档随轮完成，不全仓重写、不独立补账轮。

## 5. 规矩与技能关卡

开工 `Skill(fde-delivery-flow)`；方案 `Skill(strategy-red-team)`；修复 `Skill(tdd)`。R1a测试边界依本书CLI；跨进程排障 `Skill(systematic-debugging)`。
提交前 `Skill(code-review)`；≥3文件/跨模块 `Skill(requesting-code-review)` 独立盲审，只读diff/文本，不执行被审代码；高敏面 `Skill(intended-vs-implemented)`。实现者执行测试，审查者与执行分离。
push/完成前 `Skill(verification-before-completion)`；收尾 `Skill(neat-freak)`。桌面再 `Skill(fde-gui-regression)`→`Skill(fde-package-verify)`；服务端按README全量测试/类型检查，结构变化刷新清单。工具跑全套工具测试，原四CI job全绿。
新检查有真实失败→修复通过；禁skip/todo、删测试、放宽判据、mock被测核心、吞异常或`|| true`。同项连败3次先查根因/转独立项，不假绿。
feature→push fork（永不origin）→PR→四CI绿→合并。主树有在途改动不强切；ff不满足记挂账；清场依授权。每轮同步进度、CHANGELOG、必要入口；手册若改变保持双份同源。文档-only先验链接与约束，不为凑测试执行被审代码。

## 6. 完成条件

1. R1a有真实CLI正反例；后续轮有竞争/恢复、真实试用、净收益、容量结果。材料/工具就绪、样本不足、OWNER待办不冒充业务完成；总Goal仅在全部适用轮验收或用户明确取消后完成。
2. 无越权/凭据/原件入库、不改他人工作、原CI不退；PR/合并/部署/用户验收分别留痕。BLOCKED随交付提交，无项写无。
每轮报告实际命令、退出码及红→绿证据。同项连续失败3次停止该项继续独立项，如实报告，不因轮数到限宣称总Goal完成。
