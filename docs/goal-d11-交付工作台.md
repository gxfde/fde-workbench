# goal-d11 · 交付工作台升级轮次报告（2026-11-01）

## 〇、只读预检

- fork/main = `10ed338`（goal-d10 squash 合并点），无新提交；并发会话主树 6 M + ?? 痕迹原样未碰。
- 隔离 worktree：`D:\test\fde-workbench-d11`（feat/goal-d11 @ 10ed338，unset-upstream，junction 双挂载，双 .env 已拷）。
- 待拍板三项（provider kimi 化 / export-sow×signoff / reviewed 翻转）**本轮零触碰**——不发明拍板结果。

## 一、能力项差距（P4 试点包 + 承前挂账清尾）

| # | 差距 | 现状 | 验收判据 |
|---|---|---|---|
| A | **T6 高成本 run 前评审**（总纲 §2.2 T6：「`max_cost_units` 超阈值档的 run 先评审性价比（可按项目关闭）」；d7 挂账） | T1/T2/T4/T5 状态机强制已落，T6 全缺 | start_run 前置闸：全局阈值（settings 可配置，0=关闭）+ 拟用 agent 成本档命中 + 项目未关闭 → 无已封存 T6 纪要侧链该项目则 409 `t6_gate_open`；项目级关闭开关 `projects.t6_review_disabled`（迁移加列）；T6-lite 模板注册；闸三态+边界（`max_cost_units=0`=不限额视为最高档必触发）钉住 |
| B | **pilot-report 桌面页**（d6 挂账④：当前 API JSON） | `GET /agents/pilot-report` 六指标已全（仅 admin）；桌面零渲染 | `#/pilot` PilotReportPage：试点窗口/额度状态卡 + 六指标卡（值如实渲染，None=「数据未积累」不编造——沿 MetricsReportPage 心智）；导航入口 admin 可见 |
| C | **插件能力登记表种子**（d6 挂账⑥：lcsc.browse 等插件 capability 的 PluginPackage 种子数据） | plugin_packages 表在，种子零 | `seeds/plugin_packages.json` + 懒装载幂等加载（沿 agents/seeds 模式）；已知插件（Jev 立创查询等）capabilities 从 manifest_json 读；测试钉装载幂等与能力清单 |
| D | **门户采纳状态透出**（d10 挂账 #1） | 采纳后 `#/translator` 列表无任何标注，靠 guidance 侧 translation_id 反查 | 翻译列表/详情 serialize +`adopted_into`（项目 id/分析 id 对）；门户卡「已采纳 N 项目」徽标；测试钉 |
| E | **轻文案两件**（d10 挂账 #3 #4） | 纪要证据形态无桌面提示；guidance_source_missing 落通用错误 | CapabilityProfilesPage 晋级表单 +workbench-minutes 形态提示；GuidanceReview 错误映射 +guidance_source_missing 中文文案 |

**销号登记（零代码）**：d7 挂账「checkpoint 人工拍板桌面页」——goal-d9 已落 SignoffConsole（终审台三区合并视图挂方案详情页，d9 报告 §一），本轮在台账正式销号。

### 不做边界

- 待拍板三项零触碰（provider kimi 化 / export-sow×signoff 强制关系 / artifacts reviewed 翻转）。
- T6 不做 std/full 档模板（承前挂账「std-full 档独立门模板」仍等试点升级）。
- pilot-report 不做 O-8/UM-5 阈值自动判定（D15：只出数，阈值人工评）。

## 二、设计决议

1. **T6 成本档判据**：`agent.max_cost_units == 0 or agent.max_cost_units > settings.t6_review_cost_threshold`——`max_cost_units=0` 在 adapter 语义中是「单 run 不限额」（adapter.py「0 = 单 run 不限额」），即最高成本档，**必须触发**；阈值 0 = 全局关闭（试点期默认关，蔡工配置开启）。总纲原文「超阈值档」的两种读法（run 实际成本不可预知）取 agent 配置档解读——启动前唯一可判定的事实是拟用 agent 的授权成本档。
2. **项目级关闭承载**：`projects.t6_review_disabled` Boolean 列（迁移，零新表）——总纲原文「可按项目关闭」的忠实落地；经项目 PATCH（_normalize_update_input 扩布尔字段）由项目负责人/admin 设置。
3. **T6 纪要侧链按项目**：`t6_gate_satisfied` 模式同 T1（trigger=mandatory + template.gate=="T6" + topic_refs.project_id 侧链 + auto 纪要排除）——T6 评审的是「项目内高成本 run 的性价比」，同项目评审一次即放行后续 run（review 对象是性价比结论，非单次 run）。
4. **闸序**：start_run 现有闸链（agent_assisted_required → t1_gate_open）之后追加 t6_gate_open——T6 是成本维度的前置评审，先过协同声明与计划评审再谈性价比。
5. **插件种子**：`seeds/plugin_packages.json` + control 侧懒装载幂等加载（`ensure_plugin_seeds`，沿 agents/seeds.py 的「存在即跳过」模式）；种子含 manifest_json.capabilities（`_plugin_capabilities` 消费格式）；package_sha256 对种子内容计算（登记完整性）。

## 三、验证判据

