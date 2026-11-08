"""仿真沙箱项目与场景投影（G9 接线轮 · IT-01）。

**问题**：V3.1 的 ``AgentRun.project_id`` / ``WorkflowRun.project_id`` / 
``ProjectGuidanceAnalysis.project_id`` / ``ProjectSolution.project_id`` 都是
**真实项目的必填外键**。模拟运行没有真实项目 ⇒ 真实执行面此前**无法接线**
（G1 §8.4 决策 B「结果外置」的代价）。

**解法（沙箱项目）**：训练场拥有**一个专属的合成项目**（``SIM-V32-LAB``），
作为真实执行面的**宿主**。它不是客户项目——没有客户资料、没有交付包、没有
证据链；它的 ``enterprise_code`` 以 ``SIM·`` 开头，代号纪律照旧（三段两枚「·」）。

**场景投影**：把案例的**已披露事实**投影成沙箱项目的
``ProjectGuidanceAnalysis``（status=confirmed 的「已确认业务问题」）＋ 一份
**中性的任务骨架**方案。真实 Agent 拿到的上下文因此与生产形态同构。

**两条不可越界的纪律**：
1. **投影只含已披露内容**——隐藏事实未披露前**不进** Agent 上下文（否则等于
   把答案喂给被测方，破坏整个训练场的意义）。
2. **骨架是任务说明，不是答案**——期望结果/验收标准/Rubric **绝不**进沙箱。
"""
from __future__ import annotations

import hashlib
from typing import Any

from sqlalchemy import select

from fde_api.auth.models import User
from fde_api.guidance.models import ProjectGuidanceAnalysis
from fde_api.solutions.models import ProjectSolution
from fde_api.workbench.models import Project

SANDBOX_PROJECT_CODE = "SIM-V32-LAB"
SANDBOX_PROJECT_NAME = "FDE 交付模拟训练场（仿真沙箱）"
# 代号纪律：三段两枚「·」（与 projects 服务层同尺）；「SIM」段标明非真实客户。
SANDBOX_ENTERPRISE_CODE = "SIM·训练场·平台"

# 沙箱里允许存在的项目数量（恒为 1；出现第二个即数据异常）
SANDBOX_PROJECT_LIMIT = 1
# 沙箱里的方案骨架行名（复用同一行，避免产物挂 solution 外键后被删）
SOLUTION_NAME = "模拟交付骨架（仿真沙箱）"


