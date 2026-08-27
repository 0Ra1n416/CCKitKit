# 平台实测记录

本文档记录**实际跑过的验证**,不是推断。每条都标注验证方式。
后续开发时若与此冲突,请先重跑验证再改结论——这些坑大多**不报错,只静默失效**。

验证环境:
- Windows 11 Pro 26200,Claude Code 2.1.245,Python 3.13.12
- WSL Ubuntu-26.04,Python 3.14.4

---

## 1. 链接机制

### 1.1 Windows 上 symlink 需要管理员,junction 不需要

```powershell
New-Item -ItemType Junction      ...  # → OK
New-Item -ItemType SymbolicLink  ...  # → 失败:此操作要求提升权限
```

**这一条决定了 Windows 必须用 junction。** 否则用户每次 `cckit enable` 都要提权。

### 1.2 CC 能穿透链接发现 skill(架构可行性的关键验证)

做法:在 `.claude/skills/` 下建 junction 指向别处的真实 skill 目录,skill 的
description 里埋唯一标记词,然后 `claude -p` 让 CC 列出可用 skill。

结果:CC 报回了 junction 后面的 skill 名,并确认看到了标记词。**CC 侧零改动。**

这是整个 store + 链接架构成立的前提。

### 1.3 三个平台差异(全部实测)

| 操作 | Windows | Linux |
|---|---|---|
| 创建 | `_winapi.CreateJunction(target, link)` | `os.symlink(target, link)` |
| 删除 | `os.unlink` ✅ / `os.rmdir` ✅ | `os.unlink` ✅ / `os.rmdir` ❌ |
| `os.path.islink()` | **False** | True |
| `os.path.isjunction()` | True | False |

两个致命点:

- **`os.rmdir()` 在 Linux 上删 symlink 抛 `NotADirectoryError`(errno=20)。**
  统一用 `os.unlink()`,两平台都可用。
- **检测必须两个函数都查。** 只查 `islink()` 会在 Windows 漏判,只查
  `isjunction()` 会在 Linux 漏判。漏判的后果是 cckit 把自己装的 skill 当成用户手写的,
  拒绝管理它,且**不报错**。

差异已封装在 `src/cckit/link.py`(4 个函数),上层不应再出现平台分支。

### 1.4 两个安全行为(好消息,可依赖)

两平台**都拒绝**在已存在的目录上建链接:

- Windows:`OSError` winerror **183**
- Linux:`FileExistsError`

即 cckit 不可能静默覆盖用户手写的 skill。但调用方仍应先判断 `exists()` 再给出
友好提示,而不是把裸异常抛给用户。

**删链接不会删穿。** 实测 `os.unlink()` 后目标目录内文件完好。
⚠️ 但**永远不要用 `shutil.rmtree()` 删链接**——它的语义是"递归删内容",
一旦哪天在某平台跟随了链接就会删穿到 store 源码。这是数据丢失级的坑。

### 1.5 悬空链接可检出

目标被删后:`lexists()` → True,`exists()` → False,`islink/isjunction` → True。
`cckit doctor` 用这个组合找残留。

### 1.6 `_winapi.CreateJunction` 可用

Python 3.13.12 实测存在。它是 CPython 私有 API(CPython 自测套件在用,稳定),
但已在 `link.py` 里加了 `mklink /J` 的 subprocess 兜底。

**Python 下限 3.12+**,因为 `os.path.isjunction()` 是 3.12 引入的。
`uv` 会自己拉合适的 Python,不构成用户负担。

---

## 2. CC 的 skill 加载行为

### 2.1 `skillOverrides` 四档实测

在 `.claude/settings.json` 写 `{"skillOverrides": {"probe-off": "off",
"probe-nameonly": "name-only"}}`,然后让 CC 报告它看到了什么:

| 状态 | 名字可见 | description 可见 |
|---|---|---|
| 默认 / `on` | 是 | **是**(标记词被读到) |
| `name-only` | 是 | **否**(标记词读不到) |
| `off` | **否** | 否(整条从列表消失) |

第四档 `user-invocable-only` 未实测。

`name-only` 是有用的第三态:CC 知道工具存在、用户可 `/skill-name` 手动调用,
但 description 不占清单预算。

**限制(文档):`skillOverrides` 对 plugin skill 无效**,只作用于 personal / project skill。

### 2.2 ⚠️ skill 清单有预算,超了静默丢弃 description

文档结论(未实测,但影响设计):

- 会话启动只加载**名字 + description 清单**,不加载正文;
- 清单预算 = **模型上下文窗口的 1%**;
- 超预算时**名字全部保留,description 从"最少被调用"的开始丢**;
- description + `when_to_use` 合计在清单里**截断于 1536 字符**;
- 可调键:`skillListingBudgetFraction`、`skillListingMaxDescChars`。

**这是设计级约束。** 工具箱变大后,新装 skill 的 description 可能根本没进上下文——
CC 看得到名字但不知道何时该用它,表现为"装了但 CC 从不用",且**无任何提示**。

因此 `cckit list` / `cckit add` 必须报预算占用。这不是锦上添花,是防止工具箱静默退化。

