#!/usr/bin/env python3
"""Shared YouTube re-auth helper for the upload pipelines
(Split Node / System Breakers, Split Node Shorts, The Crayon Diet).

ensure_youtube_creds() returns a working google Credentials object for
uploads, doing EVERYTHING inline so a failed upload never stops the run:

  1. loads the creds file and refreshes the token if possible
  2. if that fails (invalid_grant / expired / missing), it runs an
     INTERACTIVE paste-back OAuth flow right here:
       - prints the authorization URL
       - waits for the code you paste back into the terminal (input())
         OR into oauth_code.txt next to the script (agent/cron fallback)
       - exchanges it, saves the creds file, returns fresh creds
  3. the pipeline then carries on and retries the upload.

No extra dependencies: uses only `requests` + the `google-auth` libs the
pipelines already have (google_auth_oauthlib is NOT required).
"""
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

try:
    import requests
    _HAS_REQUESTS = True
except Exception:  # pragma: no cover
    _HAS_REQUESTS = False

TOKEN_URI = "https://oauth2.googleapis.com/token"
AUTH_URI = "https://accounts.google.com/o/oauth2/v2/auth"
REDIRECT_URI = "http://localhost"

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/youtube.force-ssl",
]


def _find_secret(project_dir) -> Path | None:
    for p in sorted(Path(project_dir).glob("client_secret_*.json")):
        return p
    return None


def _iso_expiry(expires_in):
    try:
        return (datetime.now(timezone.utc) + timedelta(seconds=int(expires_in))).isoformat()
    except Exception:
        return None


def _load_creds(data):
    """Build a google.oauth2 Credentials object from the creds dict."""
    from google.oauth2.credentials import Credentials
    expiry_raw = data.get("token_expiry") or data.get("expiry")
    expiry = None
    if expiry_raw:
        try:
            e = expiry_raw.replace("Z", "+00:00") if isinstance(expiry_raw, str) else expiry_raw
            expiry = datetime.fromisoformat(e)
            if expiry.tzinfo is not None:
                expiry = expiry.astimezone(timezone.utc).replace(tzinfo=None)
        except Exception:
            expiry = None
    return Credentials(
        token=data.get("access_token", data.get("token", "")),
        refresh_token=data.get("refresh_token"),
        client_id=data.get("client_id"),
        client_secret=data.get("client_secret"),
        token_uri=data.get("token_uri", TOKEN_URI),
        scopes=data.get("scopes", SCOPES),
        expiry=expiry,
    )


def _read_code(code_file: Path):
    """Get the auth code: try the terminal paste-back first, then poll
    oauth_code.txt (for agent/cron runs where stdin is not a terminal)."""
    try:
        inp = input("Paste authorization code here: ").strip()
        if inp:
            return inp
    except (EOFError, KeyboardInterrupt, OSError):
        pass
    # If a code is already staged in the file, use it immediately (do NOT
    # delete-first - that would throw away a pre-written code and force a wait).
    if code_file.is_file():
        _staged = code_file.read_text().strip()
        if _staged:
            try:
                code_file.unlink()
            except Exception:
                pass
            return _staged
    print(f"  (no terminal input - waiting for the code in {code_file})", flush=True)
    deadline = time.time() + 3600
    while time.time() < deadline:
        if code_file.is_file():
            code = code_file.read_text().strip()
            if code:
                try:
                    code_file.unlink()
                except Exception:
                    pass
                return code
        time.sleep(2)
    return None


