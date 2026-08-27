# 架构

## 核心概念

| 概念 | 含义 |
|---|---|
| **kit** | 分发单位。一个 git 仓库 = 一个 kit,含 1..N 个 skill + 一份 `cckit.yaml` |
| **skill** | 使用单位。CC 实际调用的东西,开关粒度也在这一层 |
| **store** | kit 真实文件的存放地,全局唯一一份 |
| **env** | 每个 skill 独立的运行环境(venv / node_modules) |
| **link** | store 与 CC 扫描目录之间的目录链接。启用状态的物理载体 |

单个 skill 与 skill 集合**不分两套格式**,单个只是 N=1 的特例。理由见
[05-design-log.md](05-design-log.md) 的 D-05。

## 目录布局

```
~/.cckit/                          # 可被 CCKIT_HOME 覆盖
  store/<kit>/                     # git clone 的真实内容,含 cckit.yaml
    <skill>/SKILL.md
  envs/<kit>__<skill>/             # 每 skill 一个独立环境
  registry.json                    # 装了什么、装在哪、什么版本
  logs/

<CC 配置目录>/skills/<skill>        # link → store。全局启用
<项目>/.claude/skills/<skill>       # link → store。项目启用
<项目>/cckit.lock                   # 提交进 git,供团队复现
```

⚠️ `<CC 配置目录>` 必须通过 `CLAUDE_CONFIG_DIR` 解析,不可硬编码 `~/.claude`。

**store 全局唯一**:同一 kit 在多个项目启用时不重复下载、不重复装环境。
启用状态按作用域分别记录。

## 四态模型

这是 CCKitKit 最核心的设计。**link 与 `skillOverrides` 是正交的两层**,不是二选一:

- **link** 决定"哪些作用域能扫到它"
- **`skillOverrides`** 决定"扫到之后是什么状态"

| 状态 | link | skillOverrides | CC 看到的 |
|---|---|---|---|
| `installed` | ✗ | — | 什么都看不到 |
| `enabled` | ✓ | 无 / `on` | 名字 + description |
| `name-only` | ✓ | `name-only` | 只有名字,不占预算 |
| `off` | ✓ | `off` | 什么都看不到 |

`off` 与 `installed` 对 CC 的效果相同,但语义不同:`off` 保留在启用列表里,是"临时关";
`installed` 是"装了但没启用到任何地方"。

### disable 的两种实现

```
cckit disable <skill>            # 写 skillOverrides: off —— 默认
cckit disable <skill> --purge    # 删 link
```

默认走 `skillOverrides`:可逆、不动文件、瞬间生效。`--purge` 用于彻底移出扫描范围。

> 代价必须说清:走 `skillOverrides` 意味着 cckit 要写 CC 的 `settings.json`。
> 这与"独立体系、不碰 CC 配置"的初衷有张力。取舍理由见 D-03。

## 作用域

| 作用域 | link 位置 | skillOverrides 写入 |
|---|---|---|
| 全局 | `<CC 配置目录>/skills/` | `<CC 配置目录>/settings.json` |
| 项目 | `<项目>/.claude/skills/` | `<项目>/.claude/settings.local.json` |

项目级 `skillOverrides` 写 `settings.local.json` 而非 `settings.json`:后者会被提交,
而"我本机关掉这个 skill"是个人偏好,不该强加给同事。团队共享的意图由 `cckit.lock` 承载。

⚠️ 同名时**全局 skill 覆盖项目 skill**(见 06 的 2.3)。项目安装时必须检测并警告。

## 环境隔离

**每个 skill 一个独立 venv**,不是每个 kit 一个。

- 依赖冲突彻底隔离(kit A 要 `numpy<2`、kit B 要 `numpy>=2`,互不影响)
- 卸载 = 删目录,无残留
- 代价是磁盘占用,但 `uv` 有全局缓存,实际开销远小于直觉

用 `uv` 而非 `pip`:速度,且它能自己拉指定版本的 Python——省掉"请先装 Python 3.11"
这类死路。

**纯 prompt 类 skill 不创建 env。** 由 manifest 的 `needs: []` 表达,装它时完全不触发
环境安装。

## 状态真相来源

避免多处记录同一事实导致漂移:

| 事实 | 真相来源 |
|---|---|
| 装了哪些 kit / 版本 / 来源 sha | `registry.json` |
| 是否启用(某作用域) | **文件系统**(link 是否存在) |
| 是否 name-only / off | **CC 的 settings.json**(`skillOverrides`) |
| 团队期望装什么 | `cckit.lock`(提交进 git) |

启用状态不在 `registry.json` 里冗余存一份。`cckit list` 现场扫文件系统和 settings。
`cckit.lock` 记录的是**期望**,不是**现状**——这是它和 registry 的根本区别。

判据是**能否从文件系统观测出来**:观测不到的才存。理由见 D-13。

### 状态层 `cckit.state`

状态的读写**只允许**经由 `cckit.state`,调用方不得直接碰文件系统或 `settings.json`:

```
Web UI ─┐
        ├─→ cckit.state ─→ 文件系统 + settings.json
CLI    ─┘
```

这样 `list` 的扫描逻辑、以及写入时的加锁与原子替换,都只需实现一次。
CLI 的 `--json` 输出与 Web 的响应共用同一个 `list_skills()`,不存在两套逻辑。

⚠️ 写 `settings.json` 有三条硬要求(文件锁、原子替换、只改 `skillOverrides`),
不满足会导致丢失更新或损坏用户配置。完整契约与实测依据见
[09-state-api.md](09-state-api.md)。

## 脚本执行:`cckit exec`

skill 的脚本需要跑在自己的 venv 里。SKILL.md 里不写解释器路径(不可移植),
统一走:

```bash
cckit exec <skill> <script> [args...]
```

cckit 负责:

1. 查 registry 定位 skill 与其 env
2. 按平台解析解释器(`Scripts/python.exe` vs `bin/python`)
3. 注入环境变量:
   - `CCKIT_SKILL_DIR` — skill 自己的目录。**必需**,因为 CC 跑 Bash 时 cwd 是项目根,
     脚本引用自己的资源文件需要这个
   - `CCKIT_KIT_DIR`、`CCKIT_ENV_DIR`
   - manifest `env:` 段声明的变量
4. 记录用量(用于预算优化建议)
5. cwd **保持调用方的 cwd**,让用户给的相对路径正常工作

env 缺失时不静默失败,报错并提示跑 `cckit doctor`。

> 这个入口顺带给了我们一个真实的拦截点——用户最初设想的"总控 skill 拦截调用"在这里
> 才真正拿得到。但它只覆盖带脚本的 skill;纯 prompt skill 的开关仍靠可见性。详见 D-04。
