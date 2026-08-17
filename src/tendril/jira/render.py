"""Render JIRA issue descriptions into styled Rich Text.

JIRA gives us two shapes for the same field: ADF (structured JSON, from the v3
API and enhanced_jql) and legacy wiki markup (plain string, from the v2 API
that atlassian-python-api's `.issue()` hits). Both are handled here.

Deliberately limited: paragraphs, headings, bullet/ordered lists, blockquotes,
inline code + code blocks, horizontal rules, and inline marks (bold, italic,
code, strike, underline, link). Tables and panels are skipped — they don't fit
a narrow terminal column well and were called out as out-of-scope.
"""

from __future__ import annotations

import re
from typing import Any

from rich.style import Style
from rich.text import Text


# ---------- top-level dispatcher ----------


def render_description(raw_json: dict | None) -> Text | None:
    """Pick the right renderer based on the shape JIRA returned. None → no description."""
    body = ((raw_json or {}).get("fields") or {}).get("description")
    if body is None:
        return None
    if isinstance(body, dict):
        return adf_to_rich(body)
    if isinstance(body, str):
        if not body.strip():
            return None
        return wiki_to_rich(body)
    return Text(str(body))


# ---------- ADF ----------


_BLOCK_SEP = "\n\n"


def adf_to_rich(node: dict) -> Text:
    """Render an ADF document (or subtree) to Rich Text."""
    node_type = node.get("type", "")

    if node_type == "doc":
        return _join_blocks(node.get("content") or [])

    if node_type == "paragraph":
        return _adf_inline(node.get("content") or [])

    if node_type == "heading":
        inner = _adf_inline(node.get("content") or [])
        inner.stylize("bold")
        return inner

    if node_type == "bulletList":
        return _adf_list(node.get("content") or [], marker=lambda _i: "• ")

    if node_type == "orderedList":
        start = int((node.get("attrs") or {}).get("order", 1))
        return _adf_list(
            node.get("content") or [],
            marker=lambda i: f"{start + i}. ",
        )

    if node_type == "codeBlock":
        raw = _adf_plain_text(node.get("content") or [])
        return _code_block(raw)

    if node_type == "blockquote":
        inner = _join_blocks(node.get("content") or [])
        return _prefix_lines(inner, "│ ", style="dim")

    if node_type == "rule":
        return Text("─" * 40, style="dim")

    if node_type in ("panel", "table"):
        return Text(f"[{node_type} skipped]", style="dim")

    # Unknown block — try to recover its inline children so we don't lose content.
    return _adf_inline(node.get("content") or [])


def _join_blocks(children: list[Any]) -> Text:
    parts = [adf_to_rich(c) for c in children if isinstance(c, dict)]
    parts = [p for p in parts if p.plain]
    return Text(_BLOCK_SEP).join(parts)


def _adf_list(items: list[Any], *, marker) -> Text:
    lines: list[Text] = []
    idx = 0
    for item in items:
        if not isinstance(item, dict) or item.get("type") != "listItem":
            continue
        body = _adf_list_item(item)
        prefix = "  " + marker(idx)
        combined = Text(prefix) + body
        # Multi-line items (nested paragraphs / lists): indent continuation
        # under the marker so the tree reads visually.
        if "\n" in combined.plain:
            combined = _indent_continuation(combined, " " * len(prefix))
        lines.append(combined)
        idx += 1
    return Text("\n").join(lines)


def _indent_continuation(text: Text, indent: str) -> Text:
    """Indent every line after the first by `indent`. Overall style preserved; per-span styling on
    continuation lines is flattened to the baseline — acceptable for nested-list ergonomics."""
    plain = text.plain
    if "\n" not in plain:
        return text
    head, _, tail = plain.partition("\n")
    tail_indented = "\n".join(indent + line for line in tail.split("\n"))
    return Text(f"{head}\n{tail_indented}", style=text.style)


def _adf_list_item(item: dict) -> Text:
    """Render a listItem's children — paragraphs and nested lists — into one Text."""
    parts: list[Text] = []
    for child in item.get("content") or []:
        if not isinstance(child, dict):
            continue
        if child.get("type") == "paragraph":
            parts.append(_adf_inline(child.get("content") or []))
        else:
            parts.append(adf_to_rich(child))
    return Text("\n").join(parts)


