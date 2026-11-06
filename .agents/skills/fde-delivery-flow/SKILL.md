---
name: fde-delivery-flow
description: The standard change-delivery checklist for the fde-workbench repo — feature branch, push to fork (never origin), PR, wait for all 4 CI jobs, merge, fast-forward local main, delete branch. Use whenever the user asks to 提交代码 / 发 PR / 合并 / 交付这个改动 / 走交付流 / push 上去, or before pushing anything in this repo.
use_boundaries.when_to_use: 要提交代码改动走 feature 分支、push fork、PR、CI 全绿、合并、ff 本地 main、删分支时，push 前也应核对一遍
use_boundaries.when_not_to_use: 只读浏览与检索类操作不产生提交，不需要走交付流
references.required_reading: ["AGENTS.md", "CONTRIBUTING.md"]
references.authoritative_sources: ["AGENTS.md"]


---

# FDE 标准交付流检查单

每一处变更（含纯文档）都走这条流。**串行执行：同一时间只有一个 goal 在改工作树。**

## 0. 远端铁律（先于一切）

- `origin` = 上游（gxfde），**永不 push**。
- `fork` = caishide/fde-workbench，一切工作推送与 tag 都只打到这里。
- push 前确认远端名：`git remote -v | grep push`。

## 1. 分支与实施

- [ ] 从最新 main 建分支：`git checkout main && git checkout -b <type>/<slug>`（fix/feat/chore/docs）。
- [ ] 实施改动；密钥只出现变量名（FDE_DB_PASSWORD / FDE_JWT_SECRET / FDE_BRIDGE_TOKEN…），永不写值；客户资料只用代号。

## 2. 本地验证（按改动面，全量不许定向替代）

- [ ] 桌面改动：`npm run typecheck` && `npm run test:desktop`（仓库根）。
- [ ] 服务端改动：`MSYS_NO_PATHCONV=1 wsl -d Ubuntu-24.04 -- docker compose build && … up -d`（有迁移加 `alembic upgrade head`）→ `npm run test:server`。
- [ ] 纯文档：跳过测试，自查无客户真实信息、无密钥值。

## 3. PR

- [ ] `git push fork <branch>`。
- [ ] `gh pr create --repo caishide/fde-workbench --base main --head <branch>`，标题格式沿用仓库惯例（如 `fix(guidance): …`）。
- [ ] PR 描述写清动机、改动面、验证证据（测试数字/构建结果）。

## 4. CI 门（4 个 job 全绿才许合并）

- [ ] `desktop`（typecheck + vitest）
- [ ] `server-tests`（pytest，Ubuntu）
- [ ] `gitleaks`（秘密扫描）
- [ ] `pseudonymization`（客户资料代号纪律）

查状态：`gh pr checks <PR号> --repo caishide/fde-workbench`。任何红：回分支修，重走第 2 步，不 force-push 盖 CI。

## 5. 合并与收尾

- [ ] 合并 PR（`gh pr merge --squash` 或仓库惯例 merge commit）。
- [ ] ff 本地 main：`git fetch fork && git checkout main && git merge --ff-only fork/main`（main 上绝不产生本地提交）。
- [ ] 删分支：`git branch -d <branch>` + `git push fork --delete <branch>`。
- [ ] 核对：`git rev-parse main fork/main` 两值一致。

## 6. 交付后

- [ ] 需要记版本轨迹时更新 `CHANGELOG`；需求类改动同步 `docs/后续需求台账-F5与D11.md`。
- [ ] 桌面端面向用户的交付另见 `fde-package-verify` 技能（打包 + asar 字节验证 + r N+1 目录）。

## 常见事故对照

| 事故 | 防线 |
|---|---|
| 误 push origin | 第 0 步 remote -v 核对；push 命令永远显式写 `fork` |
| 定向测试绿但全量红 | 第 2 步明文全量；CI 也是全量 |
| main 与 fork/main 分叉 | 第 5 步 ff-only，失败即查而不是强推 |
| 密钥进历史 | 第 1 步自查 + gitleaks job 兜底，红了不算事故、绿了也别大意 |

## 契约键语义锚

- required_reading（执行前必读）：AGENTS.md、CONTRIBUTING.md——AGENTS.md「工作流与陷阱」节是分支与合并纪律的唯一权威；CONTRIBUTING.md 是贡献口径。
- authoritative_sources（冲突裁决）：AGENTS.md——技能正文是操作化展开，冲突以权威为准。