class SandboxError(Exception):
    """沙箱错误。"""

    def __init__(self, code: str, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def ensure_sandbox_project(*, actor: User, session: Any | None = None) -> Project:
    """幂等取/建仿真沙箱项目。

    只允许 **admin** 建（平台资产，不是任何人的项目）；已存在则直接返回。
    """
    if actor.role != "admin":
        raise SandboxError(
            "forbidden", "仿真沙箱项目仅平台管理员可创建。", 403
        )
    if session is not None:
        return _ensure_with_session(session, actor)
    from fde_api.extensions import db

    with db.session() as own_session:
        project = _ensure_with_session(own_session, actor)
        own_session.commit()
        return project


def _ensure_with_session(session: Any, actor: User) -> Project:
    existing = session.scalar(
        select(Project).where(Project.project_code == SANDBOX_PROJECT_CODE)
    )
    if existing is not None:
        return existing
    count = session.scalar(
        select(Project).where(Project.enterprise_code == SANDBOX_ENTERPRISE_CODE)
    )
    if count is not None:
        raise SandboxError(
            "sandbox_project_conflict",
            "沙箱代号已被占用——训练场只允许一个沙箱项目。",
            409,
        )
    from datetime import date

    project = Project(
        project_code=SANDBOX_PROJECT_CODE,
        name=SANDBOX_PROJECT_NAME,
        enterprise_code=SANDBOX_ENTERPRISE_CODE,
        status="active",
        business_line="FDE",
        background="V3.2 交付模拟训练场的仿真宿主项目：无客户资料、无交付包、无证据链。",
        notes="由模拟训练场自动创建；请勿手工在此项目下录入真实业务数据。",
        leader_user_id=actor.id,
        # projects 的既有 NOT NULL 契约：planned_start_date 用当日；
        # planned_end_date 留空（仿真运行无真实工期）；template_snapshot 记
        # 「空模板快照」标记（沙箱无行业模板，也不应挂真实模板版本）。
        planned_start_date=date.today(),
        template_snapshot={"simulation_only": True, "template": "none"},
    )
    session.add(project)
    session.flush()
    return project


def _task_framing(*, scenario_key: str, variant: str, split: str) -> str:
    """中性的任务骨架（**不含**期望结果/验收标准/Rubric）。"""
    return (
        "# 模拟交付任务（合成训练环境）\n\n"
        f"- 案例代号: {scenario_key}\n"
        f"- 客户行为变体: {variant}\n"
        f"- 数据集: {split}\n\n"
        "## 你的任务\n\n"
        "你是 FDE 交付顾问。基于下方「已确认业务问题」完成一次交付准备：\n"
        "1. 澄清并结构化需求（每条需求要能对应到一条已确认问题）；\n"
        "2. 给出方案骨架（数据接入/流程/权限等维度按需展开）；\n"
        "3. 拆解任务与依赖；\n"
        "4. 给出**可度量**的验收标准。\n\n"
        "## 纪律\n\n"
        "- 你的产出将接受**独立**的确定性规则与模型评估；请把依据写进产出正文。\n"
        "- 未在「已确认业务问题」中出现的事实，**不要**当成已知事实使用。\n"
        "- 本环境为合成训练环境，数据均为构造样例，不对应任何真实企业。\n"
    )


def project_scenario(
    *,
    session: Any,
    project: Project,
    scenario_key: str,
    variant: str,
    split: str,
    brief: list[str],
    disclosed: list[dict[str, Any]],
    actor: User,
) -> dict[str, Any]:
    """把案例投影进沙箱项目（guidance analysis + 方案骨架）。

    返回投影摘要（版本号、指纹），供 Trace 留证。
    """
    prepare_projection(session=session, project=project)

    items: list[dict[str, Any]] = [
        {
            "text": str(text),
            "classification": "customer_stated",
            "source_refs": [f"simulation:{scenario_key}#brief-{index}"],
            "confirmed": True,
            "severity": "medium",
        }
        for index, text in enumerate(brief, start=1)
    ]
    for fact in disclosed:
        fact_id = str(fact.get("fact_id") or "")
        items.append(
            {
                "text": str(fact.get("text") or ""),
                "classification": "customer_stated",
                "source_refs": [f"simulation:{scenario_key}#{fact_id}"],
                "confirmed": True,
                "severity": str(fact.get("category") or "medium"),
            }
        )

    version_number = 1 + int(
        session.scalar(
            select(ProjectGuidanceAnalysis.version_number)
            .where(ProjectGuidanceAnalysis.project_id == project.id)
            .order_by(ProjectGuidanceAnalysis.version_number.desc())
            .limit(1)
        )
        or 0
    )
    framing = _task_framing(
        scenario_key=scenario_key, variant=variant, split=split
    )
    fingerprint = hashlib.sha256(framing.encode("utf-8")).hexdigest()

    analysis = ProjectGuidanceAnalysis(
        project_id=project.id,
        version_number=version_number,
        source_kind="presurvey_docx",
        source_filename=f"simulation-{scenario_key}.md",
        source_sha256=fingerprint,
        status="confirmed",
        analysis_state="ready",
        customer_vision="仿真训练环境的合成客户背景（非真实客户）。",
        key_business_problems_json=items,
        evidence_json={
            "simulation_only": True,
            "scenario_key": scenario_key,
            "variant": variant,
            "split": split,
            "disclosed_fact_ids": [
                str(fact.get("fact_id") or "") for fact in disclosed
            ],
        },
        created_by_user_id=actor.id,
        reviewed_by_user_id=actor.id,
    )
    session.add(analysis)

    solution = session.scalar(
        select(ProjectSolution).where(
            ProjectSolution.project_id == project.id,
            ProjectSolution.name == SOLUTION_NAME,
        )
    )
    if solution is None:
        solution = ProjectSolution(
            project_id=project.id,
            name=SOLUTION_NAME,
            design_markdown=framing,
            owner_user_id=actor.id,
            deliverables="由被测智能体产出的交付物（写入真实执行面的工作区）。",
            acceptance_criteria="由被测智能体产出；评估侧另行判定。",
            data_systems="合成训练数据（sim.* 虚拟工具）。",
            schedule="仿真运行即时。",
        )
        session.add(solution)
    else:
        # 就地更新骨架（**不删**：产物行可能挂 solution 外键）
        solution.design_markdown = framing
    session.flush()
    return {
        "project_id": project.id,
        "analysis_id": analysis.id,
        "analysis_version": version_number,
        "solution_id": solution.id,
        "context_sha256": fingerprint,
        "projected_items": len(items),
    }


def prepare_projection(*, session: Any, project: Project) -> None:
    """准备下一次投影：旧分析置 ``superseded``、方案骨架就地更新。

    **不删行**：分析行被智能体产物的链路引用（产物行可能挂 solution 外键），
    删除会撞 FK；且「版本化 + 取代」本来就是本仓的既有语义（superseded 状态
    已在 CHECK 里）。上下文渲染取**最新 confirmed**——旧分析被取代即不再生效，
    上一次的已披露事实因此**不会泄漏**给下一次运行。
    """
    previous = list(
        session.scalars(
            select(ProjectGuidanceAnalysis).where(
                ProjectGuidanceAnalysis.project_id == project.id,
                ProjectGuidanceAnalysis.status == "confirmed",
            )
        )
    )
    for analysis in previous:
        analysis.status = "superseded"
    session.flush()
