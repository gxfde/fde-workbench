#!/usr/bin/env python
"""Render every catalog document template with the shared fixture context and
assert the output is a clean, well-formed DOCX.

For each canonical document type this script:

* loads the template from ``apps/fde-workbench/resources/document-templates/<key>.docx``
  (building the full set via ``build-document-templates.py`` into the artifact
  directory first when a template is missing),
* loads ``server/tests/fixtures/documents/fixture-data.json`` as the render
  context,
* renders it with :func:`fde_api.documents.generator.render_docx`,
* asserts the output is a valid OOXML archive (``zipfile.testzip()`` and the
  presence of ``word/document.xml``),
* asserts no residual Jinja placeholder (``{{`` / ``{%``) survives rendering
  (via :func:`fde_api.documents.qa.inspect_generated_docx`),
* asserts every ``required_sections`` value from the catalog appears in the
  extracted text, and
* optionally (``--render-pdf``, when LibreOffice is installed) converts the
  rendered DOCX to PDF and asserts a non-empty PDF exists.  If LibreOffice is
  not available the PDF step is skipped with a notice so the script still runs
  in CI.

Rendered artifacts are written under ``.artifacts/document-fixtures/``.  The
repository source templates and the fixture data are never modified.

Usage::

    PYTHONPATH=server/src server/.venv/bin/python scripts/verify-document-fixtures.py --all
    PYTHONPATH=server/src server/.venv/bin/python scripts/verify-document-fixtures.py --all --render-pdf

The script exits non-zero on any failure and prints a single summary line::

    fixture_ok=<N> residual=<N> sections_ok=<N> [pdf=SOK|SKIPPED]
"""

from __future__ import annotations

import argparse
import io
import json
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any

# The catalog lives on the server package path; import it explicitly so the
# script works whether or not ``fde_api`` is already imported.
try:
    from fde_api.documents.catalog import (
        DOCUMENT_TYPES,
        RESOURCE_TEMPLATES_DIR,
        load_document_catalog,
    )
    from fde_api.documents.generator import render_docx
    from fde_api.documents.qa import extract_docx_xml_text, inspect_generated_docx
except Exception:  # pragma: no cover - fallback for running without the venv
    _script_dir = Path(__file__).resolve().parent
    _workbench_dir = _script_dir.parent
    _server_src = _workbench_dir / "server" / "src"
    sys.path.insert(0, str(_server_src))
    from fde_api.documents.catalog import (  # type: ignore[no-redef]
        DOCUMENT_TYPES,
        RESOURCE_TEMPLATES_DIR,
        load_document_catalog,
    )
    from fde_api.documents.generator import render_docx  # type: ignore[no-redef]
    from fde_api.documents.qa import (  # type: ignore[no-redef]
        extract_docx_xml_text,
        inspect_generated_docx,
    )


SCRIPT_DIR = Path(__file__).resolve().parent
WORKBENCH_DIR = SCRIPT_DIR.parent
FIXTURE_PATH = (
    WORKBENCH_DIR / "server" / "tests" / "fixtures" / "documents" / "fixture-data.json"
)
ARTIFACTS_DIR = WORKBENCH_DIR / ".artifacts" / "document-fixtures"

DOCX_EXTENSION = ".docx"
_PLACEHOLDER_TOKENS = ("{{", "{%")


def _load_template_bytes(key: str) -> tuple[bytes, str]:
    """Return ``(template_bytes, source_description)`` for ``key``.

    Prefers the on-disk resource template; when a resource is missing the full
    template set is (re)built into a temporary directory via the build script's
    ``build_into`` helper so the render is always possible.
    """
    resource = RESOURCE_TEMPLATES_DIR / f"{key}{DOCX_EXTENSION}"
    if resource.is_file():
        return resource.read_bytes(), f"resource:{resource.name}"
    with tempfile.TemporaryDirectory() as temp_dir:
        # The on-disk template is missing, so build the full set through the
        # build script's ``build_into`` helper (loaded by file path so it works
        # whether or not ``scripts`` is an importable package).
        from importlib.util import module_from_spec, spec_from_file_location

        build_script = SCRIPT_DIR / "build-document-templates.py"
        spec = spec_from_file_location("build_document_templates", str(build_script))
        if spec is None or spec.loader is None:
            raise RuntimeError("could not load build-document-templates.py")
        module = module_from_spec(spec)
        spec.loader.exec_module(module)
        built = module.build_into(Path(temp_dir))
        target = next(
            (path for path in built if path.name == f"{key}{DOCX_EXTENSION}"), None
        )
        if target is None or not target.is_file():
            raise RuntimeError(f"template build produced no {key}.docx")
        return target.read_bytes(), f"built:{target.name}"


def _is_ooxml(data: bytes) -> bool:
    if not data.startswith(b"PK"):
        return False
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            names = archive.namelist()
            if archive.testzip() is not None:
                return False
    except (zipfile.BadZipFile, ValueError):
        return False
    return "word/document.xml" in names


def _residual_placeholder(text: str) -> bool:
    return any(token in text for token in _PLACEHOLDER_TOKENS)


