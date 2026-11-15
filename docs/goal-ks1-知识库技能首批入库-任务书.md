# Goal 任务书：知识库技能首批入库（ks1 线）

> 发起：蔡工 2026-11-11 委托拟订；验收归发起会话（管理者复跑明卷＋暗卷后给人话报告）。
> 用法：新开会话，让执行 agent 完整读取本文件后按书执行；本文件对执行者只读。

你是执行者，这份文档是你唯一的任务来源；中途没人可问，拿不准的写 `docs/skill-library/BLOCKED.md`，跳过继续做别的，最后随交付提交。断了换新会话：先读 `docs/skill-library/PROGRESS.md` 接着做，别重做；每做完一项立刻更新。这活为什么干：把外部 FDE 知识库（D:/test/FDE/knowledge，已有 24 份提炼卡）里已蒸馏的交付方法论，独立重写成 5 份技能文档入库，作为「知识库→交付系统技能中心」线的第一批件；干完后蔡工可在桌面端把它们逐份录成个人技能。让步顺序：许可合规 > 独立重写 > 数量 > 速度。「只允许／不许」违反即失败；「建议」有更好的路可以走，在 PROGRESS.md 记一句为什么。

## 我替领导拍的板
1. 首批就写下面固定的 5 个主题（猜的）｜猜错代价=这批白写，领导可在发起前直接改名单。
2. 原料只读 cards/ 提取卡与 _extracted/ 抽取文本，不读 PDF 原件（猜的）｜代价=可能漏 PDF 独有细节；卡层是已提炼层，风险低。
3. 本批只产仓库文档，不写数据库、不发布技能——录入技能中心由蔡工在桌面端亲手做（猜的）｜代价=技能暂不生效。
4. 诊断知识种子、训练场案例两个落点不在本批（串行，先技能包）｜代价=那两线延后。

## 界限
- 在独立 worktree 干活（主工作树被另一条线占着，别碰它的检出分支与未跟踪文件）。
- 只允许新建：`docs/skill-library/` 下全部文件；其余一律只读。`PROGRESS.md`/`BLOCKED.md` 也放这个目录。
- 本任务书文件只读，不许修改、不许搬动。
- 不许读：`D:/test/FDE/knowledge/诊断案例集/`（评测答案，污染红线）；`D:/test/FDE/knowledge/fde-skills/` 仓正文（AGPL+许可混置）；D:/test/FDE 下 fdeops、openfde 目录。
- 不许写 D:/test/FDE 下任何文件；不许 push origin（上游，永只读）；不许动 main。
- 没有判卷脚本，验收=本文给出的命令；顺手修无关问题→写 BLOCKED.md。

## 现状与任务 0（2026-11-11 实测）
- 提取卡 24 份：`ls "D:/test/FDE/knowledge/cards" | wc -l` → 24。
- 许良手册抽取件在场：`ls "D:/test/FDE/knowledge/_extracted" | grep 许良` → 非空（卡01 登记其开源仓 the-fde-handbook 为 MIT）。
- 本地 main=fork/main 零差异；fork/main 顶=`e05f1d6`。
- `.git/hooks/pre-commit` 跑全量 pytest（约 40 分钟）⇒ 本批提交一律 `git commit --no-verify`，质量闸在 CI。
任务 0：建独立 worktree 并复跑上面三条核对（命令都须真实存在、数字逐个对上）：
```
git -C D:/test/fde-workbench worktree add -b skill-library-batch1 D:/test/fde-wt-skilllib fork/main
```
之后一切操作在 D:/test/fde-wt-skilllib 内。对不上→停，证据写 BLOCKED.md 最上面，只做不受影响的部分。核对无误后把「理解的目标／顺序／最大风险」≤10 行写进 PROGRESS.md 再动工。

## 任务 1：许可账（排在写技能之前——来源不可用=白写）
写 `docs/skill-library/batch-1/LICENSE-AUDIT.md`：本批引用到的每个来源一行，列：来源路径｜许可（实读其 LICENSE 或卡内登记，注明依据出处）｜快照日期｜可用层（MIT=可改编；无开源许可=仅抽象借鉴）。已知：卡01 许良=MIT；卡05 白皮书／卡08 工作手册／卡11 案例100／卡12 FDE-main=无开源许可⇒仅抽象。某来源许可查不清→弃用该来源、换卡层主题并在 BLOCKED.md 登记，不许先写后补。
验收：`grep -c "|" docs/skill-library/batch-1/LICENSE-AUDIT.md` ≥ 5。

