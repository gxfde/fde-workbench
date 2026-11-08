# 蔡工FDE智能交付系统 · 整套架构图（archify 取证生成）

用 **archify**（v3.2.0，`~/.agents/skills/archify`）从本仓库**真实代码取证**生成的六个视角架构图（2026-11-08 全量同步 + 新增第六图「降级与失败路径」）。
每张都是**独立 standalone HTML**（内联 SVG、暗/亮主题、可导出 PNG/JPEG/WebP/SVG/WebM、带路径/透镜视图），
`candidate.json` 为生成输入，`receipts/` 为该图**通过那一轮**的 finalize/browser-check 回执，
`<name>.delivery.json`（交付回执）**必须与 HTML 同目录**——`check --require-provenance` 按同目录找 sidecar，
放错目录会得到 `provenance: unknown`，
`preview.png` 为 **1440px 宽整页实拍**（含图、卡片与节点索引，非首屏截图）。六张的 `validate / deliver / check / browser-check` 四闸全绿、0 诊断。

> 仓库全程**只读**生成，本目录只放产物与证据，不改动任何业务代码。

## 入口

- [index.html](index.html) —— 汇总页，五张图卡片入口 + 规模/取证版本速览。

## 五张图

| 视角 | 目录 | 图 | 规模 | 取证 revision |
|---|---|---|---|---|
| architecture | `architecture/` | 系统总体架构 | 14 节点 / 16 连接 / 4 边界 | `e66647b` |
| workflow | `workflow/` | 交付主流程：从项目到回款 | 16 节点 / 19 边 / 6 车道 | `e66647b` |
| sequence | `sequence/` | Workflow run 一次执行的完整调用链 | 8 参与者 / 42 消息 / 10 段 | `e66647b` |
| dataflow | `dataflow/` | 集成桥采集 → 服务端投影 → 一等证据登记簿 | 12 节点 | `e66647b` |
| lifecycle | `lifecycle/` | Workflow 运行生命周期状态机 | 14 态 / 22 迁移 | `e66647b` |
| degradation | `degradation/` | 降级与失败路径：故障 → 判定 → 兜底与人工 | 12 节点 / 8 边 / 3 车道 | `e66647b` |

打开任意 `<type>/<type>-*.html`（或 `index.html`）即在浏览器中查看；每张 HTML 自带主题切换与导出控件。

## 取证版本说明

2026-11-08 全量刷新（架构评估 P2-7 + 第六图）：六张统一钉 `e66647b`（含 P1-2 工作流执行器拆分、
P2-5 蓝图注册表单一真身、P3-9 桌面发起运行）。
当时实测口径与 AGENTS「当前状态」逐位一致：**49 蓝图 / 391 路由 / 130 表 / 51 rev（head e9c4a1f7b3d2）/
49 蓝图注册 app.py::_BLUEPRINT_SPECS（28-101）**。口径漂移由 `scripts/audit/check_archify_diagram_freshness.py`
机械拦截（见下「防陈旧闸」）。
链接模式为 `local-only`：fork/main 领先 upstream（gxfde），web 链接会指向不存在的上游 revision；
SRC 标记保留 文件路径+行号+revision，可在本仓 checkout 下复验。

## 文档口径纠偏（以代码为准，写进图里）

- run 层起始态是 **`queued`**（不是 `pending`）；`paused` 仅存于 CHECK 值域、执行器永不写入。
- 发起路由是 `POST /projects/{pid}/workflows/{def_id}/runs`；`/workflow-runs` 只是列表/详情/取消/恢复面。
- 桌面控制台能列/详情/取消/恢复，**也能发起 run**（P3-9：已发布定义卡上的「启动」按钮，can_manage 显隐）。
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

### 整图完整性（preview.png 验收，2026-11-08 截断事故的永久防线）

archify `visual-check` / `browser-check` 的截图是**固定视口首屏实拍**（1440×900 等），
高图（本目录 sequence/architecture/workflow 三张）首屏装不下——2026-11-08 曾因此交付过
底部被截断的 preview.png（HTML 本体完整、滚动可达全部内容，但预览图「整个图不完整」）。
规则：

- **preview.png 必须整页实拍**：`tools/capture-full-preview.mjs` 先由页面实测
  scrollHeight，再以 `Page.captureScreenshot{captureBeyondViewport:true}` 一次拍全，
  逐张断言 PNG 高度 ≥ 页面高度（PASS/FAIL 输出，任一 FAIL 退出码非 0）。
- 重拍命令（在 `archify-diagrams/` 下）：

  ```bash
  ARCHIFY_CHROME="/c/Program Files (x86)/Microsoft/Edge/Application/msedge.exe" \
    node tools/capture-full-preview.mjs sequence/*.html architecture/*.html workflow/*.html dataflow/*.html lifecycle/*.html
  ```

- 拍完**逐张目检底部**（图例 / 卡片 / 节点索引必须入画）。四闸全绿 ≠ 整图完整，
  完整性以预览实拍为准。

## 防陈旧闸（P2-7：把「图纸落后一轮」变成机器检查）

图纸是特别容易过期的文档——它的内容是**结构快照**，而结构每轮都在变。此前五张图钉在
fork/main `58f7a26`，其后主干又并入了 V3.1 P0/P1 与商业化 G1 等多轮，图里的
「47 蓝图 · 384 路由」「128 表」早已过期，而**没有任何机器能发现它**（文档口径纪律管的是
「引用时现测」，管不了「图上已经写着的旧数字」）。

新增 `scripts/audit/check_archify_diagram_freshness.py`（stdlib only）：

- 逐张读 `*/candidate.json`，抽出图上出现的「N 蓝图 / N 路由 / N 表 / N 迁移」，
  与本仓**唯一的机器可读结构口径** `docs/audit/v3-workbench-inventory.json` 逐项对账，
  **漂移即红**（宁红不漏）；
- `meta.repository.revision` 必须是 40 位十六进制（钉住取证基线）；
- 每张图必须同时有候选与已渲染 HTML（半张图不算交付）。

```bash
python scripts/audit/check_archify_diagram_freshness.py          # 人跑
python scripts/audit/check_archify_diagram_freshness.py --json   # CI 跑
```

处置：按 inventory 改图里的数字 → 重跑 archify finalize（输出路径已存在时加
`--out-dir <folder>/review-<n>`）→ 整页实拍 preview.png → 三样一起提交。


## 硬约束备忘（archify v3 取证/排版）

- 桌面可读性下限：viewBox 宽 ≤ **992px**（1440 视口 930px 图宽预算，6px 投影字号下限）；超宽会撞 `composition/desktop-readability`。
- 反向/回环边共用走廊会撞 `composition/ambiguous-corridor`；解法常是**结构**（把被闸控的节点挪进同一车道）而非加显式 `via` 几何。
- `meta.views` 在 `meta` 下，不在顶层。
- workflow：同一泳道同一列的多个节点**必须**各自写 `yOffset`（渲染器不自动堆叠，否则撞
  `workflow/node-overlap`）；跨泳道的斜边容易撞 `composition/proper-crossing`——解法是**结构**：
  把边改成只向右、上下泳道用短边（第六图即按此重排：列=阶段、边只向右、扇出不跨泳道）。
- workflow（readable-v2）装饰性 semantic-sigil 会被画到 viewBox 底缘之外（v3.2.0 实测至 +173 单位，画高不计 sigil）；节点/边/标签等真实内容不受影响。用 `meta.viewBox` 加高会翻转车道独立测量模式（实测要求 1010×3193 重排），得不偿失，维持不修、如实记录。
