# Agent Autoloop 开源项目评估与「蔡工FDE智能交付系统」借鉴分析

- **评估日期**：2026-11-04
- **评估对象**：`https://github.com/KKKKhazix/agent-autoloop`（MIT，v1.0.0，2026-11-03 发布）
- **评估人**：FDE 工作台架构侧
- **证据口径**：本报告所有标注 **[已核实]** 的结论均来自本次会话直接抓取的仓库原文（README.md / README.en.md / AGENTS.md / INSTALL.md / docs/protocol.md / docs/plugins.md）与源码文件（`kernel/decide.ts`、`kernel/due.ts`、`protocol/validate.ts` 等），未依赖二手转述。标注 **[推测]** 的部分为基于源码结构的推断，未经作者确认。

---

## 0. 结论先行

| 维度 | 评价 |
|---|---|
| 与我方定位关系 | **互补偏弱**，不是同赛道竞品。它是「单机个人 Agent 自动化中台」，我方是「多租户企业级 FDE 交付工作台」 |
| 最值得抄的一条 | **「挂起零消耗」+ 回执协议**：Agent 遇拍板事项时进程退出、状态落库、零 Token 占用，回复后续接原会话。我方已有等价物但**未做「零消耗挂起」的语义分离** |
| 最值得抄的第二条 | **跳数熔断（hops ≤ 8）**：事件驱动的自触发链必须有硬上限。我方目前**没有跨节点/跨运行的链式跳数控制** |
| 最值得抄的第三条 | **指令数据分离（Prompt 注入防线）**：外部文本只作资料入文件，不拼提示词。我方有 MCP 工具面但**无「事件文字禁入提示词」的硬规则** |
| 不该抄的 | 事件溯源纯追加日志 + 无迁移的投影重建（我方是 SQL 权威库，已有一套迁移体系，抄它等于推翻现有资产）、桌面通知/飞书卡片通道（我方有桌面端）、零依赖极简内核（我方是企业级多租户） |
| 一句话判断 | **借「协议与语义」，不借「架构与存储」。** 它的价值在 4 个语义约定 + 1 套回执 DSL，不在 1650 行内核代码 |

---

## 1. 项目概述

### 1.1 核心定位 [已核实]

> "让你的命令行 Agent 在后台自己接活、自己跟进到底；平时不烦你，遇到拿不准的事才发卡片找你拍板。"

定位是**单机、单用户、命令行为主的 Agent 自动化中台**。核心主张：

- **极轻量**：零第三方运行时依赖（`package.json` 不写 `dependencies`），内核约 1651 行
- **插件化**：除内核外一切（事件源 / Agent / 通知通道 / 交付流水线）都是可热插拔插件
- **无界面**：没有后台页面，只有 CLI（`status` / `answer` / `why` / `doctor` / `check`）和一张「不跑脚本的表单」卡片页
- **本地优先**：装在 Mac/Linux 本机，不开放公网端口，不买云服务器

作者自述背景：做了约 1 年的个人 Agent 自动化系统后重构开源；架构借鉴了 Pi 的极简内核 + Extensions 设计、DeepSeek Harness 的「一切皆插件」理念。

### 1.2 解决的问题 [已核实]

针对的痛点非常具体：

1. **人守着终端用 Agent**：输一句话、盯着跑、等下一步；关窗口或人走开事情就断
2. **多 Agent 互相调用会无限循环**：作者原话「A 干完叫 B，B 干完又叫 A，额度直接炸」
3. **长流程挂起烧钱**：Agent 每隔几分钟问一次「我回了没有」
4. **写入操作重试会做两遍**：网络抖动导致重复执行
5. **Prompt 注入**：外部 Issue/PR 正文是 Agent 都能读到的攻击面
6. **状态不可追**：事后说不清「这一轮为什么跑、当时用哪版规则、结果如何」

### 1.3 整体架构 [已核实]

源码分 8 层，命名清晰：

```
kernel/    内核（1651 行，零依赖，纯函数）
  ├─ decide.ts    所有会改变中台状态的决策（纯函数：view + input + now + env → facts）
  ├─ state.ts     状态投影
  ├─ evolve.ts    日志追加 + 投影写入（独占）
  ├─ store.ts     事实日志存储
  ├─ due.ts       到期任务计算（cron / later / retry / delivery / offline / lease）
  ├─ rules.ts     规则类型与匹配
  ├─ query.ts     视图查询
  ├─ credentials.ts 凭据（HMAC 签名、密钥）
  ├─ cron.ts      cron 解析
  └─ http.ts      接口行为定义
host/      运行外壳（Node HTTP、SQLite、时钟、配置、后台服务、插件加载）
protocol/  通信格式 + JSON Schema + 输入校验 + HTTP 客户端 + 一致性检查
worker/    接单程序（领活 → 跑 Agent → 心跳/停止 → 读并提交回执）
cli/ bin/  用户命令
plugins/   内置插件（claude / codex / acp / command / github / desktop / feishu / webhook / delivery）
examples/  场景模板 + 最小插件模板 + Shell 示例
skills/    中台自身的配置与操作手册（SKILL.md）
tests/ sim/ 行为测试 + 模拟/穷举/强杀/变异检查
```

**核心设计契约（AGENTS.md 明文）**：

> 「内核只收、只分、只派、只记。`kernel/` 不主动连接任何东西，不知道任何产品的名字。`tests/purity.test.ts` 守着这几条。」

内核边界（AGENTS.md）：

> 「`decide(view, input, now, environment)` 只能产生事实；判断和提交在同一事务中……内核不读时钟、不取随机数、不读环境或文件。时间、规则变更、主密钥和请求从外壳传入。」

这是**纯函数 + 依赖注入**的典型内核设计：`now`、`env` 作为参数传入而非内核自取，因此「同样的输入永远得出同样的结果」。

### 1.4 技术栈 [已核实]

