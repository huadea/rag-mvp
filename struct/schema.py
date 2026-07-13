"""
字段定义：字段名、正则规则、查询关键词、聚合分组。
每个字段是一个 dict，规则提取和查询路由都从这里读配置。
"""

FIELDS = [
    {
        "field_name": "项目名称",
        "field_type": "single",
        "group": "项目基础信息",
        "anchors": ["项目名称", "项目全称"],
        "pattern": r"[:：]\s*(.+)",
        "query_keywords": ["项目名称", "项目全称", "项目叫什么"],
    },
    {
        "field_name": "招标编号",
        "field_type": "single",
        "group": "项目基础信息",
        "anchors": ["招标编号", "项目编号", "招标文件编号"],
        "pattern": r"[:：]\s*([A-Za-z0-9\-]+)",
        "query_keywords": ["招标编号", "项目编号", "编号"],
    },
    {
        "field_name": "委托代理编号",
        "field_type": "single",
        "group": "项目基础信息",
        "anchors": ["委托代理编号", "代理编号"],
        "pattern": r"[:：]\s*(.+)",
        "query_keywords": ["委托代理编号", "代理编号"],
    },
    {
        "field_name": "项目概况",
        "field_type": "synthesis",
        "group": "项目基础信息",
        "anchors": ["项目概况", "项目简介"],
        "pattern": r"[:：]\s*(.+)",
        "query_keywords": ["项目概况", "项目简介", "项目大概是做什么"],
    },
    {
        "field_name": "招标人/采购人",
        "field_type": "single",
        "group": "项目基础信息",
        "anchors": ["招标人/采购人", "招标人名称", "招标人", "采购人"],
        "pattern": r"[:：]\s*(.+)",
        "query_keywords": ["招标人", "采购人", "招标人是谁", "采购人是谁"],
    },
    {
        "field_name": "资金来源及落实情况",
        "field_type": "single",
        "group": "项目基础信息",
        "anchors": ["资金来源及落实情况", "资金来源"],
        "pattern": r"[:：]\s*(.+)",
        "query_keywords": ["资金来源", "资金落实情况", "资金来源及落实情况"],
    },
    {
        "field_name": "标段/包号划分",
        "field_type": "table",
        "group": "项目基础信息",
        "anchors": ["标段/包号划分", "标包划分", "标段划分"],
        "pattern": None,  # 表格解析，逻辑在 rule_extractor 处理
        "query_keywords": ["标段", "包号划分", "标包划分", "有哪些标包", "标包信息"],
    },
    {
        "field_name": "投标文件递交截止时间与地点",
        "field_type": "single",
        "group": "项目基础信息",
        "anchors": ["投标文件递交截止时间", "递交截止时间", "投标截止时间"],
        "pattern": r"(\d{4}年\d{1,2}月\d{1,2}日[^\n]*)",
        "query_keywords": ["投标截止时间", "递交截止时间", "投标文件递交截止时间与地点"],
    },
    {
        "field_name": "开标时间与地点",
        "field_type": "single",
        "group": "项目基础信息",
        "anchors": ["开标时间"],
        "pattern": r"(\d{4}年\d{1,2}月\d{1,2}日[^\n]*)",
        "query_keywords": ["开标时间", "开标地点", "何时开标", "在哪开标"],
    },
    {
        "field_name": "投标有效期",
        "field_type": "single",
        "group": "项目基础信息",
        "anchors": ["投标有效期"],
        "pattern": r"[:：]\s*(.+)",
        "query_keywords": ["投标有效期", "投标有效期多久"],
    },
    {
        "field_name": "投标保证金",
        "field_type": "table",
        "group": "项目基础信息",
        "anchors": ["投标保证金"],
        "pattern": r"[:：]\s*(.+)",
        "query_keywords": ["投标保证金", "保证金要求", "保证金金额"],
    },
    {
        "field_name": "履约保证金",
        "field_type": "single",
        "group": "项目基础信息",
        "anchors": ["履约保证金"],
        "pattern": r"[:：]\s*(.+)",
        "query_keywords": ["履约保证金"],
    },
    {
        "field_name": "现场踏勘/答疑会",
        "field_type": "single",
        "group": "项目基础信息",
        "anchors": ["现场踏勘", "踏勘现场", "答疑会"],
        "pattern": r"[:：]\s*(.+)",
        "query_keywords": ["现场踏勘", "答疑会", "是否踏勘", "是否召开答疑会"],
    },
    {
        "field_name": "采购方式",
        "field_type": "single",
        "group": "项目基础信息",
        "anchors": ["采购方式", "招标方式"],
        "pattern": r"[:：]\s*(.+)",
        "query_keywords": ["采购方式", "招标方式"],
    },
    {
        "field_name": "招标范围",
        "field_type": "single",
        "group": "项目基础信息",
        "anchors": ["招标范围", "采购范围"],
        "pattern": r"[:：]\s*(.+)",
        "query_keywords": ["招标范围", "采购范围"],
    },
    {
        "field_name": "招标控制价",
        "field_type": "single",
        "group": "项目基础信息",
        "anchors": ["招标控制价", "最高限价合计", "预算金额"],
        "pattern": r"[:：]?\s*([\d,.]+\s*(?:万元|元|人民币)?)",
        "query_keywords": ["招标控制价", "预算金额", "最高限价合计"],
    },
    {
        "field_name": "投标竞争下浮率",
        "field_type": "single",
        "group": "项目基础信息",
        "anchors": ["投标竞争下浮率", "下浮率"],
        "pattern": r"[:：]\s*(.+)",
        "query_keywords": ["投标竞争下浮率", "下浮率"],
    },
    {
        "field_name": "是否接受联合体投标",
        "field_type": "single",
        "group": "项目基础信息",
        "anchors": ["联合体投标", "联合体"],
        "pattern": None,  # 布尔判断，逻辑在 rule_extractor 处理
        "query_keywords": ["联合体投标", "是否接受联合体", "联合体"],
    },
    {
        "field_name": "是否允许分包",
        "field_type": "single",
        "group": "项目基础信息",
        "anchors": ["分包"],
        "pattern": None,  # 布尔判断，逻辑在 rule_extractor 处理
        "query_keywords": ["分包", "是否允许分包"],
    },
    {
        "field_name": "评标方法",
        "field_type": "single",
        "group": "项目基础信息",
        "anchors": ["评标方法"],
        "pattern": r"[:：]\s*(.+)",
        "query_keywords": ["评标方法", "评标办法"],
    },
]

# 聚合查询分组：虚拟查询词 → 展开成多个字段名
AGGREGATE_GROUPS = {
    "项目基础信息": [f["field_name"] for f in FIELDS],
}

# 字段名 → 字段定义的快速查找表
FIELD_MAP = {f["field_name"]: f for f in FIELDS}
