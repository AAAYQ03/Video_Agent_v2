"use client"

// components/agent-canvas/NodeDetail.tsx
// 节点详情面板 — 点击节点后在右侧展示

import { useAgentStore } from "@/stores/agentStore"
import { X, Clock, CheckCircle2, AlertCircle, Settings } from "lucide-react"
import { Button } from "@/components/ui/button"

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"

export function NodeDetail() {
  const { graph, selectedNodeId, setSelectedNode, jobId } = useAgentStore()

  if (!graph || !selectedNodeId) return null

  const node = graph.nodes.find((n) => n.id === selectedNodeId)
  if (!node) return null

  const durationMs = node.result?.duration_ms as number | undefined
  const durationText = durationMs
    ? durationMs > 60000
      ? `${(durationMs / 60000).toFixed(1)} min`
      : durationMs > 1000
      ? `${(durationMs / 1000).toFixed(1)}s`
      : `${durationMs}ms`
    : null

  const handleApproveGate = async () => {
    if (!jobId) return
    try {
      await fetch(`${API_BASE_URL}/api/job/${jobId}/agent/approve-gate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ node_id: node.id }),
      })
    } catch (err) {
      console.error("Failed to approve gate:", err)
    }
  }

  return (
    <div className="bg-gray-900 border-l border-gray-700 w-full">
      {/* Header */}
      <div className="px-4 py-3 border-b border-gray-700 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Settings className="w-4 h-4 text-gray-400" />
          <span className="text-sm font-medium text-gray-200">{node.label}</span>
        </div>
        <button
          onClick={() => setSelectedNode(null)}
          className="text-gray-500 hover:text-gray-300"
        >
          <X className="w-4 h-4" />
        </button>
      </div>

      {/* Content */}
      <div className="px-4 py-3 space-y-4 overflow-y-auto">
        {/* 状态 */}
        <div>
          <div className="text-xs text-gray-500 mb-1">状态</div>
          <div className={`text-sm font-medium ${
            node.status === "SUCCESS" ? "text-green-400" :
            node.status === "FAILED" ? "text-red-400" :
            node.status === "RUNNING" ? "text-blue-400" :
            node.status === "WAITING_APPROVAL" ? "text-amber-400" :
            "text-gray-400"
          }`}>
            {node.status}
          </div>
        </div>

        {/* 类型 */}
        <div>
          <div className="text-xs text-gray-500 mb-1">节点类型</div>
          <div className="text-sm text-gray-300">{node.type}</div>
        </div>

        {/* 耗时 */}
        {durationText && (
          <div>
            <div className="text-xs text-gray-500 mb-1">耗时</div>
            <div className="text-sm text-gray-300 flex items-center gap-1">
              <Clock className="w-3.5 h-3.5" />
              {durationText}
            </div>
          </div>
        )}

        {/* 时间 */}
        {node.startedAt && (
          <div>
            <div className="text-xs text-gray-500 mb-1">开始时间</div>
            <div className="text-sm text-gray-300">
              {new Date(node.startedAt).toLocaleTimeString()}
            </div>
          </div>
        )}

        {/* 重试次数 */}
        {node.retryCount > 0 && (
          <div>
            <div className="text-xs text-gray-500 mb-1">重试次数</div>
            <div className="text-sm text-gray-300">
              {node.retryCount} / {node.maxRetries}
            </div>
          </div>
        )}

        {/* 配置 */}
        {Object.keys(node.config).length > 0 && (
          <div>
            <div className="text-xs text-gray-500 mb-1">配置</div>
            <pre className="text-xs text-gray-400 bg-gray-800 rounded p-2 overflow-x-auto">
              {JSON.stringify(node.config, null, 2)}
            </pre>
          </div>
        )}

        {/* 执行结果 */}
        {Object.keys(node.result).length > 0 && (
          <div>
            <div className="text-xs text-gray-500 mb-1">执行结果</div>
            <pre className="text-xs text-gray-400 bg-gray-800 rounded p-2 overflow-x-auto max-h-48">
              {JSON.stringify(node.result, null, 2)}
            </pre>
          </div>
        )}

        {/* 错误信息 */}
        {node.status === "FAILED" && node.result?.error && (
          <div className="bg-red-950/50 border border-red-800 rounded p-3">
            <div className="flex items-center gap-1.5 text-red-400 text-sm font-medium mb-1">
              <AlertCircle className="w-3.5 h-3.5" />
              错误
            </div>
            <p className="text-xs text-red-300">{String(node.result.error)}</p>
          </div>
        )}

        {/* Gate 审批按钮 */}
        {node.status === "WAITING_APPROVAL" && (
          <div className="pt-2">
            <Button
              onClick={handleApproveGate}
              className="w-full bg-amber-600 hover:bg-amber-500 text-white"
            >
              <CheckCircle2 className="w-4 h-4 mr-2" />
              确认通过
            </Button>
          </div>
        )}
      </div>
    </div>
  )
}