| 项 | 内容 |
|---|---|
| 语言 | TypeScript（Node 24，`--experimental-strip-types` 直跑 `.ts`） |
| 运行时依赖 | **0**（`package.json` 无 `dependencies`） |
| 存储 | SQLite（host 层，`host/store.ts`）+ 追加式事实日志 |
| 传输 | 本地 HTTP + JSON（三口子：事件源 POST /v1/events、接单程序 claim、通道收卡） |
| 校验 | JSON Schema（`protocol/schema.json`）+ 手工 `protocol/validate.ts` |
| 平台 | **macOS / Linux，暂不支持 Windows** [已核实，INSTALL.md 明文] |
| 依赖管理 | 内置插件零依赖，第三方插件「只克隆，不装依赖、不跑安装脚本」 |

### 1.5 目录结构与关键模块划分 [已核实]

完整 188 条路径已抓取核对，关键模块职责：

- **`kernel/`** — 决策与事实。`decide.ts` 是唯一的状态变更入口（541 行），所有 handler 在一个 draft 上算改动，最后产出一条 fact。
- **`host/`** — 真实世界接入层。`host/http.ts` 被 AGENTS.md 限制为「只把 Node 请求变成 Request，不超过 50 行」。
- **`protocol/`** — 跨进程契约。`protocol/validate.ts` 校验 Agent 回执；`protocol/conformance.ts` 做一致性检查。
- **`worker/`** — 接单程序。领活、跑 Agent、心跳、停止、提交回执。
- **`plugins/delivery/`** — 交付流水线插件，9 个文件：`delivery.ts` / `review.ts` / `github.ts` / `poll.ts` / `run.ts` / `action.ts` / `action.yml` / `project.ts` / `input.ts`。

### 1.6 主要工作流程 [已核实]

**五步循环**（README 编号与架构图一一对应）：

```
1. 新事件进来     → 定时任务 / GitHub Issue / 业务告警 → 统一格式事件送进内核
2. 按规则派活     → rules.json 决定：交给哪个 Agent、去哪个目录、用哪个 Skill
                    同事项短时间多条消息合并成一轮（防"一窝蜂改同一个东西"）
3. 干完一轮就退出 → Agent 把结果写在最后一条回复里，进程直接退出
4. 拿不准才问你   → 删数据/重启服务/花钱/对外发消息 → 内核发卡片（飞书/桌面通知）
                    等回复期间不占进程、不耗 Token
5. 点一下接着干   → 接上原来的对话，继续把活干完
```

**Agent 与中台的唯一约定**——在最后一条回复里附一段 `agent-autoloop` 代码块：

```text
```agent-autoloop
{
  "ask": [{ "title": "怎么发货？", "text": "两种方式今天都能发出。",
            "options": ["快递", "自提"], "key": "shipping" }]
}
```
```

支持 5 种回执动作（`protocol/validate.ts` 实测校验逻辑）：
- `ask` — 提问（2–5 个 options，最多 5 项）
- `notice` — 通知（最多 10 项）
- `resolve` — 关闭已解决卡片（最多 50 项，每项须带 1000 字内核实依据）
- `later` — 预约复查（带时区的 `at` + `about`；或 `cancel: true`）
- `events` — 触发新事件（最多 100 项）

**规则文件 `rules.json` 结构** [已核实]：

```jsonc
{
  "timezone": "Asia/Shanghai",
  "askFirst": ["删数据", "停服", "花钱", "对外发消息"],
  "sources":  { "github": { "name": "GitHub", "adapter": "github" } },
  "agents":   { "codex": { "name": "Codex", "worker": "mac-mini", "use": "codex", "access": "edit" } },
  "channels": { "feishu": { "name": "飞书", "answerers": ["ou_xxx"] } },
  "rules": [{
    "name": "处理告警",
    "when": { "source": "shop", "types": ["alert.*"] },   // 或 { "cron": "0 9 * * *" }
    "to": "codex", "cwd": "~/code/shop", "skill": "run-ops", "prompt": "...",
    "group": "ops",        // 同一组一次一轮
    "parallel": 3,         // 按对象分事项，同一对象一次一轮，本组最多 3 轮
    "tell": "needed",      // always / needed / never
    "emits": { "source": "shop", "types": ["pr.*"] }  // 回执里能发什么事件
  }]
}
```

**三个关键机制的实现细节** [已核实，来自 `kernel/decide.ts` / `kernel/due.ts`]：

- **挂起零消耗**：`decide.ts` 的 `RESEND_AT = [0, 1, 3, 7, 15, 25, 35, 45, 55]`（分钟）、`RESEND_WINDOW = 57 * MINUTE` —— 卡片重发是指数退避序列，57 分钟后判定通道放弃。
- **事件溯源**：`evolve.ts` 独占投影写入，`commit` 独占日志追加；投影格式指纹变化时从日志逐条重建，**不写数据迁移**。
- **跳数熔断**：`decide.ts` 中 `const MAX_HOPS = 8`；`hopsOf()` 取事件链上最大 hops；**经人工提问和定时复查也不清零**，Agent 自己改不了。

---

## 2. 能力拆解

### 2.1 自动执行

| 机制 | 设计 [已核实] |
|---|---|
| 事件统一化 | 任何触发器 → 标准事件 `{id, type, subject, summary, detail, link}`，`id`+`type` 必填 |
| 事件幂等 | 「同一来源同一 `id` 只记一次，所以来源尽管重发」——来源侧传 `id`，内核去重 |
| 派活 | 内核按 `rules.json` 匹配 `source` + `types`（支持 `alert.*` 通配） |
| 事项（lane） | 规则 + 对象 → 一个「事项」；`parallel` 写了就按对象分事项 |
| 合并轮次 | 同一事项短时间多条事件合并成一轮，防止并发同改 |
| Agent 抽象 | 「Agent 就是一个进程」——给提示词、打印最后一条消息即可，**不需要 SDK** |
| 一轮不等人 | 「要问人就结束这一轮」，禁止任何让 Agent 阻塞等待的机制 |

**新增 Agent 的成本**：只写一个插件（`command(turn)` / `read(stdout, code, stderr)` / `link(session)` / `check()` 四个方法）。内置 `command` 插件可一行配置接入任意 CLI：`{prompt}` 作为独立参数传递，**不被当作 shell 代码执行**。

