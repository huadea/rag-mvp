"""
规则提取：对每个字段用锚点词 + 正则在章节列表中匹配。
返回：(命中记录列表, 未命中字段定义列表)
"""

import re
from schema import FIELDS


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

    # 联合体字段做布尔判断
    if field_name == "是否接受联合体":
        return _match_joint_venture(field_def, sections)

    for section in sections:
        text = section["content"]
        for anchor in anchors:
            # 找到锚点词所在的行
            for line in text.splitlines():
                if anchor in line:
                    if pattern:
                        m = re.search(pattern, line)
                        if m:
                            value = m.group(1).strip()
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


def _match_joint_venture(field_def: dict, sections: list[dict]) -> dict | None:
    group_name = field_def.get("group", "")
    for section in sections:
        text = section["content"]
        if "联合体" not in text:
            continue
        # 在联合体周围 200 字符窗口内判断接受/不接受
        idx = text.find("联合体")
        window = text[max(0, idx - 50): idx + 150]
        reject_words = ["不接受", "不允许", "不得", "禁止"]
        accept_words = ["接受", "允许", "可以"]
        is_rejected = any(w in window for w in reject_words)
        is_accepted = any(w in window for w in accept_words)

        if is_rejected:
            value = "不接受"
        elif is_accepted:
            value = "接受"
        else:
            continue  # 上下文不明确，交给 LLM

        # 找包含"联合体"的那一行作为来源原文
        source_line = next(
            (ln.strip() for ln in section["content"].splitlines() if "联合体" in ln),
            window.strip(),
        )
        return {
            "field_name": "是否接受联合体",
            "field_value": value,
            "source_section": section["title"],
            "source_text": source_line,
            "confidence": "高",
            "extraction_method": "rule",
            "group_name": group_name,
        }

    return None
