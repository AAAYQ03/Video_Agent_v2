"""
Phase 2.3 分支隔离测试

覆盖：
  1. graph_model.create_branch 的图结构正确性（节点 ID/状态/边/intent_override）
  2. agent_loop._branch_job_dir 路由正确
  3. 跨分支并行就绪：两个分支的同层节点能同时返回 get_ready_nodes
  4. 分支与主路径不共享 result（深拷贝彻底）
"""
from __future__ import annotations

from pathlib import Path

import pytest

from core.agent_loop import _branch_job_dir
from core.graph_model import NodeStatus, NodeType, WorkflowGraph


# ============================================================
# create_branch 基础正确性
# ============================================================


class TestCreateBranchBasics:
    def test_descendants_count_matches(self):
        """从 INTENT_INJECTION 分叉应产出 5 个新节点（assets→storyboard→video→merge→output）。"""
        graph = WorkflowGraph.create_default(user_goal="test")
        new_nodes = graph.create_branch("node_intent", "exp1")
        assert len(new_nodes) == 5

        types = {n.type for n in new_nodes}
        assert types == {
            NodeType.ASSET_GENERATION,
            NodeType.STORYBOARD,
            NodeType.VIDEO_GENERATION,
            NodeType.MERGE,
            NodeType.OUTPUT,
        }

    def test_new_node_ids_have_branch_prefix(self):
        graph = WorkflowGraph.create_default(user_goal="test")
        new_nodes = graph.create_branch("node_intent", "exp1")
        for n in new_nodes:
            assert n.id.startswith("branch_exp1__")

    def test_new_nodes_have_branch_field_set(self):
        graph = WorkflowGraph.create_default(user_goal="test")
        new_nodes = graph.create_branch("node_intent", "exp1")
        for n in new_nodes:
            assert n.branch == "exp1"

    def test_new_nodes_status_is_pending(self):
        graph = WorkflowGraph.create_default(user_goal="test")
        new_nodes = graph.create_branch("node_intent", "exp1")
        for n in new_nodes:
            assert n.status == NodeStatus.PENDING
            assert n.result == {}
            assert n.retry_count == 0

    def test_main_branch_unchanged(self):
        """分叉后主分支节点完全未动。"""
        graph = WorkflowGraph.create_default(user_goal="test")
        original_main = [n for n in graph.nodes if n.branch == "main"]
        original_count = len(original_main)
        original_ids = {n.id for n in original_main}

        graph.create_branch("node_intent", "exp1")

        main_after = [n for n in graph.nodes if n.branch == "main"]
        assert len(main_after) == original_count
        assert {n.id for n in main_after} == original_ids


# ============================================================
# 边的处理 — 内部边 + 跨分支边
# ============================================================


class TestCreateBranchEdges:
    def test_internal_edges_remapped(self):
        """分支内部边的两端 ID 应都重映射。"""
        graph = WorkflowGraph.create_default(user_goal="test")
        graph.create_branch("node_intent", "exp1")

        # 找分支版的 ASSET_GEN → STORYBOARD 边
        branch_asset_id = "branch_exp1__node_assets"
        branch_storyboard_id = "branch_exp1__node_storyboard"

        matching = [
            e for e in graph.edges
            if e.source == branch_asset_id and e.target == branch_storyboard_id
        ]
        assert len(matching) == 1

    def test_cross_branch_edge_keeps_main_source(self):
        """
        WATERMARK_CLEAN → STORYBOARD 是主路径的边，但分支的 STORYBOARD 也需要
        WATERMARK 的产物。所以应有：WATERMARK_CLEAN(main) → STORYBOARD_branch 这条新边。
        """
        graph = WorkflowGraph.create_default(user_goal="test")
        graph.create_branch("node_intent", "exp1")

        branch_storyboard_id = "branch_exp1__node_storyboard"
        cross_edges = [
            e for e in graph.edges
            if e.target == branch_storyboard_id and e.source == "node_watermark"
        ]
        assert len(cross_edges) == 1

    def test_fork_node_connects_to_first_branch_descendant(self):
        """
        从 INTENT_INJECTION fork 时，原 INTENT→ASSETS 的边会被复制成
        INTENT(main) → ASSETS_branch（因为 ASSETS 是 fork_node 的直接子节点，
        被深拷贝；source 不在 descendants，保留原样）。
        """
        graph = WorkflowGraph.create_default(user_goal="test")
        graph.create_branch("node_intent", "exp1")

        branch_asset_id = "branch_exp1__node_assets"
        connecting = [
            e for e in graph.edges
            if e.source == "node_intent" and e.target == branch_asset_id
        ]
        assert len(connecting) == 1


# ============================================================
# intent_override 应用
# ============================================================


class TestIntentOverride:
    def test_intent_override_lands_in_branch_intent_node(self):
        """从 ABSTRACTION fork 时，分支会有自己的 INTENT_INJECTION 节点，
        intent_override 应写入它的 config。"""
        graph = WorkflowGraph.create_default(user_goal="改成日系")
        graph.create_branch("node_abstraction", "cyberpunk", intent_override="赛博朋克")

        branch_intent = next(
            n for n in graph.nodes
            if n.branch == "cyberpunk" and n.type == NodeType.INTENT_INJECTION
        )
        assert branch_intent.config.get("intent") == "赛博朋克"
        assert branch_intent.config.get("branch_name") == "cyberpunk"
        assert branch_intent.config.get("branch_intent_override") is True

    def test_main_intent_unchanged_by_branch_override(self):
        graph = WorkflowGraph.create_default(
            user_goal="test",
            intent_config={"intent": "日系清新"},
        )
        graph.create_branch(
            "node_abstraction", "cyberpunk", intent_override="赛博朋克",
        )
        main_intent = next(
            n for n in graph.nodes
            if n.branch == "main" and n.type == NodeType.INTENT_INJECTION
        )
        assert main_intent.config.get("intent") == "日系清新"


