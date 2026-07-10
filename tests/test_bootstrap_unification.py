# -*- coding: utf-8 -*-
"""
test_bootstrap_unification.py
------------------------------
「core.dbの単一ファイル化」がやりたかったことそのものを検証するテスト:

  2つの別々のアプリ(ここでは archlife / interview_app を模したマニフェスト)が、
  それぞれ独立に bootstrap_app() を呼んだとき、
    - 同じ core.db ファイルを見ている
    - 同じ device_id / 同じ profile_id を共有している
    - 互いが source_apps に登録され、相手の存在が見える
  ことを保証する。
"""
from __future__ import annotations

import json

from local_ai_core.bootstrap import bootstrap_app
from local_ai_core.schema import db_session


def _write_manifest(tmp_path, app_key: str, display_name: str):
    path = tmp_path / f"{app_key}.plugin_manifest.json"
    path.write_text(
        json.dumps(
            {
                "app_key": app_key,
                "display_name": display_name,
                "version": "0.1.0",
                "requested_scopes": [
                    {"scope": "schedule_items:read", "purpose": "テスト用の申告"},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path


def test_two_apps_share_same_profile_via_shared_paths(monkeypatch, tmp_path):
    # 実運用と同じく、パスは環境変数(=全アプリ共通のデフォルト解決ロジック)経由で揃える。
    core_db_path = str(tmp_path / "core.db")
    device_identity_path = str(tmp_path / "device_identity.json")
    monkeypatch.setenv("LOCAL_AI_CORE_DB_PATH", core_db_path)
    monkeypatch.setenv("LOCAL_AI_CORE_DEVICE_IDENTITY_PATH", device_identity_path)

    archlife_manifest = _write_manifest(tmp_path, "archlife", "ライフサポートOS")
    interview_manifest = _write_manifest(tmp_path, "interview_app", "就活支援")

    # 1つ目のアプリ(Archlifeを模す)が先に起動
    profile_id_archlife = bootstrap_app(archlife_manifest)

    # 2つ目のアプリ(interview_appを模す)が後から起動
    profile_id_interview = bootstrap_app(interview_manifest)

    # 同じprofileを共有していること(= 別々のprofileが分裂して作られていない)
    assert profile_id_archlife == profile_id_interview

    with db_session(core_db_path) as conn:
        app_keys = {
            row["app_key"]
            for row in conn.execute("SELECT app_key FROM source_apps").fetchall()
        }
        profile_count = conn.execute("SELECT COUNT(*) AS c FROM profiles").fetchone()["c"]
        device_count = conn.execute("SELECT COUNT(*) AS c FROM device_identity").fetchone()["c"]

    # 両アプリが同じ台帳に登録されている(= 互いの存在が見える)
    assert {"archlife", "interview_app"} <= app_keys
    # profileもdevice_identityも1件のみ(分裂していない)
    assert profile_count == 1
    assert device_count == 1
