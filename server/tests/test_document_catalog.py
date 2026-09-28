from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

from fde_api.documents.catalog import (
    DOCUMENT_TYPES,
    RESOURCE_TEMPLATES_DIR,
    load_document_catalog,
    load_template_manifest,
)
from fde_api.documents.models import DOCUMENT_TYPE_KEYS


EXPECTED_KEYS = set(DOCUMENT_TYPE_KEYS)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_catalog_contains_all_document_types():
    catalog = load_document_catalog()
    assert set(catalog) == EXPECTED_KEYS
    assert len(catalog) == 17
    for key, entry in catalog.items():
        assert isinstance(entry["name"], str) and entry["name"]
        assert entry["source"] in {"built"} or str(entry["source"]).endswith(".docx")
        assert isinstance(entry["modules"], list)
        assert isinstance(entry["required_sections"], list)


def test_expected_document_type_keys_are_stable():
    assert set(DOCUMENT_TYPES) == EXPECTED_KEYS


def test_manifest_matches_catalog():
    manifest = load_template_manifest()
    assert set(manifest) == set(DOCUMENT_TYPES)
    for key, entry in DOCUMENT_TYPES.items():
        assert manifest[key]["name"] == entry["name"]
        assert manifest[key]["source"] == entry["source"]
        assert manifest[key]["modules"] == list(entry["modules"])
        assert manifest[key]["required_sections"] == list(entry["required_sections"])


def test_build_does_not_modify_repository_sources(tmp_path):
    """Running the build into a tmp output dir leaves the source contracts intact."""
    workbench_root = Path(__file__).resolve().parents[2]
    script = workbench_root / "scripts" / "build-document-templates.py"
    assert script.is_file(), script

    source_hashes_before = {
        path.name: _sha256(path)
        for path in sorted(RESOURCE_TEMPLATES_DIR.glob("*.docx"))
    }
    assert source_hashes_before, "expected neutral document templates in the repo"

    output_dir = tmp_path / "rendered"
    result = subprocess.run(
        [sys.executable, str(script), "--output-dir", str(output_dir)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr

    for key in DOCUMENT_TYPES:
        rendered = output_dir / f"{key}.docx"
        assert rendered.is_file(), f"missing rendered template {key}"

    source_hashes_after = {
        path.name: _sha256(path)
        for path in sorted(RESOURCE_TEMPLATES_DIR.glob("*.docx"))
    }
    assert source_hashes_before == source_hashes_after
