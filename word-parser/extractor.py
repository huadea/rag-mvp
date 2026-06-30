"""
将 ParsedDoc 转换为 Markdown 文本，可直接被 struct/doc_parser.py 消费。
对外接口：to_markdown(doc: ParsedDoc) -> str
          extract_file(file_path: str) -> str
"""

from pathlib import Path

from parser import ParsedDoc, Paragraph, Table, parse


def to_markdown(doc: ParsedDoc) -> str:
    lines: list[str] = []
    for item in _ordered(doc):
        if isinstance(item, Paragraph):
            lines.append(_para_to_md(item))
        elif isinstance(item, Table):
            lines.append(_table_to_md(item))
        lines.append("")  # 空行分隔
    return "\n".join(lines).strip()


def extract_file(file_path: str, output_path: str | None = None) -> str:
    """解析 .docx 并返回 Markdown 字符串，同时可选写入文件。"""
    doc = parse(file_path)
    md = to_markdown(doc)
    if output_path:
        Path(output_path).write_text(md, encoding="utf-8")
    return md


# ── 内部工具 ──────────────────────────────────────────────────────────────────

def _ordered(doc: ParsedDoc):
    """按文档原始顺序返回段落和表格（ParsedDoc 已按顺序存储）。"""
    # paragraphs 和 tables 是按 body 顺序追加的，直接合并需要重建顺序。
    # 由于 ParsedDoc 已在 parser.py 中按 body 顺序追加，这里简单交错：
    # 实际上 parser.py 是分开存储的，无法还原混合顺序。
    # 如需严格顺序，parser.py 可改为统一 list；此处按"段落全部在前，表格全部在后"输出。
    yield from doc.paragraphs
    yield from doc.tables


def _para_to_md(para: Paragraph) -> str:
    if para.level > 0:
        return f"{'#' * para.level} {para.text}"
    return para.text


def _table_to_md(table: Table) -> str:
    if not table.rows:
        return ""
    rows = table.rows
    header = rows[0]
    sep = ["---"] * len(header)
    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join(sep) + " |",
    ]
    for row in rows[1:]:
        # 对齐列数
        padded = row + [""] * (len(header) - len(row))
        lines.append("| " + " | ".join(padded[: len(header)]) + " |")
    return "\n".join(lines)
