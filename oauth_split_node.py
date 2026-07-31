#!/usr/bin/env python3
"""Split Node YouTube OAuth helper - file-based code handoff.

Flow:
  1. Run this script -> writes auth URL to oauth_url.txt and waits.
  2. User opens URL, authorizes, gets a code, pastes it into oauth_code.txt
     (or tells the agent, who writes it there).
  3. Script polls for oauth_code.txt, exchanges the code, saves credentials
     to ~/.youtube-upload-credentials.json, prints CREDS_SAVED.
"""
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, r"C:\Users\josep\AppData\Local\hermes\hermes-agent\venv\Lib\site-packages")
from google_auth_oauthlib.flow import InstalledAppFlow

PROJECT_DIR = Path(r"F:\aaaaaVIBECODING\System Breakers")
SECRETS_FILE = PROJECT_DIR / "client_secret_874421706318-sl7gg802bovuib9h2q95hq9lvlb661oi.apps.googleusercontent.com.json"
URL_FILE = PROJECT_DIR / "oauth_url.txt"
CODE_FILE = PROJECT_DIR / "oauth_code.txt"
CREDS_FILE = Path.home() / ".youtube-upload-credentials.json"

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
]


def main():
    secrets = json.loads(SECRETS_FILE.read_text())
    flow = InstalledAppFlow.from_client_config(secrets, SCOPES, redirect_uri="http://localhost")
    auth_url, _ = flow.authorization_url(access_type="offline", prompt="consent")
    URL_FILE.write_text(auth_url)
    print("AUTH_URL_READY")
    print("Waiting for code in oauth_code.txt ...", flush=True)

    # Poll for the code file (up to 60 min)
    deadline = time.time() + 3600
    while time.time() < deadline:
        if CODE_FILE.is_file():
            code = CODE_FILE.read_text().strip()
            if code:
                CODE_FILE.unlink()
                break
        time.sleep(2)
    else:
        print("TIMEOUT: no code received")
        sys.exit(1)

    flow.fetch_token(code=code)
    creds = flow.credentials
    data = {
        "access_token": creds.token,
        "refresh_token": creds.refresh_token,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "token_uri": creds.token_uri,
        "scopes": list(creds.scopes),
        "token_expiry": creds.expiry.isoformat() if creds.expiry else None,
    }
    CREDS_FILE.write_text(json.dumps(data, indent=2))
    print("CREDS_SAVED")


if __name__ == "__main__":
    main()
