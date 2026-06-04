"""WebSocket 端点 —— 前端订阅课堂实时更新的长连接入口。

本模块暴露唯一的 WebSocket 路由 ``/ws/{session_id}``，前端通过它建立
持久连接，接收由 ``events.py`` 和 ``sessions.py`` 通过
``WebSocketManager.broadcast()`` 推送的实时消息。

消息流向
--------
::

  前端 WS 客户端                          后端
  ─────────────                         ────
      │                                    │
      │── GET /ws/{sid} ──────────────────→│  websocket.py 接受连接
      │                                    │  websocket_manager.connect()
      │←── {"type":"ws.connected"} ───────│  握手确认
      │                                    │
      │         ... 连接保持 ...            │  events.py 收到新事件
      │                                    │  connection_manager.broadcast()
      │←── {"type":"event.received"} ─────│  实时事件通知
      │←── {"type":"session.ended"}  ─────│  会话状态变更
      │                                    │
      │── X 断开 ─────────────────────────→│  WebSocketDisconnect
      │                                    │  connection_manager.disconnect()
"""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from backend.app.core import SessionNotFoundError, session_manager, websocket_manager
from backend.app.models import WebSocketMessage


router = APIRouter(tags=["websocket"])
"""WebSocket 路由实例，未设置 prefix（路径直接在根级别 /ws/...）。"""


@router.websocket("/ws/{session_id}")
async def session_updates(websocket: WebSocket, session_id: str) -> None:
    """订阅指定课堂会话的实时更新流。

    前端在加入课堂后立即连接此端点，之后所有与该课堂相关的事件通知
    （新事件到达、会话结束等）都会通过此连接推送，无需前端轮询。

    连接生命周期
    ------------
    1. **校验**：调用 ``session_manager.get_session()`` 确认课堂存在，
       不存在则以 1008 关闭连接
    2. **握手**：调用 ``websocket_manager.connect()`` 完成 WebSocket
       升级，将客户端注册到该 session 的连接池
    3. **确认**：发送 ``ws.connected`` 消息，前端可据此确认连接已就绪
    4. **保持**：进入无限循环 ``receive_text()``，保持连接活跃。
       当前忽略客户端发来的所有消息（MVP 阶段不需要双向通信）
    5. **断开**：捕获 ``WebSocketDisconnect``，调用
       ``websocket_manager.disconnect()`` 清理连接池

    当前限制（MVP）
    --------------
    - **无初始快照**：连接后不推送当前 transcript / timeline /
      knowledge graph 快照，前端只能收到连接之后的新事件
    - **无心跳**：不发送 ping/pong，代理可能因空闲超时断开连接
    - **忽略客户端消息**：``receive_text()`` 的返回值被丢弃，
      后续可用于接收 ping 响应、光标同步或指令
    """
    # 0. MVP 阶段已经有 SessionManager，因此这里先校验课堂是否存在。
    #    1008 表示 policy violation，前端可解释为“订阅的课堂不存在”。
    try:
        session_manager.get_session(session_id)
    except SessionNotFoundError:
        await websocket.close(code=1008, reason="Session not found")
        return

    # 1. 完成 WebSocket 握手并注册到连接池
    await websocket_manager.connect(session_id, websocket)

    # 2. 发送握手确认，前端可借此判断连接已就绪
    await websocket.send_json(
        WebSocketMessage(
            type="ws.connected",
            session_id=session_id,
            data={"message": "connected"},
        ).model_dump()
    )

    try:
        # 3. 阻塞循环保持连接打开。当前忽略所有客户端发来的消息，
        #    但保留 receive_text() 调用作为扩展点：
        #    - 心跳 ping/pong
        #    - 光标位置同步
        #    - 学生端问答/反馈指令
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        # 4. 客户端主动断开或网络异常，从连接池移除
        websocket_manager.disconnect(session_id, websocket)
