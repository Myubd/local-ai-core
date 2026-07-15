import sqlite3
from pathlib import Path

import pytest

from local_ai_core.schema.migrate import init_core_schema
from local_ai_core.permissions import PermissionGate
from local_ai_core.assistant import AssistantOrchestrator, ContextSource
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


def test_assistant_skips_unpermitted_sources(db_path):
    gate = PermissionGate(db_path)
    # career.* memoryだけ許可し、knowledge_itemsは許可しない
    gate.grant(1, "interview_app", "memory:read:career.*")

    orchestrator = AssistantOrchestrator(db_path, gate=gate)

    captured_context = {}

    def fake_llm(question, context):
        captured_context.update(context)
        return f"回答: {question}"

    sources = [
        ContextSource(
            scope="memory:read:career.*",
            label="自己分析メモ",
            fetch=lambda: {"strengths": ["粘り強さ"]},
        ),
        ContextSource(
            scope="knowledge_items:read",
            label="企業研究資料",
            fetch=lambda: {"should_not_be_called": True},
        ),
    ]

    answer = orchestrator.ask(1, "interview_app", "面接で何を話せばいい?", sources, fake_llm)

    assert answer.used_scopes == ["memory:read:career.*"]
    assert answer.skipped_scopes == ["knowledge_items:read"]
    # 許可されていないソースのfetchは一切呼ばれておらず、contextにも含まれない
    assert "企業研究資料" not in captured_context
    assert "自己分析メモ" in captured_context
    assert answer.text.startswith("回答:")


def test_assistant_records_session_transparency(db_path):
    gate = PermissionGate(db_path)
    gate.grant(1, "interview_app", "memory:read:career.*")
    orchestrator = AssistantOrchestrator(db_path, gate=gate)

    sources = [
        ContextSource(scope="memory:read:career.*", label="自己分析メモ", fetch=lambda: {}),
    ]
    orchestrator.ask(1, "interview_app", "質問1", sources, lambda q, c: "回答")

    sessions = orchestrator.recent_sessions(1)
    assert len(sessions) == 1
    assert sessions[0]["used_scopes"] == ["memory:read:career.*"]
    # 質問文そのものは保存しない設計。タイトルは短い断片のみ
    assert sessions[0]["title"] == "質問1"
