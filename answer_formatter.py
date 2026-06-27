"""
把字段记录格式化为终端可读的文本输出。
"""

_CONFIDENCE_LABEL = {"高": "高", "中": "中", "低": "低（建议人工确认）"}


def format_records(records: list[dict]) -> str:
    if not records:
        return "未找到相关字段信息。"

    parts: list[str] = []
    for r in records:
        value = r.get("field_value") or "（未找到）"
        confidence = _CONFIDENCE_LABEL.get(r.get("confidence", "低"), "低")
        section = r.get("source_section") or "—"
        source = r.get("source_text") or "—"

        block = (
            f"【{r['field_name']}】{value}\n"
            f"  来源章节：{section}\n"
            f"  来源原文：{source}\n"
            f"  置信度：{confidence}"
        )
        parts.append(block)

    return "\n\n".join(parts)


def format_not_found() -> str:
    return (
        "该问题不在结构化检索范围内，建议转向量检索。\n"
        "可查询的问题示例：项目编号、招标人、最高限价、投标截止时间、是否接受联合体等。"
    )
