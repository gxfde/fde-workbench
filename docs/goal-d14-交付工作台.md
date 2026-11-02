# goal-d14 · 翻译模型来源改挂「AI 聊天」同源（拍板落地轮）

> 输入：蔡工指令「翻译可以使用AI服务的大模型吧？就是AI聊天那个，已经配置好了的。我没有kimi的密钥。只有minimax的编程套餐和智谱的编程套餐，或者deepseek的密钥。」
> 承接：goal-d13（PR #65 `f661ca4` + 补正轮 PR #66 `0570384`）。基线 `0570384`，隔离 worktree `D:\test\fde-workbench-d14`（branch `feat/goal-d14`），主树与并发会话零触碰。

## 一、事实核查（先查清「AI 聊天」到底走的哪条路，再改）

| 项 | 实测结论 |
|---|---|
| 「AI 聊天」= 什么 | 桌面端「AI Server 对话」→ `/api/v1/ai/chat/conversations` → `execute_ai_prompt`（`control/ai_server_client.py`） |
| 本机 AI Server(DSH) 状态 | **未启用**——部署 `server/.env` 无 `FDE_DSH_*` 任何键（`dsh_enabled` 默认 false） |
| 未启用时走哪条 | `execute_ai_prompt` → `_degraded_direct_result` → `direct_provider_completion`（**直连降级**） |
| 直连用哪个模型 | `resolve_model_preference`：①模型偏好表里该用户的默认模型 → ②无偏好则**系统默认槽位** `FDE_DEEPSEEK_*` |
| 本机实际值 | `FDE_DEEPSEEK_BASE_URL=https://api.minimaxi.com/v1`、`FDE_DEEPSEEK_API_KEY` 已配、各模型槽位 = `MiniMax-M3.1-Flash` ⇒ **AI 聊天现在就是 minimax 在跑，本来就不需要 kimi** |
| d13 那条路 | 翻译被切到「kimi-k3 专用槽位」（补正轮又把 base_url 独立成默认 moonshot）⇒ **都要 kimi key，蔡工没有 ⇒ 走不通** |

结论：d13 拍板项 1 的前提（有一把可用的 kimi key）不成立，须改。改法不是新造供应商槽位，而是让翻译**复用 AI 聊天那套模型解析**。

## 二、拍板（AskUserQuestion 交互式）

| # | 拍板项 | 结论 |
|---|---|---|
| 1 | 翻译最终用哪个模型来源 | **跟随 AI 聊天同源解析**（模型偏好优先，回落系统默认槽位） |
| 2 | d13 引入的 kimi 翻译槽位（key/base_url/model） | **保留为可选 env 覆盖**（三件配齐才强制走 kimi-k3） |

## 三、实施

**A·翻译模型解析改造**（`translator/jobs.py`）
- 新增 `_AiTarget`（base_url / api_key / model / timeout / source）与 `_resolve_ai_target(session, settings, user_id)`，优先级：
  1. **env 覆盖**：`kimi_translator_api_key` 已配 ⇒ 强制走翻译槽位（base_url/model 仍取翻译槽位自己的，与共享 `kimi_base_url` 解耦——d13 补正轮的有效结论保留）；
  2. **同源解析**：复用 `resolve_model_preference`（与 AI 聊天**同一套**解析：模型偏好表 → 系统默认槽位）；
  3. **兜底系统默认槽位**：个人偏好不可用（无 AI 权限 / 密钥不可解 / 未配置）时回落，**不让一个人的偏好问题拖垮翻译**；系统默认也没 key 时由客户端分类失败 `ai_service_not_configured`（不裸 500、不卡 running）。
- 客户端仍是 `DeepSeekClient`（通用 OpenAI 兼容 JSON 客户端）；**它内部自带 DSH 分支**：`dsh_enabled` 为真时自动改走 `structured_completion`（AI Server 那条）⇒ 将来启用 AI Server，翻译自动同源，无需再改代码。
- 后台任务无请求上下文 ⇒ 显式 `ai_actor_id.set(翻译提交人)`，使 DSH 模式下按**这个人**的偏好解析（与他的 AI 聊天一致），并在 finally **复位**（worker 线程复用，残留会串到下一个任务）。
- `row.ai_model` 落账改为**实际解析出的模型名**（不再写死 kimi-k3）。

