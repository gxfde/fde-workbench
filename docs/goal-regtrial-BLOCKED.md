# goal-regtrial · 待裁决清单（BLOCKED）

> 规矩：拿不准的写这里（待裁决清单），跳过继续做别的，随交付提交。**空的写「无」**。
> 本轮**非空**——三项均属 OWNER 亲手面（AI 不代开公网写面、不代持凭据）。

## B1｜SMTP 真凭据（发信通道就位）— 阻断「真发信轮」

- **缺什么**：SMTP 服务器地址/端口/账号/口令/FROM/允许发信域根。任务书拍板默认＝OWNER 提供。
- **建议形态**：Zoho（与 AI外贸获客 backend 同款，已于 2026-11-09 实发验证过）——在 Zoho 上给
  `mail.fde18.com` 这类专用发信子域建邮箱（如 `noreply@mail.fde18.com`；仅为示例，实际子域及 DNS/服务商就绪由 OWNER 确认，主域不发信），把账号与口令**带外**给执行者
  （口令走 `SecretStr`，不落盘、不进 argv、不进仓）。
- **到位后做什么**：①本机主栈 `server/.env` 追加 7 键（`FDE_SMTP_ENABLED/HOST/PORT/USERNAME/PASSWORD/FROM/SEND_SUBDOMAIN`）；
  ②复跑真发信轮：`python scripts/verify/verify_registration_trial.py --base-url https://app.fde18.com
  --imap-host <imap 主机> --imap-user <账号> --imap-password-env <口令环境变量> …`（口令只经环境变量）；
  ③回执贴对话（逐环实际输出）。
- **不阻断什么**：代码侧已全绿（32 例新测试＋SES 27 例零回归＋变异四连红→绿＋本机全链 PASS）。

## B2｜远端部署树公网开闸（注册面开闸三条件）— 阻断「对外放量」

- **缺什么**：远端 `app.fde18.com` 部署树的写面开闸（**公网写面，AI 不代开**）。清单如下，OWNER 亲手：

  | 键 | 值 | 说明 |
  |---|---|---|
  | `FDE_SMTP_ENABLED` | `true` | 发信通道开关（与 `FDE_SES_ENABLED` **互斥**——同开＝启动失败 fail-closed） |
  | `FDE_SMTP_HOST` / `FDE_SMTP_PORT` | Zoho SMTP 主机 / `587` | 587＝STARTTLS；465＝隐式 TLS |
  | `FDE_SMTP_USERNAME` / `FDE_SMTP_PASSWORD` | 账号 / 口令 | 口令 `SecretStr`，真值不进仓 |
  | `FDE_SMTP_FROM` | 如 `noreply@mail.fde18.com` | 仅示例；须落在 OWNER 已确认的允许发信子域内 |
  | `FDE_SMTP_SEND_SUBDOMAIN` | 如 `mail.fde18.com` | 仅示例；允许发信子域根由 OWNER 确认（主域不发信，SPF/DKIM 面不扩到主域） |
  | `FDE_REGISTRATION_ENABLED` | `true` | 注册面部署闸（默认关；开闸＝公网免注册写面） |
  | `FDE_PUBLIC_BASE_URL` | `https://app.fde18.com` | 验证链接的公网根地址（缺任一项＝注册面整体 404） |
  | `FDE_REGISTRATION_IP_DAILY_LIMIT` | `10` | 试点实数 10/日/IP（代码缺省 20 保守占位，部署面按 10 配） |
  | `FDE_REGISTRATION_RATE_FAIL_CLOSED` | `1` | 公网面必须 fail-closed（Redis 故障即拒） |
  | `FDE_REGISTRATION_REVIEW_ENTRIES` | `deliverer,partner` | 企业/创业者邮箱验证后自助激活；交付者/区域服务商仍纳审。不得留空：空值会使四入口全部不纳审 |

  开闸后动作：compose recreate（api/worker/scheduler）→ 容器 env 复验 → `/api/v1/health/ready` 200 →
  公网注册面 404→201 复验（**先确认开闸面暴露范围符合预期**）→ 值守四项启动。
- **边界**：本轮**远端写操作＝0**，AI 未碰远端部署树、未开任何公网面。

## B3｜真发信轮的取信通道（IMAP 侧）

- **缺什么**：真发信后验证邮件落到真实邮箱，需能取件（IMAP 主机/账号/口令或应用专用密码）。
- **处置**：由 OWNER 一并带外提供（或指定一个专用收件邮箱）；口令只经环境变量传入
  （`--imap-password-env`），不进 argv、不进仓、不进回执。

---

**除以上三项外，本轮无其他 BLOCKED**（代码面、测试面、端到端链路、桌面交付物、文档三同步均已完成）。

2026-11-18 配置示例校正：审核清单对齐 `registration/service.py::review_entries` 与既有配置测试；发信示例对齐专用子域纪律。仅修正文档，未改部署配置、DNS或公网开关，B1/B2/B3均继续待OWNER。
