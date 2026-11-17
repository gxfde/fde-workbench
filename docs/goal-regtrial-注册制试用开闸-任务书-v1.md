# goal-regtrial · 注册制试用开闸任务书 v1

你是执行者，本文档是你唯一任务来源，中途没人可问——拿不准的写 `docs/goal-regtrial-BLOCKED.md`（待裁决清单），跳过继续做别的，随交付提交。断了/换新会话：先读 `docs/goal-regtrial-PROGRESS.md`（进度账）接着做，别重做，每做完一项立刻更新。

**这活为什么干**：SES 生产权限 2026-11-05 被 AWS 拒绝、路线冻结（OWNER 拍板）；对外受控试用（G-C 已签放行）要放量，把「HOST 手工发号」升级为「注册制自助试用」。发信通道加 provider 无关 SMTP（Zoho 形态——AI外贸获客 backend 2026-11-09 同款模式实发验证过）；注册面四入口＋邮箱验证＋限流＋审核状态机已在库（M2，PR #309）。本线＝通道小 PR＋配置面＋端到端，**不等任何外部审批**。

**让步顺序**：生产活体安全 > 口径诚实 > 做得全 > 做得快。
**法与情报**：「只允许/不许」违反即失败；「建议」有更好的路可走，在 PROGRESS 记一句为什么。AGENTS.md 红线全文适用（密钥不落盘不进 argv 不进仓、AI 不代开公网写面、origin 永不 push）。

## 我替领导拍的板

- **SMTP 凭据与 FROM 地址**＝OWNER 提供中（建议 fde18.com 域邮箱；未到位前代码侧照常推进，端到端一步 BLOCKED 备料）。猜错代价＝端到端延迟，不影响代码交付。
- **审核制**＝enterprise **不纳审**（验证邮箱即进＝自助语义），靠限流＋值守扛滥用；收紧＝改配置 recreate，零代码。猜错代价＝垃圾注册进来（可停用，风险低）。
- **限流**＝每 IP 每日 10（保守值，键名以 config.py 现测为准）；公网面 `FDE_REGISTRATION_RATE_FAIL_CLOSED=1`。
- **远端部署树开闸**＝列 OWNER 亲手清单随交付上交，AI 不代开公网写面；本线只做本机主栈端到端验证。

## 界限

- 独立 worktree 施工（`git worktree add` 自 fork/main tip 新建），不占评测树/部署树工作区。
- 白名单：`server/**`、`desktop/**`（仅当 R3 需补入口）、`docs/**`、`scripts/**`（仅端到端脚本）；`server/.env` 只许追加 `FDE_SMTP_*`/注册面键（本机验证态）。
- 判卷标准碰都不许碰：`.github/workflows/ci.yml`、既有测试断言与阈值不得放松；**既有 `FDE_SES_*` 键与 `test_mailing_ses.py` 27 例一字不动**（零回归）。
- 顺手活（重构 mailing 其它部分、顺手修无关 bug、顺手升依赖）→ BLOCKED 登记，不做。
- 收不回的操作（远端写面、注册面公网开闸、删数据）→ 停下写 BLOCKED.md 做别的。
- **本任务书目前只在评测工作树、未入库**（untracked）——开工第一步把它**逐字节复制**进你 worktree 同名相对路径：`C:/Users/P1/.zcode/worktrees/a6c5/fde-workbench/docs/goal-regtrial-注册制试用开闸-任务书-v1.md`；复制后 `git status -s` 应见 `??`；**随本线收口 PR 一并提交入库**（丢失即重新复制）。

## 现状与任务 0

评测基线（2026-11-17 现测）：
- fork/main tip `4dadbc64`（#502）；服务端结构口径 **523 路由/55 蓝图/160 表/89 rev 单头 `b7f2d9e4c6a8`**（引用前现测为准）。
- `server/src/fde_api/mailing/`＝policy/ses_client/service/routes/models 五文件；`SesClient` 是 Protocol，`service.send_email` 只依赖协议；五步闸门在 policy；`test_mailing_ses.py` 27 例。
- 注册面 `server/src/fde_api/registration/` 四文件；前端 `desktop/src/renderer/src/commercial/EnterpriseRegisterPage.tsx` 在场。
- 本机与远端容器 `FDE_SES_ENABLED=false`；`config.py` 三键 `registration_enabled/public_base_url/ses_enabled` 默认全关。

