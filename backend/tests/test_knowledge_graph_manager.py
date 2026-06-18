import unittest

from backend.app.core import KnowledgeGraphManager, KnowledgeGraphNotFoundError
from backend.app.models import KnowledgeExtraction, RealtimeEvent


class KnowledgeGraphManagerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.manager = KnowledgeGraphManager()
        self.session_id = "lec_test_graph_001"
        self.manager.start_session(self.session_id)

    def test_apply_extraction_adds_nodes_and_edges(self) -> None:
        patch = self.manager.apply_extraction(
            KnowledgeExtraction(
                extraction_id="ext_001",
                session_id=self.session_id,
                source_segment_ids=["seg_001"],
                timestamp_range=(10.0, 15.0),
                entities=[
                    {
                        "entity_id": "ent_fourier",
                        "name": "傅里叶变换",
                        "type": "concept",
                        "description": "时域到频域的变换方法",
                    },
                    {"entity_id": "ent_freq", "name": "频域", "type": "concept"},
                ],
                relations=[
                    {
                        "source": "傅里叶变换",
                        "target": "频域",
                        "relation": "maps_to",
                    }
                ],
                importance=0.91,
            )
        )

        graph = self.manager.get_graph(self.session_id)
        self.assertEqual(graph.version, 1)
        self.assertEqual(len(graph.nodes), 2)
        self.assertEqual(len(graph.edges), 1)
        self.assertEqual(patch.from_version, 0)
        self.assertEqual(patch.to_version, 1)
        self.assertEqual([op.op for op in patch.operations], ["add_node", "add_node", "add_edge"])
        self.assertIn("ent_fourier", graph.root_nodes)

    def test_repeated_entity_updates_existing_node_without_duplicate(self) -> None:
        extraction = KnowledgeExtraction(
            extraction_id="ext_001",
            session_id=self.session_id,
            entities=[{"name": "傅里叶变换"}],
            importance=0.7,
        )
        self.manager.apply_extraction(extraction)

        patch = self.manager.apply_extraction(
            KnowledgeExtraction(
                extraction_id="ext_002",
                session_id=self.session_id,
                entities=[
                    {
                        "name": " 傅里叶变换 ",
                        "description": "将信号转换到频域分析",
                    }
                ],
                importance=0.95,
            )
        )

        graph = self.manager.get_graph(self.session_id)
        self.assertEqual(len(graph.nodes), 1)
        self.assertEqual(graph.nodes[0].importance, 0.95)
        self.assertEqual(graph.nodes[0].summary, "将信号转换到频域分析")
        self.assertEqual(patch.operations[0].op, "update_node")

    def test_graph_source_refs_are_compact_and_skip_event_refs(self) -> None:
        self.manager.apply_extraction(
            KnowledgeExtraction(
                extraction_id="ext_many_refs_001",
                session_id=self.session_id,
                source_segment_ids=[
                    "seg_001",
                    "seg_002",
                    "seg_003",
                    "seg_004",
                    "seg_005",
                ],
                timestamp_range=(1.0, 12.0),
                entities=[{"name": "傅里叶变换"}],
                relations=[
                    {
                        "source": "傅里叶变换",
                        "target": "频域",
                        "relation": "maps_to",
                    }
                ],
            )
        )
        self.manager.apply_extraction(
            KnowledgeExtraction(
                extraction_id="ext_many_refs_002",
                session_id=self.session_id,
                source_segment_ids=["seg_006", "seg_007"],
                timestamp_range=(13.0, 20.0),
                entities=[{"name": "傅里叶变换", "description": "频域分析工具"}],
                relations=[
                    {
                        "source": "傅里叶变换",
                        "target": "频域",
                        "relation": "maps_to",
                    }
                ],
            )
        )

        graph = self.manager.get_graph(self.session_id)
        fourier = next(node for node in graph.nodes if node.label == "傅里叶变换")
        self.assertLessEqual(len(fourier.source_refs), 3)
        self.assertEqual({ref.type for ref in fourier.source_refs}, {"segment"})
        self.assertEqual(
            [ref.id for ref in fourier.source_refs],
            ["seg_005", "seg_006", "seg_007"],
        )

        self.assertEqual(len(graph.edges), 1)
        edge = graph.edges[0]
        self.assertLessEqual(len(edge.source_refs), 2)
        self.assertEqual({ref.type for ref in edge.source_refs}, {"segment"})
        self.assertEqual([ref.id for ref in edge.source_refs], ["seg_006", "seg_007"])

    def test_relation_can_create_missing_endpoint_nodes(self) -> None:
        patch = self.manager.apply_extraction(
            KnowledgeExtraction(
                extraction_id="ext_003",
                session_id=self.session_id,
                relations=[
                    {
                        "source": "傅里叶变换",
                        "target": "时域",
                        "relation": "input_domain",
                    }
                ],
            )
        )

        graph = self.manager.get_graph(self.session_id)
        self.assertEqual(len(graph.nodes), 2)
        self.assertEqual(len(graph.edges), 1)
        self.assertEqual([op.op for op in patch.operations], ["add_node", "add_node", "add_edge"])

    def test_non_knowledge_event_does_not_update_graph(self) -> None:
        patch = self.manager.handle_event(
            RealtimeEvent(
                session_id=self.session_id,
                event_type="transcript.segment",
                payload={"text": "不会更新图谱"},
            )
        )

        graph = self.manager.get_graph(self.session_id)
        self.assertIsNone(patch)
        self.assertEqual(graph.version, 0)
        self.assertEqual(graph.nodes, [])

    def test_get_graph_raises_for_unknown_session(self) -> None:
        with self.assertRaises(KnowledgeGraphNotFoundError):
            self.manager.get_graph("missing")


if __name__ == "__main__":
    unittest.main()
