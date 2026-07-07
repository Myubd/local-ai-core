# local-ai-core

「プライバシーファーストなローカルAIエコシステム」の共通コア層。
就活支援アプリ（interview_app）とライフサポートOS（Archlife）、および今後追加する
パーソナルナレッジ・学習支援・健康管理・家計管理・デスクトップアシスタントが、
同じローカルLLMランタイムと共通データ基盤を共有するための土台。

設計方針は共通化設計書（`プライバシーファースト・ローカルAIエコシステム_共通化設計書.md`）
の Phase 1〜3 に対応する。

## 何が入っているか

| モジュール | 役割 | 元になった実装 |
|---|---|---|
| `llm/base.py` | LLMプロバイダーの抽象基底クラス（`chat` / `chat_stream` / `embed` / `list_models`） | interview_app `react-fastapi/backend/llm/base.py` をアプリ非依存に一般化 |
| `llm/ollama_provider.py` | ローカルOllamaを叩く具象プロバイダー | interview_app `llm/ollama_provider.py` + Archlife `server.js` の `callLocalQwen` を統合 |
| `llm/external_providers.py` | Claude / OpenAI への外部呼び出し（オプトイン専用） | Archlife `server.js` の `callClaude` / `callOpenAI` を一般化 |
| `llm/router.py` | 「既定はローカル、ユーザーが明示的に許可した時だけ外部API」というルーティングを一元管理 | Archlife の `ai_settings`（`allow_external_api`）方針をアプリ非依存に抽出 |
| `prompts/guards.py` | ハルシネーション防止・出力フォーマット強制などの共通ガード | interview_app `shared/prompts/guards.py` の考え方を一般化 |
| `prompts/templates.py` | アプリごとに用途別プロンプトテンプレートを登録できるレジストリ | Archlife `server.js` の `buildPrompt`（テンプレート辞書）を一般化・拡張可能に |
| `schema/core_schema.sql` | 全アプリ共通のコアエンティティ（`profile` / `schedule_items` / `knowledge_items` / `device_identity` / `ai_settings`） | 新規設計。既存の `sessions` / `blobs` / `knowledge_bases` 等を包含できる形に統合 |
| `schema/migrate.py` | 冪等なマイグレーション実行機構 | interview_app `db/database.py` の `_run_migrations` パターンをアプリ非依存に一般化 |
| `identity/device_identity.py` | ログイン不要の端末内ID発行・パスフレーズからの鍵導出・AES-GCM暗号化 | Archlife `cryptoStorage.js`（PBKDF2 + AES-GCM）をPython/サーバー側でも使える形に移植 |
| `permissions/gate.py` | 「AIが全部知っている」を避けるための権限ゲート。スコープの申告・ユーザーによる許可/失効・アクセス直前チェック・監査ログ | 新規設計。就活支援/ライフサポートOS双方の「今後追加すべき機能」として要件定義したものを実装 |
| `memory/store.py` | 全アプリ共通のAIメモリー。`user_confirmed`（確定事実）と`ai_inferred`（AI推測）を区別して保持し、読み書きは必ず`permissions`経由 | 新規設計(最優先モジュール) |
| `plugins/manifest.py` | 各アプリが `plugin_manifest.json` 1枚で自己申告・登録できるプラグイン機構 | 新規設計。`source_apps`(既存)と`permissions`(新規)を橋渡しする |

## 各アプリからの使い方（想定）

```python
from local_ai_core.llm import LLMRouter, OllamaProvider, ClaudeProvider, OpenAIProvider
from local_ai_core.prompts import PromptRegistry, guards
from local_ai_core.schema import init_core_schema
from local_ai_core.identity import DeviceIdentity

# 1. 起動時にコアスキーマを初期化（アプリ固有スキーマとは名前空間を分離）
init_core_schema("core.db")

# 2. デバイスIDと暗号鍵を用意（ログイン不要）
identity = DeviceIdentity(storage_path="device_identity.json")

# 3. LLMルーターを組み立てる（既定ローカル、オプトインで外部API）
router = LLMRouter(
    local=OllamaProvider(model="qwen3:8b"),
    external={"claude": ClaudeProvider(), "openai": OpenAIProvider()},
)

# 4. 用途別テンプレートを登録して呼び出す
registry = PromptRegistry()
registry.register("today_priorities", "あなたはライフ管理アプリのアシスタントです。...")

prompt = registry.render("today_priorities", payload={"tasks": [...]})
response = await router.chat(prompt, allow_external=False)
```

## 権限管理・メモリー・プラグインの使い方（新規モジュール）

このエコシステムの大原則は「**申告しただけでは何も読めない。ユーザーが許可して初めて読める**」こと。

```python
from local_ai_core.schema import init_core_schema
from local_ai_core.permissions import PermissionGate, PermissionDenied
from local_ai_core.memory import MemoryStore
from local_ai_core.plugins import PluginManifest, register_plugin

# 1. 起動時: コアスキーマ初期化 + 自分自身をプラグインとして登録(申告のみ、まだ何も読めない)
init_core_schema("core.db")
manifest = PluginManifest.load("plugin_manifest.json")  # 例は examples/ を参照
register_plugin("core.db", manifest)

# 2. 設定画面: ユーザーがまだ許可していない申告の一覧を見せる
gate = PermissionGate("core.db")
for req in gate.pending_requests(profile_id=1):
    print(req["app_key"], req["scope"], "-", req["purpose"])

# 3. ユーザーが「許可する」を押した時だけ有効化される
gate.grant(profile_id=1, app_key="interview_app", scope="memory:read:career.*")

# 4. メモリーの読み書きは常にこのゲート経由。許可がなければ PermissionDenied
mem = MemoryStore("core.db", gate=gate)
mem.set(1, "interview_app", "career.strengths", ["粘り強さ"], confidence="ai_inferred")
item = mem.get(1, "interview_app", "career.strengths")

# 5. いつでも失効できる。以後は即座にアクセス不可になる
gate.revoke(profile_id=1, app_key="interview_app", scope="memory:read:career.*")
```

新しいアプリを追加する時にコアのコードを触る必要はなく、そのアプリのリポジトリに
`plugin_manifest.json`(`examples/*.plugin_manifest.json` 参照)を1枚追加し、
起動時に `register_plugin()` を呼ぶだけでよい。

## 移行の順序（設計書と対応）

1. **Phase 1**: 就活支援アプリの `llm/*` をこのパッケージの `llm/*` に置き換え、Archlifeの `server.js` のAI呼び出し部分をこのパッケージ経由のFastAPIルート越しに呼ぶ形に変更する
2. **Phase 2**: Archlifeのバックエンドをこのパッケージを使うFastAPIアプリに移植し、DBをSQLiteへ変更。`identity/device_identity.py` で `anon_id` + パスフレーズ方式を置き換える
3. **Phase 3**: `schema/core_schema.sql` を実データベースとして採用し、両アプリのアプリ固有テーブルから `profile_id` / `schedule_item_id` 等で参照する
4. **Phase 4**(実装済み): `permissions` / `memory` / `plugins` を追加。各アプリは `plugin_manifest.json` で自己申告し、`PermissionGate` 経由でのみ他アプリのデータ・メモリーにアクセスできるようにする。この段階を経て初めて、Document Center / Automation / Voice Assistant など「複数アプリのデータを横断するモジュール」を安全に追加できる
