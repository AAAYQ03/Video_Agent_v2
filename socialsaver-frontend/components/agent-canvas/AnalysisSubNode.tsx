"use client"

// components/agent-canvas/AnalysisSubNode.tsx
// Film IR 分析子节点 — 可展开显示详细分析内容

import { memo, useCallback } from "react"
import { Handle, Position, type NodeProps } from "@xyflow/react"
import { useAgentStore } from "@/stores/agentStore"
import {
  BookOpen, FileText, Clapperboard, Users,
  ChevronDown, ChevronRight, CheckCircle2, Loader2,
} from "lucide-react"

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"

// 子节点图标映射
const SUB_ICONS: Record<string, React.ElementType> = {
  story_theme: BookOpen,
  narrative: FileText,
  shot_recipe: Clapperboard,
  character_ledger: Users,
}

// API 路径映射
const API_PATHS: Record<string, string> = {
  story_theme: "film_ir/story_theme",
  narrative: "film_ir/narrative",
  shot_recipe: "film_ir/shots",
  character_ledger: "character-ledger",
}

interface AnalysisSubNodeData {
  subNodeId: string
  label: string
  icon: string
  status: string
  analysisData: Record<string, unknown> | null
  isExpanded: boolean
  jobId: string
}

function AnalysisSubNodeInner({ data }: NodeProps) {
  const nodeData = data as unknown as AnalysisSubNodeData
  const { subNodeId, label, icon, status, analysisData, isExpanded, jobId } = nodeData
  const { toggleSubNodeExpand, updateSubNodeData } = useAgentStore()

  const Icon = SUB_ICONS[icon] || FileText

  const handleClick = useCallback(async () => {
    toggleSubNodeExpand(subNodeId)

    // 首次展开时从 API 拉取数据
    if (!analysisData && jobId) {
      const apiPath = API_PATHS[icon]
      if (!apiPath) return
      try {
        const res = await fetch(`${API_BASE_URL}/api/job/${jobId}/${apiPath}`)
        if (res.ok) {
          const data = await res.json()
          updateSubNodeData(subNodeId, data)
        }
      } catch {
        // 静默失败
      }
    }
  }, [subNodeId, analysisData, jobId, icon, toggleSubNodeExpand, updateSubNodeData])

  return (
    <div
      className={`
        rounded-lg border shadow-lg cursor-pointer transition-all
        ${isExpanded ? "min-w-[360px] max-w-[480px]" : "min-w-[180px] max-w-[220px]"}
        bg-gray-850 border-gray-600 hover:border-gray-500
      `}
      onClick={handleClick}
      style={{ backgroundColor: "#1a1d23" }}
    >
      <Handle type="target" position={Position.Top} className="!w-2 !h-2 !bg-gray-500" />

      {/* 标题栏 */}
      <div className="px-3 py-2 flex items-center gap-2">
        <Icon className="w-3.5 h-3.5 text-blue-400 flex-shrink-0" />
        <span className="text-sm text-gray-200 flex-1">{label}</span>
        {status === "success" && <CheckCircle2 className="w-3.5 h-3.5 text-green-400 flex-shrink-0" />}
        {isExpanded ? (
          <ChevronDown className="w-3.5 h-3.5 text-gray-500 flex-shrink-0" />
        ) : (
          <ChevronRight className="w-3.5 h-3.5 text-gray-500 flex-shrink-0" />
        )}
      </div>

      {/* 展开后的详细内容 */}
      {isExpanded && (
        <div className="border-t border-gray-700 px-3 py-2 max-h-[500px] overflow-y-auto">
          {!analysisData ? (
            <div className="flex items-center gap-2 text-gray-500 text-xs py-2">
              <Loader2 className="w-3 h-3 animate-spin" />
              加载中...
            </div>
          ) : (
            <AnalysisContent type={icon} data={analysisData} />
          )}
        </div>
      )}

      <Handle type="source" position={Position.Bottom} className="!w-2 !h-2 !bg-gray-500" />
    </div>
  )
}

export const AnalysisSubNode = memo(AnalysisSubNodeInner)

// ============================================================
// 各分析类型的内容渲染
// ============================================================

