"""V3.1 P0-1：访谈事实与需求结构化（discovery 域）。

从访谈纪要/转写草稿抽取结构化事实（business_facts）与需求（requirements），
全部条目带来源定位（source_locator）与审阅态；抽取经后台任务异步执行
（outbox topic ``project.discovery.extract``，克隆 guidance 管线范式）。

设计裁决（docs/v3.1/00-gap-register.md P0-1 节，2026-11-08）：
1. 任务书七组 JSON 示例收敛为 ``facts[].fact_type`` 十值分类 + ``requirements``
   独立组——语义覆盖等同，存储归一（开放问题=open_question）。
2. classification 对齐 guidance 五分类（customer_stated/ai_synthesized/
   ai_inferred/open_question/human_added）；AI 只能产出前三类与 open_question。
3. 抽取行 status 只存 queued/running/review_required/failed 四值——任务书示例的
   accepted/rejected 是全量审阅完成度，属派生态（B#13-C 先例：派生值不物化），
   由序列化层 ``review_summary`` 呈现。
4. 来源只允许 interview_minutes（正式纪要）与 transcript_drafts（draft 态草稿）；
   source_sha256 由服务端从源行读取，客户端不可伪造。
5. 源文本在入库时已经过 T-A2 代号化（transcripts 服务闸），抽取输入不二次
   脱敏；模型输出端仍过 ``redact_text_detailed`` 兜底（guidance 第③层同构）。
"""
