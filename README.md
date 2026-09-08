<div align="center">

# CCKitKit

[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue)](#) [![版本](https://img.shields.io/badge/version-0.3.1-lightgrey)](#) [![测试](https://img.shields.io/badge/tests-132%20passed-brightgreen)](#)

</div>

> 命令名 `cckit` —— Claude Code 的 **Skill 工具箱管理器**：从任意 git 仓库拉取带环境依赖的 Skill，自动配置隔离环境，支持 skill 粒度的开关与干净卸载。

---

## 安装

**用户安装（推荐）：**

```bash
# 先装 uv
# Windows (PowerShell):  irm https://astral.sh/uv/install.ps1 | iex
# Linux / macOS:         curl -LsSf https://astral.sh/uv/install.sh | sh

# 再装 cckit
uv tool install cckit
```

从 Releases 下载安装： 见 [Releases](https://github.com/0Ra1n416/CCKitKit/releases) 。

从源码安装（开发者）：

```bash
git clone <repo> && cd CCKitKit
uv sync                       # 建开发环境（自动装 pytest）
uv run cckit --help           # 不安装直接跑
```

## 快速上手

所有命令默认作用于**全局**，加 `--project` 作用于当前项目。

```bash
# 安装一个 kit（git URL 或本地路径）
cckit add https://github.com/example/video-toolkit
cckit add ./local-kit --project --local

# 导入非标准仓库（没有 cckit.yaml 的普通 skill 仓库，由 Claude Code 改造）
uv tool install 'cckit[alt]'
cckit add https://github.com/someone/my-skill --alt

# 列出所有 skill 及清单预算占用
cckit list
cckit list --json            # 机器可读输出

# 四态开关
cckit enable my-skill        # → enabled
cckit disable my-skill       # → off（写 skillOverrides，可逆）
cckit disable my-skill --purge   # → installed（删 link）
cckit name-only my-skill     # → name-only（CC只能读到Skill名字，而读不到Description，节省预算）

# 卸载 / 诊断
cckit remove video-toolkit   # 删 link/env/store/registry/overrides
cckit doctor                 # 只诊断不自动修
cckit doctor --fix           # 只修明确安全的项

# 运行 skill 脚本（所有安装的 Skill 要求 SKILL.md 里统一写这一句，不写解释器路径）
cckit exec my-skill scripts/run.py [args...]
```

共 **9 个命令**：`add` / `list` / `enable` / `disable` / `name-only` / `remove` / `doctor` / `exec` / `web`。完整规格见 [Docs/cli-spec.md](Docs/cli-spec.md)。

## Web 管理面板

cckit 附带一个可选的管理面板（列表 / 导入 / 卸载 / 状态切换 / 诊断）。它是**纯增量**：不装 `[web]` 额外依赖时，`cckit` 本体与现在完全一样，`uv tool install cckit` 也不会带入任何 web 依赖。

### 启用

**普通用户**（前端已随 wheel 打包，一条命令即用）：

```bash
uv tool install 'cckit[web]'   # 带后端依赖 + 前端静态产物
cckit web                       # 前后端一起起，打开 http://127.0.0.1:8000 即用
```

**开发者**（源码仓库里改前端）：

```bash
cd web && npm install && npm run build   # 产出 web/dist/，uv build 时打进 wheel
cckit web                                 # 自动定位前端(包内 static → 源码 web/dist)

# 开发调试：前端单独起 vite dev(自带 /api 代理)
cckit web                # 后端(不托管前端)
cd web && npm run dev    # 前端 dev server(:5173)，代理 /api 到 :8000
```

前端是 Vite + React 19 + Tailwind v4 + shadcn/ui，静态产物由后端托管。

### 功能

- **dashboard 布局**：`Sidebar`（可收起成图标条）+ 右侧内容区。
- **作用域**：全局 + 装过 kit 的项目 + 手动「关注」的项目（即使暂无 skill 也显示，并自动建 `.claude`；关注项可取消关注）。
- **kit 列表**：项目 kit 可收起/展开/卸载；每个 skill 带四态开关，`name-only` 附解释。
- **全局 skill 项目覆盖**：项目作用域下，全局 skill 单独一组，可「跟随全局 / 仅名字 / 关闭」单独覆盖（不复用四态）。
- **添加 Kit**：填仓库地址或本地路径 → 展示安装计划（依赖 / postinstall / 系统依赖 / 来源+sha）等确认 → 实时日志。
- **导入非标准仓库**：开关「允许导入非标准仓库」后，对没有 `cckit.yaml` 的普通 skill 仓库走三阶段转换（准备 / 改造 / 审计），成功后进入既有安装流程。
- **诊断**：勾选 `--fix` 自动修复明确安全的项，下方展示逐项结果。
- **刷新**：侧栏刷新按钮 + 写操作后自动刷新；所有开关改动提示「新会话生效」。

### 安全与部署

- 后端**默认只绑 `127.0.0.1`**。要作为服务器面板被浏览器访问时，用 `cckit web --host 0.0.0.0`。
  ⚠️ 放开即把「能装 kit（跑作者代码）、能改 skill 状态」的能力暴露给网段，请只在可信内网使用，必要时在反向代理层加鉴权。
- 嵌入其他页面用 **iframe**：后端托管前端后，宿主页 `<iframe src="http://<server>:<port>/">` 即可（同源隔离，无 CORS 问题）。
- **子路径部署**：要把面板挂到宿主 dashboard 的某个子路径下（如 `/cckit/`），用 `cckit web --base /cckit`。
  此时整站（`/cckit/api/*`、`/cckit/assets/*`）都挂到该前缀下，反向代理只需把 `/cckit/*` 原样转发给 cckit，
  宿主页 `<iframe src="http://<server>:<port>/cckit/">` 即可，不会与 dashboard 自身的 `/api` 冲突。
  `--base` 是**运行时**配置，无需重新构建前端。

## 特色

Claude Code 原生已有 plugin + marketplace（git 源、sha 锁定、多组件打包），但有两个官方明确留空的缺口：

1. **环境配置是空白。** 官方唯一的自动依赖安装限于 npm/bun（且强制 `--ignore-scripts` + 60 秒超时），Python 依赖、原生编译、系统级二进制（如 `ffmpeg`）一律无解。
2. **skill 粒度开关拿不到。** `enabledPlugins` 是插件级布尔开关，无法只关插件里的某一个 skill。

cckit 不重复造插件系统，只填这两个缺口：它把 skill 装到 **personal / project 层**——恰好是 `skillOverrides` 唯一生效的层。

> ⚠️ **cckit 的核心功能（装依赖、跑 postinstall）正是官方明确拒绝实现的那件事。** 我们是本机工具、用户主动安装的，信任模型不同——但安全责任必须由我们承担。

## 核心概念

| 概念 | 含义 |
|---|---|
| **kit** | 分发单位。一个 git 仓库 = 一个 kit，含 1..N 个 skill + 一份 `cckit.yaml` |
| **skill** | 使用单位。CC 实际调用的东西，开关粒度也在这一层 |
| **store** | kit 真实文件的存放地（`~/.cckit/store/<kit>/`），全局唯一一份 |
| **env** | 每个 skill 独立的运行环境（venv / node_modules） |
| **link** | store 与 CC 扫描目录之间的目录链接，启用状态的物理载体 |

单个 skill 与 skill 集合**不分两套格式**，单个只是 `skills[]` 里 N=1 的特例。

### 四态模型

这是最核心的设计。**link 与 `skillOverrides` 是正交的两层**：link 决定"哪些作用域扫得到"，`skillOverrides` 决定"扫到之后什么状态"。

| 状态 | link | CC 看到 |
|---|---|---|
| `installed` | ✗ | 什么都看不到 |
| `enabled` | ✓ | 名字 + description |
| `name-only` | ✓ | 只有名字，不占预算 |
| `off` | ✓ | 什么都看不到 |

启用状态是**派生的**：`cckit list` 现场扫文件系统 + 读 `settings.json` 的 `skillOverrides`。

### 环境隔离

**每个 skill 一个独立 venv**（不是每个 kit 一个），依赖冲突彻底隔离、卸载即删目录。纯 prompt skill（`needs: []`）不创建 env。使用 `uv` 构建，速度有保障，且能自己拉指定版本的 Python。

## 开发符合规范的 kit

kit 的唯一硬判据：**仓库根目录有一份合法的 `cckit.yaml`**。最小 kit 长这样：

```
my-kit/
├── cckit.yaml                  # 唯一硬判据
└── my-skill/                   # 目录名必须与 skills[].name 逐字符一致
    ├── SKILL.md                # 必须存在
    └── scripts/run.py          # (可选)
```

```yaml
cckit: 1
kit: my-kit
version: 0.1.0
description: 一句话说明这个 kit 做什么

skills:
  - name: my-skill              # 小写 kebab-case，与目录名一致
    needs: [python]             # [] = 纯 prompt；python/node 触发建环境
    scripts: [scripts/run.py]
```

安装前会跑 schema 校验 + 语义检查 + lint（skill 名合法性、description 质量、CRLF、prompt injection、typosquatting 提示），error 一律在做事之前中止。完整开发手册见 [skills/kit-builder/kit-builder/kit-authoring.md](skills/kit-builder/kit-builder/kit-authoring.md)，字段规范见 [skills/kit-builder/kit-builder/manifest-spec.md](skills/kit-builder/kit-builder/manifest-spec.md)。

## 安全模型

cckit 装的是仓库作者的代码，因此这些是**不可省略的硬要求**，不是"最佳实践"：

- **锁 commit sha，不锁分支**——分支/tag 能被作者事后移动，sha 不能。
- **安装前展示完整计划并等确认**（要装哪些包、跑哪些 postinstall、缺哪些系统依赖、来源 + sha）。`-y` 跳过确认，会有警示。
- **postinstall 只允许写 kit 自己的目录与其 env**——任何系统级操作必须改声明为 `requires.system`。
- **系统级依赖绝不自动安装**——只检查存在性 + 版本约束 + 给当前平台 hint。
  - `version_cmd` 收紧为 `<bin> <版本标志>` 白名单（`--version` / `-V` / `-v` / `version` / `-version`），其余一律拒绝并报 warn——堵住"借版本检查塞任意命令"的风险。
- **SKILL.md prompt injection 启发式扫描**，**依赖名 typosquatting 提示**。
- **写 `settings.json` 三件套**：文件锁 + 原子替换 + 只改 `skillOverrides` 键，否则会丢失更新或损坏用户配置。

> 安装一个 kit 等同于在本机运行该仓库作者的代码。**请只安装你信任来源的 kit，并在安装前阅读 cckit 展示的执行计划。** 

### 非标准仓库导入（`--alt`）的安全边界

`--alt` 会在安装前调用 Claude Code 改造并审计**临时目录里**的仓库，额外的边界：

- **标准仓库不碰 LLM**：有合法 `cckit.yaml` 时，即使带 `--alt` 也走原确定性流程。
- **权限是 `auto`，不是无条件放行**：`permission_mode="auto"` 由 Claude Code 自动判断
  每个工具调用是否放行；不设 `can_use_tool`、不用 `bypassPermissions`。
- **隔离仓库自带的 settings/MCP**：`setting_sources=["user"]` 只加载用户级 settings，
  跳过仓库自带的 `.claude/settings*.json`；`strict_mcp_config=True` 忽略仓库的
  `.mcp.json`，防止仓库自我授权或借 MCP 执行代码。
- **`cwd` 只是工作目录，不是沙箱**：它把 Agent 限定在临时仓库，但不等于文件系统隔离。
- **确定性校验与安装计划确认仍是闸门**：改造后先过 `manifest/schema/semantic/lint`，
  审计通过后还要走安装计划展示与用户确认、回滚机制；审计失败/不明确即中止。
- **不记录改造后的 SHA**：保留原始来源 URL/ref，但不把原始 SHA 误标为改造后内容。
- **临时目录必然清理**：成功、失败、取消、Ctrl+C 都清理 `cckit-alt-*` 目录并关闭
  Claude Code 子进程。

## CCkit 目录布局

```
~/.cckit/                          # 可被 CCKIT_HOME 覆盖
  store/<kit>/                     # git clone 的真实内容，含 cckit.yaml
    <skill>/SKILL.md
  envs/<kit>__<skill>__<runtime>/  # 每 skill 一个独立环境
  registry.json                    # 装了什么、装在哪、什么版本
  usage.jsonl                      # 用量统计（追加式，并发安全）

<CC 配置目录>/skills/<skill>        # link → store。全局启用
<项目>/.claude/skills/<skill>       # link → store。项目启用
```

⚠️ `<CC 配置目录>` 会依照 `CLAUDE_CONFIG_DIR` > `XDG_CONFIG_HOME/claude` > `~/.claude` 进行定位。

## 开发与测试

```bash
uv sync                 # 建开发环境（含 pytest）
uv run pytest -q        # 测试
uv run cckit --help     # 直接跑，无需安装
uv tool install --editable .   # 本机可编辑安装
```

代码结构（`src/cckit/`，19 个文件，含 `web/` 子包）：

| 模块 | 职责 |
|---|---|
| `cli.py` | argparse 分发到 9 个子命令 |
| `installer.py` | `add` 全流程：锁 sha → 校验 → lint → 计划确认 → store/env/postinstall/registry/link |
| `alt.py` | 非标准仓库导入：前置条件 → 物化 → kit-builder 改造 → 审计 → 复用本地安装 |
| `manifest.py` | `cckit.yaml` 加载 + schema 校验 + 语义检查 |
| `schema.py` | JSON Schema 加载器（Draft 2020-12） |
| `lint.py` | 命名 / description / CRLF / prompt injection / typosquatting |
| `env.py` | uv venv / node env 与解释器解析 |
| `exec.py` | skill 脚本统一入口（白名单 + 环境变量注入） |
| `state.py` | 四态派生 + 文件锁 + 原子写 + 清单预算 |
| `registry.py` | `registry.json` 原子读写 |
| `link.py` | 跨平台目录链接层（Windows junction / POSIX symlink） |
| `doctor.py` | 只读诊断 + 安全修复 |
| `config.py` | 路径与平台解析（`CCKIT_HOME` / `CLAUDE_CONFIG_DIR` / 项目根） |
| `errors.py` | 受检错误 `CckitError` |
| `projects.py` | 关注项目清单 `projects.json` 原子读写 |
| `web/` | Web 管理面板后端（FastAPI，惰性 import，`[web]` 可选依赖） |
