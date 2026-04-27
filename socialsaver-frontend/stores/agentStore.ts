// stores/agentStore.ts
// Agent Canvas 状态管理 (Zustand)

import { create } from "zustand"

// ============================================================
// 类型定义
// ============================================================

export type NodeStatus =
  | "PENDING"
  | "QUEUED"
  | "RUNNING"
  | "SUCCESS"
  | "FAILED"
  | "WAITING_APPROVAL"
  | "SKIPPED"

export interface GraphNode {
  id: string
  type: string
  label: string
  config: Record<string, unknown>
  gate: boolean
  status: NodeStatus
  result: Record<string, unknown>
  position: { x: number; y: number }
  branch: string
  retryCount: number
  maxRetries: number
  startedAt: string | null
  completedAt: string | null
}

export interface GraphEdge {
  id: string
  source: string
  target: string
  condition?: string
}

export interface AgentGraph {
  version: number
  createdAt: string
  userGoal: string
  status: string
  gateDefaults: string[]
  nodes: GraphNode[]
  edges: GraphEdge[]
}

export interface AgentEvent {
  ts: string
  event: string
  data: Record<string, unknown>
}

// ============================================================
// Store
// ============================================================

// 子节点展开数据（从 API 拉取的分析结果）
export interface SubNodeData {
  id: string
  parentNodeId: string
  label: string
  icon: string  // "story_theme" | "narrative" | "shot_recipe" | "character_ledger"
  status: string
  data: Record<string, unknown> | null  // API 返回的分析数据
  expanded: boolean  // 是否展开显示详细内容
}

interface AgentStore {
  // 状态
  jobId: string | null
  graph: AgentGraph | null
  events: AgentEvent[]
  chatMessages: ChatMessage[]
  selectedNodeId: string | null
  isConnected: boolean
  agentStatus: "not_started" | "running" | "completed" | "failed" | "paused" | "stopped"
  expandedNodes: Set<string>  // 哪些节点处于展开状态（显示子节点）
  subNodes: SubNodeData[]     // 展开后的子节点列表
  expandedSubNodes: Set<string>  // 哪些子节点展开了详细内容

  // Actions
  setJobId: (jobId: string) => void
  setGraph: (graph: AgentGraph) => void
  updateNodeStatus: (nodeId: string, status: NodeStatus, result?: Record<string, unknown>) => void
  addEvent: (event: AgentEvent) => void
  addChatMessage: (message: ChatMessage) => void
  setSelectedNode: (nodeId: string | null) => void
  setConnected: (connected: boolean) => void
  setAgentStatus: (status: AgentStore["agentStatus"]) => void
  handleSSEEvent: (event: AgentEvent) => void
  toggleNodeExpand: (nodeId: string) => void
  toggleSubNodeExpand: (subNodeId: string) => void
  setSubNodes: (subNodes: SubNodeData[]) => void
  updateSubNodeData: (subNodeId: string, data: Record<string, unknown>) => void
  reset: () => void
}

export interface ChatMessage {
  id: string
  role: "agent" | "user"
  content: string
  timestamp: string
}

