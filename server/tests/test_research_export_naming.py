from types import SimpleNamespace

from fde_api.research.export_service import _find_research_result_file, _research_result_name


class _ScalarResult:
    def __init__(self, items):
        self._items = items

    def all(self):
        return self._items


class _Session:
    def __init__(self, items):
        self._items = items

    def scalars(self, _query):
        return _ScalarResult(self._items)


def test_research_result_name_describes_its_subject_and_form():
    assert _research_result_name("销售部", "岗位调研") == "调研结果-销售部-岗位调研"


def test_renamed_research_result_is_reused_by_form_identity():
    renamed = SimpleNamespace(
        tags_json={"research_form_id": "form-1"},
        display_name="人工修改后的调研报告名",
    )
    unrelated = SimpleNamespace(
        tags_json={"research_form_id": "form-2"},
        display_name="其他调研结果",
    )

    assert _find_research_result_file(_Session([unrelated, renamed]), "project-1", "form-1") is renamed