### 2.2 任务编排

| 机制 | 设计 [已核实] |
|---|---|
| 规则优先级 | 「规则才是指令」：交给谁、在哪、用什么权限**只由规则决定** |
| `cwd` / `agent` / `access` 注入 | 「事件里带 `cwd`、`agent`、`access` 字段会被直接拒收」 |
| `emits` 白名单 | 回执能发什么事件由规则声明，不写就不能发 |
| `elsewhere` | 「在别处定时跑的任务」——中台不启动，只在 `status` 里列出，需要找人时用 `POST /v1/tell` |
| 队列重取时刷新 | 「排队和等待重试的任务在领取时一起采用最新的 Agent、目录、提示词和权限」 |
| 已领任务冻结 | 「已经领取的任务保留领取时的 Job 配置和接单程序……不随规则更新换人」 |
| 事项不可重拆 | 「事件已经归属的事项不重新拆分或合并」 |

### 2.3 循环重试

| 机制 | 设计 [已核实] |
|---|---|
| 跳数熔断 | `MAX_HOPS = 8`；**人工提问不清零、定时复查不清零**、Agent 不可改；超限只记录不发卡 |
| 重试退避 | `due.ts` 中 `retry` 类到期项来自 `runs.not_before` |
| 租约（lease） | `RUN_LEASE = 5 * MINUTE`：claimed run 超 5 分钟未被 worker 提及即进入「存疑」 |
| worker 心跳 | `WORKER_FRESH = 2 * MINUTE`：worker 超过 2 分钟未报活即视为失联 |
| 失联通知 | `OFFLINE_AFTER = 10 * MINUTE`：等待中的 run 超过 10 分钟无主 → 通知本人 |
| 单一调度器 | `due.ts` 注释：「The shell keeps one timer, for the earliest of them, so nothing has to poll」——**所有到期类型共用一个定时器**，避免轮询 |

### 2.4 状态持久化

| 机制 | 设计 [已核实] |
|---|---|
| 追加式事实日志 | 「所有状态都从一条只追加的日志算出来」 |
| 同事务双写 | 「日志和索引在同一个事务里写进磁盘，写完才应答」 |
| 崩溃安全 | 强杀 1000 次，已确认记录一条不丢（`node sim/crash.ts 1000 12648430`） |
| 无迁移 | 格式指纹变化时从日志逐条重建；`kernel/schema.sql` 只声明查询视图的列，不按版本加迁移文件 |
| 视图可重建 | 「视图随时从日志重建，不能绕过日志改业务数据」 |
| 规模实测 | 110 万条事实时启动 99.8 ms；格式变化后首次全量重建 43.1 秒 |

### 2.5 结果校验

| 机制 | 设计 [已核实] |
|---|---|
| 回执 JSON Schema | `protocol/schema.json` + `protocol/validate.ts` 双重校验 |
| 严格字段白名单 | `only(result, ["outcome","summary","error","session","usage","ask","notice","resolve","later","events"])`——多字段直接拒 |
| 容量上限 | ask≤5 / notice≤10 / resolve≤50 / later≤10 / events≤100 |
| 长度上限 | title≤200、text≤4000、about≤4000、key≤100、resolve 依据≤1000 |
| options 约束 | 2–5 个，每个 ≤200 字；`recommend` 必须是合法序号 |
| `later` 时区 | 必须带时区 `at`；`cancel: true` 时不得带 `at` |
| 写错不重做 | 「万一 JSON 写错了，中台只让它在原会话里重写最后这段回复，**不会把已经干完的业务重做一遍**；重写也失败时，保留原结论并通知你回执没有生效」 |
| 一致性检查 | `protocol/conformance.ts` 做跨模块一致性校验 |
| 变异测试 | `sim/mutate.ts`：变异必须先证明原版测试实际执行且通过，「不拿语法错误当检出」 |

### 2.6 人工干预（Human-in-the-loop）

| 机制 | 设计 [已核实] |
|---|---|
| 触发条件 | `askFirst: ["删数据","停服","花钱","对外发消息"]` — 规则显式声明 |
| 卡片语义 | 带 options = 提问（你选 = 一条新事件）；不带 = 通知 |
| 通道插件 | 桌面通知（默认）/ 飞书 / 钉钉 / 企微 / Slack / Discord（webhook 模板） |
| 回答者鉴权 | `channels.answerers: ["ou_xxx"]`；「通道的回答没核对回答者和原消息」是审查要点 |
| 卡片可续接 | 「尽量接着原来的会话」——`session` 字段跨轮保留 |
| 卡片生命周期 | `open` / `closed`；`resolve` 动作带核实依据；`decide` 幂等（同卡片不能被回答两次、不能被结案两次） |
| 卡片页是纯表单 | 「一个不跑脚本的表单，给只会发文字的通道用」——防「打开链接就算回答」 |
| 失联兜底 | worker 失联 10 分钟后发卡片通知本人 |

### 2.7 日志与可观测性

| 机制 | 设计 [已核实] |
|---|---|
| `why` 命令 | `agent-autoloop why 1` 打印：轮次 / 规则版本 / 触发事件来源·类型·对象 / 领取者 / 结束状态 |
| `/v1/stream` | 规则版本、回答、回执都能通过 HTTP 流读到 |
| 用量统计 | `status` 显示今天与最近 7 天轮数、Token、费用（`cli/spend.ts`） |
| 性能基准 | `npm run benchmark`，达标线按参考机器（M5 Pro / 24GB / Node 24.21.0）定 |
| 实测性能 | 冷启动 88.78ms；空闲 59.94MB RSS；1000 长轮询 170.49MB RSS；持久化写入 2394 条/秒；派活 p99 1.82ms |
| 模拟/穷举 | `node sim/random.ts 24301 200000` 20 万步固定种子可复现；含断网/丢包/崩溃/重复提交 |
| 强杀测试 | `node sim/crash.ts 1000 12648430` |
| 指标脚本 | `scripts/metrics.ts`、`scripts/history.ts` |

---

## 3. 可借鉴点

