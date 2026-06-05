import type { LectureSession } from "../types/classroom";

// 顶部课堂生命周期控制。
//
// 组件本身不调用 API，只通过 onStart/onEnd 把用户动作交给 App。
// 这样按钮只关心展示和可用性，业务流程集中在页面或 store 中。
type ClassroomControlsProps = {
  session: LectureSession | null;
  isBusy: boolean;
  onStart: () => void;
  onEnd: () => void;
};

export function ClassroomControls({
  session,
  isBusy,
  onStart,
  onEnd,
}: ClassroomControlsProps) {
  // 只有 recording 状态允许结束课堂。未开始、已结束或请求中都会禁用对应按钮。
  const isRecording = session?.status === "recording";

  return (
    <div className="control-group">
      <button
        className="primary-button"
        type="button"
        disabled={isBusy || isRecording}
        onClick={onStart}
      >
        {isBusy && !isRecording ? "开始中" : "开始课堂"}
      </button>
      <button
        className="secondary-button"
        type="button"
        disabled={isBusy || !isRecording}
        onClick={onEnd}
      >
        {isBusy && isRecording ? "结束中" : "结束课堂"}
      </button>
    </div>
  );
}
