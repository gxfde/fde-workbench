# R1a：发布候选核验实施规格

状态：本地实现及CI接线就绪；WSL 44例全部通过、零skip（11.158s）；最终合流提交108c28d三钩子通过且真实干净候选自核exit0；独立复审通过，远端CI待完成。依据 [leader任务书](goal-optimize-leader.md)；本规格只细化R1a，不授权Docker部署。

## 1. 要解决的问题

发布前识别脏工作树、错误提交、迁移图不完整和发布输入漂移。候选核验通过不能证明镜像或活体一致，也不能替代takeover_check、部署互斥、alembic现测和三验。

## 2. 白名单与公共接口

新增 `scripts/deploy/release_preflight.py`、`tests/deploy/test_release_preflight.py`；README部署节登记用法；现有CI只追加该测试步骤。CHANGELOG/AGENTS/本线文档随轮更新。禁止修改server应用、迁移原件、compose部署行为、Dockerfile及其他线文件。

本地CLI（已实现，尚未集成发布）：

```text
python scripts/deploy/release_preflight.py --tree <repository-root> --expected-commit <40-character-SHA>
python -m unittest discover -s tests/deploy -p test_*.py -v
```

正常核验与参数错误输出一个JSON对象；`--help`为帮助文本的明确例外；退出码0＝候选一致、1＝候选拒绝、2＝参数/环境不可用。字段至少有schema_version、status、expected_commit、observed_commit、migration_heads、input_sha256、errors、live_status。live_status始终为not_checked，禁止命名ready_for_production。

## 3. 核验要求

- 只接受目标Git仓根；Git失败、不是仓、不是根、预期SHA非法都明确失败。不得把父仓误当目标仓。
- 核对实际HEAD、索引和工作树，以及未跟踪且未忽略文件。预期SHA由调用者提供，不能自动将当前HEAD当作预期而宣称已对外部版本核准。
- 忽略.env等既有ignored路径，不读取其内容；错误只输出固定分类和必要的安全相对路径，不能透传子进程stderr、配置值或迁移源码。拒绝白名单输入的外链/符号链接，防读取仓外文件。
- 发布输入白名单以实际构建契约核定，至少含compose、Dockerfile、锁定依赖和迁移。记录相对路径→sha256；声明仅覆盖所列输入，其余已跟踪源码由提交身份关联。不要对未知文件类型或整个工作树无差别哈希。
- 迁移使用AST静态解析，不import、不exec、不执行alembic。revision/down_revision支持已存在的常量写法；重复revision、缺失父节点、多头、环必须失败。depends_on/branch_labels如在场，先核本仓语义，不能静默忽略并报完整图通过；不支持形态明确失败。
- 采集前后复核HEAD及脏态，检测到变化则失败。本措施不是原子快照，不能防所有ABA变化；R1b部署锁与固定发布产物负责进一步闭合竞争窗口。
- 不运行Git hooks，不启动Docker，不连数据库，不修改配置，不写部署锁，不安装新依赖。

## 4. 测试与反例

测试以真实临时Git仓和子进程CLI为边界，仅使用合成文件，不触碰主仓索引或真实配置。一个垂直切片先红后绿，再加下一类反例；记录命令/退出码。

| 契约 | 反例/观测 |
|---|---|
| 干净、匹配的单头仓通过 | 合成两步迁移、固定输入；exit0，live_status=not_checked |
| 外部预期版本校验 | 另一合法SHA；exit1，不误报通过 |
| 脏态拒绝 | tracked修改、staged修改、untracked文件分别拒绝 |
| 秘密不外泄 | ignored.env含合成哨兵；输出与错误均无哨兵；不因该文件存在而误报脏态 |
| 图有效性 | 缺父、重复、多头、独立环、非法元数据分别拒绝 |
| 输入边界 | 缺必需输入、仓外链接、非根目录、Git失败明确失败 |
| 不执行被检内容 | 迁移体包含合成写文件语句，核验后该文件不存在 |
| 检查器真能抓错 | 在临时fixture中制造错SHA/多头等真实失败，再修fixture恢复通过；不得修改原测试阈值 |