### 2.3 ⚠️ 同名冲突优先级是"全局盖项目"

文档:**enterprise > personal > project**。

即全局 skill **覆盖**项目 skill,不是直觉的反向。后果:全局装了 `burn-subtitles`,
项目想用改过的版本,项目版**不生效且无提示**。`cckit` 必须在项目安装时检测同名全局
skill 并明确警告。

⚠️ 注意这与 **settings 的优先级方向相反**(settings 是 managed > CLI > 项目 local >
项目 > 用户)。两套规则别记混。

### 2.4 frontmatter 可移植性:CC 外只允许 6 个字段

CC 之外(claude.ai 上传、Skills API、`package_skill.py`)只接受
`name` `description` `license` `compatibility` `metadata` `allowed-tools`,
多写别的字段是**硬报错**,不是忽略。

因此 **cckit 不往 frontmatter 加任何自创字段**,私有信息只塞进 `metadata`(CC 忽略它)。
白拿的好处:cckit 装的 skill 仍可直接上传到 claude.ai。

### 2.5 其他相关键与保留名

- `disableSkillShellExecution`:开启后**所有带脚本的 skill 静默失效**。
  `cckit doctor` 必须检查它,否则用户会遇到"脚本莫名不执行"。
- `synced/` 是**保留目录名**(claude.ai 同步用),cckit 绝不能占用或写入。
- 配置目录**不可硬编码** `~/.claude`:CC 二进制中 `CLAUDE_CONFIG_DIR` 出现 55 次、
  `XDG_CONFIG_HOME` 出现 26 次,说明可重定向。准确回落顺序**尚未实测**,
  实现时必须先验证。

### 2.6 改开关不影响已在运行的会话(部分结论)

做法:建 link → 让 CC 确认看到该 skill → **会话进行中**删掉 link →
`--resume` 同一会话再问。

结果:CC 仍报告能看到。

⚠️ 该结论需打折扣:用的是 `--resume`,无法完全区分"CC 缓存了 skill 清单"与
"模型只是记得自己刚才的回答"。两者对 UI 的结论相同(不要暗示"已生效"),
但机制不明,`reloadSkills` 相关行为仍需单独验证。

---

## 3. 性能与并发(为状态层而测)

### 3.1 扫描式状态查询足够快

200 个 skill(远超真实规模)、一半启用,完整枚举 + 判链接 + 读 frontmatter +
合并 `skillOverrides`:

```
中位 6.7 ms | 最快 6.2 ms | 最慢 8.0 ms
```

结论:**不需要缓存。** 详见 [09-state-api.md](09-state-api.md)。

### 3.2 ⚠️ 并发写 settings.json 会丢失更新

8 个进程并发做 read-modify-write:

```
无锁                                  → 8 条只活下来 1 条
os.open(O_CREAT|O_EXCL) 加锁 + os.replace → 8 条完整保留
```

`O_CREAT|O_EXCL` 是跨平台原子操作,不需要 `fcntl` / `msvcrt` 分支。**已实测有效。**

这是 Web 接入下最容易踩且最难定位的坑,表现为"关了它,刷新后又开着"。

### 3.3 JSON Schema 校验链路可用

`yaml.safe_load()` → `jsonschema.Draft202012Validator` 可直接校验 YAML manifest。
实测对故意写坏的 manifest 一次性报出全部 5 处错误(含位置),
对 `Docs/examples/video-toolkit/cckit.yaml` 报 0 错误。

---

## 4. 其他跨平台注意点

- **venv 布局**:Windows `.venv/Scripts/python.exe`,POSIX `.venv/bin/python`。
  这是 `cckit exec` 存在的理由之一——SKILL.md 里不写解释器路径。
- **大小写敏感**:Linux 上 `Foo` 与 `foo` 是两个目录(已实测),Windows 上是一个。
  故 skill 名强制小写 kebab-case,lint 拒大写。否则同一 kit 在 Linux 装出两个 skill、
  在 Windows 装出一个。
- **换行符**:CRLF 的 `.sh` 在 Linux 上以 `bad interpreter` 失败。lint 检查 LF。
- **Windows 保留名**:`con` `prn` `aux` `nul` `com1..9` `lpt1..9` 不能作 skill 名。
- **可执行位**:POSIX 下脚本需要 exec bit;若 kit 作者在 Windows 开发可能未设置。

---

## 5. 待验证清单(实现前必须补)

- [ ] `CLAUDE_CONFIG_DIR` / `XDG_CONFIG_HOME` 的准确回落顺序
- [ ] `skillOverrides` 第四档 `user-invocable-only` 的实际行为
- [ ] 清单预算超限时的真实表现(需装到足够多 skill 才能触发)
- [ ] 会话中途改动的生效机制(2.6 只得到部分结论;需验证 `SessionStart` 的
      `reloadSkills: true` 与 `ConfigChange` 事件能否用于主动重载)
- [ ] macOS 上的行为(本次未验证,理论同 Linux 分支)
- [ ] 陈旧锁的清理策略(进程崩溃留下 `.lock` 时的超时阈值)