以下每条都对照我方「蔡工FDE智能交付系统」的**实际现状**（已在源码核实）给出落地方式。

### 借鉴点 1 ★★★：回执 DSL —— 让我方 Agent 的「意图」成为结构化数据，而非自然语言

**它怎么做的**：Agent 只需在最后一条回复附一段 ```agent-autoloop JSON```，声明「我要提问 / 要通知 / 要结案 / 要复查 / 要触发新事件」，内核一次事务内全部生效。

**我方现状**：`agents/service.py::_finalize` 已从 Agent 输出中提取结论，但**没有统一的结构化意图 DSL**。当前 Agent 想要人拍板，走的是 `signoff.py::ensure_pending_signoff` 这条专用路径——每种需要人工介入的场景要单独写一条通道。

**落地方式**：定义我方版本 `fde-receipt` 回执块，挂到 `agents/service.py` 的 finalize 环节：

```json
{
  "ask":       [{"title": "...", "text": "...", "options": ["A","B"], "key": "..."}],
  "notice":    [{"title": "...", "text": "..."}],
  "resolve":   [{"card": 123, "reason": "核实依据 ≤1000 字"}],
  "later":     [{"key": "retry-deploy", "at": "2026-11-05T09:00:00+08:00", "about": "复查上线"}],
  "events":    [{"id": "...", "type": "...", "subject": "...", "link": "..."}]
}
```

配套做**与 autoloop 相同的严格校验**（字段白名单 `only(...)`、容量上限、长度上限、`later` 强制带时区），并把「解析失败 → 只让 Agent 重写最后一段，不重跑业务」这条作为硬规则——它正是我方 `agents/service.py` 里「失败终态拒同键重跑」机制的反面：业务已成功但回执写坏时，不应让业务重做。

**预期收益**：
- Agent 意图从「解析自然语言 + LLM 猜」变成「解析 JSON + schema 校验」，消除一整类误判
- 新增人工介入场景不用改服务端代码，只需扩 DSL 字段
- 直接消除我方「LLM 提议 → 人批准」链路的表达损耗

---

### 借鉴点 2 ★★★：挂起零消耗 —— 把「等人拍板」从「进程占用」变成「状态持久化」

**它怎么做的**：Agent 要问人时，**这一轮直接结束**，进程退出，等待状态存数据库。等人三天不回来，三天零 Token。回答后接上原会话继续。

**我方现状**：
- `workflows/executor.py` 的 `human_approval` 节点已实现「等审批」：`run.status = waiting_approval`，**且 pending 审批行在拍板前不释放**——语义上已经很接近
- 但 `agents/service.py` 的 `MAX_TOOL_ROUNDS = 6` 是**单次运行内的工具轮上限**，与我方 `agents` 模块的「失败终态拒同键重跑」机制一起，形成了「人不在 → 任务挂死或需显式重试」的缝隙

**落地方式**：
1. 在 `workflow_node_runs` 增加 `parked_state` 语义（或用现有 `waiting` 状态 + `attempt` 保留），明确「挂起 ≠ 失败 ≠ 取消」三态
2. 审批等待期不占 worker 槽位——我方 `background_jobs` 队列在 `waiting_approval` 时不应继续持有 worker
3. 恢复时**必须沿用原 `session` 续接**，我方 `agents/service.py` 已有 `_retry_family` / `recover_run`，需明确「挂起恢复 ≠ 显式重试」，保留会话上下文
4. 配套做**卡片重发退避**（autoloop 用 `[0,1,3,7,15,25,35,45,55]` 分钟），避免审批人一天被提醒 20 次

**预期收益**：
- 无人值守夜间跑批时不再空转烧 Token
- 审批 SLA 可观测：能统计「挂起时长分布」，直接暴露流程瓶颈
- 与我方已有 `waiting_approval` 状态合并，零迁移

---

### 借鉴点 3 ★★★：跳数熔断（hops ≤ 8）—— 给自触发链上硬上限

**它怎么做的**：`MAX_HOPS = 8`，事件带 `hops` 字段累加，**经人工提问和定时复查都不清零**，Agent 自己改不了。超限只记录、不派活、发卡告知。

**我方现状（这是最明确的缺口）**：
- `workflows/executor.py` 的 `skill` 节点会触发 Agent，`agent` 节点又调 `agents.service.start_run`，`human_approval` 拍板后**重投 workflow.run**——存在链式自触发路径
- 全局搜索**未见任何 hops / 深度 / 链长限制**
- 我方唯一的轮次上限是 `MAX_TOOL_ROUNDS = 6`（单次运行内工具轮），**不是跨运行的链长**

**落地方式**：
1. `workflow_runs` 增加 `hops` 列，默认 0；每次「事件驱动新运行」时 `hops = 上游 hops + 1`
2. **人工审批不清零、定时复查不清零**（与 autoloop 一致——这是关键，否则人可以绕过限制）
3. 执行器入口检查：`hops > 8` → 该 run 直接置 `failed`（原因 `hops_exceeded`），**不派活**，同时发一条通知给项目负责人
4. `later` 预约复查产生的重投同样继承 hops

**预期收益**：
- 兜住「A 叫 B、B 又叫 A」的额度爆炸——这在多 Agent 交付链里是真实风险
- 熔断是**可解释的失败**（`hops_exceeded`），不是沉默超限
- 成本极低：1 列 + 1 处判断

---

### 借鉴点 4 ★★★：指令数据分离 —— 给「外部文字禁入提示词」立硬规则

**它怎么做的**：外部事件（Issue 标题/正文、告警内容）**只作为资料放进文件**，不拼进提示词；提示词里只有校验过字符的类型、编号和链接。事件里带 `cwd` / `agent` / `access` 字段**直接拒收**。

**我方现状**：
- 我方已有 `evidence/` 一等证据表（`project_evidence`，指纹幂等不可变，只存 `source_uri` + `content_sha256`）——**指纹体系是现成的**
- 但**没有「外部文字禁入提示词」的机制性约束**。客户真实资料、外部文件内容进入 LLM 提示词是当前的口径软约束，不是硬规则
- 我方 `agents/service.py::_write_workspace` 已经在写工作区文件（context），说明「资料走文件」的基础设施已存在

