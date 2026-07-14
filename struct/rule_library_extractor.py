"""
从招标文件里提取"资格 / 废标 / 无效 / 响应 / 承诺"五类内容，产出统一的
规则表，而不是四份互相重叠、还需要人工再整理一遍的独立检索结果。

设计对应五步：
1. 文档结构化——按章节切分并归类到"区域"（投标须知正文/前附表/用户
   需求书/投标文件格式模板/评标办法/合同条款），同一句话落在不同区域
   含义不同（"我方保证……"在承诺书模板里是承诺，在合同条款里是履约
   条款），不看区域就没法分类。
2. 每一类都是"关键词 + 结构模式"的触发规则，不是单纯关键词命中。
3. 逐句扫描，按固定执行顺序做五类触发判断。
4. 候选去重与过滤：同文本合并、跨类关联成一条规则而不是分散存多份、
   按区域过滤掉误命中（比如合同条款里的承诺句）、程序性裁定单独标注。
5. 输出一份规则表，而不是资格/无效/响应/承诺四份并列文档。

本文件独立于 rule_extractor.py/schema.py 等既有代码，只只读地复用
doc_parser.parse() 做章节切分，不修改、不依赖其余现有模块的内部结构。
"""

import re
from dataclasses import dataclass, field

import doc_parser

_TAG_RE = re.compile(r"<[^>]+>")


def _clean(text: str) -> str:
    text = _TAG_RE.sub("", text)
    return re.sub(r"\s+", " ", text).strip()


def _normalize(text: str) -> str:
    """去重用的归一化 key：忽略空白差异。"""
    return re.sub(r"\s+", "", text)


# ── 第一步：区域分类 ─────────────────────────────────────────────────

# 顺序有意义：更具体的模式排在前面（"投标须知前附表"包含"投标须知"这个
# 子串，必须先判断前附表，否则会被"投标须知正文"这条规则先吞掉）。
_REGION_RULES: list[tuple[str, list[str]]] = [
    ("投标人须知前附表", ["投标须知前附表", "须知前附表"]),
    ("投标文件格式", [
        "投标文件格式", "投标函", "承诺书", "资格声明函", "授权委托书",
        "法定代表人身份证明", "开标一览表",
    ]),
    ("评标办法", [
        "评标办法", "评标方法", "初步评审", "详细评审", "评审表", "评分标准",
    ]),
    ("合同条款", ["合同条款", "合同书格式", "合同书", "协议书"]),
    ("用户需求书", ["用户需求书", "技术要求", "商务要求", "用 户 需 求 书"]),
    ("投标须知正文", ["投标须知", "投 标 须 知", "招标公告", "招 标 公 告"]),
]


def _classify_region(section_title: str) -> str:
    normalized = section_title.replace(" ", "").replace("　", "").replace("*", "")
    for region, keywords in _REGION_RULES:
        for kw in keywords:
            if kw.replace(" ", "") in normalized:
                return region
    return "其他"


# ── 分句 ─────────────────────────────────────────────────────────────

_SENTENCE_SPLIT_LEN = 150


def _split_sentences(content: str) -> list[str]:
    """
    先按非空行切（大多数条款本来就是独立成行），行内如果混了多句
    （常见于把整段/整表拼成一行的情况）再按中文句号进一步切分，
    避免把一大段无关内容当成一句一起判断。
    """
    sentences: list[str] = []
    for line in content.splitlines():
        line = _clean(line)
        if not line:
            continue
        if len(line) <= _SENTENCE_SPLIT_LEN:
            sentences.append(line)
            continue
        for piece in re.split(r"(?<=[。；])", line):
            piece = piece.strip()
            if piece:
                sentences.append(piece)
    return sentences


# ── 第二步：五类触发规则 ─────────────────────────────────────────────

_CONCLUSION_WORDS = [
    "无效投标", "投标无效", "视为无效", "拒收", "拒绝收取", "不予受理",
    "认定其投标无效", "废标", "按无效投标处理", "作废标处理", "予以废标",
]
_CONDITION_WORDS = ["未", "超过", "有下列情形之一", "不得", "不允许", "不符合", "逾期", "无效"]

_PROCEDURAL_RE = re.compile(r"评标委员会(认定|决定|视为|有权|按照少数服从多数)")

_TOPIC_KEYWORDS: list[tuple[str, list[str]]] = [
    ("保证金", ["保证金"]),
    ("文件形式", ["密封", "签字", "盖章", "页码", "装订", "签署"]),
    ("资格证明", ["资格", "许可证", "信用中国", "营业执照", "联合体", "授权书"]),
    ("技术响应", ["★", "▲", "响应", "偏离"]),
    ("串标围标", ["串通", "围标", "串标", "恶意竞争"]),
]


