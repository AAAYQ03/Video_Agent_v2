// hooks/use-agent-sse.ts
// SSE Hook — 连接 Agent 事件流，驱动画布实时更新

import { useEffect, useRef, useCallback } from "react"
import { useAgentStore } from "@/stores/agentStore"

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"

export function useAgentSSE(jobId: string | null) {
  const eventSourceRef = useRef<EventSource | null>(null)
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null)
  const reconnectAttemptRef = useRef(0)

  const { handleSSEEvent, setConnected, setGraph } = useAgentStore()

  const fetchGraph = useCallback(async () => {
    if (!jobId) return
    try {
      const res = await fetch(`${API_BASE_URL}/api/job/${jobId}/agent/graph`)
      if (res.ok) {
        const graph = await res.json()
        setGraph(graph)
      }
    } catch {
      // 静默失败
    }
  }, [jobId, setGraph])

  const connect = useCallback(() => {
    if (!jobId) return

    // 清理旧连接
    if (eventSourceRef.current) {
      eventSourceRef.current.close()
    }

    const url = `${API_BASE_URL}/api/job/${jobId}/agent/stream`
    const es = new EventSource(url)
    eventSourceRef.current = es

    es.onopen = () => {
      setConnected(true)
      reconnectAttemptRef.current = 0
      // 连接成功后拉取完整 graph
      fetchGraph()
    }

    // 监听所有事件类型
    const eventTypes = [
      "graph_created", "graph_resumed",
      "node_started", "node_completed", "node_failed", "node_retrying",
      "node_progress",
      "gate_reached",
      "workflow_complete", "workflow_blocked", "workflow_paused",
      "workflow_resumed", "workflow_stopped",
      "agent_message", "graph_updated",
      "quality_issue",
    ]

    for (const eventType of eventTypes) {
      es.addEventListener(eventType, (e: MessageEvent) => {
        try {
          const parsed = JSON.parse(e.data)
          handleSSEEvent(parsed)

          // graph 结构变化时重新拉取
          if (["graph_created", "graph_resumed", "graph_updated"].includes(eventType)) {
            fetchGraph()
          }
        } catch {
          // JSON 解析失败，忽略
        }
      })
    }

    es.onerror = () => {
      setConnected(false)
      es.close()

      // 指数退避重连: 1s, 2s, 4s, 8s, 16s (上限)
      const delay = Math.min(1000 * Math.pow(2, reconnectAttemptRef.current), 16000)
      reconnectAttemptRef.current += 1

      reconnectTimeoutRef.current = setTimeout(() => {
        connect()
      }, delay)
    }
  }, [jobId, handleSSEEvent, setConnected, fetchGraph])

  useEffect(() => {
    connect()

    return () => {
      if (eventSourceRef.current) {
        eventSourceRef.current.close()
      }
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current)
      }
      setConnected(false)
    }
  }, [connect, setConnected])

  return {
    disconnect: () => {
      if (eventSourceRef.current) {
        eventSourceRef.current.close()
        setConnected(false)
      }
    },
    reconnect: connect,
  }
}
