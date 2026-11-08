# 商业化阶段状态

- 基线 SHA：`eee317c`（fork/main，PR #214 合并态；任务书自述基线 `858e090` 已被其后 8 个合并超越，本轮以现测为准）
- 当前分支：`feat/commercial-g0-audit`（工作树 `D:\test\fde-wt-g1`）
- 当前阶段：**G0 基线审计 + 四个歧义 ADR + 智能化现状实测**
- 状态：**completed**（本轮交付后；业务代码零改动）
- 开始/完成时间：2026-11-08 16:35 开工 / 2026-11-08 同日收口（以 PR 合并时间为准）

## 本阶段目标

按任务书 §14 总提示词第 3 条：「第一个 Goal 只做 G0 基线审计 + 四个歧义 ADR，不改业务代码。」覆盖任务书 §2 G0 必做项 1–8。

## 真实代码定位

见 `00-baseline-audit.md` §B–§F（逐行锚点实测）。要点：任务书 §2 表格全部属实；权益四字段全库零命中；派单/席位/结算/降级链结构完备但活库零使用。

## 设计决策及理由（含 ADR 编号）

- **ADR-001**（`decisions/ADR-001-role-vs-delivery-level.md`）：角色分层与交付能力等级正交；`fde_profiles.level` 零改动保护；R1–R4 不落 L 编号；含 level 依赖全集与测试影响面。
- **ADR-002**（`decisions/ADR-002-entitlement-model.md`）：四权益独立建模方向；不覆盖 `fde_profiles.status`；`certification_status` 与 `fde_level_evidence` 并存。
- **ADR-003**（`decisions/ADR-003-revenue-ledger-vs-dispatch-settlement.md`）：收入科目层独立于 `delivery_settlements`；份额算法复用 `seat_shares_for`；比例不落数。
- **ADR-006**（`decisions/ADR-006-naming-convention-r1r4.md`）：R1–R4 命名规范；六套「level 同名家族」区分；凡引用 L 编号必须写三要素。
- ADR-004 / ADR-005 / ADR-007 分别归 G2 / G5 / G1 设计轮成文（不预支）。

## 修改文件

全部为新增文档（零业务代码、零迁移、零路由）：

```text
docs/commercialization/
  00-baseline-audit.md      （基线审计：§B 逐项核验、口径七项现测、活库智能化实测）
  00-gap-register.md        （15 条缺口登记 + Goal 矩阵）
  phase-status.md           （本文件）
  decisions/
    ADR-001-role-vs-delivery-level.md
    ADR-002-entitlement-model.md
    ADR-003-revenue-ledger-vs-dispatch-settlement.md
    ADR-006-naming-convention-r1r4.md
```

## 数据库迁移

零迁移（基线维持 49 rev，head `d5a8c2f4b7e1`）。

## API / 权限 / API Catalog

零改动（路由 384、api_catalog ENTRIES 94 不变）。

## 前端变化

无（桌面便携版重打包挂账不适用于本轮）。

## 测试命令与结果

- 本轮纯文档，未跑新测试；基线口径引用 CI main run **42461768715**（#214，2026-11-08）job log 实测：
  - server-tests：**2333 passed + 6 skipped**（11m28s，job 128672384334）
  - desktop：**951 passed / 81 文件**（vitest，job 128672384201）
  - secrets-scan / pseudonymization 均绿。
- mypy 基线 279 行未动（`wc -l server/mypy-baseline.txt` 现测）。

## 安全检查

- 活库查询全部只读 SELECT（经 api 容器应用自身配置连接），零写入、零生产变更。
- 未读取无关密钥；`server/.env` 未打开；客户资料零触碰。
- 遵守红线：本审计不含任何客户真实姓名/扫描件/凭证。

## 数据兼容与回滚

- 无 schema/数据变更，无需回滚方案；文档可随时 revert。

## 验收证据

- 任务书 §2 G0 必做项 1–8 对照：1=§A、2=§B、3=§C/§D、4=§E.1、5=§E.3、6=§G、7=§H、8=两份 00- 文档已产出。
- 智能化评级判定：实测样本=0 ⇒ 维持书面口径 **L2+（交付智能化等级：平台，越大越自动化）**，不因口述升格（§0.5 硬约束）；G1–G6 关键流转按「默认人工确认」实现。
- 四个歧义裁决全部落盘且与任务书 §0 的裁决要求逐条对照（见各 ADR 尾节）。

## 遗留问题

1. ADR-004/005/007 待 G2/G5/G1 成文。
2. GAP-15（AI 草稿采纳率埋点）待 G2 一并落。
3. 任务书 §17 外部输入 8 项维持待外部状态（法务意见、数值类、v4.0 原件核验等）。
4. 任务书基线 SHA（858e090）与当前权威基线（eee317c）的漂移已在本文档头部说明，后续 Goal 以「开工前现测」纪律处置。

## 是否允许进入下一阶段

**允许进入 G1（权益四分与角色分层，T-04/T-05）**——前置：G0 交付物合并后，按 ADR-001/002/006 的裁决边界实施；G1 开工轮仍须重新 fetch fork/main 对齐迁移 head。
