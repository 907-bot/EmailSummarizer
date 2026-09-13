#!/usr/bin/env python3
"""Email Summarizer CLI.

Fetches emails via Google (Gmail API or IMAP), summarizes them using
a free Hugging Face LLM, and delivers summaries to macOS notifications and Messages app.
"""

import argparse
import os
import sys
import time
from dotenv import load_dotenv

from database import get_all_emails, get_labels_summary, is_email_stored, save_email
from gmail_service import GmailApiClient, GmailImapClient, get_mock_emails
from notifier import copy_to_clipboard, send_macos_notification, send_to_apple_messages
from summarizer import DEFAULT_CHAT_MODEL, EmailSummarizer


def parse_args():
    parser = argparse.ArgumentParser(
        description="Summarize Google emails with free Hugging Face LLM and notify via macOS Messages/Notifications."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run using realistic mock emails to test the summarizer, database, and notifications.",
    )
    parser.add_argument(
        "--max-emails",
        "-n",
        type=int,
        default=None,
        help="Maximum number of emails to summarize (default from .env or 5).",
    )
    parser.add_argument(
        "--all-emails",
        action="store_true",
        help="Fetch all recent inbox emails instead of only unread ones.",
    )
    parser.add_argument(
        "--mode",
        choices=["oauth", "imap"],
        default=None,
        help="Google email authentication mode: 'oauth' (Gmail API) or 'imap' (App password).",
    )
    parser.add_argument(
        "--recipient",
        "-r",
        type=str,
        default=None,
        help="Apple Messages recipient (phone number or Apple ID email).",
    )
    parser.add_argument(
        "--no-notify",
        action="store_true",
        help="Disable macOS desktop notifications.",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help=f"Hugging Face model to use (default: {DEFAULT_CHAT_MODEL}).",
    )
    parser.add_argument(
        "--copy",
        action="store_true",
        help="Copy the combined email summaries to the macOS clipboard.",
    )
    parser.add_argument(
        "--history",
        action="store_true",
        help="Display all previously stored emails and summaries from the database.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force re-summarize emails even if already saved in database.",
    )
    return parser.parse_args()


