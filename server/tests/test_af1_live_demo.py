"""AF1-WP1 收口批：真服务失败→修正端到端演示（WP1 验收锚）。

真模型（本机 Ollama qwen3:14b，方案 B①）+ 真 ontology-service（测试内自起
uvicorn subprocess，sqlite 临时库）+ 真 dry_validate_change_set（1.3.6-af0
零状态变更预检）：候选按需求原文携带口语数据类型词（text），第一轮预检返回
真实 violations（unknown data_type 'text'），违规回灌下一轮，模型按词表修正
后复检 verdict=pass——**循环机制全真**（真 provider 工具调用、真 HTTP 校验、
真实校验错误驱动修正；S-13 spy 只记录真响应，不替换任何行为）。

运行条件（缺一即收集期跳过，CI 恒跳过）：
  1. ``FDE_AF1_LIVE_DEMO=1``；
  2. 本机 Ollama 在线（127.0.0.1:11434，qwen3:14b 已拉取）；
  3. 本机 ontology-service 源码树（默认 ``D:/test/Fde-Ontology/ontology-service``，
     可用 ``FDE_AF1_ONTOLOGY_SERVICE_ROOT`` 覆盖；用其自带 .venv 起 uvicorn）。

复现（需本机 PG 测试库，走 tests/conftest.py 既有 D14 机制）：
``FDE_AF1_LIVE_DEMO=1 python -m pytest tests/test_af1_live_demo.py -s``
"""
from __future__ import annotations

import os
import secrets
import socket
import subprocess
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import requests
from pydantic import SecretStr
from sqlalchemy.orm import Session

from fde_api.control.ai_tool_loop import direct_tool_completion
from fde_api.control.model_preferences import resolve_model_preference
from fde_api.integrations.models import ProjectOntologyBinding
from fde_api.integrations.ontology_client import OntologyClient, build_context_header
from fde_api.workbench.models import Project

from test_gates_api import admin_client, gate_project  # noqa: F401  (fixture 供给方)

# FDE_AF1_OLLAMA_BASE 可覆盖（WP5 仪器层连通性配置，2026-11-19：WSL NAT 模式
# 下 Windows→WSL localhost 转发不可用，评测运行经 WSL IP 直连本机 Ollama；
# 默认值=AF1 冻结配置不变——本行只增覆盖通道，不改任何运行语义）。
OLLAMA_BASE = os.environ.get("FDE_AF1_OLLAMA_BASE", "http://127.0.0.1:11434")
OLLAMA_MODEL = "qwen3:14b"
DEMO_ACTOR = "af1-demo-agent"
DEMO_PROJECT_REF = "af1-demo-project"

pytestmark = [
    pytest.mark.af1_live,
    pytest.mark.skipif(
        os.environ.get("FDE_AF1_LIVE_DEMO", "").strip() != "1",
        reason="requires FDE_AF1_LIVE_DEMO=1 (real Ollama + local ontology-service)",
    ),
]


