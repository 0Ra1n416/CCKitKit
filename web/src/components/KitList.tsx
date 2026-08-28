import { useState } from "react"
import {
  AlertTriangle,
  Check,
  ChevronDown,
  ChevronRight,
  Trash2,
} from "lucide-react"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"
import type { SkillItem, SkillState } from "@/lib/api"

const STATE_META: Record<
  SkillState,
  { label: string; dot: string; desc: string }
> = {
  installed: {
    label: "已安装",
    dot: "bg-muted-foreground/40",
    desc: "未建链接，CC 看不到",
  },
  enabled: {
    label: "已启用",
    dot: "bg-primary",
    desc: "CC 可见名字 + description",
  },
  "name-only": {
    label: "仅名字",
    dot: "bg-sky-500",
    desc: "CC 只能读到名字，省预算",
  },
  off: {
    label: "已关闭",
    dot: "bg-muted-foreground/60",
    desc: "有链接但被覆盖，CC 看不到",
  },
}

function StateSelect({
  skill,
  onChange,
}: {
  skill: SkillItem
  onChange: (state: SkillState) => void
}) {
  const meta = STATE_META[skill.state]
  const trigger = (
    <button
      disabled={!skill.managed}
      className={cn(
        "flex items-center gap-1.5 rounded-md border px-2 py-1 text-xs transition-colors",
        skill.managed ? "hover:bg-accent" : "cursor-not-allowed opacity-50",
      )}
    >
      <span className={cn("h-2 w-2 rounded-full", meta.dot)} />
      {meta.label}
      {skill.managed && <ChevronDown className="h-3 w-3 opacity-50" />}
    </button>
  )

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        {skill.state === "name-only" ? (
          <Tooltip>
            <TooltipTrigger asChild>{trigger}</TooltipTrigger>
            <TooltipContent side="left">{meta.desc}</TooltipContent>
          </Tooltip>
        ) : (
          trigger
        )}
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuLabel>切换状态（新会话生效）</DropdownMenuLabel>
        {(Object.keys(STATE_META) as SkillState[]).map((st) => (
          <DropdownMenuItem
            key={st}
            onClick={() => onChange(st)}
            className="justify-between gap-6"
          >
            <span className="flex items-center gap-2">
              <span className={cn("h-2 w-2 rounded-full", STATE_META[st].dot)} />
              {STATE_META[st].label}
            </span>
            {skill.state === st ? (
              <Check className="h-4 w-4 text-primary" />
            ) : (
              <span className="text-[10px] text-muted-foreground">
                {STATE_META[st].desc}
              </span>
            )}
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

function SkillRow({
  skill,
  onChange,
}: {
  skill: SkillItem
  onChange: (state: SkillState) => void
}) {
  return (
    <div className="flex items-center justify-between gap-3 px-4 py-2 transition-colors hover:bg-accent/40">
      <div className="flex min-w-0 items-center gap-2">
        <span className="truncate text-sm">{skill.name}</span>
        {!skill.managed && (
          <span className="shrink-0 rounded border px-1 text-[10px] text-muted-foreground">
            只读
          </span>
        )}
        {skill.managed && skill.env_ok === false && (
          <Tooltip>
            <TooltipTrigger asChild>
              <AlertTriangle className="h-3.5 w-3.5 shrink-0 text-destructive" />
            </TooltipTrigger>
            <TooltipContent side="right">
              环境缺失或损坏，请在「诊断」中修复
            </TooltipContent>
          </Tooltip>
        )}
      </div>
      <StateSelect skill={skill} onChange={onChange} />
    </div>
  )
}

function KitItem({
  kit,
  version,
  skills,
  onRemove,
  onChange,
}: {
  kit: string
  version: string | null
  skills: SkillItem[]
  onRemove: () => void
  onChange: (skill: SkillItem, state: SkillState) => void
}) {
  const [open, setOpen] = useState(true)
  return (
    <div className="overflow-hidden rounded-lg border bg-card">
      <div className="flex items-center justify-between px-3 py-2">
        <button
          onClick={() => setOpen((o) => !o)}
          className="flex min-w-0 items-center gap-1.5 text-left"
        >
          {open ? (
            <ChevronDown className="h-4 w-4 shrink-0 text-muted-foreground" />
          ) : (
            <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground" />
          )}
          <span className="truncate font-medium">{kit}</span>
          {version && (
            <span className="shrink-0 text-xs text-muted-foreground">{version}</span>
          )}
        </button>
        <Button
          variant="ghost"
          size="sm"
          onClick={onRemove}
          className="h-7 text-xs text-muted-foreground hover:text-destructive"
        >
          <Trash2 className="h-3.5 w-3.5" /> 卸载
        </Button>
      </div>
      {open && (
        <div className="divide-y border-t">
          {skills.map((s) => (
            <SkillRow
              key={s.name}
              skill={s}
              onChange={(state) => onChange(s, state)}
            />
          ))}
        </div>
      )}
    </div>
  )
}

export function KitList({
  skills,
  onChange,
  onRemove,
}: {
  skills: SkillItem[]
  onChange: (skill: SkillItem, state: SkillState) => void
  onRemove: (kit: string) => void
}) {
  const groups = new Map<string, SkillItem[]>()
  for (const s of skills) {
    const key = s.kit ?? "__unmanaged__"
    if (!groups.has(key)) groups.set(key, [])
    groups.get(key)!.push(s)
  }

  const managedKits = [...groups.entries()].filter(([k]) => k !== "__unmanaged__")
  const unmanaged = groups.get("__unmanaged__") ?? []

  if (skills.length === 0) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-2 text-muted-foreground">
        <p className="text-sm">该作用域暂无 skill</p>
        <p className="text-xs">点击右上角「添加 Kit」开始，或切换到其他作用域</p>
      </div>
    )
  }

  return (
    <div className="space-y-3">
      {managedKits.map(([kit, list]) => (
        <KitItem
          key={kit}
          kit={kit}
          version={list[0]?.version ?? null}
          skills={list}
          onRemove={() => onRemove(kit)}
          onChange={onChange}
        />
      ))}

      {unmanaged.length > 0 && (
        <div className="overflow-hidden rounded-lg border border-dashed bg-card/50">
          <div className="px-3 py-2 text-xs font-medium text-muted-foreground">
            非 cckit 管理（用户手写 / 插件，只读）
          </div>
          <div className="divide-y border-t">
            {unmanaged.map((s) => (
              <SkillRow key={s.name} skill={s} onChange={() => {}} />
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
