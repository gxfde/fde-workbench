# 试点前联调检查单 · iptables 网络隔离 + 沙箱 zcode CLI 钉定

> goal-d10 交付（台账节三十三 #8 承前）。**本检查单只定步骤与判据；真实执行是人工项**——需要蔡工在宿主机与试点环境操作，Agent 不代跑。执行证据按红线只留指针 + sha256（原件落 `D:\test\FDE\engagements\pilot-precheck\`，不进仓库）。
>
> **2026-11-07 20:08 校正（D1=A 拍板）**：执行通道裁定为 **Windows 宿主侧 zcode 代理**，zcode **不进 sandbox-runner 容器**（#191 E1–E4 四重阻断：node≥22.5／provider 注入／登录态注入／`network_mode: none` 零 egress）。故**二表**的钉定对象由「沙箱镜像内 zcode CLI」改为「宿主侧代理进程」，二表 #3 不再依赖一表的 iptables drop 前提；**一表 iptables 生效性断言仍原样有效**（沙箱基线不因通道裁决改变）。依据：`docs/audit/T-Z1-zcode真机实测与通道裁定提案-2026-11-07.md` §1.2/§2、`docs/audit/下一步实施台账-2026-11-07.md` §8、**不代执行、两表结果仍待人工回填**。

## 一、iptables 生效性断言（沙箱网络隔离）

背景：agents run 的沙箱镜像靠 iptables 做出站白名单（只允许工作台 API / 对象存储 / 包管理镜像源；其余网段 drop）。**从未在真实环境验证过 drop 规则生效性**——模拟环境 docker network 隔离不等于 iptables 规则正确。

| # | 步骤 | 通过判据 |
|---|---|---|
| 1 | 导出当前规则 `iptables -L OUTPUT -n -v --line-numbers`（宿主与沙箱 netns 各一次） | 白名单链存在且含三允许段；输出存档 `01-iptables-rules.txt` |
| 2 | 沙箱内 `curl -m 5 https://<工作台API>/api/v1/health/ready` | 200 READY |
| 3 | 沙箱内 `curl -m 5 https://<对象存储>/minio/health/live` | 200 |
| 4 | 沙箱内 `curl -m 5 https://example.com`（白名单外） | **超时/拒绝（非 200）**——drop 真实生效的核心断言 |
| 5 | 宿主 `iptables -L OUTPUT -n -v` 再导出，比对规则计数器 | 步骤 4 的 drop 计数器增长 → 证明流量真的过了这条链 |
| 6 | 容器重启后复跑 #2–#4 | 规则持久化（否则 systemd unit / entrypoint 注入需修） |

**失败处置**：#4 得到 200 = 隔离失效，试点冻结；先修规则再复跑全表。

## 二、宿主侧代理 zcode CLI 钉定（D1=A 后校正）

背景：编码执行落在 **Windows 宿主侧代理进程空间**（服务端 Linux 容器不得直连宿主 CLI，`bridge/__init__.py:3-8`）。CLI 版本漂移会改变行为契约（`-p/--json/--cwd`、`--resume <sessionId>`、汇总字段形状）——试点前钉死版本与指纹。**本表与容器内沙箱镜像无关**；`docker/sandbox/Dockerfile` 已同步注明「不安装 zcode」。

| # | 步骤 | 通过判据 |
|---|---|---|
| 1 | 宿主侧 `zcode --version`（经 `ELECTRON_RUN_AS_NODE=1 … zcode.cjs` 或等价 wrapper），记录版本号、`zcode.cjs` 二进制 sha256、provider `zcode-builtin.json` revision | 与钉定值 **0.17.1** 一致；存档 `02-zcode-version.txt`（原件只留本地） |
| 2 | 冒烟：宿主代理在**该 run 的隔离工作区**内跑 `zcode -p <自拟文本> --json --cwd <workspace>` 一次完整单发 | 退出码 0 + `--json` 为**单对象汇总**（非 ndjson）+ `usage`/`projection` 齐备 + 耗时 < 60s；形状对照 `server/tests/fixtures/zcode_json_summary.json` |
| 3 | 故障冒烟：provider／凭据不可用或模型 API 不可达时再跑一次 | **明确失败码、无挂死、无静默降级**；失败不产出半成品、不写真相层；与一表 iptables 无依赖关系 |
| 4 | 回退演练：切回上一版宿主代理／CLI 版本，重复 #1–#2 | 回退路径可用（试点期间出问题的唯一自救通道）；版本切换留痕 |

**失败处置**：版本／sha256 与钉死值不符 ⇒ **供应链异常，立即冻结并排查**；`--json` 形状与夹具不符 ⇒ 先按 `agents/zcode_contract.py` 复核契约，不得靠改断言放行。**商用条款书面回执未到位前不进入真实凭据联调**（D3 生产启用闸，见 `docs/audit/D4-D7人工项推进包-2026-11-07.md` §1）。

## 三、证据与交接

- 执行人 / 执行时间 / 每表结果（PASS/FAIL + 存档文件名）回填本文件下表；证据原件放 `D:\test\FDE\engagements\pilot-precheck\`，仓库与数据库只登记 sha256。
- 全表 PASS = 试点前人工联调项销号（台账节三十三 #8）；任一 FAIL = 试点冻结，修复后全表重跑。

| 表 | 结果 | 执行人 | 日期 | 证据 sha256 |
|---|---|---|---|---|
| 一、iptables | 待执行 | （人工） | | |
| 二、宿主侧代理 zcode CLI（D1=A 校正） | 待执行 | （人工） | | |
