from __future__ import annotations

from tendril.jira.render import (
    adf_to_rich,
    render_description,
    wiki_to_rich,
)


def _spans_with_style(text, style_needle: str):
    """Return spans whose stringified style contains a substring like 'bold' or 'italic'."""
    return [s for s in text.spans if style_needle in str(s.style)]


class TestAdf:
    def test_paragraph_plain_text(self) -> None:
        doc = {
            "type": "doc",
            "content": [
                {"type": "paragraph", "content": [{"type": "text", "text": "hello world"}]}
            ],
        }
        out = adf_to_rich(doc)
        assert out.plain == "hello world"

    def test_two_paragraphs_get_blank_line(self) -> None:
        doc = {
            "type": "doc",
            "content": [
                {"type": "paragraph", "content": [{"type": "text", "text": "one"}]},
                {"type": "paragraph", "content": [{"type": "text", "text": "two"}]},
            ],
        }
        assert adf_to_rich(doc).plain == "one\n\ntwo"

    def test_heading_is_bold(self) -> None:
        doc = {
            "type": "doc",
            "content": [
                {
                    "type": "heading",
                    "attrs": {"level": 2},
                    "content": [{"type": "text", "text": "Problem"}],
                }
            ],
        }
        out = adf_to_rich(doc)
        assert out.plain == "Problem"
        assert _spans_with_style(out, "bold"), out.spans

    def test_inline_marks(self) -> None:
        doc = {
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "content": [
                        {"type": "text", "text": "bold ", "marks": [{"type": "strong"}]},
                        {"type": "text", "text": "italic ", "marks": [{"type": "em"}]},
                        {"type": "text", "text": "code", "marks": [{"type": "code"}]},
                    ],
                }
            ],
        }
        out = adf_to_rich(doc)
        assert out.plain == "bold italic code"
        assert _spans_with_style(out, "bold")
        assert _spans_with_style(out, "italic")

    def test_link_preserves_url(self) -> None:
        doc = {
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "content": [
                        {
                            "type": "text",
                            "text": "click",
                            "marks": [
                                {"type": "link", "attrs": {"href": "https://example.com"}}
                            ],
                        }
                    ],
                }
            ],
        }
        out = adf_to_rich(doc)
        assert out.plain == "click"
        assert any("example.com" in str(s.style) for s in out.spans)

    def test_hard_break_inserts_newline(self) -> None:
        doc = {
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "content": [
                        {"type": "text", "text": "line1"},
                        {"type": "hardBreak"},
                        {"type": "text", "text": "line2"},
                    ],
                }
            ],
        }
        assert adf_to_rich(doc).plain == "line1\nline2"

    def test_bullet_list(self) -> None:
        doc = {
            "type": "doc",
            "content": [
                {
                    "type": "bulletList",
                    "content": [
                        {
                            "type": "listItem",
                            "content": [
                                {"type": "paragraph", "content": [{"type": "text", "text": "a"}]}
                            ],
                        },
                        {
                            "type": "listItem",
                            "content": [
                                {"type": "paragraph", "content": [{"type": "text", "text": "b"}]}
                            ],
                        },
                    ],
                }
            ],
        }
        assert adf_to_rich(doc).plain == "  • a\n  • b"

    def test_ordered_list_respects_start(self) -> None:
        doc = {
            "type": "doc",
            "content": [
                {
                    "type": "orderedList",
                    "attrs": {"order": 3},
                    "content": [
                        {
                            "type": "listItem",
                            "content": [
                                {"type": "paragraph", "content": [{"type": "text", "text": "x"}]}
                            ],
                        },
                        {
                            "type": "listItem",
                            "content": [
                                {"type": "paragraph", "content": [{"type": "text", "text": "y"}]}
                            ],
                        },
                    ],
                }
            ],
        }
        assert adf_to_rich(doc).plain == "  3. x\n  4. y"

    def test_code_block_indented(self) -> None:
        doc = {
            "type": "doc",
            "content": [
                {
                    "type": "codeBlock",
                    "content": [{"type": "text", "text": "foo\nbar"}],
                }
            ],
        }
        assert adf_to_rich(doc).plain == "    foo\n    bar"

    def test_rule(self) -> None:
        out = adf_to_rich({"type": "doc", "content": [{"type": "rule"}]})
        assert out.plain == "─" * 40

    def test_panel_is_skipped(self) -> None:
        doc = {
            "type": "doc",
            "content": [
                {"type": "paragraph", "content": [{"type": "text", "text": "before"}]},
                {"type": "panel", "content": [{"type": "text", "text": "hidden"}]},
                {"type": "paragraph", "content": [{"type": "text", "text": "after"}]},
            ],
        }
        assert "hidden" not in adf_to_rich(doc).plain
        assert "before" in adf_to_rich(doc).plain
        assert "after" in adf_to_rich(doc).plain

    def test_blockquote_prefixes_lines(self) -> None:
        doc = {
            "type": "doc",
            "content": [
                {
                    "type": "blockquote",
                    "content": [
                        {"type": "paragraph", "content": [{"type": "text", "text": "quoted"}]},
                    ],
                }
            ],
        }
        assert adf_to_rich(doc).plain.startswith("│ quoted")


