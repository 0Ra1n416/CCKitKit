import { useState } from "react"
import {
  Warning,
  Check,
  CaretDown,
  CaretRight,
  Trash,
} from "@phosphor-icons/react"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import { Card } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import {
  Popover,
  PopoverContent,
  PopoverDescription,
  PopoverHeader,
  PopoverTitle,
  PopoverTrigger,
} from "@/components/ui/popover"
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

const GLOBAL_STATE_LABEL: Record<string, string> = {
  enabled: "已启用",
  "name-only": "仅名字",
  off: "已关闭",
  installed: "已安装",
}

function StateSelect({
  skill,
  onChange,
}: {
  skill: SkillItem
  onChange: (state: SkillState) => void
}) {
  const meta = STATE_META[skill.state]

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        render={
          <button
            disabled={!skill.managed}
            className={cn(
              "flex items-center gap-1.5 rounded-lg border px-2.5 py-1 text-sm transition-colors",
              skill.managed ? "hover:bg-accent" : "cursor-not-allowed opacity-50",
            )}
          >
            <span className={cn("h-2 w-2 rounded-full", meta.dot)} />
            {meta.label}
            {skill.managed && <CaretDown className="h-3 w-3 opacity-50" />}
          </button>
        }
      />
      <DropdownMenuContent align="end" className="min-w-[max(var(--anchor-width),12rem)]">
        <DropdownMenuGroup>
          <DropdownMenuLabel>切换状态（新会话生效）</DropdownMenuLabel>
        </DropdownMenuGroup>
        {(Object.keys(STATE_META) as SkillState[]).map((st) => (
          <DropdownMenuItem
            key={st}
            onClick={() => onChange(st)}
            className="justify-between gap-3"
          >
            <span className="flex shrink-0 items-center gap-2 whitespace-nowrap">
              <span className={cn("h-2 w-2 rounded-full", STATE_META[st].dot)} />
              {STATE_META[st].label}
            </span>
            {skill.state === st ? (
              <Check className="h-4 w-4 shrink-0 text-primary" />
            ) : (
              <span className="text-[11px] leading-snug text-muted-foreground">
                {STATE_META[st].desc}
              </span>
            )}
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

function GlobalStateSelect({
  skill,
  onChange,
}: {
  skill: SkillItem
  onChange: (state: SkillState) => void
}) {
  const gs = skill.global_state ?? "installed"
  const options: { label: string; action: SkillState; desc?: string }[] = [
    { label: "跟随全局", action: "enabled", desc: "清除项目覆盖，与全局一致" },
  ]
  if (gs === "enabled") {
    options.push({ label: "仅名字", action: "name-only" })
    options.push({ label: "关闭", action: "off" })
  } else if (gs === "name-only") {
    options.push({ label: "关闭", action: "off" })
  }

  const currentLabel = skill.override
    ? STATE_META[skill.state].label
    : `跟随全局 · ${GLOBAL_STATE_LABEL[gs] ?? gs}`
  const currentDot = skill.override
    ? STATE_META[skill.state].dot
    : "bg-primary/50"

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        render={
          <button className="flex items-center gap-1.5 rounded-lg border px-2.5 py-1 text-sm transition-colors hover:bg-accent">
            <span className={cn("h-2 w-2 rounded-full", currentDot)} />
            {currentLabel}
            <CaretDown className="h-3 w-3 opacity-50" />
          </button>
        }
      />
      <DropdownMenuContent align="end" className="min-w-[max(var(--anchor-width),13rem)]">
        <DropdownMenuGroup>
          <DropdownMenuLabel>项目内覆盖（新会话生效）</DropdownMenuLabel>
        </DropdownMenuGroup>
        {options.map((opt) => {
          const active = skill.override
            ? skill.state === opt.action
            : opt.action === "enabled"
          return (
            <DropdownMenuItem
              key={opt.label}
              onClick={() => onChange(opt.action)}
              className="justify-between gap-3"
            >
              <span className="whitespace-nowrap">{opt.label}</span>
              {active ? (
                <Check className="h-4 w-4 shrink-0 text-primary" />
              ) : (
                opt.desc && (
                  <span className="text-[11px] text-muted-foreground">{opt.desc}</span>
                )
              )}
            </DropdownMenuItem>
          )
        })}
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
            <TooltipTrigger
              render={
                <Warning className="h-3.5 w-3.5 shrink-0 text-destructive" />
              }
            />
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

function GlobalSkillsGroup({
  skills,
  onChange,
}: {
  skills: SkillItem[]
  onChange: (skill: SkillItem, state: SkillState) => void
}) {
  const [open, setOpen] = useState(true)
  return (
    <Card size="sm" className="gap-0 p-0">
      <div className="flex items-center justify-between px-4 py-2.5">
        <button
          onClick={() => setOpen((o) => !o)}
          className="flex min-w-0 items-center gap-2 text-left"
        >
          {open ? (
            <CaretDown className="h-4 w-4 shrink-0 text-muted-foreground" />
          ) : (
            <CaretRight className="h-4 w-4 shrink-0 text-muted-foreground" />
          )}
          <span className="text-[15px] font-medium">全局 Skill</span>
          <span className="shrink-0 text-sm text-muted-foreground">
            {skills.length} 个
          </span>
        </button>
      </div>
      {open && (
        <div className="divide-y border-t">
          {skills.map((s) => (
            <div
              key={s.name}
              className="flex items-center justify-between gap-3 px-4 py-2 transition-colors hover:bg-accent/40"
            >
              <div className="flex min-w-0 items-center gap-2">
                <span className="truncate text-sm">{s.name}</span>
                <span className="shrink-0 rounded border px-1 text-[10px] text-muted-foreground">
                  全局
                </span>
                {s.env_ok === false && (
                  <Tooltip>
                    <TooltipTrigger
                      render={
                        <Warning className="h-3.5 w-3.5 shrink-0 text-destructive" />
                      }
                    />
                    <TooltipContent side="right">
                      环境缺失或损坏，请在「诊断」中修复
                    </TooltipContent>
                  </Tooltip>
                )}
              </div>
              <GlobalStateSelect
                skill={s}
                onChange={(state) => onChange(s, state)}
              />
            </div>
          ))}
        </div>
      )}
    </Card>
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
  const [confirmOpen, setConfirmOpen] = useState(false)
  return (
    <Card size="sm" className="gap-0 p-0">
      <div className="flex items-center justify-between px-4 py-2.5">
        <button
          onClick={() => setOpen((o) => !o)}
          className="flex min-w-0 items-center gap-2 text-left"
        >
          {open ? (
            <CaretDown className="h-4 w-4 shrink-0 text-muted-foreground" />
          ) : (
            <CaretRight className="h-4 w-4 shrink-0 text-muted-foreground" />
          )}
          <span className="truncate text-[15px] font-medium">{kit}</span>
          {version && (
            <span className="shrink-0 text-sm text-muted-foreground">{version}</span>
          )}
        </button>
        <Popover open={confirmOpen} onOpenChange={setConfirmOpen}>
          <PopoverTrigger className="inline-flex h-8 items-center gap-2 rounded-xl px-3 text-sm text-muted-foreground transition-colors hover:bg-muted hover:text-destructive">
            <Trash className="h-3.5 w-3.5" />
            卸载
          </PopoverTrigger>
          <PopoverContent align="end" className="w-64 gap-3">
            <PopoverHeader>
              <PopoverTitle>卸载 {kit}？</PopoverTitle>
              <PopoverDescription>将删除 link、环境与 store 记录</PopoverDescription>
            </PopoverHeader>
            <div className="flex justify-end gap-2">
              <Button size="sm" variant="ghost" onClick={() => setConfirmOpen(false)}>
                取消
              </Button>
              <Button
                size="sm"
                variant="destructive"
                onClick={() => {
                  onRemove()
                  setConfirmOpen(false)
                }}
              >
                确认卸载
              </Button>
            </div>
          </PopoverContent>
        </Popover>
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
    </Card>
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
  const globalSkills = skills.filter((s) => s.is_global_skill)
  const rest = skills.filter((s) => !s.is_global_skill)

  const groups = new Map<string, SkillItem[]>()
  for (const s of rest) {
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
        <p className="text-xs">点击左侧「添加 Kit」开始，或切换到其他作用域</p>
      </div>
    )
  }

  return (
    <div className="space-y-3">
      {globalSkills.length > 0 && (
        <GlobalSkillsGroup skills={globalSkills} onChange={onChange} />
      )}

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
