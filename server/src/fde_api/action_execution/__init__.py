"""action_execution 域（AE1 · D1 裁决落位 Workbench worker，与 ``data_engineering``
平级；52 号 §2 D1 拍板落痕）。

WP1（docs/ai-fde/53 §3）：单步 T4 执行链 ``ActionExecutor``——「幂等门 →
白名单门 → 审批闸 → 干跑/真执行 → 审计 → 结果」，形态以契约
``docs/ai-fde/_ae-execution-contract-v1.json`` v1.0.6（FROZEN-v1）为唯一真身。

模块分工：``schemas``（三形态校验/构造，第 1/5 层）｜ ``executor``（五层编排
纯核心 + ``ActionExecutor``）｜ ``service``（真门装配 + 落库）｜ ``routes``
（POST 提交 / GET 详情）｜ ``models``（``action_executions`` append-only 执行
记录）。表达式语义与连接器只读沙箱真身均在 ontology-service，workbench 侧
不得复刻（D1 落痕实施约束）；白名单加载器与连接器适配已落（WP3），本域 WP1
默认 fail-closed。
"""
