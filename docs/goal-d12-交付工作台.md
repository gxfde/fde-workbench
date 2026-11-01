# goal-d12 · 试点数据回流前的工程收尾（pilot 路由归一化 + 门户历史一览 + 试点 runbook）

依据《交付工作台升级 PRD v1.0 定稿》P4 试点准备收尾 + d11 挂账④销号。**零迁移、零新路由、零服务端代码改动**（head 仍 `c3e7a9b1d5f4` / 22 revision / 96 业务表；路由 269 / ENTRIES 94 不变）。

## 一、差距清单与决议

预检（fork/main `fb5621e` 实测）：试点包四件（T6 / checkpoint 页 / pilot 页 / 插件种子）已全清；试点前置仅剩人工联调检查单执行。承前挂账里**待拍板类全数顺延不碰**（provider kimi 化 / export-sow×signoff / reviewed 翻转 / 撤销声明策略 / T6 阈值定值 / T6-lite 审定 / D10 五项），**数据回流类同样顺延**（一次通过率 retry 折算 / U6 全量成本归集 / std-full 档）。本轮锁定三件纯工程收尾：

| # | 差距 | 根因/依据 | 决议 |
|---|---|---|---|
| 1 | **`authorizedRoute` 漏 `#/pilot` 规则**——d11 新增 pilot 路由时未加：project_lead/viewer/fde_engineer 直输 `#/pilot` 会渲染页面、发起必败请求、吃服务端裸 403 `pilot_report_forbidden`（d11 挂账④的原现象） | metrics 路由在 authorizedRoute 有「平台侧专属否则回落项目列表」归一化（goal-d8），pilot 缺对称规则 | **A：加对称块**（admin 专属，否则回落 `projectsRoute`）——三层对齐：AppShell 导航 isAdmin 门（已有）/ 前端归一化减少暴露面（本轮）/ 服务端 admin-only 最终防线（已有）。挂账④**销号** |
| 2 | **翻译器门户无历史一览**：服务端 `GET /api/v1/translator/translations`（本人最近 20 条 + `adopted_into` 批量反查，goal-d11 已备）前端无消费——提交过的草稿无处回看、无法再采纳到其他项目 | d10 决议①「同一草稿可采多项目=个人资产」隐含回看入口；服务端列表能力闲置 | **B：门户页尾「最近翻译」card**——状态徽标（排队中/翻译中/就绪/失败）+ 原话摘要（40 字截断）+ 「已采纳 N 项目」计数徽标 + ready/failed 行「查看」载入结果卡（可再采纳）；挂载即拉、poll 终态自动刷新、「重新加载」按钮；加载失败静默降级 muted 行不阻塞表单（沿 AdoptionSection 先例） |
| 3 | **试点执行操作面知识散落**：开关族/T6 评审流/采纳流/六指标口径分布在 d9–d11 报告与源码注释里，蔡工试点时需逐处翻找 | P4 试点准备最后一里 | **C：`docs/试点执行手册-runbook.md`**——只收录已实现事实（开关键名逐一对过 `config.py`），待拍板项显式标注，§8 留人工勾选登记 |

## 二、不做边界

- **不碰**：T6 阈值数值（默认 0=关保持）、T6-lite 模板内容、provider、export-sow×signoff、reviewed 翻转、撤销声明策略、D10 五项——全部待蔡工拍板，runbook 只写「待拍板」不预设。
- 不做 pilot 页 403 页面态：归一化后正常路径不再到达 403；PilotReportPage catch 保留服务端中文消息作纵深防御，最小改动。
- 不加 CSS：translator-* 类为语义钩子，历史区复用现有 card/badge/text-button 类。
- 服务端零改动：列表端点与 adopted_into 已备（d11），本轮纯前端消费。

## 三、验证（全部本包实测）

| 项 | 结果 |
|---|---|
| vitest（定向） | navigation + translator-and-metrics **58/58**（含新增 5 例：pilot 归一化 2 + 历史一览 3） |
| vitest（全量串行） | **730/730 全绿**（60 文件 `--no-file-parallelism`；d11 基线 725，本轮 +5） |
| typecheck | `tsc -p tsconfig.node.json && tsc -p tsconfig.web.json` **零错误** |
| 变异闭环 | **5/5 红**（m1 pilot 角色翻转 / m5 pilot 规则删除=原始 bug 形态 / m2 历史 URL 断链 / m3 采纳徽标门控取反 / m4 查看按钮 noop）；红判定解析器先 selftest（7/7 样本）再跑；每步 restore **字节级核对 IDENTICAL**；全部变异 old 串 apply 前断言恰好匹配 1 次 |
| pytest / mypy | 服务端零改动，不适用（CI server-tests 全量兜底） |

**过程如实登记**：变异循环首跑在 Windows 下以 `shell=False` 启动 `npx` 报 `WinError 2`（npx 实为 npx.cmd）——修正为 `npx.cmd` 重跑；首跑崩溃时 m1 变异已 apply 未 restore，残留 `role !== "admin"` 于 useHashRoute.ts，重跑前人工还原并以 grep 复核（m2–m5 未及 apply，无连锁残留）。

## 四、遗留与下轮建议

- 挂账④（pilot 页导航权限细化）本轮**销号**；其余承前挂账原样顺延（全部待拍板或待试点数据）。
- 试点前置项 = 人工联调检查单执行（蔡工）+ §4 T6 阈值拍板（试点数据回流后）。
- 试点数据回流后：O-8/UM-5 阈值人工评审（pilot 六指标 + 本手册 §6 为评审输入）。
