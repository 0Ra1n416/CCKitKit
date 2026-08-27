---
name: kit-builder
description: 把开发者的普通 skill(一个带 SKILL.md 的目录或几个脚本)改造成符合 CCKitKit 规范的 kit:生成 cckit.yaml、整理目录结构、声明 python/node/系统依赖与环境变量,并自检通过校验。
---

# kit-builder

帮开发者把一个普通 skill 改造成**能被 cckit 安装的 kit**。kit 的唯一硬判据是
仓库根目录有一份合法的 `cckit.yaml`;本 skill 就是围绕这个目标做检查、补全、自检。

规范原文在 `./kit-authoring.md`(开发手册)与 `./manifest-spec.md`
(字段规范)。本 skill 附带的模板在 `templates/` 下。

## 什么时候用这个 skill

- 开发者说"把这个 skill 打包成 kit"、"让它能被 cckit 装"、"写个 cckit.yaml"。
- 开发者手上已有 skill 内容(SKILL.md + 可选脚本),需要补齐 kit 外壳。

## 流程

### 第 0 步:摸清现状

先确认开发者手上有什么:

1. skill 叫什么(目录名 / 现在的 skill 名)。
2. 有没有 SKILL.md?frontmatter 是否完整(`name` + 非空 `description`)?
3. 有没有脚本?脚本用什么语言(需不需要 Python / Node 环境)?
4. 依赖哪些 Python 包 / npm 包 / 系统二进制(ffmpeg、git、…)?
5. 需要用户提供哪些环境变量(API key 之类)?

问清楚再动手,别急着生成。

### 第 1 步:搭目录结构

产出最小结构(kit 根 = 将要成为 git 仓库的目录):

```
<kit-name>/
├── cckit.yaml
└── <skill-name>/
    ├── SKILL.md
    └── scripts/           # 如有脚本
```

硬规则:`skills[].name` 必须与目录名**逐字符一致**(小写 kebab-case);每个 skill 目录
下必须有 `SKILL.md`。

### 第 2 步:写 `cckit.yaml`

从 `templates/cckit.yaml` 抄一份,替换占位符。字段规则:

- **顶层必填**:`cckit: 1`、`kit`、`version`、`description`、`skills`。
- `kit` / `skills[].name` 都是小写 kebab-case,最长 64 字符,只含 `[a-z0-9]` 与 `-`。
- `version` 语义化版本,形如 `1.2.0`。
- `skills[].needs` 的取值:
  - `[]` —— 纯 prompt,不建环境。
  - `[python]` / `[node]` —— 触发建对应环境;此时 `requires.python.file` /
    `requires.node.file` 要指向 `requirements.txt` / `package.json`。
  - 其他字符串 —— 视为 `requires.system[].bin` 的引用,只做存在性检查。
- `requires.system[]` 里的 `hint` **必须是分平台 map**(`windows` / `linux` / `macos`),
  不能是单个字符串,且至少覆盖 `platforms` 声明的每个平台。
- `scripts[]` 相对 skill 目录,且**必须真实存在**。
- `env[]` 的 `name` 必须匹配 `^[A-Z][A-Z0-9_]*$`。

### 第 3 步:核对 SKILL.md

- `description` 非空(CC 靠它选工具,缺失是 error)。
- 触发条件("Use when..."、"当用户…") 放进 `when_to_use`,别留在 description。
- `description` + `when_to_use` 合计 ≤ 1536 字符。
- **不往 frontmatter 塞自创字段**。私有信息只进 `metadata`(CC 忽略它)。
- 脚本调用不写解释器路径,统一 `cckit exec <skill> <script> [args...]`;
  脚本引用自身资源用环境变量 `CCKIT_SKILL_DIR`。

### 第 4 步:过一遍会被拦的坑

生成前自查(完整清单见开发手册 §6):

- skill 名不含大写、不撞 Windows 保留名(`con` `prn` `aux` `nul` `com1-9` `lpt1-9`)、
  不叫 `synced`。
- 文本文件(尤其 `.sh`)用 LF,别留 CRLF。
- SKILL.md 别出现「要求忽略既有指令」、读取 `.env`、访问 SSH 私钥、
  向外部地址上传数据等可疑字样(会被提示 prompt injection)。
- `requirements.txt` / `package.json` 里的依赖名没有 typosquatting(`reqeusts` 之类)。
- postinstall 只写 kit 自己的目录与其 env,系统级操作改声明为 `requires.system`。

### 第 5 步:自检

在 kit 根目录跑,把报错逐条修到干净:

```bash
uv run cckit add ./<kit-name> --no-enable
```

校验/ lint 失败会在做任何事之前中止并报出全部错误。看到安装计划后按 `N` 取消
(除非开发者要真装)。

## 注意

- 如果开发者还没有 skill 内容、只想从零写一个,先按上面的结构补 SKILL.md,
  再走流程。
- 改动开发者已有文件前先展示你要写的内容;别静默覆盖对方的 `SKILL.md`。
- 平台相关建议(系统依赖 hint、可执行位、LF)要覆盖开发者在 `platforms` 声明的全部平台。
