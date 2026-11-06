# UI/UX 美化方案 · 实施记录（B / S0 / S1）

| 项 | 值 |
| --- | --- |
| 状态 | **已实施，验收中**（B0 / B1 / B1a / S0 / 静态守卫 / S1 代码改动完成） |
| 对应方案 | `docs/UI-UX美化方案-v2.md`（APPROVED · 已定稿，位于 C 盘文档工作树） |
| 真源 | `docs/tokens.json`（C 盘文档工作树与 D 盘实施基线内容一致） |
| 实施基线 | `D:\test\fde-workbench`（黑金 `:root`，2026-11-06 交互式选择卡拍板） |
| 实施日期 | 2026-11-06 |
| 实施范围 | **B + S0 + S1**（用户拍板）；S2 / S3 继续单独排期 |
| 交付状态 | 未提交、未 push、未打包发行 |

> 本文件是 `tokens.json` 中 `decisions.D4.trace` 与 `status` 字段指向的留痕目标，用来记录「定稿口径 → 实施口径」的差异与全部落地项。**方案 v2 正文保持定稿状态不回改**；所有实施偏差只在本文件与 `tokens.json.decisions` 中留痕。

---

## 1. 实施前的事实核对与两处拍板

### 1.1 基线差异

| 事实 | 结论 |
| --- | --- |
| C 盘 `desktop/src/renderer/src/styles.css:3,22-29` 仍是蓝绿 `#5FD68B / #2BB7B0 / #3A7BFD` | 文档工作树是旧快照，**不作为实施基线** |
| D 盘 `styles.css:3,26-52` 已是黑金 `--brand-ink #14181C` / `--gold-5 #A3721F` | 拍板为唯一实施基线 |
| D 盘 2026-11-06 00:53 另一轮改动已把主按钮文字由白色改为石墨黑 | 定稿方案的「白字」前提失效，见 D4 |
| D 盘 `git status --short` 有大量并行未提交改动（含 `shared/brand.ts` 重命名、`ResearchImportDialog.tsx` 删除、`server/**` 等） | 本轮只做增量编辑；不 stage、不 commit、不 revert、不碰无关文件 |
| D 盘原本不存在 `docs/tokens.json` 与 `design-tokens.test.ts` | 由本轮镜像 / 新建 |

### 1.2 两次交互式拍板

| 编号 | 问题 | 拍板结果 |
| --- | --- | --- |
| D4 | 方案 v2 指定主按钮文字 `#A3721F`，但 D 盘基线已用石墨黑 `#14181C`（17.84:1，远优于 4.21:1） | **保留石墨黑文字**，同时落实「渐变降级为非交互展示面」+「白底 + 金描边」；`#A3721F` 由文字色退为描边 / hover 激活色 |
| 范围 | 方案含 B / S0 / S1 / S2 / S3 | 本轮只做 **B + S0 + S1**；S2（组件化、导航分组、`window.confirm` 归一、ToastHost）与 S3（8 个 CSS 全量治理、规范文档、深色模式）单独排期 |

---

## 2. B0 · 真源与治理字段

- `docs/tokens.json`（C / D 两盘内容一致）
  - `status` → `IMPLEMENTING · 已定稿并进入实施（B/S0/S1，见 docs/UI-UX实施记录-B-S0-S1.md）`
  - 新增 `decisions.D4`，并把 D1 标为 `supersededBy: D4`（历史结论不删）
  - `color.button.primary.text.value`：`#A3721F` → `#14181C`，`css` → `桌面端 var(--brand-ink) / 官网 var(--ink)`
  - `acceptance.criterion` → `≥4.5:1（WCAG AA 正文；D4 实施口径）`；`knownDebt` → `无`
  - `status.info.border` 按 D 盘基线校准 `#B6BEC9` → `#C4CBD3`
  - `onDark*` 的 `css` 字段由「待建」改为已落地变量
  - `governance.guard` 更新为已新增 `design-tokens.test.ts`；`governance.executionBaseline.implementedOn` 写入实施日期
  - 新增 `trace`：指向本文件

---

## 3. B1 / B1a · 主按钮族基础一致性

### 3.1 落地内容

| 文件 | 改动 |
| --- | --- |
| `desktop/src/renderer/src/styles.css` | `.primary-button` 默认态改 `background: var(--surface)` + `border: 1px solid var(--gold-5)` + `color: var(--brand-ink)`；hover 保持白底，用同色 1px 外圈与阴影承担反馈；`--brand-gradient` 加注释限定为**非交互展示面** |
| `site/index.html` | `.btn-gold` 改 `background: var(--card)` + `border-color: var(--gold-deep)` + `color: var(--ink)`；`.btn-gold:hover` 不再铺深金底，改白底 + 同色描边 + `box-shadow: 0 0 0 1px var(--gold-deep)` |
| `desktop/src/renderer/src/styles.css` | `.nav-item.active`、`.template-editor-tabs button.active`、`.detail-tabs a.active` 去渐变，交互控件不再铺品牌渐变 |

