---
name: fde-gui-regression
description: Browser-driven UI regression for the FDE workbench renderer. Use when the user asks to 跑一遍界面回归 / UI 回归 / 浏览器里点一遍 / 验一下指引链界面 / 验一下集成桥页面 / 确认并用于项目指引按钮还在不在 / GUI 测试 — covers the harness server (desktop/gui-harness), the seeded fixture, the two regression chains (指引链只读草稿确认 + 集成桥采集/刷新), and where the screenshots land.
use_boundaries.when_to_use: 要跑界面回归或验证桌面 UI 改动未破坏指引链与集成桥两条关键交互链时
use_boundaries.when_not_to_use: 纯服务端改动且 CI desktop job 已绿时，不必人工跑界面回归
references.required_reading: ["desktop/gui-harness/shots.mjs"]
references.authoritative_sources: ["desktop/gui-harness/shots.mjs"]


---

# FDE 工作台 GUI 回归（浏览器驱动）

目标：用真实浏览器点真实 renderer，回归两条最容易出事故的界面链路。

- **指引链**：只读草稿态必须直接出现「确认并用于项目指引」按钮（PR #18 修的就是这条主路径；
  它被堵死过一次——用户进的是只读预览，没有确认按钮，路径整条断掉）。
- **集成桥**：按钮齐备（立即采集 / 刷新 / 重新投影）、采集触发有用户可见反馈、刷新不炸。

## 为什么需要 harness（桌面端本身是 Electron）

桌面端 renderer 通过 Electron preload 拿 `window.fde` 桥（auth / api / bridge / app），
浏览器里没有这个桥。`desktop/gui-harness/` 用一个 **dev-only** Vite 插件注入等价实现：

- `api.request` → 同源 `/api` 代理到后端 `127.0.0.1:8010`（浏览器受同源约束，桌面端走 IPC 不受）；
- `auth.*` → 后端 `/api/v1/auth/*`（注意渲染层字段是 camelCase `deviceLabel`，
  服务端要 `device_label`，shim 自己转）；
- `bridge.capture` → 明确报「浏览器 harness 无宿主计划任务」（harness 没有 Windows 计划任务，
  这一步走的是前端真实错误路径）；
- `app.version()` → 返回**裸字符串**（这一段契约与 auth/api 不同，返回信封会让 React 崩）。

生产构建与 `npm run dev` 都不受影响（harness 是独立 config，且只 `apply: "serve"`）。

## 跑法

```bash
# 1) 起 harness（仓库根；独立进程，别和 desktop dev 混跑）
node_modules/.bin/vite --config desktop/gui-harness/vite.config.ts
#    → http://127.0.0.1:5199

# 2) 跑回归（仓库根；Playwright 用仓库自带的 playwright-core + 本机已装 Chromium）
node desktop/gui-harness/regression.mjs
#    → 逐条 PASS/FAIL；截图落在 desktop/gui-harness/screenshots/（已 gitignore）
```

前置：后端在 `127.0.0.1:8010`（`docker compose up -d`）。

## fixture（合成数据，不碰客户数据）

回归需要一个 ready+**draft** 的指引版本。种子脚本走**真实服务层**（`create_project`），
因为渲染层会校验 `template_snapshot`——手写的空快照会被 UI 直接判为「项目详情加载失败」，
那样测的就不是界面了。种子只创建合成数据：

- 用户 `gui.regression`（admin，合成口令）；
- 项目 `FDE-GUI-REGRESSION`；
- 预调研文件 + 一个 available 版本；
- 一条 `analysis_state=ready` / `status=draft` 的指引。

两个必踩的坑（都写进种子脚本了）：

1. `enterprise_code` 必须是「客户A·行业·城市」三段两枚「·」，否则服务端拒收；
2. 预调研文件**同时**要有 `display_name=预调研表` 和 `business_category=预调研`——
   挂载认领按这两个条件查，缺一个就认领不到，「查看预调研分析」入口不出现。
   （这条命名约定无服务端保障，已记台账待修。）

## 断言口径（改动界面后按这些复核）

- 指引链：挂载认领入口存在 → 点开是**只读** → 只读态有「确认并用于项目指引」、
  **没有**「保存修改」→ 点「编辑」后才有「保存修改」。
  注意「编辑」在页面上**不唯一**（项目信息卡也有一个），定位必须限定在弹窗内。
- 集成桥：三个按钮都在；点「立即采集」后出现采集相关反馈；点「刷新」页面不炸。
- 控制台无**应用级**错误。`frame-ancestors` 那条是浏览器对「CSP 经 `<meta>` 下发」的固有提示，
  与应用无关，别当缺陷。

## 坑位速查

- SPA 靠 `hashchange` 切路由：**直接改 hash 不重渲染**，要点侧边栏链接。
- `page.goto` 到只有 hash 不同的地址不算导航，页面不更新。
- Playwright 的 `getByRole(name)` 对中文是**整名匹配**且不唯一时报 count>1，按容器限定。
- 一次只留一个 harness 进程：多个实例抢 5199 端口，代理会慢到 9 秒/请求，登录看着像卡死。
- Git Bash → WSL → 容器传中文会被编码搞坏：脚本文件写 ASCII，中文用 `\uXXXX` 转义。

## 契约键语义锚

- required_reading（执行前必读）：desktop/gui-harness/shots.mjs、desktop/tests/README.md——gui-harness 目录（shots.mjs 与 fixture 种子）是回归链定义的唯一权威。
- authoritative_sources（冲突裁决）：desktop/gui-harness/——技能正文是操作化展开，冲突以权威为准。