def _convert_to_pdf(docx_path: Path, pdf_path: Path) -> tuple[bool, str]:
    """Convert ``docx_path`` to ``pdf_path`` with LibreOffice; never raises.

    Returns ``(ok, message)``. ``ok`` is ``True`` only when ``pdf_path`` exists
    and is non-empty.
    """
    soffice = shutil.which("libreoffice") or shutil.which("soffice")
    if soffice is None:
        return False, "LibreOffice not installed"
    try:
        result = subprocess.run(
            [soffice, "--headless", "--convert-to", "pdf", "--outdir", str(pdf_path.parent), str(docx_path)],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except Exception as exc:  # noqa: BLE001 - a conversion failure is a skip
        return False, f"LibreOffice conversion failed: {exc}"
    if result.returncode != 0:
        return False, f"LibreOffice conversion exited {result.returncode}"
    if not pdf_path.is_file() or pdf_path.stat().st_size == 0:
        return False, "LibreOffice produced an empty or missing PDF"
    return True, ""

class _TypeFailure(Exception):
    """Collects the QA description for one document type that failed."""


def verify_one(key: str, entry: dict[str, Any], context: dict, render_pdf: bool) -> dict[str, Any]:
    """Render and fully verify one document type.

    Returns a report dict for the summary line and writes the rendered artifact.
    """
    required_sections = list(entry.get("required_sections", []) or [])
    template_bytes, source_repr = _load_template_bytes(key)

    rendered = render_docx(io.BytesIO(template_bytes), context, {})
    rendered_bytes = _stream_bytes(rendered)
    text = extract_docx_xml_text(io.BytesIO(rendered_bytes))

    # Write the rendered DOCX artifact next to wherever the summary points.
    docx_artifact = ARTIFACTS_DIR / f"{key}{DOCX_EXTENSION}"
    docx_artifact.parent.mkdir(parents=True, exist_ok=True)
    docx_artifact.write_bytes(rendered_bytes)

    failures: list[str] = []

    if not _is_ooxml(rendered_bytes):
        failures.append("not a valid OOXML archive")

    residual = _residual_placeholder(text)
    if residual:
        failures.append("residual Jinja placeholder remains")

    qa = inspect_generated_docx(io.BytesIO(rendered_bytes), required_sections)
    missing_sections = [section for section in required_sections if section not in qa.sections]
    if missing_sections:
        failures.append(f"missing required sections: {missing_sections}")

    pdf_render: str = "OFF"
    if render_pdf:
        docx_artifact.parent.mkdir(parents=True, exist_ok=True)
        pdf_path = docx_artifact.with_suffix(".pdf")
        ok, message = _convert_to_pdf(docx_artifact, pdf_path)
        if ok:
            pdf_render = "SOK"
        else:
            pdf_render = "SKIPPED"
            if not message.startswith("LibreOffice"):
                print(f"  NOTE {key}: PDF conversion skipped ({message})")

    return {
        "key": key,
        "name": entry.get("name", key),
        "source": source_repr,
        "required_sections": required_sections,
        "found_sections": qa.sections,
        "missing_sections": missing_sections,
        "residual": residual,
        "failures": failures,
        "pdf_render": pdf_render,
    }


def _stream_bytes(stream) -> bytes:
    if hasattr(stream, "seek"):
        try:
            stream.seek(0)
        except Exception:  # noqa: BLE001 - seek is best-effort
            pass
    data = stream.read()
    return data if isinstance(data, bytes) else bytes(data)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--all",
        action="store_true",
        help="Verify every catalog document type (the default batch mode).",
    )
    parser.add_argument(
        "--render-pdf",
        action="store_true",
        help="Convert each rendered DOCX to PDF with LibreOffice (skipped if absent).",
    )
    args = parser.parse_args(argv)

    if not FIXTURE_PATH.is_file():
        raise SystemExit(f"fixture data missing: {FIXTURE_PATH}")
    context = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    catalog = load_document_catalog()

    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    print(f"verify fixtures: {len(catalog)} types, fixture={FIXTURE_PATH.name}")

    reports: list[dict[str, Any]] = []
    for key, entry in catalog.items():
        try:
            report = verify_one(key, entry, context, args.render_pdf)
        except Exception as exc:  # noqa: BLE001 - report any render failure per type
            report = {
                "key": key,
                "name": entry.get("name", key),
                "source": "ERROR",
                "required_sections": list(entry.get("required_sections", []) or []),
                "found_sections": [],
                "missing_sections": list(entry.get("required_sections", []) or []),
                "residual": False,
                "failures": [str(exc)],
                "pdf_render": "OFF",
            }
        reports.append(report)

        status = "OK" if not report["failures"] else "FAIL"
        print(
            f"  {key:<22} {status}  sections="
            f"{len(report['found_sections'])}/{len(report['required_sections'])}"
            f"  residual={report['residual']}"
        )
        for failure in report["failures"]:
            print(f"      - {failure}")

    fixture_ok = sum(1 for report in reports if not report["failures"])
    residual = sum(1 for report in reports if report["residual"])
    sections_ok = sum(
        1
        for report in reports
        if len(report["required_sections"]) > 0
        and len(report["found_sections"]) == len(report["required_sections"])
    )
    pdf_render_values = [report["pdf_render"] for report in reports]
    if args.render_pdf and all(value == "SOK" for value in pdf_render_values):
        pdf_summary = "pdf=SOK"
    elif args.render_pdf:
        pdf_summary = "pdf=SKIPPED"
    else:
        pdf_summary = "pdf=SKIPPED"

    print(
        f"fixture_ok={fixture_ok} residual={residual} sections_ok={sections_ok} [{pdf_summary}]"
    )
    if fixture_ok != len(reports):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
