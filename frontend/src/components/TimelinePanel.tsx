import { useEffect, useRef } from "react";

import { EmptyState } from "./EmptyState";
import type { GlobalSearchSourceRef } from "../types/agent";
import type { TimelineItem } from "../types/classroom";
import { formatClassTime } from "../utils/time";

// 统一课堂时间线。
//
// 后端 ContextManager 会把 transcript/image/knowledge 三类事件都转换为
// TimelineItem。前端收到 event.received 后，可以直接把
// data.context_update.timeline_item 追加到这个数组。
type TimelinePanelProps = {
  timeline: TimelineItem[];
  focusedSource?: GlobalSearchSourceRef | null;
};

const timelineTypeLabels: Record<TimelineItem["type"], string> = {
  transcript: "字幕",
  visual: "图片/OCR",
  knowledge: "知识点",
};

export function TimelinePanel({ timeline, focusedSource }: TimelinePanelProps) {
  // 后端 ContextManager 会维护排序后的 timeline；前端这里再排序一次，作为对
  // WebSocket 到达顺序抖动的兜底。slice() 避免直接修改 props 数组。
  const sortedTimeline = timeline.slice().sort((left, right) => left.ts - right.ts);
  const itemRefs = useRef<Record<string, HTMLLIElement | null>>({});
  const focusedTimelineId = focusedSource
    ? findTimelineItemId(sortedTimeline, focusedSource)
    : null;

  useEffect(() => {
    if (!focusedTimelineId) {
      return;
    }

    itemRefs.current[focusedTimelineId]?.scrollIntoView({
      block: "center",
      behavior: "smooth",
    });
  }, [focusedTimelineId]);

  return (
    <section className="panel timeline-panel" aria-labelledby="timeline-title">
      <div className="panel-header">
        <div>
          <h2 id="timeline-title">时间线</h2>
          <span>{sortedTimeline.length} 项</span>
        </div>
      </div>

      {sortedTimeline.length === 0 ? (
        <EmptyState label="等待事件" />
      ) : (
        <ol className="timeline-list">
          {sortedTimeline.map((item) => (
            <li
              className={`timeline-item ${
                focusedTimelineId === item.item_id ? "focused-source" : ""
              }`}
              key={item.item_id}
              ref={(element) => {
                itemRefs.current[item.item_id] = element;
              }}
            >
              <span>{formatClassTime(item.ts)}</span>
              <div>
                <div className="timeline-title-row">
                  <strong>{item.title}</strong>
                  <em className={`type-pill ${item.type}`}>
                    {timelineTypeLabels[item.type]}
                  </em>
                </div>
              </div>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

function findTimelineItemId(
  timeline: TimelineItem[],
  focusedSource: GlobalSearchSourceRef,
): string | null {
  // transcript / visual 的 timeline item_id 通常就是 segment_id / image_id。
  // 为了兼容未来数据格式，这里也检查 timeline.data 中的常见 ID 字段。
  const match = timeline.find((item) => {
    if (item.item_id === focusedSource.id) {
      return true;
    }

    const data = item.data;
    return (
      data.segment_id === focusedSource.id ||
      data.image_id === focusedSource.id ||
      data.extraction_id === focusedSource.id ||
      data.node_id === focusedSource.id ||
      data.edge_id === focusedSource.id
    );
  });

  return match?.item_id ?? null;
}
