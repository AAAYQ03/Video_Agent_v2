# core/graph_model.py
"""
DAG Workflow Graph Model
========================
Agent Workflow Canvas (Mode 2) 的核心数据模型。

定义 Node、Edge、WorkflowGraph 三层结构，提供：
- 拓扑排序（就绪节点计算）
- 环检测（Kahn 算法）
- DAG 合法性校验
- JSON 序列化 / 持久化
"""

import json
import shutil
import time
from enum import Enum
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional, Set, Any
from datetime import datetime, timezone


# ============================================================
# 枚举定义
# ============================================================

class NodeStatus(str, Enum):
    """节点执行状态"""
    PENDING = "PENDING"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    SKIPPED = "SKIPPED"


class NodeType(str, Enum):
    """节点类型 — 每种类型映射到一个后端执行函数"""

    # 一级节点（核心流程）
    INPUT = "INPUT"
    ANALYZE = "ANALYZE"
    FILM_IR_ANALYSIS = "FILM_IR_ANALYSIS"
    ABSTRACTION = "ABSTRACTION"
    INTENT_INJECTION = "INTENT_INJECTION"
    ASSET_GENERATION = "ASSET_GENERATION"
    STORYBOARD = "STORYBOARD"
    VIDEO_GENERATION = "VIDEO_GENERATION"
    MERGE = "MERGE"
    OUTPUT = "OUTPUT"

    # 二级节点（细粒度控制）
    CHARACTER_LEDGER = "CHARACTER_LEDGER"
    WATERMARK_CLEAN = "WATERMARK_CLEAN"
    SINGLE_SHOT_STYLIZE = "SINGLE_SHOT_STYLIZE"
    SINGLE_SHOT_VIDEO = "SINGLE_SHOT_VIDEO"
    QUALITY_CHECK = "QUALITY_CHECK"
    BRANCH_MERGE = "BRANCH_MERGE"

    # 扩展节点（用户可拖入）
    CUSTOM_PROMPT = "CUSTOM_PROMPT"
    STYLE_OVERRIDE = "STYLE_OVERRIDE"


# 不可删除的节点类型
UNDELETABLE_TYPES: Set[NodeType] = {NodeType.INPUT, NodeType.OUTPUT, NodeType.ANALYZE}

# 默认 Gate 节点类型
DEFAULT_GATE_TYPES: Set[NodeType] = {
    NodeType.INTENT_INJECTION,   # 确认 remix 脚本
    NodeType.ASSET_GENERATION,   # 确认角色/环境形象（+上传参考图）
    NodeType.STORYBOARD,         # 确认分镜画面
}

# 支持自评估的节点类型
EVALUATABLE_TYPES: Set[NodeType] = {
    NodeType.STORYBOARD,
    NodeType.SINGLE_SHOT_STYLIZE,
    NodeType.VIDEO_GENERATION,
    NodeType.SINGLE_SHOT_VIDEO,
}

# 节点类型的合法前置依赖（用于校验连线合法性）
# key: 节点类型, value: 必须在它的祖先中出现的节点类型集合
#
# 依赖说明（与 Mode 1 完全一致）：
#   WATERMARK_CLEAN:  需要 ANALYZE 提取的原始帧
#   FILM_IR_ANALYSIS: 需要 ANALYZE 的视频和基础分镜数据
#   ASSET_GENERATION: 需要 identity anchors(INTENT_INJECTION) + character ledger(FILM_IR_ANALYSIS)
#   STORYBOARD:       需要 remix prompts(INTENT_INJECTION) + 清洗后的帧(WATERMARK_CLEAN)
#
# Mode 1 的并行关系：
#   ANALYZE 完成后，WATERMARK_CLEAN 和 FILM_IR_ANALYSIS 并行执行
#   STORYBOARD 需要等两条路径都完成
REQUIRED_PREDECESSORS: Dict[NodeType, Set[NodeType]] = {
    NodeType.WATERMARK_CLEAN: {NodeType.ANALYZE},
    NodeType.FILM_IR_ANALYSIS: {NodeType.ANALYZE},
    NodeType.ABSTRACTION: {NodeType.FILM_IR_ANALYSIS},
    NodeType.INTENT_INJECTION: {NodeType.ABSTRACTION},
    NodeType.ASSET_GENERATION: {NodeType.INTENT_INJECTION, NodeType.ANALYZE, NodeType.FILM_IR_ANALYSIS},
    NodeType.STORYBOARD: {NodeType.INTENT_INJECTION, NodeType.WATERMARK_CLEAN},
    NodeType.VIDEO_GENERATION: {NodeType.STORYBOARD},
    NodeType.MERGE: {NodeType.VIDEO_GENERATION},
    NodeType.OUTPUT: {NodeType.MERGE},
}

