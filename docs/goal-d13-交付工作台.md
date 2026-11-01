# goal-d13 · 交付工作台拍板轮：交互式定案 11 项 + 三件代码实施

> 输入：蔡工指令「继续，需要拍板就使用交互式选择方式解决」+ goal-d12 报告（fork/main `a87de24`，开工前 fetch 到 `08076d8`——并发会话 PR #64 docs/nf-agents-main-pointer 已并入）+ 承前挂账全表（台账节三十三～三十七）。隔离 worktree `D:\test\fde-workbench-d13`（branch `feat/goal-d13`，基线 `08076d8`），主树与并发 worktree（`D:/test/fde-workbench-nf`）零触碰。

## 一、拍板轮：11 项全定案（AskUserQuestion 交互式，三批）

d12 收口时工程欠账已全清，剩余全部是待拍板类（7 项）与数据回流类（3 项）。本轮按蔡工指令把**全部拍板项以交互式选择逐项定案**，无一顺延、无一发明：

| # | 拍板项（挂账出处） | 结论 | 性质 |
|---|---|---|---|
| 1 | 翻译管道 provider kimi 化（d9#3） | **直接切 kimi-k3** | 本轮实施（A） |
| 2 | export-sow×signoff 强制关系（d9#4） | **仅 agent_assisted 包强制** | 本轮实施（B） |
| 3 | artifacts reviewed 翻转语义（d9#5） | **approved 自动翻转** | 本轮实施（C） |
| 4 | 撤销声明既有 run 处理（d8#4） | **保持不回溯**（溯源三点成链已可查） | 销号零代码 |
| 5 | T6 阈值定值与开启（d11①） | **维持 0=关**，试点数据回流后 O-8/UM-5 评审定值 | 记录+顺延（定值明确归入数据回流） |
| 6 | T6-lite 模板内容审定（d11②） | **审定通过**（d11 注册版即定稿） | 销号零代码 |
| 7 | D10②九卡原句 | **改写为检查问句**（SOP 原句不进代码库） | 纪律定稿零代码 |
| 8 | D10③报价卡数值禁区 | **维持核对要点制**（模板零公式零系数零数值） | 销号零代码 |
| 9 | D10④G3 会闸关系 | **拍板前人核**（S3 纪要辅助拍板不作门证据；现状语义） | 销号零代码 |
| 10 | D10①S 编号映射 | **确认 PartyMode §2.1 场景矩阵为准**（代码现状） | 销号零代码 |
| 11 | D10⑤审定流程 | **本次交互即审定**（模板内容维持现状） | 流程闭环 |

拍板结论回写：《D10会议模板内容蒸馏准备_SOP来源映射.md》（文档中心）§三 全五项+附注标注结论；`docs/试点执行手册-runbook.md` §4/§8 更新（T6-lite 已审定、阈值定值明确待数据回流）。

## 二、三件实施（零迁移：head `c3e7a9b1d5f4` 22 revision 不变）

**A·翻译管道切 kimi-k3**（`config.py` + `translator/jobs.py` + `system_configuration.py` + `.env.example` + 桌面端系统配置页）
- `kimi_translator_api_key`（Secret）+ `kimi_translator_model`（默认 `kimi-k3`）独立槽位——key 与预调研分开配，换档不互相牵连；`deepseek_translator_model` 删除（干净切换，非双栈并存）。
- **补正（合并后发现，见 §三）**：槽位再加一条独立 `kimi_translator_base_url`（默认 `https://api.moonshot.cn/v1`）——base_url 也要独立，否则部署 env 把共享 `FDE_KIMI_BASE_URL` 指向别家兼容端点时，翻译会拿 `kimi-k3` 打一个没有该模型的端点。桌面端系统配置页同步补「翻译管道 API 地址 / 模型 / 密钥」三项（原先 `kimi_translator_model` 未在 UI 可见，管理员无法在页面改槽位）。
- 客户端仍走 `DeepSeekClient`——本体是通用 OpenAI 兼容 JSON 客户端（请求体仅 model/json_object/max_tokens 三参数，无厂商专有字段），换 base_url/key/model 即换供应商；不配 fallback（kimi 槽位无备用模型，失败走本模块重试语义）。
- 无 key 行为：请求发出前即分类失败 `ai_service_not_configured`（不可重试），绝不裸 500、不卡 running、`ai_model` 不虚标。
- 注入键 `fde_api_translator_deepseek` → `fde_api_translator_ai`（provider 中立）；system_configuration PUBLIC/SECRET_FIELDS 登记两新键。

