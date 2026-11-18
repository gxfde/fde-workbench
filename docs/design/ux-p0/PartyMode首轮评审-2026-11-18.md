# Party Mode 首轮评审记录：交付工作台 UI/UX

- 日期：2026-11-18；状态：讨论中，待蔡工拍板。
- 对象：[体验方案](./EXPERIENCE.md) 与 [视觉规范](./DESIGN.md)；源码基线 `81242018`。
- 方式：产品、UX、架构、QA 模拟专家圆桌；只读源码核查，不代表真人专家签字、GUI 实测或上线验收。

## 优先修订项

| 编号 | 级别 | 核实的问题 | 方案修订与验收 |
|---|---|---|---|
| R01 · UX-04/A05 | P0 阻断 | [交付登记路由](https://github.com/caishide/fde-workbench/blob/812420186853f75ae1c9bfd66479b2a19aeb839f/server/src/fde_api/handover/routes.py#L126) 只传 `package_id`；[服务端登记](https://github.com/caishide/fde-workbench/blob/812420186853f75ae1c9bfd66479b2a19aeb839f/server/src/fde_api/handover/service.py#L577) 检查 `sealed`，不比较用户看过的 `manifest_sha256`。而[解封](https://github.com/caishide/fde-workbench/blob/812420186853f75ae1c9bfd66479b2a19aeb839f/server/src/fde_api/handover/service.py#L556) 后仍可用同一包 ID 重新封存。弹窗只能防误点，不能保证登记的是所见快照。 | 弹窗显示包名、件数、封存时间和摘要，不写不存在的包版本号。按角色与当前快照在服务端同一事务内校验并登记，让登记与解封/重封并发串行化；不扩大权限或改变状态机。A 打开旧确认框，B 解封重封，A 提交必须冲突且无登记事件；两次并发登记最多一条成功审计事件。校验接口的旧客户端兼容方式另定，不把“可省略校验”当成系统级保护已完成。 |
| R02 · UX-03/A03 | P0 阻断 | [提交门禁证据](https://github.com/caishide/fde-workbench/blob/812420186853f75ae1c9bfd66479b2a19aeb839f/server/src/fde_api/projects/gate_service.py#L240) 会把目标状态写成 `claimed` 并替换引用；虽有行锁，未比对用户确认时看到的旧条目。`expected_revision` 是[现有裁定路径](https://github.com/caishide/fde-workbench/blob/812420186853f75ae1c9bfd66479b2a19aeb839f/server/src/fde_api/projects/gate_service.py#L397) 的保护，不能直接认定也覆盖证据替换。 | 目标默认空；替换说明将回到「待核验」。写入在锁内绑定空/旧证据身份、指纹与核验状态等可比较快照；不是再读一次后无条件覆盖。两会话对同一项做替换，旧确认必须被拒，且不写证据行/审计事件；测试空项被抢先填入和同引用但状态改变。保持现有人工核验勾选与判门权限，不把体验分步误写成已有两个独立写端点。 |
| R03 · UX-01/A01 | P0 阻断 | [任务刷新](https://github.com/caishide/fde-workbench/blob/812420186853f75ae1c9bfd66479b2a19aeb839f/desktop/src/renderer/src/projects/TaskEditor.tsx#L109) 只换版本；[任务服务](https://github.com/caishide/fde-workbench/blob/812420186853f75ae1c9bfd66479b2a19aeb839f/server/src/fde_api/projects/task_service.py#L864) 会从 `progress` 推导状态，状态、进度、阻塞原因及开始/结束日期、工期各有联动。逐字段或只传脏字段不能单独保证语义正确。 | 按业务组展示冲突、按编辑意图提交，保留现有字段闸与版本条件；刷新和合并未完成前禁保存。补测 A 改进度/B 标阻塞，A 改工期/B 改计划起始，第三方在合并后再改，以及合并期间权限撤回。验证数据、展示和事件，不只验弹窗。 |
| R04 · UX-02/A02 | P0 保留 | [事实审阅](https://github.com/caishide/fde-workbench/blob/812420186853f75ae1c9bfd66479b2a19aeb839f/desktop/src/renderer/src/discovery/DiscoveryPanel.tsx#L272) 渲染当前筛选，却从[全部已加载事实](https://github.com/caishide/fde-workbench/blob/812420186853f75ae1c9bfd66479b2a19aeb839f/desktop/src/renderer/src/discovery/DiscoveryPanel.tsx#L348) 取批量操作对象。列表是「加载更多」，不是固定分页。 | 文案写「当前筛选 · 已加载 · 已选 N 条」，不写「本页全部」；提交前预览并冻结目标。目标被他人处理或部分失败时就地回显，回读已知结果，重试只对仍符合条件的失败项；补测加载更多、切筛选和提交途中结果变化。服务端复核写是否受版本或待审状态保护，未核实前不做自动合并或自动重试。 |
| R05 · UX-04/A04 | P1 前置快修（建议由 P0 拆出） | [封包读请求](https://github.com/caishide/fde-workbench/blob/812420186853f75ae1c9bfd66479b2a19aeb839f/desktop/src/renderer/src/handover/HandoverPackagesPanel.tsx#L189) 静默吃掉失败，独立于登记动作；把失败显示为空会妨碍排障，但这条证据本身不证明发生不可逆写入。 | 可先做独立前端修复：按列表/类型区分加载、真实空、失败、有旧数据但未更新。候选刷新失败时保留勾选、不要当「已验证可用」；截断结果不能证明选项已失效。若观察到该呈现会诱发替代错选，再升 P0。 |

## 保留主方向，缩小首批范围

- **接单直达先试（UX-05/A06）**：[后端交接](https://github.com/caishide/fde-workbench/blob/812420186853f75ae1c9bfd66479b2a19aeb839f/server/src/fde_api/dispatch/offer_service.py#L568) 在接单事务提交后执行。分别验「接单成功，交接已核实」「已接单，成员交接失败或暂无法核实」「写请求结果未知」；已有项目访问不等同本次成员交接成功，不自动重发接单。
- **优先补导航错配，不先重排全局（UX-06/07/10）**：非管理员可见的 [AI 与扩展](https://github.com/caishide/fde-workbench/blob/812420186853f75ae1c9bfd66479b2a19aeb839f/desktop/src/renderer/src/layout/AppShell.tsx#L82) 与[路由规则](https://github.com/caishide/fde-workbench/blob/812420186853f75ae1c9bfd66479b2a19aeb839f/desktop/src/renderer/src/routing/useHashRoute.ts#L206) 对齐可独立快修；项目分组与登录默认页先用低保真草图走查，保留当前标签、历史别名和原对象链接。更正原稿措辞：指标报表为平台侧角色，试点报告目前仅管理员；不要把两者混写成为负责人原可读，也不能借分组放行。
- **优化反馈，不重建规则（UX-08/09）**：保留异步操作版本续看和看板回读；分别验证「写入成功但下一次读失败」「写入结果未知」「确实写失败」。报价前置由服务端事实或错误码提供，前端不平行计算规则。
- **拆开质量闸和易用性指标（M01）**：A01–A11 走可重复的合成项目负例，涉及并发至少双会话，生产数据不用来复演。首次用 8 名匹配参与者做发现性试点、按角色分别记分母；「7/8」不作为首批发布闸，「下降 25%」是待测目标。不要让查看者执行管理动作来凑分母。样本汇报原始用时、完成/恢复、错路和错误严重度，不作总体推广。
- **视觉规范可沿用**：保留现有全局样式；色彩对比、窄窗和高缩放可见性待真人/桌面验证，不宣称静态文档已通过。

## 待继续讨论

最小实施建议：可独立动前端的任务冲突、批量审阅、封包读反馈和入口错配先切小任务；证据替换、最终交付登记涉及同一确认快照的服务端保护，先补契约与双会话负例再排实施。全局导航改版与默认落点继续作为待验证假设。未据此更新原稿、提交代码或决定发布时间。
