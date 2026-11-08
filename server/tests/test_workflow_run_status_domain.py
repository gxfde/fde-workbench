"""workflow_runs.status 值域纪律（架构评估 P2-6）。

`paused` 是 `workflow_runs.status` CHECK 值域里的**预留值**：全仓无任何写入方
（run 永远不会进入 paused）。本模块把它从「忘了的死值」钉成「登记在册的预留值」——

- 形状钉①：`workflow_runs` 表的 CHECK 约束文本仍含 `paused`（防误删值域）；
- 形状钉②：`workflows/models.py::RUN_STATUSES` 仍含 `paused`（常量与 CHECK 同源）；
- 写入方钉③：`src/fde_api/workflows/**` 内 `"paused"` 字面量**只允许**出现在
  `models.py`（值域声明处）；任何新写入方出现即红——要么改值域，要么先改本钉。

**边界**：其他域的 `paused` 是**活值域**（projects / meetings / task_board 的
automation / weixin channel / research opportunity / documents / workbench），
它们各有真实写入方，不在本钉范围内——本钉只管 workflow run 自己的值域。

拍板记录：2026-11-08 蔡工拍板「保留 CHECK + 加机械钉」，不收窄值域、不迁移。
收窄 CHECK 会改 schema（CHECK 置换零列重建，T-J2 同款手法），收益（消灭一个
死值）小于代价（动已上线表 + 未来启用 paused 需再迁一次）。
"""
import re

from conftest import SERVER_ROOT

WORKFLOWS_PACKAGE = SERVER_ROOT / "src" / "fde_api" / "workflows"

# workflows 包内允许出现 "paused" 字面量的文件——值域声明处（models.py）。
# 其余文件出现即视为「出现了 workflow run 的 paused 写入方」。
ALLOWED_PAUSED_FILES = {"models.py"}

PAUSED_LITERAL = re.compile(r"""["']paused["']""")


def test_workflow_run_status_check_keeps_paused():
    """形状钉①：workflow_runs 的 CHECK 值域仍含 paused（值域是登记在册的预留域）。"""
    from fde_api.workflows.models import WorkflowRun

    checks = [
        constraint
        for constraint in WorkflowRun.__table__.constraints
        if constraint.name == "ck_workflow_runs_status"
    ]
    assert len(checks) == 1, "ck_workflow_runs_status 约束缺失或重复"
    check_text = str(checks[0].sqltext)
    assert "paused" in check_text, (
        f"ck_workflow_runs_status 值域里没有 paused：{check_text}"
        "——值域若确实要收窄，先走拍板 + 迁移（CHECK 置换零列重建），"
        "不要直接改模型常量（会和线上表漂移）"
    )


def test_run_statuses_constant_keeps_paused():
    """形状钉②：RUN_STATUSES 常量与 CHECK 同源，仍含 paused。"""
    from fde_api.workflows.models import RUN_STATUSES

    assert "paused" in RUN_STATUSES, f"RUN_STATUSES 缺 paused：{RUN_STATUSES}"
    assert len(RUN_STATUSES) == len(set(RUN_STATUSES)), "RUN_STATUSES 有重复项"


def test_workflows_package_has_no_paused_writer():
    """写入方钉③：workflows 包内 "paused" 字面量只允许出现在 models.py。

    一旦某个执行器/结算/恢复分支开始把 run 写成 paused，本钉即红——那时
    `paused` 才真正成为活值域，本钉与形状钉①②都应改成「活值域」口径，
    并同步补上暂停/恢复语义（而不是悄悄留着一条写不出来的状态）。
    """
    offenders: dict[str, list[int]] = {}
    for path in sorted(WORKFLOWS_PACKAGE.rglob("*.py")):
        hits = [
            index
            for index, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
            if PAUSED_LITERAL.search(line)
        ]
        if hits:
            offenders[path.name] = hits
    assert set(offenders) <= ALLOWED_PAUSED_FILES, (
        "workflows 包内出现了 paused 写入方："
        f"{offenders}——除值域声明处（models.py）外不得写 paused。"
        "若这是真实需求，先拍板并补暂停/恢复语义，再改本钉"
    )
    assert "models.py" in offenders, (
        "models.py 里找不到 paused 字面量——值域声明被误删，"
        "形状钉①②会同步红"
    )
