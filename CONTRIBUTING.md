# Contributing

感谢你参与 FDE Workbench。提交变更前请先创建 issue 说明问题或目标；安全问题请按 `SECURITY.md` 私下报告。

## 开发流程

1. Fork 仓库并从 `main` 创建分支。
2. 按 README 完成本地环境和数据库迁移。
3. 修改源码，同时补充或更新测试。
4. 运行 `npm run typecheck`、`npm run test:desktop` 和 `npm run test:server`。
5. 提交 Pull Request，写明目的、实现方式、验证证据和兼容性影响。

不要提交真实客户资料、生产数据库、访问令牌、API Key、日志、构建产物或个人信息。新增配置必须进入管理员系统配置或 `.env.example` 的启动前配置清单，不得硬编码。
