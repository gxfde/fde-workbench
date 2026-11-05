# DSH 适配层决策记录 v1（B#27——零代码）

> **登记号**：借鉴清单 **B#27**（FF-FDE-Delivery-Workbench 上游基线锁定与适配层缺口处置）。
> **来源**：调研会话《自动化运行-DSH替代可行性评估-2026-11-05》（P3 评估报告 §4 已消费，锚=合同 §4.4-4）与《开源项目借鉴总览-2026-11-05》§0 专项结论/§4——调研报告为 **docs/audit/ 在途未提交产物**（落定回写归调研会话），本记录只消费其结论、不复制其证据链。
> **状态**：决策记录（零代码零配置）；任何实施（装 DSH / 写适配层）须另立轮走既有流程。

---

## 1. 裁决（维持，不翻案）

**当前不安装 DSH、不换执行体**（`FDE_DSH_ENABLED=false` 维持）——三重约束：无真实业务需求（自动化诉求环节未澄清，调研前提 2）、官方 developer preview **未经安全审计**（SAFETY.md 原文）、成本收益不成立（已自动化面完全不依赖 DSH，见 §2）。「尽可能自动化」的真瓶颈是**人工拍板红线**（设计决议），不是缺少某个 Agent。

## 2. 事实基线（为何「装官方 DSH」不等于「能自动化」）

1. **我方协议是自定的**：`control/dsh_runtime.py` 连的是 HTTP 8020 上的 FDE 自定协议 **`fde-dsh-v1`**（`config.py:74`）——端点 `/v1/health`、`/v1/executions`、`/v1/executions/{id}/progress`、`/v1/plugins/apply` + 反向回调 `/internal/dsh/...`（`control/routes.py:323-383`）。
2. **官方源码零命中**：调研会在 FF 本地副本（`upstream/deepseek-harness/`，官方 `0.2.1-rc.2` 全量 vendored）的 `packages/{web,api,host}/src` 实查——上述端点与 `fde-dsh-v1` 字符串**零命中**。官方 CLI 只有一次性 `headless`、stdio JSON-RPC（`sdk`/`acp`）与回环 Web UI（3080），**没有任何 `/v1/executions` REST 端点**。
3. **结论**：装官方 DSH **不会自动满足我方协议**——适配层仍需自写。「有源码 ≠ 能接上」。
4. **依赖面收窄**（调研 §5）：已自动化且完全不依赖 DSH 的=workflow 定义与 skill 节点（C 轨）、scheduler+outbox+worker 后台链、G1–G9 门禁候选链、派单 8 态机；真依赖 DSH 的仅 A 轨 `automation.execute`（`automation_jobs.py:90` 无 fallback）与 AI 聊天写工具（B 轨，有已验证的 13 只读降级路径）。

## 3. 若将来启用 `FDE_DSH_*`：适配层必须自写的清单

| 件 | 内容 |
|---|---|
| REST 面 | `/v1/health`、`/v1/executions`、`/v1/executions/{id}/progress`、`/v1/plugins/apply` + `Idempotency-Key` 重放 + `X-FDE-Protocol-Version` 协商 + `runtime_version` 返回与落库一致 |
| 反向回调 | `/internal/dsh/executions/{run}/…` events / knowledge / approvals 三类（service token HMAC `compare_digest`，与 MCP token 两套） |
| 审批链 | 15min 窗 + `arguments_sha256` + 执行前复查（我方 `automation_approvals` 五要素在表，无结构性缺口） |
| MCP 回环 | `issue_mcp_token` 15min HS256 JWT（claims: sub/ver/project_id/execution_id/capabilities）注入 `mcp:{url,token}`；`auth_version` 撤销即时失效 |
| 降级 | `DEGRADABLE_DSH_CODES` 白名单降级标 `degraded=true`；`dsh_execution_conflict` **不降级**；降级态不签发 MCP token |
| 实现参照 | FF 本地副本官方源码（`upstream/deepseek-harness/`）+ 其 Python SDK（`sdk-minimal` 进程内）——**进程内 SDK 不是网络服务，仍需自包 HTTP 层** |

## 4. 上游基线锁定法（FF 可抄实现，采纳为接入前置规范）

- **lock 八字段**：`repository / commit / release / tag / previousCommit / previousRelease / checkout / lockedAt`（FF `upstream/deepseek-harness.lock.json` 样例：commit `687f282e…` / release `0.2.1-rc.2` / lockedAt 2026-10-23）。
- **升级 = 三方合并**：旧官方树 + 当前下游树 + 新官方树；**不覆盖目录、不 `git pull upstream master`**。
- **developer preview 纪律**：必须固定版本，不自动跟随 master；会话逐代迁移验证；**回退须同时回退数据副本**（运行期版本随 run 冻结在 `automation_task_runs.dsh_runtime_version`，破坏性变更会污染溯源）。
- **部署隔离**（FF 语义采纳）：`DSH_HOME` 独立隔离启动为硬门禁；默认仅本机监听。

## 5. 安全前置（接入前必须全过，缺一不立项）

1. 官方 `SAFETY.md`：developer preview、未经安全审计、可执行模型生成代码/加载第三方插件——接入评估须按「不可信运行时」对待。
2. SDK 两个红线级默认值必须显式关闭：`sdk-minimal` **pins `danger-full-access`**（shell 可改任何可见路径）；`session-log-deepseek` **默认上传未接受的日志事件**（≤8 MiB/请求）——**接客户资料 = 绝对禁止，除非 patch 关闭 + 一次性 workspace/home**。
3. 客户资料红线：证据只存 `source_uri`+sha256、真实资料不出本机；会话/日志零外传。
4. 调研 §11 验证要点全过（协议/降级/鉴权/治理/红线/成熟度/现实前置七层）。

## 6. 与既有决议的关系

- P3 合同 §4.4-4 / P3 评估报告 §4：调研结论作为输入已消费，同向。
- 借鉴清单 B#20（DSH 替代内评）：本记录即其 P0 层落盘；P1（协议适配层立项）与 P2（zcode/codex 编程类后端）维持条件触发，触发=用户澄清具体自动化诉求环节。
- agents 轨（D 轨）人工授权写路径红线不变：AI 不得代发起/接管/重试（`agents/routes.py:4`）；任何执行体更换不得绕过。
