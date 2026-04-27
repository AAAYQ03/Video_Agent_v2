"use client"

// app/dashboard/agent-canvas/page.tsx
// Agent Workflow Canvas 主页面
// 流程：上传视频 → 立刻看到画布（所有节点 PENDING）→ 输入目标 → Agent 执行

import { useState, useEffect, useRef, useCallback, Suspense } from "react"
import { useSearchParams, useRouter } from "next/navigation"
import { ReactFlowProvider } from "@xyflow/react"
import { WorkflowCanvas } from "@/components/agent-canvas/WorkflowCanvas"
import { AgentChat } from "@/components/agent-canvas/AgentChat"
import { NodeDetail } from "@/components/agent-canvas/NodeDetail"
import { BranchCompare } from "@/components/agent-canvas/BranchCompare"
import { useAgentSSE } from "@/hooks/use-agent-sse"
import { useAgentStore, type AgentGraph } from "@/stores/agentStore"
import { uploadVideo, getUploadStatus } from "@/lib/api"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import {
  ArrowLeft, Play, Pause, Square, Wifi, WifiOff,
  Loader2, Upload, CheckCircle2, Film, GitBranch,
} from "lucide-react"
import Link from "next/link"

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"

// 客户端生成的预览 DAG（和后端 create_default 一致）
function createPreviewGraph(): AgentGraph {
  const y = 120
  const nodes = [
    { id: "node_input", type: "INPUT", label: "上传视频", x: 0, y: 0 },
    { id: "node_analyze", type: "ANALYZE", label: "AI 分析视频", x: 0, y: y },
    { id: "node_watermark", type: "WATERMARK_CLEAN", label: "水印清理", x: -200, y: y * 2 },
    { id: "node_film_ir", type: "FILM_IR_ANALYSIS", label: "Film IR 深度分析", x: 200, y: y * 2 },
    { id: "node_abstraction", type: "ABSTRACTION", label: "逻辑抽象", x: 200, y: y * 3 },
    { id: "node_intent", type: "INTENT_INJECTION", label: "意图注入", x: 200, y: y * 4 },
    { id: "node_assets", type: "ASSET_GENERATION", label: "资产生成", x: 200, y: y * 5 },
    { id: "node_storyboard", type: "STORYBOARD", label: "生成分镜", x: 0, y: y * 6 },
    { id: "node_video", type: "VIDEO_GENERATION", label: "生成视频", x: 0, y: y * 7 },
    { id: "node_merge", type: "MERGE", label: "合并输出", x: 0, y: y * 8 },
    { id: "node_output", type: "OUTPUT", label: "完成", x: 0, y: y * 9 },
  ].map((n) => ({
    id: n.id,
    type: n.type,
    label: n.label,
    config: {},
    gate: ["INTENT_INJECTION", "ASSET_GENERATION", "STORYBOARD"].includes(n.type),
    status: "PENDING" as const,
    result: {},
    position: { x: n.x, y: n.y },
    branch: "main",
    retryCount: 0,
    maxRetries: 2,
    startedAt: null,
    completedAt: null,
  }))

  const edges = [
    { source: "node_input", target: "node_analyze" },
    { source: "node_analyze", target: "node_watermark" },
    { source: "node_analyze", target: "node_film_ir" },
    { source: "node_film_ir", target: "node_abstraction" },
    { source: "node_abstraction", target: "node_intent" },
    { source: "node_intent", target: "node_assets" },
    { source: "node_watermark", target: "node_storyboard" },
    { source: "node_assets", target: "node_storyboard" },
    { source: "node_storyboard", target: "node_video" },
    { source: "node_video", target: "node_merge" },
    { source: "node_merge", target: "node_output" },
  ].map((e) => ({
    id: `e_${e.source}_${e.target}`,
    source: e.source,
    target: e.target,
  }))

  return {
    version: 1,
    createdAt: new Date().toISOString(),
    userGoal: "",
    status: "PENDING",
    gateDefaults: ["INTENT_INJECTION", "ASSET_GENERATION", "STORYBOARD"],
    nodes,
    edges,
  }
}

