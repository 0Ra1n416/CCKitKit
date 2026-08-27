# Kit 开发手册:把普通 skill 变成 kit

本文针对**想发布 kit 的开发者**。如果你的作品现在是一个普通 skill(一个带
`SKILL.md` 的目录,或几个脚本),本文告诉你把它改造成 cckit 能安装的 kit 需要做
什么。

简单来说，**符合 kit 要求只有一条硬判据 —— 仓库根目录有一份合法的 `cckit.yaml`。**
没有它,`cckit add` 直接拒绝。其余操作都是为了让这份 manifest 站得住、让 skill 装得干净。

规范原文见 [manifest-spec.md](manifest-spec.md), 本文是从"改造一个既有 skill"的视角重述一遍。

---

## 1. kit 和 skill 的关系

| 概念 | 是什么 | 谁在使用 |
|---|---|---|
| **kit** | 一个 git 仓库 = 一个 kit。含 1..N 个 skill + 一份 `cckit.yaml` | cckit 安装/卸载的单位 |
| **skill** | kit 里的一个子目录,内含 `SKILL.md`(和可选脚本) | CC 实际调用、开关的单位 |

一个 skill 的 kit 只是 `skills` 数组里只有一项的特例。
**如果你只有一个 skill, `skills: [ {name: xxx, needs: ...} ]` 写一项即可。**

## 2. 最小 kit 的目录结构

一个合法的、能装进 cckit 的最小 kit 长这样:

```
my-kit/                         # git 仓库根 = kit 根
├── cckit.yaml                  # 唯一硬判据,必须在这里
└── my-skill/                   # skill 目录,名字必须与 cckit.yaml 里一致
    ├── SKILL.md                # 必须存在(语义检查会查)
    └── scripts/                # (可选)skill 脚本
        └── run.py
```

三条硬规则:

1. `cckit.yaml` 必须在 kit 根目录。
2. `skills[].name` 必须与对应子目录名**逐字符一致**(小写 kebab-case)。
3. 每个 skill 目录下必须有 `SKILL.md`。

## 3. 三步改造

把普通 skill 变成 kit,做这三步就够了。

### 第 1 步:写 `cckit.yaml`

以你的 skill 名为 `my-skill` 为例,先写最简版:

```yaml
cckit: 1

kit: my-kit                    # kit 标识,小写 kebab-case
version: 0.1.0                 # 语义化版本
description: 一句话说清这个 kit 做什么

skills:
  - name: my-skill             # 必须与目录名一致
    needs: []                  # 先按纯 prompt 写,有依赖再改
```

这个最简版已经**通过 schema 校验**。`needs: []` 表示纯 prompt skill,安装时不建任何
环境 —— 如果你的 skill 目前没有依赖,到这里就完成了。

### 第 2 步:整理 SKILL.md 的 frontmatter

检查你的 `SKILL.md` 开头是否是一段合法的 YAML frontmatter(`---` 开始、`---` 结束):

```yaml
---
name: my-skill
description: 用一句话说明这个 skill 能做什么
---
```

要点(详细规则见 §5):

- `description` **必须非空** —— CC 靠它决定要不要调用你的 skill。缺失是 lint **error**。
- 描述里别写触发条件("Use when..."、"当用户…时")—— 那属于 `when_to_use`,
  写在 `description` 里会被 lint 警告。
- **不要**往 frontmatter 塞自创字段。私有信息只写进 `metadata`(CC 会忽略它,
  见 §5.2)。

### 第 3 步:本地自检

在 kit 根目录跑:

```bash
uv run cckit add ./my-kit --no-enable
```

cckit 会先 clone/校验、再展示安装计划。**只要校验或 lint 有错,它会在做任何事之前
中止**,你据此修即可。看到计划后按 `N` 取消(除非你真想装)。详细自检见 §7。

---

## 4. `cckit.yaml` 字段速查

