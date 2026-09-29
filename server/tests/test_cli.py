from threading import Barrier, Thread

from sqlalchemy import select

from fde_api.auth.models import User
from fde_api.documents.template_service import SYSTEM_USERNAME


INITIAL_PASSWORD = "InitialPass!234"


def test_create_admin_reads_password_from_environment_without_printing_it(
    app, db_session, monkeypatch
):
    monkeypatch.setenv("FDE_INITIAL_ADMIN_PASSWORD", INITIAL_PASSWORD)

    result = app.test_cli_runner().invoke(
        args=["create-admin", "--username", "  ＡDMIN  ", "--display-name", "First Admin"]
    )

    assert result.exit_code == 0
    assert INITIAL_PASSWORD not in result.output
    db_session.expire_all()
    created = db_session.scalars(select(User).where(User.username == "admin")).one()
    assert created.display_name == "First Admin"
    assert created.role == "admin"
    assert created.must_change_password is True
    assert created.is_active is True
    assert created.password_hash != INITIAL_PASSWORD


def test_create_admin_is_idempotent_for_same_active_admin(
    app, db_session, monkeypatch
):
    monkeypatch.setenv("FDE_INITIAL_ADMIN_PASSWORD", INITIAL_PASSWORD)
    runner = app.test_cli_runner()
    first = runner.invoke(
        args=["create-admin", "--username", "admin", "--display-name", "First Admin"]
    )
    db_session.expire_all()
    original = db_session.scalars(select(User).where(User.username == "admin")).one()
    original_hash = original.password_hash
    original_id = original.id

    second = runner.invoke(
        args=["create-admin", "--username", "ADMIN", "--display-name", "Changed Name"]
    )

    assert first.exit_code == 0
    assert second.exit_code == 0
    assert INITIAL_PASSWORD not in first.output + second.output
    db_session.expire_all()
    users = db_session.scalars(select(User)).all()
    assert len(users) == 1
    assert users[0].id == original_id
    assert users[0].display_name == "First Admin"
    assert users[0].password_hash == original_hash


def test_create_admin_refuses_missing_password_environment(app, db_session, monkeypatch):
    monkeypatch.delenv("FDE_INITIAL_ADMIN_PASSWORD", raising=False)

    result = app.test_cli_runner().invoke(
        args=["create-admin", "--username", "admin", "--display-name", "First Admin"]
    )

    assert result.exit_code != 0
    assert "FDE_INITIAL_ADMIN_PASSWORD" in result.output
    assert db_session.scalars(select(User)).all() == []


def test_create_admin_rejects_initial_password_shorter_than_six(
    app, db_session, monkeypatch
):
    short_password = "12345"
    monkeypatch.setenv("FDE_INITIAL_ADMIN_PASSWORD", short_password)

    result = app.test_cli_runner().invoke(
        args=["create-admin", "--username", "admin", "--display-name", "First Admin"]
    )

    assert result.exit_code != 0
    assert short_password not in result.output
    assert db_session.scalars(select(User)).all() == []


def test_create_admin_rejects_oversized_username_and_password_before_hashing(
    app, db_session, monkeypatch
):
    import fde_api.cli as cli

    def must_not_hash(*_args):
        raise AssertionError("oversized credential reached hashing")

    monkeypatch.setattr(cli, "hash_password", must_not_hash)
    runner = app.test_cli_runner()
    monkeypatch.setenv("FDE_INITIAL_ADMIN_PASSWORD", INITIAL_PASSWORD)
    username_result = runner.invoke(
        args=["create-admin", "--username", "u" * 121, "--display-name", "Admin"]
    )
    monkeypatch.setenv("FDE_INITIAL_ADMIN_PASSWORD", "P" * 1025)
    password_result = runner.invoke(
        args=["create-admin", "--username", "admin", "--display-name", "Admin"]
    )

    assert username_result.exit_code != 0
    assert password_result.exit_code != 0
    assert db_session.scalars(select(User)).all() == []


