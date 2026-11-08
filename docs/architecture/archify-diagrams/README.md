# 蔡工FDE智能交付系统 · 整套架构图（archify 取证生成）

用 **archify**（v3.2.0，`~/.agents/skills/archify`）从本仓库**真实代码取证**生成的五个视角架构图（2026-11-08 全量同步 fork/main）。
每张都是**独立 standalone HTML**（内联 SVG、暗/亮主题、可导出 PNG/JPEG/WebP/SVG/WebM、带路径/透镜视图），
`candidate.json` 为生成输入，`receipts/` 为该图**通过那一轮**的 finalize/deliver/check/browser-check 回执，
`preview.png` 为 1440×900 亮色截图。五张的 `validate / deliver / check / browser-check` 四闸全绿、0 诊断。

> 仓库全程**只读**生成，本目录只放产物与证据，不改动任何业务代码。

## 入口

- [index.html](index.html) —— 汇总页，五张图卡片入口 + 规模/取证版本速览。

## 五张图

| 视角 | 目录 | 图 | 规模 | 取证 revision |
|---|---|---|---|---|
| architecture | `architecture/` | 系统总体架构 | 14 节点 / 16 连接 / 4 边界 | `58f7a26` |
| workflow | `workflow/` | 交付主流程：从项目到回款 | 16 节点 / 19 边 / 6 车道 | `58f7a26` |
| sequence | `sequence/` | Workflow run 一次执行的完整调用链 | 8 参与者 / 42 消息 / 10 段 | `58f7a26` |
| dataflow | `dataflow/` | 集成桥采集 → 服务端投影 → 一等证据登记簿 | 12 节点 | `58f7a26` |
| lifecycle | `lifecycle/` | Workflow 运行生命周期状态机 | 14 态 / 22 迁移 | `58f7a26` |

打开任意 `<type>/<type>-*.html`（或 `index.html`）即在浏览器中查看；每张 HTML 自带主题切换与导出控件。

## 取证版本说明

2026-11-08 全量刷新：五张统一钉 fork/main `58f7a26`（V3.1 P1-1 宿主执行通道轮）。
当时实测口径与 AGENTS「当前状态」逐位一致：**47 蓝图 / 384 路由 / 128 表 / 50 rev（head e7c4a9d2f6b8）/ 47蓝图注册 app.py:44-133**。
链接模式为 `local-only`：fork/main 领先 upstream（gxfde），web 链接会指向不存在的上游 revision；
SRC 标记保留 文件路径+行号+revision，可在本仓 checkout 下复验。

## 文档口径纠偏（以代码为准，写进图里）

- run 层起始态是 **`queued`**（不是 `pending`）；`paused` 仅存于 CHECK 值域、执行器永不写入。
- 发起路由是 `POST /projects/{pid}/workflows/{def_id}/runs`；`/workflow-runs` 只是列表/详情/取消/恢复面。
- 桌面控制台能列/详情/取消/恢复，**不能**发起 run。
- resume / 拍板重投 **hops+1 继承不清零**，入口超 `MAX_RUN_HOPS=8` → 409 `hops_exceeded`（B#1 跳数熔断）。
- 取消后在途分派返回**不静默丢弃**：节点终态不复活，落 `cancelled_after_dispatch` 标记（CR-022）。
- 节点成功同事务挂**门禁证据候选**（产物自带 `gate_evidence` 四元组才挂，平台不派生指纹，T-W7）。
- 交付方案 plans：draft→approved→published **双点退位**（同一时刻至多一个 published，审查人≠生成人，V3.1 P0-3）。
- 结项封包 handover：draft→sealed→delivered，**delivered 终态不可逆**，deliver 仅 admin（T-B1 #196）。
- 访谈转写 transcripts：只入草稿区（不可引用、T+7 自动清理），客户确认晋升纪要才进正式库（T-A9）。
- lifecycle 已迁移 **archify schema v3**（mainPath 单主链 + 分支下沉，渲染器管几何；v2 lanes/cols 已废）。

## 复跑校验

`receipts/` 里的 `.finalize-summary.json` / `.browser-check.json` 是该图通过轮的完整回执。
若要重新校验一张图（需 archify + 本机 Edge 作浏览器驱动）：

```bash
export ARCHIFY_CHROME="/c/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"
cd docs/architecture/archify-diagrams/<type>
node ~/.agents/skills/archify/archify/bin/archify.mjs check <type>-*.html --require-provenance
```

`candidate.json` 是 archify 的 typed JSON 输入；重渲染用
`... finalize <type> candidate.json <type>-*.html --repo-root <repo> --quality showcase`。

## 硬约束备忘（archify v3 取证/排版）

- 桌面可读性下限：viewBox 宽 ≤ **992px**（1440 视口 930px 图宽预算，6px 投影字号下限）；超宽会撞 `composition/desktop-readability`。
- 反向/回环边共用走廊会撞 `composition/ambiguous-corridor`；解法常是**结构**（把被闸控的节点挪进同一车道）而非加显式 `via` 几何。
- `meta.views` 在 `meta` 下，不在顶层。
