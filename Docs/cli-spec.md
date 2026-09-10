# CLI 规格

约定:所有命令默认作用于**全局**;加 `--project` 作用于当前项目。
所有破坏性操作在非 `-y` 时需确认。

## `cckit add <source>`

拉取并安装一个 kit。

```bash
cckit add https://github.com/someone/video-toolkit
cckit add https://gitee.com/someone/video-toolkit --ref v1.2.0
cckit add ./local-kit --project --local
```

`<source>` 接受任意 git URL(GitHub / Gitee / GitLab / 自建均可,只要是标准 git over HTTPS/SSH) 或本地路径（需要加上 `--local` 选项）。

### 流程

1. **clone** 到临时目录,解析 `--ref`(缺省默认分支)
2. **锁定 commit sha**——记录 sha 而非分支名。分支会被作者事后改动
3. **校验 manifest**:存在性 → JSON Schema → 语义检查(`needs` 引用、skill 目录与
   `skills[]` 一致、平台匹配)。任一失败则**中止且不留残留**
4. **lint**:skill 名合法性、description 质量、CRLF、保留名(见 03)
5. **展示计划并等确认**:要装哪些包、跑哪个 postinstall、缺哪些系统依赖。
   ⚠️ 这一步不可省略,是与官方安全模型之间唯一的桥(见 07)
6. **移入 store**,建 env,装依赖,跑 postinstall
7. **建 link** 启用(除非 `--no-enable`)
8. **写 registry**,报告清单预算占用

### 关键选项

| 选项 | 说明 |
|---|---|
| `--ref <ref>` | 分支 / tag / commit |
| `--no-enable` | 只装不启用(落到 `installed` 态) |
| `--project` | 装到当前项目而非全局 |
| `--only <skill,...>` | 只启用 kit 中的部分 skill |
| `--alt` | 允许导入非标准仓库(没有 `cckit.yaml` 的普通 skill 仓库),由 Claude Code 改造 |
| `-y` | 跳过确认。CI 用,文档需警示风险 |

### 非标准仓库导入(`--alt`)

默认情况下,仓库根目录没有合法 `cckit.yaml` 会直接拒绝安装。加上 `--alt` 后,
cckit 会在**显式开启、经过前置条件检查**的前提下,调用 Claude Code 把一个普通
skill 仓库改造成标准 kit,再复用现有安装流程:

```bash
# 前置依赖:alt extra(内含 claude-agent-sdk)
uv tool install 'cckit[alt]'

# 导入一个普通 skill 仓库(没有 cckit.yaml)
cckit add https://github.com/someone/my-skill --alt
cckit add ./my-skill --local --alt
```

流程:

1. 把远程仓库按 `--ref` 拉取、或把本地目录复制到临时目录(总是剥离 `.git`);
2. 若仓库根目录已有 `cckit.yaml`,**仍走标准流程,不调用 Claude Code**;
3. 前置条件检查:`claude-agent-sdk` 可导入 + 全局 `kit-builder` 处于 `enabled`;
   - 未装 SDK → 提示 `uv tool install 'cckit[alt]'` 并以错误结束;
   - `kit-builder` 缺失/状态不合适 → 提示修复命令,无冲突时可选择自动修复;
   - 存在作用域/来源冲突 → 停止,不静默覆盖;
4. 以临时仓库为 `cwd` 调用 `kit-builder` 改造仓库;
5. 确定性校验:`manifest.load → validate_schema → semantic_check → lint`;
6. 调用 Claude Code **审计**改造结果(prompt injection、敏感读取、外传、越界等);
7. 只有校验与审计都通过,才把临时目录作为本地 Kit 交给现有安装接口,继续沿用
   `--project` / `--no-enable` / `--only` / `-y` 等参数与安装计划确认;
8. 无论成功、失败、取消还是 Ctrl+C,临时目录都在最外层 `try/finally` 清理。

安全边界(详见 [07-security.md](07-security.md) 与 [05-design-log.md](05-design-log.md)):

