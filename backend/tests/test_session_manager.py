import unittest

from backend.app.core import SessionConflictError, SessionManager, SessionNotFoundError
from backend.app.models import StartSessionRequest


class SessionManagerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.manager = SessionManager()

    def test_create_session_starts_recording(self) -> None:
        session = self.manager.create_session(
            StartSessionRequest(title="通信原理第8讲", course="通信原理")
        )

        self.assertTrue(session.session_id.startswith("lec_"))
        self.assertEqual(session.title, "通信原理第8讲")
        self.assertEqual(session.course, "通信原理")
        self.assertEqual(session.status, "recording")
        self.assertIsNone(session.end_time)

    def test_get_session_raises_for_unknown_id(self) -> None:
        with self.assertRaises(SessionNotFoundError):
            self.manager.get_session("lec_missing")

    def test_end_session_is_idempotent(self) -> None:
        session = self.manager.create_session(StartSessionRequest(title="测试课堂"))

        ended_once = self.manager.end_session(session.session_id)
        ended_twice = self.manager.end_session(session.session_id)

        self.assertEqual(ended_once.status, "ended")
        self.assertEqual(ended_once.end_time, ended_twice.end_time)

    def test_require_recording_rejects_ended_session(self) -> None:
        session = self.manager.create_session(StartSessionRequest(title="测试课堂"))
        self.manager.end_session(session.session_id)

        with self.assertRaises(SessionConflictError):
            self.manager.require_recording(session.session_id)


if __name__ == "__main__":
    unittest.main()
