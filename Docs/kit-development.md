# kit 开发手册

请参照 [manifest-spec.md](../skills/kit-builder/kit-builder/manifest-spec.md) 和
[kit-authoring.md](../skills/kit-builder/kit-builder/kit-authoring.md)

或者使用 `kit-builder` [SKILL](../skills/kit-builder/kit-builder/SKILL.md) 来把 skill 构建成 cckit 支持的模式。

如果你的仓库是**没有 `cckit.yaml` 的普通 skill 仓库**,也可以直接用
`cckit add <仓库> --alt` 让它自动走 `kit-builder` 改造 + Claude Code 审计后导入,
无需手动写 manifest(需先装 `cckit[alt]`,详见 [cli-spec.md](./cli-spec.md))。

*当然，建议您手动进行构建，使用自动构建可能造成部分内容与您的预期不符！*