完整字段参考在 [manifest-spec](manifest-spec.md), 这里按"什么时候你会用到它"组织。

### 4.1 顶层

| 字段 | 必填 | 说明 |
|---|---|---|
| `cckit` | ✓ | manifest 格式版本,当前只能写 `1` |
| `kit` | ✓ | kit 标识,小写 kebab-case,最长 64 字符 |
| `version` | ✓ | 语义化版本,形如 `1.2.0` |
| `description` | ✓ | 一句话说明,最长 200 字符 |
| `platforms` | | `windows` / `linux` / `macos` 子集;缺省 = 全平台 |
| `requires` | | 环境需求(§4.2) |
| `env` | | 需要用户提供的环境变量(§4.4) |
| `skills` | ✓ | 至少一项(§4.5) |
| `postinstall` | | 安装后钩子(§4.6) |

`author` / `homepage` / `license` 是可选元数据,建议写上 —— 尤其 `license`,
安装计划会展示给用户。

### 4.2 `requires` — 环境需求

```yaml
requires:
  runtime:                     # 解释器版本约束,uv 会按它自动拉,用户无需预装
    python: ">=3.11"
    node: ">=20"               # 可选
  system:                      # 系统级二进制:只检查存在性,绝不自动装
    - bin: ffmpeg
      hint:
        windows: winget install ffmpeg
        linux: sudo apt install ffmpeg
        macos: brew install ffmpeg
      version: ">=6.0"         # 可选,配 version_cmd 使用
      version_cmd: ffmpeg -version
  python:                      # Python 依赖,复用标准文件
    file: requirements.txt
  node:                        # Node 依赖,复用标准文件
    file: package.json
```

- **`system` 声明系统二进制。** 这一项的语义是"安装前检查在不在 PATH,不在就报缺失并
  给出**当前平台**的 hint",**永远不会自动 `sudo apt install`**。这是硬性安全要求,别指望 cckit 帮你装系统级工具。
- **`hint` 必须是分平台 map**,不能写成一个字符串。写成 `hint: winget install ffmpeg`
  这种单个字符串是 Windows-only 错误,lint 直接拒。**至少覆盖你在 `platforms` 声明的
  每个平台。**
- **Python / Node 依赖直接复用 `requirements.txt` / `package.json`**,不发明新格式。
  文件路径相对 kit 根。

### 4.3 依赖声明只在 skill 粒度生效

依赖不是 kit 级一次声明全局生效,而是**每个 skill 自己声明它需要什么**(`needs`)。

### 4.4 `env` — 需要用户提供的环境变量

```yaml
env:
  - name: OPENAI_API_KEY       # 必须匹配 ^[A-Z][A-Z0-9_]*$
    required: false            # true 时缺失会报错
    description: 用于 describe-video 的字幕润色,不填则跳过
```

这些变量在 `cckit exec` 时会被注入到 skill 脚本环境;`required: true` 且缺失时报错。

### 4.5 `skills[]`

```yaml
skills:
  - name: my-skill             # 必须与目录名一致
    needs: [ffmpeg, python]    # 依赖标签
    scripts: [scripts/run.py]  # 可选:相对 skill 目录的脚本路径
```

`needs` 的取值规则:

| 值 | 含义 |
|---|---|
| `python` | 触发建 venv 并装 `requires.python.file` |
| `node` | 触发建 node 环境并装 `requires.node.file` |
| 其他任意字符串 | 视为 `requires.system[].bin` 的引用,只做存在性检查 |
| `[]`(空数组) | 纯 prompt skill,**完全不建环境** |

引用了未在 `system` 声明的名字 → lint 报错。**声明 `needs: [python]` 但 `requires` 里
没写 `python.file`,会拿到一个空的 venv**,这是合法但通常不是你想要的。

`scripts[]` 必须**真实存在**(相对 skill 目录),否则语义检查报错。它同时也是
`cckit exec` 的执行白名单 —— 不在列表里的脚本路径会被拒绝。

