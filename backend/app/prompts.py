"""Centralized prompt builders used by LLM and local Qwen features.

All model-facing instructions live here so prompt wording, JSON schemas, and
grounding rules can be reviewed in one place. Callers should pass only the
runtime data needed to fill a prompt; validation of model output remains in the
feature modules that own each schema.
"""

from collections.abc import Mapping, Sequence


def summary_system_prompt() -> str:
    """System prompt for post-class summary generation."""
    return (
        "你是课堂学习助手。只能基于用户提供的课堂资料总结，不要编造。"
        "请输出 JSON object，字段为 summary_markdown 和 source_refs。"
        "source_refs 是数组，元素包含 type(segment 或 knowledge_node) 和 id。"
    )


def summary_user_prompt(classroom_brief: str) -> str:
    """User prompt for post-class summary generation."""
    return (
        "请用中文生成一份简洁课堂总结，包含重点、知识脉络和复习建议。"
        "输出必须是 JSON，不要 Markdown code fence。\n\n"
        f"{classroom_brief}"
    )


def todo_system_prompt() -> str:
    """System prompt for structured todo extraction."""
    return (
        "你是课堂待办提取助手。只能基于课堂资料提取老师布置的任务、"
        "作业、预习、复习、提交或考试提醒。请输出 JSON object，字段为 "
        "todos。todos 是数组，每项包含 title、type、due_time、confidence、"
        "source_refs。source_refs 元素包含 type(segment 或 knowledge_node) 和 id。"
    )


def todo_user_prompt(classroom_brief: str) -> str:
    """User prompt for structured todo extraction."""
    return (
        "请从下面课堂资料中提取待办。如果没有明确待办，todos 返回空数组。"
        "输出必须是 JSON，不要 Markdown code fence。\n\n"
        f"{classroom_brief}"
    )


def quiz_system_prompt() -> str:
    """System prompt for quiz generation."""
    return (
        "你是课堂自测题生成助手。只能基于课堂资料出题，不要引入课外内容。"
        "请输出 JSON object，字段为 quiz。quiz 是数组，每项包含 question、"
        "type、options、answer、explanation、source_refs。source_refs 元素"
        "包含 type(segment 或 knowledge_node) 和 id。"
    )


def quiz_user_prompt(classroom_brief: str) -> str:
    """User prompt for quiz generation."""
    return (
        "请生成 3 到 5 道中文自测题，优先覆盖关键概念。输出必须是 JSON，"
        "不要 Markdown code fence。\n\n"
        f"{classroom_brief}"
    )


def grounded_qa_system_prompt() -> str:
    """System prompt for grounded classroom QA."""
    return (
        "你是课堂答疑助手。必须优先依据课堂来源回答；可以使用你的通用"
        "知识补充解释，但必须明确区分课堂内容和补充解释。不要编造课堂"
        "中没有出现过的来源。请输出 JSON object，字段 answer。"
    )


def grounded_qa_user_prompt(
    *,
    student_prompt: str,
    retrieved_answer: str,
    source_refs: Sequence[Mapping[str, object]],
) -> str:
    """User prompt for grounded classroom QA."""
    refs = "\n".join(
        f"- {item.get('type')}:"
        f"{item.get('id')}; ts={item.get('ts')}; text={item.get('text')}"
        for item in source_refs
    )
    return (
        f"学生问题：{student_prompt}\n\n"
        f"课堂检索回答：{retrieved_answer}\n\n"
        "课堂来源：\n"
        f"{refs}\n\n"
        "请用中文回答，格式上明确包含“根据课堂内容”和“补充解释”。"
    )


def llm_knowledge_extractor_system_prompt() -> str:
    """System prompt for backend LLM knowledge extraction."""
    return (
        "You are EDU-Mate's internal classroom knowledge extractor. "
        "Return only a JSON object matching this schema: "
        "{extraction_id:string optional, source_segment_ids:string[], "
        "source_visual_ids:string[], entities:[{entity_id?:string, "
        "name:string, type:string, description?:string}], "
        "relations:[{source:string,target:string,relation:string}], "
        "importance:number optional}. "
        "Use only the provided classroom transcript/OCR/caption sources. "
        "Do not invent source ids. Prefer concise Chinese entity names. "
        "Relations must use snake_case labels such as defines, mentions, "
        "related_to, maps_to, belongs_to, part_of, derives_from."
    )


