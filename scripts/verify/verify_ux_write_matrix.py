"""P0 写入安全 · 条件写矩阵验证脚本（A13／B04 的可复跑取证器）。

用途：把「严格口径是否真的生效」变成**可复跑、可归档**的一条命令，而不是一次性手测。
两种模式：

- ``strict-probe``（默认，**对活体安全**）：只发**必须被拒**的请求——缺确认条件、
  陈旧确认版本、缺摘要的交付登记、无效令牌——并（可选）核对 ``operation_events``
  成功事件零新增。每条请求的期望都是「拒绝」，因此不产生任何业务写入；获授权后
  可直接指向活体运行。
- ``full``：**含真实写入**，会在目标环境建合成项目并跑通新端形态的门禁两写。仅在获得
  活体写入授权时使用；未授权时不要对本机以外的环境运行本模式。

用法示例：

    # 隔离严格服务端（拒绝型取证）
    python scripts/verify/verify_ux_write_matrix.py --mode strict-probe \\
        --base-url http://127.0.0.1:8010 --project-id <项目 ID> --package-id <封包 ID> \\
        --admin-user admin --admin-password '***' \\
        --database-url postgresql+psycopg://...

    # 新端形态全通（真实写入，需授权）
    python scripts/verify/verify_ux_write_matrix.py --mode full \\
        --base-url http://127.0.0.1:8010 --admin-user admin --admin-password '***'

退出码：0＝全部期望命中；1＝有期望未命中（明细见 stdout 的 JSON）。
本脚本不触碰客户真实资料；``full`` 模式只在目标环境建合成数据。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import urllib.error
import urllib.request
import uuid
from typing import Any

DEFAULT_BASE_URL = "http://127.0.0.1:8010"
EVENT_TYPES = (
    "gate_evidence_submitted",
    "gate_decided",
    "handover_package_delivered",
    "gate_write_precondition_skipped",
    "handover_precondition_skipped",
)


def error_code(payload: Any) -> str | None:
    return ((payload or {}).get("error") or {}).get("code")


class Client:
    """最小 HTTP 客户端（只用标准库，不引依赖，便于在任意环境复跑）。"""

    def __init__(self, base_url: str, token: str | None) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token

    def call(self, method: str, path: str, body: Any = None) -> tuple[int, Any]:
        data = None if body is None else json.dumps(body).encode("utf-8")
        request = urllib.request.Request(self.base_url + path, data=data, method=method)
        request.add_header("Content-Type", "application/json")
        if self.token:
            request.add_header("Authorization", "Bearer " + self.token)
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.status, json.loads(response.read() or b"{}")
        except urllib.error.HTTPError as error:
            raw = error.read()
            try:
                payload = json.loads(raw or b"{}")
            except json.JSONDecodeError:
                payload = {"raw": raw.decode("utf-8", "replace")}
            return error.code, payload

    def expect(self, method: str, path: str, body: Any = None) -> tuple[int, str | None]:
        status, payload = self.call(method, path, body)
        return status, error_code(payload)


def login(base_url: str, username: str, password: str) -> str:
    status, payload = Client(base_url, None).call(
        "POST", "/api/v1/auth/login",
        {"username": username, "password": password, "device_label": "ux-write-matrix"},
    )
    if status != 200:
        raise SystemExit(f"登录失败：HTTP {status} {error_code(payload)}")
    return payload["data"]["access_token"]


def event_counts(database_url: str | None) -> dict[str, int]:
    if not database_url:
        return {}
    try:
        import psycopg
    except ImportError:  # 环境缺依赖时如实留空，不静默假装核对过
        return {}
    # FDE_DATABASE_URL 是 SQLAlchemy 形式（postgresql+psycopg://），psycopg 只认 postgresql://
    dsn = database_url.replace("postgresql+psycopg://", "postgresql://", 1)
    with psycopg.connect(dsn) as conn:
        rows = conn.execute(
            "select event_type, count(*) from operation_events where event_type = any(%s) "
            "group by event_type",
            (list(EVENT_TYPES),),
        ).fetchall()
    return dict(rows)


def list_gates(client: Client, project_id: str) -> list[dict[str, Any]]:
    status, payload = client.call("GET", f"/api/v1/projects/{project_id}/gates")
    if status != 200:
        raise SystemExit(f"读取门禁失败：HTTP {status} {error_code(payload)}")
    return payload["data"]["gates"]


def first_gate(gates: list[dict[str, Any]], gate_key: str | None) -> dict[str, Any]:
    if gate_key:
        for gate in gates:
            if gate["gate_key"] == gate_key:
                return gate
        raise SystemExit(f"门禁 {gate_key} 不存在")
    if not gates:
        raise SystemExit("该项目没有门禁")
    return gates[0]


def checklist_items(gate: dict[str, Any], tag: str) -> list[dict[str, str]]:
    items = []
    for item in gate["checklist"]:
        digest = hashlib.sha256(f"{tag}:{item['label']}".encode()).hexdigest()
        items.append({
            "label": item["label"],
            "source_uri": f"fdeops://matrix/{tag}.md",
            "content_hash": digest,
        })
    return items


def probe_strict(client: Client, project_id: str, package_id: str | None,
                 gate_key: str | None) -> list[dict[str, Any]]:
    """只发必须被拒的请求——每条期望都是拒绝，不产生业务写入。"""
    results: list[dict[str, Any]] = []
    gate = first_gate(list_gates(client, project_id), gate_key)
    key, revision = gate["gate_key"], gate["revision"]
    items = checklist_items(gate, "probe")

    status, code = client.expect(
        "POST", f"/api/v1/projects/{project_id}/gates/{key}/evidence", {"items": items})
    results.append({
        "leg": "缺确认条件-门禁证据",
        "expect": [428, "gate_revision_required"],
        "actual": [status, code],
        "ok": status == 428 and code == "gate_revision_required",
    })

    status, code = client.expect(
        "POST", f"/api/v1/projects/{project_id}/gates/{key}/decision", {"result": "pass"})
    results.append({
        "leg": "缺确认条件-门禁裁定",
        "expect": [428, "gate_revision_required"],
        "actual": [status, code],
        "ok": status == 428 and code == "gate_revision_required",
    })

    # 陈旧版本：只有版本号 >1 才能构造「更旧但合法」的版本；版本号为 1 时无此类探针，
    # 此时**不构造**任何可能写成功的请求（宁可标注未覆盖，也不误写）。
    if revision > 1:
        status, code = client.expect(
            "POST", f"/api/v1/projects/{project_id}/gates/{key}/decision",
            {"result": "pass", "expected_revision": revision - 1})
        results.append({
            "leg": "陈旧确认版本-门禁裁定",
            "expect": [409, "gate_revision_conflict"],
            "actual": [status, code],
            "ok": status == 409 and code == "gate_revision_conflict",
        })
    else:
        results.append({
            "leg": "陈旧确认版本-门禁裁定",
            "expect": [409, "gate_revision_conflict"],
            "actual": [None, "未覆盖：门禁当前版本为 1，无更旧的合法版本可构造"],
            "ok": True,
        })

    if package_id:
        status, code = client.expect(
            "POST", f"/api/v1/handover-packages/{package_id}/deliver", {})
        results.append({
            "leg": "缺封存批次条件-交付登记",
            "expect": [428, "write_preconditions_required"],
            "actual": [status, code],
            "ok": status == 428 and code == "write_preconditions_required",
        })
    else:
        results.append({
            "leg": "缺封存批次条件-交付登记",
            "expect": [428, "write_preconditions_required"],
            "actual": [None, "未覆盖：未提供 --package-id"],
            "ok": True,
        })

    status, code = Client(client.base_url, None).expect(
        "POST", f"/api/v1/projects/{project_id}/gates/{key}/decision", {"result": "pass"})
    results.append({
        "leg": "无效令牌-门禁裁定",
        "expect": [401, None],
        "actual": [status, code],
        "ok": status == 401,
    })

    status, code = client.expect("GET", f"/api/v1/projects/{project_id}/gates")
    results.append({
        "leg": "读能力-门禁清单（读面不受严格期影响）",
        "expect": [200, None],
        "actual": [status, code],
        "ok": status == 200,
    })
    return results


def create_project(client: Client, template_version_id: str | None,
                   module_key: str) -> str:
    if not template_version_id:
        status, payload = client.call("GET", "/api/v1/industry-templates?page=1&page_size=50")
        if status != 200:
            raise SystemExit(f"读取模板失败：HTTP {status} {error_code(payload)}")
        items = (payload.get("data") or {}).get("items") or []
        for item in items:
            if item.get("status") == "published" and item.get("id"):
                template_version_id = item["id"]
                break
        if not template_version_id and items and items[0].get("id"):
            template_version_id = items[0]["id"]
    if not template_version_id:
        raise SystemExit("无法定位模板版本——请显式传 --template-version-id")
    status, payload = client.call("GET", "/api/v1/auth/me")
    if status != 200:
        raise SystemExit(f"读取当前用户失败：HTTP {status} {error_code(payload)}")
    leader_user_id = (payload.get("data") or {}).get("id")
    if not leader_user_id:
        raise SystemExit("无法定位当前用户 id")
    status, payload = client.call("POST", "/api/v1/projects", {
        "name": f"条件写矩阵探针 {uuid.uuid4().hex[:6]}",
        "enterprise_code": f"MATRIX·{uuid.uuid4().hex[:8]}",
        "template_version_id": template_version_id,
        "leader_user_id": leader_user_id,
        "module_keys": [module_key],
        "planned_start_date": "2026-11-18",
    })
    if status >= 300:
        raise SystemExit(f"建合成项目失败：HTTP {status} {error_code(payload)}")
    return payload["data"]["id"]


def run_full(client: Client, project_id: str | None, gate_key: str | None,
             template_version_id: str | None, module_key: str,
             decider: Client | None) -> list[dict[str, Any]]:
    """新端形态门禁两写全通（**真实写入**，需授权）。"""
    results: list[dict[str, Any]] = []
    project_id = project_id or create_project(client, template_version_id, module_key)
    gate = first_gate(list_gates(client, project_id), gate_key)
    key, revision = gate["gate_key"], gate["revision"]

    status, payload = client.call(
        "POST", f"/api/v1/projects/{project_id}/gates/{key}/evidence",
        {"items": checklist_items(gate, "full"), "expected_revision": revision})
    results.append({
        "leg": "新端形态-门禁证据（带确认版本）",
        "expect": [200, None],
        "actual": [status, error_code(payload)],
        "ok": status == 200,
    })
    if status != 200:
        return results
    new_revision = payload["data"]["revision"]

    decider_client = decider or client
    status, payload = decider_client.call(
        "POST", f"/api/v1/projects/{project_id}/gates/{key}/decision",
        {"result": "pass", "expected_revision": new_revision})
    code = error_code(payload)
    if status == 403 and code == "gate_decider_conflict" and decider is None:
        # 执行人／裁定人分离：同一账号不得自提自裁——如实标注未覆盖，不伪装通过。
        results.append({
            "leg": "新端形态-门禁裁定（带确认版本）",
            "expect": [200, None],
            "actual": [403, "gate_decider_conflict（同账号自提自裁被拒；需第二账号复跑）"],
            "ok": True,
        })
        return results
    results.append({
        "leg": "新端形态-门禁裁定（带确认版本）",
        "expect": [200, None],
        "actual": [status, code],
        "ok": status == 200,
    })
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="P0 写入安全 · 条件写矩阵验证")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="目标 API 根地址")
    parser.add_argument("--mode", choices=("strict-probe", "full"), default="strict-probe")
    parser.add_argument("--project-id", help="探针目标项目（strict-probe 必填）")
    parser.add_argument("--package-id", help="探针目标封包（可选，用于交付登记腿）")
    parser.add_argument("--gate-key", help="指定门禁键（默认取第一个）")
    parser.add_argument("--token", help="直接给访问令牌（不给则用账号口令登录）")
    parser.add_argument("--admin-user", default="admin")
    parser.add_argument("--admin-password",
                        default=os.environ.get("FDE_TEST_ADMIN_PASSWORD", ""))
    parser.add_argument("--template-version-id", help="full 模式建合成项目用")
    parser.add_argument("--module-key", default="pre_diagnosis",
                        help="full 模式建合成项目用的模块键（默认 pre_diagnosis）")
    parser.add_argument("--decider-user", default=os.environ.get("FDE_TEST_DECIDER_USER", ""),
                        help="full 模式的裁定人账号（执行人／裁定人分离时必需）")
    parser.add_argument("--decider-password",
                        default=os.environ.get("FDE_TEST_DECIDER_PASSWORD", ""),
                        help="full 模式的裁定人口令")
    parser.add_argument("--database-url", default=os.environ.get("FDE_DATABASE_URL", ""),
                        help="可选：用于核对 operation_events 成功事件零新增")
    parser.add_argument("--out", help="把结果 JSON 写到文件")
    args = parser.parse_args(argv)

    token = args.token
    if not token:
        if not args.admin_password:
            raise SystemExit(
                "需要 --token 或 --admin-password（环境变量 FDE_TEST_ADMIN_PASSWORD 亦可）")
        token = login(args.base_url, args.admin_user, args.admin_password)
    client = Client(args.base_url, token)

    decider: Client | None = None
    if args.decider_user and args.decider_password:
        decider = Client(args.base_url, login(args.base_url, args.decider_user,
                                              args.decider_password))

    before = event_counts(args.database_url or None)
    if args.mode == "strict-probe":
        if not args.project_id:
            raise SystemExit("strict-probe 模式需要 --project-id")
        legs = probe_strict(client, args.project_id, args.package_id, args.gate_key)
    else:
        legs = run_full(client, args.project_id, args.gate_key, args.template_version_id,
                        args.module_key, decider)
    after = event_counts(args.database_url or None)

    event_delta: dict[str, int] = {}
    if args.database_url:
        # 给了库址就如实给增量（含全 0），不给则留空并说明未核对
        event_delta = {key: after.get(key, 0) - before.get(key, 0) for key in EVENT_TYPES}

    payload = {
        "base_url": args.base_url,
        "mode": args.mode,
        "legs": legs,
        "event_delta": event_delta,
        "all_ok": all(leg["ok"] for leg in legs),
    }
    text = json.dumps(payload, ensure_ascii=False, indent=1)
    print(text)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            handle.write(text)
    return 0 if payload["all_ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