export const useAgentStore = create<AgentStore>((set, get) => ({
  // 初始状态
  jobId: null,
  graph: null,
  events: [],
  chatMessages: [],
  selectedNodeId: null,
  isConnected: false,
  agentStatus: "not_started",
  expandedNodes: new Set(),
  subNodes: [],
  expandedSubNodes: new Set(),

  // Actions
  setJobId: (jobId) => set({ jobId }),

  setGraph: (graph) => set({ graph }),

  updateNodeStatus: (nodeId, status, result) =>
    set((state) => {
      if (!state.graph) return state
      const nodes = state.graph.nodes.map((n) =>
        n.id === nodeId ? { ...n, status, ...(result ? { result } : {}) } : n
      )
      return { graph: { ...state.graph, nodes } }
    }),

  addEvent: (event) =>
    set((state) => ({ events: [...state.events, event] })),

  addChatMessage: (message) =>
    set((state) => ({ chatMessages: [...state.chatMessages, message] })),

  setSelectedNode: (nodeId) => set({ selectedNodeId: nodeId }),

  setConnected: (connected) => set({ isConnected: connected }),

  setAgentStatus: (status) => set({ agentStatus: status }),

  toggleNodeExpand: (nodeId) =>
    set((state) => {
      const next = new Set(state.expandedNodes)
      if (next.has(nodeId)) {
        next.delete(nodeId)
        // 收起时清除该节点的子节点
        return {
          expandedNodes: next,
          subNodes: state.subNodes.filter((s) => s.parentNodeId !== nodeId),
        }
      } else {
        next.add(nodeId)
        return { expandedNodes: next }
      }
    }),

  toggleSubNodeExpand: (subNodeId) =>
    set((state) => {
      const next = new Set(state.expandedSubNodes)
      if (next.has(subNodeId)) {
        next.delete(subNodeId)
      } else {
        next.add(subNodeId)
      }
      return { expandedSubNodes: next }
    }),

  setSubNodes: (subNodes) => set({ subNodes }),

  updateSubNodeData: (subNodeId, data) =>
    set((state) => ({
      subNodes: state.subNodes.map((s) =>
        s.id === subNodeId ? { ...s, data, expanded: true } : s
      ),
    })),

  handleSSEEvent: (event) => {
    const { addEvent, updateNodeStatus, setGraph, addChatMessage, setAgentStatus } = get()
    addEvent(event)

    switch (event.event) {
      case "graph_created":
      case "graph_resumed":
        // 收到完整 graph 后需要通过 API 获取
        setAgentStatus("running")
        break

      case "node_started":
        updateNodeStatus(event.data.nodeId as string, "RUNNING")
        addChatMessage({
          id: `msg_${Date.now()}`,
          role: "agent",
          content: `正在执行: ${event.data.label}`,
          timestamp: event.ts,
        })
        break

      case "node_progress":
        // 子步骤进度更新（不改变节点状态，更新 result 中的 substeps）
        updateNodeStatus(
          event.data.nodeId as string,
          "RUNNING",
          { substeps: event.data.substeps }
        )
        if (event.data.substepStatus === "running") {
          addChatMessage({
            id: `msg_${Date.now()}`,
            role: "agent",
            content: `  ↳ ${event.data.substep}...`,
            timestamp: event.ts,
          })
        }
        break

      case "node_completed":
        updateNodeStatus(
          event.data.nodeId as string,
          "SUCCESS",
          event.data.result as Record<string, unknown>
        )
        addChatMessage({
          id: `msg_${Date.now()}`,
          role: "agent",
          content: `${event.data.label} 完成 (${((event.data.duration_ms as number) / 1000).toFixed(1)}s)`,
          timestamp: event.ts,
        })
        break

      case "node_failed":
        updateNodeStatus(event.data.nodeId as string, "FAILED", {
          error: event.data.error,
        })
        addChatMessage({
          id: `msg_${Date.now()}`,
          role: "agent",
          content: `${event.data.label} 失败: ${event.data.error}`,
          timestamp: event.ts,
        })
        break

      case "node_retrying":
        updateNodeStatus(event.data.nodeId as string, "RUNNING")
        addChatMessage({
          id: `msg_${Date.now()}`,
          role: "agent",
          content: `${event.data.nodeType} 重试中 (${event.data.attempt}/${event.data.maxRetries})`,
          timestamp: event.ts,
        })
        break

      case "gate_reached":
        updateNodeStatus(event.data.nodeId as string, "WAITING_APPROVAL")
        addChatMessage({
          id: `msg_${Date.now()}`,
          role: "agent",
          content: `等待确认: ${event.data.label}`,
          timestamp: event.ts,
        })
        break

      case "workflow_complete":
        setAgentStatus("completed")
        addChatMessage({
          id: `msg_${Date.now()}`,
          role: "agent",
          content: `工作流完成! 状态: ${event.data.status}`,
          timestamp: event.ts,
        })
        break

      case "workflow_blocked":
        setAgentStatus("failed")
        addChatMessage({
          id: `msg_${Date.now()}`,
          role: "agent",
          content: `工作流被阻塞，请检查失败节点`,
          timestamp: event.ts,
        })
        break

      case "workflow_paused":
        setAgentStatus("paused")
        break

      case "workflow_resumed":
        setAgentStatus("running")
        break

      case "workflow_stopped":
        setAgentStatus("stopped")
        break

      // Phase 1.5
      case "planner_succeeded":
        addChatMessage({
          id: `msg_${Date.now()}`,
          role: "agent",
          content: "✓ LLM 规划器已生成最小 DAG",
          timestamp: event.ts,
        })
        break
      case "planner_failed":
        addChatMessage({
          id: `msg_${Date.now()}`,
          role: "agent",
          content: `⚠ 规划失败回退到默认模板: ${event.data.error || ""}`,
          timestamp: event.ts,
        })
        break

      // Phase 2.3
      case "branch_created":
        addChatMessage({
          id: `msg_${Date.now()}`,
          role: "agent",
          content: `🌿 分支 "${event.data.branchName}" 已创建（${event.data.newNodeCount} 个节点）`,
          timestamp: event.ts,
        })
        break
    }
  },

  reset: () =>
    set({
      graph: null,
      events: [],
      chatMessages: [],
      selectedNodeId: null,
      isConnected: false,
      agentStatus: "not_started",
      expandedNodes: new Set(),
      subNodes: [],
      expandedSubNodes: new Set(),
    }),
}))
