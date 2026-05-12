"""Gmail APIのrefresh tokenを一度だけローカルで取得するスクリプト.

使い方:
    1. Google Cloud Console で OAuth2 クライアント (Desktop アプリ) を作成
    2. ダウンロードした client_secret_*.json を credentials.json にリネームしてプロジェクト直下に置く
    3. uv run python scripts/get_gmail_token.py
    4. ブラウザが開くので自分のGmailアカウントで認可
    5. 表示された refresh_token / client_id / client_secret を GitHub Secrets に登録
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
CREDENTIALS_PATH = Path(__file__).resolve().parent.parent / "credentials.json"


def main() -> int:
    if not CREDENTIALS_PATH.exists():
        print(f"[ERROR] credentials.json が見つかりません: {CREDENTIALS_PATH}")
        print("Google Cloud Console で作成した OAuth クライアントの JSON を")
        print("credentials.json という名前でプロジェクト直下に置いてください.")
        return 1

    flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_PATH), SCOPES)
    creds = flow.run_local_server(port=0, prompt="consent", access_type="offline")

    if not creds.refresh_token:
        print("[ERROR] refresh_token が取得できませんでした.")
        print("Google アカウントの 'アプリのアクセス' から既存の許可を削除して再実行してください.")
        return 1

    with CREDENTIALS_PATH.open() as f:
        client_info = json.load(f)
    installed = client_info.get("installed") or client_info.get("web") or {}

    print("\n" + "=" * 60)
    print("取得成功. 以下の値を GitHub Secrets に登録してください:")
    print("=" * 60)
    print(f"GMAIL_CLIENT_ID:     {installed.get('client_id', '')}")
    print(f"GMAIL_CLIENT_SECRET: {installed.get('client_secret', '')}")
    print(f"GMAIL_REFRESH_TOKEN: {creds.refresh_token}")
    print("=" * 60)
    print("(これらの値は今後変更されません. credentials.json はリポジトリにコミットされません.)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
