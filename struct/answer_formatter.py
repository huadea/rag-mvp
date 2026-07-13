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
        "可查询的问题示例：招标编号、招标人/采购人、招标控制价、投标文件递交截止时间与地点、是否接受联合体投标等。"
    )


def format_markdown(records: list[dict], group_name: str = "项目基础信息") -> str:
    """
    按参考文档的嵌套列表格式输出，仅展示字段名与字段值（不含来源/置信度）。
    多值字段（如"标段/包号划分"）按子列表展开。
    """
    lines = [f"- {group_name}", ""]
    for r in records:
        value = r.get("field_value")
        lines.append(f"  - {r['field_name']}")
        lines.append("")
        if not value:
            lines.append("    空")
        elif "\n" in value:
            for item in value.split("\n"):
                lines.append(f"    - {item}")
        else:
            lines.append(f"    {value}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"
