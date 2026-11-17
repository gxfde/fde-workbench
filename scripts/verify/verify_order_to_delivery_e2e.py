r"""接单→交付 端到端贯通验证器（活体；写库；可重复执行）。

**验证什么**：派单线「接单→交付」全链在真实活体上是否通畅——立项（FDE_DISPATCH
渠道闸）→ 机会主体 → 方案 → 报价（首单回校闸）→ 成交回填 → claims×11 →
对外签字闸 → 交付包发布 → 指派 → 接单人真实接单（乐观锁）→ 自动交接
（项目成员）→ 权限边界负例 → 交付执行（任务/证据）→ 交付件（文档 manual
修订 + 确认）→ 封包 → 封存 → 交付登记（admin 终态）。

**跑法**（活体主栈侧）：

    python scripts/verify/verify_order_to_delivery_e2e.py \
        --username admin --password "<平台侧密码>" \
        --deliverer <接单人账号> --deliverer-token "<接单人 access_token>"

- `--deliverer`：接单人账号（须 active 且系统角色 ≥ fde_engineer）。接单、任务
  推进等"接单人视角"步骤用**该账号自己的凭证**执行，验证真实接单路径而非
  admin 代接。凭证二选一：`--deliverer-token`（access_token，15 分钟有效）或
  `--deliverer-password`；都不给则降级 admin 代接（S15/S18/S20/S21 标 SKIP，
  核心链照走）。
- **前置**：`flask seed-document-templates` 已跑过（文档模板 17 类 published；
  未灌则 S24 建文档 422 `document_template_not_published`——这是部署态自检点，
  脚本会在该步给出修复指引）。
- `--password` 不传则从标准输入读一行（同 scripts/agents/start-run.py 先例）。

**边界（脚本不越权）**：

1. 全程**合成代号**数据（企业代号 `E2E贯通·制造·佛山`，每跑一次新建独立项目，
   互不干扰、可重复执行）；不碰真相层、不发邮件、不调外部服务；
2. claims/confirm/deliver 等"闸动作"是对合成数据的**机制验证**，不代表任何
   真实业务拍板；
3. **首次执行会消耗一次全库「工作室首单」语义判定名额**（首单=全库非仿真
   finalized 计数==0；首跑之后 finalize 走非首单分支，本脚本两分支都兼容）；
4. 不含 agent run（发起权归人）；artifact 型封包链不在本脚本范围。
"""
from __future__ import annotations

import argparse
import base64
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_BASE_URL = "http://127.0.0.1:8010"
CLAIM_FIELDS = (
    "ideal_hours", "integration_factor", "data_factor", "compliance_factor",
    "buffer_factor", "hourly_rate", "cash_cost", "b_layer_score",
    "formula_price", "final_amount", "actual_hours",
)
FINAL_AMOUNT = 18000  # ≥ 首单预设成本 9000 × 1.25 底线 11250


# ── HTTP ───────────────────────────────────────────────────────────────────

