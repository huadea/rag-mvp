"""
规则提取。字段分三类，处理方式不同：

- 结构化表格/布尔/时间地点字段（标段/包号划分、投标保证金、招标控制价、
  是否接受联合体投标、是否允许分包、开标时间与地点、投标文件递交截止
  时间与地点）：有固定格式可以精确解析，直接产出确定性结果，不经过
  候选收集，也不需要 LLM。

- 归纳型字段（synthesis）：不在这里处理，交给 llm_extractor 直接总结。

- 其余通用单值字段：只做"候选收集"——锚点命中就摘出候选段落（含相邻
  1~2 行扩展），锚点未命中则换 query_keywords 当同义词再搜一轮；
  收集到的候选不在这里挑答案，而是交给 llm_extractor 做仲裁。
  两轮都没有候选，直接判定为空，不需要调用 LLM。
"""

import re
from schema import FIELDS, FIELD_MAP

_TAG_RE = re.compile(r"<[^>]+>")


def _clean(value: str) -> str:
    """去掉残留的 HTML 标签（表格单元格解析后可能带 </p></td> 等），合并多余空白。"""
    value = _TAG_RE.sub("", value)
    return re.sub(r"\s+", " ", value).strip()


_BID_ROW_RE = re.compile(
    r"<tr><td><p>(\d+)</p></td><td><p>([^<]+)</p></td>"
    r"<td><p>([^<]+)</p></td><td><p>([\d,.]+)</p></td></tr>"
)
_BID_TOTAL_RE = re.compile(
    r"<tr><td colspan=\"3\"><p>合计</p></td><td><p>([\d,.]+)</p></td></tr>"
)

# 优先信任的章节：文档标题可能带 Markdown 加粗符号或 PDF 转换带来的逐字
# 空格（如"第一章  招 标 公 告"），比较前需要归一化，且用子串而非精确相等。
_PRIORITY_TITLES = ["投标须知前附表", "招标公告", "项目基本情况"]


def _is_priority_section(title: str) -> bool:
    normalized = title.replace(" ", "").replace("　", "")
    return any(p in normalized for p in _PRIORITY_TITLES)


# 有专用确定性解析器、不走"候选收集+LLM仲裁"流程的字段
_DETERMINISTIC_FIELDS = {
    "标段/包号划分",
    "投标保证金",
    "招标控制价",
    "是否接受联合体投标",
    "是否允许分包",
    "开标时间与地点",
    "投标文件递交截止时间与地点",
}


def extract(sections: list[dict]) -> tuple[list[dict], dict[str, list[dict]], list[dict]]:
    """
    返回 (确定性命中记录, {字段名: 候选列表}, 两轮都没候选的字段定义列表)。
    synthesis 类型字段不在这里处理，调用方需自行从 FIELDS 里过滤出来交给
    llm_extractor 做归纳。
    """
    hit_records: list[dict] = []
    candidates_by_field: dict[str, list[dict]] = {}
    empty_fields: list[dict] = []

    for field_def in FIELDS:
        name = field_def["field_name"]

        if field_def.get("field_type") == "synthesis":
            continue

        if name in _DETERMINISTIC_FIELDS:
            record = _match_deterministic(field_def, sections)
            if record:
                hit_records.append(record)
            else:
                empty_fields.append(field_def)
            continue

        candidates = collect_candidates_for_field(field_def, sections)
        if candidates:
            candidates_by_field[name] = candidates
        else:
            empty_fields.append(field_def)

    return hit_records, candidates_by_field, empty_fields


def _match_deterministic(field_def: dict, sections: list[dict]) -> dict | None:
    name = field_def["field_name"]
    if name == "标段/包号划分":
        return _match_bid_packages(field_def, sections)
    if name == "投标保证金":
        return _match_deposit_by_package(field_def, sections)
    if name == "招标控制价":
        return _match_control_price(field_def, sections)
    if name == "是否接受联合体投标":
        return _match_boolean(
            field_def, sections, keyword="联合体",
            accept_label="接受", reject_label="不接受",
        )
    if name == "是否允许分包":
        return _match_boolean(
            field_def, sections, keyword="分包",
            accept_label="允许", reject_label="不允许",
        )
    if name in ("开标时间与地点", "投标文件递交截止时间与地点"):
        return _match_time_and_location(field_def, sections)
    return None


# ── 候选收集（供 LLM 仲裁使用）───────────────────────────────────────

_MAX_CANDIDATES = 6


