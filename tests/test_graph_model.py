# tests/test_graph_model.py
"""
Step 0.1 验证 — DAG 数据模型单元测试

覆盖：
- 拓扑排序
- 环检测
- 就绪节点计算
- JSON 序列化/反序列化
- DAG 合法性校验
- 节点/边增删
- 级联失效
- 线性 DAG 工厂方法
"""

import json
import tempfile
from pathlib import Path

import pytest
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.graph_model import (
    Node, Edge, WorkflowGraph,
    NodeType, NodeStatus,
    UNDELETABLE_TYPES, DEFAULT_GATE_TYPES,
)


# ============================================================
# 辅助函数
# ============================================================

def make_linear_graph(n=4) -> WorkflowGraph:
    """创建一个 n 节点的简单线性 DAG: A → B → C → D"""
    types = [NodeType.INPUT, NodeType.ANALYZE, NodeType.STORYBOARD, NodeType.OUTPUT]
    nodes = []
    edges = []
    for i in range(n):
        t = types[i] if i < len(types) else NodeType.CUSTOM_PROMPT
        nodes.append(Node(id=f"n{i}", type=t))
    for i in range(n - 1):
        edges.append(Edge(id=f"e{i}", source=f"n{i}", target=f"n{i+1}"))
    return WorkflowGraph(nodes=nodes, edges=edges, user_goal="test")


def make_diamond_graph() -> WorkflowGraph:
    """
    菱形 DAG:
        A
       / \\
      B   C
       \\ /
        D
    """
    nodes = [
        Node(id="A", type=NodeType.INPUT),
        Node(id="B", type=NodeType.STORYBOARD),
        Node(id="C", type=NodeType.VIDEO_GENERATION),
        Node(id="D", type=NodeType.OUTPUT),
    ]
    edges = [
        Edge(id="e1", source="A", target="B"),
        Edge(id="e2", source="A", target="C"),
        Edge(id="e3", source="B", target="D"),
        Edge(id="e4", source="C", target="D"),
    ]
    return WorkflowGraph(nodes=nodes, edges=edges, user_goal="test")


# ============================================================
# 拓扑排序
# ============================================================

class TestTopologicalSort:

    def test_linear(self):
        g = make_linear_graph()
        sorted_nodes = g.topological_sort()
        ids = [n.id for n in sorted_nodes]
        assert ids == ["n0", "n1", "n2", "n3"]

    def test_diamond(self):
        g = make_diamond_graph()
        sorted_nodes = g.topological_sort()
        ids = [n.id for n in sorted_nodes]
        # A 必须在 B、C 之前；B、C 必须在 D 之前
        assert ids.index("A") < ids.index("B")
        assert ids.index("A") < ids.index("C")
        assert ids.index("B") < ids.index("D")
        assert ids.index("C") < ids.index("D")

    def test_single_node(self):
        g = WorkflowGraph(
            nodes=[Node(id="only", type=NodeType.INPUT)],
            edges=[],
        )
        result = g.topological_sort()
        assert len(result) == 1
        assert result[0].id == "only"


# ============================================================
# 环检测
# ============================================================

class TestCycleDetection:

    def test_no_cycle(self):
        g = make_linear_graph()
        assert g.has_cycle() is False

    def test_simple_cycle(self):
        """A → B → A"""
        nodes = [
            Node(id="A", type=NodeType.INPUT),
            Node(id="B", type=NodeType.ANALYZE),
        ]
        edges = [
            Edge(id="e1", source="A", target="B"),
            Edge(id="e2", source="B", target="A"),
        ]
        g = WorkflowGraph(nodes=nodes, edges=edges)
        assert g.has_cycle() is True

    def test_triangle_cycle(self):
        """A → B → C → A"""
        nodes = [
            Node(id="A", type=NodeType.INPUT),
            Node(id="B", type=NodeType.ANALYZE),
            Node(id="C", type=NodeType.STORYBOARD),
        ]
        edges = [
            Edge(id="e1", source="A", target="B"),
            Edge(id="e2", source="B", target="C"),
            Edge(id="e3", source="C", target="A"),
        ]
        g = WorkflowGraph(nodes=nodes, edges=edges)
        assert g.has_cycle() is True

    def test_diamond_no_cycle(self):
        g = make_diamond_graph()
        assert g.has_cycle() is False


