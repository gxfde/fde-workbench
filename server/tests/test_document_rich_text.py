from fde_api.documents.rich_text import (
    RichTextBlock,
    RichTextDocument,
    RichTextSanitizationError,
    render_rich_text,
    sanitize_rich_text,
)


def test_rich_text_removes_scripts_and_external_images():
    document = sanitize_rich_text(
        {
            "type": "doc",
            "content": [
                {"type": "script", "text": "alert(1)"},
                {"type": "image", "src": "https://evil"},
            ],
        }
    )
    assert document.blocks == ()


def test_rich_text_keeps_safe_paragraph_and_links():
    document = sanitize_rich_text(
        {
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "content": 'Visit <a href="https://example.com">example</a> now',
                    "marks": ["bold", "unknown_mark"],
                },
            ],
        }
    )
    assert len(document.blocks) == 1
    block = document.blocks[0]
    assert block.type == "paragraph"
    assert "example" in block.content
    # The anchor tag itself is not in the allowed-tag whitelist, so its markup
    # and any href are removed; the text survives.
    assert "href" not in block.content
    assert block.marks == ["bold"]

    unsafe = sanitize_rich_text(
        {
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "content": '<a href="javascript:alert(1)">bad</a>',
                    "marks": [],
                },
            ],
        }
    )
    assert len(unsafe.blocks) == 1
    assert "javascript:" not in unsafe.blocks[0].content
    assert "bad" in unsafe.blocks[0].content


def test_rich_text_removes_unsafe_markup():
    document = sanitize_rich_text(
        {
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "content": '<img src="x" onerror="alert(1)"><script>alert(1)</script> safe text',
                    "marks": [],
                },
            ],
        }
    )
    assert len(document.blocks) == 1
    cleaned = document.blocks[0].content
    assert "<img" not in cleaned
    assert "<script" not in cleaned
    assert "onerror" not in cleaned
    assert "safe text" in cleaned


def test_render_rich_text_is_deterministic():
    document = RichTextDocument(
        blocks=(
            RichTextBlock(type="paragraph", content="Hello", marks=["bold"]),
            RichTextBlock(
                type="bullet_list", content=["one", "two"], marks=[]
            ),
            RichTextBlock(
                type="table",
                content=[["a", "b"], ["c", "d"]],
                marks=[],
            ),
        )
    )
    expected = [
        {"type": "paragraph", "content": "Hello", "marks": ["bold"]},
        {"type": "bullet_list", "content": ["one", "two"], "marks": []},
        {"type": "table", "content": [["a", "b"], ["c", "d"]], "marks": []},
    ]
    assert render_rich_text(document) == expected
    assert render_rich_text(document) == render_rich_text(document)


def test_sanitize_rich_text_rejects_bad_shapes():
    for value in (None, [], "doc", {"type": "para"}):
        try:
            sanitize_rich_text(value)
        except RichTextSanitizationError:
            continue
        raise AssertionError(f"expected RichTextSanitizationError for {value!r}")
