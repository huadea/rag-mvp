"""
索引阶段入口。

用法：
    uv run build_index.py <招标文件.md>
"""

import sys
from pathlib import Path

import doc_parser
import rule_extractor
import llm_extractor
import field_store
from schema import FIELD_MAP, FIELDS


def main(file_path: str) -> None:
    path = Path(file_path).resolve()
    if not path.exists():
        print(f"[错误] 文件不存在：{path}")
        sys.exit(1)
    if path.suffix.lower() != ".md":
        print(f"[错误] 仅支持 .md 文件，当前文件：{path.name}")
        sys.exit(1)

    doc_path = str(path)
    print(f"[1/5] 解析文档：{path.name}")
    sections = doc_parser.parse(doc_path)
    full_text = doc_parser.full_text(doc_path)
    print(f"      识别章节数：{len(sections)}")

    print("[2/5] 规则提取（确定性字段 + 候选收集）...")
    hit_records, candidates_by_field, empty_fields = rule_extractor.extract(sections)
    print(f"      确定性命中：{len(hit_records)} 个字段")
    print(f"      待 LLM 仲裁（有候选）：{len(candidates_by_field)} 个字段")
    print(f"      两轮都无候选：{len(empty_fields)} 个字段（直接置空，不调用 LLM）")

    print("[3/5] LLM 逐字段仲裁（一个字段一次调用，不做批量合并，便于调试）...")
    arbitrated_records = []
    for field_name, candidates in candidates_by_field.items():
        record = llm_extractor.arbitrate(FIELD_MAP[field_name], candidates)
        arbitrated_records.append(record)
        status = "命中" if record.get("field_value") else "未命中"
        print(f"      [{status}] {field_name} <- {len(candidates)} 个候选")

    print("[4/5] LLM 归纳型字段（如项目概况）...")
    synthesis_fields = [f for f in FIELDS if f.get("field_type") == "synthesis"]
    synthesis_records = llm_extractor.extract(synthesis_fields, sections, full_text)

    empty_records = [
        llm_extractor.null_record(f["field_name"], f.get("group", ""), "规则+同义词均未找到候选")
        for f in empty_fields
    ]

    print("[5/5] 写入字段库...")
    all_records = hit_records + arbitrated_records + synthesis_records + empty_records
    field_store.clear(doc_path)
    field_store.save(doc_path, all_records)
    print(f"      已写入 {len(all_records)} 条记录 → fields.db")

    print("\n完成！使用以下命令查询：")
    print(f'    uv run query.py "{doc_path}" "投标截止时间是什么"')


if __name__ == "__main__":
    # if len(sys.argv) < 2:
    #     print("用法：uv run build_index.py <招标文件.md>")
    #     sys.exit(1)
    main('D:\\GitOpen\\rag-mvp\\demo.md')