# ============================================================
# 就绪节点
# ============================================================

class TestReadyNodes:

    def test_initial_state(self):
        """初始状态下只有 INPUT 节点（无父节点）就绪"""
        g = make_linear_graph()
        ready = g.get_ready_nodes()
        assert len(ready) == 1
        assert ready[0].id == "n0"

    def test_after_first_complete(self):
        """n0 完成后，n1 就绪"""
        g = make_linear_graph()
        g.get_node("n0").mark_success()
        ready = g.get_ready_nodes()
        assert len(ready) == 1
        assert ready[0].id == "n1"

    def test_diamond_parallel(self):
        """菱形图：A 完成后，B 和 C 同时就绪"""
        g = make_diamond_graph()
        g.get_node("A").mark_success()
        ready = g.get_ready_nodes()
        ready_ids = {n.id for n in ready}
        assert ready_ids == {"B", "C"}

    def test_diamond_converge(self):
        """菱形图：B、C 都完成后，D 才就绪"""
        g = make_diamond_graph()
        g.get_node("A").mark_success()
        g.get_node("B").mark_success()
        # C 还没完成，D 不就绪
        ready = g.get_ready_nodes()
        ready_ids = {n.id for n in ready}
        assert "D" not in ready_ids
        assert "C" in ready_ids

        # C 也完成了
        g.get_node("C").mark_success()
        ready = g.get_ready_nodes()
        ready_ids = {n.id for n in ready}
        assert ready_ids == {"D"}

    def test_running_not_ready(self):
        """RUNNING 状态的节点不算就绪"""
        g = make_linear_graph()
        g.get_node("n0").mark_running()
        ready = g.get_ready_nodes()
        assert len(ready) == 0

    def test_skipped_parent_counts_as_done(self):
        """父节点 SKIPPED 等同于 SUCCESS"""
        g = make_linear_graph()
        g.get_node("n0").status = NodeStatus.SKIPPED
        ready = g.get_ready_nodes()
        assert len(ready) == 1
        assert ready[0].id == "n1"


# ============================================================
# 状态查询
# ============================================================

class TestStateQueries:

    def test_is_complete(self):
        g = make_linear_graph()
        assert g.is_complete() is False

        for n in g.nodes:
            n.mark_success()
        assert g.is_complete() is True

    def test_is_complete_with_failed(self):
        """FAILED 也算终态"""
        g = make_linear_graph()
        for n in g.nodes:
            n.mark_success()
        g.get_node("n2").mark_failed("test error")
        assert g.is_complete() is True

    def test_has_failures(self):
        g = make_linear_graph()
        assert g.has_failures() is False
        g.get_node("n1").mark_failed("error")
        assert g.has_failures() is True

    def test_has_waiting_gates(self):
        g = make_linear_graph()
        assert g.has_waiting_gates() is False
        g.get_node("n2").status = NodeStatus.WAITING_APPROVAL
        assert g.has_waiting_gates() is True

    def test_progress(self):
        g = make_linear_graph()
        g.get_node("n0").mark_success()
        g.get_node("n1").mark_running()
        g.get_node("n3").mark_failed("err")
        progress = g.get_progress()
        assert progress == {"total": 4, "done": 1, "failed": 1, "running": 1}


# ============================================================
# 序列化 / 反序列化
# ============================================================

