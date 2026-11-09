"""工作流引擎：把 Plan 变成可执行的多工具调用序列。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .advice import build_advice
from .templates_meta import TEMPLATES
from .tools.base import ToolContext, ToolRegistry, ToolResult
from .utils import mask_sensitive


@dataclass
class WorkflowOutput:
    reply: str
    suggestions: list[str] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)


def _fail_text(result: ToolResult, fallback: str) -> str:
    error = result.error or {}
    message = error.get("message") or result.summary or fallback
    return message


def _dedupe_citations(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = set()
    result = []
    for item in items:
        key = (item.get("type"), item.get("title"), item.get("entry"), item.get("time"))
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


class WorkflowEngine:
    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry
        self.handlers = {
            "weather_brief": self.weather_brief,
            "weather_air": self.weather_air,
            "campus_qa": self.campus_qa,
            "trip_plan": self.trip_plan,
            "doc_fill": self.doc_fill,
            "memory_update": self.memory_update,
            "help": self.help,
            "out_of_scope": self.out_of_scope,
            "clarify": self.clarify,
            "clarify_template": self.clarify,
            "cancel": self.cancel,
        }

    def run(self, plan, ctx: ToolContext) -> WorkflowOutput:
        handler = self.handlers.get(plan.workflow)
        if handler is None:
            return WorkflowOutput(
                reply="我暂时没有对应的处理流程，请换一种说法。",
                suggestions=["郑州现在天气", "图书馆几点关门", "帮我填活动报名表"],
            )
        if plan.workflow in {"clarify", "clarify_template"}:
            return handler(plan, ctx)
        return handler(plan, ctx)

    # ---------- 天气 ----------
    def weather_brief(self, plan, ctx: ToolContext) -> WorkflowOutput:
        self.registry.invoke("time.now", {}, ctx)
        result = self.registry.invoke(
            "weather.get",
            {
                "city": plan.args.get("city"),
                "when": plan.args.get("when", "today"),
                "preferred_hour": plan.args.get("preferred_hour"),
            },
            ctx,
        )
        if not result.ok:
            return WorkflowOutput(
                reply=(
                    "天气服务暂时不可用："
                    + _fail_text(result, "请稍后再试。")
                    + "\n你可以先查校园知识库，或稍后重试。"
                ),
                suggestions=["图书馆开放时间", "校车时刻表", "再查一次天气"],
                meta={"degraded": True, "error": result.error},
            )

        weather = result.data
        advice = build_advice(weather, ctx.memory.all_profile(ctx.session_id))
        reply = self._weather_text(weather, advice)
        return WorkflowOutput(
            reply=reply,
            suggestions=["那明天呢？", "需要带伞吗？", "图书馆现在开吗？", "生成出行计划卡"],
            meta={"weather": weather, "advice": advice},
        )

    def weather_air(self, plan, ctx: ToolContext) -> WorkflowOutput:
        self.registry.invoke("time.now", {}, ctx)
        weather_result = self.registry.invoke(
            "weather.get",
            {
                "city": plan.args.get("city"),
                "when": plan.args.get("when", "today"),
                "preferred_hour": plan.args.get("preferred_hour"),
            },
            ctx,
        )
        air_result = self.registry.invoke(
            "weather.air_quality", {"city": plan.args.get("city")}, ctx
        )
        lines = []
        if weather_result.ok:
            advice = build_advice(weather_result.data, ctx.memory.all_profile(ctx.session_id))
            lines.append(self._weather_text(weather_result.data, advice, include_window=False))
        else:
            lines.append("天气：" + _fail_text(weather_result, "暂时查不到。"))
        if air_result.ok:
            air = air_result.data
            lines.append(
                f"空气质量：{air.get('level')}（US AQI {air.get('us_aqi')}，"
                f"PM2.5 {air.get('pm2_5')} μg/m³）。"
            )
            if isinstance(air.get("us_aqi"), (int, float)) and air["us_aqi"] > 100:
                lines.append("建议减少长时间户外运动，敏感人群外出可戴口罩。")
        else:
            lines.append("空气质量：" + _fail_text(air_result, "暂时查不到。"))
        lines.append("")
        lines.append("数据时间：" + (weather_result.data.get("fetched_at", "") if weather_result.ok else "—") + "（Open-Meteo）")
        return WorkflowOutput(
            reply="\n".join(lines),
            suggestions=["今天适合跑步吗？", "明天天气", "生成出行计划卡"],
            meta={"air": air_result.data if air_result.ok else None},
        )

    def _weather_text(self, weather: dict[str, Any], advice: dict[str, Any], include_window: bool = True) -> str:
        current = weather.get("current") or {}
        daily = weather.get("daily") or {}
        window = weather.get("best_window") or {}
        city = weather.get("city", "郑州")
        label = weather.get("date_label", "今天")

        if current:
            head = (
                f"{city}{label}：此刻 {current.get('temperature')}℃，"
                f"体感 {current.get('apparent')}℃，{current.get('weather')}；"
                f"今日 {daily.get('temp_min')}–{daily.get('temp_max')}℃，"
                f"当天最大降水概率 {advice.get('rain_probability')}%。"
            )
        else:
            head = (
                f"{city}{label}：{daily.get('weather')}，"
                f"{daily.get('temp_min')}–{daily.get('temp_max')}℃，"
                f"当天最大降水概率 {advice.get('rain_probability')}%。"
            )

        lines = [
            head,
            f"• 穿衣：{advice['clothing']}（{advice['feel']}）",
            f"• 带伞：{advice['umbrella']}",
        ]
        if advice.get("wind_tip"):
            lines.append(f"• 风力：{advice['wind_tip']}")
        if advice.get("uv_tip"):
            lines.append(f"• 防晒：{advice['uv_tip']}")
        if advice.get("layer_tip"):
            lines.append(f"• 温差：{advice['layer_tip']}")
        if include_window and window:
            lines.append(
                f"• 更合适的窗口：{window.get('label')}，"
                f"降水概率约 {window.get('rain_probability')}%，体感 {window.get('temperature')}℃"
            )
        lines.append("")
        lines.append(
            f"数据时间：{weather.get('fetched_at', '')}"
            f"（{weather.get('source', 'Open-Meteo')}；"
            f"{'缓存数据' if weather.get('stale_cache') else '实时接口'}）"
        )
        return "\n".join(lines)

    # ---------- 校园知识库 ----------
    def campus_qa(self, plan, ctx: ToolContext) -> WorkflowOutput:
        result = self.registry.invoke(
            "campus.search", {"query": plan.args.get("query", ctx.user_text), "top_k": 2}, ctx
        )
        if not result.ok:
            return WorkflowOutput(
                reply="校园知识库暂时不可用：" + _fail_text(result, "请稍后再试。"),
                suggestions=["郑州天气", "帮我填活动报名表"],
            )
        data = result.data
        if not data.get("found"):
            return WorkflowOutput(
                reply=(
                    "校园知识库里暂时没有找到相关条目。\n"
                    "你可以换一个说法，或直接查看学校官网/公众号的最新通知。\n"
                    "我目前收录：图书馆、校车、食堂、校园卡、快递、报修、请假流程、场地、网络等。"
                ),
                suggestions=["图书馆开放时间", "校车时刻表", "宿舍报修怎么弄"],
                meta={"found": False},
            )
        lines = ["根据校园知识库："]
        for item in data["results"][:2]:
            lines.append(f"• {item['title']}：{item['answer']}")
            lines.append(f"  来源：{item['source']}（更新于 {item['updated']}）")
        lines.append("")
        lines.append("如果你需要，我也可以把请假/报名信息填进对应模板。")
        return WorkflowOutput(
            reply="\n".join(lines),
            suggestions=["帮我填请假申请表", "图书馆附近有打印店吗？", "生成出行计划卡"],
            meta={"results": data["results"]},
        )

    # ---------- 综合出行 ----------
    def trip_plan(self, plan, ctx: ToolContext) -> WorkflowOutput:
        args = plan.args
        destination = args.get("destination") or "校园"
        self.registry.invoke("time.now", {}, ctx)
        weather_result = self.registry.invoke(
            "weather.get",
            {
                "city": args.get("city"),
                "when": args.get("when", "today"),
                "preferred_hour": args.get("preferred_hour"),
            },
            ctx,
        )
        query = f"{destination} 开放时间" if destination != "校园" else ctx.user_text
        campus_result = self.registry.invoke("campus.search", {"query": query, "top_k": 2}, ctx)

        if not weather_result.ok and not campus_result.ok:
            return WorkflowOutput(
                reply=(
                    "这次出行规划没有完成：天气接口和校园知识库都暂时不可用。\n"
                    "请稍后重试，或分别查询天气/校园信息。"
                ),
                suggestions=["再试一次", "郑州天气", "图书馆开放时间"],
                meta={"degraded": True},
            )

        lines = ["已经按“天气 → 校园信息 → 出行卡”的顺序跑完："]
        advice = None
        window = {}
        if weather_result.ok:
            weather = weather_result.data
            advice = build_advice(weather, ctx.memory.all_profile(ctx.session_id))
            window = weather.get("best_window") or {}
            lines.append(
                f"• 天气：{weather.get('city')}{weather.get('date_label')} "
                f"{weather.get('daily', {}).get('temp_min')}–"
                f"{weather.get('daily', {}).get('temp_max')}℃，"
                f"{weather.get('daily', {}).get('weather')}，"
                f"当天最大降水概率 {advice.get('rain_probability')}%。"
            )
            if window:
                lines.append(
                    f"• 推荐窗口：{window.get('label')}（降水概率约 "
                    f"{window.get('rain_probability')}%，体感 {window.get('temperature')}℃）。"
                )
            lines.append(f"• 穿带：{advice['clothing']}；{advice['umbrella']}。")
        else:
            lines.append("• 天气：暂时不可用（" + _fail_text(weather_result, "接口异常") + "）。")

        campus_line = ""
        if campus_result.ok and campus_result.data.get("found"):
            top = campus_result.data["results"][0]
            campus_line = f"{top['title']}：{top['answer']}"
            lines.append(f"• 校园：{campus_line}")
        else:
            lines.append("• 校园：知识库未命中额外信息，建议出发前查看场馆公告。")

        artifact = None
        if args.get("make_card") and weather_result.ok:
            checklist = advice.get("checklist", []) if advice else ["校园卡", "水杯"]
            card_result = self.registry.invoke(
                "doc.plan_card",
                {
                    "city": weather_result.data.get("city", args.get("city", "郑州")),
                    "date_label": weather_result.data.get("date_label", "今天"),
                    "weather_line": (
                        f"{weather_result.data.get('daily', {}).get('weather')}，"
                        f"{weather_result.data.get('daily', {}).get('temp_min')}–"
                        f"{weather_result.data.get('daily', {}).get('temp_max')}℃，"
                        f"降水概率 {advice.get('rain_probability')}%"
                        if advice
                        else "天气数据已获取"
                    ),
                    "advice_line": advice["summary"] if advice else "",
                    "window_line": window.get("label", ""),
                    "knowledge_line": campus_line,
                    "checklist": checklist,
                    "destination": destination,
                },
                ctx,
            )
            if card_result.ok:
                artifact = card_result.data.get("artifact")
                lines.append(f"• 出行卡：已生成《{artifact['name']}》，可在右侧下载。")
            else:
                lines.append("• 出行卡：生成失败（" + _fail_text(card_result, "文档工具异常") + "）。")

        lines.append("")
        if window:
            lines.append(f"建议：{window.get('advice', '按计划出门')}；出发前再看一眼实时降水。")
        else:
            lines.append("建议：出发前再看一眼实时降水，带好校园卡和水杯。")
        return WorkflowOutput(
            reply="\n".join(lines),
            suggestions=["帮我填活动报名表", "图书馆开放时间", "明天天气"],
            meta={
                "weather": weather_result.data if weather_result.ok else None,
                "advice": advice,
                "campus": campus_result.data if campus_result.ok else None,
                "artifact": artifact,
            },
        )

    # ---------- 文档填写 ----------
    def doc_fill(self, plan, ctx: ToolContext) -> WorkflowOutput:
        template_id = plan.args.get("template_id")
        fields = plan.args.get("fields") or {}
        if template_id not in TEMPLATES:
            return WorkflowOutput(
                reply="我暂时没有这个模板。目前支持《校园活动报名表》和《学生请假申请表》。",
                suggestions=["帮我填活动报名表", "帮我填请假申请表"],
            )

        check = self.registry.invoke(
            "doc.validate", {"template_id": template_id, "fields": fields}, ctx
        )
        if not check.ok:
            return WorkflowOutput(
                reply="字段校验失败：" + _fail_text(check, "请检查填写内容。"),
                suggestions=["重新填写", "查看模板字段"],
            )

        data = check.data
        meta = TEMPLATES[template_id]
        if data.get("missing"):
            self.registry.invoke("memory.get_profile", {}, ctx)
            ctx.memory.set_pending(
                ctx.session_id,
                "doc_fill",
                {"template_id": template_id, "fields": data.get("fields", {})},
            )
            missing = data["missing"]
            if plan.args.get("resumed"):
                lead = "这一轮补上了部分信息，但还差："
            else:
                lead = f"可以，我来填《{meta['name']}》。还需要你补充："
            reply = (
                f"{lead}\n"
                + "、".join(missing)
                + "\n\n请按“字段=值”的格式发我，例如："
                + self._example_for(missing)
                + "\n已收到的字段我会先暂存，不会生成空表。"
            )
            return WorkflowOutput(
                reply=reply,
                suggestions=["取消填写", "查看模板字段", "先查明天天气"],
                meta={"missing": missing, "pending": True},
            )

        fill_result = self.registry.invoke(
            "doc.fill", {"template_id": template_id, "fields": data.get("fields", {})}, ctx
        )
        if not fill_result.ok:
            if (fill_result.error or {}).get("code") == "MISSING_FIELDS":
                ctx.memory.set_pending(
                    ctx.session_id,
                    "doc_fill",
                    {"template_id": template_id, "fields": data.get("fields", {})},
                )
            return WorkflowOutput(
                reply="文档生成失败：" + _fail_text(fill_result, "请稍后重试。"),
                suggestions=["重新填写", "查看模板字段"],
            )

        artifact = fill_result.data.get("artifact") or {}
        ctx.memory.clear_pending(ctx.session_id)
        display_fields = []
        for key, value in (artifact.get("fields") or {}).items():
            if key in {"申请日期", "备注"} or value in {"", "—"}:
                continue
            shown = mask_sensitive(value) if key in {"联系电话", "手机号"} else value
            display_fields.append(f"• {key}：{shown}")
        reply = (
            f"已按《{meta['name']}》生成文档，字段校验通过。\n"
            + "\n".join(display_fields)
            + f"\n\n文件：{artifact.get('filename', artifact.get('name', '文档') + '.docx')}\n"
            + "你可以在右侧“产物”区下载，打开后核对格式再提交。"
        )
        return WorkflowOutput(
            reply=reply,
            suggestions=["再填一份请假表", "查看明天天气", "图书馆开放时间"],
            meta={"artifact": artifact},
        )

    @staticmethod
    def _example_for(missing: list[str]) -> str:
        examples = {
            "姓名": "姓名=林晓",
            "学号": "学号=20231234",
            "学院": "学院=计算机学院",
            "专业": "专业=软件工程",
            "班级": "班级=软工2301",
            "联系电话": "联系电话=13800001234",
            "活动名称": "活动=秋季校园马拉松",
            "活动日期": "活动日期=2026-11-15",
            "请假事由": "事由=参加普通话水平测试",
            "开始时间": "开始时间=2026-11-12 08:00",
            "结束时间": "结束时间=2026-11-12 12:00",
        }
        return "，".join(examples.get(item, f"{item}=…") for item in missing[:3])

    # ---------- 记忆/帮助/兜底 ----------
    def memory_update(self, plan, ctx: ToolContext) -> WorkflowOutput:
        result = self.registry.invoke(
            "memory.set_profile",
            {"key": plan.args.get("key"), "value": plan.args.get("value")},
            ctx,
        )
        if not result.ok:
            return WorkflowOutput(reply="记忆保存失败：" + _fail_text(result, "请稍后重试。"))
        return WorkflowOutput(
            reply=(
                f"好的，已记住：{plan.args.get('key')} = {plan.args.get('value')}。\n"
                "下次查天气/看出行建议时我会优先使用这个偏好。"
            ),
            suggestions=["郑州天气", "帮我填请假表", "你能做什么"],
        )

    def help(self, plan, ctx: ToolContext) -> WorkflowOutput:
        return WorkflowOutput(
            reply=(
                "我是晴雨校园助手，专门处理校园出行与事务。\n"
                "• 查天气：实时温度、降水概率、穿衣/带伞建议、最佳出门窗口\n"
                "• 查校务：图书馆、校车、食堂、校园卡、快递、报修、请假流程\n"
                "• 填文档：校园活动报名表、学生请假申请表（DOCX 可下载）\n"
                "• 做计划：把天气 + 校园信息 + 随身清单组合成出行计划卡\n"
                "• 记偏好：默认城市、出发地、怕冷/怕热\n\n"
                "你可以直接说：“明天早上8点去图书馆，帮我安排一下并生成出行卡”。"
            ),
            suggestions=[
                "郑州现在天气需要带伞吗",
                "图书馆几点关门",
                "帮我填活动报名表",
                "明天去图书馆并生成出行卡",
            ],
        )

    def out_of_scope(self, plan, ctx: ToolContext) -> WorkflowOutput:
        if plan.args.get("kind") == "security":
            return WorkflowOutput(
                reply=(
                    "这个请求我不能配合：内部提示词、工具配置和系统指令不对外提供。\n"
                    "如果你愿意，我可以继续帮你查天气、找校园信息或填写文档。"
                ),
                suggestions=["郑州天气", "图书馆开放时间", "帮我填请假表"],
            )
        return WorkflowOutput(
            reply=(
                "这个请求超出了我的服务范围。我只处理校园出行与校园事务：\n"
                "查天气、查校园知识库、填写报名/请假文档、生成出行计划卡。\n"
                "如果你有这类需求，我可以马上帮你。"
            ),
            suggestions=["郑州天气", "图书馆开放时间", "帮我填活动报名表"],
        )

    def clarify(self, plan, ctx: ToolContext) -> WorkflowOutput:
        return WorkflowOutput(
            reply=plan.clarify or "我需要再确认一下：你想查天气、查校园信息，还是填写文档？",
            suggestions=["郑州天气", "图书馆开放时间", "帮我填活动报名表"],
        )

    def cancel(self, plan, ctx: ToolContext) -> WorkflowOutput:
        return WorkflowOutput(
            reply=plan.args.get("message", "已取消。"),
            suggestions=["郑州天气", "图书馆开放时间", "帮我填活动报名表"],
        )

