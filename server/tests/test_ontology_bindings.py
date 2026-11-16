"""绑定服务与状态机测试（sqlite 内存外文件库；评审 W-G 验证缺口补齐）。







评审实证：0e5ca24 的服务层零测试放过了两个 dead-on-arrival 缺陷



（uq 卡死升级流 / I5 空 org 上下文）。本文件钉死：



- I5 语义（409 version_not_published / 503 down / 502 auth / D10 org 上下文）；



- 单活跃绑定 uq（active_marker）+ retire 后重绑；



- upgrade 生命周期（upgrade_pending → approved: retire+successor ｜ rejected: 恢复）；



- I4 自批 403、重复审批 409、approve 时点二次 I5；



- 项目访问控制（S-01：无权/不存在一律 404）。







不依赖 CI MySQL：用真实 Settings + create_app（sqlite 文件库），仅建相关表。



"""







from __future__ import annotations







from collections.abc import Iterator



from datetime import UTC, date, datetime



from pathlib import Path



from typing import Any







import pytest



from flask import Flask



from pydantic import SecretStr



from sqlalchemy import DefaultClause, event, select



from sqlalchemy import text as sa_text



from sqlalchemy.orm import Session







from fde_api.app import create_app



from fde_api.auth.models import Base, User



from fde_api.config import Settings



from fde_api.evidence.models import ProjectEvidence



from fde_api.extensions import db



from fde_api.integrations import service



from fde_api.integrations.models import ProjectOntologyBinding



from fde_api.integrations.ontology_client import (



    OntologyAuthError,



    OntologyClientError,



    OntologyConflict,



    OntologyUnavailable,



)



from fde_api.workbench.models import Project, ProjectMember







_BASE: dict[str, str] = {



    "database_url": "",  # 每测试填 sqlite 文件



    "redis_url": "redis://127.0.0.1:6379/2",



    "jwt_secret": "test-secret-with-at-least-thirty-two-characters",



}











def _fill_sqlite_timestamps(



    session: Session, flush_context: object, instances: object



) -> None:



    """sqlite 无 UTC_TIMESTAMP(6)（MySQL 专有 server_default）：flush 前显式



    回填时间戳列。方言守卫保证 CI MySQL 路径零影响。"""



    bind = session.bind



    if bind is None or bind.dialect.name != "sqlite":



        return



    now = datetime.now(UTC)



    for obj in session.new:



        for field in ("created_at", "updated_at", "acted_at"):



            if (



                hasattr(type(obj), field)



                and getattr(obj, field, None) is None



                and field in type(obj).__mapper__.columns



            ):



                setattr(obj, field, now)











def _leader() -> User:



    return User(



        id="u-leader", username="leader@test", role="project_lead", password_hash="x", is_active=True



    )











def _approver() -> User:



    return User(



        id="u-bo", username="bo@test", role="fde_engineer", password_hash="x", is_active=True



    )











class FakeClient:



    """get_version_snapshot 行为可编排；记录调用以断言 D10 org 上下文。"""







    def __init__(self, behavior: str = "ok", version: str = "1.0.0") -> None:



        self.behavior = behavior



        self.version = version



        self.calls: list[dict[str, Any]] = []
        self.delivery_behavior = "ok"







    def get_version_snapshot(self, **kwargs: Any) -> dict[str, Any]:



        self.calls.append(kwargs)



        if self.behavior == "ok":



            return {"version": self.version, "snapshot_sha256": "abc", "_status": 200}



        if self.behavior == "404":



            return {"code": "not_found", "_status": 404}



        if self.behavior == "down":



            raise OntologyUnavailable("refused")



        if self.behavior == "auth":



            raise OntologyAuthError({"message": "bad api key"})



        if self.behavior == "conflict":



            raise OntologyConflict({"message": "base_conflict"})



        raise AssertionError(f"unknown behavior {self.behavior}")

    def issue_trustboard_delivery_link(self, **kwargs: Any) -> dict[str, Any]:
        """M6 交付链接：默认返回含会话令牌的完整体（验证最小暴露收敛）。"""
        self.calls.append(kwargs)
        if self.delivery_behavior == "ok":
            return {
                "token": "vt-session-leak-check",
                "delivery_path": "/ui/#/overview?d=vh-handover",
                "handover_expires_at": "2026-11-16T09:00:00+00:00",
                "expires_at": "2026-11-16T20:00:00+00:00",
                "jti": "jti-1",
                "_status": 200,
            }
        if self.delivery_behavior == "down":
            raise OntologyUnavailable("refused")
        if self.delivery_behavior == "no-path":
            return {"token": "vt-x", "_status": 200}
        raise AssertionError(f"unknown delivery_behavior {self.delivery_behavior}")











@pytest.fixture



def wb_app_off(tmp_path: Path) -> Iterator[Flask]:



    """ontology_enabled=False 的同构应用（D12 契约钉用；建库但零 seed）。"""



    base = dict(_BASE)



    base["database_url"] = f"sqlite:///{tmp_path / 'wb-off.db'}"



    settings = Settings(env="test", **base)  # type: ignore[arg-type]



    yield create_app(settings)











