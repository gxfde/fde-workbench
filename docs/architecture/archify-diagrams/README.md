# 蔡工FDE智能交付系统 · 整套架构图（archify 取证生成）

用 **archify**（v3.0.1，`~/.agents/skills/archify`）从本仓库**真实代码取证**生成的五个视角架构图。
每张都是**独立 standalone HTML**（内联 SVG、暗/亮主题、可导出 PNG/JPEG/WebP/SVG/WebM、带路径/透镜视图），
`candidate.json` 为生成输入，`receipts/` 为该图**通过那一轮**的 finalize/deliver/check/browser-check 回执，
`preview.png` 为 1440×900 亮色截图。五张的 `validate / deliver / check / browser-check` 四闸全绿、0 诊断。

> 仓库全程**只读**生成，本目录只放产物与证据，不改动任何业务代码。

## 入口

- [index.html](index.html) —— 汇总页，五张图卡片入口 + 规模/取证版本速览。

## 五张图

| 视角 | 目录 | 图 | 规模 | 取证 revision |
|---|---|---|---|---|
| architecture | `architecture/` | 系统总体架构 | 14 节点 / 16 连接 / 4 边界 | `46dfd4f` |
| workflow | `workflow/` | 交付主流程：从项目到回款 | 13 节点 / 15 边 / 6 车道 | `46dfd4f` |
| sequence | `sequence/` | Workflow run 一次执行的完整调用链 | 8 参与者 / 42 消息 / 10 段 | `9bc342e` |
| dataflow | `dataflow/` | 集成桥采集 → 服务端投影 → 一等证据登记簿 | 12 节点 | `05f3773` |
| lifecycle | `lifecycle/` | Workflow 运行生命周期状态机（双层） | 14 态 / 21 迁移 | `46dfd4f` |

打开任意 `<type>/<type>-*.html`（或 `index.html`）即在浏览器中查看；每张 HTML 自带主题切换与导出控件。

## 取证版本说明

生成期间本仓库被另一工作流（goal-c2 / T-O4b）推进，五张图分别钉在各自取证时的 HEAD：
`46dfd4f`（3 张）/ `9bc342e`（sequence）/ `05f3773`（dataflow）。
已核对这几个版本之间**被引用的源文件字节完全一致**（`git diff --stat` 为空），证据在五个 pin 下均成立。

## 文档口径纠偏（以代码为准，写进图里）

- run 层起始态是 **`queued`**（不是 `pending`）；`paused` 仅存于 CHECK 值域、执行器永不写入。
- 发起路由是 `POST /projects/{pid}/workflows/{def_id}/runs`；`/workflow-runs` 只是列表/详情/取消/恢复面。
- 桌面控制台能列/详情/取消/恢复，**不能**发起 run。

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
