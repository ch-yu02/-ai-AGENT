import unittest

from backend.app.agent import IntentRouter


class IntentRouterTest(unittest.TestCase):
    def setUp(self) -> None:
        self.router = IntentRouter()

    def test_routes_summary_prompts(self) -> None:
        self.assertEqual(self.router.route("总结这节课的重点"), "summary")
        self.assertEqual(self.router.route("给我一份复习提纲"), "summary")

    def test_routes_todo_prompts(self) -> None:
        self.assertEqual(self.router.route("老师布置了什么作业？"), "todos")
        self.assertEqual(self.router.route("下次考试提醒有哪些"), "todos")

    def test_routes_quiz_prompts(self) -> None:
        self.assertEqual(self.router.route("根据这节课出 5 道题"), "quiz")
        self.assertEqual(self.router.route("quiz me"), "quiz")

    def test_defaults_to_qa_and_honors_explicit_mode(self) -> None:
        self.assertEqual(self.router.route("傅里叶变换讲了什么？"), "qa")
        self.assertEqual(self.router.route("随便问", mode="summary"), "summary")


if __name__ == "__main__":
    unittest.main()