@pytest.fixture



def wb_app(tmp_path: Path) -> Iterator[Flask]:



    base = dict(_BASE)



    base["database_url"] = f"sqlite:///{tmp_path / 'wb.db'}"



    settings = Settings(



        env="test",



        ontology_enabled=True,



        ontology_api_key=SecretStr("k"),



        ontology_signing_key=SecretStr("s"),



        **base,  # type: ignore[arg-type]



    )



    app = create_app(settings)



    engine = app.extensions["fde_api_db"]



    tables = [



        Base.metadata.tables[n]



        for n in (



            "users",



            "projects",



            "project_members",



            "project_ontology_bindings",



            "ontology_binding_upgrades",



            "project_evidence",  # D16：批注回执落 evidence（写面）



            "operation_events",  # D16：证据登记的审计留痕落此表



        )



    ]



    # sqlite 拒绝 MySQL 专有 DEFAULT 文案（UTC_TIMESTAMP(6)/ON UPDATE ...）：



    # 建表前临时翻译为 CURRENT_TIMESTAMP（DefaultClause 包裹保持 ORM 结构），teardown 还原



    _saved: dict[Any, Any] = {}



    for table in tables:



        columns: Any = table.columns



        for col in columns:



            sd = col.server_default



            arg = getattr(sd, "arg", None)



            rendered = str(arg) if arg is not None else ""



            if "TIMESTAMP" in rendered.upper():



                _saved[col] = sd



                col.server_default = DefaultClause(sa_text("CURRENT_TIMESTAMP"))



    # sqlite 无 char_length()（PG 原生函数）⇒ 注册等价 UDF，否则 project_evidence



    # 的 CHECK 约束在建表时即失败（不改主线 DDL，夹具层适配）



    @event.listens_for(engine, "checkout")



    def _register_char_length(dbapi_connection, *_args):



        dbapi_connection.create_function(



            "char_length", 1, lambda value: len(value) if value is not None else None



        )







    try:



        Base.metadata.create_all(engine, tables=tables)



        _seed(app)



        event.listen(Session, "before_flush", _fill_sqlite_timestamps)



        yield app



    finally:



        event.remove(Session, "before_flush", _fill_sqlite_timestamps)



        for col, sd in _saved.items():



            col.server_default = sd











def _seed(app: Flask) -> None:



    with app.app_context():



        session = db.session()



        session.add_all(



            [



                _leader(),



                _approver(),



                User(



        id="u-out", username="out@test", role="viewer", password_hash="x", is_active=True



    ),



                Project(



                    id="p-1",



                    project_code="PRJ-1",



                    name="项目一",



                    enterprise_code="ENT-1",  # 主线代号制（M4 后明文企业列已废）



                    leader_user_id="u-leader",



                    status="active",



                    planned_start_date=date(2026, 1, 1),



                    planned_end_date=date(2026, 12, 31),



                    template_snapshot={},  # NOT NULL 无默认（评审 sqlite 适配发现）



                    org_id="org-1",  # D10 段 2：租户归属（org 上下文唯一来源）



                ),



                Project(



                    id="p-2",



                    project_code="PRJ-2",



                    name="项目二",



                    enterprise_code="ENT-2",



                    leader_user_id="u-leader",



                    status="active",



                    planned_start_date=date(2026, 1, 1),



                    planned_end_date=date(2026, 12, 31),



                    template_snapshot={},



                    org_id="org-2",  # 另一租户：org 上下文随项目走



                ),



                Project(



                    id="p-3",



                    project_code="PRJ-3",



                    name="项目三",



                    enterprise_code="ENT-3",



                    leader_user_id="u-leader",



                    status="active",



                    planned_start_date=date(2026, 1, 1),



                    planned_end_date=date(2026, 12, 31),



                    template_snapshot={},



                    org_id=None,  # 归属戳会补 internal org；fail-closed 用例显式清空



                ),



                ProjectMember(project_id="p-1", user_id="u-bo", role="member"),



            ]



        )



        session.commit()











def _patch_client(monkeypatch: pytest.MonkeyPatch, fake: FakeClient) -> None:



    monkeypatch.setattr(service, "client_from_settings", lambda: fake)











def _create(



    wb_app: Flask, monkeypatch: pytest.MonkeyPatch, fake: FakeClient



) -> dict[str, Any]:



    _patch_client(monkeypatch, fake)



    with wb_app.app_context():



        return service.create_binding(



            actor=_leader(), project_id="p-1",



            payload={"ontology_id": "ont-1", "pinned_version_id": "ver-1"},



        )











def _propose(



    wb_app: Flask, monkeypatch: pytest.MonkeyPatch, binding_id: str



) -> dict[str, Any]:



    _patch_client(monkeypatch, FakeClient(behavior="ok", version="1.1.0"))



    with wb_app.app_context():



        return service.propose_upgrade(



            actor=_leader(), project_id="p-1", binding_id=binding_id,



            payload={



                "to_version_id": "ver-2",



                "diff_summary": "新增两个字段",



                "source_change_set_id": "cs-9",



            },



        )











