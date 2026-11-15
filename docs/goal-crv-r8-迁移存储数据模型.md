# goal-crv r8 轮记录：迁移·存储·数据模型（终稿）

> 循环：goal-crv ｜ 轮：r8 ｜ 域：迁移·存储·数据模型（工作流 27 文件逐行＝storage 5＋files 8＋documents 11＋transcripts 1＋jobs/reconcile＋previews/processors；直审 23 文件＝meetings 5＋evidence 4＋metrics 4＋documents/catalog.py＋**guidance 9〔分配表 row 41 主域补审，2026-11-13 增补〕**；迁移链主会话脚本核）｜ 审查时点基点：`35ffbea`（各片核验 git diff 基点零差异）
> 审读方式：CreateWorkflow 四片（run `dwfrun-11a05b48`）＋主会话直审＋迁移链静态核（73 文件＝73 revision、单头 `b5d9e2f4a7c1`、零悬挂 down_revision、全链可达无孤立——与 AGENTS 口径逐位一致）
> **结论一句话**：存储层安全基座扎实（validate_object_key 拒绝性规范化/五状态机 fail-closed/防穿越双闸/签名键域分离/M4-D 24 调用点接线零漏网唯 .head( 一处）；迁移链完整单头；guidance/translator 脱敏主干（闸①分层/闸②词典/输出兜底/复核闸）机械纪律在位但**复核事件账携带企业名明文**与**脱敏面覆盖不对称**（录入卡零脱敏＋人工编辑不复扫）两处 needs-decision；真实缺陷集中在**双 P1**（富文本契约断裂＝编辑器正文全丢、complete_upload 完整性错误未映射＝上传会话永久卡死）、**M7 懒收场全程幻影**（收场写入随请求回滚永不落库）与文件/文档链的并发与资源面——P1×2／P2×13／P3×3（合并 ~20 锚），零 P0。

## 1 覆盖声明（§6 三档如实列）

- **逐行读：50 文件**＝工作流四片 27（存储与文件基础 12／文件服务与转写 4／文档生成巨件 3／文档模板与快照 8）＋主会话直审 23（meetings 5／evidence 4／metrics 4／documents/catalog.py／**guidance 9：service 573＋jobs 299＋models 136＋redaction 207＋routes 99＋ai_schema 93＋docx_extract 52＋ai_prompt 59＋enterprise_dict 110＝1,629 行**）。meetings/service.py 1428 行单批全读。
- **抽查：0**（佐证读——layout.py 翻译面/extensions/app teardown/测试钉 grep——在 ShardReport notes 如实标注，不计逐行档）｜**没读：0**（guidance/translator 全闭合；translator 6 文件随 guidance 交叉面一并读毕）。
- 四片合规声明在案（零执行/零写/未触禁区/基点零差异）；E0＝P1×2 双证据重读（rich_text.py:80-89/163-167＋DocumentEditor.tsx:180-198＋draft_service.py:378-379:705-706＋generator.py:328-346；service.py:295-312/455-466/838-869＋models.py:63-68/121-123/201-203）＋P2×13 锚点逐一重读＋P3 归并入族。
- **覆盖缺口自纠（2026-11-13）**：分配表 row 41 `guidance/` 主域＝r8，初版工作流与直审面均未纳入——r8 PR 开启前补审闭合（§2.5 闭合性硬要求）；本节即终版声明。

## 2 QR 台账（r8 增量 · 单一真身在总报告附录）

**本轮新增 QR-117～134（18 条）**：

### P1（2 条，E0 双证据确认）
| QR | 锚点 | 标题 |
|---|---|---|
| QR-117 | rich_text.py:163-167 ↔ DocumentEditor.tsx:196-198 | **桌面/服务端富文本键名契约断裂：编辑器正文逐块静默丢弃**——桌面 plainToRichText 产 `{type:"paragraph",text}`（读回也读 text），服务端 `_clean_text(raw_block.get("content"))` 只认 content 键，非字符串→空→`continue`；draft_service.py:378 先 sanitize 后存⇒`draft.rich_text_json` 被覆写为空形态，重载显示为空、generate 同读⇒正文 100% 不进 DOCX。自 v0.1.0（5ded7b3）即损坏；服务端测试钉 content 键形状、桌面零钉——集成契约无钉。判级 P1（趋近 P0 的草稿数据破坏面）。**〔2026-11-13 随批 F 升格 P1→P0 并 CLOSED：`rich_text.py` 优先读 `content` 兼容 `text`，`DocumentEditor.tsx` 改发规范 `content` 并兼容服务端数组回读形态，端到端契约钉入 `test_crv_batch_f.py`＋`project-documents.test.tsx`〕** |
| QR-118 | files/service.py:857 | **complete_upload 新建 ProjectFile 撞 display_name 唯一约束 → IntegrityError 未映射且 multipart 已终结⇒会话永久卡死**——同名同 category 上传（display_name 缺省取文件名主干）必触发：首次 500、重试恒 422 invalid_parts（manifest 已删）、abort 恒 400；rename 面有 `except IntegrityError→409`（:461-462）而 complete 面漏——同文件不对称实证；_next_version_number（:862-869 无锁）并发同 file_id 撞版本唯一同路径。**〔2026-11-13 批 F CLOSED：`complete_multipart` 前 `_preflight_upload_target` 预检 404/409＋并发 `IntegrityError→409`＋`head(storage_prefix)` 重放与 `abort_upload` 幂等清理〕** |

### P2（11 条，E0 锚点逐一重读确认）
| QR | 锚点 | 标题 |
|---|---|---|
| QR-119 | documents/version_service.py:836 | 预览存在性探测 head() 直连逻辑键绕过布局翻译——同函数签名走 existing_read_key+layout（:841-847），read_new+ 态预览面整体假故障；M4-D 静态钉 marker 集漏 .head( |
| QR-120 | files/expiration.py:121 | 过期上传清理 sweep 窗口饿死——cleanup 成功只写 completion_json 不改 status，终态 expired 行永居候选集按 expires_at 升序占满 limit=100 ⇒ 新到期行永不进窗，远端 multipart 永不回收（静默存储泄漏） |
| QR-121 | files/service.py:80 | create_upload_session 在 DB 事务内 begin_multipart——并发同 idempotency_key 撞唯一约束 500（无回放）＋回滚后孤儿 multipart 目录零清理路径（B#13-B 链触达不到未入库会话） |
| QR-122 | files/service.py:224 | complete 的 placement copy 失败误报 422 invalid_parts——存储故障与 parts 校验共用错误码；dual_write 第二目标网络失败→用户被误导「分片无效」，会话同入不可恢复态 |
| QR-123 | documents/generator.py:239/836-839 | DeepSeek 同步网络调用在 handle_document_generation 的 DB 事务内——worker 连接 idle-in-transaction 跨整个外部调用（最坏 2×超时），并发生成线性放大池占用（T-13′ 泄漏连接持锁堵塞运维事故同型先例） |
| QR-124 | documents/draft_service.py:751-757 | 建议文档名拼接后未截断——「项目计划及进度-{project.name}」/「SOW-{机会名}」在模型 String(160)（workbench/models.py:260、research/models.py:219）合法名 >80 触发误导性 422「请填写文档名称」，项目计划/PoV-SOW 创建整链不可用 |
| QR-125 | documents/version_service.py:1177-1193 | D4 草稿下载门禁只护专用端点——_signed_download 不查 version.status，序列化面对 draft 版本系统性签发 300s URL；测试钉自相矛盾（:532/:548 钉端点 409 vs :588-590 钉列表 draft 带 download_url）（判级存疑：可辩刻意两层语义，D4 注释无此限定） |
| QR-126 | documents/version_service.py:340-396 | confirm_document_version 不校验目标版本有可交付字节——生成失败版本（sha256=""、占位 uploading）可被确认成 confirmed；document.status=confirmed 而下载恒 409（既有 fixture 依赖此行为，无刻意声明） |
| QR-127 | documents/project_routes.py:241-273 | 手工修订上传链路无体积上限——file_storage.read() 全量进内存＋base64 解码无界＋testzip 全量解压（解压炸弹）；files 面 100MB 闸同系统内口径缺口，全仓无 MAX_CONTENT_LENGTH |
| QR-128 | meetings/service.py:1142-1168/1031-1034 | **M7 懒收场全程幻影**：收场写入随请求回滚永不落库——读路径（get_meeting/get_minutes/get_meeting_cost 无 begin()）flush 后 session close 回滚、写路径 reap 后主操作 raise 同事务回滚；连锁：超时 live 会议 close_meeting 恒 409 minutes_already_sealed 死循环（幻影 auto 纪要挡道，永不可人工封存）、resume 409 谎称「已自动收场」；两测试假绿见证（test_meeting_orchestration.py:256-277 同事务读回）。E0 双证据：全服务零 commit＋sessionmaker 无 teardown＋_mark_meeting_degraded_now 独立事务先例对照 |
| QR-129 | evidence/service.py:417-440 | execution_facts 三源查询全量 .all() 无 SQL 级 LIMIT——project_evidence＋operation_events＋ai_call_audits（只增日志表）全表拉内存排序再截前 N，与 docstring「有界」口径漂移；counts 需求可用 count() 聚合替代 |
| QR-133 | guidance/jobs.py:82-96＋translator/service.py:112-124/translator/jobs.py:124-134＋service.py:397-409 | **redaction_review 事件账携带企业名明文入库**——复核条目（`{"name": <原文>, occurrences, matched_dict}`）随 `OperationEvent.changes` 落库：词典命中（matched_dict=True）＝部署态真实客户名（现场词典经 `FDE_ENTERPRISE_DICT` env 指本地文件，enterprise_dict.py:6-7）＋疑似名正则原文；采纳流（:397-409）把条目**再次**写入新事件；测试钉断言 name 在场（test_guidance_redaction_worker.py:175／test_guidance_retry.py:532）＝既有设计。复核闸功能需要名字（人工核对替换）vs 红线「数据库只存代号」字面——**needs-decision**（指纹化复核清单 UI 反解 or 红线例外登记） |
| QR-134 | guidance/service.py:468-486＋:159-187＋models.py:26-33 | **T-A2 脱敏面覆盖不对称**——①presurvey 录入卡 customer_vision/notes（各 2000 字自由文本）零脱敏直落库（save_presurvey_intake 无 redact 调用；models docstring 声明「不触碰 S0–S2 红线」属豁免声明非机械闸，而同类别 translator 表单有三道闸）；②update_analysis 人工 PATCH 编辑正文零复扫——**AI 产出的已脱敏草稿可经人工编辑重新引入真名**，confirm 复核闸（:255）只聚合 AI 阶段清单，编辑引入的新名字既不替换也不进复核清单（第四条绕行路，前三道闸全部作废于该面）——**needs-decision**（录入卡豁免成立则登记；编辑面至少补输出端扫描） |

### P3（3 条合并 ~20 锚——§5 规矩 5）
- **QR-130 上传/转写/会中健壮性族**（6 锚）：files/service.py:68 幂等回放不比对输入指纹（同 key 异 name/size 拿旧会话，complete 元数据错位）｜service.py:217-233 complete_multipart 成功后置步骤失败→重试恒 422＋storage_prefix 孤儿对象｜files/previews.py:114 外层 rollback 吞掉内层已 flush 的 failed 标记（版本停留旧 preview_status 且 job 已消费）｜previews.py:220 request_preview_regeneration 未排除 source="preview"（嵌套 preview 纵深缺口）｜transcripts/service.py:381 promote_draft 无行锁＋IntegrityError 未映射 500｜meetings/service.py:708 add_turn seq check-then-act 并发撞唯一约束 500
- **QR-131 扫描链契约与模板校验缺口族**（5 锚）：files/service.py:250 病毒扫描链全链休眠——file.scan 零生产者（grep 闭集仅 3 处注册面），活体上传恒 not_required 即 available，sha256 恒空、魔法字节校验不可达（**判级裁定：test_file_uploads_api.py:212/216 两枚行为钉证明属既有拍板——「内部工作台立即可用」，降 P3 登记契约未显式化**：processors docstring 仍描述完整链＋零静态钉锁「有意休眠」语义）｜template_parser.py:369-410 扫描面≠渲染面（文本框 w:txbxContent 占位符绕过上传校验与 QA 残留检查；ClosedSandbox 兜底注入面）｜template_parser.py:284-315 {% if %} 无配平追踪且 publish 不强制 test_generate（残缺模板至生成期才失败）｜documents/mapping.py:160 validate_mapping 生产零调用（mapping_json 一致性从不在入库路径校验，字段静默空白）
- **QR-132 文档/会门/指标卫生族**（8 锚）：draft_service.py:469-473 死代码（solution 注入分支在 436-437 硬闸后不可达）｜generator.py:292-303 意外异常 str(exc) 直落 generation_error 透出（SQL/驱动细节；DeepSeekError 已有 public_message 兜底）｜version_service.py:911-917 online_revise 每版新建库卡不回写 library_file_id（与 draft_service「同一文件身份追加版本」语义相悖，文件库多卡分裂）｜meetings/service.py:1329/1364/1389 t1/t2/t6 门判定全表扫描 trigger=mandatory 无预过滤｜:541-608+1402 T6 侧链键魔法化——create_meeting 不提升 project_id 进 topic_refs（与 solution_id 一等处理不对称），须调用方手写魔法键（fail-closed 方向＋test_t6_gate.py:82 教键）｜meetings/routes.py:1 docstring 9≠11 路由｜metrics/service.py:135-147 p0_senior 同 run 多轮拍板重复计样＋definition 配对键漂移（checkpoint.handoff_run_id vs 实现读事件 changes.run_id）｜evidence/service.py:245 函数内 `import re as _re`（顶层已有）

## 3 清白亮点（供总报告引用）

- **存储层安全基座全清白**：base.py validate_object_key 拒绝性规范化（%/反斜杠/九种歧义斜杠/NFKC/Cc-Cf-Zl-Zp）＋根闭集＋逐段 ./.. 黑名单；layout.py 五状态机单一权威闭集 fail-closed＋写读矩阵；local.py 防穿越双闸（Windows 盘符重置亦拦）＋键级 RLock＋copy 双键排序防死锁＋签名 compare_digest 窗口 ≤300s；oss.py SecretStr＋__repr__ 零凭据＋SDK 日志 NullHandler。
- **M4-D 24 调用点接线回归零漏网**：documents/generator/version_service/template_service、research/export、guidance/jobs、mcp_gateway、file_delivery、previews/processors 全走 layout helper；S2/S3 路径组装走 org_object_prefix 与 docstring 逐字一致——唯一漏网即 QR-119（.head( 不在静态钉 marker 集）。
- **迁移链静态核**：73 文件＝73 revision、单头 `b5d9e2f4a7c1`、零悬挂 down_revision、从头可达 73/73 无孤立无环（主会话 python 脚本，纯文本快照）。
- **transcripts 域 T-A2 脱敏链闭合**：redact_text_detailed 疑似同样替换、词典故障 503 fail-closed 同码、确认三要素闭环＋未来时戳拒绝、墓碑双 CHECK、draft_id 纯字符串无 FK 物理隔离＋org 段单一权威无穿越。
- **meetings 纪要封存主干清白**：close_meeting 三段式契约（分歧 ≥2 方原样保留）＋守卫复核引用闭合＋PM-2 三层防火墙（徽标注入/处方拒收/专业结论只进待办段固定前缀）＋sealed_sha256 规范化 JSON＋denied 独立事务留痕；auto 纪要永不作门证据有钉（t2/t1/t6 三门＋U4 修订回路全排除）。
- **metrics/review_tickets 三道闸**：出厂默认关／坏规则 422 fail-closed／insufficient_data 永不判越限＋指标闭集＋prompt_ref 注册表校验＋同日幂等指纹＋报告缺行 fail-closed。
- **evidence upsert 保存点幂等**（begin_nested 并发撞唯一读回赢家）；validate_evidence 五维只读干跑零写入零事件。
- **guidance/translator 脱敏主干机械纪律在位**（QR-133/134 是边界张力非主干缺陷）：闸①分层失败语义全链一致（凭据正则 422／词典机制故障 fail-closed 同码 DICT_FAILURE_CODE 单点／疑似替换+复核／通用词零改动——redaction.py:88-130）；闸②词典来源纪律（seeds 合成示例 3 行实测、真实词典 env 指本地文件）；AI 输出端兜底 redact_draft_payload 双 AI 入口单一权威（jobs.py:196/translator jobs.py:119）；confirm 复核闸只认字面 true fail 向安全侧（routes.py:75）；输出端兜底层覆盖 LIST_FIELDS＋evidence 值。
- **guidance jobs/translator jobs 重试纪律**：retry limit=1 有钉；CR-051 sink 清空防 occurrences 翻倍；退避仅瞬时码；终态保证（绝不停 analyzing/running）＋worker-loss 收尾钩子；异常串不进日志（只记类型，防文档内容泄入日志——jobs.py:224）。
- **translator 主干**：AI 调用在事务外（running 先 commit——与 QR-123 generator 事务内调用相反的正确先例）；actor ContextVar 用完复位（worker 线程复用防串）；采纳闸序（先翻译记录闸 404 不泄露草稿存在性再项目闸）＋IntegrityError 409 同义；api_catalog 收编口径登记（translate 创作类收编、拍板类永不收编）；source_refs 白名单三键无处编造。
- **research/models.py**：subject link 同项目组合 FK＋set/before_insert 双事件监听同步 project_id＋跨项目 ResearchSubjectLinkOwnershipError；merge 不变量 CHECK（指向=已归档＋不自指）；revision 不可变（confirmed raise）；导出/导入批次 CHECK 版本单调。
- **seeds 面三查绿**（主会话直审）：enterprise-names.txt 合成示例 3 行（黑名单示例控股公司/合成测试集团/虚拟演武厂——零真实名）；lessons.json 零答案词汇 10 条 SOP-only；10 个 JSON 种子全部可解析。
- **scripts/bridge-poll.mjs 清白**（233 行逐行）：slug 白名单 `^[a-z0-9][a-z0-9-]{0,79}$` 前置于命令拼接（防注入）；只读命令白名单（remember/ingest/log/debrief 不在采集器）；fdeops 目录读取失败降级不中断整轮；maxBuffer 8MB＋CLI 超时 90s＋files 截 50 有界；token 走 Authorization 头不入 argv；captured_at ISO 格式（r6 QR-104 服务端校验面输入合规）。

## 4 口径数字变化

零生产 diff 轮：485/52/153/73 全不变。

## 5 备注

1. 判级存疑 3 处如实标注（QR-119 按潜势、QR-125/126 测试钉矛盾面）；QR-131 判级裁定＝扫描链休眠有行为钉属既有拍板，登记「契约未显式化」而非链缺陷。QR-133/134 属 needs-decision（设计张力非机械缺陷，须蔡工拍板后定修复方向）。
2. **Kimi 文件腿未脱敏上传不另立条**：r2 已立 P1（锚 ai/kimi.py:74，QR-024~040 段）——本域 jobs.py:115-147 的 file 腿消费同一客户端，引用续注不重报；本地抽取腿的文本路径脱敏在位（build_messages 前 `_redact_and_build`）。
3. QR-117 影响面注记：桌面编辑器是唯一 rich_text 生产者（grep 闭集）——修复方向二选一（服务端兼容 text 键 or 桌面改发 content），顺带定死文本模型（bleach 输出 HTML 序列化 vs 生成端按字面写入的 &/&lt; 残留）。
4. QR-118 家族关联：QR-121（create 面 IntegrityError）与 QR-130（transcripts promote/meetings add_turn）同属「唯一约束 IntegrityError 未映射 500」家族——修复批建议统一 except 映射模式。
5. 既有钉/挂账回避：CR-006/013/016/021/022/027/028/032、B#28、V31-P1 诚实截断、M4-D 五步迁移闸（QR-105 已报 CLI 面）均未触碰未重报；QR-128 与 r6 QR-099/100（进程存活面）无重叠（本轮为事务回滚面）。
6. 域重点④transcripts 深域（只收文本 T+7 细节）与⑤org 三列回填（org_scope 监听面归 r1 QR-023）经片内定点核未见新面；documents/ai_content.py 由 generator 片消费面覆盖。
