#!/usr/bin/env python3
"""discord_bot.py - Self-contained Discord bot setup + announcements for Split Node.

Everything here uses ONLY the standard library (urllib) against the Discord
REST API - no pip install needed, no discord.py. You provide your own bot
token + a channel and Split Node posts episode announcements there.

Quick start:
    python discord_bot.py --setup        # guided one-time setup (token + channel)
    python discord_bot.py --test         # verify token + reach the channel
    python discord_bot.py --send "hi"    # send a one-off test message

Setup flow (also in the README):
    1. Create a bot at https://discord.com/developers/applications
       -> "New Application" -> name it -> "Bot" -> "Add Bot".
    2. Copy the bot TOKEN (under the Bot section -> "Reset Token" if needed).
    3. Invite the bot to your server with the invite URL the setup prints
       (it needs "Send Messages" + "View Channels" permissions).
    4. Tell the setup which channel to post to (channel ID or #name).
    5. It saves DISCORD_BOT_TOKEN + DISCORD_ANNOUNCE_CHANNELS to .env.

Config (all optional, from .env or env vars):
    DISCORD_BOT_TOKEN          the bot token
    DISCORD_ANNOUNCE_CHANNELS  comma-separated channel IDs or #names
    DISCORD_CHANNEL            single channel (shorthand)
"""
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
ENV_FILE = PROJECT_DIR / ".env"
API = "https://discord.com/api/v10"
DEV_LINK = "https://discord.com/developers/applications"
INVITE_LINK = "https://discord.com/api/oauth2/authorize"

# Retry on 429 (rate limited) and 5xx (server hiccup) with exponential backoff.
_RETRIES = 4
_BASE_DELAY = 1.0


def _load_env():
    if ENV_FILE.is_file():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())


_load_env()


def _token() -> str:
    return (os.environ.get("DISCORD_BOT_TOKEN") or "").strip()


def _set_env(key: str, value: str):
    lines = []
    if ENV_FILE.is_file():
        lines = ENV_FILE.read_text(encoding="utf-8").splitlines()
    new_lines = []
    found = False
    for ln in lines:
        if ln.strip().startswith(key + "="):
            new_lines.append(f"{key}={value}")
            found = True
        else:
            new_lines.append(ln)
    if not found:
        new_lines.append(f"{key}={value}")
    ENV_FILE.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    os.environ[key] = value


def _api(path: str, method: str = "GET", payload: dict | None = None,
         token: str | None = None) -> dict:
    """Discord REST call with rate-limit/5xx retry. Returns parsed JSON."""
    tok = token if token is not None else _token()
    if not tok:
        return {"error": "no token", "message": "DISCORD_BOT_TOKEN not set"}
    url = API + path
    data = json.dumps(payload).encode() if payload is not None else None
    for attempt in range(1, _RETRIES + 1):
        req = urllib.request.Request(
            url, data=data, method=method,
            headers={
                "Authorization": f"Bot {tok}",
                "Content-Type": "application/json",
                "User-Agent": "DiscordBot (https://github.com/DrGekoz/Split-Node-YouTube, 1.0)",
            })
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                raw = r.read().decode()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            raw = e.read().decode(errors="ignore")
            try:
                err = json.loads(raw)
            except Exception:
                err = {"message": raw[:200]}
            if e.code == 429:  # rate limited - respect Retry-After
                retry = float(err.get("retry_after", _BASE_DELAY * attempt))
                time.sleep(retry + 0.5)
                continue
            if 500 <= e.code < 600:  # server hiccup - backoff + retry
                time.sleep(_BASE_DELAY * (2 ** (attempt - 1)))
                continue
            err["http_status"] = e.code
            return err
        except Exception as e:
            if attempt == _RETRIES:
                return {"error": str(e)}
            time.sleep(_BASE_DELAY * (2 ** (attempt - 1)))
    return {"error": "retries exhausted"}


def get_current_user() -> dict:
    return _api("/users/@me")


def get_guilds(token: str | None = None) -> list[dict]:
    r = _api("/users/@me/guilds", token=token)
    return r if isinstance(r, list) else []


def get_channels(guild_id: str, token: str | None = None) -> list[dict]:
    r = _api(f"/guilds/{guild_id}/channels", token=token)
    return r if isinstance(r, list) else []


def resolve_channel(spec: str, token: str | None = None) -> str | None:
    """Turn a channel ID or #name into a channel ID. Returns None if not found."""
    spec = (spec or "").strip()
    if not spec:
        return None
    if spec.lstrip("#").isdigit():
        return spec.lstrip("#")
    name = spec.lstrip("#").lower()
    for g in get_guilds(token):
        for ch in get_channels(g["id"], token):
            if ch.get("type") in (0, 5) and ch.get("name", "").lower() == name:
                return ch["id"]
    return None


