"""
把用户自然语言问题映射到一个或多个字段名。
支持单字段查询和聚合分组查询。
"""

import re
from schema import FIELDS, AGGREGATE_GROUPS

# 去除问句后缀，帮助关键词匹配
_QUESTION_SUFFIX = re.compile(
    r"(是什么|是多少|有哪些|怎么样|如何|在哪|在哪里|是谁|是哪|叫什么|是几|有几|？|\?)\s*$"
)


def route(question: str) -> list[str]:
    q = _QUESTION_SUFFIX.sub("", question).strip()

    # 1. 先检查聚合分组
    for group_keyword, field_names in AGGREGATE_GROUPS.items():
        if group_keyword in q:
            return field_names

    # 2. 再按字段关键词逐一匹配
    matched: list[str] = []
    for field_def in FIELDS:
        for kw in field_def["query_keywords"]:
            if kw in q:
                matched.append(field_def["field_name"])
                break  # 一个字段只加一次

    return matched