**B·配置面**
- `config.py`：`kimi_translator_api_key/base_url/model` 三件保留，注释降级为「可选 env 覆盖」；`system_configuration` 的 PUBLIC/SECRET 登记不变（管理员仍可在系统配置页改）。
- `.env.example`：三件注释化并写明「不配 = 跟随 AI 聊天模型」。
- 桌面端系统配置页：翻译三项文案改为「覆盖项」，密钥标签注明「留空 = 跟随 AI 聊天模型」。

**C·测试**（新增 6 个 + 改写 3 个既有用例语义）
- 新增 `tests/test_translator_model_source.py`：偏好优先 / 无偏好回落系统默认 / env 覆盖优先于偏好 / 偏好密钥解不开时回落 / 全链路无凭据分类失败 / ready 分支落账实际模型名。
- 改写（语义随 d14 变化，非迁就）：`test_kimi_slot_unconfigured_fails_classified` → `test_no_credential_anywhere_fails_classified`（无凭据的定义从「kimi 槽位未配」改为「偏好与系统默认都没有 key」）；`test_translator_uses_own_base_url_slot` → `test_env_override_uses_own_base_url_slot`（按新 `_client(settings, target)` 签名重写，仍钉「翻译槽位 base_url 不被共享槽位牵连」）；`test_job_success_persists_draft_with_contract` 的 ai_model 断言改为「等于解析出的模型」。

## 四、验证（全实测）与过程如实登记

| 项 | 结果 |
|---|---|
| 服务端 pytest | **1712 收集 = 1706 passed + 6 skipped**（d13 基线 1706 +6 新用例） |
| 桌面端 vitest | **730/730**（60 文件，零用例新增） |
| typecheck | 零错误 |
| mypy 基线门 | 无新增（基线 289 / 当前 279）· ruff `F401,F841` 全过 |
| 迁移 | 零（head `c3e7a9b1d5f4` 22 revision 不变） |

**过程如实登记**：
①**并发会话争用测试库**：本轮本地全量 pytest 先被**并发会话**（主树 7:32 起的 pytest）占住测试库的会话级 advisory lock（`hashtext('fde_workbench_test_session')`，**常量键、与库名无关**），我这条被堵 45 分钟。按纪律不动他人进程 ⇒ **另起独立 PostgreSQL 实例**（`fde-d14-pg` + socat 转发 15433）隔离 advisory lock；socat 首次不通是因**默认 bridge 网络无容器名 DNS**，改挂自定义网络后即通（Windows 侧 127.0.0.1:15433 可达）。
②**中途 kill pytest 会留下孤儿事务**：被 kill 的会话在 `pg_stat_activity` 里留下 `idle in transaction` 且持有 advisory lock，把后续跑的会话堵在 `Lock` 上（既有 `fde-db-lock-forensics` 配方：查 pg_stat_activity → pg_terminate_backend 解堵）。
③**改完代码要重跑门**：ContextVar 复位是在全量套件跑到一半时补的 → 该次结果作废，停掉后重跑一次权威全量。
④**ruff F841**：新增用例里 `captured` 赋值未使用 → 改为同时断言客户端构造参数（既消告警又加强用例）。
⑤**d13 旧用例语义失效 3 个**：按新语义改写（见 §三 C），不靠放宽断言蒙混。
⑥**测试脚手架两处坑**：①`Fernet.generate_key()` 返回 bytes，要 `Fernet(Fernet.generate_key())` 才能 encrypt；②job 读的是 `app.config["SETTINGS"]`，局部 `model_copy` 不生效，必须替换 app 里的 SETTINGS。

## 五、不做边界与遗留

- **不做**：kimi 真实联调（无 key，配了 env 覆盖才会走）；智谱 GLM 接入（**需蔡工提供可在 API 端点用的 GLM key + 模型名**，本轮未做）；AI Server(DSH) 部署（属运维，启用后翻译自动同源）；翻译改用「模型偏好表里的个人模型」以外的第二把密钥。
- **遗留**：全部为人工/运维项——①若要用智谱 GLM：提供 key + 模型名后，在系统配置页/模型偏好里加一条即可（无需改码）；②AI Server 部署与 `FDE_DSH_*` 配置；③试点前置人工项（iptables + zcode CLI 联调检查单）。
- **新挂账**：无（承前挂账全部数据回流或人工项，见台账节三十九）。
