<div align="center">
  <img src="desktop/src/renderer/src/assets/logo-caigong-fde.svg" width="112" alt="蔡工FDE智能交付系统 Logo" />
  <h1>蔡工FDE智能交付系统</h1>
  <p>面向 Forward Deployed Engineer 团队的开源智能交付工作台</p>
  <p>
    <img src="https://img.shields.io/badge/version-v0.2.0-2d7dd2" alt="版本 v0.2.0" />
    <img src="https://img.shields.io/badge/license-MIT-22a06b" alt="MIT 许可证" />
    <img src="https://img.shields.io/badge/desktop-Windows%20x64%20%7C%20macOS%20arm64-555b6e" alt="Windows x64 与 macOS arm64 构建配置" />
    <img src="https://img.shields.io/badge/release-source%20only-f59e0b" alt="仅源码发布" />
  </p>
  <p>
    <a href="#主要能力">主要能力</a> ·
    <a href="#快速搭建">快速搭建</a> ·
    <a href="#配置边界">配置说明</a> ·
    <a href="#后端运维">后端运维</a> ·
    <a href="#换机迁移清单">换机迁移</a> ·
    <a href="#开发与测试">开发与测试</a> ·
    <a href="#打包桌面端">打包桌面端</a> ·
    <a href="CHANGELOG.md">版本记录</a>
  </p>
</div>

---

蔡工FDE智能交付系统（FDE Workbench）覆盖 FDE 交付全流程：项目、成员、任务、甘特、调研、AI 机会、方案、交付文档、文件库、术语表、工作流，以及 **G1–G9 交付门禁**和**报价/收款/合同**商务模块。它由 Electron 桌面端与 Flask API 组成，业务数据保存在部署者自己的 PostgreSQL、Redis 和文件存储中；桌面端侧边栏内置「使用帮助」，随时可查各模块操作说明。

| 当前版本 | 你需要知道的事 |
| --- | --- |
| 桌面平台 | Windows x64 便携版（免安装目录）已在 Windows 11 日常使用验收；NSIS 安装包与 macOS arm64 DMG 可构建但未做发行验收 |
| 发布内容 | 提供源码，不附带已签名、已验收的安装包；不包含客户端自更新 |
| 首次登录 | 空数据库初始化后使用 `admin` / `ChangeMe123!`，首次登录强制改密 |
| AI 功能 | 基础功能无需 AI Key；模型及其他外部集成由管理员分别配置 |

> [!IMPORTANT]
> 本仓库是清理后的开源发行版，不包含生产数据库、客户资料、运行日志、对象存储文件、访问凭据、安装包或发布备份。门禁证据在工作台中只保存 `source_uri` 指针和 sha256 指纹，真实证据文件始终留在项目工作目录，不进仓库。

> [!WARNING]
> **商用前请独立核验。**本项目以 *vibe coding*（AI 辅助快速开发）方式构建。开源发布不代表已经完成全面的安全审计、合规评估、性能压测或生产级验收，也不保证适用于特定业务。商用、对外服务或处理真实客户数据前，请审查源码及依赖，并验证权限隔离、数据安全、文件处理、模型输出、备份恢复和升级迁移；同时完成适用的法律与行业合规评估。不要直接将默认配置或初始管理员凭据用于生产。

## 主要能力

| 项目工作台 | 交付门禁与商务 | AI 与平台管理 |
| --- | --- | --- |
| 项目、成员、任务、甘特关系和阶段管理；文件库、调研工作台、术语表、AI 机会、方案设计与交付文档 | **门禁引擎 G1–G9**：pending → evidence → passed/failed 状态机（G9 支持 conditional_pass）；证据只存 URI + sha256 指针，claimed 与 accepted 分离；任务与工作流产物可自动挂为证据候选（建议性，采纳仍走人工提交闸） | AI 模型、Skills（治理态与效果统计）、工作流控制台、AI 用量月度预算与审计账本、插件、AI Server、微信/ClawBot 集成 |
| 项目负责人、FDE 工程师、查看者等角色权限 | **报价 / 收款（里程碑）/ 合同**商务看板；标准 FDE 项目模板一键派生 | 行业模板、文档模板、模块管理、用户管理、系统配置 |
| 集成桥：本地 openfde / fdeops 工作目录在台内的只读投影 | 任务中心：后台任务、自动化执行与工作流人工审批集中可见 | 桌面端内嵌「使用帮助」：模块操作 + 门禁流程 + 实操示例 |