def main():
    # Load environment variables from .env file
    load_dotenv()

    args = parse_args()

    max_emails = args.max_emails or int(os.getenv("MAX_EMAILS", "3"))
    unread_only = not args.all_emails
    auth_mode = args.mode or os.getenv("GMAIL_AUTH_MODE", "oauth").lower()
    enable_notifications = not args.no_notify and (
        os.getenv("ENABLE_DESKTOP_NOTIFICATIONS", "true").lower() == "true"
    )
    recipient = args.recipient or os.getenv("MESSAGES_RECIPIENT", "").strip()
    hf_token = os.getenv("HF_TOKEN")
    hf_model = args.model or os.getenv("HF_MODEL") or DEFAULT_CHAT_MODEL

    print("=" * 65)
    print(" 📬 EMAIL SUMMARIZER (Hugging Face LLM + Google Mail + macOS)")
    print("=" * 65)
    print(f"• Mode: {'DRY RUN (Mock Data)' if args.dry_run else f'Google Email ({auth_mode.upper()})'}")
    print(f"• Model: {hf_model}")
    print(f"• HF Token: {'Configured ✅' if hf_token else 'Not found (using smart extractor fallback) ⚠️'}")
    print(f"• Desktop Notifications: {'Enabled 🔔' if enable_notifications else 'Disabled 🔕'}")
    print(f"• Apple Messages Dispatch: {f'Enabled 💬 (To: {recipient})' if recipient else 'Disabled (No recipient set)'}")
    print(f"• Email Limit: {max_emails} (Filter: {'Unread only' if unread_only else 'All recent'})")
    print("-" * 65)

    # History Mode: View previously stored emails and labels
    if args.history:
        print("\n📚 Fetching previously summarized emails from database (emails.db)...")
        stored = get_all_emails(limit=50)
        labels_count = get_labels_summary()
        
        print("\n📊 Labels Breakdown:")
        for lbl, count in labels_count.items():
            print(f"   • {lbl}: {count}")

        if not stored:
            print("\nDatabase is currently empty. Run without --history to summarize emails.")
            return

        print(f"\nFound {len(stored)} saved email(s):\n" + ("=" * 65))
        for row in stored:
            print(f"[{row['label']}] 📩 {row['subject']}")
            print(f"      From: {row['sender']} | Date: {row['date']}")
            print(f"      Key Takeaway: {row['key_takeaway']}")
            print(f"      Action Items: {row['action_items']}")
            print("-" * 65)
        return

    # 1. Fetch Emails
    emails = []
    if args.dry_run:
        print("\n📥 Fetching mock test emails...")
        emails = get_mock_emails()[:max_emails]
    else:
        try:
            if auth_mode == "oauth":
                print("\n📥 Connecting to Gmail API via OAuth...")
                client = GmailApiClient()
                emails = client.fetch_recent_emails(max_results=max_emails, unread_only=unread_only)
            else:
                user = os.getenv("GMAIL_USER")
                pwd = os.getenv("GMAIL_APP_PASSWORD")
                if not user or not pwd:
                    print("\n❌ Error: IMAP mode requires GMAIL_USER and GMAIL_APP_PASSWORD in .env.")
                    print("Tip: Run with --dry-run to test immediately without configuring credentials.")
                    sys.exit(1)
                print(f"\n📥 Connecting to Gmail IMAP ({user})...")
                client = GmailImapClient(username=user, app_password=pwd)
                emails = client.fetch_recent_emails(max_results=max_emails, unread_only=unread_only)
        except FileNotFoundError as e:
            print(f"\n❌ Setup needed: {e}")
            print("\n💡 Tip: Run `python app.py --dry-run` to see the summarizer and notification in action right now!")
            sys.exit(1)
        except Exception as e:
            print(f"\n❌ Error fetching emails: {e}")
            sys.exit(1)

    if not emails:
        print("\n✨ No emails found matching the criteria.")
        return

    print(f"\nFound {len(emails)} email(s) to process.\n")

    # 2. Summarize Emails & Store in Database
    summarizer = EmailSummarizer(token=hf_token, model=hf_model)
    all_summaries = []

    for i, item in enumerate(emails, start=1):
        already_cached = is_email_stored(item.id)
        
        print(f"[{i}/{len(emails)}] 📩 Subject: {item.subject}")
        print(f"       From:    {item.sender}")
        print(f"       Date:    {item.date}")

        if already_cached and not args.force:
            print("       💾 Found existing summary in database (skipping re-summarization).")
            # Fetch cached summary from DB
            cached_item = get_all_emails(search=item.subject, limit=1)
            if cached_item:
                summary_data = {
                    "summary": cached_item[0]["summary"],
                    "key_takeaway": cached_item[0]["key_takeaway"],
                    "action_items": cached_item[0]["action_items"],
                    "label": cached_item[0]["label"],
                }
            else:
                summary_data = summarizer.summarize(
                    sender=item.sender,
                    subject=item.subject,
                    date=item.date,
                    body=item.body,
                )
        else:
            print("       🤖 Generating summary with Hugging Face...")
            summary_data = summarizer.summarize(
                sender=item.sender,
                subject=item.subject,
                date=item.date,
                body=item.body,
            )
            # Save to SQLite database
            save_email(
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
            print(f"       🏷️  Categorized as: [{summary_data['label']}] & Saved to Database.")

        summary_text = summary_data["summary"]
        label = summary_data["label"]

        print(f"\n--- Summary [{label}] ---")
        print(summary_text)
        print("-" * 40)

        # 3. macOS Desktop Notification
        if enable_notifications:
            first_line = summary_data.get("key_takeaway") or item.subject
            notify_text = f"[{label}] {first_line}"
            send_macos_notification(
                title=f"Email: {item.subject[:30]}",
                subtitle=item.sender.split("<")[0].strip(),
                message=notify_text,
                sound="Glass",
            )
            print("       🔔 Notification sent to macOS Notification Center.")

        # 4. Apple Messages App Dispatch (if recipient configured)
        if recipient:
            msg_payload = (
                f"📬 Email Summary [{label}]:\n"
                f"Subject: {item.subject}\n"
                f"From: {item.sender}\n\n"
                f"{summary_text}"
            )
            success = send_to_apple_messages(recipient=recipient, message=msg_payload)
            if success:
                print(f"       💬 Forwarded summary to Messages ({recipient}).")
            else:
                print(f"       ⚠️ Could not forward to Messages.")

        all_summaries.append(f"[{label}] Subject: {item.subject}\nFrom: {item.sender}\n\n{summary_text}")
        
        if i < len(emails):
            time.sleep(1)

    # 5. Optional Clipboard Copy
    if args.copy:
        full_digest = "\n\n" + ("=" * 40) + "\n\n".join(all_summaries)
        copy_to_clipboard(full_digest)
        print("\n📋 Combined summaries copied to your clipboard!")

    print("\n✅ All done! All emails processed and stored in database (emails.db).\n")



if __name__ == "__main__":
    main()
