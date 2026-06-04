import unittest

from backend.app.core import WebSocketManager
from backend.app.models import WebSocketMessage


class FakeWebSocket:
    """测试用的轻量 WebSocket 替身。

    它只实现 WebSocketManager 需要的 accept/send_json 两个方法，
    因此测试不需要启动 FastAPI 服务或真实网络连接。
    """

    def __init__(self, fail_send: bool = False) -> None:
        self.accepted = False
        self.fail_send = fail_send
        self.sent_payloads: list[dict] = []

    async def accept(self) -> None:
        self.accepted = True

    async def send_json(self, data: dict) -> None:
        if self.fail_send:
            raise RuntimeError("send failed")
        self.sent_payloads.append(data)


class WebSocketManagerTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.manager = WebSocketManager()
        self.session_id = "lec_ws_001"

    async def test_connect_accepts_and_registers_socket(self) -> None:
        socket = FakeWebSocket()

        await self.manager.connect(self.session_id, socket)

        self.assertTrue(socket.accepted)
        self.assertEqual(self.manager.connection_count(self.session_id), 1)
        self.assertEqual(self.manager.session_count(), 1)

    async def test_broadcast_sends_to_same_session_only(self) -> None:
        socket_a = FakeWebSocket()
        socket_b = FakeWebSocket()
        other_socket = FakeWebSocket()
        await self.manager.connect(self.session_id, socket_a)
        await self.manager.connect(self.session_id, socket_b)
        await self.manager.connect("lec_other", other_socket)

        result = await self.manager.broadcast(
            self.session_id,
            WebSocketMessage(
                type="event.received",
                session_id=self.session_id,
                data={"event_count": 1},
            ),
        )

        self.assertEqual(result.attempted, 2)
        self.assertEqual(result.delivered, 2)
        self.assertEqual(result.removed, 0)
        self.assertEqual(len(socket_a.sent_payloads), 1)
        self.assertEqual(len(socket_b.sent_payloads), 1)
        self.assertEqual(other_socket.sent_payloads, [])

    async def test_broadcast_removes_failed_socket_and_keeps_sending(self) -> None:
        good_socket = FakeWebSocket()
        failed_socket = FakeWebSocket(fail_send=True)
        await self.manager.connect(self.session_id, failed_socket)
        await self.manager.connect(self.session_id, good_socket)

        result = await self.manager.broadcast(
            self.session_id,
            WebSocketMessage(type="session.ended", session_id=self.session_id),
        )

        self.assertEqual(result.attempted, 2)
        self.assertEqual(result.delivered, 1)
        self.assertEqual(result.removed, 1)
        self.assertEqual(self.manager.connection_count(self.session_id), 1)
        self.assertEqual(len(good_socket.sent_payloads), 1)

    async def test_disconnect_is_idempotent_and_cleans_empty_session(self) -> None:
        socket = FakeWebSocket()
        await self.manager.connect(self.session_id, socket)

        self.manager.disconnect(self.session_id, socket)
        self.manager.disconnect(self.session_id, socket)

        self.assertEqual(self.manager.connection_count(self.session_id), 0)
        self.assertEqual(self.manager.session_count(), 0)

    async def test_broadcast_to_empty_session_is_noop(self) -> None:
        result = await self.manager.broadcast(
            self.session_id,
            WebSocketMessage(type="noop", session_id=self.session_id),
        )

        self.assertEqual(result.attempted, 0)
        self.assertEqual(result.delivered, 0)
        self.assertEqual(result.removed, 0)


if __name__ == "__main__":
    unittest.main()
