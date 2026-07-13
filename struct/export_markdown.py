"""
导出阶段入口：读取已建好的字段库，把"项目基础信息"分组的全部字段
按参考文档的嵌套列表格式导出为 Markdown。

用法：
    uv run export_markdown.py <招标文件.md> [输出.md]

前置条件：需先对该文档运行过 build_index.py，字段库中已有数据。
"""

import sys
from pathlib import Path

import field_store
import answer_formatter
from schema import AGGREGATE_GROUPS

_GROUP_NAME = "项目基础信息"


def main(file_path: str, output_path: str | None = None) -> None:
    doc_path = str(Path(file_path).resolve())
    field_names = AGGREGATE_GROUPS[_GROUP_NAME]

    records = field_store.get_by_names(doc_path, field_names)
    order = {name: i for i, name in enumerate(field_names)}
    records.sort(key=lambda r: order.get(r["field_name"], 999))

    md = answer_formatter.format_markdown(records, group_name=_GROUP_NAME)

    if output_path:
        Path(output_path).write_text(md, encoding="utf-8")
        print(f"已写入：{output_path}")
    else:
        print(md)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法：uv run export_markdown.py <招标文件.md> [输出.md]")
        sys.exit(1)
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
