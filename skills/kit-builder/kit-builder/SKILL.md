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

### 第 0 步:摸清现状(**以扫代码为准,不只是问**)

**很多时候没有开发者可以问**(例如 cckit 的 `--alt` 流程把你放进一个临时仓库,
周围只有代码)。所以第 0 步的动作是**读仓库**,不是列问题:

1. 有哪些 skill?(带 `SKILL.md` 的一级子目录;根目录本身就是 skill 的情况也要认。)
2. 有哪些脚本?什么语言?
3. 依赖:Python 包 / npm 包 / 外部命令(看 `requirements.txt`、`package.json`、
   以及脚本里的 `import` / `require` / 实际调用的命令)。
4. **需要用户提供哪些环境变量** —— 必须逐个脚本搜,见下节。
5. **哪些文件是用户可以改的配置文件** —— 同上。

有开发者在场时,可以拿这份清单去确认;没有就自己扫完直接往下走。
**第 4、5 项最容易漏**:只看 README 通常会漏掉脚本里真正读的东西,
而漏声明的后果是用户装完看不出缺什么,直到脚本跑崩。

#### 找环境变量:逐个脚本搜,别凭印象

按语言搜读取点(把每个 skill 的脚本都过一遍):

| 语言 | 常见写法 |
|---|---|
| Python | `os.environ["X"]`、`os.environ.get("X")`、`os.getenv("X")` |
| Node / JS | `process.env.X`、`process.env["X"]` |
| Shell | `$X`、`${X}`、`${X:-默认值}` |

**先排除 cckit 自己注入的那几个**,它们不需要声明:
`CCKIT_SKILL_DIR`、`CCKIT_KIT_DIR`、`CCKIT_ENV_DIR`、`NODE_PATH`。

**只对 `scripts[]` 里的脚本声明** —— 这些变量由 `cckit exec` 在**拉起脚本时**注入。
两个地方读不到,所以不要为它们声明:

- `postinstall` 阶段:那时只注入 `CCKIT_KIT_DIR`,声明了也不会生效;
- 纯 prompt skill(没有脚本):没有任何东西会去读它。

对搜出来的每个变量,判断两件事:

**① 放 `kit_env` 还是放到某个 skill 的 `env`?**

- 被**两个及以上** skill 的脚本读 → `kit_env`(kit 共用,用户填一次)
- 只被**一个** skill 读 → 该 skill 的 `env`
- `kit_env` 是整个 kit 共用的,放错会让"缺值"提醒出现在所有 skill 上,所以拿不准时
  倾向放到 skill 级

**② `required` 填什么?**

- 取不到就走错误分支(抛异常 / `sys.exit(1)` / `process.exit(1)` / 打印错误后中止)→ `true`
- 取不到就用默认值,或**跳过某一步骤**继续跑 → `false`

变量名**原样照抄**脚本里的写法(`[A-Z][A-Z0-9_]*` 之外的名字本来就是非法的,
遇到了说明这个名字需要改,而不是照抄)。

#### 找用户可改的配置文件:看脚本读了什么

搜脚本里读文件的地方(`open(...)`、`json.load`、`yaml.safe_load`、`readFileSync`、…),
看它读的是不是**相对 skill 目录**的路径(通常由 `CCKIT_SKILL_DIR` 或脚本自身位置拼出来)。

**三条同时满足**才进 `conf_files`:

1. 文件**随仓库存在**(作者带了一份默认值)—— 校验会检查存在性,不存在会被拒;
2. 内容是**给用户调参数**的(阈值、格式、模型名、目录、开关、映射表);
3. 路径**相对 skill 目录**(绝对路径与 `..` 会被拒)。

**这些不要放进 `conf_files`:**

- 脚本的**产物**(报告、缓存、日志)—— 不是给用户改的;
- `requirements.txt` / `package.json` —— 它们走 `requires`;
- `SKILL.md` 本身;
- 测试数据、示例、fixture;
- 路径在 skill 目录**之外**的任何文件。

#### 两条硬规矩

- **不臆造**:只声明代码里**真的出现**的东西。判断标准很机械 —— 这个名字在脚本里
  出现过就声明,没出现就不声明。不要用"可能用于…""也许需要…"这种措辞。
- **不写值**:环境变量只有 `name` / `required` / `description`。**永远不要**把任何
  实际值写进 `cckit.yaml` —— 写了就会随仓库分发给所有用户,密钥尤其致命。

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
- `conf_files[]` 相对 skill 目录,**必须真实存在**且不得用绝对路径或 `..` 逃逸。
- `env[]`(skill 级)与 `kit_env[]`(kit 级)的 `name` 必须匹配 `^[A-Z][A-Z0-9_]*$`;
  两者**都只有 `name` / `required` / `description` 三个字段,没有 `value` / `default`**
  —— 值由用户自己填,别把密钥写进 manifest。

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

**先做不需要任何命令的反向核对** —— 这一步最常发现遗漏,务必做:

- 再搜一遍所有脚本的环境变量读取点,确认**每一个**都已经出现在 `kit_env` 或
  某个 skill 的 `env` 里(漏一个,用户就得等脚本跑崩才知道);
- 再搜一遍所有脚本读的文件,确认该进 `conf_files` 的都在,且每条路径都**真实存在**、
  都在 skill 目录内;
- 确认 `cckit.yaml` 里**没有任何值**,只有 `name` / `required` / `description`。

然后(若当前环境能调用 `cckit`)跑一次真实校验:

```bash
cckit add <kit 目录>
```

⚠️ **绝对不要加 `-y`。** `add` 没有"只校验"模式,`-y` 会真的把 kit 装进用户的 store。
它会先展示执行计划再等确认,在提示处回答 `N` 取消即可;schema / 语义 / lint 的报错
在做任何事之前就会全部打出来,失败也不会留下残留。

调不到 `cckit` 命令时(例如尚未安装)跳过这条,靠上面的反向核对 + 逐条对照
`manifest-spec.md` 与开发手册 §6 自查。**宁可不跑,也不要为了"跑通"而加 `-y`。**

## 注意

- 如果开发者还没有 skill 内容、只想从零写一个,先按上面的结构补 SKILL.md,
  再走流程。
- 改动开发者已有文件前先展示你要写的内容;别静默覆盖对方的 `SKILL.md`。
- 平台相关建议(系统依赖 hint、可执行位、LF)要覆盖开发者在 `platforms` 声明的全部平台。
