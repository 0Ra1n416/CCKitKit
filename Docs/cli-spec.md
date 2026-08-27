# CLI 规格

约定:所有命令默认作用于**全局**;加 `--project` 作用于当前项目。
所有破坏性操作在非 `-y` 时需确认。

## `cckit add <source>`

拉取并安装一个 kit。

```bash
cckit add https://github.com/someone/video-toolkit
cckit add https://gitee.com/someone/video-toolkit --ref v1.2.0
cckit add ./local-kit --project --local
```

`<source>` 接受任意 git URL(GitHub / Gitee / GitLab / 自建均可,只要是标准 git over HTTPS/SSH) 或本地路径（需要加上 `--local` 选项）。

### 流程

1. **clone** 到临时目录,解析 `--ref`(缺省默认分支)
2. **锁定 commit sha**——记录 sha 而非分支名。分支会被作者事后改动
3. **校验 manifest**:存在性 → JSON Schema → 语义检查(`needs` 引用、skill 目录与
   `skills[]` 一致、平台匹配)。任一失败则**中止且不留残留**
4. **lint**:skill 名合法性、description 质量、CRLF、保留名(见 03)
5. **展示计划并等确认**:要装哪些包、跑哪个 postinstall、缺哪些系统依赖。
   ⚠️ 这一步不可省略,是与官方安全模型之间唯一的桥(见 07)
6. **移入 store**,建 env,装依赖,跑 postinstall
7. **建 link** 启用(除非 `--no-enable`)
8. **写 registry**,报告清单预算占用

### 关键选项

| 选项 | 说明 |
|---|---|
| `--ref <ref>` | 分支 / tag / commit |
| `--no-enable` | 只装不启用(落到 `installed` 态) |
| `--project` | 装到当前项目而非全局 |
| `--only <skill,...>` | 只启用 kit 中的部分 skill |
| `-y` | 跳过确认。CI 用,文档需警示风险 |

### 必须拦截的情况

- 当前平台不在 `platforms` 内 → 拒绝,不等装完才发现
- 系统依赖缺失 → 报告并给**当前平台**的 hint,询问是继续(env 仍可建)还是中止
- link 目标已存在真实目录 → 报错说明这是用户手写的 skill,不覆盖
- **项目安装时存在同名全局 skill → 明确警告"全局会覆盖项目版"**

## `cckit list`

```
$ cckit list

video-toolkit  1.2.0  (sha 30287f5)
  ● burn-subtitles     enabled     env ok
  ◐ describe-video     name-only   prompt-only
doc-tools      0.4.1  (sha a1b2c3d)
  ○ pdf-extract        off         env ok
  ✗ ocr-scan           enabled     env MISSING  → cckit doctor

清单预算: 3.2k / 8.0k 字符 (40%)
```

预算行是硬要求,不是装饰。工具箱变大后超预算会**静默丢弃 description**,
表现为"装了但 CC 从不用"且无提示。

选项:`--project` 只列项目;`--all` 全作用域;`--json` 机器可读。

`--json` 应同时列出**非 cckit 管理**的 skill(用户手写、插件带的),标记为只读。
用户看到的是完整工具箱视图,但只有 cckit 装的能被开关。

实现上直接调 `cckit.state.list_skills()`,**不要自己扫目录**——该函数同时服务
Web 接口,两边必须共用同一份逻辑。

## `cckit enable` / `disable`

```bash
cckit enable <skill>              # → enabled
cckit disable <skill>             # → off,写 skillOverrides(默认)
cckit disable <skill> --purge     # → installed,删 link
cckit name-only <skill>           # → name-only,省预算
```

`disable` 默认走 `skillOverrides` 而非删 link:可逆、不动文件、瞬间生效。
`--purge` 用于彻底移出扫描范围。对全局 skill,全局 `--purge` 还会清掉它在各项目根留下的
项目级 `skillOverrides` 覆盖(避免孤儿覆盖)。

⚠️ 全局 skill 的项目级开关语义不同: `disable <name> --project` 写项目覆盖;
`enable <name> --project` 清掉覆盖、跟随全局;`disable <name> --purge --project` **会报错**
——全局 skill 没有项目 link 可删,去掉 `--project` 在全局作用域执行。

⚠️ 一律通过 `cckit.state.set_state()` 落盘,**不直接写 `settings.json`**。
实测无锁并发写会丢失更新(8 个并发只活下来 1 条),且半截写入会让 CC 完全读不了
settings。

改动**不影响已在运行的会话**,输出应提示"新会话生效"。

## `cckit remove <kit>`

删 link → 删 env → 删 store → 清理 registry 与 `skillOverrides` 残留条目。

⚠️ **不能只删 skill 目录。** env 在 `~/.cckit/envs/`、状态在 registry 与
settings.json,必须由 cckit 跟踪清理。

`--keep-env` 保留 env(便于重装调试)。

## `cckit doctor`

只诊断,不自动修;每项给出可复制的修复命令。

| 检查项 | 为什么 |
|---|---|
| `uv` 是否在 PATH | 缺失则无法建 env |
| 悬空 link(目标已消失) | 用 `lexists && !exists` 检出 |
| link 指向是否与 registry 一致 | 手工改动会导致漂移 |
| env 是否完整、解释器是否可执行 | 换机 / Python 升级会坏 |
| 系统依赖是否仍在 | 用户可能卸了 ffmpeg |
| **`disableSkillShellExecution` 是否开启** | 开了则**所有带脚本 skill 静默失效** |
| 清单预算是否超限 | 超了会静默丢 description |
| 同名冲突(全局 vs 项目) | 全局静默覆盖项目版 |

这张表里各项的共同点是**不报错,只静默失效**。

`--fix` 只处理明确安全的项(清理悬空 link、重建 env)。

## `cckit exec <skill> <script> [args...]`

skill 脚本的统一入口。SKILL.md 里只写这一句,不写解释器路径。

要点:cwd **保持调用方 cwd**(让用户给的相对路径正常工作),脚本自身资源通过
`CCKIT_SKILL_DIR` 定位。`scripts` 未在 manifest 声明的路径应拒绝执行。
