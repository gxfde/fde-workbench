import type { ReactNode } from "react"

import "./help.css"

// 工作台内嵌使用手册（#help）：素材来自 docs/工作台操作使用手册.md，
// 覆盖模块操作说明 + 门禁 G1–G9 流程 + 故障排查（§14 第 2 条：
// 门禁"提交后转圈又回到未提交"绝大多数是登录态问题，先重登再查参数）。

interface HelpSection {
  id: string
  title: string
  body: ReactNode
}

const SECTIONS: HelpSection[] = [
  {
    id: "getting-started",
    title: "开始前：三件必查的事",
    body: (
      <>
        <p>桌面端能进界面，不等于后端活着。绝大多数"点了没反应 / 一直转圈"是后端没起或登录态过期。</p>
        <ol>
          <li>
            <strong>后端服务是否在跑</strong>：桌面端连本地 API（默认
            <code>http://127.0.0.1:8010</code>）。后端没起时所有页面报"无法连接服务端"。
            起法：<code>docker compose up -d api worker scheduler</code>（见「故障排查」第 1 条）。
          </li>
          <li>
            <strong>后台 worker 是否在跑</strong>：文档生成类操作（调研导出、项目计划导出、SOW
            导出）都靠 worker 消费队列；worker 没起时这些操作会一直停在"正在后台生成…"。
          </li>
          <li>
            <strong>登录态是否过期</strong>：访问令牌 15 分钟过期，靠 30 天刷新令牌自动续。
            如果突然全按钮"提交后转圈又回到未提交"，先「退出登录」重新登录一次。
          </li>
        </ol>
        <p>首次登录会进"强制改密"页，改完才能看到工作台；忘记密码找管理员在"用户管理"里重置。</p>
      </>
    ),
  },
  {
    id: "roles",
    title: "角色与权限",
    body: (
      <table className="help-table">
        <thead>
          <tr><th>角色</th><th>能干什么</th></tr>
        </thead>
        <tbody>
          <tr><td>管理员（admin）</td><td>全部模块 + 系统管理（行业模板 / 文档模板 / 模块 / 用户 / 系统配置）</td></tr>
          <tr><td>项目负责人（project_lead）</td><td>名下项目的管理操作</td></tr>
          <tr><td>工程师（fde_engineer）</td><td>被指派的工程任务，可填调研表</td></tr>
          <tr><td>查看者（viewer）</td><td>基本只读，大量按钮不渲染</td></tr>
        </tbody>
      </table>
    ),
  },
  {
    id: "projects",
    title: "项目工作台",
    body: (
      <>
        <ul>
          <li>登录后默认进项目列表：按 状态 / 负责人 / 行业 / 模块「应用筛选」，点卡片「进入项目」。</li>
          <li>「新建项目」（管理员 / 项目负责人）三种方式：从模板新建 / 上传预调研表（.docx，AI 解析回填）/ 手动 4 步向导（基础信息 → 负责人 → 首期模块 → 确认创建）。</li>
          <li>新建时<strong>必填</strong>只有：项目名称、客户代号、计划开始日期；客户代号格式"客户A·行业·城市"，实名映射只在 fdeops/openfde。</li>
          <li>勾选有前置依赖的模块时前置自动补选；取消前置会被拦。</li>
        </ul>
        <p>项目详情 10 个标签页：概览 / 任务 / 门禁 / 报价收款 / 调研 / 方案设计 / 工作流 / 术语表 / 文件库 / 项目管理（键盘左右可切换，可书签直达）。</p>
        <ul>
          <li><strong>概览</strong>：改状态（状态机约束）、编辑基本信息、看甘特图；「导出项目计划及进度」前提是管理员已发布"项目计划及进度"文档模板。</li>
          <li><strong>任务</strong>：进度 0–100 整数；工期必须与计划起止的工作日数一致；阻塞必须写原因。</li>
          <li><strong>调研</strong>：左树选对象，写共用/个人备忘录（Ctrl+S 保存），填调研表，导出到文件库；查看者只能看不能填；未保存离开会被拦。</li>
          <li><strong>方案设计</strong>：关联 AI 机会写方案 → 保存 → 导出 SOW；"弃用"需输密码确认。</li>
          <li><strong>文件库</strong>：按 类型/业务阶段/状态 筛选，上传（≤100MB），下载/预览/版本/弃用/恢复；生成失败点「重新生成」。</li>
        </ul>
      </>
    ),
  },
  {
    id: "workflow-ontology",
    title: "工作流与术语表",
    body: (
      <ul>
        <li><strong>工作流</strong>：定义卡片（草稿/已发布/已归档 · 版本 · 节点数）+ run 列表（排队中/运行中/等待审批/已暂停/成功/失败/已取消，附错误摘要与 truncated 提示）；点开单条 run 看节点树（八态 + attempt + 错误信息）。</li>
        <li>「取消」仅非终态 run 可点——对已结束 run 再取消是幂等语义；「恢复」仅"失败"的 run，失败/已跳过节点重投，其余状态提示不可恢复。定义的新建/发布暂无 UI 入口（见"已知功能缺口"）。</li>
        <li><strong>术语表</strong>：术语只读（按规范名或别名搜索，合并让位显示"（让位别名）"）；关系类型只读卡片（登记/停用走管理通道，全局行需系统运维员）。</li>
        <li><strong>变更集评审</strong>：AI 候选与人工提案的唯一落点——草稿 → 评审中 → 已确认/已否决，确认前不物化；否决必须写理由；自己提交自己确认会被 403 拒（拍板人≠提交人）。</li>
      </ul>
    ),
  },
  {
    id: "gates",
    title: "门禁 G1–G9（最常卡住的地方）",
    body: (
      <>
        <p>
          每门 5 态：<strong>待证据 → 待核验 → 已过门 / 有条件通过（仅 G9）/ 未过门</strong>。
          核心规则：<code>claimed ≠ accepted</code> —— 清单项在人工核验"接受"之前一律是黄标。
        </p>
        <table className="help-table">
          <thead>
            <tr><th>Gate</th><th>清单要交什么</th></tr>
          </thead>
          <tbody>
            <tr><td>G1 立项</td><td>评分记录</td></tr>
            <tr><td>G2 需求确认</td><td>真需求卡（leads.md 附）</td></tr>
            <tr><td>G3 诊断交付</td><td>诊断报告（数字全 claimed）、SOW-A 签署、A 款预付到账、数据授权书</td></tr>
            <tr><td>G4 合同签署</td><td>SOW-B/C、结果合同页、报价单、里程碑计划、SOW-B 签署、B 预付 50%、独立 SOW-C</td></tr>
            <tr><td>G5 交付启动</td><td>trust-profile/success/brief 等 .fde/ 全套</td></tr>
            <tr><td>G6 方案设计</td><td>问题陈述（SCQA）、基线数字、非目标清单</td></tr>
            <tr><td>G7 试点</td><td>options 文档、success.md 定稿、Eval 计划、B 试点章程定稿</td></tr>
            <tr><td>G8 上线决策</td><td>prototype-log、POC 验收表、business-case（过门必须选 proceed/pivot/stop）</td></tr>
            <tr><td>G9 上线门禁</td><td>生产环境、Runbook、Go-Live 单、演练记录、SOW-C 里程碑（末款绑 G9，可 conditional_pass）</td></tr>
          </tbody>
        </table>
        <p><strong>操作流程</strong>（管理员 / 项目负责人）：</p>
        <ol>
          <li>
            "待证据"/"未过门"点「提交证据」：逐项填出处指针（如
            <code>fdeops://engagements/&#123;代号&#125;/.fde/…</code>）和 64 位 sha256
            （Windows 用 <code>certutil -hashfile 文件名 SHA256</code> 生成）；<strong>全部清单项填完</strong>才能提交。
          </li>
          <li>
            "待核验"点「人工核验拍板」：勾选接受（默认全不勾）；<strong>pass 要求清单项全部勾 accepted</strong>；
            可选 fail（G9 还可 conditional_pass）；可附 500 字内拍板说明；提交后"事件留痕"追加一条记录。
          </li>
        </ol>
        <p className="help-warn">
          "全部显示未提交 / 提交后转圈又回去"多数不是门禁服务坏了，而是<strong>登录态问题</strong>——
          先「退出登录」重新登录再试；仍卡着看 Network 里
          <code>/gates/…/evidence</code> 返回的是 401（认证）还是 400（参数，通常是 sha256 不足 64 位）。
        </p>
      </>
    ),
  },
  {
    id: "gates-walkthrough",
    title: "实操示例：证据文件怎么写（somwyn 样板）",
    body: (
      <>
        <p>
          每个项目的门禁证据都放在
          <code>{"D:\\test\\FDE\\engagements\\fdeops\\<项目代号>\\.fde\\gates\\"}</code>
          ——用编辑器直接写文件，工作台只交「出处指针 + sha256」。somwyn 项目已建好 30 件样板，可直接照抄结构。
        </p>
        <p><strong>三步流程（以 somwyn 为例）：</strong></p>
        <ol>
          <li>
            <strong>写文件</strong>：进
            <code>D:\test\FDE\engagements\fdeops\somwyn\.fde\gates\</code>，
            按 <code>G1-评分记录.md</code>、<code>G3-诊断报告.md</code> 这类命名写真实内容；
            签署扫描件/银行回单属"放置实际件"——把 PDF/图片放进本目录，说明页里写了核验点。
          </li>
          <li>
            <strong>算哈希</strong>：在 gates 目录运行 <code>哈希清单.ps1</code>（右键"使用 PowerShell 运行"），
            一次列出全部文件的 sha256 与建议 URI，直接复制。
          </li>
          <li>
            <strong>工作台提交</strong>：门禁 → 对应 G → 提交证据 → 贴 URI + 64 位哈希 →
            全部清单项填完 → 提交（标 claimed）→ 有权限的人「人工核验拍板」。
          </li>
        </ol>
        <p><strong>门 → 文件对照（somwyn 实际 30 件）：</strong></p>
        <table className="help-table">
          <thead>
            <tr><th>门</th><th>文件</th></tr>
          </thead>
          <tbody>
            <tr><td>G1 / G2</td><td>评分记录；真需求卡（leads.md 附页）</td></tr>
            <tr><td>G3</td><td>诊断报告 + SOW-A 签署件 + A 款到账回单 + 数据授权书（后三件放实际凭证）</td></tr>
            <tr><td>G4</td><td>SOW-B/C 草稿、结果合同页、报价单（可用工作台报价模块做底稿）、里程碑计划（可用项目计划导出）、SOW-B 签署件、B 预付 50% 回单、独立 SOW-C —— 共 7 件</td></tr>
            <tr><td>G5</td><td><strong>不用新写</strong>——.fde 根目录的 trust-profile / success / brief 就是全套，URI 直接指过去</td></tr>
            <tr><td>G6</td><td>问题陈述（SCQA）、基线数字、非目标清单</td></tr>
            <tr><td>G7</td><td>options 文档、success 定稿确认、Eval 计划、B 试点章程（需客户书面确认）</td></tr>
            <tr><td>G8</td><td>prototype-log（部署日志就是现成素材）、POC 验收表、business-case</td></tr>
            <tr><td>G9</td><td>生产环境说明、Runbook、Go-Live 单（客户签署件）、演练记录、SOW-C 里程碑核验（40/40/20 末款绑 G9）</td></tr>
          </tbody>
        </table>
        <p>
          <strong>数字类内容先标 claimed</strong>：没和客户核实的数字一律标 claimed，人工核验后才算 accepted；
          <strong>别把占位模板直接提交</strong>——那是假证据，核验这关过不去，也污染事件留痕。
        </p>
        <p className="help-warn">
          <strong>隐私铁律</strong>：真实客户资料只存 fdeops/openfde 文件层（数据库里只有代号）。
          <code>gates</code> 所在的 .fde 仓库<strong>永不配置远程</strong>（不进 GitHub，本地版本历史足够）；
          签署扫描件/回单已被 .gitignore 排除（<code>gates/*实际件*、*.pdf/jpg/png</code>），只留文件系统。
        </p>
      </>
    ),
  },
  {
    id: "commercial",
    title: "报价收款",
    body: (
      <ul>
        <li>一键「首单默认参数（轻量 / ¥150/h / ×1.0）」建报价；或展开「自定义系数」选 档位 / 锚点 / 时薪 / 系数。</li>
        <li>报价卡显示公式价、锚点区间、建议报价与 claims 核验进度；首单要回填"实际工时"校准；成交后「回填成交价」。</li>
        <li>收款：选 SOW 类型（B 50/50、C 40/40/20、A 预付、D 月付预付）+ 合同基数，「生成收款计划」；每行可「设到期」「回填」实收与发票号。</li>
        <li>合同卡片只存指针（PDF 在 fdeops）：填签约日、验收窗口、账期、终止条款摘要和 fdeops:// 指针，「登记/更新」。</li>
      </ul>
    ),
  },
  {
    id: "bridge",
    title: "集成桥",
    body: (
      <ul>
        <li>openfde 知识轨 + fdeops 流程轨的只读投影；真相在文件，"文件永远赢"；采集节奏宿主计划任务每 4 小时。</li>
        <li>三个按钮分工：「立即采集」触发宿主计划任务马上采一轮（新快照到站后本页自动刷新，约 1–3 分钟）；「刷新」只重读台内投影；「重新投影」用最近一次快照重投影——后两者都不触发宿主采集。</li>
        <li>"文件已删"行有「清投影」：只清投影，不动真相文件。</li>
        <li>Engagement 为空 ≠ 坏了，是采集器还没跑过；超过 6 小时无快照会出现"⚠ 采集断连"黄警。</li>
      </ul>
    ),
  },
  {
    id: "task-center",
    title: "任务中心",
    body: (
      <ul>
        <li>"待审批操作"（AI Server 高风险动作与工作流人工审批节点）：「审核并批准」需输当前密码；「拒绝」直接拒绝；审批通过才放行/继续。</li>
        <li>项目任务看板：拖卡片到 未开始/进行中/已阻塞/已完成/已取消；拖到"已阻塞"必须填原因。</li>
        <li>自动/定时任务卡片的「立即执行」入队并提示 run id；列表每 30 秒与重新聚焦时自动刷新。</li>
      </ul>
    ),
  },
  {
    id: "ai",
    title: "AI Server 对话与扩展",
    body: (
      <ul>
        <li>右下角气泡打开对话；Enter 发送（Shift+Enter 换行）；在项目详情里发起会自动关联当前项目。</li>
        <li>可选对话模型并开"深度思考"（仅 deepseek 系支持）；完成后可展开看 Token 与费用估算。</li>
        <li>AI Server 运行时不可用时降级为纯模型直答（无工具能力），页面会提示；回复中立创商城链接会调起内置浏览器（账号有 lcsc_search 工具时）。</li>
        <li>「AI 与扩展」：个人/公共 Skill、插件登记与审批、模型管理（API Key 服务端加密）、立创工具搜索与记录对比。</li>
        <li>Skill 卡「版本」对话框：版本历史 + 效果统计（对话/工作流消费、按版本分布）+ 治理动作（提交评审/发布/回滚/弃用，均需当前密码；权限外只读）。</li>
        <li>所有 AI 功能依赖模型服务的 API Key 已配置，否则报"AI 服务尚未配置，请联系管理员"。</li>
      </ul>
    ),
  },
  {
    id: "admin",
    title: "管理页（仅管理员）",
    body: (
      <ul>
        <li><strong>行业模板</strong>：建/编辑/发布/停用；只有"已发布"版本才能被"新建项目-从模板新建"选用；草稿可让 AI 生成后人工审核发布。</li>
        <li><strong>文档模板</strong>：四类 DOCX（调研结果/项目计划及进度/PoV/SOW），上传→测试→发布；<strong>这是 SOW、项目计划、调研结果能否生成的前置</strong>。</li>
        <li><strong>模块管理</strong>：模块标识创建后不可改；停用后不再出现在模板可选模块里；并发冲突先「刷新模块版本」再重做。</li>
        <li><strong>用户管理</strong>：建账号（临时密码 ≥6 位，首次登录强制改密）、改角色、AI 权限分级、停用/启用、重置密码。</li>
        <li><strong>系统配置</strong>：AI 模型服务 / AI Server / 微信 ClawBot / 存储与 ClamAV；密钥"留空保持不变"。</li>
      </ul>
    ),
  },
  {
    id: "troubleshooting",
    title: "故障排查（照顺序查最快）",
    body: (
      <ol>
        <li>
          <strong>整个工作台打不开 / "无法连接服务端"</strong>：起后端（WSL 里）：
          <code>docker compose up -d api worker scheduler</code>；改过 server 源码后要
          <code>docker compose build</code> + <code>up -d</code> 重建，并
          <code>docker exec fde-workbench-api-1 alembic upgrade head</code>（迁移不会自动跑）。
        </li>
        <li>
          <strong>门禁"转圈又回到未提交"</strong>：先「退出登录」重新登录；仍卡看 Network 里
          <code>/gates/…/evidence</code> 的响应码（401=认证，400=参数，通常是 sha256 不足 64 位）。
        </li>
        <li><strong>文档生成一直"正在后台生成"</strong>：worker 没跑，补 <code>docker compose up -d worker</code>。</li>
        <li><strong>导出报"模板未发布"</strong>：管理员去"文档模板"上传并发布对应 DOCX 再导。</li>
        <li><strong>"内容已被其他人更新"</strong>：乐观锁冲突，点提示里的「刷新」按钮再重做。</li>
        <li><strong>AI 报"尚未配置"</strong>：管理员补模型 API Key（系统配置 / 模型管理）。</li>
        <li><strong>集成桥空 / 采集断连</strong>：宿主计划任务（每 4 小时）或 WSL 服务停了；先点「立即采集」试一轮，仍不行再检查计划任务与 logs/bridge-poll.log。</li>
        <li><strong>某按钮看不到</strong>：看角色（见"角色与权限"）；查看者大量按钮不渲染。</li>
      </ol>
    ),
  },
]

const KNOWN_GAPS: string[] = [
  "调研表 confirm / reject / revise 三态流转——暂无前端入口。",
  "自动任务创建——暂无前端入口（只能靠已有入口/服务）。",
  "扩展市场搜索/同步——服务在跑但页面无入口。",
  "工作流定义的新建/发布——暂无人工 UI 入口（控制台只读呈现 + 运行控制）。",
]

export function HelpPage() {
  // 目录用页内滚动而非 hash 锚点：hash 变更会被路由解析器接管（#help/x
  // 会被归到项目页），改用 scrollIntoView 直达章节。
  function jumpTo(sectionId: string): void {
    document.getElementById(sectionId)?.scrollIntoView({ behavior: "smooth", block: "start" })
  }

  return (
    <section className="page page-stack help-page" aria-label="使用帮助">
      <div className="page-header">
        <h1>使用帮助</h1>
        <p className="supporting-copy">
          随时查阅各模块怎么用、门禁 G1–G9 怎么提交、出问题按哪条查。
          完整文字版手册：仓库 <code>docs/工作台操作使用手册.md</code>。右下角智能助手内置了这本手册的服务端副本（与实操作例等章节保持同步）：问它
          「使用帮助里怎么说 / 门禁怎么提交证据」这类问题时，它会用 help_fetch 工具按章节检索手册原文再作答。
        </p>
      </div>

      <nav className="help-toc" aria-label="目录">
        {[...SECTIONS.map((section) => section.id), "known-gaps", "release-notes"].map((id) => {
          const title = SECTIONS.find((section) => section.id === id)?.title
            ?? (id === "known-gaps" ? "已知功能缺口" : "发布与升级")
          return (
            <button key={id} type="button" className="help-toc-link" onClick={() => jumpTo(id)}>
              {title}
            </button>
          )
        })}
      </nav>

      {SECTIONS.map((section) => (
        <section key={section.id} className="help-section" id={section.id}>
          <h2>{section.title}</h2>
          {section.body}
        </section>
      ))}

      <section className="help-section" id="known-gaps">
        <h2>已知功能缺口（暂无前端入口，别到处找）</h2>
        <ul>
          {KNOWN_GAPS.map((gap) => (
            <li key={gap}>{gap}</li>
          ))}
        </ul>
      </section>

      <section className="help-section" id="release-notes">
        <h2>发布与升级</h2>
        <p>
          Windows 安装包未签名、未发行验收；客户端无自更新，升级走"重新打包 + 数据库迁移"。
          数据库升级前同时备份 PostgreSQL 和文件存储。
        </p>
      </section>
    </section>
  )
}
