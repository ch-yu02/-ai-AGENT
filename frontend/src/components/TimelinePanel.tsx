import { EmptyState } from "./EmptyState";
import type { TimelineItem } from "../types/classroom";
import { formatClassTime } from "../utils/time";

// 统一课堂时间线。
//
// 后端 ContextManager 会把 transcript/image/knowledge 三类事件都转换为
// TimelineItem。前端收到 event.received 后，可以直接把
// data.context_update.timeline_item 追加到这个数组。
type TimelinePanelProps = {
  timeline: TimelineItem[];
};

export function TimelinePanel({ timeline }: TimelinePanelProps) {
  return (
    <section className="panel timeline-panel" aria-labelledby="timeline-title">
      <div className="panel-header">
        <div>
          <h2 id="timeline-title">时间线</h2>
          <span>{timeline.length} 项</span>
        </div>
      </div>

      {timeline.length === 0 ? (
        <EmptyState label="等待事件" />
      ) : (
        <ol className="timeline-list">
          {timeline.map((item) => (
            <li className="timeline-item" key={item.item_id}>
              <span>{formatClassTime(item.ts)}</span>
              <div>
                <strong>{item.title}</strong>
                <em>{item.type}</em>
              </div>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