**任务 0（逐条跑、贴输出）**：①`git fetch fork && git log --oneline -1 fork/main && git rev-list HEAD..fork/main --count`（>3 停报 BLOCKED）；②`ls server/src/fde_api/mailing/ | wc -l`（=5）；③`grep -c "def test" server/tests/test_mailing_ses.py`（=27）；④`ls desktop/src/renderer/src/commercial/EnterpriseRegisterPage.tsx`（在场）；⑤`grep -n "registration_enabled\|ses_enabled\|public_base_url" server/src/fde_api/config.py`（三键在）。对不上就停，证据写 BLOCKED.md 最上面，只做不受影响部分；核对无误后把「理解的目标/顺序/最大风险」≤10 行写进 PROGRESS.md 再动工。

## 任务（按依赖排序）

**R1 SMTP 发信通道 PR**（核心）
- NEW `mailing/smtp_client.py`：`SmtplibClient` 实现 `SesClient` 协议——`smtplib.SMTP(host, port)` + `starttls()` + login + `sendmail`；返回 message-id 头形态标识（幂等台账语义不变）；超时/拒收映射进既有 throttle/拒收两分类。
- 工厂分支：`FDE_SMTP_ENABLED=true` 构造 SmtplibClient（SES 键路径一字不动）；两开关同开＝启动失败 fail-closed。
- 新配置键 `FDE_SMTP_HOST/PORT/USERNAME/PASSWORD/FROM`（启用即校验必填齐）；`.env.example` 注释态占位（真值永不进仓）。
- 测试：闸门 9 例（纯 policy）复用不改；NEW mock smtplib 客户端测试＋工厂分支＋双开关互斥钉；**变异验证红→try/finally 还原→绿**贴输出。

**R2 配置面与红线修订**
- AGENTS「注册面公开写面纪律」开闸三条件「SES 启用」→「发信通道启用（SMTP 或 SES）」，修订随 PR 并注记「2026-11-17 OWNER 拍板 SES 冻结后修订」。
- 限流实数与 fail-closed 建议值落 `.env.example` 注释（注册面键名现测后对号）。

**R3 前端注册入口可达性现测**（小活）
- 现测 web 形态注册路由挂载与入口可达（`EnterpriseRegisterPage` 的 hash 路由与导航）；缺则补链接（桌面/网页同构一个 PR；涉桌面则 `npm run typecheck && npm run test:desktop`＋r54 三源 bump＋asar 正反向双证）。

**R4 本机主栈端到端**（凭据到位才执行；未到位 BLOCKED 备料）
- 先闸：`python scripts/deploy/takeover_check.py --tree D:/test/fde-workbench --live`（FAIL 先补齐再动）。
- `docker compose -p fde-workbench build api worker scheduler` → `up -d --force-recreate`（只动 fde-workbench 前缀，qiflow-* 邻栈零触碰）→ 容器内 `alembic current`＝head 复验。
- `server/.env` 填 `FDE_SMTP_*`＋`FDE_REGISTRATION_ENABLED=1`＋公网根地址＋限流两键 → 全链逐环贴输出：注册 → 收验证邮件 → 邮箱验证 → 登录 → 试用写动作。复验不符立即停手还原。

**R5 文档三同步＋收口 PR**
- CHANGELOG 节＋台账登记＋AGENTS 状态行；feature 分支 → push fork（origin 永不 push）→ PR → 四 CI job 全绿 → **人工合并（蔡工）**。远端开闸 OWNER 清单写进 PROGRESS 随交付上交。

## 规矩

- **防作弊**：CI 绿只认四 job `conclusion=success`；禁 skip/todo/放宽断言/改阈值/mock 被测单元/`|| true`；测试收集数只许 ≥ 基线；CHANGELOG 只增不改旧节。
- **Skill 关卡（DoD 硬性，不是建议）**：开工 `Skill(fde-delivery-flow)`（认领前查在途 PR）；公网写面改动 PR 前 `Skill(intended-vs-implemented)`＋`Skill(code-review)` 只读 diff；R1 完成 `Skill(verification-before-completion)`；R3 涉桌面 `Skill(fde-gui-regression)`＋`Skill(fde-package-verify)`；缺陷定位 `Skill(systematic-debugging)`；收尾 `Skill(neat-freak)`。
- 三道止损：同一验收连败 3 次换下一项；活体状态比开工差（三验恶化）→ 立即回滚原镜像并如实报告；或跑满 5 轮——满轮即停，如实汇报卡在哪。

## 完成条件（两条硬指标）

1. **度量**：R1 PR 四 CI job 全绿（新测试＋变异验证红→绿回执在案）；凭据到位时本机主栈端到端全链 PASS 回执（注册→邮件→验证→登录→写动作，逐环实际输出贴对话，只说通了不算）。
2. **约束**：`git diff` 既有 `FDE_SES_*` 键与 27 例零触碰；远端部署树写操作=0（开闸列 OWNER 清单）；SMTP 密码/凭据零进仓零进 argv 零进回执。

每条判据贴实际命令输出，只说做完了不算。`BLOCKED.md` 随交付提交，空的写「无」。
