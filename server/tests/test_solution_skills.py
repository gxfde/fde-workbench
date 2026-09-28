from types import SimpleNamespace

from fde_api.control.builtin_skills import LEGACY_SKILLS, SKILLS, _is_unchanged_builtin
from fde_api.control.api_catalog import CATALOG
from fde_api.control.ontology import ONTOLOGY


def test_solution_ontology_distinguishes_opportunities_solutions_and_documents():
    assert {"solution", "opportunity", "document", "document_version"} <= ONTOLOGY["entities"].keys()
    assert any(r[0] == "solution" and r[2] == "opportunity" for r in ONTOLOGY["relations"])
    assert any(r[0] == "solution" and r[2] == "document" for r in ONTOLOGY["relations"])
    assert CATALOG["solutions.archive"]["confirmation"]
    assert not CATALOG["solutions.update"]["confirmation"]


def test_new_public_skills_follow_saved_solution_export():
    by_key = {item[0]: item for item in SKILLS}
    assert "solutions.export_sow" in by_key["delivery-scope-documents"][-1]
    assert "solutions.export_sow" in by_key["document-production"][-1]
    assert "不要在机会识别表填写交付范围" in by_key["ai-opportunity-review"][-1]


def test_builtin_upgrade_preserves_admin_edits_and_inactive_skills():
    previous = next(x for x in LEGACY_SKILLS if x[0] == "delivery-scope-documents")
    key, name, description, capabilities, instructions = previous
    skill = SimpleNamespace(name=name, description=description, status="active")
    version = SimpleNamespace(instructions_text=instructions, required_capabilities=capabilities,
        manifest_json={"version": "1.0.0", "source": "fde-workbench", "read_only": False})
    assert _is_unchanged_builtin(skill, version, previous)
    version.instructions_text += "管理员定制内容"
    assert not _is_unchanged_builtin(skill, version, previous)
    version.instructions_text = instructions
    skill.status = "inactive"
    assert not _is_unchanged_builtin(skill, version, previous)
