"""goal-d4 共享测试基建：假沙箱后端/事件源/产物扫描 + 受控时钟 + d4 app 夹具。

被各 test_agent_*.py 以 fixture 再导出方式复用（沿 leader_client 惯例）。
CI 无 docker/真实 zcode CLI——全部断言落在可注入事实层（技术文档 §10）。
"""
from __future__ import annotations

from base64 import urlsafe_b64encode
from dataclasses import dataclass
from hashlib import sha256
from typing import Any
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet

from test_document_drafts_api import _persist_project

from fde_api.agents.adapter import ArtifactFile
from fde_api.agents.models import AgentCredential, AgentRegistry
from fde_api.agents.sandbox import SandboxError
from fde_api.app import create_app
from fde_api.auth.models import User
from fde_api.auth.passwords import hash_password
from fde_api.auth.tokens import issue_access_token
from conftest import INITIAL_PASSWORD


class RecordingBackend:
    """捕获 argv/env 的假后端；fail 非 None 时模拟沙箱故障（A-1 场景）。"""

    def __init__(self, *, fail: str | None = None) -> None:
        self.calls: list[tuple[list[str], dict[str, str] | None]] = []
        self.fail = fail

    def run(self, argv, *, env=None) -> None:
        self.calls.append((list(argv), dict(env) if env is not None else None))
        if self.fail:
            raise SandboxError(self.fail)

    @property
    def argvs(self) -> list[list[str]]:
        return [argv for argv, _ in self.calls]


class ScriptedEvents:
    """按 poll 次数放事件批次；脚本耗尽后恒返空（配合受控时钟走向超时）。"""

    def __init__(self, script) -> None:
        self.script = [list(batch) for batch in script]
        self.polls = 0

    def poll(self):
        if self.polls < len(self.script):
            batch = self.script[self.polls]
            self.polls += 1
            return batch
        return []


class FakeScanner:
    def __init__(self, artifacts) -> None:
        self.artifacts = list(artifacts)

    def scan(self):
        return list(self.artifacts)


class FakeClock:
    """受控单调时钟：sleep 即推进——适配器监听段的确定性时序。"""

    def __init__(self, start: float = 0.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


@dataclass(frozen=True)
class ApiClient:
    client: Any
    user: User
    headers: dict

    def get(self, *args, **kwargs):
        return self.client.get(*args, headers=self.headers, **kwargs)

    def post(self, *args, **kwargs):
        return self.client.post(*args, headers=self.headers, **kwargs)

    def patch(self, *args, **kwargs):
        return self.client.patch(*args, headers=self.headers, **kwargs)


def encrypt_credential(settings, value: str) -> str:
    """与 service._decrypt_credential 同源派生（jwt_secret → Fernet key）。"""
    key = urlsafe_b64encode(sha256(settings.jwt_secret.encode()).digest())
    return Fernet(key).encrypt(value.encode()).decode()


def make_user(db_session, role: str) -> User:
    user = User(
        username=f"d4.{role}.{uuid4().hex}",
        display_name=role,
        role=role,
        password_hash=hash_password(INITIAL_PASSWORD),
        must_change_password=False,
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    return user


def api_client(d4_client, db_session, d4_settings, role: str) -> ApiClient:
    user = make_user(db_session, role)
    return ApiClient(d4_client, user, {"Authorization": f"Bearer {issue_access_token(user, d4_settings)}"})


def seed_agent(
    db_session,
    settings,
    *,
    kind: str = "zcode",
    name: str = "ZCode 沙箱智能体",
    enabled: bool = True,
    capability: str = "agent.code.write",
    allowed_tools=("read_file",),
    credential_ref: str | None = "zcode-prod",
    max_cost_units: int = 0,
    max_duration_ms: int = 0,
    sandbox_profile: str = "default",
) -> AgentRegistry:
    if credential_ref:
        db_session.add(
            AgentCredential(
                name=credential_ref,
                credential_ciphertext=encrypt_credential(settings, "zkey-1234567890"),
            )
        )
    registry = AgentRegistry(
        kind=kind,
        name=name,
        enabled=enabled,
        capability_tier=capability,
        sandbox_profile=sandbox_profile,
        credential_ref=credential_ref,
        allowed_tools=list(allowed_tools),
        max_cost_units=max_cost_units,
        max_duration_ms=max_duration_ms,
    )
    db_session.add(registry)
    db_session.commit()
    return registry


def prime_run(
    d4_app,
    *,
    backend: RecordingBackend | None = None,
    events: ScriptedEvents | None = None,
    artifacts=(),
    clock: FakeClock | None = None,
    scanner_factory=None,
) -> RecordingBackend:
    """按注注入点装好一次 run 的全部假件；返回后端供 argv 断言。

    事件工厂每次 run 产出全新 ScriptedEvents（同一脚本克隆）——run/重试链
    各拿各的事件流，绝不共享耗尽状态（否则第二个 run 会真实空转到超时）。
    """
    resolved_backend = backend or RecordingBackend()
    d4_app.extensions["fde_agent_sandbox_backend"] = resolved_backend
    script = events.script if events is not None else [[{"type": "done", "exit_code": 0}]]
    d4_app.extensions["fde_agent_event_provider_factory"] = lambda run_id, workspace: ScriptedEvents(script)
    if scanner_factory is not None:
        d4_app.extensions["fde_agent_output_scanner_factory"] = scanner_factory
    else:
        d4_app.extensions["fde_agent_output_scanner_factory"] = lambda run_id, workspace: FakeScanner(artifacts)
    if clock is not None:
        d4_app.extensions["fde_agent_clock"] = clock
        d4_app.extensions["fde_agent_sleeper"] = clock.sleep
    return resolved_backend


def artifact_file(path: str, kind: str = "doc", refs=("ref-1",)) -> ArtifactFile:
    return ArtifactFile(path=path, kind=kind, source_refs=tuple(refs))


# d4 专属 app/client：快速退避（0 秒）+ workspace 根落 tmp_path
@pytest.fixture
def d4_settings(test_settings, tmp_path):
    return test_settings.model_copy(
        update={
            "local_storage_root": tmp_path / "object-storage",
            "agent_retry_backoff_base_seconds": 0,
            "agent_workspace_root": str(tmp_path / "agent-workspaces"),
            "transcript_draft_root": tmp_path / "transcript-drafts",
        }
    )


@pytest.fixture
def d4_app(d4_settings):
    app = create_app(d4_settings)
    app.config.update(TESTING=True)
    return app


@pytest.fixture
def d4_client(d4_app):
    return d4_app.test_client()