def collect_candidates_for_field(field_def: dict, sections: list[dict]) -> list[dict]:
    """
    候选粒度是"段落"：锚点/关键词所在行 + 前后各扩 1 行，而不是单行内的
    正则捕获值——这样"字段名和值分两行写"（如"招标人名称"和值同行，
    "地点"另起一行）也能被同一个候选段落覆盖到，不用为每种结构再写
    专用函数。最终不在这里挑答案，只负责把候选交给 llm_extractor.arbitrate。
    """
    field_name = field_def["field_name"]
    group_name = field_def.get("group", "")
    anchors = [a for a in field_def.get("anchors", []) if a]

    candidates = _collect_paragraph_candidates(field_name, group_name, anchors, sections)
    if candidates:
        return candidates[:_MAX_CANDIDATES]

    # 锚点一个都没命中，换 query_keywords 当同义词再搜一轮
    synonyms = [kw for kw in field_def.get("query_keywords", []) if kw and kw not in anchors]
    if not synonyms:
        return []
    candidates = _collect_paragraph_candidates(
        field_name, group_name, synonyms, sections, keyword_index_offset=len(anchors),
    )
    return candidates[:_MAX_CANDIDATES]


def collect_candidates_with_keywords(
    field_def: dict,
    sections: list[dict],
    keywords: list[str],
) -> list[dict]:
    """
    用调用方给定的关键词列表（如 LLM 现场生成的同义词）再收集一轮候选。
    供"锚点 + 预置同义词都未命中"时的第三轮兜底使用。
    """
    keywords = [kw for kw in keywords if kw]
    if not keywords:
        return []
    candidates = _collect_paragraph_candidates(
        field_def["field_name"], field_def.get("group", ""), keywords, sections,
    )
    return candidates[:_MAX_CANDIDATES]


def _collect_paragraph_candidates(
    field_name: str,
    group_name: str,
    keywords: list[str],
    sections: list[dict],
    keyword_index_offset: int = 0,
) -> list[dict]:
    candidates: list[dict] = []
    seen_texts: set[str] = set()

    for section in sections:
        # 只保留非空行参与"前后扩 1 行"，否则遇到空行会白白扩到一个空
        # 位置，抓不到隔着一个空行的下一句真正的值（比如"1. 评标方法"
        # 后面空一行才是"本次评标采用综合评分法"）。
        non_blank = [line for line in section["content"].splitlines() if line.strip()]
        section_priority = 0 if _is_priority_section(section["title"]) else 1
        for keyword_index, keyword in enumerate(keywords):
            for i, line in enumerate(non_blank):
                if keyword not in line:
                    continue
                start = max(0, i - 1)
                end = min(len(non_blank), i + 2)
                paragraph_lines = [_clean(l) for l in non_blank[start:end]]
                paragraph = "\n".join(pl for pl in paragraph_lines if pl)
                if not paragraph or paragraph in seen_texts:
                    continue
                seen_texts.add(paragraph)
                candidates.append({
                    "field_name": field_name,
                    "group_name": group_name,
                    "source_section": section["title"],
                    "source_text": paragraph,
                    "_priority": section_priority,
                    "_keyword_index": keyword_index_offset + keyword_index,
                })

    candidates.sort(key=lambda c: (c["_priority"], c["_keyword_index"]))
    for c in candidates:
        c.pop("_priority", None)
        c.pop("_keyword_index", None)
    return candidates


# ── 内部专用：时间+地点解析仍需要精确捕获日期数值，保留正则窗口版 ──────

def _collect_pattern_candidates(
    field_name: str,
    anchors: list[str],
    pattern: str,
    group_name: str,
    sections: list[dict],
) -> list[dict]:
    candidates: list[dict] = []
    for section in sections:
        text = section["content"]
        section_priority = 0 if _is_priority_section(section["title"]) else 1
        for anchor_index, anchor in enumerate(anchors):
            for line in text.splitlines():
                if anchor not in line:
                    continue
                idx = line.find(anchor)
                window = line[idx: idx + len(anchor) + 60]
                boundary = window.find("</p>")
                if boundary != -1:
                    window = window[:boundary]
                m = re.search(pattern, window)
                if not m:
                    continue
                value = _clean(m.group(1))
                if not value or len(value) > 200:
                    continue
                candidates.append({
                    "field_name": field_name,
                    "field_value": value,
                    "source_section": section["title"],
                    "source_text": line.strip(),
                    "confidence": "高",
                    "extraction_method": "rule",
                    "group_name": group_name,
                    "_priority": section_priority,
                    "_anchor_index": anchor_index,
                })

    candidates.sort(key=lambda c: (c["_priority"], c["_anchor_index"]))
    return candidates


_LOCATION_RE = re.compile(r"[:：]\s*(.+)")
_TIME_PATTERN = r"(\d{4}年\d{1,2}月\d{1,2}日[^\n]*)"


