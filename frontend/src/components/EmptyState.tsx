type EmptyStateProps = {
  label: string;
};

// 各实时面板共用的空状态。
// 它只接收短文案，不放业务判断；是否为空由具体面板决定。
export function EmptyState({ label }: EmptyStateProps) {
  return <div className="empty-state">{label}</div>;
}
