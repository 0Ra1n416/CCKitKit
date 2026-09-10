import { useEffect, useState } from "react"
import {
  Warning,
  Check,
  CaretDown,
  CaretRight,
  GearSix,
  Key,
  Trash,
} from "@phosphor-icons/react"
import { toast } from "sonner"
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
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import {
  Popover,
  PopoverContent,
  PopoverDescription,
  PopoverHeader,
  PopoverTitle,
  PopoverTrigger,
} from "@/components/ui/popover"
import { cn } from "@/lib/utils"
import { api, type EnvRequirement, type Scope, type SkillItem, type SkillState } from "@/lib/api"

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

/** 配置读写的作用域上下文（项目作用域才需要 root） */
type ConfigCtx = { scope: Scope; root?: string }

/**
 * 「必需的环境变量还没填」的提醒图标。
 *
 * 只是提醒不是报错 —— 点右侧齿轮就能填，所以用琥珀色而非红色，
 * 与 `env_ok === false`（运行环境坏了，得去「诊断」修）区分开。
 */
function MissingEnvIcon({ names }: { names: string[] }) {
  if (names.length === 0) return null
  return (
    <Tooltip>
      <TooltipTrigger
        render={<Key className="h-3.5 w-3.5 shrink-0 text-amber-400" />}
      />
      <TooltipContent side="right">
        缺少必需的环境变量：{names.join("、")}。点右侧齿轮填写
      </TooltipContent>
    </Tooltip>
  )
}

