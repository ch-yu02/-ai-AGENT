"""WebSocket 连接管理 —— 按课堂会话分组的客户端连接池与消息广播。

本模块是 api 层的 **共享基础设施**，不定义任何 HTTP 或 WebSocket 路由。
它提供 ``ConnectionManager`` 单例，供以下路由模块复用：

- ``websocket.py`` —— 调用 ``connect()`` / ``disconnect()`` 管理连接生命周期
- ``events.py``   —— 调用 ``broadcast()`` 推送实时事件通知
- ``sessions.py`` —— 调用 ``broadcast()`` 推送会话状态变更

架构位置
--------
::

  ┌──────────────┐  ┌──────────────┐   ┌──────────────┐
  │ websocket.py │  │  events.py   │   │ sessions.py  │    ← 路由层
  └──────┬───────┘  └──────┬───────┘   └──────┬───────┘
         │ connect/        │ broadcast()      │ broadcast()
         │ disconnect      │                  │
         └──────────┬──────┴──────────────────┘
                    ▼
         ┌─────────────────────┐
         │  ConnectionManager  │   ← 本模块（基础设施层）
         │  (realtime.py)      │
         └─────────────────────┘
"""

from fastapi import WebSocket

from backend.app.models import WebSocketMessage


class ConnectionManager:
    """按课堂会话（session_id）分组管理 WebSocket 客户端连接。

    职责边界
    --------
    本类 **只负责连接追踪和消息投递**，不涉及：

    - 会话是否存在（由 ``SessionManager`` 负责）
    - 消息内容是否正确（由调用方保证）
    - 连接认证 / 授权（当前 MVP 不做）

    数据结构
    --------
    ``active_connections`` 是一个以 session_id 为 key 的字典，每个 value
    是该课堂下所有已连接的 WebSocket 客户端列表。同一课堂可以有多个订阅者
    （如教师端 + 多个学生端同时在线）。

    未来扩展
    --------
    - 心跳 / ping 处理：定期检测僵尸连接并清理
    - 新客户端回放：连接时推送最新的 transcript / timeline 快照
    - 按客户端过滤：支持向特定角色（教师/学生）定向推送
    """

    def __init__(self) -> None:
        # session_id → 该课堂下所有已连接的 WebSocket 客户端列表。
        # 使用普通 dict（非 defaultdict），由 connect/disconnect 手动管理
        # key 的创建和清理，避免空列表残留。
        self.active_connections: dict[str, list[WebSocket]] = {}

    # ── 连接生命周期 ─────────────────────────────────────────────

    async def connect(self, session_id: str, websocket: WebSocket) -> None:
        """接受 WebSocket 握手并将客户端注册到指定课堂的连接池。

        调用时机：``websocket.py`` 的 ``/ws/{session_id}`` 端点，
        在 FastAPI 将 WebSocket 升级后立即调用。

        流程：
          1. 调用 ``websocket.accept()`` 完成 WebSocket 握手
          2. 将客户端追加到 ``active_connections[session_id]`` 列表，
             若该 session 首次有客户端连接则自动创建列表
        """
        await websocket.accept()
        # setdefault 兼顾首次连接（创建新列表）和后续连接（返回已有列表）
        self.active_connections.setdefault(session_id, []).append(websocket)

    def disconnect(self, session_id: str, websocket: WebSocket) -> None:
        """从连接池移除客户端，若课堂已无订阅者则清理 key。

        调用时机：``websocket.py`` 中 ``WebSocketDisconnect`` 异常捕获后。

        清理策略：先从列表中移除该客户端；若该 session 下已无任何连接，
        则从字典中删除该 key，避免 ``active_connections`` 中堆积空列表。
        """
        connections = self.active_connections.get(session_id, [])
        if websocket in connections:
            connections.remove(websocket)
        # 空列表意味着该课堂已无前端订阅者，清理 key 防止内存泄漏
        if not connections:
            self.active_connections.pop(session_id, None)

    # ── 消息广播 ─────────────────────────────────────────────────

    async def broadcast(self, session_id: str, message: WebSocketMessage) -> None:
        """向指定课堂的所有已连接客户端群发 JSON 消息。

        调用时机：
        - ``events.py`` 收到新事件后，广播 ``event.received``
        - ``sessions.py`` 创建/结束会话后，广播 ``session.started`` / ``session.ended``

        线程安全注意事项
        -----------------
        先拷贝连接列表再遍历发送。因为 ``send_json`` 是异步操作，其间
        若有客户端断开连接触发 ``disconnect()`` 回调，会修改原始列表，
        导致迭代器异常。拷贝后迭代的是快照，不受并发修改影响。

        发送失败处理
        ------------
        当前 MVP 不捕获单个 ``send_json`` 的异常——若某个客户端发送失败
        （如连接已断开但尚未触发 disconnect），异常会向上传播到路由层。
        后续可改为 catch 后静默移除该客户端。
        """
        # 防御性拷贝：断开连接的客户端可能在 send_json 期间修改原列表
        connections = list(self.active_connections.get(session_id, []))
        for websocket in connections:
            await websocket.send_json(message.model_dump())


# ── 模块级单例 ──────────────────────────────────────────────────────
# 整个后端进程共享一个 ConnectionManager 实例。各路由模块通过
# from backend.app.api.realtime import connection_manager 获取。
#
# 单例是合理的选择：WebSocket 连接池是全局状态，拆分为多实例反而
# 会导致广播漏发（事件只发到部分实例的连接池中）。

connection_manager = ConnectionManager()
"""ConnectionManager 的全局单例实例。

websocket.py 通过它注册/注销连接，events.py 和 sessions.py 通过它广播消息。
"""
