"""
権限管理(PermissionGate) / メモリー(MemoryStore) / プラグインマニフェストの結合テスト。

このテストが確認している「絶対に守るべき性質」:
1. マニフェストで申告しただけでは何もアクセスできない(既定拒否)。
2. 許可(grant)して初めて、そのスコープに一致するアクセスだけが通る。
3. あるアプリへの許可は、他のアプリには一切波及しない(アプリ間の分離)。
4. 許可・拒否のいずれも access_log に必ず記録される(監査可能性)。
5. revoke すると即座にアクセスできなくなる。
"""
import sqlite3
from pathlib import Path

import pytest

from local_ai_core.schema.migrate import init_core_schema
from local_ai_core.permissions import PermissionGate, PermissionDenied
from local_ai_core.memory import MemoryStore
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
    return path


@pytest.fixture()
def registered(db_path):
    interview = PluginManifest.load(EXAMPLES_DIR / "interview_app.plugin_manifest.json")
    archlife = PluginManifest.load(EXAMPLES_DIR / "archlife.plugin_manifest.json")
    register_plugin(db_path, interview)
    register_plugin(db_path, archlife)
    return db_path


def test_pending_requests_lists_declared_scopes(registered):
    gate = PermissionGate(registered)
    pending = gate.pending_requests(1)
    scopes = {(p["app_key"], p["scope"]) for p in pending}
    assert ("interview_app", "memory:read:career.*") in scopes
    assert ("archlife", "memory:write:life.*") in scopes


def test_memory_write_denied_before_grant(registered):
    gate = PermissionGate(registered)
    mem = MemoryStore(registered, gate=gate)
    with pytest.raises(PermissionDenied):
        mem.set(1, "interview_app", "career.strengths", ["粘り強さ"], confidence="ai_inferred")


def test_memory_roundtrip_after_grant(registered):
    gate = PermissionGate(registered)
    mem = MemoryStore(registered, gate=gate)
    gate.grant(1, "interview_app", "memory:write:career.*")
    gate.grant(1, "interview_app", "memory:read:career.*")

    mem.set(1, "interview_app", "career.strengths", ["粘り強さ"], confidence="ai_inferred")
    item = mem.get(1, "interview_app", "career.strengths")

    assert item is not None
    assert item.value == ["粘り強さ"]
    assert item.confidence == "ai_inferred"
    assert item.source_app == "interview_app"


def test_grant_does_not_leak_across_apps(registered):
    gate = PermissionGate(registered)
    mem = MemoryStore(registered, gate=gate)
    gate.grant(1, "interview_app", "memory:write:career.*")
    mem.set(1, "interview_app", "career.strengths", ["粘り強さ"], confidence="ai_inferred")

    # archlife はこのスコープを許可されていないので読めない
    with pytest.raises(PermissionDenied):
        mem.get(1, "archlife", "career.strengths")


def test_revoke_blocks_further_access(registered):
    gate = PermissionGate(registered)
    mem = MemoryStore(registered, gate=gate)
    gate.grant(1, "interview_app", "memory:write:career.*")
    gate.grant(1, "interview_app", "memory:read:career.*")
    mem.set(1, "interview_app", "career.strengths", ["粘り強さ"], confidence="ai_inferred")

    gate.revoke(1, "interview_app", "memory:read:career.*")
    with pytest.raises(PermissionDenied):
        mem.get(1, "interview_app", "career.strengths")


def test_access_log_records_both_granted_and_denied(registered):
    gate = PermissionGate(registered)
    mem = MemoryStore(registered, gate=gate)

    with pytest.raises(PermissionDenied):
        mem.set(1, "interview_app", "career.strengths", ["x"], confidence="ai_inferred")

    gate.grant(1, "interview_app", "memory:write:career.*")
    mem.set(1, "interview_app", "career.strengths", ["x"], confidence="ai_inferred")

    conn = sqlite3.connect(registered)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT granted FROM access_log WHERE app_key = 'interview_app' ORDER BY id"
    ).fetchall()
    conn.close()

    assert [r["granted"] for r in rows] == [0, 1]


def test_grant_requires_prior_scope_registration(db_path):
    gate = PermissionGate(db_path)
    with pytest.raises(ValueError):
        gate.grant(1, "unknown_app", "memory:read:whatever")


def test_manifest_rejects_scope_without_purpose():
    with pytest.raises(ValueError):
        PluginManifest.from_dict(
            {
                "app_key": "bad_app",
                "display_name": "テスト",
                "requested_scopes": [{"scope": "memory:read:x"}],
            }
        )
