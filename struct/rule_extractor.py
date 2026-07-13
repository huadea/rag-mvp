"""
规则提取：对每个字段用锚点词 + 正则在章节列表中匹配。
返回：(命中记录列表, 未命中字段定义列表)
"""

import re
from schema import FIELDS

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


def extract(sections: list[dict]) -> tuple[list[dict], list[dict]]:
    hit_records: list[dict] = []
    miss_fields: list[dict] = []

    for field_def in FIELDS:
        record = _match_field(field_def, sections)
        if record:
            hit_records.append(record)
        else:
            miss_fields.append(field_def)

    return hit_records, miss_fields


def _match_field(field_def: dict, sections: list[dict]) -> dict | None:
    field_name = field_def["field_name"]
    anchors = field_def["anchors"]
    pattern = field_def["pattern"]
    group_name = field_def.get("group", "")

    if field_name == "标段/包号划分":
        return _match_bid_packages(field_def, sections)
    if field_name == "投标保证金":
        return _match_deposit_by_package(field_def, sections)
    if field_name == "招标控制价":
        return _match_control_price(field_def, sections)
    if field_name == "是否接受联合体投标":
        return _match_boolean(
            field_def, sections, keyword="联合体",
            accept_label="接受", reject_label="不接受",
        )
    if field_name == "是否允许分包":
        return _match_boolean(
            field_def, sections, keyword="分包",
            accept_label="允许", reject_label="不允许",
        )
    if field_name in ("开标时间与地点", "投标文件递交截止时间与地点"):
        return _match_time_and_location(field_def, sections)

    if not pattern:
        return None

    candidates = _collect_candidates(field_name, anchors, pattern, group_name, sections)
    if not candidates:
        return None
    best = dict(candidates[0])
    best.pop("_priority")
    best.pop("_anchor_index")
    return best


def _collect_candidates(
    field_name: str,
    anchors: list[str],
    pattern: str,
    group_name: str,
    sections: list[dict],
) -> list[dict]:
    """
    收集所有候选命中并按优先级排序，而不是"第一个命中就返回"——无关段落
    （如邮寄说明的脚注）里凑巧出现锚点词+冒号时，会在真正的字段声明之前
    被错误命中。排序：先按章节优先级，同优先级内再按锚点在 anchors 列表
    里的顺序（越靠前越具体，如"招标人名称"应优先于泛化的"招标人"）。
    返回的每个候选额外带 `_priority`/`_anchor_index`，调用方用完需自行 pop。
    """
    candidates: list[dict] = []
    for section in sections:
        text = section["content"]
        section_priority = 0 if _is_priority_section(section["title"]) else 1
        for anchor_index, anchor in enumerate(anchors):
            for line in text.splitlines():
                if anchor not in line:
                    continue
                # 只在锚点词之后的一小段窗口内找值，避免匹配到行内更靠后、
                # 与锚点无关的冒号（例如整段正文里出现的其他"字段：值"）
                idx = line.find(anchor)
                window = line[idx: idx + len(anchor) + 60]
                # 大段 HTML 表格常整行拼成一条"line"，窗口容易跨过当前
                # 单元格边界（</p></td>...）把下一格无关内容也吞进来，
                # 先在边界处截断，避免值里混入邻格文本。
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


def _match_time_and_location(field_def: dict, sections: list[dict]) -> dict | None:
    """
    "开标时间与地点""投标文件递交截止时间与地点"这类字段在源文档里通常是
    两个相邻但独立的条款（如"（一）...时间：xxx"和"（二）地点：xxx"），
    时间锚点的正则只能捕获同一行内的文本，永远抓不到下一行的地点。
    这里先用通用逻辑抓时间，再在同一章节里找紧随其后的"地点"行拼接上去。
    """
    field_name = field_def["field_name"]
    anchors = field_def["anchors"]
    pattern = field_def["pattern"]
    group_name = field_def.get("group", "")

    time_candidates = _collect_candidates(field_name, anchors, pattern, group_name, sections)
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
