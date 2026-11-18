"""P3 门禁引擎活体冒烟（设计 §5.1/§5.3 口径逐条验）。

在 api 容器内跑（docker cp 进去后 docker exec python），走真实 app + 真实 PG：
  GET/POST /api/v1/projects/<id>/gates[...] 全生命周期 + 负例 + 事件留痕，
  结束后把演练项目与临时用户清干净（不留脏数据）。

用法：
  docker cp scripts/gate-engine-smoke.py fde-workbench-api-1:/tmp/
  docker exec fde-workbench-api-1 python /tmp/gate-engine-smoke.py

断言口径（对应设计 §5）：
  1) 首次 GET 懒实例化 9 门（G1..G9 顺序、pending、清单带 label）
  2) claimed≠accepted：部分接受过门被 400 拒（不是点鼠标过场）
  3) conditional_pass 仅 G9；G8 pass 必带 decision 三态
  4) failed 可重新提交（G4「可随时重启」fail_exit 有出处）
  5) 失败出口文本随 decide fail 返回（§7 验收「失败出口可触发」）
  6) 权限：非成员 viewer GET/POST 403
  7) 事件流 gates_instantiated / gate_evidence_submitted / gate_decided 落库可查
"""

from __future__ import annotations

import hashlib
import os
import sys
import uuid
from datetime import date

from sqlalchemy import select

from fde_api.app import create_app
from fde_api.auth.models import User
from fde_api.auth.passwords import hash_password
from fde_api.auth.tokens import issue_access_token
from fde_api.config import Settings
from fde_api.extensions import db

