import { useEffect, useRef, useState } from "react"
import { Check, CircleNotch, ShieldWarning, Warning } from "@phosphor-icons/react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { cn } from "@/lib/utils"
import { api, type LintMsg, type Plan } from "@/lib/api"
import { useSSE } from "@/hooks/useSSE"
import type { ActiveScope } from "./AppSidebar"

interface PreviewResult {
  preview_id: string
  kit_name: string
  plan: Plan
  lint_msgs: LintMsg[]
  project_warns: string[]
}

type Step = "form" | "plan" | "running" | "done" | "error"

function PlanSection({
  title,
  children,
  tone = "default",
}: {
  title: string
  children: React.ReactNode
  tone?: "default" | "warn" | "danger"
}) {
  return (
    <div className="space-y-1">
      <p
        className={cn(
          "text-xs font-medium",
          tone === "danger"
            ? "text-destructive"
            : tone === "warn"
              ? "text-amber-400"
              : "text-muted-foreground",
        )}
      >
        {title}
      </p>
      {children}
    </div>
  )
}

export function AddKitDialog({
  open,
  onOpenChange,
  active,
  onInstalled,
}: {
  open: boolean
  onOpenChange: (o: boolean) => void
  active: ActiveScope
  onInstalled: () => void
}) {
  const [step, setStep] = useState<Step>("form")
  const [source, setSource] = useState("")
  const [local, setLocal] = useState(false)
  const [ref, setRef] = useState("")
  const [preview, setPreview] = useState<PreviewResult | null>(null)
  const [logs, setLogs] = useState<string[]>([])
  const [error, setError] = useState("")
  const [busy, setBusy] = useState(false)
  const runSSE = useSSE()
  const logRef = useRef<HTMLDivElement>(null)

  const scopeLabel =
    active.scope === "global"
      ? "全局"
      : `项目 ${active.root?.split(/[\\/]/).filter(Boolean).pop() ?? ""}`

  useEffect(() => {
    logRef.current?.scrollTo({ top: logRef.current.scrollHeight })
  }, [logs])

  const reset = () => {
    setStep("form")
    setSource("")
    setLocal(false)
    setRef("")
    setPreview(null)
    setLogs([])
    setError("")
    setBusy(false)
  }

  const doPreview = async () => {
    setBusy(true)
    setError("")
    try {
      const r = await api.addPreview({
        source,
        ref: ref.trim() || undefined,
        local,
        project: active.scope === "project",
        root: active.scope === "project" ? active.root : undefined,
      })
      setPreview(r)
      setStep("plan")
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const doExecute = async () => {
    if (!preview) return
    setStep("running")
    setLogs([])
    setError("")
    try {
      await runSSE(await api.addExecute(preview.preview_id, false), {
        onProgress: (ev) => setLogs((l) => [...l, ev.message ?? ""]),
        onDone: () => {
          setStep("done")
          onInstalled()
        },
        onError: (msg) => {
          setError(msg)
          setStep("error")
        },
      })
    } catch (e) {
      setError((e as Error).message)
      setStep("error")
    }
  }

  const cancelPlan = () => {
    if (preview) api.cancelPreview(preview.preview_id).catch(() => {})
    setPreview(null)
    setStep("form")
  }

  const hasLintError = (preview?.lint_msgs ?? []).some((m) => m.level === "error")

  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        if (!o) reset()
        onOpenChange(o)
      }}
    >
      <DialogContent className="max-w-xl">
        {step === "form" && (
          <>
            <DialogHeader>
              <DialogTitle>添加 Kit</DialogTitle>
              <DialogDescription>安装到「{scopeLabel}」作用域</DialogDescription>
            </DialogHeader>
            <div className="space-y-3">
              <div className="inline-flex rounded-md border p-0.5">
                <button
                  onClick={() => setLocal(false)}
                  className={cn(
                    "rounded px-2.5 py-1 text-xs transition-colors",
                    !local ? "bg-accent text-accent-foreground" : "text-muted-foreground",
                  )}
                >
                  仓库地址
                </button>
                <button
                  onClick={() => setLocal(true)}
                  className={cn(
                    "rounded px-2.5 py-1 text-xs transition-colors",
                    local ? "bg-accent text-accent-foreground" : "text-muted-foreground",
                  )}
                >
                  本地路径
                </button>
              </div>
              <Input
                autoFocus
                placeholder={
                  local
                    ? "本地路径，如 ./my-kit 或 C:\\kits\\my-kit"
                    : "git 仓库地址，如 https://github.com/you/video-toolkit"
                }
                value={source}
                onChange={(e) => setSource(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && source.trim() && doPreview()}
              />
              {!local && (
                <Input
                  placeholder="分支 / tag / commit（可选）"
                  value={ref}
                  onChange={(e) => setRef(e.target.value)}
                />
              )}
              {error && <p className="text-sm text-destructive">{error}</p>}
            </div>
            <DialogFooter>
              <Button variant="ghost" onClick={() => onOpenChange(false)}>
                取消
              </Button>
              <Button onClick={doPreview} disabled={!source.trim() || busy}>
                {busy && <CircleNotch className="animate-spin" />} 下一步
              </Button>
            </DialogFooter>
          </>
        )}

        {step === "plan" && preview && (
          <>
            <DialogHeader>
              <DialogTitle>安装计划</DialogTitle>
              <DialogDescription>
                安装等于运行仓库作者代码，请确认来源可信
              </DialogDescription>
            </DialogHeader>

            <div className="max-h-[50vh] space-y-3 overflow-y-auto pr-1 text-sm">
              <div className="flex items-center gap-2 text-xs text-muted-foreground">
                <span className="font-medium text-foreground">{preview.plan.kit}</span>
                <span>{preview.plan.version}</span>
                <span className="truncate">sha {preview.plan.sha?.slice(0, 8) ?? "(本地)"}</span>
              </div>
              {preview.plan.description && (
                <p className="text-xs text-muted-foreground">{preview.plan.description}</p>
              )}

              <PlanSection title="将安装的 skill">
                <ul className="space-y-0.5">
                  {preview.plan.skills.map((s) => (
                    <li key={s.name} className="text-xs">
                      · {s.name}
                      <span className="text-muted-foreground">
                        {" "}
                        {s.needs.length ? `needs: ${s.needs.join(", ")}` : "纯 prompt"}
                      </span>
                    </li>
                  ))}
                </ul>
              </PlanSection>

              {preview.plan.python_packages.length > 0 && (
                <PlanSection title="Python 依赖">
                  <p className="text-xs text-muted-foreground">
                    {preview.plan.python_packages.join(", ")}
                  </p>
                </PlanSection>
              )}

              {preview.plan.node_packages.length > 0 && (
                <PlanSection title="Node 依赖">
                  <p className="text-xs text-muted-foreground">
                    {preview.plan.node_packages.join(", ")}
                  </p>
                </PlanSection>
              )}

              {preview.plan.postinstall.length > 0 && (
                <PlanSection title="postinstall" tone="warn">
                  {preview.plan.postinstall.map((p, i) => (
                    <p key={i} className="text-xs text-amber-400">
                      {p.run} (when: {p.when ?? "always"})
                    </p>
                  ))}
                </PlanSection>
              )}

              {preview.plan.system_missing.length > 0 && (
                <PlanSection title="缺失的系统依赖（不自动安装）" tone="danger">
                  {preview.plan.system_missing.map((d) => (
                    <p key={d.bin} className="text-xs text-destructive">
                      {d.bin} {d.hint ? `→ ${d.hint}` : ""}
                    </p>
                  ))}
                </PlanSection>
              )}

              {preview.lint_msgs.length > 0 && (
                <PlanSection title="lint" tone={hasLintError ? "danger" : "warn"}>
                  {preview.lint_msgs.map((m, i) => (
                    <p
                      key={i}
                      className={cn(
                        "text-xs",
                        m.level === "error" ? "text-destructive" : "text-amber-400",
                      )}
                    >
                      [{m.level}] {m.message}
                    </p>
                  ))}
                </PlanSection>
              )}
            </div>

            <DialogFooter>
              <Button variant="ghost" onClick={cancelPlan}>
                返回
              </Button>
              <Button
                onClick={doExecute}
                disabled={hasLintError}
                className={cn(hasLintError && "opacity-50")}
              >
                <ShieldWarning className="h-4 w-4" /> 确认安装
              </Button>
            </DialogFooter>
          </>
        )}

        {step === "running" && (
          <>
            <DialogHeader>
              <DialogTitle>正在安装…</DialogTitle>
              <DialogDescription>{preview?.kit_name}</DialogDescription>
            </DialogHeader>
            <div
              ref={logRef}
              className="h-56 space-y-1 overflow-y-auto rounded-md border bg-muted/40 p-3 font-mono text-xs"
            >
              {logs.length === 0 && (
                <p className="text-muted-foreground">等待命令输出…</p>
              )}
              {logs.map((l, i) => (
                <p key={i} className="text-muted-foreground">
                  <span className="text-primary">▸</span> {l}
                </p>
              ))}
            </div>
          </>
        )}

        {step === "done" && (
          <>
            <DialogHeader>
              <DialogTitle className="flex items-center gap-2">
                <Check className="h-5 w-5 text-primary" /> 安装完成
              </DialogTitle>
              <DialogDescription>开关改动将在新会话生效</DialogDescription>
            </DialogHeader>
            <DialogFooter>
              <Button onClick={() => onOpenChange(false)}>完成</Button>
            </DialogFooter>
          </>
        )}

        {step === "error" && (
          <>
            <DialogHeader>
              <DialogTitle className="flex items-center gap-2 text-destructive">
                <Warning className="h-5 w-5" /> 安装失败
              </DialogTitle>
            </DialogHeader>
            <p className="text-sm text-muted-foreground">{error}</p>
            <DialogFooter>
              <Button onClick={() => onOpenChange(false)}>关闭</Button>
            </DialogFooter>
          </>
        )}
      </DialogContent>
    </Dialog>
  )
}
