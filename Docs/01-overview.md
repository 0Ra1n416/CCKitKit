# CCKitKit 概览与定位

## 一句话

CCKitKit(命令名 `cckit`)是 Claude Code 的 **Skill 工具箱管理器**:从任意 git 仓库拉取
带环境依赖的 Skill,自动配置隔离环境,支持 skill 粒度的开关与干净卸载。

## 为什么需要它

Claude Code 2.1.245 原生已有 plugin + marketplace 系统,并且已经解决了不少事:任意 git 源、
子目录稀疏拉取、commit sha 锁定、skills/commands/agents/hooks/MCP 多组件打包。
**CCKitKit 不重复这些。** 它只填两个官方明确留空的缺口。

### 缺口一:环境配置是空白

实测证据:扫描官方 marketplace 全部插件,带 `requirements.txt` / `package.json` /
`pyproject.toml` 的数量为 **0**。

这不是生态没跟上,是平台**设计上不给这条路**。官方文档明确:

- 唯一的自动依赖安装限于 npm/bun,且必须有锁文件;
- 强制 `--ignore-scripts` + 冻结解析 + 60 秒超时;
- 原话:"no code from the plugin or its packages executes during it",
  以及 "You can't turn the automatic install off";
- `yarn.lock` 与 `pnpm-lock.yaml` 被**故意跳过**,因为它们支持能绕过
  `--ignore-scripts` 的解析期钩子;
- hook 事件列表中**不存在** `PluginInstall` / `PostInstall` 之类的安装期事件。

后果:Python 依赖、原生编译、系统级二进制,官方全部无解。作者只能自己写
`SessionStart` hook 比对 `package.json` 哈希再手动装——只覆盖 Node,且很笨。

> **CCKitKit 的核心功能,正是官方明确拒绝实现的那件事。**
> 这不代表不能做——我们是本机工具、用户自己装的,信任模型不同。但安全责任是官方
> 推给我们的,不是顺手接的。详见 [07-security.md](07-security.md)。

### 缺口二:skill 粒度开关拿不到

- `enabledPlugins` 是**插件级**布尔开关,无法只关插件里的某一个 skill。
- `skillOverrides` 提供 skill 粒度四档控制,但文档明确它**对 plugin skill 无效**,
  只作用于 personal / project skill。

后果:一个含 20 个 skill 的插件,你想只留 3 个,原生做不到。

CCKitKit 把 skill 装到 **personal / project 层**——恰好是 `skillOverrides` 唯一生效的层。
这不是巧合,是选定架构后拿到的红利,详见 [05-design-log.md](05-design-log.md) 的 D-03。
