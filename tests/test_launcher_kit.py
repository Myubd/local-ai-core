"""
launcher_kit.py の回帰テスト。

Ollamaの実インストールやネットワークが絡む部分(install_ollama, pull_model等)は
ここでは対象外とする(元のlaunch_fastapi.pyでも自動テストの対象外だった)。
ここでは、切り出しの過程で壊れやすい「純粋なロジック部分」と「ログハンドラーの
差し込み口」を中心に確認する。
"""
import sys
import time

import pytest

from local_ai_core import launcher_kit as lk


# ── strip_ansi / format_bytes ──────────────────────────────

def test_strip_ansi_removes_escape_sequences():
    raw = "\x1b[?2026h\x1b[1Gpulling manifest\x1b[K"
    assert lk.strip_ansi(raw) == "pulling manifest"


def test_strip_ansi_removes_braille_spinner_chars():
    raw = "⠋ downloading..."
    assert "⠋" not in lk.strip_ansi(raw)


def test_strip_ansi_plain_text_unchanged():
    assert lk.strip_ansi("plain text") == "plain text"


@pytest.mark.parametrize(
    "size,expected_unit",
    [(500, "B"), (2048, "KB"), (5 * 1024 * 1024, "MB"), (3 * 1024 ** 3, "GB")],
)
def test_format_bytes_picks_correct_unit(size, expected_unit):
    assert lk.format_bytes(size).endswith(expected_unit)


# ── ログハンドラーの差し込み ─────────────────────────────

def test_log_calls_extra_handler_with_message_level_group():
    captured = []
    lk.set_log_handler(lambda message, level, group: captured.append((message, level, group)))
    try:
        lk.log("hello", "SUCCESS", group="test-group")
    finally:
        lk.set_log_handler(None)

    assert captured == [("hello", "SUCCESS", "test-group")]


def test_log_without_handler_does_not_raise():
    lk.set_log_handler(None)
    lk.log("no handler registered")  # 例外が出ないことだけを確認


def test_log_handler_exception_is_swallowed():
    def _broken_handler(message, level, group):
        raise RuntimeError("boom")

    lk.set_log_handler(_broken_handler)
    try:
        lk.log("this should not raise")  # ハンドラーが例外を出しても起動処理は止めない
    finally:
        lk.set_log_handler(None)


# ── ポート待受 ──────────────────────────────────────────────

def test_wait_for_port_returns_true_when_port_is_open():
    import socket
    import threading

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = server.getsockname()[1]

    def _accept_once():
        try:
            conn, _ = server.accept()
            conn.close()
        except Exception:
            pass

    t = threading.Thread(target=_accept_once, daemon=True)
    t.start()

    try:
        assert lk.wait_for_port(port, timeout=2.0) is True
    finally:
        server.close()


def test_wait_for_port_times_out_when_nothing_listening():
    # 未使用ポート(誰もbindしていないことがほぼ確実な高番ポート)を使う
    start = time.time()
    result = lk.wait_for_port(59321, timeout=0.5)
    elapsed = time.time() - start

    assert result is False
    assert elapsed < 2.0  # timeoutを大きく超えて待ち続けていないこと


# ── Ollama状態確認(ネットワーク不要な部分のみ) ──────────────

def test_is_ollama_running_false_when_nothing_listening():
    assert lk.is_ollama_running("http://localhost:59322") is False


def test_ensure_models_no_download_when_all_installed(monkeypatch):
    monkeypatch.setattr(lk, "get_installed_models", lambda: ["qwen3:8b", "nomic-embed-text:latest"])

    pull_calls = []
    monkeypatch.setattr(lk, "pull_model", lambda name: pull_calls.append(name) or True)

    lk.ensure_models(["qwen3:8b", "nomic-embed-text"])

    assert pull_calls == []  # 全部インストール済みなのでpullは呼ばれない


def test_ensure_models_downloads_missing_models(monkeypatch):
    monkeypatch.setattr(lk, "get_installed_models", lambda: ["qwen3:8b"])

    pull_calls = []
    monkeypatch.setattr(lk, "pull_model", lambda name: pull_calls.append(name) or True)

    lk.ensure_models(["qwen3:8b", "nomic-embed-text"])

    assert pull_calls == ["nomic-embed-text"]


# ── クラッシュログ ──────────────────────────────────────────

def test_write_crash_log_creates_file_with_context(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))

    try:
        raise ValueError("something went wrong")
    except ValueError as e:
        lk.write_crash_log("TestApp", "起動テスト", e)

    log_path = tmp_path / "TestApp" / "crash.log"
    assert log_path.exists()
    content = log_path.read_text(encoding="utf-8")
    assert "起動テスト" in content
    assert "ValueError" in content
    assert "something went wrong" in content


def test_crash_log_path_uses_app_folder_name(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    path = lk.crash_log_path("MyApp")
    assert "MyApp" in path
    assert path.endswith("crash.log")


# ── コンソールを閉じた時のハンドラー(Windows専用の×ボタン対策) ────

def test_install_console_close_handler_noop_on_non_windows(monkeypatch):
    monkeypatch.setattr(lk.sys, "platform", "linux")
    called = []
    # 例外が出ず、何も登録されない(呼ばれない)ことだけを確認する
    lk.install_console_close_handler(lambda: called.append(True))
    assert called == []


def test_install_console_close_handler_registers_and_triggers_cleanup(monkeypatch):
    # Windows専用のctypes呼び出しをモックに差し替えて、
    # 「登録される」「CTRL_CLOSE_EVENT等でcleanup_fnが呼ばれる」
    # 「それ以外のイベントでは呼ばれない」ことを検証する。
    monkeypatch.setattr(lk.sys, "platform", "win32")

    registered_handlers = []

    class _FakeKernel32:
        def SetConsoleCtrlHandler(self, handler, add):
            registered_handlers.append(handler)
            return True

    class _FakeWindll:
        kernel32 = _FakeKernel32()

    import types
    fake_ctypes = types.SimpleNamespace(
        windll=_FakeWindll(),
        WINFUNCTYPE=lambda *a, **kw: (lambda fn: fn),  # デコレータ相当を素通しする
    )
    fake_wintypes = types.SimpleNamespace(BOOL=bool, DWORD=int)
    fake_ctypes.wintypes = fake_wintypes

    monkeypatch.setitem(sys.modules, "ctypes", fake_ctypes)
    monkeypatch.setitem(sys.modules, "ctypes.wintypes", fake_wintypes)

    called = []
    lk.install_console_close_handler(lambda: called.append(True))

    assert len(registered_handlers) == 1
    handler_fn = registered_handlers[0]

    # CTRL_CLOSE_EVENT (2) では呼ばれる
    result = handler_fn(2)
    assert called == [True]
    assert result is True

    # 無関係なイベント(例: CTRL_C_EVENT=0)では呼ばれない
    called.clear()
    result = handler_fn(0)
    assert called == []
    assert result is False