# ============================================================
# 错误处理
# ============================================================


class TestBranchErrors:
    def test_main_name_reserved(self):
        graph = WorkflowGraph.create_default(user_goal="test")
        with pytest.raises(ValueError, match="保留"):
            graph.create_branch("node_intent", "main")

    def test_duplicate_branch_raises(self):
        graph = WorkflowGraph.create_default(user_goal="test")
        graph.create_branch("node_intent", "exp1")
        with pytest.raises(ValueError, match="已存在"):
            graph.create_branch("node_intent", "exp1")

    def test_unknown_fork_node(self):
        graph = WorkflowGraph.create_default(user_goal="test")
        with pytest.raises(ValueError, match="不存在"):
            graph.create_branch("node_doesnt_exist", "exp1")

    def test_terminal_node_no_descendants(self):
        """OUTPUT 节点没有下游，不能从这里 fork。"""
        graph = WorkflowGraph.create_default(user_goal="test")
        with pytest.raises(ValueError, match="没有下游"):
            graph.create_branch("node_output", "exp1")

    def test_invalid_branch_name(self):
        graph = WorkflowGraph.create_default(user_goal="test")
        with pytest.raises(ValueError, match="非法"):
            graph.create_branch("node_intent", "")
        with pytest.raises(ValueError, match="非法"):
            graph.create_branch("node_intent", "with/slash")


# ============================================================
# 跨分支并行就绪
# ============================================================


class TestParallelReadiness:
    def test_two_branches_ready_at_same_layer(self):
        """主和 exp1 两个分支的 ASSET_GENERATION 节点应能同时就绪。"""
        graph = WorkflowGraph.create_default(user_goal="test")
        graph.create_branch("node_intent", "exp1")

        # 把所有上游标 SUCCESS（INPUT/ANALYZE/WATERMARK/FILM_IR/ABSTRACT/INTENT）
        for nid in [
            "node_input", "node_analyze", "node_watermark",
            "node_film_ir", "node_abstraction", "node_intent",
        ]:
            graph.get_node(nid).status = NodeStatus.SUCCESS

        ready = graph.get_ready_nodes()
        # 应该 ASSET_GEN(main) 和 ASSET_GEN(exp1) 都就绪
        ready_pairs = {(n.type, n.branch) for n in ready}
        assert (NodeType.ASSET_GENERATION, "main") in ready_pairs
        assert (NodeType.ASSET_GENERATION, "exp1") in ready_pairs


# ============================================================
# 深拷贝彻底性 — 分支与主路径不共享内存
# ============================================================


class TestDeepCopy:
    def test_branch_node_result_independent_from_main(self):
        graph = WorkflowGraph.create_default(user_goal="test")
        graph.create_branch("node_intent", "exp1")

        main_asset = graph.get_node("node_assets")
        branch_asset = graph.get_node("branch_exp1__node_assets")

        # 改一个不影响另一个
        main_asset.result = {"output": "main_video.mp4"}
        assert branch_asset.result == {}

        branch_asset.result = {"output": "exp1_video.mp4"}
        assert main_asset.result == {"output": "main_video.mp4"}

    def test_branch_config_independent_from_main(self):
        graph = WorkflowGraph.create_default(
            user_goal="test", intent_config={"intent": "原始"}
        )
        graph.create_branch(
            "node_abstraction", "exp1", intent_override="新方向"
        )

        main_intent = next(
            n for n in graph.nodes
            if n.branch == "main" and n.type == NodeType.INTENT_INJECTION
        )
        branch_intent = next(
            n for n in graph.nodes
            if n.branch == "exp1" and n.type == NodeType.INTENT_INJECTION
        )

        # 改其中一个的 config 不影响另一个
        main_intent.config["new_key"] = "main_value"
        assert "new_key" not in branch_intent.config


# ============================================================
# _branch_job_dir 路由
# ============================================================


class TestBranchJobDirRouting:
    def test_main_branch_uses_root_job_dir(self):
        root = Path("/tmp/test_proj")
        assert _branch_job_dir(root, "job_abc", "main") == root / "jobs" / "job_abc"

    def test_other_branch_uses_subdir(self):
        root = Path("/tmp/test_proj")
        assert _branch_job_dir(root, "job_abc", "exp1") == (
            root / "jobs" / "job_abc" / "branches" / "exp1"
        )


# ============================================================
# 持久化往返（save → load 后分支结构保留）
# ============================================================


class TestBranchPersistence:
    def test_branch_survives_save_load_roundtrip(self, tmp_path):
        # 从 ABSTRACTION fork 让 INTENT 进 descendants，才能验证 intent_override
        # 经过 save→load 仍然保留
        graph = WorkflowGraph.create_default(user_goal="test")
        graph.create_branch("node_abstraction", "exp1", intent_override="新方向")

        job_dir = tmp_path / "jobs" / "job_test"
        job_dir.mkdir(parents=True)
        graph.save(job_dir)

        loaded = WorkflowGraph.load(job_dir)
        assert loaded is not None

        branch_nodes = [n for n in loaded.nodes if n.branch == "exp1"]
        assert len(branch_nodes) == 6  # INTENT + ASSETS + STORYBOARD + VIDEO + MERGE + OUTPUT

        branch_intent = next(
            n for n in branch_nodes if n.type == NodeType.INTENT_INJECTION
        )
        assert branch_intent.config.get("intent") == "新方向"
