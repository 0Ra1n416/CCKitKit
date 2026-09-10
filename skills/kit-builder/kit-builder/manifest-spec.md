# cckit.yaml 规范

每个 kit 仓库根目录必须有一份 `cckit.yaml`。**没有它,`cckit add` 直接拒绝**——
这是"合法 kit"的唯一判据。

## 完整示例

```yaml
cckit: 1                        # manifest 格式版本,必填

kit: video-toolkit              # kit 标识,小写 kebab-case,必填
version: 1.2.0                  # 语义化版本,必填
description: 视频处理工具集      # 必填
author: someone
homepage: https://github.com/someone/video-toolkit
license: MIT

# 支持的平台。缺省视为全平台。当前平台不在列表内时 add 直接拒绝,
# 不会等到装完才发现跑不了。
platforms: [windows, linux, macos]

requires:
  runtime:
    python: ">=3.11"            # uv 会按此拉取,用户无需预装
  # 系统级依赖:只检查存在性 + 给提示,绝不自动安装(见 D-02)
  system:
    - bin: ffmpeg               # 用 `ffmpeg --version` 之类探测
      hint:                     # 必须分平台。只写 winget 是 Windows-only 错误
        windows: winget install ffmpeg
        linux: sudo apt install ffmpeg   # 或 dnf / pacman
        macos: brew install ffmpeg
  python:
    file: requirements.txt      # 直接复用标准文件,不自创依赖格式
  node:
    file: package.json

# kit 共用的环境变量。只声明"要什么",**值由用户自己填**
# (存在 <cckit 数据目录>/envs.json,由 cckit exec 注入)。缺失且 required 时报错。
kit_env:
  - name: OPENAI_API_KEY
    required: false
    description: 用于 describe-video 的字幕润色,不填则跳过该步骤

skills:
  - name: burn-subtitles        # 必须与 skill 目录名一致
    needs: [ffmpeg, python]     # 依赖在 skill 粒度声明
    scripts: [scripts/burn.py]  # 供 lint 校验与 exec 白名单
    env:                        # 该 skill 专属的环境变量;与 kit_env 同名时以这里为准
      - name: FONT_DIR
        required: true
        description: 字幕字体所在目录
    conf_files: [config.json]   # 相对 skill 目录;声明"这个文件用户可以改"
  - name: describe-video
    needs: []                   # 纯 prompt,装它不触发任何环境安装

postinstall:
  - run: scripts/setup.py       # 只允许操作 kit 自己的目录(见 D-02)
    when: always                # always | python | node
```

## 字段参考

### 顶层

| 字段 | 必填 | 说明 |
|---|---|---|
| `cckit` | ✓ | manifest 格式版本。当前只接受 `1` |
| `kit` | ✓ | 小写 kebab-case。store 目录名 |
| `version` | ✓ | 语义化版本 |
| `description` | ✓ | 一句话说明 |
| `platforms` | | `windows` / `linux` / `macos` 的子集,缺省全平台 |
| `requires` | | 环境需求,见下 |
| `kit_env` | | kit 共用的环境变量声明,见下 |
| `skills` | ✓ | 至少一个 |
| `postinstall` | | 安装后钩子 |

`author` / `homepage` / `license` 为可选元数据。

### `kit_env[]` 与 skill 的 `env[]`

两者形状相同,都是**只声明、不提供值**:

| 字段 | 必填 | 说明 |
|---|---|---|
| `name` | ✓ | 变量名,必须匹配 `^[A-Z][A-Z0-9_]*$` |
| `required` | | 缺省 `false`。为 `true` 且用户没填、环境里也没有 → `cckit exec` 报错中止 |
| `description` | | 用途说明。CLI / Web 都拿它当提示文案,**建议写** |

- `kit_env` 是 **kit 级**:整个 kit 共用,值填一次即可。
- skill 里的 `env` 是 **skill 级**:只对该 skill 生效。同名时 **skill 级覆盖 kit 级**。
- ⚠️ **不要在这里写值。** manifest 里没有 `value` / `default` 字段 —— 值一律由用户
  在 `cckit env <skill> <NAME> <VALUE>` 或 Web 面板里填,存在 `<cckit 数据目录>/envs.json`。
  这样能杜绝"作者把自己的密钥提交进仓库、再分发给所有用户"。
- 只在脚本里读环境变量(`os.environ` / `process.env`)即可,不需要额外的读取代码:
  `cckit exec` 会在拉起脚本时注入。

### skill 的 `conf_files[]`

一个字符串数组,每项是**相对 skill 目录**的路径,声明"这个文件用户可以改"。

- 路径必须落在 skill 目录内:拒绝绝对路径与 `..` 逃逸(lint 与 `semantic_check` 都会拦)。
- 文件**必须真实存在**(通常随仓库带一份默认值),否则安装被拒绝。
- 用途是**展示与编辑**:`cckit list --confs` 会列出来,Web 面板可以预览和修改。
  cckit 不会读取或解析它,怎么用这个文件由你的脚本决定。