# 节点类型的默认显示名称
NODE_LABELS: Dict[NodeType, str] = {
    NodeType.INPUT: "上传视频",
    NodeType.ANALYZE: "AI 分析视频",
    NodeType.FILM_IR_ANALYSIS: "Film IR 深度分析",
    NodeType.ABSTRACTION: "逻辑抽象",
    NodeType.INTENT_INJECTION: "意图注入",
    NodeType.ASSET_GENERATION: "资产生成",
    NodeType.STORYBOARD: "生成分镜",
    NodeType.VIDEO_GENERATION: "生成视频",
    NodeType.MERGE: "合并输出",
    NodeType.OUTPUT: "完成",
    NodeType.CHARACTER_LEDGER: "角色发现",
    NodeType.WATERMARK_CLEAN: "水印清理",
    NodeType.SINGLE_SHOT_STYLIZE: "单镜头定妆",
    NodeType.SINGLE_SHOT_VIDEO: "单镜头视频",
    NodeType.QUALITY_CHECK: "质量检查",
    NodeType.BRANCH_MERGE: "分支合并",
    NodeType.CUSTOM_PROMPT: "自定义 Prompt",
    NodeType.STYLE_OVERRIDE: "风格覆盖",
}


# ============================================================
# 数据类
# ============================================================

@dataclass
class Node:
    """DAG 中的一个节点"""
    id: str
    type: NodeType
    label: str = ""
    config: Dict[str, Any] = field(default_factory=dict)
    gate: bool = False
    status: NodeStatus = NodeStatus.PENDING
    result: Dict[str, Any] = field(default_factory=dict)
    position: Dict[str, float] = field(default_factory=lambda: {"x": 0.0, "y": 0.0})
    branch: str = "main"
    retry_count: int = 0
    max_retries: int = 2
    started_at: Optional[str] = None
    completed_at: Optional[str] = None

    def __post_init__(self):
        if isinstance(self.type, str):
            self.type = NodeType(self.type)
        if isinstance(self.status, str):
            self.status = NodeStatus(self.status)
        if not self.label:
            self.label = NODE_LABELS.get(self.type, self.type.value)

    def mark_running(self):
        self.status = NodeStatus.RUNNING
        self.started_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    def mark_success(self, result: Dict[str, Any] = None):
        self.status = NodeStatus.SUCCESS
        self.completed_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        if result:
            self.result = result

    def mark_failed(self, error: str):
        self.status = NodeStatus.FAILED
        self.completed_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        self.result = {"error": error}

    def reset_for_retry(self):
        self.retry_count += 1
        self.status = NodeStatus.PENDING
        self.started_at = None
        self.completed_at = None
        self.result = {}

    def can_retry(self) -> bool:
        return self.retry_count < self.max_retries

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type.value,
            "label": self.label,
            "config": self.config,
            "gate": self.gate,
            "status": self.status.value,
            "result": self.result,
            "position": self.position,
            "branch": self.branch,
            "retryCount": self.retry_count,
            "maxRetries": self.max_retries,
            "startedAt": self.started_at,
            "completedAt": self.completed_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Node":
        return cls(
            id=data["id"],
            type=data["type"],
            label=data.get("label", ""),
            config=data.get("config", {}),
            gate=data.get("gate", False),
            status=data.get("status", "PENDING"),
            result=data.get("result", {}),
            position=data.get("position", {"x": 0.0, "y": 0.0}),
            branch=data.get("branch", "main"),
            retry_count=data.get("retryCount", 0),
            max_retries=data.get("maxRetries", 2),
            started_at=data.get("startedAt"),
            completed_at=data.get("completedAt"),
        )