PASS: list[str] = []
FAIL: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(f"{name}{(' | ' + detail) if detail and not ok else ''}")
    print(("PASS " if ok else "FAIL ") + name + (f" | {detail}" if detail else ""))


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def main(app=None, settings=None) -> int:
    """注入 app/settings 供 pytest 在隔离测试库上自动执行。"""
    # C11：口令一律从环境变量读，脚本内无明文（CI/本地均需先导出）。
    password = os.environ.get("FDE_SMOKE_GATE_PASSWORD")
    if not password:
        print("FAIL 缺少环境变量 FDE_SMOKE_GATE_PASSWORD（冒烟口令不落脚本）")
        return 2
    app = app or create_app()
    app.config.update(TESTING=True)
    client = app.test_client()
    settings = settings or Settings()

    with app.app_context():
        session = db.session()
        # 不复用真 admin（must_change_password 会被路由 403 拦），自建临时管理员 + 临时 viewer
        admin = User(
            username=f"gate-smoke-admin.{uuid.uuid4().hex[:8]}",
            display_name="门禁冒烟admin",
            role="admin",
            password_hash=hash_password(password),
            must_change_password=False,
            is_active=True,
        )
        viewer = User(
            username=f"gate-smoke.{uuid.uuid4().hex[:8]}",
            display_name="门禁冒烟viewer",
            role="viewer",
            password_hash=hash_password(password),
            must_change_password=False,
            is_active=True,
        )
        # P0-5 门禁验收分离（goal-r1）：执行人（lead，提交证据）≠ 拍板人（admin）
        lead = User(
            username=f"gate-smoke-lead.{uuid.uuid4().hex[:8]}",
            display_name="门禁冒烟lead",
            role="project_lead",
            password_hash=hash_password(password),
            must_change_password=False,
            is_active=True,
        )
        session.add_all([admin, viewer, lead])
        session.commit()
        admin_token = issue_access_token(admin, settings)
        viewer_token = issue_access_token(viewer, settings)
        lead_token = issue_access_token(lead, settings)
        admin_id, viewer_id, lead_id = admin.id, viewer.id, lead.id

    admin_headers = {"Authorization": f"Bearer {admin_token}"}
    viewer_headers = {"Authorization": f"Bearer {viewer_token}"}
    lead_headers = {"Authorization": f"Bearer {lead_token}"}
    marker = uuid.uuid4().hex[:8]

    # ---- 建演练项目（manual，代号三段两枚·）----
    created = client.post(
        "/api/v1/projects",
        json={
            "name": f"P3门禁冒烟{marker}",
            "enterprise_code": "客户Z·门禁演练·内部",
            "planned_start_date": date.today().isoformat(),
            "leader_user_id": lead_id,
            "module_keys": ["sop_presale"],
            "creation_source": "manual",
            "project_snapshot": {"modules": [{"module_key": "sop_presale"}]},
        },
        headers=admin_headers,
    )
    check("建演练项目 201", created.status_code == 201, str(created.status_code))
    if created.status_code != 201:
        print(created.get_data(as_text=True)[:400])
        _cleanup_users(app, viewer_id, admin_id, lead_id)
        return 1
    project_id = created.get_json()["data"]["id"]
    gates_url = f"/api/v1/projects/{project_id}/gates"

    try:
        # ---- 1) 懒实例化 + 顺序 + pending ----
        first = client.get(gates_url, headers=admin_headers)
        check("GET gates 200", first.status_code == 200, str(first.status_code))
        body = first.get_json()["data"]
        gates = body["gates"]
        check("实例化 9 门", len(gates) == 9, str(len(gates)))
        check("G1..G9 顺序", [g["gate_key"] for g in gates] == [f"G{i}" for i in range(1, 10)])
        check("初始全 pending", all(g["status"] == "pending" for g in gates))
        g3 = next(g for g in gates if g["gate_key"] == "G3")
        check("G3 清单 4 项", len(g3["checklist"]) == 4, str(len(g3["checklist"])))
        check("清单项未提交(None)", all(i["claim_status"] is None for i in g3["checklist"]))
        check("模板字段带出(fail_exit/出处)", bool(g3["fail_exit"]) and bool(g3["template_source_uri"]))
        check(
            "Gate 行冻结 gates.json 哈希（64hex）",
            isinstance(g3.get("template_hash"), str) and len(g3["template_hash"]) == 64,
            str(g3.get("template_hash")),
        )
        again = client.get(gates_url, headers=admin_headers)
        check(
            "重复 GET 不重复实例化",
            len(again.get_json()["data"]["gates"]) == 9
            and sum(
                1 for e in again.get_json()["data"]["events"] if e["event_type"] == "gates_instantiated"
            ) == 1,
        )

        # 仅对本次冒烟新建的合成项目提交。以首次读和成功回执演进条件，禁止重试冲突。
        gate_revisions = {gate["gate_key"]: gate["revision"] for gate in gates}

        def post_gate(url, *, json, headers):
            gate_key = url.split("/")[-2]
            if gate_key in gate_revisions:
                json = {**json, "expected_revision": gate_revisions[gate_key]}
            response = client.post(url, json=json, headers=headers)
            if response.status_code == 200:
                gate_revisions[gate_key] = response.get_json()["data"]["revision"]
            return response

        # ---- 2) 负例：非法 key / 无证据就核验 / 非法 hash / 未知清单项 ----
        r = post_gate(
            f"{gates_url}/X1/decision", json={"result": "pass"}, headers=admin_headers
        )
        check("非法门禁键 400", r.status_code == 400, str(r.status_code))
        r = post_gate(
            f"{gates_url}/G3/decision", json={"result": "pass"}, headers=admin_headers
        )
        check("无证据核验 409", r.status_code == 409 and r.get_json()["error"]["code"] == "invalid_gate_state")
        r = post_gate(
            f"{gates_url}/G3/evidence",
            json={"items": [{"label": "SOW-A 签署", "source_uri": "fdeops://x", "content_hash": "zz"}]},
            headers=lead_headers,
        )
        check("非法 hash 400", r.status_code == 400)
        r = post_gate(
            f"{gates_url}/G3/evidence",
            json={"items": [{"label": "不存在的项", "source_uri": "fdeops://x", "content_hash": sha256("x")}]},
            headers=lead_headers,
        )
        check("未知清单项 400", r.status_code == 400 and r.get_json()["error"]["code"] == "invalid_gate_evidence")

        # ---- 3) G3 全生命周期：提交 → claimed 黄标 → 全接受过门 ----
        labels = [i["label"] for i in g3["checklist"]]
        r = post_gate(
            f"{gates_url}/G3/evidence",
            json={
                "items": [
                    {"label": label, "source_uri": f"fdeops://engagements/p3smoke/{label}", "content_hash": sha256(label)}
                    for label in labels
                ]
            },
            headers=lead_headers,
        )
        check("G3 提交 200 → evidence", r.status_code == 200 and r.get_json()["data"]["status"] == "evidence")
        check("清单全 claimed", all(i["claim_status"] == "claimed" for i in r.get_json()["data"]["checklist"]))
        # P0-5 门禁验收分离（goal-r1）：执行人（lead）拍自己的门 → 403
        r = post_gate(
            f"{gates_url}/G3/decision", json={"result": "pass"}, headers=lead_headers
        )
        check(
            "执行人拍自己的门 403（P0-5）",
            r.status_code == 403 and r.get_json()["error"]["code"] == "gate_decider_conflict",
            r.get_data(as_text=True),
        )
        r = post_gate(
            f"{gates_url}/G3/decision", json={"result": "pass"}, headers=admin_headers
        )
        check(
            "G3 过门 passed + 全 accepted",
            r.status_code == 200
            and r.get_json()["data"]["status"] == "passed"
            and all(i["claim_status"] == "accepted" for i in r.get_json()["data"]["checklist"]),
        )
        r = post_gate(
            f"{gates_url}/G3/evidence",
            json={"items": [{"label": labels[0], "source_uri": "fdeops://again", "content_hash": sha256("again")}]},
            headers=lead_headers,
        )
        check("已过门再提交 409", r.status_code == 409 and r.get_json()["error"]["code"] == "gate_already_decided")

        # ---- 4) claimed≠accepted：G7 只交部分证据强过硬过门 → 400 ----
        g7 = next(g for g in gates if g["gate_key"] == "G7")
        partial = [i["label"] for i in g7["checklist"]][:2]
        post_gate(
            f"{gates_url}/G7/evidence",
            json={"items": [{"label": l, "source_uri": f"fdeops://p3/{l}", "content_hash": sha256(l)} for l in partial]},
            headers=lead_headers,
        )
        r = post_gate(
            f"{gates_url}/G7/decision", json={"result": "pass"}, headers=admin_headers
        )
        check(
            "部分证据过门被拒 400",
            r.status_code == 400 and r.get_json()["error"]["code"] == "gate_evidence_incomplete",
            r.get_data(as_text=True),
        )

        # ---- 5) G8：pass 必带 decision；decision 只许 G8；三态可拍 ----
        g8 = next(g for g in gates if g["gate_key"] == "G8")
        post_gate(
            f"{gates_url}/G8/evidence",
            json={"items": [{"label": i["label"], "source_uri": f"fdeops://p3/{i['label']}", "content_hash": sha256(i["label"])} for i in g8["checklist"]]},
            headers=lead_headers,
        )
        r = post_gate(
            f"{gates_url}/G8/decision", json={"result": "pass"}, headers=admin_headers
        )
        check("G8 无 decision 400", r.status_code == 400 and r.get_json()["error"]["code"] == "gate_decision_required")
        r = post_gate(
            f"{gates_url}/G8/decision", json={"result": "pass", "decision": "restart"}, headers=admin_headers
        )
        check("非法 decision 400", r.status_code == 400)
        r = post_gate(
            f"{gates_url}/G8/decision", json={"result": "conditional_pass"}, headers=admin_headers
        )
        check("G8 conditional_pass 400（A1 回归钉：仅 G9）", r.status_code == 400 and r.get_json()["error"]["code"] == "gate_result_not_allowed")
        r = post_gate(
            f"{gates_url}/G8/decision", json={"result": "pass", "decision": "proceed"}, headers=admin_headers
        )
        check(
            "G8 proceed 过门",
            r.status_code == 200 and r.get_json()["data"]["status"] == "passed" and r.get_json()["data"]["decision"] == "proceed",
        )
        r = post_gate(
            f"{gates_url}/G6/evidence",
            json={"items": [{"label": "问题陈述（SCQA）", "source_uri": "fdeops://p3/g6", "content_hash": sha256("g6")}]},
            headers=lead_headers,
        )
        r = post_gate(
            f"{gates_url}/G6/decision", json={"result": "pass", "decision": "stop"}, headers=admin_headers
        )
        check("非 G8 带 decision 400", r.status_code == 400 and r.get_json()["error"]["code"] == "gate_decision_not_allowed")

        # ---- 6) G9 conditional_pass 唯一性 ----
        g9 = next(g for g in gates if g["gate_key"] == "G9")
        r = post_gate(
            f"{gates_url}/G9/decision", json={"result": "conditional_pass"}, headers=admin_headers
        )
        check("G9 无证据 conditional 409", r.status_code == 409)
        post_gate(
            f"{gates_url}/G9/evidence",
            json={"items": [{"label": i["label"], "source_uri": f"fdeops://p3/{i['label']}", "content_hash": sha256(i["label"])} for i in g9["checklist"]]},
            headers=lead_headers,
        )
        r = post_gate(
            f"{gates_url}/G6/decision", json={"result": "conditional_pass"}, headers=admin_headers
        )
        check("非 G9 conditional_pass 400", r.status_code == 400 and r.get_json()["error"]["code"] == "gate_result_not_allowed")
        r = post_gate(
            f"{gates_url}/G9/decision", json={"result": "conditional_pass"}, headers=admin_headers
        )
        check("G9 conditional_pass 过门", r.status_code == 200 and r.get_json()["data"]["status"] == "conditional_pass")
        r = post_gate(
            f"{gates_url}/G3/decision", json={"result": "pass"}, headers=admin_headers
        )
        check("已过门再核验 409", r.status_code == 409)

        # ---- 7) failed + 失败出口 + 重启 ----
        g4 = next(g for g in gates if g["gate_key"] == "G4")
        post_gate(
            f"{gates_url}/G4/evidence",
            json={"items": [{"label": i["label"], "source_uri": f"fdeops://p3/{i['label']}", "content_hash": sha256(i["label"])} for i in g4["checklist"]]},
            headers=lead_headers,
        )
        r = post_gate(
            f"{gates_url}/G4/decision", json={"result": "fail", "note": "客户暂缓"}, headers=admin_headers
        )
        data = r.get_json().get("data") or {}
        check(
            "G4 fail → failed + 失败出口带出",
            r.status_code == 200 and data.get("status") == "failed" and "重启" in (data.get("fail_exit") or ""),
            str(data.get("fail_exit")),
        )
        r = post_gate(
            f"{gates_url}/G4/evidence",
            json={"items": [{"label": g4["checklist"][0]["label"], "source_uri": "fdeops://p3/restart", "content_hash": sha256("restart")}]},
            headers=lead_headers,
        )
        check("failed 可重新提交 → evidence", r.status_code == 200 and r.get_json()["data"]["status"] == "evidence")

        # ---- 8) 权限：非成员 viewer ----
        r = client.get(gates_url, headers=viewer_headers)
        check("非成员 viewer GET 403", r.status_code == 403)
        r = post_gate(
            f"{gates_url}/G5/evidence",
            json={"items": [{"label": "x", "source_uri": "fdeops://x", "content_hash": sha256("x")}]},
            headers=viewer_headers,
        )
        check("非成员 viewer POST 403", r.status_code == 403)

        # ---- 9) 事件留痕 ----
        final = client.get(gates_url, headers=admin_headers).get_json()["data"]
        types = [e["event_type"] for e in final["events"]]
        check(
            "事件流三类齐",
            "gates_instantiated" in types and "gate_evidence_submitted" in types and "gate_decided" in types,
            str(types[:8]),
        )
        check("事件带操作者", all(e.get("actor_display_name") for e in final["events"]))
    finally:
        # ---- 清理：演练项目 + 临时 viewer，不留脏数据 ----
        # projects.id 的子表很多（research/memo/profile/batch…），不逐个手猜：
        # 按 metadata 反向拓扑序删除带 project_id 的表，再用 module/task 两轮指针补删孙表。
        with app.app_context():
            session = db.session()
            try:
                with session.begin():
                    from sqlalchemy import select as _select

                    from fde_api.auth.models import Base
                    from fde_api.auth.models import User as UserModel
                    from fde_api.workbench.models import Project, ProjectModule, ProjectTask

                    module_ids = list(
                        session.scalars(
                            _select(ProjectModule.id).where(ProjectModule.project_id == project_id)
                        )
                    )
                    task_ids = list(
                        session.scalars(
                            _select(ProjectTask.id).where(
                                ProjectTask.project_module_id.in_(module_ids)
                            )
                        )
                    )
                    for table in reversed(Base.metadata.sorted_tables):
                        columns = table.columns
                        if "task_id" in columns and task_ids:
                            session.execute(table.delete().where(columns["task_id"].in_(task_ids)))
                        elif "predecessor_task_id" in columns and task_ids:
                            session.execute(
                                table.delete().where(columns["predecessor_task_id"].in_(task_ids))
                            )
                        elif "successor_task_id" in columns and task_ids:
                            session.execute(
                                table.delete().where(columns["successor_task_id"].in_(task_ids))
                            )
                        elif "project_module_id" in columns and module_ids:
                            session.execute(
                                table.delete().where(columns["project_module_id"].in_(module_ids))
                            )
                        elif "project_id" in columns:
                            session.execute(table.delete().where(columns["project_id"] == project_id))
                    # projects 行本身没有 project_id 列，上面扫不到——显式删
                    session.execute(
                        Project.__table__.delete().where(Project.id == project_id)
                    )
                    session.execute(
                        UserModel.__table__.delete().where(
                            UserModel.id.in_([admin_id, viewer_id, lead_id])
                        )
                    )
                print("清理完成")
            except Exception as error:  # noqa: BLE001
                print(f"清理失败：{error!r}")
                FAIL.append(f"清理失败 {error!r}")

    print(f"\n===== {len(PASS)} passed, {len(FAIL)} failed =====")
    for item in FAIL:
        print("  FAILED: " + item)
    return 0 if not FAIL else 1


def _cleanup_users(app, *user_ids: str) -> None:
    """建项目失败等提前返回路径的兜底：临时用户绝不留在库里。"""
    with app.app_context():
        session = db.session()
        try:
            with session.begin():
                from fde_api.auth.models import User as UserModel

                session.execute(
                    UserModel.__table__.delete().where(UserModel.id.in_(list(user_ids)))
                )
        except Exception as error:  # noqa: BLE001
            print(f"用户清理失败：{error!r}")


if __name__ == "__main__":
    sys.exit(main())