class TestSerialization:

    def test_roundtrip(self):
        """to_dict → from_dict 无损"""
        g = make_linear_graph()
        g.get_node("n0").mark_success({"shots": 12})
        g.get_node("n1").config = {"intent": "test"}

        data = g.to_dict()
        g2 = WorkflowGraph.from_dict(data)

        assert len(g2.nodes) == len(g.nodes)
        assert len(g2.edges) == len(g.edges)
        assert g2.user_goal == g.user_goal
        assert g2.get_node("n0").status == NodeStatus.SUCCESS
        assert g2.get_node("n0").result == {"shots": 12}
        assert g2.get_node("n1").config == {"intent": "test"}

    def test_json_roundtrip(self):
        """JSON string 序列化/反序列化无损"""
        g = make_linear_graph()
        json_str = json.dumps(g.to_dict(), ensure_ascii=False)
        data = json.loads(json_str)
        g2 = WorkflowGraph.from_dict(data)
        assert len(g2.nodes) == len(g.nodes)

    def test_save_and_load(self):
        """文件持久化 round-trip"""
        g = make_linear_graph()
        g.get_node("n0").mark_success({"test": True})

        with tempfile.TemporaryDirectory() as tmpdir:
            job_dir = Path(tmpdir)
            g.save(job_dir)

            # 文件存在
            assert (job_dir / "agent_graph.json").exists()

            # 加载回来
            g2 = WorkflowGraph.load(job_dir)
            assert g2 is not None
            assert len(g2.nodes) == 4
            assert g2.get_node("n0").status == NodeStatus.SUCCESS

    def test_load_nonexistent(self):
        """加载不存在的文件返回 None"""
        with tempfile.TemporaryDirectory() as tmpdir:
            g = WorkflowGraph.load(Path(tmpdir))
            assert g is None


# ============================================================
# DAG 合法性校验
# ============================================================

class TestValidation:

    def test_valid_default(self):
        """用工厂方法生成的默认 DAG 应通过校验"""
        g = WorkflowGraph.create_default("test")
        errors = g.validate()
        assert errors == []

    def test_missing_input(self):
        nodes = [Node(id="n0", type=NodeType.ANALYZE)]
        g = WorkflowGraph(nodes=nodes, edges=[])
        errors = g.validate()
        assert any("INPUT" in e for e in errors)

    def test_missing_output(self):
        nodes = [Node(id="n0", type=NodeType.INPUT)]
        g = WorkflowGraph(nodes=nodes, edges=[])
        errors = g.validate()
        assert any("OUTPUT" in e for e in errors)

    def test_unreachable_node(self):
        """孤立节点应被检测到"""
        g = make_linear_graph()
        g.nodes.append(Node(id="orphan", type=NodeType.CUSTOM_PROMPT))
        g._rebuild_index()
        errors = g.validate()
        assert any("Unreachable" in e for e in errors)

    def test_cycle_detected(self):
        nodes = [
            Node(id="A", type=NodeType.INPUT),
            Node(id="B", type=NodeType.OUTPUT),
        ]
        edges = [
            Edge(id="e1", source="A", target="B"),
            Edge(id="e2", source="B", target="A"),
        ]
        g = WorkflowGraph(nodes=nodes, edges=edges)
        errors = g.validate()
        assert any("cycle" in e.lower() for e in errors)


# ============================================================
# 节点增删
# ============================================================