## 任务 2：5 份技能文档
写到 `docs/skill-library/batch-1/`，文件名与主题固定：
1. `SKILL-01-presales-diagnosis.md` 售前诊断提问框架（源：卡01+卡11）
2. `SKILL-02-gate-review-discipline.md` 门禁评审怎么开（源：卡01+卡05）
3. `SKILL-03-pricing-proposal.md` 报价结构与收费口径（源：卡08+卡01）
4. `SKILL-04-weekly-value-report.md` 客户周报价值三分法（源：卡12+卡11）
5. `SKILL-05-handover-closeout.md` 移交撤场要点（源：卡01）
死规矩（每份适用，违一份=整批失败）：
- 每份 ≤6000 字，四节固定：适用场景／怎么做／人机边界（AI 只起草与核对，承诺、拍板、收付款永远是人）／来源对照表（声明独立重写：用了哪些卡的哪些抽象维度）。
- 只做抽象借鉴：分类维度与判据结构可参考；条目措辞、清单顺序、表格结构必须自己重写，不复现原文条目序列。
- 效果数字／市场数字一律不进正文（改写为「以客户自身基线为准」类表述）；流程性参数（如时限）自定不受限。
- 系统门禁清单的唯一权威是本仓 `server/seeds/gates.json`——第 2 份只写怎么开评审，不复述清单本身。
自检（防抄）：每份写完，从正文随机取 3 句、各截 ≥15 字连续片段，去对应 `_extracted/*.txt` 与卡原文 grep——不得命中（本批禁原文引用）；命中=改写后重测。
验收：
```
ls docs/skill-library/batch-1/SKILL-*.md | wc -l    # = 5
for f in docs/skill-library/batch-1/SKILL-*.md; do grep -q "来源对照" "$f" || echo "MISSING:$f"; done    # 无输出
```
反向验证：临时建缺「来源对照」节的 `SKILL-TEST.md` 跑上面的循环→必须打印 MISSING；删掉重跑→无输出。两段输出都贴对话。

## 任务 3：索引与交付
`docs/skill-library/batch-1/README.md`：5 份清单+每份一句用途+录入指引（桌面端扩展页→个人技能，一技能一版本、正文直接粘贴，注明蔡工亲手录）+「本批全部为独立重写」的批量声明。提交与 PR（--no-verify 只免本地钩子，不豁免 CI）：
```
git add docs/skill-library
git commit --no-verify -m "docs(skill-library): 知识库技能首批 5 份独立重写+许可账"
git push fork skill-library-batch1
gh pr create -R caishide/fde-workbench --base main --fill
```

## 规矩
- 防作弊点名：禁 `|| true`；禁跳过或放松上面任何检查；禁把「重写」偷换成「改几个词」（正文与源连续 ≥15 字相同即失败；卡内带引号短引用本批一律不用）；LICENSE-AUDIT 每行必须有实读出处，编造许可=失败。
- 同一条验收连败 3 次→换下一项并记录；结果比开工差→回滚如实报告（没做成但说清了=合格，做了但更糟=不合格）。
- 不新增依赖、不装工具、不改 CI；需要就写 BLOCKED.md。
- PR 的 CI 四个 job 应全绿（纯文档改动）；红了修自己，不许改 CI 或判卷。

## 完成条件
① `git log --oneline fork/main..skill-library-batch1` 非空且 PR 链接已贴对话；② 任务 2 两条验收命令输出=5 与无输出；③ `grep -rniE "诊断案例集|fde-skills" docs/skill-library/batch-1/SKILL-*.md docs/skill-library/batch-1/README.md` 无输出。每条都在对话里贴实际命令输出（含反向验证的红→绿证据），只说「做完了」不算。BLOCKED.md 随交付提交，空的也写「无」。或已跑满 3 轮重试——满轮即停，如实汇报卡在哪、还差什么。
