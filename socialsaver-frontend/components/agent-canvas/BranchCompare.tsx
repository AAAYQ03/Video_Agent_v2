"use client"

// components/agent-canvas/BranchCompare.tsx
// Phase 2.4：所有分支的 OUTPUT 节点都 SUCCESS 时弹出，让用户选一版

import { useEffect, useMemo, useState } from "react"
import { useAgentStore, type GraphNode } from "@/stores/agentStore"
import { Button } from "@/components/ui/button"
import { CheckCircle2, GitBranch, X, Trophy } from "lucide-react"

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"

/**
 * 给定一个分支名，找出该分支的 OUTPUT 节点
 */
function findOutputNode(nodes: GraphNode[], branch: string): GraphNode | undefined {
  return nodes.find((n) => n.type === "OUTPUT" && n.branch === branch)
}

/**
 * 从节点 result 中提取可播放的视频路径（如果有）
 * Mode 1 / Mode 2 的 OUTPUT / MERGE 节点产物字段名不一，做几种容错
 */
function extractVideoUrl(node: GraphNode | undefined, jobId: string): string | null {
  if (!node) return null
  const r = node.result as Record<string, unknown>
  const candidates = [
    r.video,
    r.output_path,
    r.path,
    r.url,
    (r.assets as Record<string, unknown> | undefined)?.video,
  ].filter(Boolean) as string[]

  for (const c of candidates) {
    if (typeof c !== "string") continue
    // 已经是 http(s) URL
    if (c.startsWith("http")) return c
    // 相对路径：拼成 /assets URL（注意：Batch 1 之后此路径需要签名 URL，
    // 这里先返回直链让 dev 模式能看到，生产应通过 /api/asset/sign 换签名）
    return `${API_BASE_URL}/assets/${jobId}/${c.replace(/^\/+/, "")}`
  }
  return null
}

interface BranchCompareProps {
  open: boolean
  onClose: () => void
}

export function BranchCompare({ open, onClose }: BranchCompareProps) {
  const { graph, jobId } = useAgentStore()
  const [picked, setPicked] = useState<string | null>(null)

  const branches = useMemo(() => {
    if (!graph) return [] as string[]
    const set = new Set<string>()
    graph.nodes.forEach((n) => set.add(n.branch || "main"))
    return Array.from(set)
  }, [graph])

  // 仅当有 ≥2 个分支 + 每个分支的 OUTPUT 都 SUCCESS 时才有比较意义
  const allOutputsDone = useMemo(() => {
    if (!graph || branches.length < 2) return false
    return branches.every((b) => {
      const out = findOutputNode(graph.nodes, b)
      return out?.status === "SUCCESS"
    })
  }, [graph, branches])

  useEffect(() => {
    if (!open) setPicked(null)
  }, [open])

  if (!open || !graph || !jobId) return null
  if (!allOutputsDone) {
    // 防御：万一被父级提前打开，给出友好提示
    return (
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm">
        <div className="bg-gray-900 border border-gray-700 rounded-xl w-[400px] p-6 text-center">
          <p className="text-sm text-gray-300 mb-4">还有分支未完成，无法对比</p>
          <Button variant="outline" onClick={onClose}>
            关闭
          </Button>
        </div>
      </div>
    )
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm overflow-y-auto p-6">
      <div className="bg-gray-900 border border-gray-700 rounded-xl w-full max-w-6xl shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-3 border-b border-gray-700">
          <div className="flex items-center gap-2">
            <Trophy className="w-4 h-4 text-amber-400" />
            <h3 className="text-sm font-medium text-gray-200">
              分支对比 — 选一版保留
            </h3>
            <span className="text-xs text-gray-500 ml-2">{branches.length} 个分支已完成</span>
          </div>
          <button
            onClick={onClose}
            className="text-gray-500 hover:text-gray-300"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Branches grid */}
        <div
          className="grid gap-4 p-5"
          style={{
            gridTemplateColumns: `repeat(${Math.min(branches.length, 3)}, minmax(0, 1fr))`,
          }}
        >
          {branches.map((branch) => {
            const out = findOutputNode(graph.nodes, branch)
            const videoUrl = extractVideoUrl(out, jobId)
            const intentNode = graph.nodes.find(
              (n) => n.type === "INTENT_INJECTION" && n.branch === branch
            )
            const intent = intentNode?.config?.intent as string | undefined
            const isPicked = picked === branch

            return (
              <div
                key={branch}
                className={`bg-gray-950 border-2 rounded-lg overflow-hidden transition-colors ${
                  isPicked
                    ? "border-amber-500"
                    : "border-gray-700 hover:border-gray-600"
                }`}
              >
                {/* Branch header */}
                <div className="px-3 py-2 border-b border-gray-800 flex items-center gap-2">
                  <GitBranch className="w-3.5 h-3.5 text-amber-400" />
                  <span className="text-sm font-medium text-gray-200">
                    {branch}
                  </span>
                  {branch === "main" && (
                    <span className="text-xs text-gray-500 ml-auto">主分支</span>
                  )}
                </div>

                {/* Intent description */}
                {intent && (
                  <div className="px-3 py-2 bg-amber-500/5 border-b border-gray-800">
                    <div className="text-xs text-gray-500 mb-0.5">意图</div>
                    <div className="text-xs text-amber-300">{intent}</div>
                  </div>
                )}

                {/* Video preview */}
                <div className="aspect-video bg-black flex items-center justify-center">
                  {videoUrl ? (
                    <video
                      src={videoUrl}
                      controls
                      className="w-full h-full object-contain"
                    />
                  ) : (
                    <div className="text-xs text-gray-600 p-4 text-center">
                      未找到产物视频
                      <br />
                      <span className="text-[10px]">
                        (OUTPUT 节点 result 字段中无可识别的 video 路径)
                      </span>
                    </div>
                  )}
                </div>

                {/* Pick button */}
                <div className="p-3">
                  <Button
                    onClick={() => setPicked(branch)}
                    variant={isPicked ? "default" : "outline"}
                    className={`w-full ${
                      isPicked
                        ? "bg-amber-600 hover:bg-amber-500"
                        : "border-gray-600"
                    }`}
                  >
                    {isPicked ? (
                      <>
                        <CheckCircle2 className="w-4 h-4 mr-2" />
                        已选中
                      </>
                    ) : (
                      "选这一版"
                    )}
                  </Button>
                </div>
              </div>
            )
          })}
        </div>

        {/* Footer actions */}
        <div className="flex items-center justify-between px-5 py-3 border-t border-gray-700 bg-gray-950/50">
          <p className="text-xs text-gray-500">
            选定的版本会保留为最终结果；其他分支产物可以保留在
            <code className="text-amber-300 px-1">branches/</code>
            目录下供后续参考
          </p>
          <div className="flex gap-2">
            <Button variant="outline" onClick={onClose} className="border-gray-600">
              稍后再说
            </Button>
            <Button
              disabled={!picked}
              onClick={() => {
                // MVP：只是关闭对话框；保留/删除分支的实际操作待 Phase 4 落地
                console.log(`[Phase 2.4 MVP] User picked branch: ${picked}`)
                onClose()
              }}
              className="bg-amber-600 hover:bg-amber-500"
            >
              确认选择「{picked || "..."}」
            </Button>
          </div>
        </div>
      </div>
    </div>
  )
}