class TestWiki:
    def test_heading(self) -> None:
        out = wiki_to_rich("h2. Problem")
        assert out.plain == "Problem"
        assert _spans_with_style(out, "bold"), out.spans

    def test_paragraph_split_by_blank_line(self) -> None:
        out = wiki_to_rich("one\n\ntwo")
        assert out.plain == "one\n\ntwo"

    def test_inline_bold_italic_code(self) -> None:
        out = wiki_to_rich("*bold* and _italic_ and {{code}}")
        assert out.plain == "bold and italic and code"
        assert _spans_with_style(out, "bold")
        assert _spans_with_style(out, "italic")

    def test_smart_link_shortens_to_key(self) -> None:
        line = "[https://x.atlassian.net/browse/PROJ-42|https://x.atlassian.net/browse/PROJ-42|smart-link]"
        out = wiki_to_rich(line)
        assert "PROJ-42" in out.plain
        assert "atlassian" not in out.plain

    def test_bullet_list(self) -> None:
        out = wiki_to_rich("* one\n* two")
        assert out.plain == "  • one\n  • two"

    def test_code_block(self) -> None:
        src = "{code}\nfoo\nbar\n{code}"
        out = wiki_to_rich(src)
        assert "    foo" in out.plain
        assert "    bar" in out.plain

    def test_panel_is_skipped(self) -> None:
        src = "before\n{panel:title=x}\nhidden\n{panel}\nafter"
        out = wiki_to_rich(src)
        assert "hidden" not in out.plain
        assert "before" in out.plain
        assert "after" in out.plain

    def test_rule(self) -> None:
        assert "─" in wiki_to_rich("----").plain


class TestDispatcher:
    def test_none_when_field_absent(self) -> None:
        assert render_description({"fields": {}}) is None
        assert render_description(None) is None
        assert render_description({"fields": {"description": None}}) is None

    def test_none_when_empty_string(self) -> None:
        assert render_description({"fields": {"description": "   \n  "}}) is None

    def test_dict_routes_to_adf(self) -> None:
        raw = {
            "fields": {
                "description": {
                    "type": "doc",
                    "content": [
                        {"type": "paragraph", "content": [{"type": "text", "text": "adf"}]}
                    ],
                }
            }
        }
        out = render_description(raw)
        assert out is not None and out.plain == "adf"

    def test_string_routes_to_wiki(self) -> None:
        raw = {"fields": {"description": "h1. Hi\n\nbody"}}
        out = render_description(raw)
        assert out is not None
        assert "Hi" in out.plain
        assert "body" in out.plain
