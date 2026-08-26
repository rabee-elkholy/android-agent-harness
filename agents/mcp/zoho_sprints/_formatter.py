"""HTML and text formatters for Zoho Sprints rich-text descriptions."""
from __future__ import annotations

import re

_EMOJI_RE = re.compile(
    "["
    "\U0001F600-\U0001F64F"
    "\U0001F300-\U0001F5FF"
    "\U0001F680-\U0001F6FF"
    "\U0001F1E0-\U0001F1FF"
    "\U00002702-\U000027B0"
    "\U0000FE00-\U0000FE0F"
    "\U0001F900-\U0001F9FF"
    "\U0001FA00-\U0001FA6F"
    "\U0001FA70-\U0001FAFF"
    "\U00002600-\U000026FF"
    "\U0000200D"
    "\U00002B50\U00002B05-\U00002B07\U00002934-\U00002935"
    "\U000023CF\U000023E9-\U000023F3\U000023F8-\U000023FA"
    "]+",
    flags=re.UNICODE,
)


def _strip_emoji(text: str) -> str:
    return _EMOJI_RE.sub("", text).strip()


def format_zoho_html(text: str) -> str:
    if not text:
        return text
    text = _strip_emoji(text)
    if not text:
        return text
    if text.strip().startswith("<div dir="):
        return text
    has_arabic = bool(re.search(r"[\u0600-\u06FF]", text))
    code_blocks: list[str] = []

    def _save_code_block(match: re.Match[str]) -> str:
        code_blocks.append(match.group(1))
        return f"___CODE_BLOCK_{len(code_blocks) - 1}___"

    text = re.sub(r"```(?:\w+)?\n?(.*?)```", _save_code_block, text, flags=re.DOTALL)
    html_parts: list[str] = []
    in_list = False
    list_type = "ul"

    def _format_inline(s: str) -> str:
        s = re.sub(
            r"`([^`]+)`",
            r'<code style="color: #ffffff; font-family: Consolas, Monaco, monospace; font-size: 0.95em; direction: ltr; display: inline-block; font-weight: bold;">\1</code>',
            s,
        )
        return re.sub(r"\*\*(.+?)\*\*", r'<strong style="color: #ffffff; font-weight: 700;">\1</strong>', s)

    for line in text.strip().splitlines():
        stripped = line.strip()
        if not stripped:
            if in_list:
                html_parts.append(f"</{list_type}>")
                in_list = False
            continue
        cb_match = re.match(r"^___CODE_BLOCK_(\d+)___$", stripped)
        if cb_match:
            if in_list:
                html_parts.append(f"</{list_type}>")
                in_list = False
            code_content = code_blocks[int(cb_match.group(1))].strip()
            code_content = code_content.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            html_parts.append(
                f'<pre style="color: #ffffff; font-family: Consolas, Monaco, monospace; font-size: 13px; direction: ltr; text-align: left; margin: 8px 0; overflow-x: auto;"><code>{code_content}</code></pre>'
            )
            continue
        if stripped in ("---", "***", "___"):
            if in_list:
                html_parts.append(f"</{list_type}>")
                in_list = False
            html_parts.append('<hr style="border: 0; border-top: 1px solid rgba(255, 255, 255, 0.2); margin: 14px 0;">')
            continue
        heading = None
        if stripped.startswith("# "):
            heading = (stripped[2:], "1.25em", "12px 0 10px 0")
        elif stripped.startswith("## "):
            heading = (stripped[3:], "1.1em", "12px 0 6px 0")
        elif stripped.startswith("### "):
            heading = (stripped[4:], "1.05em", "10px 0 4px 0")
        if heading:
            if in_list:
                html_parts.append(f"</{list_type}>")
                in_list = False
            title, size, margin = heading
            html_parts.append(
                f'<div style="font-size: {size}; font-weight: 700; color: #ffffff; margin: {margin};">{_format_inline(title)}</div>'
            )
            continue
        if re.match(r"^\d+\.\s+", stripped):
            if not in_list or list_type != "ol":
                if in_list:
                    html_parts.append(f"</{list_type}>")
                html_parts.append("<ol style='margin-right: 22px; padding-right: 0; margin-bottom: 10px; color: #ffffff;'>")
                in_list = True
                list_type = "ol"
            item_text = _format_inline(re.sub(r"^\d+\.\s+", "", stripped))
            html_parts.append(f"<li style='margin-bottom: 6px; color: #ffffff; font-size: 14px;'>{item_text}</li>")
            continue
        if stripped.startswith("- ") or stripped.startswith("* "):
            if not in_list or list_type != "ul":
                if in_list:
                    html_parts.append(f"</{list_type}>")
                html_parts.append("<ul style='margin-right: 22px; padding-right: 0; margin-bottom: 10px; color: #ffffff;'>")
                in_list = True
                list_type = "ul"
            html_parts.append(
                f"<li style='margin-bottom: 6px; color: #ffffff; font-size: 14px;'>{_format_inline(stripped[2:])}</li>"
            )
            continue
        if in_list:
            html_parts.append(f"</{list_type}>")
            in_list = False
        html_parts.append(f"<p style='margin: 6px 0; color: #ffffff; font-size: 14px;'>{_format_inline(stripped)}</p>")
    if in_list:
        html_parts.append(f"</{list_type}>")
    inner = "\n".join(html_parts)
    if has_arabic:
        return (
            '<div dir="rtl" style="text-align: right; direction: rtl; line-height: 1.85; '
            "font-family: -apple-system, BlinkMacSystemFont, Segoe UI, Tahoma, Arial, sans-serif; "
            f'color: #ffffff; font-size: 14px;">\n{inner}\n</div>'
        )
    return inner
