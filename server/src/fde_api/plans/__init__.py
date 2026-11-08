"""delivery_plans 模块：交付方案（V3.1 P0-3）。

任务书 §7：从已批准需求、事实和本体生成可审核 Delivery Plan，映射到
现有 project_tasks（不新建平行任务系统）。

三表（00-gap-register P0-3 裁决 3.3，负结论核验=全仓 grep 零命中）：
- delivery_plans：项目内版本化方案（乐观锁 version；状态机
  draft→approved→published + superseded；新版本=新行，不覆盖已批准历史）；
- delivery_plan_items：条目（类型闭集；requirement_keys 引用**已批准**需求、
  fact_ids 引用已接受事实——方案只能引用已审阅输入）；
- delivery_plan_task_links：条目↔既有 project_tasks 关联（任务以原任务表
  为唯一事实源，links 只存映射；UNIQUE(item,task)=幂等锚）。

生成器为**确定性拼装**（无 AI 调用）：从 discovery 已接受需求/事实与
ontology confirmed 术语拼装条目，走人工审阅——与 T-A5 骨架/compiler
先例同哲学（AI/自动输出先进草稿区）。
"""
