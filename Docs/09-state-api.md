# 状态层与 Web 接入

`cckit.state` 是**唯一**允许读写 skill 状态的模块。CLI 与 Web 都只能走它,
不允许任何调用方直接碰文件系统或 `settings.json`。

## 为什么状态是"派生"的,不是"存储"的

CC 决定加载哪些 skill 时只看两处:`skills/` 目录下有什么、`settings.json` 的
`skillOverrides` 写了什么。**它不知道 cckit 存在**,不会读 `registry.json`。

所以若把"是否启用"存进数据库,会出现:

```
数据库    burn-subtitles = enabled
文件系统  link 不存在
CC 实际   不加载
```

数据库说的话没人听——它不是真相来源,只是一份可能过期的副本。
而 `cckit list` 的职责恰恰是回答"CC 现在实际会加载什么"。

这是声明式状态 vs 观测状态的区别:`cckit.lock` 是**声明**(期望装什么),
文件系统是**观测**(实际是什么)。两者都要,但不能混为一谈。

### 漂移是必然,不是边缘情况

以下每一种都会让存储的状态说谎,且全部是用户的合法操作:

- 手动删了 `skills/` 下的目录
- 自己编辑了 `skillOverrides`
- 同事改了项目配置,你 `git pull` 下来
- CC 升级,或 `CLAUDE_CONFIG_DIR` 变了
- cckit 在"写存储"与"写文件系统"之间崩溃

存了之后仍需 `reconcile` 去对比、且必须以文件系统为准——那不如一开始就直接读文件系统。

## 存储 vs 派生的划分

判据:**能否从文件系统观测出来。**

| 数据 | 位置 | 理由 |
|---|---|---|
| 装了哪些 kit、版本、sha、来源 | `registry.json` | 观测不出来,必须存 |
| env 路径与运行时类型 | `registry.json` | 同上 |
| 用量统计 | `registry.json` | 同上 |
| 团队期望装什么 | `cckit.lock` | 这是声明,不是现状 |
| **是否启用 / name-only / off** | **文件系统 + settings.json** | 观测得到,存了会漂移 |

## API 契约

```python
# cckit/state.py

@dataclass
class SkillState:
    name: str
    kit: str | None                 # 非 cckit 管理时为 None
    scope: Literal['global', 'project']
    state: Literal['installed', 'enabled', 'name-only', 'off']
    managed: bool                   # False = 用户手写或插件带的,只读
    env_ok: bool | None             # None = 该 skill 无需 env
    desc_chars: int                 # 用于预算统计
    version: str | None

def list_skills(scope=None) -> list[SkillState]: ...
def get_state(name, scope) -> str: ...
def set_state(name, state, scope) -> None: ...        # 带锁 + 原子写
def budget() -> tuple[int, int]: ...                  # (已用字符, 上限)
```

`list_skills()` 必须同时列出**非 cckit 管理**的 skill,标记 `managed=False`。
用户看到的是完整工具箱视图,但只有 cckit 装的能被开关。

## `registry.json` 结构

唯一的持久化存储。只放**观测不出来**的东西。

```json
{
  "version": 1,
  "kits": {
    "video-toolkit": {
      "source": {
        "url": "https://github.com/someone/video-toolkit",
        "ref": "v1.2.0",
        "sha": "30287f5e3f122a646d1ac5ca3ab96e130c52a3ad"
      },
      "version": "1.2.0",
      "installed_at": "2026-08-27T02:10:00Z",
      "store": "~/.cckit/store/video-toolkit",
      "skills": [
        { "name": "burn-subtitles", "env": "~/.cckit/envs/video-toolkit__burn-subtitles",
          "runtime": "python", "needs": ["ffmpeg", "python"] },
        { "name": "describe-video", "env": null, "runtime": null, "needs": [] }
      ],
      "known_scopes": ["global", "C:/work/proj-a"]
    }
  }
}
```

### `known_scopes` 不是启用状态

