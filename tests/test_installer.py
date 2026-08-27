"""installer:计划计算与渲染(不触发网络/uv 的部分)。"""
from __future__ import annotations

from cckit import config, installer, manifest


def test_compute_plan(tmp_path):
    kit = tmp_path / "k"
    kit.mkdir()
    (kit / "cckit.yaml").write_text(
        "cckit: 1\n"
        "kit: k\n"
        "version: 1.0.0\n"
        "description: d\n"
        "requires:\n"
        "  system:\n"
        "    - bin: definitely-not-a-real-bin-xyz\n"
        "      hint:\n"
        "        windows: winget install x\n"
        "        linux: apt install x\n"
        "        macos: brew install x\n"
        "  python:\n"
        "    file: requirements.txt\n"
        "skills:\n"
        "  - name: s\n"
        "    needs: [python]\n",
        encoding="utf-8")
    (kit / "requirements.txt").write_text("requests\nnumpy\n", encoding="utf-8")

    data = manifest.load(kit / "cckit.yaml")
    plan = installer.compute_plan("https://example.com/k", "v1", "sha123", data, kit)

    assert plan.sha == "sha123"
    assert plan.ref == "v1"
    assert plan.python_packages == ["requests", "numpy"]
    assert any(d["bin"] == "definitely-not-a-real-bin-xyz" for d in plan.system_missing)


def test_render_plan_mentions_source_sha_and_postinstall():
    from cckit.installer import Plan, render_plan
    p = Plan(source="https://x", ref="v1", sha="abc", kit="k", version="1.0.0",
             description="d", postinstall=[{"run": "scripts/setup.py", "when": "python"}])
    text = render_plan(p)
    assert "https://x" in text
    assert "abc" in text
    assert "scripts/setup.py" in text
    assert "代码" in text  # 安全警示


def test_build_envs_dual_runtime(tmp_path, monkeypatch):
    """needs 同时含 python 与 node 时,各建一个独立 env,不再互相吞掉。"""
    data = {
        "kit": "k",
        "skills": [
            {"name": "s", "needs": ["python", "node"]},
            {"name": "prompt", "needs": []},
        ],
    }

    calls: list[tuple] = []
    monkeypatch.setattr(
        installer.env_mod, "create_python_env",
        lambda env_dir, c=None, r=None: calls.append(("python", env_dir)))
    monkeypatch.setattr(
        installer.env_mod, "create_node_env",
        lambda env_dir, p=None: calls.append(("node", env_dir)))

    envs = installer.build_envs(data, tmp_path)

    assert set(envs["s"]) == {"python", "node"}
    assert envs["s"]["python"] == config.envs_dir() / "k__s__python"
    assert envs["s"]["node"] == config.envs_dir() / "k__s__node"
    assert envs["prompt"] == {}
    assert sorted(rt for rt, _ in calls) == ["node", "python"]
