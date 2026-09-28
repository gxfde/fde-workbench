from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, field
from multiprocessing import get_context
import os
from pathlib import Path
import stat
from threading import Event, Lock, local
from time import monotonic
from typing import Any, Callable, Iterator

import pytest
from sqlalchemy import URL, create_engine, text
from sqlalchemy.exc import SQLAlchemyError


_OBSERVER_SKIP_MESSAGE = (
    "privileged MySQL observer unavailable; set "
    "FDE_TEST_OBSERVER_DATABASE_URL to a same-instance test-only observer"
)
_TEST_DATABASE_NAME = "fde_workbench_test"
_LOCAL_MYSQL_HOSTS = {None, "localhost", "127.0.0.1", "::1"}


class ObserverPrerequisiteUnavailable(RuntimeError):
    pass


class ObserverInstanceMismatch(AssertionError):
    pass


class MysqlLockRaceTimeout(AssertionError):
    pass


class MysqlLockRaceChildError(AssertionError):
    pass


@dataclass(frozen=True)
class MysqlServerIdentity:
    kind: str
    value: str


@dataclass
class MysqlObserver:
    connection: Any
    identity: MysqlServerIdentity
    application_identity: MysqlServerIdentity
    connection_id: int
    database_name: str
    application_principal: str = ""
    observer_principal: str = ""


@dataclass
class RaceDiagnostics:
    tracked_connection_ids: set[int] = field(default_factory=set)
    lock_connection_ids: dict[str, int] = field(default_factory=dict)
    worker_identities: dict[str, MysqlServerIdentity] = field(default_factory=dict)
    worker_instances_verified: bool = False
    kill_commands: list[tuple[str, int]] = field(default_factory=list)
    child_pid: int | None = None
    child_exitcode: int | None = None
    hard_terminated: bool = False


@dataclass(frozen=True)
class TrackedMysqlState:
    active_transactions: tuple[int, ...]
    lock_wait_count: int


@dataclass(frozen=True)
class MysqlLockRaceResult:
    responses: tuple[tuple[int, dict[str, Any]], tuple[int, dict[str, Any]]]
    lock_wait_evidence: dict[str, Any]
    lock_connection_ids: dict[str, int]


_OBSERVED_LOCK_WAIT = text(
    """
    SELECT
        requesting_thread.PROCESSLIST_ID AS requesting_connection_id,
        blocking_thread.PROCESSLIST_ID AS blocking_connection_id,
        lock_wait.REQUESTING_ENGINE_TRANSACTION_ID AS requesting_transaction_id,
        lock_wait.BLOCKING_ENGINE_TRANSACTION_ID AS blocking_transaction_id,
        requesting_lock.OBJECT_SCHEMA AS object_schema,
        requesting_lock.OBJECT_NAME AS object_name,
        requesting_lock.LOCK_STATUS AS requesting_lock_status,
        blocking_lock.LOCK_STATUS AS blocking_lock_status
    FROM performance_schema.data_lock_waits AS lock_wait
    JOIN performance_schema.data_locks AS requesting_lock
      ON requesting_lock.ENGINE = lock_wait.ENGINE
     AND requesting_lock.ENGINE_LOCK_ID = lock_wait.REQUESTING_ENGINE_LOCK_ID
    JOIN performance_schema.data_locks AS blocking_lock
      ON blocking_lock.ENGINE = lock_wait.ENGINE
     AND blocking_lock.ENGINE_LOCK_ID = lock_wait.BLOCKING_ENGINE_LOCK_ID
    JOIN performance_schema.threads AS requesting_thread
      ON requesting_thread.THREAD_ID = lock_wait.REQUESTING_THREAD_ID
    JOIN performance_schema.threads AS blocking_thread
      ON blocking_thread.THREAD_ID = lock_wait.BLOCKING_THREAD_ID
    WHERE requesting_thread.PROCESSLIST_ID = :second_connection_id
      AND blocking_thread.PROCESSLIST_ID = :first_connection_id
      AND requesting_lock.OBJECT_SCHEMA = :database_name
      AND requesting_lock.OBJECT_NAME = 'projects'
      AND blocking_lock.OBJECT_SCHEMA = :database_name
      AND blocking_lock.OBJECT_NAME = 'projects'
      AND requesting_lock.LOCK_STATUS = 'WAITING'
      AND blocking_lock.LOCK_STATUS = 'GRANTED'
    """
)


