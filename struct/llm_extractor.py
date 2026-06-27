"""
LLM 兜底提取：对规则未命中的字段调用 DeepSeek，要求返回 JSON。
提取后对 source_text 做字符串包含校验，失败则降级为低置信度。
"""

import json
import os
import re

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(
            api_key=os.getenv("DEEPSEEK_API_KEY"),
            base_url="https://api.deepseek.com",
        )
    return _client


_SYSTEM_PROMPT = """你是一个信息提取助手，专门从招标文件中提取指定字段。

规则：
1. 只从给定的文档原文中提取，不得推断或编造。
2. source_text 必须是文档中逐字存在的原文片段，不能转述。
3. 找不到时，field_value 必须返回 null，source_section 和 source_text 也返回 null。
4. 必须返回合法的 JSON，格式如下（不要加任何额外文字）：
{
  "field_value": "提取到的值 或 null",
  "source_section": "来源章节标题 或 null",
  "source_text": "原文片段 或 null"
}"""


def extract(
    miss_fields: list[dict],
    sections: list[dict],
    full_text: str,
) -> list[dict]:
    if not miss_fields:
        return []

    records: list[dict] = []
    # 把章节拼成带标题的上下文，优先使用全文（MVP 阶段文档不大）
    context = _build_context(sections, full_text)

    for field_def in miss_fields:
        record = _extract_one(field_def, context, full_text)
        records.append(record)

    return records


def _extract_one(field_def: dict, context: str, full_text: str) -> dict:
    field_name = field_def["field_name"]
    group_name = field_def.get("group", "")

    user_prompt = f"""请从以下招标文件中提取字段：【{field_name}】

文档内容：
{context}

返回 JSON，字段：field_value、source_section、source_text。"""

    try:
        resp = _get_client().chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0,
        )
        raw = resp.choices[0].message.content.strip()
        data = _parse_json(raw)
    except Exception as e:
        return _null_record(field_name, group_name, f"LLM调用失败: {e}")

    field_value = data.get("field_value")
    source_section = data.get("source_section")
    source_text = data.get("source_text")

    # source_text 校验：必须是原文的真实子串
    if source_text and source_text not in full_text:
        confidence = "低"
    elif field_value is None:
        confidence = "低"
    else:
        confidence = "中"

    return {
        "field_name": field_name,
        "field_value": field_value,
        "source_section": source_section,
        "source_text": source_text,
        "confidence": confidence,
        "extraction_method": "llm",
        "group_name": group_name,
    }


def _parse_json(raw: str) -> dict:
    # 去掉可能的 markdown 代码块包裹
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    return json.loads(raw)


def _null_record(field_name: str, group_name: str, reason: str = "") -> dict:
    return {
        "field_name": field_name,
        "field_value": None,
        "source_section": None,
        "source_text": reason or None,
        "confidence": "低",
        "extraction_method": "llm",
        "group_name": group_name,
    }


def _build_context(sections: list[dict], full_text: str) -> str:
    # MVP 阶段直接用全文，控制在 8000 字以内避免超 token
    if len(full_text) <= 8000:
        return full_text
    # 超长时拼章节标题 + 内容（截断）
    parts = []
    total = 0
    for s in sections:
        chunk = f"## {s['title']}\n{s['content']}"
        if total + len(chunk) > 8000:
            break
        parts.append(chunk)
        total += len(chunk)
    return "\n\n".join(parts)
