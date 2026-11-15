"""resolve_test_database_url 的安全契约单测：拒绝分支逐条钉死。

goal prompt §0.6 的隔离契约过去只靠「跑起来没炸」间接验证；评审会
（docs/goal-audit-2026-10-26.md §6 P2-5）指出远端 *_test 主机不拦是理论
弱点——这里把 driver / 库名 / 主机三类拒绝和回环接受全部变成直接断言。
"""
from __future__ import annotations

from pathlib import Path

import pytest

import conftest
from conftest import resolve_test_database_url


def _resolve(monkeypatch: pytest.MonkeyPatch, url: str) -> str:
    monkeypatch.delenv("FDE_TEST_DATABASE_URL", raising=False)
    monkeypatch.setenv("FDE_TEST_DATABASE_URL", url)
    return resolve_test_database_url()


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+psycopg://fde:pw@127.0.0.1:15432/fde_workbench_test",
        "postgresql+psycopg://fde:pw@localhost:15432/fde_workbench_test",
        "postgresql+psycopg://fde:pw@[::1]:15432/fde_workbench_test",
    ],
)
def test_accepts_loopback_hosts(monkeypatch: pytest.MonkeyPatch, url: str) -> None:
    assert _resolve(monkeypatch, url) == url


def test_rejects_remote_host_even_with_test_suffix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(RuntimeError, match="loopback"):
        _resolve(
            monkeypatch,
            "postgresql+psycopg://fde:pw@db.internal.example.com:5432/fde_workbench_test",
        )


def test_rejects_public_ip_host(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(RuntimeError, match="loopback"):
        _resolve(
            monkeypatch,
            "postgresql+psycopg://fde:pw@203.0.113.7:5432/fde_workbench_test",
        )


def test_rejects_missing_host(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(RuntimeError, match="loopback"):
        _resolve(monkeypatch, "postgresql+psycopg:///fde_workbench_test")


def test_rejects_non_psycopg_driver(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(RuntimeError, match="driver"):
        _resolve(
            monkeypatch,
            "postgresql+psycopg2://fde:pw@127.0.0.1:15432/fde_workbench_test",
        )


def test_rejects_forbidden_development_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(RuntimeError, match="dedicated"):
        _resolve(
            monkeypatch,
            "postgresql+psycopg://fde:pw@127.0.0.1:15432/fde_workbench",
        )


def test_rejects_twenty_database(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(RuntimeError, match="dedicated"):
        _resolve(monkeypatch, "postgresql+psycopg://twenty:pw@127.0.0.1:15432/twenty")


# ---------------------------------------------------------------------------
# D14：仓根 .env 可钉住本仓专属测试库（worktree 与主线互不踩 schema）
# ---------------------------------------------------------------------------


def _write_env_file(root: Path, body: str) -> Path:
    server_root = root / "server"
    server_root.mkdir(exist_ok=True)
    (root / ".env").write_text(body, encoding="utf-8")
    return server_root


def test_env_file_database_name_selects_worktree_private_database(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """.env 的 FDE_TEST_DATABASE_NAME 生效：库名不再是共享的 fde_workbench_test。"""
    server_root = _write_env_file(
        tmp_path,
        "FDE_DB_PASSWORD=pw\nFDE_TEST_DATABASE_NAME=fde_workbench_v33m2_test\n",
    )
    monkeypatch.setattr(conftest, "SERVER_ROOT", server_root)
    monkeypatch.delenv("FDE_TEST_DATABASE_URL", raising=False)

    url = resolve_test_database_url()

    assert url.endswith("/fde_workbench_v33m2_test")
    assert "postgresql+psycopg://" in url


def test_env_file_database_name_defaults_to_shared_database(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """.env 未钉库名时行为不变（仍回落 fde_workbench_test）。"""
    server_root = _write_env_file(tmp_path, "FDE_DB_PASSWORD=pw\n")
    monkeypatch.setattr(conftest, "SERVER_ROOT", server_root)
    monkeypatch.delenv("FDE_TEST_DATABASE_URL", raising=False)

    assert resolve_test_database_url().endswith("/fde_workbench_test")


def test_process_env_wins_over_env_file_database_name(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """进程环境优先于 .env（CI 用 FDE_TEST_DATABASE_URL 覆盖本地默认值）。"""
    server_root = _write_env_file(
        tmp_path,
        "FDE_DB_PASSWORD=pw\nFDE_TEST_DATABASE_NAME=fde_workbench_v33m2_test\n",
    )
    monkeypatch.setattr(conftest, "SERVER_ROOT", server_root)
    monkeypatch.setenv(
        "FDE_TEST_DATABASE_URL",
        "postgresql+psycopg://fde:pw@127.0.0.1:15432/fde_workbench_ci_test",
    )

    assert resolve_test_database_url().endswith("/fde_workbench_ci_test")
