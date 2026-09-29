<div align="center">
  <img src="desktop/src/renderer/src/assets/logo.png" width="112" alt="FDE Workbench Logo" />
  <h1>FDE Workbench</h1>
  <p>面向 Forward Deployed Engineer 团队的开源项目工作台</p>
  <p>
    <img src="https://img.shields.io/badge/version-v0.1.0-2d7dd2" alt="版本 v0.1.0" />
    <img src="https://img.shields.io/badge/license-MIT-22a06b" alt="MIT 许可证" />
    <img src="https://img.shields.io/badge/desktop-macOS%20arm64%20%7C%20Windows%20x64%20build-555b6e" alt="macOS arm64 与 Windows x64 构建配置" />
    <img src="https://img.shields.io/badge/release-source%20only-f59e0b" alt="仅源码发布" />
  </p>
  <p>
    <a href="#主要能力">主要能力</a> ·
    <a href="#首次启动">首次启动</a> ·
    <a href="#配置边界">配置说明</a> ·
    <a href="#后端运维">后端运维</a> ·
    <a href="#开发与测试">开发与测试</a> ·
    <a href="CHANGELOG.md">版本记录</a>
  </p>
</div>

---

FDE Workbench 覆盖项目、任务、调研、AI 机会、方案、交付文档、文件、用户、Skills、插件和模型配置。它由 Electron 桌面端与 Flask API 组成，业务数据保存在部署者自己的 MySQL、Redis 和文件存储中。

| 当前版本 | 你需要知道的事 |
| --- | --- |
| 桌面平台 | macOS Apple Silicon（arm64）DMG 与 Windows x64 NSIS 构建配置；Windows 尚未完成发行验收 |
| 发布内容 | 提供源码，不附带已签名、已验收的安装包；不包含客户端自更新 |
| 首次登录 | 空数据库初始化后使用 `admin` / `ChangeMe123!`，首次登录强制改密 |
| AI 功能 | 基础功能无需 AI Key；模型及其他外部集成由管理员分别配置 |

> [!IMPORTANT]
> 本仓库是清理后的开源发行版，不包含生产数据库、客户资料、运行日志、对象存储文件、访问凭据、安装包或发布备份。

> [!WARNING]
> **商用前请独立核验。**本项目以 *vibe coding*（AI 辅助快速开发）方式构建。开源发布不代表已经完成全面的安全审计、合规评估、性能压测或生产级验收，也不保证适用于特定业务。商用、对外服务或处理真实客户数据前，请审查源码及依赖，并验证权限隔离、数据安全、文件处理、模型输出、备份恢复和升级迁移；同时完成适用的法律与行业合规评估。不要直接将默认配置或初始管理员凭据用于生产。

## 主要能力

| 项目协作 | 调研与交付 | AI 与管理 |
| --- | --- | --- |
| 项目、成员、任务、甘特关系和阶段管理 | 调研对象、调研表、备忘录、AI 机会和方案设计 | AI 模型、Skills、插件、AI Server、微信/ClawBot 集成 |
| 项目负责人、FDE 工程师、查看者等角色权限 | 文档模板、交付文档、版本和项目文件管理 | 管理员配置模型服务、扩展市场、对象存储和 ClamAV |

## 平台支持