def _mysql_error_code(error: SQLAlchemyError) -> int | None:
    original = getattr(error, "orig", None)
    arguments = getattr(original, "args", ())
    return arguments[0] if arguments else None


def _read_server_identity(connection) -> MysqlServerIdentity:
    try:
        server_uuid = connection.scalar(text("SELECT @@server_uuid"))
    except SQLAlchemyError as error:
        if _mysql_error_code(error) != 1193:
            raise
    else:
        if server_uuid:
            return MysqlServerIdentity("server_uuid", str(server_uuid))

    server_id, hostname, port = connection.execute(
        text("SELECT @@server_id, @@hostname, @@port")
    ).one()
    return MysqlServerIdentity(
        "server_location", f"{server_id}|{hostname}|{int(port)}"
    )


def _assert_same_instance(
    application_identity: MysqlServerIdentity,
    observer_identity: MysqlServerIdentity,
) -> None:
    if application_identity != observer_identity:
        raise ObserverInstanceMismatch(
            "observer and application must use the same MySQL instance"
        )


def _assert_worker_instances(
    application_identity: MysqlServerIdentity,
    worker_identities: dict[str, MysqlServerIdentity],
) -> None:
    if set(worker_identities) != {"first", "second"} or any(
        identity != application_identity for identity in worker_identities.values()
    ):
        raise ObserverInstanceMismatch(
            "captured worker connections must use the same MySQL instance"
        )


def _has_named_privilege(grants: list[str], privilege: str) -> bool:
    return any(
        "ALL PRIVILEGES ON *.*" in grant or privilege in grant
        for grant in grants
    )


def _probe_observer_privileges(
    connection,
    *,
    database_name: str,
    application_principal: str,
    observer_principal: str,
) -> None:
    try:
        connection.execute(
            _OBSERVED_LOCK_WAIT,
            {
                "first_connection_id": 0,
                "second_connection_id": 0,
                "database_name": database_name,
            },
        ).first()
        connection.execute(
            text(
                "SELECT trx_mysql_thread_id "
                "FROM information_schema.innodb_trx LIMIT 1"
            )
        ).first()
        grants = [
            str(row[0]).upper()
            for row in connection.execute(text("SHOW GRANTS FOR CURRENT_USER"))
        ]
    except SQLAlchemyError:
        raise ObserverPrerequisiteUnavailable(_OBSERVER_SKIP_MESSAGE) from None

    can_inspect_transactions = _has_named_privilege(grants, "PROCESS")
    can_kill_workers = (
        application_principal == observer_principal
        or _has_named_privilege(grants, "CONNECTION_ADMIN")
        or _has_named_privilege(grants, "SUPER")
    )
    if not can_inspect_transactions or not can_kill_workers:
        raise ObserverPrerequisiteUnavailable(_OBSERVER_SKIP_MESSAGE)


