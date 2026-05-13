"""エントリーポイント. Gmail取得 → Claude分析 → Slack通知 → state.json更新."""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from src import analyzer, gmail_client, slack

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("main")

STATE_PATH = Path(__file__).resolve().parent.parent / "state.json"
MAX_EMAILS_PER_RUN = 50

REQUIRED_ENV = [
    "GMAIL_CLIENT_ID", "GMAIL_CLIENT_SECRET", "GMAIL_REFRESH_TOKEN",
    "ANTHROPIC_API_KEY", "SLACK_BOT_TOKEN", "SLACK_CHANNEL",
]


def _load_state() -> dict:
    if not STATE_PATH.exists():
        return {"last_run_unix": 0, "last_run_iso": "1970-01-01T00:00:00+00:00"}
    with STATE_PATH.open() as f:
        return json.load(f)


def _save_state(unix_ts: int) -> None:
    iso = datetime.fromtimestamp(unix_ts, tz=timezone.utc).isoformat()
    STATE_PATH.write_text(json.dumps({"last_run_unix": unix_ts, "last_run_iso": iso}, indent=2) + "\n")
    logger.info("state saved: last_run_unix=%d (%s)", unix_ts, iso)


def _check_env() -> dict[str, str]:
    missing = [k for k in REQUIRED_ENV if not os.environ.get(k)]
    if missing:
        logger.error("環境変数が未設定: %s", ", ".join(missing))
        sys.exit(2)
    return {k: os.environ[k] for k in REQUIRED_ENV}


def main() -> int:
    env = _check_env()
    model = os.environ.get("CLAUDE_MODEL", analyzer.DEFAULT_MODEL)
    state = _load_state()
    after_unix = int(state.get("last_run_unix", 0))
    run_start_unix = int(time.time())

    logger.info("=== 実行開始 ===  前回: %s / モデル: %s", state.get("last_run_iso"), model)

    service = gmail_client.build_service(env["GMAIL_CLIENT_ID"], env["GMAIL_CLIENT_SECRET"], env["GMAIL_REFRESH_TOKEN"])
    emails = gmail_client.fetch_messages(service, after_unix=after_unix, max_results=MAX_EMAILS_PER_RUN)

    result = analyzer.analyze_emails(emails, api_key=env["ANTHROPIC_API_KEY"], model=model)
    logger.info(
        "claude usage: input=%d output=%d (model=%s)",
        result.input_tokens, result.output_tokens, model,
    )

    slack.post(
        bot_token=env["SLACK_BOT_TOKEN"],
        channel=env["SLACK_CHANNEL"],
        result=result,
        total_fetched=len(emails),
        model=model,
    )
    _save_state(run_start_unix)

    logger.info("=== 実行完了 ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
