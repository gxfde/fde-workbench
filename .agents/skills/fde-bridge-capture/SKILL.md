---
name: fde-bridge-capture
description: Runbook for triggering and verifying a manual integration-bridge (集成桥) capture run in the FDE workbench. Use whenever the user asks to 采集 / 手动采集 / 立即采集 / 跑一轮桥 / 采集没反应 / bridge poll / FDE-Bridge-Poll / 看看桥的最新快照 — covers schtasks trigger with Git Bash double-slash, log location, why server changes need an image rebuild, and the read-only discipline of the collector.
use_boundaries.when_to_use: 用户要求采集/手动采集/立即采集/跑一轮桥，或采集没反应需要核实桥的最新快照时
use_boundaries.when_not_to_use: 与集成桥采集无关的日常排查，先走 system-health 与日志定位，不要把本 runbook 当通用运维入口
references.required_reading: ["scripts/bridge-poll.mjs", "AGENTS.md"]
references.authoritative_sources: ["AGENTS.md"]


---

# FDE 集成桥手动采集 runbook

目标：触发一轮采集并确认新快照到站。采集器是 `scripts/bridge-poll.mjs`（openfde 只读 CLI + fdeops 文件探针 → POST `/api/v1/bridge/snapshots`），**只能跑在 Windows 宿主**（openfde CLI 是 Win 版 Node 工具，Docker 容器内的后端 subprocess 不到它）。

## 触发方式（二选一，同一代码路径）

**命令行（Git Bash，注意双斜杠防路径转换）：**

```bash
schtasks //Run //TN "FDE-Bridge-Poll"
```

**桌面端：** 集成桥页 →「立即采集」按钮（`desktop/src/main/bridge-capture.ts` 内部执行的就是 `schtasks /Run /TN FDE-Bridge-Poll`，非 Windows 平台直接报 `bridge_platform` 错）。

触发是异步的：计划任务起进程 → bridge-poll.mjs 采集 → 推服务端 → 集成桥页约 1–3 分钟内自动刷新出新快照。

## 验证到站

```bash
tail -20 logs/bridge-poll.log
```

成功行样例：`推送成功：run xxxxxxxx，engagement N 个，unlinked …，orphan 项目 …，vanished …`。
桌面端集成桥页看「最近采集时间」是否刷新到刚才。

## 排障

| 症状 | 处置 |
|---|---|
| `schtasks` 报任务不存在 | 宿主先跑 `scripts/install-bridge-poll-task.ps1` 安装（每 4 小时周期任务） |
| 日志 `FAIL 服务端拒绝（HTTP 4xx）` | 多为 `FDE_BRIDGE_TOKEN` 与 `server/.env` 不一致或容器没重启（见下） |
| 日志 `FAIL 推送失败（服务端不可达）` | 后端容器没起：`docker compose ps` 查 |
| 触发成功但页面 3 分钟不刷新 | 查宿主 `logs/bridge-poll.log` 是否还在跑（CLI 超时 60s/命令）；再查桌面端轮询 |

## 改过 server/ 之后必读

采集是把快照推给**容器里的 API**。服务端代码烤进镜像——`docker compose up -d` 单跑无效，必须：

```bash
MSYS_NO_PATHCONV=1 wsl -d Ubuntu-24.04 -- docker compose build
MSYS_NO_PATHCONV=1 wsl -d Ubuntu-24.04 -- docker compose up -d
# 有新迁移再：docker compose exec api alembic upgrade head
```

## 纪律红线

- `bridge-poll.mjs` **只读**：只调 openfde 只读 CLI + 读文件，绝不写真相层；不要给它加任何写路径。
- 采集只在 Windows 宿主跑；CI/Ubuntu 上相关测试必须显式传 platform（可注入）。
- `--check` 模式（ orphan 项目 > 0 退出码 2）是铁律巡检，不要改动其语义。

## 契约键语义锚

- required_reading（执行前必读）：scripts/bridge-poll.mjs、AGENTS.md——AGENTS.md「集成桥手动采集」节是命令与纪律的唯一权威；scripts/bridge-poll.mjs 是被调用的采集器本体（只读纪律在其头部声明）。
- authoritative_sources（冲突裁决）：AGENTS.md——技能正文是操作化展开，冲突以权威为准。
