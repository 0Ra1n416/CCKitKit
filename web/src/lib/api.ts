// cckit Web 后端 API 的类型与封装。SSE 端点返回原生 fetch Response,由 useSSE 消费。

export type Scope = "global" | "project"
export type SkillState = "installed" | "enabled" | "name-only" | "off"

export interface ScopeEntry {
  path: string
  source: "global" | "installed" | "watched"
  has_skills: boolean
}

export interface SkillItem {
  name: string
  kit: string | null
  scope: Scope
  state: SkillState
  managed: boolean
  env_ok: boolean | null
  desc_chars: number
  version: string | null
  is_global_skill: boolean
  global_state: string | null
  override: boolean
}

export interface Budget {
  used: number
  limit: number
}

export interface KitInfo {
  name: string
  version: string | null
  source: string | null
  ref: string | null
  sha: string | null
  installed_at: string | null
  store: string | null
}

export interface Plan {
  source: string
  ref: string | null
  sha: string | null
  kit: string
  version: string
  description: string
  python_packages: string[]
  node_packages: string[]
  postinstall: { run: string; when?: string }[]
  system_missing: { bin: string; hint?: string }[]
  system_version_warn: { bin: string; detail?: string }[]
  system_version_error: { bin: string; detail?: string }[]
  skills: { name: string; needs: string[] }[]
}

export interface LintMsg {
  level: "error" | "warn"
  message: string
}

export interface Finding {
  check: string
  status: "ok" | "warn" | "error"
  message: string
  fix: string | null
}

export interface SseEvent {
  event:
    | "progress"
    | "done"
    | "error"
    | "alt_progress"
    | "alt_done"
    | "alt_cancelled"
    | "alt_error"
  stage?: string
  status?: string
  kind?: string
  message?: string
  findings?: Finding[]
  session_id?: string
  repo_dir?: string
}

export interface AltCheckResult {
  sdk_available: boolean
  status:
    | "ready"
    | "missing"
    | "not_enabled"
    | "conflict"
    | "source_conflict"
    | "missing_extra"
  reason: string
  auto_fix: "install" | "enable" | null
}

export interface AltProgressEvent {
  stage: "prepare" | "builder" | "audit"
  kind: "status" | "text" | "tool" | "error" | "done"
  message: string
  session_id?: string
}

declare global {
  interface Window {
    __CCKIT_BASE__?: string
  }
}

// 运行时根路径前缀:后端 serve 时注入 window.__CCKIT_BASE__(见 cckit web --base),
// 根部署为空 → 所有路径仍落在 /api/*。
const BASE = window.__CCKIT_BASE__ ?? ""
const apiUrl = (p: string) => `${BASE}${p}`

async function req<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init)
  const data = await res.json().catch(() => ({}))
  if (!res.ok) {
    throw new Error(
      (data as { error?: { message?: string } })?.error?.message ??
        `请求失败 (${res.status})`,
    )
  }
  return data as T
}

const jsonHeaders = { "Content-Type": "application/json" }

export const api = {
  scopes: () => req<{ scopes: ScopeEntry[] }>(apiUrl("/api/scopes")),

  addScope: (path: string) =>
    req<{ scopes: ScopeEntry[] }>(apiUrl("/api/scopes"), {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify({ path }),
    }),

  removeScope: (path: string) =>
    req<{ scopes: ScopeEntry[] }>(apiUrl("/api/scopes"), {
      method: "DELETE",
      headers: jsonHeaders,
      body: JSON.stringify({ path }),
    }),

  skills: (scope: Scope, root?: string) =>
    req<{ skills: SkillItem[]; budget: Budget }>(
      apiUrl(`/api/skills?scope=${scope}${root ? `&root=${encodeURIComponent(root)}` : ""}`),
    ),

  setState: (name: string, state: SkillState, scope: Scope, root?: string) =>
    req<{ message: string }>(
      apiUrl(`/api/skills/${encodeURIComponent(name)}/state`),
      {
        method: "POST",
        headers: jsonHeaders,
        body: JSON.stringify({ state, scope, root }),
      },
    ),

  kits: () => req<{ kits: KitInfo[] }>(apiUrl("/api/kits")),

  removeKit: (kit: string) =>
    req<{ message: string }>(apiUrl(`/api/kits/${encodeURIComponent(kit)}/remove`), {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify({ keep_env: false }),
    }),

  addPreview: (body: {
    source: string
    ref?: string
    local: boolean
    project: boolean
    root?: string
    only?: string
    alt?: boolean
  }) =>
    req<{
      preview_id: string
      kit_name: string
      plan: Plan
      lint_msgs: LintMsg[]
      project_warns: string[]
      non_standard?: boolean
    }>(apiUrl("/api/add/preview"), {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify(body),
    }),

  // SSE 端点:返回原生 Response,由调用方消费流。
  addExecute: (preview_id: string, no_enable: boolean) =>
    fetch(apiUrl("/api/add/execute"), {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify({ preview_id, no_enable }),
    }),

  cancelPreview: (preview_id: string) =>
    req<{ message: string }>(apiUrl(`/api/add/preview/${preview_id}`), {
      method: "DELETE",
    }),

  // alt:非标准仓库导入
  altCheck: () => req<AltCheckResult>(apiUrl("/api/add/alt/check")),

  altFix: (action: "install" | "enable") =>
    req<{ message: string }>(apiUrl("/api/add/alt/fix"), {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify({ action }),
    }),

  altStart: (body: {
    source: string
    ref?: string
    local: boolean
    project: boolean
    root?: string
    only?: string
  }) =>
    fetch(apiUrl("/api/add/alt/start"), {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify(body),
    }),

  altCancel: (session_id: string) =>
    req<{ message: string }>(apiUrl("/api/add/alt/cancel"), {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify({ session_id }),
    }),

  altComplete: (session_id: string) =>
    req<{
      preview_id: string
      kit_name: string
      plan: Plan
      lint_msgs: LintMsg[]
      project_warns: string[]
    }>(apiUrl("/api/add/alt/complete"), {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify({ session_id }),
    }),

  doctor: (fix: boolean) =>
    fetch(apiUrl("/api/doctor"), {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify({ fix }),
    }),
}
