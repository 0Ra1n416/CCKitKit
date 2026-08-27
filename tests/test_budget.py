"""budget:清单预算计算。"""
from __future__ import annotations

import json

from cckit import config, link, registry, state
from helpers import install_kit_skill


def test_budget_default_empty():
    used, limit = state.budget()
    assert used == 0
    assert limit == 8000


def test_budget_counts_enabled_only():
    install_kit_skill("foo", desc="test skill")  # 10 字符
    state.set_state("foo", "enabled", "global")
    used, _ = state.budget()
    assert used == 10

    state.set_state("foo", "name-only", "global")
    used2, _ = state.budget()
    assert used2 == 0


def test_budget_fraction_scaling():
    settings_dir = config.claude_config_dir()
    settings_dir.mkdir(parents=True, exist_ok=True)
    (settings_dir / "settings.json").write_text(
        json.dumps({"skillListingBudgetFraction": 0.02}), encoding="utf-8")
    _, limit = state.budget()
    assert limit == 16000


def test_budget_scope_filters(tmp_path):
    install_kit_skill("gfoo", desc="global skill")
    state.set_state("gfoo", "enabled", "global")

    (tmp_path / ".claude").mkdir()
    root = config.project_root()
    store = config.store_dir()
    pstore = store / "pkit"
    (pstore / "pfoo").mkdir(parents=True)
    (pstore / "pfoo" / "SKILL.md").write_text(
        "---\ndescription: project skill\n---\n", encoding="utf-8")
    registry.add_kit("pkit", {
        "source": {"url": "https://x/pkit", "ref": None, "sha": None},
        "version": "1.0.0",
        "store": str(pstore),
        "skills": [{"name": "pfoo", "env": None, "runtime": None, "needs": []}],
        "known_scopes": [str(root)]})
    proj_skills = root / ".claude" / "skills"
    proj_skills.mkdir(parents=True)
    link.create(pstore / "pfoo", proj_skills / "pfoo")

    g_used, _ = state.budget("global")
    p_used, _ = state.budget("project")
    a_used, _ = state.budget()
    assert g_used == len("global skill")
    assert p_used == len("project skill")
    assert a_used == g_used + p_used