def _adf_inline(nodes: list[Any]) -> Text:
    out = Text()
    for n in nodes:
        if not isinstance(n, dict):
            continue
        t = n.get("type")
        if t == "text":
            out.append(n.get("text") or "", style=_marks_to_style(n.get("marks") or []))
        elif t == "hardBreak":
            out.append("\n")
        elif t == "mention":
            attrs = n.get("attrs") or {}
            out.append(attrs.get("text") or attrs.get("displayName") or "@?", style="cyan")
        elif t == "emoji":
            attrs = n.get("attrs") or {}
            out.append(attrs.get("text") or attrs.get("shortName") or "")
        elif t == "inlineCard":
            attrs = n.get("attrs") or {}
            url = attrs.get("url") or ""
            out.append(_shorten_jira_url(url), style=Style(color="blue", underline=True, link=url))
        else:
            # Unknown inline node — recurse into content if any.
            content = n.get("content")
            if isinstance(content, list):
                out.append_text(_adf_inline(content))
    return out


def _marks_to_style(marks: list[Any]) -> Style:
    parts: list[str] = []
    link_url: str | None = None
    for mark in marks:
        if not isinstance(mark, dict):
            continue
        mt = mark.get("type")
        if mt == "strong":
            parts.append("bold")
        elif mt == "em":
            parts.append("italic")
        elif mt == "code":
            parts.append("bright_yellow on grey11")
        elif mt == "strike":
            parts.append("strike")
        elif mt == "underline":
            parts.append("underline")
        elif mt == "link":
            attrs = mark.get("attrs") or {}
            link_url = attrs.get("href") or None
            parts.append("blue underline")
    style = Style.parse(" ".join(parts)) if parts else Style()
    if link_url:
        style = style + Style(link=link_url)
    return style


def _adf_plain_text(nodes: list[Any]) -> str:
    out: list[str] = []
    for n in nodes:
        if not isinstance(n, dict):
            continue
        t = n.get("type")
        if t == "text":
            out.append(n.get("text") or "")
        elif t == "hardBreak":
            out.append("\n")
        else:
            content = n.get("content")
            if isinstance(content, list):
                out.append(_adf_plain_text(content))
    return "".join(out)


def _code_block(source: str) -> Text:
    """Indent every line by 4 spaces; render with a subtle background."""
    lines = source.split("\n")
    indented = "\n".join("    " + line for line in lines)
    return Text(indented, style="on grey11")


def _prefix_lines(text: Text, prefix: str, *, style: str = "") -> Text:
    """Prepend `prefix` to every line of the given Text."""
    plain = text.plain
    lines = plain.split("\n")
    joined = "\n".join(prefix + line for line in lines)
    return Text(joined, style=style)


def _shorten_jira_url(url: str) -> str:
    """`https://x.atlassian.net/browse/PROJ-123` → `PROJ-123`. Untouched otherwise."""
    m = re.search(r"/browse/([A-Za-z][A-Za-z0-9_]*-\d+)", url)
    return m.group(1) if m else url


# ---------- wiki markup (v2 API string) ----------


_HEADING_RE = re.compile(r"^h([1-6])\.\s*(.*)$")
_BULLET_RE = re.compile(r"^(\*+)\s+(.*)$")
_NUMBERED_RE = re.compile(r"^(#+)\s+(.*)$")
_RULE_RE = re.compile(r"^-{4,}$")
_PANEL_START = re.compile(r"^\{(panel|info|note|warning|tip)(?::[^}]*)?\}$")
_PANEL_END_TOKENS = {"{panel}", "{info}", "{note}", "{warning}", "{tip}"}
_CODE_START = re.compile(r"^\{code(?::[^}]*)?\}$")

_INLINE_TOKEN = re.compile(
    r"\{\{(?P<code>[^}]+)\}\}"
    r"|\[(?P<link>[^\]]+)\]"
    r"|\*(?P<bold>[^*\n]+)\*"
    r"|_(?P<italic>[^_\n]+)_"
)