def _infer_topic(sentence: str) -> str:
    for topic, keywords in _TOPIC_KEYWORDS:
        if any(kw in sentence for kw in keywords):
            return topic
    return "其他"


def _match_response(sentence: str) -> dict | None:
    """③ 响应类：★/▲ 必须分开处理（一票否决 vs 扣分），默认响应规则单独标注。"""
    if any(kw in sentence for kw in ["视同完全响应", "视为完全响应"]):
        return {
            "topic": "技术响应-默认规则",
            "conclusion": "默认视为完全响应",
            "severity": "无",
        }
    if "★" in sentence:
        return {"topic": "技术响应", "conclusion": "未响应/负偏离则无效", "severity": "一票否决"}
    if "▲" in sentence:
        return {"topic": "技术响应", "conclusion": "未响应/负偏离则扣分", "severity": "扣分"}
    if any(kw in sentence for kw in ["实质性响应", "响应表", "负偏离"]):
        return {"topic": "技术响应", "conclusion": "需人工核查", "severity": "无"}
    return None


def _match_invalid(sentence: str) -> dict | None:
    """② 无效/废标类：条件从句 + 无效类结论词成对出现，废标并入无效。"""
    if not any(w in sentence for w in _CONCLUSION_WORDS):
        return None
    has_condition = any(w in sentence for w in _CONDITION_WORDS)
    return {
        "topic": _infer_topic(sentence),
        "conclusion": "无效",
        "severity": "一票否决" if has_condition else "争议裁定",
    }


_COMMITMENT_RE = re.compile(r"(我方|乙方|投标人)(同意|保证|承诺|接受)")


def _match_commitment(sentence: str, region: str) -> tuple[dict | None, bool]:
    """
    ④ 承诺类：第一人称声明句，必须限定在投标文件格式模板区域。
    返回 (命中记录 或 None, 是否因区域不符被排除)。
    """
    if not _COMMITMENT_RE.search(sentence):
        return None, False
    if region != "投标文件格式":
        return None, True  # 命中了句式，但区域是合同条款等，排除
    return {
        "topic": "承诺声明",
        "conclusion": "核对投标文件是否附有对应声明",
        "severity": "无",
    }, False


_QUALIFICATION_RE = re.compile(r"具有.{0,6}(资格|能力)|信用中国|联合体|营业执照|许可证|授权书")
_QUALIFICATION_REGIONS = {"投标须知正文", "投标人须知前附表", "投标文件格式"}


def _match_qualification(sentence: str, region: str) -> dict | None:
    """① 资格类：证明主体资格的条款，限定在资格相关区域，不扫合同条款。"""
    if not _QUALIFICATION_RE.search(sentence):
        return None
    if region not in _QUALIFICATION_REGIONS:
        return None
    return {"topic": "资格证明", "conclusion": "核对是否提供对应证明文件", "severity": "无"}


# ── 第三/四步：逐句处理 + 合并 + 过滤 ────────────────────────────────

@dataclass
class RuleEntry:
    clause_text: str
    topic: str
    conclusion: str
    severity: str
    source_region: str
    source_section: str
    origin_tags: list[str] = field(default_factory=list)


def _process_sentence(sentence: str, region: str, section_title: str) -> tuple[RuleEntry | None, dict | None]:
    """返回 (规则条目 或 None, 被排除的合同履约条款记录 或 None)。"""
    tags: list[str] = []
    hits: list[dict] = []

    resp = _match_response(sentence)
    if resp:
        tags.append("响应")
        hits.append(resp)

    inv = _match_invalid(sentence)
    if inv:
        tags.append("无效/废标")
        hits.append(inv)

    commit, excluded_by_region = _match_commitment(sentence, region)
    if commit:
        tags.append("承诺")
        hits.append(commit)
    elif excluded_by_region:
        return None, {
            "clause_text": sentence,
            "source_region": region,
            "source_section": section_title,
            "reason": f"命中承诺句式但区域为「{region}」，非投标文件格式模板，归入合同履约条款库",
        }

    qual = _match_qualification(sentence, region)
    if qual:
        tags.append("资格")
        hits.append(qual)

    if not hits:
        return None, None

    # 跨类关联而非跨类重复：无效类是"结果标签"，如果同句还命中了资格/
    # 响应/承诺的触发结构，topic 取内容来源那一条，conclusion/severity
    # 以无效结论为准（因为它代表"违反了前面那条会怎样"）。
    invalid_hit = next((h for h in hits if h["conclusion"] == "无效"), None)
    content_hits = [h for h in hits if h is not invalid_hit]
    base = content_hits[0] if content_hits else invalid_hit

    if invalid_hit:
        conclusion = invalid_hit["conclusion"]
        severity = invalid_hit["severity"]
    else:
        conclusion = base["conclusion"]
        severity = base["severity"]
    topic = base["topic"]

    # 程序性裁定：触发权在评标委员会而非系统自动判断，单独标注，
    # 不能和"系统可自动判定"的规则混在一起。
    if _PROCEDURAL_RE.search(sentence):
        topic = "程序性裁定"
        conclusion = "需人工核查"
        severity = "争议裁定"

    entry = RuleEntry(
        clause_text=sentence,
        topic=topic,
        conclusion=conclusion,
        severity=severity,
        source_region=region,
        source_section=section_title,
        origin_tags=tags,
    )
    return entry, None