class TestNodeEditing:

    def test_add_node(self):
        g = make_linear_graph()
        new_node = Node(id="new1", type=NodeType.CUSTOM_PROMPT)
        errors = g.add_node(new_node)
        assert errors == []
        assert g.get_node("new1") is not None

    def test_add_duplicate_node(self):
        g = make_linear_graph()
        errors = g.add_node(Node(id="n0", type=NodeType.INPUT))
        assert len(errors) > 0

    def test_remove_middle_node_auto_reconnect(self):
        """删除中间节点后上下游自动重连"""
        # 构造 A → B → C → D，B 使用可删除类型
        nodes = [
            Node(id="A", type=NodeType.INPUT),
            Node(id="B", type=NodeType.CUSTOM_PROMPT),  # 可删除
            Node(id="C", type=NodeType.STORYBOARD),
            Node(id="D", type=NodeType.OUTPUT),
        ]
        edges = [
            Edge(id="e1", source="A", target="B"),
            Edge(id="e2", source="B", target="C"),
            Edge(id="e3", source="C", target="D"),
        ]
        g = WorkflowGraph(nodes=nodes, edges=edges)
        errors = g.remove_node("B")  # 删除 B
        assert errors == []
        assert g.get_node("B") is None
        # A 应该直连到 C
        children_of_a = g.get_children("A")
        assert any(c.id == "C" for c in children_of_a)

    def test_cannot_delete_input(self):
        g = make_linear_graph()
        errors = g.remove_node("n0")  # INPUT 节点
        assert len(errors) > 0
        assert g.get_node("n0") is not None

    def test_cannot_delete_running(self):
        g = make_linear_graph()
        g.get_node("n1").mark_running()
        errors = g.remove_node("n1")
        assert len(errors) > 0


# ============================================================
# 边增删
# ============================================================

class TestEdgeEditing:

    def test_add_edge(self):
        g = make_linear_graph()
        g.add_node(Node(id="extra", type=NodeType.CUSTOM_PROMPT))
        errors = g.add_edge(Edge(id="e_new", source="n1", target="extra"))
        assert errors == []

    def test_add_edge_creates_cycle(self):
        """添加会导致环的边应被拒绝"""
        g = make_linear_graph()  # n0 → n1 → n2 → n3
        errors = g.add_edge(Edge(id="e_bad", source="n2", target="n0"))
        assert len(errors) > 0
        assert "cycle" in errors[0].lower()

    def test_add_duplicate_edge(self):
        g = make_linear_graph()
        errors = g.add_edge(Edge(id="e_dup", source="n0", target="n1"))
        assert len(errors) > 0

    def test_remove_edge(self):
        g = make_linear_graph()
        errors = g.remove_edge("e0")
        assert errors == []
        # n0 不再连到 n1
        children = g.get_children("n0")
        assert len(children) == 0

    def test_remove_nonexistent_edge(self):
        g = make_linear_graph()
        errors = g.remove_edge("nonexistent")
        assert len(errors) > 0


# ============================================================
# 级联失效
# ============================================================

class TestCascadeInvalidate:

    def test_cascade_resets_downstream(self):
        """修改 n1 后，n1/n2/n3 都应该回到 PENDING"""
        g = make_linear_graph()
        for n in g.nodes:
            n.mark_success()

        g.cascade_invalidate("n1")

        assert g.get_node("n0").status == NodeStatus.SUCCESS  # 上游不受影响
        assert g.get_node("n1").status == NodeStatus.PENDING
        assert g.get_node("n2").status == NodeStatus.PENDING
        assert g.get_node("n3").status == NodeStatus.PENDING

    def test_cascade_diamond(self):
        """菱形图：修改 A，所有节点都重置"""
        g = make_diamond_graph()
        for n in g.nodes:
            n.mark_success()

        g.cascade_invalidate("A")

        for n in g.nodes:
            assert n.status == NodeStatus.PENDING


# ============================================================
# 工厂方法
# ============================================================

