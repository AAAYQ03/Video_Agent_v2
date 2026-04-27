"use client"

// components/agent-canvas/AgentChat.tsx
// 右侧 Agent Chat 面板

import { useRef, useEffect } from "react"
import { useAgentStore } from "@/stores/agentStore"
import { Bot, User, Loader2, CheckCircle2, AlertCircle, Lock } from "lucide-react"

const ICON_MAP: Record<string, React.ElementType> = {
  "完成": CheckCircle2,
  "失败": AlertCircle,
  "等待确认": Lock,
}

function getMessageIcon(content: string) {
  for (const [keyword, Icon] of Object.entries(ICON_MAP)) {
    if (content.includes(keyword)) return Icon
  }
  return null
}

export function AgentChat() {
  const { chatMessages, agentStatus } = useAgentStore()
  const scrollRef = useRef<HTMLDivElement>(null)

  // 自动滚动到底部
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [chatMessages])

  return (
    <div className="flex flex-col h-full bg-gray-900 border-l border-gray-700">
      {/* Header */}
      <div className="px-4 py-3 border-b border-gray-700 flex items-center gap-2">
        <Bot className="w-4 h-4 text-blue-400" />
        <span className="text-sm font-medium text-gray-200">Agent</span>
        <span className={`ml-auto text-xs px-2 py-0.5 rounded-full ${
          agentStatus === "running"
            ? "bg-blue-500/20 text-blue-300"
            : agentStatus === "completed"
            ? "bg-green-500/20 text-green-300"
            : agentStatus === "failed"
            ? "bg-red-500/20 text-red-300"
            : "bg-gray-500/20 text-gray-400"
        }`}>
          {agentStatus === "running" && "执行中"}
          {agentStatus === "completed" && "已完成"}
          {agentStatus === "failed" && "已阻塞"}
          {agentStatus === "paused" && "已暂停"}
          {agentStatus === "stopped" && "已停止"}
          {agentStatus === "not_started" && "未启动"}
        </span>
      </div>

      {/* 消息列表 */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto px-4 py-3 space-y-3">
        {chatMessages.length === 0 && (
          <div className="text-center text-gray-500 text-sm mt-8">
            Agent 启动后这里会显示执行日志
          </div>
        )}

        {chatMessages.map((msg) => {
          const ContentIcon = msg.role === "agent" ? getMessageIcon(msg.content) : null

          return (
            <div key={msg.id} className="flex gap-2 items-start">
              <div className={`mt-0.5 flex-shrink-0 ${
                msg.role === "agent" ? "text-blue-400" : "text-gray-400"
              }`}>
                {msg.role === "agent" ? (
                  <Bot className="w-3.5 h-3.5" />
                ) : (
                  <User className="w-3.5 h-3.5" />
                )}
              </div>
              <div className="flex-1 min-w-0">
                <p className={`text-sm leading-relaxed ${
                  msg.content.includes("失败")
                    ? "text-red-400"
                    : msg.content.includes("完成")
                    ? "text-green-400"
                    : msg.content.includes("等待确认")
                    ? "text-amber-400"
                    : "text-gray-300"
                }`}>
                  {msg.content}
                </p>
                <span className="text-xs text-gray-600 mt-0.5 block">
                  {new Date(msg.timestamp).toLocaleTimeString()}
                </span>
              </div>
            </div>
          )
        })}

        {agentStatus === "running" && (
          <div className="flex items-center gap-2 text-blue-400 text-sm">
            <Loader2 className="w-3.5 h-3.5 animate-spin" />
            <span>处理中...</span>
          </div>
        )}
      </div>
    </div>
  )
}
