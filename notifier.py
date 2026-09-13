"""Notification and Messages Sharing Module for macOS.

Handles:
1. Native macOS desktop notifications (Notification Center alerts with sound).
2. Direct dispatch to Apple Messages app (iMessage/SMS) using AppleScript.
3. macOS clipboard sync (pbcopy) for instant pasting.
"""

from __future__ import annotations

import subprocess
import sys


def _escape_applescript_string(text: str) -> str:
    """Escape backslashes and double quotes for AppleScript string literals."""
    return text.replace("\\", "\\\\").replace('"', '\\"').replace("\r", " ").replace("\n", "\\n")


def send_macos_notification(
    title: str,
    subtitle: str,
    message: str,
    sound: str = "Glass",
) -> bool:
    """Send a native macOS desktop notification using osascript.
    
    Args:
        title: Main notification title (e.g. "Email Summarizer")
        subtitle: Subtitle (e.g. Sender or Subject)
        message: Body preview of the summary
        sound: Sound effect (e.g. "Glass", "Ping", "Submarine", or None)
    """
    if sys.platform != "darwin":
        print(f"[Desktop Notification Mock] [{title}] {subtitle}: {message}")
        return False

    escaped_title = _escape_applescript_string(title)
    escaped_subtitle = _escape_applescript_string(subtitle)
    # Truncate message for the notification banner so it doesn't get clipped awkwardly
    clean_msg = message.replace("\n", " ").strip()
    if len(clean_msg) > 160:
        clean_msg = clean_msg[:157] + "..."
    escaped_msg = _escape_applescript_string(clean_msg)

    sound_clause = f' sound name "{sound}"' if sound else ""
    script = (
        f'display notification "{escaped_msg}" with title "{escaped_title}" '
        f'subtitle "{escaped_subtitle}"{sound_clause}'
    )

    try:
        res = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, check=False)
        return res.returncode == 0
    except Exception as e:
        print(f"Failed to display desktop notification: {e}")
        return False


def send_to_apple_messages(
    recipient: str,
    message: str,
) -> bool:
    """Send an iMessage / SMS using the macOS Messages application via AppleScript.

    Args:
        recipient: Phone number (e.g., "+15551234567") or Apple ID email address.
        message: The text content to send.
    """
    if sys.platform != "darwin":
        print(f"[Messages App Mock] To {recipient}: {message}")
        return False

    if not recipient or not recipient.strip():
        print("No recipient specified for Messages app.")
        return False

    escaped_recipient = _escape_applescript_string(recipient.strip())
    escaped_message = _escape_applescript_string(message.strip())

    script = f'''
    tell application "Messages"
        try
            set targetService to 1st service whose service type = iMessage
            set targetBuddy to buddy "{escaped_recipient}" of targetService
            send "{escaped_message}" to targetBuddy
            return "SUCCESS"
        on error errMsg
            -- Fallback: try default service
            try
                set targetBuddy to buddy "{escaped_recipient}"
                send "{escaped_message}" to targetBuddy
                return "SUCCESS"
            on error secondaryError
                return "ERROR: " & secondaryError
            end try
        end try
    end tell
    '''

    try:
        res = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, check=False)
        if "SUCCESS" in res.stdout:
            return True
        else:
            print(f"Apple Messages send warning: {res.stdout or res.stderr}")
            return False
    except Exception as e:
        print(f"Failed to send via Apple Messages: {e}")
        return False


def copy_to_clipboard(text: str) -> bool:
    """Copy text to macOS clipboard using pbcopy."""
    if sys.platform != "darwin":
        return False
    try:
        proc = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE)
        proc.communicate(text.encode("utf-8"))
        return proc.returncode == 0
    except Exception:
        return False
