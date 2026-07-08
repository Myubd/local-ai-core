import sqlite3
from pathlib import Path

import pytest

from local_ai_core.schema.migrate import init_core_schema
from local_ai_core.permissions import PermissionGate, PermissionDenied
from local_ai_core.knowledge import KnowledgeStore
from local_ai_core.schedule import ScheduleStore
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

    manifest = PluginManifest.load(EXAMPLES_DIR / "interview_app.plugin_manifest.json")
    register_plugin(path, manifest)
    return path


def test_knowledge_write_denied_before_grant(db_path):
    gate = PermissionGate(db_path)
    store = KnowledgeStore(db_path, gate=gate)
    with pytest.raises(PermissionDenied):
        store.upsert(1, "interview_app", "kb_1", title="ソニー")


def test_knowledge_upsert_and_list_after_grant(db_path):
    gate = PermissionGate(db_path)
    gate.grant(1, "interview_app", "knowledge_items:write")
    gate.grant(1, "interview_app", "knowledge_items:read")
    store = KnowledgeStore(db_path, gate=gate)

    store.upsert(1, "interview_app", "kb_1", title="ソニー", category="company",
                 summary="ゲーム/エンタメ領域。中途/新卒とも積極採用。")
    # 同じ source_ref_id で呼ぶと更新される(重複作成されない)
    store.upsert(1, "interview_app", "kb_1", title="ソニーグループ", category="company")

    items = store.list_active(1, "interview_app")
    assert len(items) == 1
    assert items[0].title == "ソニーグループ"


def test_knowledge_deactivate(db_path):
    gate = PermissionGate(db_path)
    gate.grant(1, "interview_app", "knowledge_items:write")
    gate.grant(1, "interview_app", "knowledge_items:read")
    store = KnowledgeStore(db_path, gate=gate)

    store.upsert(1, "interview_app", "kb_1", title="ソニー")
    store.deactivate(1, "interview_app", "kb_1")

    assert store.list_active(1, "interview_app") == []


def test_schedule_upsert_denied_before_grant(db_path):
    gate = PermissionGate(db_path)
    store = ScheduleStore(db_path, gate=gate)
    with pytest.raises(PermissionDenied):
        store.upsert(1, "interview_app", "session_5", item_type="event", title="ソニー最終面接")


def test_schedule_upsert_and_list_after_grant(db_path):
    gate = PermissionGate(db_path)
    gate.grant(1, "interview_app", "schedule_items:write")
    gate.grant(1, "interview_app", "schedule_items:read")
    store = ScheduleStore(db_path, gate=gate)

    store.upsert(1, "interview_app", "session_5", item_type="event",
                 title="ソニー最終面接", due_at="2026-08-01 10:00")
    items = store.list_open(1, "interview_app")
    assert len(items) == 1
    assert items[0].title == "ソニー最終面接"

    store.set_status(1, "interview_app", "session_5", status="done")
    assert store.list_open(1, "interview_app") == []
