import { EmptyState } from "./EmptyState";
import type { ImageCapture } from "../types/classroom";
import { formatClassTime } from "../utils/time";

// 图片 / OCR / VLM 面板。
//
// MVP 阶段后端只保证 image_path、ocr_text、caption 等结构化字段。
// 如果 image_path 是 local://...，浏览器暂时不能直接加载图片，所以这里优先
// 展示 OCR 文本或图片描述；后续有静态文件路由后再补真实图片预览。
type VisualOcrPanelProps = {
  visuals: ImageCapture[];
};

export function VisualOcrPanel({ visuals }: VisualOcrPanelProps) {
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
        <div className="scroll-list">
          {visuals.map((visual) => (
            <article className="visual-item" key={visual.image_id}>
              <div>
                <strong>{visual.image_type || "课堂图片"}</strong>
                <span>{formatClassTime(visual.capture_ts)}</span>
              </div>
              {/* OCR 优先，其次 VLM caption，最后展示路径作为联调线索。 */}
              <p>{visual.ocr_text || visual.caption || visual.image_path}</p>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}