```css
/* styles.css —— B1 / B1a 后的主按钮 */
.primary-button {
  border: 1px solid var(--gold-5);        /* #A3721F */
  background: var(--surface);
  color: var(--brand-ink);                /* #14181C */
  box-shadow: var(--shadow-brand);
}
.primary-button:hover:not(:disabled) {
  background: var(--surface);
  border-color: var(--gold-5);
  box-shadow: 0 0 0 1px var(--gold-5), 0 10px 26px rgba(201, 143, 43, 0.40);
}
```

### 3.2 B1a 描边上移（验收口径驱动的修正）

定稿方案用 `#C98F2B` 作金描边，但按 WCAG 相对亮度公式复算：

| 色对 | 实算对比度 | 判据 | 结果 |
| --- | --- | --- | --- |
| `#C98F2B` on `#FFFFFF` | 2.82:1 | UI 控件 ≥3:1 | **不达标** |
| 白字 on `#C98F2B` | 2.82:1 | 正文 ≥4.5:1 | 不达标（原方案问题） |
| 白字 on `#E8A33D` | 2.16:1 | 正文 ≥4.5:1 | 不达标（品牌指南自述与实算不一致） |
| `#A3721F` on `#FFFFFF` | 4.21:1 | UI 控件 ≥3:1 | 达标 |
| `#14181C` on `#FFFFFF` | 17.84:1 | 正文 ≥4.5:1 | 达标 |

→ 描边整体上移一阶到 `#A3721F`（桌面 `var(--gold-5)` / 官网 `var(--gold-deep)`）；`tokens.json` 的 `color.border.buttonPrimary`、`color.button.primary.border`、`borderHover` 与 `D4.borderAdjustment` 同步。hover 反馈改用「同色 1px 外圈 + 阴影」，避免再次引入低对比色对。

---

## 4. S0 · 纯 CSS 阻断项

| 类别 | 改动 |
| --- | --- |
| 语义深墨色 | 新增 `--success-ink #0B6E3D`、`--warning-ink #8A3F06`、`--danger-ink #96261A`、`--info-ink #2B3340`；语义小字（提示、徽标、错误文案）由浅色改为对应 `*-ink` |
| 深底文字 | 新增 `--on-dark-primary #FFFFFF`、`--on-dark-secondary #C4CBD3`、`--on-dark-muted #B9C2CB`、`--on-dark-disabled #8A929E`；侧栏游离硬编码灰蓝统一收敛 |
| 重复 / 未定义令牌 | `--blue-pale-border`、`--radius-lg` 别名化；从未定义的 `var(--primary)` 真实引用改为 `var(--blue-ink)`；`--brand-gradient` 标注为非交互展示面 |
| 全局焦点 | 统一 `button/a/input/select/textarea:focus-visible` → `outline: 2px solid var(--brand-gold-bright)` + `outline-offset: 2px`，各局部覆写对齐 |
| 小字 | `.app-version` 由 11px 提到 `var(--font-caption)` |
| 禁用态 | disabled 按钮族统一 `opacity: var(--opacity-disabled)`（`0.55`） |
| 语义反转 | 新增 `.notice.warning`（warning 边框 / 底色 / 深墨文字），供「方案已弃用」等警示使用 |

---

## 5. 静态守卫

新增 `desktop/tests/main/design-tokens.test.ts`，仿 `brand-hardcode.test.ts` 的静态文本闸思路：不启动 Electron、不渲染 React、不改写既有用例。10 个用例覆盖：

1. `tokens.json` ↔ `:root` 核心色值一致；
2. 不存在 `var(--primary)` 真实引用；
3. 深底文字令牌与 `*-ink` 令牌已建立；
4. 桌面 `.primary-button` 默认态 / hover 态；
5. 官网 `.btn-gold` 默认态 / hover 态；
6. `--brand-gradient` 不出现在交互控件；
7. 展示面仍保留渐变；
8. 全局焦点统一；
9. 语义色小字使用 `*-ink`；
10. `window.confirm/alert` 数量 ≤ 16（S2 归一的收敛上限）。

首次运行 9/10：断言 `expect(styles).not.toMatch(/var\(--primary\)/)` 命中了 S0 自己写的说明注释。修复方式是守卫内新增 `stripComments(source)`，`rootDeclarations()` 与断言都基于去注释文本；注释文案同步改为不含 `var(--primary)` 字面量。复跑 10/10。

