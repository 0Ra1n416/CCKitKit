import { cn } from "@/lib/utils"
import type { Budget } from "@/lib/api"

export function BudgetBar({ budget }: { budget: Budget }) {
  const { used, limit } = budget
  const pct = limit > 0 ? Math.min(100, (used / limit) * 100) : 0
  const over = used > limit
  return (
    <div className="border-t px-4 py-2.5 text-xs text-muted-foreground">
      <div className="mb-1.5 flex items-center justify-between">
        <span className="font-medium">清单预算</span>
        <span className={cn("tabular-nums", over && "text-destructive")}>
          {used.toLocaleString()} / {limit.toLocaleString()} 字符
          {over ? " · 超限" : ` · ${Math.round((used / Math.max(1, limit)) * 100)}%`}
        </span>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-muted">
        <div
          className={cn(
            "h-full rounded-full transition-all",
            over ? "bg-destructive" : "bg-primary",
          )}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  )
}
