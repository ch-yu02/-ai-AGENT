"""临时应用状态 —— MVP 阶段的内存事件暂存区。

.. attention::
   本模块是 **临时方案**，仅在 core 层各 Manager 就绪前使用。
   当 ContextManager / KnowledgeGraphManager / LocalStorage 实现后，
   整个模块应被删除，事件流将直接交由正式 Manager 处理。

设计背景
--------
core 层的 Manager（SessionManager 除外）尚在开发中。为了让 API 路由层
（events.py、sessions.py）能够独立跑通集成测试，需要一个最简的内存暂存
方案来承接实时事件。

当前数据流
----------
::

  前端/端侧 SDK
      │  POST /api/events  (RealtimeEvent)
      ▼
  events.py 路由
      │  1. session_manager.require_recording()  ← 门控检查
      │  2. app_state.events[sid].append(event)  ← 暂存原始事件
      │  3. connection_manager.broadcast()       ← 推送 WebSocket
      ▼
  前端 WebSocket 订阅者

未来数据流（AppState 删除后）
-----------------------------
::

  前端/端侧 SDK
      │  POST /api/events  (RealtimeEvent)
      ▼
  events.py 路由
      │  1. session_manager.require_recording()
      │  2. context_manager.ingest(event)          ← 解析并分流
      │     ├─ transcript.segment  → 更新 transcript / timeline
      │     ├─ image.capture      → 更新 visuals / timeline
      │     └─ knowledge.extraction → knowledge_graph_manager.apply()
      │  3. connection_manager.broadcast()         ← 推送派生结果
      ▼
  前端 WebSocket 订阅者
"""

from collections import defaultdict

from backend.app.models import RealtimeEvent


class AppState:
    """临时内存状态容器，在 core 层 Manager 就绪前作为事件暂存区。

    当前职责
    --------
    仅负责按 session_id 收集原始 ``RealtimeEvent`` 对象，不做任何解析、
    转换或持久化。API 路由层通过 ``app_state`` 单例访问。

    未来替代
    --------
    以下 Manager 就绪后，各自接管本应由它们处理的职责，``AppState`` 将被删除：

    - **SessionManager**（已就绪）：会话生命周期管理，不再需要 AppState
      来追踪 session。
    - **ContextManager**（待实现）：负责将 transcript.segment /
      image.capture 事件转换为结构化的 transcript、timeline、visuals。
    - **KnowledgeGraphManager**（待实现）：负责处理 knowledge.extraction
      事件，维护知识图谱的节点和边。
    - **LocalStorage**（待实现）：负责将上述结构化数据持久化到磁盘，
      提供跨重启的恢复能力。

    注意事项
    --------
    - 本类**不应添加任何业务逻辑**。所有复杂行为应等待正式 Manager 实现。
    - 内存无限增长：当前不做清理。可用于 Demo，但不可用于生产。
    - 测试隔离：测试代码可通过 ``app_state.events.clear()`` 重置状态。
    """

    def __init__(self) -> None:
        # 按 session_id 分组的原始事件列表。
        # 使用 defaultdict(list) 使得首次访问任意 session_id 时自动创建空列表，
        # 调用方无需检查 key 是否存在。
        #
        # 未来 ContextManager 会将这些原始事件转换为结构化的 transcript、
        # timeline、visuals 和 knowledge graph 更新，到时此字典即可移除。
        self.events: dict[str, list[RealtimeEvent]] = defaultdict(list)


# ── 模块级单例 ──────────────────────────────────────────────────────
# 整个后端进程共享一个 AppState 实例。各路由模块通过
# from backend.app.api.state import app_state 获取。
#
# 这是有意为之的简单设计：AppState 本身是临时方案，不需要依赖注入的
# 复杂度。等正式 Manager 层就绪后，此单例连同整个模块一起删除。

app_state = AppState()
"""AppState 的全局单例实例。

events.py 通过此实例暂存原始事件，等待下游 Manager 处理。
"""
