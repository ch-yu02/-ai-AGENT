import { useEffect, useState } from "react";

import type { LectureSession } from "../types/classroom";

// 顶部课堂生命周期控制。
//
// 组件本身不调用 API，只通过 onStart/onEnd 把用户动作交给 App。
// 这样按钮只关心展示和可用性，业务流程集中在页面或 store 中。
type ClassroomControlsProps = {
  session: LectureSession | null;
  isBusy: boolean;
  isAttachBusy: boolean;
  isRenameBusy: boolean;
  onStart: () => void;
  onAttach: () => void;
  onEnd: () => void;
  onRename: (title: string, course: string | null) => void;
};

export function ClassroomControls({
  session,
  isBusy,
  isAttachBusy,
  isRenameBusy,
  onStart,
  onAttach,
  onEnd,
  onRename,
}: ClassroomControlsProps) {
  // 只有 recording 状态允许结束课堂。未开始、已结束或请求中都会禁用对应按钮。
  const isRecording = session?.status === "recording";
  const [isEditingName, setIsEditingName] = useState(false);
  const [titleDraft, setTitleDraft] = useState(session?.title ?? "");
  const [courseDraft, setCourseDraft] = useState(session?.course ?? "");

  useEffect(() => {
    setTitleDraft(session?.title ?? "");
    setCourseDraft(session?.course ?? "");
    setIsEditingName(false);
  }, [session?.session_id, session?.title, session?.course]);

  function submitRename() {
    const title = titleDraft.trim();
    if (!session || !title || isRenameBusy) {
      return;
    }
    onRename(title, courseDraft.trim() || null);
    setIsEditingName(false);
  }

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
        disabled={isBusy || isAttachBusy || isRecording}
        onClick={onAttach}
      >
        {isAttachBusy ? "接入中" : "接入当前课堂"}
      </button>
      <button
        className="secondary-button"
        type="button"
        disabled={isBusy || !isRecording}
        onClick={onEnd}
      >
        {isBusy && isRecording ? "结束中" : "结束课堂"}
      </button>
      {session ? (
        <div className="session-name-control">
          {isEditingName ? (
            <form
              className="session-name-form"
              onSubmit={(event) => {
                event.preventDefault();
                submitRename();
              }}
            >
              <input
                aria-label="课堂标题"
                disabled={isRenameBusy}
                onChange={(event) => setTitleDraft(event.target.value)}
                placeholder="课堂标题"
                value={titleDraft}
              />
              <input
                aria-label="课程名称"
                disabled={isRenameBusy}
                onChange={(event) => setCourseDraft(event.target.value)}
                placeholder="课程名称"
                value={courseDraft}
              />
              <button
                className="primary-button"
                disabled={!titleDraft.trim() || isRenameBusy}
                type="submit"
              >
                {isRenameBusy ? "保存中" : "保存"}
              </button>
              <button
                className="secondary-button"
                disabled={isRenameBusy}
                onClick={() => setIsEditingName(false)}
                type="button"
              >
                取消
              </button>
            </form>
          ) : (
            <button
              className="secondary-button"
              disabled={isRenameBusy}
              onClick={() => setIsEditingName(true)}
              type="button"
            >
              编辑名称
            </button>
          )}
        </div>
      ) : null}
    </div>
  );
}
