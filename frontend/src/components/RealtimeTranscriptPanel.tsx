import { useEffect, useRef } from "react";

import { EmptyState } from "./EmptyState";
import type { TranscriptSegment } from "../types/classroom";
import { formatClassTime } from "../utils/time";

// 实时字幕面板。
//
// 数据来源是 transcript.segment 事件。后续 WebSocket reducer 收到
// event.received 后，可以从 context_update.timeline_item.data 或原始 payload
// 解析出 TranscriptSegment，并追加到 transcript 数组。
type RealtimeTranscriptPanelProps = {
  transcript: TranscriptSegment[];
};

export function RealtimeTranscriptPanel({ transcript }: RealtimeTranscriptPanelProps) {
  // 字幕是“实时流”，用户最关心最新一句。
  // listRef 指向可滚动容器；每当 transcript.length 增长时，把滚动条推到底部。
  // 这里只依赖 length，而不是整个 transcript 数组，避免内容更新时频繁打断用户滚动。
  const listRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const list = listRef.current;

    if (!list) {
      return;
    }

    list.scrollTop = list.scrollHeight;
  }, [transcript.length]);

  return (
    <section className="panel transcript-panel" aria-labelledby="transcript-title">
      <div className="panel-header">
        <div>
          <h2 id="transcript-title">实时字幕</h2>
          <span>{transcript.length} 条</span>
        </div>
      </div>

      {transcript.length === 0 ? (
        <EmptyState label="等待字幕" />
      ) : (
        <div className="scroll-list transcript-list" ref={listRef}>
          {transcript.map((segment) => (
            // segment_id 由 ASR/mock sender 提供；缺省时后端 ContextManager 会补齐。
            <article className="transcript-item" key={segment.segment_id}>
              <div className="item-meta">
                <span>
                  {formatClassTime(segment.start_ts)} - {formatClassTime(segment.end_ts)}
                </span>
                <span>{segment.speaker || "teacher"}</span>
                {typeof segment.confidence === "number" ? (
                  <span>{Math.round(segment.confidence * 100)}%</span>
                ) : null}
              </div>
              <p>{segment.text}</p>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}