### 4.6 `postinstall[]`

```yaml
postinstall:
  - run: scripts/setup.py      # 相对 kit 根
    when: always               # always(默认) / python / node
```

- `when: python` 表示只在建好 Python 环境后才执行;`node` 同理。
- **硬约束:postinstall 只允许写 kit 自己的目录和它的 env 目录。** 任何系统级操作
  必须改成 `requires.system` 声明(只检查、只提示)。违反这条会破坏可卸载性,
  也是安全红线。
- 这条约束靠**声明 + 用户确认**落实,不靠真沙箱 —— 所以别在脚本里做越界的事。

---

## 5. SKILL.md 的写法

### 5.1 frontmatter 里能写什么

cckit **不往你的 frontmatter 加任何自创字段**。原因:CC 之外(claude.ai 上传、
Skills API)只接受 6 个 spec 字段,多写别的字段是**硬报错**,不是忽略。

这 6 个字段是:`name`、`description`、`license`、`compatibility`、`metadata`、
`allowed-tools`。

- **想让 skill 未来能直接上传 claude.ai**,就只在这 6 个里选。
- `when_to_use`、`paths` 是 CC 原生字段,CC 本地能用,但不在上面 6 个里,
  上传 claude.ai 会被拒。只在纯 CC 场景下用它们。

推荐用 `paths` 做项目级自动激活(例如只在含 `*.mp4` 的项目激活),它比作用域开关更细,
且**不占清单预算**。

### 5.2 私有信息写进 `metadata`

cckit 需要知道"这个 skill 属于哪个 kit、哪个版本",但不加自创顶层字段,而是塞进
`metadata`(CC 会忽略 `metadata`):

```yaml
---
name: my-skill
description: ...
metadata:
  cckit_kit: my-kit           # 由 cckit 写入,作者不必手写
  cckit_version: 0.1.0
---
```

**作为作者,你不要手写 `cckit_kit` / `cckit_version`** —— 那是 cckit 安装时写入的。
你只需要做到"不往 frontmatter 加别的自创字段"。

### 5.3 description 是 CC 选工具的唯一依据

CC 靠 `description` 决定要不要把你的 skill 放进上下文、要不要调用它。所以:

- **必须非空**(lint error)。
- 两个 skill 描述太像,CC 会挑错那个,用户完全看不出原因 —— 这是最难 debug 的一类问题,
  所以安装时就会对"与已装 skill 语义重叠"告警。写 description 时避免和别人雷同。
- `description` + `when_to_use` 合计超过 **1536 字符**会被 CC 截断(lint warn)。
- 触发条件("Use when..."、"当用户…") 移进 `when_to_use`,别留在 description 里。

### 5.4 脚本怎么被调用

SKILL.md 里**不写解释器路径**(不可移植,Windows 是 `Scripts/python.exe`、
POSIX 是 `bin/python`)。统一写:

```bash
cckit exec my-skill scripts/run.py [args...]
```

cckit 会:找到该 skill 的 env → 按平台解析解释器 → 注入
`CCKIT_SKILL_DIR` / `CCKIT_KIT_DIR` / `CCKIT_ENV_DIR` 和 manifest `env` 里的变量 →
在**调用方 cwd** 下运行。你的脚本引用自身资源时用 `CCKIT_SKILL_DIR`,不要假设 cwd。

---

## 6. 安装时会卡你的 lint 规则

`cckit add` 在做任何事之前会跑 schema 校验 + 语义检查 + lint。以下是 lint 会**拦**的
(完整实现见 `src/cckit/lint.py`,都在 [manifest-spec](manifest-spec.md) 有对应):