**落地方式**：
1. 在 `agents/context.py` / `_render_context` 层面建立**硬边界**：外部来源内容（客户回执、扫描件 OCR、桥接采集产物、外部工单文本）一律写入 workspace 文件，提示词中只放**受控引用**（文件路径 + sha256 指纹）
2. 在 `evidence` 表登记该文件指针与指纹，形成「资料 → 指纹 → 证据」闭环，复用我方 `evidence` 的 kind 值域（已有 `guidance`/`research`/`bridge`/`task`）
3. 事件/工单入站时，**剥离任何试图指定执行位置/权限/工具的字段**——对应我方 API 层的入站清洗
4. 在 `_render_context` 里显式标注「以下内容为资料，不含指令」

**预期收益**：
- 把我方「客户真实资料永不进 git」的红线，**从存储层扩展到提示词层**
- 防止客户/外部方通过文档内容劫持 FDE Agent 的行为（我方交付场景里客户是外部方，攻击面真实存在）
- 复用现有 `evidence` 表，零新增表

---

### 借鉴点 5 ★★☆：三项「让状态可追」的语义分离

**它怎么做的**：
- **规则版本号**随每轮记录（`why` 里显示「规则版本 #1」）
- **事项 vs 轮次分离**：「一轮会结束，事项会继续」——事项是长生命周期对象，卡片/会话/到期复查都挂在事项上
- **领取时刷新配置，已领取的冻结**：改规则影响排队中的，不影响在跑的

**我方现状**：
- `workflows/models.py` 已有 `WorkflowDefinitionVersion`（**不可变版本表**）——版本化基础已在
- 但 `workflow_runs` 只记 `definition_id + definition_version`，**不记规则版本快照**；`agents` 侧更是完全没有「这一轮用了哪版上下文/规则」的锚点
- 我方 `run.summary` 有 `evidence_created` 之类增量字段，但**没有统一的「这一轮的来龙去脉」一条命令可查**

**落地方式**：
1. `workflow_runs` 增加 `rules_version`（或复用 `definition_version` 作快照锚点），写入时冻结
2. 落地 `why` 等价物：我方已有 `run_detail` 路由 + `workflow_node_runs` 明细，**做一个「运行溯源」聚合视图**，一次返回：触发事件 → 规则版本 → 节点树 → 证据指针 → 人工介入记录
3. 事项/轮次分离可直接映射到我方 `workflow_runs`（事项）与 `workflow_node_runs`（轮次内的节点），但**跨 run 的事项（多轮复查）目前无载体**——若要做「半小时后复查」「持续异常不重复通知」，需要一个类似 autoloop `事项` 的聚合对象

**预期收益**：
- 客户问「上周那版方案为什么被驳回」时，一句话可查清
- 复用现有 `definition_version` + `evidence` 表，不新增表结构

---

### 借鉴点 6 ★★☆：单一调度器 + 到期时间统一计算

**它怎么做的**：`kernel/due.ts` 一个函数算出**所有**类型的最早到期时间（cron / later / retry / delivery 重发 / worker 失联 / 租约到期），外壳只用一个定时器，等最早的。注释明写：「so nothing has to poll」。

**我方现状**：
- `control/scheduler.py::dispatch_due_automations` 负责 cron + interval 派发
- `control/automation_jobs.py` 负责队列消费与失败计数
- `workflows/executor.py` 有 `_recover_interrupted`（handler 入口恢复）
- 但**到期类型是分散的**：定时任务一套、worker 租约一套、`not_before` 重试一套、审批过期判定在拍板时惰性做（我方 AGENTS.md 原文：「过期=拍板时惰性判定」）

**落地方式**：
1. 抽一个 `due_table(session, now)` 服务端函数，统一计算所有到期项的 `(kind, key, at)`，与 autoloop 的 `due.ts` 结构对齐
2. 调度器改为「只等最早的一个定时器」，其余靠同一函数重算——**消除轮询**
3. 把「审批过期」从「拍板时惰性判定」改为**到期表主动扫**，让超时审批能主动提醒（现在只在有人拍板时才检查，等于过期卡片静默悬挂）

**预期收益**：
- 减少无效轮询（我方已是队列驱动，成本不高，但到期逻辑分散会持续生 bug）
- 审批超时可主动暴露，而非静默

---

### 借鉴点 7 ★★☆：回执「写错只重写、不重做业务」的分离

**它怎么做的**：JSON 解析失败时，**只让 Agent 在原会话里重写最后一段回复**，已完成的业务绝不重做；重写也失败则保留原结论 + 通知「回执未生效」。

**我方现状**：我方 `agents/service.py` 的语义是**「失败终态拒同键重跑」**（V8 规则）——这是好的，但它处理的是「业务失败」。**「业务成功 + 回执解析失败」这一档在我方没有明确语义**，可能落到「整轮失败」，导致重试时业务被做两遍（典型：重复发信、重复扣款、重复部署）。

**落地方式**：
1. Agent run 增加明确的 `succeeded_but_receipt_invalid` 终态（或以 `summary` 标记 + `error` 分级区分）
2. 该终态下：**业务结果标记为已完成，重试只允许重写回执**，`idempotency_key` 复用以防业务重做
3. 回执重写上限（autoloop 是「重写也失败就保留原结论并通知」），超过即通知人工，不无限重试

**预期收益**：
- 直接消除「重复外呼 / 重复交付」的尾部风险——我方 `api_actions` 已有 sha256 幂等键，可在此基础上补齐这一档
- 与我方 AGENTS.md 记录的「六铁律」中「幂等/白名单」诉求一致

---

### 借鉴点 8 ★★☆：插件化的四个方向 —— 对应我方「四层可替换」诉求

**它怎么做的**：事件 / Agent / 通道 / 交付四个方向全部插件化，`agent-autoloop add <git 地址>` 安装，只克隆不装依赖不跑脚本。

