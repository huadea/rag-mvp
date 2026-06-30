"""
解析 .docx 文件，返回标准化的段落、表格、标题列表。
对外接口：parse(file_path) -> ParsedDoc
"""

from dataclasses import dataclass, field
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn


@dataclass
class Paragraph:
    text: str
    style: str   # e.g. "Heading 1", "Normal"
    level: int   # 0=正文, 1-6=标题级别


@dataclass
class Table:
    rows: list[list[str]]  # 二维字符串，合并单元格展开


@dataclass
class ParsedDoc:
    paragraphs: list[Paragraph] = field(default_factory=list)
    tables: list[Table] = field(default_factory=list)


def parse(file_path: str) -> ParsedDoc:
    doc = Document(Path(file_path))
    result = ParsedDoc()

    # docx body 按顺序包含段落和表格，通过 doc.element.body 遍历保留顺序
    body = doc.element.body
    para_iter = iter(doc.paragraphs)
    table_iter = iter(doc.tables)

    for child in body:
        tag = child.tag.split("}")[-1]
        if tag == "p":
            para = next(para_iter, None)
            if para is None:
                continue
            text = para.text.strip()
            if not text:
                continue
            level = _heading_level(para.style.name)
            result.paragraphs.append(Paragraph(text=text, style=para.style.name, level=level))
        elif tag == "tbl":
            tbl = next(table_iter, None)
            if tbl is None:
                continue
            result.tables.append(Table(rows=_extract_table(tbl)))

    return result


def _heading_level(style_name: str) -> int:
    """将 Word 样式名映射到标题级别，0 表示正文。"""
    lower = style_name.lower()
    if "heading" in lower:
        for part in lower.split():
            if part.isdigit():
                return int(part)
        return 1
    return 0


def _extract_table(tbl) -> list[list[str]]:
    """提取表格内容，处理合并单元格（取第一个有文字的单元格内容）。"""
    rows = []
    for row in tbl.rows:
        cells = []
        for cell in row.cells:
            text = cell.text.strip()
            cells.append(text)
        # 去除因合并单元格导致的重复列（相邻相同值保留一个）
        deduped = _dedup_merged(cells)
        rows.append(deduped)
    return rows


def _dedup_merged(cells: list[str]) -> list[str]:
    """Word 合并单元格会重复填充同一文本，去除连续重复项。"""
    if not cells:
        return cells
    result = [cells[0]]
    for c in cells[1:]:
        if c != result[-1]:
            result.append(c)
    return result
