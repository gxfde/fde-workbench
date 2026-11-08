"""xdist 每 worker 隔离的纯函数钉（架构评估 P1-3）。

并行跑测的正确性全押在「每个 worker 独占一块」上：并发 worker 若共用一份
数据，每用例的 DELETE-all 清库会互删；PG 的 advisory lock 又以 database 为域，
同库多 worker 会把整场测试重新串行化（那正是本项要消除的等待）。

本模块只钉**纯函数面**（不连库、不起 worker）——三条：
1. 非 xdist 运行 ⇒ URL 原样返回（默认路径零变化）；
2. worker 库名恒以 `_test` 结尾 ⇒「只允许测试库」硬闸一字不改；
3. 同库分 schema 的退路下，advisory lock 键按 worker 分化（否则并发 worker
   仍被同一把锁串行化）。
"""
import os

from conftest import (
    _SESSION_LOCK_KEY,
    _session_lock_key,
    _worker_schema_from_url,
    _xdist_worker_index,
)

BASE_URL = "postgresql+psycopg://fde:pw@127.0.0.1:15432/fde_workbench_test"


def test_non_xdist_run_keeps_base_url(monkeypatch):
    """非 xdist 运行（默认路径）：worker 序号为 None ⇒ URL 原样。"""
    monkeypatch.delenv("PYTEST_XDIST_WORKER", raising=False)
    assert _xdist_worker_index() is None
    assert _worker_schema_from_url(BASE_URL) is None
    assert _session_lock_key(BASE_URL) == _SESSION_LOCK_KEY


def test_worker_index_parses_xdist_env(monkeypatch):
    """xdist 注入 PYTEST_XDIST_WORKER=gwN ⇒ 解析出序号 N。"""
    monkeypatch.setenv("PYTEST_XDIST_WORKER", "gw3")
    assert _xdist_worker_index() == 3
    monkeypatch.setenv("PYTEST_XDIST_WORKER", "not-a-worker")
    assert _xdist_worker_index() is None
    monkeypatch.setenv("PYTEST_XDIST_WORKER", "")
    assert _xdist_worker_index() is None


def test_worker_database_name_keeps_test_suffix(monkeypatch):
    """A 路径的 worker 库名必须以 _test 结尾（硬闸不改）。"""
    from conftest import _XDIST_DB_PREFIX, _XDIST_DB_SUFFIX

    for index in (0, 1, 7):
        name = f"{_XDIST_DB_PREFIX}{index}{_XDIST_DB_SUFFIX}"
        assert name.endswith("_test"), name
        assert name != BASE_URL.rsplit("/", 1)[-1], "worker 库不得与基础库同名"


def test_schema_path_lock_key_differs_per_worker(monkeypatch):
    """B 路径（同库分 schema）：锁键按 worker 分化，否则并发 worker 仍被串行化。"""
    schema_url = (
        BASE_URL + "?options=-c%20search_path%3Dfde_xdist_w0"
    )
    assert _worker_schema_from_url(schema_url) == "fde_xdist_w0"
    assert _session_lock_key(schema_url) != _SESSION_LOCK_KEY
    other = BASE_URL + "?options=-c%20search_path%3Dfde_xdist_w1"
    assert _session_lock_key(other) != _session_lock_key(schema_url)


def test_worker_env_is_not_leaked_into_serial_runs(monkeypatch):
    """环境里没有 PYTEST_XDIST_WORKER 时不得凭空造 worker（默认路径零变化）。"""
    monkeypatch.delenv("PYTEST_XDIST_WORKER", raising=False)
    assert os.environ.get("PYTEST_XDIST_WORKER") is None
    assert _xdist_worker_index() is None
