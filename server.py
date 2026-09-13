"""Web Application Server for Email Summarizer.

Provides a fast, beautiful dashboard to view previous summarized emails,
filter by labels, trigger inbox sync, and forward to Apple Messages.
Includes a dedicated /login UI for user authentication with Gmail and Google App Passwords.
"""

from __future__ import annotations

import imaplib
import os
import re
import sys
from typing import Optional
from dotenv import load_dotenv, set_key
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import database
from gmail_service import GmailApiClient, GmailImapClient, get_mock_emails
from notifier import copy_to_clipboard, send_macos_notification, send_to_apple_messages
from summarizer import DEFAULT_CHAT_MODEL, EmailSummarizer

load_dotenv()

app = FastAPI(title="MailBrief AI - Email Summarizer App")

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Ensure database is ready
database.init_db()

# Serve static folder
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
if not os.path.exists(STATIC_DIR):
    os.makedirs(STATIC_DIR)

ENV_FILE_PATH = os.path.join(os.path.dirname(__file__), ".env")

# In-memory runtime session for connected credentials
ACTIVE_CREDENTIALS = {
    "user": os.getenv("GMAIL_USER", "").strip(),
    "password": os.getenv("GMAIL_APP_PASSWORD", "").strip(),
}


class ConnectRequest(BaseModel):
    email: str
    app_password: str


class SyncRequest(BaseModel):
    max_emails: int = 5
    unread_only: bool = False
    dry_run: bool = False


class SendMessageRequest(BaseModel):
    email_id: str
    recipient: Optional[str] = None


@app.get("/api/auth/status")
def auth_status():
    """Check current authentication status and connected email."""
    user = ACTIVE_CREDENTIALS.get("user") or os.getenv("GMAIL_USER", "").strip()
    pwd = ACTIVE_CREDENTIALS.get("password") or os.getenv("GMAIL_APP_PASSWORD", "").strip()
    is_valid = bool(user and pwd and pwd != "your_16_character_app_password")
    return {
        "connected": is_valid,
        "email": user if is_valid else "",
        "auth_mode": os.getenv("GMAIL_AUTH_MODE", "imap"),
    }


@app.post("/api/auth/connect")
def connect_account(req: ConnectRequest):
    """Verify and connect user's Gmail using Google App Password."""
    email = req.email.strip().lower()
    app_password = req.app_password.strip().replace(" ", "")

    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="Please enter a valid Gmail address.")

    if not app_password or len(app_password) < 8:
        raise HTTPException(
            status_code=400,
            detail="Google App Password must be 16 characters. Click the link below to generate one.",
        )

    # Test real authentication with Gmail IMAP
    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(email, app_password)
        mail.logout()
    except imaplib.IMAP4.error as e:
        err_msg = str(e)
        if "AuthenticationFailed" in err_msg or "invalid credentials" in err_msg.lower():
            raise HTTPException(
                status_code=401,
                detail=(
                    "Invalid email or App Password. "
                    "Make sure you are using a 16-character Google App Password (not your normal Gmail password), "
                    "that 2-Step Verification is ON, and IMAP is enabled in Gmail settings."
                ),
            )
        raise HTTPException(status_code=401, detail=f"Google IMAP Login error: {err_msg}")
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Network error connecting to imap.gmail.com: {str(e)}",
        )

    # Save credentials in runtime session
    ACTIVE_CREDENTIALS["user"] = email
    ACTIVE_CREDENTIALS["password"] = app_password

    # Also persist to local .env if available
    try:
        if os.path.exists(ENV_FILE_PATH):
            set_key(ENV_FILE_PATH, "GMAIL_USER", email)
            set_key(ENV_FILE_PATH, "GMAIL_APP_PASSWORD", app_password)
            set_key(ENV_FILE_PATH, "GMAIL_AUTH_MODE", "imap")
    except Exception:
        pass

    return {
        "status": "success",
        "message": "Gmail account connected and verified successfully!",
        "email": email,
    }


@app.post("/api/auth/disconnect")
def disconnect_account():
    """Clear active session credentials."""
    ACTIVE_CREDENTIALS["user"] = ""
    ACTIVE_CREDENTIALS["password"] = ""
    return {"status": "success", "message": "Disconnected"}


@app.get("/api/emails")
def list_emails(
    label: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
):
    """Fetch previously stored emails filtered by label or search query."""
    emails = database.get_all_emails(label=label, search=search, limit=limit)
    return {"status": "success", "count": len(emails), "emails": emails}


@app.get("/api/labels")
def list_labels():
    """Fetch label categories and item counts."""
    counts = database.get_labels_summary()
    return {"status": "success", "labels": counts}


@app.get("/api/stats")
def get_stats():
    """Quick statistics for top cards."""
    counts = database.get_labels_summary()
    total = counts.get("All", 0)
    security = counts.get("Security", 0)
    meetings = counts.get("Meeting", 0)
    actions = counts.get("Action Required", 0)
    work = counts.get("Work", 0)
    return {
        "total": total,
        "security": security,
        "meetings": meetings,
        "actions": actions,
        "work": work,
    }