| 检查 | 级别 | 说明 |
|---|---|---|
| skill 名大写 / 非法字符 | error | schema 的 slug pattern 只认小写 kebab-case |
| Windows 保留名 | error | `con` `prn` `aux` `nul` `com1`-`com9` `lpt1`-`lpt9` |
| 名为 `synced` | error | CC 保留目录(claude.ai 同步用) |
| 仅大小写不同的重名 | error | Linux 上是两个目录、Windows 上是一个,行为分裂 |
| description 缺失 | error | CC 靠它选工具 |
| description 含触发条件 | warn | 移到 `when_to_use` |
| description+when_to_use 超 1536 | warn | CC 会截断 |
| 与已装 skill 语义重叠 | warn | CC 可能挑错 |
| 文本文件含 CRLF | warn | Linux 上 `.sh` 会 bad interpreter |
| SKILL.md 疑似 prompt injection | warn | "ignore previous instructions"、读 `.env`、SSH 私钥、向外部 POST 数据等 |
| 依赖名疑似 typosquatting | warn | `reqeusts` / `numpyy` 这类 |

最后三条是安全相关的启发式警告。它们不会阻止
安装,但你应该把它们清干净 —— 你的 kit 是给陌生人装的,一个疑似注入的警告会吓跑用户。

---

## 7. 本地自检与发布

### 7.1 自检

在 kit 根目录:

```bash
# 方式一:走完整安装管线(校验 + lint + 计划),看到计划后按 N 取消即可
uv run cckit add ./my-kit --no-enable

# 方式二:只验 schema 与语义,快速定位
uv run cckit add ./my-kit --no-enable -y
```

校验失败会在**做任何事之前**中止并报出所有错误(含路径)。`-y` 会真的执行安装,
用于"确认它能装";只想验格式就 `--no-enable` 后按 `N`。

### 7.2 平台自检

如果你声明了 `platforms: [windows, linux, macos]`,但只在 Windows 上开发,请至少在
Linux(WSL 即可)上跑一遍 `cckit add`,重点看:

- `.sh` 脚本没有 CRLF(bad interpreter 只在 Linux 报错);
- 大小写敏感导致的目录名/脚本路径不一致(Windows 上不报,Linux 上崩);
- 脚本有没有可执行位(Windows 开发常漏)。

### 7.3 发布

1. 把 kit 推到一个 git 仓库(GitHub / Gitee / GitLab / 自建皆可)。
2. 打个 tag(如 `v0.1.0`)作为稳定版本。
3. **不要依赖分支名作为版本。** cckit 安装时会锁 commit sha 而非分支 —— 分支和 tag
   都能被事后移动,sha 不能。你后续改动 kit 时,老用户仍锁在旧 sha,除非他们主动
   `update`。
4. 在 README 写清:这个 kit 装什么、依赖什么系统二进制、postinstall 会做什么。
   —— 用户会在 cckit 展示的安装计划里看到这些,提前写清能建立信任。

---

## 8. 完整示例

参考 kit:[`examples/video-toolkit/`](examples/video-toolkit/)(也是测试夹具)。
它覆盖了系统依赖、Python 依赖、env、带脚本 skill + 纯 prompt skill、postinstall,
对照本文可看清每个字段的落位。

## 9. 常见错误清单

| 症状 | 原因 |
|---|---|
| `skill 'x' 缺少对应目录` | `skills[].name` 和目录名不一致(含大小写/连字符差异) |
| `needs 引用了未声明的系统依赖` | `needs` 里的名字没在 `requires.system[].bin` 声明 |
| `hint` 校验不过 | `hint` 写成了字符串,必须是 `{windows/linux/macos: ...}` map |
| `requires.python.file 指向的文件不存在` | `requirements.txt` 没放在 kit 根,或路径写错 |
| skill 名大写被拒 | schema 只认小写 kebab-case |
| 装进 Linux 后脚本跑不起来 | `.sh` 是 CRLF / 没可执行位(§7.2) |
| 用户反馈"装了但 CC 从不用" | description 缺失或超预算被静默丢弃(§5.3) |