def wiki_to_rich(source: str) -> Text:
    """Render legacy JIRA wiki markup (v2 API string) to Rich Text."""
    out = Text()
    lines = source.replace("\r\n", "\n").split("\n")
    in_code = False
    code_lines: list[str] = []
    in_skip_block = False

    def _flush_blank_before_block() -> None:
        if out.plain and not out.plain.endswith("\n\n"):
            if out.plain.endswith("\n"):
                out.append("\n")
            else:
                out.append("\n\n")

    for line in lines:
        stripped = line.strip()

        # Code block boundaries — {code} or {code:lang}
        if _CODE_START.match(stripped):
            if in_code:
                _flush_blank_before_block()
                out.append_text(_code_block("\n".join(code_lines)))
                out.append("\n\n")
                code_lines = []
                in_code = False
            else:
                in_code = True
            continue
        if in_code:
            code_lines.append(line)
            continue

        # Panel / info / note / warning / tip — skipped entirely.
        # Close check goes first: `{panel}` matches both the start and the end
        # regex, and when already inside a block we must treat it as the close.
        if in_skip_block:
            if stripped in _PANEL_END_TOKENS:
                in_skip_block = False
            continue
        if _PANEL_START.match(stripped):
            in_skip_block = True
            continue

        # Horizontal rule
        if _RULE_RE.match(stripped):
            _flush_blank_before_block()
            out.append("─" * 40, style="dim")
            out.append("\n\n")
            continue

        # Heading
        m = _HEADING_RE.match(line)
        if m:
            _flush_blank_before_block()
            content = _wiki_inline(m.group(2))
            content.stylize("bold")
            out.append_text(content)
            out.append("\n\n")
            continue

        # Bullet list
        m = _BULLET_RE.match(line)
        if m:
            depth = len(m.group(1))
            out.append("  " * depth + "• ")
            out.append_text(_wiki_inline(m.group(2)))
            out.append("\n")
            continue

        # Numbered list
        m = _NUMBERED_RE.match(line)
        if m:
            depth = len(m.group(1))
            out.append("  " * depth + "1. ")
            out.append_text(_wiki_inline(m.group(2)))
            out.append("\n")
            continue

        # Blockquote
        if line.startswith("bq. "):
            out.append("│ ", style="dim")
            out.append_text(_wiki_inline(line[4:]))
            out.append("\n")
            continue

        # Blank line → paragraph break
        if stripped == "":
            if not out.plain.endswith("\n\n"):
                out.append("\n")
            continue

        # Ordinary paragraph line
        out.append_text(_wiki_inline(line))
        out.append("\n")

    # Trailing hanging code block — best-effort flush.
    if in_code and code_lines:
        _flush_blank_before_block()
        out.append_text(_code_block("\n".join(code_lines)))
        out.append("\n")

    # Trim trailing whitespace so successive updates look clean.
    # (Rich's Text.rstrip mutates in place and returns None.)
    out.rstrip()
    return out


def _wiki_inline(source: str) -> Text:
    out = Text()
    pos = 0
    for m in _INLINE_TOKEN.finditer(source):
        if m.start() > pos:
            out.append(source[pos : m.start()])
        if m.group("code") is not None:
            out.append(m.group("code"), style="bright_yellow on grey11")
        elif m.group("link") is not None:
            _render_wiki_link(out, m.group("link"))
        elif m.group("bold") is not None:
            out.append(m.group("bold"), style="bold")
        elif m.group("italic") is not None:
            out.append(m.group("italic"), style="italic")
        pos = m.end()
    if pos < len(source):
        out.append(source[pos:])
    return out


def _render_wiki_link(out: Text, body: str) -> None:
    """Handle `[text|url]`, `[url|url|smart-link]`, and bare `[text]`."""
    parts = body.split("|")
    if len(parts) >= 3 and parts[-1].strip() == "smart-link":
        url = parts[0]
        out.append(_shorten_jira_url(url), style=Style(color="blue", underline=True, link=url))
        return
    if len(parts) == 2:
        text, url = parts
        out.append(text, style=Style(color="blue", underline=True, link=url))
        return
    out.append(parts[0])
