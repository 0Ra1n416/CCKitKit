import { useState } from "react"
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

export function AddScopeDialog({
  open,
  onOpenChange,
  onAdd,
}: {
  open: boolean
  onOpenChange: (o: boolean) => void
  onAdd: (path: string) => void
}) {
  const [path, setPath] = useState("")

  const confirm = () => {
    if (!path.trim()) return
    onAdd(path.trim())
    setPath("")
    onOpenChange(false)
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        if (!o) setPath("")
        onOpenChange(o)
      }}
    >
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>添加关注项目</DialogTitle>
          <DialogDescription>
            输入项目绝对路径，将自动创建 .claude 目录使其成为项目作用域
          </DialogDescription>
        </DialogHeader>
        <Input
          autoFocus
          placeholder="项目绝对路径，如 C:\work\proj-a"
          value={path}
          onChange={(e) => setPath(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && confirm()}
        />
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            取消
          </Button>
          <Button disabled={!path.trim()} onClick={confirm}>
            添加
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