def llm_knowledge_extractor_user_prompt(
    *,
    session_id: str,
    transcript: Sequence[Mapping[str, object]],
    visuals: Sequence[Mapping[str, object]],
) -> str:
    """User prompt for backend LLM knowledge extraction."""
    lines = [f"session_id: {session_id}", "", "transcript:"]
    if transcript:
        for segment in transcript:
            lines.append(
                "- "
                f"id={segment.get('id')}; "
                f"ts={_float(segment.get('start_ts')):.2f}-{_float(segment.get('end_ts')):.2f}; "
                f"text={segment.get('text') or ''}"
            )
    else:
        lines.append("- none")

    lines.extend(["", "visuals:"])
    if visuals:
        for visual in visuals:
            lines.append(
                "- "
                f"id={visual.get('id')}; "
                f"ts={_float(visual.get('capture_ts')):.2f}; "
                f"ocr={visual.get('ocr') or ''}; "
                f"caption={visual.get('caption') or ''}"
            )
    else:
        lines.append("- none")
    return "\n".join(lines)


def markdown_knowledge_tree_system_prompt() -> str:
    """System prompt for cloud extraction from structured Markdown notes."""
    return (
        "You are EDU-Mate's cloud classroom knowledge-tree agent. "
        "Return only one JSON object. Build a lightweight knowledge tree "
        "from the provided structured Markdown notes and recent source subtitles. "
        "Use only provided content; do not add outside facts. "
        "Each streaming request includes full notes for context plus a recent "
        "subtitle window for this update; extract only new or changed graph "
        "items grounded in the recent subtitle window, while using the existing "
        "graph and full notes to deduplicate and preserve hierarchy. "
        "source_segment_ids must list only the few direct supporting subtitle ids, "
        "at most 5, selected from the recent subtitle window; never return the "
        "full subtitle list. "
        "Prefer Chinese labels. Make hierarchy parent-to-child: "
        "course/topic contains subtopic/concept. Relations should use "
        "snake_case labels such as contains, defines, causes, example_of, "
        "contrasts_with, leads_to, related_to. JSON schema: "
        "{extraction_id?:string, source_segment_ids:string[], "
        "entities:[{entity_id?:string,name:string,type:string,description?:string}], "
        "relations:[{source:string,target:string,relation:string}], "
        "importance?:number}."
    )


def markdown_knowledge_tree_user_prompt(
    *,
    session_id: str,
    snapshot_id: str,
    sequence: int,
    update_status: str,
    existing_nodes: Sequence[str],
    existing_edges: Sequence[str],
    source_segments: Sequence[Mapping[str, object]],
    markdown: str,
    recent_source_segments: Sequence[Mapping[str, object]] | None = None,
) -> str:
    """User prompt for cloud extraction from structured Markdown notes."""
    focused_segments = (
        list(recent_source_segments)
        if recent_source_segments is not None
        else list(source_segments)
    )
    recent_lines = [
        f"- id={segment.get('segment_id')}; "
        f"ts={_float(segment.get('start_ts')):.2f}-{_float(segment.get('end_ts')):.2f}; "
        f"text={segment.get('text') or ''}"
        for segment in focused_segments
    ] or ["- none"]
    return "\n".join(
        [
            f"session_id: {session_id}",
            f"snapshot_id: {snapshot_id}",
            f"sequence: {sequence}",
            f"update_status: {update_status}",
            f"full_source_subtitle_count: {len(source_segments)}",
            f"recent_source_subtitle_count: {len(focused_segments)}",
            "",
            "existing_graph_nodes:",
            ", ".join(existing_nodes) or "none",
            "",
            "existing_graph_edges:",
            "; ".join(existing_edges) or "none",
            "",
            "recent_source_subtitles_for_this_update:",
            *recent_lines,
            "",
            "full_structured_markdown_notes_context:",
            markdown,
            "",
            "Task: return only graph additions or refinements directly supported by "
            "recent_source_subtitles_for_this_update. Use full_structured_markdown_notes_context "
            "only to understand course context and avoid duplicates.",
            "",
            "Return JSON only:",
        ]
    )


