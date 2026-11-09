# Google Calendar & Gmail setup (bring-your-own-credentials)

Secretary integrates with Google Calendar (read/sync) and Gmail (read) via OAuth.
Google is **optional** and **bring-your-own-credentials**: you need your own
Google Cloud project and OAuth client. Real sign-in is human-gated; all code is
built and tested against mocked HTTP (respx), so no real Google credentials are
needed to develop or run the test suite.

## 1. Create a Google Cloud project

1. Go to the [Google Cloud Console](https://console.cloud.google.com/).
2. Create a new project (or select an existing one).
3. Enable the **Google Calendar API** and the **Gmail API** for the project.

## 2. Configure the OAuth consent screen

1. In the Google Cloud Console, go to **APIs & Services → OAuth consent screen**.
2. Select **External** user type.
3. Fill in the app name, support email, and developer contact.
4. Add scopes:
   - `https://www.googleapis.com/auth/calendar.events`
   - `https://www.googleapis.com/auth/gmail.readonly`
   - `https://www.googleapis.com/auth/gmail.compose`
5. Add yourself (your Google address) as a **test user**.
6. **Important:** publish the consent screen as **"In production"**.
   - In "Testing" status, refresh tokens expire after ~7 days and Calendar/Email
     break mid-project. "In production" is required for durable refresh tokens.

## 3. Create the OAuth client ID

1. In the Google Cloud Console, go to **APIs & Services → Credentials**.
2. Click **Create credentials → OAuth client ID**.
3. Application type: **Desktop app**.
4. Note the **Client ID** and **Client Secret**.
5. Download the client JSON → this is `credentials.json`.

## 4. Install credentials.json

`credentials.json` is looked up in this order:

1. `SECRETARY_CREDENTIALS` environment variable, if set (points to any path).
2. `%LOCALAPPDATA%\Secretary\credentials.json` (installed-app default).
3. The project root `credentials.json`, only when running from source (not PyInstaller-frozen).

The first existing file wins. During source development you may place
`credentials.json` at the project root (next to this repo); the installed app
uses the `%LOCALAPPDATA%\Secretary\` location.

The file is git-ignored and never committed. It contains your client secret — treat
it like a password. Never print or log its contents.

## 5. Configure keys (optional but recommended)

Store LLM API keys in Windows Credential Manager (service `Secretary`):

- `llm_api_key:groq` — Groq API key (default LLM provider).
- `llm_api_key:gemini` — Gemini API key.

You can set these via Credential Manager or the Settings → LLM screen.

## 6. Verify with diagnostics

Run:

```
python -m secretary --diagnose
```

Expected output (when Google is connected):

```
DIAGNOSE OK
  [x] Python 3.12.10 on win32
  [x] config loaded
  [x] keyring importable
  [x] store connects (WAL + foreign_keys)
  [x] tzdata present
  [x] Google credentials present: C:\Users\...\AppData\Local\Secretary\credentials.json
  [x] Groq API key present in Credential Manager
  [x] Gemini API key present in Credential Manager
  [x] Google refresh token present in Credential Manager
```

If anything is missing it is reported as a problem (never the actual key/token
value).

## 7. Connect Google

1. Start Secretary (`python -m secretary`).
2. Open **Settings**.
3. In the **Google Calendar & Gmail** section, click **Connect Google**.
4. Your system browser opens the Google consent screen.
5. Sign in and approve the requested scopes.
6. The browser redirects to a local loopback port; Secretary exchanges the code
   and stores the refresh token in Credential Manager.
7. Settings now shows **Google: connected** and the button becomes
   **Reconnect Google**.

## 8. See your Calendar events

1. Open the **Calendar** view.
2. Secretary runs a windowed sync (last 7 days to next 60 days) and displays
   your events, including all-day events.
3. Subsequent syncs use Google's `nextSyncToken` (incremental). If the token is
   ever invalidated (HTTP 410), Secretary automatically falls back to a full
   resync.

## 9. Revoke access (human-gated)

1. Go to your [Google Account permissions](https://myaccount.google.com/permissions).
2. Find Secretary and **remove access**.
3. Secretary's next refresh/sync will fail with an OAuth error.
4. Settings shows **Google: disconnected** (or a sync-failed chip), and the
   button returns to **Connect Google**.

## 10. Reconnect flow

1. After revoking access, click **Reconnect Google** in Settings.
2. The consent flow runs again; re-approve to obtain a new refresh token.
3. Settings shows **Google: connected** again and sync resumes.

## Notes

- Only the **refresh token** is stored in Credential Manager (service
  `Secretary`, key `google_token`); access tokens are rebuilt in memory and
  refreshed lazily. Client ID is stored as `google_client_id`.
- `credentials.json` and all tokens are local to your machine; nothing is
  uploaded by Secretary.
- Gmail is read-only in this version; sending is opt-in at Phase 3.5.