源码包含 **macOS Apple Silicon（arm64）DMG** 和 **Windows x64 NSIS** 的构建配置。Windows 构建支持来自社区贡献 [PR #1](https://github.com/gxfde/fde-workbench/pull/1)；贡献者报告在 Windows 11 x64 上构建并安装成功，但安装包图标、卸载，以及连接后端后的完整业务流程尚未完成验收。本项目目前不提供已经签名、可直接视为正式发行版的 Windows 安装包，也不承诺其他 Windows 架构或版本的兼容性。

## 技术架构

| 层 | 技术 | 说明 |
| --- | --- | --- |
| 桌面端 | Electron、React、TypeScript、electron-vite | 通过受限 IPC 调用后端 API |
| API | Python 3.12/3.13、Flask、SQLAlchemy、Alembic | 认证、权限和业务接口 |
| 数据 | MySQL 8、Redis 7 | 主数据、任务队列与调度 |
| 文件 | 本地目录或兼容 Aliyun OSS 的对象存储 | 由管理员在工作台配置 |
| 后台进程 | Flask CLI worker / scheduler | 文件处理、异步任务与自动化 |

## 环境要求

- Node.js 22+ 与 npm 10+
- Python 3.12 或 3.13
- MySQL 8.0+、Redis 7+
- Docker（可选；可只用于启动 MySQL/Redis，也可运行整个后端）
- ClamAV、LibreOffice（可选；用于病毒扫描和文档预览/转换）

## 首次启动

所有命令都在本仓库根目录执行。

### 1. 启动 MySQL 和 Redis

```bash
docker compose up -d mysql redis
```

也可以使用已有服务，并在 `server/.env` 中填写连接地址。

如需用 Docker 一并运行 API、worker 和 scheduler，跳过以下第 2~4 步，直接看「用 Docker 运行后端」。

### 2. 安装依赖并创建启动配置

```bash
npm install
python3.12 -m venv server/.venv
server/.venv/bin/pip install -r server/requirements.lock -e 'server[test]'
cp .env.example server/.env
```

编辑 `server/.env`，至少将 `FDE_JWT_SECRET` 换成独立随机值：

```bash
python3 -c 'import secrets; print(secrets.token_urlsafe(48))'
```

### 3. 建库、迁移与初始化

```bash
cd server
.venv/bin/alembic upgrade head
.venv/bin/flask --app fde_api.app:create_app bootstrap-open-source
cd ..
```

初始化命令可重复执行，不会覆盖已有用户或业务数据。全新数据库会创建一个必须首次改密的管理员：

| 项目 | 初始值 |
| --- | --- |
| 用户名 | `admin` |
| 密码 | `ChangeMe123!` |
| 首次登录 | 强制修改密码 |

初始凭据仅用于空数据库首次进入。登录后必须立即改密；已有任何用户时，初始化命令不会再创建该账号。

### 4. 启动后端

分别打开三个终端：

```bash
cd server && .venv/bin/flask --app fde_api.app:create_app run --host 127.0.0.1 --port 8010
```

```bash
cd server && .venv/bin/flask --app fde_api.app:create_app worker
```

```bash
cd server && .venv/bin/flask --app fde_api.app:create_app scheduler
```

### 5. 启动桌面端

```bash
npm run dev
```

登录并完成改密后，管理员进入左侧“系统配置”，设置模型 API、AI Server、微信/ClawBot、扩展市场、存储与安全扫描。模型 API Key 等密钥在后端加密保存且不回显。

无需先配置 AI Key 即可登录和使用项目、任务、调研记录、文件等非 AI 功能；AI 生成、分析和对话等功能需要对应模型服务及 API Key。OSS、微信/ClawBot 等外部集成也需分别配置，并非填写一个 AI Key 就能开启全部功能。所有功能均要求后端及其数据库、Redis 等基础服务正常运行。

## 用 Docker 运行后端

除 MySQL/Redis 外，compose 也可以把 API、worker 和 scheduler 一起跑在容器里：`migrate` 服务先执行迁移与初始化，随后三个长期进程启动。桌面端是 Electron 原生程序，仍需在本机运行，见「首次启动」第 5 步。

### 1. 准备密钥

compose 从仓库根目录的 `.env` 读取 `FDE_JWT_SECRET`。该文件已被 `.gitignore` 排除，不会提交：

```bash
python3 -c 'import secrets; print("FDE_JWT_SECRET=" + secrets.token_urlsafe(48))' > .env
```

`FDE_JWT_SECRET` 同时是加密已存集成密钥的根材料。一旦更换，之前保存的密钥将无法解密，因此请妥善保存并保持稳定。

### 2. 启动与停止

```bash
docker compose up -d          # 启动全部服务
docker compose ps             # 查看状态
docker compose logs -f api    # 跟踪 API 日志
docker compose down           # 停止（加 -v 会一并删除数据卷）
```

`migrate` 是一次性服务，退出码为 0 表示迁移与初始化完成。`alembic upgrade head` 与 `bootstrap-open-source` 均可重复执行，因此每次 `up` 都重新执行一遍也是安全的。API 监听宿主机 `8010` 端口，与桌面端开发态的默认地址一致。

### 3. 镜像说明

容器不读取 `server/.env`（该文件在 `.dockerignore` 中排除，其中的 `127.0.0.1` 地址在容器内不适用）；连接信息由 `compose.yaml` 显式注入。

| 项目 | 说明 |
| --- | --- |
| 基础镜像 | `python:3.12-slim`，镜像约 570MB |
| 代码位置 | 源码在构建时写入镜像；修改后端代码后需 `docker compose build && docker compose up -d` 生效 |
| 文件存储 | `fde_storage` 数据卷，挂载到 `/app/server/.fde-storage`，由 API 与 worker 共享 |
| 浏览器功能 | 默认不安装 Playwright Chromium，Mermaid 图表渲染与 LCSC 浏览器自动化不可用；需要时用 `docker compose build --build-arg INSTALL_PLAYWRIGHT_BROWSERS=1 api` 开启 |
| 文档预览 / 病毒扫描 | 镜像不含 LibreOffice 与 ClamAV，相关功能会降级失败，不影响其他功能 |

## 配置边界

工作台运行后可变的集成配置全部由管理员在“系统配置”或“AI 与扩展”中管理。以下是应用启动前的基础设施配置，服务尚未启动时无法通过界面设置：

| 环境变量 | 用途 |
| --- | --- |
| `FDE_DATABASE_URL` | MySQL SQLAlchemy URL |
| `FDE_REDIS_URL` | Redis URL |
| `FDE_JWT_SECRET` | JWT 签名及本地密钥加密根材料，至少 32 字符 |
| `FDE_API_HOST` / `FDE_API_PORT` | API 监听地址和端口 |
| `FDE_ENV` | `development`、`test` 或 `production` |
| `FDE_DESKTOP_API_URL` | 开发态桌面端连接的 API 地址 |

不要在提交、issue、日志或截图中暴露 `.env`。生产环境切换 `FDE_JWT_SECRET` 前应先在系统配置中重新录入所有加密密钥。

## 后端运维

### 数据库迁移

```bash
cd server
.venv/bin/alembic current
.venv/bin/alembic upgrade head
```

升级前应同时备份 MySQL 和文件存储。迁移文件位于 `server/migrations/versions/`，不得修改已发布迁移，应新增迁移。

### 健康检查

- `GET /api/v1/health/live`：进程存活
- `GET /api/v1/health/ready`：数据库、Redis 等依赖就绪状态

### 生产部署要点

- 使用 Gunicorn 承载 `fde_api.wsgi:app`，并独立运行 worker 与 scheduler。
- API 仅暴露在 HTTPS 反向代理之后；不要将 Flask 开发服务器用于生产。
- MySQL、Redis、OSS 使用独立最小权限账号；限制网络访问来源。
- 本地文件存储目录、数据库和管理员配置密文必须一起备份。
- 桌面安装包默认连接 `http://127.0.0.1:8010`。远程部署时，在打包前设置受信任的 HTTPS API 地址并修改 `desktop/package.json` 的 `build.extraMetadata.fdeApiUrl`。
- 开源版没有内置更新中心；版本升级由部署者通过代码发布、数据库迁移和重新打包完成。

## 开发与测试

```bash
npm run typecheck
npm run test:desktop
npm run test:server
npm run test:operations
```

完整 `npm test` 需要 MySQL 和 Redis。端到端测试只允许使用数据库名精确为 `fde_workbench_test` 的测试库：

```bash
mysql -uroot -p -e "CREATE DATABASE fde_workbench_test CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci"
FDE_E2E_DATABASE_URL='mysql+pymysql://USER:PASSWORD@127.0.0.1:3306/fde_workbench_test' npm run test:e2e
```

## 打包桌面端

macOS Apple Silicon（arm64）DMG：

```bash
npm run package:mac
```

Windows x64 NSIS 安装包（在 Windows 构建环境执行）：

```bash
npm run package:win
```

桌面安装包只包含客户端；使用前仍需按上文部署后端、MySQL 和 Redis。默认 API 地址为 `http://127.0.0.1:8010`，连接远程后端时须在打包前配置 `desktop/package.json` 中的 `build.extraMetadata.fdeApiUrl` 为受信任的 HTTPS 地址。

`package:mac` 使用本地临时签名，**不是**已签名公证的正式 macOS 发行流程。正式外发应使用发行者自己的 Developer ID 完成签名、公证、装订及 Gatekeeper 验收。Windows 构建脚本能生成安装包，但构建或安装成功不等于发行验收；公开分发前应完成代码签名，并在真实 Windows 环境验证安装包图标、安装、启动、登录及后端连接、主要功能和卸载。**未签名安装包不能当作已验收发行版发布或宣传。**本仓库不包含签名证书、公证凭据或历史安装包。

### 更换 Logo 与安装图标

- 界面及本 README 页首使用 [`desktop/src/renderer/src/assets/logo.png`](desktop/src/renderer/src/assets/logo.png)。更换 Logo 时，直接用同名 PNG 替换该文件，再重新构建客户端。
- macOS 安装图标由 `npm run package:mac` 调用 `icon:mac`，根据上述 Logo 生成 [`desktop/build/icon.png`](desktop/build/icon.png) 和 [`desktop/build/icon.icns`](desktop/build/icon.icns)。
- Windows 应用图标使用 [`desktop/build/icon.png`](desktop/build/icon.png)，NSIS 安装及卸载图标使用 [`desktop/build/icon.ico`](desktop/build/icon.ico)。更换 Logo 后还需用新图标重新生成并替换 `.ico`；仅替换界面 Logo 不会自动更新 Windows 安装图标。

## 数据与安全

- 仓库中不应出现真实客户、账号、项目、调研、文档、附件或模型对话数据。
- `.gitignore` 已排除密钥、日志、存储目录、依赖和构建产物，但提交前仍应执行秘密扫描。
- 初始管理员强制改密；生产环境应设置强密码、HTTPS、备份和访问审计。
- 密钥不经 API 回显。数据库泄露防护仍依赖安全保存 `FDE_JWT_SECRET` 与数据库访问控制。
- 漏洞报告方式见 [SECURITY.md](SECURITY.md)。

## 目录

```text
desktop/     Electron 主进程、预加载层、React UI 与桌面测试
server/      Flask API、Alembic 迁移、后台任务与服务端测试
resources/   通用、无客户数据的文档模板
scripts/     本地开发、测试和打包脚本
tests/       端到端与运维契约测试
```

## 参与贡献与许可

贡献流程见 [CONTRIBUTING.md](CONTRIBUTING.md)。代码采用 [MIT License](LICENSE)；项目名称、Logo 和第三方商标不因代码许可而自动授予商标使用权。第三方依赖遵循其各自许可证。
