"""本体绑定面开关契约（D12/D13；WP4⑥ / §13 验收 8 的等价物）。

D12：蓝图**无条件**进 _BLUEPRINT_SPECS（蓝图注册表单一真身机器闸 P2-5，
app.py 除注册表循环外禁止直接注册），门控收敛在
integrations.service.ensure_enabled()——关闭 ⇒ 四入口一律 404 not_found
（禁用面与不存在面不可区分，对齐主线 diagnostics_enabled 先例）。

D13：门控判定**先于**鉴权（蓝图级 before_request 预闸）。四入口挂
@require_auth，若只在服务层设闸，未鉴权探针先撞鉴权（401）而非 404
（=面不存在）——「该路径存在」被泄露。故关闭态下无论是否鉴权，响应与
「路径不存在」逐字节同形（code/message/details 全同）。

评审 W-G：挂载双向不钉死则门禁可静默失效（该测试此前缺失）。
sqlite 文件库 + 真实 Settings；不依赖 CI PostgreSQL。
"""

from __future__ import annotations

from pathlib import Path

from flask import Flask
from pydantic import SecretStr

from fde_api.app import create_app
from fde_api.config import Settings

_BASE: dict[str, str] = {
    "redis_url": "redis://127.0.0.1:6379/2",
    "jwt_secret": "test-secret-with-at-least-thirty-two-characters",
}


def _settings(tmp_path: Path, *, enabled: bool) -> Settings:
    base = dict(_BASE)
    base["database_url"] = f"sqlite:///{tmp_path / ('flag-on.db' if enabled else 'flag-off.db')}"
    kwargs: dict[str, object] = {"env": "test", **base}
    if enabled:
        kwargs.update(
            ontology_enabled=True,
            ontology_api_key=SecretStr("k"),
            ontology_signing_key=SecretStr("s"),
        )
    return Settings(**kwargs)  # type: ignore[arg-type]


def _ontology_routes(app: Flask) -> set[str]:
    return {str(r) for r in app.url_map.iter_rules() if "ontology-bindings" in str(r)}


def _ontology_endpoints(app: Flask) -> set[tuple[str, str]]:
    """(method, rule) 集合。

    Flask 对同一路径的 GET 与 POST 生成两条独立 Rule（规则串相同、端点不同），
    故「四入口」必须按方法区分计数——只按规则串去重会得 3（漏 GET/POST 之一）。
    """
    found: set[tuple[str, str]] = set()
    for rule in app.url_map.iter_rules():
        if "ontology-bindings" not in str(rule):
            continue
        methods: set[str] = set(rule.methods or ())
        for method in sorted(methods - {"HEAD", "OPTIONS"}):
            found.add((method, str(rule)))
    return found


_EXPECTED_ENDPOINTS = {
    ("GET", "/api/v1/projects/<project_id>/ontology-bindings"),
    ("POST", "/api/v1/projects/<project_id>/ontology-bindings"),
    (
        "POST",
        "/api/v1/projects/<project_id>/ontology-bindings/<binding_id>/upgrade-proposal",
    ),
    (
        "POST",
        "/api/v1/projects/<project_id>/ontology-bindings"
        "/<binding_id>/approve-upgrade/<upgrade_id>",
    ),
    (
        "POST",
        "/api/v1/projects/<project_id>/ontology-bindings/<binding_id>/grounding-check",
    ),
    (
        "GET",
        "/api/v1/projects/<project_id>/ontology-bindings/<binding_id>/lineage",
    ),
    # M4-WP3（D26/D28）：Logic/Action 代理五入口
    (
        "POST",
        "/api/v1/projects/<project_id>/ontology-bindings/<binding_id>/logic/<logic_key>/run",
    ),
    (
        "POST",
        "/api/v1/projects/<project_id>/ontology-bindings/<binding_id>/actions/<action_key>/propose",
    ),
    (
        "POST",
        "/api/v1/projects/<project_id>/ontology-bindings"
        "/<binding_id>/action-requests/<request_id>/approvals",
    ),
    (
        "GET",
        "/api/v1/projects/<project_id>/ontology-bindings/<binding_id>/action-requests/<request_id>",
    ),
    (
        "POST",
        "/api/v1/projects/<project_id>/ontology-bindings/<binding_id>/actions/<action_key>/execute",
    ),
}