测试不得mock被测CLI或图算法；权限/平台不支持的测试前提明确说明，不能静默跳过后宣称全平台覆盖。现有CI四job不改判据，只追加本套测试。

## 5. 本地实现与限制（2026-11-18）

- 新增工具和测试均为标准库，无安装依赖。完整命令一次输出JSON，失败不透传Git错误、参数原文或迁移源码。
- 当前仓迁移元数据经AST只读核对：revision字符串89；down_revision字符串86/tuple2/None1；branch_labels与depends_on均None（各89）。未执行迁移或应用，不把此数当路由/库/活体口径。
- 首轮23例通过后，独立审查新增反例；27例中条件重赋值和AugAssign两例失败（exit1）。修复后38例用时173.879s、exit0，其中37例通过、1例因本机无创建目录符号链接权限明确skip；随后WSL实跑38例全部通过、零skip（11.958s，exit0），补齐本地循环路径验证；远端CI仍待执行。初次临时目录权限错误单列环境失败，不计功能红例。
- 首次Git调用前静态检查标准Git管理文件，不展开include/includeIf；拒绝filter驱动、partial-clone/promisor、外部exclude/attributes路径及未支持的配置语法。每次Git调用固定禁用对象替换、lazy-fetch、网络协议、全局/系统配置、hooks及fsmonitor；子模块暂不支持。assume-unchanged/skip-worktree索引位不允许掩盖修改。非空depends_on/branch_labels暂不支持，明确拒绝而非假绿。
- 迁移枚举只支持`script_location=migrations`、默认非递归且非sourceless模式；拒绝version_locations与子目录迁移；tracked/disk两侧共用Alembic默认文件名排除规则（.#与__init__前缀），目录中额外未跟踪迁移直接拒绝且不读取内容。
- AST支持模块文档、普通导入、无装饰器函数、简单字面量赋值，以及既有迁移中的`sa.text(字面量SQL)`常量。元数据须为简单字面量声明；条件语句、AugAssign、删除、解构赋值、命名空间更新等不支持形态明确拒绝。此检查不执行或证明导入依赖/函数体的运行语义，不是恶意Python沙箱。
- 支持普通仓和标准Git linked worktree。运行前提是受信任且保持静止的本地管理目录；不承诺抵抗恶意Git管理文件、并发配置篡改或所有路径竞态。对象替换和部分克隆不在支持范围。
- 只哈希白名单文件与已跟踪迁移；未承诺被忽略构建输入、外部镜像或生成产物一致。前后HEAD/脏态检查不提供原子性或ABA保证。
- --help沿用CLI帮助文本（不输出JSON）；正常核验与参数错误输出JSON。核验会读取Git配置及列明的发布配置，不读取部署.env、不访问数据库/容器。

## 6. 审查、回退与交付

实现者执行验证，独立审查者只读diff/文本，重点看输入边界、错判通过、秘密输出、Git竞争和真实部署保证的表述。遵守fde-delivery-flow的技能与发布关卡。

工具无副作用，回退为停止调用并回退本PR；不得删除已发布迁移或重置数据库。交付记录明确工具完成、CI状态、是否合并；活体检查保持未做。只有本规格正反例全过并经审查，R1a才验收；不能据此把R1b/R1c标DONE。

最新补强：Git配置先逐行去缩进，避免ConfigParser把合法Git深缩进节吞进前值；无值布尔项解析异常固定分类。新反例先红后修，最终43例/12.144s/exit0/零skip。详细历史见PROGRESS，远端CI尚待执行。

实际工作树兼容补强：只有extensions.worktreeConfig启用时才读config.worktree；关闭态遗留配置不参与核验，开启态危险路径仍拒绝。44例WSL全绿，真实干净提交自核待兼容补丁提交后执行。
