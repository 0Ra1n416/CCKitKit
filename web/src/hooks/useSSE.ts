import { useCallback } from "react"
import type { SseEvent } from "@/lib/api"

export interface SseHandler {
  onProgress?: (ev: SseEvent) => void
  onDone?: (ev: SseEvent) => void
  onError?: (message: string) => void
}

/**
 * 消费 SSE 响应(fetch Response body 是 ReadableStream)。
 * 逐 `data: {json}\n\n` 帧解析,分发 progress / done / error。
 */
export function useSSE() {
  return useCallback(async (response: Response, handler: SseHandler) => {
    if (!response.ok || !response.body) {
      const data = await response.json().catch(() => ({}))
      handler.onError?.(
        (data as { error?: { message?: string } })?.error?.message ??
          `请求失败 (${response.status})`,
      )
      return
    }
    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ""
    try {
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const parts = buffer.split("\n\n")
        buffer = parts.pop() ?? ""
        for (const part of parts) {
          const line = part.trim()
          if (!line.startsWith("data:")) continue
          const payload = line.slice(5).trim()
          if (!payload) continue
          let ev: SseEvent
          try {
            ev = JSON.parse(payload)
          } catch {
            continue
          }
          if (ev.event === "progress") handler.onProgress?.(ev)
          else if (ev.event === "done") handler.onDone?.(ev)
          else if (ev.event === "error")
            handler.onError?.(ev.message ?? "未知错误")
        }
      }
    } finally {
      reader.releaseLock()
    }
  }, [])
}