export default function AgentCanvasPageWrapper() {
  return (
    <Suspense fallback={<div className="flex items-center justify-center h-screen bg-gray-950 text-gray-400">Loading...</div>}>
      <AgentCanvasPage />
    </Suspense>
  )
}

function AgentCanvasPage() {
  const searchParams = useSearchParams()
  const router = useRouter()
  const initialJobId = searchParams.get("jobId")

  const [jobId, setLocalJobId] = useState<string | null>(initialJobId)
  const [hasVideo, setHasVideo] = useState(!!initialJobId)
  const [analysisReady, setAnalysisReady] = useState(false)
  const [analysisStatus, setAnalysisStatus] = useState("")
  const [goal, setGoal] = useState("")
  const [skipGates, setSkipGates] = useState(false)

  // 上传相关
  const [uploading, setUploading] = useState(false)
  const [dragActive, setDragActive] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)

  // Phase 2.4：分支对比视图状态
  const [compareOpen, setCompareOpen] = useState(false)
  const [autoOpenedCompare, setAutoOpenedCompare] = useState(false)

  // 素材分级（Batch 1 设计原意：让用户显式选择，责任前置）
  const [materialTag, setMaterialTag] = useState<"INTERNAL" | "VIRAL_REF">("INTERNAL")
  const [containsConfidential, setContainsConfidential] = useState(false)
  const [referenceUrl, setReferenceUrl] = useState("")
  const [referenceDimensions, setReferenceDimensions] = useState<string[]>([])

  const REFERENCE_DIMENSIONS = [
    { value: "structure", label: "结构" },
    { value: "pacing", label: "节奏" },
    { value: "visual_style", label: "视觉风格" },
    { value: "script_hook", label: "脚本钩子" },
  ]

  const isMaterialValid =
    materialTag === "INTERNAL" ||
    (referenceUrl.trim().length > 0 && referenceDimensions.length > 0)

  const toggleDimension = (value: string) => {
    setReferenceDimensions((prev) =>
      prev.includes(value) ? prev.filter((d) => d !== value) : [...prev, value]
    )
  }

  const {
    setJobId, setGraph, updateNodeStatus,
    graph, selectedNodeId, isConnected, agentStatus,
  } = useAgentStore()

  // 同步 jobId 到 store
  useEffect(() => {
    if (jobId) setJobId(jobId)
  }, [jobId, setJobId])

  // 有 jobId 时检查状态 + 设置预览 DAG
  useEffect(() => {
    if (!initialJobId) return
    setHasVideo(true)

    // 先展示预览 DAG
    if (!graph) {
      const preview = createPreviewGraph()
      // 有 jobId 说明视频已上传，INPUT 标绿
      const inputNode = preview.nodes.find(n => n.id === "node_input")
      if (inputNode) inputNode.status = "SUCCESS"
      setGraph(preview)
    }

    const checkStatus = async () => {
      try {
        const status = await getUploadStatus(initialJobId)
        const filmIrResult = {
          substeps: [
            { name: "主题分析", status: "success" },
            { name: "脚本分析", status: "success" },
            { name: "分镜切割", status: "success" },
            { name: "角色发现", status: "success" },
          ],
        }
        if (status.status === "completed") {
          setAnalysisReady(true)
          setAnalysisStatus("分析完成")
          updateNodeStatus("node_analyze", "SUCCESS")
          updateNodeStatus("node_watermark", "SUCCESS")
          updateNodeStatus("node_film_ir", "SUCCESS", filmIrResult)
        } else if (status.status === "analyzing" || status.status === "queued") {
          setAnalysisStatus(status.message || "分析中...")
          updateNodeStatus("node_analyze", "RUNNING")
          pollAnalysisStatus(initialJobId)
        } else {
          setAnalysisReady(true)
          updateNodeStatus("node_analyze", "SUCCESS")
          updateNodeStatus("node_watermark", "SUCCESS")
          updateNodeStatus("node_film_ir", "SUCCESS", filmIrResult)
        }
      } catch {
        setAnalysisReady(true)
      }
    }
    checkStatus()
  }, [initialJobId])

  // SSE 连接：jobId 存在就订阅
  // 注意：之前的 (agentStatus !== "not_started" ? jobId : null) 是死锁——
  // agentStatus 变化的唯一信号是 SSE graph_created 事件，门控让事件
  // 永远收不到，dialog 永远不消失。改为有 jobId 立即订阅。
  useAgentSSE(jobId)

  // Phase 2.4: 多分支全部完成时自动弹对比视图
  useEffect(() => {
    if (!graph) return
    const branches = Array.from(new Set(graph.nodes.map(n => n.branch || "main")))
    if (branches.length < 2) return
    const allOutputsDone = branches.every(b => {
      const out = graph.nodes.find(n => n.type === "OUTPUT" && n.branch === b)
      return out?.status === "SUCCESS"
    })
    if (allOutputsDone && !autoOpenedCompare) {
      setCompareOpen(true)
      setAutoOpenedCompare(true)
    }
  }, [graph, autoOpenedCompare])

  // 轮询分析状态
  const pollAnalysisStatus = useCallback((jid: string) => {
    const interval = setInterval(async () => {
      try {
        const status = await getUploadStatus(jid)
        setAnalysisStatus(status.message || "分析中...")
        if (status.status === "completed") {
          clearInterval(interval)
          setAnalysisReady(true)
          setAnalysisStatus("分析完成")
          // Mode 1 的上传流程完成时，以下步骤都已执行完毕
          updateNodeStatus("node_analyze", "SUCCESS")
          updateNodeStatus("node_watermark", "SUCCESS")
          updateNodeStatus("node_film_ir", "SUCCESS", {
            substeps: [
              { name: "主题分析", status: "success" },
              { name: "脚本分析", status: "success" },
              { name: "分镜切割", status: "success" },
              { name: "角色发现", status: "success" },
            ],
          })
        } else if (status.status === "failed") {
          clearInterval(interval)
          setAnalysisStatus(`分析失败: ${status.message}`)
          updateNodeStatus("node_analyze", "FAILED", { error: status.message })
        }
      } catch {
        clearInterval(interval)
      }
    }, 3000)
  }, [updateNodeStatus])

  // 处理文件上传
  const handleFileUpload = async (file: File) => {
    if (!file.type.startsWith("video/")) return
    if (!isMaterialValid) {
      setAnalysisStatus("⚠️ 请先填写完整的素材信息")
      return
    }
    setUploading(true)
    try {
      const result = await uploadVideo(file, {
        materialTag,
        ...(materialTag === "INTERNAL" && containsConfidential
          ? { containsConfidential: true }
          : {}),
        ...(materialTag === "VIRAL_REF"
          ? {
              referenceUrl: referenceUrl.trim(),
              referenceDimensions,
            }
          : {}),
      })
      const newJobId = result.job_id
      setLocalJobId(newJobId)
      setJobId(newJobId)
      setHasVideo(true)
      setAnalysisStatus("上传成功，AI 正在分析视频...")
      router.replace(`/dashboard/agent-canvas?jobId=${newJobId}`)

      // 立刻展示预览 DAG，INPUT 标绿，ANALYZE 标蓝
      const preview = createPreviewGraph()
      const inputNode = preview.nodes.find(n => n.id === "node_input")
      const analyzeNode = preview.nodes.find(n => n.id === "node_analyze")
      if (inputNode) {
        inputNode.status = "SUCCESS"
        inputNode.completedAt = new Date().toISOString()
      }
      if (analyzeNode) {
        analyzeNode.status = "RUNNING"
        analyzeNode.startedAt = new Date().toISOString()
      }
      setGraph(preview)

      pollAnalysisStatus(newJobId)
    } catch (err) {
      setAnalysisStatus(`上传失败: ${err instanceof Error ? err.message : "未知错误"}`)
    } finally {
      setUploading(false)
    }
  }

  // 拖拽
  const handleDrag = (e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setDragActive(e.type === "dragenter" || e.type === "dragover")
  }
  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setDragActive(false)
    if (e.dataTransfer.files?.[0]) handleFileUpload(e.dataTransfer.files[0])
  }
  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files?.[0]) handleFileUpload(e.target.files[0])
  }

  // 启动 Agent
  const handleStart = async () => {
    if (!jobId || !goal.trim()) return
    try {
      await fetch(`${API_BASE_URL}/api/job/${jobId}/agent/start`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ goal: goal.trim(), skip_gates: skipGates }),
      })
    } catch (err) {
      console.error("Failed to start agent:", err)
    }
  }

  // 暂停/恢复/停止
  const handlePauseResume = async () => {
    if (!jobId) return
    const endpoint = agentStatus === "paused" ? "resume" : "pause"
    await fetch(`${API_BASE_URL}/api/job/${jobId}/agent/${endpoint}`, { method: "POST" }).catch(() => {})
  }
  const handleStop = async () => {
    if (!jobId) return
    await fetch(`${API_BASE_URL}/api/job/${jobId}/agent/pause`, { method: "POST" }).catch(() => {})
  }

  return (
    <div className="flex flex-col h-screen bg-gray-950 text-gray-100">
      {/* Header */}
      <header className="h-12 border-b border-gray-800 flex items-center px-4 gap-3 flex-shrink-0">
        <Link href="/dashboard/remix" className="text-gray-400 hover:text-gray-200">
          <ArrowLeft className="w-4 h-4" />
        </Link>
        <Film className="w-4 h-4 text-blue-400" />
        <span className="text-sm font-medium">Agent Canvas</span>
        {jobId && <span className="text-xs text-gray-500">Job: {jobId}</span>}

        <div className="ml-auto flex items-center gap-3">
          {/* 分析状态（上传后、Agent 启动前） */}
          {hasVideo && !analysisReady && agentStatus === "not_started" && (
            <div className="flex items-center gap-1.5 text-xs text-amber-400">
              <Loader2 className="w-3.5 h-3.5 animate-spin" />
              {analysisStatus}
            </div>
          )}
          {/* Phase 2.4：多分支时显示对比视图按钮 */}
          {graph && (() => {
            const branches = Array.from(new Set(graph.nodes.map(n => n.branch || "main")))
            return branches.length >= 2 ? (
              <Button
                size="sm"
                variant="outline"
                onClick={() => setCompareOpen(true)}
                className="h-7 text-xs border-amber-500/40 text-amber-300 hover:bg-amber-500/10"
              >
                <GitBranch className="w-3.5 h-3.5 mr-1" />
                对比 {branches.length} 个分支
              </Button>
            ) : null
          })()}

          {hasVideo && analysisReady && agentStatus === "not_started" && (
            <div className="flex items-center gap-1.5 text-xs text-green-400">
              <CheckCircle2 className="w-3.5 h-3.5" />
              视频分析完成
            </div>
          )}

          {/* SSE 连接状态 */}
          {agentStatus !== "not_started" && (
            <div className={`flex items-center gap-1.5 text-xs ${isConnected ? "text-green-400" : "text-red-400"}`}>
              {isConnected ? <Wifi className="w-3.5 h-3.5" /> : <WifiOff className="w-3.5 h-3.5" />}
              {isConnected ? "Connected" : "Disconnected"}
            </div>
          )}

          {/* 控制按钮 */}
          {agentStatus === "running" && (
            <>
              <Button size="sm" variant="outline" onClick={handlePauseResume} className="h-7 text-xs border-gray-600">
                <Pause className="w-3.5 h-3.5 mr-1" /> 暂停
              </Button>
              <Button size="sm" variant="outline" onClick={handleStop} className="h-7 text-xs border-gray-600 text-red-400">
                <Square className="w-3.5 h-3.5 mr-1" /> 停止
              </Button>
            </>
          )}
          {agentStatus === "paused" && (
            <Button size="sm" variant="outline" onClick={handlePauseResume} className="h-7 text-xs border-gray-600 text-green-400">
              <Play className="w-3.5 h-3.5 mr-1" /> 恢复
            </Button>
          )}
        </div>
      </header>

      {/* Main content */}
      <div className="flex-1 flex overflow-hidden">
        {/* 左侧：Canvas（始终显示） */}
        <div className="flex-1 relative">

          {/* 覆盖层：上传视频（无 jobId 时） */}
          {!hasVideo && (
            <div className="absolute inset-0 flex items-center justify-center z-20 bg-gray-950/80 backdrop-blur-sm">
              <div className="bg-gray-900 border border-gray-700 rounded-xl w-[540px] shadow-2xl overflow-hidden">

                {/* 上半：素材分级表单 */}
                <div className="p-5 border-b border-gray-700 space-y-4">
                  <div>
                    <label className="text-xs text-gray-400 block mb-2">
                      素材类别 <span className="text-red-400">*</span>
                    </label>
                    <div className="grid grid-cols-2 gap-2">
                      <button
                        type="button"
                        onClick={() => setMaterialTag("INTERNAL")}
                        className={`p-3 rounded-lg border text-left transition-colors ${
                          materialTag === "INTERNAL"
                            ? "border-blue-500 bg-blue-500/10"
                            : "border-gray-700 hover:border-gray-600 bg-gray-800/50"
                        }`}
                      >
                        <div className="text-sm font-medium text-gray-200">内部自制</div>
                        <div className="text-xs text-gray-500 mt-0.5">
                          自家拍 / 自家采购的素材
                        </div>
                      </button>
                      <button
                        type="button"
                        onClick={() => setMaterialTag("VIRAL_REF")}
                        className={`p-3 rounded-lg border text-left transition-colors ${
                          materialTag === "VIRAL_REF"
                            ? "border-amber-500 bg-amber-500/10"
                            : "border-gray-700 hover:border-gray-600 bg-gray-800/50"
                        }`}
                      >
                        <div className="text-sm font-medium text-gray-200">爆款参考</div>
                        <div className="text-xs text-gray-500 mt-0.5">
                          外部爆款用于学习模仿
                        </div>
                      </button>
                    </div>
                  </div>

                  {/* INTERNAL 选项 */}
                  {materialTag === "INTERNAL" && (
                    <label className="flex items-center gap-2 text-xs text-gray-400 cursor-pointer">
                      <input
                        type="checkbox"
                        checked={containsConfidential}
                        onChange={(e) => setContainsConfidential(e.target.checked)}
                        className="rounded border-gray-600"
                      />
                      含未公开信息（保密级，将走加强审计与导出审批）
                    </label>
                  )}

                  {/* VIRAL_REF 必填字段 */}
                  {materialTag === "VIRAL_REF" && (
                    <>
                      <div>
                        <label className="text-xs text-gray-400 block mb-1">
                          原片链接 <span className="text-red-400">*</span>
                        </label>
                        <input
                          type="url"
                          value={referenceUrl}
                          onChange={(e) => setReferenceUrl(e.target.value)}
                          placeholder="https://www.tiktok.com/..."
                          className="w-full bg-gray-800 border border-gray-600 rounded px-3 py-1.5 text-xs text-gray-200 focus:outline-none focus:border-amber-500"
                        />
                      </div>
                      <div>
                        <label className="text-xs text-gray-400 block mb-1.5">
                          参考维度 <span className="text-red-400">*</span>
                          <span className="text-gray-600 ml-1">（至少选 1 项）</span>
                        </label>
                        <div className="flex flex-wrap gap-1.5">
                          {REFERENCE_DIMENSIONS.map((d) => {
                            const selected = referenceDimensions.includes(d.value)
                            return (
                              <button
                                key={d.value}
                                type="button"
                                onClick={() => toggleDimension(d.value)}
                                className={`px-2.5 py-1 rounded text-xs border transition-colors ${
                                  selected
                                    ? "border-amber-500 bg-amber-500/10 text-amber-300"
                                    : "border-gray-700 text-gray-400 hover:border-gray-600"
                                }`}
                              >
                                {d.label}
                              </button>
                            )
                          })}
                        </div>
                        <p className="text-xs text-gray-600 mt-1.5">
                          这是合规留证字段——出现版权疑问时能证明"参考学习不是抄袭"
                        </p>
                      </div>
                    </>
                  )}
                </div>

                {/* 下半：拖拽 / 点击区 */}
                <div
                  className={`p-10 text-center transition-colors ${
                    isMaterialValid
                      ? `cursor-pointer ${
                          dragActive
                            ? "bg-blue-500/10"
                            : "hover:bg-gray-800/40"
                        }`
                      : "opacity-50 cursor-not-allowed"
                  }`}
                  onDragEnter={isMaterialValid ? handleDrag : undefined}
                  onDragLeave={handleDrag}
                  onDragOver={isMaterialValid ? handleDrag : undefined}
                  onDrop={isMaterialValid ? handleDrop : undefined}
                  onClick={() => isMaterialValid && fileInputRef.current?.click()}
                >
                  <input
                    ref={fileInputRef}
                    type="file"
                    accept="video/*"
                    className="hidden"
                    onChange={handleFileSelect}
                  />
                  {uploading ? (
                    <>
                      <Loader2 className="w-8 h-8 text-blue-400 mx-auto mb-3 animate-spin" />
                      <p className="text-sm text-gray-300">上传中...</p>
                    </>
                  ) : !isMaterialValid ? (
                    <>
                      <Upload className="w-8 h-8 text-gray-700 mx-auto mb-3" />
                      <p className="text-sm text-amber-400/70">
                        请先完成素材信息再上传
                      </p>
                    </>
                  ) : (
                    <>
                      <Upload className="w-8 h-8 text-gray-500 mx-auto mb-3" />
                      <p className="text-sm text-gray-300 mb-1">
                        拖拽视频到这里，或点击选择
                      </p>
                      <p className="text-xs text-gray-500">
                        MP4 / MOV / WebM 等
                      </p>
                    </>
                  )}
                </div>
              </div>
            </div>
          )}

          {/* 覆盖层：输入目标（分析完成 + Agent 未启动）
              注意：之前有 !graph?.nodes.some(n => n.status !== "PENDING") 条件
              但 Mode 1 分析完毕会把 4 个上游节点标 SUCCESS，导致此条件永假
              对话框永远不出现。已移除——只看 agentStatus 即可。 */}
          {hasVideo && analysisReady && agentStatus === "not_started" && (
            <div className="absolute inset-0 flex items-center justify-center z-10 bg-gray-950/60 backdrop-blur-[2px]">
              <div className="bg-gray-900 border border-gray-700 rounded-xl p-6 w-[420px] shadow-2xl">
                <div className="flex items-center gap-2 mb-1">
                  <CheckCircle2 className="w-4 h-4 text-green-400" />
                  <span className="text-xs text-green-400">视频分析完成</span>
                </div>
                <h2 className="text-lg font-semibold mb-4">启动 Agent</h2>
                <Textarea
                  placeholder="描述你想要的效果，例如：改成吉卜力动画风格，主角换成一个小女孩..."
                  value={goal}
                  onChange={(e) => setGoal(e.target.value)}
                  className="mb-3 bg-gray-800 border-gray-600 min-h-[100px] text-sm"
                />
                <div className="flex items-center gap-2 mb-4">
                  <input
                    type="checkbox"
                    id="skipGates"
                    checked={skipGates}
                    onChange={(e) => setSkipGates(e.target.checked)}
                    className="rounded border-gray-600"
                  />
                  <label htmlFor="skipGates" className="text-xs text-gray-400">
                    跳过确认节点（全自动模式）
                  </label>
                </div>
                <Button onClick={handleStart} disabled={!goal.trim()} className="w-full bg-blue-600 hover:bg-blue-500">
                  <Play className="w-4 h-4 mr-2" /> 开始执行
                </Button>
              </div>
            </div>
          )}

          <ReactFlowProvider>
            <WorkflowCanvas />
          </ReactFlowProvider>
        </div>

        {/* 右侧：Chat + 节点详情 */}
        <div className="w-[320px] flex flex-col flex-shrink-0">
          {selectedNodeId ? <NodeDetail /> : <AgentChat />}
        </div>
      </div>

      {/* Phase 2.4：分支对比视图（多分支全部 OUTPUT SUCCESS 时自动弹出，
          也可通过顶栏「对比 N 个分支」按钮手动打开） */}
      <BranchCompare open={compareOpen} onClose={() => setCompareOpen(false)} />
    </div>
  )
}