class RuleLibraryExtractor:
    """对外主入口：给定招标文件（.md），提取五类内容合并成一份规则表。"""

    def extract(self, md_path: str) -> dict:
        sections = doc_parser.parse(md_path)

        rules: list[RuleEntry] = []
        contract_clauses: list[dict] = []
        seen: set[tuple[str, str]] = set()

        # doc_parser 把每个标题都拆成扁平的独立章节，子章节标题本身往往
        # 不会重复上级章节的名字（比如"1.1.7 纪律与保密事项"不会写"投标
        # 须知"四个字），单看自己的标题分不出区域。这里按文档原有顺序继承
        # 最近一次成功识别出的区域，直到遇到下一个能明确匹配的标题为止。
        current_region = "其他"

        for section in sections:
            own_region = _classify_region(section["title"])
            if own_region != "其他":
                current_region = own_region
            region = current_region

            for sentence in _split_sentences(section["content"]):
                entry, excluded = _process_sentence(sentence, region, section["title"])

                if excluded:
                    contract_clauses.append(excluded)
                    continue
                if entry is None:
                    continue

                # 同文本合并：按"条件内容+结论词"整体做完全匹配去重，
                # 而不是简单的字符串查重复（防止同一句免责声明在每条
                # 需求后面重复出现时被当成多条规则）。
                key = (_normalize(entry.clause_text), entry.conclusion)
                if key in seen:
                    continue
                seen.add(key)
                rules.append(entry)

        return {
            "rules": [vars(r) for r in rules],
            "contract_clauses": contract_clauses,
        }


# ── CLI ──────────────────────────────────────────────────────────────

def _format_markdown(result: dict) -> str:
    rules = result["rules"]
    lines = [f"# 规则库（共 {len(rules)} 条）", ""]
    lines.append("| 主题 | 触发结论 | 严重性 | 来源区域 | 来源章节 | 原始检索标签 | 条款原文 |")
    lines.append("|---|---|---|---|---|---|---|")
    for r in rules:
        clause = r["clause_text"].replace("|", "\\|")
        if len(clause) > 80:
            clause = clause[:80] + "…"
        tags = "、".join(r["origin_tags"])
        lines.append(
            f"| {r['topic']} | {r['conclusion']} | {r['severity']} | "
            f"{r['source_region']} | {r['source_section']} | {tags} | {clause} |"
        )

    contract_clauses = result["contract_clauses"]
    lines.append("")
    lines.append(f"## 合同履约条款库（已排除，共 {len(contract_clauses)} 条，与废标判定无关）")
    lines.append("")
    for c in contract_clauses[:20]:
        clause = c["clause_text"].replace("|", "\\|")
        if len(clause) > 100:
            clause = clause[:100] + "…"
        lines.append(f"- [{c['source_section']}] {clause}")
    if len(contract_clauses) > 20:
        lines.append(f"- …（共 {len(contract_clauses)} 条，仅展示前 20 条）")

    return "\n".join(lines) + "\n"


def main(md_path: str, output_path: str | None = None) -> None:
    result = RuleLibraryExtractor().extract(md_path)
    md = _format_markdown(result)
    if output_path:
        from pathlib import Path
        Path(output_path).write_text(md, encoding="utf-8")
        print(f"已写入：{output_path}（{len(result['rules'])} 条规则）")
    else:
        print(md)


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("用法：uv run rule_library_extractor.py <招标文件.md> [输出.md]")
        sys.exit(1)
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
