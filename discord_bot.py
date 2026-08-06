#!/usr/bin/env python3
"""discord_bot.py - Self-contained Discord bot setup + announcements for Split Node.

Everything here uses ONLY the standard library (urllib) against the Discord
REST API - no pip install needed, no discord.py. You provide your own bot
token + a channel and Split Node posts episode announcements there.

Quick start:
    python discord_bot.py --setup        # guided setup (token + channels)
    python discord_bot.py --test         # verify token + reach channels
    python discord_bot.py --list         # list configured announce channels
    python discord_bot.py --remove <id>  # remove a channel
    python discord_bot.py --send "hi"    # test-send to ALL configured channels

MULTI-SERVER / MULTI-CHANNEL: the same bot token can post to as many servers
and channels as you like. `--setup` lets you pick several servers and several
channels in one go (comma-separated), and re-running `--setup` ADDS more.
Channels are stored comma-separated in .env as DISCORD_ANNOUNCE_CHANNELS.

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


def _load_channels() -> list[str]:
    """Return the list of announce channels (IDs or #names) from .env. Supports
    multiple servers + multiple channels via comma-separated DISCORD_ANNOUNCE_CHANNELS."""
    raw = (os.environ.get("DISCORD_ANNOUNCE_CHANNELS")
           or os.environ.get("DISCORD_CHANNEL") or "")
    return [c.strip() for c in raw.split(",") if c.strip()]


def _set_channels(channels: list[str]):
    _set_env("DISCORD_ANNOUNCE_CHANNELS", ",".join(c.strip() for c in channels if c.strip()))


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

    # Guild selection - can pick MULTIPLE servers and MULTIPLE channels.
    guilds = get_guilds(tok)
    if not guilds:
        print("""
  [SETUP] This bot is in NO servers yet. Invite it:
    {INVITE_LINK}?client_id=YOUR_CLIENT_ID&permissions=3072&scope=bot
  (get YOUR_CLIENT_ID from the application page; it needs Send Messages
   + View Channels). After inviting, re-run:  python discord_bot.py --setup
""".format(INVITE_LINK=INVITE_LINK))
        return False

    # Start from existing channels so re-running ADDS, not replaces.
    current = _load_channels()
    print(f"\n  [SETUP] Existing channels ({len(current)}): "
          f"{', '.join(current) or 'none'}")

    print("\n  [SETUP] Pick servers (the bot is in these):")
    for i, g in enumerate(guilds, 1):
        print(f"    {i}. {g.get('name')} ({g.get('id')})")
    print("  Enter one or more numbers, comma-separated, e.g. '1,2'.")
    gsel = input("  Servers (or Enter to keep existing): ").strip()
    if not gsel:
        print("  [SETUP] No servers selected - keeping existing channels.")
        return True
    picks = set()
    for part in gsel.replace(";", ",").split(","):
        part = part.strip()
        if part.isdigit():
            try:
                picks.add(guilds[int(part) - 1]["id"])
            except Exception:
                pass
        else:
            # allow pasting a server name / id directly
            for g in guilds:
                if part.lower() in (g["name"] or "").lower() or part == g["id"]:
                    picks.add(g["id"])
    if not picks:
        print("  [SETUP] No valid servers selected.")
        return False

    new_ids = []
    for gid in picks:
        guild = next((g for g in guilds if g["id"] == gid), None)
        if not guild:
            continue
        chans = [c for c in get_channels(gid, tok) if c.get("type") in (0, 5)]
        if not chans:
            print(f"  [SETUP] No text channels found in '{guild.get('name')}'.")
            continue
        print(f"\n  [SETUP] Text channels in '{guild.get('name')}':")
        for i, c in enumerate(chans, 1):
            print(f"    {i}. #{c.get('name')} ({c.get('id')})")
        csel = input("  Pick channels (numbers, comma-separated) [1]: ").strip() or "1"
        for part in csel.replace(";", ",").split(","):
            part = part.strip()
            if part.isdigit():
                try:
                    ch = chans[int(part) - 1]
                except Exception:
                    continue
            else:
                low = part.lstrip("#").lower()
                ch = next((c for c in chans
                           if (c["name"] or "").lower() == low or c["id"] == part), None)
            if ch and ch["id"] not in new_ids:
                new_ids.append(ch["id"])
                print(f"    -> added #{ch.get('name')} ({ch['id']})")

    if not new_ids:
        print("  [SETUP] No channels added.")
        return False
    merged = [c for c in current if c not in new_ids] + new_ids
    _set_channels(merged)
    print(f"\n  [OK] Saved {len(new_ids)} new channel(s) to .env.")
    print(f"  [OK] Total announce channels: {len(merged)}")
    print("  [OK] Run `python discord_bot.py --list` to see them, "
          "or `--remove <id>` to drop one.")
    return True


def list_channels():
    """Print the currently configured announce channels with friendly names."""
    tok = _token()
    chans = _load_channels()
    if not chans:
        print("[LIST] No announce channels configured. Run `--setup` to add some.")
        return 0
    # Build id -> (guild_name, channel_name) map across all the bot's servers.
    id2name = {}
    if tok:
        for g in get_guilds(tok):
            for ch in get_channels(g["id"], tok):
                id2name[ch["id"]] = (g["name"], ch["name"])
    print(f"[LIST] {len(chans)} announce channel(s):")
    for c in chans:
        cid = c.lstrip("#")
        info = id2name.get(cid)
        loc = f"{info[0]} / #{info[1]}" if info else "resolved"
        resolved = resolve_channel(c, tok)
        print(f"  - {c}  ({loc}; id={resolved or 'N/A'})")
    return 0


def remove_channel(spec: str):
    """Remove a channel by ID or #name from the announce list."""
    chans = _load_channels()
    target = spec.lstrip("#")
    kept = [c for c in chans if c.lstrip("#") != target]
    if len(kept) == len(chans):
        print(f"[REMOVE] '{spec}' not in the announce list.")
        return 1
    _set_channels(kept)
    print(f"[REMOVE] Removed '{spec}'. {len(kept)} channel(s) remain.")
    return 0


def send_to_all(content: str, token: str | None = None) -> list[dict]:
    """Send a message to every configured announce channel (multi-server)."""
    results = []
    for ch in _load_channels():
        r = send_message(content, ch, token)
        results.append((ch, r))
        if r.get("error"):
            print(f"  [SEND] FAILED {ch}: {r.get('message', r.get('error'))}")
        else:
            print(f"  [SEND] OK -> {ch} (id={r.get('id', '?')})")
    return results


def main():
    args = sys.argv[1:]
    if "--setup" in args:
        sys.exit(0 if setup() else 1)
    if "--test" in args:
        t = test()
        if t.get("ok"):
            print(f"[OK] Bot connected: {t['bot']}")
            print(f"[OK] Servers: {', '.join(t['guilds']) or 'none'}")
            chans = _load_channels()
            if chans:
                for ch in chans:
                    r = resolve_channel(ch)
                    print(f"[OK] Channel '{ch}' -> ID {r if r else 'NOT FOUND'}")
            sys.exit(0)
        print(f"[FAIL] {t.get('message', t.get('error', '?') )}")
        sys.exit(1)
    if "--list" in args:
        sys.exit(list_channels())
    if "--remove" in args:
        i = args.index("--remove")
        spec = args[i + 1] if i + 1 < len(args) else ""
        if not spec:
            print("[REMOVE] usage: python discord_bot.py --remove <channel_id_or_#name>")
            sys.exit(2)
        sys.exit(remove_channel(spec))
    if "--send" in args:
        i = args.index("--send")
        content = args[i + 1] if i + 1 < len(args) else "Hello from Split Node!"
        chans = _load_channels()
        if not chans:
            print("[FAIL] No announce channels configured. Run `--setup` first.")
            sys.exit(1)
        print(f"[SEND] Posting to {len(chans)} channel(s)...")
        send_to_all(content)
        sys.exit(0)
    # No args - print instructions
    print(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main())
