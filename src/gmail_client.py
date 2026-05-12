"""Gmail API クライアント. refresh token から認証してメールを取得する."""

from __future__ import annotations

import base64
import logging
import re
from dataclasses import dataclass
from email.utils import parseaddr

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
TOKEN_URI = "https://oauth2.googleapis.com/token"


@dataclass
class Email:
    id: str
    thread_id: str
    subject: str
    sender: str
    sender_email: str
    date: str
    snippet: str
    body: str

    def to_prompt_text(self, index: int) -> str:
        body = self.body[:3000] if self.body else self.snippet
        return (
            f"--- メール #{index} ---\n"
            f"件名: {self.subject}\n"
            f"差出人: {self.sender} <{self.sender_email}>\n"
            f"日時: {self.date}\n"
            f"本文:\n{body}\n"
        )

    def gmail_url(self) -> str:
        return f"https://mail.google.com/mail/u/0/#inbox/{self.id}"


def build_service(client_id: str, client_secret: str, refresh_token: str):
    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri=TOKEN_URI,
        client_id=client_id,
        client_secret=client_secret,
        scopes=SCOPES,
    )
    creds.refresh(Request())
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def _decode_body(data: str) -> str:
    if not data:
        return ""
    try:
        return base64.urlsafe_b64decode(data.encode("ASCII")).decode("utf-8", errors="replace")
    except Exception as e:
        logger.warning("body decode failed: %s", e)
        return ""


def _extract_body(payload: dict) -> str:
    """MIMEツリーから text/plain を優先的に取り出す. なければ text/html を平文化."""
    if not payload:
        return ""
    mime_type = payload.get("mimeType", "")
    body = payload.get("body", {}) or {}
    data = body.get("data")

    if mime_type == "text/plain" and data:
        return _decode_body(data)

    parts = payload.get("parts") or []
    for part in parts:
        if part.get("mimeType") == "text/plain":
            text = _extract_body(part)
            if text:
                return text
    for part in parts:
        text = _extract_body(part)
        if text:
            return text

    if mime_type == "text/html" and data:
        html = _decode_body(data)
        return re.sub(r"<[^>]+>", " ", html)
    return ""


def _get_header(headers: list[dict], name: str) -> str:
    for h in headers:
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


def fetch_messages(service, after_unix: int, max_results: int = 100) -> list[Email]:
    """after_unix 以降に受信したメール (受信トレイ) を取得."""
    query_parts = ["in:inbox", "-category:promotions", "-category:social"]
    if after_unix > 0:
        query_parts.append(f"after:{after_unix}")
    query = " ".join(query_parts)
    logger.info("gmail query: %s", query)

    emails: list[Email] = []
    page_token: str | None = None
    fetched = 0

    while True:
        resp = (
            service.users()
            .messages()
            .list(userId="me", q=query, maxResults=min(100, max_results - fetched), pageToken=page_token)
            .execute()
        )
        ids = resp.get("messages", []) or []
        for m in ids:
            if fetched >= max_results:
                break
            msg = service.users().messages().get(userId="me", id=m["id"], format="full").execute()
            payload = msg.get("payload", {}) or {}
            headers = payload.get("headers", []) or []
            subject = _get_header(headers, "Subject")
            from_raw = _get_header(headers, "From")
            sender_name, sender_email = parseaddr(from_raw)
            date = _get_header(headers, "Date")
            body = _extract_body(payload)
            emails.append(
                Email(
                    id=msg["id"],
                    thread_id=msg.get("threadId", ""),
                    subject=subject or "(件名なし)",
                    sender=sender_name or sender_email or from_raw,
                    sender_email=sender_email,
                    date=date,
                    snippet=msg.get("snippet", ""),
                    body=body,
                )
            )
            fetched += 1
        page_token = resp.get("nextPageToken")
        if not page_token or fetched >= max_results:
            break

    logger.info("fetched %d emails", len(emails))
    return emails
