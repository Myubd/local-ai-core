import sqlite3
from pathlib import Path

import pytest

from local_ai_core.schema.migrate import init_core_schema
from local_ai_core.permissions import PermissionGate
from local_ai_core.automation import AutomationStore, AutomationEngine
from local_ai_core.plugins import PluginManifest, register_plugin

EXAMPLES_DIR = Path(__file__).resolve().parent.parent / "examples"


@pytest.fixture()
def db_path(tmp_path):
    path = str(tmp_path / "core.db")
    init_core_schema(path)
    conn = sqlite3.connect(path)
    conn.execute("INSERT INTO device_identity (id, key_salt) VALUES ('dev1', 'salt')")
    conn.execute(
        "INSERT INTO profiles (id, device_id, display_name) VALUES (1, 'dev1', 'テスト太郎')"
    )
    conn.commit()
    conn.close()

    manifest = PluginManifest.load(EXAMPLES_DIR / "archlife.plugin_manifest.json")
    register_plugin(path, manifest)
    return path


def test_rule_denied_without_grant(db_path):
    store = AutomationStore(db_path)
    rule_id = store.create(
        profile_id=1,
        owner_app="archlife",
        name="締切3日前の提案",
        trigger_type="schedule_due_soon",
        action_type="suggest",
        required_scopes=["schedule_items:read"],
    )
    rule = store.get(1, rule_id)

    engine = AutomationEngine(db_path, store=store)
    result = engine.run_rule(
        profile_id=1,
        rule=rule,
        context_provider=lambda t, c: {"dummy": True},
        suggestion_fn=lambda a, c, ctx: "提案文",
    )

    assert result.status == "denied"
    assert result.denied_scope == "schedule_items:read"
    runs = store.list_runs(1, rule_id)
    assert runs[0]["status"] == "denied"


def test_rule_runs_after_grant_and_records_summary(db_path):
    gate = PermissionGate(db_path)
    gate.grant(1, "archlife", "schedule_items:read")

    store = AutomationStore(db_path)
    rule_id = store.create(
        profile_id=1,
        owner_app="archlife",
        name="締切3日前の提案",
        trigger_type="schedule_due_soon",
        action_type="suggest",
        required_scopes=["schedule_items:read"],
    )
    rule = store.get(1, rule_id)

    engine = AutomationEngine(db_path, gate=gate, store=store)
    result = engine.run_rule(
        profile_id=1,
        rule=rule,
        context_provider=lambda t, c: {"open_tasks": 3},
        suggestion_fn=lambda a, c, ctx: f"未完了タスクが{ctx['open_tasks']}件あります",
    )

    assert result.status == "ok"
    assert "3件" in result.suggestion
    runs = store.list_runs(1, rule_id)
    assert runs[0]["status"] == "ok"
    assert "3件" in runs[0]["result_summary"]


def test_rule_error_is_recorded(db_path):
    gate = PermissionGate(db_path)
    gate.grant(1, "archlife", "schedule_items:read")
    store = AutomationStore(db_path)
    rule_id = store.create(
        profile_id=1, owner_app="archlife", name="壊れたルール",
        trigger_type="schedule_due_soon", action_type="suggest",
        required_scopes=["schedule_items:read"],
    )
    rule = store.get(1, rule_id)

    def _boom(*args, **kwargs):
        raise RuntimeError("何かが失敗した")

    engine = AutomationEngine(db_path, gate=gate, store=store)
    result = engine.run_rule(
        profile_id=1, rule=rule,
        context_provider=_boom,
        suggestion_fn=lambda a, c, ctx: "unused",
    )

    assert result.status == "error"
    runs = store.list_runs(1, rule_id)
    assert runs[0]["status"] == "error"


def test_enable_disable_and_list(db_path):
    store = AutomationStore(db_path)
    rule_id = store.create(
        profile_id=1, owner_app="archlife", name="ルールA",
        trigger_type="manual", action_type="suggest",
    )
    assert len(store.list_enabled(1)) == 1
    store.set_enabled(1, rule_id, False)
    assert len(store.list_enabled(1)) == 0
    assert len(store.list_all(1)) == 1
