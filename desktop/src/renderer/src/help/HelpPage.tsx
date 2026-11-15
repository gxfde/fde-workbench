import { useEffect, useState, type ReactNode } from "react"

import "./help.css"

// 工作台内嵌使用手册（#help）。
//
// 结构约定：每个功能章节按「适用场景 → 前置条件 → 操作步骤 → 预期结果 → 常见问题」组织，
// 新用户可只读「操作步骤」独立完成动作，老用户可只查「常见问题」定位卡点。
//
// 事实核对基线（2026-11-07，改写时逐条比对代码与种子数据）：
//   · 项目详情标签页 13 个（ProjectDetailPage.tsx tabs 定义：概览/任务/门禁/报价收款/调研/方案设计/工作流/智能体/评审会/术语表/执行事实/文件库/项目管理）
//   · 门禁状态机 pending → evidence → passed | conditional_pass | failed（gate_service.py:42）
//   · conditional_pass 仅 G9；G8 过门必须书面拍板 proceed / pivot / stop（gate_service.py:450-470）
//   · G1–G9 清单项逐项对齐 server/seeds/gates.json
//   · 访问令牌 15 分钟过期、刷新令牌 30 天（config.py:22-23）
//   · 单文件上传上限 100MB（files/service.py:42）
//   · 采集断连阈值 360 分钟（bridge/sync.py:27）

interface HelpSection {
  id: string
  title: string
  body: ReactNode
}

/** 章节内的结构化小节，用于统一「适用场景 / 前置条件 / 操作步骤 / 预期结果 / 常见问题」五要素。 */
function Steps({ items }: { items: ReactNode[] }): ReactNode {
  return (
    <ol className="help-steps">
      {items.map((item, index) => (
        <li key={index}>{item}</li>
      ))}
    </ol>
  )
}