- ⚠️ 文件就放在 skill 目录里,**`cckit remove`(以及重装)会连同 store 一起删掉**,
  用户改过的内容会丢。需要长期保留的数据请让脚本写到用户自己的目录,不要依赖这里。

### `requires.system[]`

| 字段 | 必填 | 说明 |
|---|---|---|
| `bin` | ✓ | 可执行文件名,用于 PATH 探测 |
| `hint` | ✓ | **必须分平台的 map**,至少覆盖 `platforms` 声明的每个平台 |
| `version` | | 版本约束。需配 `version_cmd` |
| `version_cmd` | | 取版本的命令,缺省 `<bin> --version` |

`version` 声明后,`cckit add` 会用 `version_cmd`(缺省 `<bin> --version`)实测版本并按
PEP 440 约束(如 `>=6.0`、`~=6.0`、`==6.*`,逗号分隔为 AND)比对;不满足或无法验证会
列入安装计划提示,不阻断安装。

⚠️ 安全约束:`version_cmd` 只允许只读的版本查询,形如 `<bin> <版本标志>` ——
`<bin>` 必须与 `bin` 字段一致,`<版本标志>` 仅限 `--version` / `-V` / `-v` /
`version` / `-version`。任何其它命令(多参数、别的标志、别的二进制、管道/重定向)
一律拒绝:**不执行**,改为报 warn 让你手动核对版本。这是因为 version_cmd 会在用户
确认安装前就运行,必须堵住"作者塞任意命令"的口子。

⚠️ `hint` 写成单个字符串会被 lint 拒绝。

### `skills[]`

| 字段 | 必填 | 说明 |
|---|---|---|
| `name` | ✓ | 必须与 skill 目录名**完全一致**。小写 kebab-case |
| `needs` | ✓ | 依赖标签数组。空数组表示纯 prompt skill,**不建 env** |
| `scripts` | | 相对 skill 目录的脚本路径,供 lint 与 `exec` 白名单 |
| `env` | | 该 skill 专属的环境变量声明,见上 |
| `conf_files` | | 相对 skill 目录、可供用户修改的配置文件,见上 |

`needs` 的取值:`python` / `node` 触发对应环境安装;其余值视为
`requires.system[].bin` 的引用,只做存在性检查。引用了未声明的名字 → lint 报错。

一个 skill **可同时**声明 `python` 与 `node`(如 `needs: [python, node]`):
两者各自建独立 env,互不干扰;`cckit exec` 按脚本扩展名自动选解释器
(`.py` → python、`.js` / `.mjs` → node)。

### `postinstall[]`

| 字段 | 必填 | 说明 |
|---|---|---|
| `run` | ✓ | 相对 kit 根的脚本路径 |
| `when` | | `always`(默认)/ `python` / `node`,后两者仅在对应环境建好后执行 |

**硬约束:postinstall 只允许写 kit 自己的目录与其 env 目录。** 任何系统级操作必须
改为 `requires.system` 声明。违反此约束会破坏可卸载性。

## skill 名的额外约束

除小写 kebab-case 外,lint 还拒绝:

- **Windows 保留名**:`con` `prn` `aux` `nul` `com1`-`com9` `lpt1`-`lpt9`
- **仅大小写不同的重名**:Linux 上是两个目录、Windows 上是一个,行为会分裂
- **`synced`**:CC 的保留目录名(claude.ai 同步用)

## SKILL.md 的约束

cckit **不往 frontmatter 加任何自创字段**。私有信息只写进 `metadata`(CC 忽略它):

```yaml
---
name: burn-subtitles
description: ...
metadata:
  cckit_kit: video-toolkit      # 由 cckit 写入,作者不必手写
  cckit_version: 1.2.0
---
```

原因:CC 之外(claude.ai 上传、Skills API)只接受 6 个 spec 字段,多写别的是**硬报错**。
这样，cckit 装的 skill 仍可直接上传到 claude.ai。

推荐作者使用 `paths` 字段做项目级自动激活(如只在有 `*.mp4` 的项目激活),
它比作用域级开关更细,且不占清单预算。

## description 的 lint 规则

`cckit add` 时检查每个 skill 的 description:

| 检查 | 级别 | 阈值 |
|---|---|---|
| 含触发条件(如 "Use when...") | warn | — |
| 长度 | warn | description + `when_to_use` 合计 > 1536 字符会被 CC 截断 |
| 与已装 skill 语义重叠 | warn | 见下 |
| 缺失 | error | CC 靠它选工具 |

description 是 CC 选工具的**唯一**依据。两个 skill 描述太像,CC 会挑错那个,
而用户完全看不出原因——这是最难 debug 的一类问题,所以会在安装时就拦截。
