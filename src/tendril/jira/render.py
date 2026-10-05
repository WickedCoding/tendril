"""Render JIRA issue descriptions into styled Rich Text.

JIRA gives us two shapes for the same field: ADF (structured JSON, from the v3
API and enhanced_jql) and legacy wiki markup (plain string, from the v2 API
that atlassian-python-api's `.issue()` hits). Both are handled here.

Deliberately limited: paragraphs, headings, bullet/ordered/task lists, blockquotes,
panels, expands, inline code + code blocks, horizontal rules, status lozenges, dates,
image/file placeholders, and inline marks (bold, italic, code, strike, underline, link). Tables are skipped —
they don't fit a narrow terminal column well and were called out as out-of-scope.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from rich.style import Style
from rich.text import Text


# ---------- top-level dispatcher ----------


def render_description(raw_json: dict | None) -> Text | None:
    """Render an issue's description from its stored payload. None → no description."""
    return render_body(((raw_json or {}).get("fields") or {}).get("description"))


def render_body(body: Any) -> Text | None:
    """Render one JIRA rich-text value: a description or a comment body.

    Picks the renderer based on the shape JIRA returned. None → nothing to show.
    """
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
        return _adf_list(node.get("content") or [], marker=lambda _i, _item: "• ")

    if node_type == "orderedList":
        start = int((node.get("attrs") or {}).get("order", 1))
        return _adf_list(
            node.get("content") or [],
            marker=lambda i, _item: f"{start + i}. ",
        )

    if node_type == "taskList":
        return _adf_list(node.get("content") or [], marker=_task_marker)

    if node_type == "codeBlock":
        raw = _adf_plain_text(node.get("content") or [])
        return _code_block(raw)

    if node_type == "blockquote":
        inner = _join_blocks(node.get("content") or [])
        return _prefix_lines(inner, "│ ", style="dim")

    if node_type == "rule":
        return Text("─" * 40, style="dim")

    if node_type == "panel":
        return _adf_panel(node)

    if node_type in ("expand", "nestedExpand"):
        return _adf_expand(node)

    if node_type == "table":
        return Text("[table skipped]", style="dim")

    if node_type == "mediaSingle":
        return _adf_media(node.get("content") or [], kind="image")

    if node_type == "mediaGroup":
        return _adf_media(node.get("content") or [], kind="file")

    # Unknown block — try to recover its inline children so we don't lose content.
    return _adf_inline(node.get("content") or [])


# panelType → (icon, colour). `custom` panels and unknown types fall back to a plain bar.
_PANEL_STYLES = {
    "info": ("ℹ", "blue"),
    "note": ("✎", "magenta"),
    "warning": ("⚠", "yellow"),
    "error": ("✖", "red"),
    "success": ("✔", "green"),
}


def _adf_panel(node: dict) -> Text:
    """Render a panel as a coloured bar with its type icon on the first line.

    Unlike blockquotes, the panel body keeps its inline styling: panels often
    carry the bold warnings that matter most.
    """
    panel_type = (node.get("attrs") or {}).get("panelType")
    icon, colour = _PANEL_STYLES.get(panel_type, ("", "dim"))
    body = _join_blocks(node.get("content") or [])
    if not body.plain:
        return body
    first = f"│ {icon} " if icon else "│ "
    return _prefix_styled(body, first, "│ " + " " * (len(first) - 2), style=colour)


def _adf_expand(node: dict) -> Text:
    """Render an expand as its bold title with the body indented underneath.

    A terminal can't collapse, so the body is always shown; the `▾` marks where
    the collapsible section starts.
    """
    title = ((node.get("attrs") or {}).get("title") or "").strip() or "Details"
    header = Text("▾ ", style="dim")
    header.append(title, style="bold")
    body = _join_blocks(node.get("content") or [])
    if not body.plain:
        return header
    return Text("\n").join([header, _prefix_styled(body, "  ", "  ")])


def _adf_media(children: list[Any], *, kind: str) -> Text:
    """One placeholder line per media child. The image itself never reaches the cache."""
    labels = [
        Text(_media_label(c.get("attrs") or {}, kind), style="dim")
        for c in children
        if isinstance(c, dict) and c.get("type") == "media"
    ]
    return Text("\n").join(labels)