def test_create_binding_happy_path_and_d10_context(



    wb_app: Flask, monkeypatch: pytest.MonkeyPatch



) -> None:



    fake = FakeClient(behavior="ok", version="1.0.0")



    binding = _create(wb_app, monkeypatch, fake)



    assert binding["status"] == "active"



    # pinned_version 以 runtime 核实响应回填（不信任客户端自报）



    assert binding["pinned_version"] == "1.0.0"



    assert binding["bound_by_user_id"] == "u-leader"



    # D10：I5 调用必须带 org 上下文 + 真实 project_id（评审 W-B 阻断缺陷的回归钉）；



    # 段 2 起 org 上下文来自**项目归属**（不再是配置值）



    assert fake.calls[0]["org_id"] == "org-1"



    assert fake.calls[0]["project_id"] == "p-1"



    assert fake.calls[0]["actor_id"] == "u-leader"











def test_create_binding_unpublished_version_409(



    wb_app: Flask, monkeypatch: pytest.MonkeyPatch



) -> None:



    with wb_app.app_context():



        _patch_client(monkeypatch, FakeClient(behavior="404"))



        with pytest.raises(service.BindingError) as excinfo:



            service.create_binding(



                actor=_leader(), project_id="p-1",



                payload={"ontology_id": "ont-1", "pinned_version_id": "ver-draft"},



            )



    assert excinfo.value.status == 409



    assert excinfo.value.code == "version_not_published"











def test_create_binding_runtime_down_503(wb_app: Flask, monkeypatch: pytest.MonkeyPatch) -> None:



    with wb_app.app_context():



        _patch_client(monkeypatch, FakeClient(behavior="down"))



        with pytest.raises(service.BindingError) as excinfo:



            service.create_binding(



                actor=_leader(), project_id="p-1",



                payload={"ontology_id": "ont-1", "pinned_version_id": "ver-1"},



            )



    assert excinfo.value.status == 503



    assert excinfo.value.code == "ontology_unavailable"


def test_translate_runtime_call_messages_carry_no_internal_details() -> None:
    """Vex 13:22 M6 放行条件(a)（S-07）：_translate_runtime_call 三处映射文案零内部细节回显。

    异常链（__cause__）保留全部拓扑细节供服务端日志；管理面文案只留语义
    （不可达/冲突/失败 + 原状态码），禁 ``{exc}`` 直透内网 URL/内部路径。
    """
    intranet = "http://10.203.7.42:8902/api/v1/versions/ver-1/snapshot"

    def raiser(exc: Exception) -> Any:
        def call() -> dict[str, Any]:
            raise exc

        return call

    cases = [
        (OntologyUnavailable(f"ontology runtime unreachable: {intranet}"),
         503, "ontology_unavailable"),
        (OntologyConflict({"message": "base_conflict"}), 409, "runtime_conflict"),
        (OntologyClientError("ontology runtime 5xx: 502 /api/v1/versions"),
         502, "runtime_error"),
    ]
    for exc, status, code in cases:
        with pytest.raises(service.BindingError) as excinfo:
            service._translate_runtime_call(raiser(exc))
        assert excinfo.value.status == status
        assert excinfo.value.code == code
        assert intranet not in excinfo.value.message
        assert "10.203.7.42" not in excinfo.value.message
        assert "/api/v1/" not in excinfo.value.message