- 使用 `ClaudeAgentOptions(permission_mode="auto", cwd=临时目录)`,**不设置**
  `can_use_tool`,**不使用** `bypassPermissions`;`auto` 是自动权限判断,不是无条件放行;
- **隔离仓库自带的 settings/MCP**:`setting_sources=["user"]` 只加载用户级 settings,
  `strict_mcp_config=True` 忽略仓库的 `.mcp.json`,防止仓库自我授权或借 MCP 执行代码;
- `cwd` 只是限定 Agent 的工作目录,不是完整文件系统沙箱;
- 审计失败、审计无法完成或审计结论不明确时,不得继续安装;
- alt 流程**不记录改造后的 SHA**(改造后的内容已非原始仓库状态);保留原始来源 URL、ref。

### 必须拦截的情况

- 当前平台不在 `platforms` 内 → 拒绝,不等装完才发现
- 系统依赖缺失 → 报告并给**当前平台**的 hint,询问是继续(env 仍可建)还是中止
- link 目标已存在真实目录 → 报错说明这是用户手写的 skill,不覆盖
- **同作用域已存在同名 skill → 拒绝安装**。CC 的 skill 名字空间是单层的(link 落点
  是 `<skills_dir>/<name>`,没有 kit 前缀),一个名字在一个作用域内只能属于一个 kit。
  不拦的后果是静默失效:`state.set_state` 见到已有 link 直接 `pass`,后装的 skill
  只写进 registry 却永远建不上 link(在 `list` 里显示为 installed),此后按名操作
  (`enable` / `disable` / `exec`)还会因归属歧义报错。报错需点名占用者(哪个 kit、
  悬空 link、还是用户手写的目录)并给出释放该名字的办法;`--only` 排除掉的 skill
  本次不建 link,不参与检查。检查看的是**目标作用域的名字有没有被 link 占用**,
  与 `--no-enable` 无关(该名字在这个作用域已注定建不上 link)。
- **项目安装时存在同名全局 skill → 明确警告"全局会覆盖项目版"**(跨作用域同名是
  允许的,由 CC 的优先级决定谁生效,不属于上一条的拒绝范围)

## `cckit list`

```
$ cckit list

video-toolkit  1.2.0  [env]
  ● burn-subtitles     enabled     env ok        [envs]  [conf_files]  ⚠ 缺必需变量 FONT_DIR → cckit env
  ◐ describe-video     name-only   prompt-only
doc-tools      0.4.1  (sha a1b2c3d)
  ○ pdf-extract        off         env ok
  ✗ ocr-scan           enabled     env MISSING  → cckit doctor

清单预算: 3.2k / 8.0k 字符 (40%)
```

预算行是硬要求,不是装饰。工具箱变大后超预算会**静默丢弃 description**,
表现为"装了但 CC 从不用"且无提示。

选项:`--project` 只列项目;`--all` 全作用域;`--json` 机器可读。

**依赖标记**:kit 行末尾的 `[env]` 表示该 kit 有 `kit_env` 声明;skill 行末尾的
`[envs]` / `[conf_files]` 表示该 skill 有相应声明。没有就不显示,不给每一行加噪声。

**缺配置提醒**:skill 行末尾的 `⚠ 缺必需变量 <名字> → cckit env` 表示该 skill 生效的
环境变量里有声明 `required: true` 却还没值的(见下)。判定口径与 `cckit exec` 注入时完全
一致:kit 级与 skill 级声明都算、同名以 skill 级为准、值先看 `envs.json` 再看进程环境。
没有未填的项就不显示这行 —— 与依赖标记同样是"只在真有事时出现"。

> 注意与 `env MISSING → cckit doctor` 区分:那个是**运行环境(venv)坏了**,要去诊断;
> 这个只是**变量还没填**,`cckit env` 填上即可。

**`--envs` / `--confs`** 在列表之后追加明细:

```
$ cckit list --envs

[envs]
  burn-subtitles
    [kit  ] OPENAI_API_KEY       可选  未设  用于字幕润色,不填则跳过
    [skill] FONT_DIR             必需  已设  字幕字体所在目录
  describe-video
    无
```

