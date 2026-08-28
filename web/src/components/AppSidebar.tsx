import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuAction,
  SidebarMenuButton,
  SidebarMenuItem,
} from "@/components/ui/sidebar"
import { Badge } from "@/components/ui/badge"
import { Progress } from "@/components/ui/progress"
import {
  ArrowsClockwise,
  Folder,
  FolderPlus,
  Globe,
  Plus,
  Stethoscope,
  X,
} from "@phosphor-icons/react"
import { cn } from "@/lib/utils"
import type { Budget, ScopeEntry } from "@/lib/api"

export interface ActiveScope {
  scope: "global" | "project"
  root?: string
}

function labelOf(s: ScopeEntry): string {
  if (s.path === "global") return "全局"
  return s.path.split(/[\\/]/).filter(Boolean).pop() || s.path
}

export function AppSidebar({
  scopes,
  active,
  onSelect,
  onAddScope,
  onRemoveScope,
  onAddKit,
  onDoctor,
  onRefresh,
  refreshing,
  budget,
}: {
  scopes: ScopeEntry[]
  active: ActiveScope
  onSelect: (s: ActiveScope) => void
  onAddScope: () => void
  onRemoveScope: (path: string) => void
  onAddKit: () => void
  onDoctor: () => void
  onRefresh: () => void
  refreshing: boolean
  budget: Budget
}) {
  const { used, limit } = budget
  const pct = limit > 0 ? (used / limit) * 100 : 0
  const over = used > limit

  return (
    <Sidebar collapsible="icon" variant="inset">
      <SidebarHeader>
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton size="lg" tooltip="CCKitKit">
              <svg viewBox="0 0 20 20" className="size-5 shrink-0">
                <rect
                  width="20"
                  height="20"
                  rx="5"
                  fill="var(--primary)"
                  fillOpacity="0.15"
                />
                <circle cx="10" cy="10" r="3.5" fill="var(--primary)" />
              </svg>
              <span className="truncate">CCKitKit</span>
              <Badge variant="outline" className="ml-auto text-[11px] font-normal">
                v0.2.0
              </Badge>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarHeader>

      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupLabel>作用域</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              {scopes.map((s) => {
                const isActive =
                  s.path === "global"
                    ? active.scope === "global"
                    : active.scope === "project" && active.root === s.path
                return (
                  <SidebarMenuItem key={s.path}>
                    <SidebarMenuButton
                      isActive={isActive}
                      tooltip={s.path === "global" ? "全局" : s.path}
                      onClick={() =>
                        onSelect(
                          s.path === "global"
                            ? { scope: "global" }
                            : { scope: "project", root: s.path },
                        )
                      }
                    >
                      {s.path === "global" ? <Globe /> : <Folder />}
                      <span>{labelOf(s)}</span>
                    </SidebarMenuButton>
                    {s.source === "watched" && (
                      <SidebarMenuAction
                        onClick={() => onRemoveScope(s.path)}
                        showOnHover
                        aria-label="取消关注"
                        title="取消关注"
                      >
                        <X />
                      </SidebarMenuAction>
                    )}
                  </SidebarMenuItem>
                )
              })}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>

        <SidebarGroup>
          <SidebarGroupLabel>项目</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              <SidebarMenuItem>
                <SidebarMenuButton onClick={onAddScope} tooltip="添加关注项目">
                  <FolderPlus />
                  <span>添加关注项目</span>
                </SidebarMenuButton>
              </SidebarMenuItem>
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>

        <SidebarGroup>
          <SidebarGroupLabel>Kit 管理</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              <SidebarMenuItem>
                <SidebarMenuButton onClick={onAddKit} tooltip="添加 Kit">
                  <Plus />
                  <span>添加 Kit</span>
                </SidebarMenuButton>
              </SidebarMenuItem>
              <SidebarMenuItem>
                <SidebarMenuButton onClick={onDoctor} tooltip="诊断">
                  <Stethoscope />
                  <span>诊断</span>
                </SidebarMenuButton>
              </SidebarMenuItem>
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>

        <SidebarGroup>
          <SidebarGroupLabel>工具</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              <SidebarMenuItem>
                <SidebarMenuButton onClick={onRefresh} tooltip="刷新">
                  <ArrowsClockwise className={refreshing ? "animate-spin" : ""} />
                  <span>刷新</span>
                </SidebarMenuButton>
              </SidebarMenuItem>
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>

      <SidebarFooter>
        <div className="px-2 py-1 group-data-[collapsible=icon]:hidden">
          <div className="flex items-center justify-between px-1 text-xs text-muted-foreground">
            <span>清单预算</span>
            <span className={cn("tabular-nums", over && "text-destructive")}>
              {used.toLocaleString()} / {limit.toLocaleString()}
            </span>
          </div>
          <Progress value={Math.min(100, pct)} className="mt-2" />
        </div>
        <div className="hidden items-center justify-center py-2 group-data-[collapsible=icon]:flex">
          <div className="relative size-9">
            <svg viewBox="0 0 36 36" className="size-full -rotate-90">
              <circle
                cx="18"
                cy="18"
                r="15.915"
                fill="none"
                stroke="var(--muted)"
                strokeWidth="3"
              />
              <circle
                cx="18"
                cy="18"
                r="15.915"
                fill="none"
                stroke={over ? "var(--destructive)" : "var(--primary)"}
                strokeWidth="3"
                strokeLinecap="round"
                strokeDasharray={`${Math.min(100, pct)} 100`}
              />
            </svg>
            <span className="absolute inset-0 flex items-center justify-center text-[9px] tabular-nums">
              {Math.round(pct)}
            </span>
          </div>
        </div>
      </SidebarFooter>
    </Sidebar>
  )
}
