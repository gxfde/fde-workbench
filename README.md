# FDE Workbench

最新版本与变更记录见 [CHANGELOG.md](CHANGELOG.md)。

FDE Workbench 是面向 Forward Deployed Engineer 团队的开源项目工作台，覆盖项目、任务、调研、AI 机会、方案、交付文档、文件、用户、Skills、插件和模型配置。项目由 Electron 桌面端与 Flask API 组成，业务数据保存在部署者自己的 MySQL、Redis 和文件存储中。

本仓库是干净的开源发行版：不包含生产数据库、客户资料、运行日志、对象存储文件、访问凭据、安装包、发布备份或客户端自更新模块。

> **使用与商用提示**：本项目是以 *vibe coding*（AI 辅助快速开发）方式构建的产品。开源发布不代表代码已经完成全面的安全审计、合规评估、性能压测或生产级验收，也不构成对特定业务场景的适用性保证。用于商用、对外服务或处理真实客户数据前，请自行审查源码及依赖，验证权限隔离、数据安全、文件处理、模型输出、备份恢复和升级迁移，并按所在地法律法规与行业要求完成合规评估。不要把默认配置或初始管理员凭据直接用于生产环境。

## 主要能力

- 项目、成员、任务、甘特关系与项目阶段管理
- 调研对象、调研表、备忘录、AI 机会与方案设计
- 文档模板、交付文档、版本和项目文件管理
- 角色权限：管理员、项目负责人、FDE 工程师、查看者
- AI 模型、Skills、插件、AI Server、微信/ClawBot 集成
- 管理员系统配置：模型服务、扩展市场、对象存储和 ClamAV
- Electron 桌面端；本项目不包含客户端自更新能力

## 平台支持

当前仅提供 **macOS Apple Silicon（arm64）DMG** 的构建配置。项目目前没有 Windows 客户端版本，也不提供 Windows 安装包、Windows 构建脚本或兼容性保障。Windows 支持属于后续社区开发范围。

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
- Docker（可选，仅用于快速启动 MySQL/Redis）
- ClamAV、LibreOffice（可选；用于病毒扫描和文档预览/转换）

## 首次启动

所有命令都在本仓库根目录执行。

### 1. 启动 MySQL 和 Redis

```bash
docker compose up -d mysql redis
```

也可以使用已有服务，并在 `server/.env` 中填写连接地址。

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

- `GET /health/live`：进程存活
- `GET /health/ready`：数据库、Redis 等依赖就绪状态

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

```bash
npm run package:mac
```

当前配置仅生成 Apple Silicon macOS DMG，并使用本地临时签名。正式外发应由发行者使用自己的 Developer ID 完成签名、公证和 Gatekeeper 验收。本仓库不包含证书、公证凭据或历史安装包。当前没有 Windows 客户端或 Windows 安装包；`package:mac` 也不适用于 Windows。

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
