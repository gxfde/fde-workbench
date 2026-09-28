#!/usr/bin/env python
"""Generate or copy the document templates used by the Document Engine.

The script reads the stable catalog in
``fde_api.documents.catalog`` and, for every canonical document type key,
produces a real, renderable DOCX at
``apps/fde-workbench/resources/document-templates/<key>.docx``:

* Contract/legal types (``source`` is a path under ``03-合同模板``) are COPIED
  verbatim from the finalized source DOCX. The source files are never modified.
* All other types (``source == "built"``) are GENERATED deterministically with
  python-docx (title + headings + paragraphs with ``{{ project.name }}`` plus a
  loop section using ``{% for role in subjects.roles %}``). These minimal
  templates carry placeholders that the document generator renders.

Usage::

    python scripts/build-document-templates.py                    # build into resources/
    python scripts/build-document-templates.py --output-dir DIR   # build into DIR
    python scripts/build-document-templates.py --check-reproducible  # build twice into temp dirs, compare hashes

``--check-reproducible`` builds into two throwaway temp directories and fails
(non-zero exit) if any output DOCX differs by SHA-256 between the two runs.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import shutil
import sys
import tempfile
from pathlib import Path

from docx import Document
from docx.enum.section import WD_ORIENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor

# The catalog lives on the server package path; import it explicitly so the
# script works whether or not ``fde_api`` is already imported.
try:
    from fde_api.documents.catalog import DOCUMENT_TYPES, RESOURCE_TEMPLATES_DIR
    from fde_api.documents.catalog import resolve_document_source
except Exception:  # pragma: no cover - fallback for running without the venv
    _script_dir = Path(__file__).resolve().parent
    _workbench_dir = _script_dir.parent
    _server_src = _workbench_dir / "server" / "src"
    # The catalog is dependency-free; artifact runtimes need not import the
    # Flask/SQLAlchemy application merely to generate a DOCX.
    import runpy
    _catalog = runpy.run_path(str(_server_src / "fde_api" / "documents" / "catalog.py"))
    DOCUMENT_TYPES = _catalog["DOCUMENT_TYPES"]
    RESOURCE_TEMPLATES_DIR = _catalog["RESOURCE_TEMPLATES_DIR"]
    resolve_document_source = _catalog["resolve_document_source"]


DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
DOCX_EXTENSION = ".docx"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build_built_template(key: str, entry: dict) -> bytes:
    """Deterministically generate one minimal-but-valid DOCX for a built type."""
    name = entry["name"]
    document = Document()

    if key == "sow":
        return build_solution_sow_template()

    if key == "research_result":
        document.add_heading("【待填写：调研对象】调研结果", level=1)
        document.add_paragraph("企业：【待填写：企业名称】")
        document.add_paragraph("项目：【待填写：项目名称】")
        document.add_paragraph("生成时间：【待填写：生成时间】")
        document.add_heading("调研摘要", level=2)
        document.add_paragraph("【待填写：调研摘要】")
        document.add_heading("关键发现", level=2)
        document.add_paragraph("【待填写：关键发现】")
        document.add_heading("建议", level=2)
        document.add_paragraph("【待填写：建议】")
        document.add_heading("调研记录", level=2)
        document.add_paragraph("【待插入：调研内容】")
        buffer = io.BytesIO()
        document.save(buffer)
        return buffer.getvalue()

    if key == "project_plan_progress":
        _style_project_plan_template(document)
        kicker = document.add_paragraph("项目交付 · 计划与进度快照")
        kicker.style = document.styles["Subtitle"]
        document.add_heading("项目计划及进度", level=1)
        metadata = document.add_table(rows=2, cols=2)
        metadata.style = "Table Grid"
        metadata.cell(0, 0).text = "项目：{{ project.name }}"
        metadata.cell(0, 1).text = "企业：{{ enterprise.name }}"
        metadata.cell(1, 0).text = "生成日期：【待填写：生成日期】"
        metadata.cell(1, 1).text = "文档状态：系统生成"
        for cell in metadata._cells:
            _shade_cell(cell, "F4F6F9")
        document.add_heading("企业与项目信息", level=2)
        document.add_paragraph("【待插入：企业与项目信息】")
        document.add_heading("客户目标与项目指引", level=2)
        document.add_paragraph("【待插入：客户目标与项目指引】")
        document.add_heading("任务甘特图", level=2)
        document.add_paragraph("【待插入：任务甘特图】")
        document.add_heading("任务清单", level=2)
        document.add_paragraph("【待插入：任务清单】")
        buffer = io.BytesIO()
        document.save(buffer)
        return buffer.getvalue()

    document.add_heading(name, level=1)
    document.add_paragraph(f"这是一份【{name}】模板，占位符将在文档生成时替换。")
    document.add_heading("基本信息", level=2)
    document.add_paragraph(f"项目名称：{{{{ project.name }}}}")
    document.add_paragraph(f"企业名称：{{{{ enterprise.name }}}}")

    document.add_heading("参与角色", level=2)
    table = document.add_table(rows=1, cols=2)
    table.style = "Table Grid"
    header = table.rows[0].cells
    header[0].text = "角色"
    header[1].text = "职责"
    loop_row = table.add_row()
    loop_row.cells[0].text = "{% for role in subjects.roles %}{{ role.name }}{% endfor %}"
    loop_row.cells[1].text = (
        "{% for role in subjects.roles %}{{ role.responsibility }}{% endfor %}"
    )

    document.add_heading("内容", level=2)
    for section in entry.get("required_sections", []) or []:
        document.add_heading(section, level=3)
        document.add_paragraph(f"{{{{ project.name }}}}——{section}：")

    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def build_solution_sow_template() -> bytes:
    """SOW content follows a saved solution, not an AI opportunity or price list."""
    document = Document()
    section = document.sections[0]
    section.page_width, section.page_height = Inches(8.5), Inches(11)
    section.top_margin = section.bottom_margin = Inches(0.7)
    section.left_margin = section.right_margin = Inches(0.8)
    for style_name, size in (("Normal", 11), ("Title", 24), ("Subtitle", 11),
                             ("Heading 1", 15), ("Heading 2", 12)):
        style = document.styles[style_name]
        style.font.name = "Songti SC"
        fonts = style._element.get_or_add_rPr().rFonts
        for attr in list(fonts.attrib):
            if "Theme" in attr:
                del fonts.attrib[attr]
        fonts.set(qn("w:eastAsia"), "Songti SC")
        style.font.size = Pt(size)
        style.font.color.rgb = RGBColor(0, 0, 0)
        style.font.underline = False
        style.paragraph_format.line_spacing = 1.25
        style.paragraph_format.space_after = Pt(7)
        style.paragraph_format.space_before = Pt(14 if style_name.startswith("Heading") else 0)
        style.paragraph_format.keep_with_next = style_name.startswith("Heading") or style_name == "Title"
    for border in document.styles.element.xpath(".//w:pBdr"):
        border.getparent().remove(border)
    document.add_paragraph("SOW 工作说明书", style="Title")
    document.add_paragraph("【待填写：方案名称】", style="Subtitle")
    document.add_paragraph("本工作说明书明确关联 AI 机会对应的交付设计、交付物、验收依据和实施条件。关联机会用于追溯业务需求，具体实施内容以本文件记载的方案及双方确认事项为准。")
    document.add_heading("项目信息", level=1)
    document.add_paragraph("项目名称：{{ project.name }}\n企业名称：{{ enterprise.name }}\n文档编号：{{ document.business_code }}    文档版本：{{ document.version_number }}\n来源方案版本：【待填写：来源方案版本】\n生成日期：【待填写：生成日期】")
    for heading, token in (
        ("关联 AI 机会", "关联AI机会"),
        ("方案设计", "方案设计"),
        ("交付物", "交付物"),
        ("预期指标与验收标准", "预期指标与验收标准"),
        ("所需数据与系统", "所需数据与系统"),
        ("计划排期", "计划排期"),
        ("风险与依赖", "风险与依赖"),
    ):
        document.add_heading(heading, level=1)
        document.add_paragraph(f"【待填写：{token}】")
    document.add_heading("商务与责任事项", level=1)
    document.add_paragraph("【待填写：待确认商务与责任事项】")
    document.add_paragraph("签署前应明确双方主体、服务边界与排除项、费用及支付安排、资源与第三方费用承担、成果权属、数据安全责任、验收流程和支持期限。未确认事项须另行协商并书面确认。")
    document.add_heading("变更与确认", level=1)
    document.add_paragraph("本文件对应生成时已保存的方案版本。后续调整应明确变更内容、影响和双方确认记录，并形成新的文档版本；方案编辑不会自动改变本文件。")
    document.add_paragraph("甲方名称及授权代表：________________\n确认日期：________________\n\n乙方名称及授权代表：________________\n确认日期：________________")
    document.core_properties.title = "SOW 工作说明书"
    document.core_properties.subject = "交付方案与关联 AI 机会"
    document.core_properties.author = ""
    output = io.BytesIO()
    document.save(output)
    return output.getvalue()


def _style_project_plan_template(document: Document) -> None:
    """Apply the compact-reference preset with a landscape schedule override."""
    section = document.sections[0]
    section.orientation = WD_ORIENT.LANDSCAPE
    section.page_width = Inches(11)
    section.page_height = Inches(8.5)
    section.top_margin = Inches(0.55)
    section.bottom_margin = Inches(0.55)
    section.left_margin = Inches(0.6)
    section.right_margin = Inches(0.6)
    section.header_distance = Inches(0.3)
    section.footer_distance = Inches(0.3)

    normal = document.styles["Normal"]
    normal.font.name = "PingFang SC"
    normal._element.rPr.rFonts.set(qn("w:eastAsia"), "PingFang SC")
    normal.font.size = Pt(10.5)
    normal.paragraph_format.space_before = Pt(0)
    normal.paragraph_format.space_after = Pt(6)
    normal.paragraph_format.line_spacing = 1.25

    for style_name, size, color, before, after in (
        ("Title", 24, "0B2545", 0, 8),
        ("Heading 1", 24, "0B2545", 0, 8),
        ("Heading 2", 14, "2E74B5", 14, 7),
        ("Heading 3", 12, "1F4D78", 10, 5),
        ("Subtitle", 9.5, "66758F", 0, 2),
    ):
        style = document.styles[style_name]
        style.font.name = "PingFang SC"
        style._element.rPr.rFonts.set(qn("w:eastAsia"), "PingFang SC")
        style.font.size = Pt(size)
        style.font.color.rgb = RGBColor.from_string(color)
        style.paragraph_format.space_before = Pt(before)
        style.paragraph_format.space_after = Pt(after)
        style.paragraph_format.keep_with_next = style_name.startswith("Heading")

    header = section.header.paragraphs[0]
    header.text = "FDE 工作台  |  项目计划及进度"
    header.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    for run in header.runs:
        run.font.name = "PingFang SC"
        run.font.size = Pt(8.5)
        run.font.color.rgb = RGBColor.from_string("66758F")
    footer = section.footer.paragraphs[0]
    footer.text = "本文件由系统依据当前项目数据生成"
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    for run in footer.runs:
        run.font.name = "PingFang SC"
        run.font.size = Pt(8)
        run.font.color.rgb = RGBColor.from_string("8995AD")


def _shade_cell(cell, fill: str) -> None:
    properties = cell._tc.get_or_add_tcPr()
    shading = properties.find(qn("w:shd"))
    if shading is None:
        shading = OxmlElement("w:shd")
        properties.append(shading)
    shading.set(qn("w:fill"), fill)


def build_into(output_dir: Path) -> list[Path]:
    """Write ``<key>.docx`` for every catalog type and return the created paths."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    created: list[Path] = []
    for key, entry in DOCUMENT_TYPES.items():
        source = entry["source"]
        destination = output_dir / f"{key}{DOCX_EXTENSION}"
        if source == "built":
            data = build_built_template(key, entry)
        else:
            source_path = resolve_document_source(source)
            if source_path is None or not source_path.is_file():
                raise SystemExit(
                    f"Missing source template for '{key}': {source_path}"
                )
            data = source_path.read_bytes()
        destination.write_bytes(data)
        created.append(destination)
    return created