@contextmanager
def open_mysql_observer(application_engine) -> Iterator[MysqlObserver]:
    if application_engine.dialect.name != "mysql":
        raise ObserverPrerequisiteUnavailable(_OBSERVER_SKIP_MESSAGE)

    observer_url = os.environ.get("FDE_TEST_OBSERVER_DATABASE_URL")
    if not observer_url and application_engine.url.host not in _LOCAL_MYSQL_HOSTS:
        raise ObserverPrerequisiteUnavailable(_OBSERVER_SKIP_MESSAGE)

    observer_engine = None
    observer_connection = None

    def close_observer_resources() -> None:
        if observer_connection is not None:
            try:
                observer_connection.close()
            except SQLAlchemyError:
                pass
        if observer_engine is not None:
            observer_engine.dispose()

    try:
        with application_engine.connect() as application_connection:
            database_name, socket_path, application_principal = (
                application_connection.execute(
                    text("SELECT DATABASE(), @@socket, CURRENT_USER()")
                ).one()
            )
            application_identity = _read_server_identity(application_connection)

        if database_name != _TEST_DATABASE_NAME:
            raise ObserverPrerequisiteUnavailable(_OBSERVER_SKIP_MESSAGE)

        if observer_url:
            observer_target = observer_url
        else:
            socket = Path(str(socket_path))
            try:
                is_local_socket = socket.is_absolute() and stat.S_ISSOCK(
                    socket.stat().st_mode
                )
            except OSError:
                is_local_socket = False
            if not is_local_socket:
                raise ObserverPrerequisiteUnavailable(_OBSERVER_SKIP_MESSAGE)
            observer_target = URL.create(
                "mysql+pymysql",
                username="root",
                database=database_name,
                query={"unix_socket": str(socket)},
            )

        observer_engine = create_engine(
            observer_target,
            pool_pre_ping=True,
            connect_args={"connect_timeout": 3, "read_timeout": 3, "write_timeout": 3},
        )
        observer_connection = observer_engine.connect().execution_options(
            isolation_level="AUTOCOMMIT"
        )
        observer_identity = _read_server_identity(observer_connection)
        _assert_same_instance(application_identity, observer_identity)
        observer_connection_id, observer_principal = observer_connection.execute(
            text("SELECT CONNECTION_ID(), CURRENT_USER()")
        ).one()
        _probe_observer_privileges(
            observer_connection,
            database_name=database_name,
            application_principal=str(application_principal),
            observer_principal=str(observer_principal),
        )
        observer = MysqlObserver(
            connection=observer_connection,
            identity=observer_identity,
            application_identity=application_identity,
            connection_id=int(observer_connection_id),
            database_name=str(database_name),
            application_principal=str(application_principal),
            observer_principal=str(observer_principal),
        )
    except (ObserverPrerequisiteUnavailable, ObserverInstanceMismatch):
        close_observer_resources()
        raise
    except SQLAlchemyError:
        close_observer_resources()
        raise ObserverPrerequisiteUnavailable(_OBSERVER_SKIP_MESSAGE) from None

    try:
        yield observer
    finally:
        close_observer_resources()


@contextmanager
def open_mysql_observer_or_skip(application_engine) -> Iterator[MysqlObserver]:
    stack = ExitStack()
    try:
        observer = stack.enter_context(open_mysql_observer(application_engine))
    except ObserverPrerequisiteUnavailable:
        stack.close()
        pytest.skip(_OBSERVER_SKIP_MESSAGE)
    with stack:
        yield observer


def _connection_id_parameters(connection_ids: set[int]):
    ordered_ids = sorted(int(connection_id) for connection_id in connection_ids)
    placeholders = ", ".join(
        f":connection_id_{index}" for index, _ in enumerate(ordered_ids)
    )
    parameters = {
        f"connection_id_{index}": connection_id
        for index, connection_id in enumerate(ordered_ids)
    }
    return ordered_ids, placeholders, parameters


def tracked_mysql_state(
    observer: MysqlObserver, connection_ids: set[int]
) -> TrackedMysqlState:
    if not connection_ids:
        return TrackedMysqlState((), 0)
    _, placeholders, parameters = _connection_id_parameters(connection_ids)
    transactions = tuple(
        sorted(
            int(connection_id)
            for connection_id in observer.connection.scalars(
                text(
                    "SELECT trx_mysql_thread_id FROM information_schema.innodb_trx "
                    f"WHERE trx_mysql_thread_id IN ({placeholders})"
                ),
                parameters,
            )
        )
    )
    lock_parameters = dict(parameters)
    lock_parameters["database_name"] = observer.database_name
    lock_wait_count = int(
        observer.connection.scalar(
            text(
                "SELECT COUNT(*) "
                "FROM performance_schema.data_lock_waits AS lock_wait "
                "JOIN performance_schema.data_locks AS requesting_lock "
                "  ON requesting_lock.ENGINE = lock_wait.ENGINE "
                " AND requesting_lock.ENGINE_LOCK_ID = lock_wait.REQUESTING_ENGINE_LOCK_ID "
                "JOIN performance_schema.data_locks AS blocking_lock "
                "  ON blocking_lock.ENGINE = lock_wait.ENGINE "
                " AND blocking_lock.ENGINE_LOCK_ID = lock_wait.BLOCKING_ENGINE_LOCK_ID "
                "JOIN performance_schema.threads AS requesting_thread "
                "  ON requesting_thread.THREAD_ID = lock_wait.REQUESTING_THREAD_ID "
                "JOIN performance_schema.threads AS blocking_thread "
                "  ON blocking_thread.THREAD_ID = lock_wait.BLOCKING_THREAD_ID "
                f"WHERE (requesting_thread.PROCESSLIST_ID IN ({placeholders}) "
                f"    OR blocking_thread.PROCESSLIST_ID IN ({placeholders})) "
                "  AND requesting_lock.OBJECT_SCHEMA = :database_name "
                "  AND requesting_lock.OBJECT_NAME = 'projects' "
                "  AND blocking_lock.OBJECT_SCHEMA = :database_name "
                "  AND blocking_lock.OBJECT_NAME = 'projects'"
            ),
            lock_parameters,
        )
        or 0
    )
    return TrackedMysqlState(transactions, lock_wait_count)


