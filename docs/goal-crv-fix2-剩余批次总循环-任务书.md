# goal-crv-fix2 剩余修复批次总循环任务书

## 目标与红线
按 `docs/audit/全面代码审查报告-2026-11-13.md` 与 `docs/goal-crv-BLOCKED.md` §5 拍板 A，除在途批 B/F 外，清零剩余 **P1、拍板项及 r7 桌面五项 P2** 并统一部署。证据见总报告与 `docs/goal-crv-r{1,3,4,5,7,8}-*.md`；每轮先 `git fetch fork` 按最新 HEAD 现测定位。
- **隔离**：建 `D:/test/fde-wt-crv2`；禁碰主树脏改动、在途 `fde-wt-crv` 及 `#435`。根 `node_modules` 挂 junction，删树前先 `rmdir` 摘链。
- **红线**：禁 push `origin`；分支 `goal-crv-fix-{a|c|d|e|g|r7|close}` 与 PR 只推 `fork`（`gh -R caishide/fde-workbench`）。脚本必 `Write` `.py` 执行，禁 heredoc 与复杂 `python -c`。禁触 `D:\test\FDE\…` 与 `.env`；桩令牌低熵防 `gitleaks`；跨包函数内懒导入；Redis 测禁 `autouse` 清全库。

## 轮次（每批一轮一 PR，串行，预算 ≤9 轮）
1. **r1 批 A（零迁移）**：`QR-001` `auth/routes.py::_login_fail_key` 同源 NFKC+小写归一；`QR-002` `auth/service.py::change_password` 补 `_registration_state_gate` 拒非激活态续签并核齐 `suspend_registration`；`QR-003` `control/api_actions.py::_authorized` 兼容 `agents.run_start` 的 `body.project_id` 使双腿票据闸可达；`QR-004`+`018` `projects/service.py` PATCH `enterprise_code` 复跑 `ensure_enterprise_channel`（守 ≤1946 行，超则抽模块，禁涨预算）+`quote_service.py::create_quote` 渠道闸入 `Project` `with_for_update` 锁内。
2. **r2 批 C（零迁移）**：`QR-041`(#1A) `diagnostics/service.py` `lead_contact.contact` 保明文（凭据闸照常），仅 admin/认领受控读并留痕；`QR-042`(#2A) 读写懒检 `expires_at<=now` 置 `expired`、清空匿名内容字段并返 409 `session_closed`（`claimed` 保全）；`QR-043` `registration/routes.py` 四入口/重发/legacy 三处 `_ensure_surface_open` 移限流前，关闸恒 **404**；`QR-044` `claim_service.py::get_claim`+`lead_routes.py` 仅 `admin` 或 `claimant_user_id==actor.id` 可读，否则 **404**。
3. **r3 批 D（唯一 1 个 Alembic 迁移）**：`QR-055` `commercial/models.py` 加 `seat_status='active'⇒seat_expires_at IS NOT NULL` CHECK+必填，换 3 份旧夹具；`QR-056`+`059` `attribution_service.py::record_settlement` 补无包 `project_share` 归属校验（齐 `regional_service`）+阻同一 `project_share` 多商机重复结算（唯一约束或锁检 409）；`QR-057` `role_assignment_service.py` `source_uri` 扩 `String(500)`；`QR-067`(#3A) `commercial/admin_routes.py` 四 GET 补 `is_platform_operator`（403）。单步迁移挂 `fork/main` 单头，同步 `test_migrations.py`、`extract_workbench_inventory.py`、`check_archify_diagram_freshness.py`。
4. **r4 批 E（零迁移）**：`QR-071` `dispatch/settlements.py` 补 `published` 态 `seat_delivery=None` 及席位落定/重分配预扣税重算（齐 T6 口径）；`QR-072` `workflows/compiler.py` 修 `solution`（`solutions.create`）缺 `parameters.project_id`、骨架入 `body` 与 `title` 契约，补编译→执行测；`QR-073` 及通道核销：实核 `#422`（`is_unsafe_artifact_path`+`QR-088/089`）与 `#433`（`QR-092/094/095`）在位与三形态测，写核销记录（避 `#435`）。
5. **r5 批 G（零迁移）**：`QR-133`(#6A) `guidance`/`translator` 4 锚 `OperationEvent` 仅存词目 ID/`sha256` 指纹、疑似词仅计数，禁落真名，换 3 份旧钉并加 `changes` 零真名钉；`QR-134`(#7A) `guidance/service.py::update_analysis` 保存复扫文本与列表词典及凭据闸，录入卡豁免入 `AGENTS.md`。
6. **r6 批 R7（桌面五项＋便携版）**：`QR-109`/`110` `desktop/src/main/index.ts` 补 `will-redirect`、`desktop-execute` 入 `lcscIpcEnabled` 默认关闸；`QR-111` `lcsc-runner.ts` 点击前复验 `denied` 并补测；`QR-112` `fde-web-bridge.ts`↔`shared/api-safety.ts` 提双桥共用响应校验与脱敏纯函数并扩钉；`QR-113` `AgentsConsole.tsx` 去顶层 `error` 整页早返回，改页内错误条+重试。现测主树 `desktop/release/` 最新 `r<N>` 顺延打包落主树 `release/`，验 `asar` 英文探针命中+旧版 0 命中。
7. **r7 收口与部署**：总报告末加销号节（不改 v1.0 正文）、回写 `goal-crv-BLOCKED/PROGRESS.md`、`AGENTS.md`（独立 bullet，**禁重写**超长链行）；随轮写 `CHANGELOG.md` `delivery` 节（守 ≤20% 钉）。跑 `python scripts/deploy/takeover_check.py --tree D:/test/fde-wt-crv2 --live` PASS → `wsl -d Ubuntu-24.04 -- docker compose -p fde-workbench build api worker scheduler`+`up -d --force-recreate` → 容器内 `alembic upgrade head` → **活体三验**（`url_map`≡inventory、`alembic current`≡新单头、三镜像 ID≡本树构建且 `health/ready` 200）。

## 验证与止损闸
- **变异红→绿**：每条配新测，「注变异→**真红**→`try/finally` 还原核 `sha256`（禁 `git checkout --`）→**全绿**」，记 `docs/goal-crv-fix2-PROGRESS.md`。
- **本地闸**：服务端跑定向 pytest+`ruff check`+`python scripts/check-python-types.py`（≤277 零新增）+`pytest server/tests/test_architecture_purity.py server/tests/test_source_size_budgets.py server/tests/test_ledger_sync_nail.py`；桌面跑 `npm run typecheck`+`npm run test:desktop`。
- **PR 与止损**：每批待最新 SHA **4 必需 CI job 全绿**后 squash 合并；同轮真红 ≥2 次写 `docs/goal-crv-fix2-BLOCKED.md` 停损，禁删测、降断言、涨预算或无理由 skip/xfail。不重修批 B/F，不越界改其余 P2/P3。
