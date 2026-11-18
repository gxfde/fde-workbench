"""P4 报价/收款/合同 + P5 模板派生 活体冒烟（设计 §6/§7 口径逐条验）。

在 api 容器内跑（stdin 灌入），真实 app + 真实 PG：
  报价：首单默认参数 → 公式价 ¥12,600 → 锚点 A 分支 [18,000–22,500]；
        负例（冷启动 B 层上限 / 首单硬约束 / 非法系数 / C 分支必须四选一）；
        claims 单调前进；先 calibrate 才能 finalize（结项 checklist 固定一步）；
        对外草稿 HTML 三档无系数。
  收款：B 50/50 计划生成 + 重复 409 + 重建；D+7/15/30/60 现算；回填/开票；
        G8 stop 联动结算打标。
  合同：指针校验 + upsert + 四类补位视图。
  P5：标准 FDE 项目模板派生 14 节点任务 + 9 门挂点 + 13 依赖边 + 9 门懒实例化。
  权限：非成员 viewer 403；清理：项目 + 临时用户删干净（模板与种子保留）。

用法：
  docker exec -i fde-workbench-api-1 python - < scripts/commercial-smoke.py
（前置：alembic upgrade head + scripts/load_fde_template.py 已灌模板）
"""

from __future__ import annotations

import hashlib
import os
import sys
import uuid
from datetime import date, timedelta

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


def _cleanup_users(app, *user_ids: str) -> None:
    """提前返回路径也要删临时用户（不留脏账号）。"""
    with app.app_context():
        session = db.session()
        try:
            with session.begin():
                from fde_api.auth.models import User as UserModel

                for uid in user_ids:
                    if uid:
                        session.execute(
                            UserModel.__table__.delete().where(UserModel.id == uid)
                        )
        except Exception as error:  # noqa: BLE001
            print(f"用户清理失败：{error!r}")