def _wait_for_no_tracked_mysql_state(
    observer: MysqlObserver, connection_ids: set[int], timeout: float
) -> None:
    _assert_same_instance(
        observer.application_identity, _read_server_identity(observer.connection)
    )
    deadline = monotonic() + timeout
    poll_event = Event()
    while True:
        state = tracked_mysql_state(observer, connection_ids)
        if not state.active_transactions and state.lock_wait_count == 0:
            return
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise AssertionError(
                "tracked worker transactions or lock waits remained after cleanup"
            )
        poll_event.wait(timeout=min(0.02, remaining))


def _exact_active_lock_connections(
    observer: MysqlObserver, connection_ids: set[int]
) -> set[int]:
    if not connection_ids:
        return set()
    _, placeholders, parameters = _connection_id_parameters(connection_ids)
    parameters["database_name"] = observer.database_name
    return {
        int(connection_id)
        for connection_id in observer.connection.scalars(
            text(
                "SELECT DISTINCT worker_thread.PROCESSLIST_ID "
                "FROM performance_schema.data_locks AS worker_lock "
                "JOIN performance_schema.threads AS worker_thread "
                "  ON worker_thread.THREAD_ID = worker_lock.THREAD_ID "
                "JOIN information_schema.innodb_trx AS worker_trx "
                "  ON worker_trx.trx_mysql_thread_id = worker_thread.PROCESSLIST_ID "
                f"WHERE worker_thread.PROCESSLIST_ID IN ({placeholders}) "
                "  AND worker_lock.OBJECT_SCHEMA = :database_name "
                "  AND worker_lock.OBJECT_NAME = 'projects'"
            ),
            parameters,
        )
    }


def _kill_exact_lock_connections(
    observer: MysqlObserver, connection_ids: set[int], kind: str
) -> tuple[int, ...]:
    if kind not in {"QUERY", "CONNECTION"}:
        raise ValueError("unsupported MySQL KILL kind")
    current_identity = _read_server_identity(observer.connection)
    _assert_same_instance(observer.application_identity, current_identity)
    if observer.connection_id in connection_ids:
        raise AssertionError("observer connection was tracked as a test worker")

    errors = []
    attempted_connection_ids = tuple(
        sorted(_exact_active_lock_connections(observer, connection_ids))
    )
    for connection_id in attempted_connection_ids:
        try:
            observer.connection.exec_driver_sql(
                f"KILL {kind} {int(connection_id)}"
            )
        except SQLAlchemyError as error:
            if _mysql_error_code(error) != 1094:
                errors.append(
                    RuntimeError(
                        f"KILL {kind} failed for tracked test worker {connection_id}"
                    )
                )
    if errors:
        raise ExceptionGroup(f"one or more KILL {kind} commands failed", errors)
    return attempted_connection_ids


def _kill_and_record(
    observer: MysqlObserver,
    connection_ids: set[int],
    kind: str,
    diagnostics: RaceDiagnostics,
) -> None:
    attempted_connection_ids = _kill_exact_lock_connections(
        observer, connection_ids, kind
    )
    diagnostics.kill_commands.extend(
        (kind, connection_id) for connection_id in attempted_connection_ids
    )