**B·export-sow 仅 agent_assisted 强制 signoff**（`solutions/service.py` export_sow）
- 闸链：`DeliveryPackage.solution_id == solution.id AND agent_assisted` 命中 → 该方案须有 `signoff` checkpoint `approved` → 否则 409 `solution_signoff_required`。
- **闸在复用路径之前（严格口径）**：未 approved 的 AI 协同方案一个字节都不出系统（含既有导出的重取）；纯人工方案（无包或 agent_assisted=False）完全不受影响。
- 只读 `DeliveryPackage`（派单 8 态机零触碰），无任何派单写路径。

**C·signoff approved 自动翻转 reviewed**（`solutions/service.py` resolve_signoff）
- approved 时：`linked_solution_id == solution.id`（**终审通道内产物**）且 `reviewed=False` → `True`；拦截/降级留痕（`linked=None`）与 rejected 均不翻转。`reviewed` 此前无任何置 True 路径（服务端只有 C-1 拦截置 False），本闸即人工核验完成的正式入口——AI 不代拍板红线不破（approved 本身就是人工拍板行为）。
- `solution_signoff_resolved` 事件新增 `artifacts_reviewed_flipped` 计数（审计可反查）。

**测试**（+6：translator 1 + signoff 5）：kimi 槽位无 key 分类失败 / approved 翻转 linked 产物+事件计数=1 / rejected 零翻转+计数=0 / agent_assisted 未 approved 409 / 纯人工越过闸落 design 校验 / approved 后闸开。注入键改名 5 处 + `ai_model == "kimi-k3"` 断言钉默认档。

## 三、验证（全实测）与过程如实登记

| 项 | 结果 |
|---|---|
| 服务端 pytest | **1706 收集 = 1700 passed + 6 skipped**（d13 基线 1698=1692+6，本轮 +2 补正用例 +6 拍板用例） |
| 桌面端 vitest | **730/730**（60 文件；补正轮改系统配置页 UI，零用例新增） |
| typecheck | 零错误 |
| mypy 基线门 | `scripts/check-python-types.py` 过（基线 289 / 当前 279 无新增）· ruff `F401,F841` 全过 |
| 变异 | **5/5 红**（m1 模型错标 / m2 翻转决策反转 / m3 翻转范围去守卫 / m4 闸条件反转 / m5 事件计数归零）；红判定 selftest 7/7 先行；old 串 apply 前 count==1 断言（5 锚点全唯一预核）；restore sha256 字节级断言零失败 + grep 残留复核全 0 |
| 容器（合并后） | 四容器 healthy；`/api/v1/health/ready` 200（database ok / redis ok）；`alembic current` = `c3e7a9b1d5f4 (head)`（22 revision，d13 零迁移）；镜像重建后代码内 kimi 槽位 / 导出闸 / 翻转逻辑实装核验通过 |

### d13 首轮过程如实登记

①export 新用例首跑用错未认证 `d4_client` 吃 401（改 `leader` 包装器修正）；②helper 引用模块级 `d4_settings` fixture 函数（非解析值）AttributeError——helper 显式收 settings 参数修正；③测试库 socat 隧道（fde-pg-forward→twenty-db）一次「server closed unexpectedly」抖动，复测自愈非代码问题；④pytest 跑动触发 `template_manifest.json` 重写，内容与 fork/main 字节级 identical（hash 比对），M 标记为 stat 脏位，checkout 清除；⑤**本地漏跑 mypy → CI server-tests 门挂**（`Result[Any]` 无 `rowcount` attr-defined ×1）——翻转实现改「select 先数 ids 再 update」，`check-python-types.py` 过（基线 289/当前 279 无新增）+ ruff 过 + 14 用例复跑全过；**流程教训：mypy 门必须与 pytest/vitest 同批本地跑，不能只靠 CI 兜底**。

### 合并后补正轮（发现 → 判定 → 补正 → 复验）

**发现**：PR #65 合并（fork/main `f661ca4`）后核对部署 env，发现 `server/.env` 把共享 `FDE_KIMI_BASE_URL` 覆写为 `https://api.minimaxi.com/v1`（预调研实际跑 `MiniMax-M3.1-Flash`）。d13 首版实现让翻译管道**共用**该 base_url ⇒ 配好 key 后，翻译请求会带 `model=kimi-k3` 打到 minimaxi 端点，而该端点没有 kimi-k3 → 拍板的「切 kimi-k3」在当前部署下无法真正成立。

**判定**：这是**实施与拍板语义不符的缺陷**（不是新的待拍板项，不发明拍板结果）。拍板原话已是「直接切 kimi-k3 + 独立槽位、换档不互相牵连」，故按该语义补正：**翻译槽位 base_url 也独立**。

