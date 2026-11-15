---
name: fde-delivery-flow
description: The standard change-delivery checklist for the fde-workbench repo — feature branch, push to fork (never origin), PR, wait for all 4 CI jobs, merge, fast-forward local main, delete branch, with embedded skill gates (code-review, intended-vs-implemented, verification-before-completion, neat-freak). Use whenever the user asks to 提交代码 / 发 PR / 合并 / 交付这个改动 / 走交付流 / push 上去, or before pushing anything in this repo.
use_boundaries.when_to_use: 要提交代码改动走 feature 分支、push fork、PR、CI 全绿、合并、ff 本地 main、删分支时，push 前也应核对一遍
use_boundaries.when_not_to_use: 只读浏览与检索类操作不产生提交，不需要走交付流
references.required_reading: ["AGENTS.md", "CONTRIBUTING.md"]
references.authoritative_sources: ["AGENTS.md"]


---

# FDE 标准交付流检查单（含嵌入式技能关卡）

每一处变更（含纯文档）都走这条流。**串行执行：同一时间只有一个 goal 在改工作树；并发大线须用独立 git worktree 隔离。**

> **为什么在此处显式嵌入 `Skill(...)` 调用？**
> 宿主（如 ZCode）在全局数百个技能共存时默认不预注入技能 `description`，未点名时模型自主触发率仅 30%–50%。将关键质量技能固化为本交付流的必经关卡，只要进入交付流即链式触发整套审查、证伪、实证与口径收尾。

## 0. 远端与在途盘点铁律（先于一切）

- `origin` = 上游（gxfde），**永不 push**。
- `fork` = caishide/fde-workbench，一切工作推送与 tag 都只打到这里。
- 开工前必查在途 PR 与并发树：`gh pr list -R caishide/fde-workbench --state open` + `git worktree list`，严防撞车改同一批热点文件。
- push 前确认远端名：`git remote -v | grep push`。
- 若属新阶段立项 / 架构方案 / 高敏开关设计：编码前先调 `Skill(skill="strategy-red-team")` 压测承重假设。

## 1. 分支与实施

- [ ] 从最新 `fork/main` 建分支（或建独立 worktree）：`git fetch fork && git checkout -B <type>/<slug> fork/main`（fix/feat/chore/docs）。
- [ ] 修缺陷或加门禁时优先配合 `Skill(skill="tdd")` 先写失败用例（或做「变异真红 → `try/finally` 字节还原 → 复绿」验证）；遇到跨进程 / CI 偶发红灯 / 首次修复无效时，立即调 `Skill(skill="systematic-debugging")` 追根因，禁盲猜叠补丁。
- [ ] 实施改动；密钥只出现变量名（FDE_DB_PASSWORD / FDE_JWT_SECRET / FDE_BRIDGE_TOKEN…），永不写值；客户资料只用代号；标准答案永不进仓。

## 2. 提交与 Push 前技能审查闸（非纯文档改动必过）

- [ ] **代码契约与安全自审（必调）**：调用 `Skill(skill="code-review")` 只读审视 `git diff fork/main...HEAD`（严守 B#3 红线：AI 审查只读 diff/文本快照，绝不执行被审代码）。
- [ ] **跨模块独立盲审（改动 ≥ 3 个文件或跨前后端模块时加调）**：调用 `Skill(skill="requesting-code-review")` 派发零历史包袱的只读子代理审 `BASE_SHA..HEAD_SHA`。
- [ ] **书面意图 ↔ 代码落点双向证伪（触及以下任一边界必调）**：凡涉及多租户隔离（`permissions.py` / `org_id`）、公网免注册写面（`diagnostics` / `registration` 404 隐身与限流）、脱敏管线、商业结算分账、宿主通道/出站闸、`AGENTS.md` 红线相关代码，必须调用 `Skill(skill="intended-vs-implemented")` 双向核对 `文档:行号` ↔ `服务端执行点:行号`。

## 3. 本地实证闸（按改动面，全量不许定向替代）