def _send_child_message(sender, guard: Lock, message: tuple[Any, ...]) -> None:
    with guard:
        sender.send(message)


def _run_lock_race_child(
    status_sender,
    control_receiver,
    settings_payload: dict[str, Any],
    request_url: str,
    request_headers: dict[str, str],
    request_payloads: tuple[dict[str, Any], dict[str, Any]],
    request_method: str,
    lock_target: str,
    force_child_hang: bool,
) -> None:
    from fde_api.app import create_app
    from fde_api.config import Settings
    from fde_api.extensions import db
    from fde_api.research import form_service, subject_service

    release_first_lock = Event()
    first_lock_acquired = Event()
    worker_state = local()
    send_guard = Lock()
    executor = None
    app = None
    lock_module, lock_attribute = {
        "subject_project": (subject_service, "_lock_project"),
        "form_project": (form_service, "_load_project"),
    }[lock_target]
    real_lock_project = getattr(lock_module, lock_attribute)

    def send(message: tuple[Any, ...]) -> None:
        _send_child_message(status_sender, send_guard, message)

    def coordinated_lock(*args, **kwargs):
        role = worker_state.role
        connection_id = int(args[0].scalar(text("SELECT CONNECTION_ID()")))
        worker_identity = _read_server_identity(args[0])
        send(
            (
                "lock_connection_id",
                role,
                connection_id,
                worker_identity.kind,
                worker_identity.value,
            )
        )
        if role == "first":
            locked_project = real_lock_project(*args, **kwargs)
            first_lock_acquired.set()
            send(("first_lock_acquired",))
            if not release_first_lock.wait(timeout=30):
                raise AssertionError("parent did not release the first project lock")
            return locked_project
        if role == "second":
            if not first_lock_acquired.wait(timeout=10):
                raise AssertionError("first worker did not acquire the project row lock")
            args[0].execute(text("SET SESSION innodb_lock_wait_timeout = 10"))
            return real_lock_project(*args, **kwargs)
        raise AssertionError("concurrent worker did not declare a lock role")

    def create_in_independent_request(role: str, payload: dict[str, Any]):
        worker_state.role = role
        try:
            with app.app_context():
                response = app.test_client().open(
                    request_url,
                    method=request_method,
                    json=payload,
                    headers=request_headers,
                )
                return response.status_code, response.json
        finally:
            del worker_state.role

    try:
        app = create_app(Settings(**settings_payload))
        app.config.update(TESTING=True)
        setattr(lock_module, lock_attribute, coordinated_lock)
        executor = ThreadPoolExecutor(max_workers=2)
        futures = (
            executor.submit(create_in_independent_request, "first", request_payloads[0]),
            executor.submit(create_in_independent_request, "second", request_payloads[1]),
        )
        if force_child_hang:
            Event().wait()
        command = control_receiver.recv()
        if command != "release":
            raise AssertionError("parent sent an invalid lock-race command")
        release_first_lock.set()
        responses = tuple(future.result(timeout=15) for future in futures)
        send(("responses", responses))
    except BaseException as error:
        try:
            send(("child_error", type(error).__name__))
        except BaseException:
            pass
    finally:
        release_first_lock.set()
        if executor is not None:
            executor.shutdown(wait=True, cancel_futures=True)
        setattr(lock_module, lock_attribute, real_lock_project)
        if app is not None:
            with app.app_context():
                db.engine.dispose()
        status_sender.close()
        control_receiver.close()


def _wait_for_child_handshake(
    process,
    status_receiver,
    diagnostics: RaceDiagnostics,
    timeout: float,
) -> None:
    deadline = monotonic() + timeout
    first_lock_acquired = False
    while len(diagnostics.tracked_connection_ids) < 2 or not first_lock_acquired:
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise MysqlLockRaceTimeout(
                "lock-race child did not expose both worker connections in time"
            )
        if status_receiver.poll(min(0.05, remaining)):
            message = status_receiver.recv()
            if message[0] == "lock_connection_id":
                role = str(message[1])
                connection_id = int(message[2])
                diagnostics.lock_connection_ids[role] = connection_id
                diagnostics.tracked_connection_ids.add(connection_id)
                diagnostics.worker_identities[role] = MysqlServerIdentity(
                    kind=str(message[3]), value=str(message[4])
                )
            elif message[0] == "first_lock_acquired":
                first_lock_acquired = True
            elif message[0] == "child_error":
                raise MysqlLockRaceChildError(
                    f"lock-race child failed with {message[1]}"
                )
        elif not process.is_alive():
            raise MysqlLockRaceChildError("lock-race child exited before the handshake")


