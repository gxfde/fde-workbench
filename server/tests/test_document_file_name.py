from unittest.mock import Mock
from fde_api.documents.draft_service import _available_document_file_name


def test_name_collision_preserves_history_and_allocates_suffix():
    session = Mock()
    session.scalar.side_effect = ['deprecated-file', 'another-file', None]
    assert _available_document_file_name(session, 'p', 'SOW-研发工作台') == 'SOW-研发工作台（3）'
    assert not session.add.called


def test_existing_file_is_excluded_and_long_names_are_bounded():
    session = Mock()
    session.scalar.side_effect = ['other-file', None]
    name = _available_document_file_name(session, 'p', '文' * 255, 'own-file')
    assert len(name) == 255 and name.endswith('（2）')
    query = session.scalar.call_args.args[0]
    assert 'project_files.id !=' in str(query)