function AnalysisContent({ type, data }: { type: string; data: Record<string, unknown> }) {
  switch (type) {
    case "story_theme":
      return <StoryThemeContent data={data} />
    case "narrative":
      return <NarrativeContent data={data} />
    case "shot_recipe":
      return <ShotRecipeContent data={data} />
    case "character_ledger":
      return <CharacterLedgerContent data={data} />
    default:
      return <pre className="text-xs text-gray-400">{JSON.stringify(data, null, 2)}</pre>
  }
}

// ---------- 主题分析 ----------
function StoryThemeContent({ data }: { data: Record<string, unknown> }) {
  const theme = data as Record<string, unknown>
  return (
    <div className="space-y-2 text-xs">
      <Field label="核心主题" value={getNestedValue(theme, "coreTheme.summary") || getNestedValue(theme, "coreTheme")} />
      <Field label="关键词" value={getNestedValue(theme, "coreTheme.keywords")} />
      <Field label="叙事方法" value={getNestedValue(theme, "narrativeStructure.method") || getNestedValue(theme, "narrative")} />
      <Field label="视觉风格" value={getNestedValue(theme, "audioVisual.visualStyle") || getNestedValue(theme, "audioVisual")} />
      <Field label="情感基调" value={getNestedValue(theme, "thematicStance.emotionalTone") || getNestedValue(theme, "thematicStance")} />
      <Field label="象征符号" value={getNestedValue(theme, "symbolism")} />
      <Field label="现实意义" value={getNestedValue(theme, "realWorldSignificance")} />
    </div>
  )
}

// ---------- 脚本分析 ----------
function NarrativeContent({ data }: { data: Record<string, unknown> }) {
  const narrative = data as Record<string, unknown>
  return (
    <div className="space-y-2 text-xs">
      <Field label="主题意图" value={getNestedValue(narrative, "themeIntent")} />
      <Field label="故事结构" value={getNestedValue(narrative, "storyStructure")} />
      <Field label="角色系统" value={getNestedValue(narrative, "characterSystem")} />
      <Field label="冲突设计" value={getNestedValue(narrative, "conflictDesign")} />
      <Field label="节奏控制" value={getNestedValue(narrative, "plotRhythm")} />
      <Field label="类型风格" value={getNestedValue(narrative, "genreStyle")} />
      {narrative.detailedCharacterBios && (
        <div>
          <span className="text-gray-500 block mb-1">角色详细描述</span>
          {Array.isArray(narrative.detailedCharacterBios) ? (
            narrative.detailedCharacterBios.map((bio: Record<string, unknown>, i: number) => (
              <div key={i} className="bg-gray-800 rounded p-2 mb-1">
                <span className="text-blue-300 font-medium">{String(bio.name || bio.displayName || `角色 ${i + 1}`)}</span>
                <p className="text-gray-400 mt-0.5">{String(bio.description || bio.bio || "")}</p>
              </div>
            ))
          ) : (
            <pre className="text-gray-400 bg-gray-800 rounded p-2">{formatValue(narrative.detailedCharacterBios)}</pre>
          )}
        </div>
      )}
    </div>
  )
}

// ---------- 分镜切割 ----------
function ShotRecipeContent({ data }: { data: Record<string, unknown> }) {
  const shots = (data as Record<string, unknown[]>)?.shots || (data as Record<string, unknown[]>)?.storyboard || []
  if (!Array.isArray(shots)) {
    return <pre className="text-xs text-gray-400">{JSON.stringify(data, null, 2)}</pre>
  }

  return (
    <div className="space-y-2 text-xs">
      <div className="text-gray-500 mb-1">{shots.length} 个镜头</div>
      {shots.map((shot: Record<string, unknown>, i: number) => {
        const shotId = shot.shotId || shot.shot_id || `shot_${String(i + 1).padStart(2, "0")}`
        const camera = shot.camera as Record<string, unknown> | undefined
        return (
          <div key={i} className="bg-gray-800 rounded p-2 space-y-1">
            <div className="flex items-center justify-between">
              <span className="text-blue-300 font-medium">{String(shotId)}</span>
              <span className="text-gray-500">
                {shot.startTime && `${String(shot.startTime)} - ${String(shot.endTime)}`}
              </span>
            </div>
            {shot.subject && (
              <p className="text-gray-300">{String(shot.subject).slice(0, 120)}</p>
            )}
            {camera && (
              <div className="flex flex-wrap gap-1.5 mt-1">
                {camera.shotSize && <Tag label={String(camera.shotSize)} />}
                {camera.cameraAngle && <Tag label={String(camera.cameraAngle)} />}
                {camera.cameraMovement && <Tag label={String(camera.cameraMovement)} />}
              </div>
            )}
            {shot.lighting && (
              <p className="text-gray-500 text-[10px]">{String(shot.lighting).slice(0, 80)}</p>
            )}
          </div>
        )
      })}
    </div>
  )
}

