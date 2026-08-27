# CCKitKit 开发文档

`cckit` 是 Claude Code 的 **Skill 工具箱管理器**:从任意 git 仓库拉取带环境依赖的 Skill,
自动配置隔离环境,支持 skill 粒度开关与干净卸载。

## 文档索引

| 文档 | 内容 | 何时读 |
|---|---|---|
| [01-overview.md](01-overview.md) | 定位、要填的两个缺口及其证据 | 先读这个 |
| [02-architecture.md](02-architecture.md) | 目录布局、四态模型、作用域、环境隔离 | 核心设计 |
| [03-manifest-spec.md](03-manifest-spec.md) | `cckit.yaml` 完整规范 | 写 kit 或实现校验时 |
| [04-cli-spec.md](04-cli-spec.md) | 各命令的行为与必须拦截的情况 | 实现命令时 |
| [05-design-log.md](05-design-log.md) | 决策记录:改了什么、为什么 | **改动任何设计前必读** |
| [06-platform-findings.md](06-platform-findings.md) | 实测记录与待验证清单 | **动链接/路径代码前必读** |
| [07-security.md](07-security.md) | 威胁模型与不可省略的要求 | 实现 add / postinstall 前 |
| [08-installation.md](08-installation.md) | 分发方案与理由 | 打包发布时 |
| [09-state-api.md](09-state-api.md) | 状态层契约、并发要求、Web 接入 | **实现 list/开关 或 Web 前必读** |

配套:[`schema/cckit.schema.json`](schema/cckit.schema.json)、
[`examples/video-toolkit/`](examples/video-toolkit/)(参考 kit,应作为测试夹具)。

## 快速上手:7 件必须知道的事

1. **不重复造插件系统。** CC 原生已有 plugin + marketplace(git 源、sha 锁定、多组件打包)。
   cckit 只填两个官方留空的缺口:**环境配置**与**skill 粒度开关**。

2. **四态模型。** `installed` / `enabled` / `name-only` / `off`。
   link 决定"哪些作用域扫得到",`skillOverrides` 决定"扫到后什么状态"——**两者正交**。

3. **每 skill 一个独立 venv**,由 `uv` 管理。纯 prompt skill(`needs: []`)不建 env。

4. **脚本统一走 `cckit exec`。** SKILL.md 里不写解释器路径。它顺带是唯一可靠的拦截点。

   **状态读写统一走 `cckit.state`。** 启用状态是**派生**的(现场读文件系统 + settings),
   不落库——CC 不读我们的数据库,存了必然漂移。CLI 与 Web 共用这一层。见 D-13 / D-14。

5. **安装是确定性的,不调 LLM。** CC 只在 installer 失败时作为诊断兜底。理由见 D-01。

6. **安装前必须展示计划并等确认。** 我们在做官方明确拒绝做的事(跑安装脚本),
   这是与官方安全模型之间唯一的桥。见 [07](07-security.md)。

7. **几个静默失效的坑**,全都不报错:
   - `os.rmdir()` 删链接在 Linux 上报错 → 统一用 `os.unlink()`
   - 检测链接必须 `islink()` **和** `isjunction()` 都查(各在一个平台返回 False)
   - skill 清单超预算会**静默丢弃 description** → `list` 必须报预算
   - 同名时**全局 skill 覆盖项目 skill**,与 settings 优先级方向相反
   - `disableSkillShellExecution` 开启会让所有带脚本 skill 失效 → `doctor` 必查
   - 并发写 `settings.json` 会**丢失更新**(实测 8 个并发只活下来 1 条)→ 必须加锁
   - 开关改动**不影响已在运行的会话** → UI 别暗示"已生效"

## 当前状态

**v0.1 已实现**:`cckit` 命令行工具与全部 8 个命令(`add` / `list` / `enable` /
`disable` / `name-only` / `remove` / `doctor` / `exec`),`uv run cckit --help` 可用。

已落地模块(`src/cckit/`):

- `link.py` —— 跨平台链接层(create / is_link / remove / is_dangling)
- `config` / `schema` / `manifest` —— 配置解析、JSON Schema + 语义校验
- `env` —— uv venv / node env 与解释器解析
- `installer` —— add 全流程(锁 sha、计划确认、store/env/postinstall/registry/link)
- `exec` —— skill 脚本统一入口(白名单 + 环境变量注入)
- `state` —— 四态派生 + 文件锁 + 原子写 + 清单预算
- `registry` —— registry.json 原子读写
- `lint` —— 命名 / description / CRLF / prompt injection / typosquatting
- `doctor` —— 只读诊断 + 安全修复

测试:`tests/` 下 56 项,`uv run pytest -q` 全绿;`Docs/examples/video-toolkit` 作为夹具。

## v0.1 范围

命令:`add` / `list` / `enable` / `disable` / `name-only` / `remove` / `doctor` / `exec`

- 运行时只支持 Python(uv venv)与 Node
- 依赖文件复用 `requirements.txt` / `package.json`,不自创格式
- 四态开关、安装计划展示、`list` 报预算、`doctor` 全项检查
- `cckit.state` 状态层(含文件锁与原子写)。Web 界面本身推迟,但**状态层在 v0.1 就要做对**
  ——它是 Web 的接入点,事后补会导致两套逻辑

**推迟到 v0.2+**:`cckit.lock` 与 `sync`、`profile`、`update` 的 diff 展示、
用量统计。

## 约定

- 平台差异只允许存在于 `link.py` 之类的适配层,上层代码不写平台分支
- 新增平台相关结论前,先在 Windows 和 Linux 上各跑一遍,再写进
  [06](06-platform-findings.md);推断出来的结论必须标注为推断
- 改动既有设计前先读 [05](05-design-log.md) 对应记录,确认不是在重新踩坑
