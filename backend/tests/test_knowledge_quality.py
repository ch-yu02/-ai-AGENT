import unittest

from backend.app.knowledge_quality import is_low_value_entity_name


class KnowledgeQualityTest(unittest.TestCase):
    def test_filters_generic_classroom_and_placeholder_labels(self) -> None:
        for label in [
            "知识点",
            "本节课重点",
            "核心内容",
            "直接原因",
            "ent_1",
            "e2",
            "概念名",
            "第一个问题",
        ]:
            self.assertTrue(is_low_value_entity_name(label), label)

    def test_keeps_concrete_course_concepts(self) -> None:
        for label in [
            "傅里叶变换",
            "频域",
            "鸦片战争",
            "半殖民地半封建社会",
            "农民阶级",
            "鸦片战争直接原因",
        ]:
            self.assertFalse(is_low_value_entity_name(label), label)


if __name__ == "__main__":
    unittest.main()