---

## 6. S1 · 操作闭环与弹窗可访问性

### 6.1 三个新增基座

| 文件 | 职责 |
| --- | --- |
| `desktop/src/renderer/src/common/useAsyncAction.ts` | `idle → pending → success/error` 局部状态机；用 `useRef` 的 `running` 挡住同帧重复点击；**不吞异常**、不改 API 契约、不接管结果回执（ToastHost 属 S2） |
| `desktop/src/renderer/src/common/useDialogA11y.ts` | Esc 关闭、Tab 双向焦点陷阱、打开焦点移入、关闭焦点归还触发元素；`onClose` 用 ref 存最新值避免重做焦点初始化 |
| `desktop/src/renderer/src/common/RouteErrorBoundary.tsx` | 把路由视图渲染异常白屏换成可操作兜底页（重试 / 返回工作台）；`App.tsx` 以 `routeHash(permittedRoute)` 作 key，切换路由自动重置 |

### 6.2 15 个高危写动作接入护栏

| 文件 | 动作 | 数量 |
| --- | --- | --- |
| `documents/ProjectDocuments.tsx` | 下载 / 生成 / 在线修订 / 确认 / 标记弃用 | 5 |
| `files/FileVersionTimeline.tsx` | 下载 / 弃用 / 恢复 | 3 |
| `library/ProjectLibrary.tsx` | 下载 / 弃用 / 恢复 / 重新生成 | 4 |
| `modules/ModulesPage.tsx` | 停用 / 启用模块 | 1 |
| `users/UsersPage.tsx` | 停用 / 启用账号 | 1 |
| `projects/CommercialBoard.tsx` | 设到期日 | 1 |

每个动作点统一补 `disabled={action.isBusy}`、`aria-busy={action.busyKey === key}`、`处理中…` 文案、`action.run(key, task)` 包裹。

**异常链核查**：15 个 task 函数全部自带 `try/catch`（或经 `mutate()` 统一吞错），因此 `void action.run(...)` 不会向外抛未处理的 Promise rejection，各页原有的错误展示行为保持不变。`DangerConfirmDialog` 的密码二次校验强度未被削弱。

### 6.3 弹窗与语义

| 文件 | 改动 |
| --- | --- |
| `files/FilePreview.tsx`、`documents/DocumentPreview.tsx`、`documents/DocumentEditor.tsx` | 挂 `useDialogA11y(onClose)` 到 `role="dialog" aria-modal="true"` 容器 |
| `documents/DocumentEditor.tsx` | `saved` 成功提示补 `role="status"` |
| `solutions/SolutionDetailPage.tsx` | 「此方案已弃用」从复用 success 样式的 `.notice` 改为 `.notice warning` + `role="alert"` |
| `App.tsx` | `<RouteErrorBoundary key={routeHash(permittedRoute)}><RoutePage … /></RouteErrorBoundary>` |

### 6.4 收口阶段发现并修复的两个问题

1. **`CommercialBoard` hook 作用域错误**：脚本把 `const action = useAsyncAction()` 挂在父组件 `CommercialBoard`，而「设到期」按钮在子组件 `PaymentRow` 内 → `npm run typecheck` 报 4 处 `TS2304: Cannot find name 'action'`。修复为删除父组件的无用实例、在 `PaymentRow` 内实例化。
2. **叠加弹窗的键盘冲突**：`useDialogA11y` 在 `document` 捕获阶段无条件 `stopPropagation()`，而 `DangerConfirmDialog` 用自身 `onKeyDown` 处理 Esc。两者叠加时，底层 hook 会让上层确认框的 Esc 失效、反而关闭底层预览。修复为焦点归属守卫：

```ts
const active = document.activeElement as HTMLElement | null
const activeDialog = active?.closest('[role="dialog"][aria-modal="true"]') ?? null
if (activeDialog && activeDialog !== dialog) return  // 焦点在上层弹窗，本 hook 让位
```

守卫同时覆盖 Esc 与 Tab 循环，避免把上层弹窗的 Tab 困在底层。

### 6.5 新增行为测试

`desktop/tests/renderer/dialog-a11y.test.tsx`（3 用例）：

- 打开时焦点移入弹窗、Esc 关闭、关闭后焦点归还触发元素；
- Tab / Shift+Tab 在弹窗内循环，不跑到背景页面；
- 叠加危险确认弹窗时底层让位：Esc 由上层处理、底层不被关闭。

---

## 7. 验收结果

