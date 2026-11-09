"""校园知识库检索工具（轻量 RAG：关键词 + 字符重叠排序）。"""
from __future__ import annotations

import re
from typing import Any

from ..config import FAQ_PATH
from ..utils import read_json
from .base import ToolContext, ToolParam, ToolSpec, ToolRegistry


def _grams(text: str) -> set[str]:
    text = re.sub(r"\s+", "", str(text or "").lower())
    grams: set[str] = set()
    for i in range(len(text) - 1):
        pair = text[i : i + 2]
        if re.search(r"[\u4e00-\u9fa5a-z0-9]", pair):
            grams.add(pair)
    return grams


def _load_entries() -> list[dict[str, Any]]:
    payload = read_json(FAQ_PATH, {"entries": []})
    return payload.get("entries", [])


def search(ctx: ToolContext, query: str, top_k: int = 2) -> dict[str, Any]:
    query = (query or "").strip()
    if not query:
        return {
            "found": False,
            "results": [],
            "query": query,
            "_summary": "知识库检索需要一个问题关键词。",
        }

    q_grams = _grams(query)
    scored: list[dict[str, Any]] = []
    for entry in _load_entries():
        keyword_hits = sum(1 for kw in entry.get("keywords", []) if kw and kw in query)
        title_overlap = len(q_grams & _grams(entry.get("title", "")))
        answer_overlap = len(q_grams & _grams(entry.get("answer", "")))
        category_overlap = len(q_grams & _grams(entry.get("category", "")))
        score = keyword_hits * 4.0 + title_overlap * 2.2 + answer_overlap * 0.7 + category_overlap
        if score <= 0:
            continue
        scored.append(
            {
                "id": entry["id"],
                "title": entry["title"],
                "category": entry.get("category", ""),
                "answer": entry["answer"],
                "source": entry.get("source", "校园知识库"),
                "updated": entry.get("updated", ""),
                "contact": entry.get("contact", ""),
                "score": round(score, 2),
                "confidence": round(min(0.98, 0.45 + score / 18), 2),
            }
        )

    scored.sort(key=lambda item: item["score"], reverse=True)
    results = scored[: max(1, min(top_k, 4))]
    found = bool(results and results[0]["score"] >= 1.2)

    if found:
        for item in results:
            ctx.citations.append(
                {
                    "type": "campus_kb",
                    "title": item["source"],
                    "entry": item["title"],
                    "updated": item["updated"],
                }
            )

    return {
        "found": found,
        "query": query,
        "results": results if found else [],
        "candidates": results if not found else [],
        "kb_updated": read_json(FAQ_PATH, {}).get("meta", {}).get("updated", ""),
        "_summary": (
            f"命中 {len(results)} 条校园知识："
            + "、".join(item["title"] for item in results)
            if found
            else "知识库暂未收录该问题。"
        ),
    }


def register(registry: ToolRegistry) -> None:
    registry.register(
        ToolSpec(
            name="campus.search",
            description="检索校园知识库，回答图书馆、校车、食堂、校园卡、快递、报修、请假、场地、网络等问题，并返回来源与更新时间。",
            category="knowledge",
            params=[
                ToolParam("query", "string", "要检索的校园问题", required=True),
                ToolParam("top_k", "integer", "返回条数，1-4", required=False, default=2),
            ],
            handler=search,
            timeout_s=3,
        )
    )
