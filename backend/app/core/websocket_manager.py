"""WebSocket 管理器。

WebSocketManager 负责维护“课堂 session_id -> 前端连接列表”的映射，
并向某一课堂的所有订阅者广播实时消息。

它在后端链路中的位置：

  sessions.py 创建/结束课堂 ─┐
  events.py 接收实时事件   ───┼──> WebSocketManager.broadcast()
  websocket.py 建立长连接 ────┘

职责边界
--------
- 负责：连接注册、断开清理、按 session 广播、发送失败清理。
- 不负责：校验 session 是否存在、决定消息内容、生成图谱或上下文数据。

为什么放在 core 层？
------------------
WebSocket 连接池是后端运行时的核心共享状态。API 路由只是入口，真正的
连接生命周期管理和广播策略应放在 core 层，方便后续被任务队列、后台
处理器或课后技能复用。
"""

from dataclasses import dataclass
from typing import Protocol

from fastapi import WebSocket

from backend.app.models import WebSocketMessage


class WebSocketLike(Protocol):
    """WebSocketManager 依赖的最小 WebSocket 接口。

    使用 Protocol 的好处是：生产环境可传 FastAPI 的 WebSocket，测试里
    可传一个轻量 fake 对象，不需要启动真实网络服务。
    """

    async def accept(self) -> None:
        """Complete the WebSocket handshake."""

    async def send_json(self, data: dict) -> None:
        """Send one JSON-serializable payload to the client."""


@dataclass(frozen=True)
class BroadcastResult:
    """一次广播的统计结果。

    API 路由目前不需要读取返回值，但测试和后续监控可以用它判断：
    - attempted：尝试发送给多少个连接
    - delivered：成功发送给多少个连接
    - removed：发送失败并被清理的连接数
    """

    attempted: int
    delivered: int
    removed: int


class WebSocketManager:
    """按课堂会话分组管理 WebSocket 客户端连接。"""

    def __init__(self) -> None:
        # active_connections 的 key 是 session_id，value 是订阅该课堂的
        # WebSocket 连接列表。同一课堂可被多个前端同时订阅。
        self.active_connections: dict[str, list[WebSocketLike]] = {}

    # ── 连接生命周期 ─────────────────────────────────────────

    async def connect(self, session_id: str, websocket: WebSocketLike) -> None:
        """接受 WebSocket 握手并注册连接。

        调用方：api/websocket.py 的 ``/ws/{session_id}`` 路由。

        步骤：
          1. 调用 ``accept()`` 完成 WebSocket 协议升级。
          2. 把连接追加到该 session 的连接池。
        """
        await websocket.accept()
        self.active_connections.setdefault(session_id, []).append(websocket)

    def disconnect(self, session_id: str, websocket: WebSocketLike) -> None:
        """从连接池中移除一个客户端连接。

        该方法是幂等的：如果连接已经不存在，不会抛异常。这能兼容
        “发送失败时清理”和“WebSocketDisconnect 回调清理”同时发生的情况。
        """
        connections = self.active_connections.get(session_id)
        if connections is None:
            return

        if websocket in connections:
            connections.remove(websocket)

        # 如果某个 session 已无订阅者，删除 key，避免空列表长期残留。
        if not connections:
            self.active_connections.pop(session_id, None)

    def clear(self) -> None:
        """清空所有连接，仅用于测试或本地 demo 重置。"""
        self.active_connections.clear()

    # ── 查询辅助 ─────────────────────────────────────────────

    def connection_count(self, session_id: str | None = None) -> int:
        """返回连接数量。

        - 传入 session_id：返回该课堂的订阅者数量。
        - 不传 session_id：返回所有课堂的连接总数。
        """
        if session_id is not None:
            return len(self.active_connections.get(session_id, []))
        return sum(len(connections) for connections in self.active_connections.values())

    def session_count(self) -> int:
        """返回当前有 WebSocket 订阅者的课堂数量。"""
        return len(self.active_connections)

    # ── 消息广播 ─────────────────────────────────────────────

    async def broadcast(
        self,
        session_id: str,
        message: WebSocketMessage,
    ) -> BroadcastResult:
        """向指定课堂的所有连接广播一条消息。

        发送策略：
          - 先复制连接列表，避免发送期间连接池被修改导致迭代异常。
          - 某个连接发送失败时，只清理这个失败连接，继续给其他连接发送。
          - 返回 BroadcastResult，便于测试和后续监控。
        """
        connections = list(self.active_connections.get(session_id, []))
        delivered = 0
        removed = 0
        payload = message.model_dump()

        for websocket in connections:
            try:
                await websocket.send_json(payload)
                delivered += 1
            except Exception:
                # 客户端可能已断开但 FastAPI 尚未触发 WebSocketDisconnect。
                # 这里主动移除失败连接，避免后续每次广播都重复失败。
                self.disconnect(session_id, websocket)
                removed += 1

        return BroadcastResult(
            attempted=len(connections),
            delivered=delivered,
            removed=removed,
        )


websocket_manager = WebSocketManager()
"""WebSocketManager 的全局单例实例。"""

# 向后兼容旧命名：之前 api/realtime.py 暴露的是 connection_manager。
connection_manager = websocket_manager
"""Backward-compatible alias for older route imports."""
