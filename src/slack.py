"""Slack Incoming Webhook で Block Kit 整形メッセージを投稿."""

from __future__ import annotations

import logging

import requests

from src.analyzer import AnalysisResult, EmailAnalysis

logger = logging.getLogger(__name__)

IMPORTANCE_EMOJI = {"high": ":rotating_light:", "medium": ":bell:", "low": ":information_source:", "spam": ":no_entry_sign:"}
IMPORTANCE_LABEL = {"high": "重要", "medium": "通常", "low": "参考", "spam": "迷惑"}
IMPORTANCE_ORDER = {"high": 0, "medium": 1, "low": 2, "spam": 3}

MAX_VISIBLE_EMAILS = 20  # Slack の 50 ブロック制限内に収めるため


def _build_blocks(result: AnalysisResult, total_fetched: int, model: str) -> list[dict]:
    sorted_analyses = sorted(result.analyses, key=lambda a: IMPORTANCE_ORDER.get(a.importance, 99))
    visible_all = [a for a in sorted_analyses if a.importance != "spam"]
    visible = visible_all[:MAX_VISIBLE_EMAILS]
    omitted = len(visible_all) - len(visible)
    spam_count = sum(1 for a in sorted_analyses if a.importance == "spam")

    blocks: list[dict] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": ":mailbox_with_mail: 就活メール要約", "emoji": True},
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f"取得: {total_fetched}件 | 表示: {len(visible)}件 | 除外(迷惑): {spam_count}件 | model: `{model}`",
                }
            ],
        },
    ]

    if result.overall_note:
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f"_{result.overall_note}_"}})

    if not visible:
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": ":white_check_mark: 対応が必要なメールはありません."}})
        return blocks

    blocks.append({"type": "divider"})
    for a in visible:
        blocks.extend(_build_email_block(a))

    if omitted > 0:
        blocks.append(
            {"type": "section", "text": {"type": "mrkdwn", "text": f":mag: 他 *{omitted}件* (low優先度) は表示省略. Gmailで直接確認."}}
        )
    return blocks


def _build_email_block(a: EmailAnalysis) -> list[dict]:
    emoji = IMPORTANCE_EMOJI.get(a.importance, ":email:")
    label = IMPORTANCE_LABEL.get(a.importance, a.importance)
    company = a.company or "(企業不明)"
    subject = a.email.subject[:80]
    lines = [f"*{emoji} [{label}] {company} — {a.category}*", f"件名: {subject}", f"要約: {a.summary}"]
    if a.action_required:
        lines.append(f":pushpin: *対応*: {a.action_required}")
    if a.deadline:
        lines.append(f":alarm_clock: *期限*: {a.deadline}")
    lines.append(f"<{a.email.gmail_url()}|Gmailで開く>")
    return [
        {"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(lines)}},
        {"type": "divider"},
    ]


def post(webhook_url: str, result: AnalysisResult, total_fetched: int, model: str) -> None:
    blocks = _build_blocks(result, total_fetched, model)
    fallback = f"就活メール要約: 取得{total_fetched}件 / 表示{len([a for a in result.analyses if a.importance != 'spam'])}件"
    payload = {"text": fallback, "blocks": blocks}
    logger.info("posting to Slack: %d blocks", len(blocks))
    resp = requests.post(webhook_url, json=payload, timeout=30)
    resp.raise_for_status()
