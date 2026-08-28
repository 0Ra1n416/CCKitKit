import { Plus, RefreshCw, Stethoscope } from "lucide-react"
import { Button } from "@/components/ui/button"

export function Topbar({
  onRefresh,
  onAdd,
  onDoctor,
  refreshing,
}: {
  onRefresh: () => void
  onAdd: () => void
  onDoctor: () => void
  refreshing: boolean
}) {
  return (
    <header className="flex h-12 shrink-0 items-center justify-between border-b bg-card px-4">
      <div className="flex items-center gap-2.5">
        <div className="flex h-6 w-6 items-center justify-center rounded-md bg-primary/15">
          <div className="h-2 w-2 rounded-full bg-primary" />
        </div>
        <span className="text-sm font-semibold tracking-tight">CCKitKit</span>
        <span className="rounded-full border px-1.5 py-0.5 text-[10px] text-muted-foreground">
          v0.2.0
        </span>
      </div>
      <div className="flex items-center gap-1.5">
        <Button variant="ghost" size="sm" onClick={onRefresh} disabled={refreshing}>
          <RefreshCw className={refreshing ? "animate-spin" : ""} />
          刷新
        </Button>
        <Button size="sm" onClick={onAdd}>
          <Plus />
          添加 Kit
        </Button>
        <Button variant="outline" size="sm" onClick={onDoctor}>
          <Stethoscope />
          诊断
        </Button>
      </div>
    </header>
  )
}