def call(method, path, token=None, body=None, base_url=DEFAULT_BASE_URL):
    data = None
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(base_url + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as err:
        try:
            payload = json.loads(err.read().decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            payload = None
        return err.code, payload


def data_of(resp):
    status, payload = resp
    return status, (payload or {}).get("data")


def login(base_url, username, password, device_label="verify-e2e-order-delivery"):
    status, payload = call("POST", "/api/v1/auth/login", body={
        "username": username, "password": password, "device_label": device_label,
    }, base_url=base_url)
    if status != 200:
        code = ((payload or {}).get("error") or {}).get("code")
        raise SystemExit(f"登录失败 http={status} code={code}（连续失败 5 次锁约 15 分钟）")
    token = ((payload or {}).get("data") or {}).get("access_token")
    if not token:
        raise SystemExit("登录响应里没有 access_token。")
    return token


def whoami(base_url, token):
    status, data = data_of(call("GET", "/api/v1/auth/me", token, base_url=base_url))
    return (data or {}).get("id") if status == 200 else None


# ── 主链 ───────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--username", help="平台侧账号（admin/project_lead）")
    parser.add_argument("--admin-token",
                        help="平台侧 access_token（与 --username 二选一；15 分钟有效）")
    parser.add_argument("--password", help="账号密码。不传则从标准输入读一行")
    parser.add_argument("--deliverer", default="diag-ai-service",
                        help="接单人账号（role ≥ fde_engineer 且 active）")
    deliverer_cred = parser.add_mutually_exclusive_group()
    deliverer_cred.add_argument("--deliverer-token", help="接单人 access_token（推荐；15 分钟有效）")
    deliverer_cred.add_argument("--deliverer-password", help="接单人密码（与平台侧不同时用）")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--docx",
                        default=str(REPO_ROOT / "resources" / "document-templates" / "acceptance.docx"),
                        help="manual 修订用的 DOCX（默认 acceptance 上线验收单模板）")
    args = parser.parse_args()

    password = args.password
    if not args.admin_token:
        if password is None:
            if sys.stdin.isatty():
                import getpass
                password = getpass.getpass(f"{args.username} 的密码：")
            else:
                password = sys.stdin.readline().rstrip("\r\n")
        if not password:
            raise SystemExit("未提供密码（或改用 --admin-token）。")

    ledger: list[dict] = []

    def step(no, name, ok, detail="", skipped=False):
        tag = "SKIP" if skipped else ("PASS" if ok else "FAIL")
        print(f"S{no:02d} [{tag}] {name}" + (f"  — {detail}" if detail else ""), flush=True)
        ledger.append({"step": no, "name": name, "ok": bool(ok), "skipped": skipped,
                       "detail": detail})
        if not ok and not skipped:
            print(json.dumps(ledger, ensure_ascii=False, indent=2))
            raise SystemExit(f"贯通在第 {no} 步断链：{name}")

    if args.admin_token:
        admin_token = args.admin_token
    else:
        admin_token = login(args.base_url, args.username, password)
    admin_id = whoami(args.base_url, admin_token)
    if not admin_id:
        raise SystemExit("平台侧身份回读失败（token 无效或过期？）。")
    step(0, "平台侧登录", True, f"user_id={str(admin_id)[:8]}…")

    # 接单人凭证：token > password > 降级 admin 代接
    deliv_token = args.deliverer_token
    deliverer_id = whoami(args.base_url, deliv_token) if deliv_token else None
    if not deliverer_id and args.deliverer_password:
        deliv_token = login(args.base_url, args.deliverer, args.deliverer_password,
                            device_label="verify-e2e-deliverer")
        deliverer_id = whoami(args.base_url, deliv_token)
    degraded = deliverer_id is None
    if degraded:
        deliverer_id = admin_id  # admin 代接（accept_offer 允许平台侧）
        step(0, "接单人凭证", True, "未提供 token/password ⇒ 降级 admin 代接（视角步骤 SKIP）",
             skipped=True)
    else:
        step(0, "接单人登录（真实账号）", True,
             f"user={args.deliverer} id={str(deliverer_id)[:8]}…")

    # S1 文档模板前置自检
    status, data = data_of(call("GET", "/api/v1/document-templates", admin_token,
                                base_url=args.base_url))
    items = (data or {}).get("items") or []
    published = [i for i in items if (i.get("latest_published_version_number") or 0) >= 1]
    step(1, "文档模板种子在场（否则跑 seed-document-templates）",
         status == 200 and len(published) >= 1,
         f"templates={len(items)} published≥v1={len(published)}")

    # S1b 现取 published 行业模板版本（含 SOP 模块）
    status, data = data_of(call("GET", "/api/v1/industry-templates", admin_token,
                                base_url=args.base_url))
    rows = (((data or {}).get("items")) if isinstance(data, dict) else (data or [])) or []
    tpl_version_id = None
    for row in rows:
        if row.get("status") != "published":
            continue
        keys = {m.get("module_key") for m in (row.get("modules") or [])}
        if {"sop_presale", "sop_delivery", "sop_post_delivery"} <= keys:
            tpl_version_id = row.get("id") or row.get("version_id")
            break
    step(1, "published 行业模板版本（含 SOP 三模块）", bool(tpl_version_id),
         f"version={tpl_version_id}")

    # S2 立项（FDE_DISPATCH；过 H1/H2 渠道闸）
    status, data = data_of(call("POST", "/api/v1/projects", admin_token, {
        "name": "贯通验证-接单到交付",
        "enterprise_code": "E2E贯通·制造·佛山",
        "business_line": "FDE_DISPATCH",
        "planned_start_date": "2026-11-18",
        "leader_user_id": admin_id,
        "template_version_id": tpl_version_id,
        "module_keys": ["sop_presale", "sop_delivery", "sop_post_delivery"],
        "creation_source": "template",
        "background": "verify 脚本合成案例（机制验证，非真实客户）",
    }, base_url=args.base_url))
    project = data or {}
    pid = project.get("id")
    pv = project.get("version")
    step(2, "立项（FDE_DISPATCH）", status == 201 and bool(pid),
         f"project={pid} code={project.get('project_code')}")

    # S3 机会主体（零 AI）
    status, data = data_of(call("POST", f"/api/v1/projects/{pid}/research/subjects", admin_token, {
        "version": pv, "subject_type": "opportunity", "subject_key": "e2e_opp_01",
        "name": "贯通验证机会主体", "description": "合成（供方案关联）",
    }, base_url=args.base_url))
    opp_id = (data or {}).get("id")
    pv = (data or {}).get("project_version", pv + 1)
    step(3, "机会主体落库", status == 201 and bool(opp_id),
         f"tracking={(data or {}).get('tracking_code')}")

    # S4 方案
    status, data = data_of(call("POST", f"/api/v1/projects/{pid}/solutions", admin_token, {
        "name": "贯通验证交付方案", "opportunity_ids": [opp_id],
        "design_markdown": "# 设计\n合成方案。", "deliverables": "验收单",
        "acceptance_criteria": "合成标准", "business_category": "生产部署",
    }, base_url=args.base_url))
    sid = (data or {}).get("id")
    step(4, "方案落库", status == 201 and bool(sid), f"solution={sid}")

    # S5 报价（首单预设）
    status, data = data_of(call("POST", f"/api/v1/projects/{pid}/quotes", admin_token,
                                {"preset": "first_order_defaults"}, base_url=args.base_url))
    quote = data or {}
    quote_id, quote_key = quote.get("id"), quote.get("quote_key")
    step(5, "报价落库", status == 201 and bool(quote_id), f"key={quote_key}")

    # S6 负例：未回校 finalize（首单库 → 409；非首单库 → 200 直接成交）
    status, payload = call("POST", f"/api/v1/projects/{pid}/quotes/{quote_key}/finalize",
                           admin_token, {"final_amount": FINAL_AMOUNT}, base_url=args.base_url)
    code = ((payload or {}).get("error") or {}).get("code")
    already_finalized = status == 200
    step(6, "首单回校闸（首单库 409 calibration_required／非首单库直接成交）",
         status in (200, 409),
         f"http={status} code={code}" + ("（非首单库：已成交，后续回校步 SKIP）" if already_finalized else ""))

    # S7 回校（非首单库已成交则 SKIP）
    if already_finalized:
        step(7, "回校（非首单库已成交，SKIP）", True, "", skipped=True)
    else:
        status, data = data_of(call("POST", f"/api/v1/projects/{pid}/quotes/{quote_key}/calibrate",
                                    admin_token,
                                    {"actual_hours": 46, "deviation_reason": "verify 合成回校"},
                                    base_url=args.base_url))
        cal = (data or {}).get("calibration") or {}
        step(7, "回校落库", status == 200 and cal.get("actual_hours") == 46,
             f"deviation={cal.get('deviation_pct')}")

    # S8 成交回填（非首单库已成交则 SKIP）
    if already_finalized:
        step(8, "finalize（非首单库已成交，SKIP）", True, "", skipped=True)
    else:
        status, data = data_of(call("POST", f"/api/v1/projects/{pid}/quotes/{quote_key}/finalize",
                                    admin_token, {"final_amount": FINAL_AMOUNT},
                                    base_url=args.base_url))
        step(8, "finalize 成交回填",
             status == 200 and (data or {}).get("status") == "finalized",
             f"final={((data or {}).get('ledger') or {}).get('final_amount')}")

    # S9 负例：claims 未推 → 409 signoff_required
    status, payload = call("POST", f"/api/v1/projects/{pid}/quotes/{quote_key}/offer",
                           admin_token, base_url=args.base_url)
    code = ((payload or {}).get("error") or {}).get("code")
    step(9, "负例：未签字 offer 被拦", status == 409 and code == "signoff_required",
         f"http={status} code={code}")

    # S10 claims ×11
    done = 0
    for field in CLAIM_FIELDS:
        status, _ = data_of(call("POST", f"/api/v1/projects/{pid}/quotes/{quote_key}/claims",
                                 admin_token, {"field": field, "claim_status": "accepted"},
                                 base_url=args.base_url))
        if status == 200:
            done += 1
    step(10, "claims ×11 → accepted", done == 11, f"accepted={done}/11")

    # S11 对外签字件
    status, data = data_of(call("POST", f"/api/v1/projects/{pid}/quotes/{quote_key}/offer",
                                admin_token, base_url=args.base_url))
    step(11, "offer 正式件放行", status == 200 and (data or {}).get("external") is True, "")

    # S12 交付包
    status, data = data_of(call("POST", "/api/v1/dispatch/packages", admin_token, {
        "solution_id": sid, "quote_id": quote_id, "dispatch_mode": "assign",
        "onsite_required": True, "onsite_visits": 2,
    }, base_url=args.base_url))
    pkg_id = (data or {}).get("id")
    step(12, "交付包建包", status == 201 and bool(pkg_id), f"code={(data or {}).get('package_code')}")

    # S13 发布
    status, data = data_of(call("POST", f"/api/v1/dispatch/packages/{pkg_id}/publish", admin_token, {
        "candidate_user_ids": [deliverer_id], "difficulty": "medium",
    }, base_url=args.base_url))
    step(13, "发布（报价 finalized 前置）",
         status == 200 and (data or {}).get("dispatch_status") == "published", "")

    # S14 指派
    status, payload = call("POST", f"/api/v1/dispatch/packages/{pkg_id}/offers", admin_token,
                           {"candidate_user_ids": [deliverer_id]}, base_url=args.base_url)
    offers = (payload or {}).get("data") or []
    offer_id = offers[0].get("offer_id") if offers else None
    step(14, "指派 offer（assign）", status == 201 and bool(offer_id), "")

    # S15 接单人收件箱（降级模式 SKIP）
    mine = []
    if degraded:
        step(15, "接单人收件箱（降级 admin 代接，SKIP）", True, "", skipped=True)
    else:
        status, data = data_of(call("GET", "/api/v1/dispatch/offers/mine", deliv_token,
                                    base_url=args.base_url))
        mine = [o for o in (data or []) if o.get("offer_id") == offer_id]
        step(15, "接单人收件箱可见", status == 200 and len(mine) == 1,
             f"status={mine[0].get('status') if mine else '-'}")

    # S16 接单（乐观锁；降级模式 admin 代接）
    offer_version = mine[0].get("version") if mine else 1
    accept_token = deliv_token if not degraded else admin_token
    status, payload = call("POST", f"/api/v1/dispatch/offers/{offer_id}/accept", accept_token,
                           {"version": offer_version}, base_url=args.base_url)
    accept = ((payload or {}).get("data") or {}) if status == 200 else {}
    step(16, "接单＋自动交接", status == 200 and accept.get("status") == "accepted",
         f"handover.added={(accept.get('handover') or {}).get('added')}"
         + ("（admin 代接）" if degraded else ""))

    # S17 交接核验
    status, data = data_of(call("GET", f"/api/v1/projects/{pid}/members", admin_token,
                                base_url=args.base_url))
    members = (data or {}).get("items") if isinstance(data, dict) else (data or [])
    ok_members = deliverer_id in {m.get("user_id") for m in (members or [])}
    _status2, data2 = data_of(call("GET", f"/api/v1/dispatch/packages/{pkg_id}", admin_token,
                                  base_url=args.base_url))
    step(17, "交接核验（成员＋包终态）",
         ok_members and (data2 or {}).get("dispatch_status") == "accepted",
         f"members={len(members or [])} pkg={(data2 or {}).get('dispatch_status')}")

    # S18 负例：接单人建报价 403（降级模式 SKIP——admin 有 can_manage）
    if degraded:
        step(18, "权限边界（降级模式，SKIP）", True, "", skipped=True)
    else:
        status, _ = call("POST", f"/api/v1/projects/{pid}/quotes", deliv_token,
                         {"preset": "first_order_defaults"}, base_url=args.base_url)
        step(18, "权限边界：接单人建报价被拦", status == 403, f"http={status}")

    # S19 任务派发
    status, data = data_of(call("POST", f"/api/v1/projects/{pid}/modules/sop_delivery/tasks",
                                admin_token, {
        "name": "贯通验证交付任务", "description": "合成任务", "duration_days": 2,
        "assignee_user_id": deliverer_id,
    }, base_url=args.base_url))
    task_id, task_ver = (data or {}).get("id"), (data or {}).get("version")
    step(19, "任务派给接单人", status == 201 and bool(task_id), "")

    # S20 接单人推进（降级模式 SKIP）
    if degraded:
        step(20, "接单人推进任务（降级模式，SKIP）", True, "", skipped=True)
    else:
        status, data = data_of(call("PATCH", f"/api/v1/projects/{pid}/tasks/{task_id}", deliv_token,
                                    {"version": task_ver, "status": "in_progress", "progress": 50},
                                    base_url=args.base_url))
        step(20, "接单人推进任务", status == 200 and (data or {}).get("status") == "in_progress", "")
        status, data = data_of(call("PATCH", f"/api/v1/projects/{pid}/tasks/{task_id}", deliv_token,
                                    {"version": (data or {}).get("version"), "status": "completed",
                                     "progress": 100}, base_url=args.base_url))
        step(20, "接单人完成任务", status == 200 and (data or {}).get("status") == "completed", "")
        task_ver = (data or {}).get("version")

    # S21 负例：接单人改 manager 字段 403（降级模式 SKIP）
    if degraded:
        step(21, "权限边界（降级模式，SKIP）", True, "", skipped=True)
    else:
        status, _ = call("PATCH", f"/api/v1/projects/{pid}/tasks/{task_id}", deliv_token,
                         {"version": task_ver, "duration_days": 5}, base_url=args.base_url)
        step(21, "权限边界：接单人改 manager 字段被拦", status == 403, f"http={status}")

    # S22 SOP 证据指针
    status, data = data_of(call("PATCH", f"/api/v1/projects/{pid}/tasks/{task_id}", admin_token, {
        "version": task_ver, "evidence_uri": "verify-e2e://order-to-delivery/task",
        "evidence_hash": "0" * 64,
    }, base_url=args.base_url))
    step(22, "SOP 证据指针登记", status == 200, "")

    # S23 证据台账
    status, data = data_of(call("POST", f"/api/v1/projects/{pid}/evidence", admin_token, {
        "kind": "task", "source_uri": "verify-e2e://order-to-delivery/task",
        "content_sha256": "1" * 64, "origin": "verify 脚本合成案例", "captured_from": "human",
    }, base_url=args.base_url))
    step(23, "证据登记", status in (200, 201) and bool(((data or {}).get("evidence") or {}).get("id")), "")

    # S24 建文档
    status, data = data_of(call("GET", f"/api/v1/projects/{pid}", admin_token, base_url=args.base_url))
    pv = (data or {}).get("version")
    status, data = data_of(call("POST", f"/api/v1/projects/{pid}/documents", admin_token, {
        "document_type": "acceptance", "expected_version": pv,
        "business_category": "生产部署",
    }, base_url=args.base_url))
    if status != 201:
        code = ((payload or {}).get("error") or {}).get("code")
        raise SystemExit(
            f"建文档失败 http={status} code={code}——若 422 document_template_not_published，"
            "请先跑：docker compose exec api flask --app fde_api.wsgi:app seed-document-templates"
        )
    doc_id, doc_ver_no = (data or {}).get("id"), (data or {}).get("version")
    step(24, "项目文档落库", bool(doc_id), f"document={doc_id}")

    # S25 manual 修订（双交付件）
    docx_bytes = Path(args.docx).read_bytes()
    status, data = data_of(call("POST", f"/api/v1/projects/{pid}/documents/{doc_id}/revisions/manual",
                                admin_token, {
        "version": doc_ver_no, "note": "verify 合成交付件",
        "file_base64": base64.b64encode(docx_bytes).decode("ascii"),
    }, base_url=args.base_url))
    doc_version_id = (data or {}).get("id")
    file_version_id = (data or {}).get("docx_file_version_id")
    doc_version_new = (data or {}).get("document_version", doc_ver_no + 1)
    step(25, "manual 修订（document+file 双交付件）", status == 201 and bool(doc_version_id),
         f"sha={str((data or {}).get('sha256'))[:16]}…")

    # S26 确认
    status, data = data_of(call("POST", f"/api/v1/projects/{pid}/documents/{doc_version_id}/confirm",
                                admin_token, {"version": doc_version_new}, base_url=args.base_url))
    step(26, "文档版本确认", status == 200 and (data or {}).get("status") == "confirmed", "")

    # S27 挑选面
    ok_doc = ok_file = False
    status, data = data_of(call("GET", f"/api/v1/handover-packages/artifacts?project_id={pid}&type=document",
                                admin_token, base_url=args.base_url))
    rows = (data or {}).get("items") if isinstance(data, dict) else (data or [])
    ok_doc = any(r.get("document_version_id") == doc_version_id for r in (rows or []))
    status, data = data_of(call("GET", f"/api/v1/handover-packages/artifacts?project_id={pid}&type=file",
                                admin_token, base_url=args.base_url))
    rows = (data or {}).get("items") if isinstance(data, dict) else (data or [])
    ok_file = any(r.get("file_version_id") == file_version_id for r in (rows or []))
    step(27, "封包挑选面投影", ok_doc and ok_file, f"doc={ok_doc} file={ok_file}")

    # S28 建封包
    status, data = data_of(call("POST", "/api/v1/handover-packages", admin_token, {
        "project_id": pid, "label": "贯通验证结项交付包",
        "items": [
            {"item_type": "document", "document_version_id": doc_version_id},
            {"item_type": "file", "file_version_id": file_version_id},
        ],
    }, base_url=args.base_url))
    hpack_id = (data or {}).get("id")
    step(28, "建封包", status == 201 and bool(hpack_id), "")

    # S29 封存
    status, data = data_of(call("POST", f"/api/v1/handover-packages/{hpack_id}/seal", admin_token,
                                base_url=args.base_url))
    manifest = (data or {}).get("manifest_sha256")
    step(29, "封存（manifest 冻结）", status == 200 and bool(manifest),
         f"manifest={str(manifest)[:16]}…")

    # S30 交付登记
    status, data = data_of(call("POST", f"/api/v1/handover-packages/{hpack_id}/deliver",
                                admin_token, base_url=args.base_url))
    step(30, "交付登记（终态）", status == 200 and (data or {}).get("status") == "delivered", "")

    print("\n===== 贯通链收束 =====")
    print(json.dumps({
        "project_id": pid, "solution_id": sid, "quote_id": quote_id,
        "dispatch_package_id": pkg_id, "offer_id": offer_id,
        "handover_package_id": hpack_id, "manifest_sha256": manifest,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
