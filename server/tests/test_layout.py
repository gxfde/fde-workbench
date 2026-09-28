import importlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_required_project_files_exist():
    required = [
        ROOT / "package.json",
        ROOT / ".env.example",
        ROOT / "desktop" / "package.json",
        ROOT / "server" / "pyproject.toml",
    ]
    assert all(path.is_file() for path in required)


def test_requirements_lock_has_no_local_editable_project_entry():
    lockfile = ROOT / "server" / "requirements.lock"
    contents = lockfile.read_text()
    assert "-e " not in contents
    assert str(ROOT) not in contents


def test_fde_api_is_importable_after_editable_install():
    assert importlib.import_module("fde_api") is not None