def _ontology_service_root() -> Path:
    return Path(
        os.environ.get("FDE_AF1_ONTOLOGY_SERVICE_ROOT", "")
        or r"D:\test\Fde-Ontology\ontology-service"
    )


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture
def live_ontology_service(tmp_path: Path) -> Iterator[dict[str, Any]]:
    """自起 ontology-service：sqlite 临时库 + 测试随机密钥（仅环境注入，不落日志）。"""
    root = _ontology_service_root()
    venv_python = root / ".venv" / "Scripts" / "python.exe"
    assert venv_python.exists(), f"ontology-service venv missing: {venv_python}"
    api_key = secrets.token_hex(32)
    signing_key = secrets.token_hex(32)
    database_url = f"sqlite:///{(tmp_path / 'af1_live.db').as_posix()}"

    schema_script = tmp_path / "_create_schema.py"
    schema_script.write_text(
        "import sys\n"
        "from ontology_service.db import make_engine\n"
        "from ontology_service.models import Base\n"
        "Base.metadata.create_all(make_engine(sys.argv[1]))\n"
        "print('schema-ok')\n",
        encoding="utf-8",
    )
    done = subprocess.run(
        [str(venv_python), str(schema_script), database_url],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
    )
    assert "schema-ok" in done.stdout, done.stderr or done.stdout

    env = dict(os.environ)
    env.update({
        "ONTOLOGY_ENV": "dev",
        "ONTOLOGY_DATABASE_URL": database_url,
        "ONTOLOGY_API_KEY": api_key,
        "ONTOLOGY_SIGNING_KEY": signing_key,
        "ONTOLOGY_INGEST_TOKEN": "af1-live-demo-token",
    })
    # bind(0)→close→spawn 存在端口竞态窗口（xdist/他进程）；健康检查失败即换
    # 端口重试，stderr 落盘备查（评审 F3/B7：DEVNULL 会让启动失败根因不可诊断）
    server: subprocess.Popen[bytes] | None = None
    stderr_handle = None
    base_url = ""
    failure_detail = ""
    for attempt in range(3):
        stderr_path = tmp_path / f"uvicorn_stderr_{attempt}.log"
        stderr_handle = stderr_path.open("wb")
        port = _free_port()
        base_url = f"http://127.0.0.1:{port}"
        server = subprocess.Popen(
            [str(venv_python), "-m", "uvicorn", "ontology_service.app:app",
             "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"],
            cwd=tmp_path,  # 远离仓根 .env；服务配置只认显式 env
            env=env,
            stdout=subprocess.DEVNULL, stderr=stderr_handle,
        )
        healthy = False
        for _ in range(60):
            try:
                if requests.get(f"{base_url}/healthz", timeout=2).status_code == 200:
                    healthy = True
                    break
            except (requests.ConnectionError, requests.Timeout):
                time.sleep(0.5)
            else:
                time.sleep(0.5)
        if healthy:
            break
        failure_detail = stderr_path.read_text(encoding="utf-8", errors="replace")[-800:]
        server.terminate()
        try:
            server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait(timeout=5)
        server = None
        stderr_handle.close()
        stderr_handle = None
    assert server is not None and stderr_handle is not None, (
        "ontology-service 3 次尝试均未健康（端口竞态/导入失败？）——uvicorn stderr 尾部："
        + failure_detail
    )
    stderr_handle.close()
    try:
        yield {"base_url": base_url, "api_key": api_key, "signing_key": signing_key}
    finally:
        assert server is not None
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait(timeout=5)