- [ ] **完成前实证硬闸（必调）**：宣称完成或执行 push 前，调用 `Skill(skill="verification-before-completion")` 逐项核验真实命令退出码（禁凭体感宣称通过）：
  - 桌面改动：`npm run typecheck` && `npm run test:desktop`（仓库根）；改 UI 布局 / 路由 / IPC / CSP 时加调 `Skill(skill="fde-gui-regression")`。
  - 服务端改动：`npm run test:server` + `python scripts/check-python-types.py`；若增删蓝图/路由/表/迁移，必跑 `python scripts/audit/extract_workbench_inventory.py` 刷新清单并更新 `docs/architecture/archify-diagrams/`（过 `python scripts/audit/check_archify_diagram_freshness.py`）。
  - 涉及活体 Docker 部署：先跑 `python scripts/deploy/takeover_check.py --tree <部署树根> --live`，再 `MSYS_NO_PATHCONV=1 wsl -d Ubuntu-24.04 -- docker compose build && … up -d --force-recreate` + `alembic upgrade head`，并完成**活体三验**（`url_map` 条数 / `alembic current` == head / 容器镜像 ID 一致）。
  - 纯文档：核验 `test_ledger_sync_nail.py` / `test_diagnostic_eval_contamination.py`（若触及 `CHANGELOG.md` / `docs/audit/`），自查无客户真实信息、无密钥值。

## 4. 口径与洁癖收尾闸（发 PR 前必过）

- [ ] **台账与口径对齐（涉文档/台账/口径必调）**：调用 `Skill(skill="neat-freak")` 现测核对路由/蓝图/表/迁移/用例数字（禁承袭旧数），全文同模式终扫防串位，双份操作手册（`docs/工作台操作使用手册.md` 与 `server/src/fde_api/control/bundled/help_manual.md`）保持字节一致，清理临时文件。

## 5. PR

- [ ] `git push fork <branch>`。
- [ ] `gh pr create --repo caishide/fde-workbench --base main --head <branch>`，标题格式沿用仓库惯例（如 `fix(guidance): …`）。
- [ ] PR 描述写清动机、改动面、已执行的审查技能回执与验证证据（测试数字/构建结果）。

## 6. CI 门（4 个 job 全绿才许合并）

- [ ] `desktop`（typecheck + vitest）
- [ ] `server-tests`（pytest，Ubuntu）
- [ ] `gitleaks`（秘密扫描）
- [ ] `pseudonymization`（客户资料代号纪律）

查状态：`gh pr checks <PR号> --repo caishide/fde-workbench`。任何红：回分支修，重走第 2–3 步，不 force-push 盖 CI。

## 7. 合并与收尾

- [ ] 合并 PR（`gh pr merge --squash` 或仓库惯例 merge commit）。
- [ ] ff 本地 main：`git fetch fork && git checkout main && git merge --ff-only fork/main`（main 上绝不产生本地提交）。
- [ ] 删分支与回收临时 worktree：`git branch -d <branch>` + `git push fork --delete <branch>`（若有 junction 软链先 `rmdir` 摘链再删树）。
- [ ] 核对：`git rev-parse main fork/main` 两值一致；同步更新 `codegraph sync`。

## 8. 交付后

- [ ] 需要记版本轨迹时并入随轮 PR 更新 `CHANGELOG.md` 与 `AGENTS.md`（遵守 `test_ledger_sync_nail.py` 台账消耗型占比 ≤20% 纪律，补账不单独开轮）；需求类改动同步 `docs/后续需求台账-F5与D11.md`。
- [ ] 桌面端面向用户的交付必调 `Skill(skill="fde-package-verify")`（打包 + `scripts/verify-asar-bytes.mjs` 正反向中文 marker 字节验证 + `r<N+1>` 目录）。

## 常见事故对照

| 事故 | 防线 |
|---|---|
| 误 push origin | 第 0 步 remote -v 核对；push 命令永远显式写 `fork` |
| 技能装了但漏调、自审走过场 | 第 2–4 步显式嵌入 `code-review` / `intended-vs-implemented` / `verification-before-completion` / `neat-freak` |
| 定向测试绿但全量红 | 第 3 步明文全量 + `verification-before-completion` 退出码实证；CI 也是全量 |
| main 与 fork/main 分叉 | 第 7 步 ff-only，失败即查而不是强推 |
| 密钥或真实客户名进历史 | 第 1 步自查 + gitleaks / pseudonymization 双 job 兜底 |

## 契约键语义锚

- required_reading（执行前必读）：AGENTS.md、CONTRIBUTING.md——AGENTS.md「工作流与陷阱」节是分支与合并纪律的唯一权威；CONTRIBUTING.md 是贡献口径。
- authoritative_sources（冲突裁决）：AGENTS.md——技能正文是操作化展开，冲突以权威为准。
