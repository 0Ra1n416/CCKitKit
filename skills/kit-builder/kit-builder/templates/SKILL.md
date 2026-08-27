---
name: <skill-name>
description: <用一句话说明这个 skill 能做什么。CC 靠它决定是否调用,必须非空。>
# 可选字段(按需,别加自创字段):
# when_to_use: <触发条件。只在纯 CC 场景用;想上传 claude.ai 就别写它>
# license: <MIT 等>
# allowed-tools: <本 skill 需要的工具白名单>
---

# <skill-name>

<在这里写这个 skill 的正文:它做什么、怎么用。>

## 脚本调用

<如果有脚本,统一写,不要写解释器路径:>

```bash
cckit exec <skill-name> scripts/<run.py> [args...]
```

<脚本引用自身资源用环境变量 CCKIT_SKILL_DIR,不要假设 cwd。>
