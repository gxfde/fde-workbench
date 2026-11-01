# 试点前联调检查单 · iptables 网络隔离 + 沙箱 zcode CLI 钉定

> goal-d10 交付（台账节三十三 #8 承前）。**本检查单只定步骤与判据；真实执行是人工项**——需要蔡工在宿主机与试点环境操作，Agent 不代跑。执行证据按红线只留指针 + sha256（原件落 `D:\test\FDE\engagements\pilot-precheck\`，不进仓库）。

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

## 二、沙箱镜像 zcode CLI 钉定

背景：run 在沙箱内调 zcode CLI 驱动编码智能体。CLI 版本漂移会改变行为契约（输出格式/退出码）——试点前钉死版本。

| # | 步骤 | 通过判据 |
|---|---|---|
| 1 | 沙箱内 `zcode --version`，记录版本号与二进制 sha256 | 与镜像构建时锁定版本一致；存档 `02-zcode-version.txt` |
| 2 | 冒烟：最小 prompt（如「输出 hello」）跑一次完整 run | 退出码 0 + 输出包含预期串 + 耗时 < 60s |
| 3 | 断网冒烟：#4 的 drop 生效前提下再跑一次（应失败得干净） | 明确失败码，无挂死——CLI 对网络拒绝的行为可预期 |
| 4 | 回退演练：切回上一版镜像 tag，重复 #1–#2 | 回退路径可用（试点期间出问题的唯一自救通道） |

**失败处置**：CLI 版本不匹配 → 重建镜像（`docker compose build sandbox`）后复跑；二进制 sha256 与锁死值不符 = 供应链异常，立即冻结并排查。

## 三、证据与交接

- 执行人 / 执行时间 / 每表结果（PASS/FAIL + 存档文件名）回填本文件下表；证据原件放 `D:\test\FDE\engagements\pilot-precheck\`，仓库与数据库只登记 sha256。
- 全表 PASS = 试点前人工联调项销号（台账节三十三 #8）；任一 FAIL = 试点冻结，修复后全表重跑。

| 表 | 结果 | 执行人 | 日期 | 证据 sha256 |
|---|---|---|---|---|
| 一、iptables | 待执行 | （人工） | | |
| 二、zcode CLI | 待执行 | （人工） | | |
