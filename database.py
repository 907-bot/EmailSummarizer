"""SQLite Database module for storing summarized emails with labels and metadata."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Any, Dict, List, Optional

DB_PATH = "emails.db"


def get_db_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Initialize SQLite database tables."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS emails (
            id TEXT PRIMARY KEY,
            sender TEXT,
            subject TEXT,
            date TEXT,
            snippet TEXT,
            body TEXT,
            summary TEXT,
            key_takeaway TEXT,
            action_items TEXT,
            label TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_emails_label ON emails(label)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_emails_created_at ON emails(created_at)")
    conn.commit()
    conn.close()


def is_email_stored(email_id: str) -> bool:
    """Check if an email is already processed and stored in the database."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM emails WHERE id = ?", (email_id,))
    row = cursor.fetchone()
    conn.close()
    return row is not None


def save_email(
    email_id: str,
    sender: str,
    subject: str,
    date: str,
    snippet: str,
    body: str,
    summary: str,
    key_takeaway: str = "",
    action_items: str = "",
    label: str = "General",
) -> None:
    """Insert or update an email record in SQLite."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO emails (
            id, sender, subject, date, snippet, body, summary,
            key_takeaway, action_items, label, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            sender=excluded.sender,
            subject=excluded.subject,
            date=excluded.date,
            snippet=excluded.snippet,
            body=excluded.body,
            summary=excluded.summary,
            key_takeaway=excluded.key_takeaway,
            action_items=excluded.action_items,
            label=excluded.label
        """,
        (
            email_id,
            sender,
            subject,
            date,
            snippet,
            body,
            summary,
            key_takeaway,
            action_items,
            label,
            datetime.now().isoformat(),
        ),
    )
    conn.commit()
    conn.close()


def get_all_emails(
    label: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    """Retrieve emails with optional label filter and text search."""
    conn = get_db_connection()
    cursor = conn.cursor()

    query = "SELECT * FROM emails WHERE 1=1"
    params: List[Any] = []

    if label and label.lower() != "all":
        query += " AND label = ?"
        params.append(label)

    if search and search.strip():
        search_pattern = f"%{search.strip()}%"
        query += " AND (subject LIKE ? OR sender LIKE ? OR summary LIKE ? OR body LIKE ?)"
        params.extend([search_pattern, search_pattern, search_pattern, search_pattern])

    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)

    cursor.execute(query, params)
    rows = cursor.fetchall()
    results = [dict(row) for row in rows]
    conn.close()
    return results


def get_labels_summary() -> Dict[str, int]:
    """Return count of emails per label."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT label, COUNT(*) as count FROM emails GROUP BY label ORDER BY count DESC")
    rows = cursor.fetchall()
    summary = {row["label"]: row["count"] for row in rows}
    
    cursor.execute("SELECT COUNT(*) as total FROM emails")
    total_row = cursor.fetchone()
    summary["All"] = total_row["total"] if total_row else 0
    
    conn.close()
    return summary


# Auto-initialize database on import
init_db()
