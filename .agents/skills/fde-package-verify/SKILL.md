---
name: fde-package-verify
description: How to build, verify and hand off the Windows x64 portable build (便携版) of the FDE desktop app. Use whenever the user asks to 打包 / 出便携版 / 重新打一版 / 交付新版本给蔡工 / verify app.asar / 打包验证 — covers electron-builder output, delivery directory naming (r N+1), sha256, and the Chinese-marker byte verification that prevents false negatives.
use_boundaries.when_to_use: 要打包便携版并做 asar 字节验证交付给用户时
use_boundaries.when_not_to_use: 开发自测走 typecheck 与 test:desktop，不是打包交付，不需要本 runbook
references.required_reading: ["README.md", "desktop/package.json"]
references.authoritative_sources: ["README.md"]


---

# FDE 便携版打包与验证

目标：产出一个**字节级验证过**的 Windows x64 便携版目录，按 `r N+1` 命名交付给用户。
部署命令与产物形态的唯一权威是 `README.md`「打包桌面端」节；本技能是其操作化展开，若与 README 冲突以 README 为准。

## 前置检查

1. 确认改动已在 main 上（交付版必须来自已合并代码，不打包 feature 分支）。
2. 版本号核对：`desktop/package.json` 与 `server/pyproject.toml` 的 `version` 必须一致（根目录 `VERSION` 同步展示用）。
3. API 地址：默认 `http://127.0.0.1:8010`；要连远程后端，**打包前**改 `desktop/package.json` 的 `build.extraMetadata.fdeApiUrl`，打包后改无效。

## 打包（在仓库根执行）

```bash
cd desktop
npm run build
npx electron-builder --win dir --x64
```

产物在 `desktop/../release/win-unpacked/`（整个文件夹拷走即用）。失败时先看 electron-vite build 是否成功——**build 失败后继续打包是本流程最常见事故**（教训：打包前必须先 build 成功，见 memory verify-before-trust-lessons）。

## 验证（两道都过才算数）

### 1. sha256 指纹

```bash
cd release/win-unpacked/resources
sha256sum app.asar
```

记录指纹到交付说明，供用户侧核对。

### 2. 中文 marker 字节验证（必做）

控制台直接 `grep 中文 app.asar` 会因编码转换**假阴性**，必须用 marker 文件法：

```bash
cd release/win-unpacked/resources
printf '门禁与阶段唯一映射' > marker.txt        # 选一段本次改动新增的中文 UI 文案
grep -acf marker.txt app.asar                  # 输出 ≥1 即命中；0 = 打的是旧包
rm marker.txt
```

marker 应选**本次要交付的改动独有的中文片段**——用旧版本也有的句子验证不出新旧。grep 前不要用 `iconv`/管道转换 asar。

## 命名与交付

```bash
cd release
ls -d *便携版*   # 找当前最大 r 序号，如 蔡工FDE-0.2.0-便携版-r3
cp -r win-unpacked "蔡工FDE-<版本>-便携版-r<N+1>"   # r3 存在则命名 r4，绝不覆盖旧目录
```

- 目录名固定格式：`蔡工FDE-<version>-便携版-r<N>`；旧目录**永不覆盖**（用户可能还在用旧版，回退要靠它）。
- 交付时告知用户：目录路径 + asar sha256 + 验证过的 marker 片段。

## 红线提醒

- `release/` 已 gitignore，产物永不进 git。
- 便携版只含客户端；用户机器仍需可达的后端 API（README「快速搭建」）。
- 未签名的安装包不得对外发布宣传（README 明文约束）。

## 契约键语义锚

- required_reading（执行前必读）：README.md、desktop/package.json——README「打包桌面端」节是部署命令与产物形态的唯一权威（本技能正文已声明冲突以 README 为准）。
- authoritative_sources（冲突裁决）：README.md——技能正文是操作化展开，冲突以权威为准。
