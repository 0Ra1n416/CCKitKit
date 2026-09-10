import { useEffect, useState } from "react"
import { Megaphone } from "@phosphor-icons/react"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import { Button } from "@/components/ui/button"
import { api, type NoticeView } from "@/lib/api"

/**
 * 面板顶部的管理员通知（`cckit web --notice TITLE FILE`）。
 *
 * 标题由后端在启动时注入 `window.__CCKIT_NOTICE_TITLE__`，所以首屏就能画出来 ——
 * 不会先空一下再冒出来。**正文在打开弹窗时才去取**：公告通常比标题长得多，
 * 塞进每一次 `index.html` 响应不划算，而且这样改了公告文件也不用重启服务。
 *
 * 正文按**纯文本**渲染（`<pre>`），不解析 Markdown：面板能访问到的人都看得到这份
 * 内容，走 HTML 渲染会平白多一个 XSS 面。
 */
export function NoticeMenu({ title }: { title: string }) {
  const [open, setOpen] = useState(false)
  const [notice, setNotice] = useState<NoticeView | null>(null)
  const [error, setError] = useState("")
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!open) return
    let alive = true
    setLoading(true)
    setError("")
    api
      .notice()
      .then((v) => {
        if (alive) setNotice(v)
      })
      .catch((e) => {
        if (alive) setError((e as Error).message)
      })
      .finally(() => {
        if (alive) setLoading(false)
      })
    return () => {
      alive = false
    }
  }, [open])

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger
        render={
          <Button
            variant="default"
            className="ml-auto h-auto w-1/2 justify-start gap-2 px-3 py-1 text-left"
          />
        }
      >
        {/* 图标与文字都用按钮自己的前景色(on-primary 那组),不再另指定灰色 */}
        <Megaphone className="h-4 w-4 shrink-0" />
        {/* min-w-0 是关键:flex 子项默认不小于内容宽,少了它 truncate 不会生效 */}
        <span className="flex min-w-0 flex-1 flex-col items-start">
          <span className="text-[10px] leading-tight text-primary-foreground/70">
            管理员通知
          </span>
          <span className="w-full truncate text-xs leading-tight">{title}</span>
        </span>
      </DialogTrigger>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>管理员通知</DialogTitle>
          <DialogDescription>{title}</DialogDescription>
        </DialogHeader>
        {error ? (
          <p className="text-sm text-destructive">{error}</p>
        ) : (
          <pre className="max-h-[60vh] overflow-y-auto rounded-xl bg-muted/50 p-4 font-mono text-xs break-words whitespace-pre-wrap">
            {loading ? "加载中…" : (notice?.content || "（没有内容）")}
          </pre>
        )}
      </DialogContent>
    </Dialog>
  )
}