| 判据 | 门 |
|---|---|
| T6 闸：触发/已评审放行/项目关闭放行/全局关闭零触发/0 档必触发 | pytest 定向 |
| T6-lite 模板注册 + t6_gate_satisfied 侧链/auto 排除 | pytest 定向 |
| pilot-report 桌面页渲染（状态卡/六指标/None 灰态）+ 路由 | vitest 定向 |
| 插件种子装载幂等 + capabilities 非空 | pytest 定向 |
| adopted_into 透出 + 门户徽标 | pytest + vitest |
| pytest 全量 / vitest 串行全量 / ruff / mypy 基线无新增 / 迁移双跑 | 全量门 |
| 变异 ≥8×8 红绿（统一循环，共用快照字节级核对） | 变异门 |

**反假绿灯四条**：变异不红先怀疑测试空洞（红判定解析器先自检）；mock 按解包后载荷喂；全量串行口径；容器验证核对镜像时间戳。

## 三·五、实施变更清单（实测）

- **迁移 1**：`c3e7a9b1d5f4`（22 revision，down_revision=a1d3f5b7c9e2）——projects.t6_review_disabled Boolean NOT NULL server_default false。97 张表不变（零新表）。
- **服务端**：config.py +`t6_review_cost_threshold`（0=全局关，试点默认）；meetings/templates.py +`T6-lite`（gate="T6"、mandatory、守卫+模块智能体+finance persona）；meetings/service.py +`t6_gate_satisfied`（mandatory+gate=="T6"+topic_refs.project_id 侧链+auto 排除，模式同 T1）；agents/service.py start_run 闸链追加 t6_gate_open（协同声明→T1→**T6**，判据=max_cost_units==0 或 >阈值，项目开关可关闭，409 detail 携 gate/agent_max_cost_units/threshold）；workbench/models.py Project +t6_review_disabled；projects routes/service PATCH 白名单+布尔严格校验（非布尔 400）+DTO 透出；control/plugin_seeds.py 新模块（ensure_plugin_seeds 懒装载幂等）+seeds/plugin_packages.json（lcsc-browser-baseline/jev 两插件，capabilities=["lcsc.browse"]）；translator/service.py +adopted_into 透出（批量反查 ProjectGuidanceAnalysis.translation_id，详情与列表都带）。
- **桌面**：PilotReportPage.tsx 新页（试点状态卡+六指标卡，None=「数据未积累」灰态，滞留 run 计数）+ #/pilot 路由 + admin 导航「试点报告」；TranslatorPortalPage +adopted_into 徽标（已采纳→项目链接）；CapabilityProfilesPage +workbench-minutes 证据形态提示（M10 桌面透出）。
- **销号**：d6 挂账③「checkpoint 人工拍板 UI」=d9 SignoffConsole 已落（台账正式销号）；d6 挂账④「pilot-report 桌面页」本轮落；d6 挂账⑥「插件能力登记种子」本轮落；d10 挂账 #1/#3/#4 本轮落/透出验证。
- 行为变更：start_run 新增 T6 闸（**默认阈值 0=全局关——v0.2.0 行为零回归**，蔡工配置开启）；项目 DTO +t6_review_disabled 键；翻译序列化 +adopted_into 键；extensions_center 首次进入多一次种子装载（幂等）。既有测试零适配。

## 三·六、验证（全部本包实测）

| 项 | 结果 |
|---|---|
| pytest | **1698 收集 = 1692 passed / 6 skipped / 0 failed**（d10 基线 1684 收集；+14=T6 11+种子 2+adopted 1；全量两轮） |
| vitest / typecheck | **725/725 全绿**（60 文件串行；+3=pilot 2+adopted 徽标 1）；typecheck 零错误 |
| ruff / mypy | CI 口径 All checks passed；基线门 OK（baseline 289 / current 279 无新增） |
| 迁移 | head `c3e7a9b1d5f4` 真库 down→up→down→up 双跑干净 |
| 变异闭环 | **11×11 红绿**（阈值方向/0 档触发/项目开关/闸失效/侧链方向/跨项目/auto 排除/种子幂等/adopted 断链/状态卡文案/徽标门控）；红判定解析器先自检再跑（d10 教训）；**2 处变异锚定修正 + 1 处测试空洞加固（跨项目负向用例）如实登记**；每步 restore 字节级 IDENTICAL |

## 四、遗留与下轮建议

### 挂账（新登记，台账节三十六）

| # | 事项 | 时点 |
|---|---|---|
| 1 | T6 阈值定值与开启（`t6_review_cost_threshold` 当前 0=关；单位/档位数值待试点数据回流后蔡工拍板） | 试点后 |
| 2 | T6-lite 模板内容审定（PM-1 蒸馏源标注——D10 五项「模板内容审定」同族顺延） | 待蔡工审定 |
| 3 | std/full 档独立门模板（承前，T6 当前仅 lite 档） | 试点升级后 |
| 4 | pilot-report 页与 metrics 页的导航分组/权限细化（当前 pilot 仅 admin 导航可见，project_lead 可直输 #/pilot 但服务端 403） | 低优 |

### 下轮建议（goal-d12）

- **试点包收尾核对**：T6 + checkpoint 桌面页（SignoffConsole 已落）+ pilot-report 桌面页 + 插件种子——四件至此全清；试点前置项仅剩人工联调检查单执行（蔡工）与 D10 待拍板项。
- **待拍板顺延**：provider kimi 化 / export-sow×signoff / reviewed 翻转 / T6 阈值定值 / D10 五项。
- 试点数据回流后：O-8/UM-5 阈值人工评审（pilot-report 六指标即评审输入）。
