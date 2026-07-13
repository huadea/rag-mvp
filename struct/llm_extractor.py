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


_EXTRACT_PROMPT = """你是一个信息提取助手，专门从招标文件中提取指定字段。

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

_SYNTHESIZE_PROMPT = """你是一个信息归纳助手，专门基于招标文件原文对指定字段做简要总结。

规则：
1. 只能基于给定的文档原文归纳，禁止编造原文中不存在的具体数字、金额、日期等事实性内容。
2. 归纳结果不超过150字。
3. source_text 必须列出你归纳时参考的1-2句原文依据（可以是非连续的多处摘录，用"；"分隔）。
4. 找不到任何相关内容时，field_value 必须返回 null。
5. 必须返回合法的 JSON，格式如下（不要加任何额外文字）：
{
  "field_value": "归纳后的内容 或 null",
  "source_section": "来源章节标题 或 null",
  "source_text": "参考的原文片段 或 null"
}"""

_ARBITRATE_PROMPT = """你是一个信息仲裁助手。你会收到若干个候选片段，其中最多有一个
是指定字段的正确取值，其余可能是无关的干扰内容（如脚注、举例、其他条款）。

规则：
1. 只能从给定候选中判断，不得使用候选之外的信息，也不得编造。
2. field_value 是从选中候选里提炼出的简洁答案（不是整段照抄），
   但不能包含候选原文之外的内容。
3. matched_candidate 是你选中的候选编号（从1开始的整数）；如果所有候选
   都不是该字段的有效答案，field_value 和 matched_candidate 都返回 null。
4. 必须返回合法的 JSON，格式如下（不要加任何额外文字）：
{
  "field_value": "提炼后的答案 或 null",
  "matched_candidate": 选中的候选编号（整数）或 null
}"""

# 优先装入 LLM 上下文/优先信任的章节。文档标题可能带 Markdown 加粗符号或
# PDF 转换带来的逐字空格（如"第一章  招 标 公 告"），比较前需要归一化。
_PRIORITY_TITLES = ["投标须知前附表", "招标公告", "项目基本情况"]


def _is_priority_section(title: str) -> bool:
    normalized = title.replace(" ", "").replace("　", "")
    return any(p in normalized for p in _PRIORITY_TITLES)


def extract(
    miss_fields: list[dict],
    sections: list[dict],
    full_text: str,
) -> list[dict]:
    if not miss_fields:
        return []

    records: list[dict] = []
    for field_def in miss_fields:
        # 按字段单独装填上下文：优先塞入真正包含该字段锚点词的章节，而不是
        # 所有字段共用一份通用上下文——通用上下文在长文档里会被挤爆，导致
        # 锚点词明明在文档中出现过、却因为没被塞进预算而始终提取不到。
        context = _build_context(field_def, sections, full_text)
        record = _extract_one(field_def, context, full_text)
        records.append(record)

    return records


def _extract_one(field_def: dict, context: str, full_text: str) -> dict:
    field_name = field_def["field_name"]
    group_name = field_def.get("group", "")
    system_prompt = _SYNTHESIZE_PROMPT if field_def.get("field_type") == "synthesis" else _EXTRACT_PROMPT

    user_prompt = f"""请从以下招标文件中提取字段：【{field_name}】

文档内容：
{context}

返回 JSON，字段：field_value、source_section、source_text。"""

    try:
        resp = _get_client().chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0,
        )
        raw = resp.choices[0].message.content.strip()
        data = _parse_json(raw)
    except Exception as e:
        return null_record(field_name, group_name, f"LLM调用失败: {e}")

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


def arbitrate(field_def: dict, candidates: list[dict]) -> dict:
    """
    给定规则收集到的候选段落列表（每个候选已经是"锚点/同义词所在段落 +
    前后扩展"的完整原文），一次调用 LLM，让它从候选里判断哪个是正确答案，
    而不是像规则那样靠启发式排序硬选一个——候选本身已经是真实原文摘录，
    LLM 只做"选择题"而不是自由抽取，幻觉空间比整章节自由问答小得多。
    """
    field_name = field_def["field_name"]
    group_name = field_def.get("group", "")

    candidate_block = "\n\n".join(
        f"候选{i + 1}（来源章节：{c['source_section']}）：\n{c['source_text']}"
        for i, c in enumerate(candidates)
    )
    user_prompt = f"""请判断以下候选片段中，哪一个是【{field_name}】字段的正确取值。

{candidate_block}

返回 JSON，字段：field_value、matched_candidate。"""

    try:
        resp = _get_client().chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": _ARBITRATE_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0,
        )
        raw = resp.choices[0].message.content.strip()
        data = _parse_json(raw)
    except Exception as e:
        return null_record(field_name, group_name, f"LLM调用失败: {e}")

    field_value = data.get("field_value")
    matched_index = data.get("matched_candidate")

    source_section = None
    source_text = None
    if isinstance(matched_index, int) and 1 <= matched_index <= len(candidates):
        # 来源以程序自己保存的候选原文为准，不用模型自己复述的内容，
        # 避免"答案本身没编，但引用的来源被模型顺手改写了"这种问题。
        chosen = candidates[matched_index - 1]
        source_section = chosen["source_section"]
        source_text = chosen["source_text"]
    else:
        field_value = None

    confidence = "高" if field_value and source_text else "低"

    return {
        "field_name": field_name,
        "field_value": field_value,
        "source_section": source_section,
        "source_text": source_text,
        "confidence": confidence,
        "extraction_method": "llm_arbitrate",
        "group_name": group_name,
    }


def _parse_json(raw: str) -> dict:
    # 去掉可能的 markdown 代码块包裹
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    return json.loads(raw)


def null_record(field_name: str, group_name: str, reason: str = "") -> dict:
    return {
        "field_name": field_name,
        "field_value": None,
        "source_section": None,
        "source_text": reason or None,
        "confidence": "低",
        "extraction_method": "llm",
        "group_name": group_name,
    }


def _build_context(field_def: dict, sections: list[dict], full_text: str) -> str:
    # MVP 阶段直接用全文，控制在 8000 字以内避免超 token
    if len(full_text) <= 8000:
        return full_text

    anchors = [a for a in field_def.get("anchors", []) if a]

    def _section_priority(s: dict) -> int:
        # 0：章节内容里真的出现了该字段的锚点词，最可能是答案所在地
        # 1：通用的高信任章节（投标须知前附表等）
        # 2：其余章节，按文档原有顺序垫底（stable sort 保序）
        if any(a in s["content"] for a in anchors):
            return 0
        if _is_priority_section(s["title"]):
            return 1
        return 2

    ordered = sorted(sections, key=_section_priority)
    parts = []
    total = 0
    for s in ordered:
        chunk = f"## {s['title']}\n{s['content']}"
        if total + len(chunk) > 8000:
            continue  # 这章太大放不下，跳过但不终止，后面更小的章节仍有机会塞进去
        parts.append(chunk)
        total += len(chunk)
    return "\n\n".join(parts)
