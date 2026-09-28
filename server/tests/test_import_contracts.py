import subprocess
import sys

from conftest import SERVER_ROOT


def _run_clean_import(statement: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", statement],
        cwd=SERVER_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_template_service_imports_in_clean_interpreter():
    result = _run_clean_import(
        "from fde_api.templates.service import publish_template_version"
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_project_events_imports_in_clean_interpreter():
    result = _run_clean_import("from fde_api.projects.events import record_event")

    assert result.returncode == 0, result.stdout + result.stderr


def test_storage_contract_imports_in_clean_interpreter():
    result = _run_clean_import(
        "from fde_api.storage import ObjectStorage, LocalObjectStorage, AliyunOssStorage"
    )

    assert result.returncode == 0, result.stdout + result.stderr
