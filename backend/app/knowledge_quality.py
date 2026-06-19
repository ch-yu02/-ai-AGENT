"""Shared quality gates for knowledge graph extraction.

The LLM prompts try to avoid noisy graph items, but the graph layer still needs
deterministic guards. These helpers keep low-value entity filtering consistent
across realtime extraction, Markdown notes extraction, and graph persistence.
"""

from __future__ import annotations

import re


LOW_VALUE_ENTITY_KEYS = {
    "",
    "一个",
    "一些",
    "这个",
    "那个",
    "这些",
    "那些",
    "本节",
    "本课",
    "该课",
    "内容",
    "相关内容",
    "主要内容",
    "核心内容",
    "具体内容",
    "知识",
    "知识点",
    "概念",
    "重点",
    "要点",
    "难点",
    "考点",
    "得分点",
    "支点",
    "课程",
    "课堂",
    "主题",
    "课程主题",
    "课程目标",
    "讲课思路",
    "学习目标",
    "老师",
    "同学",
    "大家",
    "我们",
    "问题",
    "例子",
    "方法",
    "部分",
    "方面",
    "东西",
    "特点",
    "影响",
    "原因",
    "背景",
    "意义",
    "作用",
    "过程",
    "结果",
    "失败",
    "要求",
    "任务",
    "章节",
    "小节",
    "标题",
    "小标题",
}

GENERIC_SUFFIXES = ("知识点", "概念", "定义", "方法", "课程", "内容", "考点")
GENERIC_SHORT_SUFFIXES = (
    "内容",
    "问题",
    "例子",
    "方面",
    "部分",
    "特点",
    "影响",
    "原因",
    "背景",
    "意义",
    "作用",
    "过程",
    "结果",
    "目标",
    "要求",
    "任务",
    "主线",
    "思路",
)
GENERIC_PREFIXES = (
    "本节",
    "本节课",
    "本课",
    "这节课",
    "这一节",
    "这一部分",
    "这部分",
    "老师讲",
    "老师讲解",
    "课程",
    "课堂",
)

PLACEHOLDER_RE = re.compile(
    r"^(?:e|ent|entity|node|concept|item|id)[_\-]?\d+$",
    flags=re.IGNORECASE,
)
ORDINAL_ONLY_RE = re.compile(
    r"^第[一二三四五六七八九十百千万0-9]+(?:个)?(?:点|部分|方面|问题|例子|节|小节)?$"
)


def comparable_text(value: str) -> str:
    """Create a punctuation-insensitive key for graph quality checks."""
    return re.sub(r"[\W_]+", "", value.lower(), flags=re.UNICODE)


def strip_generic_entity_affixes(key: str) -> str:
    """Remove common generic suffixes around otherwise specific labels."""
    for suffix in GENERIC_SUFFIXES:
        if key.endswith(suffix) and len(key) > len(suffix) + 1:
            return key[: -len(suffix)]
    return key


def is_low_value_entity_name(name: str) -> bool:
    """Return true for generic labels that make noisy graph nodes."""
    key = comparable_text(name)
    if not key:
        return True
    if key in LOW_VALUE_ENTITY_KEYS:
        return True
    if len(key) <= 1:
        return True
    if key.isdigit():
        return True
    if PLACEHOLDER_RE.match(key):
        return True
    if key in {"nodeoptional", "conceptname", "entityname", "概念名", "实体名", "节点名"}:
        return True
    if key in {"起点概念名", "终点概念名", "起点实体", "终点实体"}:
        return True
    if ORDINAL_ONLY_RE.match(key):
        return True
    if _is_generic_classroom_phrase(key):
        return True
    if _is_short_generic_suffix_phrase(key):
        return True
    return False


def _is_generic_classroom_phrase(key: str) -> bool:
    """Filter short classroom discourse labels instead of subject concepts."""
    if len(key) > 10:
        return False
    return any(key.startswith(prefix) for prefix in GENERIC_PREFIXES)


def _is_short_generic_suffix_phrase(key: str) -> bool:
    """Filter labels such as '核心特点' or '直接原因' when subject is missing."""
    if len(key) > 4:
        return False
    return any(key.endswith(suffix) for suffix in GENERIC_SHORT_SUFFIXES)


__all__ = [
    "comparable_text",
    "is_low_value_entity_name",
    "strip_generic_entity_affixes",
]
