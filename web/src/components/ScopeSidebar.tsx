import { useState } from "react"
import { Check, Folder, FolderPlus, Globe, X } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import { cn } from "@/lib/utils"
import type { ScopeEntry } from "@/lib/api"

export interface ActiveScope {
  scope: "global" | "project"
  root?: string
}

function labelOf(s: ScopeEntry): string {
  if (s.path === "global") return "全局"
  return s.path.split(/[\\/]/).filter(Boolean).pop() || s.path
}

export function ScopeSidebar({
  scopes,
  active,
  onSelect,
  onAdd,
}: {
  scopes: ScopeEntry[]
  active: ActiveScope
  onSelect: (s: ActiveScope) => void
  onAdd: (path: string) => void
}) {
  const [adding, setAdding] = useState(false)
  const [path, setPath] = useState("")

  const confirm = () => {
    if (!path.trim()) return
    onAdd(path.trim())
    setPath("")
    setAdding(false)
  }

  return (
    <aside className="flex w-56 shrink-0 flex-col border-r bg-card">
      <div className="flex-1 overflow-y-auto p-2">
        <p className="px-2 py-1.5 text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
          作用域
        </p>
        {scopes.map((s) => {
          const isActive =
            s.path === "global"
              ? active.scope === "global"
              : active.scope === "project" && active.root === s.path
          return (
            <Tooltip key={s.path}>
              <TooltipTrigger asChild>
                <button
                  onClick={() =>
                    onSelect(
                      s.path === "global"
                        ? { scope: "global" }
                        : { scope: "project", root: s.path },
                    )
                  }
                  className={cn(
                    "flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm transition-colors",
                    isActive
                      ? "bg-accent text-accent-foreground"
                      : "text-muted-foreground hover:bg-accent/50",
                  )}
                >
                  {s.path === "global" ? (
                    <Globe className="h-4 w-4 shrink-0" />
                  ) : (
                    <Folder className="h-4 w-4 shrink-0" />
                  )}
                  <span className="flex-1 truncate">{labelOf(s)}</span>
                  {s.source === "watched" && (
                    <span className="text-[10px] text-muted-foreground">关注</span>
                  )}
                  {s.has_skills && <span className="h-1.5 w-1.5 rounded-full bg-primary/70" />}
                </button>
              </TooltipTrigger>
              {s.path !== "global" && (
                <TooltipContent side="right">{s.path}</TooltipContent>
              )}
            </Tooltip>
          )
        })}
      </div>

      <div className="border-t p-2">
        {adding ? (
          <div className="space-y-2">
            <Input
              autoFocus
              placeholder="项目绝对路径"
              value={path}
              onChange={(e) => setPath(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") confirm()
                if (e.key === "Escape") {
                  setAdding(false)
                  setPath("")
                }
              }}
            />
            <div className="flex justify-end gap-1">
              <Button
                size="sm"
                variant="ghost"
                onClick={() => {
                  setAdding(false)
                  setPath("")
                }}
              >
                <X className="h-3 w-3" /> 取消
              </Button>
              <Button size="sm" disabled={!path.trim()} onClick={confirm}>
                <Check className="h-3 w-3" /> 添加
              </Button>
            </div>
          </div>
        ) : (
          <Button
            variant="ghost"
            size="sm"
            className="w-full justify-start text-muted-foreground"
            onClick={() => setAdding(true)}
          >
            <FolderPlus className="h-4 w-4" /> 关注项目
          </Button>
        )}
      </div>
    </aside>
  )
}
