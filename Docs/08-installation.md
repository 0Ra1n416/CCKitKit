# 安装与分发

## 终端用户视角

```bash
# Windows (PowerShell)
irm https://astral.sh/uv/install.ps1 | iex
uv tool install cckit

# Linux / macOS
curl -LsSf https://astral.sh/uv/install.sh | sh
uv tool install cckit
```

我们额外提供 `install.ps1` / `install.sh`,检测 `uv` 缺失则先装它,把上面合成**一条命令**。

**用户不需要预装 Python。** `uv` 是独立静态二进制,会自己拉 cckit 需要的 Python 3.12+。
安装前提只有 `uv` 一个。

## 为什么是 `uv tool install`

### `pip install` 出局:Linux 上被 PEP 668 拒绝

实测 WSL Ubuntu-26.04 存在 `/usr/lib/python3.14/EXTERNALLY-MANAGED`,
`pip install --user` 会被系统拒绝,需要 `--break-system-packages` 才能绕过。

让用户输入"break system packages"作为安装指令,不可接受。

### `uv` 不是额外负担,是硬依赖

cckit 必须给每个 skill 建 venv,并处理"kit 要 Python 3.11 但用户只有 3.13"的情况。

实测本机就是这个局面:User PATH 中同时有 Python 3.10 和 3.11,而 `python` 解析到 3.13.12。
没有 `uv`,只能告诉用户"请自己装 Python 3.11"——死路。有 `uv` 则自动。

所以"装 uv"不是为装 cckit 付的成本,它本来就要装。

### PATH 恰好可用(Windows)

实测 `~/.local/bin` 已在 Windows User PATH 中(`claude` 自身即装于此),
而这正是 `uv tool install` 放二进制的位置。**装完即用,无需改 PATH 或重开终端。**

⚠️ Linux 侧实测 `~/.local/bin` **不在** PATH 中。`uv` 会自行提示,
但我们的 `install.sh` 应主动检测并给出明确指引。

## 被否决的方案

| 方案 | 否决理由 |
|---|---|
| `pip install --user` | Linux PEP 668 直接拒绝 |
| 独立二进制(PyInstaller) | 三平台 CI、体积大、Windows 易被杀软误报;而 `uv` 已解决分发 |
| 做成 CC 插件 | 循环依赖;且受插件系统限制(`--ignore-scripts`、60s 超时、仅 npm) |
| `pipx install` | 可行但 `pipx` 自身也需安装,而 `uv` 是我们无论如何都要的 |

`uvx cckit ...`(零安装直接跑)可作为试用路径,但常规使用应 `uv tool install`,
因为 cckit 需要持久状态(`~/.cckit/`)。

## 开发者视角

```bash
git clone <repo> && cd CCKitKit
uv sync                      # 建开发环境
uv run cckit --help          # 不安装直接跑
uv run pytest                # 跑测试
uv tool install --editable . # 本机可编辑安装
```

## 自举注意

cckit 用 `uv` 管理 skill 的 venv,自己也由 `uv tool install` 安装,
但**两者互不干扰**:cckit 自身的环境由 uv 的 tool 机制管理,
skill 的 venv 在 `~/.cckit/envs/`,由 cckit 显式调用 `uv venv` 创建。

`cckit doctor` 必须检查 `uv` 是否在 PATH。缺失时**只给安装提示,不自动装**——
`uv` 是系统级工具,自动装它违反我们自己的"系统级依赖只声明不自动装"原则(见 D-02)。