const SECTIONS: HelpSection[] = [
  {
    id: "start",
    title: "新手上路：5 分钟跑通第一个项目",
    body: (
      <>
        <p className="help-lead">
          如果你第一次用这个工作台，按这四步走一遍，就能完成「建项目 → 填调研表 → 提交门禁证据」的主线。
          每一步都能独立看懂，不需要先读完整个手册。
        </p>

        <h3>第 1 步：确认后端在跑（1 分钟）</h3>
        <p>
          <strong>适用场景</strong>：界面能打开，但页面报错、或按钮点了没反应。
        </p>
        <p>
          <strong>前置条件</strong>：已安装 Docker Desktop 和 WSL。
        </p>
        <Steps
          items={[
            <>
              打开 WSL 终端，进项目目录，执行 <code>docker compose up -d api worker scheduler</code>。
            </>,
            <>
              回到桌面端刷新。<strong>三个服务缺一不可</strong>：<code>api</code> 提供接口，
              <code>worker</code> 消费导出队列，<code>scheduler</code> 跑定时任务。
            </>,
          ]}
        />
        <p>
          <strong>预期结果</strong>：项目列表正常加载，不再报「无法连接服务端」。
        </p>
        <p className="help-warn">
          <strong>常见问题</strong>：只有 api 起来、worker 没起时，页面看起来正常，但导出类操作会一直停在
          「正在后台生成…」。看到这句提示就补 <code>docker compose up -d worker</code>。
        </p>

        <h3>第 2 步：建一个项目（2 分钟）</h3>
        <p>
          <strong>适用场景</strong>：第一次使用，或需要为新客户建交付项目。
        </p>
        <p>
          <strong>前置条件</strong>：需要管理员或项目负责人权限（查看者看不到「新建项目」按钮）。
        </p>
        <Steps
          items={[
            <>
              点「新建项目」，选一种方式：
              <strong>从模板新建</strong>（推荐，快）、
              <strong>上传预调研表</strong>（.docx 自动解析回填）、
              <strong>手动向导</strong>（基础信息 → 负责人 → 首期模块 → 确认创建）。
            </>,
            <>
              填写<strong>必填</strong>三项：项目名称、客户名称、计划开始日期。
            </>,
            <>
              客户名称填称呼即可；<strong>所属行业</strong>可从下拉里选，也可跳过。
              系统会自动拼出内部代号，<strong>不用手写格式</strong>。
              联系人/电话/地址等实名资料不要填在这里——真实资料只留在 fdeops/openfde 文件目录，
              永远不进数据库和 Git。
            </>,
            <>
              勾选首期模块。有前置依赖的模块会自动补选前置，取消前置会被系统拦下。
            </>,
          ]}
        />
        <p>
          <strong>预期结果</strong>：生成一个含 13 个标签页的项目详情页。
        </p>
        <p className="help-warn">
          <strong>常见问题</strong>：「新建项目」按钮看不见 → 你的角色不是管理员或项目负责人；
          代号格式被拒 → 检查是否用了三个「·」分隔的两段式。
        </p>

        <h3>第 3 步：填一份调研表（1 分钟）</h3>
        <p>
          <strong>适用场景</strong>：调研阶段，需要把访谈内容结构化记录下来。
        </p>
        <p>
          <strong>前置条件</strong>：项目已建好；工程师或项目负责人权限。
        </p>
        <Steps
          items={[
            <>
              进项目 →「调研」标签 → 左侧树选中调研对象。
            </>,
            <>
              在「共用备忘录」或「个人备忘录」写记录，按 <code>Ctrl+S</code> 保存。
            </>,
            <>
              填调研表，点「确认事实」提交。事实确认后若要改，点「创建修订版」——修订版会留下完整版本链，
              不会覆盖原始记录。
            </>,
          ]}
        />
        <p>
          <strong>预期结果</strong>：调研表进入「已确认」状态，可用于导出调研结果文档。
        </p>
        <p className="help-warn">
          <strong>常见问题</strong>：提示「内容已被其他人更新」→ 点提示里的「刷新」再重做，这是并发编辑保护，
          不是故障；有未保存内容想离开 → 会被拦下，先保存。
        </p>

        <h3>第 4 步：提交一道门禁证据（1 分钟）</h3>
        <p>
          <strong>适用场景</strong>：阶段推进，需要证据让门禁放行。
        </p>
        <p>
          <strong>前置条件</strong>：对应门禁处于「待证据」或「未过门」；证据文件已写好并算出哈希。
        </p>
        <Steps
          items={[
            <>
              进「门禁」标签，点对应门（如 G1），点「提交证据」。
            </>,
            <>
              逐项填写：证据文件的<strong>出处指针</strong>（如
              <code>fdeops://engagements/&#123;代号&#125;/.fde/…</code>）和 <strong>64 位 sha256 哈希</strong>。
            </>,
            <>
              <strong>必须全部清单项填完</strong>才能提交。Windows 上用
              <code>certutil -hashfile 文件名 SHA256</code> 生成哈希。
            </>,
            <>
              提交后状态变为「待核验」，等待有拍板权限的人做人工核验。
            </>,
          ]}
        />
        <p>
          <strong>预期结果</strong>：门禁从「待证据」变为「待核验」，事件留痕追加一条记录。
        </p>
        <p className="help-warn">
          <strong>常见问题</strong>：提交后转圈又回到未提交 → 九成是登录态过期，先「退出登录」重新登录；
          还卡着就看 Network 里 <code>/gates/…/evidence</code> 的返回码：<strong>401</strong> 是认证问题，
          <strong>400</strong> 是参数问题（常见于 sha256 不足 64 位）。
        </p>
      </>
    ),
  },
  {
    id: "prerequisites",
    title: "开始前：三件必查的事",
    body: (
      <>
        <p className="help-lead">
          桌面端能打开界面，不等于后端活着。绝大多数「点了没反应 / 一直转圈」都出在这三件事上。
          接手一台新机器、或长时间没打开工作台时，先查这一节。
        </p>

        <h3>1. 后端服务是否在跑</h3>
        <p>
          <strong>适用场景</strong>：任何页面报「无法连接服务端」。
        </p>
        <p>
          <strong>前置条件</strong>：Docker Desktop 已启动。
        </p>
        <Steps
          items={[
            <>
              连接地址由发行形态决定：桌面端使用打包时配置的 API 地址，浏览器版走同源 <code>/api</code>，均无需手动填写。
            </>,
            <>
              在 WSL 里执行 <code>docker compose up -d api worker scheduler</code> 启动全部三个服务。
            </>,
            <>
              <strong>改过 server 源码后必须重建</strong>：<code>docker compose build</code> →
              <code>docker compose up -d</code> →
              <code>docker exec fde-workbench-api-1 alembic upgrade head</code>。
              只跑 <code>up -d</code> 不会更新代码，迁移也不会自动执行。
            </>,
          ]}
        />
        <p>
          <strong>预期结果</strong>：<code>docker compose ps</code> 三个服务都是 running 状态。
        </p>

        <h3>2. 后台 worker 是否在跑</h3>
        <p>
          <strong>适用场景</strong>：调研结果导出、项目计划导出、SOW 导出一直停在「正在后台生成…」。
        </p>
        <p>
          <strong>前置条件</strong>：api 已启动。
        </p>
        <Steps
          items={[
            <>
              补 <code>docker compose up -d worker</code>。
            </>,
          ]}
        />
        <p>
          <strong>预期结果</strong>：导出任务进入队列后，几秒到几十秒内在文件库出现结果。
        </p>

        <h3>3. 登录态是否过期</h3>
        <p>
          <strong>适用场景</strong>：全页面按钮「提交后转圈又回到未提交」，且其他操作也陆续失效。
        </p>
        <p>
          <strong>前置条件</strong>：能正常进入登录页。
        </p>
        <Steps
          items={[
            <>
              访问令牌 <strong>15 分钟过期</strong>，靠 <strong>30 天</strong>有效的刷新令牌自动续期。
            </>,
            <>
              如果自动续期失效（换机器、刷新令牌过期、时钟异常），「退出登录」后重新登录一次即可。
            </>,
          ]}
        />
        <p>
          <strong>预期结果</strong>：所有操作恢复正常。
        </p>
        <p className="help-warn">
          <strong>首次登录会被强制改密</strong>，改完才能看到工作台。忘记密码请管理员在「用户管理」里重置。
        </p>
      </>
    ),
  },
  {
    id: "roles",
    title: "角色与权限：为什么某个按钮不见了",
    body: (
      <>
        <p className="help-lead">
          界面按权限裁剪。看不到某个按钮，多数不是故障，而是你的角色没有该权限。
          先查这张表，再决定找谁。
        </p>

        <h3>四种角色</h3>
        <table className="help-table">
          <thead>
            <tr><th>角色</th><th>能做什么</th></tr>
          </thead>
          <tbody>
            <tr><td>管理员（admin）</td><td>全部模块 + 系统管理（行业模板 / 文档模板 / 模块管理 / 用户管理 / 系统配置）</td></tr>
            <tr><td>项目负责人（project_lead）</td><td>名下项目的全部管理操作，包括建项目、提门禁证据、拍板</td></tr>
            <tr><td>工程师（fde_engineer）</td><td>被指派的工程任务，可填调研表</td></tr>
            <tr><td>查看者（viewer）</td><td>只读。写操作按钮不渲染，只能看</td></tr>
          </tbody>
        </table>
        <p>
          <strong>预期结果</strong>：按上表对照，你看到的界面应当与角色一致。
        </p>
        <p className="help-warn">
          <strong>常见问题</strong>：「提交证据」按钮不见了 → 需要项目负责人或管理员权限；
          「人工核验拍板」不见 → 拍板人不能是提交人，你自己提的证据要别人拍；
          「系统管理」入口不见 → 你是非管理员。
        </p>
      </>
    ),
  },
  {
    id: "project",
    title: "项目工作台",
    body: (
      <>
        <p className="help-lead">
          一个项目 = 一个客户的完整交付过程，从调研到上线。项目详情页用 13 个标签页承载全部环节。
        </p>

        <h3>项目列表</h3>
        <p>
          <strong>适用场景</strong>：找项目、切换项目。
        </p>
        <Steps
          items={[
            <>按状态 / 负责人 / 行业 / 模块筛选，缩小范围。</>,
            <>点项目卡片上的「进入项目」，进入详情页。</>,
          ]}
        />

        <h3>13 个标签页一览</h3>
        <table className="help-table">
          <thead>
            <tr><th>标签</th><th>用途</th></tr>
          </thead>
          <tbody>
            <tr><td>概览</td><td>改状态、编辑基本信息、看甘特图</td></tr>
            <tr><td>任务</td><td>任务分工、进度、依赖、阻塞</td></tr>
            <tr><td>门禁</td><td>G1–G9 证据提交与人工核验</td></tr>
            <tr><td>报价收款</td><td>报价、收款计划、合同登记</td></tr>
            <tr><td>调研</td><td>调研对象、备忘录、调研表</td></tr>
            <tr><td>方案设计</td><td>AI 机会、方案撰写、SOW 导出、交接包</td></tr>
            <tr><td>工作流</td><td>工作流定义与运行实例</td></tr>
            <tr><td>智能体</td><td>智能体运行态监控（运行列表 / 详情 / 工具调用 / 成本汇总，只读）</td></tr>
            <tr><td>评审会</td><td>评审会列表 / 话轮流 / 纪要（只读，纪要仅收敛后生成）</td></tr>
            <tr><td>术语表</td><td>术语与关系类型（只读）</td></tr>
            <tr><td>执行事实</td><td>证据、审计与调用的只读事实链</td></tr>
            <tr><td>文件库</td><td>上传、下载、版本、弃用</td></tr>
            <tr><td>项目管理</td><td>成员、模块、变更记录</td></tr>
          </tbody>
        </table>
        <p className="help-note">
          键盘 <code>←</code> <code>→</code> 切换标签页，<code>Home</code> / <code>End</code> 直接跳到第一个 / 最后一个；
          也可以用地址栏直达某个标签。
          <br />
          <strong>前提</strong>：焦点需在标签栏上（点一下当前标签，或用 <code>Tab</code> 键移进去），
          在页面其他位置按方向键不起作用。
        </p>

        <h3>概览</h3>
        <p>
          <strong>适用场景</strong>：项目初期设信息、推进状态、看整体排期。
        </p>
        <p>
          <strong>前置条件</strong>：项目已建好。
        </p>
        <Steps
          items={[
            <>
              「改状态」受状态机约束，只能跳到允许的下一状态，不能跳步。
            </>,
            <>
              「导出项目计划及进度」需要管理员<strong>先发布「项目计划及进度」文档模板</strong>，
              否则报「模板未发布」。
            </>,
          ]}
        />
        <p>
          <strong>预期结果</strong>：状态变更即时生效，甘特图按任务日期渲染。
        </p>

        <h3>任务</h3>
        <p>
          <strong>适用场景</strong>：把交付拆成可跟踪的小任务。
        </p>
        <Steps
          items={[
            <>
              进度填 <strong>0–100 的整数</strong>。
            </>,
            <>
              工期必须与计划起止日期的<strong>工作日天数一致</strong>（不含周末）。
            </>,
            <>
              标为「已阻塞」时<strong>必须写阻塞原因</strong>。
            </>,
          ]}
        />
        <p>
          <strong>预期结果</strong>：甘特图与进度统计同步更新。
        </p>

        <h3>调研</h3>
        <p>
          <strong>适用场景</strong>：整理访谈信息、填写结构化调研表。
        </p>
        <Steps
          items={[
            <>左侧树选调研对象。</>,
            <>
              写共用备忘录（团队共享）或个人备忘录（仅自己可见），<code>Ctrl+S</code> 保存。
            </>,
            <>
              填调研表 → 「确认事实」提交。确认后要改，点「创建修订版」，旧版本保留在版本链里。
            </>,
            <>
              导出调研结果到文件库（需管理员已发布「调研结果」文档模板）。
            </>,
          ]}
        />
        <p>
          <strong>预期结果</strong>：调研表变为「已确认」，可导出。
        </p>
        <p className="help-warn">
          <strong>常见问题</strong>：查看者能看不能填；未保存就切走会被拦下——这是防丢数据的机制，不是卡顿。
        </p>

        <h3>方案设计</h3>
        <p>
          <strong>适用场景</strong>：把 AI 识别出的机会写成可交付方案。
        </p>
        <Steps
          items={[
            <>关联 AI 机会 → 写方案 → 保存。</>,
            <>
              导出 SOW（需管理员已发布「SOW 工作说明书」文档模板）。
            </>,
            <>
              「弃用」方案需<strong>输入当前密码</strong>确认。
            </>,
          ]}
        />
        <p>
          <strong>预期结果</strong>：SOW 进入文件库，可进入门禁 G3 提交。
        </p>
        <p className="help-note">
          同一「方案设计」标签下方还有<strong>交接包面板</strong>，用于结项交付物打包：
          生命周期 <strong>草稿 → 封存 → 已交付</strong>，封存冻结清单与指纹，交付登记为管理员专属、不可逆。
        </p>

        <h3>文件库</h3>
        <p>
          <strong>适用场景</strong>：集中管理项目的交付物文件。
        </p>
        <Steps
          items={[
            <>按类型 / 业务阶段 / 状态筛选。</>,
            <>
              上传文件，<strong>单个文件不超过 100MB</strong>。
            </>,
            <>
              可下载、在线预览、查看版本历史、弃用、恢复弃用文件。
            </>,
            <>
              生成失败的文件点「重新生成」。
            </>,
          ]}
        />
        <p>
          <strong>预期结果</strong>：文件出现在对应筛选条件下，版本历史可追溯。
        </p>
      </>
    ),
  },
  {
    id: "agents",
    title: "智能体（运行态监控，只读）",
    body: (
      <>
        <p className="help-lead">
          这个标签页呈现本项目的智能体运行态，是一个<strong>只读监控台</strong>——
          handoff / 重试等写操作在服务器侧进行，不在本页。
        </p>
        <h3>看什么</h3>
        <Steps
          items={[
            <>运行列表：每次智能体调用一条 run，列 状态 / 所用能力 / 发起账号 / Token 消耗 / 耗时 / 是否降级；列表有界，超出会标 <code>truncated</code>。</>,
            <>点列表行展开运行详情：节点树、调用过的工具（名称 / 决策 / 能力 / 理由 / 耗时）与产物清单。</>,
            <>对 run 产物可「标记复核 / 撤回复核」——只给证据打复核标记，不改变产物本体（真相在文件）。</>,
            <>项目成本汇总：本项目全部 run 的 Token 与耗时汇总，便于看智能体开销。</>,
          ]}
        />
        <p className="help-note">
          智能体产生的证据 / 审计事实链统一归到「执行事实」标签页，本页只呈现运行态。
          服务端返回的 403/409 原样呈现，不吞。
        </p>
      </>
    ),
  },
  {
    id: "meetings",
    title: "评审会（只读呈现）",
    body: (
      <>
        <p className="help-lead">
          这个标签页呈现本项目的评审会（含门禁强制会），同样是<strong>只读</strong>——
          召集 / 插话 / 收敛等写操作不在本页。
        </p>
        <h3>看什么</h3>
        <Steps
          items={[
            <>会议列表：列 状态（进行中 / 已暂停 / 已收敛）、门禁层级（轻量门 / 标准门 / 完整门）、触发方式（强制门 / 自主召集 / 人工开会）、话轮数与召集缘由。</>,
            <>点会议行展开看话轮流（按序）。</>,
            <>纪要：会议<strong>收敛封存后</strong>才生成，含 共识 / 争议 / 待办 与封存指纹 sha256；进行中 / 已暂停的会议尚未归档，不预取纪要。</>,
          ]}
        />
        <p className="help-warn">
          <strong>常见问题</strong>：live/paused 阶段看到「会议收敛后生成纪要」属正常，不是没数据——
          纪要只在会议收敛封存后拉取。
        </p>
      </>
    ),
  },
  {
    id: "gates",
    title: "门禁 G1–G9（最常卡住的地方）",
    body: (
      <>
        <p className="help-lead">
          门禁是交付流程的关卡：每个阶段结束要交证据，有人核验通过才能往下走。
          这是全工作台最容易卡住的地方，也是最值得先读的一节。
        </p>

        <h3>五种状态</h3>
        <table className="help-table">
          <thead>
            <tr><th>状态</th><th>含义</th><th>谁能推进</th></tr>
          </thead>
          <tbody>
            <tr><td>待证据</td><td>本门还没提交任何证据</td><td>项目负责人 / 管理员</td></tr>
            <tr><td>待核验</td><td>证据已提交，等人工核验</td><td>拍板人（≠ 提交人）</td></tr>
            <tr><td>已过门</td><td>核验通过</td><td>终态，不可撤销</td></tr>
            <tr><td>有条件通过</td><td>仅 G9 可用，带条件放行</td><td>终态，不可撤销</td></tr>
            <tr><td>未过门</td><td>核验未通过，需重新提交</td><td>项目负责人 / 管理员</td></tr>
          </tbody>
        </table>
        <p className="help-lead">
          <strong>核心规则：<code>claimed ≠ accepted</code>。</strong>
          清单项在人工核验勾选「接受」之前，一律显示为黄标（claimed）。
          你提交了证据，不代表证据被认可——必须有人拍板。
        </p>

        <h3>每道门要交什么</h3>
        <table className="help-table">
          <thead>
            <tr><th>门</th><th>清单项</th></tr>
          </thead>
          <tbody>
            <tr><td>G1 立项</td><td>评分记录</td></tr>
            <tr><td>G2 需求确认</td><td>真需求卡</td></tr>
            <tr><td>G3 诊断交付</td><td>诊断报告（数字全 claimed）、SOW-A 签署、A 款预付到账、数据授权书</td></tr>
            <tr><td>G4 合同签署</td><td>SOW-B/SOW-C、结果合同页、报价单、里程碑计划、SOW-B 签署、B 预付 50%、独立 SOW-C（共 7 项）</td></tr>
            <tr><td>G5 交付启动</td><td>trust-profile / success / brief 等 .fde 全套</td></tr>
            <tr><td>G6 方案设计</td><td>问题陈述（SCQA）、基线数字、非目标清单</td></tr>
            <tr><td>G7 试点</td><td>options 文档、success.md 定稿、Eval 计划、B 试点章程定稿</td></tr>
            <tr><td>G8 上线决策</td><td>prototype-log、POC 验收表、business-case</td></tr>
            <tr><td>G9 上线门禁</td><td>生产环境、Runbook、Go-Live 单、演练记录、SOW-C 里程碑（40/40/20，末款绑 G9）</td></tr>
          </tbody>
        </table>

        <h3>提交证据</h3>
        <p>
          <strong>适用场景</strong>：本门处于「待证据」或「未过门」，你要为它补齐材料。
        </p>
        <p>
          <strong>前置条件</strong>：证据文件已写好；你有项目负责人或管理员权限。
        </p>
        <Steps
          items={[
            <>
              进「门禁」标签，点对应门，点「提交证据」。
            </>,
            <>
              逐项填两项：<strong>出处指针</strong>（文件在 fdeops 里的定位）和
              <strong>64 位 sha256 哈希</strong>。
            </>,
            <>
              指针示例：<code>fdeops://engagements/&#123;代号&#125;/.fde/gates/…</code>；
              Windows 上用 <code>certutil -hashfile 文件名 SHA256</code> 生成哈希。
            </>,
            <>
              <strong>全部清单项填完</strong>才能点提交。已过门的门不能再提交证据。
            </>,
          ]}
        />
        <p>
          <strong>预期结果</strong>：状态变为「待核验」，所有项显示为黄标（claimed），事件留痕追加一条记录。
        </p>

        <h3>人工核验拍板</h3>
        <p>
          <strong>适用场景</strong>：你是拍板人，核验别人提交的证据。
        </p>
        <p>
          <strong>前置条件</strong>：门处于「待核验」；<strong>你不是证据提交人</strong>。
        </p>
        <Steps
          items={[
            <>
              点「人工核验拍板」，逐项勾选是否接受（默认全部不勾）。
            </>,
            <>
              选结论：<strong>pass</strong>（要求全部清单项都被接受）、
              <strong>fail</strong>（打回，需重新提交）。
              <strong>conditional_pass</strong>（有条件通过）<strong>只有 G9 能选</strong>。
            </>,
            <>
              G8 过门时<strong>必须书面拍板</strong>：proceed / pivot / stop 三选一，不选会被拒绝。
            </>,
            <>
              可附 500 字以内的拍板说明，提交后事件留痕追加一条。
            </>,
          ]}
        />
        <p>
          <strong>预期结果</strong>：门变为「已过门」或「未过门」，被接受的清单项转为绿色。
        </p>
        <p className="help-warn">
          <strong>常见问题</strong>：
          <br />· 提示「该门禁尚无待核验证据」→ 对方还没提交，先等他提交。
          <br />· 提示「不能自己确认自己提交的证据」→ 找另一位有拍板权限的人。
          <br />· G8 选 pass 报「必须书面拍板」→ 补上 proceed / pivot / stop。
          <br />· 选了 conditional_pass 报「仅限 G9」→ 换个门，或改选 pass / fail。
        </p>
      </>
    ),
  },
  {
    id: "gates-evidence",
    title: "实操示例：证据文件怎么准备（somwyn 样板）",
    body: (
      <>
        <p className="help-lead">
          工作台只存「出处指针 + 哈希」，不存文件本体。文件要你自己写在 fdeops 的项目目录里。
          这一节给出可直接照做的三步流程。
        </p>

        <h3>证据放在哪</h3>
        <p>
          每个项目的门禁证据统一放在
          <code>{"D:\\test\\FDE\\engagements\\fdeops\\<项目代号>\\.fde\\gates\\"}</code>，
          用任意文本编辑器写文件即可。文件命名建议按 <code>G3-诊断报告.md</code>、
          <code>G1-评分记录.md</code> 这种「门号-名称」格式，便于对应。
        </p>
        <p className="help-note">
          <strong>现成样板</strong>：<code>somwyn</code> 项目的 <code>.fde/gates/</code> 目录里已备好全套样板文件
          （覆盖 G1 到 G9，含 README 说明），直接照抄结构改内容即可，不必从零想有哪些文件。
        </p>

        <h3>三步流程</h3>
        <Steps
          items={[
            <>
              <strong>写文件</strong>：进项目代号对应的 <code>.fde/gates/</code> 目录，按门号命名写好内容。
              签署扫描件、银行回单这类<strong>实际凭证</strong>，把 PDF 或图片放进同一目录，
              并在说明页里写清核验点。
            </>,
            <>
              <strong>算哈希</strong>：在 gates 目录运行 <code>哈希清单.ps1</code>
              （Windows 下右键「使用 PowerShell 运行」），一次列出全部文件的 sha256 与建议 URI，直接复制。
              没有这个脚本时，逐个用 <code>certutil -hashfile 文件名 SHA256</code>。
            </>,
            <>
              <strong>提交</strong>：门禁 → 对应门 → 提交证据 → 粘贴 URI 与 64 位哈希 → 全部填完 → 提交
              → 等待有权限的人人工核验拍板。
            </>,
          ]}
        />

        <h3>哪些证据不用重新写</h3>
        <table className="help-table">
          <thead>
            <tr><th>门</th><th>说明</th></tr>
          </thead>
          <tbody>
            <tr><td>G5</td><td><strong>不用新写</strong>——.fde 根目录的 trust-profile / success / brief 就是全套，URI 直接指过去</td></tr>
            <tr><td>G4 部分项</td><td>报价单可用工作台报价模块做底稿；里程碑计划可用项目计划导出</td></tr>
            <tr><td>G8</td><td>prototype-log 可用部署日志作素材</td></tr>
          </tbody>
        </table>

        <h3>两条硬规矩</h3>
        <p className="help-warn">
          <strong>1. 数字类内容先标 claimed。</strong>
          没和客户核实过的数字一律标 claimed，人工核验后才算 accepted。
          <br />
          <strong>2. 别把占位模板直接提交。</strong>
          那是假证据，核验这关过不去，还会污染事件留痕。
        </p>

        <h3>隐私铁律</h3>
        <p className="help-warn">
          真实客户资料只存 fdeops/openfde 文件层，数据库里只有代号。
          <code>.fde</code> 目录<strong>永不配置远程仓库</strong>（不进 GitHub，本地版本历史已经够用）；
          签署扫描件和回单已被 <code>.gitignore</code> 排除（<code>*.pdf</code>、<code>*.jpg</code>、
          <code>*.png</code>），只留在文件系统里。
        </p>
      </>
    ),
  },
  {
    id: "commercial",
    title: "报价收款与合同",
    body: (
      <>
        <h3>建报价</h3>
        <p>
          <strong>适用场景</strong>：客户询价，需要出一版报价。
        </p>
        <p>
          <strong>前置条件</strong>：项目已建好；已掌握预估工时与客户情况。
        </p>
        <Steps
          items={[
            <>
              第一次报价直接点「<strong>首单默认参数</strong>」（轻量档 / ¥150 每小时 / 系数 ×1.0 / 冷启动锚点），
              一键取值。
            </>,
            <>
              需要调整时展开「<strong>自定义系数</strong>」，自选档位 / 锚点 / 时薪 / 系数。
            </>,
            <>
              报价卡会显示公式价、锚点区间、建议报价，以及 claims 核验进度。
            </>,
            <>
              首单成交后<strong>回填「实际工时」</strong>校准模型；
              成交后点「<strong>回填成交价</strong>」记录实际成交金额。
            </>,
          ]}
        />
        <p>
          <strong>预期结果</strong>：报价卡保存成功，claims 核验进度可跟踪。
        </p>

        <h3>收款计划</h3>
        <p>
          <strong>适用场景</strong>：合同谈定，需要拆出分期回款节点。
        </p>
        <Steps
          items={[
            <>
              选 SOW 类型：<strong>B（50/50）</strong>、<strong>C（40/40/20）</strong>、
              <strong>A（预付）</strong>、<strong>D（月付预付）</strong>。
            </>,
            <>
              填合同基数，点「生成收款计划」。
            </>,
            <>
              每行可「设到期」日期；实际收到款后「回填」实收金额与发票号。
            </>,
          ]}
        />
        <p>
          <strong>预期结果</strong>：生成按期次分行的收款计划表。
        </p>

        <h3>合同登记</h3>
        <p>
          <strong>适用场景</strong>：合同签署后，把合同信息登记进系统备查。
        </p>
        <p>
          <strong>前置条件</strong>：合同 PDF 已归档在 fdeops。
        </p>
        <Steps
          items={[
            <>
              填签约日、验收窗口、账期、终止条款摘要，以及 <code>fdeops://</code> 指针。
            </>,
            <>
              点「登记 / 更新」。
            </>,
          ]}
        />
        <p>
          <strong>预期结果</strong>：合同卡片保存，<strong>只存指针不存文件</strong>——PDF 仍在 fdeops。
        </p>
        <p className="help-warn">
          <strong>常见问题</strong>：导出报价单报「模板未发布」→ 管理员要先在「文档模板」发布对应 DOCX。
        </p>
      </>
    ),
  },
  {
    id: "workflow",
    title: "工作流",
    body: (
      <>
        <p className="help-lead">
          工作流是把多步骤流程自动串起来的机制。控制台展示「定义」和「运行实例」两类东西。
        </p>

        <h3>定义</h3>
        <p>
          <strong>适用场景</strong>：了解某个流程由哪些节点组成。
        </p>
        <p>
          <strong>前置条件</strong>：管理员或项目负责人权限（查看者只读）。
        </p>
        <Steps
          items={[
            <>
              定义卡片显示：状态（草稿 / 已发布 / 已归档）、版本号、节点数量。
            </>,
            <>
              点开可看完整节点结构。
            </>,
          ]}
        />
        <p>
          <strong>预期结果</strong>：看懂流程的组成与当前版本。
        </p>
        <p className="help-note">
          <strong>注意</strong>：工作流定义的<strong>新建与发布暂无人工操作入口</strong>，目前只能查看和运行控制。
          需要新建流程请联系管理员通过配置方式处理。
        </p>

        <h3>运行实例（run）</h3>
        <p>
          <strong>适用场景</strong>：排查一次自动流程跑到哪一步、为什么停。
        </p>
        <Steps
          items={[
            <>
              run 列表显示状态：排队中 / 运行中 / 等待审批 / 已暂停 / 成功 / 失败 / 已取消，
              失败时附错误摘要。
            </>,
            <>
              点开单条 run，看节点树：每个节点的八态、attempt 次数、错误信息。
            </>,
            <>
              节点树里出现 <code>truncated</code> 提示，说明输出太长被截断，看完整内容请到对应产物。
            </>,
          ]}
        />
        <p>
          <strong>预期结果</strong>：定位到卡住或失败的节点。
        </p>

        <h3>控制运行</h3>
        <table className="help-table">
          <thead>
            <tr><th>操作</th><th>可用条件</th></tr>
          </thead>
          <tbody>
            <tr><td>取消</td><td>仅非终态的 run 可点。对已结束的 run 重复取消不会报错（幂等）</td></tr>
            <tr><td>恢复</td><td>仅「失败」的 run 可恢复，重投失败与已跳过的节点；其余状态会提示不可恢复</td></tr>
          </tbody>
        </table>
        <p>
          <strong>预期结果</strong>：取消后 run 转入「已取消」；恢复后失败节点重新入队。
        </p>
      </>
    ),
  },
  {
    id: "ontology",
    title: "术语表与变更集评审",
    body: (
      <>
        <p className="help-lead">
          术语表是项目的<strong>共享词典</strong>——统一项目里各说各话的术语。
          变更集评审是<strong>结构化数据变更的唯一入口</strong>。
        </p>

        <h3>术语表</h3>
        <p>
          <strong>适用场景</strong>：查某个术语的标准叫法，或查两个概念的关系。
        </p>
        <Steps
          items={[
            <>
              按<strong>规范名或别名</strong>搜索，两种叫法都能搜到同一个术语。
            </>,
            <>
              关系类型以卡片形式展示（登记 / 停用走管理通道，全局行需系统运维员操作）。
            </>,
          ]}
        />
        <p>
          <strong>预期结果</strong>：找到术语的标准定义和关联关系。
        </p>
        <p className="help-note">
          <strong>注意</strong>：术语表当前<strong>只读</strong>，不能在前端新增或编辑。
        </p>

        <h3>变更集评审</h3>
        <p>
          <strong>适用场景</strong>：AI 给出了候选结构化变更，或你手工提交了一条变更提案，需要走评审流程。
        </p>
        <p>
          <strong>前置条件</strong>：提案已提交（来自 AI 候选或人工提案）。
        </p>
        <Steps
          items={[
            <>
              变更集状态流转：<strong>草稿 → 评审中 → 已确认 / 已否决</strong>。
            </>,
            <>
              评审中可查看待确认的每条变更；<strong>确认前不会写进正式数据</strong>。
            </>,
            <>
              <strong>否决必须写理由</strong>，否则无法提交。
            </>,
          ]}
        />
        <p>
          <strong>预期结果</strong>：确认后变更才物化进正式数据；否决则丢弃但保留记录。
        </p>
        <p className="help-warn">
          <strong>常见问题</strong>：提示 403 无法确认 → <strong>拍板人不能是提交人</strong>，
          需换一位有评审权限的人处理。
        </p>
      </>
    ),
  },
  {
    id: "facts",
    title: "执行事实（只读）",
    body: (
      <>
        <p className="help-lead">
          这是一个<strong>只读</strong>面板，把项目里散落的执行痕迹汇成一条可查的事实链，
          用来回答「这事到底发生了什么」。
        </p>

        <h3>看什么</h3>
        <p>
          <strong>适用场景</strong>：客户问「这个报价单是谁在什么时候改的」「上次 AI 调用用了多少 token」。
        </p>
        <Steps
          items={[
            <>
              进项目 →「执行事实」标签。
            </>,
            <>
              查看三条来源合并后的事实链：
              <strong>项目证据</strong>（登记的证据实体）、
              <strong>操作事件</strong>（人做的写操作）、
              <strong>AI 调用审计</strong>（模型调用记录）。
            </>,
          ]}
        />
        <p>
          <strong>预期结果</strong>：得到一份按时间倒序排列的可追溯事实记录。
        </p>
        <p className="help-note">
          <strong>注意</strong>：前两类是<strong>项目维度</strong>，第三类是<strong>账号维度</strong>——
          AI 调用审计没有项目外键，是跨项目共用的同一条审计流，这里按当前账号过滤。
          这一点在响应里会明示，不是数据串了。
        </p>
        <p className="help-warn">
          <strong>常见问题</strong>：某类事实看不到 → 该类事实<strong>没有记录就是没有</strong>，
          不会推断补齐。外部操作若无真实回执，此处呈现为「无记录」，
          不会由模型自述或时间线拼装出「已完成」的语义。
        </p>
      </>
    ),
  },
  {
    id: "agent-artifacts",
    title: "智能体产物与售前参考",
    body: (
      <>
        <p className="help-lead">
          智能体每执行一次 run 都会产出文件并落库——库里只存指针 + sha256 指纹，原件留在宿主工作区。
          产出构成由该 run 的执行智能体与上下文决定：售前智能体以文档为主，同一智能体两次 run
          的组合也可能不同（试点项目的两次售前 run 分别产出 3 份与 5 份）。
        </p>

        <h3>在桌面端哪里看</h3>
        <Steps
          items={[
            <>进项目 →「智能体」标签 → run 列表点开目标 run。</>,
            <>
              run 详情里每个产物都有 <strong>[预览]</strong>（Markdown 就地渲染）与{" "}
              <strong>[下载]</strong>。
            </>,
            <>
              未复核产物会同时出现在「<strong>终审队列</strong>」，可逐件或批量标记复核
              （需项目负责人/管理员权限）。复核不是装饰：未复核产物不应作为对外依据。
            </>,
            <>
              原件规律：宿主裸跑模式下在{" "}
              <code>D:\test\agent-workspaces\platform\&lt;RUN_ID&gt;\output\</code>，
              可直接双击阅读。
            </>,
          ]}
        />

        <h3>售前五件套（2026-11-13 试点项目 run-002 实例）</h3>
        <table className="help-table">
          <thead>
            <tr><th>产物</th><th>作用</th></tr>
          </thead>
          <tbody>
            <tr><td>presales-brief.md</td><td>售前任务简报：项目代号、执行智能体、文档状态与引用情况一览</td></tr>
            <tr><td>discovery-questionnaire.md</td><td>调研问卷：首访要问的问题清单</td></tr>
            <tr><td>assumptions-and-gaps.md</td><td>假设与缺口：哪些前提未验证、信息差在哪</td></tr>
            <tr><td>solution-directions.md</td><td>方案方向：可选技术路线与取舍</td></tr>
            <tr><td>delivery-plan.md</td><td>交付计划：阶段划分与验收口径草案</td></tr>
          </tbody>
        </table>
        <p>
          参考样板已存仓库 <code>docs/售前产物参考/run-002-20261113/</code>。
          新项目做售前时拿这套结构对照：先简报 → 再问卷 → 盘假设缺口 → 出方案方向 → 落交付计划。
        </p>

        <p className="help-warn">
          <strong>常见问题</strong>：产物列表为空 → 该 run 尚无产物落库，先看 run 状态；
          [预览] 报 503 → 产物指纹与库不一致或原件被移动，先别把这份产物当依据。
        </p>
      </>
    ),
  },
  {
    id: "bridge",
    title: "集成桥",
    body: (
      <>
        <p className="help-lead">
          集成桥把两个外部系统的内容<strong>只读</strong>投影进工作台：
          openfde 知识轨（术语与知识）+ fdeops 流程轨（交付过程）。
        </p>
        <p className="help-lead">
          <strong>核心原则：真相在文件里，文件永远赢。</strong>工作台这边只存副本投影，
          外部文件改了，重新采集即可同步过来。
        </p>

        <h3>三个按钮的区别</h3>
        <table className="help-table">
          <thead>
            <tr><th>按钮</th><th>做什么</th><th>会不会触发宿主采集</th></tr>
          </thead>
          <tbody>
            <tr><td>立即采集</td><td>触发宿主计划任务马上采一轮</td><td>会</td></tr>
            <tr><td>刷新</td><td>只重读工作台内已有的投影</td><td>不会</td></tr>
            <tr><td>重新投影</td><td>用最近一次快照重新生成投影</td><td>不会</td></tr>
          </tbody>
        </table>
        <p>
          <strong>适用场景</strong>：想看到最新的外部内容 → 点「立即采集」；
          只是页面显示旧了 → 点「刷新」。
        </p>
        <p>
          <strong>前置条件</strong>：宿主侧计划任务在跑（默认每 4 小时一轮）。
        </p>
        <p>
          <strong>预期结果</strong>：「立即采集」后约 1–3 分钟新快照到站，页面自动刷新。
        </p>

        <h3>异常状态</h3>
        <table className="help-table">
          <thead>
            <tr><th>现象</th><th>含义与处理</th></tr>
          </thead>
          <tbody>
            <tr><td>Engagement 为空</td><td>不是坏了，是采集器还没跑过。点「立即采集」跑一轮即可</td></tr>
            <tr><td>⚠ 采集断连</td><td>任一轨超过 <strong>6 小时</strong>（360 分钟）没有新快照，通常是 WSL 停机或计划任务没跑</td></tr>
            <tr><td>某行显示「文件已删」</td><td>外部文件已删除，点「清投影」清掉这条记录——只清投影，不动外部文件</td></tr>
          </tbody>
        </table>
      </>
    ),
  },
  {
    id: "tasks",
    title: "任务中心",
    body: (
      <>
        <p className="help-lead">
          任务中心集中处理「需要你拍板的事」和「项目的任务进度」。
        </p>

        <h3>待审批操作</h3>
        <p>
          <strong>适用场景</strong>：AI Server 触发高风险动作，或工作流走到人工审批节点，
          需要你决定放不放行。
        </p>
        <Steps
          items={[
            <>
              在「待审批操作」里找到待处理项。
            </>,
            <>
              「<strong>审核并批准</strong>」需<strong>输入当前密码</strong>（高风险操作二次确认）。
            </>,
            <>
              「<strong>拒绝</strong>」直接拒绝，无需密码。
            </>,
          ]}
        />
        <p>
          <strong>预期结果</strong>：批准后动作才放行或工作流继续；拒绝后流程按拒绝路径走。
        </p>

        <h3>项目任务看板</h3>
        <p>
          <strong>适用场景</strong>：日常更新任务状态。
        </p>
        <Steps
          items={[
            <>
              拖动卡片到目标列：未开始 / 进行中 / 已阻塞 / 已完成 / 已取消。
            </>,
            <>
              拖到「已阻塞」时<strong>必须填原因</strong>。
            </>,
          ]}
        />
        <p>
          <strong>预期结果</strong>：项目「任务」标签页的进度与甘特图同步更新。
        </p>

        <h3>自动任务</h3>
        <p>
          <strong>适用场景</strong>：需要马上触发一个自动化任务，不用等定时。
        </p>
        <Steps
          items={[
            <>
              在自动 / 定时任务卡片点「立即执行」，任务入队后会提示 run id。
            </>,
            <>
              列表每 30 秒自动刷新一次，窗口重新聚焦时也会刷新。
            </>,
          ]}
        />
        <p>
          <strong>预期结果</strong>：拿到 run id，可在「工作流」标签页跟踪执行过程。
        </p>
        <p className="help-note">
          <strong>注意</strong>：自动任务的<strong>创建暂无人工操作入口</strong>，目前只能执行已有任务。
        </p>
      </>
    ),
  },
  {
    id: "ai",
    title: "AI Server 对话与扩展",
    body: (
      <>
        <h3>AI 对话</h3>
        <p>
          <strong>适用场景</strong>：让 AI 帮你写方案、查资料、总结文件。
        </p>
        <p>
          <strong>前置条件</strong>：管理员已在「系统配置」或「模型管理」配好 API Key，
          否则会报「AI 服务尚未配置，请联系管理员」。
        </p>
        <Steps
          items={[
            <>
              点右下角气泡打开对话面板。<code>Enter</code> 发送、<code>Shift+Enter</code> 换行。
            </>,
            <>
              在项目详情页里发起对话，会<strong>自动关联当前项目</strong>，AI 能引用项目上下文。
            </>,
            <>
              可选对话模型，并开启「深度思考」（仅 deepseek 系模型支持）。
            </>,
            <>
              回答完成后展开可看 <strong>Token 用量</strong>与<strong>费用估算</strong>。
            </>,
          ]}
        />
        <p>
          <strong>预期结果</strong>：拿到回答，必要时可核对消耗。
        </p>
        <p className="help-warn">
          <strong>常见问题</strong>：
          <br />· AI Server 运行时不可用 → 自动降级为纯模型直答（<strong>没有工具能力</strong>，
          不能查库、不能调工具），页面会提示。
          <br />· 回复里出现立创商城链接 → 点开会自动调起内置浏览器（账号有 lcsc_search 工具时）。
        </p>

        <h3>AI 与扩展</h3>
        <p>
          <strong>适用场景</strong>：管理技能（Skill）、插件、模型和第三方工具。
        </p>
        <table className="help-table">
          <thead>
            <tr><th>功能</th><th>说明</th></tr>
          </thead>
          <tbody>
            <tr><td>技能</td><td>个人技能与公共技能；卡片上的「版本」可查版本历史与效果统计（对话 / 工作流消费次数、按版本分布）</td></tr>
            <tr><td>插件</td><td>登记与审批；管理员可批准或拒绝待处理的插件变更申请</td></tr>
            <tr><td>模型管理</td><td>配置各模型服务的 API Key（服务端加密存储）</td></tr>
            <tr><td>立创工具</td><td>元器件搜索、记录对比、规格书下载</td></tr>
          </tbody>
        </table>
        <p>
          <strong>前置条件</strong>：技能治理动作（提交评审 / 发布 / 回滚 / 弃用）都需<strong>输入当前密码</strong>；
          权限范围外的账号只能查看。
        </p>
      </>
    ),
  },
  {
    id: "admin",
    title: "管理页（仅管理员）",
    body: (
      <>
        <p className="help-lead">
          这几项决定别的模块能不能正常用。<strong>文档模板未发布，会连带挡住多个导出功能。</strong>
        </p>

        <h3>行业模板</h3>
        <p>
          <strong>适用场景</strong>：新行业开工，要一套预置的项目模板。
        </p>
        <Steps
          items={[
            <>建 / 编辑 / 发布 / 停用。</>,
            <>
              只有「<strong>已发布</strong>」版本才能被「新建项目 → 从模板新建」选用。
            </>,
            <>
              草稿可以让 AI 生成内容，再人工审核后发布。
            </>,
          ]}
        />
        <p>
          <strong>预期结果</strong>：新建项目时能在模板下拉里看到它。
        </p>

        <h3>文档模板</h3>
        <p>
          <strong>适用场景</strong>：要能导出调研结果、项目计划、PoV 或 SOW。
        </p>
        <p className="help-warn">
          <strong>这是 SOW、项目计划、调研结果能否生成的前置条件。</strong>
          模板没发布，导出一定报「模板未发布」。
        </p>
        <Steps
          items={[
            <>
              四类 DOCX 模板：<strong>调研结果</strong>、<strong>项目计划及进度</strong>、
              <strong>PoV 验证方案</strong>、<strong>SOW 工作说明书</strong>。
            </>,
            <>
              上传 → 测试 → 发布。
            </>,
            <>
              模板里的动态内容位置必须保留占位标记（如 <code>【待插入：调研内容】</code>），
              否则生成内容会插不进去。
            </>,
          ]}
        />
        <p>
          <strong>预期结果</strong>：上传新版本不会覆盖历史版本，发布后才用于后续生成。
        </p>

        <h3>模块管理</h3>
        <Steps
          items={[
            <>
              模块标识<strong>创建后不可改</strong>，取名要想清楚。
            </>,
            <>
              停用后不再出现在模板的可选模块里。
            </>,
            <>
              遇到并发冲突，先「刷新模块版本」再重做。
            </>,
          ]}
        />

        <h3>用户管理</h3>
        <Steps
          items={[
            <>
              建账号：临时密码至少 6 位，用户<strong>首次登录强制改密</strong>。
            </>,
            <>
              改角色、调 AI 权限分级、停用 / 启用账号、重置密码。
            </>,
          ]}
        />

        <h3>系统配置</h3>
        <p>
          覆盖 AI 模型服务、AI Server、微信 ClawBot、存储与 ClamAV。
          修改密钥时<strong>留空表示保持不变</strong>，不需要重填原值。
        </p>
      </>
    ),
  },
  {
    id: "troubleshooting",
    title: "故障排查（照顺序查最快）",
    body: (
      <>
        <p className="help-lead">
          按下面的顺序从上往下查，多数问题在前三条就能定位。
        </p>
        <Steps
          items={[
            <>
              <strong>整个工作台打不开 / 报「无法连接服务端」</strong> →
              起后端：<code>docker compose up -d api worker scheduler</code>。
              改过 server 源码的还要先 <code>docker compose build</code>，
              再 <code>docker exec fde-workbench-api-1 alembic upgrade head</code>（迁移不会自动跑）。
            </>,
            <>
              <strong>提交后转圈又回到未提交</strong> →
              先「退出登录」重新登录（令牌 15 分钟过期）。
              仍卡就看 Network 里 <code>/gates/…/evidence</code> 的返回码：
              <strong>401</strong> = 认证问题，<strong>400</strong> = 参数问题（通常是 sha256 不足 64 位）。
            </>,
            <>
              <strong>导出一直「正在后台生成…」</strong> →
              worker 没跑，补 <code>docker compose up -d worker</code>。
            </>,
            <>
              <strong>导出报「模板未发布」</strong> →
              管理员去「文档模板」上传并发布对应 DOCX，再回来导出。
            </>,
            <>
              <strong>提示「内容已被其他人更新」</strong> →
              并发编辑保护。点提示里的「刷新」按钮再重做。
            </>,
            <>
              <strong>AI 报「尚未配置」</strong> →
              管理员补模型 API Key（系统配置 / 模型管理）。
            </>,
            <>
              <strong>集成桥空 / 采集断连</strong> →
              宿主计划任务（每 4 小时）或 WSL 服务停了。先点「立即采集」试一轮，
              仍不行检查计划任务与 <code>logs/bridge-poll.log</code>。
            </>,
            <>
              <strong>某个按钮看不到</strong> →
              看角色（见「角色与权限」一节）。查看者的大量写操作按钮不渲染。
            </>,
            <>
              <strong>AI 只能聊天、不能查数据</strong> →
              AI Server 运行时不可用，已降级为纯模型直答。找管理员查 AI Server 状态。
            </>,
          ]}
        />
      </>
    ),
  },
]

