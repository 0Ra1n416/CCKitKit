import { useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { AppSidebar, type ActiveScope } from "@/components/AppSidebar"
import { KitList } from "@/components/KitList"
import { AddKitDialog } from "@/components/AddKitDialog"
import { DoctorDialog } from "@/components/DoctorDialog"
import { AddScopeDialog } from "@/components/AddScopeDialog"
import {
  SidebarInset,
  SidebarProvider,
  SidebarTrigger,
} from "@/components/ui/sidebar"
import { TooltipProvider } from "@/components/ui/tooltip"
import { api, type SkillItem, type SkillState } from "@/lib/api"

export default function App() {
  const qc = useQueryClient()
  const [active, setActive] = useState<ActiveScope>({ scope: "global" })
  const [addOpen, setAddOpen] = useState(false)
  const [doctorOpen, setDoctorOpen] = useState(false)
  const [addScopeOpen, setAddScopeOpen] = useState(false)

  const scopesQ = useQuery({ queryKey: ["scopes"], queryFn: api.scopes })
  const skillsQ = useQuery({
    queryKey: ["skills", active.scope, active.root],
    queryFn: () => api.skills(active.scope, active.root),
  })

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["scopes"] })
    qc.invalidateQueries({ queryKey: ["skills"] })
  }

  const setStateMut = useMutation({
    mutationFn: ({ skill, state }: { skill: SkillItem; state: SkillState }) =>
      api.setState(skill.name, state, active.scope, active.root),
    onSuccess: (data) => {
      toast.error(data.message)
      qc.invalidateQueries({ queryKey: ["skills"] })
    },
    onError: (e) => toast.error((e as Error).message),
  })

  const removeKitMut = useMutation({
    mutationFn: (kit: string) => api.removeKit(kit),
    onSuccess: () => {
      toast.success("已卸载")
      invalidate()
    },
    onError: (e) => toast.error((e as Error).message),
  })

  const addScopeMut = useMutation({
    mutationFn: (path: string) => api.addScope(path),
    onSuccess: (data, path) => {
      toast.success("已关注项目")
      qc.setQueryData(["scopes"], data)
      setActive({ scope: "project", root: path })
    },
    onError: (e) => toast.error((e as Error).message),
  })

  const removeScopeMut = useMutation({
    mutationFn: (path: string) => api.removeScope(path),
    onSuccess: (data, path) => {
      toast.success("已取消关注")
      qc.setQueryData(["scopes"], data)
      if (active.scope === "project" && active.root === path) {
        setActive({ scope: "global" })
      }
    },
    onError: (e) => toast.error((e as Error).message),
  })

  const handleRemove = (kit: string) => {
    removeKitMut.mutate(kit)
  }

  const skills = skillsQ.data?.skills ?? []
  const budget = skillsQ.data?.budget ?? { used: 0, limit: 0 }
  const scopes = scopesQ.data?.scopes ?? []
  const refreshing = skillsQ.isFetching || scopesQ.isFetching

  return (
    <TooltipProvider delay={200}>
      <SidebarProvider>
        <AppSidebar
          scopes={scopes}
          active={active}
          onSelect={setActive}
          onAddScope={() => setAddScopeOpen(true)}
          onRemoveScope={(p) => removeScopeMut.mutate(p)}
          onAddKit={() => setAddOpen(true)}
          onDoctor={() => setDoctorOpen(true)}
          onRefresh={invalidate}
          refreshing={refreshing}
          budget={budget}
        />
        <SidebarInset>
          <header className="flex h-12 shrink-0 items-center gap-2 border-b px-4">
            <SidebarTrigger />
            <span className="text-sm font-medium">Skills</span>
          </header>
          <div className="flex-1 overflow-y-auto p-4">
            <KitList
              skills={skills}
              onChange={(s, st) => setStateMut.mutate({ skill: s, state: st })}
              onRemove={handleRemove}
            />
          </div>
        </SidebarInset>
      </SidebarProvider>

      <AddKitDialog
        open={addOpen}
        onOpenChange={setAddOpen}
        active={active}
        onInstalled={invalidate}
      />
      <DoctorDialog
        open={doctorOpen}
        onOpenChange={setDoctorOpen}
        onDone={invalidate}
      />
      <AddScopeDialog
        open={addScopeOpen}
        onOpenChange={setAddScopeOpen}
        onAdd={(p) => addScopeMut.mutate(p)}
      />
    </TooltipProvider>
  )
}
