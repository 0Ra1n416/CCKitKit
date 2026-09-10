"""cckit 命令行入口。

argparse 分发到各子命令:add / list / enable / disable / name-only /
remove / doctor / exec。破坏性操作在非 -y 时需确认。
"""
from __future__ import annotations

import argparse
import json
import sys

from . import doctor, exec as exec_mod, installer, registry, state
from .errors import CckitError
from .manifest import MissingManifestError

_SYMBOLS = {"installed": "·", "enabled": "●", "name-only": "◐", "off": "○"}  # 状态图标预定义
_STATE_LABELS = {"installed": "已安装", "enabled": "已启用", "name-only": "仅名字", "off": "已关闭"}


def _scope(args) -> str:
    """
    返回作用域字符串,project 或 global。默认 global,除非 --project 指定。

    :param args: argparse.Namespace, 解析后的命令行参数
    
    :return: 作用域字符串
    """
    return "project" if getattr(args, "project", False) else "global"


def _fmt(n: int) -> str:
    """
    格式化数字,大于 1000 的用 k 表示。

    :param n: int, 要格式化的数字

    :return: 格式化后的字符串
    """
    if n >= 1000:
        return f"{n / 1000:.1f}k"
    return str(n)


def _pct(used: int, limit: int) -> str:
    """
    百分比计算,limit 为 0 时返回 "∞"。

    :param used: int, 已使用的数量
    :param limit: int, 限制的数量

    :return: 百分比字符串
    """
    if limit <= 0:
        return "∞"
    return str(used * 100 // limit)


def _env_label(s: state.SkillState) -> str:
    """
    返回 skill 的依赖环境状态标签。

    :param s: state.SkillState, skill 的状态对象
    
    :return: 依赖环境状态标签字符串
    """
    if not s.managed:
        return ""
    if s.env_ok is None:
        return "prompt-only"
    if s.env_ok:
        return "env ok"
    return "env MISSING → cckit doctor"


def _as_dict(s: state.SkillState) -> dict:
    """
    将 SkillState 对象转换为字典,用于 JSON 输出。

    :param s: state.SkillState, skill 的状态对象

    :return: 字典表示的 skill 状态
    """
    return {
        "name": s.name,
        "kit": s.kit,
        "scope": s.scope,
        "state": s.state,
        "managed": s.managed,
        "env_ok": s.env_ok,
        "desc_chars": s.desc_chars,
        "version": s.version,
        "is_global_skill": s.is_global_skill,
        "global_state": s.global_state,
        "override": s.override,
        "envs": s.envs,
        "conf_files": s.conf_files,
        "missing_env": s.missing_env,
    }


def _kit_env_decls(kit: str | None) -> list[dict]:
    """kit 级(kit_env)声明的环境变量;非 cckit 管理的条目返回空。"""
    if not kit:
        return []
    return (registry.get_kit(kit) or {}).get("kit_env") or []


def _skill_marks(s: state.SkillState) -> str:
    """skill 行的依赖标记。仅在确有声明时出现,避免给所有行加噪声。"""
    marks = ""
    if s.envs:
        marks += "  [envs]"
    if s.conf_files:
        marks += "  [conf_files]"
    return marks


def _missing_mark(s: state.SkillState) -> str:
    """声明了 required 却还没值的环境变量提醒。

    没有就不占位 —— 与 [envs] / [conf_files] 一样,只在真有事时出现。
    """
    if not s.missing_env:
        return ""
    return f"  ⚠ 缺必需变量 {'、'.join(s.missing_env)} → cckit env"


def _print_list(skills: list[state.SkillState]) -> None:
    """
    打印 skill 列表。

    :param skills: list[state.SkillState], skill 列表
    """
    # 按 kit 分组打印,kit 内按 name 排序
    by_kit: dict[str, list[state.SkillState]] = {}

    for s in skills:
        by_kit.setdefault(s.kit or "(非 cckit 管理)", []).append(s)
    for kit, items in by_kit.items():
        ver = next((i.version for i in items if i.version), None)
        # kit 级(kit_env)声明的环境变量标记在 kit 行上,skill 级的标在各自 skill 行上
        kit_mark = "  [env]" if _kit_env_decls(items[0].kit) else ""
        if ver:
            print(f"{kit}  {ver}{kit_mark}")
        else:
            print(f"{kit}{kit_mark}")
        for s in items:
            env = _env_label(s)
            scope_tag = "  [project]" if s.scope == "project" else ""
            ro_tag = "  [只读]" if not s.managed else ""
            if s.is_global_skill:
                if s.override:
                    state_str = f"项目覆盖 {_STATE_LABELS.get(s.state, s.state)}"
                else:
                    state_str = f"跟随全局 {_STATE_LABELS.get(s.global_state or '', s.global_state or '?')}"
            else:
                state_str = s.state
            print(f"  {_SYMBOLS[s.state]} {s.name:<20} {state_str:<16} {env}"
                  f"{_skill_marks(s)}{scope_tag}{ro_tag}{_missing_mark(s)}")


# ---- 子命令 ----

# 各个子命令的实现函数,返回 int 作为退出码

def cmd_add(args) -> int:
    if args.alt:
        from . import alt
        alt.install_alt(
            args.source, ref=args.ref, project=args.project,
            no_enable=args.no_enable, only=args.only, assume_yes=args.yes,
            is_local_path=args.local)
        return 0
    installer.install(
        args.source, ref=args.ref, project=args.project,
        no_enable=args.no_enable, only=args.only, assume_yes=args.yes, is_local_path=args.local)
    return 0


def _print_env_detail(skills: list[state.SkillState]) -> None:
    """`list --envs`:逐 skill 列出所需环境变量。

    **不回显值** —— 只报"已设/未设",免得密钥进终端 scrollback。
    """
    print("\n[envs]")
    rows = [s for s in skills if s.managed and s.kit]
    if not rows:
        print("  无")
        return
    for s in rows:
        print(f"  {s.name}")
        reqs = state.env_requirements(s.kit, s.name, state.env_scope_of(s))
        if not reqs:
            print("    无")
            continue
        for r in reqs:
            need = "必需" if r.required else "可选"
            got = "已设" if r.value is not None else "未设"
            desc = f"  {r.description}" if r.description else ""
            print(f"    [{r.level:<5}] {r.name:<20} {need}  {got}{desc}")


def _print_conf_detail(skills: list[state.SkillState]) -> None:
    """`list --confs`:逐 skill 列出可改的配置文件(相对 skill 根)。"""
    print("\n[conf_files]")
    rows = [s for s in skills if s.managed]
    if not rows:
        print("  无")
        return
    for s in rows:
        print(f"  {s.name}")
        if not s.conf_files:
            print("    无")
            continue
        for rel in s.conf_files:
            print(f"    {rel}")


def cmd_list(args) -> int:
    if args.all:
        scope = None
    elif args.project:
        scope = "project"
    else:
        scope = "global"
    skills = state.list_skills(scope)
    if args.json:
        print(json.dumps([_as_dict(s) for s in skills], ensure_ascii=False, indent=2))
        return 0
    if not skills:
        print("(无 skill)")
    else:
        _print_list(skills)
    if args.envs:
        _print_env_detail(skills)
    if args.confs:
        _print_conf_detail(skills)
    used, limit = state.budget(scope)
    print(f"\n清单预算: {_fmt(used)} / {_fmt(limit)} 字符 ({_pct(used, limit)}%)")
    return 0


def cmd_env(args) -> int:
    """查看 / 设置 / 清除 skill 需要的环境变量。

    值存 ~/.cckit/envs.json,由 `cckit exec` 注入 —— 不写 Claude Code 的 settings.json。
    声明在 kit_env(kit 级)或 skill 的 env(skill 级)里,由作者写,用户只填值。
    """
    scope = _scope(args)
    kit, _skill_info = registry.find_skill(args.skill, scope)
    reqs = state.env_requirements(kit, args.skill, scope)

    if args.name is None:                       # 只看不改
        if not reqs:
            print(f"{args.skill} 没有声明任何环境变量")
            return 0
        for r in reqs:
            need = "必需" if r.required else "可选"
            got = "已设" if r.value is not None else "未设"
            desc = f"  {r.description}" if r.description else ""
            print(f"[{r.level:<5}] {r.name:<20} {need}  {got}{desc}")
        return 0

    req = next((r for r in reqs if r.name == args.name), None)
    if req is None:
        raise CckitError(
            f"{args.name!r} 不在 {args.skill!r} 声明的环境变量里"
            f"(已有声明见 `cckit list --envs`)")

    # 声明在 kit 级就写 kit 桶,在 skill 级就写 skill 桶 —— 与注入时的查找一致
    owner = args.skill if req.level == "skill" else None

    if args.unset:
        state.set_user_env(req.name, None, kit=kit, skill=owner, scope=scope)
        print(f"{req.name} 已清除({scope} 作用域)")
        return 0

    value = args.value
    if value is None:
        value = input(f"{req.name}({req.description or '无说明'}): ").strip()
    state.set_user_env(req.name, value, kit=kit, skill=owner, scope=scope)
    print(f"{req.name} 已保存({scope} 作用域),下次 cckit exec 生效")
    return 0


def cmd_enable(args) -> int:
    scope = _scope(args)
    ret = state.set_state(args.skill, "enabled", scope)
    if ret:
        print(ret)
    else:
        print(f"{args.skill} → enabled({scope}),新会话生效")
    return 0


def cmd_disable(args) -> int:
    scope = _scope(args)
    if args.purge:
        ret = state.set_state(args.skill, "installed", scope)
        if ret:
            print(ret)
        else:
            print(f"{args.skill} → installed({scope}),新会话生效")
    else:
        ret = state.set_state(args.skill, "off", scope)
        if ret:
            print(ret)
        else:
            print(f"{args.skill} → off({scope}),新会话生效")
    return 0


def cmd_name_only(args) -> int:
    scope = _scope(args)
    ret = state.set_state(args.skill, "name-only", scope)
    if ret:
        print(ret)
    else:
        print(f"{args.skill} → name-only({scope}),新会话生效")
    return 0


def cmd_remove(args) -> int:
    if not args.yes:
        ans = input(f"确认移除 kit {args.kit!r}? [y/N] ").strip().lower()
        if ans not in ("y", "yes"):
            print("已取消")
            return 0
    installer.remove_kit(args.kit, keep_env=args.keep_env)
    print(f"已移除 {args.kit}")
    return 0


def cmd_doctor(args) -> int:
    findings = doctor.run(fix=args.fix)
    for f in findings:
        icon = {"ok": "[ok]", "warn": "[warn]", "error": "[error]"}[f.status]
        print(f"{icon} {f.check}: {f.message}")
        if f.fix and f.status != "ok":
            print(f"     fix: {f.fix}")
    n_err = sum(1 for f in findings if f.status == "error")
    if args.fix:
        print("\n已执行安全修复(清理悬空 link、重建 env)")
    print(f"\n{len(findings)} 项检查,{n_err} 项错误")
    return 1 if n_err else 0


def cmd_exec(args) -> int:
    return exec_mod.run(args.skill, args.script, args.args, scope=_scope(args))


def cmd_web(args) -> int:
    """启动 Web 管理面板。fastapi/uvicorn 缺失时给出友好提示,不崩溃。"""
    try:
        from .web import serve
    except ImportError:
        print("web 端未安装,请运行: uv tool install 'cckit[web]'", file=sys.stderr)
        return 1
    serve(args.host, args.port, args.static_dir, args.base)
    return 0


# ---- parser ----

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="cckit", description="Claude Code 的 Skill 工具箱管理器")
    sub = p.add_subparsers(dest="command")

    a = sub.add_parser("add", help="安装一个 kit")
    a.add_argument("source", help="git URL(默认)或本地路径(配合 --local)")
    a.add_argument("--local", action="store_true", help="source 解释为本地路径进行安装")
    a.add_argument("--ref", help="分支 / tag / commit")
    a.add_argument("--no-enable", action="store_true", help="只装不启用(installed 态)")
    a.add_argument("--project", action="store_true", help="装到当前项目而非全局")
    a.add_argument("--only", help="只启用指定 skill(逗号分隔)")
    a.add_argument("--alt", action="store_true",
                   help="允许导入非标准仓库(用 kit-builder + Claude Code 改造;需安装 [alt] 依赖)")
    a.add_argument("-y", "--yes", action="store_true",
                   help="跳过确认(CI 用)。⚠️ 安装等于运行仓库作者代码,请自行确认来源可信")
    a.set_defaults(func=cmd_add)

    l = sub.add_parser("list", help="列出 skill(附清单预算)")
    g = l.add_mutually_exclusive_group()
    g.add_argument("--project", action="store_true", help="只列项目作用域")
    g.add_argument("--all", action="store_true", help="列出全部作用域")
    l.add_argument("--json", action="store_true", help="机器可读输出")
    l.add_argument("--envs", action="store_true",
                   help="附上各 skill 需要的环境变量(只报是否已设,不回显值)")
    l.add_argument("--confs", action="store_true",
                   help="附上各 skill 可修改的配置文件")
    l.set_defaults(func=cmd_list)

    v = sub.add_parser("env", help="查看/设置 skill 需要的环境变量")
    v.add_argument("skill")
    v.add_argument("name", nargs="?",
                   help="变量名;省略则列出该 skill 的全部环境变量")
    v.add_argument("value", nargs="?",
                   help="变量值;省略则交互输入。值存 ~/.cckit/envs.json")
    v.add_argument("--unset", action="store_true", help="清除该变量的值")
    v.add_argument("--project", action="store_true", help="作用于项目作用域")
    v.set_defaults(func=cmd_env)

    e = sub.add_parser("enable", help="启用 skill")
    e.add_argument("skill")
    e.add_argument("--project", action="store_true")
    e.set_defaults(func=cmd_enable)

    d = sub.add_parser("disable", help="禁用 skill(默认写 skillOverrides: off)")
    d.add_argument("skill")
    d.add_argument("--purge", action="store_true", help="删 link,彻底移出扫描范围")
    d.add_argument("--project", action="store_true")
    d.set_defaults(func=cmd_disable)

    n = sub.add_parser("name-only", help="只显示名字,省清单预算")
    n.add_argument("skill")
    n.add_argument("--project", action="store_true")
    n.set_defaults(func=cmd_name_only)

    r = sub.add_parser("remove", help="卸载 kit(清理 link/env/store/registry/overrides)")
    r.add_argument("kit")
    r.add_argument("--keep-env", action="store_true", help="保留 env(便于重装调试)")
    r.add_argument("-y", "--yes", action="store_true", help="跳过确认")
    r.set_defaults(func=cmd_remove)

    doc = sub.add_parser("doctor", help="诊断(只诊断不自动修)")
    doc.add_argument("--fix", action="store_true", help="只修明确安全的项")
    doc.set_defaults(func=cmd_doctor)

    x = sub.add_parser("exec", help="运行 skill 脚本")
    x.add_argument("skill")
    x.add_argument("script")
    x.add_argument("--project", action="store_true", help="作用于项目作用域")
    x.add_argument("args", nargs=argparse.REMAINDER, help="传给脚本的参数")
    x.set_defaults(func=cmd_exec)

    w = sub.add_parser("web", help="启动 Web 管理面板(需安装 [web] 额外依赖)")
    w.add_argument("--host", default="127.0.0.1",
                   help="监听地址(默认 127.0.0.1;部署时用 --host 0.0.0.0)")
    w.add_argument("--port", type=int, default=8000, help="端口(默认 8000)")
    w.add_argument("--static-dir", default=None,
                   help="前端静态产物目录(缺省不托管,配合 vite dev 使用)")
    w.add_argument("--base", default="",
                   help="根路径前缀(如 /cckit);经反向代理挂到子路径、iframe 嵌入时用")
    w.set_defaults(func=cmd_web)

    return p


def _configure_stdio() -> None:
    """把 stdout/stderr 切到 UTF-8。

    Windows 上 Python 的默认控制台/管道编码是 GBK,而 list 的 ●/◐/○、计划里的
    ⚠️ 等符号无法被 GBK 编码,会直接抛 UnicodeEncodeError。统一改成 UTF-8。
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def main(argv: list[str] | None = None) -> int:
    _configure_stdio()
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 0
    try:
        return args.func(args) or 0
    except MissingManifestError as e:
        print(f"错误: {e}", file=sys.stderr)
        print("提示: 这是非标准仓库(缺少 cckit.yaml)。可用 `--alt` 让 Claude Code 改造后导入,"
              "需先运行: uv tool install 'cckit[alt]'", file=sys.stderr)
        return 1
    except CckitError as e:
        print(f"错误: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("已中断", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