const KNOWN_GAPS: string[] = [
  "自动任务创建——暂无前端入口，只能执行已有任务。",
  "扩展市场搜索 / 同步——服务在跑，但页面无入口。",
  "工作流定义的新建与发布——暂无人工 UI 入口（控制台只读呈现 + 运行控制）。",
  "术语表与关系类型——当前只读，无前端新增 / 编辑入口。",
]

export function HelpPage() {
  // 目录用页内滚动而非 hash 锚点：hash 变更会被路由解析器接管（#help/x
  // 会被归到项目页），改用 scrollIntoView 直达章节；并用 IntersectionObserver
  // 高亮当前所在章节。
  const [activeId, setActiveId] = useState<string>(SECTIONS[0]?.id ?? "start")

  function jumpTo(sectionId: string): void {
    const el = document.getElementById(sectionId)
    // jsdom 与部分旧环境无 scrollIntoView——缺省时不跳转（目录仍可点击，滚动高亮照常降级）
    if (el && typeof el.scrollIntoView === "function") {
      el.scrollIntoView({ behavior: "smooth", block: "start" })
    }
  }

  useEffect(() => {
    // 滚动高亮是**渐进增强**：无 IntersectionObserver（jsdom 测试环境 / 旧浏览器）
    // 时直接跳过，目录点击跳仍照常工作——不可因增强功能缺失而整页崩溃。
    if (typeof IntersectionObserver === "undefined") return
    const sections = Array.from(
      document.querySelectorAll<HTMLElement>(".help-content > .help-section"),
    )
    if (!sections.length) return
    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries.filter((e) => e.isIntersecting)
        if (!visible.length) return
        visible.sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)
        setActiveId(visible[0].target.id)
      },
      { rootMargin: "-20% 0px -70% 0px", threshold: 0 },
    )
    sections.forEach((s) => observer.observe(s))
    return () => observer.disconnect()
  }, [])

  const tocItems = [
    ...SECTIONS.map((s) => ({ id: s.id, title: s.title })),
    { id: "known-gaps", title: "已知功能缺口" },
    { id: "release-notes", title: "发布与升级" },
  ]

  return (
    <section className="page page-stack help-page" aria-label="使用帮助">
      <div className="page-header">
        <h1>使用帮助</h1>
        <p className="supporting-copy">
          每个章节都按「适用场景 → 前置条件 → 操作步骤 → 预期结果 → 常见问题」组织：
          新用户只读「操作步骤」就能独立完成动作，老用户直接查「常见问题」定位卡点。
          完整文字版手册在仓库 <code>docs/工作台操作使用手册.md</code>。
          右下角智能助手内置了这本手册的服务端副本，问它「门禁怎么提交证据」这类问题，
          它会用 help_fetch 工具按章节检索手册原文再作答。
        </p>
      </div>

      <div className="help-layout">
        <nav className="help-toc" aria-label="目录">
          {tocItems.map((item, index) => (
            <button
              key={item.id}
              type="button"
              className={`help-toc-link${activeId === item.id ? " is-active" : ""}`}
              aria-current={activeId === item.id ? "true" : undefined}
              onClick={() => jumpTo(item.id)}
            >
              <span className="help-toc-index">{String(index + 1).padStart(2, "0")}</span>
              <span>{item.title}</span>
            </button>
          ))}
        </nav>

        <div className="help-content">
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
              <strong>适用场景</strong>：拿到新版本安装包，或需要升级现有环境。
            </p>
            <Steps
              items={[
                <>
                  Windows 安装包<strong>未签名</strong>，也未做发行验收——Windows 可能弹安全提示，属正常现象。
                </>,
                <>
                  客户端<strong>没有自更新</strong>。升级流程是「重新打包 + 数据库迁移」：
                  重新生成安装包，替换后执行 <code>alembic upgrade head</code>。
                </>,
                <>
                  数据库升级前<strong>同时备份 PostgreSQL 和文件存储</strong>——两者缺一不可。
                </>,
              ]}
            />
            <p>
              <strong>预期结果</strong>：新版本正常启动，历史数据完整。
            </p>
          </section>
        </div>
      </div>
    </section>
  )
}