⚠️ **只报"已设/未设",绝不回显值** —— 否则密钥会进终端 scrollback 与日志。
没有声明时显示「无」。

`--json` 每个 skill 额外带 `envs` / `conf_files`。

`--json` 应同时列出**非 cckit 管理**的 skill(用户手写、插件带的),标记为只读。
用户看到的是完整工具箱视图,但只有 cckit 装的能被开关。

## `cckit env <skill> [name] [value]`

查看 / 设置 / 清除 skill 需要的环境变量。

```bash
cckit env burn-subtitles                      # 列出声明与「已设/未设」
cckit env burn-subtitles FONT_DIR /usr/fonts  # 设置
cckit env burn-subtitles FONT_DIR             # 省略值则交互输入
cckit env burn-subtitles FONT_DIR --unset     # 清除
cckit env burn-subtitles FONT_DIR --project   # 作用于项目作用域
```

- 变量必须**已在 manifest 里声明**(`kit_env` 或 skill 的 `env`),不能凭空造 ——
  否则就是往脚本环境里塞任意变量。
- 声明在 `kit_env` 里的写 **kit 桶**(整个 kit 共用一份);声明在 skill 里的写
  **skill 桶**。同名时 skill 级覆盖 kit 级。
- 值存在 cckit 数据目录的 `envs.json`(锁 + 原子写),由 `cckit exec` 注入。
  **不写 Claude Code 的 `settings.json`** —— 见 [07-security.md](07-security.md) 第 10 条。
- 取值优先级:`envs.json` > 调用方的进程环境。两处都没有且声明 `required: true`
  时,`cckit exec` 报错中止(不静默跳过)。

实现上直接调 `cckit.state.list_skills()`,**不要自己扫目录**——该函数同时服务
Web 接口,两边必须共用同一份逻辑。

## `cckit enable` / `disable`

```bash
cckit enable <skill>              # → enabled
cckit disable <skill>             # → off,写 skillOverrides(默认)
cckit disable <skill> --purge     # → installed,删 link
cckit name-only <skill>           # → name-only,省预算
```

`disable` 默认走 `skillOverrides` 而非删 link:可逆、不动文件、瞬间生效。
`--purge` 用于彻底移出扫描范围。对全局 skill,全局 `--purge` 还会清掉它在各项目根留下的
项目级 `skillOverrides` 覆盖(避免孤儿覆盖)。

⚠️ 全局 skill 的项目级开关语义不同: `disable <name> --project` 写项目覆盖;
`enable <name> --project` 清掉覆盖、跟随全局;`disable <name> --purge --project` **会报错**
——全局 skill 没有项目 link 可删,去掉 `--project` 在全局作用域执行。

⚠️ 一律通过 `cckit.state.set_state()` 落盘,**不直接写 `settings.json`**。
实测无锁并发写会丢失更新(8 个并发只活下来 1 条),且半截写入会让 CC 完全读不了
settings。

改动**不影响已在运行的会话**,输出应提示"新会话生效"。

## `cckit remove <kit>`

删 link → 删 env → 删 store → 清理 registry 与 `skillOverrides` 残留条目。

⚠️ **不能只删 skill 目录。** env 在 `~/.cckit/envs/`、状态在 registry 与
settings.json,必须由 cckit 跟踪清理。

`--keep-env` 保留 env(便于重装调试)。

## `cckit doctor`

只诊断,不自动修;每项给出可复制的修复命令。

| 检查项 | 为什么 |
|---|---|
| `uv` 是否在 PATH | 缺失则无法建 env |
| 悬空 link(目标已消失) | 用 `lexists && !exists` 检出 |
| link 指向是否与 registry 一致 | 手工改动会导致漂移 |
| env 是否完整、解释器是否可执行 | 换机 / Python 升级会坏 |
| 系统依赖是否仍在 | 用户可能卸了 ffmpeg |
| **`disableSkillShellExecution` 是否开启** | 开了则**所有带脚本 skill 静默失效** |
| 清单预算是否超限 | 超了会静默丢 description |
| 同名冲突(全局 vs 项目) | 全局静默覆盖项目版 |

