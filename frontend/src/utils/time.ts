// 将课堂内相对秒数格式化成 mm:ss。
//
// 后端事件中的 start_ts / capture_ts / timeline.ts 都是“课堂开始后的相对时间”，
// 不是绝对时间戳。这里做统一格式化，避免每个面板重复实现。
export function formatClassTime(seconds: number): string {
  // mock 或算法模块联调时可能给出 NaN/负数；UI 兜底到 00:00，保持页面稳定。
  const safeSeconds = Number.isFinite(seconds) ? Math.max(0, seconds) : 0;
  const minutes = Math.floor(safeSeconds / 60);
  const remainingSeconds = Math.floor(safeSeconds % 60);

  return `${String(minutes).padStart(2, "0")}:${String(remainingSeconds).padStart(2, "0")}`;
}
