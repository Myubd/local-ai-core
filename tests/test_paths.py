# -*- coding: utf-8 -*-
"""
test_paths.py
-------------
core.db / device_identity.json のパス解決が「全アプリで必ず同じ場所を指す」
ことを保証するためのテスト。ここが壊れると、複数アプリが別々のcore.dbを
見てしまい、共通データ基盤が実質分裂する。
"""
from __future__ import annotations

import importlib

import local_ai_core.paths as paths_module


def _reload():
    """モジュールレベルの定数は変えていないが、念のため毎回再読み込みして
    テスト間の環境変数の影響が残らないようにする。"""
    importlib.reload(paths_module)
    return paths_module


def test_core_db_path_env_override_wins(monkeypatch, tmp_path):
    override = str(tmp_path / "custom_core.db")
    monkeypatch.setenv("LOCAL_AI_CORE_DB_PATH", override)
    mod = _reload()
    assert mod.get_core_db_path() == override


def test_core_db_path_legacy_env_fallback(monkeypatch, tmp_path):
    """新しい環境変数が無くても、旧CORE_DB_PATHがあればそれを使う(移行期の後方互換)。"""
    monkeypatch.delenv("LOCAL_AI_CORE_DB_PATH", raising=False)
    legacy = str(tmp_path / "legacy_core.db")
    monkeypatch.setenv("CORE_DB_PATH", legacy)
    mod = _reload()
    assert mod.get_core_db_path() == legacy


def test_two_apps_resolve_to_identical_path_without_env(monkeypatch, tmp_path):
    """環境変数を何も設定しない場合でも、(異なるプロセス/アプリを模した)
    2回の呼び出しは同じパスを返す = 複数アプリが自然に同じファイルを共有する。
    """
    monkeypatch.delenv("LOCAL_AI_CORE_DB_PATH", raising=False)
    monkeypatch.delenv("CORE_DB_PATH", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.delenv("APPDATA", raising=False)
    mod = _reload()

    path_from_app_a = mod.get_core_db_path()
    path_from_app_b = mod.get_core_db_path()
    assert path_from_app_a == path_from_app_b


def test_device_identity_path_env_override_wins(monkeypatch, tmp_path):
    override = str(tmp_path / "custom_device_identity.json")
    monkeypatch.setenv("LOCAL_AI_CORE_DEVICE_IDENTITY_PATH", override)
    mod = _reload()
    assert mod.get_device_identity_path() == override


def test_core_db_and_device_identity_share_same_directory_by_default(monkeypatch, tmp_path):
    monkeypatch.delenv("LOCAL_AI_CORE_DB_PATH", raising=False)
    monkeypatch.delenv("CORE_DB_PATH", raising=False)
    monkeypatch.delenv("LOCAL_AI_CORE_DEVICE_IDENTITY_PATH", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.delenv("APPDATA", raising=False)
    mod = _reload()

    import os as _os

    core_db_dir = _os.path.dirname(mod.get_core_db_path())
    identity_dir = _os.path.dirname(mod.get_device_identity_path())
    assert core_db_dir == identity_dir
