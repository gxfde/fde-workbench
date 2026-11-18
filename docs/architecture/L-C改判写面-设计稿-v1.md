# L-C 改判写面设计稿 v1（条款③后半——已实施）

> **状态**：IMPLEMENTED（2026-11-18 蔡工四项交互拍板全落推荐项——supersede＝查询口径收敛／留痕＝detail_json 追加／不加 operation_event／现在就开 W1+W2；W1 服务端 #517 `53b46889`＋W2 桌面 #518 `2ad37f96` 已合并，+1 路由 523→524 零迁移，r57 便携版）。
> **来源**：goal-l2.0 任务书挂账「条款③ L-C 原文核对视图收口（G7b 挂账『交付原文核对入口』）」——只读面已由收尾轮 #513（`6612691b`，r56）收口；本稿补齐后半「**改判历史 L-C 终裁**」的写面设计。
> **基线现测**：fork/main `19df7d22`（2026-11-18）。
> **冲突裁决**：设计稿 v1.1（AI 原生化学习闭环 2.0）＞本文；本文与实态冲突时以实态为准并回改。

## 一、现状盘点（全部现测，2026-11-18）

### 1.1 已有写面（比登记预期完备）

- **终裁行写面已在**：`POST /simulation/runs/<run_id>/evaluation/human`（`evaluator.record_human_evaluation`）——admin/project_lead 角色闸＋verdict 闭集（pass/conditional/fail/hard_fail/inconclusive）＋total_score 0–1＋**note 必填**；每次调用落一条**新** human 层评估行（`evaluator_id=human:<user_id>`、`decided_by_user_id` 留痕），机器原行并列不覆盖。**服务端不存在「已终裁不可再终裁」的状态闸**——重复插行＝再终裁的底层能力天然在场。
- **最新行收敛口径已在**：`analyze_run` 的 L-C 腿与 `get_evaluation_report` 的 final 均按 `created_at DESC` 取最新 human 行——再终裁后，三源归因与终裁显示自动收敛到新行。
- **只读核对视图已收口**（#513）：发现卡证据条原文展开＋L-C 人工评估行 note 原文＋交付物原文展开，运行详情页三要素并排。

### 1.2 真缺口（按危害排序）

| # | 缺口 | 危害 |
|---|---|---|
| ① | **supersede 联动缺失**：再终裁后，**旧** human 行派生的 findings（confirmed 置信）仍保持 open 且可被 `draft-ai` 选中建提案——旧裁决可「借尸还魂」，与新裁决并行误导蒸馏 | P0 |
| ② | **finding 状态迁移写面缺失**：`SimulationFinding.status ∈ (open, confirmed, rejected)` 但创建后**无任何迁移端点**（全行恒 open）；「确认」语义实际活在 `root_causes.confidence`（L-C 派生=confirmed／L-B=likely）。L-B likely 发现无法被单点人工确认/驳回（唯一粗路径＝插 human 行重跑 analyze） | P1 |
| ③ | **终裁历史链读面缺失**：评估报告并列渲染全部 human 行，但无「第 N 次终裁」序标与前后分数对照；改判发生时表单旁无上次结论摘要，蔡工无从感知「这是第几次改判、改了什么」 | P2 |
| ④ | **finding 行状态字段语义空转**：桌面徽标逻辑只读 `root_causes.confidence`，`status` 字段不参与任何判定与显示 | P2（随②一并解决） |

### 1.3 设计边界（继承，不重开）

- **评估行不可变纪律不破**：human 层评估行创建后零改写（改判＝追加新行，历史行原样保留——审计链天然完整：`decided_by_user_id`＋`created_at`＋note 全在行内）。
- **AI 不代拍板**：改判恒人工提交；服务端只提供写面与收敛口径。
- **平台级生效沿 §6-6**：本设计不引入 org 维度（登记于 AI 原生化学习闭环 2.0 任务书挂账，另线再议）。
- **不追溯撤销既有提案**：改判前已创建/已审批/已发布的提案不受影响（提案指纹独立防重）；改判后新发现另起提案（`payload_sha256` 指纹防同载荷重复）。

## 二、设计

### 2.1 P0：supersede 查询口径收敛（不写旧行）

**裁法**：不改写旧 findings 行（避免与行内容不可变精神打架、零迁移），把「哪些 findings 有效」收敛为**查询口径**——单一真身函数：

```python
# simulation/improvement_service.py
def effective_findings(session, *, run_id: str) -> list[SimulationFinding]:
    """有效发现＝最新 human 行派生的发现 ∪ 非 human 层全部发现。

    再终裁（新增 human 行）后，旧 human 行派生的 confirmed 发现自动失効——
    查询口径收敛，零写面零迁移；旧行原样留痕（审计链不断）。
    """
```