这张表里各项的共同点是**不报错,只静默失效**。

`--fix` 只处理明确安全的项(清理悬空 link、重建 env)。

## `cckit exec <skill> <script> [args...]`

skill 脚本的统一入口。SKILL.md 里只写这一句,不写解释器路径。

要点:cwd **保持调用方 cwd**(让用户给的相对路径正常工作),脚本自身资源通过
`CCKIT_SKILL_DIR` 定位。`scripts` 未在 manifest 声明的路径应拒绝执行。

除 `CCKIT_SKILL_DIR` / `CCKIT_KIT_DIR` / `CCKIT_ENV_DIR`(以及 node 的 `NODE_PATH`)
外,还注入 `kit_env` 与 skill 的 `env` 声明的环境变量:

- 同名时 **skill 级覆盖 kit 级**;
- 值先取用户在 CLI/Web 填的(`envs.json`),没有再回落调用方的进程环境;
- 声明 `required: true` 却两处都取不到 → **报错中止**,并给出 `cckit env` 的填写命令;
- `required: false` 且没值 → 不注入、不报错,由脚本自己决定跳过哪一步。

## `cckit web`

启动 Web 管理面板(需 `[web]` extra,缺失时提示 `uv tool install 'cckit[web]'`)。
前端静态产物随 wheel 打包,后端自动定位(包内 `static` → 源码 `web/dist`)。

```bash
cckit web                            # 前端后端一起起,打开 http://127.0.0.1:8000 即用
cckit web --host 0.0.0.0 --port 8000 # 部署到服务器
cckit web --base /cckit              # 挂到根路径前缀 /cckit 下
cckit web --notice "维护通知" ./notice.md   # 面板顶部挂一条管理员通知
```

| 选项 | 说明 |
|---|---|
| `--host` | 监听地址,默认 `127.0.0.1`;部署时 `0.0.0.0` |
| `--port` | 端口,默认 `8000` |
| `--static-dir` | 前端静态产物目录(缺省不托管,配合 vite dev 使用) |
| `--base` | 根路径前缀(如 `/cckit`)。运行时把整站(`/api/*`、`/assets/*`)挂到该前缀下,反向代理只需原样透传 `/base/*`;用于把面板以 iframe 嵌入宿主 dashboard 的子路径而不与宿主 `/api` 冲突 |
| `--notice TITLE FILE` | 面板顶部显示一条**管理员通知**,点开看 `FILE` 的内容。不传就不显示任何控件 |

`--base` 是**运行时**配置:后端 serve 时把 `window.__CCKIT_BASE__` 注入 `index.html`,
前端据此拼 `/api` 前缀;前端资源用相对路径(`Vite base: "./"`)自动跟随子路径,无需重新构建。

### 管理员通知(`--notice`)

给运维一个"在面板上挂公告"的口子。**不传 `--notice` 时前后端都不做任何额外的事** ——
没有控件、没有额外请求。

- **启动时校验 `FILE` 是否存在**(不是普通文件就直接报错退出)。路径写错当场暴露,
  不会等到用户点开弹窗才发现。
- 标题随 `index.html` 注入(`window.__CCKIT_NOTICE_TITLE__`),所以**首屏就画得出来**,
  不会先空一下再冒出来;正文走 `GET /api/info` **按需取**,因此改了公告文件**不用重启服务**。
- 正文按**纯文本**返回、前端用 `<pre>` 渲染 —— 不解析 Markdown,也不走 HTML,
  免得平白多一个 XSS 面。大小上限 256 KiB,非 UTF-8 用 `errors="replace"` 兜住。
- 没配 `--notice` 时 `/api/info` 返回 **404**,前端据此完全不渲染那个控件
  (比返回空对象更能区分"没配置"和"配置了但没内容")。

⚠️ **通知内容对所有能访问面板的人都可见。** 默认只绑 `127.0.0.1` 没问题,但
`--host 0.0.0.0` 部署时它就是公开的 —— **不要往公告文件里放密钥**。见
[07-security.md](07-security.md)。
