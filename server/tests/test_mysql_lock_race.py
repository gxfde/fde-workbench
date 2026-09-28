import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError

from fde_api.extensions import db
from mysql_lock_race import (
    MysqlObserver,
    MysqlServerIdentity,
    ObserverInstanceMismatch,
    _assert_worker_instances,
    _kill_exact_lock_connections,
    open_mysql_observer_or_skip,
    run_mysql_lock_race,
)


class _NoKillConnection:
    def __init__(self):
        self.kill_commands: list[str] = []

    def exec_driver_sql(self, statement):
        if statement.upper().startswith("KILL "):
            self.kill_commands.append(statement)
        raise AssertionError("mismatched observers must not execute SQL cleanup")


def _identity(value: str) -> MysqlServerIdentity:
    return MysqlServerIdentity(kind="server_uuid", value=value)


def test_observer_server_uuid_mismatch_refuses_before_workers_and_kill(monkeypatch):
    """Removing the pre-start identity gate could KILL a same-numbered session elsewhere."""
    connection = _NoKillConnection()
    observer = MysqlObserver(
        connection=connection,
        identity=_identity("application-instance"),
        application_identity=_identity("application-instance"),
        connection_id=900,
        database_name="fde_workbench_test",
    )
    worker_starts: list[object] = []
    monkeypatch.setattr(
        "mysql_lock_race._read_server_identity",
        lambda _connection: _identity("observer-instance"),
    )

    with pytest.raises(ObserverInstanceMismatch, match="same MySQL instance"):
        run_mysql_lock_race(
            observer=observer,
            settings_payload={},
            request_url="/unused",
            request_headers={},
            request_payloads=({}, {}),
            process_factory=lambda *_args, **_kwargs: worker_starts.append(object()),
        )

    assert worker_starts == []
    assert connection.kill_commands == []


def test_remote_mysql_without_explicit_observer_is_an_explicit_pytest_skip(
    monkeypatch,
):
    """Falling back to local root for a remote application DB would be unsafe and mysterious."""
    monkeypatch.delenv("FDE_TEST_OBSERVER_DATABASE_URL", raising=False)
    remote_engine = create_engine(
        "mysql+pymysql://test_user:not-logged@db.example.invalid/fde_workbench_test"
    )

    try:
        with pytest.raises(pytest.skip.Exception, match="FDE_TEST_OBSERVER_DATABASE_URL"):
            with open_mysql_observer_or_skip(remote_engine):
                raise AssertionError("an unavailable observer must skip before yielding")
    finally:
        remote_engine.dispose()


def test_kill_rechecks_server_identity_before_executing_any_command(monkeypatch):
    """Losing the observer connection must not reconnect to another server and reuse IDs."""
    connection = _NoKillConnection()
    observer = MysqlObserver(
        connection=connection,
        identity=_identity("expected-instance"),
        application_identity=_identity("expected-instance"),
        connection_id=900,
        database_name="fde_workbench_test",
    )
    monkeypatch.setattr(
        "mysql_lock_race._read_server_identity",
        lambda _connection: _identity("replacement-instance"),
    )

    with pytest.raises(ObserverInstanceMismatch, match="same MySQL instance"):
        _kill_exact_lock_connections(observer, {101, 102}, "CONNECTION")

    assert connection.kill_commands == []


def test_captured_worker_connections_must_report_the_observer_server_uuid():
    """A DNS or endpoint switch after the initial probe must disable observer KILL."""
    with pytest.raises(ObserverInstanceMismatch, match="worker connections"):
        _assert_worker_instances(
            _identity("application-instance"),
            {
                "first": _identity("application-instance"),
                "second": _identity("replacement-instance"),
            },
        )


@pytest.mark.mysql_observer
def test_observer_context_does_not_hide_scenario_sql_errors_as_prerequisite_skips(app):
    """Only observer acquisition failures are prerequisites; scenario faults must fail."""
    with app.app_context():
        with pytest.raises(SQLAlchemyError, match="injected scenario SQL failure"):
            with open_mysql_observer_or_skip(db.engine):
                raise SQLAlchemyError("injected scenario SQL failure")