**补正内容**（分支 `feat/goal-d13-translator-baseurl`）：
1. `config.py` 新增 `kimi_translator_base_url`（默认 `https://api.moonshot.cn/v1`，与默认模型 kimi-k3 自洽）。
2. `translator/jobs.py` 客户端改取翻译槽位自己的 base_url（不再取共享 `kimi_base_url`）。
3. `system_configuration.py`：`PUBLIC_FIELDS` / `URL_FIELDS` 登记新键（管理员可在系统配置页改，走 URL 校验）。
4. 桌面端 `SystemConfigurationPage.tsx` 补「翻译管道 API 地址 / 模型 / 密钥」三项（补正前 `kimi_translator_model` 在 UI 完全不可见，管理员改不了槽位）。
5. `.env.example` 增 `FDE_KIMI_TRANSLATOR_BASE_URL` 与「若沿用共享端点须同步改模型名」的提示。
6. 测试 +2：①客户端构造取的是翻译槽位 base_url（共享槽位指向别家时仍取本槽位）；②翻译槽位 base_url 默认与 kimi-k3 自洽且改它不动共享槽位（env 无关断言）。

**复验**：pytest 1706 收集全绿 · vitest 730/730 · typecheck 零错误 · mypy 门无新增 · ruff 全过 · 容器重建后四容器 healthy + READY 200 + alembic head 不变。

**补正轮过程如实登记**：
①**PR #66 首版 CI server-tests 门挂 ×2**（约 1 分钟即红 → mypy 门）——根因：补正轮新增两个用例写在我**跑完 mypy 门之后**，新增用例里直接 `Settings()` 构造（该类 `database_url`/`redis_url`/`jwt_secret` 为必填）⇒ mypy 新增 6 处 `call-arg`（基线未覆盖）→ 门拦下。修法：用例改用 fixture 的 `d4_settings.model_copy(update=...)`（不重跑构造器）→ 本地 mypy 门重跑「无新增（基线 289 / 当前 279）」+ ruff 全过 + 目标用例 19 全绿后重推。**这条正是 d13 首轮教训的同款复发**：mypy 门必须与 pytest/vitest **同批**跑，且「改完代码再改测试」后必须**重跑**该门，不能沿用上一批结论。
②**本地全量 pytest 首跑 1675 errors**（31 passed）——根因是本地 shell 未设 `FDE_TEST_DATABASE_URL`（.env 只在 `FDE_DATABASE_URL` 里内嵌口令，无独立 `FDE_DB_PASSWORD`，conftest 的回退路径取不到口令 → 全部 DB 用例 setup error），非代码问题；改为显式指向 `127.0.0.1:15432` 隧道后复跑全绿。
③`test_transient_error_backs_off_and_fails_classified` 在与桌面 vitest 并行时计时抖动失败 1 次，单跑复现为通过——计时敏感用例，负载下波动，非改动引入。
④新增用例首版断言写成「翻译槽位默认 base_url ≠ 共享槽位默认 base_url」而两者默认值本就相同（都是 moonshot）→ 改为「改翻译槽位不动共享槽位」的独立性断言。
④**mypy 门事故复盘（承前 d13 教训）**：首轮起 mypy 与 pytest、vitest **同批本地跑**，首轮未再出现「本地漏跑、CI 兜底翻红」——但补正轮**又复发一次同款**（新增用例写在 mypy 门跑过之后 ⇒ CI 翻红，见补正轮登记①）。**教训升级**：该纪律不只在「开工时」成立，**每次改动（含只改测试）后都要重跑 mypy 门**，上一批的结论不可沿用。
⑤容器内实装核验时 `docker exec` 偶发 WSL 服务超时（`0x8007274c`，`docker ps` 同时正常）——改用宿主同代码核验 + 容器日志无 Traceback，判定为环境抖动非代码问题。


## 四、不做边界与遗留

- **不做**：kimi 真实联调（需蔡工在 `server/.env` 配 `FDE_KIMI_TRANSLATOR_API_KEY`；若不落 Moonshot 端点则同时配 `FDE_KIMI_TRANSLATOR_BASE_URL` 与该端点实际支持的模型名；配前翻译提交会分类失败——预期行为）；export-sow 全量强制（拍板只选 agent_assisted 面）；rejected 反向处理（拍板未选）；撤销声明任何回溯（拍板保持不回溯）；std-full 档模板 / U6 全量归集 / retry 折算（数据回流类原样顺延）。
- **剩余顺延（全部数据回流或人工）**：一次通过率 retry 折算 / U6 全量成本归集 / std-full 档独立门模板 / T6 阈值定值（→ O-8/UM-5 人工评审输入）；试点前置 = iptables+zcode CLI 联调检查单执行（蔡工人工）+ 翻译槽位 key/端点/模型配置 + 试点数据回流。
- **新挂账**：无。
