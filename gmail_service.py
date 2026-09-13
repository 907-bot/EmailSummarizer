"""Google Email Access Module (Gmail API & IMAP).

Supports:
1. Google Gmail API with OAuth2 (token.json persistence).
2. Gmail IMAP with Google App Password as a quick zero-GCP-setup alternative.
"""

from __future__ import annotations

import base64
import email
from email.header import decode_header
import email.policy
import html
import imaplib
import os
import re
from dataclasses import dataclass
from typing import List, Optional

from bs4 import BeautifulSoup

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


@dataclass
class EmailItem:
    id: str
    sender: str
    subject: str
    date: str
    snippet: str
    body: str

    def format_preview(self, max_length: int = 400) -> str:
        clean_snippet = self.snippet.replace("\n", " ").strip()
        if len(clean_snippet) > max_length:
            return clean_snippet[:max_length] + "..."
        return clean_snippet


def clean_html_to_text(content: str) -> str:
    """Convert HTML email bodies to clean readable plaintext."""
    if not content:
        return ""
    
    # Unescape HTML entities first
    content = html.unescape(content)
    
    # If contains HTML tags
    if "<" in content and ">" in content:
        soup = BeautifulSoup(content, "html.parser")
        # Remove script and style elements
        for element in soup(["script", "style", "head", "meta", "noscript"]):
            element.decompose()
        text = soup.get_text(separator="\n")
    else:
        text = content

    # Clean whitespace and repetitive lines
    lines = [line.strip() for line in text.splitlines()]
    clean_lines = []
    prev_blank = False
    for line in lines:
        if not line:
            if not prev_blank:
                clean_lines.append("")
                prev_blank = True
        else:
            clean_lines.append(line)
            prev_blank = False

    cleaned_text = "\n".join(clean_lines).strip()
    return cleaned_text


def _decode_base64(data_str: str) -> str:
    """Decode base64url encoded string from Gmail API."""
    if not data_str:
        return ""
    try:
        data = base64.urlsafe_b64decode(data_str.encode("ASCII"))
        return data.decode("utf-8", errors="replace")
    except Exception:
        return ""


def _extract_body_from_gmail_payload(payload: dict) -> str:
    """Extract plain text or HTML body from a Gmail API message payload."""
    mime_type = payload.get("mimeType", "")
    body_data = payload.get("body", {}).get("data")

    if mime_type == "text/plain" and body_data:
        return clean_html_to_text(_decode_base64(body_data))

    plain_text_parts = []
    html_parts = []

    def _walk_parts(parts: list):
        for part in parts:
            part_mime = part.get("mimeType", "")
            data = part.get("body", {}).get("data")
            if part_mime == "text/plain" and data:
                plain_text_parts.append(_decode_base64(data))
            elif part_mime == "text/html" and data:
                html_parts.append(_decode_base64(data))
            if "parts" in part:
                _walk_parts(part["parts"])

    if "parts" in payload:
        _walk_parts(payload["parts"])

    if plain_text_parts:
        return clean_html_to_text("\n".join(plain_text_parts))
    if html_parts:
        return clean_html_to_text("\n".join(html_parts))
    if body_data:
        return clean_html_to_text(_decode_base64(body_data))

    return ""


class GmailApiClient:
    """Access emails using the official Google Gmail REST API via OAuth2."""

    def __init__(self, credentials_path: str = "credentials.json", token_path: str = "token.json"):
        self.credentials_path = credentials_path
        self.token_path = token_path
        self.service = None

    def authenticate(self) -> None:
        """Authenticate using local OAuth tokens or client credentials."""
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build

        creds = None
        if os.path.exists(self.token_path):
            creds = Credentials.from_authorized_user_file(self.token_path, SCOPES)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                if not os.path.exists(self.credentials_path):
                    raise FileNotFoundError(
                        f"Google credentials file '{self.credentials_path}' not found.\n"
                        "Please download your OAuth client credentials from Google Cloud Console "
                        f"and save it as '{self.credentials_path}', or switch to IMAP mode."
                    )
                flow = InstalledAppFlow.from_client_secrets_file(self.credentials_path, SCOPES)
                creds = flow.run_local_server(port=0)

            with open(self.token_path, "w") as token:
                token.write(creds.to_json())

        self.service = build("gmail", "v1", credentials=creds)

    def fetch_recent_emails(self, max_results: int = 5, unread_only: bool = True) -> List[EmailItem]:
        """Fetch emails from the user's Gmail inbox."""
        if not self.service:
            self.authenticate()

        query = "label:INBOX is:unread" if unread_only else "label:INBOX"
        results = (
            self.service.users()
            .messages()
            .list(userId="me", q=query, maxResults=max_results)
            .execute()
        )

        messages = results.get("messages", [])
        email_items: List[EmailItem] = []

        for msg_summary in messages:
            msg = (
                self.service.users()
                .messages()
                .get(userId="me", id=msg_summary["id"], format="full")
                .execute()
            )

            headers = {h["name"].lower(): h["value"] for h in msg.get("payload", {}).get("headers", [])}
            sender = headers.get("from", "Unknown Sender")
            subject = headers.get("subject", "(No Subject)")
            date = headers.get("date", "")
            snippet = msg.get("snippet", "")
            body = _extract_body_from_gmail_payload(msg.get("payload", {}))

            if not body:
                body = snippet

            email_items.append(
                EmailItem(
                    id=msg["id"],
                    sender=sender,
                    subject=subject,
                    date=date,
                    snippet=snippet,
                    body=body,
                )
            )

        return email_items