def test_flag_off_surface_registered_but_nonfunctional(tmp_path: Path) -> None:
    """off（默认）：六入口仍在路由表（注册表单一真身），但整面 404 not_found。

    D12：路由表不再是「与 V3.2 逐条相同」的判据——等价物改为「功能面不可
    用且不可区分于不存在」（下面两钉承担）。
    """
    app = create_app(_settings(tmp_path, enabled=False))
    assert _ontology_endpoints(app) == _EXPECTED_ENDPOINTS
    assert len(_ontology_routes(app)) == 10  # 规则串去重后（M3 五规则 + M4 五规则）
    assert app.config["SETTINGS"].ontology_enabled is False

    client = app.test_client()
    response = client.get("/api/v1/projects/proj-1/ontology-bindings")
    assert response.status_code == 404
    assert response.get_json()["error"]["code"] == "not_found"

    # 六个入口逐个探：关闭态一律 404（写入口亦不得先行受理）
    probes: tuple[tuple[str, str, dict[str, object] | None], ...] = (
        ("GET", "/api/v1/projects/proj-1/ontology-bindings", None),
        ("POST", "/api/v1/projects/proj-1/ontology-bindings", {}),
        (
            "POST",
            "/api/v1/projects/proj-1/ontology-bindings/bind-1/upgrade-proposal",
            {},
        ),
        (
            "POST",
            "/api/v1/projects/proj-1/ontology-bindings/bind-1/approve-upgrade/up-1",
            {},
        ),
        (
            "POST",
            "/api/v1/projects/proj-1/ontology-bindings/bind-1/grounding-check",
            {},
        ),
        (
            "GET",
            "/api/v1/projects/proj-1/ontology-bindings/bind-1/lineage",
            None,
        ),
    )
    for method, path, body in probes:
        call = client.open(path, method=method, json=body)
        assert call.status_code == 404, (method, path, call.status_code)
        assert call.get_json()["error"]["code"] == "not_found", (method, path)


def test_flag_off_probe_indistinguishable_from_absent_path(tmp_path: Path) -> None:
    """D13：关闭态探针与「路径不存在」逐字节同形（未鉴权 + 伪鉴权两种）。

    红线：禁用面若比不存在面多给一个可区分信号（401/文案差异），即为
    存在性泄露（M8 红队扫描面命中即阻断）。
    """
    app = create_app(_settings(tmp_path, enabled=False))
    client = app.test_client()

    absent = client.get("/api/v1/projects/proj-1/there-is-no-such-surface")
    assert absent.status_code == 404
    baseline = absent.get_json()

    probes: tuple[tuple[str, dict[str, str]], ...] = (
        ("no-auth", {}),
        ("bogus-auth", {"Authorization": "Bearer not-a-real-token"}),
    )
    for label, headers in probes:
        response = client.get(
            "/api/v1/projects/proj-1/ontology-bindings", headers=headers
        )
        assert response.status_code == 404, (label, response.status_code)
        assert response.get_json() == baseline, (label, response.get_json())


def test_flag_on_mounts_bindings_api(tmp_path: Path) -> None:
    """on：§5.2 四路径 + M3 D21 两路径 + M4 Logic/Action 五入口（共 11 个 method/rule 端点；去重规则 10 条）。"""
    app = create_app(_settings(tmp_path, enabled=True))
    routes = sorted(str(r) for r in app.url_map.iter_rules() if "ontology-bindings" in str(r))
    assert len(routes) == 11, routes  # url_map 不去重：GET/POST 同串各计一条
    assert _ontology_endpoints(app) == _EXPECTED_ENDPOINTS
    assert any(r.endswith("/ontology-bindings") for r in routes)
    assert any("upgrade-proposal" in r for r in routes)
    assert any("grounding-check" in r for r in routes)
    assert any(r.endswith("/lineage") for r in routes)
    assert any("approve-upgrade" in r for r in routes)
    assert any("/logic/" in r for r in routes)
    assert any("/actions/" in r for r in routes)
    assert any("action-requests" in r for r in routes)


_INGEST_ENDPOINTS: set[tuple[str, str]] = {
    ("POST", "/api/v1/projects/<project_id>/ontology-candidates"),
    ("GET", "/api/v1/projects/<project_id>/change-sets/<change_set_id>/review-package"),
}


def test_flag_off_ingest_and_review_package_indistinguishable_from_absent_path(
    tmp_path: Path,
) -> None:
    """D12 + D13 + D17：开关关闭时候选直提与评审包导出同样在 url_map 注册，但先于鉴权返回逐字节同形 404。"""
    app = create_app(_settings(tmp_path, enabled=False))
    present: set[tuple[str, str]] = set()
    for rule in app.url_map.iter_rules():
        methods: set[str] = set(rule.methods or ())
        for method in sorted(methods - {"HEAD", "OPTIONS"}):
            present.add((method, str(rule)))
    assert _INGEST_ENDPOINTS.issubset(present)

    client = app.test_client()
    absent = client.get("/api/v1/projects/proj-1/there-is-no-such-surface")
    assert absent.status_code == 404
    absent_body = absent.get_json()

    for headers in ({}, {"Authorization": "Bearer forged-token"}):
        r_post = client.post("/api/v1/projects/proj-1/ontology-candidates", json={}, headers=headers)
        r_get = client.get("/api/v1/projects/proj-1/change-sets/cs-1/review-package", headers=headers)
        assert r_post.status_code == 404 and r_post.get_json() == absent_body
        assert r_get.status_code == 404 and r_get.get_json() == absent_body