def test_create_admin_refuses_existing_non_admin_user(
    app, db_session, monkeypatch
):
    from fde_api.auth.passwords import hash_password

    existing = User(
        username="admin",
        display_name="Viewer",
        role="viewer",
        password_hash=hash_password(INITIAL_PASSWORD),
        must_change_password=False,
        is_active=True,
    )
    db_session.add(existing)
    db_session.commit()
    monkeypatch.setenv("FDE_INITIAL_ADMIN_PASSWORD", INITIAL_PASSWORD)

    result = app.test_cli_runner().invoke(
        args=["create-admin", "--username", "admin", "--display-name", "First Admin"]
    )

    assert result.exit_code != 0
    db_session.expire_all()
    unchanged = db_session.scalars(select(User)).one()
    assert unchanged.role == "viewer"
    assert unchanged.display_name == "Viewer"


def test_concurrent_create_admin_treats_same_active_admin_winner_as_success(
    app, db_session, monkeypatch
):
    import fde_api.cli as cli

    monkeypatch.setenv("FDE_INITIAL_ADMIN_PASSWORD", INITIAL_PASSWORD)
    both_observed_absence = Barrier(2)
    real_hash_password = cli.hash_password
    outcomes = []

    def coordinated_hash_password(raw_password):
        both_observed_absence.wait(timeout=10)
        return real_hash_password(raw_password)

    monkeypatch.setattr(cli, "hash_password", coordinated_hash_password)
    command_callback = app.cli.commands["create-admin"].callback.__wrapped__

    def invoke(display_name):
        try:
            with app.app_context():
                command_callback(username="ADMIN", display_name=display_name)
            outcomes.append(None)
        except Exception as error:  # surfaced in the main test thread
            outcomes.append(error)

    first = Thread(target=invoke, args=("First winner",), name="first-admin")
    second = Thread(target=invoke, args=("Second winner",), name="second-admin")
    first.start()
    second.start()
    first.join(10)
    second.join(10)

    assert not first.is_alive()
    assert not second.is_alive()
    assert outcomes == [None, None]
    db_session.expire_all()
    admins = db_session.scalars(select(User).where(User.username == "admin")).all()
    assert len(admins) == 1
    assert admins[0].role == "admin"
    assert admins[0].is_active is True


def test_bootstrap_open_source_creates_initial_admin_despite_system_seed_user(
    app, db_session
):
    """The seeded `system` user must not be mistaken for an operator account.

    Seeding document templates inserts `system` with an empty password hash
    before the user count runs. Treating it as an existing user left a fresh
    database with no usable login at all.
    """
    result = app.test_cli_runner().invoke(args=["bootstrap-open-source"])

    assert result.exit_code == 0
    assert "initial_admin_created=True" in result.output
    db_session.expire_all()
    admin = db_session.scalars(select(User).where(User.username == "admin")).one()
    assert admin.role == "admin"
    assert admin.is_active is True
    assert admin.must_change_password is True
    assert admin.password_hash != ""
    seeded = db_session.scalars(
        select(User).where(User.username == SYSTEM_USERNAME)
    ).one()
    assert seeded.password_hash == ""


def test_bootstrap_open_source_keeps_existing_admin_on_rerun(app, db_session):
    runner = app.test_cli_runner()
    assert runner.invoke(args=["bootstrap-open-source"]).exit_code == 0
    db_session.expire_all()
    original = db_session.scalars(select(User).where(User.username == "admin")).one()
    original_id = original.id
    original_hash = original.password_hash

    result = runner.invoke(args=["bootstrap-open-source"])

    assert result.exit_code == 0
    assert "initial_admin_created=False" in result.output
    db_session.expire_all()
    admins = db_session.scalars(select(User).where(User.username == "admin")).all()
    assert len(admins) == 1
    assert admins[0].id == original_id
    assert admins[0].password_hash == original_hash


def test_bootstrap_open_source_respects_existing_non_seed_user(app, db_session):
    """An already-present operator still suppresses the initial admin."""
    from fde_api.auth.passwords import hash_password

    db_session.add(
        User(
            username="operator",
            display_name="Operator",
            role="viewer",
            password_hash=hash_password(INITIAL_PASSWORD),
            must_change_password=False,
            is_active=True,
        )
    )
    db_session.commit()

    result = app.test_cli_runner().invoke(args=["bootstrap-open-source"])

    assert result.exit_code == 0
    assert "initial_admin_created=False" in result.output
    db_session.expire_all()
    assert db_session.scalars(select(User).where(User.username == "admin")).all() == []
