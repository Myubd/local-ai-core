import sqlite3
from pathlib import Path

import pytest

from local_ai_core.schema.migrate import init_core_schema
from local_ai_core.permissions import PermissionGate, PermissionDenied
from local_ai_core.documents import DocumentStore
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


def test_document_write_denied_before_grant(db_path):
    gate = PermissionGate(db_path)
    store = DocumentStore(db_path, gate=gate)
    with pytest.raises(PermissionDenied):
        store.register(1, "interview_app", "/home/user/resume.pdf", title="履歴書")


def test_document_register_and_list_after_grant(db_path):
    gate = PermissionGate(db_path)
    gate.grant(1, "interview_app", "documents:write")
    gate.grant(1, "interview_app", "documents:read")
    store = DocumentStore(db_path, gate=gate)

    doc_id = store.register(
        1, "interview_app", "/home/user/resume.pdf", title="履歴書",
        source_ref_id="resume_1", category="resume",
    )
    # 同じsource_ref_idで再登録すると更新される(重複作成されない)
    store.register(
        1, "interview_app", "/home/user/resume_v2.pdf", title="履歴書(最新版)",
        source_ref_id="resume_1", category="resume",
    )

    items = store.list_active(1, "interview_app")
    assert len(items) == 1
    assert items[0].title == "履歴書(最新版)"
    assert items[0].file_path == "/home/user/resume_v2.pdf"
    assert items[0].id == doc_id


def test_document_deactivate(db_path):
    gate = PermissionGate(db_path)
    gate.grant(1, "interview_app", "documents:write")
    gate.grant(1, "interview_app", "documents:read")
    store = DocumentStore(db_path, gate=gate)

    doc_id = store.register(1, "interview_app", "/tmp/note.txt", title="メモ")
    store.deactivate(1, "interview_app", doc_id)

    assert store.list_active(1, "interview_app") == []
