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

## 移行の順序（設計書と対応）

1. **Phase 1**: 就活支援アプリの `llm/*` をこのパッケージの `llm/*` に置き換え、Archlifeの `server.js` のAI呼び出し部分をこのパッケージ経由のFastAPIルート越しに呼ぶ形に変更する
2. **Phase 2**: Archlifeのバックエンドをこのパッケージを使うFastAPIアプリに移植し、DBをSQLiteへ変更。`identity/device_identity.py` で `anon_id` + パスフレーズ方式を置き換える
3. **Phase 3**: `schema/core_schema.sql` を実データベースとして採用し、両アプリのアプリ固有テーブルから `profile_id` / `schedule_item_id` 等で参照する