def transcript_polish_prompt(
    *,
    raw_text: str,
    previous_context: Sequence[str],
) -> str:
    """Prompt for local Qwen subtitle punctuation and phonetic correction."""
    context = "\n".join(f"- {item}" for item in previous_context[-3:]) or "- 无"
    return (
        "你是课堂实时字幕润色助手。请只处理本次 Whisper 原始转写，让字幕适合直接展示："
        "补充标点；根据发音、近音、同音、上下文和课堂术语修正语音识别错别字；"
        "把粘连文本拆成语意通顺的自然短句。\n"
        "纠错原则：如果 Whisper 词面不通顺，但按读音能明显对应到常见词、课程术语或上下文术语，"
        "应改成正确写法，例如“靠点”可改为“考点”，“苏晨克”可改为“速成课”。"
        "修正后的句子不要求逐字出现在原文中，但读音、语义和信息量必须与本次原始转写一致。\n"
        "严格限制：不得总结，不得扩写，不得补全被截断的句子，不得加入原文没有的信息。"
        "不确定的词保持原样，不要猜测；上一段字幕上下文只用于辨认术语，禁止复制到输出。"
        "每个分句都必须只表达本次原始转写中已经出现的内容。\n"
        "只输出一个 JSON object，不要 Markdown，不要解释。\n"
        "JSON schema: {\"sentences\": [\"一句自然字幕\", \"下一句自然字幕\"]}\n\n"
        "上一段字幕上下文:\n"
        f"{context}\n\n"
        "Whisper 原始转写:\n"
        f"{raw_text.strip()}\n\n"
        "JSON:"
    )


def transcript_polish_repair_prompt(raw_text: str) -> str:
    """Repair prompt for malformed local Qwen subtitle polish output."""
    return (
        "下面的文本本应是课堂字幕润色 JSON，但格式不合法。\n"
        "请只输出一个合法 JSON object，不要解释，不要 Markdown。\n"
        "必须且只能包含 sentences 字段，类型为字符串数组。\n\n"
        f"原始文本:\n{raw_text}\n\n"
        "合法 JSON:"
    )


def local_qwen_extraction_prompt(
    *,
    session_id: str,
    segments: Sequence[Mapping[str, object]],
) -> str:
    """Prompt for local Qwen knowledge extraction from transcript segments."""
    source_lines = "\n".join(
        f"- id={segment.get('segment_id')}; "
        f"ts={_float(segment.get('start_ts')):.2f}-{_float(segment.get('end_ts')):.2f}; "
        f"text={segment.get('text') or ''}"
        for segment in segments
    )
    allowed_ids = ", ".join(str(segment.get("segment_id")) for segment in segments)
    return (
        "你是 EDU-Mate 的本地课堂知识图谱抽取器。\n"
        "请只根据给定字幕抽取轻量知识图谱，不要补充字幕中没有出现的信息。\n"
        "只输出一个 JSON object，不要 Markdown，不要解释。\n"
        "JSON schema:\n"
        "{\n"
        '  "entities": [\n'
        '    {"entity_id": "node_optional", "name": "概念名", "type": "concept", '
        '"description": "一句话定义或课堂依据"}\n'
        "  ],\n"
        '  "relations": [\n'
        '    {"source": "起点概念名", "target": "终点概念名", "relation": "related_to"}\n'
        "  ],\n"
        '  "source_segment_ids": ["seg_id"],\n'
        '  "importance": 0.0\n'
        "}\n"
        "要求：\n"
        "- entity name 使用简洁中文课堂术语。\n"
        "- relation 使用 snake_case 英文标签，例如 defines, mentions, related_to, "
        "belongs_to, part_of, causes, contrasts_with。\n"
        f"- source_segment_ids 只能从这些 ID 中选择：{allowed_ids}。\n"
        "- 没有明确知识点时返回空 entities 和空 relations。\n\n"
        f"session_id: {session_id}\n"
        "字幕:\n"
        f"{source_lines}\n\n"
        "JSON:"
    )


