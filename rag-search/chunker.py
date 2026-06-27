"""
招标文件切块模块。

切块策略（三层）：
  第一层：按 # 标题识别章节，构建 section_path，chunk 不跨章节
  第二层：章节内按空行切段落，逐段累加，超 800 字输出 chunk
  第三层：单段落超 800 字时，按句子边界切分，前后补充上下文
"""

import re
import uuid
from datetime import datetime
from pathlib import Path

CHUNK_MAX = 800       # 段落累加上限（字）
SENTENCE_MAX = 800    # 句子级子块上限（字）
CONTEXT_LEN = 100     # 前后补充上下文长度（字）

SENTENCE_END = re.compile(r"[。？！]")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)


# ── 对外接口 ──────────────────────────────────────────────────────────────────

def chunk_document(file_path: str) -> list[dict]:
    text = Path(file_path).read_text(encoding="utf-8")
    document_id = Path(file_path).stem
    sections = _parse_sections(text)
    chunks = []
    for sec in sections:
        chunks.extend(_chunk_section(sec, document_id))
    return chunks


# ── 第一层：章节识别 ──────────────────────────────────────────────────────────

def _parse_sections(text: str) -> list[dict]:
    matches = list(HEADING_RE.finditer(text))
    sections = []
    stack: list[tuple[int, str]] = []  # (level, title)

    for i, m in enumerate(matches):
        level = len(m.group(1))
        title = m.group(2).strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        content = text[start:end].strip()

        # 维护层级栈，构建 section_path
        while stack and stack[-1][0] >= level:
            stack.pop()
        stack.append((level, title))
        section_path = " / ".join(t for _, t in stack)

        sections.append({
            "title": title,
            "level": level,
            "content": content,
            "section_path": section_path,
        })

    return sections


# ── 第二层：段落累加 ──────────────────────────────────────────────────────────

def _chunk_section(sec: dict, document_id: str) -> list[dict]:
    section_path = sec["section_path"]
    title = sec["title"]
    content = sec["content"]

    if not content:
        return [_make_chunk(document_id, section_path, title, title)]

    paragraphs = _split_paragraphs(content)
    chunks = []
    current: list[str] = []
    current_len = 0

    for para in paragraphs:
        para_len = len(para)

        if current_len + para_len <= CHUNK_MAX:
            current.append(para)
            current_len += para_len
        else:
            if current:
                chunks.extend(_make_section_chunks(document_id, section_path, title, current))
            if para_len <= CHUNK_MAX:
                current = [para]
                current_len = para_len
            else:
                # 第三层：单段落超限
                chunks.extend(_sentence_split(document_id, section_path, title, para))
                current = []
                current_len = 0

    if current:
        chunks.extend(_make_section_chunks(document_id, section_path, title, current))

    return chunks


def _make_section_chunks(document_id, section_path, title, paragraphs: list[str]) -> list[dict]:
    source = "\n\n".join(paragraphs)
    return [_make_chunk(document_id, section_path, title, source)]


# ── 第三层：句子级分块 ────────────────────────────────────────────────────────

def _sentence_split(document_id: str, section_path: str, title: str, para: str) -> list[dict]:
    sentences = _split_sentences(para)
    groups: list[str] = []  # 每组是拼好的核心文本

    current: list[str] = []
    current_len = 0
    for sent in sentences:
        if current_len + len(sent) <= SENTENCE_MAX:
            current.append(sent)
            current_len += len(sent)
        else:
            if current:
                groups.append("".join(current))
            current = [sent]
            current_len = len(sent)
    if current:
        groups.append("".join(current))

    chunks = []
    for i, core in enumerate(groups):
        prefix = _extract_suffix_context(groups[i - 1]) if i > 0 else ""
        suffix = _extract_prefix_context(groups[i + 1]) if i + 1 < len(groups) else ""
        chunk_text_body = prefix + core + suffix
        chunks.append(_make_chunk(document_id, section_path, title, core, chunk_text_body))

    return chunks


def _split_sentences(text: str) -> list[str]:
    parts = SENTENCE_END.split(text)
    ends = SENTENCE_END.findall(text)
    sentences = []
    for j, part in enumerate(parts):
        s = part + (ends[j] if j < len(ends) else "")
        if s.strip():
            sentences.append(s)
    return sentences


def _extract_suffix_context(text: str) -> str:
    """取文本尾部 100 字，并延伸到最近的句首（上一个句子结尾之后）。"""
    if len(text) <= CONTEXT_LEN:
        return text
    tail = text[-CONTEXT_LEN:]
    m = SENTENCE_END.search(tail)
    if m:
        return tail[m.end():]
    return tail


def _extract_prefix_context(text: str) -> str:
    """取文本头部 100 字，并延伸到最近的句尾（。？！）。"""
    head = text[:CONTEXT_LEN]
    m = list(SENTENCE_END.finditer(head))
    if m:
        return head[:m[-1].end()]
    # 100 字内没找到句尾，继续往后找
    m2 = SENTENCE_END.search(text, CONTEXT_LEN)
    if m2:
        return text[:m2.end()]
    return head


# ── 段落切割 ──────────────────────────────────────────────────────────────────

def _split_paragraphs(content: str) -> list[str]:
    raw = re.split(r"\n{2,}", content)
    paragraphs = []
    list_buf: list[str] = []
    table_buf: list[str] = []

    for block in raw:
        block = block.strip()
        if not block:
            continue

        lines = block.splitlines()
        is_list = all(re.match(r"^[-*]\s", l) or not l.strip() for l in lines)
        is_table = all(re.match(r"^\|", l) or not l.strip() for l in lines)

        if is_list:
            list_buf.append(block)
            continue
        if list_buf:
            paragraphs.append("\n".join(list_buf))
            list_buf = []

        if is_table:
            table_buf.append(block)
            continue
        if table_buf:
            paragraphs.append("\n".join(table_buf))
            table_buf = []

        paragraphs.append(block)

    if list_buf:
        paragraphs.append("\n".join(list_buf))
    if table_buf:
        paragraphs.append("\n".join(table_buf))

    return paragraphs


# ── 工具函数 ──────────────────────────────────────────────────────────────────

def _make_chunk(
    document_id: str,
    section_path: str,
    title: str,
    source_text: str,
    chunk_text_body: str | None = None,
) -> dict:
    header = f"{section_path}\n{title}"
    chunk_text = header + "\n" + (chunk_text_body if chunk_text_body is not None else source_text)
    return {
        "chunk_id": str(uuid.uuid4()),
        "document_id": document_id,
        "section_path": section_path,
        "chunk_text": chunk_text,
        "source_text": source_text,
        "chunk_type": _detect_type(section_path),
        "package_no": _detect_package(section_path),
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }


def _detect_type(section_path: str) -> str:
    rules = [
        ("技术要求", "technical_requirement"),
        ("用户需求", "requirement"),
        ("评分", "scoring"),
        ("合同", "contract"),
        ("资格", "qualification"),
        ("开标", "submission"),
        ("投标", "submission"),
    ]
    for keyword, chunk_type in rules:
        if keyword in section_path:
            return chunk_type
    return "other"


def _detect_package(section_path: str) -> str:
    m = re.search(r"标包\s*(\d+)", section_path)
    return m.group(1) if m else ""