def _wait_for_observed_lock_wait(
    observer: MysqlObserver,
    connection_ids: dict[str, int],
    timeout: float,
) -> dict[str, Any]:
    if set(connection_ids) != {"first", "second"}:
        raise AssertionError("the lock race must expose first and second worker connections")
    deadline = monotonic() + timeout
    poll_event = Event()
    while True:
        candidates = observer.connection.execute(
            _OBSERVED_LOCK_WAIT,
            {
                "first_connection_id": connection_ids["first"],
                "second_connection_id": connection_ids["second"],
                "database_name": observer.database_name,
            },
        ).mappings().first()
        if candidates is not None:
            return dict(candidates)
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise AssertionError(
                "observer did not find the second worker waiting on the first worker's "
                "projects row lock"
            )
        poll_event.wait(timeout=min(0.02, remaining))


def _wait_for_child_responses(process, status_receiver, timeout: float):
    deadline = monotonic() + timeout
    while True:
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise MysqlLockRaceTimeout(
                "lock-race child did not finish within the hard timeout"
            )
        if status_receiver.poll(min(0.05, remaining)):
            message = status_receiver.recv()
            if message[0] == "responses":
                return tuple(message[1])
            if message[0] == "child_error":
                raise MysqlLockRaceChildError(
                    f"lock-race child failed with {message[1]}"
                )
        elif not process.is_alive():
            raise MysqlLockRaceChildError("lock-race child exited without responses")


def _record_cleanup_error(errors: list[BaseException], operation: Callable[[], None]):
    try:
        operation()
    except BaseException as error:
        errors.append(error)


def _process_is_alive(process, errors: list[BaseException]) -> bool:
    try:
        return bool(process.is_alive())
    except BaseException as error:
        errors.append(error)
        return True


def _raise_primary_and_cleanup_errors(
    primary_error: BaseException | None,
    cleanup_errors: list[BaseException],
) -> None:
    if primary_error is not None and cleanup_errors:
        raise BaseExceptionGroup(
            "lock-race assertion and cleanup both failed",
            [primary_error, *cleanup_errors],
        )
    if primary_error is not None:
        raise primary_error
    if len(cleanup_errors) == 1:
        raise cleanup_errors[0]
    if cleanup_errors:
        raise BaseExceptionGroup("lock-race cleanup failed", cleanup_errors)


