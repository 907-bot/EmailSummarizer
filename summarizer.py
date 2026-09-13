"""Hugging Face LLM Email Summarizer Module.

Uses Hugging Face Serverless Inference API (Free tier) to generate concise,
action-oriented email summaries.
"""

from __future__ import annotations

import os
import re
from typing import Optional
from huggingface_hub import InferenceClient

# Default recommended free models on Hugging Face Serverless API:
DEFAULT_CHAT_MODEL = "meta-llama/Llama-3.2-3B-Instruct"
FALLBACK_MODELS = [
    "meta-llama/Llama-3.2-3B-Instruct",
    "mistralai/Mistral-7B-Instruct-v0.3",
    "Qwen/Qwen2.5-7B-Instruct",
    "facebook/bart-large-cnn",
]


LABELS = [
    "Work",
    "Security",
    "Meeting",
    "Finance",
    "Newsletter",
    "Personal",
    "Action Required",
    "General",
]


class EmailSummarizer:
    """Summarizes and categorizes emails using Hugging Face LLM models."""

    def __init__(self, token: Optional[str] = None, model: Optional[str] = None):
        self.token = token or os.getenv("HF_TOKEN")
        self.model = model or os.getenv("HF_MODEL") or DEFAULT_CHAT_MODEL
        self.client = InferenceClient(token=self.token) if self.token else None

    def classify_label(self, subject: str, sender: str, body: str) -> str:
        """Classify email into one of standard labels."""
        text = f"{subject} {sender} {body}".lower()

        # Security patterns
        if any(k in text for k in ["security", "access key", "password", "unauthorized", "verify your account", "2fa", "iam"]):
            return "Security"
        # Meeting patterns
        if any(k in text for k in ["meeting", "sync", "zoom", "google meet", "calendar", "invite", "catch up", "rescheduled"]):
            return "Meeting"
        # Finance patterns
        if any(k in text for k in ["invoice", "receipt", "billing", "payment", "bank", "subscription", "pricing", "credit card"]):
            return "Finance"
        # Newsletter patterns
        if any(k in text for k in ["unsubscribe", "digest", "weekly newsletter", "monthly update", "view in browser", "roundup"]):
            return "Newsletter"
        # Action required patterns
        if any(k in text for k in ["action required", "action needed", "deadline", "urgent", "immediate attention", "approval needed"]):
            return "Action Required"
        # Work / Project patterns
        if any(k in text for k in ["roadmap", "sprint", "pull request", "deployment", "jira", "github", "rfc", "feature freeze", "pr"]):
            return "Work"
        # Personal patterns
        if any(k in text for k in ["coffee", "lunch", "weekend", "dinner", "how are you", "congratulations"]):
            return "Personal"

        return "General"

    def _format_prompt(self, sender: str, subject: str, date: str, body: str) -> str:
        truncated_body = body[:4000] if len(body) > 4000 else body
        prompt = (
            f"You are an executive email assistant. Summarize the following email clearly and concisely.\n\n"
            f"From: {sender}\n"
            f"Subject: {subject}\n"
            f"Date: {date}\n\n"
            f"Email Body:\n{truncated_body}\n\n"
            f"Instructions:\n"
            f"Provide a 3-part structured summary:\n"
            f"1. One-sentence Key Takeaway\n"
            f"2. 2-3 Core Bullet Points\n"
            f"3. Action Items or Next Steps (if none, write 'None required')\n\n"
            f"Keep it concise, professional, and ready for quick mobile reading."
        )
        return prompt

    def summarize(
        self,
        sender: str,
        subject: str,
        date: str,
        body: str,
    ) -> dict:
        """Generate a structured summary and classify label for the given email.
        
        Returns:
            dict containing 'summary', 'key_takeaway', 'action_items', 'label'.
        """
        label = self.classify_label(subject, sender, body)

        if not body.strip():
            return {
                "summary": "No content to summarize in this email.",
                "key_takeaway": "Empty email",
                "action_items": "None",
                "label": label,
            }

        # If user has configured a Hugging Face token, call HF Inference API
        if self.token:
            summary = self._call_hugging_face(sender, subject, date, body)
            if summary:
                takeaway, actions = self._extract_structured_fields(summary, subject)
                return {
                    "summary": summary,
                    "key_takeaway": takeaway,
                    "action_items": actions,
                    "label": label,
                }

        # Graceful fallback
        fallback = self._local_extractive_summary(sender, subject, body, label)
        return fallback

    def _extract_structured_fields(self, summary: str, fallback_subject: str) -> tuple[str, str]:
        lines = summary.splitlines()
        takeaway = ""
        action_items = ""
        
        for i, line in enumerate(lines):
            clean = line.strip()
            if "takeaway" in clean.lower() or "1." in clean:
                takeaway = clean.split(":", 1)[-1].strip() if ":" in clean else clean
                if not takeaway and i + 1 < len(lines):
                    takeaway = lines[i + 1].strip()
                break

        if not takeaway:
            takeaway = lines[0].strip() if lines else fallback_subject

        # Extract action items
        collecting_actions = False
        action_lines = []
        for line in lines:
            clean = line.strip()
            if "action" in clean.lower() or "next step" in clean.lower():
                collecting_actions = True
                continue
            if collecting_actions:
                if clean.startswith(("-", "•", "*", "1.", "2.")):
                    action_lines.append(clean)
                elif clean and not clean.startswith("**"):
                    action_lines.append(clean)

        action_items = "\n".join(action_lines) if action_lines else "None required"
        return takeaway, action_items

    def _call_hugging_face(self, sender: str, subject: str, date: str, body: str) -> Optional[str]:
        prompt = self._format_prompt(sender, subject, date, body)
        models_to_try = [self.model] + [m for m in FALLBACK_MODELS if m != self.model]

        for model_name in models_to_try:
            try:
                if "bart" in model_name.lower() or "t5" in model_name.lower():
                    clean_text = f"Subject: {subject}. From: {sender}. {body[:1500]}"
                    result = self.client.summarization(clean_text, model=model_name)
                    if isinstance(result, list) and len(result) > 0:
                        return result[0].get("summary_text", "").strip()
                    elif hasattr(result, "summary_text"):
                        return getattr(result, "summary_text", "").strip()
                    return str(result).strip()

                response = self.client.chat.completions.create(
                    model=model_name,
                    messages=[
                        {
                            "role": "system",
                            "content": "You are a professional executive email assistant. Summarize emails with high clarity and structure.",
                        },
                        {"role": "user", "content": prompt},
                    ],
                    max_tokens=350,
                    temperature=0.2,
                )
                content = response.choices[0].message.content
                if content and content.strip():
                    return content.strip()

            except Exception:
                continue

        return None

    def _local_extractive_summary(self, sender: str, subject: str, body: str, label: str) -> dict:
        """Smart fallback summary when offline or awaiting HF_TOKEN configuration."""
        sentences = re.split(r"(?<=[.!?])\s+", body.strip())
        meaningful_sentences = [
            s.strip() for s in sentences if len(s.strip()) > 20 and not s.lower().startswith("best regards")
        ]
        key_lines = meaningful_sentences[:3] if meaningful_sentences else [body[:200]]

        takeaway = key_lines[0] if key_lines else subject
        bullets = "\n".join(f"• {line}" for line in key_lines[1:]) if len(key_lines) > 1 else "• Detailed in email body."

        # Detect action keywords
        action_keywords = ["please", "action required", "by", "schedule", "deadline", "need you to", "review"]
        action_items_list = []
        for s in sentences:
            if any(k in s.lower() for k in action_keywords):
                action_items_list.append(f"• {s.strip()}")
                if len(action_items_list) >= 2:
                    break

        actions = "\n".join(action_items_list) if action_items_list else "• None required"

        token_hint = (
            "\n\n*(Note: To enable full Hugging Face LLM summaries, set your free HF_TOKEN in .env)*"
            if not self.token
            else ""
        )

        full_summary = (
            f"**Key Takeaway**: {takeaway}\n\n"
            f"**Highlights**:\n{bullets}\n\n"
            f"**Action Items**:\n{actions}"
            f"{token_hint}"
        )

        return {
            "summary": full_summary,
            "key_takeaway": takeaway,
            "action_items": actions,
            "label": label,
        }