安全基线（默认启用）：argon2 口令哈希；15 分钟 access token + 30 天轮换 refresh token，改密后旧令牌立即失效；登录连续失败 5 次锁定约 15 分钟（Redis 计数，Redis 不可用时静默放行不影响认证）；API 容器非 root 运行；模型 API Key 等密钥后端加密保存且不经 API 回显。

## 平台支持

源码包含 **Windows x64**（NSIS 安装包 + 免安装便携目录）和 **macOS Apple Silicon（arm64）DMG** 的构建配置。Windows 便携版（`win-unpacked` 目录）已在 Windows 11 x64 日常使用中验收；NSIS 安装包的图标、卸载及完整业务流程尚未完成发行验收。本项目不提供已签名、可直接视为正式发行版的安装包，也不承诺其他架构或版本的兼容性。

## 技术架构

| 层 | 技术 | 说明 |
| --- | --- | --- |
| 桌面端 | Electron、React、TypeScript、electron-vite | 通过受限 IPC 调用后端 API（/api/v1/auth/* 仅允许改密校验路径） |
| API | Python 3.12、Flask、SQLAlchemy、Alembic、Gunicorn | 认证、权限、门禁与业务接口 |
| 数据 | PostgreSQL 16、Redis 7 | 主数据；后台任务为自研 Redis 队列（无 Celery），登录限流与健康检查共用 Redis |
| 文件 | 本地目录或兼容 Aliyun OSS 的对象存储 | 由管理员在工作台配置 |
| 后台进程 | 容器 worker / scheduler | 文件处理、异步任务与自动化调度 |
| 部署 | Docker Compose（redis / api / worker / scheduler） | API 只绑定 `127.0.0.1:8010`；数据库复用网络上已有的 PostgreSQL 16 实例 |

> 整套交互式架构图（总体架构 / 交付流程 / 工作流执行时序 / 集成桥证据数据流 / 运行状态机，五视角）已用 archify 从本仓库真实代码取证生成，见 [docs/architecture/archify-diagrams/index.html](docs/architecture/archify-diagrams/index.html)（每张为独立 standalone HTML，含通过回执与行号级证据）。

## 环境要求

- Docker 与 Docker Compose v2（后端全栈）
- Node.js 22+ 与 npm 10+（桌面端开发或打包时需要；只使用便携版 exe 可不装）
- PostgreSQL 16（可直接复用同网络已有实例，无需新装数据库软件）
- ClamAV、LibreOffice（可选；用于病毒扫描和文档预览/转换，缺失时对应功能降级）

## 快速搭建

目标：换一台新电脑，从克隆仓库到登录工作台。**路线 A（Docker Compose 全栈）是本仓库 compose.yaml 的原生形态，推荐。**

### 路线 A：Docker Compose 全栈（推荐）

所有命令在仓库根目录执行（Windows 用 Git Bash 即可）。

**1. 网络与数据库。**compose 通过 external 网络 `automation_qiflow-net` 用 Docker DNS 别名 `twenty-db` 连库，不依赖容器 IP，也不修改数据库宿主的任何配置：

```bash
docker network create automation_qiflow-net 2>/dev/null || true

# 全新机器：起一个 PostgreSQL 16 并挂上网络别名 twenty-db（已有多实例的机器跳过 run，只做下面两步建角色建库）
docker run -d --name fde-postgres \
  --network automation_qiflow-net --network-alias twenty-db \
  -e POSTGRES_PASSWORD=换成管理员口令 -v fde_pgdata:/var/lib/postgresql/data \
  postgres:16

# 建业务角色与数据库（口令与下一步 .env 里的 FDE_DB_PASSWORD 保持一致）
docker exec fde-postgres psql -U postgres -c "CREATE ROLE fde LOGIN PASSWORD '换成FDE口令';"
docker exec fde-postgres psql -U postgres -c "CREATE DATABASE fde_workbench OWNER fde;"
```

**2. 两份环境配置**（都在 gitignore 里，换机时需手工携带，见「换机迁移清单」）：

```bash
cp .env.example .env           # 仓库根：compose 插值读取，至少填 FDE_DB_PASSWORD
cp server/.env.example server/.env    # 容器 env_file：至少把 FDE_JWT_SECRET 换成随机值
```

生成随机密钥：

```bash
python -c 'import secrets; print(secrets.token_urlsafe(48))'
```

`server/.env` 里的 `FDE_DATABASE_URL` / `FDE_REDIS_URL` 在 compose 里会被覆盖（分别指向 `twenty-db:5432` 与 `redis:6379`），无需改动。

**3. 构建并启动全栈**（redis + api + worker + scheduler）：

```bash
docker compose build
docker compose up -d
```

**4. 迁移与初始化**（容器内执行；迁移文件目录已挂载到宿主 `server/migrations`）：

```bash
docker compose exec api alembic upgrade head
docker compose exec api flask --app fde_api.wsgi:app bootstrap-open-source
# 可选：灌入门禁清单 / 收款里程碑 / SOP 种子数据
docker compose exec api python load_seeds.py
```

初始化命令可重复执行，不会覆盖已有数据。全新数据库会创建一个必须首次改密的管理员：

| 项目 | 初始值 |
| --- | --- |
| 用户名 | `admin` |
| 密码 | `ChangeMe123!` |
| 首次登录 | 强制修改密码 |

> [!NOTE]
> 登录连续失败 5 次会锁定约 15 分钟。首次登录前确认用的是上表口令，改密时不要反复试错。

**5. 验证并启动桌面端**：

```bash
curl http://127.0.0.1:8010/api/v1/health/ready
npm install
npm run dev
```

登录并完成改密后，管理员进入左侧「系统配置」，设置模型 API、AI Server、微信/ClawBot、扩展市场、存储与安全扫描。无需先配置 AI Key 即可使用项目、任务、门禁、报价收款、文件等非 AI 功能。各模块的日常操作见桌面端侧边栏「使用帮助」（与 `docs/工作台操作使用手册.md` 同源）。

### 路线 B：本地 venv 开发（不使用容器跑后端）

适合改服务端代码时的快速迭代。数据库与 Redis 仍需可用（可用路线 A 第 1 步的容器，或自备实例并把地址填入 `server/.env`）：

```bash
npm install
python3.12 -m venv server/.venv            # Windows: py -3.12 -m venv server/.venv
server/.venv/bin/pip install -r server/requirements.lock -e 'server[test]'   # Windows: server\.venv\Scripts\pip ...
cp server/.env.example server/.env          # 填 FDE_JWT_SECRET 与可达的 FDE_DATABASE_URL

cd server
.venv/bin/alembic upgrade head             # Windows: .venv\Scripts\alembic ...
.venv/bin/flask --app fde_api.app:create_app bootstrap-open-source

# 三个终端分别启动（Windows 把 .venv/bin/ 换成 .venv\Scripts\）：
.venv/bin/flask --app fde_api.app:create_app run --host 127.0.0.1 --port 8010
.venv/bin/flask --app fde_api.wsgi:app worker
.venv/bin/flask --app fde_api.wsgi:app scheduler
```

> 命令里的 `.venv/bin/` 是 Unix 写法；Windows 侧对应 `server\.venv\Scripts\`（`pip` / `alembic` / `flask` 同名）。仓库根的 `npm run test:server` 与 `scripts/run-server-tests.mjs` 会自动探测两套路径，跨平台不用改命令。

回到仓库根目录 `npm run dev` 启动桌面端。

## 配置边界

工作台运行后可变的集成配置全部由管理员在「系统配置」或「AI 与扩展」中管理。以下是应用启动前的基础设施配置，服务尚未启动时无法通过界面设置：

| 环境变量 | 用途 |
| --- | --- |
| `FDE_DATABASE_URL` | PostgreSQL SQLAlchemy URL（`postgresql+psycopg://…`）；compose 部署时被覆盖为 `twenty-db` 别名 |
| `FDE_REDIS_URL` | Redis URL；compose 部署时被覆盖为 `redis://redis:6379/0` |
| `FDE_JWT_SECRET` | JWT 签名及本地密钥加密根材料，至少 32 字符；**换机迁移必须原样携带** |
| `FDE_DB_PASSWORD` | compose 插值用，只从仓库根 `.env` 读取，缺失时 compose 拒绝启动 |
| `FDE_API_HOST` / `FDE_API_PORT` | API 监听地址和端口 |
| `FDE_ENV` | `development`、`test` 或 `production` |
| `FDE_DESKTOP_API_URL` | 开发态桌面端连接的 API 地址 |
| `FDE_PRODUCT_NAME` | 服务端侧产品名（默认与桌面 `desktop/src/shared/brand.ts` 同值，改名双侧同步）；chat 等服务端界面文案取值处 |
| `FDE_AI_MONTHLY_TOKEN_BUDGET` | AI 调用月度 token 预算（按用户核算），超限拒绝新调用并留审计记录；`0` = 不限额 |
| `FDE_AGENT_MONTHLY_BUDGET` | 平台月度 agent 预算（token 单位）；`0` = 不限额 |

不要在提交、issue、日志或截图中暴露 `.env`。生产环境切换 `FDE_JWT_SECRET` 前应先在系统配置中重新录入所有加密密钥，否则已保存的加密配置将无法解密。

## 后端运维

### 数据库迁移

compose 部署（迁移文件目录挂载在宿主 `server/migrations/`，容器内生成的迁移可直接进 git）：

```bash
docker compose exec api alembic current
docker compose exec api alembic upgrade head
```

venv 部署则在 `server/` 下直接运行 `alembic`。升级前应同时备份 PostgreSQL 和文件存储。不得修改已发布迁移，应新增迁移。

### 镜像与代码变更

后端镜像在 **构建时** 烘入 `server/src` 源码，运行时只挂载 `migrations` 目录。修改服务端代码后必须：

```bash
docker compose build && docker compose up -d
```

只 `up -d` 不会更新代码，容器仍跑旧镜像。

### 健康检查

- `GET /api/v1/health/live`：进程存活
- `GET /api/v1/health/ready`：数据库、Redis 等依赖就绪状态

四个 compose 服务（redis / api / worker / scheduler）统一 `restart: unless-stopped`，并各带一条 healthcheck：

| 服务 | healthcheck | 含义 |
| --- | --- | --- |
| redis | `redis-cli ping` | Redis 存活 |
| api | `GET /api/v1/health/ready` | 进程活着**且**数据库/Redis 就绪（DB 挂时不再报 healthy） |
| worker | `python -m fde_api.health.heartbeat worker` | 消费循环仍在刷新心跳（`fde:health:worker`，TTL 180s） |
| scheduler | `python -m fde_api.health.heartbeat scheduler` | 调度循环仍在刷新心跳（`fde:health:scheduler`，TTL 900s） |

worker / scheduler 不监听端口，光看「容器 Up」看不出循环是否卡死——心跳键停止刷新即被判 unhealthy（任务会一直停在「正在排队」）。心跳写在 Redis，Redis 不可用时 healthcheck 直接失败（依赖断了不算健康）。

### 生产部署要点

- compose 的 api 服务已用 Gunicorn（2 worker）承载并绑定 `127.0.0.1:8010`；远程访问须经 HTTPS 反向代理，不要将 Flask 开发服务器用于生产。
- PostgreSQL、Redis、OSS 使用独立最小权限账号；Redis 不发布宿主端口（compose 默认不发布）。
- 本地文件存储目录（容器卷 `fde_storage`）、数据库和管理员配置密文必须一起备份。
- 桌面安装包默认连接 `http://127.0.0.1:8010`。远程部署时，在打包前修改 `desktop/package.json` 的 `build.extraMetadata.fdeApiUrl` 为受信任的 HTTPS 地址。
- 开源版没有内置更新中心；版本升级由部署者通过代码发布、数据库迁移和重新打包完成。

## 换机迁移清单

把整套工作台搬到新电脑：

1. **装基础软件**：Docker（含 Compose v2）；需要开发或重新打包桌面端时另装 Node.js 22+。
2. **带走的文件**（都不在 git 里）：仓库根 `.env`、`server/.env`（含 `FDE_JWT_SECRET`，必须原样携带，否则已有加密配置解不开）、桌面便携版文件夹（如 `release/蔡工FDE-0.2.0-便携版/`）。
3. **导出数据**（旧机；容器名按第 1 步自建的是 `fde-postgres`，复用其他实例时换成对应容器或用宿主 pg_dump）：
   ```bash
   docker exec fde-postgres pg_dump -U postgres -d fde_workbench -Fc > fde_workbench.dump
   docker volume ls | grep fde_storage   # 确认卷名（默认 <目录名>_fde_storage）
   docker run --rm -v fde-workbench_fde_storage:/data -v "$PWD:/backup" alpine \
     tar czf /backup/fde_storage.tgz -C /data .
   ```
4. **新机重建**：按「快速搭建 · 路线 A」第 1–3 步起网络、数据库、配置和容器（先不要执行初始化），然后恢复数据、再把旧库升到当前 schema：
   ```bash
   docker exec -i fde-postgres pg_restore -U postgres -d fde_workbench < fde_workbench.dump
   docker volume create fde-workbench_fde_storage
   docker run --rm -v fde-workbench_fde_storage:/data -v "$PWD:/backup" alpine \
     tar xzf /backup/fde_storage.tgz -C /data
   docker compose exec api alembic upgrade head
   docker compose exec api flask --app fde_api.wsgi:app bootstrap-open-source   # 已有用户时是 no-op
   ```
5. **校验**：`curl http://127.0.0.1:8010/api/v1/health/ready`，桌面端登录后抽查项目、门禁和文件库。

## 开发与测试

```bash
npm run typecheck
npm run test:desktop
npm run test:server
npm run test:operations
```

完整 `npm test` 需要 PostgreSQL 和 Redis。服务端测试只允许使用数据库名以 `_test` 结尾的隔离测试库（安全断言会拒绝任何指向业务库的 URL）：

```bash
psql -U postgres -c "CREATE DATABASE fde_workbench_test OWNER fde"
FDE_TEST_DATABASE_URL='postgresql+psycopg://fde:PASSWORD@127.0.0.1:15432/fde_workbench_test' npm run test:server
```

未设置 `FDE_TEST_DATABASE_URL` 时，`server/tests/conftest.py` 会用仓库根 `.env` 里的 `FDE_DB_PASSWORD` 自动拼出 `127.0.0.1:15432/fde_workbench_test`（本机已把 PostgreSQL 转发到 15432 时可直接 `npm run test:server`）；任何库名不以 `_test` 结尾的 URL 都会被安全断言拒绝。`npm run test:desktop` 已固定串行（`--no-file-parallelism`），并行裸跑 vitest 会引入抖动。全量服务端测试约 15–25 分钟，pre-commit 钩子也会跑一遍，提交时请耐心等待而不是中断。

CI（`.github/workflows/ci.yml`）对 push 与 PR 运行四个 job：`server-tests`（隔离 PostgreSQL 测试库）、`pseudonymization`（代号化扫描，`scripts/check-pseudonymization.sh --self-test` 先验证扫描器灵敏度）、`desktop`（typecheck + vitest）、`secrets-scan`（gitleaks）；PR 合并前四个必须全绿。

## 打包桌面端

Windows x64 NSIS 安装包：

```bash
npm run package:win    # 先 electron-vite build，再 electron-builder --win nsis
```

Windows x64 便携版（免安装目录，日常使用形态）：

```bash
cd desktop
npm run build
npx electron-builder --win dir --x64   # 产物在 release/win-unpacked/，整个文件夹拷走即用
```

macOS Apple Silicon（arm64）DMG：

```bash
npm run package:mac
```

桌面产物只包含客户端；使用前仍需按「快速搭建」部署后端。默认 API 地址 `http://127.0.0.1:8010`，连远程后端时在打包前修改 `desktop/package.json` 的 `build.extraMetadata.fdeApiUrl`。

`package:mac` 使用本地临时签名，**不是**已签名公证的正式 macOS 发行流程。Windows 构建脚本能生成安装包，但构建或安装成功不等于发行验收；公开分发前应完成代码签名，并在真实 Windows 环境验证安装、启动、登录及主要功能。**未签名安装包不能当作已验收发行版发布或宣传。**本仓库不包含签名证书、公证凭据或历史安装包。

### 版本号约定

发布升版时，`desktop/package.json` 与 `server/pyproject.toml` 的 `version` 同步修改（根目录 `VERSION` 文件同步作展示用），并在 fork 上打附注标签（如 `v0.2.0`）。客户端构建号取自 `desktop/package.json`。

### 更换 Logo 与安装图标

- 界面品牌资源在 `desktop/src/renderer/src/assets/`：[`logo-caigong-fde.svg`](desktop/src/renderer/src/assets/logo-caigong-fde.svg)（侧边栏、favicon 及本 README 页首）、`logo-caigong-fde-full.png`（带字全标）、`logo-caigong-fde-light.svg`（浅色底变体）。产品名一律取 `desktop/src/shared/brand.ts`（桌面侧单点，main/renderer/tests 双侧引用；服务端侧单点在 `server/src/fde_api/config.py`，可用 `FDE_PRODUCT_NAME` 覆写），不在代码里硬编码。
- Windows 构建图标使用 [`desktop/build/icon.png`](desktop/build/icon.png) 与 [`desktop/build/icon.ico`](desktop/build/icon.ico)（安装器图标三处同源）。
- macOS 图标由 `npm run icon:mac`（`desktop/scripts/generate-icon.sh`）从 `assets/logo.png` 渲染圆角图标并生成 `build/icon.icns`（渲染只写临时目录，**不回写** `build/icon.png` / `icon.ico` 等 Windows 图标文件），`npm run package:mac` 会先自动执行；换 Logo 时需同步更新该源图并重新生成图标。

## 数据与安全

- 仓库中不应出现真实客户、账号、项目、调研、文档、附件或模型对话数据；客户工作目录（含门禁证据原件）永不配置远程仓库。
- `.gitignore` 已排除密钥、日志、存储目录、依赖和构建产物；CI 常驻 gitleaks 秘密扫描，提交前本地也应自查。
- 初始管理员强制改密；生产环境应设置强密码、HTTPS、备份和访问审计。
- 密钥不经 API 回显。数据库泄露防护仍依赖安全保存 `FDE_JWT_SECRET` 与数据库访问控制。
- 漏洞报告方式见 [SECURITY.md](SECURITY.md)。

## 目录

```text
desktop/     Electron 主进程、预加载层、React UI（含内嵌使用帮助）与桌面测试
server/      Flask API、Alembic 迁移、种子数据、后台任务与服务端测试
docs/        工作台操作使用手册、系统意图文档、goal 循环报告、V3 架构审计（docs/audit、docs/architecture）与实施 backlog、需求台账
resources/   通用、无客户数据的文档模板
scripts/     本地开发、测试和打包脚本
tests/       端到端与运维契约测试
compose.yaml 后端全栈编排（redis / api / worker / scheduler）
```

## 参与贡献与许可

贡献流程见 [CONTRIBUTING.md](CONTRIBUTING.md)。代码采用 [MIT License](LICENSE)；项目名称、Logo 和第三方商标不因代码许可而自动授予商标使用权。第三方依赖遵循其各自许可证。
