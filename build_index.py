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


def main(file_path: str) -> None:
    path = Path(file_path).resolve()
    if not path.exists():
        print(f"[错误] 文件不存在：{path}")
        sys.exit(1)
    if path.suffix.lower() != ".md":
        print(f"[错误] 仅支持 .md 文件，当前文件：{path.name}")
        sys.exit(1)

    doc_path = str(path)
    print(f"[1/4] 解析文档：{path.name}")
    sections = doc_parser.parse(doc_path)
    full_text = doc_parser.full_text(doc_path)
    print(f"      识别章节数：{len(sections)}")

    print("[2/4] 规则提取...")
    hit_records, miss_fields = rule_extractor.extract(sections)
    print(f"      规则命中：{len(hit_records)} 个字段")
    print(f"      待 LLM 补全：{len(miss_fields)} 个字段")

    print("[3/4] LLM 兜底提取...")
    llm_records = llm_extractor.extract(miss_fields, sections, full_text)
    llm_hit = sum(1 for r in llm_records if r.get("field_value") is not None)
    print(f"      LLM 补全：{llm_hit}/{len(llm_records)} 个字段有值")

    print("[4/4] 写入字段库...")
    all_records = hit_records + llm_records
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
