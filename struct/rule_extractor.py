"""
规则提取：对每个字段用锚点词 + 正则在章节列表中匹配。
返回：(命中记录列表, 未命中字段定义列表)
"""

import re
from schema import FIELDS

_TAG_RE = re.compile(r"<[^>]+>")


def _clean(value: str) -> str:
    """去掉残留的 HTML 标签（表格单元格解析后可能带 </p></td> 等），合并多余空白。"""
    value = _TAG_RE.sub("", value)
    return re.sub(r"\s+", " ", value).strip()


_BID_ROW_RE = re.compile(
    r"<tr><td><p>(\d+)</p></td><td><p>([^<]+)</p></td>"
    r"<td><p>([^<]+)</p></td><td><p>([\d,.]+)</p></td></tr>"
)


def extract(sections: list[dict]) -> tuple[list[dict], list[dict]]:
    hit_records: list[dict] = []
    miss_fields: list[dict] = []

    for field_def in FIELDS:
        record = _match_field(field_def, sections)
        if record:
            hit_records.append(record)
        else:
            miss_fields.append(field_def)

    return hit_records, miss_fields


def _match_field(field_def: dict, sections: list[dict]) -> dict | None:
    field_name = field_def["field_name"]
    anchors = field_def["anchors"]
    pattern = field_def["pattern"]
    group_name = field_def.get("group", "")

    if field_name == "标段/包号划分":
        return _match_bid_packages(field_def, sections)
    if field_name == "是否接受联合体投标":
        return _match_boolean(
            field_def, sections, keyword="联合体",
            accept_label="接受", reject_label="不接受",
        )
    if field_name == "是否允许分包":
        return _match_boolean(
            field_def, sections, keyword="分包",
            accept_label="允许", reject_label="不允许",
        )

    for section in sections:
        text = section["content"]
        for anchor in anchors:
            # 找到锚点词所在的行
            for line in text.splitlines():
                if anchor in line:
                    if pattern:
                        # 只在锚点词之后的一小段窗口内找值，避免匹配到行内更靠后、
                        # 与锚点无关的冒号（例如整段正文里出现的其他"字段：值"）
                        idx = line.find(anchor)
                        window = line[idx: idx + len(anchor) + 60]
                        m = re.search(pattern, window)
                        if m:
                            value = _clean(m.group(1))
                            if not value:
                                continue
                            # 过滤掉明显过长的匹配（可能是整段文字而非字段值）
                            if len(value) > 200:
                                continue
                            return {
                                "field_name": field_name,
                                "field_value": value,
                                "source_section": section["title"],
                                "source_text": line.strip(),
                                "confidence": "高",
                                "extraction_method": "rule",
                                "group_name": group_name,
                            }

    return None


def _match_bid_packages(field_def: dict, sections: list[dict]) -> dict | None:
    group_name = field_def.get("group", "")
    for section in sections:
        text = section["content"]
        if "标包号" not in text or "最高限价" not in text:
            continue
        rows = _BID_ROW_RE.findall(text)
        if not rows:
            continue

        items = [f"标包{no}{name}{qty}{price}元" for no, name, qty, price in rows]
        return {
            "field_name": "标段/包号划分",
            "field_value": "\n".join(items),
            "source_section": section["title"],
            "source_text": "；".join(
                f"标包{no}｜{name}｜{qty}｜{price}元" for no, name, qty, price in rows
            ),
            "confidence": "高",
            "extraction_method": "rule",
            "group_name": group_name,
        }

    return None


def _match_boolean(
    field_def: dict,
    sections: list[dict],
    keyword: str,
    accept_label: str,
    reject_label: str,
) -> dict | None:
    field_name = field_def["field_name"]
    group_name = field_def.get("group", "")
    reject_words = ["不接受", "不允许", "不得", "禁止", "不可以"]
    accept_words = ["接受", "允许", "可以"]

    for section in sections:
        text = section["content"]
        if keyword not in text:
            continue
        # 在关键词周围 200 字符窗口内判断接受/不接受
        idx = text.find(keyword)
        window = text[max(0, idx - 50): idx + 150]
        is_rejected = any(w in window for w in reject_words)
        is_accepted = any(w in window for w in accept_words)

        if is_rejected:
            value = reject_label
        elif is_accepted:
            value = accept_label
        else:
            continue  # 上下文不明确，交给 LLM

        # 找包含关键词的那一行作为来源原文
        source_line = next(
            (ln.strip() for ln in text.splitlines() if keyword in ln),
            window.strip(),
        )
        return {
            "field_name": field_name,
            "field_value": value,
            "source_section": section["title"],
            "source_text": source_line,
            "confidence": "高",
            "extraction_method": "rule",
            "group_name": group_name,
        }

    return None
