"""
把 .md 文件按 # 标题切成章节列表。
返回：[{"title": str, "level": int, "content": str, "raw": str}]
"""

import re
from pathlib import Path


def parse(file_path: str) -> list[dict]:
    text = Path(file_path).read_text(encoding="utf-8")
    return _split_sections(text)


def full_text(file_path: str) -> str:
    return Path(file_path).read_text(encoding="utf-8")


def _split_sections(text: str) -> list[dict]:
    # 匹配 markdown 标题行：# / ## / ### …
    heading_re = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)
    matches = list(heading_re.finditer(text))

    sections = []
    for i, m in enumerate(matches):
        level = len(m.group(1))
        title = m.group(2).strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        content = text[start:end].strip()
        raw = text[m.start():end].strip()
        sections.append({
            "title": title,
            "level": level,
            "content": content,
            "raw": raw,
        })

    # 如果文档没有任何标题，把整篇文本作为一个虚拟章节
    if not sections:
        sections.append({
            "title": "全文",
            "level": 1,
            "content": text.strip(),
            "raw": text.strip(),
        })

    return sections
