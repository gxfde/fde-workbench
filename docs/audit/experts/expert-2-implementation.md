# 代码实现官评审意见

> 本轮为独立代码级评审，所有结论均以 2026-11-06 实测（`Read`/`Grep`/命令输出）为准。凡「上轮已核验、本轮未重跑」的次要行号标注〔未复核〕；Q1/Q2/Q5/Q6/Q7 相关行号全部重跑实测。
> 说明：本文件为 party mode 多专家评审的代码实现官产出（上轮 429 截断后重跑补齐）。

## A. 总评

方案**整体方向与事实基底扎实**（现状校正 §2 的行号命中率极高），但本轮深挖出 **4 项 P0 事实错误**，集中在被用户重点关注的 Q5/Q6/Q7：

1. **Q7 最重**：方案断言「服务端零改动，纯桌面端工作量」——实测 `agents/` 与 `meetings/` **都没有 run 列表 / 会议列表端点**（只有单详情），UI 无法渲染列表，**服务端必须先补列表接口**，「零改动」不成立。
2. **Q5 provider 配置根因写错**：`zcode-builtin.json` **其实存在**（在 `resources/config/provider/`，不是方案写的 `resources/glm/provider/`）；真实问题是「CLI 查找路径与安装位置错位」，拷一份到 `D:\config\provider\` 即修复（已实测修复后进入模型调用，报 429 是 MiniMax Token Plan 上限，与 zcode 无关）。
3. **Q5 ZcodeAdapter 契约错位**（方案未察觉）：`adapter.py` 的 `spawn_argv` 按 `zcode run --task --output --events ndjson` 调用，但**真实 zcode 0.17.1 没有 `run` 子命令、没有 `--task/--events`**；真实形态是 `zcode -p --mode --json --cwd --resume` 或 `zcode app-server`（stdio ZCode Protocol）。适配器 CLI 调用段必须重写。
4. **G2 缺口误判**：方案称「presurvey 的 S3 前置闸未见落地」——实测 `_require_s3_gate`（`guidance/service.py:402`）已在 `presurvey-source`/`create_analysis` 强制调用，**S3 闸（G3=passed，SOW-A 签署+A 款到账+授权书四项）已实现**（以内部前置闸形态，非独立路由）。这个「缺口」实际不存在。

此外 **Q6「复用 openfde」与 Q5「zcode 优先」存在逻辑缝**：openfde 的 `executors.ts` 只有 `claude/codex` 两个 executor，**全仓对 zcode 零命中**，openfde 承载不了 zcode 执行；且服务端是 Linux 容器、**subprocess 不到 openfde（Windows Node 工具）**——这正是既有 `bridge/` 模块用「宿主侧采集器」模式的原因。方案 Q6 的「编排」侧目前**无现成调用契约**，bridge 只同步 status 统计。

**Q2 红线原文不可考**：方案引用的 `leads/forms/_TEMPLATE-初诊记录.md:4` 在主仓**不存在**；somwyn FDE.md 的「S2」实为交付里程碑 slice（线索回收与 P1 实证），其 `Never violate` 段**无「录音」条目**（grep 0 命中）；AGENTS.md 红线有「代号化」但**无「录音不可存」**。Q2 的拍板依据悬空，需用户补红线原文出处后才能成立。

## B. 代码级断言核验表

| 方案中的断言 | 位置 | 实测结果 | 判定 |
|---|---|---|---|
| Q5：zcode 有 `-p/--prompt`、`--mode`(build/edit/plan/yolo/guarded)、`--cwd`、`--json`、`--resume`、`--disallowed-tools`、`--target`、`--workflow-mode` | §10 Q5「依据」 | `zcode.cjs --help` 实测**全部存在**；`--mode` 默认 yolo；**另发现 `app-server`（ZCode Protocol stdio）命令方案未提** | ✅ 成立（且可加 app-server 作为更适合适配器的契约） |
| Q5：`--json` 输出为机器可解析事件流 | §10 Q5 | `--help` 仅注「Print machine-readable JSON where supported」；实跑被 429 截断**未取到 stdout 格式** | ⚠️ 未验证（风险项，见 F） |
| Q5：provider 配置 `zcode-builtin.json`「缺失」 | §10 Q5 ② | **文件存在于 `D:/software/zcode/resources/config/provider/`**（260KB，35 个 templateId）；CLI 实查 `resources\glm\provider\` 与 `D:\config\provider\` 两候选路径均无 ⇒ 报错真实。**根因＝查找路径错位，非文件缺失** | ❌ 根因写错（修复已实测：拷到 `D:\config\provider\` 通过 provider 定位） |
| Q5：zcode 不在 PATH，需 wrapper | §10 Q5 | `command -v zcode` 无结果；全局只有 `openfde`/`node` | ✅ 成立 |
| Q5：`agents/service.py:182` `if agent.kind != "zcode"` → `adapter_missing` | §10 Q5 | `service.py:182` 实测为 `if agent.kind != "zcode" or agent.kind not in ADAPTER_KINDS: return "adapter_missing"`（`ADAPTER_KINDS={zcode,codex,claude_code,opencode}`，`adapter.py:25`） | ✅ 基本成立（「唯一可用 kind」准确，其余三家在注册表但无 executor 落 adapter，走 L 降级） |
| Q6：`executors.ts` 362 行；`:127` claude-code、`:62` claudeArgs(权限档)、`:200` codex、`:137` codexArgs(沙箱档)、`:321` offline executor | §10 Q6「依据」 | **行号逐一命中**，接口形态属实 | ✅ 成立，**但遗漏关键点：executor 集只有 claude/codex，无 zcode**（`grep -ri zcode` 全仓 0 命中） |
| Q6：工作台只做编排与留痕，openfde 负责 worktree/agent 进程/权限 | §10 Q6 | 留痕侧已有 `bridge/`（宿主采集 4h 投影 status）；**但「编排执行 `openfde run task`」无现成契约**，且 Linux 容器 subprocess 不到 openfde（`bridge/__init__.py:3` 明示） | ⚠️ 半成立：留痕有，编排契约缺（需新建宿主侧采集器触发） |
| Q6 是否踩 #4 purity 边界 | §10 Q6 | `fork/main:server/tests/test_architecture_purity.py`（B#4·#130）**只扫描 `workflows/` 包**（顶层不 import control.service/routes、内核不读 env/flask、无产品名）；`agents/`、`bridge/` 不在其范围 | ✅ 不踩（Q6 边界与 #4 无交集；注意该文件在 fork/main，本地 main 分支暂无） |
| Q7：agents 11 路由 | §10 Q7 / §2.1 | `@agents_blueprint` 实测 **11 条**，行号 42/53/60/67/75/84/97/104/111/118 全部命中 | ✅ 条数与行号成立 |
| Q7：meetings 8 路由 | §10 Q7 / §2.1 | `@meetings_blueprint` 实测 **10 条**（创建/详情/插话/关闭/纪要/模板/清单/暂停/恢复/成本）；docstring 自述「9 路由」 | ⚠️ 条数错（实 10，方案写 8） |
| Q7：服务端接口已齐备，**零改动**，纯桌面端工作量 | §10 Q7 | **不成立**：`agents` 无 `GET /runs` 列表端点；`meetings` 无 `GET /meetings` 列表端点。run 列表/会议列表 UI 需服务端先补列表路由 | ❌ 事实错误（P0） |
| Q7：`_serialize_run`/`list_tool_calls`/`get_cost` 足以渲染 run 详情/tool-calls/cost | §4.2 / Q7 | 详情含 `status/token_cost/duration_ms/degraded/fallback_level/artifacts(sha256/reviewed)`；tool-calls 含 `decision/capability/reason/duration_ms/denied_count`；cost 含 scope。**足以渲染详情/tool-calls/cost 面板**；但**无 diff/test_results/commit/known_risks**（即 §4.2 所列结构） | ✅ 详情类成立；§4.2 完整结构需 G7 新字段（方案自认差距，一致） |
| Q1：`redact_text`（`redaction.py:22`）做手机号/邮箱/证件脱敏，故意不脱企业名 | §10 Q1 | 实测：`redact_text` 脱 email/mobile/idcard/landline，**疑似凭据（密码/api_key/token）直接 raise 422 拒收**，确**不脱企业名** | ✅ 成立（方案「脱敏」表述准确，补充：凭据是拒收非脱敏） |
| Q1：`check-pseudonymization.sh:91` 中文 2–15 字 + 公司/集团/厂 结尾正则；`:104` pg_dump；`:206` enterprise_code 三段式 | §10 Q1 | `:91` 实测 `perl 'while (/([\x{4E00}-\x{9FA5}]{2,15}(?:公司\|集团\|厂))/g)'`；`:104` `pg_dump --data-only --inserts`；`:206` `check_code_format` enterprise_code 点计数 =2 | ✅ 全部成立 |
| Q1：presurvey 走 `ai/kimi.py:204` `extract_docx_xml_text`，**完全绕过脱敏** | §10 Q1 / G 缺口 | **确认「调用链不存在」**：`redact_presurvey`（`redaction.py:31`）**全仓零调用点**；presurvey `create_analysis` 走 `enqueue_outbox("project.presurvey.analyze")`→AI 提取（kimi.py:204），该链无 `redact_text/redact_presurvey`。唯一 `redact_text` 调用点在 `ai/project_draft.py:67`（项目草稿，非 presurvey） | ✅ 判定成立（presurvey 链确实零脱敏） |
| Q2：S2 红线原文在 `leads/forms/_TEMPLATE-初诊记录.md:4` | §10 Q2 / G8 | **该文件主仓不存在**（`leads/` 目录空/无）；somwyn FDE.md「S2」=交付 slice（线索回收与 P1 实证），`Never violate` 段**无「录音」项**；AGENTS.md:8 有代号化红线但**无「录音不可存」** | ❌ 引用位置错误 + 红线原文不可考（需用户补出处） |

## C. 逐条比对表（对照借鉴总览）

> 注意：总览 §6.5 的 **Q1–Q18** 与本方案的 **Q1–Q7 是两套独立编号**（前者=借鉴清单决议，后者=商务改造决议）。下表按「选型/原则」比对，**不**做 Q 号一一对应，防误读。

| 借鉴总览要点 | 方案中的位置 | 判定 | 问题描述 / 证据 |
|---|---|---|---|
| §0/#20 DSH「维持现状：不装、不换执行体」（`dsh_enabled=False`） | §10 Q5「DSH 不作为第二家编码智能体」 | **已一致** | 方向吻合：DSH 在仓库是独立 AI Server 编排层（`control/dsh_runtime.py`），非编码执行器，Q5 判其「与编码执行器不同位置」准确 |
| §6.5 Q5（fde-gym 评测「不引每 run 一容器与境外模型」） vs 方案 Q5「zcode 跑沙箱容器」 | §10 Q5 | **存在冲突（实为编号撞车，领域不同）** | 总览 Q5 针对**评测夹具**（#23/#24/#25）；方案 Q5 的「沙箱容器」是**既有 `sandbox-runner`**（`compose.yaml:130`，per-run 容器+tmpfs+network none，已落地），**二者不同域**。⚠️ 待澄清：建议由用户裁决在方案 Q5 标注「zcode 沙箱＝工作台既有 sandbox-runner，与总览 §6.5 Q5『fde-gym 评测不引容器/境外模型』决议无关」，防读者误读为冲突 |
| §6.5 Q7（移植形态＝内部自检夹具） vs 方案 Q7（桌面控制台） | §10 Q7 | **已一致（无冲突，编号撞车）** | 总览 Q7 指 fde-gym 产物形态；方案 Q7 指桌面 UI。二者独立，无张力，仅编号易混 |
| §1 #4 purity 架构测试（锁 `workflows/` 边界） | §10 Q6「工作台只做编排与留痕」 | **已一致** | 实测 #4 只扫 `workflows/`；Q6 在 `agents/`/`bridge/` 侧动刀，**不踩 #4 边界**。方案无需为此改动 |
| §1 #12/#31（外部文字禁入提示词 / 原件-派生分离 / 导入零 AI 调用，P1 本轮可排期） | §10 Q1「入库自动代号化替换」 | **存在冲突（需澄清）** | Q1「同一词典双向复用」的词典源＝`/d/test/FDE/leads.md`（**真相层**），而 §5.3 红线「执行面不可触真相层」＋AGENTS.md:8「真实资料只留本地 fdeops/openfde 工作目录」。⚠️ 待澄清：建议由用户裁决——**代号化替换层须为非-AI 纯函数（字典匹配）**（合 #31「导入零模型调用」），且**企业名词典须从 leads.md 抽到 DB/仓库供执行面读，不得让沙箱挂真相层**；方案「直接复用同一份 leads.md 词典」需改口径 |
| §1 #2（zcode 会话能力未核实，repair 降级为默认） + §6.6「zcode CLI 会话续接」采集项 | §10 Q5「`--resume <sessionId>` 已存在」 | **存在冲突（能力判定越位）** | `--resume` 参数**存在**≠「会话续接行为」已验证。总览 §6.6 把「zcode 会话续接」列为平台 owner 待采集项、#2 明确「未核实则以降级路径为默认」。⚠️ 待澄清：建议由用户裁决——方案 Q5 不宜据此宣称 zcode 已具备会话续接，应先按 §6.6 跑小样本核查再启用 |
| §7 许可硬条款（无 LICENSE/AGPL 只译设计不复制正文） | 全文 | **已一致（不触及）** | 方案只涉自有工具（zcode/openfde 皆本机自研/已装），未引入 §7 受限第三方正文，无冲突 |
| §5 实施节奏四态（已兑现/可排期/零载体/封存，B# 编号） | §7 实施顺序（商务改造五阶段） | **已一致（独立体系，需声明）** | 方案「阶段一/二/三」是**商务改造排期**，总览 B# 是**借鉴登记排期**，两套编号独立（总览文首明说）。⚠️ 待澄清：建议由用户裁决在方案 §7 注一句「本文阶段与总览 B#/§5 四态为独立排期体系，不互相覆盖」 |

## D. 必须修改项（P0/P1/P2 排序）

**P0（事实错误，不改即误导实施）**
1. **Q7「服务端零改动」改为「需先补服务端列表端点」**：`agents` 增 `GET /api/v1/agents/runs`（按 project/status/时间过滤＋分页），`meetings` 增 `GET /api/v1/meetings`（按 project 过滤）。否则 run 列表/会议列表 UI 无数据源。方案 §10 Q7「服务端零改动，纯桌面端工作量」「落地约束：零路由新增」**两处需回写**。
2. **Q5 provider 配置根因订正**：改为「`zcode-builtin.json` 存在但 CLI 查找路径（`resources\glm\provider\`、`D:\config\provider\`）与安装位置（`resources\config\provider\`）错位；修复＝部署一份到 `D:\config\provider\`（实测通过 provider 定位，后续 429 系 MiniMax Token Plan 上限，非 zcode 配置问题）」。
3. **Q5 增补 ZcodeAdapter 契约重写项**：`adapter.py:91 spawn_argv`（`zcode run --task --output --events ndjson`）**与 zcode 0.17.1 真实 CLI 不匹配**（无 `run` 子命令/`--task`/`--events`；真实为 `-p/--mode/--json/--cwd/--resume` 或 `app-server` stdio）。方案须把「重写 ZcodeAdapter 的 CLI 调用段对齐真实接口」列为 Q5 落地项，而非仅「满足三要件」（三要件是参数级，未覆盖调用契约形态）。
4. **G2 订正为「非缺口」**：S3 前置闸已由 `_require_s3_gate`（`guidance/service.py:402`）在 `presurvey-source`/`create_analysis` 强制实现（G3=passed，含 SOW-A 签署+A 款到账+授权书四项）。方案「第一阶段第 3 条：presurvey 的 S3 前置闸落地」改为「S3 闸已实现，若需暴露独立查询接口再另立」；§2.3 G2 行标注「实际已实现，缺口不成立」。

**P1（逻辑缝/边界，需澄清）**
5. **Q6 与 Q5 逻辑缝**：openfde 无 zcode executor（全仓 zcode 0 命中）。Q5「zcode 唯一优先」＋Q6「复用 openfde」并存时，二选一须写明：① zcode 走工作台自有 `ZcodeAdapter`（仅复用 openfde 的 worktree 生命周期＋`AgentEvent` 归一协议＋`RunRow` 留痕），或 ② 给 openfde 新增 zcode executor（改 openfde 源码，非工作台）。建议①，方案须明示。
6. **Q6「编排」无现成契约 + 进程边界**：bridge 只同步 status 统计，`openfde run task` 执行编排无契约；且服务端 Linux 容器 **subprocess 不到 openfde**（Windows Node 工具，`bridge/__init__.py:3` 明示）。Q6 落地须走「宿主侧采集器」模式（POST 命令→宿主跑 openfde→POST 快照回），方案「依赖 openfde 常驻可用」需扩为「依赖**宿主侧采集器**＋openfde 常驻＋新建编排快照契约」。
7. **Q1 代号化词典源触红线**：`leads.md`（真相层）作词典源与 §5.3「执行面不可触真相层」冲突。需改为「词典抽至 DB/仓库、执行面读 DB」，并声明「代号化替换＝非-AI 纯函数层」（合 #31 导入零调用纪律）。
8. **Q2 红线原文锚定**：方案引用的 `leads/forms/_TEMPLATE-初诊记录.md:4` 主仓不存在；somwyn FDE.md「S2」为交付 slice 非「录音红线」。需用户补「不录音转写入库」红线的**真实仓库出处**，Q2 拍板（录音不存、转写文字可入库）方可成立；当前 G8「S2 红线与本方案冲突点」标注为「原文出处待补」。

**P2（精度/表述）**
9. meetings 路由数 8→**10**（`meetings/routes.py`：含 cost/pause/resume）；guidance presurvey 链路由数「8」→实测更多（含 `GET /guidance` :94）。
10. Q2「MiniMax purpose 枚举（只有 voice_clone/prompt_audio/video_understanding）」实测为 **5 项**（另含 `t2a_async_input`/`video_generation_input`，`kimi.py:39-42`）；「无 ASR 项」结论仍成立，枚举列举需补全。
11. Q5 标注「`--json` 事件流格式实测被 429 截断未验证」「`--resume` 会话续接待 §6.6 小样本核查」为风险项，避免「zcode 可直接接 ZcodeAdapter」被读成已验证。

## E. 可选优化项
- **zcode `app-server`（ZCode Protocol stdio）** 比「`-p --json` 一次性」更契合适配器的持续事件流需求，建议 Q5/§5.1 把 `app-server` 列为首选契约形态（`--help` 实测存在 `app-server Run the ZCode Protocol stdio app server`）。
- openfde 的 `AgentEvent` 归一协议（`executors.ts:13-27`：session/message/tool/tool_result/stderr/error/result）＋ `RunRow` 字段集（`runs.ts:21-48`，含 `cost_usd/turns/exit_marker/log_path`）可直接作为工作台 `agent_artifacts`/run 详情补 diff/test_results 时（G7/§4.2）的**字段参照**——比在 Flask 侧重造更省力，且与 #30/#31 留痕纪律同构。
- G7「run 产物→交付包」可对齐 openfde `RunRow.worktree`（branch/ahead/dirty）＋ `worktreeStatus`（`worktree.ts`）现成语义，减少自研。

## F. 待澄清的开放问题与风险清单

| # | 类型 | 问题 | 建议裁决方 |
|---|---|---|---|
| F1 | 待澄清（P0 衍生） | Q7 服务端「零改动」判定与实测（无 run/会议列表端点）矛盾，**是漏看还是有隐藏列表端点**？我未在任何文件找到 `GET /agents/runs`/`GET /meetings` 列表。 | 用户（拍板后我补列表端点设计） |
| F2 | 待澄清（P0 衍生） | ZcodeAdapter 重写目标：对齐 zcode `-p/--json` 还是 `app-server` stdio？（方案未选） | 用户（选型） |
| F3 | 待澄清 | zcode provider 修复方式：永久部署到 `D:\config\provider\`，还是打进沙箱镜像/以 wrapper 注入（§5.3「版本钉死」）？ | 用户（部署口径） |
| F4 | 待澄清 | Q6 走「openfde 加 zcode executor」（改 openfde）还是「工作台 ZcodeAdapter + openfde 仅管 worktree」（不改 openfde）？ | 用户（边界） |
| F5 | 待澄清 | Q1 代号化词典：抽到 DB（执行面读 DB）还是保持读 leads.md（触真相层红线）？替换层是否确认「非-AI 纯函数」？ | 用户（红线口径） |
| F6 | 待澄清 | Q2「不录音转写入库」红线的**真实仓库出处**（方案引的 `leads/forms/_TEMPLATE-初诊记录.md:4` 不存在）；补出处前 Q2 拍板是否可成立？ | 用户（补出处） |
| F7 | 风险 | zcode `--json` 事件流格式未验证（429 截断）＋ `--resume` 会话续接未核实（§6.6 采集项）。ZcodeAdapter 接法须待二者实测通过。 | 平台 owner（§6.6 采集） |
| F8 | 风险 | openfde `serve` 默认端口 4517、`run` 默认 2h 超时/10m stall——与工作台沙箱纪律（超时熔断/心跳 kill）对齐度需在 Q6 落地时实测核对。 | 编排实施时验 |
| F9 | 备注 | `test_architecture_purity.py`（#4）在 **fork/main**，本地 main 分支暂无；Q6 若动 `workflows/` 须对齐 fork/main 权威版。 | 已知（权威＝fork/main） |
| F10 | 备注 | Q5/Q7 与总览 §6.5 Q5/Q7 **编号撞车但领域不同**（fde-gym 评测 vs 工作台沙箱/UI），建议在方案加注防误读。 | 文档标注 |

---
**结论**：方案现状基底（§2 行号）可信度高，**可评审通过但须先修 4 项 P0**（Q7 列表端点、Q5 provider 根因、Q5 adapter 契约重写、G2 误判）与 **4 项 P1 澄清**（Q6×Q5 缝、Q6 进程边界、Q1 词典红线、Q2 红线出处）。**不得建议与总览已定选型矛盾的做法**——上述均按总览「维持 #20 不装 DSH、#4 只约束 workflows/、#12/#31 导入零调用、§7 许可硬条款」校准，无一处越线。