// ---------- 角色发现 ----------
function CharacterLedgerContent({ data }: { data: Record<string, unknown> }) {
  const characters = (data as Record<string, unknown[]>)?.characters ||
    (data as Record<string, unknown[]>)?.characterLedger || []
  const environments = (data as Record<string, unknown[]>)?.environments ||
    (data as Record<string, unknown[]>)?.environmentLedger || []

  return (
    <div className="space-y-3 text-xs">
      {/* 角色 */}
      <div>
        <span className="text-gray-500 block mb-1">角色 ({Array.isArray(characters) ? characters.length : 0})</span>
        {Array.isArray(characters) && characters.map((char: Record<string, unknown>, i: number) => (
          <div key={i} className="bg-gray-800 rounded p-2 mb-1">
            <div className="flex items-center justify-between">
              <span className="text-blue-300 font-medium">
                {String(char.displayName || char.name || `角色 ${i + 1}`)}
              </span>
              <span className={`text-[10px] px-1.5 py-0.5 rounded ${
                char.importance === "PRIMARY" ? "bg-blue-500/20 text-blue-300" : "bg-gray-600/30 text-gray-400"
              }`}>
                {String(char.importance || "SECONDARY")}
              </span>
            </div>
            {char.visualDescription && (
              <p className="text-gray-400 mt-1">{String(char.visualDescription).slice(0, 100)}</p>
            )}
            {char.appearsInShots && Array.isArray(char.appearsInShots) && (
              <div className="flex flex-wrap gap-1 mt-1">
                {char.appearsInShots.map((s: string, j: number) => (
                  <span key={j} className="text-[10px] bg-gray-700 px-1 rounded">{s}</span>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>

      {/* 环境 */}
      {Array.isArray(environments) && environments.length > 0 && (
        <div>
          <span className="text-gray-500 block mb-1">环境 ({environments.length})</span>
          {environments.map((env: Record<string, unknown>, i: number) => (
            <div key={i} className="bg-gray-800 rounded p-2 mb-1">
              <span className="text-green-300 font-medium">
                {String(env.displayName || env.name || `环境 ${i + 1}`)}
              </span>
              {env.visualDescription && (
                <p className="text-gray-400 mt-0.5">{String(env.visualDescription).slice(0, 80)}</p>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ============================================================
// 辅助组件
// ============================================================

function Field({ label, value }: { label: string; value: unknown }) {
  if (!value) return null
  return (
    <div>
      <span className="text-gray-500">{label}</span>
      <p className="text-gray-300 mt-0.5">{formatValue(value)}</p>
    </div>
  )
}

function Tag({ label }: { label: string }) {
  return (
    <span className="text-[10px] bg-gray-700 text-gray-300 px-1.5 py-0.5 rounded">
      {label}
    </span>
  )
}

function formatValue(value: unknown): string {
  if (typeof value === "string") return value
  if (Array.isArray(value)) return value.join(", ")
  if (typeof value === "object" && value !== null) {
    // 尝试提取常见字段
    const obj = value as Record<string, unknown>
    if (obj.summary) return String(obj.summary)
    if (obj.description) return String(obj.description)
    return JSON.stringify(value, null, 2)
  }
  return String(value)
}

function getNestedValue(obj: Record<string, unknown>, path: string): unknown {
  return path.split(".").reduce((acc: unknown, key) => {
    if (acc && typeof acc === "object") return (acc as Record<string, unknown>)[key]
    return undefined
  }, obj)
}