**我方现状**：我方 `control/` 下有 `mcp_gateway.py` / `clawbot_gateway.py` / `clawbot_weixin.py` / `lcsc_browser.py` / `dsh_runtime.py` 等多套接入层，`api_catalog` + `api_actions` 已是白名单化的能力面，`extensions_service.py` 已有扩展管理。**能力面比它宽**。

**可借鉴的不是「插件化」本身，而是两条纪律**：
1. **「内核不导入插件」**——我方 `control/` 与 `workflows/` 的导入方向需要核验（我方 AGENTS.md 已记：「events.py 顶层引 control.models 实测反转 projects↔control 导入序即环」——**我方已经踩过这个坑**，autoloop 用「内核不导入插件」从架构上根除）
2. **「Agent 就是一个进程」**——我方 `agents/adapter.py` 已有 agent 适配层，但绑定较深；autoloop 只要求「给提示词 → 打印最后一条消息」，接入成本极低

**落地方式**：核验我方 `workflows/`（业务内核）与 `control/`（能力面）的依赖方向，确保内核不反向依赖能力实现；把新 Agent 接入成本压到「一个适配器 + 一份命令配置」。

---

### 借鉴点 9 ★☆☆：交付流水线插件的边界纪律

**它怎么做的**（`plugins/delivery/`，AGENTS.md 原文）：「交付进程**不能检出或运行 PR 的代码、测试、配置、hooks**；只能把裸 Git 对象变成文字快照。默认 Codex 审查忽略用户配置与记忆，保留快照只读沙箱。」「必须保住的事故逻辑：设置只来自 main；分支自己的改动才审查；冲突解决保留；草稿检查不放行；提交或 main 变化不合并；自动合并确认关闭；丢失的合并响应读回；Ship 成功与健康版本一起验证。」

**我方现状**：我方 AGENTS.md 已有强红线——「客户真实资料永不进 git」「密钥不入 VCS」「证据原件永不进仓库」；`pseudonymization` 是 4 个 CI job 之一。

**可借鉴点**：**「审查只看裸 Git 对象，绝不执行被审代码」**——这是我方 CI 链条里尚未明文的一条。如果我方未来让 AI 自动审阅交付物，这条能直接避免「AI 执行了客户提供的脚本」的攻击面。

**落地方式**：在 CI / 自动审查环节加一条断言：审查输入必须是 diff 文本快照，不允许在审查机上执行 PR 分支的任何代码。

---

### 可借鉴点小结表

| # | 机制 | 优先级 | 我方现状 | 落地成本 | 预期收益 |
|---|---|---|---|---|---|
| 1 | 回执 DSL | ★★★ | 无统一 DSL，仅 signoff 单通道 | 中 | Agent 意图结构化，新场景零改码 |
| 2 | 挂起零消耗 | ★★★ | waiting_approval 已有，未做零消耗分离 | 中 | 不空转烧 Token，审批 SLA 可观测 |
| 3 | 跳数熔断 | ★★★ | **完全缺失** | **低**（1 列 + 1 判断） | 兜住自触发链额度爆炸 |
| 4 | 指令数据分离 | ★★★ | 有 evidence 指纹，无提示词硬边界 | 中 | 客户资料禁入提示词，堵注入面 |
| 5 | 状态可追三分离 | ★★☆ | 有 definition_version，无运行快照 | 中 | 运行溯源一条命令 |
| 6 | 单一到期调度 | ★★☆ | 到期逻辑分散 | 中 | 消除轮询，审批超时主动暴露 |
| 7 | 回执写错不重做 | ★★☆ | 「业务成功+回执失败」无语义 | 中 | 防重复外呼/重复交付 |
| 8 | 插件边界纪律 | ★★☆ | 有扩展管理，依赖方向需核验 | 低-中 | 根除导入环类问题 |
| 9 | 审查不执行被审代码 | ★☆☆ | 未明文 | 低 | 堵 AI 审查执行面 |

---

## 4. 局限性

### 4.1 不适合直接照搬的部分 [已核实]

| 项 | 原因 |
|---|---|
| **事件溯源纯追加日志 + 无迁移投影重建** | 我方是 SQL 权威库 + Alembic 迁移体系（当前 27+ rev）。抄它的「无迁移」等于推翻我方全部迁移资产，且我方已有 `definition_versions` 等不可变表设计，与「从日志重放」思路不同 |
| **零依赖极简内核** | 我方是多租户企业系统：项目隔离、RBAC、证据指纹、审批门禁（G1–G9）、审计事件（`workbench/models.py::OperationEvent`）全都要。1651 行内核装不下 |
| **单机单用户假设** | autoloop 的 `rules.json` 在 `~/.agent-autoloop/`，凭据在本地文件，`answerers` 是硬编码白名单。**我方多客户多项目共享一套服务端**，凭据与规则必须落库并按项目隔离 |
| **桌面通知 / 飞书卡片通道** | 我方已有 Electron 桌面端 + 内嵌帮助，通道应是我方 UI 而非飞书 |
| **CLI Agent 直接执行业务** | autoloop 让 Claude Code / Codex 在 `~/code/shop` 里直接改代码跑测试。我方 AGENTS.md 铁律：**交付进程不能检出或运行客户 PR 的代码**；我方已有 `agents/sandbox.py` 沙箱机制。语义相反 |
| **macOS/Linux 限定** | autoloop INSTALL.md 明文「暂不支持 Windows」。我方主战场是 Windows 宿主 + Docker |
| **「Agent 就是一个进程」的极简** | 我方 Agent 有 AI 档位（`agents/quota.py`）、沙箱、工具面、试点报告、会话族等约束，不是「一行命令接入」 |

### 4.2 隐含前提与依赖条件 [已核实]

