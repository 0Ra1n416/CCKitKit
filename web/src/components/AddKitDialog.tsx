import { useEffect, useRef, useState } from "react"
import {
  Check,
  CircleNotch,
  ShieldWarning,
  Warning,
  X,
} from "@phosphor-icons/react"
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
import {
  api,
  type AltCheckResult,
  type AltProgressEvent,
  type LintMsg,
  type Plan,
} from "@/lib/api"
import { useSSE } from "@/hooks/useSSE"
import type { ActiveScope } from "./AppSidebar"

interface PreviewResult {
  preview_id: string
  kit_name: string
  plan: Plan
  lint_msgs: LintMsg[]
  project_warns: string[]
}

type Step = "form" | "plan" | "running" | "done" | "error" | "alt"

const ALT_STAGES: AltProgressEvent["stage"][] = ["prepare", "builder", "audit"]
const STAGE_LABEL: Record<AltProgressEvent["stage"], string> = {
  prepare: "准备仓库",
  builder: "改造仓库",
  audit: "审计结果",
}

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

function StageLog({ events }: { events: AltProgressEvent[] }) {
  const ref = useRef<HTMLDivElement>(null)
  const [stick, setStick] = useState(true)
  const timerRef = useRef<number | null>(null)

  // 新事件到来(数量增长)且处于「贴底」状态时,滚到最底部。
  useEffect(() => {
    if (stick) {
      ref.current?.scrollTo({ top: ref.current.scrollHeight })
    }
  }, [events.length, stick])

  useEffect(
    () => () => {
      if (timerRef.current) window.clearTimeout(timerRef.current)
    },
    [],
  )

  const onScroll = () => {
    const el = ref.current
    if (!el) return
    if (timerRef.current) {
      window.clearTimeout(timerRef.current)
      timerRef.current = null
    }
    // 距底部 4px 内视为贴底；否则视为用户往上滚，暂停自动贴底。
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 4
    if (atBottom) {
      setStick(true)
    } else {
      setStick(false)
      // 一段时间不操作后恢复自动贴底。
      timerRef.current = window.setTimeout(() => setStick(true), 3000)
    }
  }

  return (
    <div
      ref={ref}
      onScroll={onScroll}
      className="mt-1.5 min-h-0 flex-1 space-y-0.5 overflow-y-auto pl-6 font-mono text-xs text-muted-foreground"
    >
      {events.map((e, j) => (
        <p key={j} className="break-all">
          {e.kind === "tool" ? <span className="text-primary">▸ </span> : "· "}
          {e.message}
        </p>
      ))}
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

  // alt:非标准仓库导入
  const [alt, setAlt] = useState(false)
  const [altChecking, setAltChecking] = useState(false)
  const [altCheck, setAltCheck] = useState<AltCheckResult | null>(null)
  const [altEvents, setAltEvents] = useState<AltProgressEvent[]>([])
  const [altSessionId, setAltSessionId] = useState<string | null>(null)
  const [altAllDone, setAltAllDone] = useState(false)
  const [altError, setAltError] = useState("")

  const runSSE = useSSE()
  const logRef = useRef<HTMLDivElement>(null)

  const scopeLabel =
    active.scope === "global"
      ? "全局"
      : `项目 ${active.root?.split(/[\\/]/).filter(Boolean).pop() ?? ""}`

  useEffect(() => {
    logRef.current?.scrollTo({ top: logRef.current.scrollHeight })
  }, [logs, altEvents])

  const reset = () => {
    setStep("form")
    setSource("")
    setLocal(false)
    setRef("")
    setPreview(null)
    setLogs([])
    setError("")
    setBusy(false)
    setAlt(false)
    setAltChecking(false)
    setAltCheck(null)
    setAltEvents([])
    setAltSessionId(null)
    setAltAllDone(false)
    setAltError("")
  }

  // 关闭并重置:按钮关闭与 Radix 关闭(X/点外部/Esc)都走这里,避免下次打开残留上次的
  // step/source/日志状态(尤其「安装完成」屏)。
  const close = () => {
    reset()
    onOpenChange(false)
  }

  // ---- alt 前置条件检查 ----
  const toggleAlt = async (next: boolean) => {
    if (!next) {
      setAlt(false)
      setAltCheck(null)
      return
    }
    setAltChecking(true)
    setAltCheck(null)
    try {
      const res = await api.altCheck()
      if (res.status === "ready") {
        setAlt(true)
      } else {
        setAlt(false)
        setAltCheck(res)
      }
    } catch (e) {
      setAlt(false)
      setError((e as Error).message)
    } finally {
      setAltChecking(false)
    }
  }

  const applyAltFix = async () => {
    if (!altCheck?.auto_fix) return
    setAltChecking(true)
    setError("")
    try {
      await api.altFix(altCheck.auto_fix)
      await toggleAlt(true)
    } catch (e) {
      setError((e as Error).message)
      setAltChecking(false)
    }
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
        alt,
      })
      if (r.non_standard && alt) {
        startAlt()
      } else {
        setPreview(r)
        setStep("plan")
      }
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  // ---- alt 三阶段转换 ----
  const startAlt = async () => {
    setStep("alt")
    setAltEvents([])
    setAltSessionId(null)
    setAltAllDone(false)
    setAltError("")
    try {
      await runSSE(
        await api.altStart({
          source,
          ref: ref.trim() || undefined,
          local,
          project: active.scope === "project",
          root: active.scope === "project" ? active.root : undefined,
        }),
        {
          onAltProgress: (ev) => {
            if (ev.session_id) setAltSessionId(ev.session_id)
            setAltEvents((l) => [...l, ev])
          },
          onAltDone: (ev) => {
            setAltSessionId(ev.session_id ?? null)
            setAltAllDone(true)
          },
          onAltCancelled: () => {
            setStep("form")
            setAltEvents([])
          },
          onAltError: (msg) => {
            setAltError(msg)
          },
        },
      )
    } catch (e) {
      setAltError((e as Error).message)
    }
  }

  const cancelAlt = async () => {
    if (altSessionId) {
      try {
        await api.altCancel(altSessionId)
      } catch {
        /* 忽略取消请求本身的错误 */
      }
    }
    setStep("form")
    setAltEvents([])
    setAltSessionId(null)
    setAltAllDone(false)
  }

  const completeAlt = async () => {
    if (!altSessionId) return
    setBusy(true)
    setError("")
    try {
      const r = await api.altComplete(altSessionId)
      setPreview(r)
      setStep("plan")
    } catch (e) {
      setError((e as Error).message)
      setStep("alt")
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

  const stageEvents = (stage: AltProgressEvent["stage"]) =>
    altEvents.filter((e) => e.stage === stage)
  const stageDone = (stage: AltProgressEvent["stage"]) =>
    stageEvents(stage).some((e) => e.kind === "done")

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

              <label className="flex cursor-pointer items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={alt}
                  disabled={altChecking}
                  onChange={(e) => toggleAlt(e.target.checked)}
                  className="h-4 w-4 accent-primary"
                />
                允许导入非标准仓库（用 Claude Code 改造）
                {altChecking && <CircleNotch className="h-3.5 w-3.5 animate-spin" />}
              </label>

              {altCheck && !alt && (
                <div className="space-y-2 rounded-md border p-3 text-sm">
                  <p className="text-muted-foreground">
                    {altCheck.status === "missing_extra"
                      ? `需先安装 alt 额外依赖：${altCheck.reason}`
                      : altCheck.reason}
                  </p>
                  <div className="flex gap-2">
                    {altCheck.auto_fix && (
                      <Button size="sm" onClick={applyAltFix} disabled={altChecking}>
                        {altCheck.auto_fix === "install" ? "安装" : "修改"}
                      </Button>
                    )}
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => setAltCheck(null)}
                    >
                      取消
                    </Button>
                  </div>
                </div>
              )}

              {error && <p className="text-sm text-destructive">{error}</p>}
            </div>
            <DialogFooter>
              <Button variant="ghost" onClick={close}>
                取消
              </Button>
              <Button onClick={doPreview} disabled={!source.trim() || busy || altChecking}>
                {busy && <CircleNotch className="animate-spin" />} 下一步
              </Button>
            </DialogFooter>
          </>
        )}

        {step === "alt" && (
          <>
            <DialogHeader>
              <DialogTitle>导入非标准仓库</DialogTitle>
              <DialogDescription>
                改造与审计由 Claude Code 自动执行，临时目录会在流程结束后清理
              </DialogDescription>
            </DialogHeader>

            <div className="flex h-[48vh] flex-col gap-2">
              {ALT_STAGES.map((stage, i) => {
                const events = stageEvents(stage)
                const done = stageDone(stage)
                const isCurrent =
                  !done &&
                  (i === 0 || stageDone(ALT_STAGES[i - 1])) &&
                  !altError &&
                  !altAllDone
                return (
                  <div key={stage} className="flex min-h-0 flex-1 flex-col rounded-md border p-2.5">
                    <div className="flex shrink-0 items-center gap-2">
                      {done ? (
                        <Check className="h-4 w-4 text-primary" />
                      ) : isCurrent ? (
                        <CircleNotch className="h-4 w-4 animate-spin text-muted-foreground" />
                      ) : (
                        <span className="h-4 w-4" />
                      )}
                      <span className="text-sm font-medium">{STAGE_LABEL[stage]}</span>
                    </div>
                    {events.length > 0 && <StageLog events={events} />}
                  </div>
                )
              })}

              {altError && (
                <p className="shrink-0 text-sm text-destructive">{altError}</p>
              )}
            </div>

            <DialogFooter>
              <Button
                variant="destructive"
                onClick={cancelAlt}
                disabled={!altSessionId && !altAllDone && !!altError}
              >
                <X className="h-4 w-4" /> 终止
              </Button>
              <Button onClick={completeAlt} disabled={!altAllDone || busy}>
                {busy && <CircleNotch className="animate-spin" />} 完成
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
                <span className="truncate">
                  sha {preview.plan.sha?.slice(0, 8) ?? "(本地)"}
                </span>
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
              <Button onClick={close}>完成</Button>
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
              <Button onClick={close}>关闭</Button>
            </DialogFooter>
          </>
        )}
      </DialogContent>
    </Dialog>
  )
}
