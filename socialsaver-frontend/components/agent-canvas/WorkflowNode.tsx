"use client"

// components/agent-canvas/WorkflowNode.tsx
// 自定义节点组件 — 显示节点状态、图标、进度

import { memo } from "react"
import { Handle, Position, type NodeProps } from "@xyflow/react"
import type { NodeStatus } from "@/stores/agentStore"
import {
  Upload, Search, Droplets, Film, Layers, Wand2,
  Image, Clapperboard, Video, Merge, CheckCircle2,
  Loader2, AlertCircle, Lock, SkipForward,
  ChevronDown, ChevronRight,
} from "lucide-react"

// ============================================================
// 节点类型 → 图标映射
// ============================================================

const NODE_ICONS: Record<string, React.ElementType> = {
  INPUT: Upload,
  ANALYZE: Search,
  WATERMARK_CLEAN: Droplets,
  FILM_IR_ANALYSIS: Film,
  ABSTRACTION: Layers,
  INTENT_INJECTION: Wand2,
  ASSET_GENERATION: Image,
  STORYBOARD: Clapperboard,
  VIDEO_GENERATION: Video,
  MERGE: Merge,
  OUTPUT: CheckCircle2,
}

// ============================================================
// 状态 → 样式
// ============================================================

const STATUS_STYLES: Record<NodeStatus, {
  bg: string
  border: string
  text: string
  icon: React.ElementType | null
  animate?: string
}> = {
  PENDING: {
    bg: "bg-gray-800",
    border: "border-gray-600",
    text: "text-gray-400",
    icon: null,
  },
  QUEUED: {
    bg: "bg-gray-800",
    border: "border-gray-500",
    text: "text-gray-300",
    icon: null,
  },
  RUNNING: {
    bg: "bg-blue-950",
    border: "border-blue-500",
    text: "text-blue-300",
    icon: Loader2,
    animate: "animate-spin",
  },
  SUCCESS: {
    bg: "bg-green-950",
    border: "border-green-500",
    text: "text-green-300",
    icon: CheckCircle2,
  },
  FAILED: {
    bg: "bg-red-950",
    border: "border-red-500",
    text: "text-red-300",
    icon: AlertCircle,
  },
  WAITING_APPROVAL: {
    bg: "bg-amber-950",
    border: "border-amber-500",
    text: "text-amber-300",
    icon: Lock,
  },
  SKIPPED: {
    bg: "bg-gray-800",
    border: "border-gray-500",
    text: "text-gray-400",
    icon: SkipForward,
  },
}

// ============================================================
// 组件
// ============================================================

interface WorkflowNodeData {
  label: string
  nodeType: string
  status: NodeStatus
  gate: boolean
  result: Record<string, unknown>
  retryCount: number
  config: Record<string, unknown>
  expandable?: boolean
  expanded?: boolean
}

function WorkflowNodeInner({ data }: NodeProps) {
  const nodeData = data as unknown as WorkflowNodeData
  const { label, nodeType, status, gate, result, retryCount, expandable, expanded } = nodeData

  const style = STATUS_STYLES[status] || STATUS_STYLES.PENDING
  const NodeIcon = NODE_ICONS[nodeType] || CheckCircle2
  const StatusIcon = style.icon

  // 耗时显示
  const durationMs = result?.duration_ms as number | undefined
  const durationText = durationMs
    ? durationMs > 1000
      ? `${(durationMs / 1000).toFixed(1)}s`
      : `${durationMs}ms`
    : null

  return (
    <div
      className={`
        px-4 py-3 rounded-lg border-2 min-w-[180px] max-w-[220px]
        shadow-lg cursor-pointer transition-all hover:shadow-xl
        ${style.bg} ${style.border}
      `}
    >
      {/* 输入端口 */}
      <Handle
        type="target"
        position={Position.Top}
        className="!w-2.5 !h-2.5 !bg-gray-500 !border-gray-400"
      />

      {/* 节点内容 */}
      <div className="flex items-center gap-2.5">
        <div className={`${style.text}`}>
          <NodeIcon className="w-4 h-4" />
        </div>

        <div className="flex-1 min-w-0">
          <div className={`text-sm font-medium truncate ${style.text}`}>
            {label}
          </div>
          {durationText && status === "SUCCESS" && (
            <div className="text-xs text-gray-500 mt-0.5">
              {durationText}
            </div>
          )}
          {status === "FAILED" && result?.error && (
            <div className="text-xs text-red-400 mt-0.5 truncate">
              {String(result.error).slice(0, 30)}
            </div>
          )}
          {retryCount > 0 && status === "RUNNING" && (
            <div className="text-xs text-yellow-400 mt-0.5">
              重试 {retryCount}
            </div>
          )}
        </div>

        {/* 状态图标 */}
        <div className={`${style.text} flex-shrink-0`}>
          {StatusIcon && (
            <StatusIcon className={`w-4 h-4 ${style.animate || ""}`} />
          )}
        </div>
      </div>

      {/* 子步骤进度（Film IR 深度分析等） */}
      {status === "RUNNING" && result?.substeps && Array.isArray(result.substeps) && (
        <div className="mt-2 space-y-1">
          {(result.substeps as Array<{name: string; status: string}>).map((sub, i) => (
            <div key={i} className="flex items-center gap-1.5 text-xs">
              {sub.status === "success" ? (
                <CheckCircle2 className="w-3 h-3 text-green-400" />
              ) : sub.status === "running" ? (
                <Loader2 className="w-3 h-3 text-blue-400 animate-spin" />
              ) : sub.status === "failed" ? (
                <AlertCircle className="w-3 h-3 text-red-400" />
              ) : (
                <div className="w-3 h-3 rounded-full border border-gray-600" />
              )}
              <span className={
                sub.status === "success" ? "text-green-400" :
                sub.status === "running" ? "text-blue-300" :
                sub.status === "failed" ? "text-red-400" :
                "text-gray-500"
              }>
                {sub.name}
              </span>
            </div>
          ))}
        </div>
      )}

      {/* Gate 标记 */}
      {gate && status !== "SUCCESS" && (
        <div className="mt-1.5 flex items-center gap-1 text-xs text-amber-500/70">
          <Lock className="w-3 h-3" />
          <span>需确认</span>
        </div>
      )}

      {/* 可展开标记 */}
      {expandable && (
        <div className="mt-1.5 flex items-center gap-1 text-xs text-blue-400/70">
          {expanded ? (
            <ChevronDown className="w-3 h-3" />
          ) : (
            <ChevronRight className="w-3 h-3" />
          )}
          <span>{expanded ? "收起详情" : "查看分析详情"}</span>
        </div>
      )}

      {/* 输出端口 */}
      <Handle
        type="source"
        position={Position.Bottom}
        className="!w-2.5 !h-2.5 !bg-gray-500 !border-gray-400"
      />
    </div>
  )
}

export const WorkflowNode = memo(WorkflowNodeInner)