| 检查 | 命令 | 结果 |
| --- | --- | --- |
| TypeScript | `cd desktop && npm run typecheck` | ✅ 通过（修 `CommercialBoard` 后） |
| 静态守卫 + 弹窗契约 | `npx vitest run tests/main/design-tokens.test.ts tests/renderer/dialog-a11y.test.tsx` | ✅ 2 文件 / 13 用例通过 |
| 桌面端全量回归 | `npx vitest run --passWithNoTests --no-file-parallelism` | ✅ **65 文件 / 765 用例通过**（收口修复后复跑；首轮 S1 为 64 / 762） |
| 渲染层构建 | `npx electron-vite build --outDir out/verify` | ✅ 2500 模块转换 / 29.3s 通过；常规 `npm run build` 被本机 safe-delete 守卫拦在「清空 66 个旧产物」（>50 阈值），**非代码错误**，故改用全新空输出目录验证 |
| 便携版重打包 + asar 字节验证 | `npx electron-builder --win dir --x64` | ⏸ **已拍板暂缓**（2026-11-06 交互式选择卡选「暂不打包」），见 §9 第 1 项 |

---

## 8. 范围外（明确未做）

- **S2**：5 个 UI 原语、ToastHost、17 处 `window.confirm/alert` 归一、导航分组；
- **S3**：8 个 CSS 文件全量治理、UI/a11y 规范文档、深色模式；
- `server/**`、数据库、镜像重建、`alembic upgrade head`；
- 任何新依赖、UI 组件库、CSS 框架、外部字体、运行时样式注入、路由重写；
- 门禁 G1–G9、审批链、危险确认强制度、客户资料代号化等业务语义；
- 提交 / push / PR —— 本轮工作树保持用户原有的并行改动状态。

---

## 9. 已知债务与后续判断

1. **便携版交付已拍板暂缓（§9.1）**：`AGENTS.md:19` 要求改 `desktop/**` 后重打包便携版并做 asar 字节验证。当前 D 盘工作树含大量**不属于本轮的并行未提交改动**（`shared/brand.ts` 重命名、`ResearchImportDialog.tsx` 删除、`server/**` 等），此时 `electron-vite build` 会把整棵脏树里的半成品一起编译进 asar；且常规 build 需清空 66 个旧产物、会触发本机批量删除守卫（见 §7）。2026-11-06 交互式选择卡拍板 **「暂不打包」**：本轮交付边界为代码 + 令牌真源 + 实施记录 + 全量验收结果，打包等工作树收口或明确发行时机后单独执行，不覆盖日常使用的 `release/…便携版-r16`。
2. **危险确认期间的文案噪音**：`action.run` 包住了含 `dangerConfirm()` 的 task，确认弹窗等待用户期间背景按钮会显示「处理中…」并禁用。功能与安全性不受影响，但语义不够准确；建议 S2 把「确认阶段」与「真实写请求」分段。
3. **`window.confirm/alert`**：守卫仍允许 ≤16 处，S2 统一 Toast / Confirm 原语后收紧上限。
4. **方案 v2 正文仍是定稿口径**（主按钮文字 `#A3721F`），实施偏差只在 `tokens.json.decisions.D4` 与本文件留痕，未回改定稿正文 —— 这是刻意保持「定稿不可回改、实施偏差可追溯」。

---

## 10. 补记（收口轮）

> 本节由实施收口轮追加，记录文档首次落盘后完成的验证与修复。

- `CommercialBoard.tsx` 的 `TS2304`（4 处）已修复，`npm run typecheck` 通过。
- `useDialogA11y.ts` 增加叠加弹窗让位守卫，新增 `dialog-a11y.test.tsx` 3 用例，与 `design-tokens.test.ts` 合计 2 文件 / 13 用例通过。
- 15 个 `void action.run(...)` 调用点已逐一核对：task 全部自带异常收敛，无未处理 rejection。
- C 盘与 D 盘 `docs/tokens.json` 经 `diff` 核对内容完全一致。
- 全量回归复跑：**65 文件 / 765 用例全绿**；`npm run typecheck` 通过。
- `npx electron-vite build --outDir out/verify` 通过（2500 模块 / 29.3s）。常规 `npm run build` 的唯一障碍是 Vite 清空 `out/renderer/assets` 时触发本机批量删除守卫（66 > 50），改用全新空目录后不删除任何文件即可完成编译验证；`desktop/out/` 已被 `.gitignore` 忽略，不污染工作树。
- 本文件同时镜像到 C 盘文档工作树 `docs/`，使两处 `tokens.json.trace` 都不悬空。
- **交付决策**：交互式选择卡拍板「暂不打包」，本轮不重打包便携版、不覆盖 `release/…便携版-r16`；asar 字节验证等工作树收口后单独执行（§9 第 1 项）。