def _match_time_and_location(field_def: dict, sections: list[dict]) -> dict | None:
    """
    "开标时间与地点""投标文件递交截止时间与地点"这类字段在源文档里通常是
    两个相邻但独立的条款（如"（一）...时间：xxx"和"（二）地点：xxx"），
    时间锚点的正则只能捕获同一行内的文本，永远抓不到下一行的地点。
    这里先用通用逻辑抓时间，再在同一章节里找紧随其后的"地点"行拼接上去。
    """
    field_name = field_def["field_name"]
    anchors = field_def["anchors"]
    group_name = field_def.get("group", "")

    time_candidates = _collect_pattern_candidates(field_name, anchors, _TIME_PATTERN, group_name, sections)
    if not time_candidates:
        return None
    time_best = time_candidates[0]
    time_section = time_best["source_section"]
    time_value = time_best["field_value"]

    location_value = None
    location_line = None
    for section in sections:
        if section["title"] != time_section:
            continue
        for line in section["content"].splitlines():
            if "地点" not in line:
                continue
            idx = line.find("地点")
            window = line[idx: idx + len("地点") + 100]
            m = _LOCATION_RE.search(window)
            if m:
                location_value = _clean(m.group(1))
                location_line = line.strip()
                break
        break

    if location_value:
        field_value = f"{time_value}；地点：{location_value}"
        source_text = f"{time_best['source_text']}；{location_line}"
    else:
        field_value = time_value
        source_text = time_best["source_text"]

    return {
        "field_name": field_name,
        "field_value": field_value,
        "source_section": time_section,
        "source_text": source_text,
        "confidence": "高",
        "extraction_method": "rule",
        "group_name": group_name,
    }


def _match_bid_packages(field_def: dict, sections: list[dict]) -> dict | None:
    group_name = field_def.get("group", "")
    for section in sections:
        text = section["content"]
        if "标包号" not in text or "最高限价" not in text:
            continue
        rows = _BID_ROW_RE.findall(text)
        if not rows:
            continue

        items = [f"标包{no}｜{name}｜{qty}｜{price}元" for no, name, qty, price in rows]
        return {
            "field_name": "标段/包号划分",
            "field_value": "\n".join(items),
            "source_section": section["title"],
            "source_text": "；".join(
                f"标包{no}｜{name}｜{qty}｜{price}元" for no, name, qty, price in rows
            ),
            "confidence": "高",
            "extraction_method": "rule",
            "group_name": group_name,
        }

    return None


def _match_control_price(field_def: dict, sections: list[dict]) -> dict | None:
    """
    文档里往往没有"招标控制价"这个字面词，只在标包表格的"合计"行给出总额
    （术语等价于"招标控制价"）。复用标包表格定位逻辑，直接取合计行的值。
    """
    group_name = field_def.get("group", "")
    for section in sections:
        text = section["content"]
        if "标包号" not in text or "最高限价" not in text:
            continue
        m = _BID_TOTAL_RE.search(text)
        if not m:
            continue
        value = f"合计{m.group(1)}元"
        return {
            "field_name": "招标控制价",
            "field_value": value,
            "source_section": section["title"],
            "source_text": m.group(0),
            "confidence": "高",
            "extraction_method": "rule",
            "group_name": group_name,
        }
    return None


_DEPOSIT_RE = re.compile(r"标包(\d+)[：:]\s*[￥¥]\s*([\d,]+\.?\d*)")


def _match_deposit_by_package(field_def: dict, sections: list[dict]) -> dict | None:
    group_name = field_def.get("group", "")
    for section in sections:
        if "投标须知前附表" not in section["title"] and "投标保证金" not in section["content"]:
            continue
        text = section["content"]
        rows = _DEPOSIT_RE.findall(text)
        if not rows:
            continue
        items = [f"标包{no}｜¥{amount}" for no, amount in rows]
        return {
            "field_name": "投标保证金",
            "field_value": "\n".join(items),
            "source_section": section["title"],
            "source_text": "；".join(f"标包{no}：¥{amount}" for no, amount in rows),
            "confidence": "高",
            "extraction_method": "rule",
            "group_name": group_name,
        }
    return None


def _match_boolean(
    field_def: dict,
    sections: list[dict],
    keyword: str,
    accept_label: str,
    reject_label: str,
) -> dict | None:
    field_name = field_def["field_name"]
    group_name = field_def.get("group", "")
    reject_words = ["不接受", "不允许", "不得", "禁止", "不可以"]
    accept_words = ["接受", "允许", "可以"]

    for section in sections:
        text = section["content"]
        if keyword not in text:
            continue
        # 在关键词周围 200 字符窗口内判断接受/不接受
        idx = text.find(keyword)
        window = text[max(0, idx - 50): idx + 150]
        is_rejected = any(w in window for w in reject_words)
        is_accepted = any(w in window for w in accept_words)

        if is_rejected:
            value = reject_label
        elif is_accepted:
            value = accept_label
        else:
            continue  # 上下文不明确，交给 LLM

        # 找包含关键词的那一行作为来源原文
        source_line = next(
            (ln.strip() for ln in text.splitlines() if keyword in ln),
            window.strip(),
        )
        return {
            "field_name": field_name,
            "field_value": value,
            "source_section": section["title"],
            "source_text": source_line,
            "confidence": "高",
            "extraction_method": "rule",
            "group_name": group_name,
        }

    return None