def _media_label(attrs: dict, kind: str) -> str:
    """`[image: name.png, 930×589]` from what the node carries.

    `alt` holds the uploaded filename; external media have no alt, only a url.
    """
    name = attrs.get("alt") or (attrs.get("url") if attrs.get("type") == "external" else None)
    width, height = attrs.get("width"), attrs.get("height")
    size = f"{width}×{height}" if width and height else None
    details = ", ".join(p for p in (name, size) if p)
    return f"[{kind}: {details}]" if details else f"[{kind}]"


def _prefix_styled(body: Text, first: str, rest: str, *, style: str = "") -> Text:
    """Prefix the first line of `body` with `first` and every later line with `rest`.

    Unlike `_prefix_lines`, the body's own spans (bold, links, …) survive.
    """
    out: list[Text] = []
    for i, line in enumerate(body.split("\n", allow_blank=True)):
        prefixed = Text(first if i == 0 else rest, style=style)
        prefixed.append_text(line)
        out.append(prefixed)
    return Text("\n").join(out)


def _join_blocks(children: list[Any]) -> Text:
    parts = [adf_to_rich(c) for c in children if isinstance(c, dict)]
    parts = [p for p in parts if p.plain]
    return Text(_BLOCK_SEP).join(parts)


_TASK_BOXES = {"DONE": "☑", "TODO": "☐"}


def _task_marker(_idx: int, item: dict) -> str:
    state = (item.get("attrs") or {}).get("state")
    return f"{_TASK_BOXES.get(state, '☐')} "


def _adf_list(items: list[Any], *, marker) -> Text:
    entries: list[tuple[str, Text]] = []
    idx = 0
    for item in items:
        if not isinstance(item, dict):
            continue
        item_type = item.get("type")
        if item_type == "taskList":
            # ADF nests a task list as a sibling right after the item it belongs
            # under, not inside it. Attach it to that item so it indents the same
            # way a nested bullet list does.
            nested = adf_to_rich(item)
            if entries:
                prefix, body = entries[-1]
                entries[-1] = (prefix, body + Text("\n") + nested)
            else:
                entries.append(("", nested))
            continue
        if item_type not in ("listItem", "taskItem"):
            continue
        entries.append(("  " + marker(idx, item), _adf_list_item(item)))
        idx += 1

    lines: list[Text] = []
    for prefix, body in entries:
        combined = Text(prefix) + body
        # Multi-line items (nested paragraphs / lists): indent continuation
        # under the marker so the tree reads visually.
        if "\n" in combined.plain:
            combined = _indent_continuation(combined, " " * len(prefix))
        lines.append(combined)
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
    if item.get("type") == "taskItem":
        # taskItem holds inline content directly, without a paragraph wrapper.
        return _adf_inline(item.get("content") or [])
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
        elif t == "status":
            attrs = n.get("attrs") or {}
            colour = _STATUS_COLOURS.get(attrs.get("color"), "")
            out.append(f"[{attrs.get('text') or '?'}]", style=f"bold {colour}".strip())
        elif t == "date":
            out.append(_format_date((n.get("attrs") or {}).get("timestamp")))
        elif t == "mediaInline":
            out.append(_media_label(n.get("attrs") or {}, "file"), style="dim")
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


# ADF status lozenge colours → Rich colours. `neutral` and unknowns stay uncoloured.
_STATUS_COLOURS = {
    "green": "green",
    "red": "red",
    "yellow": "yellow",
    "blue": "blue",
    "purple": "magenta",
}


def _format_date(timestamp: Any) -> str:
    """ADF date node: epoch milliseconds at UTC midnight → `YYYY-MM-DD`.

    Formatted in UTC on purpose: the node is a calendar date, and converting to
    local time would shift it a day for anyone west of Greenwich.
    """
    try:
        ms = int(timestamp)
    except (TypeError, ValueError):
        return "[date?]"
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).date().isoformat()


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
