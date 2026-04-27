"use client"

// components/agent-canvas/WorkflowCanvas.tsx
// React Flow 画布 — 渲染 DAG 节点图 + 可展开的分析子节点

import { useMemo, useCallback } from "react"
import {
  ReactFlow,
  Background,
  Controls,
  type Node as RFNode,
  type Edge as RFEdge,
  type NodeTypes,
  Position,
  MarkerType,
} from "@xyflow/react"
import "@xyflow/react/dist/style.css"
import { useAgentStore, type GraphNode, type GraphEdge, type SubNodeData } from "@/stores/agentStore"
import { WorkflowNode } from "./WorkflowNode"
import { AnalysisSubNode } from "./AnalysisSubNode"

// ============================================================
// 节点类型注册
// ============================================================

const nodeTypes: NodeTypes = {
  workflow: WorkflowNode,
  analysisSubNode: AnalysisSubNode,
}

// ============================================================
// Film IR 子节点定义
// ============================================================

const FILM_IR_SUB_NODES = [
  { id: "sub_story_theme", label: "主题分析", icon: "story_theme" },
  { id: "sub_narrative", label: "脚本分析", icon: "narrative" },
  { id: "sub_shot_recipe", label: "分镜切割", icon: "shot_recipe" },
  { id: "sub_character_ledger", label: "角色发现", icon: "character_ledger" },
]

// 可展开的节点类型 → 子节点配置
const EXPANDABLE_NODES: Record<string, typeof FILM_IR_SUB_NODES> = {
  FILM_IR_ANALYSIS: FILM_IR_SUB_NODES,
}

// ============================================================
// 数据转换
// ============================================================

function toReactFlowNodes(
  nodes: GraphNode[],
  expandedNodes: Set<string>,
  subNodes: SubNodeData[],
  expandedSubNodes: Set<string>,
  jobId: string | null,
): RFNode[] {
  const rfNodes: RFNode[] = []

  for (const node of nodes) {
    const isExpandable = node.type in EXPANDABLE_NODES && node.status === "SUCCESS"
    const isExpanded = expandedNodes.has(node.id)

    rfNodes.push({
      id: node.id,
      type: "workflow",
      position: { x: node.position.x + 400, y: node.position.y + 40 },
      data: {
        label: node.label,
        nodeType: node.type,
        status: node.status,
        gate: node.gate,
        result: node.result,
        retryCount: node.retryCount,
        config: node.config,
        branch: node.branch,
        expandable: isExpandable,
        expanded: isExpanded,
      },
      sourcePosition: Position.Bottom,
      targetPosition: Position.Top,
    })

    // 展开时添加子节点
    if (isExpanded) {
      const subDefs = EXPANDABLE_NODES[node.type] || []
      const parentX = node.position.x + 400
      const parentY = node.position.y + 40

      subDefs.forEach((def, i) => {
        const subNode = subNodes.find((s) => s.id === def.id)
        const subStatus = subNode?.status || "pending"
        const subData = subNode?.data || null
        const isSubExpanded = expandedSubNodes.has(def.id)

        rfNodes.push({
          id: def.id,
          type: "analysisSubNode",
          position: {
            x: parentX + 260,
            y: parentY + i * (isSubExpanded ? 320 : 50) - 30,
          },
          data: {
            subNodeId: def.id,
            label: def.label,
            icon: def.icon,
            status: subStatus,
            analysisData: subData,
            isExpanded: isSubExpanded,
            jobId: jobId || "",
          },
          sourcePosition: Position.Bottom,
          targetPosition: Position.Top,
        })
      })
    }
  }

  return rfNodes
}

