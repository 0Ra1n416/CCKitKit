import { useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { Topbar } from "@/components/Topbar"
import { ScopeSidebar, type ActiveScope } from "@/components/ScopeSidebar"
import { KitList } from "@/components/KitList"
import { BudgetBar } from "@/components/BudgetBar"
import { AddKitDialog } from "@/components/AddKitDialog"
import { DoctorDialog } from "@/components/DoctorDialog"
import { TooltipProvider } from "@/components/ui/tooltip"
import { api, type SkillItem, type SkillState } from "@/lib/api"

export default function App() {
  const qc = useQueryClient()
  const [active, setActive] = useState<ActiveScope>({ scope: "global" })
  const [addOpen, setAddOpen] = useState(false)
  const [doctorOpen, setDoctorOpen] = useState(false)

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
      toast.info(data.message)
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

  const handleRemove = (kit: string) => {
    toast(`确定卸载「${kit}」？`, {
      action: {
        label: "确认卸载",
        onClick: () => removeKitMut.mutate(kit),
      },
    })
  }

  const skills = skillsQ.data?.skills ?? []
  const budget = skillsQ.data?.budget ?? { used: 0, limit: 0 }
  const scopes = scopesQ.data?.scopes ?? []
  const refreshing = skillsQ.isFetching || scopesQ.isFetching

  return (
    <TooltipProvider delayDuration={200}>
      <div className="flex h-screen flex-col">
        <Topbar
          onRefresh={invalidate}
          onAdd={() => setAddOpen(true)}
          onDoctor={() => setDoctorOpen(true)}
          refreshing={refreshing}
        />
        <div className="flex min-h-0 flex-1">
          <ScopeSidebar
            scopes={scopes}
            active={active}
            onSelect={setActive}
            onAdd={(p) => addScopeMut.mutate(p)}
          />
          <main className="flex min-w-0 flex-1 flex-col">
            <div className="flex-1 overflow-y-auto p-4">
              <KitList
                skills={skills}
                onChange={(s, st) => setStateMut.mutate({ skill: s, state: st })}
                onRemove={handleRemove}
              />
            </div>
            <BudgetBar budget={budget} />
          </main>
        </div>

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
      </div>
    </TooltipProvider>
  )
}