def run_check_reproducible() -> int:
    """Build twice into temp dirs and assert identical SHA-256 per output."""
    with tempfile.TemporaryDirectory() as first_dir, tempfile.TemporaryDirectory() as second_dir:
        first = build_into(Path(first_dir))
        second = build_into(Path(second_dir))
        first_hashes = {path.name: sha256(path.read_bytes()) for path in first}
        second_hashes = {path.name: sha256(path.read_bytes()) for path in second}

        mismatches: list[str] = []
        for name in first_hashes:
            if first_hashes[name] != second_hashes.get(name):
                mismatches.append(name)

        print(f"built={len(first_hashes)} reproducible_check=...")
        if mismatches:
            for name in mismatches:
                print(f"  MISMATCH {name}")
            print(f"not reproducible: {len(mismatches)} output(s) differ")
            return 1
        print("reproducible: all outputs byte-identical across two builds")
        return 0


def print_summary(created: list[Path], output_dir: Path) -> None:
    print(f"wrote {len(created)} template(s) to {output_dir}")
    for key, entry in DOCUMENT_TYPES.items():
        path = output_dir / f"{key}{DOCX_EXTENSION}"
        data = path.read_bytes()
        if entry["source"] == "built":
            source_repr = "built"
        else:
            source_repr = entry["source"]
        print(f"  {key:<20} sha256={sha256(data)[:16]}…  source={source_repr}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check-reproducible",
        action="store_true",
        help="Build twice into temp dirs and assert identical SHA-256 per output.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(RESOURCE_TEMPLATES_DIR),
        help="Directory to write templates to.",
    )
    args = parser.parse_args(argv)

    if args.check_reproducible:
        return run_check_reproducible()

    output_dir = Path(args.output_dir)
    created = build_into(output_dir)
    _write_manifest()
    print_summary(created, output_dir)
    return 0


def _write_manifest() -> None:
    """Keep ``template_manifest.json`` in sync with the catalog on every build."""
    manifest = {
        key: {
            "name": entry["name"],
            "source": entry["source"],
            "modules": list(entry["modules"]),
            "required_sections": list(entry["required_sections"]),
        }
        for key, entry in DOCUMENT_TYPES.items()
    }
    manifest_path = (
        Path(__file__).resolve().parents[1]
        / "server"
        / "src"
        / "fde_api"
        / "documents"
        / "template_manifest.json"
    )
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    raise SystemExit(main())