@dataclass
class Edge:
    """DAG 中的一条边（连线）"""
    id: str
    source: str  # 源节点 ID
    target: str  # 目标节点 ID
    condition: Optional[str] = None  # 条件表达式（可选，用于条件分支）

    def to_dict(self) -> Dict[str, Any]:
        d = {"id": self.id, "source": self.source, "target": self.target}
        if self.condition:
            d["condition"] = self.condition
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Edge":
        return cls(
            id=data["id"],
            source=data["source"],
            target=data["target"],
            condition=data.get("condition"),
        )


# ============================================================
# WorkflowGraph — 核心 DAG 容器
# ============================================================

class WorkflowGraph:
    """
    DAG 工作流图

    管理节点、边、拓扑排序、环检测、合法性校验、持久化。
    """

    def __init__(
        self,
        nodes: List[Node] = None,
        edges: List[Edge] = None,
        user_goal: str = "",
        status: str = "PENDING",
        gate_defaults: List[str] = None,
    ):
        self.nodes: List[Node] = nodes or []
        self.edges: List[Edge] = edges or []
        self.user_goal: str = user_goal
        self.status: str = status  # PENDING | RUNNING | COMPLETED | FAILED | PAUSED
        self.gate_defaults: List[str] = gate_defaults or [t.value for t in DEFAULT_GATE_TYPES]
        self.created_at: str = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        self.version: int = 1

        # 内部索引（调用 _rebuild_index 构建）
        self._node_map: Dict[str, Node] = {}
        self._children: Dict[str, List[str]] = {}  # node_id → [child_ids]
        self._parents: Dict[str, List[str]] = {}   # node_id → [parent_ids]
        self._rebuild_index()

    # ============================================================
    # 索引管理
    # ============================================================

    def _rebuild_index(self):
        """根据当前 nodes 和 edges 重建内部索引"""
        self._node_map = {n.id: n for n in self.nodes}
        self._children = {n.id: [] for n in self.nodes}
        self._parents = {n.id: [] for n in self.nodes}
        for e in self.edges:
            if e.source in self._children:
                self._children[e.source].append(e.target)
            if e.target in self._parents:
                self._parents[e.target].append(e.source)

    # ============================================================
    # 节点查询
    # ============================================================

    def get_node(self, node_id: str) -> Optional[Node]:
        return self._node_map.get(node_id)

    def get_nodes_by_type(self, node_type: NodeType) -> List[Node]:
        return [n for n in self.nodes if n.type == node_type]

    def get_nodes_by_status(self, status: NodeStatus) -> List[Node]:
        return [n for n in self.nodes if n.status == status]

    def get_nodes_by_branch(self, branch: str) -> List[Node]:
        return [n for n in self.nodes if n.branch == branch]

    def get_children(self, node_id: str) -> List[Node]:
        child_ids = self._children.get(node_id, [])
        return [self._node_map[cid] for cid in child_ids if cid in self._node_map]

    def get_parents(self, node_id: str) -> List[Node]:
        parent_ids = self._parents.get(node_id, [])
        return [self._node_map[pid] for pid in parent_ids if pid in self._node_map]

    # ============================================================
    # 拓扑排序 & 就绪节点
    # ============================================================

    def get_ready_nodes(self) -> List[Node]:
        """
        返回所有"就绪"的节点：
        - 自身状态为 PENDING
        - 所有父节点状态为 SUCCESS 或 SKIPPED
        """
        ready = []
        for node in self.nodes:
            if node.status != NodeStatus.PENDING:
                continue
            parents = self.get_parents(node.id)
            if not parents:
                # 无前置依赖（如 INPUT 节点）
                ready.append(node)
            elif all(p.status in (NodeStatus.SUCCESS, NodeStatus.SKIPPED) for p in parents):
                ready.append(node)
        return ready

    def topological_sort(self) -> List[Node]:
        """
        Kahn 算法拓扑排序

        Returns:
            排序后的节点列表

        Raises:
            ValueError: 如果图中有环
        """
        in_degree = {n.id: 0 for n in self.nodes}
        for e in self.edges:
            if e.target in in_degree:
                in_degree[e.target] += 1

        queue = [nid for nid, deg in in_degree.items() if deg == 0]
        result = []

        while queue:
            nid = queue.pop(0)
            node = self._node_map.get(nid)
            if node:
                result.append(node)
            for child_id in self._children.get(nid, []):
                in_degree[child_id] -= 1
                if in_degree[child_id] == 0:
                    queue.append(child_id)

        if len(result) != len(self.nodes):
            raise ValueError("DAG contains a cycle — topological sort failed")

        return result

    # ============================================================
    # 状态查询
    # ============================================================

    def is_complete(self) -> bool:
        """所有节点都处于终态（SUCCESS / FAILED / SKIPPED）"""
        terminal = {NodeStatus.SUCCESS, NodeStatus.FAILED, NodeStatus.SKIPPED}
        return all(n.status in terminal for n in self.nodes)

    def has_failures(self) -> bool:
        return any(n.status == NodeStatus.FAILED for n in self.nodes)

    def has_waiting_gates(self) -> bool:
        return any(n.status == NodeStatus.WAITING_APPROVAL for n in self.nodes)

    def is_blocked(self) -> bool:
        """
        无法继续推进：
        - 没有就绪节点
        - 有 Gate 等待 或 有失败节点
        """
        if self.is_complete():
            return False
        ready = self.get_ready_nodes()
        return len(ready) == 0

    def get_progress(self) -> Dict[str, int]:
        """返回执行进度统计"""
        total = len(self.nodes)
        done = sum(1 for n in self.nodes if n.status in (NodeStatus.SUCCESS, NodeStatus.SKIPPED))
        failed = sum(1 for n in self.nodes if n.status == NodeStatus.FAILED)
        running = sum(1 for n in self.nodes if n.status == NodeStatus.RUNNING)
        return {"total": total, "done": done, "failed": failed, "running": running}

    # ============================================================
    # 校验
    # ============================================================

    def has_cycle(self) -> bool:
        """检测图中是否存在环"""
        try:
            self.topological_sort()
            return False
        except ValueError:
            return True

    def validate(self) -> List[str]:
        """
        全面校验 DAG 合法性

        Returns:
            错误信息列表，空列表表示合法
        """
        errors = []

        # 1. 环检测
        if self.has_cycle():
            errors.append("DAG contains a cycle")

        # 2. 必须有 INPUT 和 OUTPUT
        input_nodes = self.get_nodes_by_type(NodeType.INPUT)
        output_nodes = self.get_nodes_by_type(NodeType.OUTPUT)
        if not input_nodes:
            errors.append("Missing INPUT node")
        if not output_nodes:
            errors.append("Missing OUTPUT node")

        # 3. 连通性：所有节点都能从某个 INPUT 到达
        if input_nodes and not errors:
            reachable = self._bfs_reachable(input_nodes[0].id)
            unreachable = [n for n in self.nodes if n.id not in reachable]
            if unreachable:
                names = [f"{n.id}({n.label})" for n in unreachable]
                errors.append(f"Unreachable nodes: {', '.join(names)}")

        # 4. 依赖完整性
        for node in self.nodes:
            required = REQUIRED_PREDECESSORS.get(node.type, set())
            if not required:
                continue
            ancestor_types = self._get_ancestor_types(node.id)
            missing = required - ancestor_types
            if missing:
                missing_names = [t.value for t in missing]
                errors.append(
                    f"Node {node.id}({node.label}) missing required predecessor(s): "
                    f"{', '.join(missing_names)}"
                )

        # 5. Edge 引用的节点必须存在
        node_ids = {n.id for n in self.nodes}
        for e in self.edges:
            if e.source not in node_ids:
                errors.append(f"Edge {e.id} references non-existent source node: {e.source}")
            if e.target not in node_ids:
                errors.append(f"Edge {e.id} references non-existent target node: {e.target}")

        return errors

    def _bfs_reachable(self, start_id: str) -> Set[str]:
        """BFS 返回从 start_id 可达的所有节点 ID"""
        visited = set()
        queue = [start_id]
        while queue:
            nid = queue.pop(0)
            if nid in visited:
                continue
            visited.add(nid)
            for child_id in self._children.get(nid, []):
                if child_id not in visited:
                    queue.append(child_id)
        return visited

    def _get_ancestor_types(self, node_id: str) -> Set[NodeType]:
        """反向 BFS 获取某节点所有祖先的类型集合"""
        visited = set()
        queue = list(self._parents.get(node_id, []))
        types = set()
        while queue:
            nid = queue.pop(0)
            if nid in visited:
                continue
            visited.add(nid)
            node = self._node_map.get(nid)
            if node:
                types.add(node.type)
            for parent_id in self._parents.get(nid, []):
                if parent_id not in visited:
                    queue.append(parent_id)
        return types

    # ============================================================
    # 图编辑
    # ============================================================

    def add_node(self, node: Node) -> List[str]:
        """
        添加节点到图中

        Returns:
            校验错误列表（空列表表示成功）
        """
        if node.id in self._node_map:
            return [f"Node {node.id} already exists"]
        self.nodes.append(node)
        self._rebuild_index()
        return []

    def remove_node(self, node_id: str) -> List[str]:
        """
        删除节点及其关联的边

        Returns:
            校验错误列表
        """
        node = self._node_map.get(node_id)
        if not node:
            return [f"Node {node_id} not found"]
        if node.type in UNDELETABLE_TYPES:
            return [f"Cannot delete {node.type.value} node"]
        if node.status == NodeStatus.RUNNING:
            return [f"Cannot delete running node {node_id}"]

        # 自动重连：如果节点有且仅有 1 个父和 1 个子，把它们直连
        parents = self._parents.get(node_id, [])
        children = self._children.get(node_id, [])
        if len(parents) == 1 and len(children) == 1:
            edge_id = f"e_auto_{parents[0]}_{children[0]}"
            self.edges.append(Edge(id=edge_id, source=parents[0], target=children[0]))

        # 删除关联的边
        self.edges = [e for e in self.edges if e.source != node_id and e.target != node_id]
        # 删除节点
        self.nodes = [n for n in self.nodes if n.id != node_id]
        self._rebuild_index()
        return []

    def add_edge(self, edge: Edge) -> List[str]:
        """
        添加边，添加前检查是否会形成环

        Returns:
            校验错误列表
        """
        # 检查节点是否存在
        if edge.source not in self._node_map:
            return [f"Source node {edge.source} not found"]
        if edge.target not in self._node_map:
            return [f"Target node {edge.target} not found"]

        # 检查是否重复
        for e in self.edges:
            if e.source == edge.source and e.target == edge.target:
                return [f"Edge from {edge.source} to {edge.target} already exists"]

        # 临时添加，检查是否形成环
        self.edges.append(edge)
        self._rebuild_index()
        if self.has_cycle():
            self.edges.pop()
            self._rebuild_index()
            return [f"Adding edge {edge.source} → {edge.target} would create a cycle"]

        return []

    def remove_edge(self, edge_id: str) -> List[str]:
        """删除边"""
        original_len = len(self.edges)
        self.edges = [e for e in self.edges if e.id != edge_id]
        if len(self.edges) == original_len:
            return [f"Edge {edge_id} not found"]
        self._rebuild_index()
        return []

    def cascade_invalidate(self, node_id: str):
        """
        级联失效：将某节点及其所有下游节点重置为 PENDING

        用于节点配置修改后触发重新执行。
        """
        to_reset = set()
        queue = [node_id]
        while queue:
            nid = queue.pop(0)
            if nid in to_reset:
                continue
            to_reset.add(nid)
            for child_id in self._children.get(nid, []):
                queue.append(child_id)

        for nid in to_reset:
            node = self._node_map.get(nid)
            if node and node.status in (NodeStatus.SUCCESS, NodeStatus.FAILED):
                node.status = NodeStatus.PENDING
                node.result = {}
                node.started_at = None
                node.completed_at = None
                node.retry_count = 0

    # ============================================================
    # 序列化 / 持久化
    # ============================================================

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "createdAt": self.created_at,
            "userGoal": self.user_goal,
            "status": self.status,
            "gateDefaults": self.gate_defaults,
            "nodes": [n.to_dict() for n in self.nodes],
            "edges": [e.to_dict() for e in self.edges],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WorkflowGraph":
        nodes = [Node.from_dict(nd) for nd in data.get("nodes", [])]
        edges = [Edge.from_dict(ed) for ed in data.get("edges", [])]
        graph = cls(
            nodes=nodes,
            edges=edges,
            user_goal=data.get("userGoal", ""),
            status=data.get("status", "PENDING"),
            gate_defaults=data.get("gateDefaults"),
        )
        graph.created_at = data.get("createdAt", graph.created_at)
        graph.version = data.get("version", 1)
        return graph

    def save(self, job_dir: Path):
        """原子写入 agent_graph.json"""
        path = job_dir / "agent_graph.json"
        content = json.dumps(self.to_dict(), ensure_ascii=False, indent=2)
        temp_path = path.with_suffix(".json.tmp")
        try:
            temp_path.write_text(content, encoding="utf-8")
            shutil.move(str(temp_path), str(path))
        except Exception:
            if temp_path.exists():
                temp_path.unlink()
            path.write_text(content, encoding="utf-8")

    @classmethod
    def load(cls, job_dir: Path) -> Optional["WorkflowGraph"]:
        """从 agent_graph.json 加载"""
        path = job_dir / "agent_graph.json"
        if not path.exists():
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return cls.from_dict(data)
        except (json.JSONDecodeError, KeyError) as e:
            print(f"⚠️ Failed to load agent_graph.json: {e}")
            return None

    # ============================================================
    # 工厂方法
    # ============================================================

    @classmethod
    def create_default(cls, user_goal: str, intent_config: Dict[str, Any] = None) -> "WorkflowGraph":
        """
        创建与 Mode 1 一致的默认 DAG

        结构（水印清理与 Film IR 分析并行）：

                          ┌→ WATERMARK_CLEAN ──────────────────────────────┐
        INPUT → ANALYZE ──┤                                                ├→ STORYBOARD → VIDEO_GEN → MERGE → OUTPUT
                          └→ FILM_IR → ABSTRACTION → INTENT → ASSET_GEN ──┘
                                                        ↑ Gate    ↑ Gate       ↑ Gate

        Args:
            user_goal: 用户目标
            intent_config: 意图注入节点的配置（如 {"intent": "改成日系风格"}）
        """
        y = 120  # y 间距

        def _node(id: str, ntype: NodeType, x: float, y_pos: float, config=None):
            return Node(
                id=id, type=ntype,
                config=config or {},
                gate=ntype in DEFAULT_GATE_TYPES,
                position={"x": x, "y": y_pos},
            )

        nodes = [
            _node("node_input",         NodeType.INPUT,             0,     0),
            _node("node_analyze",       NodeType.ANALYZE,           0,     y),
            # 并行路径 A: 水印清理
            _node("node_watermark",     NodeType.WATERMARK_CLEAN,  -200,   y * 2),
            # 并行路径 B: Film IR 深度分析链
            _node("node_film_ir",       NodeType.FILM_IR_ANALYSIS,  200,   y * 2),
            _node("node_abstraction",   NodeType.ABSTRACTION,       200,   y * 3),
            _node("node_intent",        NodeType.INTENT_INJECTION,  200,   y * 4,
                  config=intent_config or {}),
            _node("node_assets",        NodeType.ASSET_GENERATION,  200,   y * 5),
            # 汇合点：两条路径合流
            _node("node_storyboard",    NodeType.STORYBOARD,        0,     y * 6),
            _node("node_video",         NodeType.VIDEO_GENERATION,  0,     y * 7),
            _node("node_merge",         NodeType.MERGE,             0,     y * 8),
            _node("node_output",        NodeType.OUTPUT,            0,     y * 9),
        ]

        edges = [
            # 主干
            Edge(id="e_input_analyze",       source="node_input",       target="node_analyze"),
            # 分叉：ANALYZE 后并行两条路径
            Edge(id="e_analyze_watermark",   source="node_analyze",     target="node_watermark"),
            Edge(id="e_analyze_film_ir",     source="node_analyze",     target="node_film_ir"),
            # 路径 B: Film IR 链
            Edge(id="e_film_ir_abstract",    source="node_film_ir",     target="node_abstraction"),
            Edge(id="e_abstract_intent",     source="node_abstraction", target="node_intent"),
            Edge(id="e_intent_assets",       source="node_intent",      target="node_assets"),
            # 汇合：两条路径都连到 STORYBOARD
            Edge(id="e_watermark_storyboard", source="node_watermark",  target="node_storyboard"),
            Edge(id="e_assets_storyboard",   source="node_assets",      target="node_storyboard"),
            # 后续线性
            Edge(id="e_storyboard_video",    source="node_storyboard",  target="node_video"),
            Edge(id="e_video_merge",         source="node_video",       target="node_merge"),
            Edge(id="e_merge_output",        source="node_merge",       target="node_output"),
        ]

        return cls(
            nodes=nodes,
            edges=edges,
            user_goal=user_goal,
        )
