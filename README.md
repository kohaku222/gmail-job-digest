# 就活メール自動要約システム

GitHub Actions で毎日 **JST 9:00 / 17:00** に動作し, Gmailの新着メールを Claude が要約して Slack に通知します.

## 仕組み

```
GitHub Actions (cron)
   ├─ Gmail API: 前回実行以降のメール取得
   ├─ Claude API: 重要度判定 + 要約 (tool useでJSON出力)
   ├─ Slack Webhook: Block Kit整形で投稿
   └─ state.json をリポジトリに自動commit
```

## セットアップ手順

### 1. Slack: Incoming Webhook URL を取得

1. https://api.slack.com/apps → "Create New App" → "From scratch"
2. App名 (例: `job-summary`) とワークスペースを選択
3. 左メニュー "Incoming Webhooks" → "Activate Incoming Webhooks" を ON
4. "Add New Webhook to Workspace" → 通知先チャンネル選択 → "Allow"
5. 表示された Webhook URL (`https://hooks.slack.com/services/...`) をコピー
   → GitHub Secret `SLACK_WEBHOOK_URL` に登録

### 2. Anthropic: API キーと使用料上限を設定

1. https://console.anthropic.com/ にログイン
2. **Settings → Limits → Workspace spend limit** で月額上限を設定 (例: $5)
3. **API Keys → Create Key** で API Key 発行
   → GitHub Secret `ANTHROPIC_API_KEY` に登録

### 3. Gmail: OAuth2 refresh token を取得

#### 3-1. Google Cloud で OAuth クライアントを作る

1. https://console.cloud.google.com/ で新規プロジェクト作成 (例: `job-summary`)
2. **APIとサービス → ライブラリ** → "Gmail API" を有効化
3. **APIとサービス → OAuth同意画面**
   - User Type: **外部**
   - アプリ名/サポートメール/連絡先メール を入力 (他は空でOK)
   - スコープ: **gmail.readonly** を追加
   - テストユーザー: 自分のGmailアドレスを追加 (これ重要)
4. **APIとサービス → 認証情報 → 認証情報を作成 → OAuthクライアントID**
   - アプリの種類: **デスクトップ アプリ**
   - 作成後 JSON をダウンロード → プロジェクト直下に `credentials.json` として保存

#### 3-2. ローカルで一度だけ実行して refresh token を取得

```bash
uv sync
uv run python scripts/get_gmail_token.py
```

ブラウザが開くので自分のGmailで認可. 「Googleで確認されていません」と出たら **詳細 → (アプリ名)に移動 (安全ではないページ)** で進む (自分で作ったアプリなので問題なし).

ターミナルに表示される3つの値を GitHub Secrets に登録:
- `GMAIL_CLIENT_ID`
- `GMAIL_CLIENT_SECRET`
- `GMAIL_REFRESH_TOKEN`

(`credentials.json` は `.gitignore` でコミットされません.)

### 4. GitHub Secrets に登録

リポジトリの **Settings → Secrets and variables → Actions → New repository secret** で以下5つを登録:

| Secret 名 | 値 |
|---|---|
| `SLACK_WEBHOOK_URL` | 手順1で取得 |
| `ANTHROPIC_API_KEY` | 手順2で取得 |
| `GMAIL_CLIENT_ID` | 手順3-2で表示 |
| `GMAIL_CLIENT_SECRET` | 手順3-2で表示 |
| `GMAIL_REFRESH_TOKEN` | 手順3-2で表示 |

(任意) `Variables` タブで `CLAUDE_MODEL` を設定するとモデルを切替できます (デフォルト: `claude-haiku-4-5-20251001`).

### 5. 動作確認

リポジトリの **Actions** タブ → "Job Hunting Email Summary" → **Run workflow** で手動実行. Slack に通知が届けば成功.

それ以降は毎日 JST 9:00 / 17:00 に自動実行されます.

## ローカル実行 (デバッグ用)

```bash
export GMAIL_CLIENT_ID=...
export GMAIL_CLIENT_SECRET=...
export GMAIL_REFRESH_TOKEN=...
export ANTHROPIC_API_KEY=...
export SLACK_WEBHOOK_URL=...
uv run python -m src.main
```

## カスタマイズ

- **重要度の判定基準**: `src/analyzer.py` の `SYSTEM_PROMPT` を編集
- **Gmailのフィルタ**: `src/gmail_client.py` の `fetch_messages` 内 `query_parts` を編集
- **通知時刻**: `.github/workflows/job_summary.yml` の `cron` を編集 (UTC指定)
- **1回あたりの最大メール数**: `src/main.py` の `MAX_EMAILS_PER_RUN`

## ファイル構成

```
.
├── .github/workflows/job_summary.yml   # cron + 実行workflow
├── scripts/get_gmail_token.py          # 初回のみ使う token取得スクリプト
├── src/
│   ├── main.py            # エントリーポイント
│   ├── gmail_client.py    # Gmail API
│   ├── analyzer.py        # Claude API (tool use)
│   └── slack.py           # Slack Webhook (Block Kit)
├── state.json             # 前回実行時刻 (workflowが自動更新)
└── pyproject.toml
```
