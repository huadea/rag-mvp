"""
查询阶段入口。

用法：
    uv run query.py <招标文件.md> "<问题>"

示例：
    uv run query.py ./招标文件.md "投标截止时间是什么"
    uv run query.py ./招标文件.md "基本信息是什么"
"""

import sys
from pathlib import Path

import field_store
import query_router
import answer_formatter


def main(file_path: str, question: str) -> None:
    doc_path = str(Path(file_path).resolve())

    field_names = query_router.route(question)

    if not field_names:
        print(answer_formatter.format_not_found())
        return

    records = field_store.get_by_names(doc_path, field_names)

    # 按 field_names 顺序排序，保持聚合查询的字段顺序
    order = {name: i for i, name in enumerate(field_names)}
    records.sort(key=lambda r: order.get(r["field_name"], 999))

    print(answer_formatter.format_records(records))


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print('用法：uv run query.py <招标文件.md> "<问题>"')
        sys.exit(1)
    main(sys.argv[1], sys.argv[2])