1. **单机文件系统即状态库** —— 假设 SQLite 本地文件可靠。**整机断电未测**（README 明文：「进程被强杀，已经确认的事不丢（**整机断电没有单独测过**）」）
2. **规则配置是可信本地文件** —— 谁改 `rules.json` 谁就能决定交给谁、在哪干、什么权限。**无多租户、无 RBAC、无审计**
3. **凭据在插件本地** —— 内核不保管凭据是优点，但也意味着**没有集中的密钥轮换/吊销视图**
4. **「Agent 就是一个进程」= Agent 自己管会话续接** —— 依赖各家 CLI 的会话能力（Codex `codex exec`、Claude Code、ACP）。**会话能力不可移植**
5. **事件源可信度未分级** —— HMAC-SHA256 签名是插件级可选能力（示例插件演示），**核心协议不强制**。我方多客户场景下「谁能发事件」必须硬控
6. **中文大模型依赖** —— 内置 agent 插件是 Claude Code / Codex（境外服务），我方客户在境内，**合规与可达性不成立**

### 4.3 潜在风险 [已核实 + 推测]

| 风险 | 说明 | 标注 |
|---|---|---|
| **事件 ID 幂等仅在来源级** | 同一来源同一 id 只记一次。若客户 A 与客户 B 撞 id（不同来源 key 分开，OK），但**同一 source adapter 承载多客户时**需自行加前缀 | 已核实 |
| **`resolve` 可批量关 50 张卡** | 单轮回执可关闭 50 张卡。若 Agent 被诱导签发大批 `resolve`，会静默吞掉待办 | 已核实（上限 50） |
| **`later` 复查链无跳数衰减** | hops 不清零的设计正确，但也意味着**一条永久复查链会持续占事项**（事项不结束） | 已核实 |
| **卡片页是纯表单，链接即权限** | 「打开链接就算回答」被列为审查要点，说明作者已意识到。**但若 `hub.publicUrl` 暴露公网，卡片链接的鉴权强度是薄弱环节** | 已核实（存在风险，作者已列检查项） |
| **作者自陈成熟度** | README 明说：「样例数据都是虚构的；脚本和回执只用本地 HTTP 与假飞书 CLI 验证过，**没有在真实账号上跑过完整业务**」「四种 Webhook 模板**只在本地模拟服务上验证过**」 | 已核实 |
| **Windows 不支持** | 我方主力环境是 Windows 宿主 | 已核实 |
| **境外模型依赖** | 我方客户在境内，合规不可用 | 推测（基于内置插件依赖 Claude/Codex 的事实） |

### 4.4 维护成本 [推测]

- **上游活跃度**：2026-11-03 一天内 5 次提交 + 发 1.0.0，迭代极快 —— **API 演进风险高**，抄机制不抄接口
- **单人维护**：仓库 AGENTS.md 风格高度统一（大量「只写现在需要的」「不要…」），明显是单人主导 —— bus factor 低
- **文档中文口语化**、术语自造（「中台」「批奏折」「挂起零消耗」）—— 抄概念需重新命名，避免中文黑话污染我方代码
- **MIT 协议友好**（已核实 LICENSE 存在，1078 bytes，README 标 MIT）—— 代码可抄，但建议**只抄机制不抄代码**，避免风格与依赖污染

---

## 5. 落地建议

### 阶段一：快速验证（1–2 周，零架构改动）

**目标**：用最小代价验证「自触发链跳数控制」与「回执 DSL」两个最高价值假设。

| 序 | 动作 | 交付物 | 成本 |
|---|---|---|---|
| 1.1 | **给 `workflow_runs` 加 `hops` 列** + 执行器入口检查（>8 置 failed，原因 `hops_exceeded`，发通知） | 1 迁移 + 执行器 1 处判断 + 1 个测试 | **极低** |
| 1.2 | 迁移对照 `definition_service.validate_dag`：**新增「循环链」静态检查**——DAG 定义里若存在 A→B→A 的可执行回路（区别于已检测的环），告警 | 定义校验增 1 条 issue 类型 | 低 |
| 1.3 | **回执 DSL 最小版**：在 `agents/service.py` finalize 环节支持 ```fde-receipt``` 块，只实现 `ask` + `later` 两个动作，严格 schema 校验 | 1 个 parser + schema + 测试 | 中 |
| 1.4 | 在 `workflow_node_runs` 落地「挂起 ≠ 失败」：明确 `waiting` 节点在审批等待期不占 worker 槽位 | 执行器队列策略调整 | 中 |
| 1.5 | 写一份《借鉴裁决单》进 `docs/implementation/`，逐条记录「抄/不抄/改造后抄」及理由，与既有 `v3-backlog.md` 台账对齐 | 1 份文档 | 极低 |

**阶段一验证判据**：
- 构造一个「skill 节点 → agent 节点 → 触发新 run」的测试场景，断言 hops 到达 9 时熔断
- 回执 JSON 写坏时，断言业务结果**未被重做**（幂等键复用检查）
- `later` 预约复查在 Agent 退出后仍能按时触发

### 阶段二：中期改造（1–2 月）

**目标**：把「可追性」和「资料边界」两条主线做实。

| 序 | 动作 | 对应借鉴点 | 成本 |
|---|---|---|---|
| 2.1 | **运行溯源聚合视图**：`GET /projects/{id}/workflow-runs/{rid}/trace` 一次返回触发事件 → 规则版本 → 节点树 → 证据指针 → 人工介入记录；桌面端加「溯源」页签 | #5 | 中 |
| 2.2 | **指令数据分离硬边界**：外部来源内容一律写 workspace 文件 + 登记 `project_evidence` 指纹；提示词只放受控引用；`_render_context` 显式标注「资料非指令」 | #4 | 中 |
| 2.3 | **统一到期表** `due_table(session, now)`：把 cron / 重试 `not_before` / worker 租约 / 审批过期 / `later` 复查统一计算，调度器只等最早 | #6 | 中 |
| 2.4 | **审批主动超时提醒**：审批过期从「拍板时惰性判定」改为到期表主动扫 + 卡片重发退避序列 | #2 #6 | 低-中 |
| 2.5 | **回执 DSL 扩展**：`notice` / `resolve` / `events` 三动作落地；接上 `events` 动作时套用「事件源鉴权 + 剥离 cwd/agent/access 字段」 | #1 #4 | 中 |
| 2.6 | **依赖方向核验**：`workflows/`（内核）不得反向依赖 `control/`（能力面）——我方已踩过 projects↔control 导入环；补一个 CI 静态检查 | #8 | 低 |
| 2.7 | **CI 增一条断言**：AI 审查/自动交付的输入必须是 diff 文本快照，不得在审查机执行 PR 分支代码 | #9 | 低 |

