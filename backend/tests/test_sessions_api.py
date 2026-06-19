import unittest

from backend.app.api import sessions as sessions_api
from backend.app.core import session_manager
from backend.app.models import StartSessionRequest, UpdateSessionRequest


class SessionsApiTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        session_manager.clear()

    def tearDown(self) -> None:
        session_manager.clear()

    async def test_list_recording_sessions_returns_only_active_sessions(self) -> None:
        first = session_manager.create_session(StartSessionRequest(title="第一节"))
        second = session_manager.create_session(StartSessionRequest(title="第二节"))
        session_manager.end_session(first.session_id)

        sessions = await sessions_api.list_recording_sessions()

        self.assertEqual([session.session_id for session in sessions], [second.session_id])
        self.assertEqual(sessions[0].status, "recording")

    async def test_update_session_changes_recording_metadata(self) -> None:
        session = session_manager.create_session(
            StartSessionRequest(title="未命名课堂", course="旧课程")
        )

        updated = await sessions_api.update_session(
            session.session_id,
            UpdateSessionRequest(title="傅里叶变换导论", course="信号与系统"),
        )

        self.assertEqual(updated.title, "傅里叶变换导论")
        self.assertEqual(updated.course, "信号与系统")
        self.assertEqual(
            session_manager.get_session(session.session_id).title,
            "傅里叶变换导论",
        )

    async def test_update_session_rejects_empty_title(self) -> None:
        session = session_manager.create_session(StartSessionRequest(title="未命名课堂"))

        with self.assertRaises(Exception) as caught:
            await sessions_api.update_session(
                session.session_id,
                UpdateSessionRequest(title="   "),
            )

        self.assertIn("title cannot be empty", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
