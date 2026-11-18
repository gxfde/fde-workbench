# R2a：注册配置清单校正规格

状态：源码核对完成，原清单示例已修正；独立文本复核通过，随R1a交付中。不是公网开闸授权。2026-11-18。

## 目的与范围

修复`docs/goal-regtrial-BLOCKED.md`中两组与既有规则冲突的配置示例，避免OWNER照清单操作时误放开审核或在主域发信。只改文档，不新增通道、不决定实际邮箱、不改变部署配置。

白名单：上述BLOCKED文档、本线PROGRESS/路线状态，以及随轮CHANGELOG小节。其余源代码、测试断言、.env、DNS、服务器均不在本小轮写范围内。

## 已核对事实

| 清单现状 | 源码/规则 | 应改说明 |
|---|---|---|
| REVIEW_ENTRIES留空，同时说明交付者/区域服务商仍纳审 | `registration/service.py::review_entries`空值返回空集合；`test_registration_surface.py::test_review_switch_is_configurable`已有断言；config与.env.example缺省均为deliverer,partner | 明确填`deliverer,partner`；enterprise/founder可邮箱验证后自助激活；留空会全部不纳审，不是既有拍板意图 |
| B1与表格FROM/允许域根使用主域 | AGENTS发信纪律、config.py注释均要求发信子域；配置校验验证FROM落在配置允许域内，不替OWNER选域 | 两处示例统一为发信子域形态，如`noreply@mail.fde18.com`与`mail.fde18.com`；声明仅示例，实际域/DNS/provider由OWNER确认 |

## 实施与验收

1. 修改前重查在途PR及该文件是否被其他线改动；仅修示例与解释，不删除B1/B2/B3前提。
2. 全文核对重复示例，保持“主域不发信”、SMTP/SES互斥、10/日/IP与fail-closed的原口径。
3. 不运行验证邮件脚本，不用合成通过冒充真发信，不上传真实邮箱/口令。
4. 文档diff只允许上述范围；核对已存在的review_entries源码与测试即可，不为简单文案修改加镜像式测试。随实施轮保持台账闸与原CI，不单开补账轮。
5. 完成只称“配置清单校正”；真实发信/IMAP/公网开闸继续OWNER待办。回退为恢复文档上一版，不触部署。