- **消费点三处接线**：①`draft-ai` 的输入投影（finding_ids 过滤——改判后旧 confirmed 发现不再进蒸馏面）；②`create_proposal` 的 finding 引用校验（409 `finding_superseded`——引用旧 human 行派生发现建提案被拒）；③桌面 `list_findings` 投影（新增 `superseded: bool` 字段，卡片置灰＋「已被第 N 次终裁取代」提示）。
- **判定规则**：取该 run 最新 human 行 `H*`（created_at DESC, id DESC）；finding `owner_evaluation_id == H*.id` ⇒ 有效；owner 为其他 human 行 ⇒ superseded；owner 为 deterministic/model 行 ⇒ 恒有效。
- **过拟合闸/回归不受影响**（回归按 run 评分，不读 findings）。

### 2.2 P1：finding 状态迁移端点（轻量）

```
POST /simulation/findings/<finding_id>/adjudicate   # 不进 api_catalog
{action: "confirm" | "reject", note: str}           # note 必填（人工动作必须留理由）
```

- 角色闸＝终裁同尺（admin/project_lead）；状态机：`open → confirmed | rejected`（单向，**不可回迁**——改判靠再终裁收敛口径，不靠状态回翻）；幂等：同状态重复提交 409 `finding_already_adjudicated`。
- 留痕：`detail_json.adjudications[]` 追加 `{action, by_user_id, at, note}`（detail_json 为自由 JSON 追加域，不破行结构；finding 行非不可变行——status 本就是生命周期字段）。
- 与 confidence 的关系：**status 是人工裁定面，root_causes.confidence 是归因快照**——两者并存；桌面徽标以 status 优先（confirmed/rejected 徽标覆盖 confidence 推断）。
- L-B likely 发现由此获得单点人工确认路径（confirmed ⇒ 可建正式提案），不再依赖「插 human 行重跑 analyze」粗路径；L-A/L-C 发现亦可被人工驳回（reject ⇒ 从 draft-ai 有效集剔除，与 2.1 收敛口径并集生效）。

### 2.3 P2：终裁历史链读面（桌面）

- LayerCard 对 human 行加序标「第 N 次终裁」（按该 run human 行 created_at 升序）；最新行加「现行终裁」徽标。
- 再终裁提交时，表单旁就地显示**上次结论摘要**（verdict/分/note 前 80 字＋时刻）——防「不知道自己在改什么」误操作（G7b 追加轮「提交回执就地呈现」同款教训）。
- 不加 operation_event：human 行本身即完整审计链（行不可变＋decided_by＋note）；事件冗余登记取舍＝不加（留痕可推翻：若后续审计面需要统一事件流，再议补挂）。

### 2.4 桌面入口

- 终裁表单**常显**（现按角色渲染已满足——`onRecordHuman` 传入即渲染；仅需确认 SimulationRunDetail 对 admin/lead 无条件传参，人类复核必过后表单仍在＝再终裁入口天然在场，补一行测试钉防未来误加状态闸）。
- FailureAnalysis 卡片：superseded 置灰＋提示；adjudicate 按钮（confirm/reject，admin/lead 可见）＋状态徽标（confirmed/rejected/open）。

## 三、测试与判据

- supersede 钉：再终裁后旧 human 行派生 confirmed 发现 ①不进 draft-ai 投影 ②create_proposal 409 ③list_findings 投影 superseded=true；变异：收敛口径删 latest 过滤 ⇒ 三钉全红。
- adjudicate 钉：confirm/reject 单向迁移＋幂等 409＋note 必填＋角色 403＋detail_json 追加留痕。
- 桌面：序标/徽标/按钮/superseded 置灰（vitest）。
- 既有套件零回归：analyze_run 幂等（U3）／三源分流（U1/U2）／draft-ai 键集钉不受投影影响。

## 四、体量与拆轮

| 轮 | 内容 | 形态 |
|---|---|---|
| W1 | 服务端：effective_findings 单一真身＋三消费点接线＋adjudicate 端点＋钉＋变异 | 一个 PR（零迁移零路由表增量：adjudicate 为新路由不进 api_catalog） |
| W2 | 桌面：序标/徽标/按钮/superseded 置灰＋vitest＋r57 便携版 | 一个 PR |

## 五、待拍板清单（带推荐项）

1. **supersede 机制**：查询口径收敛（推荐——零写面零迁移，行不可变精神一致）／旧 finding 行置 rejected（写面迁移）。
2. **adjudicate 留痕形态**：detail_json 追加（推荐——轻量，行数预算闸友好）／独立 `finding_adjudications` 表（查询强但+1 表）。
3. **改判不加 operation_event**（推荐：行即留痕）／补挂事件（统一事件流）。
4. **实施时点**：并入下一个被点名的桌面轮（推荐——与任务书挂账 owner 口径一致）／独立点名服务端轮先行。

## 六、明确不做

- 不改评估行不可变纪律；不加 run 状态闸（已终裁可再终裁＝改判本义）；不追溯撤销既有提案；不引入 org 维度；不把 adjudicate 进 api_catalog（治理面非通用动作面）。
