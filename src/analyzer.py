"""Claude API でメール一括分析. structured output (tool use) で JSON を取得."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Literal

from anthropic import Anthropic

from src.gmail_client import Email

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-haiku-4-5-20251001"
MAX_TOKENS = 4096

SYSTEM_PROMPT = """あなたは就活中のユーザーのGmail受信トレイを整理するアシスタントです.
ユーザーから渡される複数のメールを分析し, 各メールについて以下を判定してください.

# 重要度の基準
- **high**: 即対応が必要 (面接日程の確定/変更, 選考通過/不通過, 内定通知, 期限が48時間以内のもの)
- **medium**: 確認は必要だが急ぎではない (説明会案内, ES提出締切が1週間以上先, 採用担当からの一般連絡)
- **low**: 情報として記録するだけで良い (求人情報, ニュースレター, 自動配信メール)
- **spam**: 就活と無関係 (プロモーション, 通知系の自動メール)

# 出力ルール
- 各メールごとに structured な判定を返す (提供されたtoolを使用)
- summary は日本語で1-2文, 「誰から/何の件で/何をすべきか」を含める
- deadline は本文に明記がある場合のみ ISO 8601 で記載 (なければ null)
- 同じ会社からの連続したメールは個別に判定して良い"""

ANALYZE_TOOL = {
    "name": "submit_email_analysis",
    "description": "メール群の分析結果を提出する.",
    "input_schema": {
        "type": "object",
        "properties": {
            "analyses": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "index": {"type": "integer", "description": "入力メールのインデックス (1始まり)"},
                        "importance": {"type": "string", "enum": ["high", "medium", "low", "spam"]},
                        "category": {
                            "type": "string",
                            "description": "カテゴリ (例: 面接案内, 選考結果, ES提出, 説明会, 内定, その他)",
                        },
                        "company": {"type": "string", "description": "関連企業名 (推測でも可, 不明なら空文字)"},
                        "summary": {"type": "string", "description": "日本語1-2文の要約"},
                        "action_required": {"type": "string", "description": "ユーザーが取るべき行動 (なければ空文字)"},
                        "deadline": {"type": ["string", "null"], "description": "ISO 8601 日時, なければ null"},
                    },
                    "required": ["index", "importance", "category", "company", "summary", "action_required", "deadline"],
                },
            },
            "overall_note": {
                "type": "string",
                "description": "全体に対する一言コメント (任意, 空文字でも良い). 例: '本日中の対応はありません.'",
            },
        },
        "required": ["analyses", "overall_note"],
    },
}


@dataclass
class EmailAnalysis:
    email: Email
    importance: Literal["high", "medium", "low", "spam"]
    category: str
    company: str
    summary: str
    action_required: str
    deadline: str | None


@dataclass
class AnalysisResult:
    analyses: list[EmailAnalysis]
    overall_note: str
    input_tokens: int
    output_tokens: int


def analyze_emails(emails: list[Email], api_key: str, model: str = DEFAULT_MODEL) -> AnalysisResult:
    if not emails:
        return AnalysisResult(analyses=[], overall_note="新着メールはありませんでした.", input_tokens=0, output_tokens=0)

    client = Anthropic(api_key=api_key)
    user_content = "以下のメールを分析してください.\n\n" + "\n".join(
        e.to_prompt_text(i + 1) for i, e in enumerate(emails)
    )

    logger.info("calling Claude (%s) with %d emails", model, len(emails))
    response = client.messages.create(
        model=model,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        tools=[ANALYZE_TOOL],
        tool_choice={"type": "tool", "name": "submit_email_analysis"},
        messages=[{"role": "user", "content": user_content}],
    )

    tool_use = next((b for b in response.content if b.type == "tool_use"), None)
    if tool_use is None:
        raise RuntimeError("Claudeが tool_use を返しませんでした.")
    payload = tool_use.input
    logger.debug("claude payload: %s", json.dumps(payload, ensure_ascii=False)[:500])

    analyses_by_index: dict[int, dict] = {a["index"]: a for a in payload.get("analyses", [])}
    results: list[EmailAnalysis] = []
    for i, email in enumerate(emails, start=1):
        a = analyses_by_index.get(i)
        if a is None:
            logger.warning("Claudeが index=%d の分析を返しませんでした. デフォルト値を適用.", i)
            results.append(
                EmailAnalysis(
                    email=email, importance="low", category="不明",
                    company="", summary=email.snippet[:100], action_required="", deadline=None,
                )
            )
            continue
        results.append(
            EmailAnalysis(
                email=email,
                importance=a.get("importance", "low"),
                category=a.get("category", ""),
                company=a.get("company", ""),
                summary=a.get("summary", ""),
                action_required=a.get("action_required", ""),
                deadline=a.get("deadline"),
            )
        )

    return AnalysisResult(
        analyses=results,
        overall_note=payload.get("overall_note", ""),
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
    )