def _reauth(creds_path: Path, secret_dir: Path, label: str):
    """Interactive paste-back OAuth. Returns a Credentials object or None."""
    secret = _find_secret(secret_dir)
    if secret is None:
        print(f"\n  [YOUTUBE:{label}] No client_secret_*.json found in {secret_dir}")
        print("  Get one here: https://console.cloud.google.com/apis/credentials")
        print("  (APIs & Services -> Credentials -> + CREATE CREDENTIALS -> OAuth client ID")
        print("   -> Application type = Desktop app -> DOWNLOAD the .json)")
        print("  Also add the channel email as a TEST USER on the OAuth consent screen.")
        deadline = time.time() + 3600
        while time.time() < deadline:
            secret = _find_secret(secret_dir)
            if secret is not None:
                print(f"  [YOUTUBE:{label}] Found secret: {secret.name}")
                break
            time.sleep(3)
        else:
            print(f"  [YOUTUBE:{label}] Timed out waiting for the secret - upload skipped")
            return None

    if not _HAS_REQUESTS:
        print(f"  [YOUTUBE:{label}] requests library not available - cannot authorize inline")
        return None

    secrets = json.loads(Path(secret).read_text(encoding="utf-8"))
    client_id = secrets["installed"]["client_id"]
    client_secret = secrets["installed"]["client_secret"]
    auth_url = (f"{AUTH_URI}?client_id={quote(client_id)}&redirect_uri={quote(REDIRECT_URI)}"
                f"&response_type=code&scope={quote(' '.join(SCOPES))}"
                f"&access_type=offline&prompt=consent")

    code_file = secret_dir / "oauth_code.txt"
    url_file = secret_dir / "oauth_url.txt"
    try:
        url_file.write_text(auth_url)
    except Exception:
        pass

    print("\n" + "=" * 70)
    print(f"  [YOUTUBE:{label}] Authorization required. Open this link in a browser:")
    print("=" * 70)
    print(auth_url)
    print("=" * 70)
    print("  Sign in, then PASTE the authorization code back here and press Enter.")
    print("  (Or drop it into oauth_code.txt in this project folder and press Enter.)")
    print("=" * 70)

    code = _read_code(code_file)
    if not code:
        print(f"  [YOUTUBE:{label}] No code received - upload skipped")
        return None

    r = requests.post(TOKEN_URI, data={
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": REDIRECT_URI,
        "grant_type": "authorization_code",
    }, timeout=30)
    if r.status_code != 200:
        print(f"  [YOUTUBE:{label}] Token exchange failed (HTTP {r.status_code}): {r.text[:300]}")
        return None
    tok = r.json()

    data = {
        "access_token": tok.get("access_token"),
        "token": tok.get("access_token"),
        "refresh_token": tok.get("refresh_token"),
        "client_id": client_id,
        "client_secret": client_secret,
        "token_uri": TOKEN_URI,
        "scopes": SCOPES,
        "token_expiry": _iso_expiry(tok.get("expires_in")),
        "expiry": _iso_expiry(tok.get("expires_in")),
    }
    creds_path.write_text(json.dumps(data, indent=2))
    print(f"  [OK] YouTube credentials saved to {creds_path} ({label})")
    return _load_creds(data)


def ensure_youtube_creds(creds_path, project_dir=None, label="YouTube", secrets_dir=None):
    """Load + refresh creds; if that fails, re-authorize inline and return
    fresh creds. Returns a google Credentials object or None."""
    creds_path = Path(creds_path)
    project_dir = Path(project_dir) if project_dir else creds_path.parent
    secret_dir = Path(secrets_dir) if secrets_dir else project_dir

    if creds_path.is_file():
        try:
            data = json.loads(creds_path.read_text())
            if data.get("refresh_token"):
                creds = _load_creds(data)
                if creds.valid:
                    return creds
                try:
                    from google.auth.transport.requests import Request as AuthRefresh
                    creds.refresh(AuthRefresh())
                    data["access_token"] = creds.token
                    data["token"] = creds.token
                    data["token_expiry"] = creds.expiry.isoformat() if creds.expiry else None
                    data["expiry"] = data["token_expiry"]
                    creds_path.write_text(json.dumps(data, indent=2))
                    print(f"  [OK] YouTube token refreshed ({label})")
                    return creds
                except Exception as e:
                    print(f"  [YOUTUBE:{label}] Token refresh failed ({e}) - re-authorizing inline...")
            else:
                print(f"  [YOUTUBE:{label}] No refresh_token stored - re-authorizing inline...")
        except Exception as e:
            print(f"  [YOUTUBE:{label}] Credential load failed ({e}) - re-authorizing inline...")
    else:
        print(f"  [YOUTUBE:{label}] No credentials file yet - authorizing inline...")

    return _reauth(creds_path, secret_dir, label)
