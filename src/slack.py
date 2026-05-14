"""Slack chat.postMessage API で親メッセージ + スレッド方式の通知を行う."""

from __future__ import annotations

import logging

import requests

from src.analyzer import AnalysisResult, EmailAnalysis

logger = logging.getLogger(__name__)

API_URL = "https://slack.com/api/chat.postMessage"

IMPORTANCE_EMOJI = {"high": ":rotating_light:", "medium": ":bell:", "low": ":information_source:", "spam": ":no_entry_sign:"}
IMPORTANCE_LABEL = {"high": "重要", "medium": "通常", "low": "参考", "spam": "迷惑"}
IMPORTANCE_ORDER = {"high": 0, "medium": 1, "low": 2, "spam": 3}

MAX_VISIBLE_EMAILS = 25


def _post(bot_token: str, channel: str, text: str, blocks: list[dict] | None = None, thread_ts: str | None = None) -> dict:
    payload: dict = {"channel": channel, "text": text}
    if blocks:
        payload["blocks"] = blocks
    if thread_ts:
        payload["thread_ts"] = thread_ts
    headers = {
        "Authorization": f"Bearer {bot_token}",
        "Content-Type": "application/json; charset=utf-8",
    }
    resp = requests.post(API_URL, headers=headers, json=payload, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if not data.get("ok"):
        err = data.get("error", "unknown")
        if err == "not_in_channel":
            raise RuntimeError(f"Botがチャンネル '{channel}' に参加していません. Slack上で `/invite @<botname>` を実行してください.")
        raise RuntimeError(f"Slack API error: {err} (full: {data})")
    return data


def _build_parent_blocks(
    visible_count: int,
    high_count: int,
    medium_count: int,
    low_count: int,
    spam_count: int,
    total_fetched: int,
    model: str,
    overall_note: str,
    mention_user_id: str | None = None,
) -> list[dict]:
    if visible_count == 0:
        title = ":mailbox_with_mail: 就活メール要約: 対応必要なメールなし"
    else:
        title = f":mailbox_with_mail: 就活メール要約 ({visible_count}件)"

    counts = []
    if high_count:
        counts.append(f":rotating_light: 重要 *{high_count}*")
    if medium_count:
        counts.append(f":bell: 通常 *{medium_count}*")
    if low_count:
        counts.append(f":information_source: 参考 *{low_count}*")
    counts_str = " / ".join(counts) if counts else "_対応が必要なメールはありません_"
    if mention_user_id:
        counts_str = f"<@{mention_user_id}> {counts_str}"

    blocks: list[dict] = [
        {"type": "header", "text": {"type": "plain_text", "text": title, "emoji": True}},
        {"type": "section", "text": {"type": "mrkdwn", "text": counts_str}},
        {
            "type": "context",
            "elements": [
                {"type": "mrkdwn", "text": f"取得: {total_fetched}件 | 除外(迷惑): {spam_count}件 | model: `{model}`"}
            ],
        },
    ]
    if overall_note:
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f"> {overall_note}"}})
    if visible_count > 0:
        blocks.append(
            {"type": "context", "elements": [{"type": "mrkdwn", "text": ":thread: 詳細は下のスレッド. 確認済みは :white_check_mark: でチェック"}]}
        )
    return blocks


def _build_email_blocks(a: EmailAnalysis) -> list[dict]:
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
    return [{"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(lines)}}]


def post(
    bot_token: str,
    channel: str,
    result: AnalysisResult,
    total_fetched: int,
    model: str,
    mention_user_id: str | None = None,
) -> None:
    sorted_analyses = sorted(result.analyses, key=lambda a: IMPORTANCE_ORDER.get(a.importance, 99))
    visible_all = [a for a in sorted_analyses if a.importance != "spam"]
    visible = visible_all[:MAX_VISIBLE_EMAILS]
    spam_count = sum(1 for a in sorted_analyses if a.importance == "spam")
    high_count = sum(1 for a in visible if a.importance == "high")
    medium_count = sum(1 for a in visible if a.importance == "medium")
    low_count = sum(1 for a in visible if a.importance == "low")
    omitted = len(visible_all) - len(visible)

    parent_blocks = _build_parent_blocks(
        visible_count=len(visible),
        high_count=high_count,
        medium_count=medium_count,
        low_count=low_count,
        spam_count=spam_count,
        total_fetched=total_fetched,
        model=model,
        overall_note=result.overall_note,
        mention_user_id=mention_user_id,
    )
    mention_prefix = f"<@{mention_user_id}> " if mention_user_id else ""
    fallback = f"{mention_prefix}就活メール要約: 表示{len(visible)}件 / 取得{total_fetched}件"
    parent_resp = _post(bot_token, channel, fallback, blocks=parent_blocks)
    parent_ts = parent_resp["ts"]
    logger.info("posted parent message, ts=%s", parent_ts)

    for a in visible:
        blocks = _build_email_blocks(a)
        _post(bot_token, channel, a.email.subject[:80] or "(no subject)", blocks=blocks, thread_ts=parent_ts)

    if omitted > 0:
        _post(
            bot_token,
            channel,
            f"他 {omitted}件",
            blocks=[{"type": "section", "text": {"type": "mrkdwn", "text": f":mag: 他 *{omitted}件* (low優先度) は表示省略. Gmailで直接確認."}}],
            thread_ts=parent_ts,
        )

    logger.info("posted %d email replies in thread", len(visible) + (1 if omitted > 0 else 0))
