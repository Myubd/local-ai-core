-- local-ai-core: 全アプリ共通のコアスキーマ
--
-- 設計方針:
-- - このDBは「アプリ横断で意味のあるデータ」のみを持つ。
--   各アプリ固有の詳細(面接セッションの会話ログ、家計簿の明細等)は
--   引き続き各アプリのDB/スキーマに残し、ここには参照用のIDと要約だけを置く。
-- - 単一ユーザー・ログイン不要の端末内アプリを前提とするが、将来的な複数
--   プロファイル(例: 家族利用)にも耐えられるよう profile_id で分離する。
-- - すべてのテーブルは "CREATE TABLE IF NOT EXISTS" で冪等に初期化できる。

PRAGMA foreign_keys = ON;

-- ============================================================
-- device_identity: 端末内ID(ログイン不要)。Archlifeの anon_id 相当を全アプリ共通化。
-- ============================================================
CREATE TABLE IF NOT EXISTS device_identity (
    id              TEXT PRIMARY KEY,           -- UUID。crypto.randomUUID() 相当をサーバー側でも保持
    key_salt        TEXT NOT NULL,              -- パスフレーズからの鍵導出に使うsalt(base64)
    created_at      TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

-- ============================================================
-- profiles: プロフィール本体。1端末に複数プロフィール(家族利用等)を許容。
-- ============================================================
CREATE TABLE IF NOT EXISTS profiles (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id       TEXT NOT NULL,
    display_name    TEXT,
    -- 性格診断(就活支援の personality_results)や生活パターンなど、
    -- アプリ間で共有したい要約情報をJSONで保持する。
    -- 個々の生データは各アプリ側に残し、ここには「要約」だけを置く。
    traits_json     TEXT,                       -- 例: {"big_five": {...}, "life_rhythm": "morning"}
    created_at      TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    FOREIGN KEY (device_id) REFERENCES device_identity(id) ON DELETE CASCADE
);

-- ============================================================
-- ai_settings: プロフィールごとのAI利用設定(外部API許可の有無)。
-- Archlife の ai_settings テーブルをプロフィール単位に一般化。
-- ============================================================
CREATE TABLE IF NOT EXISTS ai_settings (
    profile_id          INTEGER PRIMARY KEY,
    allow_external_api  INTEGER NOT NULL DEFAULT 0,   -- 0/1
    external_provider   TEXT CHECK (external_provider IN ('claude', 'openai')) DEFAULT 'claude',
    FOREIGN KEY (profile_id) REFERENCES profiles(id) ON DELETE CASCADE
);

-- ============================================================
-- source_apps: このコアDBにデータを書き込むアプリの登録簿。
-- 新規アプリ追加時にここへ1行足すだけで、schedule_items/knowledge_items から
-- 参照できるようになる(プラグイン方式)。
-- ============================================================
CREATE TABLE IF NOT EXISTS source_apps (
    app_key      TEXT PRIMARY KEY,   -- 例: "interview_app", "archlife", "personal_knowledge"
    display_name TEXT NOT NULL,
    registered_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

-- ============================================================
-- schedule_items: 予定/タスク/締切の共通テーブル。
-- ライフサポートOSのタスクと、就活支援の面接予定を同じ器で扱う。
-- ============================================================
CREATE TABLE IF NOT EXISTS schedule_items (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id      INTEGER NOT NULL,
    source_app      TEXT NOT NULL,              -- source_apps.app_key
    source_ref_id   TEXT,                       -- 発生元アプリ内でのID(例: interview_appのsessions.id)
    item_type       TEXT NOT NULL,              -- "task" | "event" | "deadline" | "habit"
    title           TEXT NOT NULL,
    detail          TEXT,
    due_at          TEXT,                       -- ISO8601
    status          TEXT NOT NULL DEFAULT 'open', -- open / done / cancelled
    priority        INTEGER,                    -- 1(高)〜5(低)。AI提案の並び替えに使用
    created_at      TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    FOREIGN KEY (profile_id) REFERENCES profiles(id) ON DELETE CASCADE,
    FOREIGN KEY (source_app) REFERENCES source_apps(app_key)
);

CREATE INDEX IF NOT EXISTS idx_schedule_items_profile_due ON schedule_items(profile_id, due_at);
CREATE INDEX IF NOT EXISTS idx_schedule_items_source ON schedule_items(source_app, source_ref_id);

-- ============================================================
-- knowledge_items: 資料/ナレッジの共通テーブル。
-- 就活支援の企業研究資料、パーソナルナレッジのメモ/PDF、学習支援の教材を統合。
-- 実体(embedding等)は各アプリのRAG基盤が持ち、ここはメタデータの共通台帳。
-- ============================================================
CREATE TABLE IF NOT EXISTS knowledge_items (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id      INTEGER NOT NULL,
    source_app      TEXT NOT NULL,              -- source_apps.app_key
    source_ref_id   TEXT,                       -- 発生元アプリ内でのID(例: knowledge_bases.id)
    category        TEXT,                       -- "company" | "resume" | "note" | "textbook" 等、アプリごとに自由
    title           TEXT NOT NULL,
    summary         TEXT,                       -- 横断検索用の短い要約(全文はアプリ側のRAGに保持)
    tags_json       TEXT,                       -- 例: ["ソニー", "面接対策"]
    is_active       INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    FOREIGN KEY (profile_id) REFERENCES profiles(id) ON DELETE CASCADE,
    FOREIGN KEY (source_app) REFERENCES source_apps(app_key)
);

CREATE INDEX IF NOT EXISTS idx_knowledge_items_profile ON knowledge_items(profile_id);
CREATE INDEX IF NOT EXISTS idx_knowledge_items_source ON knowledge_items(source_app, source_ref_id);

-- ============================================================
-- events: 軽量アプリ間イベントバス(ポーリング前提)。
-- 例: interview_appが面接日程を確定したら、この表に1行書き込み、
--     ライフサポートOSが定期ポーリングして schedule_items に反映する。
-- ============================================================
CREATE TABLE IF NOT EXISTS events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id      INTEGER NOT NULL,
    source_app      TEXT NOT NULL,
    event_type      TEXT NOT NULL,              -- 例: "schedule_item.created"
    payload_json    TEXT NOT NULL,
    consumed_by_json TEXT NOT NULL DEFAULT '[]', -- 消費済みのapp_keyリスト(重複配信防止)
    created_at      TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    FOREIGN KEY (profile_id) REFERENCES profiles(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_events_profile_created ON events(profile_id, created_at);

-- ============================================================
-- permission_scopes: 各アプリが「使う可能性がある」データアクセスの申告。
-- プラグインのマニフェスト(plugins/manifest.py)から登録される「申請書」。
-- ここに存在するだけではまだ何も読めない。実際の許可は permission_grants で管理する。
-- ============================================================
CREATE TABLE IF NOT EXISTS permission_scopes (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    app_key      TEXT NOT NULL,              -- source_apps.app_key
    scope        TEXT NOT NULL,              -- 例: "schedule_items:read", "memory:read:career.*"
    purpose      TEXT NOT NULL,              -- ユーザーに提示する用途説明(日本語の平易な文)
    registered_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    FOREIGN KEY (app_key) REFERENCES source_apps(app_key),
    UNIQUE (app_key, scope)
);

-- ============================================================
-- permission_grants: ユーザーが実際に許可したスコープ。
-- 「AIが全部知っている」を避けるための唯一の関所(gate)。
-- expires_at が NULL の場合は明示的に revoke されるまで有効(永続許可)。
-- ============================================================
CREATE TABLE IF NOT EXISTS permission_grants (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id  INTEGER NOT NULL,
    scope_id    INTEGER NOT NULL,
    granted_at  TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    expires_at  TEXT,                        -- ISO8601。単発/期間限定の許可に使用
    revoked_at  TEXT,                        -- NOT NULLなら失効済み
    FOREIGN KEY (profile_id) REFERENCES profiles(id) ON DELETE CASCADE,
    FOREIGN KEY (scope_id) REFERENCES permission_scopes(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_permission_grants_profile ON permission_grants(profile_id, scope_id);

-- ============================================================
-- access_log: 実際にどのアプリがどのスコープでデータを読んだかの監査ログ。
-- 「検証可能なプライバシー」を担保する(ユーザーが後から確認できる)。
-- ============================================================
CREATE TABLE IF NOT EXISTS access_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id  INTEGER NOT NULL,
    app_key     TEXT NOT NULL,
    scope       TEXT NOT NULL,
    granted     INTEGER NOT NULL,            -- 1=許可されて読めた 0=拒否された(デバッグ/監査用)
    accessed_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    FOREIGN KEY (profile_id) REFERENCES profiles(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_access_log_profile ON access_log(profile_id, accessed_at);

-- ============================================================
-- memory_items: 全アプリ共通の「AIメモリー」。
-- 生の会話ログや資料は各アプリ側(将来のDocument Center)に残し、
-- ここには「確定した/推測された事実」だけを構造化して置く。
-- confidence で「ユーザーが確認した事実」と「AIの推測」を区別し、
-- 参照側が推測情報を事実であるかのように扱わないようにする。
-- ============================================================
CREATE TABLE IF NOT EXISTS memory_items (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id      INTEGER NOT NULL,
    source_app      TEXT NOT NULL,           -- 書き込んだアプリ。source_apps.app_key
    key             TEXT NOT NULL,           -- 例: "career.strengths", "life.morning_type"
    value_json      TEXT NOT NULL,
    confidence      TEXT NOT NULL CHECK (confidence IN ('user_confirmed', 'ai_inferred')),
    created_at      TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    FOREIGN KEY (profile_id) REFERENCES profiles(id) ON DELETE CASCADE,
    FOREIGN KEY (source_app) REFERENCES source_apps(app_key),
    UNIQUE (profile_id, key)
);

CREATE INDEX IF NOT EXISTS idx_memory_items_profile_key ON memory_items(profile_id, key);
