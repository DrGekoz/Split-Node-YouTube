#!/usr/bin/env python3
"""Split Node YouTube OAuth helper - file-based code handoff.

Flow:
  1. Run this script -> finds/waits for your YouTube API secret .json, writes
     an auth URL to oauth_url.txt, and waits.
  2. You open the URL, authorize, get a code, and paste it into oauth_code.txt
     (or tell the agent, who writes it there).
  3. Script polls for oauth_code.txt, exchanges the code, saves credentials
     to ~/.youtube-upload-credentials.json, prints CREDS_SAVED.

The secret .json file is your OAuth client credentials downloaded from Google
Cloud (create an "OAuth client ID" of type "Desktop app" under the YouTube
Data API v3 project). Place it in the Split Node project folder. It must be
named  client_secret_*.json
"""
import json
import os
import sys
import time
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
URL_FILE = PROJECT_DIR / "oauth_url.txt"
CODE_FILE = PROJECT_DIR / "oauth_code.txt"
CREDS_FILE = Path.home() / ".youtube-upload-credentials.json"

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/youtube.force-ssl",
]

SETUP_LINK = "https://console.cloud.google.com/apis/credentials"

INSTRUCTIONS = f"""
========================================================================
  YouTube UPLOAD SETUP - you need your YouTube API secret .json
========================================================================
  Split Node auto-uploads finished episodes to YouTube. To do that it
  needs TWO things, in this order:

  1) Your OAuth client secret .json (one-time, ~5 min to get)
  2) One browser authorization (one-time, ~30 sec)

  >>> GETTING THE SECRET .json <<<
  1. Open:  {SETUP_LINK}
  2. Make sure the correct Google Cloud PROJECT is selected (top bar).
     If you haven't created one: + NEW PROJECT -> name it -> CREATE.
  3. In the left menu: "APIs & Services" -> "Library"
     -> search "YouTube Data API v3" -> ENABLE it.
  4. Left menu: "APIs & Services" -> "Credentials"
     -> "+ CREATE CREDENTIALS" -> "OAuth client ID"
     -> Application type = "Desktop app" -> name it -> CREATE.
  5. On the created client, click the DOWNLOAD icon (a .json downloads).
  6. SAVE THAT FILE INTO THIS PROJECT FOLDER:
        {PROJECT_DIR}
     It must be named  client_secret_*.json  (keep the google-generated name).
  7. ADD THE CHANNEL EMAIL AS A TEST USER (REQUIRED - until your project is
     verified, Google only lets LISTED test users authorize). Go to:
        OAuth consent screen -> "Test users" -> + Add users
     and enter the email address of the YouTube CHANNEL itself (the account
     that owns the channel you upload to). Without this the auth URL will
     refuse to log in.
========================================================================
"""


def _find_secret() -> Path | None:
    for p in sorted(PROJECT_DIR.glob("client_secret_*.json")):
        return p
    return None


def main():
    if CREDS_FILE.is_file():
        try:
            json.loads(CREDS_FILE.read_text())
            print("CREDS_ALREADY_SAVED")
            return
        except Exception:
            pass

    # Wait for the secret .json if it isn't present yet.
    secret = _find_secret()
    if secret is None:
        print("NO_SECRET_FOUND")
        print(INSTRUCTIONS)
        print("Waiting for client_secret_*.json in the project folder "
              "(check the instructions above)...", flush=True)
        deadline = time.time() + 3600
        while time.time() < deadline:
            secret = _find_secret()
            if secret is not None:
                print(f"FOUND_SECRET {secret.name}")
                break
            time.sleep(3)
        else:
            print("TIMEOUT: no secret file received")
            sys.exit(1)

    # Include the venv's google libs if available (fall back to whatever is
    # on PYTHONPATH if this exact venv path doesn't exist on this machine).
    _venv_site = os.environ.get("HERMES_VENV_SITE", "").strip()
    if _venv_site:
        _venv = Path(_venv_site)
        if _venv.is_dir():
            sys.path.insert(0, str(_venv))
    from google_auth_oauthlib.flow import InstalledAppFlow

    secrets = json.loads(secret.read_text(encoding="utf-8"))
    flow = InstalledAppFlow.from_client_config(secrets, SCOPES,
                                               redirect_uri="http://localhost")
    auth_url, _ = flow.authorization_url(access_type="offline", prompt="consent")
    URL_FILE.write_text(auth_url)
    print("AUTH_URL_READY")
    print("Open this URL, authorize, then paste the code into oauth_code.txt:")
    print(auth_url)
    print("Waiting for code in oauth_code.txt ...", flush=True)

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
