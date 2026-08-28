import { useEffect, useRef, useState } from "react"
import { CheckCircle, Warning, Wrench } from "@phosphor-icons/react"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { cn } from "@/lib/utils"
import { api, type Finding } from "@/lib/api"
import { useSSE } from "@/hooks/useSSE"

function StatusIcon({ status }: { status: Finding["status"] }) {
  if (status === "error")
    return <Warning className="h-4 w-4 shrink-0 text-destructive" />
  if (status === "warn")
    return <Warning className="h-4 w-4 shrink-0 text-amber-400" />
  return <CheckCircle className="h-4 w-4 shrink-0 text-primary" />
}

export function DoctorDialog({
  open,
  onOpenChange,
  onDone,
}: {
  open: boolean
  onOpenChange: (o: boolean) => void
  onDone: () => void
}) {
  const [fix, setFix] = useState(false)
  const [running, setRunning] = useState(false)
  const [logs, setLogs] = useState<string[]>([])
  const [findings, setFindings] = useState<Finding[] | null>(null)
  const [error, setError] = useState("")
  const runSSE = useSSE()
  const logRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    logRef.current?.scrollTo({ top: logRef.current.scrollHeight })
  }, [logs, findings])

  const reset = () => {
    setFix(false)
    setRunning(false)
    setLogs([])
    setFindings(null)
    setError("")
  }

  const run = async () => {
    setRunning(true)
    setLogs([])
    setFindings(null)
    setError("")
    try {
      await runSSE(await api.doctor(fix), {
        onProgress: (ev) => setLogs((l) => [...l, ev.message ?? ""]),
        onDone: (ev) => {
          setFindings(ev.findings ?? [])
          setRunning(false)
          onDone()
        },
        onError: (msg) => {
          setError(msg)
          setRunning(false)
        },
      })
    } catch (e) {
      setError((e as Error).message)
      setRunning(false)
    }
  }

  const errCount = findings?.filter((f) => f.status === "error").length ?? 0

  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        if (!o) reset()
        onOpenChange(o)
      }}
    >
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <DialogTitle>诊断</DialogTitle>
          <DialogDescription>
            检查 uv、悬空 link、env、系统依赖、清单预算等「不报错只静默失效」的项
          </DialogDescription>
        </DialogHeader>

        <label className="flex cursor-pointer items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={fix}
            onChange={(e) => setFix(e.target.checked)}
            className="h-4 w-4 accent-primary"
          />
          自动修复明确安全的项（--fix：清理悬空 link、重建损坏 env）
        </label>

        {!running && findings === null && !error && (
          <div>
            <Button onClick={run}>
              <Wrench className="h-4 w-4" /> 开始诊断
            </Button>
          </div>
        )}

        {running && (
          <div
            ref={logRef}
            className="h-40 space-y-1 overflow-y-auto rounded-md border bg-muted/40 p-3 font-mono text-xs"
          >
            {logs.length === 0 && (
              <p className="text-muted-foreground">正在诊断…</p>
            )}
            {logs.map((l, i) => (
              <p key={i} className="text-muted-foreground">
                <span className="text-primary">▸</span> {l}
              </p>
            ))}
          </div>
        )}

        {findings !== null && (
          <>
            <div className="max-h-[45vh] space-y-1.5 overflow-y-auto pr-1">
              {findings.map((f, i) => (
                <div key={i} className="rounded-md border p-2.5">
                  <div className="flex items-start gap-2">
                    <StatusIcon status={f.status} />
                    <div className="min-w-0 flex-1">
                      <p
                        className={cn(
                          "text-sm",
                          f.status === "error"
                            ? "text-destructive"
                            : f.status === "warn"
                              ? "text-amber-400"
                              : "",
                        )}
                      >
                        {f.message}
                      </p>
                      {f.fix && f.status !== "ok" && (
                        <p className="mt-0.5 text-xs text-muted-foreground">
                          修复：{f.fix}
                        </p>
                      )}
                    </div>
                  </div>
                </div>
              ))}
            </div>
            <p
              className={cn(
                "text-sm",
                errCount > 0 ? "text-destructive" : "text-muted-foreground",
              )}
            >
              {findings.length} 项检查，{errCount} 项错误
            </p>
          </>
        )}

        {error && <p className="text-sm text-destructive">{error}</p>}

        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            关闭
          </Button>
          {findings !== null && !running && (
            <Button variant="outline" onClick={run}>
              <Wrench className="h-4 w-4" /> 重新诊断
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
