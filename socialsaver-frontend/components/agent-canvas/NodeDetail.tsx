"use client"

// components/agent-canvas/NodeDetail.tsx
// 节点详情面板 — 点击节点后在右侧展示

import { useState } from "react"
import { useAgentStore } from "@/stores/agentStore"
import { X, Clock, CheckCircle2, AlertCircle, Settings, GitBranch, Loader2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import { forkBranch } from "@/lib/api"

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"

// 节点类型 → 是否允许从此处 fork（OUTPUT/MERGE 等终端节点没有下游不能 fork）
const FORK_DISALLOWED_TYPES = new Set(["OUTPUT"])

export function NodeDetail() {
  const { graph, selectedNodeId, setSelectedNode, jobId } = useAgentStore()
  const [forkOpen, setForkOpen] = useState(false)
  const [branchName, setBranchName] = useState("")
  const [intentOverride, setIntentOverride] = useState("")
  const [forking, setForking] = useState(false)
  const [forkError, setForkError] = useState<string | null>(null)

  if (!graph || !selectedNodeId) return null

  const node = graph.nodes.find((n) => n.id === selectedNodeId)
  if (!node) return null

  // 是否允许从此节点 fork：节点必须 SUCCESS 且不是终端节点
  const canFork =
    node.status === "SUCCESS" && !FORK_DISALLOWED_TYPES.has(node.type)

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

  const handleFork = async () => {
    if (!jobId || !branchName.trim()) return
    setForking(true)
    setForkError(null)
    try {
      await forkBranch(jobId, {
        forkNodeId: node.id,
        branchName: branchName.trim(),
        intentOverride: intentOverride.trim() || undefined,
      })
      setForkOpen(false)
      setBranchName("")
      setIntentOverride("")
      // SSE branch_created 事件会触发 fetchGraph 自动刷新画布
    } catch (e) {
      setForkError(e instanceof Error ? e.message : "Fork failed")
    } finally {
      setForking(false)
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

        {/* 从此处分叉（Phase 2.4）：节点 SUCCESS 且非终端时显示 */}
        {canFork && (
          <div className="pt-2">
            <Button
              onClick={() => setForkOpen(true)}
              variant="outline"
              className="w-full border-amber-500/40 text-amber-300 hover:bg-amber-500/10"
            >
              <GitBranch className="w-4 h-4 mr-2" />
              从此处分叉（AB 探索）
            </Button>
          </div>
        )}

        {/* 分支信息（如果当前节点属于非 main 分支） */}
        {node.branch && node.branch !== "main" && (
          <div className="rounded bg-amber-500/5 border border-amber-500/20 p-2">
            <div className="text-xs text-amber-400 flex items-center gap-1.5">
              <GitBranch className="w-3.5 h-3.5" />
              所属分支: {node.branch}
            </div>
          </div>
        )}
      </div>

      {/* Fork 对话框 — 简单 inline overlay，不引 Dialog 组件 */}
      {forkOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
          <div className="bg-gray-900 border border-gray-700 rounded-xl w-[460px] shadow-2xl p-5">
            <div className="flex items-center gap-2 mb-1">
              <GitBranch className="w-4 h-4 text-amber-400" />
              <h3 className="text-sm font-medium text-gray-200">
                从「{node.label}」分叉
              </h3>
            </div>
            <p className="text-xs text-gray-500 mb-4">
              复制此节点之后的所有下游节点为新分支，与主路径并行执行；
              产物写入独立目录 <code className="text-amber-300">jobs/.../branches/{branchName || "<分支名>"}</code>。
            </p>

            <div className="space-y-3">
              <div>
                <label className="text-xs text-gray-400 block mb-1">
                  分支名 <span className="text-red-400">*</span>
                </label>
                <input
                  type="text"
                  value={branchName}
                  onChange={(e) => setBranchName(e.target.value)}
                  placeholder="例如 cyberpunk_alt / variant_b"
                  className="w-full bg-gray-800 border border-gray-600 rounded px-3 py-1.5 text-xs text-gray-200 focus:outline-none focus:border-amber-500"
                />
                <p className="text-[10px] text-gray-600 mt-1">
                  仅字母数字下划线，不能是 "main"
                </p>
              </div>

              <div>
                <label className="text-xs text-gray-400 block mb-1">
                  改写意图（可选）
                </label>
                <textarea
                  value={intentOverride}
                  onChange={(e) => setIntentOverride(e.target.value)}
                  placeholder="例：把风格改成赛博朋克霓虹"
                  rows={3}
                  className="w-full bg-gray-800 border border-gray-600 rounded px-3 py-1.5 text-xs text-gray-200 focus:outline-none focus:border-amber-500"
                />
                <p className="text-[10px] text-gray-600 mt-1">
                  填写后会写入分支版的 INTENT_INJECTION 节点；不填则沿用主分支意图
                </p>
              </div>

              {forkError && (
                <div className="bg-red-950/50 border border-red-800 rounded p-2 text-xs text-red-300">
                  {forkError}
                </div>
              )}
            </div>

            <div className="flex gap-2 mt-5">
              <Button
                variant="outline"
                onClick={() => setForkOpen(false)}
                disabled={forking}
                className="flex-1 border-gray-600"
              >
                取消
              </Button>
              <Button
                onClick={handleFork}
                disabled={!branchName.trim() || forking}
                className="flex-1 bg-amber-600 hover:bg-amber-500"
              >
                {forking ? (
                  <>
                    <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                    创建中...
                  </>
                ) : (
                  <>
                    <GitBranch className="w-4 h-4 mr-2" />
                    创建分支
                  </>
                )}
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