它记录的是"**cckit 曾在哪些作用域安装过这个 kit**",作用是给 `remove` 和 `doctor`
一份"该去哪些位置找 link"的索引。**是否启用仍然靠现场检查 link 是否存在。**

没有它,`cckit remove` 无法知道要去哪些项目目录清理残留 link。

### 用量统计单独存文件,不放 registry

若放进 `registry.json`,则每次 `cckit exec` 都要加锁改写 registry——
脚本调用频率远高于安装操作,会造成写放大与锁竞争。

用量写 `~/.cckit/usage.jsonl`(追加式,无需读改写,天然并发安全)。

## 性能:扫描足够快,不要加缓存

实测 200 个 skill(远超真实规模)、一半启用,做完整枚举 + 判链接 + 读 frontmatter +
合并 overrides:

```
中位 6.7 ms | 最快 6.2 ms | 最慢 8.0 ms
```

Web 请求里无感。为省这几毫秒引入会漂移的缓存是亏本交易。
若日后确有必要,只改 `state.py` 内部,调用方不受影响。

## `set_state()` 的三条硬要求

### 1. 文件锁(否则丢失更新)

实测 8 个进程并发对 `settings.json` 做 read-modify-write:

```
无锁: 8 个并发写 → 最终只保留 1 条   ← 丢了 7 条
加锁: 8 个并发写 → 完整保留 8 条
```

Web 下极易触发:用户快速连点几个开关,或一边点网页一边跑 CLI。
表现是**"我明明关了它,刷新后又开着"**——这种 bug 极难复现定位。

⚠️ **换成数据库并不能免除此问题**,因为最终仍要写 `settings.json`(CC 只读它)。
数据库只会多一个写入点和一处可能不一致的地方。

推荐实现:`os.open(lock, O_CREAT|O_EXCL|O_WRONLY)`——跨平台原子操作,
不需要 `fcntl`(POSIX)/ `msvcrt`(Windows)分支。已实测有效。

需处理陈旧锁:进程崩溃会留下锁文件。加超时(如 10 秒)+ 检查锁文件 mtime 后强制清理。

### 2. 原子替换(否则可能损坏配置)

写临时文件再 `os.replace()`。直接覆写时若进程中途死掉,会留下半截 JSON,
**CC 将完全无法读取 settings**——这是用户可见的严重故障。

### 3. 只改 `skillOverrides`,其余键原样保留

`settings.json` 里有用户自己的配置(`model`、`env`、`permissions` 等)。
必须读入完整 dict、只改这一个键、再写回。整份覆盖会毁掉用户配置。

## Web 接入注意点

### 改开关不影响已在运行的会话

实测:建 link 让 CC 确认能看到某 skill → **会话进行中**删掉 link → resume 同一会话再问,
CC 仍报告能看到。

> 该结论需打折扣:用的是 `--resume`,无法完全区分"CC 缓存了清单"与"模型记得自己刚才的回答"。
> 但对 UI 的结论不受影响。

**因此界面不要暗示"已生效"。** 应明确提示"新会话生效",或提供"重载"入口。
否则用户会以为工具坏了。

文档中 `SessionStart` 的 `reloadSkills: true` 与 `ConfigChange` 事件可能与此相关,
值得进一步验证(已列入 [06](06-platform-findings.md) 的待验证清单)。

### 界面该显示什么

- **四态而非开/关**。`name-only` 需要一句解释,否则用户不懂它干什么用
- **清单预算进度条**。这是 Web 比 CLI 更有优势的地方——超限会静默丢弃 description,
  可视化后用户能主动降级不常用的 skill 到 `name-only`
- **`managed=False` 的项置灰只读**,并说明原因(用户手写 / 插件提供)
- **env 异常显著标出**,附 `cckit doctor` 入口

### ⚠️ 安全:只绑 127.0.0.1

Web 服务能改 CC 行为、能触发安装(而安装会执行仓库作者的代码)。
**绝不能监听 `0.0.0.0`。** 若确需远程访问,必须加鉴权。

这条要写进用户文档的显眼处,不是默认放开后让用户自己发现。