class GmailImapClient:
    """Access Gmail via IMAP with Google App Password (alternative to OAuth)."""

    def __init__(self, username: str, app_password: str):
        self.username = username
        self.app_password = app_password

    def _decode_header_str(self, header_value: Optional[str]) -> str:
        if not header_value:
            return ""
        decoded_parts = decode_header(header_value)
        result = []
        for text, encoding in decoded_parts:
            if isinstance(text, bytes):
                result.append(text.decode(encoding or "utf-8", errors="replace"))
            else:
                result.append(str(text))
        return "".join(result)

    def fetch_recent_emails(self, max_results: int = 5, unread_only: bool = True) -> List[EmailItem]:
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        try:
            mail.login(self.username, self.app_password)
            mail.select("INBOX")

            search_criterion = "UNSEEN" if unread_only else "ALL"
            status, message_ids = mail.search(None, search_criterion)

            if status != "OK" or not message_ids or not message_ids[0]:
                return []

            ids = message_ids[0].split()
            # Get latest emails (reverse order)
            latest_ids = ids[-max_results:][::-1]

            email_items: List[EmailItem] = []
            for msg_id in latest_ids:
                res, data = mail.fetch(msg_id, "(RFC822)")
                if res != "OK":
                    continue

                raw_email = data[0][1]
                msg = email.message_from_bytes(raw_email, policy=email.policy.default)

                subject = self._decode_header_str(msg.get("Subject", "(No Subject)"))
                sender = self._decode_header_str(msg.get("From", "Unknown Sender"))
                date = msg.get("Date", "")

                body = ""
                if msg.is_multipart():
                    for part in msg.walk():
                        content_type = part.get_content_type()
                        content_disposition = str(part.get("Content-Disposition", ""))
                        if "attachment" not in content_disposition:
                            if content_type == "text/plain":
                                payload = part.get_payload(decode=True)
                                if payload:
                                    body += payload.decode(part.get_content_charset() or "utf-8", errors="replace")
                            elif content_type == "text/html" and not body:
                                payload = part.get_payload(decode=True)
                                if payload:
                                    body = clean_html_to_text(payload.decode(part.get_content_charset() or "utf-8", errors="replace"))
                else:
                    payload = msg.get_payload(decode=True)
                    if payload:
                        charset = msg.get_content_charset() or "utf-8"
                        body = payload.decode(charset, errors="replace")
                        if msg.get_content_type() == "text/html":
                            body = clean_html_to_text(body)

                snippet = body[:200].replace("\n", " ").strip() if body else ""

                email_items.append(
                    EmailItem(
                        id=msg_id.decode("utf-8", errors="ignore"),
                        sender=sender,
                        subject=subject,
                        date=date,
                        snippet=snippet,
                        body=body.strip(),
                    )
                )

            return email_items
        finally:
            try:
                mail.close()
                mail.logout()
            except Exception:
                pass


def get_mock_emails() -> List[EmailItem]:
    """Generate realistic mock emails for demonstration, dry-run, and testing."""
    return [
        EmailItem(
            id="mock-101",
            sender="Sarah Chen <sarah.chen@techcorp.io>",
            subject="Q3 Product Roadmap Review & Action Items",
            date="Sun, 13 Sep 2026 09:30:00 +0000",
            snippet="Hi team, here is the summary from yesterday's roadmap sync...",
            body="""Hi team,

Following up on our Q3 Product Roadmap sync yesterday, here are the key takeaways and items requiring immediate attention:

1. Feature Freeze Date: Scheduled for October 15th. Please ensure all pull requests for the core engine are merged by end of this week.
2. Beta Testing: The external pilot program with 5 enterprise partners begins on November 1st.
3. Architecture Decision: We decided to adopt the event-driven notifications pipeline. Abhishek, could you please review the architecture RFC doc by Wednesday end of day?
4. Next Meeting: Our next check-in is this Thursday at 2:00 PM PST.

Please let me know if anyone has questions or blockers.

Best regards,
Sarah Chen
VP of Product, TechCorp""",
        ),
        EmailItem(
            id="mock-102",
            sender="Security Alerts <no-reply@security.cloudprovider.com>",
            subject="Action Required: IAM Access Key Rotation Reminder",
            date="Sun, 13 Sep 2026 11:15:00 +0000",
            snippet="Your access key AKIA... has not been rotated in 90 days...",
            body="""Hello Administrator,

This is an automated notification regarding security compliance for account #49281.

Your access key ID AKIA************ has reached 90 days of age and must be rotated per company policy within the next 7 days to maintain uninterrupted API access.

Recommended Steps:
1. Create a new access key in your IAM console.
2. Update your environment secrets and CI/CD pipelines.
3. Verify that the new key functions properly.
4. Deactivate and delete the older key.

If you have already rotated this key in the last 2 hours, please disregard this notice.

Security Compliance Team""",
        ),
        EmailItem(
            id="mock-103",
            sender="Alex Martinez <alex.m@partnerships.net>",
            subject="Coffee catch-up next Tuesday in SF?",
            date="Sun, 13 Sep 2026 14:00:00 +0000",
            snippet="Hey Abhishek! Hope you're doing well. I'll be in town...",
            body="""Hey Abhishek!

Hope you're having a productive week.

I'll be visiting San Francisco next Tuesday and Wednesday for the AI Developers Summit. Would love to catch up over coffee or lunch on Tuesday around 1:30 PM near Financial District if your schedule allows.

Let me know if that time works for you, or propose any other slot that's convenient!

Cheers,
Alex""",
        ),
    ]
