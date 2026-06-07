import { useEffect, useRef } from "react";

import { EmptyState } from "./EmptyState";
import type { GlobalSearchSourceRef } from "../types/agent";
import type { ImageCapture } from "../types/classroom";
import { formatClassTime } from "../utils/time";

// 图片 / OCR / VLM 面板。
//
// MVP 阶段后端只保证 image_path、ocr_text、caption 等结构化字段。
// 如果 image_path 是 local://...，浏览器暂时不能直接加载图片，所以这里优先
// 展示 OCR 文本或图片描述；后续有静态文件路由后再补真实图片预览。
type VisualOcrPanelProps = {
  visuals: ImageCapture[];
  focusedSource?: GlobalSearchSourceRef | null;
};

export function VisualOcrPanel({ visuals, focusedSource }: VisualOcrPanelProps) {
  // 视觉事件通常比字幕少，但每次出现都很重要；自动滚到底能让 mock sender
  // 连续发送图片/OCR 时，页面始终显示最新处理结果。
  const listRef = useRef<HTMLDivElement | null>(null);
  const itemRefs = useRef<Record<string, HTMLElement | null>>({});

  useEffect(() => {
    const list = listRef.current;

    if (!list) {
      return;
    }

    list.scrollTop = list.scrollHeight;
  }, [visuals.length]);

  useEffect(() => {
    if (focusedSource?.type !== "visual") {
      return;
    }

    itemRefs.current[focusedSource.id]?.scrollIntoView({
      block: "center",
      behavior: "smooth",
    });
  }, [focusedSource]);

  return (
    <section className="panel visual-panel" aria-labelledby="visual-title">
      <div className="panel-header">
        <div>
          <h2 id="visual-title">图片 / OCR</h2>
          <span>{visuals.length} 张</span>
        </div>
      </div>

      {visuals.length === 0 ? (
        <EmptyState label="等待视觉内容" />
      ) : (
        <div className="scroll-list visual-list" ref={listRef}>
          {visuals.map((visual) => (
            <article
              className={`visual-item ${
                focusedSource?.type === "visual" && focusedSource.id === visual.image_id
                  ? "focused-source"
                  : ""
              }`}
              key={visual.image_id}
              ref={(element) => {
                itemRefs.current[visual.image_id] = element;
              }}
            >
              <div>
                <strong>{visual.image_type || "课堂图片"}</strong>
                <span>{formatClassTime(visual.capture_ts)}</span>
              </div>
              <dl className="visual-meta">
                <div>
                  <dt>来源</dt>
                  <dd>{visual.source || "-"}</dd>
                </div>
                <div>
                  <dt>状态</dt>
                  <dd>{visual.status}</dd>
                </div>
              </dl>
              {visual.ocr_text ? (
                <div className="visual-block">
                  <span>OCR</span>
                  <p>{visual.ocr_text}</p>
                </div>
              ) : null}
              {visual.caption ? (
                <div className="visual-block">
                  <span>描述</span>
                  <p>{visual.caption}</p>
                </div>
              ) : null}
              {/* local:// 路径暂时不能直接加载，展示出来方便联调确认图片 ID。 */}
              <code className="image-path">{visual.image_path}</code>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}