def main(app=None, settings=None) -> int:
    """注入 app/settings 供 pytest 在隔离测试库上自动执行。"""
    # C11：口令一律从环境变量读，脚本内无明文（CI/本地均需先导出）。
    password = os.environ.get("FDE_SMOKE_COMMERCIAL_PASSWORD")
    if not password:
        print("FAIL 缺少环境变量 FDE_SMOKE_COMMERCIAL_PASSWORD（冒烟口令不落脚本）")
        return 2
    app = app or create_app()
    app.config.update(TESTING=True)
    client = app.test_client()
    settings = settings or Settings()

    with app.app_context():
        session = db.session()
        admin = User(
            username=f"p4-smoke-admin.{uuid.uuid4().hex[:8]}",
            display_name="P4冒烟admin",
            role="admin",
            password_hash=hash_password(password),
            must_change_password=False,
            is_active=True,
        )
        viewer = User(
            username=f"p4-smoke.{uuid.uuid4().hex[:8]}",
            display_name="P4冒烟viewer",
            role="viewer",
            password_hash=hash_password(password),
            must_change_password=False,
            is_active=True,
        )
        # P0-5 门禁验收分离（goal-r1）：执行人（lead，提交证据）≠ 拍板人（admin）
        lead = User(
            username=f"p4-smoke-lead.{uuid.uuid4().hex[:8]}",
            display_name="P4冒烟lead",
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

    created = client.post(
        "/api/v1/projects",
        json={
            "name": f"P4商业冒烟{uuid.uuid4().hex[:6]}",
            "enterprise_code": "客户Z·商业演练·内部",
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
        _cleanup_users(app, admin_id, viewer_id, lead_id)
        return 1
    project_id = created.get_json()["data"]["id"]
    p5_id: str | None = None
    p5b_id: str | None = None
    base = f"/api/v1/projects/{project_id}"

    try:
        # ================= P4 报价 =================
        # ---- 1) 首单默认参数：轻量 ¥12,600 / A 分支 ----
        r = client.post(
            f"{base}/quotes",
            json={"preset": "first_order_defaults"},
            headers=admin_headers,
        )
        check("首单默认参数建报价 201", r.status_code == 201, str(r.status_code))
        q1 = r.get_json()["data"]
        check(
            "公式价 12600（卡 §5.2 冷启动轻量）",
            q1["computed"]["formula_price"] == 12600.0,
            str(q1["computed"]["formula_price"]),
        )
        check("realistic 50h", q1["computed"]["realistic_hours"] == 50.0)
        check(
            "A 分支 + 区间 [18000, 22500]",
            q1["computed"]["branch"] == "A"
            and q1["computed"]["quote_low"] == 18000.0
            and q1["computed"]["quote_high"] == 22500.0,
            str((q1["computed"]["branch"], q1["computed"]["quote_low"], q1["computed"]["quote_high"])),
        )
        check(
            "锚点 18000–28000（卡 §5.1 冷启动轻量）",
            (q1["computed"]["anchor_low"], q1["computed"]["anchor_high"]) == (18000, 28000),
        )
        check(
            "field_claims 全 estimated（初始假设）",
            set(q1["field_claims"].values()) == {"estimated"},
        )

        # ---- 2) 负例 ----
        r = client.post(
            f"{base}/quotes",
            json={"preset": "first_order_defaults", "b_layer_score": 6},
            headers=admin_headers,
        )
        check(
            "冷启动 B 层 >5 拒（卡 §三 上限 1.05）",
            r.status_code == 400 and r.get_json()["error"]["code"] == "b_layer_cold_cap",
        )
        r = client.post(
            f"{base}/quotes",
            json={"preset": "first_order_defaults", "data_factor": 1.6},
            headers=admin_headers,
        )
        check(
            "首单硬约束② D 档拒",
            r.status_code == 400 and r.get_json()["error"]["code"] == "first_order_constraint",
        )
        r = client.post(
            f"{base}/quotes",
            json={"preset": "first_order_defaults", "hourly_rate": 300},
            headers=admin_headers,
        )
        check(
            "非法时薪拒（150/180/400 封闭）",
            r.status_code == 400 and r.get_json()["error"]["code"] == "invalid_hourly_rate",
        )
        r = client.post(
            f"{base}/quotes",
            json={"preset": "first_order_defaults", "buffer_factor": 1.8},
            headers=admin_headers,
        )
        check(
            "缓冲不许随手改（回校走 calibrate）",
            r.status_code == 400 and r.get_json()["error"]["code"] == "invalid_buffer",
        )
        # 严格数字解析负例（审查修复：负数/非法串/NaN 不许静默洗白成默认值）
        r = client.post(
            f"{base}/quotes",
            json={"tier": "light", "anchor_mode": "cold_start", "hourly_rate": 150, "ideal_hours": -5},
            headers=admin_headers,
        )
        check("负工时拒 400（防负成本击穿底线）", r.status_code == 400, str(r.status_code))
        r = client.post(
            f"{base}/quotes",
            json={"tier": "light", "anchor_mode": "cold_start", "hourly_rate": 150, "integration_factor": "abc"},
            headers=admin_headers,
        )
        check(
            "非法系数串拒 400（不静默落默认）",
            r.status_code == 400 and r.get_json()["error"]["code"] == "invalid_request",
        )
        r = client.post(
            f"{base}/quotes",
            json={"tier": "light", "anchor_mode": "cold_start", "hourly_rate": 150, "ideal_hours": "NaN"},
            headers=admin_headers,
        )
        check("NaN 工时拒 400（is_finite）", r.status_code == 400)
        # C 分支（卡 §5.3 示例：标准档 D×1.6 + 合规×1.35 + 档内×1.4）
        r = client.post(
            f"{base}/quotes",
            json={
                "tier": "standard",
                "anchor_mode": "cold_start",
                "hourly_rate": 150,
                "data_factor": 1.6,
                "compliance_factor": 1.35,
                "integration_factor": 1.4,
            },
            headers=admin_headers,
        )
        check(
            "C 分支缺 c_handling 拒（不许硬报）",
            r.status_code == 400 and r.get_json()["error"]["code"] == "branch_c_handling_required",
        )
        r = client.post(
            f"{base}/quotes",
            json={
                "tier": "standard",
                "anchor_mode": "cold_start",
                "hourly_rate": 150,
                "data_factor": 1.6,
                "compliance_factor": 1.35,
                "integration_factor": 1.4,
                "c_handling": "scope_cut",
            },
            headers=admin_headers,
        )
        q2 = r.get_json().get("data") or {}
        check(
            "C 分支 c_handling=缩范围 建成 + 公式价 70504（卡原文示例）",
            r.status_code == 201
            and q2.get("computed", {}).get("branch") == "C"
            and q2.get("computed", {}).get("formula_price") == 70504.0,
            str(q2.get("computed", {}).get("formula_price")),
        )

        # ---- 2b) B 分支 + B 层建议点（卡 §5.3「B 层系数在此生效」）----
        r = client.post(
            f"{base}/quotes",
            json={
                "tier": "standard",
                "anchor_mode": "cold_start",
                "hourly_rate": 180,
                "ideal_hours": 60,
                "b_layer_score": 4,
            },
            headers=admin_headers,
        )
        q3 = r.get_json().get("data") or {}
        # realistic 120h → 成本 26600 → 公式价 37240 ∈ [35000,50000] → B 分支
        check(
            "B 分支区间 [33516, 44688]",
            r.status_code == 201
            and q3.get("computed", {}).get("branch") == "B"
            and q3.get("computed", {}).get("quote_low") == 33516.0
            and q3.get("computed", {}).get("quote_high") == 44688.0,
            str((q3.get("computed", {}).get("quote_low"), q3.get("computed", {}).get("quote_high"))),
        )
        check(
            "B 层建议点 = 公式价×1.02 = 37984.8",
            q3.get("computed", {}).get("b_reference_price") == 37984.8,
            str(q3.get("computed", {}).get("b_reference_price")),
        )

        # ---- 3) claims 单调前进 ----
        r = client.post(
            f"{base}/quotes/Q-001/claims",
            json={"field": "ideal_hours", "claim_status": "claimed"},
            headers=admin_headers,
        )
        check("claim 前进 estimated→claimed", r.status_code == 200)
        r = client.post(
            f"{base}/quotes/Q-001/claims",
            json={"field": "ideal_hours", "claim_status": "estimated"},
            headers=admin_headers,
        )
        check(
            "claim 不许回退 409",
            r.status_code == 409 and r.get_json()["error"]["code"] == "claim_not_revertible",
        )
        r = client.post(
            f"{base}/quotes/Q-001/claims",
            json={"field": "nope", "claim_status": "claimed"},
            headers=admin_headers,
        )
        check("未知字段拒 400", r.status_code == 400)

        # ---- 4) 回校（结项 checklist 固定一步）----
        r = client.post(
            f"{base}/quotes/Q-001/finalize",
            json={"final_amount": 20000},
            headers=admin_headers,
        )
        check(
            "首单未回校不许 finalize 409",
            r.status_code == 409 and r.get_json()["error"]["code"] == "calibration_required",
        )
        r = client.post(
            f"{base}/quotes/Q-001/calibrate",
            json={"actual_hours": 60},
            headers=admin_headers,
        )
        check("缺 deviation_reason 拒 400", r.status_code == 400)
        r = client.post(
            f"{base}/quotes/Q-001/calibrate",
            json={"actual_hours": 60, "deviation_reason": "试点实际 60h，缓冲建议上调至 2.4"},
            headers=admin_headers,
        )
        data = r.get_json()["data"]
        check(
            "回校落 deviation_pct 0.2 + 建议 2.4",
            r.status_code == 200
            and data["calibration"]["deviation_pct"] == 0.2
            and data["calibration"]["calibrated_buffer_factor"] == 2.4,
        )
        r = client.post(
            f"{base}/quotes/Q-001/calibrate",
            json={"actual_hours": 55, "deviation_reason": "再校一次"},
            headers=admin_headers,
        )
        check("重复回校 409", r.status_code == 409)

        # ---- 4b) 首单身份服务端判定（审查修复：不依赖 preset 自报）----
        # Q-002 是不带 preset 建的高集成 C 分支报价：工作室尚无成交单，它就是事实首单，
        # 即使回校了也不许以 ×1.4 高集成成交（卡 §5.4 硬约束①）。
        r = client.post(
            f"{base}/quotes/Q-002/calibrate",
            json={"actual_hours": 100, "deviation_reason": "演练：绕过首单约束的尝试"},
            headers=admin_headers,
        )
        check("Q-002（非 preset）先回校 200", r.status_code == 200, str(r.status_code))
        r = client.post(
            f"{base}/quotes/Q-002/finalize",
            json={"final_amount": 60000},
            headers=admin_headers,
        )
        check(
            "事实首单高集成 finalize 拒 409（服务端判定）",
            r.status_code == 409 and r.get_json()["error"]["code"] == "first_order_constraint",
            str((r.status_code, r.get_json().get("error", {}).get("code"))),
        )

        # ---- 5) finalize（三条线 + 让利额度）----
        r = client.post(
            f"{base}/quotes/Q-001/finalize",
            json={"final_amount": 8000},
            headers=admin_headers,
        )
        check(
            "低于成交底线拒（成本×1.25）",
            r.status_code == 400 and r.get_json()["error"]["code"] == "below_deal_floor",
        )
        r = client.post(
            f"{base}/quotes/Q-001/finalize",
            json={
                "final_amount": 20000,
                "first_year_recoverable_value": 120000,
                "approval_cap": 25000,
            },
            headers=admin_headers,
        )
        data = r.get_json()["data"]
        check(
            "finalize 成交 20000 + 让利额度 5500",
            r.status_code == 200
            and data["status"] == "finalized"
            and data["ledger"]["allowance_cap"] == 5500.0,
            str(data.get("ledger", {}).get("allowance_cap")),
        )
        check(
            "C 层校验：回收比 16.7% 在区间 + 审批上限内",
            data.get("checks", {}).get("value_ratio_ok") is True
            and data.get("checks", {}).get("within_approval_cap") is True,
            str(data.get("checks")),
        )
        check("首单标记进 checks（服务端判定）", data.get("checks", {}).get("first_order") is True)

        # ---- 6) 对外草稿：三档无系数 ----
        r = client.get(f"{base}/quotes/Q-001/draft", headers=admin_headers)
        body = r.get_json()["data"]["html"]
        check("草稿 200 含三档", r.status_code == 200 and all(t in body for t in ("轻量", "标准", "旗舰")))
        check("草稿含公式价 12,600", "12,600" in body)
        check(
            "草稿不出现内部系数（缓冲/B 层/×1.4）",
            not any(k in body for k in ("缓冲", "B 层", "×1.4", "integration_factor")),
        )
        check("草稿标注内部草稿不外发", "内部草稿" in body and "不自动发送客户" in body)

        # ================= P4 收款 =================
        # ---- 7) B 50/50 计划 ----
        r = client.post(
            f"{base}/payments/plan",
            json={"sow_type": "b", "base_amount": 20000},
            headers=admin_headers,
        )
        check("B 计划生成 201", r.status_code == 201, str(r.status_code))
        rows = {p["milestone_key"]: p for p in r.get_json()["data"]["payments"]}
        check(
            "B 50/50：G4/G8 各 10000",
            set(rows) == {"G4", "G8"}
            and rows["G4"]["amount"] == 10000.0
            and rows["G8"]["amount"] == 10000.0
            and rows["G4"]["ratio"] == 0.5,
        )
        check(
            "里程碑溯源带 source_uri/hash",
            all(p["source_uri"].startswith("deliverables/") for p in rows.values()),
        )
        r = client.post(
            f"{base}/payments/plan",
            json={"sow_type": "b", "base_amount": 20000},
            headers=admin_headers,
        )
        check("重复生成 409", r.status_code == 409)
        r = client.post(
            f"{base}/payments/plan",
            json={"sow_type": "a", "base_amount": "NaN"},
            headers=admin_headers,
        )
        check("NaN 基数拒 400（is_finite）", r.status_code == 400)
        r = client.post(
            f"{base}/payments/plan",
            json={"sow_type": "b", "base_amount": 22000, "replace": True},
            headers=admin_headers,
        )
        rows = {p["milestone_key"]: p for p in r.get_json()["data"]["payments"]}
        check("replace 重建 22000 → 各 11000", rows["G4"]["amount"] == 11000.0)

        # ---- 8) 催款 D+15 / D+60 现算 ----
        d15 = (date.today() - timedelta(days=20)).isoformat()
        r = client.post(
            f"{base}/payments/G4", json={"due_date": d15}, headers=admin_headers
        )
        check("设到期日 200", r.status_code == 200)
        board = client.get(f"{base}/payments", headers=admin_headers).get_json()["data"]
        g4 = next(p for p in board["payments"] if p["milestone_key"] == "G4")
        check("逾期 20 天 → D+15 级", g4["dunning_level"] == "d15", str(g4["dunning_level"]))
        check("行级 overdue 标记（已过期未收）", g4.get("overdue") is True)
        check("汇总逾期 11000", board["summary"]["overdue"] == 11000.0, str(board["summary"]["overdue"]))

        d60 = (date.today() - timedelta(days=70)).isoformat()
        client.post(f"{base}/payments/G8", json={"due_date": d60}, headers=admin_headers)
        board = client.get(f"{base}/payments", headers=admin_headers).get_json()["data"]
        g8 = next(p for p in board["payments"] if p["milestone_key"] == "G8")
        check("逾期 70 天 → D+60 级", g8["dunning_level"] == "d60")

        # ---- 9) 回填 / 开票 ----
        r = client.post(
            f"{base}/payments/G4",
            json={"received_amount": 11000, "invoice_no": "INV-2026-001"},
            headers=admin_headers,
        )
        check("G4 回填已到账", r.status_code == 200 and r.get_json()["data"]["status"] == "received")
        board = client.get(f"{base}/payments", headers=admin_headers).get_json()["data"]
        g4 = next(p for p in board["payments"] if p["milestone_key"] == "G4")
        check("已收不再催款", g4["dunning_level"] is None)
        check("已收后 overdue 复位", g4.get("overdue") is False)
        check("汇总已收 11000", board["summary"]["received"] == 11000.0)

        # ---- 9b) 台账保护：已回填的行不许 replace 重建（审查修复）----
        r = client.post(
            f"{base}/payments/plan",
            json={"sow_type": "b", "base_amount": 30000, "replace": True},
            headers=admin_headers,
        )
        check(
            "已有收款事实 replace 拒 409（金额真相在台账）",
            r.status_code == 409 and r.get_json()["error"]["code"] == "ledger_truth_present",
            str((r.status_code, r.get_json().get("error", {}).get("code"))),
        )

        # ---- 10) G8 stop 联动结算 ----
        gates_url = f"{base}/gates"
        gates = client.get(gates_url, headers=admin_headers).get_json()["data"]["gates"]
        check("P4 项目懒实例化 9 门", len(gates) == 9)

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

        # ---- 10a) accepted_labels 越集追认拒（审查修复 P0）----
        # 只提交 1 项证据就把全部清单项塞进 accepted_labels → 必须拒；
        # 只核验已提交项 → pass 因其余未 accepted 也要拒。
        g3gate = next(g for g in gates if g["gate_key"] == "G3")
        first_label = g3gate["checklist"][0]["label"]
        all_labels = [i["label"] for i in g3gate["checklist"]]
        r = post_gate(
            f"{gates_url}/G3/evidence",
            json={
                "items": [
                    {
                        "label": first_label,
                        "source_uri": f"fdeops://p4/{first_label}",
                        "content_hash": sha256(first_label),
                    }
                ]
            },
            headers=lead_headers,
        )
        check("G3 部分提交（1 项）进 evidence", r.status_code == 200, str(r.status_code))
        r = post_gate(
            f"{gates_url}/G3/decision",
            json={"result": "pass", "accepted_labels": all_labels},
            headers=admin_headers,
        )
        check(
            "未提交项塞 accepted_labels 拒 400",
            r.status_code == 400
            and r.get_json()["error"]["code"] == "accepted_labels_not_claimed",
            str((r.status_code, r.get_json().get("error", {}).get("code"))),
        )
        r = post_gate(
            f"{gates_url}/G3/decision",
            json={"result": "pass", "accepted_labels": [first_label]},
            headers=admin_headers,
        )
        check(
            "部分核验 pass 拒 400（还有项未 accepted）",
            r.status_code == 400
            and r.get_json()["error"]["code"] == "gate_evidence_incomplete",
            str((r.status_code, r.get_json().get("error", {}).get("code"))),
        )
        r = post_gate(
            f"{gates_url}/G3/evidence",
            json={
                "items": [
                    {
                        "label": i["label"],
                        "source_uri": f"fdeops://p4/{i['label']}",
                        "content_hash": sha256(i["label"]),
                    }
                    for i in g3gate["checklist"]
                    if i["label"] != first_label
                ]
            },
            headers=lead_headers,
        )
        check("G3 补齐其余证据", r.status_code == 200, str(r.status_code))
        r = post_gate(
            f"{gates_url}/G3/decision",
            json={"result": "pass"},
            headers=admin_headers,
        )
        check("G3 全量提交后默认全核验过门", r.status_code == 200 and r.get_json()["data"]["status"] == "passed")

        g8gate = next(g for g in gates if g["gate_key"] == "G8")
        r = post_gate(
            f"{gates_url}/G8/evidence",
            json={
                "items": [
                    {
                        "label": i["label"],
                        "source_uri": f"fdeops://p4/{i['label']}",
                        "content_hash": sha256(i["label"]),
                    }
                    for i in g8gate["checklist"]
                ]
            },
            headers=lead_headers,
        )
        r = post_gate(
            f"{gates_url}/G8/decision",
            json={"result": "pass", "decision": "stop"},
            headers=admin_headers,
        )
        data = r.get_json()["data"]
        check(
            "G8 stop 过门 + 结算联动响应",
            r.status_code == 200
            and data["decision"] == "stop"
            and data.get("g8_stop_settlement", {}).get("flagged") is True,
        )
        board = client.get(f"{base}/payments", headers=admin_headers).get_json()["data"]
        g8 = next(p for p in board["payments"] if p["milestone_key"] == "G8")
        check(
            "G8 尾款行打 stop 结算标",
            g8["settlement_reason"] == "g8_stop" and "按合同结算" in g8["note"],
            str((g8["settlement_reason"], g8["note"])),
        )

        # ================= P4 合同 =================
        r = client.post(
            f"{base}/contracts",
            json={"sow_type": "b", "source_uri": "http://example.com/x.pdf"},
            headers=admin_headers,
        )
        check("非指针 source_uri 拒（A4）", r.status_code == 400 and r.get_json()["error"]["code"] == "invalid_source_uri")
        r = client.post(
            f"{base}/contracts",
            json={
                "sow_type": "b",
                "signed_at": date.today().isoformat(),
                "payment_terms": "B 50/50：SOW-B 签署 50%，毕业拍板 50%",
                "termination_terms": "任一方提前 15 天书面通知；stop 按已完成工作结算",
                "source_uri": "fdeops://engagements/客户Z/SOW-B.pdf",
                "content_hash": sha256("SOW-B"),
            },
            headers=admin_headers,
        )
        check("合同登记 200", r.status_code == 200)
        r = client.post(
            f"{base}/contracts",
            json={"sow_type": "b", "acceptance_window_days": 15},
            headers=admin_headers,
        )
        check("同 SOW upsert 200", r.status_code == 200)
        contracts = client.get(f"{base}/contracts", headers=admin_headers).get_json()["data"]["contracts"]
        check("四类补位视图（1 录 3 空）", len(contracts) == 4 and sum(1 for c in contracts if c.get("recorded")) == 1)

        # ================= 权限 =================
        r = client.get(f"{base}/quotes", headers=viewer_headers)
        check("非成员 viewer GET quotes 403", r.status_code == 403)
        r = client.post(
            f"{base}/payments/plan",
            json={"sow_type": "a", "base_amount": 8000},
            headers=viewer_headers,
        )
        check("非成员 viewer POST plan 403", r.status_code == 403)

        # ================= P5 模板派生 =================
        with app.app_context():
            from fde_api.workbench.models import IndustryTemplate, IndustryTemplateVersion

            s = db.session()
            template = s.scalars(
                select(IndustryTemplate).where(IndustryTemplate.name == "标准 FDE 项目")
            ).first()
            if template is None:
                check("模板「标准 FDE 项目」已灌", False, "先跑 scripts/load_fde_template.py")
                raise SystemExit(1)
            version = s.scalars(
                select(IndustryTemplateVersion).where(
                    IndustryTemplateVersion.template_id == template.id,
                    IndustryTemplateVersion.status == "published",
                )
            ).first()
            template_version_id = version.id if version is not None else None
            s.close()
        check("模板已发布", version is not None)
        if version is None:
            raise SystemExit(1)

        r = client.post(
            "/api/v1/projects",
            json={
                "name": f"P5模板派生冒烟{uuid.uuid4().hex[:6]}",
                "enterprise_code": "客户Z·模板演练·内部",
                "planned_start_date": date.today().isoformat(),
                "leader_user_id": admin_id,
                "creation_source": "template",
                "template_version_id": template_version_id,
                "module_keys": ["sop_presale", "sop_delivery", "sop_post_delivery"],
            },
            headers=admin_headers,
        )
        check("模板派生建项目 201", r.status_code == 201, str(r.status_code))
        if r.status_code != 201:
            print(r.get_data(as_text=True)[:400])
            raise SystemExit(1)
        p5_id = r.get_json()["data"]["id"]
        tasks = client.get(
            f"/api/v1/projects/{p5_id}/tasks", headers=admin_headers
        ).get_json()["data"]["items"]
        check("派生 14 节点任务", len(tasks) == 14, str(len(tasks)))
        gated = [t for t in tasks if t["gate"]]
        check(
            "9 门挂点（S1..S8/S10 带 gate）",
            len(gated) == 9
            and {t["gate"] for t in gated} == {f"G{i}" for i in range(1, 10)},
            str(sorted(t["gate"] for t in gated)),
        )
        check(
            "任务挂 sop_node（s1→S1…）",
            all(t["sop_node"] for t in tasks)
            and next(t for t in tasks if t["task_key"] == "s0_b")["sop_node"] == "S0-B",
        )
        edge_count = sum(len(t["dependency_keys"]) for t in tasks)
        check("依赖边 13（主链 10 + S9→S8 + S8→S10 + S12→S13）", edge_count == 13, str(edge_count))
        s8 = next(t for t in tasks if t["task_key"] == "s8")
        check(
            "S8 双前置（s7 + s9 并入 G8 前执行）",
            sorted(s8["dependency_keys"]) == ["s7", "s9"],
            str(s8["dependency_keys"]),
        )
        gates = client.get(
            f"/api/v1/projects/{p5_id}/gates", headers=admin_headers
        ).get_json()["data"]["gates"]
        check("派生项目 9 门懒实例化", len(gates) == 9)

        # ---- P5b) 后补模块同样补挂点（审查修复：append_project_module 注记缺口）----
        r = client.post(
            "/api/v1/projects",
            json={
                "name": f"P5追加模块冒烟{uuid.uuid4().hex[:6]}",
                "enterprise_code": "客户Z·追加演练·内部",
                "planned_start_date": date.today().isoformat(),
                "leader_user_id": admin_id,
                "creation_source": "template",
                "template_version_id": template_version_id,
                "module_keys": ["sop_presale"],
            },
            headers=admin_headers,
        )
        check("P5b 子集模块建项目 201", r.status_code == 201, str(r.status_code))
        if r.status_code == 201:
            p5b_id = r.get_json()["data"]["id"]
            p5b_version = client.get(
                f"/api/v1/projects/{p5b_id}", headers=admin_headers
            ).get_json()["data"]["version"]
            r = client.post(
                f"/api/v1/projects/{p5b_id}/modules",
                json={
                    "module_key": "sop_delivery",
                    "planned_start_date": date.today().isoformat(),
                    "version": p5b_version,
                },
                headers=admin_headers,
            )
            check("追加 sop_delivery 模块 201", r.status_code == 201, str(r.status_code))
            tasks_b = client.get(
                f"/api/v1/projects/{p5b_id}/tasks", headers=admin_headers
            ).get_json()["data"]["items"]
            appended = [t for t in tasks_b if t["task_key"] in ("s3", "s6", "s8")]
            check(
                "追加模块任务同样挂 sop_node/gate（与立项同规）",
                len(appended) == 3
                and all(t["sop_node"] for t in appended)
                and next(t for t in tasks_b if t["task_key"] == "s3")["gate"] == "G3",
                str([(t["task_key"], t["sop_node"], t["gate"]) for t in appended]),
            )

    finally:
        # ---- 清理：两个演练项目 + 临时用户；模板与种子保留 ----
        with app.app_context():
            session = db.session()
            try:
                with session.begin():
                    from sqlalchemy import select as _select

                    from fde_api.auth.models import Base
                    from fde_api.auth.models import User as UserModel
                    from fde_api.workbench.models import (
                        Project,
                        ProjectModule,
                        ProjectTask,
                    )

                    for pid in (project_id, p5_id, p5b_id):
                        if not pid:
                            continue
                        module_ids = list(
                            session.scalars(
                                _select(ProjectModule.id).where(
                                    ProjectModule.project_id == pid
                                )
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
                                session.execute(
                                    table.delete().where(columns["task_id"].in_(task_ids))
                                )
                            elif "predecessor_task_id" in columns and task_ids:
                                session.execute(
                                    table.delete().where(
                                        columns["predecessor_task_id"].in_(task_ids)
                                    )
                                )
                            elif "successor_task_id" in columns and task_ids:
                                session.execute(
                                    table.delete().where(
                                        columns["successor_task_id"].in_(task_ids)
                                    )
                                )
                            elif "project_module_id" in columns and module_ids:
                                session.execute(
                                    table.delete().where(
                                        columns["project_module_id"].in_(module_ids)
                                    )
                                )
                            elif "project_id" in columns:
                                session.execute(
                                    table.delete().where(columns["project_id"] == pid)
                                )
                        session.execute(
                            Project.__table__.delete().where(Project.id == pid)
                        )
                    for uid in (admin_id, viewer_id, lead_id):
                        session.execute(
                            UserModel.__table__.delete().where(UserModel.id == uid)
                        )
                print("清理完成")
            except Exception as error:  # noqa: BLE001
                print(f"清理失败：{error!r}")
                FAIL.append(f"清理失败 {error!r}")

    print(f"\n===== {len(PASS)} passed, {len(FAIL)} failed =====")
    for item in FAIL:
        print("  FAILED: " + item)
    return 0 if not FAIL else 1


if __name__ == "__main__":
    sys.exit(main())