def run_mysql_lock_race(
    *,
    observer: MysqlObserver,
    settings_payload: dict[str, Any],
    request_url: str,
    request_headers: dict[str, str],
    request_payloads: tuple[dict[str, Any], dict[str, Any]],
    request_method: str = "POST",
    lock_target: str = "subject_project",
    process_factory: Callable[..., Any] | None = None,
    diagnostics: RaceDiagnostics | None = None,
    process_timeout: float = 12,
    force_child_hang: bool = False,
) -> MysqlLockRaceResult:
    request_method = request_method.upper()
    if request_method not in {"POST", "PATCH"}:
        raise ValueError("unsupported lock-race request method")
    if lock_target not in {"subject_project", "form_project"}:
        raise ValueError("unsupported lock-race target")
    _assert_same_instance(observer.application_identity, observer.identity)
    _assert_same_instance(
        observer.application_identity, _read_server_identity(observer.connection)
    )
    diagnostics = diagnostics or RaceDiagnostics()
    context = get_context("spawn")
    status_receiver, status_sender = context.Pipe(duplex=False)
    control_receiver, control_sender = context.Pipe(duplex=False)
    factory = process_factory or context.Process
    process = factory(
        target=_run_lock_race_child,
        args=(
            status_sender,
            control_receiver,
            settings_payload,
            request_url,
            request_headers,
            request_payloads,
            request_method,
            lock_target,
            force_child_hang,
        ),
        name="fde-mysql-lock-race",
    )
    primary_error = None
    cleanup_errors: list[BaseException] = []
    race_result = None
    process_started = False

    try:
        process.start()
        process_started = True
        diagnostics.child_pid = process.pid
        status_sender.close()
        control_receiver.close()
        _wait_for_child_handshake(process, status_receiver, diagnostics, timeout=5)
        if set(diagnostics.lock_connection_ids) != {"first", "second"}:
            raise AssertionError("workers did not expose two distinct lock connections")
        if len(set(diagnostics.lock_connection_ids.values())) != 2:
            raise AssertionError("workers did not use distinct lock connections")
        _assert_worker_instances(
            observer.application_identity, diagnostics.worker_identities
        )
        diagnostics.worker_instances_verified = True
        if observer.connection_id in diagnostics.tracked_connection_ids:
            raise AssertionError("observer connection was tracked as a test worker")
        evidence = _wait_for_observed_lock_wait(
            observer, diagnostics.lock_connection_ids, timeout=5
        )
        if force_child_hang:
            process.join(process_timeout)
            if process.is_alive():
                raise MysqlLockRaceTimeout(
                    "lock-race child exceeded the parent process timeout"
                )
            raise MysqlLockRaceChildError(
                "forced-hang child exited before the parent timeout"
            )
        control_sender.send("release")
        responses = _wait_for_child_responses(
            process, status_receiver, timeout=process_timeout
        )
        process.join(process_timeout)
        if process.is_alive():
            raise MysqlLockRaceTimeout(
                "lock-race child did not exit within the hard timeout"
            )
        race_result = MysqlLockRaceResult(
            responses=responses,
            lock_wait_evidence=evidence,
            lock_connection_ids=dict(diagnostics.lock_connection_ids),
        )
    except BaseException as error:
        primary_error = error
    finally:
        if process_started:
            _record_cleanup_error(
                cleanup_errors,
                lambda: control_sender.send("release")
                if _process_is_alive(process, cleanup_errors)
                else None,
            )
            _record_cleanup_error(cleanup_errors, lambda: process.join(0.2))
            if diagnostics.worker_instances_verified:
                _record_cleanup_error(
                    cleanup_errors,
                    lambda: _kill_and_record(
                        observer,
                        diagnostics.tracked_connection_ids,
                        "QUERY",
                        diagnostics,
                    ),
                )
            _record_cleanup_error(cleanup_errors, lambda: process.join(0.2))
            if diagnostics.worker_instances_verified:
                _record_cleanup_error(
                    cleanup_errors,
                    lambda: _kill_and_record(
                        observer,
                        diagnostics.tracked_connection_ids,
                        "CONNECTION",
                        diagnostics,
                    ),
                )
            _record_cleanup_error(cleanup_errors, lambda: process.join(0.5))
            if _process_is_alive(process, cleanup_errors):
                diagnostics.hard_terminated = True
                _record_cleanup_error(cleanup_errors, process.terminate)
                _record_cleanup_error(cleanup_errors, lambda: process.join(1))
            if _process_is_alive(process, cleanup_errors):
                diagnostics.hard_terminated = True
                _record_cleanup_error(cleanup_errors, process.kill)
                _record_cleanup_error(cleanup_errors, process.join)
            if _process_is_alive(process, cleanup_errors):
                cleanup_errors.append(
                    AssertionError("lock-race child remained alive after process kill")
                )
            try:
                diagnostics.child_exitcode = process.exitcode
            except BaseException as error:
                cleanup_errors.append(error)
        _record_cleanup_error(
            cleanup_errors,
            lambda: _wait_for_no_tracked_mysql_state(
                observer, diagnostics.tracked_connection_ids, timeout=5
            ),
        )
        for pipe in (status_receiver, status_sender, control_receiver, control_sender):
            _record_cleanup_error(cleanup_errors, pipe.close)
        if process_started and not _process_is_alive(process, cleanup_errors):
            _record_cleanup_error(cleanup_errors, process.close)

    _raise_primary_and_cleanup_errors(primary_error, cleanup_errors)
    if race_result is None:
        raise AssertionError("lock race returned without a result")
    return race_result
