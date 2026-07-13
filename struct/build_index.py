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
    print(f"[1/6] 解析文档：{path.name}")
    sections = doc_parser.parse(doc_path)
    full_text = doc_parser.full_text(doc_path)
    print(f"      识别章节数：{len(sections)}")

    print("[2/6] 规则提取（确定性字段 + 候选收集）...")
    hit_records, candidates_by_field, empty_fields = rule_extractor.extract(sections)
    print(f"      确定性命中：{len(hit_records)} 个字段")
    print(f"      待 LLM 仲裁（有候选）：{len(candidates_by_field)} 个字段")
    print(f"      两轮都无候选：{len(empty_fields)} 个字段")

    print("[3/6] LLM 逐字段仲裁（一个字段一次调用，不做批量合并，便于调试）...")
    arbitrated_records = []
    for field_name, candidates in candidates_by_field.items():
        record = llm_extractor.arbitrate(FIELD_MAP[field_name], candidates)
        arbitrated_records.append(record)
        status = "命中" if record.get("field_value") else "未命中"
        print(f"      [{status}] {field_name} <- {len(candidates)} 个候选")

    print("[4/6] 对仍无候选的单值字段，让 LLM 现场生成同义词再搜一轮...")
    # 只对通用单值字段做这一轮——表格/布尔字段是专用确定性解析器解析
    # 失败，不是"关键词没搜到"，用同义词扩展搜不出更多信息，没有意义。
    single_empty = [f for f in empty_fields if f.get("field_type") == "single"]
    other_empty = [f for f in empty_fields if f.get("field_type") != "single"]
    empty_records = []
    for field_def in single_empty:
        name = field_def["field_name"]
        tried = list(field_def.get("anchors", [])) + list(field_def.get("query_keywords", []))
        synonyms = llm_extractor.generate_synonyms(field_def, tried)
        candidates = rule_extractor.collect_candidates_with_keywords(field_def, sections, synonyms) if synonyms else []
        if candidates:
            record = llm_extractor.arbitrate(field_def, candidates)
            arbitrated_records.append(record)
            status = "命中" if record.get("field_value") else "未命中"
            print(f"      [{status}] {name} <- LLM生成同义词 {synonyms} -> {len(candidates)} 个候选")
        else:
            empty_records.append(llm_extractor.null_record(name, field_def.get("group", ""), "三轮检索均未找到候选"))
            print(f"      [空] {name} <- LLM生成同义词 {synonyms or '（生成失败）'} -> 0 个候选")

    empty_records += [
        llm_extractor.null_record(f["field_name"], f.get("group", ""), "确定性解析器未命中")
        for f in other_empty
    ]

    print("[5/6] LLM 归纳型字段（如项目概况）...")
    synthesis_fields = [f for f in FIELDS if f.get("field_type") == "synthesis"]
    synthesis_records = llm_extractor.extract(synthesis_fields, sections, full_text)

    print("[6/6] 写入字段库...")
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
