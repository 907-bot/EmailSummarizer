# 📬 Google Email Summarizer with Hugging Face & macOS Messages/Notifications

An automated email summarization pipeline that fetches your emails from Google (Gmail API or IMAP), generates crisp, structured bullet-point summaries using free Hugging Face LLMs, and delivers them directly to macOS **Desktop Notifications** and the **Apple Messages** app.

---

## 🌟 Key Features

- **Free Hugging Face LLM Summaries**: Powered by Hugging Face's free Serverless Inference API (supports `meta-llama/Llama-3.2-3B-Instruct`, `mistralai/Mistral-7B-Instruct-v0.3`, or `facebook/bart-large-cnn`).
- **SQLite Database (`emails.db`)**: Automatically stores all past email summaries, key takeaways, action items, and categorized labels (`Work`, `Security`, `Meeting`, `Finance`, `Personal`, `Action Required`, etc.).
- **Interactive Web App Dashboard (`http://localhost:8000`)**:
  - Live filtering by category and labels with counter badges.
  - Full-text search across subject, sender, and takeaways.
  - One-click "Sync Gmail Inbox" or "Mock Sync".
  - One-click "Send to Messages" modal to dispatch to Apple Messages.
  - "Copy Summary" clipboard button.
- **Google Email Integration**:
  - **Gmail API (OAuth2)**: Official Google OAuth client with local token caching (`token.json`).
  - **Gmail IMAP (App Password)**: Quick, zero-Google-Cloud setup using a Google App Password.
- **Multi-Channel macOS Delivery**:
  - 🔔 **macOS Notification Center**: Native banner alerts with sound and preview snippet.
  - 💬 **Apple Messages (iMessage)**: Dispatch structured summaries directly to your phone or contact via AppleScript.

---

## 🖥️ Launching the Web App Dashboard

Start the local dashboard server:
```bash
.venv/bin/python server.py
```
Open your browser at: **[http://localhost:8000](http://localhost:8000)**


---

## 🚀 Quickstart

### 1. Environment Setup

Activate the virtual environment:
```bash
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Instant Test Run (Dry Run)

Run with mock emails to see the summarizer and notification banners in action:
```bash
python app.py --dry-run
```

---

## ⚙️ Configuration

Copy the example environment file:
```bash
cp .env.example .env
```

Open `.env` and configure the following sections:

### 1. Free Hugging Face Token
1. Sign up for free at [huggingface.co](https://huggingface.co).
2. Go to [Settings -> Access Tokens](https://huggingface.co/settings/tokens) and click **Create New Token** (Read permission is sufficient).
3. Paste the token into `.env`:
   ```env
   HF_TOKEN=hf_your_free_token_here
   HF_MODEL=meta-llama/Llama-3.2-3B-Instruct
   ```

### 2. Google Email Setup (Choose Either Method)

#### Option A: Official Gmail API (OAuth2) - *Recommended*
1. Go to [Google Cloud Console](https://console.cloud.google.com/).
2. Create a project and enable the **Gmail API** under *APIs & Services -> Library*.
3. Go to *APIs & Services -> Credentials* -> click **Create Credentials** -> **OAuth client ID**.
4. Choose Application type: **Desktop app**.
5. Download the JSON credentials file and save it as `credentials.json` in this directory.
6. Set `GMAIL_AUTH_MODE=oauth` in `.env`.
7. On first run, a browser tab will open for you to grant read-only access. It will automatically save `token.json` for subsequent runs.

#### Option B: Gmail IMAP (Google App Password) - *Fastest*
1. Go to your [Google Account Security](https://myaccount.google.com/security).
2. Under "2-Step Verification", scroll down to **App passwords**.
3. Generate a new App Password (name it e.g. "Email Summarizer").
4. Update `.env`:
   ```env
   GMAIL_AUTH_MODE=imap
   GMAIL_USER=your_email@gmail.com
   GMAIL_APP_PASSWORD=xxxx xxxx xxxx xxxx
   ```

### 3. macOS Messages & Notifications
- Desktop notifications are enabled by default (`ENABLE_DESKTOP_NOTIFICATIONS=true`).
- To forward summaries to Apple **Messages** (iMessage or SMS), set the recipient's phone number or Apple ID:
  ```env
  MESSAGES_RECIPIENT=+1234567890
  ```
  *(Leave empty if you only want desktop notification banners).*

---

## 📖 CLI Usage

```bash
# Summarize unread inbox emails
python app.py

# Summarize the 5 most recent emails (including read emails)
python app.py --all-emails --max-emails 5

# Forward summaries to a specific iMessage recipient
python app.py --recipient "+15551234567"

# Copy summary digest to macOS clipboard
python app.py --dry-run --copy

# Specify a different Hugging Face model on the fly
python app.py --model "mistralai/Mistral-7B-Instruct-v0.3"
```

### Command Flags

| Flag | Description |
|---|---|
| `--dry-run` | Run using mock email data without needing credentials |
| `--max-emails`, `-n` | Maximum number of emails to process (default: 3) |
| `--all-emails` | Fetch all recent inbox emails (default is unread only) |
| `--mode` | Override auth mode (`oauth` or `imap`) |
| `--recipient`, `-r` | Recipient phone number or Apple ID for Messages app |
| `--no-notify` | Disable macOS desktop notification banners |
| `--model` | Hugging Face model identifier |
| `--copy` | Copy email summaries to clipboard (`pbcopy`) |

---

## 📁 Project Structure

```
.
├── app.py              # CLI entry point and orchestration
├── gmail_service.py    # Gmail API (OAuth2) & IMAP client with MIME/HTML parsing
├── summarizer.py       # Hugging Face Serverless LLM client with smart fallback
├── notifier.py         # macOS osascript notifications and Apple Messages dispatch
├── requirements.txt    # Python dependencies
├── .env.example        # Environment variables template
└── README.md           # Documentation
```

---

## 🔐 Deployment & Web Credentials Page (`/login`)

When deploying the app publicly or across devices, users can connect their own Gmail accounts directly via the web interface:

- **Connect URL**: `http://localhost:8002/login` (or `https://your-domain.com/login`)
- **Inputs**:
  1. **Gmail Address**
  2. **Google App Password**
  3. Direct Link: *"Get your password to access mail by creating an app name: email summarizer"* -> links to `https://myaccount.google.com/apppasswords`.
- **Validation**: Automatically verifies credentials against Google IMAP before saving the session and launching the dashboard.

### Ready for Cloud Deployment
Includes container configuration for 1-click cloud deployment:
- `Dockerfile` (Container image setup)
- `Procfile` (PaaS runner for Render / Railway / Heroku)