@app.post("/api/sync")
def sync_emails(req: SyncRequest):
    """Sync emails from Google inbox or mock generator, summarize, and store in database."""
    hf_token = os.getenv("HF_TOKEN")
    hf_model = os.getenv("HF_MODEL") or DEFAULT_CHAT_MODEL
    auth_mode = os.getenv("GMAIL_AUTH_MODE", "imap").lower()
    enable_notifications = os.getenv("ENABLE_DESKTOP_NOTIFICATIONS", "true").lower() == "true"

    emails = []
    mode_used = "dry-run" if req.dry_run else auth_mode

    if req.dry_run:
        emails = get_mock_emails()[: req.max_emails]
    else:
        try:
            if auth_mode == "oauth":
                client = GmailApiClient()
                emails = client.fetch_recent_emails(max_results=req.max_emails, unread_only=req.unread_only)
            else:
                user = ACTIVE_CREDENTIALS.get("user") or os.getenv("GMAIL_USER")
                pwd = ACTIVE_CREDENTIALS.get("password") or os.getenv("GMAIL_APP_PASSWORD")

                if not user or not pwd or pwd == "your_16_character_app_password":
                    raise HTTPException(
                        status_code=400,
                        detail="No Gmail credentials configured. Please connect your account first at /login.",
                    )

                client = GmailImapClient(username=user, app_password=pwd)
                emails = client.fetch_recent_emails(max_results=req.max_emails, unread_only=req.unread_only)
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to fetch emails: {str(e)}")

    summarizer = EmailSummarizer(token=hf_token, model=hf_model)
    processed_count = 0
    new_count = 0

    for item in emails:
        already_cached = database.is_email_stored(item.id)
        if not already_cached:
            summary_data = summarizer.summarize(
                sender=item.sender,
                subject=item.subject,
                date=item.date,
                body=item.body,
            )
            database.save_email(
                email_id=item.id,
                sender=item.sender,
                subject=item.subject,
                date=item.date,
                snippet=item.snippet,
                body=item.body,
                summary=summary_data["summary"],
                key_takeaway=summary_data["key_takeaway"],
                action_items=summary_data["action_items"],
                label=summary_data["label"],
            )
            new_count += 1
            if enable_notifications:
                send_macos_notification(
                    title=f"New Email: {item.subject[:30]}",
                    subtitle=f"[{summary_data['label']}] {item.sender.split('<')[0].strip()}",
                    message=summary_data["key_takeaway"] or item.snippet[:120],
                )
        processed_count += 1

    return {
        "status": "success",
        "mode": mode_used,
        "total_fetched": len(emails),
        "new_summarized": new_count,
        "already_cached": processed_count - new_count,
    }


@app.post("/api/send-message")
def send_message_endpoint(req: SendMessageRequest):
    """Forward an email summary to Apple Messages app."""
    target_recipient = req.recipient or os.getenv("MESSAGES_RECIPIENT", "").strip()
    if not target_recipient:
        raise HTTPException(
            status_code=400,
            detail="Recipient phone number or Apple ID is required. Specify in request or .env.",
        )

    emails = database.get_all_emails(search=None, limit=500)
    match = next((e for e in emails if e["id"] == req.email_id), None)
    if not match:
        raise HTTPException(status_code=404, detail="Email not found in database.")

    msg_payload = (
        f"📬 Email Summary [{match['label']}]:\n"
        f"Subject: {match['subject']}\n"
        f"From: {match['sender']}\n\n"
        f"Key Takeaway: {match['key_takeaway']}\n\n"
        f"Action Items:\n{match['action_items']}\n\n"
        f"Full Summary:\n{match['summary']}"
    )

    success = send_to_apple_messages(recipient=target_recipient, message=msg_payload)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to send message via AppleScript.")

    return {"status": "success", "recipient": target_recipient}


@app.delete("/api/emails/{email_id}")
def delete_email(email_id: str):
    """Delete an email record from the database."""
    conn = database.get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM emails WHERE id = ?", (email_id,))
    conn.commit()
    conn.close()
    return {"status": "success", "deleted_id": email_id}


# Serve Login / Connect UI page
@app.api_route("/login", methods=["GET", "HEAD"])
def serve_login():
    return FileResponse(os.path.join(STATIC_DIR, "login.html"))


# Serve SPA dashboard index
@app.api_route("/", methods=["GET", "HEAD"])
def serve_index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


# Mount static assets
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def run_server(host: str = "127.0.0.1", port: int = 8000):
    import uvicorn
    print(f"🚀 Starting Email Summarizer Web App at http://{host}:{port}")
    uvicorn.run("server:app", host=host, port=port, reload=True)


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    run_server(port=port)