def local_qwen_extraction_repair_prompt(raw_text: str) -> str:
    """Repair prompt for malformed local Qwen graph extraction output."""
    return (
        "下面的文本本应是知识图谱抽取 JSON，但格式不合法。\n"
        "请只输出一个合法 JSON object，不要解释，不要 Markdown。\n"
        "必须包含 entities、relations、source_segment_ids、importance 字段。\n\n"
        f"原始文本:\n{raw_text}\n\n"
        "合法 JSON:"
    )


def qwen_markdown_notes_prompt(
    *,
    segments: Sequence[Mapping[str, object]],
    domain_terms: Sequence[str],
) -> str:
    """Prompt for local Qwen Markdown classroom notes generation."""
    transcript = "\n".join(
        f"- [{_float(segment.get('start')):.2f}-{_float(segment.get('end')):.2f}] "
        f"{segment.get('text') or ''}"
        for segment in segments
    )
    terms = "、".join(domain_terms)
    return (
        "你是一个课堂语音转录助手兼课堂笔记整理助手。"
        "系统会每隔一段时间把当前累计的 WhisperLive 字幕发给你，"
        "请把它整理成会持续更新的课堂笔记，用于记录课堂内容、重点、概念和老师强调的备考信息。"
        "请只根据给定字幕做课堂转录整理：补充标点、修正明显语音识别错别字、合并重复片段，"
        "并生成结构化 Markdown 所需 JSON。\n"
        "严格限制：不得扩写，不得添加字幕中没有的信息，不得编造例子；"
        "即使你知道相关背景知识，也不能把字幕没有说出的内容写进笔记。"
        "如果内容不足，就保持简短。\n"
        "整理目标：像认真听课的学生记笔记一样，优先保留课堂主线、知识点、定义、"
        "因果关系、老师强调的重点和可复习的条目；不要写成宣传文案或总结报告。\n"
        "可选课程关键词如下；如果未提供关键词，就只能依据字幕上下文做通用纠错："
        f"{terms or '未提供'}。\n"
        "Few-shot 校准规则：\n"
        "- 当课程关键词与 Whisper 字幕存在明显同音、近音、漏字或错字关系，"
        "并且上下文支持时，可把字幕修正为课程关键词。例如关键词“线性代数”，"
        "字幕“线形代数”可修正为“线性代数”。\n"
        "- 当关键词“薛定谔方程”与字幕“学定额方程”在发音和上下文上明显对应，"
        "可修正为“薛定谔方程”。\n"
        "- 即使没有课程关键词，只要整句上下文和发音明显支持，也可以修正常见词或课堂术语，"
        "例如“苏晨克”可修正为“速成课”，“靠点/烤点”可修正为“考点”。\n"
        "- clean_transcript 允许较大的字面修改来修正明显 ASR 错误，但信息量必须与原字幕一致；"
        "候选修正会改变原意时，保持原字幕含义，不要猜测。\n"
        "这些保守修正规则必须同时应用到 title、summary、sections、keywords、clean_transcript。\n"
        "每个 summary 条目、section bullet、clean_transcript 句子都必须能在原始字幕中找到直接依据。\n"
        "只输出一个 JSON object，不要 Markdown，不要解释。\n"
        "JSON schema:\n"
        "{\n"
        '  "title": "简短标题",\n'
        '  "summary": ["要点1", "要点2"],\n'
        '  "sections": [{"heading": "小节标题", "bullets": ["条目"]}],\n'
        '  "keywords": ["关键词"],\n'
        '  "clean_transcript": ["润色后的逐句字幕"]\n'
        "}\n\n"
        "WhisperLive 字幕:\n"
        f"{transcript}\n\n"
        "JSON:"
    )


def qwen_markdown_notes_repair_prompt(raw_text: str) -> str:
    """Repair prompt for malformed local Qwen Markdown-notes JSON output."""
    return (
        "下面文本本应是课堂笔记 JSON，但格式不合法。"
        "请只输出合法 JSON object，不要解释，不要 Markdown。"
        "必须包含 title、summary、sections、keywords、clean_transcript 字段。\n\n"
        f"原始文本:\n{raw_text}\n\n"
        "合法 JSON:"
    )


def _float(value: object) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