class TestFactory:

    def test_create_default(self):
        g = WorkflowGraph.create_default(
            user_goal="改成日系风格",
            intent_config={"intent": "改成日系风格"},
        )
        assert len(g.nodes) == 11  # 含 WATERMARK_CLEAN
        assert g.user_goal == "改成日系风格"

        # 验证首尾节点类型
        sorted_nodes = g.topological_sort()
        assert sorted_nodes[0].type == NodeType.INPUT
        assert sorted_nodes[-1].type == NodeType.OUTPUT

        # 验证无环
        assert g.has_cycle() is False

        # 验证合法性
        errors = g.validate()
        assert errors == []

        # 验证 INTENT_INJECTION 节点有 config
        intent_nodes = g.get_nodes_by_type(NodeType.INTENT_INJECTION)
        assert len(intent_nodes) == 1
        assert intent_nodes[0].config == {"intent": "改成日系风格"}

        # 验证默认 Gate（INTENT_INJECTION, ASSET_GENERATION, STORYBOARD）
        for n in g.nodes:
            if n.type in DEFAULT_GATE_TYPES:
                assert n.gate is True, f"{n.type.value} should be a Gate"
            else:
                assert n.gate is False, f"{n.type.value} should NOT be a Gate"

    def test_create_default_validates(self):
        """工厂方法生成的 DAG 必须通过校验"""
        g = WorkflowGraph.create_default("test")
        errors = g.validate()
        assert errors == []

    def test_create_default_parallel_paths(self):
        """验证 ANALYZE 后 WATERMARK_CLEAN 和 FILM_IR_ANALYSIS 并行"""
        g = WorkflowGraph.create_default("test")

        # ANALYZE 完成后，WATERMARK_CLEAN 和 FILM_IR_ANALYSIS 同时就绪
        g.get_node("node_input").mark_success()
        g.get_node("node_analyze").mark_success()
        ready = g.get_ready_nodes()
        ready_types = {n.type for n in ready}
        assert NodeType.WATERMARK_CLEAN in ready_types
        assert NodeType.FILM_IR_ANALYSIS in ready_types

    def test_create_default_storyboard_waits_for_both_paths(self):
        """验证 STORYBOARD 必须等水印清理和意图注入都完成"""
        g = WorkflowGraph.create_default("test")

        # 完成路径 B（Film IR 链）但不完成路径 A（水印清理）
        for nid in ["node_input", "node_analyze", "node_film_ir",
                     "node_abstraction", "node_intent", "node_assets"]:
            g.get_node(nid).mark_success()

        # STORYBOARD 不应该就绪（水印清理还没完成）
        ready = g.get_ready_nodes()
        ready_ids = {n.id for n in ready}
        assert "node_storyboard" not in ready_ids
        assert "node_watermark" in ready_ids  # 水印清理应该就绪

        # 完成水印清理
        g.get_node("node_watermark").mark_success()
        ready = g.get_ready_nodes()
        ready_ids = {n.id for n in ready}
        assert "node_storyboard" in ready_ids  # 现在 STORYBOARD 就绪了


# ============================================================
# Node 数据类
# ============================================================

class TestNode:

    def test_status_transitions(self):
        n = Node(id="test", type=NodeType.ANALYZE)
        assert n.status == NodeStatus.PENDING

        n.mark_running()
        assert n.status == NodeStatus.RUNNING
        assert n.started_at is not None

        n.mark_success({"result": 42})
        assert n.status == NodeStatus.SUCCESS
        assert n.completed_at is not None
        assert n.result == {"result": 42}

    def test_failed_and_retry(self):
        n = Node(id="test", type=NodeType.STORYBOARD, max_retries=2)
        n.mark_failed("api error")
        assert n.status == NodeStatus.FAILED
        assert n.result == {"error": "api error"}

        assert n.can_retry() is True
        n.reset_for_retry()
        assert n.status == NodeStatus.PENDING
        assert n.retry_count == 1

        n.mark_failed("api error again")
        n.reset_for_retry()
        assert n.retry_count == 2
        assert n.can_retry() is False  # 达到上限

    def test_auto_label(self):
        n = Node(id="test", type=NodeType.MERGE)
        assert n.label == "合并输出"

    def test_serialization(self):
        n = Node(id="test", type=NodeType.ANALYZE, config={"key": "val"})
        n.mark_success({"shots": 5})
        d = n.to_dict()
        n2 = Node.from_dict(d)
        assert n2.id == n.id
        assert n2.type == n.type
        assert n2.status == n.status
        assert n2.result == n.result
        assert n2.config == n.config