**阶段二验证判据**：
- 外部工单文本（含注入尝试）进入系统后，断言提示词 payload 中**不含**该文本本体
- 审批超时 24h 未拍板 → 自动产生提醒并更新卡片状态
- 任意一条 workflow run 可用一次 API 调用还原完整来龙去脉

### 阶段三：长期规划（3–6 月）

**目标**：从「工作流编排」升级到「交付自动化闭环」，同时保留我方独有的证据与门禁优势。

| 序 | 动作 | 说明 |
|---|---|---|
| 3.1 | **「事项」聚合对象**（对应 autoloop 的 lane/事项）：跨多轮、跨 run 的长生命周期对象，承载持续复查、持续异常不重复通知、卡片与会话归属。我方目前 `workflow_runs` 一轮一 run，缺这层聚合 | 高价值，是「持续巡检」类场景的前置 |
| 3.2 | **交付流水线插件化**：把我方「交付包生成 → 门禁校验 → 证据登记 → 客户通知」做成与 `workflows/` 平行的插件面 | 中 |
| 3.3 | **成本与额度可观测**：run 级 Token/费用归集（我方已有 `chat_cost.py` / `agents.get_cost`，但未按 run/项目维度打通）；对齐 autoloop 的「今天与最近 7 天」口径 | 中 |
| 3.4 | **模拟/穷举/强杀测试体系**：借 autoloop `sim/` 的思路，为我方执行器建「固定种子 N 万步模拟 + 强杀不丢已确认记录 + 变异检查」三件套。我方当前只有 pytest 用例，**缺状态机的对抗性验证** | 中-高，我方最缺的一类测试 |
| 3.5 | **事件入站统一网关**：所有外部触发（客户系统、邮件、企微、任务中心）统一为标准事件 + 签名鉴权 + 幂等 id，避免每加一个来源就开一条新路 | 中 |
| 3.6 | **零依赖内核纪律审计**：借 autoloop `tests/purity.test.ts` 的思路，为我方 `workflows/` 建「内核不 import 能力面 / 不含产品名 / 不读环境」的架构测试 | 低 |

---

## 6. 需要你进一步补充的信息

按优先级排列 —— 前 3 项会实质改变落地路线，建议优先答复。

| # | 问题 | 为什么关键 | 建议格式 |
|---|---|---|---|
| 1 | **近期是否有「自动交付」的真实客户诉求？具体是哪个环节想自动化**（部署 / 验收报告 / 报价收款 / 证据整理 / 客户通知）？ | 决定借鉴点 1/2/4 哪个先做。若是「部署」→ 借鉴点 7（不重做）价值最高；若是「客户通知/复查」→ 借鉴点 1+3.1 | 一句话 + 1 个具体场景 |
| 2 | **客户是否在境内、是否必须走境内模型？** | autoloop 内置 Claude Code / Codex，境外依赖不可用。我方的 AI 档位（`agents/quota.py`）现有模型清单是什么？ | 现有模型清单 |
| 3 | **工作流执行的最大链路深度与单项目并发量？** | 决定 hops 上限取 8 还是更宽，以及「统一到期表」是否值得做 | 数字（没有就估） |
| 4 | **`agents` 模块的 Agent 运行是否已有沙箱隔离？**（我方见 `agents/sandbox.py`）沙箱能否承接「外部资料入文件、只传指纹」的改造？ | 直接决定借鉴点 4 的落地成本 | 沙箱边界一句话 |
| 5 | **人工拍板当前走哪条 UI？** 桌面端任务中心 / 企微 / 邮件？是否已有卡片式交互？ | 决定借鉴点 2「挂起零消耗」的 UI 落点 | 现状描述 |
| 6 | **是否接受引入「回执 DSL」这一新的 Agent 输出契约？** 会影响既有 Agent Skill / 提示词模板的编写口径 | 借鉴点 1 是改动面最大的项，需要你拍板 | 同意 / 分阶段 / 不同意 |
| 7 | **本轮是否允许新增 1 个迁移（`hops` 列）？** 我方红线是「改 server + 新迁移 ⇒ rebuild 后必 `alembic upgrade head`」 | 借鉴点 3 的最小落地依赖此迁移 | 允许 / 本轮不允许 |
| 8 | **是否需要我把本报告并入 `docs/implementation/v3-backlog.md` 的下一轮台账（T-P0-2 / T-W7 之类编号）？** | 保持与既有 V3 实施节奏一致 | 编号与命名建议 |

---

## 7. 附：本报告的证据来源清单 [已核实]

| 文件 | 用途 |
|---|---|
| `README.md` | 定位、流程、插件表、四个内核机制、实测性能、仓库目录 |
| `README.en.md` | 英文对照（未逐条引用） |
| `AGENTS.md` | 内核边界、审查要点、插件与交付边界、验证范围 |
| `INSTALL.md` | 安装流程、平台限制、验证流程、卸载 |
| `docs/protocol.md` | 六个词、六条原则、规则 schema、来源协议、卡片、到期待办、性能口径 |
| `docs/plugins.md` | 插件四方法契约、浏览器接入、最小模板 |
| `kernel/decide.ts` | `MAX_HOPS = 8`、`RESEND_AT` 退避序列、事实与 draft 机制 |
| `kernel/due.ts` | `RUN_LEASE` / `WORKER_FRESH` / `OFFLINE_AFTER`、单一定时器 |
| `protocol/validate.ts` | 回执 schema 校验、容量与长度上限 |
| GitHub Trees API（commit `cecec75b`） | 188 条文件路径全表 |

**我方对照代码**（已核实）：`server/src/fde_api/workflows/{models,executor,definition_service}.py`、`control/{scheduler,automation_jobs,ai_tool_loop,service}.py`、`agents/{service,signoff}.py`、`evidence/models.py`、`workbench/models.py::OperationEvent`
