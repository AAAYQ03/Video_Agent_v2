# tests/test_node_executors.py
"""
Step 0.3 验证 — 节点执行器单元测试

覆盖：
- 执行器注册表完整性（所有默认 DAG 节点都有对应执行器）
- 统一执行入口（异常捕获、计时、结果标准化）
- INPUT / OUTPUT 执行器（不需要 API Key）
- 未注册类型的错误处理
"""

import tempfile
from pathlib import Path

import pytest
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.graph_model import Node, NodeType, WorkflowGraph
from core.node_executors import (
    ExecutionContext,
    execute_node,
    NODE_EXECUTORS,
    _execute_input,
    _execute_output,
)


# ============================================================
# 执行器注册表
# ============================================================

class TestExecutorRegistry:

    def test_all_default_dag_nodes_have_executors(self):
        """默认 DAG 模板中的所有节点类型都有对应执行器"""
        g = WorkflowGraph.create_default("test")
        for node in g.nodes:
            assert node.type in NODE_EXECUTORS, (
                f"NodeType {node.type.value} has no registered executor"
            )

    def test_registry_values_are_callable(self):
        """注册表中的值都是可调用的"""
        for node_type, executor in NODE_EXECUTORS.items():
            assert callable(executor), f"Executor for {node_type.value} is not callable"

    def test_core_types_covered(self):
        """核心节点类型全部覆盖"""
        required = [
            NodeType.INPUT, NodeType.ANALYZE, NodeType.WATERMARK_CLEAN,
            NodeType.FILM_IR_ANALYSIS, NodeType.ABSTRACTION,
            NodeType.INTENT_INJECTION, NodeType.ASSET_GENERATION,
            NodeType.STORYBOARD, NodeType.VIDEO_GENERATION,
            NodeType.MERGE, NodeType.OUTPUT,
        ]
        for nt in required:
            assert nt in NODE_EXECUTORS, f"Missing executor for {nt.value}"


# ============================================================
# 统一执行入口
# ============================================================

class TestExecuteNode:

    def test_exception_caught(self):
        """执行器抛异常时被捕获，返回标准化错误"""
        def bad_executor(ctx):
            raise RuntimeError("something broke")

        # 临时注入一个会爆的执行器
        original = NODE_EXECUTORS.get(NodeType.CUSTOM_PROMPT)
        NODE_EXECUTORS[NodeType.CUSTOM_PROMPT] = bad_executor
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                ctx = ExecutionContext(
                    job_id="test",
                    job_dir=Path(tmpdir),
                    node=Node(id="n1", type=NodeType.CUSTOM_PROMPT),
                )
                result = execute_node(ctx)
                assert result["status"] == "failed"
                assert "RuntimeError" in result["error"]
                assert "duration_ms" in result
        finally:
            if original:
                NODE_EXECUTORS[NodeType.CUSTOM_PROMPT] = original
            else:
                NODE_EXECUTORS.pop(NodeType.CUSTOM_PROMPT, None)

    def test_unregistered_type(self):
        """未注册的节点类型返回错误"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # STYLE_OVERRIDE 没有注册执行器
            ctx = ExecutionContext(
                job_id="test",
                job_dir=Path(tmpdir),
                node=Node(id="n1", type=NodeType.STYLE_OVERRIDE),
            )
            result = execute_node(ctx)
            assert result["status"] == "failed"
            assert "No executor" in result["error"]

    def test_duration_recorded(self):
        """执行时间被记录"""
        with tempfile.TemporaryDirectory() as tmpdir:
            job_dir = Path(tmpdir)
            # 创建 input.mp4 让 INPUT 执行器成功
            (job_dir / "input.mp4").write_bytes(b"fake video")

            ctx = ExecutionContext(
                job_id="test",
                job_dir=job_dir,
                node=Node(id="n1", type=NodeType.INPUT),
            )
            result = execute_node(ctx)
            assert "duration_ms" in result
            assert isinstance(result["duration_ms"], int)
            assert result["duration_ms"] >= 0


# ============================================================
# INPUT 执行器
# ============================================================

class TestInputExecutor:

    def test_success(self):
        """input.mp4 存在时返回 success"""
        with tempfile.TemporaryDirectory() as tmpdir:
            job_dir = Path(tmpdir)
            (job_dir / "input.mp4").write_bytes(b"fake video data")

            ctx = ExecutionContext(
                job_id="test",
                job_dir=job_dir,
                node=Node(id="n1", type=NodeType.INPUT),
            )
            result = _execute_input(ctx)
            assert result["status"] == "success"
            assert "video_path" in result

    def test_missing_video(self):
        """input.mp4 不存在时返回 failed"""
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = ExecutionContext(
                job_id="test",
                job_dir=Path(tmpdir),
                node=Node(id="n1", type=NodeType.INPUT),
            )
            result = _execute_input(ctx)
            assert result["status"] == "failed"


# ============================================================
# OUTPUT 执行器
# ============================================================

class TestOutputExecutor:

    def test_success(self):
        """final_output.mp4 存在时返回 success"""
        with tempfile.TemporaryDirectory() as tmpdir:
            job_dir = Path(tmpdir)
            (job_dir / "final_output.mp4").write_bytes(b"fake output")

            ctx = ExecutionContext(
                job_id="test",
                job_dir=job_dir,
                node=Node(id="n1", type=NodeType.OUTPUT),
            )
            result = _execute_output(ctx)
            assert result["status"] == "success"
            assert result["output_path"] is not None

    def test_missing_output(self):
        """final_output.mp4 不存在时返回 failed"""
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = ExecutionContext(
                job_id="test",
                job_dir=Path(tmpdir),
                node=Node(id="n1", type=NodeType.OUTPUT),
            )
            result = _execute_output(ctx)
            assert result["status"] == "failed"

    def test_output_in_videos_dir(self):
        """videos/final_output.mp4 也可以被找到"""
        with tempfile.TemporaryDirectory() as tmpdir:
            job_dir = Path(tmpdir)
            videos_dir = job_dir / "videos"
            videos_dir.mkdir()
            (videos_dir / "final_output.mp4").write_bytes(b"fake output")

            ctx = ExecutionContext(
                job_id="test",
                job_dir=job_dir,
                node=Node(id="n1", type=NodeType.OUTPUT),
            )
            result = _execute_output(ctx)
            assert result["status"] == "success"


# ============================================================
# ExecutionContext
# ============================================================

class TestExecutionContext:

    def test_defaults(self):
        ctx = ExecutionContext(
            job_id="job_123",
            job_dir=Path("/tmp/test"),
            node=Node(id="n1", type=NodeType.INPUT),
        )
        assert ctx.job_id == "job_123"
        assert ctx.user_goal == ""
        assert ctx.video_path is None

    def test_with_intent(self):
        ctx = ExecutionContext(
            job_id="job_123",
            job_dir=Path("/tmp/test"),
            node=Node(id="n1", type=NodeType.INTENT_INJECTION, config={"intent": "日系风格"}),
            user_goal="改成日系风格",
        )
        assert ctx.user_goal == "改成日系风格"
        assert ctx.node.config["intent"] == "日系风格"
