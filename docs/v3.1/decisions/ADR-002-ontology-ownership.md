# ADR-002：control/ontology.py 与 ontology/ 的职责划分（本体所有权）

- 状态：Accepted（2026-11-08，V3.1 P0-2 前置文档，任务书 §6 核验点 7）
- 裁决人：按任务书 §15 委托先例按推荐项执行、留痕可推翻
- 基线：fork/main `92ca0bd`（P0-1 合并后）

## 背景

仓库存在两处「本体」：

1. `server/src/fde_api/control/ontology.py`（75 行）——静态 `ONTOLOGY` 字典
   （版本 `fde-business-ontology-2`：21 实体/24 关系/9 不变量的**语义描述**），
   唯一消费方是 MCP 工具 `ontology_read`（`control/mcp_gateway.py` 原样返回）
   与一个测试。V3 T-O1（2026-11-03）引入一等治理层时已在文件头 docstring
   声明「只读语义投影，治理已迁一等表，MCP 契约不变」。
2. `server/src/fde_api/ontology/`——治理层四表（terms/aliases/relation_types/
   change_sets）+ 服务原语 + REST 路由 + 影响分析（`impact_of_term`）。

P0-0 审计（`docs/v3.1/00-baseline-audit.md` §8）实测：**两者零代码级重叠**
（无共享符号、无导入关系），重叠纯概念性。

## 决策

1. **职责声明**：
   - `control/ontology.py` = **AI 阅读用的语义快照**（提示词上下文层面的
     「本系统有哪些业务概念」），不是数据权威、不参与任何写路径。
   - `ontology/` = **唯一治理权威**（术语/别名/关系类型/变更集的状态机、
     唯一性约束、物化事务、影响分析全在此）。
2. **不删旧模块**：MCP `ontology_read` 契约冻结原样返回；删除会破坏既有
   AI 工具面与消费方预期，且无收益。
3. **防漂移边界**：
   - `control/ontology.py` 只允许维护者手工修订其**描述文本**；禁止从
     `ontology/` 表自动生成（描述是设计意图，表是运行事实，二者允许暂时
     不一致——不一致不构成 bug）。
   - 禁止任何新代码 import `control.ontology.ONTOLOGY` 参与业务判定
     （现有唯一消费方 `mcp_gateway` 除外）。
   - 语义快照的大版本演进（新增实体/关系）须同步 ADR 或本文件补记。
4. **稳定 ID 引用合同**（P0-2 起）：业务表对本体概念的**写面关联**逐步走
   `term_id`（试点实体：`project_research_subjects.term_id`，可空 FK，
   合并/停用不改写历史行）；**读面/影响分析**仍以名字域
   （UNIQUE(project,term) ∪ UNIQUE(project,alias) + canonical 链）为权威
   ——`impact_of_term` 的「名字域纽带」合同不变（`ontology/service.py:36`
   注记正式由此 ADR 收编）。

## 后果

- 新增 AI 候选通道（discovery→change-set）只落 `ontology/`，与
  `control/ontology.py` 无交集。
- `project_research_subjects` 新增可空 `term_id` 列（additive 迁移）；
  旧行不回填、读路径零变化——术语落定（change-set confirm 物化 create_term
  与 create_term 直落 confirmed）时对同名 subject 自动链接（一次性 UPDATE，
  不改写已链接行）。
- 跨项目别名冲突按 D-1 拍板建议实现为**只读告警**（create_term 与候选
  生成响应附 `cross_project_conflicts` 字段），不动项目内唯一约束。