function toReactFlowEdges(
  edges: GraphEdge[],
  nodes: GraphNode[],
  expandedNodes: Set<string>,
): RFEdge[] {
  const nodeMap = new Map(nodes.map((n) => [n.id, n]))
  const rfEdges: RFEdge[] = []

  // 主 DAG 边
  for (const edge of edges) {
    const sourceNode = nodeMap.get(edge.source)
    const isActive = sourceNode?.status === "SUCCESS" || sourceNode?.status === "SKIPPED"

    rfEdges.push({
      id: edge.id,
      source: edge.source,
      target: edge.target,
      animated: sourceNode?.status === "RUNNING",
      style: {
        stroke: isActive ? "#22c55e" : "#4b5563",
        strokeWidth: isActive ? 2 : 1,
        opacity: isActive ? 1 : 0.5,
      },
      markerEnd: {
        type: MarkerType.ArrowClosed,
        color: isActive ? "#22c55e" : "#4b5563",
        width: 16,
        height: 16,
      },
    })
  }

  // 展开节点的子节点连线
  for (const node of nodes) {
    if (!expandedNodes.has(node.id)) continue
    const subDefs = EXPANDABLE_NODES[node.type] || []
    subDefs.forEach((def) => {
      rfEdges.push({
        id: `e_expand_${node.id}_${def.id}`,
        source: node.id,
        target: def.id,
        type: "smoothstep",
        style: { stroke: "#4b5563", strokeWidth: 1, strokeDasharray: "4 4" },
        markerEnd: {
          type: MarkerType.ArrowClosed,
          color: "#4b5563",
          width: 12,
          height: 12,
        },
      })
    })
  }

  return rfEdges
}

// ============================================================
// 组件
// ============================================================

export function WorkflowCanvas() {
  const {
    graph, jobId, setSelectedNode,
    expandedNodes, subNodes, expandedSubNodes,
    toggleNodeExpand, setSubNodes,
  } = useAgentStore()

  const handleNodeClick = useCallback(
    (_: React.MouseEvent, node: RFNode) => {
      // 检查是否是可展开的节点
      const graphNode = graph?.nodes.find((n) => n.id === node.id)
      if (graphNode && graphNode.type in EXPANDABLE_NODES && graphNode.status === "SUCCESS") {
        // 展开/收起
        toggleNodeExpand(node.id)

        // 首次展开时创建子节点数据
        if (!expandedNodes.has(node.id)) {
          const subDefs = EXPANDABLE_NODES[graphNode.type] || []
          // 从 result.substeps 获取状态
          const substeps = (graphNode.result?.substeps as Array<{ name: string; status: string }>) || []

          const newSubNodes: SubNodeData[] = subDefs.map((def, i) => ({
            id: def.id,
            parentNodeId: node.id,
            label: def.label,
            icon: def.icon,
            status: substeps[i]?.status || "success",
            data: null,
            expanded: false,
          }))
          setSubNodes([
            ...subNodes.filter((s) => s.parentNodeId !== node.id),
            ...newSubNodes,
          ])
        }
      } else {
        setSelectedNode(node.id)
      }
    },
    [graph, expandedNodes, subNodes, toggleNodeExpand, setSubNodes, setSelectedNode]
  )

  const onPaneClick = useCallback(() => {
    setSelectedNode(null)
  }, [setSelectedNode])

  const rfNodes = useMemo(
    () => graph ? toReactFlowNodes(graph.nodes, expandedNodes, subNodes, expandedSubNodes, jobId) : [],
    [graph, expandedNodes, subNodes, expandedSubNodes, jobId]
  )

  const rfEdges = useMemo(
    () => graph ? toReactFlowEdges(graph.edges, graph.nodes, expandedNodes) : [],
    [graph, expandedNodes]
  )

  if (!graph) {
    return (
      <div className="flex items-center justify-center h-full text-muted-foreground">
        等待 Agent 启动...
      </div>
    )
  }

  return (
    <div className="w-full h-full">
      <ReactFlow
        nodes={rfNodes}
        edges={rfEdges}
        nodeTypes={nodeTypes}
        onNodeClick={handleNodeClick}
        onPaneClick={onPaneClick}
        fitView
        fitViewOptions={{ padding: 0.3 }}
        minZoom={0.3}
        maxZoom={1.5}
        proOptions={{ hideAttribution: true }}
      >
        <Background color="#374151" gap={20} size={1} />
        <Controls
          showInteractive={false}
          className="!bg-gray-800 !border-gray-600 !shadow-lg"
        />
      </ReactFlow>
    </div>
  )
}
