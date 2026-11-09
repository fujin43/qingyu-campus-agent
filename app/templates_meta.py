"""文档模板元数据：规划器与文档工具共用，避免循环依赖。"""
from __future__ import annotations

TEMPLATES: dict[str, dict] = {
    "activity_signup": {
        "name": "校园活动报名表",
        "filename": "活动报名表.docx",
        "aliases": ["活动报名表", "报名表", "活动表", "社团报名", "活动报名"],
        "description": "用于社团/校园活动报名，包含姓名、学号、学院、专业、班级、联系方式等字段。",
        "required": ["姓名", "学号", "学院", "专业", "班级", "活动名称", "活动日期", "联系电话"],
        "optional": ["备注"],
        "fields": [
            "姓名",
            "学号",
            "学院",
            "专业",
            "班级",
            "联系电话",
            "活动名称",
            "活动日期",
            "备注",
        ],
    },
    "leave_request": {
        "name": "学生请假申请表",
        "filename": "请假申请表.docx",
        "aliases": ["请假申请表", "请假表", "请假条", "请假单", "请假"],
        "description": "用于学生事假/病假申请，包含请假事由、起止时间、紧急联系人等字段。",
        "required": ["姓名", "学号", "学院", "请假事由", "开始时间", "结束时间"],
        "optional": ["班级", "请假天数", "紧急联系人", "联系电话", "辅导员"],
        "fields": [
            "姓名",
            "学号",
            "学院",
            "班级",
            "请假事由",
            "开始时间",
            "结束时间",
            "请假天数",
            "紧急联系人",
            "联系电话",
            "辅导员",
        ],
    },
}

FIELD_ALIASES: dict[str, str] = {
    "姓名": "姓名",
    "名字": "姓名",
    "学生姓名": "姓名",
    "学号": "学号",
    "学院": "学院",
    "院系": "学院",
    "专业": "专业",
    "班级": "班级",
    "联系电话": "联系电话",
    "联系方式": "联系电话",
    "手机": "联系电话",
    "手机号": "联系电话",
    "电话": "联系电话",
    "活动名称": "活动名称",
    "活动": "活动名称",
    "活动名": "活动名称",
    "活动日期": "活动日期",
    "举办日期": "活动日期",
    "备注": "备注",
    "请假事由": "请假事由",
    "事由": "请假事由",
    "原因": "请假事由",
    "开始时间": "开始时间",
    "结束时间": "结束时间",
    "请假天数": "请假天数",
    "天数": "请假天数",
    "紧急联系人": "紧急联系人",
    "联系人": "紧急联系人",
    "辅导员": "辅导员",
    "辅导员姓名": "辅导员",
    "申请日期": "申请日期",
}


def template_choices() -> list[dict]:
    return [
        {
            "id": key,
            "name": value["name"],
            "description": value["description"],
            "required": value["required"],
        }
        for key, value in TEMPLATES.items()
    ]


def find_template_id(text: str) -> str | None:
    text = text or ""
    for key, value in TEMPLATES.items():
        for alias in value["aliases"]:
            if alias in text:
                return key
    return None


def normalize_fields(fields: dict) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw_key, raw_value in (fields or {}).items():
        key = str(raw_key).strip()
        canonical = FIELD_ALIASES.get(key, key)
        value = str(raw_value).strip().strip("，,；;")
        if canonical and value:
            result[canonical] = value
    return result