def test_create_binding_runtime_down_message_no_intranet_echo(
    wb_app: Flask, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Vex 13:22 条件(a) 全链路钉：client 文案带内网 URL 时，绑定面 503 亦零回显（I5 路径）。"""
    intranet = "http://10.203.7.42:8902"

    class _LeakyClient(FakeClient):
        def get_version_snapshot(self, **kwargs: Any) -> dict[str, Any]:
            raise OntologyUnavailable(f"ontology runtime unreachable: {intranet}/healthz")

    with wb_app.app_context():
        _patch_client(monkeypatch, _LeakyClient())
        with pytest.raises(service.BindingError) as excinfo:
            service.create_binding(
                actor=_leader(), project_id="p-1",
                payload={"ontology_id": "ont-1", "pinned_version_id": "ver-1"},
            )
    assert excinfo.value.status == 503
    assert excinfo.value.code == "ontology_unavailable"
    assert intranet not in excinfo.value.message
    assert "10.203.7.42" not in excinfo.value.message












def test_create_binding_auth_fault_502(wb_app: Flask, monkeypatch: pytest.MonkeyPatch) -> None:



    with wb_app.app_context():



        _patch_client(monkeypatch, FakeClient(behavior="auth"))



        with pytest.raises(service.BindingError) as excinfo:



            service.create_binding(



                actor=_leader(), project_id="p-1",



                payload={"ontology_id": "ont-1", "pinned_version_id": "ver-1"},



            )



    assert excinfo.value.status == 502



    assert excinfo.value.code == "runtime_auth"











def test_create_binding_conflict_fault_502(wb_app: Flask, monkeypatch: pytest.MonkeyPatch) -> None:



    with wb_app.app_context():



        _patch_client(monkeypatch, FakeClient(behavior="conflict"))



        with pytest.raises(service.BindingError) as excinfo:



            service.create_binding(



                actor=_leader(), project_id="p-1",



                payload={"ontology_id": "ont-1", "pinned_version_id": "ver-1"},



            )



    assert excinfo.value.status == 502











def test_binding_requires_project_access(wb_app: Flask, monkeypatch: pytest.MonkeyPatch) -> None:



    """S-01：无权成员与不存在项目一律 404（不泄露存在性）。"""



    with wb_app.app_context():



        _patch_client(monkeypatch, FakeClient())



        outsider = User(



        id="u-out", username="out@test", role="viewer", password_hash="x", is_active=True



    )



        for pid in ("p-1", "p-missing"):



            with pytest.raises(service.BindingError) as excinfo:



                service.create_binding(



                    actor=outsider, project_id=pid,



                    payload={"ontology_id": "ont-1", "pinned_version_id": "ver-1"},



                )



            assert excinfo.value.status == 404











def test_single_active_binding_and_rebind_after_retire(



    wb_app: Flask, monkeypatch: pytest.MonkeyPatch



) -> None:



    binding = _create(wb_app, monkeypatch, FakeClient())



    with wb_app.app_context():



        with pytest.raises(service.BindingError) as excinfo:



            service.create_binding(



                actor=_leader(), project_id="p-1",



                payload={"ontology_id": "ont-1", "pinned_version_id": "ver-1"},



            )



        assert excinfo.value.status == 409



        # retire 后可重绑（评审 W-A：生命周期不得死锁）



        session = db.session()



        row = session.get(ProjectOntologyBinding, binding["id"])



        assert row is not None



        row.status = "retired"



        row.active_marker = None



        session.commit()



    rebound = _create(wb_app, monkeypatch, FakeClient(behavior="ok", version="1.1.0"))



    assert rebound["pinned_version"] == "1.1.0"











def test_propose_upgrade_requires_review_material(



    wb_app: Flask, monkeypatch: pytest.MonkeyPatch



) -> None:



    """§5.2：差异审查不空转——diff_summary/source_change_set_id 必带。"""



    binding = _create(wb_app, monkeypatch, FakeClient())



    _patch_client(monkeypatch, FakeClient(behavior="ok", version="1.1.0"))



    with wb_app.app_context():



        for payload in (



            {"to_version_id": "ver-2", "diff_summary": "", "source_change_set_id": "cs-9"},



            {"to_version_id": "ver-2", "diff_summary": "x", "source_change_set_id": ""},



        ):



            with pytest.raises(service.BindingError) as excinfo:



                service.propose_upgrade(



                    actor=_leader(), project_id="p-1",



                    binding_id=binding["id"], payload=payload,



                )



            assert excinfo.value.code == "invalid_request"











def test_upgrade_lifecycle_approve_creates_successor(



    wb_app: Flask, monkeypatch: pytest.MonkeyPatch



) -> None:



    binding = _create(wb_app, monkeypatch, FakeClient())



    propose = _propose(wb_app, monkeypatch, binding["id"])



    assert propose["status"] == "proposed"







    with wb_app.app_context():



        session = db.session()



        row = session.get(ProjectOntologyBinding, binding["id"])



        assert row is not None



        assert row.status == "upgrade_pending"  # data-model §3 状态位







        # I4：提案人自批 403



        with pytest.raises(service.BindingError) as excinfo:



            service.approve_upgrade(



                actor=_leader(), project_id="p-1", binding_id=binding["id"],



                upgrade_id=propose["id"], decision="approved",



            )



        assert excinfo.value.status == 403







        # 成员批准 → 二次 I5 → retire 旧行 + successor active



        fake = FakeClient(behavior="ok", version="1.1.0")



        _patch_client(monkeypatch, fake)



        result = service.approve_upgrade(



            actor=_approver(), project_id="p-1", binding_id=binding["id"],



            upgrade_id=propose["id"], decision="approved",



        )



        assert result["status"] == "active"



        assert result["pinned_version"] == "1.1.0"



        assert fake.calls[0]["version_id"] == "ver-2"  # approve 时点二次 I5



        session.expire_all()  # service 用独立 session 提交，清身份映射缓存



        old = session.get(ProjectOntologyBinding, binding["id"])



        assert old is not None



        new = session.get(ProjectOntologyBinding, result["id"])



        assert new is not None



        assert old.status == "retired" and old.active_marker is None  # retire 不删行



        assert new.status == "active" and new.active_marker == "active"



        assert old.ontology_id == new.ontology_id  # uq 三键成立（W-A 回归钉）











def test_upgrade_lifecycle_reject_restores_active(



    wb_app: Flask, monkeypatch: pytest.MonkeyPatch



) -> None:



    binding = _create(wb_app, monkeypatch, FakeClient())



    propose = _propose(wb_app, monkeypatch, binding["id"])



    with wb_app.app_context():



        _patch_client(monkeypatch, FakeClient())



        result = service.approve_upgrade(



            actor=_approver(), project_id="p-1", binding_id=binding["id"],



            upgrade_id=propose["id"], decision="rejected",



        )



        assert result["status"] == "rejected"



        session = db.session()



        row = session.get(ProjectOntologyBinding, binding["id"])



        assert row is not None



        assert row.status == "active" and row.active_marker == "active"











def test_upgrade_double_act_409(wb_app: Flask, monkeypatch: pytest.MonkeyPatch) -> None:



    binding = _create(wb_app, monkeypatch, FakeClient())



    propose = _propose(wb_app, monkeypatch, binding["id"])



    with wb_app.app_context():



        _patch_client(monkeypatch, FakeClient())



        service.approve_upgrade(



            actor=_approver(), project_id="p-1", binding_id=binding["id"],



            upgrade_id=propose["id"], decision="rejected",



        )



        # 模拟并发竞态（绑定仍 upgrade_pending 的窗口内重复审批）：



        # 服务层的 already-acted 守卫应 409，而非重复落 successor



        session = db.session()



        row = session.get(service.OntologyBindingUpgrade, propose["id"])



        assert row is not None



        bind = session.get(ProjectOntologyBinding, binding["id"])



        assert bind is not None



        row.status = "approved"



        bind.status = "upgrade_pending"



        bind.active_marker = "active"



        session.commit()



        with pytest.raises(service.BindingError) as excinfo:



            service.approve_upgrade(



                actor=_approver(), project_id="p-1", binding_id=binding["id"],



                upgrade_id=propose["id"], decision="approved",



            )



        assert excinfo.value.status == 409



        assert excinfo.value.code == "upgrade_already_acted"











def test_upgrade_approve_reverifies_i5(wb_app: Flask, monkeypatch: pytest.MonkeyPatch) -> None:



    """propose→approve 间版本下架 → approve 409，绑定保持 upgrade_pending（写不降级）。"""



    binding = _create(wb_app, monkeypatch, FakeClient())



    propose = _propose(wb_app, monkeypatch, binding["id"])



    with wb_app.app_context():



        _patch_client(monkeypatch, FakeClient(behavior="404"))



        with pytest.raises(service.BindingError) as excinfo:



            service.approve_upgrade(



                actor=_approver(), project_id="p-1", binding_id=binding["id"],



                upgrade_id=propose["id"], decision="approved",



            )



        assert excinfo.value.status == 409



        session = db.session()



        row = session.get(ProjectOntologyBinding, binding["id"])



        assert row is not None



        assert row.status == "upgrade_pending"  # 回滚：未产生 successor











def test_list_bindings_includes_pending_upgrades(



    wb_app: Flask, monkeypatch: pytest.MonkeyPatch



) -> None:



    binding = _create(wb_app, monkeypatch, FakeClient())



    _propose(wb_app, monkeypatch, binding["id"])



    _patch_client(monkeypatch, FakeClient())



    with wb_app.app_context():



        items = service.list_bindings(actor=_leader(), project_id="p-1")



        assert len(items) == 1



        assert items[0]["id"] == binding["id"]



        assert len(items[0]["pending_upgrades"]) == 1



        with pytest.raises(service.BindingError) as excinfo:



            service.list_bindings(actor=_leader(), project_id="p-missing")



        assert excinfo.value.status == 404











def test_flag_off_all_binding_entries_404_not_found(wb_app_off: Flask) -> None:



    """D12 契约钉：ontology_enabled=False ⇒ 绑定面全部入口 404 not_found。







    蓝图无条件进 _BLUEPRINT_SPECS（注册表单一真身机器闸 P2-5），开关门控



    收敛在服务层 ensure_enabled——对齐 diagnostics_enabled「不确认面存在」



    先例：禁用面与不存在面不可区分（无存在性泄露），且在任何业务校验



    （含 invalid_request / 项目访问控制）之前触发，零出站调用（fail-closed）。



    """



    leader = _leader()



    with wb_app_off.app_context():



        with pytest.raises(service.BindingError) as excinfo:



            service.list_bindings(actor=leader, project_id="p-1")



        assert (excinfo.value.status, excinfo.value.code) == (404, "not_found")



        with pytest.raises(service.BindingError) as excinfo:



            service.create_binding(actor=leader, project_id="p-1", payload={})



        assert (excinfo.value.status, excinfo.value.code) == (404, "not_found")



        with pytest.raises(service.BindingError) as excinfo:



            service.propose_upgrade(



                actor=leader, project_id="p-1", binding_id="b-1", payload={}



            )



        assert (excinfo.value.status, excinfo.value.code) == (404, "not_found")



        with pytest.raises(service.BindingError) as excinfo:



            service.approve_upgrade(



                actor=leader, project_id="p-1", binding_id="b-1",



                upgrade_id="u-1", decision="approved",



            )



        assert (excinfo.value.status, excinfo.value.code) == (404, "not_found")











# --- 段 2 步 3+4（D10 段 2：org 上下文 = 项目归属；绑定行落 org 归属） ---











def test_create_binding_stamps_project_org(



    wb_app: Flask, monkeypatch: pytest.MonkeyPatch



) -> None:



    """绑定行落项目归属 org（段 1 的可空预留列语义已终结）。"""



    fake = FakeClient()



    _patch_client(monkeypatch, fake)



    with wb_app.app_context():



        created = service.create_binding(



            actor=_leader(), project_id="p-1",



            payload={"ontology_id": "ont-1", "pinned_version_id": "ver-1"},



        )



        session = db.session()



        row = session.get(ProjectOntologyBinding, created["id"])



        assert row is not None



        assert row.org_id == "org-1"



        assert row.project_id == "p-1"











def test_create_binding_project_without_org_fails_closed(



    wb_app: Flask, monkeypatch: pytest.MonkeyPatch



) -> None:



    """项目无 org 归属 ⇒ 409 project_org_missing；零出站、零写入（fail-closed）。







    归属戳（orgs/org_scope.py 的 before_flush）只覆盖**新增**对象——存量行



    （回填前遗留 / 非 ORM 写入）可能仍无归属；此时绑定面必须 fail-closed，



    绝不以空 org 去打扰 runtime。



    """



    fake = FakeClient()



    _patch_client(monkeypatch, fake)



    with wb_app.app_context():



        session = db.session()



        project = session.get(Project, "p-3")



        assert project is not None



        project.org_id = None



        session.commit()



        with pytest.raises(service.BindingError) as excinfo:



            service.create_binding(



                actor=_leader(), project_id="p-3",



                payload={"ontology_id": "ont-1", "pinned_version_id": "ver-1"},



            )



    assert excinfo.value.status == 409



    assert excinfo.value.code == "project_org_missing"



    assert fake.calls == []  # fail-closed：绝不以空 org 出站



    with wb_app.app_context():



        session = db.session()



        rows = session.scalars(



            select(ProjectOntologyBinding).where(ProjectOntologyBinding.project_id == "p-3")



        ).all()



        assert rows == []











def test_i5_org_context_follows_project_org(



    wb_app: Flask, monkeypatch: pytest.MonkeyPatch



) -> None:



    """org 上下文按项目解析：不同租户的项目各发各的（不共用配置值）。"""



    fake = FakeClient()



    _patch_client(monkeypatch, fake)



    with wb_app.app_context():



        service.create_binding(



            actor=_leader(), project_id="p-2",



            payload={"ontology_id": "ont-2", "pinned_version_id": "ver-9"},



        )



    assert fake.calls[0]["org_id"] == "org-2"



    assert fake.calls[0]["project_id"] == "p-2"











def test_upgrade_successor_inherits_project_org(



    wb_app: Flask, monkeypatch: pytest.MonkeyPatch



) -> None:



    """升级 successor 行继承同一项目归属 org（归属不得在升级过程中漂移）。"""



    binding = _create(wb_app, monkeypatch, FakeClient())



    propose = _propose(wb_app, monkeypatch, binding["id"])



    with wb_app.app_context():



        _patch_client(monkeypatch, FakeClient(behavior="ok", version="1.1.0"))



        result = service.approve_upgrade(



            actor=_approver(), project_id="p-1", binding_id=binding["id"],



            upgrade_id=propose["id"], decision="approved",



        )



        session = db.session()



        session.expire_all()



        old = session.get(ProjectOntologyBinding, binding["id"])



        new = session.get(ProjectOntologyBinding, result["id"])



        assert old is not None and new is not None



        assert old.org_id == "org-1"



        assert new.org_id == "org-1"











def test_binding_org_mismatch_blocks_upgrade(



    wb_app: Flask, monkeypatch: pytest.MonkeyPatch



) -> None:



    """项目改属（org 变更）⇒ 旧绑定的归属不再一致 ⇒ 409 且零出站（fail-closed）。"""



    binding = _create(wb_app, monkeypatch, FakeClient())



    with wb_app.app_context():



        session = db.session()



        project = session.get(Project, "p-1")



        assert project is not None



        project.org_id = "org-moved"



        session.commit()



    fake = FakeClient(behavior="ok", version="1.1.0")



    _patch_client(monkeypatch, fake)



    with wb_app.app_context():



        with pytest.raises(service.BindingError) as excinfo:



            service.propose_upgrade(



                actor=_leader(), project_id="p-1", binding_id=binding["id"],



                payload={



                    "to_version_id": "ver-2",



                    "diff_summary": "新增两个字段",



                    "source_change_set_id": "cs-9",



                },



            )



    assert excinfo.value.status == 409



    assert excinfo.value.code == "binding_org_mismatch"



    assert fake.calls == []  # fail-closed：归属不一致时绝不打扰 runtime











def _annotation_payload() -> dict[str, Any]:



    """D16 批注回执入参（契约 §5：review_package_id = 内容寻址 sha256）。"""



    return {



        "review_package_id": "a" * 64,



        "content_sha256": "b" * 64,



        "source_uri": "ontology_review:" + "a" * 64 + "#意见-1",



        "origin": "评审员批注：字段命名需与本体对齐",



    }











def test_upgrade_approve_records_annotation_evidence(



    wb_app: Flask, monkeypatch: pytest.MonkeyPatch



) -> None:



    """D16：升级审批携带批注 ⇒ 落 project_evidence(kind=ontology_annotation)，



    并回写升级留痕 annotation_evidence_id（§15：版本升级必须记录审批人和证据）。"""



    binding = _create(wb_app, monkeypatch, FakeClient())



    propose = _propose(wb_app, monkeypatch, binding["id"])



    with wb_app.app_context():



        _patch_client(monkeypatch, FakeClient(behavior="ok", version="1.1.0"))



        service.approve_upgrade(



            actor=_approver(), project_id="p-1", binding_id=binding["id"],



            upgrade_id=propose["id"], decision="approved",



            annotation=_annotation_payload(),



        )



        session = db.session()



        session.expire_all()



        rows = session.scalars(select(ProjectEvidence)).all()



        assert len(rows) == 1



        row = rows[0]



        assert row.kind == "ontology_annotation"



        assert row.captured_from == "ontology_review:" + "a" * 64



        assert row.content_sha256 == "b" * 64



        assert row.source_uri == "ontology_review:" + "a" * 64 + "#意见-1"



        upgrade = session.get(service.OntologyBindingUpgrade, propose["id"])



        assert upgrade is not None



        assert upgrade.annotation_evidence_id == row.id











def test_upgrade_approve_without_annotation_leaves_no_evidence(



    wb_app: Flask, monkeypatch: pytest.MonkeyPatch



) -> None:



    """不带批注 ⇒ 不凭空造证据（annotation_evidence_id 保持 NULL）。"""



    binding = _create(wb_app, monkeypatch, FakeClient())



    propose = _propose(wb_app, monkeypatch, binding["id"])



    with wb_app.app_context():



        _patch_client(monkeypatch, FakeClient(behavior="ok", version="1.1.0"))



        service.approve_upgrade(



            actor=_approver(), project_id="p-1", binding_id=binding["id"],



            upgrade_id=propose["id"], decision="approved",



        )



        session = db.session()



        session.expire_all()



        assert session.scalars(select(ProjectEvidence)).all() == []



        upgrade = session.get(service.OntologyBindingUpgrade, propose["id"])



        assert upgrade is not None



        assert upgrade.annotation_evidence_id is None











def test_upgrade_approve_malformed_annotation_400_no_side_effect(



    wb_app: Flask, monkeypatch: pytest.MonkeyPatch



) -> None:



    """畸形批注 ⇒ 400 invalid_request，零证据行、升级仍 proposed、零出站调用。"""



    binding = _create(wb_app, monkeypatch, FakeClient())



    propose = _propose(wb_app, monkeypatch, binding["id"])



    with wb_app.app_context():



        fake = FakeClient(behavior="ok", version="1.1.0")



        _patch_client(monkeypatch, fake)



        for bad in (



            {"review_package_id": "not-hex", "content_sha256": "b" * 64, "source_uri": "x"},



            {"review_package_id": "a" * 64, "content_sha256": "zz", "source_uri": "x"},



            {"review_package_id": "a" * 64, "content_sha256": "b" * 64, "source_uri": ""},



        ):



            with pytest.raises(service.BindingError) as excinfo:



                service.approve_upgrade(



                    actor=_approver(), project_id="p-1", binding_id=binding["id"],



                    upgrade_id=propose["id"], decision="approved", annotation=bad,



                )



            assert excinfo.value.status == 400



            assert excinfo.value.code == "invalid_request"



        session = db.session()



        session.expire_all()



        assert session.scalars(select(ProjectEvidence)).all() == []



        upgrade = session.get(service.OntologyBindingUpgrade, propose["id"])



        assert upgrade is not None



        assert upgrade.status == "proposed"



        assert fake.calls == []





# ======================================================================
# M6-WP6：TrustBoard 交付链接签发（Workbench 侧出链，单次消费口径）
# M6-WP6-R4：交付链接内嵌一次性交接令牌；会话令牌不回吐（凭据最小暴露）
# ======================================================================


def _tb_auth_headers(app: Flask, user_id: str = "u-leader") -> dict[str, str]:
    from fde_api.auth.tokens import issue_access_token

    with app.app_context():
        session = db.session()
        user = session.scalar(select(User).where(User.id == user_id))
        assert user is not None
        # 种子用户 must_change_password=True（模型默认）⇒ 路由鉴权面会被
        # password_change_required 闸拦下；测试须先过此闸。
        user.must_change_password = False
        session.commit()
        settings = app.config["SETTINGS"]
        return {"Authorization": f"Bearer {issue_access_token(user, settings)}"}


def _tb_issue_delivery(
    wb_app: Flask, monkeypatch: pytest.MonkeyPatch, fake: FakeClient
) -> dict[str, Any]:
    _create(wb_app, monkeypatch, fake)
    _patch_client(monkeypatch, fake)
    with wb_app.app_context():
        return service.issue_trustboard_delivery_link(actor=_leader(), project_id="p-1")


def test_delivery_link_happy_path_minimal_exposure(wb_app: Flask, monkeypatch: pytest.MonkeyPatch) -> None:
    """交付链接载荷最小暴露：只给一次性消费链接 + 到期时刻，会话令牌不回吐。"""
    fake = FakeClient(behavior="ok")
    link = _tb_issue_delivery(wb_app, monkeypatch, fake)
    assert link["delivery_path"] == "/ui/#/overview?d=vh-handover"
    assert link["single_use"] is True
    assert link["expires_at"] == "2026-11-16T09:00:00+00:00"  # 取交接令牌到期（短者）
    assert "token" not in link  # 会话令牌（常驻凭据）不回吐给调用方
    delivery_call = fake.calls[-1]
    assert delivery_call["org_id"] == "org-1"
    assert delivery_call["project_id"] == "p-1"
    assert delivery_call["ontology_id"] == "ont-1"
    assert delivery_call["actor_id"] == "u-leader"


def test_delivery_link_no_active_binding_404(wb_app: Flask, monkeypatch: pytest.MonkeyPatch) -> None:
    """无 active 绑定 → 404（不泄露存在性）；零出站（fail-closed）。"""
    fake = FakeClient(behavior="ok")
    _patch_client(monkeypatch, fake)
    with wb_app.app_context():
        with pytest.raises(service.BindingError) as excinfo:
            service.issue_trustboard_delivery_link(actor=_leader(), project_id="p-1")
    assert excinfo.value.status == 404
    assert fake.calls == []  # 未到达 runtime


def test_delivery_link_flag_off_404(wb_app_off: Flask, monkeypatch: pytest.MonkeyPatch) -> None:
    """D12 契约钉：ontology_enabled=False ⇒ 交付链接面 404 not_found。"""
    fake = FakeClient(behavior="ok")
    _patch_client(monkeypatch, fake)
    with wb_app_off.app_context():
        with pytest.raises(service.BindingError) as excinfo:
            service.issue_trustboard_delivery_link(actor=_leader(), project_id="p-1")
    assert excinfo.value.status == 404
    assert excinfo.value.code == "not_found"
    assert fake.calls == []


def test_delivery_link_runtime_down_503(wb_app: Flask, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeClient(behavior="ok")
    _create(wb_app, monkeypatch, fake)
    fake.delivery_behavior = "down"
    _patch_client(monkeypatch, fake)
    with wb_app.app_context():
        with pytest.raises(service.BindingError) as excinfo:
            service.issue_trustboard_delivery_link(actor=_leader(), project_id="p-1")
    assert excinfo.value.status == 503
    assert excinfo.value.code == "ontology_unavailable"


def test_delivery_link_runtime_omits_path_502(wb_app: Flask, monkeypatch: pytest.MonkeyPatch) -> None:
    """runtime 200 但无 delivery_path（契约回归）→ 502 delivery_link_failed。"""
    fake = FakeClient(behavior="ok")
    _create(wb_app, monkeypatch, fake)
    fake.delivery_behavior = "no-path"
    _patch_client(monkeypatch, fake)
    with wb_app.app_context():
        with pytest.raises(service.BindingError) as excinfo:
            service.issue_trustboard_delivery_link(actor=_leader(), project_id="p-1")
    assert excinfo.value.status == 502
    assert excinfo.value.code == "delivery_link_failed"


def test_delivery_link_route_no_store_and_minimal_payload(
    wb_app: Flask, monkeypatch: pytest.MonkeyPatch
) -> None:
    """路由层：project_lead 可签发；响应 no-store（凭据禁缓存）；载荷最小化。"""
    fake = FakeClient(behavior="ok")
    _create(wb_app, monkeypatch, fake)
    _patch_client(monkeypatch, fake)
    client = wb_app.test_client()
    resp = client.post(
        "/api/v1/projects/p-1/ontology-bindings/trustboard/delivery-link",
        headers=_tb_auth_headers(wb_app, "u-leader"),
    )
    assert resp.status_code == 200, resp.data
    assert resp.headers["Cache-Control"] == "no-store"
    assert resp.headers["Pragma"] == "no-cache"
    body = resp.get_json()
    assert body["data"]["delivery_path"] == "/ui/#/overview?d=vh-handover"
    assert "token" not in body["data"]


def test_delivery_link_route_role_gate(wb_app: Flask, monkeypatch: pytest.MonkeyPatch) -> None:
    """角色闸：fde_engineer / viewer 一律 403（签发=客户关系责任角色）。"""
    fake = FakeClient(behavior="ok")
    _create(wb_app, monkeypatch, fake)
    _patch_client(monkeypatch, fake)
    client = wb_app.test_client()
    for user_id in ("u-bo", "u-out"):
        resp = client.post(
            "/api/v1/projects/p-1/ontology-bindings/trustboard/delivery-link",
            headers=_tb_auth_headers(wb_app, user_id),
        )
        assert resp.status_code == 403, (user_id, resp.data)
