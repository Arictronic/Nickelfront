from __future__ import annotations

import re


def clean_qwen_markdown_response(text: str) -> str:
    """Remove Qwen answer wrappers and common parser/Markdown artifacts."""
    value = (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not value:
        return ""

    value = re.sub(r"^\s*```(?:markdown|md|text)?\s*\n", "", value, flags=re.IGNORECASE)
    value = re.sub(r"\n\s*```\s*$", "", value).strip()

    fenced_blocks = re.findall(r"```(?:markdown|md|text)?\s*\n(.*?)\n\s*```", value, flags=re.IGNORECASE | re.DOTALL)
    if fenced_blocks and len("\n\n".join(fenced_blocks).strip()) >= max(40, len(value) * 0.45):
        value = "\n\n".join(block.strip() for block in fenced_blocks if block.strip()).strip()

    value = re.sub(r"(?s)<!--.*?-->", "", value)
    value = re.sub(r"(?im)^\s*\[(?:Formula candidate|Table candidate\s*\d*)\]\s*$", "", value)
    value = re.sub(r"\[(?:Formula candidate|Table candidate\s*\d*)\]", "", value, flags=re.IGNORECASE)
    value = re.sub(r"\(cid:\d+\)|\bcid:\d+\b", " ", value, flags=re.IGNORECASE)
    value = re.sub(r"[\ue000-\uf8ff]", " ", value)
    value = re.sub(r"<+\s*latexit\b[^\n>]*(?:>+)?", " ", value, flags=re.IGNORECASE)
    value = re.sub(r"[□�]+", " ", value)

    prefix_re = re.compile(
        r"^\s*(?:#{1,6}\s*)?(?:"
        r"вот\s+(?:перевод|перевед[её]нный\s+markdown)|"
        r"перевод(?:\s+на\s+[\wА-Яа-яёЁ-]+)?|"
        r"перевед[её]нный\s+markdown|"
        r"результат\s+перевода|"
        r"translation|translated\s+markdown|translated\s+text|answer|ответ"
        r")\s*[:：\-—]*\s*$",
        re.IGNORECASE,
    )
    translation_heading_re = re.compile(
        r"^\s{0,3}#{1,6}\s*(?:перевод|translation|translated\s+markdown|translated\s+text|результат\s+перевода)\b.*$",
        re.IGNORECASE,
    )

    lines = value.split("\n")

    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and (prefix_re.match(lines[0]) or translation_heading_re.match(lines[0])):
        lines.pop(0)
        while lines and not lines[0].strip():
            lines.pop(0)

    value = "\n".join(lines).strip()
    value = re.sub(r"[ \t]{2,}", " ", value)
    value = re.sub(r"\n[ \t]+", "\n", value)
    value = re.sub(r"\n{4,}", "\n\n\n", value)
    return value.strip()


def clean_regenerated_markdown_response(text: str) -> str:
    value = clean_qwen_markdown_response(text)
    if not value:
        return ""
    lines = value.split("\n")
    prefix_re = re.compile(
        r"^\s*(?:#{1,6}\s*)?(?:"
        r"восстановленн(?:ый|ая)\s+markdown|"
        r"markdown\s+страницы|"
        r"извлеч[её]нный\s+markdown|"
        r"page\s+markdown|"
        r"extracted\s+markdown|"
        r"reconstructed\s+markdown"
        r")\s*[:：\-—]*\s*$",
        re.IGNORECASE,
    )
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and prefix_re.match(lines[0]):
        lines.pop(0)
        while lines and not lines[0].strip():
            lines.pop(0)
    value = "\n".join(lines).strip()
    value = re.sub(r"(?m)^\s{0,3}#{1,6}\s*$", "", value)
    value = re.sub(r"\n{4,}", "\n\n\n", value)
    return value.strip()