def send_message(content: str, channel: str | None = None,
                 token: str | None = None) -> dict:
    """Post a message to a channel (ID or #name). Returns the API response."""
    ch = resolve_channel(channel, token) if channel else None
    if not ch:
        return {"error": "channel not found",
                "message": f"could not resolve channel '{channel}'"}
    return _api(f"/channels/{ch}/messages", method="POST",
                payload={"content": content}, token=token)


def test(token: str | None = None) -> dict:
    user = get_current_user() if token is None else _api("/users/@me", token=token)
    if user.get("error") or "id" not in user:
        return {"ok": False, **user}
    guilds = get_guilds(token)
    return {"ok": True, "bot": f"{user.get('username')}#{user.get('discriminator', '')}",
            "guilds": [g.get("name") for g in guilds]}


def setup():
    print("""
==============================================================
  DISCORD BOT SETUP - add your own bot + channel
==============================================================
  Split Node posts episode announcements to a Discord channel
  through a bot YOU control. Everything runs from this repo.

  STEP 1 - CREATE THE BOT
    Open:  {DEV_LINK}
    -> "New Application" -> name it -> "Bot" -> "Add Bot".

  STEP 2 - COPY THE TOKEN
    Under "Bot" -> "Token" -> click Reset/Copy. Paste it below.
==============================================================
""".format(DEV_LINK=DEV_LINK))
    tok = input("  Bot token: ").strip()
    if not tok:
        print("  [SETUP] No token entered")
        return False
    _set_env("DISCORD_BOT_TOKEN", tok)
    os.environ["DISCORD_BOT_TOKEN"] = tok

    t = test(tok)
    if not t.get("ok"):
        print(f"  [SETUP] Token invalid: {t.get('message', t.get('error', '?'))}")
        print("  [SETUP] Check the token and try again.")
        return False
    print(f"  [SETUP] Connected as bot '{t['bot']}'.")

    # Guild selection
    guilds = get_guilds(tok)
    if not guilds:
        print("""
  [SETUP] This bot is in NO servers yet. Invite it:
    {INVITE_LINK}?client_id=YOUR_CLIENT_ID&permissions=3072&scope=bot
  (get YOUR_CLIENT_ID from the application page; it needs Send Messages
   + View Channels). After inviting, re-run:  python discord_bot.py --setup
""".format(INVITE_LINK=INVITE_LINK))
        return False
    print("\n  [SETUP] Your bot is in these servers:")
    for i, g in enumerate(guilds, 1):
        print(f"    {i}. {g.get('name')} ({g.get('id')})")
    gi = input("  Pick a server number [1]: ").strip() or "1"
    try:
        guild = guilds[int(gi) - 1]
    except Exception:
        print("  [SETUP] Invalid server selection")
        return False

    # Channel selection
    chans = [c for c in get_channels(guild["id"], tok) if c.get("type") in (0, 5)]
    if not chans:
        print(f"  [SETUP] No text channels found in '{guild.get('name')}'.")
        return False
    print(f"\n  [SETUP] Text channels in '{guild.get('name')}':")
    for i, c in enumerate(chans, 1):
        print(f"    {i}. #{c.get('name')} ({c.get('id')})")
    ci = input("  Pick a channel number [1]: ").strip() or "1"
    try:
        ch = chans[int(ci) - 1]
    except Exception:
        print("  [SETUP] Invalid channel selection")
        return False
    _set_env("DISCORD_ANNOUNCE_CHANNELS", ch["id"])
    print(f"\n  [OK] Saved to .env: channel #{ch.get('name')} ({ch['id']})")
    print("  [OK] Discord setup complete! Announcements will post here.")
    return True


def main():
    args = sys.argv[1:]
    if "--setup" in args:
        sys.exit(0 if setup() else 1)
    if "--test" in args:
        t = test()
        if t.get("ok"):
            print(f"[OK] Bot connected: {t['bot']}")
            print(f"[OK] Servers: {', '.join(t['guilds']) or 'none'}")
            ch = os.environ.get("DISCORD_ANNOUNCE_CHANNELS") or os.environ.get("DISCORD_CHANNEL")
            if ch:
                r = resolve_channel(ch)
                print(f"[OK] Channel '{ch}' -> ID {r if r else 'NOT FOUND'}")
            sys.exit(0)
        print(f"[FAIL] {t.get('message', t.get('error', '?') )}")
        sys.exit(1)
    if "--send" in args:
        i = args.index("--send")
        content = args[i + 1] if i + 1 < len(args) else "Hello from Split Node!"
        ch = os.environ.get("DISCORD_ANNOUNCE_CHANNELS") or os.environ.get("DISCORD_CHANNEL")
        r = send_message(content, ch)
        if r.get("error"):
            print(f"[FAIL] {r.get('message', r.get('error'))}")
            sys.exit(1)
        print(f"[OK] Sent to channel {ch}")
        sys.exit(0)
    # No args - print instructions
    print(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main())