/** 改一个环境变量的值：输入框 + 取消 / 保存。留空 = 不注入该变量。 */
function EnvEditDialog({
  kit,
  skill,
  env,
  ctx,
  onOpenChange,
  onSaved,
}: {
  kit: string
  skill: string | null
  env: EnvRequirement
  ctx: ConfigCtx
  onOpenChange: (o: boolean) => void
  onSaved: () => void
}) {
  const [value, setValue] = useState(env.value ?? "")
  const [saving, setSaving] = useState(false)

  const save = () => {
    setSaving(true)
    api
      .setEnv({
        kit,
        name: env.name,
        value,
        skill,
        scope: ctx.scope,
        root: ctx.root,
      })
      .then(() => {
        toast.success(`${env.name} 已保存`)
        onSaved()
        onOpenChange(false)
      })
      .catch((e) => toast.error((e as Error).message))
      .finally(() => setSaving(false))
  }

  return (
    <Dialog open onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>{env.name}</DialogTitle>
          <DialogDescription>
            {env.description || "该 skill 需要的环境变量"}
            {env.required && "（必需）"}
          </DialogDescription>
        </DialogHeader>
        <Input
          autoFocus
          value={value}
          placeholder="留空则不注入这个变量"
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && save()}
        />
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            取消
          </Button>
          <Button disabled={saving} onClick={save}>
            保存
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

/** 预览 / 修改一个配置文件：内容在打开时按需拉取，保存走原子写。 */
function ConfEditDialog({
  kit,
  skill,
  path,
  ctx,
  onOpenChange,
}: {
  kit: string
  skill: string
  path: string
  ctx: ConfigCtx
  onOpenChange: (o: boolean) => void
}) {
  const [content, setContent] = useState<string | null>(null)
  const [error, setError] = useState("")
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    let alive = true
    api
      .readConf(ctx.scope, kit, skill, path, ctx.root)
      .then((v) => alive && setContent(v.content))
      .catch((e) => alive && setError((e as Error).message))
    return () => {
      alive = false
    }
  }, [kit, skill, path, ctx.scope, ctx.root])

  const save = () => {
    if (content === null) return
    setSaving(true)
    api
      .writeConf({
        kit,
        skill,
        path,
        content,
        scope: ctx.scope,
        root: ctx.root,
      })
      .then(() => {
        toast.success(`${path} 已保存`)
        onOpenChange(false)
      })
      .catch((e) => toast.error((e as Error).message))
      .finally(() => setSaving(false))
  }

  return (
    <Dialog open onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>{path}</DialogTitle>
          <DialogDescription>
            相对 skill 目录的配置文件，保存后立即生效
          </DialogDescription>
        </DialogHeader>
        {error ? (
          <p className="text-sm text-destructive">{error}</p>
        ) : (
          <Textarea
            autoFocus
            className="max-h-[50vh] min-h-64 overflow-y-auto font-mono text-xs"
            value={content ?? ""}
            disabled={content === null}
            onChange={(e) => setContent(e.target.value)}
          />
        )}
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            取消
          </Button>
          <Button disabled={saving || content === null || !!error} onClick={save}>
            保存
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

/**
 * 配置管理入口（齿轮图标 + 下拉）。
 *
 * skill 传 null 表示 kit 级：只列 kit_env，没有 conf_files。
 * 值在展开时才去取 —— 可能在别处改过，缓存会给出过期的默认值。
 */
function ConfigMenu({
  kit,
  skill,
  title,
  disabled,
  ctx,
  onSaved,
}: {
  kit: string
  skill: string | null
  title: string
  disabled?: boolean
  ctx: ConfigCtx
  onSaved: () => void
}) {
  const [open, setOpen] = useState(false)
  const [envs, setEnvs] = useState<EnvRequirement[]>([])
  const [confs, setConfs] = useState<string[]>([])
  const [editingEnv, setEditingEnv] = useState<EnvRequirement | null>(null)
  const [editingConf, setEditingConf] = useState<string | null>(null)

  const handleOpen = (next: boolean) => {
    setOpen(next)
    if (!next) return
    api
      .config(ctx.scope, kit, skill, ctx.root)
      .then((v) => {
        setEnvs(v.envs)
        setConfs(v.conf_files)
      })
      .catch(() => {
        setEnvs([])
        setConfs([])
      })
  }

  return (
    <>
      <DropdownMenu open={open} onOpenChange={handleOpen}>
        <DropdownMenuTrigger
          render={
            <button
              type="button"
              disabled={disabled}
              title="配置"
              aria-label="配置"
              className={cn(
                "flex h-7 w-7 items-center justify-center rounded-lg border text-muted-foreground transition-colors",
                disabled
                  ? "cursor-not-allowed opacity-40"
                  : "hover:bg-accent hover:text-foreground",
              )}
            >
              <GearSix className="h-3.5 w-3.5" />
            </button>
          }
        />
        <DropdownMenuContent
          align="end"
          className="min-w-[max(var(--anchor-width),22rem)] max-w-[28rem]"
        >
          {/* Label 必须包在 Group 里:base-ui 的 MenuGroupLabel 在 Group 之外会直接抛错 */}
          <DropdownMenuGroup>
            <DropdownMenuLabel>{title}</DropdownMenuLabel>
          </DropdownMenuGroup>

          <DropdownMenuGroup>
            <DropdownMenuLabel className="text-[11px]">环境变量</DropdownMenuLabel>
            {envs.length === 0 ? (
              <div className="px-2 py-1.5 text-xs text-muted-foreground">无</div>
            ) : (
              envs.map((e) => (
                <DropdownMenuItem
                  key={`${e.level}-${e.name}`}
                  onClick={() => setEditingEnv(e)}
                  className="justify-between gap-4"
                >
                  <span className="flex min-w-0 items-center gap-2">
                    <span className="truncate font-mono text-xs">{e.name}</span>
                    {e.required && (
                      <span className="shrink-0 text-[10px] text-destructive">
                        必需
                      </span>
                    )}
                  </span>
                  <span className="shrink-0 text-xs text-muted-foreground">
                    {e.value ? "已设" : "未设"}
                  </span>
                </DropdownMenuItem>
              ))
            )}
          </DropdownMenuGroup>

          {skill !== null && (
            <DropdownMenuGroup>
              <DropdownMenuLabel className="text-[11px]">
                配置文件
              </DropdownMenuLabel>
              {confs.length === 0 ? (
                <div className="px-2 py-1.5 text-xs text-muted-foreground">无</div>
              ) : (
                confs.map((p) => (
                  <DropdownMenuItem
                    key={p}
                    onClick={() => setEditingConf(p)}
                    className="font-mono text-xs"
                  >
                    <span className="truncate">{p}</span>
                  </DropdownMenuItem>
                ))
              )}
            </DropdownMenuGroup>
          )}
        </DropdownMenuContent>
      </DropdownMenu>

      {editingEnv && (
        <EnvEditDialog
          kit={kit}
          skill={skill}
          env={editingEnv}
          ctx={ctx}
          onOpenChange={(o) => !o && setEditingEnv(null)}
          onSaved={onSaved}
        />
      )}
      {editingConf && skill !== null && (
        <ConfEditDialog
          kit={kit}
          skill={skill}
          path={editingConf}
          ctx={ctx}
          onOpenChange={(o) => !o && setEditingConf(null)}
        />
      )}
    </>
  )
}

function SkillRow({
  skill,
  ctx,
  onChange,
  onRefresh,
}: {
  skill: SkillItem
  ctx: ConfigCtx
  onChange: (state: SkillState) => void
  onRefresh: () => void
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
        {skill.managed && <MissingEnvIcon names={skill.missing_env} />}
      </div>
      <div className="flex shrink-0 items-center gap-2">
        {skill.managed && skill.kit && (
          <ConfigMenu
            kit={skill.kit}
            skill={skill.name}
            title={skill.name}
            disabled={skill.state === "installed"}
            ctx={ctx}
            onSaved={onRefresh}
          />
        )}
        <StateSelect skill={skill} onChange={onChange} />
      </div>
    </div>
  )
}

function GlobalSkillsGroup({
  skills,
  ctx,
  onChange,
  onRefresh,
}: {
  skills: SkillItem[]
  ctx: ConfigCtx
  onChange: (skill: SkillItem, state: SkillState) => void
  onRefresh: () => void
}) {
  const [open, setOpen] = useState(true)
  // 这些是全局 skill 在项目作用域的视图:它们的配置值存在**全局**桶里,
  // 与当前看的是哪个作用域无关(D-15)。
  const globalCtx: ConfigCtx = { scope: "global" }
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
                {s.managed && <MissingEnvIcon names={s.missing_env} />}
              </div>
              <div className="flex shrink-0 items-center gap-2">
                {s.managed && s.kit && (
                  <ConfigMenu
                    kit={s.kit}
                    skill={s.name}
                    title={s.name}
                    disabled={s.state === "installed"}
                    ctx={globalCtx}
                    onSaved={onRefresh}
                  />
                )}
                <GlobalStateSelect
                  skill={s}
                  onChange={(state) => onChange(s, state)}
                />
              </div>
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
  ctx,
  onRefresh,
}: {
  kit: string
  version: string | null
  skills: SkillItem[]
  onRemove: () => void
  onChange: (skill: SkillItem, state: SkillState) => void
  ctx: ConfigCtx
  onRefresh: () => void
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
        <div className="flex shrink-0 items-center gap-2">
          {/* kit 级(kit_env)配置:只有环境变量,没有 conf_files */}
          <ConfigMenu
            kit={kit}
            skill={null}
            title={`${kit} 共用环境变量`}
            ctx={ctx}
            onSaved={onRefresh}
          />
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
      </div>
      {open && (
        <div className="divide-y border-t">
          {skills.map((s) => (
            <SkillRow
              key={s.name}
              skill={s}
              ctx={ctx}
              onChange={(state) => onChange(s, state)}
              onRefresh={onRefresh}
            />
          ))}
        </div>
      )}
    </Card>
  )
}

export function KitList({
  skills,
  ctx,
  onChange,
  onRemove,
  onRefresh,
}: {
  skills: SkillItem[]
  ctx: ConfigCtx
  onChange: (skill: SkillItem, state: SkillState) => void
  onRemove: (kit: string) => void
  onRefresh: () => void
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
        <GlobalSkillsGroup
          skills={globalSkills}
          ctx={ctx}
          onChange={onChange}
          onRefresh={onRefresh}
        />
      )}

      {managedKits.map(([kit, list]) => (
        <KitItem
          key={kit}
          kit={kit}
          version={list[0]?.version ?? null}
          skills={list}
          onRemove={() => onRemove(kit)}
          onChange={onChange}
          ctx={ctx}
          onRefresh={onRefresh}
        />
      ))}

      {unmanaged.length > 0 && (
        <div className="overflow-hidden rounded-lg border border-dashed bg-card/50">
          <div className="px-3 py-2 text-xs font-medium text-muted-foreground">
            非 cckit 管理（用户手写 / 插件，只读）
          </div>
          <div className="divide-y border-t">
            {unmanaged.map((s) => (
              <SkillRow
                key={s.name}
                skill={s}
                ctx={ctx}
                onChange={() => {}}
                onRefresh={onRefresh}
              />
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
