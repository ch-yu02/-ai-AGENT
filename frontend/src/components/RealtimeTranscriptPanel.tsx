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
        <div className="scroll-list">
          {transcript.map((segment) => (
            // segment_id 由 ASR/mock sender 提供；缺省时后端 ContextManager 会补齐。
            <article className="transcript-item" key={segment.segment_id}>
              <span>{formatClassTime(segment.start_ts)}</span>
              <p>{segment.text}</p>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}