def _seed_published_version(live: dict[str, Any], org_id: str) -> tuple[str, str]:
    """种子：建本体 → 候选（equipment 对象类型）→ validate=submit → 三审批 → 发布 1.0.0。

    返回 (ontology_id, version_id)——都取服务真身（绑定注入面 S-13 不拼格式）。
    沿 ontology-service tests/conftest.py ``full_pipeline`` 同序（全真 HTTP）。
    """
    def _post(path: str, *, actor: str, idem: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        headers = {
            "X-API-Key": live["api_key"],
            "X-FDE-Context": build_context_header(actor, org_id, DEMO_PROJECT_REF, live["signing_key"]),
            "X-Idempotency-Key": idem,
        }
        resp = requests.post(f"{live['base_url']}{path}", headers=headers, json=body, timeout=15)
        assert resp.status_code in (200, 201), f"{path}: {resp.status_code} {resp.text}"
        return resp.json()

    ontology = _post(
        "/api/v1/ontologies", actor=DEMO_ACTOR, idem="af1-demo-onto",
        body={"domain_key": "af1_live_demo", "title": "AF1 Live Demo Ontology"},
    )
    equipment_item = {
        "op": "create",
        "entity_type": "object_types",
        "entity_key": "equipment",
        "payload": {"display_name": "设备"},
    }
    change_set = _post(
        f"/api/v1/ontologies/{ontology['id']}/change-sets", actor=DEMO_ACTOR,
        idem="af1-demo-cs", body={"title": "CS af1-demo", "proposed_json": [equipment_item]},
    )
    _post(f"/api/v1/change-sets/{change_set['id']}/validate", actor=DEMO_ACTOR, idem="af1-demo-va")
    for index, (role, actor) in enumerate(
        (("business_owner", "bo-1"), ("model_consultant", "mc-1"), ("data_owner", "do-1"))
    ):
        _post(
            f"/api/v1/change-sets/{change_set['id']}/approvals", actor=actor,
            idem=f"af1-demo-ap-{index}", body={"role": role, "decision": "approved"},
        )
    published = _post(
        f"/api/v1/change-sets/{change_set['id']}/publish", actor=DEMO_ACTOR,
        idem="af1-demo-pb", body={"version": "1.0.0"},
    )
    return str(ontology["id"]), str(published["id"])


def _require_ollama() -> None:
    try:
        payload = requests.get(f"{OLLAMA_BASE}/v1/models", timeout=5).json()
    except (requests.ConnectionError, ValueError) as error:
        pytest.fail(f"FDE_AF1_LIVE_DEMO=1 但本机 Ollama 不可达（{OLLAMA_BASE}）：{error!r}")
    names = [
        str(item.get("id") or item.get("name") or "") for item in payload.get("data", [])
    ]
    assert OLLAMA_MODEL in names, f"Ollama 缺 {OLLAMA_MODEL}（现有：{names}）"


def test_live_failure_then_correction_demo(
    gate_project, live_ontology_service: dict[str, Any],
    db_session: Session, settings, app, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """轮1候选按需求原文带 text → 真服务 violations → 回灌修正 → verdict=pass。"""
    _require_ollama()
    project, _gates_url, leader = gate_project
    project_row = db_session.get(Project, project["id"])
    assert project_row is not None
    assert project_row.org_id is not None
    org_id = project_row.org_id

    # S-13：绑定行注入 ontology_id + pinned_version_id（都取服务真身）；Agent 参数面无版本
    ontology_id, version_id = _seed_published_version(live_ontology_service, org_id)
    binding = ProjectOntologyBinding(
        org_id=org_id,
        project_id=project["id"],
        ontology_id=ontology_id,
        pinned_version_id=version_id,
        pinned_version="1.0.0",
        binding_role="primary",
        status="active",
        active_marker="active",
        bound_by_user_id=leader.user.id,
    )
    db_session.add(binding)
    db_session.commit()

    # ontology 面配置钉向自起服务；自托管档钉向本机 Ollama（system-default 优先，
    # 回环地址不触 allow_public 公网冒名闸）
    monkeypatch.setattr(settings, "ontology_enabled", True, raising=False)
    monkeypatch.setattr(settings, "ontology_base_url", live_ontology_service["base_url"], raising=False)
    monkeypatch.setattr(
        settings, "ontology_api_key", SecretStr(live_ontology_service["api_key"]), raising=False)
    monkeypatch.setattr(
        settings, "ontology_signing_key", SecretStr(live_ontology_service["signing_key"]), raising=False)
    monkeypatch.setattr(settings, "ai_selfhosted_base_url", f"{OLLAMA_BASE}/v1", raising=False)
    monkeypatch.setattr(settings, "ai_selfhosted_model", OLLAMA_MODEL, raising=False)

    # S-13 spy（M4 同款）：包真方法只记录，HTTP 照发——记录里是真服务响应
    dry_calls: list[dict[str, Any]] = []
    original = OntologyClient.dry_validate_change_set

    def _spy(self: OntologyClient, **kwargs: Any) -> dict[str, Any]:
        response = original(self, **kwargs)
        dry_calls.append({"proposed_json": kwargs["proposed_json"], "response": response})
        return response

    monkeypatch.setattr(OntologyClient, "dry_validate_change_set", _spy)

    # entity_key 注入 per-run 随机后缀（评审 verification-gap①）：录放假件无法
    # 预知本 run 的实体键——防「忠实录放」假循环
    serial_key = f"equipment_serial_no_{secrets.token_hex(4)}"
    prompt = (
        "你是交付项目的本体工程助手。项目已绑定固定版本的本体，只能通过工具完成工作。\n"
        "任务（客户书面需求如下，严格按原文执行，不得改写需求给定的值）：\n"
        "需求原文要求新增属性候选：op=create、entity_type=property_definitions、"
        f"entity_key={serial_key}、显示名「设备序列号」、挂到对象类型 equipment、"
        "数据类型 text。\n"
        "重要：第一轮预检的候选必须逐字使用需求原文值（数据类型字段='text'），"
        "不得预先替换成你认为更合适的词表词；只有在预检返回 violations 之后，"
        "才允许按词表修正。\n"
        "步骤：\n"
        "1. 用 ontology_dry_validate 预检该候选（proposed_json 为候选条目数组，形状见工具说明）。\n"
        "2. 若 verdict=violations，按 violations 明细修正候选——数据类型只能从词表 "
        "string/number/boolean/date/datetime/enum/ref 中选语义最接近的一个——再次预检，直到 verdict=pass。\n"
        "3. 通过后用一两句话报告最终 verdict 与你修正了什么，不要再调用工具。\n"
        f"上下文：project_id={project['id']} binding_id={binding.id}"
    )

    with app.app_context():
        actor = leader.user
        model = resolve_model_preference(db_session, actor.id)
        assert model["id"] == "system-selfhosted", model["id"]
        text, usage, trace = direct_tool_completion(
            model=model,
            prompt=prompt,
            user=actor,
            project_id=project["id"],
            execution_id="af1-live-demo-1",
            max_tool_rounds=6,
            capabilities=["ontology.read"],
            allowed_tools=["ontology_dry_validate"],
        )

    # 真 provider 证据：usage 非空且模型钉 qwen3:14b
    assert usage["complete"] is True
    assert usage["calls"], "无 provider 记账——循环没有真正发生"
    assert usage["calls"][0]["model"] == OLLAMA_MODEL

    # 真 dry_validate 调用 ≥2 次：先违规后通过（失败→修正闭环）
    assert len(dry_calls) >= 2, f"dry_validate 调用次数不足：{len(dry_calls)}"
    first, last = dry_calls[0], dry_calls[-1]
    assert first["response"]["verdict"] == "violations", first["response"]
    assert any(
        violation["check"] == "data_type" for violation in first["response"]["violations"]
    ), first["response"]["violations"]
    assert last["response"]["verdict"] == "pass", last["response"]

    # 防录放：首轮候选必须携带本 run 随机实体键（录放假件无从预知）
    assert first["proposed_json"][0]["entity_key"] == serial_key, (
        first["proposed_json"][0]["entity_key"]
    )

    def _data_type(call: dict[str, Any]) -> Any:
        return call["proposed_json"][0]["payload"]["data_type"]

    # 修正确实发生：数据类型离开需求口语词（text），且落在合法词表
    assert _data_type(first) == "text"
    assert _data_type(last) != "text"
    assert _data_type(last) in ("string", "number", "boolean", "date", "datetime", "enum", "ref")

    # trace ≥ spy（评审 F5：网关 400 拒收轮记 trace 不记 spy，等式会误杀真修正跑）
    trace_dry = [entry for entry in trace if entry["tool"] == "ontology_dry_validate"]
    assert len(trace_dry) >= len(dry_calls) >= 2
    assert text.strip()

    # 证据输出（pytest -s 可见；不含密钥）
    print("\n[af1-live-demo] rounds(dry_validate) =", len(dry_calls))
    for index, call in enumerate(dry_calls, start=1):
        verdict = call["response"]["verdict"]
        checks = [v["check"] for v in call["response"].get("violations", [])]
        print(f"[af1-live-demo] round {index}: verdict={verdict} "
              f"data_type={_data_type(call)} checks={checks}")
    print("[af1-live-demo] final answer:", text.strip()[:200])
