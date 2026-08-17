#!/usr/bin/env python3
"""
SPLIT NODE
True stories of ordinary people who beat the system.
3D mannequin documentary generator (FERN/Black Files style).

Pipeline:
  RSS (hacker/lottery/loophole stories) -> article -> LLM narration script
  -> LLM shot list (clothed mannequins, action scenes, camera logic)
  -> RunPod Z-Image-Turbo 16:9 images per shot
  -> PocketTTS built-in male voice narration (0dB normalized)
  -> FFmpeg render 1080p with music (-19.5dB) + timecoded SFX (-15dB)
  -> FAL GPT Image 2 thumbnail -> YouTube upload (Split Node channel)
"""

import json
import os
import random
import re
import shutil
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
import uuid
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

try:
    from google.oauth2.credentials import Credentials as GoogleCreds
    from google.auth.transport.requests import Request as AuthRefresh
    from tqdm import tqdm
    _HAS_PROGRESS = True
except ImportError:
    _HAS_PROGRESS = False

try:
    import split_node_titles
except Exception:
    split_node_titles = None

try:
    import trend_scorer
except Exception:
    trend_scorer = None

# -- Config ----------------------------------------------------------
PROJECT_DIR = Path(__file__).parent.resolve()

# -- Local .env loader (secrets stay out of git) ---------------------
_ENV_FILE = PROJECT_DIR / ".env"
if _ENV_FILE.is_file():
    for _line in _ENV_FILE.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if not _line or _line.startswith("#") or "=" not in _line:
            continue
        _k, _v = _line.split("=", 1)
        os.environ.setdefault(_k.strip(), _v.strip())

# All per-episode outputs (temp TTS clips, images, rendered audio, video,
# thumbnails, scene boards, style tests) live inside a single top-level
# `episodes/` folder, one subfolder per episode: episodes/ep{N:03d}/. Nothing
# else is spread around the project root. (Joe 2026-08-12)
EPISODES_DIR = PROJECT_DIR / "episodes"
SFX_DIR = PROJECT_DIR / "cinematic_sounds"
USED_ARTICLES_FILE = PROJECT_DIR / ".used_articles.json"
EPISODE_COUNTER_FILE = PROJECT_DIR / ".episode_counter"
# Batch manifest (Joe 2026-08-14): persists the list of queued episode configs
# + per-episode done status so a batch that crashes can be resumed as a batch.
BATCH_FILE = PROJECT_DIR / ".batch_state.json"
# Per-episode resume state: when EPISODE_RESUME=<n> is set, use a dedicated
# .resume_state.ep{n}.json so multiple episodes can run in parallel in the
# same folder without clobbering each other's state. Unset/0 -> the legacy
# single .resume_state.json.
_RESUME_EP = (os.environ.get("EPISODE_RESUME") or "").strip()
try:
    _RESUME_EP_INT = int(_RESUME_EP)
except Exception:
    _RESUME_EP_INT = 0
if _RESUME_EP_INT > 0:
    RESUME_FILE = PROJECT_DIR / f".resume_state.ep{_RESUME_EP_INT:03d}.json"
else:
    RESUME_FILE = PROJECT_DIR / ".resume_state.json"

YOUTUBE_CREDENTIALS = Path.home() / ".youtube-upload-credentials.json"
CLIENT_SECRETS = PROJECT_DIR / "client_secret_874421706318-sl7gg802bovuib9h2q95hq9lvlb661oi.apps.googleusercontent.com.json"


def _episode_dir(episode_num) -> Path:
    """Root folder for ALL of one episode's outputs: episodes/ep{N:03d}/"""
    d = EPISODES_DIR / f"ep{int(episode_num):03d}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _ep_tts_dir(episode_num) -> Path:
    d = _episode_dir(episode_num) / "tts"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _ep_audio_dir(episode_num) -> Path:
    d = _episode_dir(episode_num) / "audio"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _ep_video_dir(episode_num) -> Path:
    d = _episode_dir(episode_num) / "video"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _ep_thumb_dir(episode_num) -> Path:
    d = _episode_dir(episode_num) / "thumbnails"
    d.mkdir(parents=True, exist_ok=True)
    return d


# Shared fallback background (not per-episode - reused across every episode).
FALLBACK_BG = EPISODES_DIR / "_fallback_bg.png"
EPISODES_DIR.mkdir(parents=True, exist_ok=True)

LM_STUDIO_URL = "http://localhost:1234/v1/chat/completions"
POCKET_TTS_URL = "http://127.0.0.1:8769"
FAL_API_KEY = os.environ.get("FAL_API_KEY", "")
RUNPOD_API_KEY = os.environ.get("RUNPOD_API_KEY", "")
RUNPOD_ENDPOINT = "https://api.runpod.ai/v2/z-image-turbo/runsync"

# TTS: TWO custom cloned voice refs (Joe 2026-08-13) cut from the SAME source
# video (7AfSuJfFkMY, "Dark Confession Threads" by Snook):
#   - split_node_intro.wav = the START of the video (announcement style) -> the
#     episode INTRO is spoken in this voice so it sounds like an announcement.
#   - split_node_story.wav = the MIDDLE of the video (storytelling style) -> the
#     episode from chapter 1 onwards is spoken in this more storytelling voice.
# When the voice value is a file path it is uploaded as voice_wav (clone); a bare
# name (e.g. "alba") selects a built-in PocketTTS catalog voice via voice_url.
INTRO_VOICE = str(PROJECT_DIR / "voice_refs" / "split_node_intro.wav")
STORY_VOICE = str(PROJECT_DIR / "voice_refs" / "split_node_story.wav")
# Default narrator = the storytelling voice (chapter 1 onwards).
TTS_VOICE = STORY_VOICE

# Channel / branding
CHANNEL_NAME = "Split Node"
YOUTUBE_PLAYLIST = "Split Node"
YOUTUBE_CATEGORY = "Entertainment"
YOUTUBE_LANGUAGE = "en"
DISCORD_INVITE = "https://discord.gg/YSdqKR4wVB"
# Upload enabled - Split Node channel + client secret are live
YOUTUBE_UPLOAD_ENABLED = True
# 12 persistent AI-documentary-niche tags (topic tags are LLM-generated per video)
YOUTUBE_BASE_TAGS = [
    "split node", "ai documentary", "3d documentary", "ai generated documentary",
    "true stories", "true crime documentary", "documentary", "3d animation",
    "metahuman", "people who beat the system", "incredible true stories",
]

# RSS feeds for the niche (fallback pool - primary source is HN Algolia search).
# Expanded Aug 2026 (money-hack focus): the flagship topic is MONEY HACKS /
# lottery loopholes - ordinary people finding legal ways to make money / beat
# the odds. Money-hack and lottery feeds are listed FIRST and polled first so
# they surface before the other topics.
# NOTE (2026-08-12): the list was audited by testing every feed live. Dead /
# broken feeds were REMOVED (forbes/money 404, businessinsider/money 404,
# wired/tech 404, smartmoney + pennyhoarder + securityweekly malformed XML,
# marktechpost 403, Reddit /r/* 429 rate-limited). Only feeds that actually
# return parseable items are kept.
RSS_FEEDS = [
    # ---- LOTTERY / GAMBLING / ADVANTAGE PLAY (main topic - polled first) ----
    # Sources for the flagship money-hack stories: lottery loopholes, gambling
    # advantage plays (card counting, betting models), casino exploits. Verified
    # live 2026-08-12 (each returns parseable items + strong niche matches).
    "https://www.thelotter.com/blog/feed/",          # lottery formula / how-to
    "https://www.casino.org/blog/feed/",             # gambling advantage plays
    "https://www.gamblingnews.com/feed/",            # gambling news / exploits
    # ---- MONEY HACKS / LOOPHOLES ----
    "https://www.moneycrashers.com/feed/",            # money hacks / saving / side income
    "https://www.wisebread.com/feed/",                # frugal living / money hacks
    "https://lifehacker.com/rss",                     # life + money hacks
    "https://money.com/feed/",                        # personal finance hacks
    "https://www.nerdwallet.com/blog/feed/",          # credit-card / bank hacks
    "https://www.creditcards.com/feed/",              # rewards / cashback hacks
    "https://feeds.feedburner.com/Zerohedge",         # markets / loopholes
    "https://finance.yahoo.com/news/rssindex",        # money / markets news
    "https://feeds.content.dowjones.io/public/rss/mw_marketpulse",  # MarketWatch
    "https://fortune.com/feed/",                      # money / business
    "https://www.cnbc.com/id/10000664/device/rss/rss.html",  # CNBC money
    # ---- CYBERCRIME (hackers making millions) ----
    "https://www.infosecurity-magazine.com/rss/news/", # big security pool
    "https://thecyberexpress.com/feed/",               # cybercrime / exploits
    "https://www.wired.com/feed/tag/cybersecurity/latest/rss",
    "https://krebsonsecurity.com/feed/",
    "https://feeds.feedburner.com/TheHackersNews",
    "https://www.bleepingcomputer.com/feed/",
    "https://www.404media.co/rss/",
    "https://www.darkreading.com/rss.xml",
    "https://www.schneier.com/feed/atom/",
    "https://therecord.media/feed",
    "https://grahamcluley.com/feed/",
    # ---- general / tech (beat-the-system stories surface here) ----
    "https://news.ycombinator.com/rss",
    "https://arstechnica.com/feed/",
    "https://techcrunch.com/feed/",
    "https://www.theverge.com/rss/index.xml",
    "https://venturebeat.com/feed/",
    "https://www.technologyreview.com/feed/",
    "https://feeds.bbci.co.uk/news/technology/rss.xml",
    "https://feeds.bbci.co.uk/news/world/rss.xml",
    "https://www.theguardian.com/technology/rss",
    "https://www.theguardian.com/world/rss",
    "https://feeds.washingtonpost.com/rss/world",
]

# HN Algolia search queries - tuned to the niche: math beating the lottery,
# hackers making money, loopholes exploited. MONEY-HACK / lottery queries are
# listed FIRST and polled first so they surface ahead of the other topics.
# Expanded 2026-08-12 with more money-hack terms to widen the primary pool
# (HN was exhausting on the old query set).
HN_SEARCH_QUERIES = [
    # ---- MONEY HACKS / LOTTERY LOOPHOLES (main topic - polled first) ----
    "lottery loophole",
    "lottery math",
    "lottery jackpot mathematics",
    "won the lottery system",
    "money hack",
    "money hacks",
    "side hustle millions",
    "cashback loophole",
    "credit card hack",
    "reward points exploit",
    "refund exploit",
    "arbitrage money",
    "gambling system beat",
    "card counting blackjack",
    "casino exploit",
    "math professor lottery",
    "lottery algorithm",
    "poker math win",
    "beat the lottery",
    "lottery fraud caught",
    "poker player millions",
    "hustler made money",
    "made millions online",
    "bank loophole money",
    # ---- bank / ATM / money glitches (from Joe's story list) ----
    "bank glitch",
    "atm glitch",
    "bank error overdraft",
    "accidental transfer millions",
    "crypto transfer mistake",
    "bank accidentally paid",
    "infinite money glitch",
    "check deposit glitch",
    # ---- hackers making money / exploits ----
    "hacker made millions",
    "exploit bank millions",
    "stole millions system",
    "beat the system loophole",
    "counterfeit scheme",
    "security flaw millions",
    "social engineering scam millions",
    "fraud loophole millions",
]

# MONEY-HACK priority keywords. Stories matching these are the FLAGSHIP topic
# and are boosted ahead of everything else in the candidate sort, so money-hack
# / lottery-loophole stories always surface FIRST in the RSS poll.
MONEY_PRIORITY_KEYWORDS = [
    "lottery", "jackpot", "loophole", "money hack", "money hacks", "side hustle",
    "cashback", "cash back", "reward points", "credit card hack", "credit hack",
    "refund", "arbitrage", "gambling system", "card counting", "casino exploit",
    "passive income", "make money", "making money", "wealth", "windfall",
    "millions", "payout", "payday", "mathematician", "beat the odds",
    "beat the house", "beat the system", "bookie", "betting exploit",
    "bank exploit", "atm exploit", "bonus exploit", "voucher hack", "coupon hack",
    # bank / ATM / money glitches (Joe's flagship story type)
    "bank glitch", "atm glitch", "money glitch", "bank error", "overdraft",
    "accidental transfer", "mistakenly transferred", "accidentally sent",
    "infinite money", "check deposit glitch", "crypto glitch", "banking glitch",
    "got away with", "windfall money", "spent the money",
]

# Scoring tiers - strong phrases are worth far more than weak ones
STRONG_KEYWORDS = [
    "lottery", "jackpot", "card counting", "blackjack", "casino", "loophole",
    "exploit", "hacked", "hacker", "million", "millions", "scam", "fraud",
    "counterfeit", "stole", "heist", "won", "wins", "poker", "gambling",
    "betting", "math", "mathematician", "algorithm", "money hack", "money hacks",
    "side hustle", "cashback", "cash back", "passive income", "arbitrage",
    "reward points", "credit card hack", "windfall", "payout",
]
WEAK_KEYWORDS = [
    "system", "security", "vulnerability", "breach", "hack", "cheat",
    "bet", "win", "prize", "money", "bank", "scheme", "refund", "saving",
    "deal", "voucher", "coupon",
]
# Words that indicate the story is NOT the niche (news-adjacent noise)
EXCLUDE_WORDS = [
    "election", "war", "ukraine", "russia", "trump", "biden", "covid",
    "pandemic", "stocks", "stock market", "nvidia", "iphone", "samsung",
    "macbook", "playstation", "xbox", "game review", "movie review",
    "trailer", "tv show", "nba", "nfl", "nhl", "soccer", "football",
    "cricket", "tennis", "f1", "olympics", "australia election",
]

def _story_score(title: str, description: str = "") -> int:
    """Score a story by how strongly it matches the niche."""
    text = f"{title} {description}".lower()
    if any(w in text for w in EXCLUDE_WORDS):
        return 0
    score = 0
    for kw in STRONG_KEYWORDS:
        if kw in text:
            score += 2
    for kw in WEAK_KEYWORDS:
        if kw in text:
            score += 1
    return score

def _fetch_hn_algolia(query: str) -> list[dict]:
    """Search HN Algolia for niche stories. Returns [{title, link, description, score, date}]."""
    try:
        ssl_ctx = ssl._create_unverified_context()
        q = urllib.parse.quote(query)
        url = (f"https://hn.algolia.com/api/v1/search?query={q}&tags=story"
               f"&hitsPerPage=15&numericFilters=points%3E20")
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 SplitNode/1.0"})
        with urllib.request.urlopen(req, timeout=15, context=ssl_ctx) as r:
            data = json.loads(r.read())
        items = []
        for h in data.get("hits", []):
            title = h.get("title", "")
            link = h.get("url", "")
            if not title or not link:
                continue
            points = h.get("points", 0)
            comments = h.get("num_comments", 0)
            created = h.get("created_at", "")[:10]
            desc = f"points {points}, comments {comments}, {created}"
            items.append({
                "title": title,
                "link": link,
                "description": desc,
                "score": _story_score(title),
                "hn_points": points,
                "date": h.get("created_at", ""),
            })
        return items
    except Exception as e:
        print(f"  [RSS] HN algolia failed ({query}): {str(e)[:50]}")
        return []

# Render subject base - describes WHAT to render (subject/scene/framing) with
# NO visual style wording. The style (photorealistic, arcane, etc.) is supplied
# ONLY by _style_inject() (the selected STYLE_PROFILES descriptor) so the look is
# fully controlled by the style injection, never hardcoded here (Joe 2026-08-15).
RENDER_STYLE = (
    "A human subject from the story, full body, engaged in the action and "
    "setting described."
)

# Scene-only base for shots with NO character (establishing/landscape/object).
# Neutral content + a hard negative prompt so the image generator never adds a
# person. No style wording - style comes only from _style_inject().
SCENE_STYLE = (
    "The environment and setting from the story, with the objects and detail "
    "described. EMPTY SCENE - no people, no "
    "humans, no characters, no figures, no silhouettes, no faces, no bodies, no hands, "
    "no clothing, no anatomy, absolutely no persons in the frame"
)

# Banned words stripped from EVERY image prompt before it reaches the image
# model (Joe 2026-08-15): 'unreal engine' and 'machine'/'machinery'. These can
# leak in from scene/narration text (e.g. "the machine" in lore) and must never
# reach the generator. Applied in _krea_generate (the single image entry point).
_IMG_BAN_RE = re.compile(
    r"\b(unreal\s+engine(?:\s*5)?|machin(?:e|es|ery))\b", re.IGNORECASE)


def _sanitize_image_prompt(prompt: str) -> str:
    """Strip banned words ('unreal engine', 'machine') from an image prompt and
    tidy the spacing left behind. Returns the cleaned prompt."""
    if not prompt:
        return prompt
    p = _IMG_BAN_RE.sub("", prompt)
    p = re.sub(r"\s{2,}", " ", p)
    p = re.sub(r"\s+([,.;:!?])", r"\1", p)
    p = re.sub(r"([,.;:!?])\s*,", r"\1", p)
    return p.strip()

# Style PROMPT injection (Joe 2026-08-04): b-roll shots, location sheets and
# prop sheets generate as pure txt2img with the channel style injected as
# TEXT instead of image references - faster, and impossible to hit the
# reference-copy bug. The descriptor is extracted ONCE from the two approved
# style sheets (prop + location) via the local vision model, then cached.
STYLE_PROMPT_FILE = PROJECT_DIR / "style_sheets" / "style_prompt.txt"
STYLE_PROMPT_FALLBACK = (
    "bold animated style, strong stylized brushwork, painterly shading, "
    "saturated colors, dramatic rim lighting, dark moody atmosphere, "
    "high detail, cinematic documentary recreation"
)

# PRE-BUILT STYLE PROFILES (Joe 2026-08-06): pick the whole channel's visual
# style with one env var - `STYLE=<name>` or `STYLE_PROFILE=<name>`. The
# selected descriptor is injected as TEXT into every generation (shots,
# character panels, location/prop prompts) so there are NO style image refs.
# An unrecognised/custom value is used verbatim as a free-form style tag.
STYLE_PROFILES = {
    "arcane": (
        "Stylized painterly 3D animation, bold inked outlines, cel-shaded "
        "graphic-novel texture, gritty weathered surfaces, dramatic rim lighting, "
        "saturated slightly-dirty colors, cinematic video-game concept art "
        "finish, NO TEXT, no words, no letters, no captions, no watermarks, no logos"),
    "bold-outline": (
        "bold thick black outlines, flat cel-shaded color, comic book "
        "illustration, high contrast, clean graphic shapes, dynamic angles, "
        "dramatic lighting, high detail"),
    "artsy": (
        "loose expressive brushstrokes, impressionistic painterly texture, "
        "visible canvas weave, warm muted palette, soft atmospheric light, "
        "hand-painted fine-art look, high detail"),
    "photoreal": (
        "hyper-realistic photograph, tack-sharp focus, natural skin texture, "
        "cinematic color grade, shallow depth of field, subtle film grain, "
        "high detail, professional documentary photography"),
    "noir": (
        "black and white film noir, dramatic low-key lighting, deep crushed "
        "shadows, hard contrast, gritty textured grain, moody shadows, "
        "high detail"),
    "synthwave": (
        "retro synthwave aesthetic, neon glow, purple and pink palette, "
        "chrome reflections, glowing grid floor, 1980s retro-futurism, "
        "high detail"),
    "editorial": (
        "clean modern editorial illustration, minimal detail, bold flat "
        "color fields, geometric shapes, contemporary magazine art, "
        "high detail"),
    "watercolor": (
        "delicate watercolor wash, soft bleeding edges, translucent color "
        "layers, gentle paper texture, airy and light, high detail"),
    "mannequin": (
        "photorealistic render, ray tracing, cinematic lighting, seamless "
        "glossy porcelain mannequins with a perfectly smooth ceramic finish, "
        "featureless smooth blank porcelain face (no eyes, nose or mouth "
        "carved in - a completely smooth porcelain head), off-white cream or "
        "warm brown porcelain skin tone (never realistic human skin), NO "
        "human facial features, no facial hair, the ONLY thing carried from "
        "the reference person is their HAIR - the mannequin's hair is styled, "
        "colored and textured EXACTLY like the reference photo's hair, painted "
        "sculpted hair matching the reference hairstyle, no doll joints, no "
        "seams, no visible stands or supports, figures ALWAYS fully clothed "
        "head-to-toe in complete period-accurate outfits with explicitly "
        "named footwear, 8K resolution, hyperrealistic documentary "
        "recreation"),
    "roman-statue": (
        "photorealistic render, ray tracing, cinematic lighting, classical "
        "ancient Roman marble statue, sculpted from pure white/grey Carrara "
        "marble with smooth polished stone surface, the statue's facial "
        "structure matches the reference person EXACTLY - same bone "
        "structure, same brow ridge, same nose shape, same lips, same "
        "jawline, same eyes - but rendered as carved marble like a "
        "classical Roman portrait bust, chiseled stone features, no skin "
        "pores, no realistic human skin, no stubble, no wrinkles, matte "
        "marble finish, the ONLY thing carried from the reference person "
        "beyond the face is their HAIR - carved as sculpted marble hair "
        "matching the reference hairstyle exactly, toga-clad or draped "
        "classical Roman garment, weathered classical marble, high detail, "
        "museum-quality ancient statue, 8K resolution, hyperrealistic "
        "documentary recreation"),
}

_STYLE_SELECTED_PRINTED = {"done": False}

# User-added styles persist here so "add new style" survives across runs and
# becomes selectable via STYLE=<name> like any built-in profile.
STYLE_CUSTOM_FILE = PROJECT_DIR / "style_sheets" / "custom_styles.json"


def _load_style_profiles() -> dict:
    """Built-in STYLE_PROFILES merged with any user-added styles persisted in
    custom_styles.json, so a new style is selectable on every future run."""
    merged = dict(STYLE_PROFILES)
    try:
        if STYLE_CUSTOM_FILE.is_file():
            custom = json.loads(STYLE_CUSTOM_FILE.read_text(encoding="utf-8"))
            if isinstance(custom, dict):
                for k, v in custom.items():
                    if isinstance(v, str) and v.strip():
                        merged[k.strip().lower()] = v.strip()
    except Exception:
        pass
    return merged


def list_style_profiles() -> None:
    """Print every selectable style profile (built-in + custom)."""
    for name, desc in sorted(_load_style_profiles().items()):
        print(f"  {name:16} {desc[:60]}{'...' if len(desc) > 60 else ''}")


def add_custom_style(name: str, descriptor: str) -> bool:
    """Persist a new selectable style profile. Returns True on success."""
    name = name.strip().lower()
    descriptor = descriptor.strip()
    if not name or not descriptor:
        print("  [STYLE] add requires a name AND a descriptor")
        return False
    if name in STYLE_PROFILES:
        print(f"  [STYLE] '{name}' is a built-in profile - pick another name")
        return False
    profiles = {}
    try:
        if STYLE_CUSTOM_FILE.is_file():
            profiles = json.loads(STYLE_CUSTOM_FILE.read_text(encoding="utf-8"))
    except Exception:
        profiles = {}
    if not isinstance(profiles, dict):
        profiles = {}
    profiles[name] = descriptor
    try:
        STYLE_CUSTOM_FILE.parent.mkdir(parents=True, exist_ok=True)
        STYLE_CUSTOM_FILE.write_text(json.dumps(profiles, indent=2), encoding="utf-8")
        print(f"  [STYLE] added custom style '{name}' -> selectable via STYLE={name}")
        return True
    except Exception as e:
        print(f"  [STYLE] could not save custom style: {e}")
        return False


def remove_custom_style(name: str) -> bool:
    try:
        if not STYLE_CUSTOM_FILE.is_file():
            return False
        profiles = json.loads(STYLE_CUSTOM_FILE.read_text(encoding="utf-8"))
        if isinstance(profiles, dict) and name.lower() in profiles:
            del profiles[name.lower()]
            STYLE_CUSTOM_FILE.write_text(json.dumps(profiles, indent=2),
                                         encoding="utf-8")
            print(f"  [STYLE] removed custom style '{name.lower()}'")
            return True
    except Exception:
        pass
    return False


# ---------------------------------------------------------------------------
# Easter eggs - one hidden background element in EXACTLY ONE shot per episode.
# The element is injected into that single shot's prompt as a "very small, in
# the background" element (an easter egg - subtle, easy to miss). After render
# and after upload the exact timecode of the hidden shot is reported.
# ---------------------------------------------------------------------------
EASTER_EGG_FILE = PROJECT_DIR / "style_sheets" / "easter_eggs.json"

BUILTIN_EASTER_EGGS = {
    "duck pope": (
        "In the far background, very small and soft-focus, is the Duck Pope - "
        "an ancient majestic sacred tiny white duck dressed as a pope, wearing "
        "a tall two-peaked white-and-gold papal mitre and a small white papal "
        "robe with gold trim. He is tiny and barely noticeable in the distance, "
        "blurred, not the subject of the shot, a subtle hidden detail."
    ),
}


def _load_easter_eggs() -> dict:
    """Built-in + user-added easter eggs (persisted in easter_eggs.json)."""
    merged = dict(BUILTIN_EASTER_EGGS)
    try:
        if EASTER_EGG_FILE.is_file():
            custom = json.loads(EASTER_EGG_FILE.read_text(encoding="utf-8"))
            if isinstance(custom, dict):
                for k, v in custom.items():
                    if isinstance(v, str) and v.strip():
                        merged[k.strip().lower()] = v.strip()
    except Exception:
        pass
    return merged


def list_easter_eggs() -> None:
    for name, desc in sorted(_load_easter_eggs().items()):
        print(f"  {name:18} {desc[:55]}{'...' if len(desc) > 55 else ''}")


def add_easter_egg(name: str, prompt: str) -> bool:
    name = name.strip().lower()
    prompt = prompt.strip()
    if not name or not prompt:
        print("  [EGG] add requires a name AND a prompt")
        return False
    if name in BUILTIN_EASTER_EGGS:
        print(f"  [EGG] '{name}' is a built-in easter egg - pick another name")
        return False
    eggs = {}
    try:
        if EASTER_EGG_FILE.is_file():
            eggs = json.loads(EASTER_EGG_FILE.read_text(encoding="utf-8"))
    except Exception:
        eggs = {}
    if not isinstance(eggs, dict):
        eggs = {}
    eggs[name] = prompt
    try:
        EASTER_EGG_FILE.parent.mkdir(parents=True, exist_ok=True)
        EASTER_EGG_FILE.write_text(json.dumps(eggs, indent=2), encoding="utf-8")
        print(f"  [EGG] added easter egg '{name}' (selectable in future runs)")
        return True
    except Exception as e:
        print(f"  [EGG] could not save: {e}")
        return False


def remove_easter_egg(name: str) -> bool:
    try:
        if not EASTER_EGG_FILE.is_file():
            return False
        eggs = json.loads(EASTER_EGG_FILE.read_text(encoding="utf-8"))
        if isinstance(eggs, dict) and name.lower() in eggs:
            del eggs[name.lower()]
            EASTER_EGG_FILE.write_text(json.dumps(eggs, indent=2), encoding="utf-8")
            print(f"  [EGG] removed easter egg '{name.lower()}'")
            return True
    except Exception:
        pass
    return False


def _input_timeout(prompt: str, timeout: float = 10.0, default: str = "") -> str:
    """Read a line from stdin with a timeout; return `default` if the user
    doesn't answer in time. On Windows uses msvcrt for non-blocking reads so a
    headless/automated run (no one at the keyboard) falls through to the
    default instead of hanging the pipeline forever."""
    sys.stdout.write(prompt)
    sys.stdout.flush()
    try:
        import msvcrt  # Windows only
    except ImportError:
        try:
            line = input()
            return line.strip()
        except EOFError:
            return default
    chars = []
    deadline = time.time() + timeout
    while time.time() < deadline:
        if msvcrt.kbhit():
            ch = msvcrt.getwche()
            if ch == "\r" or ch == "\n":
                sys.stdout.write("\n")
                sys.stdout.flush()
                return "".join(chars).strip()
            chars.append(ch)
        else:
            time.sleep(0.05)
    sys.stdout.write("\n")
    sys.stdout.flush()
    return default


def _ask_easter_egg() -> Optional[str]:
    """Ask whether to hide an easter egg in one shot. Returns the egg NAME or
    None. EASTER_EGG=<name> env selects directly without prompting.

    Joe 2026-08-13: if there's no answer in 10s default to YES, then after
    another 10s default the egg choice to 'duck pope' - so an unattended run
    always gets a duck-pope easter egg instead of stalling on the prompt."""
    if os.environ.get("EASTER_EGG"):
        name = os.environ.get("EASTER_EGG").strip().lower()
        eggs = _load_easter_eggs()
        if name in eggs:
            print(f"  [EGG] easter egg selected via env: '{name}'")
            return name
        print(f"  [EGG] unknown easter egg '{name}' - skipping")
        return None
    resp = _input_timeout("\n  Hide an easter egg in one shot? [Y/n]: ", 10.0, "y").lower()
    if resp in ("n", "no"):
        return None
    if not resp or resp in ("y", "yes"):
        print("  [EGG] defaulting to YES")
    eggs = _load_easter_eggs()
    names = list(eggs.keys())
    print("  Select an easter egg:")
    for i, n in enumerate(names, 1):
        print(f"    {i}. {n}")
    print(f"    {len(names)+1}. add new")
    # Default to 'duck pope' after 10s if no answer (Joe 2026-08-13)
    choice = _input_timeout(f"  Choose [1-{len(names)+1}, or a name]: ", 10.0, "duck pope").strip()
    if not choice or choice.lower() == "duck pope":
        if "duck pope" in [n.lower() for n in names]:
            print("  [EGG] defaulting to 'duck pope'")
            return "duck pope"
    if choice.lower() in ("add", "add new", "new", "custom", str(len(names)+1)):
        newname = _input_timeout("  Easter egg name: ", 10.0, "").strip()
        newprompt = _input_timeout("  Easter egg prompt (describes the small background element): ", 10.0, "").strip()
        if newname and newprompt:
            add_easter_egg(newname, newprompt)
            return newname.lower()
        print("  [EGG] need a name and a prompt - no easter egg added")
        return None
    if choice.isdigit() and 1 <= int(choice) <= len(names):
        return names[int(choice) - 1].lower()
    if choice.lower() in [n.lower() for n in names]:
        return choice.lower()
    # Fall back to duck pope if we have it
    if "duck pope" in [n.lower() for n in names]:
        print("  [EGG] invalid choice - defaulting to 'duck pope'")
        return "duck pope"
    print("  [EGG] invalid choice - no easter egg this episode")
    return None


def _inject_easter_egg(shots: list[dict], egg_name: Optional[str]) -> None:
    """Hide the easter egg into EXACTLY ONE shot of the episode (prompt text).
    Prefers a wide/medium shot so there is room in the background; falls back
    to any non-chapter shot. Idempotent on resume (skips if already set)."""
    if not egg_name:
        return
    if any(s.get("easter_egg") for s in shots):
        return
    eggs = _load_easter_eggs()
    prompt = eggs.get(egg_name, "")
    if not prompt:
        print(f"  [EGG] no prompt found for '{egg_name}' - skipping")
        return
    eligible = [i for i, s in enumerate(shots)
                if not s.get("is_chapter")
                and str(s.get("shot_type", "")).upper() in ("WS", "MS", "EWS")]
    if not eligible:
        eligible = [i for i, s in enumerate(shots) if not s.get("is_chapter")]
    if not eligible:
        print("  [EGG] no eligible shot - skipping")
        return
    idx = eligible[random.randint(0, len(eligible) - 1)]
    shots[idx]["easter_egg"] = egg_name
    shots[idx]["easter_egg_prompt"] = prompt
    print(f"  [EGG] hiding '{egg_name}' in shot {idx+1}/{len(shots)} "
          f"({shots[idx].get('shot_type', '?')})")


def _fmt_timecode(seconds: float) -> str:
    s = max(int(seconds or 0), 0)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{sec:02d}"


def _easter_egg_report(shots: list[dict]) -> Optional[str]:
    """Where the hidden easter egg lands in the final video timecode. Returns a
    human string, or None if no easter egg was injected.

    Uses the SAME timeline math as the render (_compute_clip_starts, which
    applies the real per-shot pacing gaps via _pace_gaps_after). A naive flat
    +0.3s-per-shot estimate drifts earlier than the actual video by ~0.7-1.3s
    per shot, so the reported timecode didn't match where the egg really is
    (Joe 2026-08-13). clip_starts only contains TTS-bearing shots, so we walk
    the list and consume a start for each clip shot."""
    egg_shot = next((s for s in shots if s.get("easter_egg")), None)
    if not egg_shot:
        return None
    starts = _compute_clip_starts(shots)
    si = 0
    cursor = 0.0
    for s in shots:
        if s is egg_shot:
            cursor = starts[si] if si < len(starts) else 0.0
            break
        if s.get("tts_path") and os.path.isfile(s["tts_path"]):
            si += 1
    name = str(egg_shot.get("easter_egg", "easter egg"))
    return (f"[EASTER EGG] '{name}' is hidden in the shot at "
            f"{_fmt_timecode(cursor)} in the final video")


# Set from the resume state when an episode is resumed, so a resume run keeps
# the exact style the episode was generated with (unless STYLE is set).
_RESUME_STYLE = None


def _get_style_prompt(force: bool = False) -> str:
    """Channel style descriptor for prompt injection. Resolution order:
      1. env STYLE / STYLE_PROFILE (explicit choice for THIS run)
      2. the style recorded in the resume state (resume runs keep their look)
      3. the cached sheet-extracted descriptor / arcane default
    A profile name in STYLE_PROFILES maps to its descriptor; anything else is
    treated as a free-form style tag used verbatim."""
    sel = (os.environ.get("STYLE") or os.environ.get("STYLE_PROFILE") or "").strip()
    if not sel and _RESUME_STYLE:
        sel = str(_RESUME_STYLE)
    low = sel.lower()
    profiles = _load_style_profiles()
    if sel:
        if low in profiles:
            desc = profiles[low]
        else:
            desc = sel  # custom free-form style tag (incl. resume descriptor)
    elif not force and STYLE_PROMPT_FILE.is_file():
        txt = STYLE_PROMPT_FILE.read_text(encoding="utf-8").strip()
        desc = txt or profiles["arcane"]
    else:
        desc = _describe_style_from_sheets() or profiles["arcane"]
    if not _STYLE_SELECTED_PRINTED["done"]:
        label = low if low in profiles else "custom"
        extra = f" ({sel})" if low not in profiles else ""
        print(f"  [STYLE] active profile: {label}{extra}")
        _STYLE_SELECTED_PRINTED["done"] = True
    return desc


def _describe_style_from_sheets() -> str:
    """Vision model: describe ONLY the shared visual painting/render style of
    the two approved style sheets (prop_style_sheet.png + location_style_sheet.
    png) - never the subjects. Returns a plain-text style descriptor."""
    import base64
    imgs = [str(PROP_STYLE_REF), str(LOCATION_STYLE_REF)]
    imgs = [p for p in imgs if p and os.path.isfile(p)]
    if not imgs:
        return ""
    try:
        content = [{"type": "text", "text":
            "Describe ONLY the visual PAINTING/RENDER STYLE shared by these "
            "two reference artworks - brushwork, linework, color palette, "
            "lighting, shading, rendering technique, texture and mood. Say "
            "NOTHING about the subjects, objects, people or scenes depicted. "
            "Reply with EXACTLY ONE plain sentence, at most 30 words, that a "
            "text-to-image model can use directly as a style tag. No preamble, "
            "no commentary, no quotes, no markdown."}]
        for p in imgs:
            b64 = base64.b64encode(Path(p).read_bytes()).decode()
            content.append({"type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{b64}"}})
        body = json.dumps({"model": "gemma-4-e4b-uncensored-hauhaucs-aggressive",
                           "messages": [{"role": "user", "content": content}],
                           "max_tokens": 250, "temperature": 0.2}).encode()
        req = urllib.request.Request("http://localhost:1234/v1/chat/completions",
                                     data=body,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=120) as r:
            out = json.loads(r.read().decode())
        ans = out["choices"][0]["message"]["content"].strip()
        # The roleplay-tuned model adds preamble chatter no matter how strict
        # the instruction - the actual descriptor is the LAST paragraph.
        paras = [p.strip() for p in re.split(r"\n\s*\n", ans) if p.strip()]
        ans = paras[-1] if paras else ans
        return ans[:400]
    except Exception as e:
        print(f"  [STYLE] vision extraction failed: {str(e)[:80]}")
        return ""


def _style_inject(allow_logo: bool = False) -> str:
    """CRITICAL style injection appended to every image prompt (shots, b-roll,
    location/prop sheets, character panels). The style is a NON-NEGOTIABLE
    hard requirement, framed emphatically so the model can't drop or dilute it.
    Text-only style transfer (no image refs).

    `allow_logo=True` (Joe 2026-08-09): when a business logo is being used as
    an image ref (a business-location shot / logo-on-building shot), the style's
    "no logos" clause is REMOVED so it doesn't conflict with the attached logo
    ref - the logo is allowed to appear in the frame. For all other shots the
    "no logos" clause stays (prevents gpt-image-2 hallucinating stray logos).
    """
    desc = _get_style_prompt().rstrip(".")
    if allow_logo:
        # Drop the anti-logo clause so an attached business-logo ref isn't
        # contradicted by the style prompt.
        desc = re.sub(r",?\s*(no logos|no logo)\b", "", desc, flags=re.IGNORECASE)
    return (
        f"CRITICAL - THIS IMAGE MUST BE RENDERED STRICTLY IN THE FOLLOWING "
        f"VISUAL STYLE AND NOTHING ELSE: '{desc}'. DO NOT deviate from, "
        f"dilute, or replace this style with any other art direction, "
        f"painting style, or rendering style - the chosen style is mandatory "
        f"and overrides all other stylistic choices. Apply it to the ENTIRE "
        f"frame, every element, the background, the lighting, the color grade "
        f"and the rendering finish without exception."
    )


# Channel-wide style plate: reference image(s) defining the uniform Split
# Node look (Arcane-style sheets from style_sheets/). Fed as the SCENE ref
# in identity mode (image 1) alongside character faces / location / props
# (images 2+) so every shot inherits the same style. STYLE_REF=0 disables.
# Prefer the merged sheet (build_style_sheet.py), fall back to the single
# generated plate.
STYLE_REF_IMG = PROJECT_DIR / "style_sheets" / "style_sheet.png"
if not STYLE_REF_IMG.is_file():
    STYLE_REF_IMG = PROJECT_DIR / "style_refs" / "split_node_style.png"

# Dedicated style sheets for ASSETS (Joe, 2026-08-04): the people-style
# plate (style_sheet.png) contains FACES which bled into location/prop
# panels. Location sheets and prop assets now reference their OWN clean
# style sheets (composed from Joe-approved face-free panels) so they pick
# up the render style WITHOUT copying people. STYLE_REF=0 disables all.
LOCATION_STYLE_REF = PROJECT_DIR / "style_sheets" / "location_style_sheet.png"
if not LOCATION_STYLE_REF.is_file():
    LOCATION_STYLE_REF = STYLE_REF_IMG
PROP_STYLE_REF = PROJECT_DIR / "style_sheets" / "prop_style_sheet.png"
if not PROP_STYLE_REF.is_file():
    PROP_STYLE_REF = STYLE_REF_IMG


_ASSET_STOP = {
    "the", "a", "an", "of", "in", "on", "at", "with", "and", "or", "but", "his",
    "her", "their", "its", "is", "are", "was", "were", "be", "been", "to", "from",
    "by", "for", "as", "into", "onto", "over", "under", "through", "between",
    "against", "during", "showing", "seen", "full", "dark", "dim", "dimly", "lit",
    "low", "cinematic", "moody", "wide", "extreme", "close", "up", "shot", "view",
    "scene", "framing", "camera", "angle", "room", "roomful", "empty", "large",
    "small", "big", "old", "new", "huge", "tiny", "single", "multiple", "several",
}


def _scene_keywords(scene: str) -> list[str]:
    toks = re.findall(r"[a-z0-9']+", (scene or "").lower())
    return [t for t in toks if t not in _ASSET_STOP and len(t) > 2]


def _upscale_to_1080p(image_path: str) -> None:
    """Upscale an image to exactly 1920x1080 in place using 4x-FaceUpDAT.

    Pipeline rule: all images that enter the workflow (b-roll cache, Krea 2
    shots) are upscaled to 1080p with the ComfyUI model BEFORE FFmpeg touches
    them - so the zoompan render never upscales a soft source and output stays
    crisp at hevc_nvenc 1080p.

    After upscaling, a uniform grade (style-card look: +contrast, -saturation,
    slight lift) is applied so every shot shares the same locked look.
    """
    script = PROJECT_DIR / "upscale_model.py"
    if not script.is_file():
        return
    model = r"F:\ComfyUI_windows_portable\ComfyUI\models\upscale_models\4xFaceUpDAT.safetensors"
    comfy_py = r"F:\ComfyUI_windows_portable\python_embeded\python.exe"
    if not os.path.isfile(model) or not os.path.isfile(comfy_py):
        return
    try:
        import subprocess as _sp
        _sp.run([comfy_py, str(script), model, image_path, image_path],
                capture_output=True, text=True, timeout=240)
        _apply_grade(image_path)
    except Exception:
        pass


def _apply_grade(image_path: str) -> None:
    """Style-card grade: uniform look across every shot (contrast, saturation,
    brightness). In-place. Best-effort; never raises."""
    try:
        from PIL import Image, ImageEnhance
        img = Image.open(image_path).convert("RGB")
        img = ImageEnhance.Contrast(img).enhance(1.06)
        img = ImageEnhance.Color(img).enhance(0.92)
        img = ImageEnhance.Brightness(img).enhance(0.99)
        img.save(image_path)
    except Exception:
        pass

# Camera logic per the documentary shot-list framework
CAMERA_LOGIC = """
DOCUMENTARY CAMERA LOGIC - shot variety by wideness and angle:
- EWS (Extreme Wide Shot): vast expansive view, entire landscape/exterior. Sets scale and isolation.
- WS (Wide Shot / Establishing): full body of subject + environment context. Introduces location, character-to-environment space.
- MS (Medium Shot): waist-up framing. Neutral baseline for interaction, gestures, action.
- CU (Close-Up): head and shoulders. Raw emotion, intense moments.
- ECU (Extreme Close-Up): tight focus on a feature or object (hands, tools, documents, money). Key narrative details.
- Eye-Level: neutral, honest, direct.
- Low-Angle: camera looks up, subject feels powerful/authoritative.
- High-Angle: camera looks down, subject feels vulnerable/small.
- Over-the-Shoulder (OTS): past a subject's shoulder, anchors conversational/confrontational context.
- From Behind: watching the subject act, mystery/anticipation.
- Side-On: profile view of the action.
Vary the shots across the episode - do not repeat the same framing twice in a row.
"""

# Cinematic SFX library - pre-analyzed: build (attack start), hit (peak), decay (tail end)
SFX_LIBRARY = {
    "mixkit-big-cinematic-impact-788.mp3": {"dur": 7.94, "build": 1.9, "hit": 2.15, "decay": 3.2, "desc": "big cinematic impact"},
    "mixkit-cinematic-mystery-heartbeat-transition-492.wav": {"dur": 67.27, "build": 0.0, "hit": 37.7, "decay": 56.65, "desc": "mystery heartbeat transition"},
    "mixkit-cinematic-trailer-riser-790.wav": {"dur": 2.57, "build": 1.95, "hit": 2.5, "decay": 2.5, "desc": "trailer riser (builds up)"},
    "mixkit-cinematic-transition-swoosh-heartbeat-trailer-488.wav": {"dur": 8.11, "build": 0.6, "hit": 3.45, "decay": 3.6, "desc": "transition swoosh + heartbeat"},
    "mixkit-cinematic-tunnel-reverb-woosh-1486.wav": {"dur": 6.75, "build": 0.4, "hit": 0.6, "decay": 3.0, "desc": "tunnel reverb woosh"},
    "mixkit-cinematic-whoosh-deep-impact-1143.mp3": {"dur": 4.08, "build": 0.35, "hit": 0.55, "decay": 1.1, "desc": "whoosh deep impact"},
    "mixkit-cinematic-whoosh-fast-transition-1492.wav": {"dur": 1.33, "build": 0.9, "hit": 1.05, "decay": 1.25, "desc": "fast whoosh transition"},
    "mixkit-epic-orchestra-transition-2290.wav": {"dur": 7.12, "build": 0.0, "hit": 1.1, "decay": 3.15, "desc": "epic orchestra transition"},
    "mixkit-glitchy-cinematic-suspense-hit-679.wav": {"dur": 13.33, "build": 0.1, "hit": 0.1, "decay": 6.05, "desc": "glitchy suspense hit"},
    "mixkit-magic-sparkle-whoosh-2350.wav": {"dur": 3.5, "build": 0.1, "hit": 0.45, "decay": 1.25, "desc": "magic sparkle whoosh"},
    "mixkit-reverse-cinematic-impact-trailer-784.wav": {"dur": 10.08, "build": 0.1, "hit": 0.1, "decay": 2.65, "desc": "reverse cinematic impact"},
    "mixkit-short-space-stutter-intro-riser-1144.mp3": {"dur": 6.56, "build": 2.6, "hit": 6.25, "decay": 6.5, "desc": "space stutter riser (slow build)"},
    # -- Split Node title/SFX additions (trimmed + pre-analyzed Aug 2026) --
    "typewriter-clicks.wav": {"dur": 1.6, "build": 0.0, "hit": 0.1, "decay": 1.5, "desc": "typewriter keystrokes (1.6s, for 1.5s typewriter animation)", "max_dur": 1.5},
    "glitch-off.wav": {"dur": 0.7, "build": 0.0, "hit": 0.15, "decay": 0.6, "desc": "short digital glitch (for 0.5s title glitch-off)", "max_dur": 0.5},
    "camera-shutter-short.wav": {"dur": 1.0, "build": 0.15, "hit": 0.2, "decay": 0.4, "desc": "camera shutter click (new character/location switch)"},
    # -- Key-word + chapter whoosh (Joe 2026-08-12) - hit points analyzed 2026-08-12 --
    "soundreality-whoosh-pointer-243108.mp3": {"dur": 8.04, "build": 0.6, "hit": 0.7, "decay": 2.0, "desc": "key-word whoosh pointer (word highlight)", "max_dur": 2.0},
    "Whooshs/Sub Bass - Whoosh - (Nikko Hunt's S.D.Essentials).wav": {"dur": 6.37, "build": 1.6, "hit": 2.15, "decay": 2.0, "desc": "sub bass whoosh (chapter card transition)", "max_dur": 4.0},
}

# -- Load the analysed Nikko Hunt's S.D.Essentials library (aliases -> files) --
# Built by analyze_sfx.py (re-run after adding new sounds). Each entry has a
# "file" key pointing at the real path under cinematic_sounds/.
_SFX_EXTRA_FILE = PROJECT_DIR / "sfx_library_extra.json"
if _SFX_EXTRA_FILE.is_file():
    try:
        _extra = json.loads(_SFX_EXTRA_FILE.read_text())
        for _k, _v in _extra.items():
            if _k not in SFX_LIBRARY:
                SFX_LIBRARY[_k] = _v
    except Exception as _e:
        print(f"  [WARN] sfx_library_extra.json load failed: {_e}")


def _sfx_path(name: str) -> Optional[Path]:
    """Resolve an SFX_LIBRARY name to its real file (handles subfolder paths)."""
    meta = SFX_LIBRARY.get(name)
    if not meta:
        return None
    rel = meta.get("file", name)
    p = SFX_DIR / rel
    return p if p.is_file() else None


# ---------------------------------------------------------------------------
# Foley pipeline - map ACTION words in a shot's scene text to matching sounds.
# Whenever a character is doing something (typing, driving, walking, knocking,
# etc) the matching foley sound plays under that clip. Each rule lists
# (keywords, candidate sfx names) - the first candidate that exists in the
# library wins. Keywords are matched case-insensitively against the scene.
# ---------------------------------------------------------------------------
FOLEY_MAP: list[tuple[tuple[str, ...], tuple[str, ...]]] = [
    # typing - ONLY when someone is ACTIVELY typing (Joe 2026-08-13). A bare
    # 'keyboard' / 'typewriter' / 'keys on' object in the scene must NOT trigger
    # typing foley when no one is physically typing in the image. Removed those
    # object-noun keywords so the typewriter click only fires on real typing.
    (("typing", "types on", "types away", "types rapidly", "typing on",
      "at the keyboard", "tapping", "taps on", "taps at", "hits the keys",
      "pounding the keys", "hammers the keys", "clacks the keys"),
     ("foley-typewriter-style-sound", "typewriter-clicks")),
    # boat / ship - BEFORE driving so 'boat engine' matches the boat rule
    (("boat", "ship", "sailing", "sailor", "vessel", "canoe", "rowing",
      "speedboat", "ferry", "boat engine", "ship's engine"),
     ("foley-old-boat-engine", "foley-speed-boat-in-the-jungle")),
    # driving / car / engine
    (("driving", "drives", "drove", "driver", "car", "vehicle", "road",
      "motorway", "highway", "engine", "accelerat", "vroom", "traffic"),
     ("foley-2-motorbikes-driving-past", "sweep-engine-start-up",
      "foley-yangon-traffic")),
    # walking / footsteps
    (("walking", "walks", "walked", "footsteps", "footsteps", "steps",
      "paces", "strides", "marches", "runs", "ran", "treads", "treading"),
     ("foley-footsteps-in-fake-versace-sliders",)),
    # door / knocking
    (("door", "doorway", "knock", "knocks", "knocked", "opens the door",
      "closes the door", "slams", "slams the door", "enters the room",
      "leaves the room"),
     ("foley-door-closing",)),
    # fire / burning / crackle
    (("fire", "burn", "burning", "burns", "flames", "flame", "fireplace",
      "crackle", "campfire", "arson", "lit the fire"),
     ("foley-crackle",)),
    # rain
    (("rain", "raining", "rainfall", "downpour", "storm outside",
      "pouring rain", "rain on"),
     ("nature-rain-on-the-road", "nature-rain-pattering")),
    # thunder
    (("thunder", "thunderstorm", "lightning", "storm brewing"),
     ("nature-close-thunder", "nature-distant-thunder")),
    # ocean / waves / sea / beach
    (("ocean", "sea", "waves", "beach", "shore", "coast", "surf", "tide",
      "sailing the sea"),
     ("nature-waves-breaking", "nature-distant-ocean-with-a-few-birds",
      "nature-beach-with-distant-chatter")),
    # river / flowing water
    (("river", "creek", "stream", "flowing water", "water flowing", "brook",
      "babbling"),
     ("nature-fast-flowing-river", "nature-trickling-water")),
    # waterfall
    (("waterfall", "falls", "cascade"),
     ("nature-heavy-waterfall-close",)),
    # city / street / construction
    (("city", "street", "downtown", "urban", "construction", "building site",
      "busy city", "market", "bazaar"),
     ("foley-busy-city-with-construction", "foley-yangon-traffic")),
    # jungle / forest / grass
    (("jungle", "forest", "woods", "bushland", "tall grass", "long grass",
      "undergrowth", "treeline"),
     ("nature-jungles-of-sarawak", "foley-rustling-long-grass")),
    # crickets / night insects
    (("crickets", "insects", "cicadas", "night sounds", "frogs"),
     ("nature-crickets-v-s-cockerel",)),
    # cave / bats
    (("cave", "bats", "cavern", "underground"),
     ("nature-bats-in-a-cave",)),
    # church / prayer / bell
    (("church", "prayer", "praying", "bell", "bells", "mosque", "temple",
      "chanting", "hymn"),
     ("foley-multiple-prayer-calls", "foley-bell-with-delay")),
    # cooking / gas / stove
    (("cook", "cooking", "stove", "oven", "gas burner", "kitchen", "frying",
      "boiling water", "kettle"),
     ("foley-gas-cooker-gas",)),
    # paddy field / farmland
    (("paddy", "field", "farm", "farmland", "plantation", "rice"),
     ("nature-paddy-fields", "nature-paddy-fields-early-morning")),
    # market street performers
    (("street performer", "busker", "musician playing", "crowd", "crowds"),
     ("foley-barcelona-street-performers",)),
]

# Lowest-priority foley: any scene that clearly describes an action but has no
# specific match falls back to a gentle sweep / whoosh so it isn't silent.
_FOLEY_FALLBACK = ("sweep-gentle", "whoosh-light")


def _foley_for_scene(scene: str) -> Optional[str]:
    """Return the best foley sound for an action described in the scene text,
    or None when the scene has no clear action sound. Picks the first rule
    whose keywords match AND whose candidate file actually exists."""
    if not scene:
        return None
    s = scene.lower()
    for keywords, candidates in FOLEY_MAP:
        if any(k in s for k in keywords):
            for cand in candidates:
                if _sfx_path(cand):
                    return cand
            # rule matched but no file - fall through to next rule
    return None


def _sfx_llm_choices() -> str:
    """Full categorized SFX list for the shot-list prompt. Every category in
    cinematic_sounds/ is exposed with a usage hint so the model can pick
    ambience (nature/foley/soundscape) as well as hits/whooshes/risers."""
    def pick(prefix: str) -> list[str]:
        ks = sorted(k for k in SFX_LIBRARY if k.startswith(prefix))
        return [k for k in ks
                if k != "hit-shell-shock-high-ring-not-nice-for-ears"]
    groups = [
        ("HITS - dramatic impact / reveals / big moments", pick("hit-")),
        ("WHOOSHES - transitions, camera moves, energy", pick("whoosh-")),
        ("RISERS - build-up that resolves INTO a reveal", pick("riser-")),
        ("SWEEPS - gliding transitions / scene shifts", pick("sweep-")),
        ("GLITCHES - digital fracture / corruption", pick("glitch-")),
        ("NATURE - outdoor ambience (rain, waves, thunder, jungle)", pick("nature-")),
        ("FOLEY - real-world action/environment (traffic, footsteps, doors, engines)", pick("foley-")),
        ("SOUNDSCAPES - tense/uneasy ambient beds (abyss, rumble, tension)", pick("soundscape-")),
    ]
    lines = [f"  {label}: {', '.join(ks)}" for label, ks in groups if ks]
    base = [
        "mixkit-big-cinematic-impact-788.mp3", "mixkit-cinematic-mystery-heartbeat-transition-492.wav",
        "mixkit-cinematic-trailer-riser-790.wav", "mixkit-cinematic-transition-swoosh-heartbeat-trailer-488.wav",
        "mixkit-cinematic-tunnel-reverb-woosh-1486.wav", "mixkit-cinematic-whoosh-deep-impact-1143.mp3",
        "mixkit-cinematic-whoosh-fast-transition-1492.wav", "mixkit-epic-orchestra-transition-2290.wav",
        "mixkit-glitchy-cinematic-suspense-hit-679.wav", "mixkit-magic-sparkle-whoosh-2350.wav",
        "mixkit-reverse-cinematic-impact-trailer-784.wav", "mixkit-short-space-stutter-intro-riser-1144.mp3",
    ]
    lines.insert(0, "  MIXKIT (cinematic trailer sounds): " + ", ".join(base))
    return "\n".join(lines)

# -- Chapter / location / timeline title config -----------------------------
# Narration paragraphs that begin with "Chapter N - ..." become black-screen
# placeholder clips + centered glowing chapter cards.
CHAPTER_RE = re.compile(r"^\s*chapter\s+(\d{1,2})\s*[-–:.]?\s*(.+)$", re.IGNORECASE)

# Location anchors: places the narrator reads aloud, which become bottom-left
# typewriter titles (RED = location). Timeline/date titles were removed from
# the pipeline (Aug 2026) - dates no longer appear in scripts or titles.
LOCATION_PATTERNS = [
    # "Goulburn, New South Wales" / "Queen Square, Sydney" (comma pairs)
    re.compile(r"([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+){0,2}),\s+([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+){0,2})"),
    # "in Sydney" / "at the kitchen table of his flat" (in/at + place)
    re.compile(r"\b(?:in|at|from)\s+(?:(?:the|a|an)\s+)?([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+){0,2})\b"),
]
# Words too generic to be a location title (single-word in/at anchors)
LOCATION_STOPWORDS = {
    "court", "courthouse", "office", "house", "room", "bank", "city", "park",
    "street", "road", "square", "station", "home", "bed", "car", "jail",
    "prison", "kitchen", "apartment", "hall", "building", "center", "centre",
    "town", "yard", "cell", "door", "front", "back", "top", "bottom", "side",
    "morning", "night", "day", "year", "month", "week", "june", "july", "may",
}
TITLE_ANCHOR_MAX_CHARS = 110   # only look at the paragraph lead for anchors
TITLE_SFX = {
    "typewriter": "typewriter-clicks.wav",
    "glitch": "glitch-off.wav",
    "shutter": "camera-shutter-short.wav",
    "intro": "mixkit-glitchy-cinematic-suspense-hit-679.wav",
}
# Timing contract for location/timeline titles (seconds)
TYPEWRITER_SEC = 0.7
TITLE_HOLD_SEC = 4.0
GLITCH_OFF_SEC = 0.5

# Music library - tone-tagged
MUSIC_LIBRARY = {
    "suspense": [
        "music-leberch-suspense-511168.mp3",
        "music-leberch-suspense-516354.mp3",
    ],
    "triumphant": [
        "music-kulakovka-triumphant-276654.mp3",
        "music-hot_dope-winning-elevation-111355.mp3",
        "music-paulyudin-cinematic-hero-162489.mp3",
    ],
}

# Mix levels (dB) - Joe 2026-08-12: foley -5dB, camera/chapter -4dB, music -19dB,
# key-word whoosh subtle (-8dB) so it sits over narration without masking it.
VOICE_DB = 0.0
MUSIC_DB = -10.0  # music base level; ducked to -19.5dB under voice in the mix
SFX_DB = -15.0
# Ducking (Joe 2026-08-14): the music bed is sidechain-compressed under the voice
# so it pulls down while the narrator speaks and swells back in the gaps.
DUCK_THRESHOLD = os.environ.get("DUCK_THRESHOLD", "0.05")
DUCK_RATIO = os.environ.get("DUCK_RATIO", "8")
DUCK_ATTACK = os.environ.get("DUCK_ATTACK", "20")
DUCK_RELEASE = os.environ.get("DUCK_RELEASE", "500")
# Camera shutter + chapter-card whoosh are punchy transients that need to CUT
# through (Joe: -4dB for camera AND chapter sounds).
SHUTTER_DB = -4.0
CHAPTER_DB = -4.0
# Foley bed - sits under narration (Joe 2026-08-13: ALL foley reduced to -15dB
# so it no longer masks/cuts over the voice; previously -5dB was too loud).
FOLEY_DB = -15.0
# Key-word whoosh highlight - a quick pointer, kept subtle (not specified by Joe).
KEYWORD_DB = -8.0

# MINIMAL_AUDIO (Joe 2026-08-15): strict whitelist for ALL channel audio - ONLY
# the intro sound (start of video), the custom music bed (with static fallback),
# chapter sounds, and title typewriter + glitch sounds. NO foley, NO per-shot
# LLM SFX, NO key-word whoosh, NO camera shutter / establishing sweep. This is
# the audio signature for Crayon Lore and is shared by Split Node + SN Shorts.
# Set MINIMAL_AUDIO=0 to restore the old foley/SFX layers.
MINIMAL_AUDIO = os.environ.get("MINIMAL_AUDIO", "1").strip().lower() in ("1", "true", "yes")

# Discord announcement bot
DISCORD_BOT_TOKEN = os.environ.get("DISCORD_BOT_TOKEN", "")
# Announcement channels: set via .env (DISCORD_ANNOUNCE_CHANNELS) as a
# comma-separated list of channel IDs or #names, or a single DISCORD_CHANNEL.
# Run `python discord_bot.py --setup` for a guided one-time setup.
# Fallback keeps older installs (no env set) working with the original IDs.
_DC = os.environ.get("DISCORD_ANNOUNCE_CHANNELS") or os.environ.get("DISCORD_CHANNEL")
if _DC:
    DISCORD_ANNOUNCE_CHANNELS = [c.strip() for c in _DC.split(",") if c.strip()]
else:
    DISCORD_ANNOUNCE_CHANNELS = [
        "1532603687619264512",
        "1532603486829547680",
    ]

# -- State helpers ---------------------------------------------------

def _load_used_articles() -> set:
    if USED_ARTICLES_FILE.exists():
        try:
            return set(json.loads(USED_ARTICLES_FILE.read_text()))
        except Exception:
            pass
    return set()

def _save_used_article(url: str):
    used = _load_used_articles()
    used.add(url)
    USED_ARTICLES_FILE.write_text(json.dumps(list(used), indent=2))


# Rejected-article cooldown: when the user says NO to an article it is
# recorded with a timestamp and NOT re-presented for REJECT_COOLDOWN_DAYS
# (7 by default), so it doesn't keep surfacing every run.
REJECTED_ARTICLES_FILE = PROJECT_DIR / ".rejected_articles.json"
REJECT_COOLDOWN_DAYS = float(os.environ.get("REJECT_COOLDOWN_DAYS", "7"))

def _load_rejected_articles() -> dict:
    """{url: iso timestamp} for articles the user rejected. Old entries older
    than the cooldown are pruned on load so the file stays small."""
    if REJECTED_ARTICLES_FILE.exists():
        try:
            data = json.loads(REJECTED_ARTICLES_FILE.read_text())
            if not isinstance(data, dict):
                data = {}
            cutoff = datetime.now(timezone.utc) - timedelta(days=REJECT_COOLDOWN_DAYS)
            pruned = {}
            for k, v in data.items():
                try:
                    ts = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                    if ts >= cutoff:
                        pruned[k] = v
                except Exception:
                    continue
            return pruned
        except Exception:
            pass
    return {}

def _save_rejected_article(url: str):
    rejected = _load_rejected_articles()
    rejected[url] = datetime.now(timezone.utc).isoformat()
    REJECTED_ARTICLES_FILE.write_text(json.dumps(rejected, indent=2))


# ---------------------------------------------------------------------------
# Curated seed story library (Joe 2026-08-12)
#
# The RSS/HN pools keep exhausting because they return the same lottery/loophole
# stories, which get marked used or rejected. To guarantee an UNLIMITED supply
# of REAL, on-topic stories (lottery loopholes, bank/ATM glitches, money hacks,
# advantage plays, arbitrage), the pipeline draws from a pre-verified seed
# library FIRST. Every entry in stories_seed.json is a real published story
# from a major outlet (CBS, NYT, Guardian, BBC, Vice, Bloomberg...). Add more
# verified stories to that file to grow the pool forever. Once a seed story is
# made into an episode it's added to `used` like any other, so it never repeats.
# ---------------------------------------------------------------------------
SEED_STORIES_FILE = PROJECT_DIR / "stories_seed.json"
SEED_MAX = int(os.environ.get("SEED_MAX", "0"))  # 0 = unlimited (use all not-used)

def _load_seed_stories() -> list[dict]:
    """Load the curated verified seed story library. Returns [] if missing/corrupt."""
    if not SEED_STORIES_FILE.is_file():
        return []
    try:
        data = json.loads(SEED_STORIES_FILE.read_text(encoding="utf-8"))
        return list(data.get("stories", []))
    except Exception as e:
        print(f"  [SEED] could not load {SEED_STORIES_FILE.name}: {e}")
        return []


def _seed_candidates(used: set, skip: set) -> list[dict]:
    """Seed stories not yet used/rejected, scored as high-priority money-hack
    candidates (they're verified on-topic, so they qualify regardless of the
    legacy niche keywords). Sorted so the strongest money/loophole categories
    surface first."""
    out = []
    seen_titles = set()
    for s in _load_seed_stories():
        url = (s.get("url") or "").strip()
        title = (s.get("title") or "").strip()
        if not url or not title:
            continue
        if url in used or url in skip:
            continue
        tkey = re.sub(r"[^a-z0-9]+", "", title.lower())
        if tkey and tkey in seen_titles:
            continue
        seen_titles.add(tkey)
        cat = s.get("category", "")
        cat_boost = {"lottery-loophole": 3, "bank-glitch": 3, "money-glitch": 3,
                     "casino-advantage": 2, "rewards-hack": 2, "arbitrage": 2}.get(cat, 1)
        # Seed stories are pre-verified and on-topic: give them a high base score
        # so they always outrank any weak RSS/HN hit, and flag them as MONEY-HACK.
        out.append({
            "title": title,
            "link": url,
            "description": s.get("beat", ""),
            "score": max(8, cat_boost * 4),       # niche score floor
            "hn_points": 0,
            "date": s.get("date", ""),
            "trend_rel": 0,
            "trend_term": "",
            "money_priority": 1,                   # flagship topic
            "from_seed": True,
            "category": cat,
            "final_score": round(min(50 + cat_boost * 10, 100), 1),
        })
    # Order: money/loophole/glitch categories first, then higher score.
    out.sort(key=lambda x: (x.get("category", ""), x.get("final_score", 0)),
             reverse=True)
    if SEED_MAX and SEED_MAX > 0:
        out = out[:SEED_MAX]
    return out


def _parse_item_date(it: dict) -> float:
    """Best-effort epoch timestamp for an article item (for recency sort).
    Returns 0.0 when the date is missing/unparseable (oldest bucket)."""
    d = str(it.get("date") or "").strip()
    if not d:
        return 0.0
    try:
        # HN Algolia: 2026-08-06T10:00:00.000Z ; RFC822 RSS pubDate;
        # Atom updated ISO. Try a few formats.
        candidates = [
            d.replace("Z", "+00:00"),
            d.replace(" +0000", "+00:00"),
            d.replace(" GMT", "+00:00"),
        ]
        for c in candidates:
            try:
                dt = datetime.fromisoformat(c)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.timestamp()
            except Exception:
                continue
        # RFC 2822 (e.g. "Thu, 06 Aug 2026 09:00:00 GMT")
        from email.utils import parsedate_to_datetime
        dt = parsedate_to_datetime(d)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except Exception:
        return 0.0

def _load_episode_num() -> int:
    if EPISODE_COUNTER_FILE.exists():
        try:
            return int(EPISODE_COUNTER_FILE.read_text().strip() or "0")
        except Exception:
            pass
    return 0

def _fmt_time(seconds: float) -> str:
    if seconds < 0:
        return "0:00"
    total_secs = int(round(seconds))
    mins = total_secs // 60
    secs = total_secs % 60
    if mins >= 60:
        hrs = mins // 60
        mins = mins % 60
        return f"{hrs}:{mins:02d}:{secs:02d}"
    return f"{mins}:{secs:02d}"

def _get_audio_duration(path: str) -> float:
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True, timeout=15)
        return float(r.stdout.strip())
    except Exception:
        return 0.0

# -- RSS -------------------------------------------------------------

def _fetch_rss_feed(feed_url: str) -> list[dict]:
    print(f"  [RSS] {feed_url}")
    try:
        ssl_ctx = ssl._create_unverified_context()
        req = urllib.request.Request(feed_url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })
        with urllib.request.urlopen(req, timeout=15, context=ssl_ctx) as r:
            raw = r.read()
        root = ET.fromstring(raw)
        items = []
        for item in root.iter("item"):
            title = item.findtext("title", "")
            link = item.findtext("link", "")
            desc = item.findtext("description", "")
            date = item.findtext("pubDate", "") or ""
            if title and link:
                items.append({"title": title, "link": link,
                              "description": desc, "date": date})
        if not items:
            for entry in root.iter("{http://www.w3.org/2005/Atom}entry"):
                title_el = entry.find("{http://www.w3.org/2005/Atom}title")
                link_el = entry.find("{http://www.w3.org/2005/Atom}link")
                title = title_el.text if title_el is not None else ""
                link = link_el.get("href", "") if link_el is not None else ""
                updated = entry.find("{http://www.w3.org/2005/Atom}updated")
                date = updated.text if updated is not None else ""
                if title and link:
                    items.append({"title": title, "link": link,
                                  "description": "", "date": date})
        return items
    except Exception as e:
        print(f"  [RSS] failed: {str(e)[:60]}")
        return []

def _trend_topics() -> dict:
    """Run the trend-research-toolkit topic scan (rising + under-served topics
    per category). Cached 24h (TREND_SCAN_CACHE_HOURS env). Never blocks the
    pipeline: any failure returns {} and story picking falls back to niche scoring."""
    if trend_scorer is None:
        return {}
    try:
        cache_h = int(os.environ.get("TREND_SCAN_CACHE_HOURS", "24"))
    except Exception:
        cache_h = 24
    try:
        return trend_scorer.scan_topics(creds_fn=_get_youtube_creds,
                                        cache_hours=cache_h)
    except Exception as e:
        print(f"  [TREND] topic scan failed: {e}")
        return {}


def _trend_relevance(text: str, topics: dict) -> tuple[int, str]:
    """How well a story matches the current trending topics. Returns
    (score 0-100, best matched topic term)."""
    if not topics:
        return 0, ""
    low = text.lower()
    words = set(re.findall(r"[a-z0-9']+", low))
    best = (0, "")
    for cat, t in topics.items():
        term = (t.get("term") or "").lower()
        if not term:
            continue
        tw = re.findall(r"[a-z0-9']+", term)
        if not tw:
            continue
        # multi-word term: ALL words must appear; single word: must appear
        if len(tw) == 1:
            hit = tw[0] in words
        else:
            hit = all(w in low for w in tw)
        if hit:
            score = int(t.get("score", 50) or 50)
            if score > best[0]:
                best = (score, term)
    return best


def _money_priority(text: str) -> bool:
    """True if a story is a FLAGSHIP money-hack / lottery-loophole topic.
    These are boosted ahead of every other topic in the RSS poll (Joe
    2026-08-12: money hacks / lottery loopholes = the main topic)."""
    low = text.lower()
    return any(kw in low for kw in MONEY_PRIORITY_KEYWORDS)


def _collect_candidate_stories(used: set, skip: set,
                               trend_topics: Optional[dict] = None) -> list[dict]:
    """Find niche stories. Primary: HN Algolia search (scored, curated queries).
    Fallback: RSS feed keyword scan. used = made episodes, skip = rejected this session.
    Every candidate gets trend_relevance + final_score (rising/under-served shown
    during the pick prompt). Never re-displays used or previously-rejected links."""
    matches = []
    seen_links = set()
    seen_titles = set()
    trend_topics = trend_topics or {}

    # -- Primary: curated SEED library first (Joe 2026-08-12) ----------------
    # These are pre-verified REAL stories (lottery loopholes, bank glitches,
    # money hacks, advantage plays) so they always provide a solid, on-topic
    # pool that never depends on live RSS/HN availability. They surface ahead
    # of everything else and get flagged [MONEY-HACK] in the pick prompt.
    for it in _seed_candidates(used, skip):
        seen_links.add(it["link"])
        seen_titles.add(re.sub(r"[^a-z0-9]+", "", it["title"].lower()))
        matches.append(it)
    if matches:
        print(f"  [SEED] {len(matches)} curated verified stories available")

    # -- Secondary: HN Algolia niche search --
    queries = HN_SEARCH_QUERIES[:]
    random.shuffle(queries)
    for query in queries:
        items = _fetch_hn_algolia(query)
        for it in items:
            if it["link"] in used or it["link"] in skip or it["link"] in seen_links:
                continue
            if it["score"] < 4:  # needs at least 2 strong keyword hits
                continue
            tkey = re.sub(r"[^a-z0-9]+", "", it["title"].lower())
            if tkey and tkey in seen_titles:
                continue
            seen_links.add(it["link"])
            seen_titles.add(tkey)
            trend_rel, matched_term = _trend_relevance(
                f"{it['title']} {it.get('description', '')}", trend_topics)
            it["trend_rel"] = trend_rel
            it["trend_term"] = matched_term
            it["money_priority"] = 1 if _money_priority(
                f"{it['title']} {it.get('description', '')}") else 0
            it["final_score"] = round(
                0.5 * min(it["score"] * 10, 100)
                + 0.3 * trend_rel
                + 0.2 * min(it.get("hn_points", 0), 100), 1)
            matches.append(it)
        if len(matches) >= 10:
            break
        time.sleep(0.4)

    # MONEY-HACK / lottery-loophole stories first (flagship topic), then MOST
    # RECENT, then final_score as the tiebreak. Money stories always surface
    # before hacker/tech/AI regardless of recency (Joe 2026-08-12).
    matches.sort(key=lambda x: (x.get("money_priority", 0),
                                _parse_item_date(x), x.get("final_score", 0),
                                x.get("hn_points", 0)), reverse=True)

    # -- Fallback: RSS feeds if Algolia gave nothing usable --
    if not matches:
        print("  [RSS] HN Algolia found nothing, scanning feeds...")
        feeds = RSS_FEEDS[:]
        random.shuffle(feeds)
        for feed_url in feeds:
            items = _fetch_rss_feed(feed_url)
            for it in items:
                if it["link"] in used or it["link"] in skip:
                    continue
                tkey = re.sub(r"[^a-z0-9]+", "", it["title"].lower())
                if tkey and tkey in seen_titles:
                    continue
                text = f"{it['title']} {it['description']}".lower()
                score = _story_score(it["title"], it["description"])
                # Gate (Joe 2026-08-12): accept either a strong niche-score hit
                # OR a money-hack / lottery-loophole story. Money-hack is the
                # FLAGSHIP topic now, so a story that matches the money-priority
                # keywords qualifies even if it scores low on the legacy
                # lottery/hack niche keywords (e.g. cashback / reward-point /
                # side-hustle content from the money feeds).
                is_money = _money_priority(f"{it['title']} {it['description']}")
                if score >= 3 or is_money:
                    it["score"] = max(score, 3)  # floor so money stories aren't down-weighted
                    it["hn_points"] = 0
                    trend_rel, matched_term = _trend_relevance(
                        f"{it['title']} {it['description']}", trend_topics)
                    it["trend_rel"] = trend_rel
                    it["trend_term"] = matched_term
                    it["money_priority"] = 1 if is_money else 0
                    it["final_score"] = round(
                        0.5 * min(it["score"] * 10, 100) + 0.3 * trend_rel, 1)
                    seen_titles.add(tkey)
                    matches.append(it)
            if len(matches) >= 8:
                break
            time.sleep(0.3)
        matches.sort(key=lambda x: (x.get("money_priority", 0),
                                    _parse_item_date(x),
                                    x.get("final_score", 0)), reverse=True)
    return matches


def _fetch_page_title(url: str) -> str:
    """Fetch an article's <title> tag for the custom-URL story source.
    Falls back to a URL-derived label if the fetch or title parse fails."""
    try:
        ssl_ctx = ssl._create_unverified_context()
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"})
        with urllib.request.urlopen(req, timeout=15, context=ssl_ctx) as r:
            html = r.read().decode("utf-8", errors="replace")
        m = re.search(r"<title[^>]*>(.*?)</title>", html, re.DOTALL | re.IGNORECASE)
        if m:
            t = re.sub(r"\s+", " ", m.group(1)).strip()
            if t:
                return t[:200]
    except Exception as e:
        print(f"  [URL] could not fetch title ({str(e)[:50]}) - using URL label")
    import urllib.parse as _up
    label = _up.unquote(url.rstrip("/").split("/")[-1] or url)
    label = label.replace("-", " ").replace("_", " ")
    return label[:200] or url


def _pick_story() -> tuple[str, str, list]:
    """Pick a story with user confirmation. Asks Y/n per candidate;
    re-polls RSS when the candidate pool runs out.

    Joe 2026-08-14: each candidate is PARSED (article fetched + extracted)
    BEFORE it is presented to the user. A link that fails to resolve (blocked,
    dead, paywalled, empty) is auto-skipped to the next candidate with no
    prompt - only working links are offered. Returns (url, title, paragraphs)
    on accept, or ("", "", []) on abort.

    Optionally accepts a CUSTOM article URL instead of the RSS feed: type
    'u' (or paste a URL) at the prompt and the pipeline fetches that article
    directly, skipping RSS entirely.

    Before collecting candidates, runs the trend-research-toolkit scan so each
    candidate is shown with its RISING (Google Trends) and UNDER-SERVED (YouTube
    competition) scores plus a final score. used articles are never re-displayed;
    rejected candidates are skipped for the rest of the session.
    """
    used = _load_used_articles()
    rejected = _load_rejected_articles()  # persisted: {url: ts} - 7 day cooldown
    rejected_set = set(rejected.keys())
    pool: list[dict] = []
    pool_idx = 0
    rounds = 0

    print("\n[STORY] Pick a topic source:")
    print("  [RSS]  scan feeds for a 'beat the system' story")
    print("  [URL]  enter your own article URL (skip RSS entirely)")
    src = input("  Enter a URL, or press Enter for RSS: ").strip()
    if src:
        src = src.strip().strip('"\'')
        if src.lower().startswith(("http://", "https://")):
            title = _fetch_page_title(src)
            print(f"  [URL] Using custom article: {title}")
            print(f"        {src}")
            paras = fetch_article_paragraphs(src)
            if not paras:
                print(f"  [RESOLVE] custom article did not resolve - aborting")
                return ("", "", [])
            _save_used_article(src)
            return (src, title, paras)
        print(f"  [WARN] '{src[:40]}' is not a valid http(s) URL - falling back to RSS")

    print("\n[RSS] Scraping feeds for a 'beat the system' story...")
    print("  [TREND] scanning rising + under-served topics (trend-research-toolkit)...")
    trend_topics = _trend_topics()
    pool = _collect_candidate_stories(used, rejected_set, trend_topics)
    if not pool:
        print("  [FAIL] No articles found at all")
        return ("", "", [])
    print(f"  [RSS] {len(pool)} candidate stories found\n")

    while True:
        # Pool exhausted -> re-poll RSS for fresh candidates
        if pool_idx >= len(pool):
            rounds += 1
            if rounds >= 6:
                print("  [FAIL] Ran out of stories after 6 re-polls. Try again later.")
                return ("", "", [])
            print(f"\n  [RSS] Pool exhausted ({len(pool)} candidates). Re-polling feeds...")
            time.sleep(2)
            pool = _collect_candidate_stories(used, rejected_set, trend_topics)
            pool_idx = 0
            if not pool:
                print("  [FAIL] No fresh articles found on re-poll")
                return ("", "", [])

        chosen = pool[pool_idx]
        pool_idx += 1
        # PARSE BEFORE PRESENTING (Joe 2026-08-14): auto-skip links that don't
        # resolve, only offer the user working stories.
        paras = fetch_article_paragraphs(chosen["link"])
        if not paras:
            print(f"  [AUTO-SKIP] article did not resolve (blocked/no content): "
                  f"{chosen['link'][:70]}")
            _save_rejected_article(chosen["link"])
            rejected_set.add(chosen["link"])
            continue
        print(f"  {'='*60}")
        print(f"  CANDIDATE STORY:")
        print(f"    {chosen['title']}")
        print(f"    {chosen['link']}")
        print(f"    [resolved: {len(paras)} paragraphs]")
        # Score line: niche + rising (Google Trends) + under-served (YouTube)
        fs = chosen.get("final_score")
        tr = chosen.get("trend_rel", 0)
        tt = chosen.get("trend_term", "")
        hp = chosen.get("hn_points", 0)
        tag = "[MONEY-HACK]" if chosen.get("money_priority") else "          "
        print(f"    {tag} final={fs if fs is not None else '?'} | niche={chosen.get('score', 0)*10}"
              f"/100 | rising_topic='{tt}' ({tr}/100) | hn={hp}]")
        print(f"  {'='*60}")
        resp = input("  Use this topic? (Y/n/q): ").strip().lower()
        if resp in ("q", "quit"):
            print("  [SKIP] Aborted by user")
            return ("", "", [])
        if resp in ("", "y", "yes"):
            _save_used_article(chosen["link"])
            print(f"  [OK] Story selected: {chosen['title'][:70]}")
            return (chosen["link"], chosen["title"], paras)
        # User said no - persist it so it isn't re-presented for ~1 week
        _save_rejected_article(chosen["link"])
        rejected_set.add(chosen["link"])
        print("  [NEXT] Trying another story...")


def _pick_resolvable_story() -> tuple[str, str, list]:
    """Pick a story that resolves. _pick_story now PARSES each candidate before
    presenting it and auto-skips failures, so the returned article is already
    fetched; this wrapper only enforces an overall attempt budget so a run of
    user-rejections can't spin forever. Returns (url, title, paragraphs) on
    success, or ("", "", []) on abort / total failure.
    """
    max_attempts = int(os.environ.get("STORY_RESOLVE_ATTEMPTS", "5"))
    for _attempt in range(1, max_attempts + 1):
        url, title, paras = _pick_story()
        if not url:
            return ("", "", [])
        if paras:
            print(f"  [RESOLVE] article OK ({len(paras)} paragraphs) -> {url[:70]}")
            return (url, title, paras)
        print(f"  [RESOLVE] article did not resolve (blocked / no content): {url[:70]}")
        print(f"  [RETRY] Picking a different story ({_attempt}/{max_attempts})...")
        _save_rejected_article(url)
    print(f"  [RESOLVE] Could not resolve a story after {max_attempts} attempts.")
    return ("", "", [])


# -- Article ---------------------------------------------------------

# Boilerplate / site-chrome patterns that are NOT part of the article story
JUNK_PATTERNS = [
    r'\b(cookie (policy|notice|consent|banner|preferences)|accept (all )?cookies|we use cookies)\b',
    r'\bsubscribe\b', r'\bnewsletter\b', r'\bsign\s?up\b', r'\blog\s?in\b', r'\bsign\s?in\b',
    r'\bcreate (a|an) (free )?account\b', r'\balready (have|a) (an )?account\b',
    r'\b(privacy policy|terms of (service|use|conditions))\b',
    r'\bsponsor(ed)?\s*(content|post|story)?\b', r'\badvertisement\b',
    r'\b(related (articles?|stories?|posts?|content)|you might also like|you may also like|more (from|on|like this))\b',
    r'\brecommended for you\b', r'\btrending (now|stories)?\b', r'\bmost (read|popular|viewed)\b',
    r'\bread more\b', r'\bcontinue reading\b', r'\bshare (this|the) (article|story|post)\b',
    r'\bfollow (us|her|him|them) on\b',
    r'\b(download (the|our) app|get the app|available on (ios|android|the app store|google play))\b',
    r'\b(unlimited access|digital access|subscription required|become a (member|subscriber)|already a subscriber|subscribe now)\b',
    r'\b(paywall|premium (content|article|subscriber))\b',
    r'\b(all rights reserved)\b', r'\b©\b', r'\bclick here\b',
    r'\bopens? in a new (tab|window)\b', r'\b(contact us|send us a tip|email us|feedback|corrections?)\b',
    r'\b(photo credits?|image credits?|credit:)\b', r'\b(editor\s?\'?s? note|disclosure)\b',
]

def _is_junk_paragraph(text: str) -> bool:
    """Heuristic junk filter: boilerplate, nav, promo, ads, contact noise, bylines."""
    low = text.lower()
    # Legacy hard-blockers (CSS/JS fragments + newsletter/consent noise)
    if any(skip in low for skip in [
        'url(', '.css', 'javascript', '{', ';}', 'no-repeat',
        'margin:', 'padding:', 'border:', 'width:', 'height:'
    ]):
        return True
    for pat in JUNK_PATTERNS:
        if re.search(pat, low):
            return True
    # All-caps promo line (SHOUTING AD)
    if len(text) > 40 and text == text.upper():
        return True
    # Author byline ("By John Smith") or bio ("John Smith is a reporter at X")
    if re.match(r"^[Bb]y\s+[A-Z]\.?(?:[a-zA-Z'\-\.]*\s+)?[A-Z][a-zA-Z'\-\.]*(\s+[A-Z]\.?[a-zA-Z'\-\.]*){0,4}\.?$", text):
        return True
    if re.search(r'\bis (a|an|the)?\s*(staff|senior|contributing|freelance|award-winning)?\s*(writer|reporter|journalist|editor|correspondent|columnist)\s+(at|for|with)\b', low):
        return True
    # Contact info / email addresses
    if re.search(r'\b[\w.+-]+@[\w-]+\.[\w.]+\b', text):
        return True
    # Too-short fragment (nav labels, breadcrumbs)
    if len(text) < 20:
        return True
    return False


# ---------------------------------------------------------------------------
# Narration meta-strip: LLM commentary ("Here are exactly 5 narration
# paragraphs:", "Paragraph 1:", "Narration:", "Sure, here are...") must
# never reach the script or the TTS. Hardened on the prompt side too
# (NARRATION_SYSTEM_PROMPT rule 10) - this is the belt-and-suspenders gate.
# ---------------------------------------------------------------------------
_NARRATION_META_FULL_RE = re.compile(
    r"^(?:"
    # "here are exactly 5 narration paragraphs" / "...paragraphs:" / "...paragraphs - "
    r"(?:(?:sure|okay|ok|of\s+course|certainly|absolutely|got\s+it|understood|"
    r"here\s+you\s+go|no\s+problem|right|great)[,!\s]+)?"
    r"(?:here|below|above|the\s+following|these|those)\s+(?:are|is|come|follow)"
    r"[\s\S]*?paragraphs?[\s\S]{0,40}?(?:[:-]|$)"
    r"|(?:here'?s|that'?s|it'?s)\s+(?:the\s+)?(?:narration|script|draft|story)[\s\S]*$"
    r"|(?:i'?ve|i\s+have|i'?ll|i\s+will)\s+(?:written|prepared|drafted|created|"
    r"provided|added|included|expanded)[\s\S]*$"
    r"|paragraphs?\s*\d*\s*[:-][\s\S]*$"
    r"|(?:let\s+me|now\s+(?:i|let))\s+(?:write|draft|create)\s+(?:the\s+)?"
    r"(?:narration|script|paragraph|draft)[\s\S]*$"
    r")$",
    re.IGNORECASE,
)

_NARRATION_PREFIX_RE = re.compile(
    r"^(?:"
    # "Sure, here are exactly 5 narration paragraphs: <actual content>"
    r"(?:(?:sure|okay|ok|of\s+course|certainly|absolutely|got\s+it|understood|"
    r"here\s+you\s+go|no\s+problem|right|great)[,!\s]+)?"
    r"(?:here|below|above|the\s+following|these|those)\s+(?:are|is|come|follow)"
    r"[\s\S]*?paragraphs?[\s\S]{0,40}?[:-]\s*"
    r"|(?:here'?s|that'?s|it'?s)\s+(?:the\s+)?(?:narration|script|draft|story)[\s\S]*?[:-]\s*"
    r"|(?:narration|narration\s+script|script|draft|story|response)\s*[:-]\s*"
    r"|(?:context|story\s+context|article\s+excerpt|excerpt|already\s+covered)\b[\s\S]*?[:-]\s*"
    r")",
    re.IGNORECASE,
)


_STAGE_DIR_KEYWORDS = (
    "shot", "screen", "cut ", "cut to", "camera", "glow", "close-up",
    "closeup", "close up", "interior", "exterior", "transition", "pov",
    "zoom", "pan ", "montage", "establishing", "flashback", "slow motion",
    "we see", "showing", "scan", "hover", "dolly", "tracking", "insert",
    "cutaway", "b-roll", "b roll", "the scene", "the camera", "frame",
    "freeze", "voiceover", "sfx", "though ", "but wait", "shifting",
    "fade", "dissolve", "the screen", "cutaway", "over the shoulder",
    "extreme close", "wide shot", "split screen", "title card",
)


# ---------------------------------------------------------------------------
# Narration <-> clip integrity map (Joe 2026-08-10)
# ---------------------------------------------------------------------------
# A resume gap-fill MUST NOT reuse a clip that narrates a DIFFERENT story. If
# an episode folder still holds narration_XX.wav from an earlier article (same
# episode number was reused, or a script rebuild changed the lines), reusing by
# filename alone plays stale narration over the new shots/cards/description.
# We record a short hash of each clip's SPOKEN text in a sidecar (ep_dir
# /narration_map.json) every time a clip is generated, and only reuse a clip on
# gap-fill when its recorded hash matches the shot's CURRENT narration text.
_NARRATION_MAP = "narration_map.json"


def _tts_text_normal(text: str) -> str:
    """Normalize narration for hash-matching: strip stage directions, collapse
    whitespace, lowercase. Two clips that speak the same line must hash equal."""
    t = _strip_stage_directions(text or "").strip()
    return " ".join(t.lower().split())


def _tts_map_path(ep_dir) -> Path:
    return Path(ep_dir) / _NARRATION_MAP


def _tts_map_load(ep_dir) -> dict:
    try:
        return json.loads(_tts_map_path(ep_dir).read_text(encoding="utf-8"))
    except Exception:
        return {}


def _tts_map_save(ep_dir, m: dict) -> None:
    try:
        _tts_map_path(ep_dir).write_text(json.dumps(m, indent=0))
    except Exception:
        pass


def _tts_map_record(ep_dir, nidx: int, text: str, char: bool = False) -> None:
    """Record the hash of the narration just spoken into clip nidx. The 'char'
    flag distinguishes the per-character clone variant (narration_XX_char.wav)
    from the narrator variant (narration_XX.wav)."""
    m = _tts_map_load(ep_dir)
    key = f"char_{nidx}" if char else str(nidx)
    m[key] = _tts_text_normal(text)
    _tts_map_save(ep_dir, m)


def _tts_clip_matches(ep_dir, nidx: int, text: str, char: bool = False,
                      path: Optional[str] = None) -> bool:
    """True only if a clip exists for this index AND its recorded narration
    matches the current text. Used by gap-fill to reject stale clips from a
    different story (Joe 2026-08-10)."""
    if path and (not os.path.isfile(path) or os.path.getsize(path) <= 1000):
        return False
    if not path:
        p = str(Path(ep_dir) / f"narration_{nidx:02d}{'_char' if char else ''}.wav")
        if not os.path.isfile(p) or os.path.getsize(p) <= 1000:
            return False
    m = _tts_map_load(ep_dir)
    key = f"char_{nidx}" if char else str(nidx)
    return m.get(key) == _tts_text_normal(text)


def _ensure_tts_sidecar(ep_dir) -> None:
    """Backfill the narration_map for clips already on disk when none exists
    (older episodes). Without a map we can't prove a clip matches its line, so
    we conservatively RE-SPEAK: stale narration from a previous story must
    never silently ride along on a resume. A fresh run writes the map, so this
    only affects pre-fix state files."""
    m = _tts_map_load(ep_dir)
    if m:
        return
    any_clip = any(Path(ep_dir).glob("narration_*.wav"))
    if not any_clip:
        return
    print("  [TTS] no narration_map found with existing clips - treating all "
          "clips as stale (will re-speak) to avoid stale-narration mismatch")
    _tts_map_save(ep_dir, {})



def _strip_stage_directions(text: str) -> str:
    """Remove parenthetical/bracketed stage directions the LLM sneaks into
    narration (e.g. '(Waitshifting context slightly to...)' or '[cut to
    interior of the office]').

    Only strips a (...) / [...] group when it actually reads like a direction:
    it is LONG (>=5 words) and either starts with a lowercase word or contains
    a stage-direction keyword. Short parentheticals that are real content
    (dates, names, figures like '(OTC)' or '(1992)') are always kept.
    Returns the text with those groups removed and whitespace tidied.
    """
    if not text:
        return text

    def _is_dir(m: re.Match) -> bool:
        inner = m.group(1).strip()
        if len(inner.split()) < 5:
            return False
        low = inner.lower()
        return inner[0].islower() or any(k in low for k in _STAGE_DIR_KEYWORDS)

    text = re.sub(
        r"[(\[]([^()\[\]]{0,200})[)\]]",
        lambda m: "" if _is_dir(m) else m.group(0), text)
    text = re.sub(r"\s+", " ", text).strip()
    text = text.strip(" \t,;:()[]")
    text = re.sub(r"[,;:]{1,}\s*$", "", text)      # drop dangling punctuation
    text = re.sub(r"([.!?]){2,}", r"\1", text)      # collapse ".." / "!!"
    if text and text[0].islower():
        text = text[0].upper() + text[1:]
    return text.strip()


def _strip_narration_meta(text: str) -> str:
    """Strip LLM meta-commentary so it never lands in the script or TTS.

    Order matters: glued prefixes ("Narration: December 12th, 2012...")
    are stripped FIRST so the actual content survives, then pure-meta lines
    ("Here are exactly 5 narration paragraphs") are dropped, then list
    numbering ("4. text" - small numbers only, so dates like '2012.' are
    never eaten). Chapter card lines ("Chapter 2 - Title") pass through.
    Returns "" for pure-meta, cleaned text otherwise.
    """
    text = (text or "").strip().strip('"\'`*').strip()
    if not text:
        return ""
    m = _NARRATION_PREFIX_RE.match(text)
    if m:
        text = text[m.end():].strip().strip('"\'`*').strip()
        # fragment guard: leftover label-ish fragment with no terminal
        # punctuation ("The story so far") is meta, not narration
        if text and len(text) < 40 and not re.search(r"[.!?]$", text):
            return ""
    if _NARRATION_META_FULL_RE.match(text):
        return ""
    m = re.match(r"^(\d{1,2})[.)]\s+(.+)", text)
    if m and int(m.group(1)) <= 30:
        text = m.group(2).strip()
    return _strip_stage_directions(text)

def _llm_score_batch(messages: list[dict], max_tokens: int = 300) -> str:
    """Minimal LM Studio call for relevance scoring (no stop tokens, low temp)."""
    data = json.dumps({
        "model": LLM_MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0.2,
        "stop": [],
    }).encode()
    req = urllib.request.Request(LM_STUDIO_URL, data=data,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            result = json.loads(r.read())
        return result["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"  [FILTER] LLM scoring failed: {e}")
        return ""

def _rate_paragraph_relevance(topic: str, paragraphs: list[str]) -> list[str]:
    """
    LLM rates each paragraph/segment 0-10 against the overall topic.
    Discards items scoring <= 4 (off-topic junk that slipped past the
    heuristic filter: ads, site self-promo, unrelated asides).
    Fail-open: on API/parse failure everything is kept.
    """
    if not paragraphs:
        return []
    anchor = re.sub(r'\s+', ' ', topic).strip()
    if anchor.lower().startswith('http'):
        # Bare URL is a useless anchor; use the lede paragraph instead
        anchor = re.sub(r'\s+', ' ', paragraphs[0]).strip()[:200] if paragraphs else ''
    if len(anchor) < 20:
        print("  [FILTER] Topic anchor too short, skipping LLM relevance rating")
        return paragraphs

    print(f"  [FILTER] Rating {len(paragraphs)} paragraphs/segments for relevance to topic...")
    kept = []
    BATCH = 20
    for start in range(0, len(paragraphs), BATCH):
        batch = paragraphs[start:start + BATCH]
        numbered = "\n".join(
            f"{i}. {re.sub(chr(10), ' ', p)[:400]}" for i, p in enumerate(batch, start=1)
        )
        msg = [
            {"role": "system", "content": (
                "You are a strict content relevance filter. Rate how relevant each "
                "numbered paragraph is to the TOPIC on a scale of 0 to 10.\n"
                "0-4 = off-topic junk (ads, site promos, navigation, unrelated asides, "
                "boilerplate). 5-10 = genuinely about the topic.\n"
                "Reply with EXACTLY one line per paragraph in this format: NUMBER|SCORE\n"
                "Example:\n1|8\n2|2\n3|7"
            )},
            {"role": "user", "content": f"TOPIC: {anchor}\n\n{numbered}"}
        ]
        text = _llm_score_batch(msg)
        scores = {}
        for line in text.splitlines():
            m = re.match(r'^\s*(\d{1,3})\s*[|:]\s*(\d{1,2})\s*$', line.strip())
            if m:
                idx, score = int(m.group(1)), int(m.group(2))
                if 1 <= idx <= len(batch) and 0 <= score <= 10:
                    scores[idx] = score
        for i, p in enumerate(batch, start=1):
            score = scores.get(i, 5)  # unparseable -> keep (fail-open)
            if score <= 4:
                print(f"  [FILTER] DISCARD ({score}/10): {re.sub(chr(10), ' ', p)[:80]}...")
            else:
                kept.append(p)
    print(f"  [FILTER] Kept {len(kept)}/{len(paragraphs)} paragraphs/segments")
    return kept

def fetch_article_paragraphs(url: str) -> list[str]:
    """Download a web article, extract <p> tags for clean paragraphs.

    Hardened injection: strips nav/footer/aside/script containers before
    extraction, filters boilerplate/promo junk, dedupes repeats, and caps
    the result so off-topic webpage chrome never reaches the narration LLM.
    """
    print(f"  [ARTICLE] Fetching: {url}")
    try:
        ssl_ctx = ssl._create_unverified_context()
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        })
        with urllib.request.urlopen(req, timeout=15, context=ssl_ctx) as r:
            html = r.read().decode("utf-8", errors="replace")
        # Strip non-article containers BEFORE <p> extraction (nav, footer,
        # sidebar, scripts, forms carry most of the junk that sneaks in)
        html = re.sub(
            r'<(script|style|nav|footer|header|aside|form|figure|iframe)[^>]*>.*?</\1>',
            ' ', html, flags=re.DOTALL | re.IGNORECASE
        )
        paragraphs = re.findall(r'<p[^>]*>(.*?)</p>', html, re.DOTALL | re.IGNORECASE)
        clean = []
        seen = set()
        for p in paragraphs:
            text = re.sub(r'<[^>]+>', '', p)
            text = text.strip()
            text = text.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
            text = text.replace('&quot;', '"').replace('&#39;', "'").replace('&#8217;', "'")
            text = text.replace('&nbsp;', ' ').replace('&#8211;', '-').replace('&#8212;', '--')
            text = re.sub(r'\s+', ' ', text).strip()
            if len(text) <= 100:
                continue
            if _is_junk_paragraph(text):
                continue
            # Dedupe repeated boilerplate (cookie banners, promos between paras)
            norm = re.sub(r'[^a-z0-9]+', '', text.lower())
            if norm in seen:
                continue
            seen.add(norm)
            clean.append(text)
        if clean:
            print(f"  [OK] {len(clean)} paragraphs (junk-filtered)")
            return clean[:40]  # cap so LLM relevance rating stays cheap
        body = re.search(r'<body[^>]*>(.*?)</body>', html, re.DOTALL | re.IGNORECASE)
        if body:
            text = re.sub(r'<[^>]+>', ' ', body.group(1))
            text = re.sub(r'\s+', ' ', text).strip()
            chunks = [s.strip() for s in text.split('. ') if len(s.strip()) > 100 and not _is_junk_paragraph(s.strip())]
            print(f"  [OK] Body fallback: {len(chunks)} chunks")
            return chunks[:20]
        print("  [WARN] Could not extract article")
        return []
    except Exception as e:
        print(f"  [FAIL] Fetch failed: {e}")
        return []

# -- LLM (LM Studio) -------------------------------------------------

def _llm_chat(messages: list[dict], max_tokens: int = 2000, temp: float = 0.8) -> str:
    data = json.dumps({
        "model": LLM_MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temp,
    }).encode()
    req = urllib.request.Request(LM_STUDIO_URL, data=data,
                                 headers={"Content-Type": "application/json"})
    # Bumped timeout 180s -> 420s + one retry (Joe 2026-08-16): when the codex
    # imagegen pool / upscaler is running on the SAME GPU, LM Studio inference
    # crawls and a 2000-token shot prompt can exceed 180s. A short timeout that
    # aborts mid-generation makes every shot cascade into a slow retry/fallback.
    last_err = ""
    for attempt in (1, 2):
        try:
            with urllib.request.urlopen(req, timeout=420) as r:
                result = json.loads(r.read())
            return result["choices"][0]["message"]["content"].strip()
        except Exception as e:
            last_err = str(e)
            if attempt == 1:
                print(f"  [LLM error] {e} - retrying once (GPU contention?)")
    print(f"  [LLM error] {last_err}")
    return ""


# ---------------------------------------------------------------------------
# Script-writing backend: Codex CLI (gpt-5.4) instead of LM Studio (Joe 2026-08-14)
# ---------------------------------------------------------------------------
# Joe: "have Codex do the script writing but keep all the script logic the same"
# + "codex should use the cheapest gpt model for scripts". The narration + shot
# list (the WRITING stages) route through the Codex CLI on the cheapest GPT
# model that actually works on a ChatGPT account. Tested on this box:
#   gpt-5.4        -> works (clean text on stdout)
#   gpt-5.5        -> works (default, pricier)
#   gpt-5.1 / gpt-5-mini / gpt-5.1-mini / gpt-5-nano / gpt-4o-mini
#                  -> 400 "not supported when using Codex with a ChatGPT account"
# All the script LOGIC (sentence caps, pacing, dedup, shot parsing) is unchanged;
# only the text-generation engine is swapped. Set SCRIPT_BACKEND=lmstudio to
# force the old local path, or CODEX_SCRIPT_MODEL to override the model.
CODEX_SCRIPT_MODEL = os.environ.get("CODEX_SCRIPT_MODEL", "gpt-5.4")
CODEX_SCRIPT_EFFORT = os.environ.get("CODEX_SCRIPT_EFFORT", "low")

# ---- LLM backend selection (Joe 2026-08-16) ------------------------------
# Chosen at startup via _select_llm(): either LM Studio (a loaded local model)
# or Codex (a cloud OpenAI model, listed cheapest-first). LLM_PROVIDER + the
# model drive the narration writer (_script_chat); LLM_MODEL is always a valid
# LOCAL model so the aux LM Studio calls (relevance scoring, chapter titles,
# reachability probe) keep working even when the narrative uses Codex.
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "").strip().lower()
LLM_MODEL = os.environ.get("LLM_MODEL", "").strip()
NARRATIVE_MODEL = LLM_MODEL or CODEX_SCRIPT_MODEL

# Kill-switch (Joe 2026-08-17): if the active writer backend fails N
# consecutive calls, auto-switch to the other one for the rest of the run
# instead of grinding into N x 420s timeouts.
_LLM_FAIL_STREAK = 0
_LLM_KILL_SWITCHED = False
_LLM_FAIL_LIMIT = int(os.environ.get("LLM_FAIL_LIMIT", "3"))
_LLM_FAIL_DISABLE = os.environ.get("LLM_FAIL_DISABLE", "").strip().lower() in ("1", "true", "yes")

def _llm_kill_switch_available() -> bool:
    """True when the OTHER writer backend exists and can take over."""
    if LLM_PROVIDER == "codex":
        return _codex_available() and bool(_llmstudio_loaded_models())
    return _codex_available()

def _llm_note_failure() -> None:
    global _LLM_FAIL_STREAK, _LLM_KILL_SWITCHED, LLM_PROVIDER, NARRATIVE_MODEL, CODEX_SCRIPT_MODEL
    _LLM_FAIL_STREAK += 1
    if _LLM_FAIL_DISABLE or _LLM_KILL_SWITCHED:
        return
    if _LLM_FAIL_STREAK >= _LLM_FAIL_LIMIT and _llm_kill_switch_available():
        _LLM_KILL_SWITCHED = True
        _LLM_FAIL_STREAK = 0
        _old = LLM_PROVIDER
        if LLM_PROVIDER == "codex":
            LLM_PROVIDER = "lmstudio"
            NARRATIVE_MODEL = LLM_MODEL or NARRATIVE_MODEL
            print(f"  [KILL-SWITCH] codex failed {_LLM_FAIL_LIMIT}x consecutively - "
                  f"switching the writer to LM Studio for the rest of the run"
                  f" (was {_old})")
        else:
            LLM_PROVIDER = "codex"
            NARRATIVE_MODEL = CODEX_SCRIPT_MODEL
            CODEX_SCRIPT_MODEL = NARRATIVE_MODEL
            print(f"  [KILL-SWITCH] LM Studio failed {_LLM_FAIL_LIMIT}x consecutively - "
                  f"switching the writer to codex ({CODEX_SCRIPT_MODEL}) for the "
                  f"rest of the run (was {_old})")

def _llm_note_success() -> None:
    global _LLM_FAIL_STREAK
    _LLM_FAIL_STREAK = 0

def _llm_fail_disable() -> bool:
    return _LLM_FAIL_DISABLE

def _llm_kill_switched() -> bool:
    return _LLM_KILL_SWITCHED

# Approx USD per 1M input tokens for the Codex/OpenAI models that actually work
# on a ChatGPT account (see the script-backend comment below). Used ONLY to
# sort the Codex picker cheapest-first; real billing varies.
CODEX_MODEL_CATALOG = {
    "gpt-5.4": 1.25,   # tested default
    "gpt-5.3": 1.25,
    "gpt-5.2": 1.25,
    "gpt-5":   1.25,
    "gpt-5.5": 2.50,   # pricier
}


def _lmstudio_loaded_models() -> list:
    """IDs of the models currently loaded in LM Studio (/v1/models)."""
    try:
        req = urllib.request.Request(
            "http://localhost:1234/v1/models",
            headers={"User-Agent": "splitnode/1.1"})
        with urllib.request.urlopen(req, timeout=6) as r:
            data = json.loads(r.read().decode())
        return [m.get("id", "") for m in data.get("data", []) if m.get("id")]
    except Exception:
        return []


def _select_llm() -> None:
    """Startup prompt: pick the LLM backend + model.
      1 = LM Studio (lists currently-loaded models, you pick)
      2 = Codex     (lists models sorted cheapest-first, you pick)
    LLM_PROVIDER + LLM_MODEL env vars skip the prompt (headless/cron runs)."""
    global LLM_PROVIDER, LLM_MODEL, NARRATIVE_MODEL, CODEX_SCRIPT_MODEL
    if LLM_PROVIDER and LLM_MODEL:
        if LLM_PROVIDER == "codex":
            NARRATIVE_MODEL = LLM_MODEL
            CODEX_SCRIPT_MODEL = LLM_MODEL
        else:
            NARRATIVE_MODEL = LLM_MODEL
        print(f"  [LLM] backend={LLM_PROVIDER} model={NARRATIVE_MODEL} (env)")
        return
    print("\n  Select the LLM backend for this run:")
    print("    1) LM Studio  (local - shows loaded models, you pick)")
    print("    2) Codex      (cloud OpenAI - models sorted by cheapest)")
    choice = input("  LLM backend [1/2, Enter=LM Studio]: ").strip().lower()
    if choice in ("2", "codex"):
        _select_llm_codex()
    else:
        _select_llm_lmstudio()


def _select_llm_lmstudio() -> None:
    global LLM_PROVIDER, LLM_MODEL, NARRATIVE_MODEL
    models = _lmstudio_loaded_models()
    if not models:
        print("  [LLM] LM Studio not reachable / nothing loaded on :1234")
        LLM_PROVIDER = "lmstudio"
        LLM_MODEL = LLM_MODEL or "gemma-4-e4b-uncensored-hauhaucs-aggressive"
        NARRATIVE_MODEL = LLM_MODEL
        print(f"  [LLM] defaulting to LM Studio / {LLM_MODEL}")
        return
    print("  Loaded LM Studio models:")
    for i, m in enumerate(models, 1):
        print(f"    {i}) {m}")
    idx = input(f"  Pick model [1-{len(models)}, Enter={models[0]}]: ").strip()
    try:
        LLM_MODEL = models[int(idx) - 1]
    except (ValueError, IndexError):
        LLM_MODEL = models[0]
    LLM_PROVIDER = "lmstudio"
    NARRATIVE_MODEL = LLM_MODEL
    print(f"  [LLM] LM Studio -> {LLM_MODEL}")


def _select_llm_codex() -> None:
    global LLM_PROVIDER, LLM_MODEL, NARRATIVE_MODEL, CODEX_SCRIPT_MODEL
    cat = sorted(CODEX_MODEL_CATALOG.items(), key=lambda kv: (kv[1], kv[0]))
    print("  Codex models (cheapest first):")
    for i, (m, price) in enumerate(cat, 1):
        star = "  (default)" if m == "gpt-5.4" else ""
        print(f"    {i}) {m:<10} ~${price:.2f}/1M in{star}")
    idx = input(f"  Pick model [1-{len(cat)}, Enter={cat[0][0]}]: ").strip()
    try:
        NARRATIVE_MODEL = cat[int(idx) - 1][0]
    except (ValueError, IndexError):
        NARRATIVE_MODEL = cat[0][0]
    LLM_PROVIDER = "codex"
    CODEX_SCRIPT_MODEL = NARRATIVE_MODEL
    # Keep a valid LOCAL model for the aux LM Studio calls (relevance, titles).
    if not LLM_MODEL:
        locals_ = _lmstudio_loaded_models()
        LLM_MODEL = (locals_[0] if locals_
                     else "gemma-4-e4b-uncensored-hauhaucs-aggressive")
    print(f"  [LLM] Codex -> {NARRATIVE_MODEL} (aux LM Studio -> {LLM_MODEL})")


def _codex_available() -> bool:
    return shutil.which("codex") is not None or shutil.which("codex.exe") is not None


def _codex_script_chat(messages: list[dict], max_tokens: int = 2000, temp: float = 0.8) -> str:
    """Run a script-writing prompt through the Codex CLI (gpt-5.4) and return
    the assistant text. Mirrors _llm_chat's contract (returns the text, or ''
    on failure) so callers' existing retry/fallback logic is untouched.

    The system + user messages are combined into ONE prompt and piped to codex
    on stdin via a temp file (the ep014 PowerShell arg-length fix), same as the
    image path in providers.py. We read ONLY stdout so codex's own chat framing
    never pollutes the narration/shot text.

    Per-call CODEX_HOME isolation (Joe 2026-08-16): each script call runs in
    its OWN fresh CODEX_HOME (auth.json + config.toml copied in), exactly like
    providers.py Codex.generate_image. When the imagegen pool (isolated homes)
    runs CONCURRENTLY with a script call on the SHARED ~/.codex, codex exec
    instances contend on the same session/state and script calls fail rc=1 with
    empty stdout -> they'd fall back to a GPU-starved LM Studio and time out.
    Isolation gives the script call its own state namespace so it never contends
    with the parallel imagegen calls. We also surface stderr on failure (was
    swallowed) and retry once, so a transient blip doesn't cascade into a slow
    LM Studio fallback.
    """
    if not _codex_available():
        print("  [CODEX] codex CLI not found on PATH - falling back to LM Studio")
        return ""
    sys_p = next((m.get("content", "") for m in messages
                  if m.get("role") == "system"), "")
    user_p = "\n\n".join(m.get("content", "") for m in messages
                         if m.get("role") == "user")
    prompt = f"{sys_p}\n\n{user_p}".strip() if sys_p else user_p
    if not prompt:
        return ""

    # Per-call CODEX_HOME isolation (mirrors providers.py generate_image).
    _user_home = Path.home() / ".codex"
    _home = None
    _env = dict(os.environ)
    try:
        _home = Path(tempfile.gettempdir()) / f"codex_script_home_{uuid.uuid4().hex[:12]}"
        _home.mkdir(parents=True, exist_ok=True)
        for _f in ("auth.json", "config.toml"):
            _src = _user_home / _f
            if _src.is_file():
                try:
                    shutil.copy2(_src, _home / _f)
                except Exception:
                    pass
        _env["CODEX_HOME"] = str(_home)
    except Exception:
        _home = None

    def _cleanup_home():
        if _home and _home.is_dir():
            try:
                shutil.rmtree(_home, ignore_errors=True)
            except Exception:
                pass

    _tmp = None
    try:
        _tmp = os.path.join(tempfile.gettempdir(),
                            f"codex_script_{uuid.uuid4().hex[:8]}.txt")
        with open(_tmp, "w", encoding="utf-8") as _f:
            _f.write(prompt)
    except Exception as _e:
        print(f"  [CODEX] could not write prompt temp file: {_e}")
        _cleanup_home()
        return ""
    ps_cmd = (f"Get-Content -Raw '{_tmp}' | codex exec --skip-git-repo-check "
              f"-c 'model=\"{CODEX_SCRIPT_MODEL}\"' "
              f"-c 'model_reasoning_effort=\"{CODEX_SCRIPT_EFFORT}\"'")
    cmd = ["powershell.exe", "-NoProfile", "-Command", ps_cmd]

    # One retry for a transient codex failure so we don't cascade into a slow
    # LM Studio fallback on a single blip. Timeout bumped to 420s for long shots.
    last_err = ""
    for attempt in (1, 2):
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True,
                                  timeout=420, env=_env)
        except subprocess.TimeoutExpired:
            print(f"  [CODEX] timed out writing script ({CODEX_SCRIPT_MODEL}, "
                  f"attempt {attempt}/2)")
            last_err = "timeout"
            continue
        finally:
            try:
                os.remove(_tmp)
            except Exception:
                pass
        out = (proc.stdout or "").strip()
        if proc.returncode == 0 and out:
            # Strip any markdown code fences the model may wrap the answer in.
            out = re.sub(r"^```[a-zA-Z]*\s*", "", out)
            out = re.sub(r"\s*```$", "", out).strip()
            if out:
                _cleanup_home()
                return out
            last_err = "empty output after fence strip"
        else:
            last_err = (f"rc={proc.returncode} "
                        f"err={(proc.stderr or '').strip()[:200]!r}")
        if attempt == 1:
            print(f"  [CODEX] script call failed ({last_err}) - retrying once...")
    _cleanup_home()
    print(f"  [CODEX] script call failed ({last_err}) - falling back to LM Studio")
    return ""


def _script_chat(messages: list[dict], max_tokens: int = 2000, temp: float = 0.8) -> str:
    """Script-writing LLM dispatcher. Uses the startup-selected backend
    (LLM_PROVIDER): codex -> codex exec with NARRATIVE_MODEL; lmstudio ->
    _llm_chat with LLM_MODEL. Falls back to LM Studio on any codex failure so
    a broken/throttled codex can never stall an episode."""
    global CODEX_SCRIPT_MODEL
    if LLM_PROVIDER == "codex":
        CODEX_SCRIPT_MODEL = NARRATIVE_MODEL
        t = _codex_script_chat(messages, max_tokens=max_tokens, temp=temp)
        if t:
            _llm_note_success()
            return t
    t = _llm_chat(messages, max_tokens=max_tokens, temp=temp)
    if t:
        _llm_note_success()
        return t
    _llm_note_failure()
    return ""


_SCRIPT_REACH_CACHE = None


def _codex_script_reachable() -> bool:
    """Fail-fast liveness probe for the codex script backend (Joe 2026-08-14).
    Cached once per run. A short tiny prompt on stdout means codex is up and
    gpt-5.4 is usable; any failure (not installed, rate-limited, timeout)
    returns False so the caller can warn + fall back. Fail-open on probe errors."""
    global _SCRIPT_REACH_CACHE
    if _SCRIPT_REACH_CACHE is not None:
        return _SCRIPT_REACH_CACHE
    if not _codex_available():
        _SCRIPT_REACH_CACHE = False
        return False
    try:
        import tempfile as _tf
        _tmp = os.path.join(_tf.gettempdir(),
                            f"codex_probe_{uuid.uuid4().hex[:8]}.txt")
        with open(_tmp, "w", encoding="utf-8") as _f:
            _f.write("Reply with exactly the word: PONG")
        ps_cmd = (f"Get-Content -Raw '{_tmp}' | codex exec --skip-git-repo-check "
                  f"-c 'model=\"{CODEX_SCRIPT_MODEL}\"' "
                  f"-c 'model_reasoning_effort=\"{CODEX_SCRIPT_EFFORT}\"'")
        proc = subprocess.run(["powershell.exe", "-NoProfile", "-Command", ps_cmd],
                              capture_output=True, text=True, timeout=60)
        try:
            os.remove(_tmp)
        except Exception:
            pass
        ok = proc.returncode == 0 and "PONG" in (proc.stdout or "").upper()
        _SCRIPT_REACH_CACHE = ok
        if not ok:
            print(f"  [CODEX] liveness probe failed (rc={proc.returncode}) - "
                  f"codex unavailable, falling back to LM Studio")
        return ok
    except Exception as e:
        _SCRIPT_REACH_CACHE = False
        print(f"  [CODEX] liveness probe error: {e} - falling back to LM Studio")
        return False

# -- Stage 1: Narration script ---------------------------------------

TARGET_NARRATION_PARAS = 115
# Measured narration pace for length estimates (ep8: 120 paras -> 1712.7s
# voice timeline incl. 0.3s pads between clips => ~14.3s per paragraph).
SECONDS_PER_NARRATION_PARA = 14.3
# Default requested video length in minutes (maps to ~115 paragraphs).
DEFAULT_VIDEO_MINUTES = 25
# Clamp the derived paragraph count so a bad/typo'd length can't blow up.
MIN_PARAS, MAX_PARAS = 10, 400
# Deterministic cap on sentences PER narration paragraph (Joe 2026-08-13).
# The length prompt derives the paragraph count from SECONDS_PER_NARRATION_PARA
# (measured on 2-4 sentence paragraphs), so each paragraph MUST stay within that
# range or the video balloons past the requested length. _pace_narration trims
# every paragraph to this many sentences; the writer prompt also asks for it.
SENTENCES_PER_PARAGRAPH = 4
# Cap on how many SENTENCES become shots (one shot per sentence, each with its
# own image + TTS clip). Joe 2026-08-12: EVERY flattened TTS sentence must get
# its own image - so this is set effectively UNCAPPED (matches MAX_PARAS). It
# only exists as an extreme safety bound so a runaway paragraph count can't
# balloon the episode; normal episodes (~150-190 sentences) are never trimmed,
# and the narration list, TTS worker and shot list all stay in the SAME window.
MAX_SHOTS = 400

NARRATION_SYSTEM_PROMPT = (
    "You are a documentary scriptwriter for a YouTube channel called SPLIT NODE. "
    "The channel tells true stories of ordinary people who used their skills, brains, "
    "or nerve to beat the system - hackers, lottery mathematicians, card counters, "
    "scam-baiters, people who found legal loopholes and won the game of life. "
    "Your writing style is the Black Files / FERN true-crime documentary style.\n\n"
    "STORY-FIRST PRINCIPLE (the single most important rule): this is a STORY about "
    "PEOPLE and what they DO, not a tour of places. The protagonist, their choices, "
    "their struggle and their win drive every beat. Locations are scenery - mention "
    "a place only when the action genuinely moves there and it matters to the scene. "
    "Never let place-names or geography drive the narration. If two paragraphs don't "
    "need a location sentence, neither gets one.\n\n"
    "STYLE RULES (follow ALL of them):\n"
    "1. COLD OPEN: the very first paragraph drops the viewer into a specific, "
    "visceral MOMENT IN THE ACTION - a person doing something, a decision, a risk, a "
    "discovery - one dramatic image after another. Escalate the stakes. Do NOT open "
    "with a bare location or a list of places. (The '...but the story doesn't end "
    "there' twist-tease belongs to the intro sequence only, per rule 17 - it is "
    "never repeated in body paragraphs.)\n"
    "2. SURFACE PROBLEM AND DEEPER PROBLEM: every episode has a surface problem (the "
    "mechanics - the hack, the scheme, the loophole) AND a deeper emotional struggle "
    "underneath (greed, desperation, revenge, the need to prove something, injustice). "
    "Plant the deeper problem early and pay it off at the end - the viewer should feel "
    "it subconsciously even when the story is about numbers and systems.\n"
    "3. TRANSFORMATION ARC: the protagonist must CHANGE by the end. Establish where "
    "they start (their life before) and where they end (who they became, the price "
    "paid, the person they turned into). The final paragraph should echo the opening "
    "with the transformation visible.\n"
    "4. HERO'S JOURNEY BEATS: structure the story in stages - status quo, call to "
    "adventure (the opportunity or threat that starts it), trials (the attempts, the "
    "mistakes, the close calls), crisis (the lowest point where everything nearly "
    "collapses), reward (the win), return (what happened after). Chapters follow this "
    "arc.\n"
    "5. CAUSE-AND-EFFECT CHAIN: events flow as 'this happens, but this happens, "
    "therefore this happens' - never 'and then, and then'. Every paragraph is caused "
    "by the one before it. The whole episode must read as ONE continuous story with a "
    "clear through-line - never a disconnected string of vignettes. Every paragraph "
    "advances the protagonist's story; none of them is just setting.\n"
    "6. SENTENCE RHYTHM: vary sentence length aggressively - a one-word fragment "
    "('Case closed.') next to a long flowing sentence. Monotone sentence length is "
    "death. Write to be read aloud.\n"
    "7. CONTEXT FIRST, THEN ESCALATE: open simple enough for someone who knows "
    "nothing about the topic, then raise complexity beat by beat. Never open with the "
    "most advanced concept.\n"
    "8. EXACT NUMBERS, never vague. Dollar amounts, durations, counts - always "
    "use the exact figures the ARTICLE states, never an invented or borrowed "
    "figure from a different story. Never write 'a lot of money' - always write "
    "the exact figure from the article.\n"
    "9. PLACES ARE SECONDARY: use a REAL place from THIS article (a city, town, "
    "building or landmark actually named in the article) ONLY when the scene really "
    "happens there and it adds to the story. A place is stated once when first needed "
    "and then rarely repeated. NEVER open the episode or two-or-more paragraphs in a "
    "row with a location, NEVER start consecutive paragraphs with place-names, and "
    "never import or invent a location. When nothing in a paragraph is location-bound, "
    "write it with no location at all and focus on the person and the action. Do NOT "
    "use dates.\n"
    "9b. WEAVE PEOPLE AND PLACES INTO THE ACTION (STRICT): never introduce a person "
    "or a place with a standalone label or list sentence - no 'Meet John, a hacker "
    "from New York', no 'The scene is New York.' People and places must enter the "
    "story MID-ACTION, as part of what is happening ('John cracked the vault door "
    "open', 'Rain beat against the Manhattan skyline'). Every first mention of a "
    "person or place must be doing something, not being stated.\n"
    "10. METAPHOR AND SENSORY DETAIL: concrete, original images - invent fresh "
    "metaphors for THIS story, never reuse a metaphor from a different episode.\n"
    "11. RHETORICAL QUESTIONS as pivots between beats - use them at most 2-3 "
    "times TOTAL across the whole episode, never to end consecutive paragraphs, "
    "and never more than once per chapter. Ask the viewer to figure something "
    "out instead of telling them, then pay it off a few paragraphs later.\n"
    "12. IRONY AND REVERSAL: set up the obvious reading, then flip it - the system "
    "that was supposed to stop the protagonist turned out to be the reason they "
    "won.\n"
    "13. DIRECT ADDRESS 1-2 times per episode ('Be honest. If some part of you "
    "would have done the same thing, this verdict lands closer to home than it "
    "should.').\n"
    "14. NEVER invent facts that contradict the article. Expand with cinematic framing, "
    "sensory detail and dramatic tension only.\n"
    "15. NO AI-SLOP TELLS (STRICT): never write empty negation-contrast logic like "
    "'It is not X, it is Y', 'This isn't about X, it's about Y', 'Don't be fooled, "
    "this is actually...', 'What looks like X is really Y', or any sentence that "
    "announces what something is NOT before saying what it is. Say directly what "
    "something IS. Also avoid generic filler openers ('But here's the thing', 'What "
    "you might not know', 'It turns out'). Every sentence must carry real story "
    "content.\n"
    "16. OUTPUT CONTRACT: say NOTHING except the narration itself. Never write meta "
    "text or labels - no 'Here are exactly 5 narration paragraphs', no 'Paragraph 1:', "
    "no 'Narration:', no 'Sure, here are...', no 'I've written...', no numbering, no "
    "headers, no stage directions, no intros, no summaries, no signposting of any kind. "
    "Every line you output is read ALOUD by the narrator, so a single meta word is "
    "spoken on camera. Output ONLY the raw narration paragraphs.\n"
    "17. NO REPETITIVE ENDINGS (STRICT): never end a body paragraph with a "
    "twist-tease, a reveal, or a rhetorical question. The '...but the story "
    "doesn't end there' beat is used AT MOST ONCE in the whole episode - reserved "
    "for the intro sequence only, never in body paragraphs. Do not end "
    "consecutive paragraphs the same way; vary every paragraph's final line. A "
    "body paragraph ends on the fact or the moment, not on a tease.\n\n"
    "I will give you an excerpt of a news article plus story context. Your job: EXPAND "
    "it into a gripping documentary narration. Write in the present tense, cinematic, "
    "dramatic - build suspense, then resolve triumphantly near the end. Keep the "
    "protagonist and the action at the centre of every paragraph; use locations "
    "sparingly. Every narration paragraph must be 2-4 sentences and cover a DIFFERENT "
    "beat - do not repeat ideas across paragraphs, and never repeat beats I tell you "
    "are already covered."
    "\n\n"
    "When I ask you to 'generate exactly N narration paragraphs based on this context', "
    "produce EXACTLY N paragraphs, expanding the source material with cinematic detail "
    "and drama."
)

def _narration_prompt_with_bible(base_prompt: str, bible: dict) -> str:
    """Append the locked STORY BIBLE to the narration system prompt so the
    scriptwriter follows the article's real structure and names."""
    b = bible or {}
    prot = b.get("protagonist") or {}
    hj = b.get("hero_journey") or {}
    chars = b.get("characters") or []
    char_lines = "\n".join(
        f"  - {c.get('name','?')} ({c.get('gender','?')}/{c.get('age','?')}): "
        f"{c.get('role','')}" + (f" - {c.get('relation','')}" if c.get('relation') else "")
        for c in chars[:10]) or "  - (none named - use role labels)"

    def _hj(k):
        v = hj.get(k, "")
        return v if isinstance(v, str) and v.strip() else "(n/a)"

    section = (
        "\n\n=== LOCKED STORY BIBLE (you MUST follow this; it overrides all "
        "other structure) ===\n"
        f"VISUAL HOOK (open the cold open on this, make it seen): {b.get('visual_hook','')}\n"
        f"DEEPER QUESTION (plant early, answer at the end): {b.get('deeper_question','')}\n"
        f"SURFACE PROBLEM (the mechanics): {b.get('surface_problem','')}\n"
        f"DEEPER PROBLEM (the emotional struggle underneath): {b.get('deeper_problem','')}\n"
        f"PROTAGONIST: {prot.get('name','?')} ({prot.get('role','')})\n"
        f"  before: {prot.get('transformation_start','')}\n"
        f"  after:  {prot.get('transformation_end','')}\n"
        f"HERO'S JOURNEY:\n"
        f"  status_quo:  {_hj('status_quo')}\n"
        f"  call:        {_hj('call')}\n"
        f"  assistance:  {_hj('assistance')}\n"
        f"  departure:   {_hj('departure')}\n"
        f"  trials:      {_hj('trials')}\n"
        f"  approach:    {_hj('approach')}\n"
        f"  crisis:      {_hj('crisis')}\n"
        f"  reward:      {_hj('reward')}\n"
        f"  return:      {_hj('return')}\n"
        f"  new_life:    {_hj('new_life')}\n"
        f"REAL CHARACTERS (use ONLY these exact names; never invent or import "
        f"names from other stories):\n{char_lines}\n"
        f"KEY NUMBERS (use the exact figures): {', '.join(str(x) for x in (b.get('key_numbers') or [])[:12])}\n"
        f"KEY PLACES (use only these real places): {', '.join(str(x) for x in (b.get('key_places') or [])[:12])}\n"
        "IMPORTANT: the script must open with the VISUAL HOOK in a cold open, "
        "establish the DEEPER QUESTION in the first act, escalate through the "
        "hero's journey beats in order, and resolve the transformation + "
        "deeper question in the final act. Every character must be referred to "
        "by their exact locked name. Do not add characters that are not in the "
        "REAL CHARACTERS list."
    )
    return base_prompt + section


# Pacing keywords / heuristics (deterministic - the LLM can't be trusted with
# rhythm, so we enforce it here in code).
_QUESTION_END = ("?",)
_REVEAL_OPENERS = ("but ", "except ", "however ", "then ", "suddenly ",
                   "what happened next", "that's when", "and then",
                   "the truth", "it was", "turns out", "only then")
_DROP_OPENERS = ("case closed", "game over", "it was over", "and that was it",
                 "it worked", "he won", "she won", "they won", "caught",
                 "guilty", "done", "enough", "no one", "nothing")
_MID_LEN_LO = 18   # words: too short -> merge/shorten risk
_MID_LEN_HI = 46   # words: too long -> split signal


def _sentence_words(s: str) -> int:
    return len(re.findall(r"\S+", s))


def _split_long_sentence(s: str, maxw: int = 42) -> list[str]:
    """Deterministically split an overlong sentence at a clause boundary so it
    reads as DISTINCT spoken sentences (rhythm + breathing room for the voice).

    Splits on ', ' then ' while ' then ' but ' then ' and ', choosing a boundary
    so no piece exceeds maxw words. Each piece is capitalised and terminated
    with a period so it reads as its own sentence (a comma split that stays a
    comma re-merges into the same run-on)."""
    if _sentence_words(s) <= maxw:
        return [s]
    clauses = None
    for sep in (", ", " while ", " but ", " and ", " then "):
        cand = re.split(re.escape(sep), s, flags=re.I)
        if len(cand) >= 2:
            clauses = cand
            break
    if not clauses:
        # last resort: hard cut near maxw at a word boundary
        words = s.split()
        out, cur = [], ""
        for w in words:
            if cur and _sentence_words(cur) >= maxw:
                out.append(cur)
                cur = w
            else:
                cur = (cur + " " + w).strip() if cur else w
        if cur:
            out.append(cur)
        res = []
        for i, p in enumerate(out):
            p = p.rstrip(".,;")
            if i < len(out) - 1:
                p += "."
            res.append(_cap_sentence(p))
        return res
    # rebuild greedily into <=maxw-word pieces, then make each a sentence
    out, cur = [], ""
    for cl in clauses:
        cl = cl.strip()
        if cur and _sentence_words(cur + " " + cl) > maxw:
            if cur:
                out.append(cur)
            cur = cl
        else:
            cur = (cur + " " + cl).strip() if cur else cl
    if cur:
        out.append(cur)
    res = []
    for i, p in enumerate(out):
        p = p.strip().rstrip(".,;")
        if i < len(out) - 1:
            p += "."
        res.append(_cap_sentence(p))
    return res or [s]


def _cap_sentence(s: str) -> str:
    """Capitalise the first letter of a sentence, keep the rest."""
    s = s.strip()
    if not s:
        return s
    return s[0].upper() + s[1:]


# Regexes for the AI-slop "it is not X, it is Y" negation-contrast tell. When the
# writer announces what something is NOT before saying what it is, we strip the
# empty "not X," preamble and keep the positive clause so the sentence carries
# real content. Deterministic guard that runs on every narration paragraph -
# the LLM prompt bans it (rule 15) but this catches anything that still slips
# through (Joe 2026-08-10).
_AI_SLOP_CONTRAST = [
    # "It is not X, it is Y." -> "It is Y."  /  "This isn't about X, it's about Y."
    re.compile(
        r"(?:it|this|that)\s*(?:'s|'re)?\s+(?:is\s+not|isn't|isnt|was\s+not|wasn't)\s+"
        r"(?:about\s+|really\s+|just\s+|actually\s+)?[^.,;!?]*?,\s*"
        r"(?:it|this|that|what)\s*'?s?\s+(?:about\s+|really\s+)?(?:is|was|means)\s+",
        re.I),
    # "It's not X, it's Y."  (apostrophe-compressed subject, no space before 's)
    re.compile(
        r"(?:it|this|that)'s\s+(?:not|n't)\s+"
        r"(?:about\s+|really\s+|just\s+|actually\s+)?[^.,;!?]*?,\s*"
        r"(?:it|this|that|what)\s*'?s?\s+(?:about\s+|really\s+)?(?:is|was|means)\s+",
        re.I),
    # "Not X, but Y." / "This isn't X. It's Y."
    re.compile(
        r"not\s+[^.,;!?]{1,80},\s*but\s+(?:it|this|that|really)\s+",
        re.I),
    # "Don't be fooled, this is actually..." / "What looks like X is really Y"
    re.compile(
        r"don'?t\s+be\s+fooled[^.]*?,\s*",
        re.I),
    re.compile(
        r"what\s+(?:looks?\s+like|seems?\s+like|appears\s+to\s+be)\s+[^.]*?\s+is\s+really\s+",
        re.I),
    # Generic filler openers that signal padding, not story.
    re.compile(
        r"\b(?:but\s+here's\s+the\s+thing|here's\s+the\s+thing|what\s+you\s+might\s+not\s+know|"
        r"it\s+turns\s+out|as\s+it\s+turns\s+out|the\s+truth\s+is|in\s+reality|"
        r"at\s+the\s+end\s+of\s+the\s+day)\s*[,:]?\s+",
        re.I),
]


def _purge_ai_slop(text: str) -> str:
    """Deterministically strip empty negation-contrast / filler slop from one
    narration paragraph so the spoken script never contains the AI tell.

    Only removes the empty 'not X,' preamble or filler opener, keeping the
    positive clause that follows (so content is preserved, not rewritten).
    Returns the cleaned text; paragraphs that are mostly slop are left as-is.
    """
    if not text:
        return text
    out = text
    for rx in _AI_SLOP_CONTRAST:
        out = rx.sub("", out)
    # clean up doubled spaces + leading lowercase orphan after a strip
    out = re.sub(r"\s{2,}", " ", out).strip()
    # If we chopped the very first word into a lowercase clause, re-cap it
    if out and out[0].islower():
        out = out[0].upper() + out[1:]
    return out


# ---------------------------------------------------------------------------
# Narration truncation guard (Joe 2026-08-12)
# The 4B scriptwriter occasionally hits the token cap mid-sentence, leaving a
# narration paragraph cut off mid-word (e.g. "...legal conte" or ending on a
# dangling em-dash). Those clipped paragraphs were spoken verbatim, which is
# exactly the "sentences cut off early" bug Joe heard on ep13 - even the
# individual TTS files (one per paragraph) were clipped. The keyword/plan
# feature is NOT the cause; it only extracts words AFTER the script is written.
# These helpers detect a clipped paragraph and force a clean re-write (or a
# targeted completion) so every spoken sentence plays out in its entirety.
# ---------------------------------------------------------------------------
_TRUNC_TERMINAL_RE = re.compile("[.!?\\\"'\u201d\u2019]\\s*$")
_TRUNC_DANGLE_RE = re.compile("[-\u2014\u2013]\\s*$")


def _paragraph_is_truncated(p: str) -> bool:
    """True when a narration paragraph looks cut off mid-sentence: it ends on a
    bare letter/digit (no terminal punctuation) or on a dangling em/en dash."""
    s = (p or "").strip()
    if not s:
        return False
    if _TRUNC_DANGLE_RE.search(s):
        return True
    if re.search(r"[A-Za-z0-9]\s*$", s) and not _TRUNC_TERMINAL_RE.search(s):
        return True
    return False


def _extract_first_clean_para(text: str, min_len: int = 40) -> str:
    """Pull the first usable narration paragraph out of an LLM response (the
    model occasionally wraps output in list bullets / double-blank lines)."""
    parts = [p.strip() for p in re.split(r"\n\s*\n", text or "") if p.strip()]
    if not parts and "\n" in (text or ""):
        parts = [p.strip() for p in (text or "").split("\n")
                 if len(p.strip()) > min_len]
    for p in parts:
        cand = re.sub(r"^\s*[-*#]+\s*", "", p).strip()
        cand = _strip_narration_meta(cand)
        cand = _purge_ai_slop(cand)
        if len(cand) > min_len:
            return cand
    return ""


def _complete_truncated_paragraph(para: str, sys_prompt: str,
                                  section: str, ctx: str) -> str:
    """Finish a paragraph the model cut off. Sends ONLY the clipped tail for a
    natural completion and splices it back. Returns the completed paragraph, or
    the original if completion is not reliable (better to retry the whole thing
    than to paste model-echo garbage)."""
    tail_user = (
        f"{section}\n\n"
        f"A documentary narration paragraph was cut off mid-sentence. Complete "
        f"the FINAL sentence naturally and return ONLY the finishing words - "
        f"the continuation that flows on from where it stopped. Do NOT repeat "
        f"any text already given, do NOT add a new beat, do NOT add labels, "
        f"numbering or meta. End with terminal punctuation.\n\n"
        f"TRUNCATED PARAGRAPH:\n{para}\n\n"
        f"STORY CONTEXT:\n{ctx}\n\n"
        f"Return ONLY the finishing words, for example: '...and that single "
        f"keystroke changed everything.'"
    )
    try:
        tail = _strip_narration_meta(
            _script_chat([{"role": "system", "content": sys_prompt},
                       {"role": "user", "content": tail_user}],
                      max_tokens=180, temp=0.6)).strip()
    except Exception:
        return para
    tail = re.sub(r"^[-*#.\s]+", "", tail)
    if not tail:
        return para
    # Reject model-echo (it re-printed the whole paragraph instead of the tail).
    if _norm_text(tail)[:24] and _norm_text(tail) in _norm_text(para):
        return para
    joined = re.sub(r"\s+", " ", (para.rstrip() + " " + tail).strip())
    if _paragraph_is_truncated(joined):
        return para
    if not joined.endswith(".") and not joined.endswith(("!", "?")):
        joined = joined.rstrip() + "."
    return joined


def _split_sentences(text: str) -> list[str]:
    """Split text into sentences (keep ? ! . boundaries), stripped."""
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]


def _cap_paragraph_sentences(para: str, max_sents: int = SENTENCES_PER_PARAGRAPH) -> str:
    """Deterministically trim a paragraph to at most max_sents sentences
    (Joe 2026-08-13: without a hard sentence cap each 'paragraph' written by
    the 4B model is really 4-6+ sentences, so a N-paragraph target balloons to
    a 2-3x longer video than the length prompt promised)."""
    sents = _split_sentences(re.sub(r"\s+", " ", para or "").strip())
    if len(sents) <= max_sents:
        return " ".join(sents)
    return " ".join(sents[:max_sents])


def _write_narration_block(sys_prompt: str, section: str, ctx: str, dedup: str,
                           per_para: int, max_attempts: int = 3,
                           n_sents: int = SENTENCES_PER_PARAGRAPH) -> list[str]:
    """Generate ALL the narration paragraphs for ONE article paragraph in a
    SINGLE LLM call, then split them by logic.

    Joe 2026-08-13: writing each sub-paragraph in its own call lets the model
    drift and repeat beats (especially near the end of a long video), and makes
    the paragraph count ~meaningless for length because each returned 'paragraph'
    is really several sentences. Instead we ask the model to write EXACTLY
    per_para paragraphs of AT MOST n_sents sentences each, separated by blank
    lines, in one call; we split on blank lines and enforce the sentence cap in
    code. Returns the cleaned paragraphs (already capped). n_sents defaults to
    SENTENCES_PER_PARAGRAPH and is per-article-para bounded by the caller."""
    user = (
        f"{section}\n\n"
        f"STORY CONTEXT (article excerpt):\n{ctx}\n\n"
        f"ALREADY WRITTEN in the episode (do NOT repeat these beats - advance to "
        f"NEW ones):\n{dedup}\n\n"
        f"Write EXACTLY {per_para} narration paragraph{'s' if per_para != 1 else ''} expanding THIS excerpt, "
        f"separated by a BLANK LINE. Each paragraph must be AT MOST {n_sents} "
        f"sentence{'s' if n_sents != 1 else ''} long (no more than {n_sents}, fewer is fine).\n"
        f"- {'Paragraph 1' if per_para != 1 else 'The paragraph'} covers the first beat/fact/angle of the excerpt.\n"
    )
    if per_para != 1:
        user += (
            f"- Each subsequent paragraph advances to a DIFFERENT beat, fact, angle or "
            f"cause-and-effect step - never restate, rephrase or echo paragraph 1 or "
            f"anything in ALREADY WRITTEN.\n"
        )
    user += (
        f"- Vary the sentence length; end each paragraph on a complete "
        f"sentence with terminal punctuation (never cut off or dangling).\n"
        f"Output ONLY the {per_para} paragraph{'s' if per_para != 1 else ''} separated by blank lines - nothing else."
    )
    for attempt in range(max_attempts):
        raw = _script_chat([{"role": "system", "content": sys_prompt},
                         {"role": "user", "content": user}],
                        max_tokens=600 * per_para, temp=0.85)
        blocks = [b.strip() for b in re.split(r"\n\s*\n", raw or "")
                  if b and b.strip()]
        out = []
        for b in blocks:
            b = _cap_paragraph_sentences(b, n_sents)
            if b and not _paragraph_is_truncated(b):
                out.append(b)
        if len(out) >= per_para:
            return out[:per_para]
        # Not enough usable paragraphs -> regenerate
        if attempt < max_attempts - 1:
            print(f"  [LLM] narration block short ({len(out)}/{per_para}) - "
                  f"regenerating (attempt {attempt + 2}/{max_attempts})")
            time.sleep(0.4)
    return out


def _pace_narration(paras: list[str], bible: Optional[dict] = None,
                    caps: Optional[list] = None) -> list[str]:
    """Deterministic pacing + rhythm pass on the narration.

    The LLM tends to write uniform, overlong sentences with no dramatic beats.
    We fix that here in code:
      - Split overlong sentences at clause boundaries.
      - Ensure sentence LENGTH VARIES (short beat next to long flow) - Isaac's
        'rhythm' rule.
      - Break monotone runs where 3+ consecutive sentences share a length band.
    This returns the tightened narration paragraphs. It does NOT reorder or
    invent content - it only reflows what the writer produced so the voice
    reads with natural pacing. Gaps/pauses between clips are handled in the
    audio mix stage (_pace_gaps_after), not here.
    """
    if not paras:
        return paras
    out = []
    for _pi, para in enumerate(paras):
        para = re.sub(r"\s+", " ", para).strip()
        # 1. split into sentences (keep ? ! . boundaries)
        sents = [s.strip() for s in re.split(r"(?<=[.!?])\s+", para) if s.strip()]
        # 2. reflow long sentences into shorter ones
        reflowed = []
        for s in sents:
            reflowed.extend(_split_long_sentence(s))
        sents = reflowed
        # 3. rhythm: if 3+ consecutive sentences are in the SAME length band,
        #    try to split/shorten a middle one (bump variation) - deterministic.
        bands = ["short" if _sentence_words(s) < _MID_LEN_LO else
                 ("long" if _sentence_words(s) > _MID_LEN_HI else "mid")
                 for s in sents]
        for i in range(2, len(sents)):
            if bands[i] == bands[i-1] == bands[i-2] and bands[i] == "mid":
                # split the current mid sentence to inject a short beat
                pieces = _split_long_sentence(sents[i], maxw=24)
                if len(pieces) > 1:
                    sents[i:i+1] = pieces
                    bands = ["short" if _sentence_words(x) < _MID_LEN_LO else
                             ("long" if _sentence_words(x) > _MID_LEN_HI else "mid")
                             for x in sents]
        # 4. enforce the deterministic SENTENCE CAP (Joe 2026-08-13/14): the length
        #    prompt's paragraph count assumes short paragraphs, so trim any
        #    paragraph that ran longer back to its per-paragraph cap (min of the
        #    global cap and the caller's 2-sentences-per-article-sentence cap).
        cap = caps[_pi] if caps and _pi < len(caps) else SENTENCES_PER_PARAGRAPH
        if len(sents) > cap:
            sents = sents[:cap]
        # 5. rebuild the paragraph (join with single spaces; keep sentence caps)
        out.append(" ".join(sents))
    return out


def _flatten_narration_to_sentences(narration: list[str],
                                    chapter_events: Optional[list] = None,
                                    establishing_map: Optional[dict] = None,
                                    anchor_events: Optional[list] = None
                                    ) -> tuple[list[str], dict, list, dict, list]:
    """Split every narration paragraph into its individual SENTENCES.

    Returns (sentences, sentence_para_map, chapter_events, establishing_map,
    anchor_events) where:
      - sentences: flat list of one-string-per-spoken-sentence. Chapter marker
        lines ("Chapter N - Title") and establishing lines ("Meet X." / "Evart,
        Michigan.") are already single sentences, so they pass through as-is.
      - sentence_para_map: {sentence_index: full parent paragraph text} used as
        CONTEXT when building each sentence's image prompt (Joe 2026-08-10).
      - the three event maps are REMAPPED from old paragraph indices to the new
        sentence indices so downstream chapter/establishing/anchor logic stays
        aligned.

    Each returned sentence becomes its own shot / TTS clip / image, so every
    sentence the narrator says has a matching image that stays on screen for
    exactly that sentence's TTS duration.
    """
    chapter_events = list(chapter_events or [])
    establishing_map = dict(establishing_map or {})
    anchor_events = list(anchor_events or [])
    sentences: list[str] = []
    para_map: dict[int, str] = {}
    old_to_new: dict[int, int] = {}  # old paragraph idx -> first sentence idx
    for idx, para in enumerate(narration):
        para = re.sub(r"\s+", " ", para).strip()
        if not para:
            continue
        parts = [s.strip() for s in re.split(r"(?<=[.!?])\s+", para) if s.strip()]
        # Chapter markers / establishing lines are a single line -> one sentence.
        if CHAPTER_RE.match(para) or len(parts) == 0:
            parts = [para]
        if not parts:
            continue
        first = len(sentences)
        for s in parts:
            s = _cap_sentence(s.rstrip().strip())
            if not s:
                continue
            para_map[len(sentences)] = para
            sentences.append(s)
        old_to_new[idx] = first
    if not sentences:
        return narration, {}, chapter_events, establishing_map, anchor_events
    # Remap event indices from old paragraph idx -> new sentence idx
    def _remap(i):
        return old_to_new.get(i, i)
    for ev in chapter_events:
        if "para_idx" in ev:
            ev["para_idx"] = _remap(ev["para_idx"])
    for ev in anchor_events:
        if "para_idx" in ev:
            ev["para_idx"] = _remap(ev["para_idx"])
    establishing_map = {_remap(i): m for i, m in establishing_map.items()}
    print(f"  [SENT] narration flattened: {len(narration)} paragraphs "
          f"-> {len(sentences)} sentences (one image per sentence)")
    return sentences, para_map, chapter_events, establishing_map, anchor_events


def _cap_flattened_narration(narration, sentence_para_map, chapter_events,
                             establishing_map, anchor_events,
                             max_shots: int = MAX_SHOTS):
    """Trim the flattened sentence list to MAX_SHOTS so the narration list, the
    TTS worker and the shot list all use the SAME window (Joe 2026-08-12).

    Before this, _build_shot_list stopped at MAX_SHOTS while the TTS worker
    queued a clip for EVERY flattened sentence - the episode's ending was
    silently dropped AND dozens of TTS clips were generated for sentences that
    never got a shot. Dropping events whose sentence index falls outside the
    window keeps chapter/establishing/anchor timing aligned."""
    if len(narration) <= max_shots:
        return (narration, sentence_para_map, chapter_events,
                establishing_map, anchor_events)
    n = max_shots
    dropped = len(narration) - n
    narration = narration[:n]
    sentence_para_map = {k: v for k, v in sentence_para_map.items() if k < n}
    establishing_map = {k: v for k, v in establishing_map.items() if k < n}
    chapter_events = [ev for ev in (chapter_events or [])
                      if ev.get("para_idx", -1) < n]
    anchor_events = [ev for ev in (anchor_events or [])
                     if ev.get("para_idx", -1) < n]
    print(f"  [SENT] capped narration to {n} sentences "
          f"(dropped {dropped} beyond shot cap - not spoken, no wasted TTS)")
    return (narration, sentence_para_map, chapter_events,
            establishing_map, anchor_events)


def _build_narration_script(paragraphs: list[str],
                            target_paras: int = 0,
                            bible: Optional[dict] = None) -> list[str]:
    """Stage 1: expand the article into ~target narration paragraphs.

    target_paras comes from the interactive length prompt (default
    TARGET_NARRATION_PARAS). Each article paragraph is expanded into X
    narration paragraphs where X = round(target / len(article_paragraphs)),
    so the total lands as close to the target as possible even when the
    article has fewer paragraphs.

    When a STORY BIBLE is provided (built from the article BEFORE the script),
    the bible is injected into the system prompt so every narration paragraph
    follows the locked structure: visual hook cold open, deeper question,
    surface + deeper problem, hero's journey beats, transformation arc, and
    the exact real character names from the article.
    """
    target = target_paras or TARGET_NARRATION_PARAS
    print("\n[LLM] Stage 1: writing documentary narration script...")
    n_art = max(len(paragraphs), 1)
    # Joe 2026-08-14: max 1 narration paragraph per article paragraph (no
    # expansion) so the script stays tight and never repeats beats. Each
    # paragraph is further capped at min(4, 2 x article sentences).
    per_para = 1
    print(f"  [LLM] Narration = 1 paragraph per article paragraph "
          f"({n_art} article paragraphs -> {min(n_art, len(paragraphs))} narration paragraphs)")

    # Build the bible-injected system prompt (structure the whole script follows)
    sys_prompt = NARRATION_SYSTEM_PROMPT
    if bible:
        sys_prompt = _narration_prompt_with_bible(NARRATION_SYSTEM_PROMPT, bible)

    narration_paras = []
    _caps = []  # per-paragraph sentence caps (aligned with narration_paras)
    # Rolling dedupe context (Joe 2026-08-12): we store the ACTUAL text of the
    # most recent narration paragraphs (not a label) and feed them back so the
    # model can see exactly what it already wrote and must NOT repeat it. This
    # is the key to clean 1-article-paragraph -> 2-3-narration-paragraph
    # expansion: each new sub-paragraph is generated SEQUENTIALLY with the
    # sibling paragraphs from the SAME article paragraph as explicit context,
    # so it advances to a fresh beat instead of re-stating the same one.
    covered = []  # last few narration paragraphs already written (cross-article)
    for i, _para in enumerate(paragraphs):
        lo, hi = max(i - 1, 0), min(i + 2, len(paragraphs))
        ctx = "\n\n".join(paragraphs[lo:hi])
        # POSITION-AWARE SECTION LABEL (Joe 2026-08-12): the LLM must know whether
        # it is writing the episode OPENING, BODY, or OUTRO so it follows the right
        # rules for each instead of assuming a fresh start. Classified by article
        # paragraph position (first -> opening, last -> outro), which maps 1:1 to
        # episode position because narration is expanded in article order.
        n_art = len(paragraphs)
        if i == 0:
            section = ("SECTION: EPISODE OPENING - you open the story proper, right "
                       "after the intro sequence. Cold-open into the action, plant "
                       "the deeper problem early. Do NOT use the '...but the story "
                       "doesn't end there' twist-tease - that belongs to the intro "
                       "sequence only (rule 17), never here.")
        elif i >= n_art - 1:
            section = ("SECTION: EPISODE OUTRO / FINAL PARAGRAPHS - the ending. "
                       "Resolve triumphantly, pay off the transformation and the "
                       "deeper problem, echo the opening, and END the episode cleanly "
                       "on the final fact or win. No twist-tease, no dangling "
                       "rhetorical question at the end.")
        else:
            section = ("SECTION: EPISODE BODY - the middle of the story. Develop the "
                       "action and the cause-and-effect chain. Vary every paragraph's "
                       "ending; never end consecutive paragraphs with a question or a "
                       "tease (rule 17).")
        # Generate ALL the per_para narration paragraphs for this article
        # paragraph in ONE LLM call (Joe 2026-08-13: per-paragraph calls drift
        # and repeat beats near the end of a long video, and the returned
        # 'paragraphs' balloon past the length target). The block writer asks
        # for EXACTLY per_para paragraphs of EXACTLY SENTENCES_PER_PARAGRAPH
        # sentences each and splits them on blank lines in code.
        cross = [f"- {p[:160]}" for p in covered[-3:]]
        dedup = "\n".join(cross) if cross else "None yet."
        # Cap this narration paragraph to at most 2 sentences per article
        # sentence (Joe 2026-08-14), never exceeding the global cap.
        art_sents = len(_split_sentences(re.sub(r"\s+", " ", _para or "").strip()))
        cap = min(SENTENCES_PER_PARAGRAPH, max(1, 2 * art_sents))
        block = _write_narration_block(sys_prompt, section, ctx, dedup, per_para, n_sents=cap)
        for k, p_clean in enumerate(block):
            if p_clean:
                narration_paras.append(p_clean)
                _caps.append(cap)
                print(f"  [LLM] ({i+1}/{n_art}.{k+1}/{per_para}) {p_clean[:60]}...")
        # Roll the actual text into the cross-article dedupe tail.
        covered.extend([p for p in block if p])
        covered = covered[-4:]
        time.sleep(0.3)

    if not narration_paras:
        print("  [LLM] Narration failed, using article paragraphs directly")
        narration_paras = [re.sub(r"\s+", " ", p).strip()[:500]
                           for p in paragraphs[:target]]

    # Deterministic pacing pass: enforce sentence-rhythm + tighten the script
    narration_paras = _pace_narration(narration_paras, bible, caps=_caps)

    # FACT VERIFICATION (Joe 2026-08-14): a documentary that narrates specific
    # figures is only as good as those figures. Cross-check every specific
    # number/amount/percentage/date claimed in the narration against the SOURCE
    # article text; any figure the article does NOT support is rewritten to be
    # grounded (or the claim is de-specified) so we never narrate invented data.
    if os.environ.get("FACT_CHECK", "1") == "1":
        narration_paras = _verify_narration_facts(
            narration_paras, paragraphs, sys_prompt)

    print(f"  [LLM] Narration script: {len(narration_paras)} paragraphs")
    for i, p in enumerate(narration_paras):
        print(f"    {i+1}. {p[:70]}...")
    return narration_paras


# Fact-verification (Joe 2026-08-14): never narrate a specific figure the source
# article doesn't support. Extract the numeric/currency/percentage/date claims a
# paragraph makes, check each against the article text, and if a claim is NOT
# grounded, rewrite that paragraph so every specific stays true to the source.
# Runs BEFORE narration is finalised so no fake data reaches TTS/renders.
def _extract_figure_claims(text: str) -> list[str]:
    """Pull the specific numeric claims a narration paragraph asserts: dollar
    amounts, bare figures, percentages, years/dates. Returns normalized strings."""
    claims = set()
    low = text
    for pat in [
        r"\$\s?\d[\d,]*(?:\.\d+)?\s?(?:million|billion|thousand|k|m|b)?",
        r"\d[\d,]*\s?(?:million|billion|thousand)\b",
        r"\d+(?:\.\d+)?\s?(?:percent|%|%)",
        r"\b(?:19|20)\d{2}\b",
    ]:
        for m in re.finditer(pat, low, re.I):
            claims.add(re.sub(r"\s+", " ", m.group(0)).strip().lower())
    return sorted(claims)


def _verify_narration_facts(narration_paras: list[str], source_paras: list[str],
                            sys_prompt: str) -> list[str]:
    """Cross-check narration figures against the article. Any paragraph carrying a
    specific figure the source doesn't support gets a single targeted rewrite
    (ground it to the article or drop the specificity). Returns the (possibly
    rewritten) paragraph list, unchanged in count so length logic is untouched."""
    source_low = re.sub(r"\s+", " ", " ".join(source_paras)).lower()
    out = []
    fixed = 0
    for i, para in enumerate(narration_paras):
        claims = _extract_figure_claims(para)
        bad = [c for c in claims if c not in source_low]
        if not bad:
            out.append(para)
            continue
        print(f"  [FACT-CHECK] para {i+1} claims {len(bad)} figure(s) not in article: "
              f"{', '.join(bad[:4])} - rewriting to stay grounded")
        fix = _rewrite_ungrounded_para(para, bad, source_paras, sys_prompt)
        if fix and fix != para:
            out.append(fix)
            fixed += 1
            continue
        # Rewrite failed: keep the paragraph but it may carry a soft claim -
        # better to keep the story beat than to drop the whole sentence.
        out.append(para)
    if fixed:
        print(f"  [FACT-CHECK] grounded {fixed} paragraph(s) to the source article")
    return out


def _rewrite_ungrounded_para(para: str, bad: list[str], source_paras: list[str],
                             sys_prompt: str) -> str:
    """Rewrite a narration paragraph so the specific figures it claims are either
    found in the source article or de-specified (replaced with an honest vague
    form). Returns '' on failure (caller keeps the original)."""
    src = "\n\n".join(source_paras)[:3000]
    user = (
        f"A documentary narration paragraph contains specific figure(s) that do NOT "
        f"appear in the source article and may be invented. Rewrite ONLY the affected "
        f"claims so every number/amount/percentage/date in the result IS supported by "
        f"the article, OR replace the unsupported figure with a true general statement "
        f"(e.g. 'a large sum' instead of a made-up '$2.4 million'). Keep the same length "
        f"and the same dramatic tone. Do NOT invent any new figure. Return ONLY the "
        f"rewritten paragraph, nothing else.\n\n"
        f"UNSUPPORTED FIGURES: {', '.join(bad)}\n\n"
        f"NARRATION PARAGRAPH:\n{para}\n\n"
        f"SOURCE ARTICLE:\n{src}"
    )
    try:
        text = _strip_narration_meta(
            _script_chat([{"role": "system", "content": sys_prompt},
                          {"role": "user", "content": user}],
                         max_tokens=600, temp=0.5)).strip()
    except Exception:
        return ""
    text = _cap_paragraph_sentences(text)
    # Reject model-echo / no-change and verify the rewrite actually dropped the
    # unsupported figures before accepting it.
    if not text or _norm_text(text)[:24] in _norm_text(para):
        return ""
    for c in bad:
        if c in text.lower():
            return ""  # rewrite still claims the unsupported figure -> reject
    if _paragraph_is_truncated(text):
        return ""
    return text


# ---------------------------------------------------------------------------
# Narration plan: intro hook + key words + foley (Joe 2026-08-12)
# Runs at the PARAGRAPH level BEFORE sentences are split so the ONE key sentence
# and its 2-3 key words per paragraph are picked from the full paragraph, and so
# the foley pass can see the whole paragraph's actions. The plan is persisted to
# narration_plan.json (the ledger) and mirrored onto the sentence-level shots, so
# every downstream phase (TTS, images, audio mix, burn) is fully resumable.
# Key-word whooshes + foley hit points are aligned to faster-whisper sentence /
# word timecodes inside _build_audio_mix.
# ---------------------------------------------------------------------------
PLAN_CHUNK = 8


def _norm_text(s: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace - for substring timing."""
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9' ]", " ", str(s or "").lower())).strip()


# Words that carry no punch for an on-screen key-word highlight.
_KEYWORD_STOP = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "at", "for", "with",
    "that", "this", "these", "those", "it", "its", "his", "her", "their", "they",
    "he", "she", "we", "you", "i", "from", "by", "as", "was", "were", "had", "has",
    "have", "not", "but", "so", "then", "there", "would", "could", "should", "did",
    "does", "do", "is", "are", "be", "been", "into", "out", "over", "under", "than",
    "when", "while", "after", "before", "about", "them", "him", "me", "my", "our",
    "your", "just", "only", "every", "each", "more", "most", "very", "such", "how",
    "what", "why", "who", "whose", "which", "because", "also", "still", "even",
    "though", "all", "any", "some", "no", "yes", "one", "two", "three", "where",
}


def _sanitize_key_words(key_sentence: str, raw) -> list[str]:
    """Return a 2-3 word phrase that is a CONTIGUOUS, in-order substring of the
    key sentence (Joe 2026-08-16: the key words must be words that actually
    appear NEXT TO EACH OTHER in the original sentence - not 3 words picked at
    random - so per-word whisper timing can align each one to the narration).

    Prefers the contiguous span of the sentence that covers the LLM's raw key
    words; falls back to the most informative contiguous content-word n-gram.
    Always returns the words in the exact order they appear in the sentence.
    """
    s = _norm_text(key_sentence)
    toks = re.findall(r"[a-z0-9']+", s)
    if len(toks) < 2:
        return toks[:1] if toks else []
    # Distinct raw key tokens the model flagged (stop words dropped, set).
    raw_set = set()
    for w in (raw or []):
        for t in re.findall(r"[a-z0-9']+", _norm_text(w)):
            if t and t.lower() not in _KEYWORD_STOP:
                raw_set.add(t.lower())
    n = len(toks)
    best, best_sc = None, (-1.0, -1, -1)
    for size in (2, 3):
        for i in range(n - size + 1):
            win = toks[i:i + size]
            cov = sum(1 for t in win if t.lower() in raw_set) / size
            content = sum(1 for t in win if t.lower() not in _KEYWORD_STOP)
            sc = (cov, content, size)
            if sc > best_sc:
                best_sc, best = sc, win
    return best[:3]



def _summarize_paragraphs(paragraphs: list[str]) -> list[str]:
    """One-line summary PER article paragraph (max 14 words), used as compact
    context for the intro.

    Joe 2026-08-13: the article is sent ONE paragraph at a time and each summary
    is saved, so every paragraph's single key fact is captured faithfully (a
    chunked call in one prompt makes the 4B model skip/merge paragraphs). Returns
    one summary string per input paragraph, in order.
    """
    summaries: list[str] = []
    sys_p = ("You summarize a news article for a documentary writer. I give you "
             "ONE paragraph. Output ONE short line (max 14 words) capturing the "
             "single key fact or event in that paragraph. No labels, no "
             "numbering, no bullets, no commentary.")
    for i, para in enumerate(paragraphs):
        if not para or not para.strip():
            continue
        try:
            text = _llm_chat([{"role": "system", "content": sys_p},
                              {"role": "user", "content": para.strip()}],
                             max_tokens=80, temp=0.2)
            line = re.sub(r"^[-\s]*", "", (text or "").strip())
            line = re.sub(r"^\d+\s*[:.)]\s*", "", line).strip()
            if line:
                summaries.append(line[:130])
        except Exception:
            continue
        time.sleep(0.15)
    return summaries


def _generate_intro(paragraphs: list[str]) -> tuple[list[str], dict]:
    """Write the episode intro at the END of script-writing.

    Joe 2026-08-13: the intro is ONE natural paragraph (NOT seven disjoint punchy
    sentences - those read stilted). Each article paragraph is first summarized
    one-at-a-time, then ALL the summaries are sent as context to a single intro
    call along with the intro rules, and the model writes one flowing paragraph
    that moves through the Split Node Shorts 6-phase formula naturally. The
    paragraph is later flattened into per-sentence shots; up to 2 of its
    sentences are marked KEY (with 2-3 real key words) for the whoosh + on-screen
    highlight. Returns (intro_paras, intro_plan)."""
    summaries = _summarize_paragraphs(paragraphs)
    ctx = "\n".join(f"- {s}" for s in summaries) or "(no article context)"
    sys_prompt = (
        "You write the opening INTRO paragraph of a true-crime documentary, using "
        "the viral 'Split Node Shorts' 6-phase formula. Write EXACTLY ONE flowing, "
        "natural paragraph of AT MOST 3 sentences (MANDATORY - never 4+, keep it "
        "tight, ~30-60 words total) that moves smoothly through "
        "the formula in order: HOOK (grab attention), DECLARE (a big claim + a "
        "specific REAL number from the article summary), ASSESS (why this matters), "
        "ISOLATE (the central figure or situation), PROCESS (what is happening behind "
        "it), BUILD (the stakes rising), and end on a loop-tease ('...but the story "
        "doesn't end there'). Write it as ONE continuous, natural-sounding narrative "
        "paragraph - NOT a list, NOT seven disjoint punchy beats. Vary sentence "
        "length so it reads like a narrator speaking, not staccato.\n"
        "STRICT: NO people's names, NO city/town/place names, NO brand or company "
        "names, NO dates. Use ONLY real figures from the article summaries, never "
        "invent numbers. The intro sets up the hook WITHOUT revealing the specific "
        "people or places (those enter in chapter 1). Return ONLY the paragraph text, "
        "nothing else.")
    text = _script_chat([{"role": "system", "content": sys_prompt},
                      {"role": "user", "content":
                       f"ARTICLE SUMMARY:\n{ctx}\n\nWrite the intro paragraph."}],
                     max_tokens=700, temp=0.85)
    text = re.sub(r"\s+", " ", (text or "").strip()).strip()
    if len(text) < 40:
        return [], {}
    intro_paras = [text]
    # Derive 1-2 key sentences from the paragraph's own sentences (they will
    # appear verbatim in the flattened output, so the whoosh aligns by text).
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    key_plan = {}
    candidates = sentences[1:3] if len(sentences) > 2 else sentences[:1]
    for i, s in enumerate(candidates):
        kw = _sanitize_key_words(s, re.findall(r"[A-Za-z]{3,}", s))
        if kw:
            key_plan[i] = {"key_sentence": s, "key_words": kw, "foley": []}
    return intro_paras, key_plan


def _plan_narration(narration: list[str], episode_num: int) -> dict:
    """LLM narration plan per paragraph (BEFORE sentence split): the ONE key
    sentence + its 2-3 key words, plus ALL foley (human/vehicle/object) with the
    exact trigger clause where each sound happens. Written to narration_plan.json
    (the ledger) for resumability. Returns {para_idx: {...}}."""
    plan: dict[int, dict] = {}
    sys_prompt = (
        "You are a documentary sound designer. You are given narration paragraphs. "
        "For EACH paragraph return one JSON object (in the same order) with:\n"
        "- \"key_sentence\": the ONE sentence (copied verbatim as an exact contiguous "
        "substring of the paragraph) that best captures the paragraph's punch.\n"
        "- \"key_words\": 2-3 words or short phrases that are EXACT contiguous "
        "substrings of that key_sentence - the words a viewer's eye should land on. "
        "Use the words exactly as written, no stemming or rephrasing.\n"
        "- \"foley\": an array of EVERY concrete human / vehicle / object sound the "
        "action implies (footsteps, typing, car engine, rain, door slamming, gunshot, "
        "crowd, coins, glass, phone, etc). Each item is {\"sound\": \"plain one-line "
        "description\", \"trigger\": \"the exact contiguous substring of the paragraph "
        "where that sound happens\"}. Empty array if the paragraph has no foley.\n"
        "Return ONLY a JSON object: {\"items\": [<one object per paragraph, in "
        "order>]}. No prose outside the JSON.")
    for start in range(0, len(narration), PLAN_CHUNK):
        chunk = narration[start:start + PLAN_CHUNK]
        block = "\n\n".join(f"P{j+1}: {p}" for j, p in enumerate(chunk))
        data = _backend_json(
            [{"role": "system", "content": sys_prompt},
             {"role": "user", "content":
              f"PARAGRAPHS:\n{block}\n\nReturn the plan JSON for all {len(chunk)} "
              f"paragraphs ({start+1}-{start+len(chunk)}) in order."}],
            max_tokens=4500, temp=0.3)
        items = data.get("items") if isinstance(data, dict) else None
        if not isinstance(items, list):
            items = []
        for j, para in enumerate(chunk):
            i = start + j
            entry = items[j] if j < len(items) and isinstance(items[j], dict) else {}
            foley = entry.get("foley")
            plan[i] = {
                "key_sentence": str(entry.get("key_sentence") or "").strip(),
                "key_words": _sanitize_key_words(
                    str(entry.get("key_sentence") or ""),
                    entry.get("key_words") or []),
                "foley": [f for f in (foley if isinstance(foley, list) else [])
                          if isinstance(f, dict)],
            }
        time.sleep(0.2)
    # Persist the ledger for resumability + inspection.
    try:
        PROJECT_DIR.joinpath("narration_plan.json").write_text(
            json.dumps({"episode_num": episode_num, "plan": plan}, indent=2),
            encoding="utf-8")
    except Exception:
        pass
    nkey = sum(1 for e in plan.values() if e.get("key_sentence"))
    nfoley = sum(len(e.get("foley") or []) for e in plan.values())
    print(f"  [PLAN] narration plan: {nkey} key sentences, {nfoley} foley sounds "
          f"across {len(narration)} paragraphs -> narration_plan.json")
    return plan


def _fuzzy_foley_match(phrase: str) -> Optional[str]:
    """Map an LLM foley description to a concrete SFX_LIBRARY key whose file exists.
    First tries FOLEY_MAP keyword rules (footsteps/engine/typing/rain...), then a
    token-overlap scorer over library names + descriptions. Returns None if no
    confident match."""
    if not phrase:
        return None
    p = phrase.lower()
    # 1) FOLEY_MAP keyword hit -> first existing candidate
    for keywords, candidates in FOLEY_MAP:
        if any(k in p for k in keywords):
            for c in candidates:
                if c in SFX_LIBRARY and _sfx_path(c):
                    return c
    # 2) token overlap against library names + descriptions
    pw = set(re.findall(r"[a-z']+", p))
    if not pw:
        return None
    best, bestscore = None, 0
    for name, meta in SFX_LIBRARY.items():
        if not _sfx_path(name):
            continue
        hay = ((meta.get("desc") or "") + " " + name.replace("_", " ")).lower()
        hw = set(re.findall(r"[a-z']+", hay))
        score = len(pw & hw)
        if score > bestscore:
            bestscore, best = score, name
    return best if bestscore >= 1 else None


def _apply_plan_to_shots(shots: list[dict], sentence_para_map: dict,
                         plan: dict) -> None:
    """Mirror the narration plan (key words + foley) onto the sentence-level shots.
    Matches by TEXT, so it is robust to chapter/establishing/flatten index
    remapping. Sets shot['is_key'], shot['key_words'], shot['foley']."""
    for shot in shots:
        ns = _norm_text(shot.get("narration") or "")
        shot["is_key"] = False
        shot["key_words"] = []
        shot["foley"] = []
        if not ns:
            continue
        for _pi, entry in plan.items():
            ks = _norm_text(entry.get("key_sentence") or "")
            if ks and (ks == ns or (ks in ns or ns in ks)):
                shot["is_key"] = True
                shot["key_words"] = [w for w in (entry.get("key_words") or []) if w][:3]
            for f in (entry.get("foley") or []):
                trig = _norm_text(str(f.get("trigger") or ""))
                if trig and trig in ns:
                    sfx = _fuzzy_foley_match(str(f.get("sound") or ""))
                    if sfx:
                        shot["foley"].append({"sfx": sfx, "trigger": str(f.get("trigger"))})
        seen, uniq = set(), []
        for f in shot["foley"]:
            if f["sfx"] not in seen:
                seen.add(f["sfx"])
                uniq.append(f)
        shot["foley"] = uniq


def _resolve_substring_time(narration: str, substring: str, words: list,
                            clip_start: float, clip_end: float) -> float:
    """Absolute time (s) when `substring` is spoken within a shot's clip window,
    resolved from faster-whisper word timings. Falls back to clip_start+0.2."""
    if not substring or not words:
        return clip_start + 0.2
    target = _norm_text(substring)
    if not target:
        return clip_start + 0.2
    win = [w for w in words
           if (w.get("start") or 0) >= clip_start - 0.3
           and (w.get("start") or 0) <= clip_end + 0.3]
    if not win:
        return clip_start + 0.2
    joined, starts = "", []
    for w in win:
        tok = _norm_text(w.get("word", ""))
        if not tok:
            continue
        if joined:
            joined += " "
        starts.append((len(joined), float(w.get("start") or clip_start)))
        joined += tok
    idx = joined.find(target)
    if idx < 0:
        # Word-boundary fallback: any whisper word in the window near the start
        return clip_start + 0.2
    hit = None
    for pos, st in starts:
        if pos <= idx:
            hit = st
    return hit if hit is not None else clip_start + 0.2


def _resolve_phrase_word_times(narration: str, phrase_words: list, words: list,
                               clip_start: float, clip_end: float):
    """Per-word (start,end) for a CONTIGUOUS phrase, matched in-order against
    faster-whisper word timings within the shot's clip window. Returns a list of
    {text, start, end} (absolute video seconds) or None if the phrase can't be
    found. Each word's times align to WHEN it is actually spoken (Joe 2026-08-16).
    """
    if not phrase_words or not words:
        return None
    win = [w for w in words
           if (w.get("start") or 0) >= clip_start - 0.3
           and (w.get("start") or 0) <= clip_end + 0.3]
    if not win:
        return None
    joined, starts = "", []
    for w in win:
        tok = _norm_text(w.get("word", ""))
        if not tok:
            continue
        if joined:
            joined += " "
        starts.append((len(joined), len(joined) + len(tok),
                       float(w.get("start") or clip_start),
                       float(w.get("end") or 0.0)))
        joined += tok
    phrase = _norm_text(" ".join(phrase_words))
    if not phrase or not joined:
        return None
    idx = joined.find(phrase)
    if idx < 0:
        return None
    end_idx = idx + len(phrase)
    span = [(lo, hi, st, en) for (lo, hi, st, en) in starts
            if lo < end_idx and hi > idx]
    if not span:
        return None
    s_lo, s_hi = span[0][0], span[-1][1]
    s_len = max(s_hi - s_lo, 1)
    # Cumulative character offsets of the phrase words (with single spaces).
    p_offsets, acc = [], 0
    for pw in phrase_words:
        nw = _norm_text(pw)
        p_offsets.append((acc, acc + len(nw)))
        acc += len(nw) + 1
    p_len = max(acc - 1, 1)
    out = []
    for j, (po0, po1) in enumerate(p_offsets):
        mid = s_lo + s_len * ((po0 + po1) / 2.0) / p_len
        chosen = None
        for (lo, hi, st, en) in span:
            if lo <= mid <= hi:
                chosen = (st, en)
                break
        if chosen is None:
            chosen = (span[0][2], span[0][3])
        st = chosen[0]
        en = chosen[1] if chosen[1] and chosen[1] > 0 else st + 0.4
        out.append({"text": str(phrase_words[j]), "start": round(st, 3),
                    "end": round(en, 3)})
    return out


def _build_keyword_events(shots: list[dict], words: list, clip_starts: list) -> list[dict]:
    """Build on-screen KEY-WORD highlight events (kind='keyword') for every key
    sentence. The key words are a CONTIGUOUS in-order phrase from the sentence;
    per-word whisper times are attached so the title engine animates each word
    exactly as it is spoken (Joe 2026-08-16). Only 1 key sentence per paragraph
    gets a highlight."""
    events = []
    for i, shot in enumerate(shots):
        if not shot.get("is_key") or not shot.get("key_words"):
            continue
        cs = clip_starts[i] if i < len(clip_starts) else 0.0
        ce = (clip_starts[i + 1] if i + 1 < len(clip_starts)
              else cs + _get_audio_duration(shot["tts_path"]))
        phrase_words = [w for w in (shot.get("key_words") or []) if w]
        wtimes = _resolve_phrase_word_times(shot.get("narration", ""),
                                            phrase_words, words, cs, ce)
        if not wtimes:
            # Fall back to whole-phrase start for every word.
            t = _resolve_substring_time(shot.get("narration", ""),
                                        " ".join(phrase_words), words, cs, ce)
            wtimes = [{"text": w, "start": t, "end": t + 0.4} for w in phrase_words]
        text = " ".join(phrase_words)
        events.append({"kind": "keyword",
                       "start": round(min(w["start"] for w in wtimes), 3),
                       "end": round(max(w["end"] for w in wtimes) + 0.9, 3),
                       "text": text, "words": wtimes})
    return events


CHAPTER_TARGET = 10
CHAPTER_TARGET_MINUTES = 2.5
CHAPTER_INTRO_FRAC = 0.15   # chapter 1 (cold open) gets 15% of runtime
CHAPTER_OUTRO_FRAC = 0.15   # final chapter gets 15% of runtime
WORDS_PER_SEC = 2.4         # narration pace for duration estimates


def _estimate_para_duration(para: str) -> float:
    """Narration duration estimate (seconds) from word count (~2.4 wps)."""
    words = len(re.findall(r"\S+", para))
    return max(words, 6) / WORDS_PER_SEC


def _pick_chapter_breaks(narration_paras: list[str]) -> list[int]:
    """Duration-aligned chapter breaks (0-based paragraph indices).

    Targets CHAPTER_TARGET chapters: intro 15% of runtime, outro 15%, middle
    chapters split the rest evenly. This stops one chapter from running away
    with the episode (the old LLM-picked breaks let the final chapter run
    from 7:30 to the end of the video). Returns fewer breaks if the
    narration is too short to space them out.
    """
    durs = [_estimate_para_duration(p) for p in narration_paras]
    total = sum(durs)
    if total <= 0:
        return []
    n_chap = CHAPTER_TARGET
    mid_frac = (1.0 - CHAPTER_INTRO_FRAC - CHAPTER_OUTRO_FRAC) / max(n_chap - 2, 1)
    targets = []
    for c in range(1, n_chap):  # cumulative end of chapter c
        if c == 1:
            targets.append(CHAPTER_INTRO_FRAC)
        elif c == n_chap - 1:
            targets.append(1.0 - CHAPTER_OUTRO_FRAC)
        else:
            targets.append(CHAPTER_INTRO_FRAC + (c - 1) * mid_frac)
    cum = 0.0
    cum_at = []
    for d in durs:
        cum_at.append(cum)
        cum += d
    breaks = []
    prev = -1
    min_gap = 3
    last_allowed = len(narration_paras) - min_gap
    for frac in targets:
        t = frac * total
        idx = 0
        for i, t0 in enumerate(cum_at):
            if t0 >= t:
                idx = i
                break
        else:
            idx = len(narration_paras) - 1
        idx = max(idx, prev + min_gap)
        if idx > last_allowed:
            break
        breaks.append(idx)
        prev = idx
    return breaks


CHAPTER_TITLES_PROMPT = (
    "You are a documentary editor for SPLIT NODE. Chapters open with a title "
    "card the narrator reads aloud as 'Chapter N - <Title>'.\n"
    "The chapter break paragraph numbers are ALREADY FIXED - you only write "
    "the titles.\n"
    "Write EXACTLY {n} punchy chapter titles (2-6 words each, no period), one "
    "per break, in this format:\n"
    "<paragraph_number> | <Chapter Title>\n"
    "Each title must be built from THIS article's content - a distinctive "
    "image, moment, person or idea actually in the story - never a stock or "
    "invented title. No other text."
)


def _llm_chapter_titles(narration_paras: list[str], breaks: list[int]) -> list[str]:
    """LLM writes one 2-6 word title per ALREADY-chosen chapter break.

    Returns a list parallel to breaks; empty string means the LLM skipped
    that break (caller falls back to a derived title).
    """
    numbered = "\n".join(f"{i+1}. {p[:160]}" for i, p in enumerate(narration_paras))
    break_nums = ", ".join(str(b + 1) for b in breaks)
    text = _script_chat([
        {"role": "system", "content": CHAPTER_TITLES_PROMPT.format(n=len(breaks))},
        {"role": "user", "content": (
            f"FIXED CHAPTER BREAKS (paragraph numbers): {break_nums}\n\n"
            f"NARRATION SCRIPT:\n{numbered}"
        )}
    ], max_tokens=400, temp=0.5)
    title_map = {}
    for line in text.splitlines():
        m = re.match(r"^\s*(\d{1,3})\s*[|:]\s*(.+)$", line.strip())
        if m:
            idx = int(m.group(1)) - 1
            title = re.sub(r"\s+", " ", m.group(2)).strip().strip(".\"'")
            if 2 <= len(title) <= 60:
                title_map[idx] = title
    return [title_map.get(b, "") for b in breaks]


def _inject_establishing_shots(narration_paras: list[str],
                               bible: Optional[dict] = None,
                               anchor_events: Optional[list] = None) -> tuple[list[str], dict]:
    """Mark the ESTABLISHING moment for each unique LOCATION and CHARACTER.

    Joe 2026-08-12 (ep13): we used to INSERT a synthetic bare narration line
    ("Crypto." / "Meet Thevamanogari Manivel.") right before the first mention.
    Those lines were then spoken VERBATIM by the narrator, which is exactly the
    "it's just saying the story-context words (crypto / meet character) instead
    of them coming up naturally" complaint. Rule 9b in the script prompt bans
    standalone label/list sentences, but the code was re-inserting them anyway.

    New behaviour: we do NOT insert any spoken line. Instead we mark the FIRST
    real narration paragraph that naturally mentions each location/character as
    the establishing point. The shot-list builder renders that sentence's shot
    as a wide/full establishing frame with a burned "/// NAME" typewriter label
    (camera shutter + VCR cut), while the narrator SPEAKS the real story prose -
    so the place/person enters mid-action, the way the prompt intends.

    Returns (narration_paras UNCHANGED, establishing_map) where establishing_map
    = {narration_index: {"kind": "location"|"character", "name": ...}}. Indexes
    are paragraph indexes BEFORE sentence flattening (flatten remaps them)."""
    if not narration_paras:
        return narration_paras, {}

    locations: list[str] = []
    if bible:
        for p in (bible.get("key_places") or []):
            if p and p not in locations:
                locations.append(str(p))
    if anchor_events:
        for e in anchor_events:
            t = e.get("text", "")
            if t and t not in locations:
                locations.append(str(t))

    characters: list[str] = []
    if bible:
        for c in (bible.get("characters") or []):
            if isinstance(c, dict) and c.get("name"):
                nm = str(c["name"]).strip()
                if nm and nm.upper() != "NONE" and nm not in characters:
                    characters.append(nm)

    # Map each target to the first REAL paragraph index that mentions it.
    def _first_mention(sub: str, paras: list[str]) -> int:
        low = re.sub(r"\s+", " ", sub.lower())
        toks = [t for t in low.split() if len(t) > 3]
        for i, p in enumerate(paras):
            # Skip chapter-marker lines: an establishing label on a chapter
            # title card is meaningless (the card is its own shot).
            if CHAPTER_RE.match(p):
                continue
            pl = re.sub(r"\s+", " ", p.lower())
            if toks and any(t in pl for t in toks):
                return i
            if not toks and low in pl:
                return i
        return -1

    # Cap the number of LOCATION establishing shots so an episode doesn't
    # fragment across too many places. Keep the EARLIEST-mentioned ones (the
    # most central to the story) and drop the rest. Characters are uncapped.
    MAX_ESTABLISH_LOCATIONS = 4
    if len(locations) > MAX_ESTABLISH_LOCATIONS:
        ranked = [(i, loc) for loc in locations
                  if (i := _first_mention(loc, narration_paras)) >= 0]
        ranked.sort()
        keep = {loc for _, loc in ranked[:MAX_ESTABLISH_LOCATIONS]}
        dropped = [loc for loc in locations if loc not in keep]
        locations = [loc for loc in locations if loc in keep]
        if dropped:
            print(f"  [ESTABLISH] capped locations {len(locations)} (kept "
                  f"earliest mentions); skipped: {', '.join(dropped)}")

    # Mark first-mention paragraphs; no synthetic lines are inserted.
    final_map: dict[int, dict] = {}
    for loc in locations:
        idx = _first_mention(loc, narration_paras)
        if idx < 0 or idx in final_map:
            continue
        final_map[idx] = {"kind": "location", "name": loc}
    for ch in characters:
        idx = _first_mention(ch, narration_paras)
        if idx < 0:
            # fall back to first paragraph naming a single-word token
            tok = re.search(r"[A-Za-z]{4,}", ch)
            if tok:
                idx = _first_mention(tok.group(0), narration_paras)
        if idx < 0 or idx in final_map:
            continue
        final_map[idx] = {"kind": "character", "name": ch}

    if final_map:
        print(f"  [ESTABLISH] marked {len(final_map)} establishing shots "
              f"({sum(1 for m in final_map.values() if m['kind']=='location')} loc, "
              f"{sum(1 for m in final_map.values() if m['kind']=='character')} char) "
              "at first natural mention (no synthetic spoken labels)")
    return narration_paras, final_map


def _insert_chapter_markers(narration_paras: list[str]) -> tuple[list[str], list[dict]]:
    """Split the narration into duration-aligned chapters.

    Chapter boundaries are picked by ESTIMATED RUNTIME (word count), not by
    the LLM - intro and outro chapters get 15% each, the middle chapters are
    even, and each is ~CHAPTER_TARGET_MINUTES long. The LLM only supplies the
    titles. Returns (new_narration, chapter_events) where each event is
    {chapter: n, title: str, para_idx: index of the inserted paragraph}.
    """
    if len(narration_paras) < 12:
        return narration_paras, []
    print(f"\n[CHAPTERS] Duration-aligned breaks: {CHAPTER_TARGET} chapters "
          f"x ~{CHAPTER_TARGET_MINUTES}min (intro/outro longer)...")
    try:
        breaks = _pick_chapter_breaks(narration_paras)
        if len(breaks) < 2:
            print("  [CHAPTERS] Narration too short to space chapters, skipping")
            return narration_paras, []
        titles = _llm_chapter_titles(narration_paras, breaks)
        out = list(narration_paras)
        events = []
        for n, idx in enumerate(breaks, start=1):
            title = titles[n - 1].strip() if n - 1 < len(titles) else ""
            if not title:
                words = re.findall(r"[A-Za-z0-9']+", narration_paras[idx])
                title = (" ".join(words[:3]) or f"Chapter {n}").title()
            pos = idx + (n - 1)  # earlier insertions shift indices
            out.insert(pos, f"Chapter {n} - {title}")
            events.append({"chapter": n, "title": title, "para_idx": pos})
        print("  [CHAPTERS] " + ", ".join(
            f"#{e['chapter']} '{e['title']}' @para{e['para_idx']+1}" for e in events))
        return out, events
    except Exception as e:
        print(f"  [CHAPTERS] pass failed: {e}")
        return narration_paras, []


def _extract_anchor_events(narration_paras: list[str]) -> list[dict]:
    """Find location (red) anchors in paragraph leads.

    Each event: {kind: 'location', text, para_idx, anchor_words}.
    anchor_words are the whisper search words used to pin the exact read time.
    Timeline/date anchors were removed from the pipeline (Aug 2026).
    """
    events = []
    for i, para in enumerate(narration_paras):
        if CHAPTER_RE.match(para):
            continue
        lead = para[:TITLE_ANCHOR_MAX_CHARS]
        # --- location: comma-pair first, then in/at + place ---
        location = None
        m_loc = LOCATION_PATTERNS[0].search(lead)
        if m_loc:
            location = (m_loc.group(1) + ", " + m_loc.group(2)).strip()
        else:
            m_in = LOCATION_PATTERNS[1].search(lead)
            if m_in:
                place = m_in.group(1)
                if place.lower() not in LOCATION_STOPWORDS and len(place) >= 3:
                    location = place.strip()
        if location:
            words = re.findall(r"[A-Za-z']+", location.lower())
            events.append({
                "kind": "location", "text": location, "para_idx": i,
                "anchor_words": words[:2] if words else [location.lower()],
            })
    if events:
        kinds = {}
        for e in events:
            kinds[e["kind"]] = kinds.get(e["kind"], 0) + 1
        print(f"  [TITLES] anchors found: " +
              ", ".join(f"{k}={v}" for k, v in kinds.items()))
        for e in events:
            print(f"    {e['kind']:8s} para {e['para_idx']+1:3d}  '{e['text']}'")
    return events


def _build_person_events(shots: list[dict], clip_starts: list[float]) -> list[dict]:
    """First on-screen appearance of each canonical character -> a bottom-left
    PERSON typewriter title (gold). Fires at the exact moment the name is first
    spoken (whisper-matched, scoped to the character's first shot onward so an
    earlier passing mention doesn't steal the title).

    Joe 2026-08-13: names are parsed + cleaned through _parse_shot_characters /
    _clean_character_field, so a polluted 'ION CECAN, NONE' never shows as
    '(name), none' on the card and a multi-person shot emits one title per real
    person."""
    canon = _character_canonical_map(shots)
    seen = set()
    events = []
    for pos, shot in enumerate(shots):
        if shot.get("is_chapter"):
            continue
        for ch in _parse_shot_characters(shot):
            name = canon.get(ch["name"], ch["name"])
            key = _norm_char_name(name)[0]
            if not key or key in seen:
                continue
            seen.add(key)
            # all-caps spellings (e.g. the LLM wrote 'STEFAN MANDEL') display as
            # proper case on the card; genuine mixed-case names are left alone.
            display = name.title() if name.isupper() else name
            nidx = shot.get("narration_idx", pos)
            start = clip_starts[pos] if pos < len(clip_starts) else 0.0
            words = re.findall(r"[A-Za-z']+", display)
            events.append({
                "kind": "person",
                "text": display,
                "para_idx": nidx,
                "search_from": start,
                "anchor_words": words[:2] if words else [display.lower()],
            })
    if events:
        print("  [TITLES] person titles (first appearance): " +
              ", ".join(e["text"] for e in events))
    return events


def _resolve_anchor_times(events: list[dict], words: list[dict],
                          clip_starts: list[float]) -> list[dict]:
    """Pin each anchor to the exact moment the narrator reads it.

    words: faster-whisper word timings [{word, start, end}] over the voice track.
    clip_starts[i]: absolute start time of paragraph i in the voice/video timeline.
    Falls back to clip_start + 0.4 when the phrase isn't found.
    """
    resolved = []
    for ev in events:
        pi = ev["para_idx"]
        fallback = (clip_starts[pi] + 0.4) if pi < len(clip_starts) else 0.0
        t = None
        anchor = [w.lower() for w in ev.get("anchor_words", []) if w]
        if anchor and words:
            # person titles: only match from the character's first shot onward
            # (their name may be mentioned earlier in the narration)
            search_from = ev.get("search_from")
            # find first word, then the rest within a 7-word window
            for i, w in enumerate(words):
                if search_from is not None and w["start"] < search_from - 0.8:
                    continue
                wl = w["word"].strip(".,!?;:()\"'").lower()
                if wl != anchor[0]:
                    continue
                if len(anchor) == 1:
                    t = w["start"]
                    break
                window = words[i + 1:i + 7]
                j = 0
                for w2 in window:
                    w2l = w2["word"].strip(".,!?;:()\"'").lower()
                    if w2l == anchor[j + 1]:
                        j += 1
                        if j == len(anchor) - 1:
                            t = w["start"]
                            break
                if t is not None:
                    break
        if t is None:
            t = fallback
        ev = dict(ev)
        ev["start"] = round(t, 3)
        resolved.append(ev)
    return resolved


def _build_establishing_events(shots: list[dict],
                               clip_starts: list[float]) -> list[dict]:
    """A burned '/// NAME' typewriter label for EVERY establishing shot.

    Shots render CLEAN (no baked text); FFmpeg burns the label (Myriad Pro
    Bold) over each establishing frame at render time. Uses the shot's own clip
    start so the label appears right as the establishing shot cuts in.
    (Joe 2026-08-09: labels moved out of the image into the FFmpeg burn.)
    """
    events = []
    for pos, shot in enumerate(shots):
        if not shot.get("is_establishing"):
            continue
        name = (shot.get("establishing_name") or "").strip()
        if not name:
            continue
        kind = ("location" if shot.get("establishing_kind") == "location"
                else "person")
        nidx = shot.get("narration_idx", pos)
        start = clip_starts[pos] if pos < len(clip_starts) else 0.0
        events.append({
            "kind": kind,
            "text": f"/// {name}",
            "para_idx": nidx,
            "start": round(start + 0.4, 3),
        })
    return events


def _merge_establishing_titles(title_events: list[dict],
                               establishing_events: list[dict]) -> list[dict]:
    """Merge dedicated establishing labels into the resolved title events,
    replacing any existing location/person event that targets an establishing
    shot so the '/// NAME' label is burned exactly once per establishing frame.
    """
    if not establishing_events:
        return title_events
    estab_paras = {e["para_idx"] for e in establishing_events}
    kept = [ev for ev in title_events
            if ev.get("kind") == "chapter"
            or ev.get("para_idx") not in estab_paras]
    return kept + establishing_events

# -- Director's bible, scene board, episode context, templates ----------
# (Added Aug 2026: pre-visual planning stages so the pipeline works for ANY
# topic/environment/location and every episode gets a locked story + look.)

VOICE_MAP_FILE = PROJECT_DIR / "voice_map.json"
TEMPLATES_DIR = PROJECT_DIR / "templates"
EPISODE_TEMPLATE_FILE = TEMPLATES_DIR / "last_episode.json"


def _load_voice_map() -> dict:
    if VOICE_MAP_FILE.is_file():
        try:
            return json.loads(VOICE_MAP_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _lookup_voice(character: str) -> Optional[str]:
    """voice_map.json: canonical character name -> clone wav (relative to the
    project). Falls back to the narrator voice when no clone exists."""
    if not character or character == "NONE":
        return None
    vm = _load_voice_map()
    for k, v in vm.items():
        if k.lower() == character.lower():
            p = Path(v)
            if not p.is_absolute():
                p = PROJECT_DIR / p
            return str(p) if p.is_file() else None
    return None


def _llm_json(messages: list[dict], max_tokens: int = 1200, temp: float = 0.5) -> dict:
    """LLM call returning a JSON object (tolerant of code fences / prose)."""
    text = _llm_chat(messages, max_tokens=max_tokens, temp=temp)
    text = re.sub(r"```(?:json)?", "", text).strip()
    m = re.search(r"\{.*\}", text, re.S)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            pass
    return {}

def _script_json(messages: list[dict], max_tokens: int = 1200, temp: float = 0.5) -> dict:
    """JSON LLM call routed through the selected SCRIPT backend (codex when
    LLM_PROVIDER == 'codex', else LM Studio). Same tolerant extraction as
    _llm_json. The narration-plan phase used to hard-wire _llm_json (LM
    Studio only), which serialized the whole run into 420s timeouts when
    LM Studio was busy during imagegen - routing it through the writer
    backend keeps it on the same fast path as the shots."""
    text = _script_chat(messages, max_tokens=max_tokens, temp=temp)
    text = re.sub(r"```(?:json)?", "", text).strip()
    m2 = re.search(r"\{.*\}", text, re.S)
    if m2:
        try:
            return json.loads(m2.group(0))
        except Exception:
            pass
    return {}


def _backend_json(messages: list[dict], max_tokens: int = 1200, temp: float = 0.5) -> dict:
    """JSON LLM call that follows the run's writer backend: codex when selected
    (PLAN_BACKEND=lmstudio forces LM Studio), else LM Studio."""
    if LLM_PROVIDER == "codex" and \
            os.environ.get("PLAN_BACKEND", "auto").strip().lower() != "lmstudio":
        return _script_json(messages, max_tokens=max_tokens, temp=temp)
    return _llm_json(messages, max_tokens=max_tokens, temp=temp)


# -- LLM prompt relevance gate (Joe 2026-08-09) -----------------------
# Current article topic, set right before image generation so every shot and
# chapter-card prompt is cross-checked against the STORY. Stops the image model
# drifting to off-topic content (e.g. a random Mayan pyramid). Empty = gate off.
_IMG_TOPIC = ""
_SHOT_RELEVANCE_RETRIES = int(os.environ.get("SHOT_RELEVANCE_RETRIES", "2"))
# Master toggle: SHOT_RELEVANCE=0 disables the gate entirely (Joe 2026-08-09).
_SHOT_RELEVANCE_ON = os.environ.get("SHOT_RELEVANCE", "1").strip().lower() not in (
    "0", "false", "no", "off")
# Cached fast-probe of LM Studio reachability so the gate fail-opens instantly
# instead of hanging on a 180s per-call timeout when the server is busy/down.
_LLM_REACHABLE = None


def _llm_fast_reachable() -> bool:
    global _LLM_REACHABLE
    if _LLM_REACHABLE is not None:
        return _LLM_REACHABLE
    # Probe the CHAT endpoint (NOT /v1/models) with a short timeout: /v1/models
    # can still respond while inference is dead/hung, which would let the gate
    # block on a 180s per-call timeout. A tiny chat call is the real liveness test.
    _model = LLM_MODEL
    _payload = {"model": _model,
                "messages": [{"role": "user", "content": "hi"}],
                "max_tokens": 2, "temperature": 0.1}
    try:
        _req = urllib.request.Request(LM_STUDIO_URL, data=json.dumps(_payload).encode(),
                                      headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(_req, timeout=8) as _r:
            _LLM_REACHABLE = _r.status == 200
    except Exception:
        _LLM_REACHABLE = False
    if not _LLM_REACHABLE:
        print("  [RELEVANCE] LM Studio inference unreachable (chat probe timed out) - "
              "relevance gate OFF (all prompts pass through)")
    return _LLM_REACHABLE


def _set_img_topic(topic: str) -> None:
    global _IMG_TOPIC
    _IMG_TOPIC = (topic or "").strip()


def _llm_judge_prompt_relevance(prompt: str, narration: str,
                                topic: str = None) -> tuple:
    """Judge whether an image prompt is relevant to the article topic.
    Returns (relevant, note). Fail-open (True, '') when no topic, gate off,
    LM Studio unreachable, or on error. `topic` defaults to the module topic."""
    if not topic:
        topic = _IMG_TOPIC
    if not _SHOT_RELEVANCE_ON or not topic or not _llm_fast_reachable():
        return True, ""
    try:
        sys = (
            "You are a documentary image director. Given an ARTICLE TOPIC, the "
            "NARRATION line being shown, and an IMAGE PROMPT about to go to an "
            "AI image generator, judge whether the prompt is RELEVANT to the "
            "story. RELEVANT = the scene, setting, objects and people plausibly "
            "belong to this article and illustrate the narration. IRRELEVANT = it "
            "drifts to an unrelated subject with nothing to do with the story "
            "(an unrelated building, landscape, person or topic not in the "
            "article). "
            'Reply ONLY as JSON: {"relevant": true|false, "note": "<if '
            'irrelevant, one short sentence saying what is wrong and what the '
            'scene SHOULD be>"}. No markdown.'
        )
        data = _llm_json([
            {"role": "system", "content": sys},
            {"role": "user", "content":
                f"ARTICLE TOPIC: {topic}\n\n"
                f"NARRATION: {narration}\n\n"
                f"IMAGE PROMPT: {prompt}\n"},
        ], max_tokens=160, temp=0.1)
        if not isinstance(data, dict) or "relevant" not in data:
            return True, ""
        return bool(data.get("relevant")), str(data.get("note", "")).strip()
    except Exception as e:
        print(f"  [RELEVANCE] judge failed ({str(e)[:60]}) - accepting prompt")
        return True, ""


def _llm_rewrite_scene(narration: str, old_scene: str, note: str,
                       topic: str = None) -> str:
    """Rewrite a shot's scene so it directly illustrates the narration and stays
    on-topic with the article. Returns new scene text or '' on failure."""
    if not topic:
        topic = _IMG_TOPIC
    try:
        sys = (
            "You are a documentary scene director. Given the ARTICLE TOPIC, the "
            "NARRATION being shown, and a note about why the previous scene was "
            "irrelevant, write ONE new cinematic scene description (1-3 sentences) "
            "that DIRECTLY illustrates the narration and belongs to this story. "
            "Include concrete setting, key objects and what is happening. No camera "
            "framing, no shot type, no character names. Reply with ONLY the scene "
            "text."
        )
        out = _llm_chat([
            {"role": "system", "content": sys},
            {"role": "user", "content":
                f"ARTICLE TOPIC: {topic}\n\n"
                f"NARRATION: {narration}\n\n"
                f"PREVIOUS SCENE (irrelevant): {old_scene}\n\n"
                f"PROBLEM: {note}\n\nNEW SCENE:"},
        ], max_tokens=160, temp=0.6).strip()
        out = re.sub(r"\s+", " ", out).strip(" '\"")
        return out if len(out) >= 8 else ""
    except Exception:
        return ""


def _ensure_shot_prompt_relevant(prompt: str, shot: dict,
                                 character_sheets: Optional[dict],
                                 lock, topic: str = None) -> str:
    """Relevance-gate a shot prompt against the article topic. If the prompt
    drifts off-topic, rewrite the shot's scene and rebuild up to N retries.
    Fail-open (returns the prompt unchanged) when no topic or LLM errors."""
    if not topic:
        topic = _IMG_TOPIC
    for attempt in range(1, _SHOT_RELEVANCE_RETRIES + 1):
        relevant, note = _llm_judge_prompt_relevance(
            prompt, shot.get("narration", ""), topic)
        if relevant:
            return prompt
        _log = f"[RELEVANCE] shot miss ({attempt}/{_SHOT_RELEVANCE_RETRIES}): {note}"
        if lock:
            with lock:
                print(f"  {_log}")
        else:
            print(f"  {_log}")
        new_scene = _llm_rewrite_scene(
            shot.get("narration", ""), shot.get("scene", ""), note, topic)
        if not new_scene:
            break
        shot["scene"] = new_scene
        prompt = _build_shot_prompt(shot, character_sheets) + " " + _style_inject(allow_logo=_is_business_shot(shot))
    return prompt


def _ensure_card_prompt_relevant(prompt: str, title: str, n: int,
                                 topic: str = None) -> str:
    """Relevance-gate a chapter card background prompt. If it drifts off-topic,
    re-run the (topic-anchored) background prompt and rebuild, up to N retries."""
    if not topic:
        topic = _IMG_TOPIC
    for attempt in range(1, _SHOT_RELEVANCE_RETRIES + 1):
        # Judge checks the chapter card prompt against BOTH the article topic
        # and the chapter name itself (Joe 2026-08-09).
        relevant, note = _llm_judge_prompt_relevance(
            prompt, f"CHAPTER CARD {n}: {title}", topic)
        if relevant:
            return prompt
        print(f"  [CARD] relevance miss ({attempt}/{_SHOT_RELEVANCE_RETRIES}): {note}")
        bg = _llm_chapter_bg_prompt(title, n, topic)
        if not bg:
            break
        prompt = (f"{_style_inject()}. {bg}. A clean chapter card "
                  f"background with NO text, NO words, NO letters, "
                  f"NO titles, no watermark. The composition is a striking themed "
                  f"backdrop with plenty of open negative space in the centre for "
                  f"text to be overlaid later. "
                  f"minimal clutter. 16:9 widescreen "
                  f"background.")
    return prompt


# Generic words that should never be the discriminating token when checking
# whether an extracted place actually appears in the article text.
_GENERIC_PLACE_WORDS = {
    "the", "of", "and", "for", "in", "a", "an", "to", "on", "at", "near",
    "city", "town", "street", "road", "district", "area", "region", "state",
    "beach", "bay", "island", "north", "south", "east", "west", "new", "saint",
    "st", "mt", "united", "usa", "us", "great", "republic",
}


def _dedupe_consecutive_locations(narration_paras: list[str]) -> list[str]:
    """If two+ CONSECUTIVE paragraphs open with the SAME location anchor, keep
    each paragraph's content but strip the redundant leading location prefix.

    A location CAN recur across the episode (each scene shift gets a new place
    anchor) but should never be re-stated back-to-back. When the LLM (or the
    establishing-shot injector) emits the same location anchor at the start of
    consecutive paragraphs, the duplicate prefixes are removed so the narrator
    doesn't keep saying the same place over and over. The paragraph body is
    preserved; only a paragraph that was EXCLUSIVELY the location anchor is
    dropped entirely.
    """
    if len(narration_paras) < 2:
        return narration_paras

    def _lead_loc(para: str):
        """Return (loc_key_lower, end_index) if the paragraph OPENS with a
        location anchor, else ("", 0). end_index is where the place phrase
        ends so we can strip just the prefix."""
        lead = para[:TITLE_ANCHOR_MAX_CHARS]
        m = LOCATION_PATTERNS[0].search(lead)
        if m:
            return (m.group(1) + " " + m.group(2)).strip().lower(), m.end()
        m = LOCATION_PATTERNS[1].search(lead)
        if m and m.group(1).lower() not in LOCATION_STOPWORDS:
            return m.group(1).strip().lower(), m.end()
        return "", 0

    out: list[str] = []
    prev = ""
    stripped = 0
    for para in narration_paras:
        loc, end = _lead_loc(para)
        if loc and loc == prev:
            # Same place as the paragraph before - keep the body, drop the
            # redundant location prefix so it isn't re-stated back-to-back.
            rest = para[end:]
            rest = re.sub(r"^[\s.,;:]+", "", rest).strip()
            if rest and rest[0].islower():
                rest = rest[0].upper() + rest[1:]
            if rest:
                out.append(rest)
            # prev stays the same -> a 3rd consecutive repeat is stripped too
            stripped += 1
            continue
        out.append(para)
        prev = loc  # "" on a non-location paragraph resets the run
    if stripped:
        print(f"  [DEDUPE] stripped {stripped} back-to-back same-location prefix(es)")
    return out


def _build_episode_context(topic: str, paragraphs: list[str]) -> dict:
    """One LLM pass: the story's world (era, places, environments, props).
    Injected into the shot list so scenes fit ANY topic - a rainforest story
    gets rainforest scenes, not city streets."""
    sample = " ".join(paragraphs[:10])[:2800]
    ctx = _llm_json([
        {"role": "system", "content":
            "You are a documentary production researcher. From the article "
            "excerpt, extract the story's world as STRICT JSON only: "
            '{"era": "one era descriptor", '
            '"places": ["2-4 places EXPLICITLY named in the article: cities, '
            'venues, regions. Empty list if the article names no specific '
            'place - NEVER invent a city, street or venue"], '
            '"environments": ["2-4 environments/settings where scenes happen, '
            "described generically if the article doesn't name one\"], "
            '"props": ["4-8 objects central to the story"], '
            '"time_of_day": "when most scenes happen"}. '
            "Use ONLY places literally written in the article. Never invent "
            "location names. Say NOTHING outside the JSON."},
        {"role": "user", "content": f"TOPIC: {topic}\n\nARTICLE:\n{sample}"}
    ], max_tokens=700, temp=0.3)
    defaults = {"era": "modern", "places": [], "environments": [],
                "props": [], "time_of_day": "night"}
    for k in defaults:
        v = ctx.get(k)
        if isinstance(v, list):
            defaults[k] = [str(x) for x in v[:8]]
        elif isinstance(v, str) and v.strip():
            defaults[k] = v.strip()
    # HARD GUARD: drop any extracted place that is NOT actually present in the
    # article text. The LLM keeps leaking demo-story locations (e.g. "Goulburn,
    # New South Wales" / "Queen Square, Sydney" from the Luke Moore reference
    # episode) into unrelated articles - this filter rejects them outright.
    if defaults["places"]:
        art_text = re.sub(r"\s+", " ", " ".join(paragraphs)).lower()
        kept = []
        for p in defaults["places"]:
            p = str(p).strip()
            if not p:
                continue
            toks = [t for t in re.findall(r"[A-Za-z']{3,}", p.lower())
                    if t not in _GENERIC_PLACE_WORDS]
            if toks and any(t in art_text for t in toks):
                kept.append(p)
        if len(kept) != len(defaults["places"]):
            dropped = [p for p in defaults["places"] if p not in kept]
            print(f"  [CONTEXT] dropped hallucinated places: {', '.join(dropped)}")
        defaults["places"] = kept
    print("  [CONTEXT] era=%s | %d places | %d environments | %d props"
          % (defaults["era"], len(defaults["places"]),
             len(defaults["environments"]), len(defaults["props"])))
    return defaults


def _build_story_bible(topic: str, paragraphs: list[str]) -> dict:
    """STORY BIBLE (built from the ARTICLE, BEFORE the script is written).

    Implements the FERN + Isaac framework (the two scripting videos):
      - visual_hook: the ONE thing the topic must be SEEN to be understood
      - deeper_question: the 'how did this happen / why' the episode answers
      - surface_problem (mechanics) + deeper_problem (emotional struggle)
      - protagonist transformation (start -> end)
      - hero's journey beats (status quo -> call -> ... -> return -> new life)
      - REAL character roster (names + roles) locked from the article so the
        shot list and character sheets use the correct story people - never a
        stale/hallucinated name (fixes the 'Stefan Mandel leak').
    The narration script is then written to FOLLOW this bible.
    """
    sample = "\n\n".join(paragraphs[:40])[:9000]
    # Retry the bible up to 3x - a transient LM Studio timeout must NEVER yield
    # an empty bible (which would silently disable the visual-hook / roster-lock
    # for the whole episode). If the first try comes back without characters or
    # a visual hook, retry fresh.
    bible = {}
    for _attempt in range(3):
        _b = _llm_json([
            {"role": "system", "content":
            "You are a documentary director. From the article, build the locked "
            "story bible as STRICT JSON only, with EXACTLY these keys: "
            '{"visual_hook": "the one striking thing the viewer must SEE (person, place, object, action, event - the video topic has to be seen to be understood)", '
            '"deeper_question": "the deeper WHY/HOW-DID-THIS-HAPPEN question the whole episode answers (never a yes/no, always a mystery)", '
            '"surface_problem": "the mechanical problem - the hack, scheme, loophole", '
            '"deeper_problem": "the emotional struggle underneath (greed, desperation, revenge, injustice, the need to prove something)", '
            '"protagonist": {"name": "the main person", "role": "their role", "transformation_start": "who they are before", "transformation_end": "who they become / the price paid"}, '
            '"characters": [{"name": "exact name from article", "role": "their role in the story", "gender": "male|female", "age": "a concrete descriptive age written as a natural phrase, always inferred from the article - use any exact age the article states, otherwise describe the age bracket the article implies from its own clues (how the person is described, their experience, their life stage). Never leave blank - always give a concrete age descriptor even if you have to estimate", "relation": "how they relate to the protagonist"}], '
            '"hero_journey": {"status_quo": "...", "call": "...", "assistance": "...", "departure": "...", "trials": "...", "approach": "...", "crisis": "...", "reward": "...", "return": "...", "new_life": "..."}, '
            '"key_numbers": ["exact figures from the article"], '
            '"key_places": ["real places EXPLICITLY named in the article; '
            'empty list if the article names no specific place - NEVER invent '
            'a city, street or venue"], '
            '"chapter_moods": [{"n": 1, "title": "chapter title", "mood": "suspense|triumphant|neutral"}]}. '
            "Use ONLY real names, places and figures from the article. Do NOT invent "
            "characters. If the article gives no name for a person, use a role label "
            "like 'The Hacker'. Say NOTHING outside the JSON."},
            {"role": "user", "content": f"TOPIC: {topic}\n\nARTICLE:\n{sample}"}
        ], max_tokens=1400, temp=0.35)
        if _b and (_b.get("characters") or _b.get("visual_hook")):
            bible = _b
            break
        print(f"  [BIBLE] empty/incomplete on attempt {_attempt+1}, retrying...")
        time.sleep(1)
    # Normalize shapes
    if not isinstance(bible.get("characters"), list):
        bible["characters"] = []
    for c in bible["characters"]:
        if isinstance(c, dict):
            c.setdefault("name", "The Subject")
            c.setdefault("role", "character in the story")
            c.setdefault("gender", "male")
            c.setdefault("age", "mid30s")
            c.setdefault("relation", "")
    prot = bible.get("protagonist")
    if isinstance(prot, dict):
        prot.setdefault("name", "")
        prot.setdefault("role", "")
        prot.setdefault("transformation_start", "")
        prot.setdefault("transformation_end", "")
    hj = bible.get("hero_journey")
    if isinstance(hj, dict):
        for k in ("status_quo", "call", "assistance", "departure", "trials",
                  "approach", "crisis", "reward", "return", "new_life"):
            hj.setdefault(k, "")
    if not isinstance(bible.get("chapter_moods"), list):
        bible["chapter_moods"] = []
    print("  [BIBLE] visual_hook:", str(bible.get("visual_hook", "?"))[:80])
    print("  [BIBLE] deeper_question:", str(bible.get("deeper_question", "?"))[:80])
    print("  [BIBLE] deeper_problem:", str(bible.get("deeper_problem", "?"))[:80])
    prot_name = prot.get("name") if isinstance(prot, dict) else ""
    if prot_name:
        print(f"  [BIBLE] protagonist: {prot_name} ({prot.get('role','')})")
    for c in bible["characters"][:8]:
        print(f"  [BIBLE] character: {c.get('name','?')} - {c.get('role','')} "
              f"({c.get('gender','')}/{c.get('age','')})")
    print(f"  [BIBLE] {len(bible['characters'])} characters locked from article")
    return bible


def _build_directors_bible(topic: str, narration_paras: list[str]) -> dict:
    """Director's bible: per-chapter mood, hero moments (paragraph indices to
    magnify with ECU + riser), deeper problem, transformation arc. Written
    BEFORE any image generation - the plan the whole episode obeys."""
    chaps = [p for p in narration_paras if CHAPTER_RE.match(p)]
    chap_lines = " | ".join(chaps[:14]) or "none"
    sample = "\n".join(f"{i+1}. {p[:140]}" for i, p in enumerate(narration_paras[:40]))
    bible = _llm_json([
        {"role": "system", "content":
            "You are the director of a documentary. From the narration outline, "
            "produce the episode plan as STRICT JSON only: "
            '{"deeper_problem": "the emotional struggle under the mechanics", '
            '"transformation": "how the protagonist changes from start to end", '
            '"chapters": [{"n": 1, "title": "...", "mood": "suspense|triumphant|neutral"}], '
            '"hero_paras": [list of 3-6 paragraph numbers that deserve extreme '
            'close-ups / magnification], "arc": "status quo -> call -> trials -> '
            'crisis -> reward -> return" in one line}. '
            "Say NOTHING outside the JSON."},
        {"role": "user", "content":
            f"TOPIC: {topic}\nCHAPTERS: {chap_lines}\n\nNARRATION BEATS:\n{sample}"}
    ], max_tokens=900, temp=0.4)
    heroes = []
    for h in bible.get("hero_paras", []):
        try:
            n = int(h)
            if 1 <= n <= len(narration_paras):
                heroes.append(n)
        except Exception:
            pass
    bible["hero_paras"] = sorted(set(heroes))[:6]
    print("  [BIBLE] deeper: %s" % str(bible.get("deeper_problem", "?"))[:80])
    print("  [BIBLE] hero paragraphs: %s" % (bible["hero_paras"] or "none"))
    return bible


def _build_scene_board(narration_paras: list[str], topic: str,
                       episode_num: int) -> list[dict]:
    """Scene cards: one card per narration paragraph (beat, location,
    characters, mood). Saved to the episode folder as scene_board.json so the
    whole storyboard is reviewable before any image is generated."""
    cards = []
    for i in range(0, len(narration_paras), 20):
        chunk = narration_paras[i:i + 20]
        chunk_txt = "\n".join(f"{j+1}. {p[:120]}" for j, p in enumerate(chunk))
        res = _backend_json([
            {"role": "system", "content":
                "You are a storyboard artist. For each numbered narration beat "
                "produce STRICT JSON only: "
                '{"cards": [{"idx": 1, "beat": "one-line action beat", '
                '"location": "setting", "characters": ["names or []"], '
                '"mood": "suspense|triumphant|neutral"}]}. '
                "Match idx to the input numbers exactly. Say NOTHING else."},
            {"role": "user", "content": f"TOPIC: {topic}\n{chunk_txt}"}
        ], max_tokens=1200, temp=0.3)
        seen_idx = set()
        for c in res.get("cards", []):
            try:
                cidx = int(c.get("idx", i + 1))
                # The LLM occasionally hallucinates extra/duplicate/out-of-range
                # idx. Only accept cards that belong to THIS chunk and have a
                # unique idx, so the scene board never balloons past the narration.
                if not (i + 1 <= cidx <= i + len(chunk)):
                    continue
                if cidx in seen_idx:
                    continue
                seen_idx.add(cidx)
                chars = []
                for x in (c.get("characters", []) or []):
                    sx = str(x).strip().strip('"').strip()
                    if sx.lower() in ("[]", "none", "n/a", "null", ""):
                        continue
                    if sx in ("[", "]", "\""):
                        continue
                    chars.append(sx[:40])
                cards.append({
                    "idx": cidx,
                    "beat": str(c.get("beat", ""))[:160],
                    "location": str(c.get("location", ""))[:80],
                    "characters": chars[:4],
                    "mood": c.get("mood", "neutral"),
                    "seed": (hash(str(cidx)) % 2 ** 31) ^ (hash(topic) % 2 ** 31),
                })
            except Exception:
                continue
    if cards:
        ep_dir = _episode_dir(episode_num)
        ep_dir.mkdir(parents=True, exist_ok=True)
        try:
            (ep_dir / "scene_board.json").write_text(
                json.dumps(cards, indent=1), encoding="utf-8")
        except Exception:
            pass
    # REVIEW + REGEN (Joe 2026-08-17): if the sanitized board collapsed to far
    # fewer cards than the narration, offer to regenerate once before shots fire.
    if cards and len(cards) < len(narration_paras) * 0.6:
        print(f"  [BOARD] WARNING: {len(cards)} cards vs {len(narration_paras)} "
              f"paragraphs - beats may be merged/repeated.")
        if os.environ.get("REGEN_SCENE_BOARD", "").strip().lower() in ("1", "y", "yes", "true"):
            print("  [BOARD] REGEN_SCENE_BOARD=1 - forcing one rebuild")
        else:
            resp = _input_timeout("  Rebuild the scene board once? [Y/n]: ", 10.0, "y").lower()
            if resp not in ("n", "no"):
                return _build_scene_board(narration_paras, topic, episode_num)
    print(f"  [BOARD] {len(cards)} scene cards -> episodes/ep{episode_num:03d}/scene_board.json")
    return cards


def _plan_durations(narration_paras: list[str]) -> None:
    """Duration planning: per-chapter estimated runtimes + total vs target.
    Print-only - chapter placement already used word-count estimates."""
    rows = []
    cur_chap, cur_start = None, 0
    for i, para in enumerate(narration_paras):
        m = CHAPTER_RE.match(para)
        if m:
            if cur_chap is not None:
                d = sum(_estimate_para_duration(p)
                        for p in narration_paras[cur_start:i])
                rows.append((cur_chap, d))
            cur_chap, cur_start = int(m.group(1)), i
    if cur_chap is not None:
        rows.append((cur_chap, sum(_estimate_para_duration(p)
                                   for p in narration_paras[cur_start:])))
    total = sum(_estimate_para_duration(p) for p in narration_paras)
    print(f"\n  [DURATION] total est {total/60:.1f} min ({len(narration_paras)} paras)")
    for n, d in rows:
        print(f"    Chapter {n:2d}: ~{d/60:.1f} min")


def _save_episode_template(topic: str, episode_num: int, bible: dict,
                           context: dict, roster_ids: list[str]) -> None:
    """Reusable episode template: the winning formula of the last episode is
    loaded next run so the next episode starts from it, not from scratch."""
    try:
        TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
        EPISODE_TEMPLATE_FILE.write_text(json.dumps({
            "episode": episode_num, "topic": topic[:120],
            "deeper_problem": bible.get("deeper_problem", ""),
            "transformation": bible.get("transformation", ""),
            "arc": bible.get("arc", ""),
            "chapter_moods": bible.get("chapters", []),
            "era": context.get("era", ""),
            "environments": context.get("environments", []),
            "props": context.get("props", []),
            "roster_ids": roster_ids,
        }, indent=1), encoding="utf-8")
        print(f"  [TEMPLATE] saved ep{episode_num} formula -> templates/last_episode.json")
    except Exception:
        pass


def _load_episode_template() -> Optional[dict]:
    if EPISODE_TEMPLATE_FILE.is_file():
        try:
            return json.loads(EPISODE_TEMPLATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return None


def _gate(label: str) -> bool:
    """Human review gate. Y/n (default Y) - never blocks unattended runs."""
    try:
        resp = input(f"\n  {label} [Y/n]: ").strip().lower()
    except Exception:
        resp = ""
    return resp not in ("n", "no")


# -- Stage 2: Shot list ----------------------------------------------

SHOT_SYSTEM_PROMPT = (
    "You are a shot-list director for SPLIT NODE, a documentary channel "
    "(characters with detailed faces). "
    "Every person in the story is a character with detailed skin, "
    "styled hair, and clothing appropriate to the scene. "
    "The visual style is applied separately - do not describe it here."
    "Each character must be identified by NAME (use the real name from the story, or "
    "a clearly consistent invented name if the story doesn't give one - and reuse the "
    "exact same name every time that person appears). "
    "CHARACTER NAME RULE: once a person is named, ALWAYS repeat the exact same full name "
    "verbatim in every shot they appear in. NEVER switch to first-name-only, last-name-only, "
    "ALL CAPS, initials, or a different spelling - the exact name stays identical in every "
    "single shot. "
    "If a shot contains MULTIPLE people, put ALL of their names in the character field "
    "separated by commas. "
    "The scenes must show the characters actually DOING something - an action that "
    "moves the story forward. Never static portraits. Full scenes based on the actions "
    "they take in the narration. ALWAYS state which way each character faces in the scene "
    "description ('facing left', 'turned to the right', 'seen from behind', 'facing the "
    "camera') so the correct reference panel is chosen for the shot.\n\n"
    + CAMERA_LOGIC +
    "I will give you one paragraph of the narration script. Create ONE shot for it. "
    "Respond with EXACTLY ONE LINE of 8 pipe-separated fields, in this exact order, "
    "with NO labels, NO extra text, NO line breaks:\n"
    "<shot type EWS/WS/MS/CU/ECU> | <camera angle: eye-level, low-angle, high-angle, over-the-shoulder, from-behind, side-on> | "
    "<character NAME or NONE, or comma-separated names for multiple people> | <character role> | "
    "<full scene description: setting, what the character is DOING, which way each faces, props, lighting, camera framing. 2-4 sentences, action-focused> | "
    "<SFX filename or NONE> | <suspense | neutral | triumphant> | "
    "<b-roll requirement: what SECONDARY/COVER footage this shot needs to fill time or add depth - e.g. 'exterior establishing of the bank', 'close-up of the ticket booth', 'drone pan over the city', 'hands counting cash', 'the empty vault'. If the main scene already covers everything and no extra footage is needed, write NONE. 2-10 words>\n"
    "Format ONLY the pipe-separated line above. The scene description is always "
    "built from THIS narration paragraph - its real setting, action, people and "
    "objects - never a stock or invented situation. Every person shown must be a "
    "REAL CHARACTER from the provided list; never introduce a generic filler person.\n"
    "SFX choices (pick ONE fitting sound, or NONE for calm shots). Match the sound to the "
    "moment - whoosh/sweep for transitions, riser before a reveal, hit for impact, "
    "nature/foley for outdoor or environment-rich scenes, soundscape for creeping tension:\n"
    + _sfx_llm_choices() + "\n"
    "TONE guidance: suspense during tense/risky parts, triumphant near the end when they win."
)

def _parse_shot_response(text: str) -> dict:
    """Parse the 7-field pipe format. Tolerant of old labeled formats too.
    Format: shot_type | angle | character | role | scene | sfx | tone"""
    text = text.strip().strip('"\'')
    # If the model still used labeled format, convert: pull each label's value
    if re.search(r"(?:SHOT|CHARACTER|SCENE|SFX|TONE)\s*:", text):
        labels = ["SHOT", "CHARACTER", "SCENE", "SFX", "TONE"]
        positions = []
        for lab in labels:
            for m in re.finditer(rf"{lab}\s*:", text):
                positions.append((m.start(), lab))
        positions.sort()
        vals = {}
        for i, (pos, lab) in enumerate(positions):
            end = positions[i + 1][0] if i + 1 < len(positions) else len(text)
            raw = text[pos:end]
            val = re.sub(rf"^{lab}\s*:\s*", "", raw, flags=re.IGNORECASE).strip()
            val = re.sub(r"\s*\|\s*(?:SHOT|CHARACTER|SCENE|SFX|TONE)\s*:.*$", "", val,
                         flags=re.IGNORECASE).strip()
            val = val.strip("|").strip()
            vals[lab] = val
        shot_line = vals.get("SHOT", "")
        segs = [s.strip() for s in shot_line.split("|")]
        segs = [s for s in segs if not re.match(r"(?:SHOT|CHARACTER|SCENE|SFX|TONE)\s*:", s)]
        char_line = vals.get("CHARACTER", "")
        if "|" in char_line:
            cname, crole = [s.strip() for s in char_line.split("|", 1)]
        else:
            cname, crole = char_line, ""
        return {
            "shot_type": segs[0] if segs else "",
            "angle": segs[1] if len(segs) > 1 else "",
            "character": cname,
            "character_role": crole,
            "scene": vals.get("SCENE", ""),
            "sfx": vals.get("SFX", "NONE").lower(),
            "tone": vals.get("TONE", "neutral").lower(),
        }

    # Clean pipe format: split on | keeping max 7 parts (scene may contain |)
    parts = [p.strip() for p in text.split("|")]
    if len(parts) < 5:
        # Too few fields - bail with whatever we have
        return {
            "shot_type": parts[0] if parts else "",
            "angle": parts[1] if len(parts) > 1 else "",
            "character": parts[2] if len(parts) > 2 else "",
            "character_role": parts[3] if len(parts) > 3 else "",
            "scene": "",
            "sfx": "NONE",
            "tone": "neutral",
        }
    # Fields 0-3 are fixed; scene = join of middle fields; sfx/tone = last two
    shot_type = parts[0]
    angle = parts[1]
    character = parts[2]
    role = parts[3]
    scene = parts[4] if len(parts) > 4 else ""
    # b-roll is the LAST field when the model emitted 8 fields (Joe 2026-08-14);
    # tolerate legacy 7-field output (no b-roll) so a format slip never breaks parse.
    if len(parts) >= 8:
        broll = parts[-1].lower().strip()
        sfx = parts[-3].lower() if len(parts) >= 6 else "NONE"
        tone = parts[-2].lower() if len(parts) >= 7 else "neutral"
    else:
        broll = ""
        sfx = parts[-2].lower() if len(parts) >= 6 else "NONE"
        tone = parts[-1].lower() if len(parts) >= 7 else "neutral"
    # If the model wrote fewer fields, last two might be scene+sfx etc - keep simple
    return {
        "shot_type": shot_type,
        "angle": angle,
        "character": character,
        "character_role": role,
        "scene": scene,
        "sfx": sfx,
        "tone": tone,
        "broll": broll,
    }


def _build_shot_list(narration_paras: list[str], bible: Optional[dict] = None,
                     context: Optional[dict] = None,
                     establishing_map: Optional[dict] = None,
                     sentence_para_map: Optional[dict] = None,
                     checkpoint_cb=None, checkpoint_every: int = 25) -> list[dict]:
    """Stage 2: for each narration sentence, generate a shot entry.

    Each shot = ONE spoken sentence with its OWN image (Joe 2026-08-10). The
    narration list is the flattened sentence list (see
    _flatten_narration_to_sentences), so every sentence becomes its own shot,
    its own TTS clip and its own image that stays on screen for exactly that
    sentence's TTS duration.

    Injects the episode context (era/places/environments/props) and the
    director's bible (hero sentences) so the shot list fits ANY topic and
    magnifies the right moments. Hero beats get ECU framing + a riser SFX.
    Chapter sentences get a direct card shot (no LLM call, no image
    generation - the render pass shows the card image where the glowing
    chapter title is burned). Establishing sentences render as WIDE frames.

    sentence_para_map: {sentence_idx: full parent paragraph} so each shot can
    carry its full paragraph as CONTEXT for the image prompt while the shot
    focuses on its own single sentence.
    """
    establishing_map = establishing_map or {}
    sentence_para_map = sentence_para_map or {}
    print("\n[LLM] Stage 2: building shot list from narration...")
    context = context or {}
    hero_set = set(bible.get("hero_paras", []) or []) if bible else set()
    ctx_line = ""
    if context:
        ctx_line = (
            f"\nEPISODE WORLD: era={context.get('era', '')}; "
            f"places={', '.join(context.get('places', []))}; "
            f"environments={', '.join(context.get('environments', []))}; "
            f"props={', '.join(context.get('props', []))}. "
            "Scenes MUST be set in this world - use these real places, "
            "environments and props.\n")
    # Lock the REAL character roster from the story bible so the shot list
    # never invents or imports characters from other stories (fixes the
    # 'Stefan Mandel leak'). Only these exact names may appear as characters.
    roster = []
    if bible:
        for c in (bible.get("characters") or []):
            if isinstance(c, dict) and c.get("name"):
                roster.append(f"{c['name']} ({c.get('role','')})")
    if roster:
        ctx_line += (
            "\nREAL CHARACTERS (ONLY these people exist in the story - every "
            "shot with a person must use one of these EXACT names, never invent "
            "or import names):\n" + "\n".join(f"  - {r}" for r in roster) + "\n")
    import concurrent.futures as _cf
    _max_workers = int(os.environ.get("SHOT_CONCURRENCY", "6" if LLM_PROVIDER == "codex" else "3"))
    _max_workers = max(1, min(_max_workers, 24))
    _total = min(len(narration_paras), MAX_SHOTS)

    def _gen_one(_i, _para):
        # ESTABLISHING SHOT: injected line -> wide/full establishing frame.
        if _i in establishing_map:
            em = establishing_map[_i]
            is_loc = em.get("kind") == "location"
            name = em.get("name", "")
            if not is_loc:
                name = name.split(",")[0].strip()
            if is_loc:
                scene = ("An establishing extreme wide shot of the location, "
                         "the whole place in frame, no people, "
                         f"{SCENE_STYLE}")
            else:
                name = _clean_character_field(name)
                scene = ("An establishing wide full-body shot of the character, "
                         "whole person in frame from head to toe, "
                         f"highly detailed, {RENDER_STYLE}")
            return {
                "narration": _para,
                "paragraph_context": sentence_para_map.get(_i, _para),
                "narration_idx": _i,
                "shot_type": "EWS" if is_loc else "WS",
                "angle": "eye-level",
                "character": "NONE" if is_loc else name,
                "character_role": "establishing" if not is_loc else "",
                "scene": scene,
                "sfx": "NONE",
                "tone": "neutral",
                "is_establishing": True,
                "establishing_kind": em.get("kind"),
                "establishing_name": name,
            }
        m_chap = CHAPTER_RE.match(_para)
        if m_chap:
            return {
                "narration": _para,
                "paragraph_context": sentence_para_map.get(_i, _para),
                "narration_idx": _i,
                "shot_type": "CU",
                "angle": "eye-level",
                "character": "NONE",
                "character_role": "",
                "scene": "black chapter title card placeholder",
                "sfx": "NONE",
                "tone": "neutral",
                "is_chapter": True,
                "chapter_num": int(m_chap.group(1)),
                "chapter_title": m_chap.group(2).strip(),
            }
        text = _script_chat([
            {"role": "system", "content": SHOT_SYSTEM_PROMPT},
            {"role": "user", "content": (
                f"{ctx_line}NARRATION PARAGRAPH {_i+1} of {_total}:\n{_para[:1200]}\n\n"
                f"Create the shot for this paragraph."
            )}
        ], max_tokens=400, temp=0.8)
        parsed = _parse_shot_response(text)
        shot_type = parsed.get("shot_type", "")
        angle = parsed.get("angle", "")
        character = parsed.get("character", "")
        character_role = parsed.get("character_role", "")
        scene = parsed.get("scene", "")
        sfx = parsed.get("sfx", "NONE")
        tone = parsed.get("tone", "neutral")
        if not scene:
            for _r in range(2):
                print(f"  [LLM] Shot {_i+1}: parse failed, retrying ({_r+1}/2)...")
                time.sleep(0.5)
                _txt = _script_chat([
                    {"role": "system", "content": SHOT_SYSTEM_PROMPT},
                    {"role": "user", "content": (
                        f"{ctx_line}NARRATION PARAGRAPH {_i+1} of {_total}:\n"
                        f"{_para[:1200]}\n\nCreate the shot for this paragraph.")}
                ], max_tokens=400, temp=0.8)
                _p = _parse_shot_response(_txt)
                scene = _p.get("scene", "").strip()
                if scene:
                    shot_type = _p.get("shot_type", shot_type)
                    angle = _p.get("angle", angle)
                    character = _p.get("character", character)
                    character_role = _p.get("character_role", character_role)
                    sfx = _p.get("sfx", "NONE")
                    tone = _p.get("tone", "neutral")
                    parsed = _p
                    break
            if not scene:
                shot_type = shot_type or "MS"
                angle = angle or "eye-level"
                character = character or "NONE"
                character_role = character_role or "character in the story"
                scene = (f"character in the described scene, {RENDER_STYLE}")
                sfx = "NONE"
                tone = "neutral"
                parsed = {}
        character = _clean_character_field(character)
        character_role = (character_role or "").strip()
        if len(character_role) > 120:
            if not scene:
                scene = character_role
            character_role = "character in the story"
        if sfx not in SFX_LIBRARY:
            sfx = "NONE"
        if tone not in ("suspense", "neutral", "triumphant"):
            tone = "neutral"
        if not scene:
            print(f"  [LLM] Shot {_i+1}: parse failed, skipping ({text[:60]!r})")
            return None
        if _is_business_shot_meta(character, scene, sentence_para_map.get(_i, _para)):
            if _is_machine_slop(scene):
                scene = (
                    "The exterior of the company's real office building, the "
                    "business name and logo displayed on the facade and "
                    "signage, employees going about their day outside, realistic "
                    "corporate architecture"
                )
                print(f"  [LLM] Shot {_i+1}: business machine-slop scene -> "
                      f"rewrote to building-with-logo")
        return {
            "narration": _para,
            "paragraph_context": sentence_para_map.get(_i, _para),
            "narration_idx": _i,
            "shot_type": shot_type,
            "angle": angle,
            "character": character,
            "character_role": character_role,
            "scene": scene,
            "sfx": sfx,
            "tone": tone,
            "broll": parsed.get("broll", ""),
        }

    _pool = {_i: None for _i in range(_total)}
    _checkpoint_every = max(1, int(checkpoint_every or os.environ.get("SHOT_CHECKPOINT_EVERY", "25")))
    _done = 0

    def _maybe_checkpoint():
        # Main-thread, order-preserving partial snapshot for crash recovery.
        if not checkpoint_cb or _done < _checkpoint_every or _done % _checkpoint_every != 0:
            return
        _partial = [(_pool.get(_j)) for _j in range(_total) if _pool.get(_j) is not None]
        try:
            checkpoint_cb(_partial)
        except Exception as _ce:
            print(f"  [LLM] checkpoint save failed: {_ce}")

    if _max_workers <= 1:
        for _i in range(_total):
            _pool[_i] = _gen_one(_i, narration_paras[_i])
            _done += 1
            _maybe_checkpoint()
    else:
        with _cf.ThreadPoolExecutor(max_workers=_max_workers) as _ex:
            _futs = {_ex.submit(_gen_one, _i, narration_paras[_i]): _i
                     for _i in range(_total)}
            for _fu in _cf.as_completed(_futs):
                _i = _futs[_fu]
                try:
                    _pool[_i] = _fu.result()
                except Exception as _e:
                    print(f"  [LLM] Shot {_i+1} worker error: {_e}")
                    _pool[_i] = None
                _done += 1
                _maybe_checkpoint()
    # Re-assemble IN ORDER (same as the serial loop), dropping the None skips.
    shots = []
    for _i in range(_total):
        _s = _pool.get(_i)
        if _s is not None:
            shots.append(_s)
    # Hero beats + SFX no-repeat are order-dependent - apply in a final pass.
    for _i, _s in enumerate(shots):
        if (_s.get("narration_idx", -1) + 1) in hero_set:
            _s["hero"] = True
            if _s["shot_type"] not in ("ECU", "CU"):
                _s["shot_type"] = "ECU"
            if _s["sfx"] == "NONE":
                _s["sfx"] = "mixkit-cinematic-trailer-riser-790.wav"
        if _i > 0 and _s.get("sfx") == shots[_i-1].get("sfx") and _s.get("sfx") != "NONE":
            _s["sfx"] = "NONE"
        print(f"  [LLM] Shot {_i+1}: [{_s.get('shot_type')}|{_s.get('angle')}] char={_s.get('character')} {_s.get('scene','')[:50]}... (sfx={_s.get('sfx')}, tone={_s.get('tone')})")
    if not shots:
        print("  [LLM] Shot list failed, building fallback from narration")
        for i, para in enumerate(narration_paras[:12]):
            shots.append({
                "narration": para,
                "paragraph_context": sentence_para_map.get(i, para),
                "narration_idx": i,
                "shot_type": ["EWS", "WS", "MS", "CU", "ECU"][i % 5],
                "angle": ["eye-level", "low-angle", "high-angle", "over-the-shoulder", "from-behind"][i % 5],
                "character": "NONE" if i % 4 == 0 else f"Character{i}",
                "character_role": "protagonist",
                "scene": f"character in the described scene, {RENDER_STYLE}",
                "sfx": "NONE",
                "tone": "suspense" if i < len(narration_paras) - 2 else "triumphant",
            })
    # DETERMINISTIC roster enforcement: the LLM can still hallucinate character
    # names despite the prompt. Hard-filter every shot so only characters in the
    # story bible's REAL roster (or NONE) survive. Any invented/leaked name is
    # removed - this is the belt-and-suspenders that kills the cross-episode
    # name leak ('Stefan Mandel', 'Richard Lustig', etc.) for good.
    if bible and bible.get("characters"):
        allowed = {str(c.get("name", "")).strip() for c in bible["characters"]
                   if isinstance(c, dict) and c.get("name")}
        allowed = {a for a in allowed if a and a.upper() != "NONE"}
        # normalized comparison: case-insensitive, collapse whitespace
        def _norm(s):
            return re.sub(r"\s+", " ", s.strip().lower())
        norm_allowed = {_norm(a) for a in allowed}
        remap = {}  # normalized alias -> canonical roster name
        for a in allowed:
            remap[_norm(a)] = a
        kept, dropped = 0, 0
        for s in shots:
            ch = (s.get("character") or "NONE").strip()
            if ch.upper() == "NONE":
                continue
            names = [n.strip() for n in ch.split(",") if n.strip()]
            ok_names = []
            for n in names:
                if _norm(n) in norm_allowed:
                    ok_names.append(remap[_norm(n)])
            if ok_names:
                s["character"] = ", ".join(ok_names)
                kept += 1
            else:
                s["character"] = "NONE"
                s["character_role"] = ""
                dropped += 1
        print(f"  [CAST-LOCK] enforced bible roster on shot list: "
              f"{kept} shots kept roster names, {dropped} leaked/invented names dropped")
    # BUSINESS/ENTITY DEMOTE (runs regardless of bible): any shot whose
    # 'character' field is a business/entity (SpaceX, 'the company', the IRS)
    # gets its character cleared so it renders as the scene/logo, not a human.
    # This is the belt-and-suspenders that stops a company being personified.
    _biz_demoted = 0
    for s in shots:
        ch = (s.get("character") or "NONE").strip()
        if ch.upper() == "NONE":
            continue
        names = [n.strip() for n in ch.split(",") if n.strip()]
        keep = [n for n in names if not _is_business_name(n)]
        if len(keep) != len(names):
            s["character"] = ", ".join(keep) if keep else "NONE"
            if not keep:
                s["character_role"] = ""
            _biz_demoted += 1
    if _biz_demoted:
        print(f"  [CAST-LOCK] demoted {_biz_demoted} business/entity shot(s) "
              f"(company personified as a person -> NONE, renders as scene/logo)")
    shots = _merge_character_aliases(shots)
    # Assign the canonical display order (Joe 2026-08-09): `seq` = the shot's
    # exact 1-based position in the FINAL ordered list - the SAME order ffmpeg
    # uses to assemble the video (enumerate(shots) in _render_video). Filenames
    # and resume are keyed on this so the right image always lands on the right
    # frame regardless of generation order or narration_idx gaps.
    for _si, _shot in enumerate(shots):
        _shot["seq"] = _si + 1
    print(f"  [LLM] Shot list complete: {len(shots)} shots")
    return shots

def _merge_character_aliases(shots: list[dict]) -> list[dict]:
    """Collapse every spelling variant of a character onto ONE canonical full name.

    Articles + the LLM produce messy variants: 'IRWIN' / 'Irwin' / 'Mr Irwin' /
    'J. Irwin' / 'Jessy Irwin' / 'the IRS' / 'I.R.S.' ... which previously built
    2-3 character sheets for the same person. This maps each distinct spelling
    to a canonical full name using:
      - case/punctuation/honorific normalization (I.R.S. == IRS)
      - exact compact-form equality (Mark == MARK == mark)
      - token-subset folding ('Irwin' -> 'Jessy Irwin', 'J. Irwin' -> 'Jessy Irwin')
    The canonical name is the fullest (most tokens, then longest, then first-seen).
    """
    canon = _character_canonical_map(shots)
    # Bug 4 (Joe 2026-08-14): LLM dedupe pass over the resolved names - catches
    # SEMANTIC duplicates the deterministic alias merge can't (e.g. 'Stefan
    # Mandel' vs 'Mandel' vs 'Stefan' that aren't token-subsets). Merging canon
    # HERE propagates to every downstream consumer (sheets, real-photo refs,
    # on-screen titles) because this function rewrites the shot's character
    # field to the canonical name. Fail-open; CHAR_DEDUPE=0 disables.
    if os.environ.get("CHAR_DEDUPE", "1").strip().lower() not in ("0", "false", "no", "off"):
        canon = _llm_merge_duplicate_characters(canon)
    changed = 0
    for s in shots:
        c = s.get("character", "NONE")
        target = canon.get(c)
        if target and target != c:
            s["character"] = target
            changed += 1
    if changed:
        merges = ", ".join(f"{k}->{v}" for k, v in canon.items() if k != v)
        print(f"  [LLM] Character alias merge: {changed} shot(s) remapped ({merges})")
    return shots


# Honorifics dropped when normalizing a character name for dedup.
CHAR_HONORIFICS = (
    "mr|mrs|ms|miss|dr|prof|sir|madam|mx|fr|sgt|cpl|lt|capt|captain|officer|"
    "agent|det|detective|insp|chief|judge|gov|governor|sen|senator|rep|bro|sis|"
    "pvt|pfc|constable|sergeant|lieutenant"
)
# Words that carry no identity for dedup purposes.
CHAR_STOPWORDS = {"the", "a", "an", "of", "and", "de", "la", "van", "von", "for", "in", "at", "on"}


def _norm_char_name(name: str) -> tuple[str, set[str]]:
    """Normalize a character name -> (compact, significant tokens).

    compact drops every non-alphanumeric char (so 'I.R.S.' == 'IRS') and every
    stopword token ('the IRS' == 'IRS'), but keeps single-letter initials so
    acronyms survive. tokens are the significant words used for subset
    matching (single-letter initials, honorifics and stopwords removed,
    possessives stripped).
    """
    n = name.lower()
    n = re.sub(r"\(.*?\)", " ", n)                       # parentheticals
    n = re.sub(r"\b(?:%s)\.?\b" % CHAR_HONORIFICS, " ", n)  # honorifics
    n = re.sub(r"'s\b", "", n)                           # possessives
    raw_toks = re.findall(r"[a-z0-9']+", n)
    compact = "".join(t for t in raw_toks if t not in CHAR_STOPWORDS)
    toks = {t for t in raw_toks if len(t) > 1 and t not in CHAR_STOPWORDS}
    return compact, toks


# Placeholder tokens that carry no identity.
_ROLE_PLACEHOLDERS = {"none", "n/a", "na", "nobody", "no one", "unknown", "unnamed",
                      "-", "—", "etc", "unidentified"}


def _clean_character_field(raw) -> str:
    """Strip role/descriptor tokens + placeholders from a shot's character field.

    Joe 2026-08-13: the 4B shot-list model sometimes writes the character field
    as 'ION CECAN, NONE' or 'Robert Pagliarini, attorney, tax person, financial
    adviser'. Those polluted tokens (1) showed up verbatim in the bottom-left
    person title ('(name), none') and (2) made the codex real-ref search look up
    ROLE WORDS as if they were people -> 'the real people reference images are
    all wrong'. This collapses to the real names only: placeholder tokens are
    always dropped, and lowercase descriptor tokens are dropped whenever at least
    one proper-name token is present (so genuine multi-person lists like
    'Elena Petrova, Bogdan Vasilescu' survive intact).
    """
    raw = (raw or "").strip()
    if not raw or raw.upper() in ("NONE", "N/A", "NOBODY", "NO ONE", "-"):
        return "NONE"
    toks = [t.strip() for t in raw.split(",") if t and t.strip()]
    kept = [t for t in toks if t.lower() not in _ROLE_PLACEHOLDERS
            and t.upper() not in ("NONE", "N/A")]
    if not kept:
        return "NONE"
    # A token is "name-like" if its first alpha character is a capital letter.
    def _name_like(t: str) -> bool:
        m = re.search(r"[A-Za-zÀ-ÖØ-öø-ÿ]", t)
        return bool(m) and m.group(0).isupper()
    if any(_name_like(t) for t in kept):
        kept = [t for t in kept if _name_like(t)]
    if not kept:
        return "NONE"
    return ", ".join(kept)


def _character_canonical_map(shots: list[dict]) -> dict[str, str]:
    """Distinct character spelling -> canonical full name (see alias merge)."""
    names = []
    for s in shots:
        c = (s.get("character") or "NONE").strip()
        if c.upper() in ("NONE", "N/A", "NOBODY", "NO ONE", "-", ""):
            continue
        if c not in names:
            names.append(c)
    if len(names) < 2:
        return {n: n for n in names}
    info = {n: _norm_char_name(n) for n in names}

    parent = {n: n for n in names}
    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    # Pass 1: exact normalized equality (Mark == MARK == mark, IRS == I.R.S.)
    for a in names:
        for b in names:
            if a != b and info[a][0] and info[a][0] == info[b][0]:
                union(a, b)
    # Pass 2: token-subset (Irwin -> Jessy Irwin; J. Irwin -> Jessy Irwin)
    for a in names:
        at = info[a][1]
        if not at:
            continue
        for b in names:
            if a != b and info[b][1] and (at < info[b][1] or info[b][1] < at):
                union(a, b)

    def rank(n: str) -> tuple:
        # fuller name first, then fewer punctuation chars, then not starting
        # with an article, then not ALL-CAPS, then longer string, then
        # first-seen order (earlier index wins). Produces 'Jessy Irwin' over
        # 'IRWIN'/'J. Irwin', 'Mark' over 'MARK', 'IRS' over 'I.R.S.'/'the IRS'.
        return (len(info[n][1]), -n.count("."),
                -(1 if re.match(r"^(the|a|an)\b", n, re.IGNORECASE) else 0),
                -(1 if n.isupper() else 0), len(n), -names.index(n))
    best = {}
    for n in names:
        r = find(n)
        if r not in best or rank(n) > rank(best[r]):
            best[r] = n
    return {n: best[find(n)] for n in names}

# -- Stage 2b: Character sheets --------------------------------------

CHARACTER_SHEET_SYSTEM_PROMPT = (
    "You are a character designer for SPLIT NODE, a documentary channel "
    "(characters, detailed skin). You create PRECISE, REPEATABLE text character "
    "sheets so an AI image generator renders the exact same character every time. "
    "I will give you a character's name, their role in the story, and story context. "
    "\n\n"
    "Write a PERFECTLY DETAILED, VERY PRECISE character sheet. Every physical detail "
    "must be locked down so the character looks identical in every shot: face shape, "
    "skin tone, eye color and shape, nose, mouth, hair (color, style, length, "
    "texture), body build, height, posture, age, ethnicity, and a complete outfit "
    "with specific garments, colors, and materials. "
    "\n\n"
    "CLOTHING IS MANDATORY: every character is ALWAYS fully clothed in every single "
    "shot. The OUTFIT line is REQUIRED - never omit it, never leave it blank. Describe "
    "the complete head-to-toe outfit: what they wear on top (shirt/jacket/sweater with "
    "color, fabric, fit, sleeves), on the bottom (trousers/jeans/skirt), footwear "
    "(shoes/boots with color), and any accessories (tie, hat, glasses, watch, bag). "
    "Every view description must state what the character is wearing. The FULL BODY "
    "paragraph MUST include the complete outfit description.\n\n"
    "Respond EXACTLY in this format, nothing else:\n"
    "NAME: <character name>\n"
    "ROLE: <role in the story>\n"
    "GENDER: <male/female>\n"
    "AGE: <age>\n"
    "BUILD: <height, body type, posture, distinguishing physical traits>\n"
    "FACE: <face shape, skin tone, eye color+shape, eyebrows, nose, mouth, jaw, any facial hair or marks - highly specific>\n"
    "HAIR: <color, style, length, texture - highly specific>\n"
    "OUTFIT: <complete head-to-toe outfit: top, bottom, footwear, accessories with colors, fabrics, fit - highly specific, REQUIRED>\n"
    "FRONT VIEW: <how the character looks from directly in front: full body front, face forward, outfit front - 1-2 sentences>\n"
    "LEFT VIEW: <how the character looks from the left side/profile: profile silhouette, hair side, outfit side - 1-2 sentences>\n"
    "RIGHT VIEW: <how the character looks from the right side/profile - 1-2 sentences>\n"
    "BACK VIEW: <how the character looks from behind: hair back, back of outfit, silhouette - 1-2 sentences>\n"
    "FULL BODY: <complete canonical description combining everything above INCLUDING the full outfit into one dense paragraph to prepend to every image prompt>\n"
)

# ---------------------------------------------------------------------------
# CHARACTER ROSTER - 20 fixed archetypes (Metahuman 3D renders, no mannequins).
# These are TEXT-ONLY character sheets: exact, repeatable image prompts so the
# same archetype looks identical in every episode. Story characters are mapped
# to an archetype by role keywords (gender/age fallback for generic roles),
# and the SAME archetype look is reused across the whole show.
#
# Field semantics (consumed by _character_prompt_block):
#   gender/age/build/face/hair/outfit -> explicit prompt fields
#   full_body -> canonical anchor sentence(s) with the EXACT clothing
#   hints    -> role keywords used to assign a story character to this archetype
# ---------------------------------------------------------------------------
CHARACTER_ROSTER = [
    {
        "id": "hacker", "label": "Hacker",
        "hints": ["hack", "cyber", "cracker", "exploit", "dark web", "script kiddie",
                  "computer criminal", "intruder", "breacher"],
        "gender": "male", "age": "late 20s",
        "build": "slim, wiry, slightly hunched posture",
        "face": "Face Shape: Oval, slightly elongated. Forehead: High and broad, exhibiting a smooth, gently sloping curvature. Eyebrows: Medium thickness, possessing a defined arch that starts relatively low on the brow bone and sweeps upward in a gentle, consistent arc; they are well-groomed but not overly sculpted. Eyes: Almond shape, medium size, set moderately wide apart with slight lateral spacing. Iris color is a warm hazel/light brown. Eyelids show distinct upper lid definition with minimal hooding, and the lower lids have subtle puffiness at the outer corners. Nose: The bridge is straight and well-defined, exhibiting moderate width; the tip is slightly rounded but refined, projecting moderately from the face plane. Cheekbones: Moderately pronounced, creating soft but discernible planes beneath the eyes, rising gently towards the temples. Cheeks: Fullness is present, giving a youthful roundness to the mid-face, with slight natural shadowing near the nasolabial folds. Jawline: Clean and well-defined, transitioning smoothly from the lower cheek area down to a moderately tapered chin. Chin: Rounded yet firm, projecting slightly forward (orthognathic). Mouth and Lips: The lips are of medium fullness; the upper lip is slightly thinner than the lower lip, featuring a defined Cupid's bow. The mouth rests in a relaxed, slight upward curve. Ears: Medium size, set close to the head, with a visibl",
        "hair": "messy dark hair in a loose bun, strands falling over the forehead",
        "outfit": "black hoodie with the hood down, dark grey t-shirt underneath, black cargo pants, worn black sneakers, thin silver chain necklace",
        "full_body": "A late-20s male hacker, slim and wiry with a slightly hunched posture. Sharp angular jaw, pale skin, intense dark eyes, light stubble, messy dark hair in a loose bun. Wearing a black hoodie with the hood down over a dark grey t-shirt, black cargo pants, worn black sneakers, and a thin silver chain necklace.",
    },
    {
        "id": "police-officer", "label": "Police Officer",
        "hints": ["polic", "officer", "constable", "sergeant", "cop", "law enforcement", "patrol officer", "uniformed officer"],
        "gender": "male", "age": "early 30s",
        "build": "broad-shouldered, athletic, physically fit",
        "face": "Face shape: Oval, slightly elongated vertically. Forehead: High and broad, exhibiting a smooth, gently sloping curve towards the hairline. Eyebrows: Medium thickness, possessing a defined arch that starts relatively low on the brow bone and sweeps upward with moderate taper at the tail. Eyes: Deep-set, almond to slightly rounded shape; dark brown/near black iris color; medium size; well-spaced horizontally (neither too close nor widely set); upper eyelids are moderately hooded, showing slight creasing at the outer corners. Nose: The bridge is straight and robust, possessing a moderate width that tapers cleanly down to a defined tip; the nostrils are well-formed with visible alar creases. Cheekbones: Pronounced and high, creating distinct planes beneath the eyes, though the flesh above them is relatively smooth. Cheeks: Fullness is moderate, giving a grounded appearance, with subtle definition leading into the jawline. Jawline: Strong and clearly defined, exhibiting a sharp angle at the gonial angle. Chin: Medium projection, rounded yet firm, providing a solid anchor to the lower face. Mouth and Lips: The mouth is horizontally proportioned; lips are of medium fullness—the upper lip is slightly thinner than the lower lip, which has a gentle Cupid's bow definition. Ears: Set moderately high on the head, proportionate in size, with smooth helix contours and visible antihelical fold",
        "hair": "short neat brown hair, high and tight cut",
        "outfit": "dark navy police uniform shirt with a generic unmarked badge on the chest (no agency lettering), black trousers, duty belt, black boots",
        "full_body": "An early-30s male police officer, broad-shouldered and athletic. Clean-shaven with a strong jaw, blue eyes, and short neat brown hair in a high-and-tight cut. Wearing a dark navy police uniform shirt with a generic unmarked badge (no agency lettering), black trousers, a duty belt, and black boots.",
    },
    {
        "id": "special-agent", "label": "Special Agent",
        "hints": ["special agent", "federal agent", "secret service", "bureau", "fed", "fbi", "agency investigator", "plainclothes agent", "intel officer"],
        "gender": "male", "age": "mid 40s",
        "build": "solid, gym-fit, broad chest",
        "face": "Face shape: Oval, slightly elongated vertically. Forehead: High and broad, exhibiting a smooth, gently sloping curve. Eyebrows: Medium thickness, well-defined arch that begins relatively low on the brow bone and peaks sharply before tapering to a moderate tail length. Eyes: Almond-shaped, medium size, deep set beneath prominent supraorbital ridges. Iris color is a warm hazel, flecked with gold; lids show a distinct crease, and the lower lid has subtle puffiness at the outer corners. Spacing: Proportional, slightly wider than the average intercanthal distance. Nose: Straight bridge, well-defined but not overly sharp dorsum, tip is moderately rounded with a slight downward projection (nasolabial angle), width is proportionate to the midface. Cheekbones: High and pronounced, creating distinct planes beneath the eyes; cheeks themselves are relatively smooth, showing minimal volume loss for his apparent age. Jawline: Strong and chiseled, exhibiting a clear definition that transitions smoothly into the neck. Chin: Moderately pointed (subtly V-shaped), well-supported by the jaw structure. Mouth: Medium width, possessing a gentle upward curve at the corners. Lips: Fullness is balanced; the upper lip is slightly thinner than the lower lip, with a defined Cupid's bow. Ears: Set moderately high on the head, proportionate size, helix shows a slight inward roll (concha), lobe is smooth and",
        "hair": "short cropped dark hair with grey at the temples",
        "outfit": "plain dark charcoal suit, white shirt, black tie, no badge, no insignia, no logos - an anonymous federal look",
        "full_body": "A mid-40s male special agent, solid and gym-fit with a broad chest. Square jaw, weathered skin, cold grey eyes, short stubble, short cropped dark hair with grey at the temples. Wearing a plain dark charcoal suit, white shirt and black tie - no badge, no insignia, no logos, an anonymous federal look.",
    },
    {
        "id": "lawyer", "label": "Lawyer",
        "hints": ["lawyer", "attorney", "barrister", "solicitor", "counsel", "prosecutor", "defence lawyer", "defense attorney", "legal", "judge", "litigator"],
        "gender": "male", "age": "early 40s",
        "build": "lean, tall, upright posture",
        "face": "Face shape: Oval, slightly elongated. Forehead: High and broad, exhibiting a smooth, gently sloping curve. Eyebrows: Medium thickness, well-defined arch starting relatively low on the brow bone, tapering to a slight, soft tail. Eyes: Almond-shaped, medium size, deep set beneath prominent supraorbital ridges. Iris colour is a warm hazel/light brown, framed by dark lashes. Eyelids show moderate hooding, particularly on the upper lid, with visible creasing at the outer corners. Spacing is proportional and balanced. Nose: Straight bridge, moderately wide at the base, transitioning to a defined yet softly rounded tip. Nostrils are well-formed and symmetrical. Cheekbones: Moderately high set, providing subtle but distinct definition beneath the skin; cheeks themselves appear full but taut over the bone structure. Jawline: Cleanly defined, strong curve leading down from the mandibular angle. Chin: Proportionate to the rest of the face, slightly rounded at the apex. Mouth and Lips: Medium width mouth. Upper lip is fuller, exhibiting a gentle Cupid's bow; lower lip is full and smooth, with a slight downward curve at the corners. Ears: Set relatively close to the head, medium size, well-formed helix and antihelix structure, visible lobe shows subtle definition. Skin tone: Fair, warm undertones (peachy/light tan). Skin texture: Smooth overall, but pores are visible across the T-zone (fore",
        "hair": "neat dark brown hair, side part, lightly gelled",
        "outfit": "tailored navy suit, crisp white shirt, burgundy silk tie, polished leather shoes, leather briefcase",
        "full_body": "An early-40s male lawyer, lean and tall with upright posture. Narrow face, wire-rimmed glasses, sharp nose, trimmed beard, neat dark brown hair with a side part. Wearing a tailored navy suit, crisp white shirt, burgundy silk tie, polished leather shoes, carrying a leather briefcase.",
    },
    {
        "id": "mid40s-male", "label": "Everyman, mid-40s male",
        "hints": ["mid-40s male", "middle-aged man", "family man", "husband", "father of", "regular guy", "everyman"],
        "gender": "male", "age": "mid 40s",
        "build": "average build, soft around the middle, broad hands",
        "face": "Face shape: Oblong, tapering slightly towards a defined chin. Forehead: High and broad, exhibiting subtle horizontal creasing across the brow area. Eyebrows: Medium thickness, possessing a gently arched, somewhat rugged shape; the inner corners are slightly more pronounced than the outer sweep. Eyes: Deep-set, almond-shaped, medium size, dark (appears deep brown/black in monochrome), with moderate spacing. Eyelids: The upper lid shows slight hooding, and there is visible creasing at the outer canthus. Nose: Straight bridge, moderately wide at the base, terminating in a slightly bulbous yet refined tip; nostrils are well-defined. Cheekbones: Moderately prominent, creating subtle shadowing beneath them when viewed from this angle, with soft fullness to the cheeks themselves. Jawline: Strong and clearly defined, transitioning smoothly into a tapered chin. Chin: Moderate projection, rounded but firm. Mouth and Lips: The lips are medium in fullness; the upper lip is slightly thinner than the lower, forming a relaxed, downturned curve at the corners. Ears: Medium size, set relatively close to the head, with visible vertical folds (helix/antihelix) and a slight prominence on the lobe. Skin tone: Appears weathered, suggesting a warm, medium olive undertone in natural light; texture is finely porous but shows significant topographical variation due to age. Blemishes/Texture: Pronounced",
        "hair": "dark brown hair receding at the temples, neatly combed",
        "outfit": "plain navy polo shirt, khaki chinos, brown leather belt, simple analogue watch",
        "full_body": "A mid-40s male everyman, average build, soft around the middle with broad hands. Rounded face, tired brown eyes, slight smile lines, stubble, dark brown hair receding at the temples. Wearing a plain navy polo shirt, khaki chinos, a brown leather belt and a simple analogue watch.",
    },
    {
        "id": "mid40s-female", "label": "Professional woman, mid-40s",
        "hints": ["mid-40s female", "middle-aged woman", "working mother", "professional woman"],
        "gender": "female", "age": "mid 40s",
        "build": "slim, elegant, straight posture",
        "face": "Face shape: Oval, slightly tapering towards a defined chin. Forehead: Moderately high, broad, with subtle horizontal creasing across the brow area. Eyebrows: Medium thickness, moderately arched, possessing a natural, somewhat uneven texture; the inner corners are slightly denser than the outer sweeps. Eyes: Deep-set, almond shape, medium size, dark brown/hazel colour. Spacing is average, with slight medial convergence at the inner canthi. Eyelids: Upper lid shows moderate hooding, revealing a defined crease; lower lids exhibit fine creasing and slight puffiness. Nose: Bridge is straight and moderately high, exhibiting subtle dorsal flattening near the glabella. Tip is rounded but firm, slightly bulbous. Width is proportionate to the face, neither overly narrow nor wide. Cheekbones: Prominent, well-defined, showing moderate elevation beneath the skin, creating soft shadowing under the zygomatic arches. Cheeks: Fullness has diminished with age, revealing deeper nasolabial folds that run from the nose wings down towards the corners of the mouth. Jawline: Strong and clearly defined, exhibiting a slight mandibular angle prominence. Chin: Rounded yet firm, well-supported by underlying structure. Mouth and Lips: The lips are medium fullness; the upper lip is slightly thinner than the lower. Shape is naturally curved into a gentle, resting smile. Ears: Medium size, set close to the hea",
        "hair": "shoulder-length chestnut hair, blunt cut, tucked behind one ear",
        "outfit": "charcoal blazer over a cream blouse, black tailored trousers, low heels, small pearl earrings",
        "full_body": "A mid-40s professional woman, slim and elegant with straight posture. Fine features, warm hazel eyes, minimal makeup, gentle frown lines, shoulder-length chestnut hair in a blunt cut. Wearing a charcoal blazer over a cream blouse, black tailored trousers, low heels and small pearl earrings.",
    },
    {
        "id": "young-male", "label": "Young man, 20s",
        "hints": ["young male", "young man", "teenager", "teen", "student", "college", "intern", "20s male", "twenties"],
        "gender": "male", "age": "early 20s",
        "build": "lean, lanky, long limbs",
        "face": "Face shape: Oval, with subtle tapering towards a defined chin. Forehead: High and smoothly curved, exhibiting a gentle convexity. Eyebrows: Medium thickness, possessing a soft, slightly arched shape that begins relatively low on the brow bone. Eyes: Almond-shaped, medium size, set moderately wide apart. Iris colour is a warm hazel/light brown; eyelids show a distinct crease and slight hooding at the outer corners. Nose: Straight bridge, well-defined but not overly sharp, with a softly rounded tip and moderate width across the alar base. Cheekbones: Moderately prominent, creating gentle hollows beneath them that catch the light subtly. Cheeks: Fullness is present, giving a youthful plumpness, particularly in the malar region. Jawline: Cleanly defined, exhibiting a smooth transition from the lower cheek to the chin. Chin: Rounded and proportionate, neither overly pointed nor blunt. Mouth and Lips: The lips are full, especially the lower lip, which has a generous curve (cupid's bow is well-defined). The overall mouth shape is relaxed and slightly downturned at the corners. Ears: Medium size, set close to the head, with a smooth helix and antihelix; the lobe is rounded and fleshy. Skin tone: Fair, possessing a warm, rosy undertone. Skin texture: Very smooth, porcelain-like quality, though fine pores are visible across the cheeks and nose bridge. Blemishes/Wrinkles: Minimal; faint l",
        "hair": "thick sandy-brown hair, messy fringe",
        "outfit": "oversized grey hoodie, black jeans with a wallet chain, white sneakers, backpack",
        "full_body": "An early-20s young man, lean and lanky with long limbs. Boyish face, bright eyes, light freckles, clean-shaven, thick sandy-brown hair with a messy fringe. Wearing an oversized grey hoodie, black jeans with a wallet chain, white sneakers and a backpack.",
    },
    {
        "id": "young-female", "label": "Young woman, 20s",
        "hints": ["young female", "young woman", "girl", "student female", "intern female", "20s female"],
        "gender": "female", "age": "early 20s",
        "build": "petite, energetic posture",
        "face": "Face shape: Oval, with subtle tapering towards a defined chin. Forehead: High and smooth, exhibiting a gentle, convex curve. Eyebrows: Medium thickness, well-arched with a slight downward sweep at the outer corners; they possess a natural, soft taper from the inner arch. Eyes: Almond-shaped, medium size, deep set beneath slightly hooded lids. Iris color is a warm hazel, flecked with amber and green. Eyelids show moderate creasing at the outer canthus. Spacing is balanced, neither too wide nor too close together. Nose: The bridge is straight and moderately high, exhibiting subtle definition (a slight dorsal hump). The tip is refined, slightly rounded, and well-proportioned to the face width. Width is average for her facial structure. Cheekbones: Moderately prominent, creating gentle but distinct planes beneath the eyes; they rise smoothly from the mid-cheek area. Cheeks: Softly contoured, with a natural flush visible in the apples, suggesting healthy blood flow. Jawline: Clean and well-defined, exhibiting a smooth transition from the lower cheek to the chin. Chin: Gently rounded, proportionate, and slightly pointed (a subtle V-shape). Mouth and Lips: The mouth is naturally closed, forming a relaxed, slight upturn at the corners. Lips are medium fullness; the upper lip is slightly thinner than the lower lip, which has a soft cupid's bow definition. Ears: Medium size, set relative",
        "hair": "long straight auburn hair, centre part",
        "outfit": "cream knit sweater, high-waisted blue jeans, white canvas sneakers, small crossbody bag",
        "full_body": "An early-20s young woman, petite with an energetic posture. Round face, large green eyes, light makeup, long straight auburn hair with a centre part. Wearing a cream knit sweater, high-waisted blue jeans, white canvas sneakers and a small crossbody bag.",
    },
    {
        "id": "old-male", "label": "Elderly man, 60s-70s",
        "hints": ["old male", "elderly man", "retiree", "pensioner", "grandfather", "senior man", "60s", "70s", "80s"],
        "gender": "male", "age": "late 60s",
        "build": "stooped, thin, frail frame",
        "face": "face shape. Forehead is moderately high and smooth, exhibiting subtle horizontal lines across the brow area. Eyebrows are medium thickness, possessing a gentle arch that tapers slightly towards the temples; they appear well-defined but not overly sculpted. Eyes are dark (implied brown/black), almond-shaped with moderate size, set at an average distance apart. The upper eyelids show slight creasing at the outer corners, and the lower lids exhibit fine lines radiating outwards from the tear ducts. Nose has a straight, defined bridge that is slightly broad at the base; the tip is rounded but firm, and the overall width is proportional to the face. Cheekbones are moderately prominent, creating soft shadows beneath them when smiling, with the cheeks themselves appearing full and relaxed in this expression. The jawline is strong and well-defined, transitioning smoothly into a slightly tapered chin that has a gentle curve at the bottom point. Mouth is wide and open in a genuine smile, revealing upper teeth that are even and bright; the lips are medium fullness—the upper lip is slightly thinner than the lower. Ears are set relatively close to the head, appearing proportionate, with visible antihelical folds and smooth lobe texture. Skin tone is warm, tanned (implied), exhibiting a fine-grained texture overall. Texture details include numerous small pores across the cheeks and forehead,",
        "hair": "thinning white hair, combed over",
        "outfit": "brown cardigan over a checked flannel shirt, corduroy trousers, worn leather slippers",
        "full_body": "A late-60s elderly man, stooped and thin with a frail frame. Deeply lined face, bushy grey eyebrows, kind brown eyes, thick grey moustache, thinning white hair combed over. Wearing a brown cardigan over a checked flannel shirt, corduroy trousers and worn leather slippers.",
    },
    {
        "id": "old-female", "label": "Elderly woman, 60s-70s",
        "hints": ["old female", "elderly woman", "grandmother", "senior woman", "nan", "nana"],
        "gender": "female", "age": "late 60s",
        "build": "small, slightly stooped",
        "face": "Face shape: Oval, slightly elongated vertically. Forehead: High and broad, exhibiting a smooth, gently sloping contour with subtle horizontal lines etched across the upper third. Eyebrows: Medium thickness, possessing a well-defined arch that starts moderately low on the brow bone and sweeps upward to a distinct peak before tapering softly. Eyes: Almond shape, medium size, set slightly wide apart (approximately 1.5 eye-widths apart). Iris colour is a warm hazel, flecked with gold; the eyelids show moderate creasing at the outer corners, and the lower lids display faint puffiness. Nose: The bridge is straight and moderately high, exhibiting slight definition near the medial canthus. The tip is softly rounded, neither overly sharp nor bulbous, and the overall width is proportionate to the face. Cheekbones: Prominent and gently convex, casting soft shadows beneath them, particularly visible in the zygomatic arch area. Cheeks: Fullness is moderate; the skin appears slightly lifted on the malar region, suggesting good underlying structure. Jawline: Defined and gracefully curved, transitioning smoothly from the cheek to a moderately tapered chin. Chin: Rounded yet firm, possessing sufficient projection to balance the lower face. Mouth and Lips: The lips are medium fullness, with the upper lip being slightly thinner than the bottom lip. The shape is naturally curved into a gentle, clo",
        "hair": "short silver-white curls",
        "outfit": "floral print blouse, beige cardigan, pleated knee-length skirt, comfortable flat shoes, pearl necklace",
        "full_body": "A late-60s elderly woman, small and slightly stooped. Soft wrinkled face, warm blue eyes, gentle smile, reading glasses on a chain, short silver-white curls. Wearing a floral print blouse, beige cardigan, pleated knee-length skirt, comfortable flat shoes and a pearl necklace.",
    },
    {
        "id": "politician", "label": "Politician",
        "hints": ["politician", "senator", "congress", "mayor", "minister", "parliament", "mp ", "campaign", "government official", "council"],
        "gender": "male", "age": "early 50s",
        "build": "sturdy, imposing, upright",
        "face": "Face shape: Oval, slightly elongated. Forehead: High and broad, exhibiting a smooth, gently sloping curve towards the temples. Eyebrows: Medium thickness, well-defined arching upwards from a relatively straight headline; they possess a slight, natural taper at the outer edges. Eyes: Deep-set, almond-shaped, medium size, dark brown/deep hazel colour. They are spaced evenly, with moderate intercanthal distance. Eyelids: Upper lids show defined creases (hooded appearance), while lower lids are smooth but exhibit fine creasing beneath them. Nose: The bridge is straight and moderately high, exhibiting a subtle dorsal hump near the glabella. The tip is slightly rounded and projects minimally beyond the face plane. Width is proportional to the mid-face width. Cheekbones: Prominent and well-defined, creating moderate shadow definition under the zygomatic arches; they have a gentle upward sweep towards the temples. Cheeks: Fullness is moderate, with slight natural depressions (nasolabial folds) leading from the nose base down toward the corners of the mouth. Jawline: Strong and clearly defined, transitioning smoothly from the lower cheek to a well-set chin. Chin: Rounded yet firm, projecting slightly forward (orthognathic). Mouth and Lips: The lips are medium fullness; the upper lip is slightly thinner than the lower lip. The shape is naturally curved into a gentle, closed smile/smirk.",
        "hair": "full dark hair with grey streaks, immaculately styled",
        "outfit": "charcoal three-piece suit, light blue shirt, muted striped tie, American flag lapel-free (no pins, no logos), pocket square",
        "full_body": "An early-50s male politician, sturdy and imposing with upright posture. Broad face, confident smile, cleft chin, groomed eyebrows, full dark hair with grey streaks immaculately styled. Wearing a charcoal three-piece suit, light blue shirt, muted striped tie, no pins and no logos, with a pocket square.",
    },
    {
        "id": "banker", "label": "Banker / Loan Officer",
        "hints": ["bank", "banker", "loan", "mortgage", "financ", "lender", "credit", "wealth manager", "teller"],
        "gender": "male", "age": "mid 40s",
        "build": "soft build, sedentary posture",
        "face": "Face shape: Oval, with subtle tapering towards a defined chin. Forehead: Moderately high and broad, exhibiting a smooth, slightly convex curve. Eyebrows: Medium thickness, possessing a gentle, naturally arched shape; the arch is neither overly sharp nor completely flat. Eyes: Almond-shaped, medium size, set moderately wide apart. Iris color is a deep hazel, flecked with amber near the pupil. Eyelids show a distinct crease and moderate hooding above the upper lid. Nose: The bridge is straight and well-defined, exhibiting slight prominence; the tip is gently rounded but refined, and the overall width is proportional to the face. Cheekbones: Moderately high set, displaying soft definition beneath the skin, creating subtle shadow planes. Cheeks: Fullness is moderate, with a natural flush visible in the apples. Jawline: Cleanly defined, strong, and angular, transitioning smoothly into the chin. Chin: Medium projection, slightly rounded at the very tip, providing a balanced anchor to the lower face. Mouth and Lips: The mouth is naturally set, neither overly wide nor narrow. Lips are medium fullness; the upper lip has a distinct Cupid's bow, while the lower lip is fuller and curves gently downward at the corners. Ears: Medium size, set close to the head, with a smooth helix and antihelix structure; they appear proportionate and well-formed. Skin Tone: Warm olive tone, exhibiting a hea",
        "hair": "slicked-back dark hair with grey sides",
        "outfit": "light grey suit, white shirt, red tie, banker's vest, leather shoes",
        "full_body": "A mid-40s male banker, soft build with a sedentary posture. Round face, thin lips, heavy-lidded eyes, tortoiseshell glasses, slicked-back dark hair with grey sides. Wearing a light grey suit, white shirt, red tie and a banker's vest with leather shoes.",
    },
    {
        "id": "casino-dealer", "label": "Casino Dealer",
        "hints": ["casino", "dealer", "croupier", "card room", "blackjack", "poker table", "pit boss", "roulette"],
        "gender": "male", "age": "early 30s",
        "build": "lean, precise movements",
        "face": "Face shape: Oval, with subtle tapering towards a defined chin. Forehead: High and smooth, exhibiting a gentle convex curve. Eyebrows: Medium thickness, possessing a well-defined arch that starts slightly lower than the natural brow line, giving an attentive expression. Eyes: Almond-shaped, medium size, set moderately wide apart. Iris color appears to be a warm hazel or light brown (though monochrome), framed by dark lashes. Eyelids: Upper lid shows moderate creasing at the outer corner; lower lids are smooth but show faint vascularity beneath. Nose: Straight bridge of medium width, tapering gracefully to a slightly rounded tip that is neither overly bulbous nor excessively narrow. Cheekbones: Moderately pronounced, creating soft but distinct planes beneath the eyes and extending slightly upward towards the temples. Cheeks: Fullness is moderate; the skin appears taut over the zygomatic arches, with subtle definition in the malar region. Jawline: Cleanly defined, strong curve leading to a well-proportioned chin. Chin: Rounded yet firm, projecting slightly forward from the lower face plane. Mouth and Lips: The lips are medium fullness; the upper lip is slightly thinner than the lower, exhibiting a gentle Cupid's bow. The corners of the mouth turn upward in a subtle, relaxed smile. Ears: Set at an average distance from the head, proportionate to the skull size; the lobe is smooth a",
        "hair": "short black hair, neatly parted",
        "outfit": "crisp white dress shirt, black vest, black bow tie, dark trousers, sleeves rolled to the forearm",
        "full_body": "An early-30s male casino dealer, lean with precise movements. Angular face, unreadable expression, deep-set eyes, short black hair neatly parted. Wearing a crisp white dress shirt, black vest, black bow tie and dark trousers with the sleeves rolled to the forearm.",
    },
    {
        "id": "accountant", "label": "Accountant / Auditor",
        "hints": ["accountant", "auditor", "tax", "bookkeeper", "actuary", "ledger", "compliance", "forensic"],
        "gender": "female", "age": "late 30s",
        "build": "slim, precise, upright",
        "face": "Face shape: Oval, with subtle tapering towards a defined chin. Forehead: High and smoothly curved, exhibiting minimal horizontal creasing at the temples. Eyebrows: Medium thickness, possessing a gentle, slightly arched sweep; the inner corners are well-defined, meeting the brow bone cleanly. Eyes: Dark brown, almond-shaped, medium size, set moderately wide apart with slight lateral spacing. The upper eyelids show a defined crease, and the lower lids present subtle puffiness beneath the outer canthi. Nose: The bridge is straight and moderately high, exhibiting a slight convex curve near the radix; the tip is well-defined, slightly rounded, and proportionate in width to the face. Cheekbones: Moderately prominent, creating soft but distinct planes that catch the light along the zygomatic arches. Cheeks: Fullness is present, particularly on the malar region, giving a healthy, grounded appearance. Jawline: Strong and clearly delineated, transitioning smoothly from the cheekbone area down to a defined mandibular angle. Chin: Rounded yet firm, projecting slightly forward, providing a balanced terminus to the lower face. Mouth and Lips: The mouth is closed in a relaxed, neutral expression. The lips are medium fullness; the upper lip has a distinct Cupid's bow, while the lower lip is fuller and curves gently downwards at the corners. Ears: Medium-sized, set close to the head, with smoot",
        "hair": "dark hair in a tight low bun",
        "outfit": "dark green blouse, black pencil skirt, grey cardigan, sensible black pumps, wristwatch",
        "full_body": "A late-30s female accountant, slim and precise with upright posture. Sharp features, thin-framed glasses, focused grey eyes, dark hair in a tight low bun. Wearing a dark green blouse, black pencil skirt, grey cardigan, sensible black pumps and a wristwatch.",
    },
    {
        "id": "security-guard", "label": "Security Guard",
        "hints": ["security guard", "guard", "doorman", "bouncer", "night watchman", "security officer", "gatehouse"],
        "gender": "male", "age": "mid 40s",
        "build": "heavyset, broad shoulders",
        "face": "Face shape: Oval, tapering slightly towards a defined chin. Forehead: High and broad, exhibiting subtle horizontal lines of age around the temples. Eyebrows: Medium thickness, possessing a strong, moderately arched shape; the inner corners are slightly more pronounced than the outer sweep. Eyes: Deep-set, almond-shaped, medium size, dark (implied brown/hazel), with moderate spacing. Eyelids: The upper lid shows slight creasing at the outer canthus; the lower lid is relatively smooth but exhibits fine lines beneath it. Nose: Straight bridge, well-defined and slightly prominent dorsally; the tip is subtly rounded yet firm, with a medium width across the alar base. Cheekbones: High and pronounced, casting distinct shadows under the zygomatic arches, giving the mid-face structure significant definition. Cheeks: Moderately full, particularly when relaxed, but tautened by expression, showing slight indentation near the nasolabial folds. Jawline: Strong and angular, sharply defined against the neck, leading to a well-proportioned chin. Chin: Medium size, slightly squared off, providing a solid anchor to the lower face. Mouth and Lips: The mouth is set in a contemplative, downturned curve. The lips are of medium fullness; the upper lip is thinner with a distinct Cupid's bow, while the lower lip is fuller and more generous. Ears: Medium-sized, set relatively close to the head, exhibitin",
        "hair": "buzzed grey-brown hair",
        "outfit": "plain dark security uniform with a generic unmarked patch (no lettering), black cap, radio on the shoulder, black tactical boots",
        "full_body": "A mid-40s male security guard, heavyset with broad shoulders. Heavy face, thick neck, small eyes, short beard, buzzed grey-brown hair. Wearing a plain dark security uniform with a generic unmarked patch (no lettering), black cap, radio on the shoulder and black tactical boots.",
    },
    {
        "id": "executive", "label": "Corporate Executive",
        "hints": ["ceo", "executive", "founder", "director", "chairman", "president of", "boss", "business owner", "tycoon", "magnate"],
        "gender": "male", "age": "mid 50s",
        "build": "tall, commanding, broad",
        "face": "face shape. Forehead is moderately high and smooth, exhibiting a gentle convex curve. Eyebrows are medium thickness, possessing a defined arch that starts relatively low on the brow bone and sweeps upward in a graceful, slightly elongated manner. Eyes are a deep hazel-brown, almond-shaped, of average size, with moderate spacing; the upper eyelids show a distinct crease, while the lower lids appear smooth but possess subtle puffiness at the outer corners. The nose has a straight, well-defined bridge that is neither overly narrow nor wide, tapering to a slightly rounded tip. Cheekbones are moderately prominent, creating gentle planes of definition beneath the eyes, with the cheeks themselves appearing full and soft rather than gaunt. The jawline is strong and clearly defined, transitioning smoothly into a proportionate chin which is slightly rounded at the center point. The mouth is medium width, featuring lips that are neither overly thin nor excessively plump; the upper lip has a distinct Cupid's bow, while the lower lip offers a fuller curve. Ears are set close to the head, appearing proportional in size, with smooth helix and antihelix contours. Skin tone is a warm, light olive hue, exhibiting a finely textured surface punctuated by visible pores across the T-zone (forehead/nose) and faint, scattered reddish-brown freckles concentrated on the upper cheeks. There are minimal s",
        "hair": "silver-grey hair, slicked back",
        "outfit": "expensive navy suit, crisp white shirt, no tie, luxury watch, leather brogues",
        "full_body": "A mid-50s male corporate executive, tall and commanding with a broad build. Chiselled face, sharp cheekbones, piercing eyes, groomed grey beard, silver-grey hair slicked back. Wearing an expensive navy suit, crisp white shirt with no tie, a luxury watch and leather brogues.",
    },
    {
        "id": "detective", "label": "Detective / Private Investigator",
        "hints": ["detective", "private investigator", "pi", "inspector", "sleuth", "homicide", "investigator"],
        "gender": "male", "age": "late 40s",
        "build": "wiry, tired, coiled energy",
        "face": "Face shape: Oval, slightly elongated. Forehead: High, broad, with a gentle, smooth curve leading down to the temples. Eyebrows: Medium thickness, well-defined arch that is neither overly sharp nor too soft; they follow a classic, moderate parabolic curve. Eyes: Almond-shaped, medium size, deep-set beneath prominent brow bones. Iris color appears dark brown/hazel in the monochrome image. Eyelids: Upper lids are moderately hooded, showing a distinct crease; lower lids show slight puffiness and fine lines radiating outwards. Spacing: Proportional, slightly wider than average. Nose: Straight bridge, well-defined but not overly sharp dorsum. Tip is rounded with a subtle downward curve (a hint of a 'button' tip). Width: Medium width, proportionate to the face. Cheekbones: Moderately high and prominent, creating distinct planes beneath the eyes; cheeks themselves are full but taut, suggesting good underlying structure. Jawline: Strong, clearly defined, exhibiting a crisp angle from the lower ear towards the chin. Chin: Well-formed, slightly rounded apex, projecting moderately forward. Mouth: Medium width, horizontally proportioned. Lips: Full, particularly the bottom lip which is fuller than the top; Cupid's bow is distinct and well-defined. Ears: Set at an average height, proportionate size, with a smooth helix and antihelix structure; lobe is medium thickness. Skin Tone: Appears to",
        "hair": "unruly dark hair with grey flecks",
        "outfit": "rumpled tan trench coat over a dark shirt, loosened tie, worn leather shoes, notepad",
        "full_body": "A late-40s male detective, wiry and tired with coiled energy. Gaunt face, deep eye bags, five o'clock shadow, sharp nose, unruly dark hair with grey flecks. Wearing a rumpled tan trench coat over a dark shirt, a loosened tie, worn leather shoes, holding a notepad.",
    },
    {
        "id": "journalist", "label": "Journalist / Reporter",
        "hints": ["journalist", "reporter", "writer", "editor", "correspondent", "press", "columnist", "news"],
        "gender": "female", "age": "early 30s",
        "build": "slim, quick, alert",
        "face": "Face Shape: Oval, slightly elongated vertically. Forehead: High and broad, exhibiting a smooth, gently sloping curve towards the temples. The hairline is natural and well-defined. Eyebrows: Medium thickness, possessing a distinct arch that starts moderately low on the brow bone, peaks sharply near the center, and tapers gracefully to a medium tail length. They are relatively straight across the inner corner. Eyes: Almond shape, medium size, set slightly deep beneath the brow ridge. Iris color is a warm hazel-brown, flecked with gold. The upper eyelids show moderate creasing at the outer corners; the lower lids have subtle puffiness and fine lines radiating from the tear ducts. Eyelashes are dark brown, moderately long, and curled upward. Nose: Medium width overall. The bridge is straight and well-defined, showing a slight convex curve near the glabella. The tip is slightly rounded but defined, with a subtle downward tilt at the nostrils (alae). Cheekbones: Moderately prominent, creating gentle but noticeable hollows beneath them when viewed frontally. They are smoothly contoured rather than sharply angular. Cheeks: Fullness is moderate; the skin appears taut over the cheek structure, suggesting good underlying bone definition. Jawline: Clean and well-defined, exhibiting a smooth transition from the zygomatic arch down to the chin. It is neither overly sharp nor excessively soft",
        "hair": "dark wavy hair in a low ponytail",
        "outfit": "beige trench coat over a striped top, dark jeans, ankle boots, generic press badge with no logo, small recorder",
        "full_body": "An early-30s female journalist, slim and alert. Expressive face, curious brown eyes, light freckles, thin lips, dark wavy hair in a low ponytail. Wearing a beige trench coat over a striped top, dark jeans, ankle boots, a generic press badge with no logo, holding a small recorder.",
    },
    {
        "id": "scientist", "label": "Scientist / Engineer",
        "hints": ["scientist", "researcher", "engineer", "technician", "physicist", "professor", "developer", "architect", "analyst", "lab", "researcher"],
        "gender": "male", "age": "late 30s",
        "build": "average, focused posture",
        "face": "Face shape: Oval, slightly elongated vertically. Forehead: High and broad, exhibiting a smooth, gently sloping contour with subtle horizontal lines etched across the upper third. Eyebrows: Medium thickness, possessing a distinct arch that begins relatively low on the brow bone and peaks sharply before tapering to a fine point; they are well-defined and moderately dense. Eyes: Almond shape, medium size, set slightly deep beneath the brow ridge. Iris color is a warm hazel, flecked with gold near the pupil. Eyelids show moderate hooding, particularly the upper lid, creating soft shadows in the medial canthus. Spacing between eyes is proportional to the width of the face. Nose: The bridge is straight and moderately high, exhibiting slight definition/chiseled quality on the supraorbital area. The tip is slightly bulbous but refined, with a subtle downward curve at the very end. Width is average for his facial structure. Cheekbones: Prominent, displaying moderate projection beneath the zygomatic arch; they are well-defined and catch the light strongly. Cheeks: Fullness is moderate, giving a healthy, somewhat robust appearance to the mid-face area, with slight natural indentation visible near the nasolabial folds. Jawline: Strong and clearly defined, presenting a clean, slightly squared termination beneath the lower lip. Chin: Medium projection, rounded but firm, fitting smoothly into",
        "hair": "dark hair with a neat undercut",
        "outfit": "navy button-down shirt with sleeves rolled up, dark chinos, utility vest, lanyard with generic ID card (no logos)",
        "full_body": "A late-30s male scientist, average build with a focused posture. High forehead, thoughtful eyes, glasses, short beard, dark hair with a neat undercut. Wearing a navy button-down shirt with sleeves rolled up, dark chinos, a utility vest and a lanyard with a generic ID card (no logos).",
    },
    {
        "id": "lottery-clerk", "label": "Lottery / Shop Clerk",
        "hints": ["clerk", "cashier", "retailer", "shopkeeper", "store owner", "attendant", "ticket seller"],
        "gender": "female", "age": "early 50s",
        "build": "soft build, warm posture",
        "face": "Face shape: Oval, slightly elongated vertically. Forehead: High and smooth, exhibiting a gentle convex curve. Eyebrows: Medium thickness, well-defined arch that begins relatively low on the brow bone and sweeps up sharply to a distinct apex before tapering gently. Eyes: Deep-set, almond-shaped, medium size, dark brown/near-black iris color. Spacing is balanced; intercanthal distance appears slightly wider than the width of one eye. Eyelids: Upper lid shows moderate hooding with visible crease definition; lower lid is smooth but exhibits subtle puffiness at the outer corners. Nose: Straight bridge, moderately wide at the base, tip is softly rounded with a slight downward projection (nasolabial fold accentuation). Cheekbones: Prominent and well-defined, creating noticeable planes beneath the zygomatic arches. Cheeks: Fullness is moderate; skin appears taut over the cheekbones but retains soft volume in the malar region. Jawline: Strong and clearly defined, transitioning smoothly from the lower cheek to a moderately pointed chin. Chin: Well-proportioned, slightly rounded apex, projecting adequately from the face plane. Mouth and Lips: Medium width mouth. Upper lip is fuller, exhibiting a gentle Cupid's bow; lower lip is full and slightly more voluminous than the upper. Shape is generally soft and curved. Ears: Set moderately close to the head, size appears average for her facial s",
        "hair": "shoulder-length blonde hair with grey roots, clipped back",
        "outfit": "red polo shirt uniform, black trousers, name tag without a name (blank), comfortable shoes",
        "full_body": "An early-50s female shop clerk, soft build with a warm posture. Friendly round face, laugh lines, kind eyes, light makeup, shoulder-length blonde hair with grey roots clipped back. Wearing a red polo shirt uniform, black trousers, a blank name tag and comfortable shoes.",
    },
]


def _age_to_number(age: str) -> int:
    """Turn a descriptive age ('' , 'early 20s', 'mid 40s', '23-year-old',
    'late 60s', 'young', 'retiree') into a numeric midpoint. Returns -1 if
    nothing parseable (unknown)."""
    if not age:
        return -1
    a = str(age).lower().strip()
    # DECADE BANDS FIRST (must run before the bare-number match, otherwise
    # "early 20s" matches the "20" and never reaches the band logic).
    m = re.search(r"(early|mid|late|mid-)?\s*(\d{2})s", a)
    if m:
        band, decade = m.group(1), int(m.group(2))
        if band == "early":
            return decade + 2
        if band == "late":
            return decade + 8
        return decade + 5  # mid / bare "40s"
    # specific number: "23-year-old", "aged 31", "23"
    m = re.search(r"(\d{1,2})\s*-?\s*year", a) or re.search(r"(\d{1,2})", a)
    if m:
        n = int(m.group(1))
        if 10 <= n <= 100:
            return n
    # words
    if any(k in a for k in ("child", "kid", "teen", "student", "teenage")):
        return 18
    if any(k in a for k in ("young", "twenties", "early adult", "mid-20s")):
        return 25
    if any(k in a for k in ("mid-30s", "thirties", "30s")):
        return 35
    if any(k in a for k in ("forties", "40s", "middle-aged")):
        return 45
    if any(k in a for k in ("fifties", "50s")):
        return 55
    if any(k in a for k in ("old", "elder", "senior", "retiree", "60s", "70s", "80s", "grandmother", "grandfather")):
        return 70
    return -1


# KNOWN-PERSON GENDER override (Joe 2026-08-12): well-known public figures whose
# gender a small local LLM reliably mis-guesses. Keyed by lowercase name; the
# archetype matcher consults this before trusting the story bible / role text.
_KNOWN_PERSON_GENDER = {
    "matt damon": "male",
}


def _assign_archetype(name: str, role: str = "", scene: str = "",
                      gender: str = "", age: str = "") -> dict:
    """Map a story character (name + role) to the closest fixed archetype.

    Order of precedence:
      1. ROLE-KEYWORD match (e.g. 'hacker', 'detective') - the specific
         profession archetype wins, UNLESS the bible's age contradicts it
         wildly (a 'young suspect' must never render as an elderly archetype).
      2. GENDER + closest numeric AGE - parse the bible's descriptive age to
         a number and pick the roster entry of the matching gender whose age
         band is nearest. This fixes the age mismatch: a 23-year-old man and a
         retired 70-year-old now get DIFFERENT archetypes instead of both
         collapsing into the mid-40s default.
      3. Generic fallback (mid40s-male / mid40s-female).
    Returns a CHARACTER_ROSTER dict (never None).
    """
    rl = f"{role} {scene}".lower()
    target_age = _age_to_number(age)
    female = bool(re.search(r"\b(female|woman|women|girl|she|her|madam|lady|grandmother)\b", rl)) \
        or (gender and str(gender).lower().startswith("f"))
    # KNOWN-PERSON GENDER override (Joe 2026-08-12): well-known public figures
    # get their correct gender regardless of what a small local LLM guessed in
    # the story bible (the 4B model often mis-genders/mis-ages famous names).
    _kn = _KNOWN_PERSON_GENDER.get(name.strip().lower())
    if _kn:
        female = (_kn == "female")

    def _age_ok(arch_age: str) -> bool:
        """True if the archetype's age is consistent with the bible's age.
        When we have a numeric target, require it within a loose band; otherwise
        accept any non-contradictory match."""
        if target_age < 0:
            return True
        a = _age_to_number(arch_age)
        if a < 0:
            return True
        # young (<35) vs old (>55) hard veto so a young suspect never gets an
        # elderly archetype (and vice-versa) even if a role keyword matched.
        if target_age < 35 and a > 55:
            return False
        if target_age > 55 and a < 35:
            return False
        return True

    # 1. Role-keyword match (respecting age veto AND explicit gender).
    #    GENDER CONSISTENCY (Joe 2026-08-12): when the story bible (or the
    #    known-person override) explicitly genders the character, a role-keyword
    #    archetype of the WRONG gender must not win - e.g. 'Property OWNER' must
    #    never force an elderly woman into the male 'executive' archetype. A
    #    wrong-gender role match falls through to the gender/age step instead.
    _explicit_gender = bool(_kn) or bool(gender and str(gender).strip())
    for arch in CHARACTER_ROSTER:
        if any(h in rl for h in arch["hints"]):
            if not _age_ok(arch.get("age", "")):
                continue
            if _explicit_gender and (arch.get("gender", "") == "female") != female:
                continue
            return arch

    # 2. Gender + closest numeric age
    candidates = [arch for arch in CHARACTER_ROSTER
                  if (arch.get("gender", "") == "female") == female]
    if target_age >= 0 and candidates:
        best = min(candidates,
                   key=lambda a: abs(_age_to_number(a.get("age", "")) - target_age))
        # only use the age-closest match if it's meaningfully closer than the
        # generic everyman (mid40s) fallback - otherwise stick with the generic
        return best

    # 3. Generic fallback
    if female:
        return _roster_by_id("mid40s-female")
    return _roster_by_id("mid40s-male")


def _roster_by_id(arch_id: str) -> dict:
    for arch in CHARACTER_ROSTER:
        if arch["id"] == arch_id:
            return arch
    return CHARACTER_ROSTER[4]  # mid40s-male


def _character_sheet_from_archetype(arch: dict, name: str, role: str = "") -> dict:
    """Turn a roster archetype into a character sheet dict (same shape the
    prompt builder expects: gender/age/build/face/hair/outfit/full_body)."""
    sheet = {"name": name, "role": role, "archetype": arch["id"]}
    for f in ("gender", "age", "build", "face", "hair", "outfit", "full_body"):
        sheet[f] = arch.get(f, "")
    return sheet


def _build_character_sheets(shots: list[dict], narration: list[str],
                            bible: Optional[dict] = None) -> dict:
    """Map every unique story character to a FIXED roster archetype.

    Deterministic (no LLM, no cost, zero per-episode variance): a character's
    look comes from the static 20-archetype roster, so 'the hacker' looks the
    same in every episode. Falls back to the generic everyman archetype.
    When a STORY BIBLE is provided, its per-character gender/age drive the
    archetype selection so the cast matches the article (e.g. a 21-year-old
    suspect renders young, never as an elderly archetype).
    """
    canon = _character_canonical_map(shots)
    # bible roster: name -> (gender, age)
    bible_meta = {}
    if bible:
        for c in (bible.get("characters") or []):
            if isinstance(c, dict) and c.get("name"):
                bible_meta[str(c.get("name")).strip()] = (
                    str(c.get("gender", "")), str(c.get("age", "")))
    sheets = {}
    for s in shots:
        raw = (s.get("character") or "NONE").strip()
        if raw.upper() in ("NONE", "N/A", "NOBODY", "NO ONE", "-", ""):
            continue
        # Split a multi-person field ('A, B') into individual character sheets
        # so each person gets their own archetype (not one combined sheet).
        names = [n.strip() for n in raw.split(",") if n.strip()]
        for nm in names:
            c = nm  # use the individual name directly (canon maps full fields)
            if c == "NONE" or c in sheets:
                continue
            # BUSINESS/ENTITY GUARD: a company (SpaceX, 'the company', the IRS)
            # is NOT a person - it must never get a human archetype sheet. It
            # is handled by the BRAND/logo pipeline instead (Joe 2026-08-09).
            if _is_business_name(c):
                print(f"  [CAST] {c} -> SKIP (business/entity, not a person)")
                continue
            role = s.get("character_role", "")
            gender, age = _bible_meta_for(bible_meta, c)
            arch = _assign_archetype(c, role, s.get("scene", ""), gender, age)
            sheets[c] = _character_sheet_from_archetype(arch, c, role)
            print(f"  [CAST] {c} -> {arch['label']}"
                  f"{f' (role: {role})' if role else ''}"
                  f"{f' [bible age: {age}]' if age else ''}")
    print(f"  [CAST] {len(sheets)} characters assigned from the fixed roster")
    return sheets


def _bible_meta_for(bible_meta: dict, character_key: str) -> tuple:
    """Look up a character's bible gender/age by name, handling multi-name shot
    keys (a shot field can be 'Name A, Name B'). Returns (gender, age) from the
    FIRST bible roster member whose name appears in the key."""
    if not character_key:
        return ("", "")
    key_l = character_key.lower()
    # exact key match first
    if character_key in bible_meta:
        return bible_meta[character_key]
    # substring match: any roster name contained in the combined key
    for name, (gender, age) in bible_meta.items():
        if name and name.lower() in key_l:
            return (gender, age)
    return ("", "")


def _llm_merge_duplicate_characters(canon: dict[str, str]) -> dict[str, str]:
    """LLM dedupe pass over the resolved character names (Bug 4, Joe 2026-08-14).

    The deterministic alias merge (_character_canonical_map) catches spelling and
    token-subset duplicates, but not SEMANTIC duplicates the LLM would flag (two
    names that clearly refer to the same real person - e.g. a character introduced
    as 'Stefan Mandel' in one shot and 'Mandel'/'the Romanian' in another, or two
    distinct-looking spellings the word-matcher can't unify). We send the final
    unique name list back to the LLM and ask it to flag any names that are
    duplicates of one another, returning a merge map {name -> canonical name}.

    Fail-open: on any LLM error / no response, returns the input unchanged.
    The returned map maps EVERY name to a canonical representative; names the LLM
    left alone map to themselves.
    """
    unique = sorted({v for v in canon.values()})
    if len(unique) < 2:
        return {n: n for n in canon}
    prompt = (
        "I have a list of characters that appear in a story. Some of these names "
        "may refer to the SAME person written in slightly different ways (e.g. "
        "'Stefan Mandel' vs 'Mandel' vs 'Stefan', 'the Romanian' if it clearly "
        "means a listed person, initials vs full names, one full name and one "
        "partial).\n\n"
        "List:\n" + "\n".join(f"- {n}" for n in unique) + "\n\n"
        "Return ONLY a JSON object mapping each name to the SINGLE canonical name "
        "it should be merged INTO. Names that are NOT duplicates map to themselves. "
        "When multiple names are the same person, they must ALL map to the same "
        "canonical (fullest/most correct) name. Do not merge names that are "
        "genuinely different people, and do not invent names not on the list.\n"
        'Example: {"Stefan Mandel": "Stefan Mandel", "Mandel": "Stefan Mandel", '
        '"Stefan": "Stefan Mandel", "Elena Petrova": "Elena Petrova"}'
    )
    resp = _llm_json([
        {"role": "system", "content":
         "You merge duplicate character names in a cast list. Reply with JSON only."},
        {"role": "user", "content": prompt},
    ], max_tokens=1200, temp=0.1)
    if not isinstance(resp, dict) or not resp:
        print("  [DEDUPE] LLM returned nothing - keeping character names as-is")
        return {n: n for n in canon}
    # Build {name -> canonical}, validating that canonical targets exist on the
    # list (never invent/map to an off-list name, which would orphan the sheet).
    valid = set(unique)
    merge: dict[str, str] = {}
    for raw_name, canon_name in resp.items():
        src = str(raw_name).strip()
        tgt = str(canon_name).strip()
        if not src or src not in valid:
            continue
        if tgt not in valid:
            tgt = src  # off-list target -> treat as no-merge
        merge[src] = tgt
    merged = {n: merge.get(n, n) for n in unique}
    _dupes = sorted({f"{k} -> {v}" for k, v in merged.items() if k != v})
    if _dupes:
        print(f"  [DEDUPE] LLM merged {len(_dupes)} duplicate name(s):")
        for d in _dupes:
            print(f"          {d}")
    else:
        print("  [DEDUPE] no duplicate characters found")
    # Propagate the merge through the original canonical map (every distinct
    # spelling -> final canonical).
    return {n: merged.get(canon[n], canon[n]) for n in canon}

def _character_view_block(sheet: dict, angle: str) -> str:
    """Pick the character description that matches the camera angle.
    Returns the view-specific paragraph (front/left/right/back) or the full body."""
    if not sheet:
        return ""
    a = (angle or "").lower()
    if "behind" in a or "back" in a:
        view = sheet.get("back_view") or sheet.get("full_body", "")
        label = "seen from behind"
    elif "side" in a or "profile" in a or "left" in a:
        view = sheet.get("left_view") or sheet.get("full_body", "")
        label = "seen from the left side profile"
    elif "right" in a:
        view = sheet.get("right_view") or sheet.get("full_body", "")
        label = "seen from the right side profile"
    elif "over-the-shoulder" in a or "ots" in a:
        view = sheet.get("back_view") or sheet.get("full_body", "")
        label = "seen from over the shoulder (behind)"
    else:
        view = sheet.get("front_view") or sheet.get("full_body", "")
        label = "seen from directly in front"
    return f"{view} ({label})"

def _character_prompt_block(sheet: dict, angle: str, expression: str = "",
                            gaze: str = "") -> str:
    """Build the full prepend block for a character in a shot: identity + angle view.

    `expression`/`gaze` are per-SHOT fields (Joe 2026-08-14): each shot derives
    them from the narration/scene so the SAME character isn't stuck with one
    frozen facial expression. They render as explicit 'Expression: ...' and
    'Eyes: ...' lines so the image model varies the face per shot. When empty
    they're omitted (the sheet's neutral look is used).
    """
    if not sheet:
        return ""
    parts = []
    if sheet.get("gender"):
        parts.append(f"Gender: {sheet['gender']}")
    if sheet.get("age"):
        parts.append(f"Age: {sheet['age']}")
    if sheet.get("build"):
        parts.append(f"Build: {sheet['build']}")
    if sheet.get("face"):
        parts.append(f"Face: {sheet['face']}")
    if sheet.get("hair"):
        parts.append(f"Hair: {sheet['hair']}")
    if sheet.get("outfit"):
        parts.append(f"Outfit: {sheet['outfit']}")
    view = _character_view_block(sheet, angle)
    if view:
        parts.append(f"View: {view}")
    # Per-shot expression + gaze (Bug 1 fix): explicit lines so the face changes
    # per shot instead of reusing the static neutral identity look every time.
    if expression:
        parts.append(f"Expression: {expression}")
    if gaze:
        parts.append(f"Eyes: {gaze}")
    # Full body canonical description last as the anchor (always included when
    # present - it carries the full outfit, so dropping it would lose the clothing)
    if sheet.get("full_body"):
        parts.append(f"Canonical: {sheet['full_body']}")
    return " ".join(parts)


# ---------------------------------------------------------------------------
# Bug 1 / Bug 3 helpers (Joe 2026-08-14)
# ---------------------------------------------------------------------------
# Deterministic emotion keyword -> facial expression, applied per shot so the
# same character isn't frozen in a neutral face across the whole episode.
_EXPRESSION_MAP = [
    # (match words, expression text). Order matters: first hit wins.
    (("anger", "angry", "rage", "furious", "enraged", "outraged", "fury",
      "screaming", "shouting", "yelling", "snarl", "clench"), 
     "angry, jaw tight, brow furrowed"),
    (("fear", "fearful", "afraid", "terrified", "scared", "panic", "panic",
      "terror", "dread", "shaking"), 
     "fearful, wide eyes, tense jaw"),
    (("sad", "sadness", "grief", "grieving", "mourn", "crying", "cried",
      "tears", "weeping", "heartbroken", "devastated", "hopeless"),
     "sad, downcast eyes, sorrowful"),
    (("smil", "grin", "smiling", "laugh", "laughed", "chuckle", "pleased",
      "proud", "happy", "content", "satisfied"), 
     "subtle knowing smile"),
    (("shock", "shocked", "surprise", "surprised", "astonished", "stunned",
      "amazed", "bewildered"), 
     "shocked, raised eyebrows"),
    (("suspici", "suspicious", "distrust", "wary", "skeptic", "sceptic",
      "doubt", "narrowed"), 
     "suspicious, narrowed eyes"),
    (("calm", "calmly", "composed", "coolly", "measured", "collected",
      "stoic", "calmness"), 
     "calm, steady gaze"),
    (("determined", "determination", "focused", "resolute", "ruthless",
      "cold-eyed", "calculating"), 
     "determined, intense focus"),
    (("confus", "confused", "bewildered", "puzzled", "uncertain"), 
     "confused, furrowed brow"),
    (("greed", "greedy", "lust", "covet", "hungry", "desire", "obsess"),
     "hungry, covetous expression"),
    (("desperat", "desperate", "pleading", "begging", "anguish"), 
     "desperate, pleading look"),
    (("smirk", "smug", "smugly", "self-satisfied", "condescending"), 
     "smug smirk"),
]


def _shot_expression_gaze(narration: str, scene: str) -> tuple:
    """Derive (expression, gaze) for a shot from its narration + scene text.

    Deterministic keyword mapping (no LLM cost, fail-open): returns empty
    strings when nothing matches so the character's neutral sheet look is used.
    Gaze defaults to the scene's main subject when a likely subject word appears,
    else 'directly into the camera' for dramatic beats, else '' (neutral).
    """
    text = f"{narration} {scene}".lower()
    expression = ""
    for words, expr in _EXPRESSION_MAP:
        if any(w in text for w in words):
            expression = expr
            break
    gaze = ""
    # Gaze at a named in-scene subject (person/object/keyword) when present.
    gaze_target = re.search(
        r"(?:looking at|staring at|gazing at|watching|toward\w*|towards)\s+"
        r"(?:the\s+|at\s+)?([A-Za-z][A-Za-z0-9' -]{2,40}?)(?:\b(?:and|while|as)\b|\.|,|$)",
        text)
    if gaze_target:
        t = gaze_target.group(1).strip().title()
        gaze = f"looking at {t}"
    elif re.search(r"\b(directly into camera|into the lens|at the viewer)\b", text):
        gaze = "looking directly into the camera"
    elif not expression:
        gaze = ""
    return expression, gaze


def _active_render_style() -> str:
    """Neutral subject base (Joe 2026-08-15): returns the content-only
    RENDER_STYLE. The visual style is supplied ONLY by _style_inject() - no
    hardcoded style wording here, so the selected style profile (arcane,
    photoreal, etc.) fully controls the look without any conflicting art
    direction."""
    return RENDER_STYLE


def _shot_shows_hands(shot) -> bool:
    """True when a shot is likely to show a character's hands (close-up/hand
    framing or the scene explicitly mentions hands) - triggers the anatomy-correct
    hands clause so gpt-image-2 doesn't hallucinate fingers."""
    st = str(shot.get("shot_type", "")).upper()
    scene = (shot.get("scene") or "").lower()
    narr = (shot.get("narration") or "").lower()
    if st in ("ECU", "CU") and re.search(
            r"\b(hand|hands|fingers|typing|grabbing|holding|clutching|"
            r"gestur|wrist|palms|grip)\b", scene):
        return True
    if re.search(r"\b(hand|hands|fingers)\b", narr):
        return True
    return False


# ---------------------------------------------------------------------------
# Bug 2 alt (Joe 2026-08-14): pre-stylized canonical identity portrait
# ---------------------------------------------------------------------------
# codex shots use the real person's photo as the identity ref. But feeding the
# RAW photo makes gpt-image-2 copy it photorealistically (one look) while the
# style-in-text pulls toward stylized (a DIFFERENT look) - two distinct
# characters for one person. Fix: pre-stylize a SINGLE canonical portrait once
# per person (facing forward, neutral expression, rendered in the channel style)
# and reuse THAT as the identity ref for every shot. Cached to
# cast_refs/real/<safe>_portrait.png so it's generated once, not per shot.


def _stylized_identity_portrait(char_name: str, role: str) -> Optional[str]:
    """Return the pre-stylized canonical portrait for char_name (codex backend).

    Resolves the real photo (_find_real_reference), then produces ONE stylized
    forward-facing neutral-expression portrait in the channel style and caches it.
    Reuse on subsequent calls/shot renders so every shot of this person uses the
    SAME face AND style (no more photo-vs-style split). Returns the portrait path
    or None (falls back to the raw real photo / txt2img).
    """
    safe = re.sub(r"[^A-Za-z0-9]+", "_", char_name.lower()).strip("_") or "char"
    out = REAL_REFS_DIR / f"{safe}_portrait.png"
    if out.is_file() and _is_real_image(str(out)):
        _regen = os.environ.get("REGEN_IMAGES", "0").strip().lower() in ("1", "yes", "y", "true")
        if not _regen:
            print(f"  [REALREF] reuse stylized portrait {os.path.basename(out)}")
            return str(out)
        try:
            out.unlink()
        except OSError:
            pass
    src = _find_real_reference(char_name, role)
    if not src or not os.path.isfile(src):
        return None
    REAL_REFS_DIR.mkdir(parents=True, exist_ok=True)
    style = _style_inject()
    prompt = (
        f"Portrait of the person in the attached reference photo, FACING FORWARD "
        f"directly into the camera, NEUTRAL expression, eyes open looking straight "
        f"ahead. Preserve the person's facial identity exactly (bone structure, "
        f"features, hairstyle) but render them entirely in this visual style. "
        f"{style} Head and shoulders framing, evenly lit, clean single subject, "
        f"NO text, no words, no watermark. Single clean portrait, no grid, no "
        f"collage, no duplicates."
    )
    # Route through the codex backend (same as shots) so the portrait matches
    # the shots' model. Use the raw photo as the single identity ref.
    ok = _krea_generate(prompt, 55500 + len(safe) * 7, str(out),
                        ref_images=[src], denoise=1.0,
                        ref_mode="identity", ref_boost=4.0, grounding_px=768,
                        upscale=True)
    if ok and out.is_file() and _is_real_image(str(out)):
        print(f"  [REALREF] stylized portrait for {char_name} -> {os.path.basename(out)}")
        return str(out)
    # Fall back to the raw real photo if the stylized pass failed.
    return src

# -- RunPod Z-Image-Turbo --------------------------------------------

def _runpod_generate(prompt: str, seed: int, size: str = "1280*720",
                     timeout: int = 240, out_dir: Optional[Path] = None) -> Optional[str]:
    out_dir = out_dir or EPISODES_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "input": {
            "prompt": prompt,
            "size": size,
            "strength": 0.8,
            "seed": seed,
            "output_format": "png",
            "enable_safety_checker": False,
        }
    }
    payload_bytes = json.dumps(payload).encode()
    req = urllib.request.Request(
        RUNPOD_ENDPOINT, data=payload_bytes,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {RUNPOD_API_KEY}"},
        method="POST"
    )
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                result = json.loads(resp.read().decode())
            if result.get("status") == "COMPLETED":
                img_url = result.get("output", {}).get("result", "")
                if not img_url:
                    print(f"  [RUNPOD] no result URL (attempt {attempt+1})")
                    time.sleep(3)
                    continue
                out_path = str(out_dir / f"shot_{seed}.png")
                urllib.request.urlretrieve(img_url, out_path)
                if os.path.getsize(out_path) > 1000:
                    print(f"  [RUNPOD] OK {os.path.basename(out_path)} ({os.path.getsize(out_path)//1024}KB)")
                    # Pipeline rule: shots render at 1920x1080 -> upscale now
                    try:
                        _upscale_to_1080p(out_path)
                    except Exception:
                        pass
                    return out_path
            elif result.get("status") == "FAILED":
                print(f"  [RUNPOD] FAILED: {str(result.get('error'))[:120]}")
                time.sleep(3)
            else:
                print(f"  [RUNPOD] status={result.get('status')} (attempt {attempt+1})")
                time.sleep(3)
        except Exception as e:
            print(f"  [RUNPOD] attempt {attempt+1}: {str(e)[:80]}")
            time.sleep(3)
    return None

# HARD RULE (Joe 2026-08-09): shot images must NEVER contain any text. Labels
# (e.g. establishing '/// NAME') are burned by FFmpeg at render time, never in
# the source art. Appended to every shot prompt.
NO_IMAGE_TEXT = (" NO text, NO words, NO letters, NO captions, NO labels, "
                 "NO signage, NO subtitles, NO watermarks, NO typography "
                 "anywhere in the image.")
# Realistic camera depth of field (Joe 2026-08-09): every image should read like
# a real camera shot, not a flat render.
DOF_CLAUSE = (" realistic camera depth of field, natural bokeh background blur, "
              "tack-sharp subject focus, shallow-to-medium depth of field")


def _shot_filename(shot: dict, number: int) -> str:
    """Descriptive shot filename: 'shot{number:02d}_{brief description}.png'
    e.g. 'shot01_hugging_face_switzerland.png' (Joe 2026-08-09). The
    description lives ONLY in the filename - the image itself must stay clean
    (NO_IMAGE_TEXT), and any on-screen label is burned by FFmpeg at render time.
    `number` = the shot's 1-based CANONICAL order (seq) - the same order ffmpeg
    uses to assemble the video. This guarantees the filename always matches the
    frame position, even when shots generate in parallel or narration_idx has
    gaps (Joe 2026-08-09)."""
    name = (shot.get("establishing_name") or "").strip()
    if not name:
        narr = (shot.get("narration") or shot.get("scene") or "")
        words = re.findall(r"[A-Za-z0-9]+", narr)[:4]
        name = "_".join(words)
    slug = re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_").lower()
    slug = re.sub(r"_+", "_", slug)[:50].strip("_")
    if not slug:
        slug = "shot"
    return f"shot{int(number):02d}_{slug}.png"


def _chapter_filename(chapter_num: int, title: str) -> str:
    """Descriptive chapter card filename: 'chapter_{NN}_{slug}.png' e.g.
    'chapter_01_cracking_hugging_face.png' (Joe 2026-08-09). The chapter name
    lives in the FILENAME only - the card image itself stays clean (no baked
    text); the ASS chapter title is burned by FFmpeg at render time."""
    slug = re.sub(r"[^A-Za-z0-9]+", "_", title or "").strip("_").lower()
    slug = re.sub(r"_+", "_", slug)[:50].strip("_")
    if not slug:
        slug = "card"
    return f"chapter_{int(chapter_num):02d}_{slug}.png"


def _reconcile_shot_image(shot, episode_num) -> Optional[str]:
    """Return the shot's real on-disk image path, reconciling against the
    episode folder's deterministic filename. If image_path is missing/stale but
    a valid image exists under _shot_filename, adopt it so resume does NOT
    regenerate a shot whose image was actually generated (Joe 2026-08-15)."""
    p = (shot.get("image_path") or "").strip()
    if p and os.path.isfile(p) and os.path.getsize(p) > 1000:
        return p
    try:
        seq = int(shot.get("seq", 0) or (shot.get("narration_idx", 0) + 1))
        cand = str(_episode_dir(episode_num) / _shot_filename(shot, seq))
        if os.path.isfile(cand) and os.path.getsize(cand) > 1000:
            shot["image_path"] = cand
            return cand
    except Exception:
        pass
    return None


def _reconcile_chapter_card(shot, episode_num) -> Optional[str]:
    """Return the chapter card's real on-disk path, reconciling against the
    deterministic chapter_XX_slug.png filename (same idea as
    _reconcile_shot_image but for chapter title cards). If the stored
    image_path is stale/missing but a valid card exists on disk, adopt it so
    resume does NOT regenerate an already-generated card (Joe 2026-08-16)."""
    p = (shot.get("image_path") or "").strip()
    if p and os.path.isfile(p) and os.path.getsize(p) > 1000 \
            and "chapter_" in os.path.basename(p):
        return p
    try:
        n = int(shot.get("chapter_num", 1))
        title = str(shot.get("chapter_title", "")).strip() or "The Story"
        cand = str(_episode_dir(episode_num) / _chapter_filename(n, title))
        if os.path.isfile(cand) and os.path.getsize(cand) > 1000:
            shot["image_path"] = cand
            return cand
    except Exception:
        pass
    return None


# ---- Prop visual injection (Joe 2026-08-09) ----
# ~200 named props (vaults, libraries, casinos, labs, servers, etc). When a
# chapter title or a shot's narration/scene mentions a prop keyword, its visual
# descriptor is injected into the image prompt so the prop actually appears in
# the frame with correct context (e.g. 'vault' -> a massive steel bank vault).
def _match_prop_visuals(text: str) -> list[str]:
    """Return the visual descriptors for every prop keyword found in `text`."""
    if not text:
        return []
    try:
        from prop_visuals import PROP_VISUALS
    except Exception:
        return []
    low = text.lower()
    # Software/hardware-name false positives (Joe 2026-08-12): 'Unreal Engine 5'
    # and 'Metahuman' are a game engine / tech name, NOT a physical engine. Strip
    # them before matching so the 'engine' prop can never fire on them.
    low = re.sub(r"(?i)unreal\s+engine\s*5?|metahuman", " ", low)
    found = []
    # Longer/compound keys first so 'bank vault' wins over 'vault'/'bank'.
    for key in sorted(PROP_VISUALS, key=len, reverse=True):
        if re.search(rf"\b{re.escape(key)}\b", low):
            found.append(PROP_VISUALS[key])
    return found


def _inject_prop_visuals(text: str) -> str:
    """Build a prop-injection clause from `text`, or '' if no props match."""
    descs = _match_prop_visuals(text)
    if not descs:
        return ""
    return " Include these key objects from the scene: " + "; ".join(descs) + "."

# Machine/engine-structure guard (Joe 2026-08-10): when a shot is about a
# BUSINESS, the image should show the business's BUILDING with its logo, or a
# SCREEN/wall displaying the logo - NOT an abstract complex machine/engine
# structure (the LLM was drifting to "big machine engine type structures" for
# business shots). These keyword sets detect the drift so the prompt can be
# rewritten to a building-with-logo / screen-with-logo scene.
_MACHINE_SLOP_KW = re.compile(
    r"(?i)\b(gears?|gear\s+train|engine\s+block|pistons?|combustion|crankshaft|"
    r"turbine|turbine\s+blades|complex\s+engine|mechanical\s+heart|machinery\s+core|"
    r"industrial\s+gears|macro\s+shot\s+of\s+(?:the\s+)?machinery|internal\s+machinery|"
    r"engine\s+components|big\s+machine|massive\s+machine|machine\s+engine)\b")


def _is_machine_slop(text: str) -> bool:
    """True if the text describes an abstract machine/engine structure (the
    business-shot drift Joe flagged). Used to force a business-building rewrite."""
    if not text:
        return False
    return bool(_MACHINE_SLOP_KW.search(text))


def _is_business_shot_meta(character: str, scene: str, narration: str = "") -> bool:
    """Business-shot detection that works on raw shot-list metadata (before the
    shot dict exists). Mirrors _is_business_shot: business-location keywords in
    the scene, OR a known brand name alongside a location cue."""
    if not scene:
        return False
    sc, narr = scene.lower(), (narration or "").lower()
    if re.search(
            r"(?i)\b(hq|headquarters|head office|office|corporate|company|"
            r"startup|founded|boardroom|executive suite|lobby|factory floor|"
            r"data center|server room|warehouse|office building|signage|"
            r"storefront|lab|the office|their office|at the company)\b", sc):
        return True
    blob = f"{sc} {narr}"
    if any(kw in blob for kw in ("building", "campus", "hq", "headquarters",
                                 "office", "facility", "plant", "factory",
                                 "store", "storefront", "lab", "laboratory",
                                 "studio", "showroom", "warehouse", "floor")):
        _load_brand_manifest()
        for _bn in list(_KNOWN_BRANDS) + list(AI_ORGS):
            if _bn and _bn.lower() in blob:
                return True
    return False


def _business_building_clause(shot: dict) -> str:
    """For a BUSINESS shot, steer the image to a real building with the logo on
    its facade (or a screen/wall showing the logo) instead of an abstract
    machine/engine. Returns an instruction clause, or '' for non-business shots."""
    if not _is_business_shot(shot):
        return ""
    return (" The subject is a REAL business - show its actual building exterior "
            "with the company name/logo on the facade or signage, OR an interior "
            "with the logo displayed on a wall/screen. This is a place people "
            "work, NOT a machine, NOT abstract gears or engine parts, NOT a "
            "complex industrial mechanism - a real building or office.")


def _build_shot_prompt(shot: dict, character_sheets: Optional[dict] = None) -> str:
    """Build the prompt for ONE shot (shared by full gen and resume regen).
    Discovery logic (Joe 2026-08-06):
      - characters (possibly several) -> each described via their archetype
        sheet + which way they're facing
      - location + prop + action always carried by the scene text (always)
      - style injected separately by the caller (_style_inject)
      - refs (which character panel / logo / prop) chosen by _select_shot_refs
    """
    character_sheets = character_sheets or {}
    angle = shot.get("angle", "eye-level")
    cam_desc = ""
    if shot.get("shot_type"):
        cam_desc = f", {shot['shot_type']} framing, {angle} camera angle"
    scene = shot.get("scene", "")
    # ---- GROUND THE IMAGE IN THE ACTUAL NARRATION (Joe 2026-08-10) ----
    # Each shot is ONE spoken SENTENCE with its own image. The image prompt is
    # built from that specific sentence, but the LLM is also given the FULL
    # parent paragraph as CONTEXT so it understands what comes before and after
    # the selected sentence (the other sentences get their own shots generated
    # the same way). The sentence is the subject; the paragraph is context only.
    narration = str(shot.get("narration") or "").strip()
    paragraph = str(shot.get("paragraph_context") or "").strip()
    narr_ctx = ""
    if narration:
        narr_ctx = (
            f" This image is for the sentence the narrator says over THIS shot: "
            f"\"{narration[:900]}\". Build the scene, subject, business, place "
            f"and action to match THIS sentence exactly.")
        if paragraph and paragraph != narration:
            narr_ctx += (
                f" The following is the REST OF THE PARAGRAPH for CONTEXT ONLY - "
                f"it tells you what happens right before and after this sentence, "
                f"so the scene is aware of the surrounding story. It will be "
                f"rendered as its own separate images, so do NOT depict its "
                f"specific actions, only keep the mood, characters and location "
                f"consistent: \"{paragraph[:1200]}\"."
            )
    # PROP VISUALS (Joe 2026-08-09): if the narration/scene names a known prop
    # (vault, library, casino, server, etc), inject its visual descriptor so it
    # appears in the frame with the right context.
    prop_clause = _inject_prop_visuals(f"{narration} {scene}")
    # Establishing shots establish a person or place cleanly - they never get a
    # force-injected prop (Joe 2026-08-12). Without this, the word 'Engine' in
    # 'Unreal Engine 5' (part of every establishing scene) tripped the 'engine'
    # prop and bolted "a complex mechanical engine in cross-section" onto
    # character/location establishing frames.
    if shot.get("is_establishing"):
        prop_clause = ""
    # NO-TEXT clause (Joe 2026-08-09): when a business logo will be attached as
    # an image ref, drop the hard no-text/watermark ban so the logo's wordmark
    # can render (the logo IS allowed text). Otherwise keep NO text so gpt-image-2
    # doesn't hallucinate stray labels/signage.
    if _is_business_shot(shot) or (shot.get("_llm_refs") or {}).get("brands"):
        no_text_clause = " No other text, captions, labels, signage, subtitles or watermarks besides the attached business logo."
    else:
        no_text_clause = NO_IMAGE_TEXT
    # Easter egg: inject the hidden background element into this shot's prompt
    # (set on exactly one shot by _inject_easter_egg).
    egg = shot.get("easter_egg_prompt")
    if egg:
        scene = (scene + " " + egg).strip()
    chars = _parse_shot_characters(shot)
    # CODE-X hardening (Joe 2026-08-09): codex is text-to-image + real-photo
    # refs (no generated panels). The prompt must (a) tell gpt-image-2 to
    # derive each person's face/likeness from the attached reference photo and
    # (b) keep it a SINGLE clean cinematic frame - no panel grids, no reference
    # sheets, no collage. Without this, codex can render the ref as a grid.
    codex_hard = ""
    if _active_image_backend() == "codex":
        codex_hard = (
            " Use the attached reference photo(s) ONLY for each person's face "
            "and identity - keep their likeness true to the reference. "
            "Use the face image as reference only - do not copy it directly "
            "rather use it as inspiration to get the face of the person looking "
            "correct. Render a "
            "SINGLE clean cinematic frame: one person per subject, whole bodies "
            "composed in one scene, NO multi-panel grid, NO character sheet, "
            "NO side-by-side thumbnails, NO repeated copies of the same person, "
            "no split frames, no collage."
        )
    if not chars:
        # No character (establishing/landscape/object/hand-closeup shot) - use
        # the scene-only style with zero human language so no person appears.
        return (
            f"{SCENE_STYLE}. {scene}{cam_desc}.{narr_ctx}{prop_clause} "
            f"{_business_building_clause(shot)}"
            f"16:9 widescreen frame, "
            f"illustration,{DOF_CLAUSE} EXACTLY ONE "
            f"continuous scene, one location, no collage, no split panels, "
            f"no duplicated scenes{no_text_clause}"
        )
    facing_txt = {"left": "facing left", "right": "facing right",
                  "front": "facing the camera", "back": "seen from behind",
                  "behind": "seen from behind"}
    # Bug 1 fix (Joe 2026-08-14): derive ONE per-shot expression + gaze from the
    # narration + scene so the same character isn't rendered with a frozen
    # neutral face in every shot. Deterministic keyword mapping, fail-open to
    # empty (omitted) so the sheet's neutral look is used on no-match.
    expression, gaze = _shot_expression_gaze(narration, scene)
    blocks = []
    for ch in chars:
        name = ch["name"]
        sheet = _sheet_for_name(character_sheets, name)
        cb = _character_prompt_block(sheet, angle, expression, gaze) if sheet else ""
        if not cb:
            cb = f"a person named {name}"
            if expression:
                cb += f", expression: {expression}"
            if gaze:
                cb += f", eyes: {gaze}"
        facing = facing_txt.get(ch["facing"], "facing the camera")
        blocks.append(f"{cb} ({facing})")
    char_part = " ".join(blocks)
    # Bug 3 rec (Joe 2026-08-14): resolve the anatomy conflict + hands. For the
    # Arcane/stylized profiles RENDER_STYLE's photoreal-anatomy clauses fight the
    # stylized look and drive gpt-image-2 hand hallucinations. Use the style-aware
    # render style (strips photoreal skin/anatomy language for stylized profiles)
    # and, on hand-visible shots, append an explicit anatomy-correct-hands clause.
    render_style = _active_render_style()
    hands_clause = ""
    if _shot_shows_hands(shot):
        hands_clause = (" Anatomy-correct hands: exactly five natural fingers per "
                        "hand, correct proportions, no extra, fused, webbed or "
                        "claw-like fingers, no deformed or misplaced digits.")
    return (
        f"{render_style}. {char_part}. {scene}{cam_desc}{codex_hard}.{narr_ctx}{prop_clause} "
        f"{_business_building_clause(shot)}"
        f"16:9 widescreen frame, "
        f"illustration,{DOF_CLAUSE} EXACTLY ONE continuous "
        f"scene, no collage, no duplicated figures{hands_clause}{no_text_clause}"
    )


def _get_output_resolution() -> tuple:
    """(W, H) for the final image/video output - RESOLUTION env var.
    1440p (default), 1080p or 4K (3840x2160). Overridden by a per-run
    prompt that is persisted in resume state."""
    r = os.environ.get("RESOLUTION", "1440p").strip().lower()
    if r.startswith("4k") or r in ("2160p", "uhd"):
        return (3840, 2160)
    if r in ("1440p", "2k", "qhd"):
        return (2560, 1440)
    return (1920, 1080)


def _ask_resolution() -> str:
    """Interactive resolution selection (1440p default / 1080p / 4K) - affects
    the image upscale target AND the final FFmpeg video output. RESOLUTION env
    var overrides the prompt; returns the chosen key ('1440p'/'1080p'/'4k')."""
    if os.environ.get("RESOLUTION"):
        r = os.environ.get("RESOLUTION").strip().lower()
        if r.startswith("4k") or r in ("2160p", "uhd"):
            return "4k"
        if r in ("1440p", "2k", "qhd"):
            return "1440p"
        return "1080p"
    print("\n  Output resolution (affects image upscale target + final video):")
    while True:
        resp = input("  1440p, 1080p or 4K? [1440p]: ").strip().lower()
        if resp in ("4k", "2160p", "uhd", "4"):
            return "4k"
        if resp in ("1440p", "2k", "qhd", ""):
            return "1440p"
        if resp in ("1080p", "1080", "hd"):
            return "1080p"
        print(f"  [WARN] '{resp}' not recognised - enter 1440p, 1080p or 4K")


def _ask_image_regen() -> tuple[bool, bool]:
    """Ask whether to RESUME or REGENERATE the episode's images, separately
    for SHOT images and CHAPTER card images (Joe 2026-08-09).

    Returns (regen_shots, regen_chapters). Env overrides:
      REGEN_IMAGES / REGEN_SHOTS ('1'/'yes') = regen shots
      REGEN_CHAPTERS ('1'/'yes') = regen chapter cards
    If REGEN_IMAGES is set but REGEN_CHAPTERS is not, both follow REGEN_IMAGES.
    """
    env_shots = os.environ.get("REGEN_SHOTS", "") or os.environ.get("REGEN_IMAGES", "")
    if env_shots:
        s = env_shots.strip().lower() in ("1", "yes", "y", "true")
        c = os.environ.get("REGEN_CHAPTERS", "").strip().lower() in ("1", "yes", "y", "true")
        if not os.environ.get("REGEN_CHAPTERS"):
            c = s  # legacy: REGEN_IMAGES controls both
        return s, c
    print("\n  Image generation mode (shot images vs chapter cards are separate):")
    print("  [RESUME]  keep already-rendered images, only generate the missing ones")
    print("  [REGEN]   re-generate ALL images, overwriting existing ones")
    def _ask(label: str) -> bool:
        while True:
            resp = input(f"  {label}? (R)euse / (E)egenerate [R]: ").strip().lower()
            if resp in ("", "r", "resume", "reuse"):
                return False
            if resp in ("e", "regen", "regenerate"):
                return True
            print(f"  [WARN] '{resp}' not recognised - enter R (reuse) or E (regenerate)")
    regen_shots = _ask("Reuse or regenerate SHOT images")
    regen_chapters = _ask("Reuse or regenerate CHAPTER CARD images")
    return regen_shots, regen_chapters


def _ask_style_selection(current_style: str = "") -> str:
    """Ask which style profile to use for this run's images. Shows the current
    (resume) style as the default. Returns the chosen style NAME (lowercase).
    A chosen style that differs from `current_style` means the images must be
    re-generated (handled by the caller via REGEN_IMAGES). STYLE env override."""
    profiles = _load_style_profiles()
    names = sorted(profiles.keys())
    if os.environ.get("STYLE") or os.environ.get("STYLE_PROFILE"):
        return _active_style_name()
    cur = current_style.lower() if current_style else _active_style_name()
    print("\n  Style profile for this run's images:")
    print(f"  current: {cur or 'default (arcane)'}")
    for i, n in enumerate(names, 1):
        print(f"    {i:2}. {n:16} {profiles[n][:50]}{'...' if len(profiles[n]) > 50 else ''}")
    print("  Enter a number, a style name, or press Enter to keep current.")
    while True:
        resp = input(f"  Style (Enter = {cur or 'arcane'}): ").strip().lower()
        if not resp:
            return cur or "arcane"
        if resp.isdigit():
            i = int(resp)
            if 1 <= i <= len(names):
                return names[i - 1]
        elif resp in names:
            return resp
        print(f"  [WARN] '{resp}' is not a known style - enter a number or name "
              f"(or Enter to keep '{cur or 'arcane'}')")


def _ask_thumbnail_backend() -> tuple[str, str]:
    """Ask which image-gen provider to use for the YouTube THUMBNAIL.
    Sets THUMBNAIL_BACKEND / THUMBNAIL_MODEL (env override skips the prompt).
    Returns (backend, model)."""
    if os.environ.get("THUMBNAIL_BACKEND"):
        b = os.environ["THUMBNAIL_BACKEND"].strip().lower()
        m = os.environ.get("THUMBNAIL_MODEL", "").strip().lower() or None
        if b in ("local", "runpod", "fal", "codex"):
            try:
                import providers
                _, _m = providers._resolve_thumbnail()
                return b, m or _m
            except Exception:
                return b, m or "flux-schnell"
    print("\n  Thumbnail image-gen provider (for the YouTube thumbnail):")
    print("    1. local     - ComfyUI (free, your GPU)")
    print("    2. fal       - fal.ai GPT Image 2 (best text rendering)")
    print("    3. runpod    - RunPod z-image-turbo")
    print("    4. codex     - Codex CLI /imagegen GPT Image 2 (default, if installed)")
    while True:
        resp = input("  Pick 1-4 [4]: ").strip().lower()
        if resp in ("", "4", "codex"):
            return "codex", "gpt-image-2"
        if resp in ("2", "fal"):
            return "fal", "gpt-image-2"
        if resp in ("1", "local"):
            return "local", "krea2-turbo"
        if resp in ("3", "runpod"):
            return "runpod", "z-image-turbo"
        if resp in ("4", "codex"):
            return "codex", "gpt-image-2"
        print(f"  [WARN] '{resp}' not recognised - enter 1, 2, 3 or 4")


def _ask_image_backend() -> tuple[str, str]:
    """Ask which image-gen provider to use for the EPISODE IMAGES (all shots).
    Sets IMAGE_BACKEND / IMAGE_MODEL (env override skips the prompt).
    Returns (backend, model).

    Default is local (ComfyUI Krea 2 Turbo) because the shots use the
    character-identity panels as reference images, which only the local backend
    honours. Cloud backends (fal / runpod / codex) are text-to-image, so they
    drop the identity/face refs.
    """
    if os.environ.get("IMAGE_BACKEND"):
        b = os.environ["IMAGE_BACKEND"].strip().lower()
        m = os.environ.get("IMAGE_MODEL", "").strip().lower() or None
        if b in ("local", "runpod", "fal", "codex"):
            try:
                import providers
                _, _m = providers._resolve_image(b, m or None)
                return b, m or _m
            except Exception:
                return b, m or "krea2-turbo"
    print("\n  Episode image-gen provider (for ALL shot images):")
    print("    1. local     - ComfyUI Krea 2 Turbo (default, free, keeps face/identity refs)")
    print("    2. fal       - fal.ai (flux / gpt-image-2, text-to-image only)")
    print("    3. runpod    - RunPod z-image-turbo (text-to-image only)")
    print("    4. codex     - Codex CLI /imagegen (text-to-image only)")
    while True:
        resp = input("  Pick 1-4 [1]: ").strip().lower()
        if resp in ("", "1", "local"):
            return "local", "krea2-turbo"
        if resp in ("2", "fal"):
            print("  fal models: flux-dev, flux-schnell, nano-banana-2, z-image-turbo, gpt-image-2")
            m = input("  fal model? [flux-schnell]: ").strip().lower() or "flux-schnell"
            if m not in ("flux-dev", "flux-schnell", "nano-banana-2", "z-image-turbo", "gpt-image-2"):
                print(f"  [WARN] '{m}' unknown - using flux-schnell")
                m = "flux-schnell"
            return "fal", m
        if resp in ("3", "runpod"):
            print("  runpod models: z-image-turbo, nano-banana-2")
            m = input("  runpod model? [z-image-turbo]: ").strip().lower() or "z-image-turbo"
            if m not in ("z-image-turbo", "nano-banana-2"):
                print(f"  [WARN] '{m}' unknown - using z-image-turbo")
                m = "z-image-turbo"
            return "runpod", m
        if resp in ("4", "codex"):
            return "codex", "gpt-image-2"
        print(f"  [WARN] '{resp}' not recognised - enter 1, 2, 3 or 4")


def _black_placeholder(episode_num: int) -> str:
    """WxH pure-black PNG used for chapter title placeholder clips."""
    W_RES, H_RES = _get_output_resolution()
    ep_dir = _episode_dir(episode_num)
    ep_dir.mkdir(parents=True, exist_ok=True)
    out = str(ep_dir / "_black.png")
    if os.path.isfile(out) and os.path.getsize(out) > 1000:
        return out
    from PIL import Image
    Image.new("RGB", (W_RES, H_RES), (0, 0, 0)).save(out)
    return out


def _chapter_narration_context(shots: list[dict], chapter_num: int) -> str:
    """All narration text that falls inside ONE chapter (for chapter-card art).

    Walks the ordered shot list: from the given chapter marker shot until the
    NEXT chapter marker (or the end), collect the narration of every content
    shot so the chapter-card art is grounded in what the narrator actually says
    in that chapter - not just a bare title (Joe 2026-08-09).
    """
    idxs = [i for i, s in enumerate(shots) if s.get("is_chapter")]
    if not idxs:
        return ""
    pos = None
    for i in idxs:
        if int(shots[i].get("chapter_num", 0)) == int(chapter_num):
            pos = i
            break
    if pos is None:
        return ""
    end = next((i for i in idxs if i > pos), len(shots))
    paras = [str(shots[j].get("narration", "")).strip()
             for j in range(pos + 1, end)
             if str(shots[j].get("narration", "")).strip()]
    return " ".join(paras)[:1200]


def _detect_brand_in_chapter(title: str, context: str,
                             brand_assets: dict) -> Optional[str]:
    """Find the single brand (if any) a chapter card should reference.

    Joe 2026-08-09: the logo image-ref is only attached when the chapter TITLE
    itself actually names the business (e.g. 'hugging face vaults' -> Hugging
    Face). The narration context may mention a company that isn't in the title
    - that should inform the background scene, NOT attach a logo (the logo is
    a deliberate on-card credit tied to the chapter's subject, and the title is
    the reliable signal). Returns the brand name or None.
    """
    title_blob = f"{title}".lower()
    # 1. AI-org aliases (Hugging Face, OpenAI, etc.) - title must name it.
    for org, (aliases, _q) in AI_ORGS.items():
        for a in aliases:
            if re.search(rf"\b{re.escape(a)}\b", title_blob):
                if _find_logo(org):
                    return org
    # 2. Extracted/known brands - only if the TITLE names it AND we have a logo.
    for name in list(_KNOWN_BRANDS) + list(brand_assets or {}):
        if name and name.lower() in title_blob and _find_logo(name):
            return name
    return None


def _llm_chapter_bg_prompt(title: str, chapter_num: int,
                           topic: str = None,
                           context: str = "") -> str:
    """Ask the local LLM to imagine a striking background scene for a chapter.

    The chapter title plus its actual narration context is given - the LLM
    invents a cinematic, thematically-matched backdrop (setting, mood, objects)
    that the title card text will sit on top of. Returns a short image-prompt
    string, or '' if the LLM is unreachable / returns nothing usable.
    """
    if not topic:
        topic = _IMG_TOPIC
    if not (title or "").strip():
        return ""
    try:
        ctx_extra = (f" Here is the chapter's narration content to ground the "
                     f"scene in exactly what happens in this chapter:\n"
                     f"{context[:900]}") if context.strip() else ""
        msgs = [
            {"role": "system",
             "content": ("You are a documentary title-card art director. Given a "
                         "chapter title, the EPISODE'S ARTICLE TOPIC, and the "
                         "chapter's narration content, describe a SINGLE striking "
                         "cinematic background scene (setting, mood, key objects, "
                         "lighting) that matches BOTH the title's theme AND belongs "
                         "to the story's world. Ground it in the actual places and "
                         "objects the narration describes; never import a setting or "
                         "subject from outside this story. Do NOT drift to an "
                         "unrelated subject. Return ONLY a 1-2 sentence image prompt. "
                         "No text, no dialogue, no characters' faces, no words, no "
                         "watermarks.")},
            {"role": "user",
             "content": f"ARTICLE TOPIC: {topic or '(not provided)'}\n"
                        f"Chapter {chapter_num}: {title}.{ctx_extra}\n"
                        f"Background scene:"},
        ]
        out = _llm_chat(msgs, max_tokens=140, temp=0.7).strip()
        out = re.sub(r"\s+", " ", out).strip(" '\"")
        if not out or len(out) < 8 or out.lower().startswith("chapter"):
            return ""
        return out[:320]
    except Exception:
        return ""


def _generate_chapter_card(shot: dict, episode_num: int,
                           topic: str = None,
                           shots: Optional[list] = None,
                           brand_assets: Optional[dict] = None,
                           character_sheets: Optional[dict] = None) -> Optional[str]:
    """Render a chapter TITLE CARD image via the active image backend.

    GPT Image 2 / Codex CLI renders text very well, so when IMAGE_BACKEND is
    codex (or fal gpt-image-2) we generate a real 'CHAPTER N -- title' card as
    the shot's image (shown for the whole time the narrator reads the chapter),
    instead of the old black placeholder + ASS burn. Returns the card path, or
    None when the backend shouldn't render text cards (local Krea -> falls back
    to the black placeholder + ASS burn).

    PREMIUM ART LOGIC (Joe 2026-08-09):
      - The card background is generated from the chapter title PLUS its actual
        narration context (the shots that fall inside the chapter), so the art
        matches what the narrator says, not just a bare title.
      - If the chapter is about a real business (e.g. 'hugging face vaults' ->
        the Hugging Face company), its real logo is attached as an image ref
        and the prompt places the logo on the OUTSKIRTS of the frame (top
        middle ~15%, top-left, top-right) - never in the centre, which stays
        open for the title text overlaid later.
    """
    backend = _active_image_backend()
    if backend not in ("codex", "fal"):
        # Local Krea / runpod render text poorly - keep the black placeholder
        # so the ASS chapter card is burned in pass 2 (split_node_titles).
        return None
    n = int(shot.get("chapter_num", 1))
    title = str(shot.get("chapter_title", "")).strip() or "The Story"
    W_RES, H_RES = _get_output_resolution()
    ep_dir = _episode_dir(episode_num)
    ep_dir.mkdir(parents=True, exist_ok=True)
    out = str(ep_dir / _chapter_filename(n, title))
    # REGEN_CHAPTERS is the ONLY control for chapter-card regeneration (Joe
    # 2026-08-16). REGEN_IMAGES (shots) must NOT cascade into cards - the user
    # answers shots and chapter cards as two separate resume questions, so a
    # shot regen (e.g. a style change) must never wipe existing cards they
    # chose to keep.
    _regen = os.environ.get("REGEN_CHAPTERS", "").strip().lower() in ("1", "yes", "y", "true")
    if _regen and os.path.isfile(out):
        try:
            os.remove(out)
            print(f"  [CARD] REGEN - dropping stale chapter {n:02d} card")
        except OSError:
            pass
    if os.path.isfile(out) and os.path.getsize(out) > 1000:
        return out
    # ---- PREMIUM: chapter context + business logo ref (Joe 2026-08-09) ----
    context = _chapter_narration_context(shots or [], n)
    brand = _detect_brand_in_chapter(title, context, brand_assets or {})
    card_refs: list[str] = []
    brand_clause = ""
    # PROP VISUALS (Joe 2026-08-09): if the chapter title/context names a known
    # prop (vault, library, casino, server...), inject its visual descriptor so
    # the prop appears in the card background (e.g. 'hugging face vaults' ->
    # a massive vault).
    card_prop_clause = _inject_prop_visuals(f"{title} {context}")

    if brand:
        logo = _find_logo(brand)
        if logo and os.path.isfile(logo):
            card_refs.append(logo)
            # Joe 2026-08-09: let GPT Image 2 integrate the logo naturally into
            # the full composition (its normal behaviour) - NO manual placement
            # instructions. Just name it so the model folds it in where it fits.
            brand_clause = (
                f" The official {brand} company logo is included in the scene, "
                f"naturally integrated into the composition like a production "
                f"detail.")
            print(f"  [CARD] chapter {n:02d} brand ref: {brand} "
                  f"({os.path.basename(logo)})")
    # COOL BACKGROUND (Joe 2026-08-09): ask the local LLM to imagine a striking,
    # thematically-matched background for this chapter from its title + context.
    # The style prompt is injected as a prefix so the bg matches the channel's
    # look. Falls back to a clean dark-moody background if the LLM is
    # unreachable or returns nothing usable.
    bg = _llm_chapter_bg_prompt(title, n, topic, context)
    # When a logo ref is attached, drop the anti-text/watermark hard ban so the
    # logo's wordmark can render naturally (GPT Image 2 integrates it into the
    # full composition, Joe 2026-08-09). Otherwise keep NO text to stop stray
    # hallucinated words.
    _no_text = ("NO text, NO words, NO letters, NO titles, no watermark. "
                if not card_refs else
                "No other text besides the {brand} logo.".format(brand=brand) if brand else
                "No other text, no watermarks.")
    if bg:
        # MAIN PROMPT = the chapter-title-derived background FIRST, then the
        # channel style + logo/brand injections AFTER (Joe 2026-08-09). The
        # title is the anchor; style/brand are finishing touches, never the lead.
        prompt = (
            f"{bg}.{card_prop_clause} A clean chapter card background with "
            f"{_no_text} The "
            f"composition is a striking themed backdrop with plenty of open "
            f"negative space in the CENTRE for text to be overlaid later. "
            f"minimal clutter, no people as the "
            f"main subject. 16:9 widescreen background, "
            f"{DOF_CLAUSE}."
            f" {_style_inject(allow_logo=bool(card_refs))}.{brand_clause}"
        )
        print(f"  [CARD] chapter {n:02d} LLM background prompt generated")
    else:
        prompt = (
            "A chapter card background. Solid near-black "
            "background with a subtle central glow "
            "in the centre."
            f"{card_prop_clause}"
            f" {_style_inject()}.{brand_clause} {_no_text} "
            "Clean, minimal, "
            "professional broadcast background plate, no photos, no people, no "
            "objects, open negative space in the centre. 16:9 widescreen, "
            f"{DOF_CLAUSE}."
        )
    # LLM relevance gate: cross-check the card background against the article
    # topic so it matches the STORY, not an off-topic scene (Joe 2026-08-09).
    prompt = _ensure_card_prompt_relevant(prompt, title, n, topic)
    print(f"  [CARD] rendering chapter {n:02d} title card via {backend}...")
    seed = 90000 + n * 137 + episode_num
    ok = _krea_generate(prompt, seed, out, ref_images=card_refs or None, denoise=1.0,
                        upscale=True, width=W_RES, height=H_RES,
                        ref_mode="img2img", image_size="landscape_16_9")
    if ok and os.path.isfile(out) and os.path.getsize(out) > 1000:
        return out
    print(f"  [CARD] chapter {n:02d} card failed - using black placeholder")
    return None


def _active_image_backend() -> str:
    """Current IMAGE_BACKEND (default 'local')."""
    return (os.environ.get("IMAGE_BACKEND", "") or "local").strip().lower()


def _krea_generate(prompt: str, seed: int, out_path: str,
                   ref_images: Optional[list] = None, denoise: float = 0.55,
                   upscale: bool = True, timeout: int = 1800,
                   steps: int = 8, cfg: float = 1.0,
                   width: int = 1280, height: int = 720,
                   ref_mode: str = "img2img",
                   ref_method: str = "index_timestep_zero",
                   ref_boost: float = 4.0, grounding_px: int = 1024,
                   ref_images_b: Optional[list] = None,
                   negative_prompt: str = "",
                   image_size: Optional[str] = None) -> bool:
    """Generate one image, routed through the unified provider layer.

    Backend is selected at runtime by IMAGE_BACKEND (default 'local' ->
    ComfyUI Krea 2 Turbo). Set IMAGE_BACKEND=runpod or =fal or =codex to
    render shots through a cloud provider instead. ref_images/ref_mode are
    honoured by local AND codex (which attaches refs via `-i`); runpod/fal
    are text-to-image.
    """
    prompt = _sanitize_image_prompt(prompt)
    backend = _active_image_backend()
    # Codex (and cloud) outputs can come out smaller than requested - when the
    # caller left the 1280x720 default, aim the upscale at the OUTPUT res so a
    # codex shot reaches 1920x1080 (or 4K), matching the local in-graph path.
    if upscale and width == 1280 and height == 720:
        W_RES, H_RES = _get_output_resolution()
        if backend in ("codex", "fal", "runpod"):
            width, height = W_RES, H_RES
    try:
        import providers
    except Exception as e:
        print(f"  [IMG] providers import failed: {e}")
        return False
    return providers.generate_image(
        prompt, seed, out_path, backend=backend,
        ref_images=ref_images, denoise=denoise, upscale=upscale,
        timeout=timeout, steps=steps, cfg=cfg, width=width, height=height,
        ref_mode=ref_mode, ref_method=ref_method, ref_boost=ref_boost,
        grounding_px=grounding_px, ref_images_b=ref_images_b,
        negative_prompt=negative_prompt, image_size=image_size)


def _generate_motion_clip(prompt: str, out_path: str,
                          image_path: Optional[str] = None,
                          duration: int = 6, timeout: int = 1200) -> bool:
    """Generate an AI motion clip from a shot (or text prompt) via the
    selected VIDEO_BACKEND (runpod/fal). For local video, a ComfyUI video
    workflow must be installed. Returns True on success.

    Wired via env vars: VIDEO_BACKEND (default runpod), VIDEO_MODEL."""
    prompt = _sanitize_image_prompt(prompt)
    try:
        import providers
    except Exception as e:
        print(f"  [VID] providers import failed: {e}")
        return False
    image_url = None
    if image_path:
        # Upload the shot to a public host so the cloud model can fetch it.
        image_url = _upload_to_public_url(image_path)
        if not image_url:
            print(f"  [VID] could not upload {os.path.basename(image_path)} "
                  f"for image-to-video - generating from text only")
    return providers.generate_video(
        prompt, out_path, image_url=image_url, duration=duration,
        timeout=timeout)


def _upload_to_public_url(image_path: str) -> Optional[str]:
    """Host an image for image-to-video cloud providers. Tries 0x0.st
    (no key) and returns a public HTTPS URL, else None."""
    import urllib.parse
    try:
        with open(image_path, "rb") as f:
            data = f.read()
        boundary = "----splitnode" + uuid.uuid4().hex[:12]
        body = (f"--{boundary}\r\nContent-Disposition: form-data; "
                f"name=\"file\"; filename=\"shot.png\"\r\n"
                f"Content-Type: image/png\r\n\r\n").encode() + data + \
               f"\r\n--{boundary}--\r\n".encode()
        req = urllib.request.Request(
            "https://0x0.st", data=body, method="POST",
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            url = resp.read().decode().strip()
            return url if url.startswith("http") else None
    except Exception as e:
        print(f"  [VID] upload failed: {e}")
        return None


def _vision_available() -> bool:
    """LM Studio vision model loaded? (gemma vision). Never loads it here."""
    try:
        req = urllib.request.Request("http://localhost:1234/v1/models", method="GET")
        with urllib.request.urlopen(req, timeout=4) as r:
            data = json.loads(r.read().decode())
        ids = [m.get("id", "") for m in data.get("data", [])]
        return any(("gemma" in m and "vision" in m) or "gemma-4-e4b" in m
                   for m in ids)
    except Exception:
        return False


def _audit_real_photo(image_path: str, char_name: str, role: str) -> bool:
    """Ask the local vision LLM (gemma-4-e4b, same as script gen) to audit a
    real-person photo candidate:
      - does it actually show the person?
      - is it clean of text / logos / watermarks?
    Reply format: PERSON:YES/NO TEXT:YES/NO (TEXT:YES = text/logo/watermark
    PRESENT -> reject). Returns True only when the photo passes BOTH checks.
    When the vision model isn't loaded, accept best effort (True) - the audit
    activates automatically once LM Studio serves the gemma model."""
    try:
        import base64
        b64 = base64.b64encode(Path(image_path).read_bytes()).decode()
        body = json.dumps({
            "model": "gemma-4-e4b-uncensored-hauhaucs-aggressive",
            "messages": [{"role": "user", "content": [
                {"type": "text", "text":
                    "Audit this photograph for a documentary cast reference. "
                    "Answer with exactly two lines:\n"
                    f"PERSON: YES or NO - is this a real photograph of "
                    f"{char_name} ({role or 'the person in the story'})?\n"
                    "TEXT: YES or NO - is there ANY text, logo, watermark, "
                    "caption, channel badge or overlay visible in the image?"},
                {"type": "image_url", "image_url": {"url":
                    f"data:image/jpeg;base64,{b64}"}},
            ]}],
            "max_tokens": 12, "temperature": 0,
        }).encode()
        req = urllib.request.Request(
            "http://localhost:1234/v1/chat/completions", data=body,
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as r:
            out = json.loads(r.read().decode())
        ans = out["choices"][0]["message"]["content"].strip()
        person = re.search(r"PERSON:\s*(YES|NO)", ans, re.I)
        text = re.search(r"TEXT:\s*(YES|NO)", ans, re.I)
        # REJECT ONLY ON EXPLICIT NO. When the vision model returns something
        # unparseable or uncertain (person=? / blank / no match), accept best
        # effort - the model often fails to render the strict format, and
        # rejecting on uncertainty means NO real ref is ever accepted (and the
        # pipeline burns 99 candidate downloads trying). Only a clear
        # "PERSON: NO" or "TEXT: YES" rejects.
        person_rejected = bool(person and person.group(1).upper() == "NO")
        text_rejected = bool(text and text.group(1).upper() == "YES")
        p_label = person.group(1) if person else "?"
        t_label = "PRESENT" if text_rejected else ("clean" if text else "?")
        print(f"  [REALREF] audit: person={p_label} "
              f"text/logo/watermark={t_label}")
        return not (person_rejected or text_rejected)
    except Exception:
        return True


REAL_REFS_DIR = PROJECT_DIR / "cast_refs" / "real"


def _serpapi_key() -> str:
    """SerpAPI key: env -> project .env -> AdsDoctorCRM/.env.local."""
    k = os.environ.get("SERPAPI_API_KEY", "").strip()
    if k:
        return k
    for p in (PROJECT_DIR / ".env",
              Path(os.path.expanduser("~")) / "AdsDoctorCRM" / ".env.local"):
        if p.is_file():
            for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
                if line.startswith("SERPAPI_API_KEY="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def _active_style_name() -> str:
    """Return the currently selected style profile NAME (lowercase), or '' for
    the default/custom. Reads STYLE / STYLE_PROFILE env, then the resume style.

    Handles the case where the resume state stored the FULL DESCRIPTION text
    (e.g. "stylized hand-painted comic realism, cel-shaded 3d...") instead of
    the profile name "arcane" - in that case it maps the description back to
    the matching profile name so "picking arcane" doesn't falsely register as a
    style change and force a full image re-generate (Joe 2026-08-09)."""
    profiles = _load_style_profiles()
    sel = (os.environ.get("STYLE") or os.environ.get("STYLE_PROFILE") or "").strip()
    if not sel and _RESUME_STYLE:
        sel = str(_RESUME_STYLE)
    low = sel.lower()
    if low in profiles:
        return low
    # Stored value may be a full description text - find which profile it is.
    for name, desc in profiles.items():
        if desc and desc.lower() in low or (low and low in desc.lower()):
            return name
    return low  # custom free-form tag used verbatim


def _is_mannequin_style() -> bool:
    return _active_style_name() == "mannequin"

def _is_roman_statue_style() -> bool:
    return _active_style_name() == "roman-statue"

def _look_panels_spec() -> tuple[list, str]:
    """Return (panels_spec, look_label) for the active material style
    (mannequin or roman-statue). Both share the same real-face generation
    path - only the prompt wording differs."""
    if _is_roman_statue_style():
        return ROMAN_STATUE_PANELS, "roman-statue"
    return MANNEQUIN_PANELS, "mannequin"


def _serpapi_web_snippets(query: str, num: int = 3) -> list[str]:
    """Quick SerpAPI GOOGLE WEB search (not images). Returns the top result
    snippets. Used to fetch a text hair description for the mannequin style
    (no image ref - the mannequin look is prompt-driven)."""
    key = _serpapi_key()
    if not key:
        return []
    import urllib.parse as _up
    q = _up.quote(query)
    try:
        url = (f"https://serpapi.com/search.json?engine=google&q={q}"
               f"&api_key={key}&num={num}")
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=25) as r:
            data = json.loads(r.read().decode())
        snippets: list[str] = []
        kb = data.get("knowledge_graph", {}) or {}
        for f in ("description", "title", "heading"):
            if kb.get(f):
                snippets.append(str(kb[f]))
        for res in data.get("organic_results", [])[:num]:
            sn = res.get("snippet", "").strip()
            if sn:
                snippets.append(sn)
        return [s for s in snippets if s][:num + 2]
    except Exception as e:
        print(f"  [HAIR] serpapi web search failed ({str(e)[:70]})")
        return []


def _describe_hair_text(char_name: str, role: str,
                        sheet: Optional[dict] = None) -> str:
    """Text hair description for the mannequin style (NO image ref).

    Resolution order:
      1. quick SerpAPI web search for the real person's hair -> ask the local
         LLM to turn the top snippets into ONE short hair sentence
      2. fall back to the archetype's static 'hair' field (always present)
    Returns a non-empty string usable directly in a mannequin panel prompt.
    """
    sheet = sheet or {}
    arch_hair = (sheet.get("hair") or "").strip()
    query = f"{char_name} hair".strip() or char_name
    snips = _serpapi_web_snippets(query, num=3)
    if snips:
        try:
            text = _llm_chat([
                {"role": "system", "content":
                 "You extract factual physical descriptions from search results. "
                 "From the given search snippets about a real person, output EXACTLY "
                 "ONE short sentence (max 18 words) describing ONLY their hair - "
                 "colour, length, style, texture. If the snippets mention no hair, "
                 "reply with a single period '.'"},
                {"role": "user", "content": "\n".join(snips)}
            ], max_tokens=80, temp=0.2).strip()
            # Reject meta-answers / non-descriptions; fall back to the archetype.
            _META = ("not described", "not mentioned", "no information",
                     "does not mention", "not explicitly", "isn't mentioned",
                     "snippets", "the search", "a period",
                     "single period", "reply with")
            text = text.strip().strip(".")
            if text and len(text) > 3 and not any(
                    m in text.lower() for m in _META):
                print(f"  [HAIR] {char_name}: '{text}' (from web search)")
                return text
            print(f"  [HAIR] {char_name}: web snippet had no hair info - "
                  f"archetype fallback")
        except Exception as e:
            print(f"  [HAIR] llm extract failed ({str(e)[:60]})")
    if arch_hair:
        print(f"  [HAIR] {char_name}: archetype fallback '{arch_hair[:60]}'")
        return arch_hair
    return "styled hair"


def _google_images_candidates(char_name: str, role: str) -> list[str]:
    """Google Images search via SerpAPI (Joe's key, ~$0.01/query).
    Returns image URLs (original full-size preferred, thumbnail fallback)."""
    key = _serpapi_key()
    if not key:
        print("  [REALREF] no SERPAPI_API_KEY - using Openverse fallback")
        return []
    import urllib.parse as _up
    q = _up.quote(f"{char_name} {role}".strip() or char_name)
    try:
        url = (f"https://serpapi.com/search.json?engine=google_images&q={q}"
               f"&api_key={key}&ijn=0&num=6")
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read().decode())
        out: list[str] = []
        for res in data.get("images_results", []):
            if res.get("original"):
                out.append(res["original"])
            elif res.get("thumbnail"):
                out.append(res["thumbnail"])
        if out:
            print(f"  [REALREF] google images: {len(out)} candidates for {char_name}")
        return out
    except Exception as e:
        print(f"  [REALREF] serpapi failed ({str(e)[:70]})")
        return []


def _openverse_candidates(char_name: str, role: str) -> list[str]:
    import urllib.parse as _up
    queries = [char_name]
    if role and role.lower() not in char_name.lower():
        queries.append(f"{char_name} {role}")
    urls: list[str] = []
    for q in queries:
        qq = _up.quote(q)
        try:
            req = urllib.request.Request(
                f"https://api.openverse.org/v1/images/?q={qq}&page_size=6"
                f"&license_type=all",
                headers={"User-Agent": "splitnode-doc-pipeline/1.0"})
            with urllib.request.urlopen(req, timeout=25) as r:
                data = json.loads(r.read().decode())
            hits = [res.get("url") or res.get("thumbnail")
                    for res in data.get("results", []) if res]
            urls += hits
            if hits:
                break
        except Exception as e:
            print(f"  [REALREF] openverse search '{q}' failed ({str(e)[:70]})")
    return urls


def _is_real_image(path: str) -> bool:
    """Return True if `path` is a decodable image file. Guards against HTML
    redirects / error pages / truncated downloads saved with a .jpg extension
    (e.g. Instagram lookaside CDN returning an HTML page) - those crash the
    ComfyUI LoadImage node with PIL.UnidentifiedImageError and silently kill
    every character face panel."""
    try:
        from PIL import Image
        with Image.open(path) as im:
            im.load()
        return True
    except Exception:
        return False


# Domains/CDNs that routinely serve HTML/redirect/403 instead of a usable
# real-photo image (Instagram widget, TikTok API, gstatic thumbnails, Google
# image proxies). Skipped before any download to avoid burning candidates.
_BAD_REALREF_DOMAINS = (
    "lookaside.instagram.com", "tiktok.com/api", "encrypted-tbn0.gstatic.com",
    "googleusercontent.com", "ytimg.com", "imgur.com", "redd.it",
    "pbs.twimg.com", "facebook.com", "fbcdn.net", "gstatic.com",
)


def _bad_realref_url(u: str) -> bool:
    return any(d in u.lower() for d in _BAD_REALREF_DOMAINS)


_REALREF_FAIL_FILE = PROJECT_DIR / "cast_refs" / "real" / "_failures.json"


def _load_realref_failures() -> set:
    try:
        if _REALREF_FAIL_FILE.is_file():
            return set(json.loads(_REALREF_FAIL_FILE.read_text()))
    except Exception:
        pass
    return set()


def _save_realref_failure(char_name: str):
    try:
        fails = _load_realref_failures()
        fails.add(char_name.lower())
        _REALREF_FAIL_FILE.parent.mkdir(parents=True, exist_ok=True)
        _REALREF_FAIL_FILE.write_text(json.dumps(sorted(fails)))
    except Exception:
        pass


def _clear_realref_failure(char_name: str):
    """Drop a character from the cached no-real-ref set so a fresh search is
    attempted next time (used when a prior run had the internet off)."""
    try:
        fails = _load_realref_failures()
        if char_name.lower() in fails:
            fails.discard(char_name.lower())
            _REALREF_FAIL_FILE.parent.mkdir(parents=True, exist_ok=True)
            _REALREF_FAIL_FILE.write_text(json.dumps(sorted(fails)))
    except Exception:
        pass


def _find_real_reference(char_name: str, role: str) -> Optional[str]:
    """Search GOOGLE IMAGES (SerpAPI, Openverse fallback) for a photo of the
    REAL person from the story and cache it to cast_refs/real/. Returns None
    when nothing usable is found (the sheet then falls back to txt2img)."""
    safe = re.sub(r"[^A-Za-z0-9]+", "_", char_name.lower()).strip("_") or "char"
    out = REAL_REFS_DIR / f"{safe}.jpg"
    # MANUAL URL OVERRIDE (Joe, Aug 2026): set REALREF_URL_<SAFE> to force a
    # specific photo URL for this person. Always honoured - bypasses cached
    # reuse AND the cached-failure skip, so a manually-supplied URL ALWAYS
    # creates a fresh face for this episode.
    override = os.environ.get(f"REALREF_URL_{safe.upper()}")
    if override:
        return _download_realref_url(char_name, override, out, force=True)
    if out.is_file():
        if _is_real_image(str(out)):
            print(f"  [REALREF] reuse {os.path.basename(out)}")
            return str(out)
        # Corrupt cached ref (HTML redirect / bad download) - re-fetch.
        print(f"  [REALREF] cached {os.path.basename(out)} is not a valid "
              f"image - re-fetching")
        try:
            out.unlink()
        except OSError:
            pass
    # If a prior run already failed to find a real ref for this person (no
    # usable image), skip the whole 99-candidate search and go straight to
    # the txt2img fallback. Avoids re-burning the search every run. Set
    # REALREF_FORCE_SEARCH=1 to always try a fresh search (restart/regenerate).
    if (char_name.lower() in _load_realref_failures()
            and os.environ.get("REALREF_FORCE_SEARCH", "0") != "1"):
        print(f"  [REALREF] {char_name}: cached no-real-ref (skipping search)")
        return None
    urls = _google_images_candidates(char_name, role)
    if not urls:
        urls = _openverse_candidates(char_name, role)
    tried = 0
    MAX_CANDIDATES = int(os.environ.get("REALREF_MAX_CANDIDATES", "12"))
    for u in urls:
        if not u or _bad_realref_url(u):
            continue  # known-bad CDN - skip before downloading
        tried += 1
        if tried > MAX_CANDIDATES:
            print(f"  [REALREF] stopped after {MAX_CANDIDATES} candidates "
                  f"(REALREF_MAX_CANDIDATES)")
            break
        for attempt in (1, 2):
            try:
                req = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=25) as r:
                    blob = r.read()
                if len(blob) < 5000:
                    break
                REAL_REFS_DIR.mkdir(parents=True, exist_ok=True)
                out.write_bytes(blob)
                if not _is_real_image(str(out)):
                    print(f"  [REALREF] not an image (HTML/bad bytes): {u[:60]}")
                    try:
                        out.unlink()
                    except OSError:
                        pass
                    break
                # Audit the photo (person match + no text/logo/watermark)
                # when the local vision model is loaded; else accept best effort.
                if _vision_available() and not _audit_real_photo(
                        str(out), char_name, role):
                    print(f"  [REALREF] rejected (person/text/watermark): {u[:50]}")
                    try:
                        out.unlink()
                    except Exception:
                        pass
                    break
                print(f"  [REALREF] {char_name} <- {u[:70]}")
                return str(out)
            except Exception as e:
                if attempt == 2:
                    print(f"  [REALREF] download failed {u[:50]} ({str(e)[:50]})")
    # No usable ref found this run - cache it so future runs skip the search.
    _save_realref_failure(char_name)
    return None


def _download_realref_url(char_name: str, url: str, out: Path,
                          force: bool = False) -> Optional[str]:
    """Download a single URL as the real-person photo for char_name.

    Used by the manual URL override (REALREF_URL_<SAFE>). With force=True it
    overwrites any cached ref so a manually-supplied URL ALWAYS creates a
    fresh face for this episode. Returns the saved path on success, None on
    failure. Validates the bytes are a decodable image and audits the photo
    (person match / no text-watermark) when the local vision model is loaded.
    """
    if out.is_file() and not force:
        if _is_real_image(str(out)):
            return str(out)
        try:
            out.unlink()
        except OSError:
            pass
    if not url or _bad_realref_url(url):
        print(f"  [REALREF] {char_name}: override URL blocked {str(url)[:60]}")
        return None
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as r:
            blob = r.read()
        if len(blob) < 5000:
            print(f"  [REALREF] {char_name}: override too small / no bytes")
            return None
        REAL_REFS_DIR.mkdir(parents=True, exist_ok=True)
        out.write_bytes(blob)
        if not _is_real_image(str(out)):
            print(f"  [REALREF] {char_name}: override not a decodable image")
            try:
                out.unlink()
            except OSError:
                pass
            return None
        if _vision_available() and not _audit_real_photo(
                str(out), char_name, ""):
            print(f"  [REALREF] {char_name}: override rejected by vision audit")
            try:
                out.unlink()
            except Exception:
                pass
            return None
        print(f"  [REALREF] {char_name} <- override {str(url)[:80]}")
        return str(out)
    except Exception as e:
        print(f"  [REALREF] {char_name}: override download failed "
              f"({str(e)[:80]})")
        return None


# -- Location sheets + prop assets (Joe, Aug 2026) -------------------------
# Every unique location gets a 6-panel stylized sheet (3x2 grid, same layout
# as the character sheet). Every prop gets a front+back asset. Both are
# generated through the SAME identity mode as character sheets but with the
# style plate as their ONLY ref ([style_plate] alone) - they are ASSETS, so
# the style sheet styles them, and then shots are composed ONLY from the
# already-styled assets (no style plate in the shot itself).
#
# Props: text-to-image by default (refs=[style_plate] so they match the
# channel style). "Specific props" (brands, models, named real objects -
# anything a prompt can't describe) get a SerpAPI real image + style plate,
# then generate a stylized prop asset reference from those two refs.

PROP_REAL_DIR = PROJECT_DIR / "cast_refs" / "props"


def _needs_real_prop(prop: str) -> bool:
    """Does this prop need a real image reference instead of pure T2I?

    True when the prop names a SPECIFIC real-world object a text prompt
    can't describe: brand/model names, digits (years, model numbers),
    ALL-CAPS or mid-string capitalized words (e.g. 'Powerball machine',
    '1969 Camaro', 'Apple II'). Generic props (briefcase, calculator,
    spreadsheet) stay text-to-image. PROP_REAL_FORCE=1 forces real for all.
    """
    if os.environ.get("PROP_REAL_FORCE", "0") == "1":
        return True
    if os.environ.get("PROP_REAL_FORCE", "0") == "2":
        return False
    p = (prop or "").strip()
    if not p:
        return False
    # digit clusters (model years, version numbers)
    if re.search(r"\d", p):
        return True
    # a capitalized word NOT at the start = proper noun / brand / model
    words = p.split()
    for i, w in enumerate(words):
        if i > 0 and w[:1].isupper() and len(w) > 1:
            return True
    # ALL-CAPS word anywhere (IBM, FBI, CAMRY...)
    if any(w.isupper() and len(w) > 1 for w in words):
        return True
    return False


def _find_prop_reference(prop: str) -> Optional[str]:
    """SerpAPI Google-Images (Openverse fallback) for a SPECIFIC prop's real
    photo, cached to cast_refs/props/. Returns None if nothing usable."""
    safe = re.sub(r"[^A-Za-z0-9]+", "_", prop.lower()).strip("_") or "prop"
    out = PROP_REAL_DIR / f"{safe}.jpg"
    if out.is_file():
        print(f"  [PROPREF] reuse {os.path.basename(out)}")
        return str(out)
    urls = _google_images_candidates(prop, "object")
    if not urls:
        urls = _openverse_candidates(prop, "object")
    for u in urls:
        if not u:
            continue
        for attempt in (1, 2):
            try:
                req = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=25) as r:
                    blob = r.read()
                if len(blob) < 5000:
                    break
                PROP_REAL_DIR.mkdir(parents=True, exist_ok=True)
                out.write_bytes(blob)
                print(f"  [PROPREF] {prop} <- {u[:70]}")
                return str(out)
            except Exception as e:
                if attempt == 2:
                    print(f"  [PROPREF] download failed {u[:50]} ({str(e)[:50]})")
    return None


# -- Brand / AI-company logos ------------------------------------------------
# Curated registry for AI companies & models: display name -> (aliases, logo
# search query). OTHER real businesses are detected at runtime from the
# article via LLM extraction (_extract_brands). Every logo caches to
# cast_refs/logos/ and is reused across episodes. Context decides the render:
#   - entity/product talk      -> hacker-style computer screen (prop sheet + logo)
#   - HQ / physical location   -> logo on a building (location sheet + logo)
#   - location sheet IS a business building -> logo joins the sheet's refs
BRAND_MANIFEST = PROJECT_DIR / "cast_refs" / "logos" / "brands.json"
BRAND_LOGO_DIR = PROJECT_DIR / "cast_refs" / "logos"
BRAND_SCREEN_DIR = PROJECT_DIR / "image-assets" / "brand_screens"
BRAND_BUILDING_DIR = PROJECT_DIR / "image-assets" / "brand_buildings"
BRAND_INTERIOR_DIR = PROJECT_DIR / "image-assets" / "brand_interiors"
# Interior cues: logo on a counter / wall behind the counter / reception inside
INTERIOR_WORDS = ("counter", "reception", "lobby interior", "inside the building",
                  "interior", "front desk", "behind the counter", "inside their",
                  "the entrance hall", "store interior", "showroom interior")
HQ_WORDS = ("headquarters", "hq", "head office", "offices", "office",
            "campus", "building", "plant", "factory", "warehouse", "store",
            "branch", "facility", "laboratory", "lab", "studio", "showroom",
            "floor", "lobby")

AI_ORGS: dict[str, tuple[list[str], str]] = {
    "OpenAI":       (["openai", "chatgpt", "gpt-4", "gpt-4o", "gpt-5", "gpt-5o",
                      "gpt4", "gpt5", "sora", "dall-e", "dalle"], "OpenAI logo"),
    "Google":       (["google ai", "gemini", "deepmind", "google deepmind",
                      "bard"], "Google AI logo"),
    "Anthropic":    (["anthropic", "claude"], "Anthropic logo"),
    "Meta":         (["meta ai", "llama 3", "llama 4", "llama3", "llama4",
                      "llama"], "Meta AI logo"),
    "Microsoft":    (["microsoft", "copilot", "azure ai", "microsoft ai"],
                     "Microsoft AI logo"),
    "xAI":          (["xai", "x ai", "grok"], "xAI logo"),
    "Mistral":      (["mistral"], "Mistral AI logo"),
    "DeepSeek":     (["deepseek"], "DeepSeek logo"),
    "Stability AI": (["stability ai", "stable diffusion"], "Stability AI logo"),
    "Midjourney":   (["midjourney"], "Midjourney logo"),
    "Runway":       (["runway", "runwayml", "runway ai"], "Runway AI logo"),
    "Hugging Face": (["hugging face", "huggingface"], "Hugging Face logo"),
    "ElevenLabs":   (["elevenlabs", "eleven labs"], "ElevenLabs logo"),
    "Perplexity":   (["perplexity"], "Perplexity logo"),
    "Apple":        (["apple intelligence", "apple ai", "siri"],
                     "Apple Intelligence logo"),
    "Amazon":       (["amazon q", "amazon ai", "alexa"], "Amazon AI logo"),
    "NVIDIA":       (["nvidia", "cuda"], "NVIDIA logo"),
    "Adobe":        (["adobe firefly", "firefly ai"], "Adobe Firefly logo"),
}

# Runtime registry of ALL known brand display names (AI orgs + LLM-extracted
# businesses this run). Persisted to BRAND_MANIFEST so resume/re-runs can
# rebuild the asset cache without re-extracting.
_KNOWN_BRANDS: set[str] = set(AI_ORGS.keys())

# Official logos: display name -> Wikimedia Commons file title. Resolved via
# the Commons API (rasterized to a 512px PNG thumb). SerpAPI image search is
# ONLY a fallback for brands not in this registry.
OFFICIAL_LOGOS: dict[str, str] = {
    # AI companies / models
    "OpenAI":       "File:OpenAI Logo.svg",
    "Google":       "File:Google 2015 logo.svg",
    "Gemini":       "File:Google Gemini logo.svg",
    "Anthropic":    "File:Anthropic logo.svg",
    "Meta":         "File:Meta AI logo.png",
    "Microsoft":    "File:Microsoft logo (2012).svg",
    "Copilot":      "File:Microsoft Copilot wordmark.svg",
    "xAI":          "File:Logo Grok AI (xAI) 2025.png",
    "Grok":         "File:Grok logo.svg",
    "Mistral":      "File:Mistral AI logo (2025\u2013).svg",
    "DeepSeek":     "File:DeepSeek logo.svg",
    "Stability AI": "File:Stability Ai \u2014 wordmark.png",
    "Midjourney":   "File:Midjourney Emblem (in-colour).png",
    "Runway":       "File:Runway Logo.png",
    "Hugging Face": "File:Hf-logo-with-title.svg",
    "ElevenLabs":   "File:ElevenLabs Logo 03.svg",
    "Perplexity":   "File:Perplexity AI logo.svg",
    "Adobe":        "File:Adobe logo and wordmark (2017).svg",
    "Firefly":      "File:Adobe Firefly Logo.svg",
    # Big tech / frequently mentioned businesses
    "Apple":        "File:Apple logo black.svg",
    "Amazon":       "File:Amazon logo.svg",
    "NVIDIA":       "File:NVIDIA logo.svg",
    "IBM":          "File:IBM logo.svg",
    "Tesla":        "File:Tesla Motors Logo - White.svg",
    "Netflix":      "File:Netflix logo.svg",
    "Spotify":      "File:Spotify logo without text.svg",
    "LinkedIn":     "File:LinkedIn icon.svg",
    "Oracle":       "File:Oracle logo.svg",
    "Sony":         "File:Sony logo.svg",
    "Ford":         "File:Ford logo.svg",
    "Toyota":       "File:Toyota logo.svg",
    "Coca-Cola":    "File:Coca-Cola logo.svg",
    "X":            "File:X logo 2023.svg",
    "Salesforce":   "File:Salesforce.com logo.svg",
    "Nike":         "File:Logo NIKE.svg",
}

# Pre-mapped 1000+ brand logos (premap_logos.py) -> Commons file titles.
# Loaded at startup so every brand in the manifest resolves via the OFFICIAL
# Wikimedia source (no SerpAPI search needed). Manifest is committed to the
# repo; regenerate/extend with:  python premap_logos.py
_OFFICIAL_LOGOS_MANIFEST = PROJECT_DIR / "cast_refs" / "logos" / "OFFICIAL_LOGOS_MANIFEST.json"
if _OFFICIAL_LOGOS_MANIFEST.is_file():
    try:
        _m = json.loads(_OFFICIAL_LOGOS_MANIFEST.read_text(encoding="utf-8"))
        if isinstance(_m, dict):
            for _k, _v in _m.items():
                OFFICIAL_LOGOS.setdefault(_k, _v)
    except Exception as _e:
        print(f"  [LOGO] premap manifest load failed: {_e}")


def _url_matches_brand(url: str, brand: str) -> bool:
    """True if the URL's filename contains the exact brand word (case-insensitive).

    Rejects a logo download that isn't actually the brand (e.g. a random CDN
    image whose filename doesn't name the brand). Joe 2026-08-16: the exact
    word (dixpord, mcdonalds, spacex...) must appear in the downloaded file's
    name, else the logo is treated as not found and a new one is generated.
    """
    if not url or not brand:
        return False
    fn = url.rstrip("/").split("/")[-1]
    fn = re.sub(r"\.[A-Za-z0-9]{2,5}$", "", fn)  # strip extension
    return brand.strip().lower() in fn.lower()


def _commons_logo_bytes(brand: str) -> Optional[bytes]:
    """Official logo from Wikimedia Commons, rasterized to a 512px PNG thumb.
    Returns raw image bytes, or None if unavailable (caller falls back to
    SerpAPI image search). Only accepts results whose filename contains the
    exact brand word."""
    title = OFFICIAL_LOGOS.get(brand)
    if not title:
        return None
    import urllib.parse as _up
    api = ("https://commons.wikimedia.org/w/api.php?action=query&titles="
           + _up.quote(title) + "&prop=imageinfo&iiprop=url&iiurlwidth=512"
           "&format=json")
    try:
        req = urllib.request.Request(
            api, headers={"User-Agent": "SplitNode/1.1 (ads.doctor.melbourne@gmail.com)"})
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read().decode())
        pages = data.get("query", {}).get("pages", {})
        if not pages:
            return None
        ii = next(iter(pages.values())).get("imageinfo")
        if not ii:
            return None
        thumb = ii[0].get("thumburl") or ii[0].get("url")
        if not thumb:
            return None
        if not _url_matches_brand(thumb, brand):
            print(f"  [LOGO] Wikimedia result for {brand} lacks '{brand}' in "
                  f"filename - skipping")
            return None
        req2 = urllib.request.Request(
            thumb, headers={"User-Agent": "SplitNode/1.1 (ads.doctor.melbourne@gmail.com)"})
        with urllib.request.urlopen(req2, timeout=30) as r2:
            blob = r2.read()
        return blob if len(blob) >= 2000 else None
    except Exception as e:
        print(f"  [LOGO] Wikimedia fetch failed for {brand} ({str(e)[:60]})")
        return None


def _brand_safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", name.lower()).strip("_") or "brand"


# Company/corporate entity suffixes + generic corporate tokens used to detect
# a name that is a BUSINESS/ENTITY rather than a person. When the LLM lists
# 'SpaceX', 'the company', 'IRS', 'HackerOne' etc. as a 'character', we must
# NOT build a human character sheet for it - it belongs to the BRAND/logo
# pipeline instead (Joe 2026-08-09: SpaceX was being personified as a human).
BUSINESS_SUFFIX_RE = re.compile(
    r"(?i)\b(inc|corp|corporation|llc|ltd|limited|co|company|group|holdings|"
    r"systems|industries|labs|laboratories|technologies|tech|services|solutions|"
    r"media|entertainment|airlines|airways|railways|rail|motorways|express|"
    r"bank|banks|insurance|fund|funds|capital|ventures|partners|associates|"
    r"communications|networks|energy|oil|gas|mining|auto|motors|beverages|"
    r"electronics|semiconductors|software|hardware|cloud|ai|robotics|defense|"
    r"aerospace|space|rocket|telecom|wireless|logistics|shipping|retail|stores|"
    r"farms|farming|studios|games|gaming|university|hospital|healthcare|pharma|"
    r"hotel|hotels|resorts|restaurant|restaurants|cafe|cafes|school|college|"
    r"agency|agencies|ministry|department|authority|commission|administration|"
    r"service|services)\b"
)
BUSINESS_WORD_RE = re.compile(
    r"(?i)\b(company|corporation|corp|inc|llc|ltd|founder|ceo|chairman|"
    r"co-founder|cofounder|executive|executives|board|shareholder|investor|"
    r"investors|employer|employees|workforce|hq|headquarters|head office|"
    r"officer|officers|spokesman|spokesperson|spokeswoman|"
    r"business|businesses|enterprise|firm|startup|start-ups|venture|fund|"
    r"bureau|agency|authority|department|division|unit|subsidiary|team|"
    r"organisation|organization|outfit|operation|operations)\b"
)


def _is_business_name(name: str) -> bool:
    """True when a name is a business/entity, not a human.

    Detects (a) known brands in the AI-org registry + curated real-world
    companies + persisted manifest, (b) a corporate-entity suffix
    (Inc/Corp/LLC/Bank/Labs...), or (c) a generic corporate token
    ('the company', 'founder', 'CEO'). Used to STOP businesses being
    personified as human characters in the shot list / character sheets.
    """
    if not name:
        return False
    n = str(name).strip()
    if not n:
        return False
    low = n.lower()
    # Known brand registry (curated AI orgs + real-world companies + persisted
    # detected brands).
    if low in KNOWN_COMPANY_NAMES:
        return True
    for b in _KNOWN_BRANDS:
        if b and b.lower() == low:
            return True
    # Multi-token corporate/company phrases.
    if BUSINESS_WORD_RE.search(n):
        return True
    # A trailing corporate suffix - only meaningful when the name is 2+ tokens
    # OR the sole token is an obvious entity (avoid flagging a person whose
    # surname happens to be 'Smith' etc.).
    return bool(BUSINESS_SUFFIX_RE.search(n))


# Well-known real-world companies/brands (lowercase) that appear in articles
# but are NOT in the AI-org registry - flagged as businesses so they are never
# personified as a person (e.g. 'SpaceX', 'Tesla', 'Nike'). Extended at runtime
# by _extract_brands.
KNOWN_COMPANY_NAMES: set[str] = {
    "spacex", "tesla", "nike", "adidas", "amazon", "apple", "microsoft",
    "meta", "facebook", "netflix", "nvidia", "intel", "amd", "ibm", "oracle",
    "salesforce", "spotify", "uber", "lyft", "airbnb", "stripe", "paypal",
    "visa", "mastercard", "disney", "sony", "samsung", "huawei", "xiaomi",
    "qualcomm", "broadcom", "cisco", "dell", "hp", "lenovo", "asus", "acer",
    "toyota", "honda", "ford", "gm", "chevrolet", "bmw", "mercedes", "volkswagen",
    "audi", "ferrari", "lamborghini", "porsche", "tesco", "walmart", "costco",
    "target", "kroger", "ikea", "home depot", "lowes", "mcdonalds", "kfc",
    "burger king", "subway", "starbucks", "coca-cola", "pepsi", "nestle",
    "kraft", "heinz", "jpmorgan", "goldman sachs", "morgan stanley", "citibank",
    "bank of america", "wells fargo", "hsbc", "barclays", "reuters", "bloomberg",
    "guardian", "forbes", "cnn", "bbc", "nbc", "abc", "cbs", "fox", "ny times",
    "new york times", "washington post", "hackerone", "bugcrowd", "crowdstrike",
    "palantir", "spacex", "nasa", "boeing", "lockheed martin", "raytheon",
    "northrop grumman", "grubhub", "doordash", "expedia", "booking", "paypal",
    "square", "robinhood", "coinbase", "binance", "ethereum", "bitcoin",
    "irs", "hackerone", "equifax", "experian", "transunion",
    "united airlines", "american airlines", "delta", "southwest",
    "british airways", "qantas", "cathay pacific", "singapore airlines",
    "virgin", "visa", "mastercard", "amex", "american express",
}


def _load_brand_manifest() -> dict[str, str]:
    """name -> context ('screen'|'building') persisted from prior runs."""
    if BRAND_MANIFEST.is_file():
        try:
            data = json.loads(BRAND_MANIFEST.read_text(encoding="utf-8"))
            out = dict(data.get("brands", {}))
            _KNOWN_BRANDS.update(out)
            return out
        except Exception:
            pass
    return {}


def _save_brand_manifest(brands: dict[str, str]) -> None:
    try:
        BRAND_MANIFEST.parent.mkdir(parents=True, exist_ok=True)
        BRAND_MANIFEST.write_text(
            json.dumps({"brands": brands}, indent=2), encoding="utf-8")
    except Exception:
        pass


def _detect_ai_orgs(*texts: str) -> list[str]:
    """Curated alias scan: AI companies/models mentioned across texts."""
    blob = " ".join(t for t in texts if t).lower()
    found: list[str] = []
    for org, (aliases, _q) in AI_ORGS.items():
        for a in aliases:
            if re.search(rf"\b{re.escape(a)}\b", blob):
                found.append(org)
                break
    return found


BRAND_EXTRACT_PROMPT = (
    "You extract real-world businesses from a documentary article.\n"
    "Rules:\n"
    "1. List ONLY real companies/brands actually mentioned in the article. "
    "Skip generic nouns ('the company', 'the bank'), people, places, "
    "governments, fictional entities and generic product names.\n"
    "2. For each business choose ONE context type:\n"
    "   - 'screen'   if the story is about the company, its product or its "
    "technology itself\n"
    "   - 'building' if the story involves its headquarters, offices, campus, "
    "factory, stores, warehouse or any physical location of that business\n"
    "3. Output ONLY one line per business, exactly:\n"
    "   NAME|screen\n"
    "   or\n"
    "   NAME|building\n"
    "4. If no real businesses are mentioned, output exactly: NONE\n"
    "No other text, no numbering, no explanations."
)


def _extract_brands(article_title: str, paragraphs: list[str],
                    narration: list[str]) -> dict[str, str]:
    """All brands in this article: curated AI aliases + LLM business
    extraction. Returns {display name: 'screen'|'building'}."""
    out: dict[str, str] = {}
    # 1. Curated AI orgs (works even with no LLM available)
    for org in _detect_ai_orgs(article_title, *paragraphs, *narration):
        ctx = _brand_context(org, [article_title, *paragraphs, *narration])
        out[org] = ctx
    # 2. LLM extraction for any other real businesses
    try:
        excerpt = "\n\n".join([article_title or "", *paragraphs])[:6000]
        text = _llm_chat([
            {"role": "system", "content": BRAND_EXTRACT_PROMPT},
            {"role": "user", "content": f"ARTICLE:\n{excerpt}"},
        ], max_tokens=800, temp=0.2)
        for line in text.splitlines():
            m = re.match(r"^\s*([^|]{1,80})\|(screen|building)\s*$", line)
            if m:
                nm = m.group(1).strip().strip('"\'')
                if nm and nm.lower() != "none" and len(nm) > 1:
                    out.setdefault(nm, m.group(2))
    except Exception as e:
        print(f"  [BRAND] LLM extraction failed ({str(e)[:60]}) - curated AI only")
    if out:
        _KNOWN_BRANDS.update(out)
        _save_brand_manifest(out)
    return out


def _brand_context(name: str, texts: list[str]) -> str:
    """Logo placement context for a brand: 'interior' (counter/wall inside),
    'building' (exterior HQ/facade), or 'screen'. Joe 2026-08-09."""
    low_name = name.lower()
    for t in texts:
        low = (t or "").lower()
        if low_name in low:
            if any(w in low for w in INTERIOR_WORDS):
                return "interior"
            if any(w in low for w in HQ_WORDS):
                return "building"
    return "screen"


def _logo_file_ok(path) -> bool:
    """True if `path` is a file PIL can actually decode as an image."""
    try:
        from PIL import Image
        with Image.open(str(path)) as im:
            im.verify()
        return True
    except Exception:
        return False


def _coerce_raster_image(blob: bytes, brand: str) -> Optional[bytes]:
    """If `blob` is an SVG (some logo sources serve vector files that codex /
    the ref pipeline cannot process), rasterize it to a real PNG. Returns PNG
    bytes, or the original blob if already raster, or None if undecodable."""
    data = blob
    if data[:3] == b"\xef\xbb\xbf":
        data = data[3:]
    head = data[:512].lstrip().lower()
    if not (head.startswith(b"<?xml") or head.startswith(b"<svg")):
        return blob  # already a raster image
    import tempfile
    tmp = None
    try:
        from svglib.svglib import svg2rlg
        from reportlab.graphics import renderPM
        import io
        f = tempfile.NamedTemporaryFile(suffix=".svg", delete=False)
        f.write(data)
        f.close()
        tmp = f.name
        drawing = svg2rlg(tmp)
        if drawing is None:
            return None
        drawing.width *= 2
        drawing.height *= 2
        drawing.scale(2, 2)
        buf = io.BytesIO()
        renderPM.drawToFile(drawing, buf, fmt="PNG")
        return buf.getvalue()
    except Exception as e:
        print(f"  [LOGO] could not rasterize SVG for {brand}: {str(e)[:60]}")
        return None
    finally:
        if tmp:
            try:
                os.remove(tmp)
            except Exception:
                pass


def _generate_logo_ref(brand: str, out) -> Optional[str]:
    """No real logo exists for this (likely fictional) brand - generate a
    stylized logo as its OWN ref (Joe 2026-08-16) so brand/shots still get a
    valid logo image to attach instead of nothing. Cached per brand."""
    out.parent.mkdir(parents=True, exist_ok=True)
    print(f"  [LOGO] no real logo for '{brand}' - generating one as its own ref...")
    seed = abs(hash(_brand_safe(brand))) % 1000000
    try:
        # Simple directive (Joe 2026-08-16): use the pipeline's chosen image
        # provider and just ask for a logo. _krea_generate routes through
        # IMAGE_BACKEND (codex GPT Image 2 / fal / runpod / local).
        ok = _krea_generate(
            f"Generate a logo for {brand}. Clean flat vector brand logo on a "
            f"plain white background.",
            seed, str(out), ref_images=None,
            upscale=False, width=512, height=512)
    except Exception as e:
        print(f"  [LOGO] logo generation failed for {brand}: {str(e)[:60]}")
        return None
    if ok and _logo_file_ok(out):
        print(f"  [LOGO] generated logo for '{brand}' cached -> {out.name}")
        return str(out)
    try:
        if out.is_file():
            out.unlink()
    except Exception:
        pass
    return None


def _find_logo(brand: str) -> Optional[str]:
    """Logo for a brand, cached to cast_refs/logos/. Cache-first, then the
    OFFICIAL Wikimedia Commons source, and ONLY then SerpAPI image search
    (Openverse fallback) for brands not in the official registry. If nothing
    real matches (e.g. a fictional entity), GENERATE a logo as its own ref
    (Joe 2026-08-16)."""
    safe = _brand_safe(brand)
    out = BRAND_LOGO_DIR / f"{safe}.png"
    if out.is_file():
        if _logo_file_ok(out):
            return str(out)
        # corrupt/misnamed cached logo (e.g. an SVG saved as .png) - drop and
        # regenerate/re-fetch so codex never gets an unprocessable ref.
        print(f"  [LOGO] cached {safe}.png corrupt - regenerating")
        try:
            out.unlink()
        except Exception:
            pass
    # 1. Official source: Wikimedia Commons (rasterized PNG thumb)
    if brand in OFFICIAL_LOGOS:
        blob = _commons_logo_bytes(brand)
        if blob:
            blob = _coerce_raster_image(blob, brand)
            if blob:
                BRAND_LOGO_DIR.mkdir(parents=True, exist_ok=True)
                out.write_bytes(blob)
                if _logo_file_ok(out):
                    print(f"  [LOGO] {brand} cached (official Wikimedia)")
                    return str(out)
                try:
                    out.unlink()
                except Exception:
                    pass
        print(f"  [LOGO] {brand} unavailable on Wikimedia - falling back to "
              f"image search")
    # 2. Fallback: SerpAPI image search (Openverse fallback)
    query = AI_ORGS.get(brand, ([""], f"{brand} logo"))[1]
    urls = _google_images_candidates(query, "logo")
    if not urls:
        urls = _openverse_candidates(query, "logo")
    for u in urls:
        if not u:
            continue
        # Joe 2026-08-16: never DOWNLOAD a candidate whose filename lacks the
        # exact brand word - skip straight past it (generate a logo instead).
        if not _url_matches_brand(u, brand):
            print(f"  [LOGO] '{brand}': candidate filename lacks '{brand}' - skip {u[:60]}")
            continue
        for attempt in (1, 2):
            try:
                req = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=25) as r:
                    blob = r.read()
                if len(blob) < 5000:
                    break
                blob = _coerce_raster_image(blob, brand)
                if not blob:
                    break
                BRAND_LOGO_DIR.mkdir(parents=True, exist_ok=True)
                out.write_bytes(blob)
                if _logo_file_ok(out):
                    print(f"  [LOGO] {brand} cached <- {u[:70]}")
                    return str(out)
                try:
                    out.unlink()
                except Exception:
                    pass
            except Exception as e:
                if attempt == 2:
                    print(f"  [LOGO] download failed {u[:50]} ({str(e)[:50]})")
    # 3. No real logo found - generate one as this brand's own ref
    return _generate_logo_ref(brand, out)


def _logo_for_prop(prop: str, brands: Optional[dict] = None) -> Optional[str]:
    """If a prop/scene names a known brand (AI alias or extracted business),
    return its cached logo."""
    low = (prop or "").lower()
    for org, (aliases, _q) in AI_ORGS.items():
        for a in aliases:
            if re.search(rf"\b{re.escape(a)}\b", low):
                return _find_logo(org)
    for name in (brands or {}):
        if name.lower() in low:
            return _find_logo(name)
    return None


def _generate_brand_asset(brand: str, kind: str, seed: int) -> Optional[str]:
    """Stylized brand asset, cached per (brand, kind):
      kind='screen'    -> hacker computer screen with the real logo,
                          refs = [prop style sheet, logo]
      kind='building'  -> the logo on an exterior building / HQ facade,
                          refs = [location style sheet, logo]
      kind='interior'  -> the logo on a counter / wall inside the building
                          (reception, behind the counter, store interior),
                          refs = [location style sheet, logo]
    Joe 2026-08-09: logo placement is context-aware."""
    safe = _brand_safe(brand)
    out_dir = {"screen": BRAND_SCREEN_DIR, "building": BRAND_BUILDING_DIR,
               "interior": BRAND_INTERIOR_DIR}.get(kind, BRAND_SCREEN_DIR)
    out = out_dir / f"{safe}.png"
    if out.is_file():
        print(f"  [BRAND] reuse {os.path.basename(out)}")
        return str(out)
    logo = _find_logo(brand)
    if not logo:
        print(f"  [BRAND] no logo for '{brand}' - skipping {kind} asset")
        return None
    if kind in ("building", "interior") and not os.path.isfile(str(LOCATION_STYLE_REF)):
        print(f"  [BRAND] no location style sheet - skipping {kind} asset")
        return None
    if kind == "screen" and not os.path.isfile(str(PROP_STYLE_REF)):
        print(f"  [BRAND] no prop style sheet - skipping screen asset")
        return None
    style_ref = str(PROP_STYLE_REF) if kind == "screen" else str(LOCATION_STYLE_REF)
    if kind == "screen":
        prompt = (
            f"A dark hacker command-center computer screen: a large monitor in a "
            f"dark room, glowing green terminal code, scrolling data streams, and "
            f"the official {brand} logo displayed LARGE and centered on the main "
            f"screen, unmistakable, shape and colors exactly matching the reference "
            f"logo image. Use ONLY the painting and render style from the reference "
            f"artwork - bold animated style, strong stylized brushwork, painterly "
            f"shading, saturated colors, dramatic lighting. The reference images "
            f"show DIFFERENT scenes/objects - this panel is the {brand} hacker "
            f"screen and NOTHING else. STRICTLY NO people, no humans, no faces, "
            f"no characters, no figures, no silhouettes, no body parts, no hands, "
            f"no persons of any kind anywhere in frame."
        )
    elif kind == "interior":
        prompt = (
            f"A dramatic interior shot inside the {brand} building: the official "
            f"{brand} logo on the wall behind the reception counter / front desk, "
            f"large backlit sign, and the logo on the counter itself, brand colors "
            f"exactly matching the reference logo image. Modern corporate interior "
            f"with a clean lobby, warm professional lighting. Use ONLY the painting "
            f"and render style from the reference artwork - bold animated style, "
            f"strong stylized brushwork, painterly shading, saturated colors, "
            f"dramatic lighting, realistic depth of field. The reference images "
            f"show DIFFERENT scenes - this panel is the {brand} interior and "
            f"NOTHING else. STRICTLY NO people, no humans, no faces, no characters, "
            f"no figures, no silhouettes, no body parts, no hands, no persons of "
            f"any kind anywhere in frame."
        )
    else:
        prompt = (
            f"A dramatic night shot of a modern corporate building with the "
            f"official {brand} logo displayed prominently: large glowing sign on "
            f"the facade, logo on the entrance and reception, brand colors exactly "
            f"matching the reference logo image. Use ONLY the painting and render "
            f"style from the reference artwork - bold animated style, strong "
            f"stylized brushwork, painterly shading, saturated colors, dramatic "
            f"rim lighting, dark moody atmosphere. The reference images show "
            f"DIFFERENT scenes - this panel is the {brand} building and NOTHING "
            f"else. STRICTLY NO people, no humans, no faces, no characters, no "
            f"figures, no silhouettes, no body parts, no hands, no persons of any "
            f"kind anywhere in frame."
        )
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"  [BRAND] {brand} {kind} asset (refs: {style_ref.split(chr(92))[-1]}, "
          f"{os.path.basename(logo)})...")
    ok = _krea_generate(prompt, seed, str(out),
                        ref_images=[style_ref, logo], denoise=1.0,
                        upscale=False, steps=10,
                        width=1280, height=720,
                        ref_mode="identity", ref_boost=2.0,
                        grounding_px=768)
    return str(out) if ok else None


def _scan_brand_assets() -> dict[str, dict[str, str]]:
    """Rebuild {brand: {'screen': path, 'building': path, 'interior': path}}
    from the on-disk caches + brand manifest (covers resume runs)."""
    _load_brand_manifest()
    out: dict[str, dict[str, str]] = {}
    for d, kind in ((BRAND_SCREEN_DIR, "screen"),
                    (BRAND_BUILDING_DIR, "building"),
                    (BRAND_INTERIOR_DIR, "interior")):
        if d.is_dir():
            for f in sorted(d.glob("*.png")):
                for name in _KNOWN_BRANDS:
                    if _brand_safe(name) == f.stem:
                        out.setdefault(name, {})[kind] = str(f)
                        break
    return out


def _match_brand_asset(scene: str, brand_assets: dict) -> Optional[str]:
    """Pick the right brand asset for a shot, context-aware (Joe 2026-08-09):
    interior scene text (counter/reception/inside) -> interior asset; HQ/exterior
    -> building asset; otherwise the hacker screen."""
    if not scene or not brand_assets:
        return None
    low = scene.lower()
    for name, assets in brand_assets.items():
        if name.lower() not in low:
            continue
        if any(w in low for w in INTERIOR_WORDS) and assets.get("interior"):
            return assets["interior"]
        if any(w in low for w in HQ_WORDS) and assets.get("building"):
            return assets["building"]
        if assets.get("screen"):
            return assets["screen"]
        if assets.get("building"):
            return assets["building"]
        if assets.get("interior"):
            return assets["interior"]
    return None


def _brand_logo_for(location: str, brands: dict) -> Optional[str]:
    """Logo ref when a location IS a business building (e.g. 'OpenAI
    headquarters', 'Tesla factory floor') - gets baked into that location
    sheet's panels so the logo appears inside the building."""
    low = location.lower()
    for name in (brands or {}):
        if name.lower() in low:
            return _find_logo(name)
    return None


# Common hardening applied to EVERY location panel (Joe 2026-08-06):
# location sheets are PURE txt2img (no image refs), so the model must be told
# there is nothing to copy - exactly ONE continuous scene. The old prompts
# said 'reference artwork / reference images show DIFFERENT scenes' which the
# model read as 'composite multiple references' -> the 2x-collage + people
# bug. Also: strip the per-view hardcoded style (it conflicted with the real
# channel style injected via _style_inject()).
LOC_HARDEN = (
    "Render EXACTLY ONE single continuous scene showing EXACTLY ONE location. "
    "This is a standalone text-to-image - there are NO reference images to copy "
    "from. No collage, no split panels, no multiple images, no diptych, no "
    "duplicated scenes, no mirrored repeats, no doubled subjects. One plain "
    "composition, a single cohesive frame. "
    "STRICTLY NO people, no humans, no faces, no characters, no figures, no "
    "silhouettes, no body parts, no hands, no persons of any kind anywhere in "
    "frame. The place is completely empty of people."
)

# A bare place name (country/region/city/town) has no concrete scene to anchor
# on - the model freezes on 'The Netherlands' and hallucinates collage/people.
# If the location does not read as a specific built venue, anchor it to a
# representative city/street scene.
_LOC_VENUE_HINT = re.compile(
    r"(?i)\b(building|office|headquarters|hq|floor|room|apartment|house|home|"
    r"casino|store|shop|factory|warehouse|bank|hotel|hospital|station|airport|"
    r"restaurant|bar|club|nightclub|street|road|avenue|square|park|beach|desert|"
    r"forest|mountain|field|farm|mall|market|gym|church|school|university|"
    r"library|studio|kitchen|bedroom|garage|basement|rooftop|alley|pier|dock|"
    r"bridge|tunnel|yard|landfill|site|compound|facility|campus|dorm|vault|"
    r"bunker|shelter|interior|inside|of the)\b")


def _location_scene_clause(location: str) -> str:
    """For a bare place name, return a clause anchoring it to a representative
    city/street scene (so 'The Netherlands' renders as a Dutch street, not junk).
    Returns '' for specific venues which should render as-is."""
    if _LOC_VENUE_HINT.search(location):
        return ""
    return ("Show a representative city or street scene of this place, the "
            "local architecture and streetscape at a cinematic angle. ")


LOCATION_VIEWS = [
    ("establishing",
     "A wide establishing shot of the location, the entire setting visible."),
    ("front_left",
     "A medium shot of the location seen from the front-left angle."),
    ("front_right",
     "A medium shot of the location seen from the front-right angle."),
    ("interior",
     "A view inside the location, interior space, furniture and details visible."),
    ("detail",
     "A close-up detail shot of a distinctive feature of the location (a sign, "
     "a doorway, a key object)."),
    ("overhead",
     "An overhead elevated shot of the location from above, layout visible."),
]


def _generate_location_sheet(location: str, seed: int, out_dir: Path,
                             logo_ref: Optional[str] = None) -> Optional[str]:
    """6-panel stylized location sheet (3x2 grid, 1920x1080). Panels render at
    the SAME resolution as character-sheet panels (SHEET_PANEL_W x SHEET_PANEL_H,
    640x540) and are composed with the exact same grid method, so location
    sheets and character sheets line up 1:1 as shot refs. Cached per location
    name. When the location IS a business building, its logo joins the refs so
    the logo appears inside the generated location (signage, lobby, facade)."""
    safe = re.sub(r"[^A-Za-z0-9]+", "_", location.lower()).strip("_") or "loc"
    out = out_dir / f"{safe}_sheet.png"
    if out.is_file():
        print(f"  [LOCATION] reuse {os.path.basename(out)}")
        return str(out)
    # txt2img + style PROMPT injection (Joe 2026-08-04): no style-plate refs
    # - faster, and no reference-copy bug. EXCEPTION: when the location IS a
    # business building (logo_ref available), the business logo joins as an
    # image ref (Kontext - prompt controls the building, ref carries the mark).
    logo = logo_ref if (logo_ref and os.path.isfile(logo_ref)) else None
    panels: dict[str, str] = {}
    for view, prompt_txt in LOCATION_VIEWS:
        pan = out_dir / f"{safe}_{view}.png"
        if pan.is_file():
            panels[view] = str(pan)
            continue
        scene = _location_scene_clause(location)
        p = (f"{prompt_txt} {scene}The location is: {location}. "
             f"{LOC_HARDEN} {_style_inject()}")
        if logo:
            print(f"  [LOCATION] '{location}' panel {view} "
                  f"(logo ref, 640x540)...")
            ok = _krea_generate(p, seed + 111 * len(view), str(pan),
                                ref_images=[logo], denoise=1.0, upscale=False,
                                steps=10, width=SHEET_PANEL_W, height=SHEET_PANEL_H,
                                ref_mode="reference")
        else:
            print(f"  [LOCATION] '{location}' panel {view} (txt2img+style, "
                  f"640x540)...")
            ok = _krea_generate(p, seed + 111 * len(view), str(pan),
                                ref_images=None, denoise=1.0, upscale=False,
                                steps=10, width=SHEET_PANEL_W, height=SHEET_PANEL_H,
                                ref_mode="img2img")
        if ok:
            panels[view] = str(pan)
    if len(panels) < 3:
        print(f"  [LOCATION] '{location}' only {len(panels)}/6 panels - skip sheet")
        return None
    try:
        from PIL import Image, ImageDraw
        grid = Image.new("RGB", (SHEET_GRID_W, SHEET_GRID_H), (10, 10, 12))
        draw = ImageDraw.Draw(grid)
        for i, view in enumerate([v for v, _ in LOCATION_VIEWS]):
            if view not in panels:
                continue
            im = Image.open(panels[view]).convert("RGB")
            im = im.resize((SHEET_PANEL_W, SHEET_PANEL_H), Image.LANCZOS)
            col, row = i % SHEET_COLS, i // SHEET_COLS
            grid.paste(im, (col * SHEET_PANEL_W, row * SHEET_PANEL_H))
            draw.rectangle([col * SHEET_PANEL_W, row * SHEET_PANEL_H,
                            col * SHEET_PANEL_W + SHEET_PANEL_W - 1,
                            row * SHEET_PANEL_H + SHEET_PANEL_H - 1],
                           outline=(120, 120, 130), width=4)
        out_dir.mkdir(parents=True, exist_ok=True)
        grid.save(out)
        print(f"  [LOCATION] '{location}' locked -> {os.path.basename(out)} "
              f"({len(panels)}/6 panels)")
        return str(out)
    except Exception as e:
        print(f"  [LOCATION] compose failed: {e}")
        return None


def _generate_prop_asset(prop: str, seed: int, out_dir: Path,
                         brands: Optional[dict] = None) -> Optional[str]:
    """Stylized prop asset: front + back panels composed into one 1280x540
    sheet. refs = [style_plate] for T2I props, [style_plate, real_photo] for
    SPECIFIC props (SerpAPI real image). Props naming a known brand use the
    brand's cached logo as the real photo. Cached per prop name."""
    safe = re.sub(r"[^A-Za-z0-9]+", "_", prop.lower()).strip("_") or "prop"
    out = out_dir / f"{safe}_prop.png"
    if out.is_file():
        print(f"  [PROP] reuse {os.path.basename(out)}")
        return str(out)
    # txt2img + style PROMPT injection (Joe 2026-08-04): no image refs, no
    # real-photo/logo refs - the prop name in the prompt carries the object,
    # the injection carries the channel look. Faster + no reference-copy bug.
    views = [
        ("front",
         f"Render THIS OBJECT: {prop}, front view, centered, full object "
         f"visible, plain dark studio background. STRICTLY NO people, no "
         f"humans, no faces, no characters, no figures, no silhouettes, no "
         f"body parts, no hands, no text, no persons of any kind anywhere "
         f"in frame."),
        ("back",
         f"Render THIS OBJECT: {prop}, back view, centered, full object "
         f"visible, plain dark studio background. STRICTLY NO people, no "
         f"humans, no faces, no characters, no figures, no silhouettes, no "
         f"body parts, no hands, no text, no persons of any kind anywhere "
         f"in frame."),
    ]
    panels: dict[str, str] = {}
    for view, prompt_txt in views:
        pan = out_dir / f"{safe}_{view}.png"
        if pan.is_file():
            panels[view] = str(pan)
            continue
        p = f"{prompt_txt} {_style_inject()}"
        print(f"  [PROP] '{prop}' {view} panel (txt2img+style, "
              f"720p->1080p)...")
        ok = _krea_generate(p, seed + 111 * len(view), str(pan),
                            ref_images=None, denoise=1.0, upscale=True,
                            steps=10, width=1280, height=720,
                            ref_mode="img2img")
        if ok:
            panels[view] = str(pan)
    if not panels:
        return None
    try:
        from PIL import Image, ImageDraw
        grid = Image.new("RGB", (SHEET_PANEL_W * 2, SHEET_PANEL_H), (10, 10, 12))
        draw = ImageDraw.Draw(grid)
        for i, view in enumerate(("front", "back")):
            if view not in panels:
                continue
            im = Image.open(panels[view]).convert("RGB")
            im = im.resize((SHEET_PANEL_W, SHEET_PANEL_H), Image.LANCZOS)
            grid.paste(im, (i * SHEET_PANEL_W, 0))
            draw.rectangle([i * SHEET_PANEL_W, 0,
                            i * SHEET_PANEL_W + SHEET_PANEL_W - 1,
                            SHEET_PANEL_H - 1],
                           outline=(120, 120, 130), width=4)
        out_dir.mkdir(parents=True, exist_ok=True)
        grid.save(out)
        print(f"  [PROP] '{prop}' locked -> {os.path.basename(out)} "
              f"({len(panels)}/2 panels)")
        return str(out)
    except Exception as e:
        print(f"  [PROP] compose failed: {e}")
        return None


def _match_location_sheet(scene: str, location_sheets: dict) -> Optional[str]:
    """Best location sheet for a shot scene by keyword overlap."""
    if not location_sheets:
        return None
    kw = set(_scene_keywords(scene))
    if not kw:
        return None
    best, best_score = None, 0
    for loc, path in location_sheets.items():
        if not path or not os.path.isfile(path):
            continue
        loc_kw = set(re.findall(r"[a-z0-9']+", loc.lower()))
        score = len(kw & loc_kw)
        if score > best_score:
            best, best_score = path, score
    return best if best_score >= 1 else None


def _match_prop_asset(scene: str, prop_assets: dict) -> Optional[str]:
    """Best prop asset for a shot scene by keyword overlap."""
    if not prop_assets:
        return None
    kw = set(_scene_keywords(scene))
    if not kw:
        return None
    best, best_score = None, 0
    for prop_name, path in prop_assets.items():
        if not path or not os.path.isfile(path):
            continue
        prop_kw = set(re.findall(r"[a-z0-9']+", prop_name.lower()))
        score = len(kw & prop_kw)
        if score > best_score:
            best, best_score = path, score
    return best if best_score >= 1 else None


def _broll_refs(shot: dict, location_sheets: dict, prop_assets: dict) -> list:
    """Asset-sheet refs for a char=NONE shot (Joe 2026-08-04).

    A LOCATION shot (scene matches a location sheet, no prop) references the
    location sheet only. A B-ROLL shot (scene matches a prop too) references
    the location sheet + prop sheet. Empty list = no asset matched -> caller
    falls back to txt2img + style prompt injection."""
    refs: list[str] = []
    loc = _match_location_sheet(shot.get("scene", ""), location_sheets)
    if loc:
        refs.append(loc)
    prop = _match_prop_asset(shot.get("scene", ""), prop_assets)
    if prop and prop not in refs:
        refs.append(prop)
    return refs


def _build_location_sheets(context: dict, seed: int, ep_dir: Path,
                           brands: Optional[dict] = None) -> dict:
    """Location sheets for every unique place/environment in the episode world.
    A location that IS a business building (e.g. 'OpenAI headquarters') gets
    that business's logo baked into its sheet as an extra ref."""
    if os.environ.get("LOCATION_SHEETS", "0") == "0":  # default OFF (Joe 2026-08-07): no location sheets, only establishing shots
        return {}
    names: list[str] = []
    for k in ("places", "environments"):
        for v in context.get(k, []) or []:
            v = str(v).strip()
            if v and v.lower() not in (n.lower() for n in names):
                names.append(v)
    if not names:
        return {}
    out_dir = ep_dir / "location_sheets"
    out_dir.mkdir(parents=True, exist_ok=True)
    sheets = {}
    print(f"\n[ASSETS] {len(names)} locations -> stylized sheets...")
    _loc_iter = (tqdm(names[:6], desc="  [ASSETS] location sheets", unit="sheet",
                      leave=False) if _HAS_PROGRESS else names[:6])
    for i, loc in enumerate(_loc_iter):
        logo_ref = _brand_logo_for(loc, brands)
        path = _generate_location_sheet(loc, seed + i * 1000, out_dir,
                                        logo_ref=logo_ref)
        if path:
            sheets[loc] = path
    return sheets


def _build_prop_assets(context: dict, seed: int, ep_dir: Path,
                       brands: Optional[dict] = None) -> dict:
    """Front+back prop assets for the episode's props (T2I or real ref).
    Props that name a known brand (AI org or extracted business) use the
    brand's cached logo as the real reference."""
    if os.environ.get("PROP_SHEETS", "0") == "0":  # default OFF (Joe 2026-08-07): no prop assets
        return {}
    props = [str(v).strip() for v in (context.get("props", []) or []) if str(v).strip()]
    if not props:
        return {}
    out_dir = ep_dir / "props"
    out_dir.mkdir(parents=True, exist_ok=True)
    assets = {}
    print(f"\n[ASSETS] {len(props)} props -> stylized front/back assets...")
    _prop_iter = (tqdm(props[:8], desc="  [ASSETS] prop assets", unit="prop",
                       leave=False) if _HAS_PROGRESS else props[:8])
    for i, prop in enumerate(_prop_iter):
        path = _generate_prop_asset(prop, seed + 500 + i * 1000, out_dir,
                                    brands=brands)
        if path:
            assets[prop] = path
    return assets


CHAR_SHEETS_DIR_NAME = "char_sheets"
# 6-panel character sheet spec (Joe, Aug 2026):
#   face -> face_side -> face_back (face chain, img2img from the previous)
#   body_front -> body_side -> body_back (body chain, img2img from face /
#   body_front). Each panel is HARD-LOCKED to contain ONLY what we want.
# Panels render at 640x540, composed 3x2 -> 1920x1080 sheet.
SHEET_PANEL_W, SHEET_PANEL_H = 640, 540
SHEET_COLS, SHEET_ROWS = 3, 2
# grid = panels at native size, 3x2 -> 1920 long side (no stretch/skew)
SHEET_GRID_W = SHEET_PANEL_W * SHEET_COLS
SHEET_GRID_H = SHEET_PANEL_H * SHEET_ROWS

# (view, ref_source, denoise, prompt, method)
# Identity mode (krea2edit LoRA, APPROVED Aug 2026 on the Elon sheet test):
#   - face panel: [style_plate, real_photo] (2 refs, ref_boost 4.0)
#   - ALL other panels (face_side/back, body_front/side/back): chain off the
#     FACE-FRONT panel ONLY, ref_boost lowered (SHEET_CHAIN_BOOST, default
#     2.0) so the prompt controls pose/framing - boost 4.0 on a face close-up
#     forced the giant head into body shots (img2img-style bleed).
#   - "identity" = krea2edit trained path (euler, ref_boost 4, grounding 1024)
#   - Fallback when NO real photo exists: old Ostris Kontext path
#     ("reference" mode; method index_timestep_zero for front views,
#     uxo/uno for side/back).
SHEET_PANELS = [
    ("face", "real", 0.45,
     "Create a close-up portrait of THIS EXACT MAN's face, head and face only, "
     "full face centered, both eyes looking at camera, hair styled as in the "
     "reference, expression neutral. NOTHING else in frame - no shoulders, no "
     "neck, no body. The person shown is THIS EXACT MAN and no one else. "
     "Plain light grey studio background, flat even neutral lighting, no "
     "dramatic lighting, no coloured lighting, no rim light, one person only.",
     "index_timestep_zero"),
    ("face_side", "face", 0.5,
     "Show THIS EXACT MAN in left side profile, head only, same hair, same "
     "face, no body, no shoulders. EXACTLY ONE single person, absolutely no "
     "second figure, no duplicate, no mirror image. The person shown is THIS "
     "EXACT MAN and no one else. Plain light grey studio background, flat even "
     "neutral lighting, no dramatic lighting, no coloured lighting, one "
     "person only.",
     "uxo/uno"),
    ("face_back", "face", 0.5,
     "Show the back of THIS EXACT MAN's head, rear view, hair as in the "
     "reference, no face visible, no body. EXACTLY ONE single person, "
     "absolutely no second figure, no duplicate, no mirror image. The person "
     "shown is THIS EXACT MAN and no one else. Plain light grey studio "
     "background, flat even neutral lighting, no dramatic lighting, no "
     "coloured lighting, one person only.",
     "uxo/uno"),
    ("body_front", "face", 0.55,
     "Show THIS EXACT MAN full body standing facing the camera, complete "
     "outfit as in the reference, face identical, entire body head to feet, "
     "both feet on the ground, arms relaxed at sides. EXACTLY ONE single "
     "person, absolutely no second figure, no duplicate, no mirror image. "
     "The person shown is THIS EXACT MAN and no one else. Plain light grey "
     "studio background, flat even neutral lighting, no dramatic lighting, "
     "no coloured lighting.",
     "index_timestep_zero"),
    ("body_side", "body_front", 0.5,
     "Show THIS EXACT MAN full body side profile view facing left, same "
     "outfit, same face, same build, entire body head to feet. EXACTLY ONE "
     "single person, absolutely no second figure, no duplicate, no mirror "
     "image, no shadow clone, no extra person anywhere in frame. The person "
     "shown is THIS EXACT MAN and no one else. Plain light grey studio "
     "background, flat even neutral lighting, no dramatic lighting, no "
     "coloured lighting.",
     "uxo/uno"),
    ("body_back", "body_front", 0.5,
     "Show THIS EXACT MAN full body rear view, back of head and full outfit "
     "visible, standing, entire body head to feet. EXACTLY ONE single "
     "person, absolutely no second figure, no duplicate, no mirror image. "
     "The person shown is THIS EXACT MAN and no one else. Plain light grey "
     "studio background, flat even neutral lighting, no dramatic lighting, "
     "no coloured lighting.",
     "uxo/uno"),
]


# Character sheet panels are now SIX INDIVIDUAL 1280x1280 images (Joe
# 2026-08-06) - they are NOT merged into a grid anymore. Each is used as the
# image ref for a shot depending on the shot's framing + the person's facing.
CHAR_PANEL_W, CHAR_PANEL_H = 1280, 1280
CHAR_PANEL_VIEWS = ["face", "face_side", "face_back",
                    "body_front", "body_side", "body_back"]

# Negative prompt for character/body panels: hard-ban duplicate figures so a
# single identity never renders as two people (fixes the body_side 2-human
# bug beyond grounding_px=768 alone - the negative prompt steers the sampler
# away from clones/mirrors in every panel).
NO_DUPLICATE_NEGATIVE = (
    "two people, two persons, duplicate, cloned, double figure, second person, "
    "extra person, twin, mirror image, split body, two bodies, two heads, "
    "double exposure, multiple figures, crowd, mannequin, duplicate subject"
)

# Mannequin-style panels - REAL-FACE method (canonical, Joe-approved 2026-08-06):
# Use the real person's photo as the ONE identity ref (krea2edit identity mode)
# but render the result as a glossy PORCELAIN mannequin whose facial features
# (bone structure, brow, nose, lips, jaw) match the ref EXACTLY. The face reads
# as a polished museum mannequin that strongly resembles the person - not
# realistic human skin. Hair is coloured and matches the ref. When NO real
# photo exists, fall back to text-only hair injection (_describe_hair_text).
# (view, ref_src, denoise, prompt-template, method)
MANNEQUIN_PANELS = [
    ("face", "real", 1.0,
     "A seamless glossy porcelain mannequin head and face, full face centered, "
     "facing the camera. The mannequin's facial structure matches the "
     "reference person EXACTLY - same bone structure, same brow ridge, same "
     "nose shape, same lips, same jawline, same eyes. BUT the whole face is "
     "rendered in smooth glossy off-white porcelain like a museum display "
     "mannequin - polished ceramic skin, no skin pores, no realistic skin "
     "texture, no stubble, no wrinkles, no skin blemishes. Glossy porcelain "
     "eyes, porcelain nose, porcelain lips - all in matching smooth ceramic "
     "finish, face of a high-end display mannequin that strongly resembles "
     "the reference person. Rich COLOURED sculpted hair styled exactly as in "
     "the reference: {hair}. Nothing else in frame - no shoulders, no neck, "
     "no body. Plain light grey studio background, flat even neutral lighting, "
     "no rim light, one mannequin head only.",
     "index_timestep_zero"),
    ("face_side", "face", 1.0,
     "Show the SAME seamless glossy porcelain mannequin in left side profile, "
     "head only. Glossy porcelain face matching the reference person's "
     "features (brow, nose, lips, jaw) rendered in smooth ceramic - no skin "
     "texture, no stubble. Rich COLOURED sculpted hair matching the reference: "
     "{hair}. No body, no shoulders. EXACTLY ONE single figure, no duplicate, "
     "no mirror image. Plain light grey studio background, flat even neutral "
     "lighting, no rim light.",
     "uxo/uno"),
    ("face_back", "face", 1.0,
     "Show the back of a seamless glossy porcelain mannequin head, rear view. "
     "Smooth blank porcelain, no face visible. Rich COLOURED sculpted hair "
     "matching the reference: {hair} - visible from behind. No body. EXACTLY "
     "ONE single figure, no duplicate. Plain light grey studio background, "
     "flat even neutral lighting, no rim light.",
     "uxo/uno"),
    ("body_front", "face", 1.0,
     "Show a seamless glossy porcelain mannequin full body standing facing "
     "the camera, entire body head to feet, both feet on the ground, arms "
     "relaxed at sides. Glossy porcelain head with facial features matching "
     "the reference person, rendered in smooth ceramic. Rich COLOURED "
     "sculpted hair matching the reference: {hair}. Fully clothed head-to-toe "
     "in: {outfit}. EXACTLY ONE single figure, no duplicate, no mirror image. "
     "Plain light grey studio background, flat even neutral lighting, no rim "
     "light.",
     "index_timestep_zero"),
    ("body_side", "body_front", 1.0,
     "Show a seamless glossy porcelain mannequin full body side profile view "
     "facing left, entire body head to feet. Glossy porcelain head with "
     "features matching the reference person. Rich COLOURED sculpted hair "
     "matching the reference: {hair}. Fully clothed head-to-toe in: {outfit}. "
     "EXACTLY ONE single figure, no duplicate, no mirror image, no shadow "
     "clone. Plain light grey studio background, flat even neutral lighting, "
     "no rim light.",
     "uxo/uno"),
    ("body_back", "body_front", 1.0,
     "Show a seamless glossy porcelain mannequin full body rear view, back of "
     "head and full outfit visible, standing, entire body head to feet. Rich "
     "COLOURED sculpted hair matching the reference: {hair} - visible from "
     "behind. Fully clothed head-to-toe in: {outfit}. EXACTLY ONE single "
     "figure, no duplicate, no mirror image. Plain light grey studio "
     "background, flat even neutral lighting, no rim light.",
     "uxo/uno"),
]

# Roman-statue panels - REAL-FACE method (same as mannequin). Use the real
# person's photo as the ONE identity ref and render a classical Roman marble
# statue whose facial features match the ref EXACTLY. The face reads as carved
# Carrara marble (bone structure, brow, nose, lips, jaw) resembling the person,
# not realistic skin. Hair is carved marble matching the ref. When NO real
# photo exists, fall back to text-only hair injection. (view, ref_src, denoise,
# prompt-template, method)
ROMAN_STATUE_PANELS = [
    ("face", "real", 1.0,
     "A classical ancient Roman marble statue head and face, full face "
     "centered, facing the camera. The statue's facial structure matches the "
     "reference person EXACTLY - same bone structure, same brow ridge, same "
     "nose shape, same lips, same jawline, same eyes. BUT the whole face is "
     "sculpted from smooth white Carrara marble like a museum-quality Roman "
     "portrait bust - polished stone surface, chiseled features, no skin "
     "pores, no realistic skin texture, no stubble, no wrinkles, no skin "
     "blemishes. Marble eyes, marble nose, marble lips - all carved in "
     "matching stone, face of a classical Roman statue that strongly "
     "resembles the reference person. Sculpted marble hair matching the "
     "reference: {hair}. Nothing else in frame - no shoulders, no neck, no "
     "body. Plain light grey studio background, flat even neutral lighting, "
     "no rim light, one statue head only.",
     "index_timestep_zero"),
    ("face_side", "face", 1.0,
     "Show the SAME classical Roman marble statue in left side profile, head "
     "only. Marble face matching the reference person's features (brow, nose, "
     "lips, jaw) carved in smooth white stone - no skin texture, no stubble. "
     "Sculpted marble hair matching the reference: {hair}. No body, no "
     "shoulders. EXACTLY ONE single figure, no duplicate, no mirror image. "
     "Plain light grey studio background, flat even neutral lighting, no rim "
     "light.",
     "uxo/uno"),
    ("face_back", "face", 1.0,
     "Show the back of a classical Roman marble statue head, rear view. "
     "Smooth carved marble, no face visible. Sculpted marble hair matching "
     "the reference: {hair} - visible from behind. No body. EXACTLY ONE "
     "single figure, no duplicate. Plain light grey studio background, flat "
     "even neutral lighting, no rim light.",
     "uxo/uno"),
    ("body_front", "face", 1.0,
     "Show a classical Roman marble statue full body standing facing the "
     "camera, entire body head to feet, both feet on the ground. Marble head "
     "with facial features matching the reference person, carved in smooth "
     "white stone. Sculpted marble hair matching the reference: {hair}. Draped "
     "in a classical Roman toga or garment: {outfit}. EXACTLY ONE single "
     "figure, no duplicate, no mirror image. Plain light grey studio "
     "background, flat even neutral lighting, no rim light.",
     "index_timestep_zero"),
    ("body_side", "body_front", 1.0,
     "Show a classical Roman marble statue full body side profile view facing "
     "left, entire body head to feet. Marble head with features matching the "
     "reference person. Sculpted marble hair matching the reference: {hair}. "
     "Draped in a classical Roman toga or garment: {outfit}. EXACTLY ONE "
     "single figure, no duplicate, no mirror image, no shadow clone. Plain "
     "light grey studio background, flat even neutral lighting, no rim light.",
     "uxo/uno"),
    ("body_back", "body_front", 1.0,
     "Show a classical Roman marble statue full body rear view, back of head "
     "and draped garment visible, standing, entire body head to feet. Sculpted "
     "marble hair matching the reference: {hair} - visible from behind. Draped "
     "in a classical Roman toga or garment: {outfit}. EXACTLY ONE single "
     "figure, no duplicate, no mirror image. Plain light grey studio "
     "background, flat even neutral lighting, no rim light.",
     "uxo/uno"),
]

# facing -> which panel to use, per camera subject (face for close-ups, body
# for wide shots). 'right' reuses the left-facing side panel MIRRORED.
_FACING_PANEL = {
    "front":  {"face": "face",       "body": "body_front"},
    "left":   {"face": "face_side",  "body": "body_side"},
    "right":  {"face": "face_side",  "body": "body_side"},  # mirrored
    "back":   {"face": "face_back",  "body": "body_back"},
    "behind": {"face": "face_back",  "body": "body_back"},
}

# camera framing -> which body part the shot is ABOUT (drives face vs body ref)
_FRAMING_SUBJECT = {"EWS": "body", "WS": "body", "MS": "body",
                    "CU": "face", "ECU": "face"}

_BG_CHAR_HINT = re.compile(
    r"(?i)\b(in the background|behind him|behind her|stands behind|watches "
    r"from|in the doorway|across the room|in the distance|off to the side|"
    r"background|secondary)\b")


def _shot_facing(shot, default: str = "front") -> str:
    """Determine which way the on-screen character(s) face, from the camera
    angle + scene text. side panels are generated facing LEFT, so a right-facing
    shot uses the side panel mirrored."""
    angle = (shot.get("angle") or "").lower()
    scene = (shot.get("scene") or "").lower()
    if any(x in angle for x in ("from-behind", "from behind", "rear", "behind")):
        return "back"
    if any(x in angle for x in ("over-the-shoulder", "over the shoulder")):
        return "back"
    if re.search(r"(?i)\b(rear view|back of|from behind|turning away|turned "
                 r"away|walks away|his back|her back)\b", scene):
        return "back"
    if re.search(r"(?i)\b(facing left|turned left|to the left|left profile|"
                 r"left side|leftward|looking left)\b", scene):
        return "left"
    if re.search(r"(?i)\b(facing right|turned right|to the right|right "
                 r"profile|right side|rightward|looking right)\b", scene):
        return "right"
    return default


def _parse_shot_characters(shot) -> list[dict]:
    """Parse the shot's character field into [{name, facing}]. Supports a
    comma list ('Stefan Mandel, Richard Lustig') and per-name facing via
    'Name(left)'. Defaults facing from the shot's scene/angle heuristics.
    The raw field is cleaned first (Joe 2026-08-13) so role/placeholder tokens
    never become 'characters' (which would fetch a wrong real-photo ref)."""
    raw = _clean_character_field(shot.get("character", "NONE"))
    if not raw or raw.upper() == "NONE":
        return []
    default_facing = _shot_facing(shot)
    out = []
    for tok in raw.split(","):
        tok = tok.strip()
        if not tok or tok.upper() == "NONE":
            continue
        m = re.match(r"^(.*?)\s*\(([^)]*)\)\s*$", tok)
        if m:
            name, facing = m.group(1).strip(), m.group(2).strip().lower()
        else:
            name, facing = tok, default_facing
        if facing not in _FACING_PANEL:
            facing = default_facing if default_facing in _FACING_PANEL else "front"
        if name:
            out.append({"name": name, "facing": facing})
    return out


def _shot_uses_character(shot) -> bool:
    """False for close-ups that are explicitly a body part / object / prop
    (e.g. a hand, a phone, typing) - no person ref even if a name is attached."""
    st = str(shot.get("shot_type", "")).upper()
    scene = (shot.get("scene") or "").lower()
    if st in ("ECU", "CU") and re.search(
            r"(?i)\b(close-up of|closeup of|hand|hands|fingers|finger|"
            r"object|keyboard|keys|phone|screen|monitor|machine|tool|device|"
            r"wrist|watch|typing on|the\w* (button|lever|switch|dial|lock))\b",
            scene):
        return False
    return True


def _mirror_image(src: str, out: str) -> Optional[str]:
    """Horizontally flip an image (used to turn the left-facing side panels
    into right-facing refs). Returns the mirrored path or None on failure."""
    try:
        from PIL import Image, ImageOps
        im = Image.open(src).convert("RGB")
        ImageOps.mirror(im).save(out)
        return out if os.path.getsize(out) > 1000 else None
    except Exception as e:
        print(f"  [MIRROR] {e}")
        return None


def _is_business_shot(shot) -> bool:
    """True when a shot is a BUSINESS LOCATION - the company's physical
    presence (HQ, campus, office, factory, lab, storefront, or simply a shot
    that frames the company's building/place). Used to decide whether the shot
    should carry the BRAND BUILDING asset (real logo baked onto the facade)
    as an image ref (Joe 2026-08-09).

    Detection is TWO-fold:
      1. Explicit business-location keywords in the scene (HQ, campus, office,
         factory, lab, etc).
      2. OR the scene/narration names a KNOWN brand alongside a location cue
         (e.g. 'OpenAI California', 'the OpenAI campus', 'at Tesla') even when
         no generic HQ keyword appears.
    """
    scene = (shot.get("scene") or "").lower()
    narr = (shot.get("narration") or "").lower()
    if re.search(
            r"(?i)\b(hq|headquarters|head office|office|corporate|company|"
            r"startup|founded|boardroom|executive suite|lobby|factory floor|"
            r"data center|server room|warehouse|office building|signage|"
            r"storefront|lab|the office|their office|at the company)\b", scene):
        return True
    # Brand + location-cue heuristic: any known brand name appearing next to a
    # physical-location word in the scene or narration marks it a business shot.
    blob = f"{scene} {narr}"
    if any(kw in blob for kw in ("building", "campus", "hq", "headquarters",
                                 "office", "facility", "plant", "factory",
                                 "store", "storefront", "lab", "laboratory",
                                 "studio", "showroom", "warehouse", "floor")):
        _load_brand_manifest()
        for _bn in list(_KNOWN_BRANDS) + list(AI_ORGS):
            if _bn and _bn.lower() in blob:
                return True
    return False


def _llm_shot_ref_check(shot: dict, brand_assets: Optional[dict] = None,
                        topic: str = "") -> dict:
    """LLM decides which image refs a shot actually needs, from its narration.

    Given the shot's narration (the exact TTS line spoken over it) + the scene,
    the LLM lists every named business/company and every named person that the
    shot should reference, so the correct logo / real-photo refs get attached.
    This is the 'check' that decides IF a business or character is being
    mentioned and WHETHER to use an image-ref - driven by what the narration
    actually says (Joe 2026-08-09). Returns {"brands": [...], "characters": [...]}
    (fail-open: empty lists on no topic / LLM unreachable / error).
    """
    narration = str(shot.get("narration") or "").strip()
    scene = str(shot.get("scene") or "").strip()
    if not narration and not scene:
        return {"brands": [], "characters": []}
    # Candidate brands = those with a real ALREADY-CACHED logo file (so the
    # LLM can only pick something we can actually attach, and we never trigger
    # a network logo search inside the ref-check - only reuse on-disk assets).
    brand_names = []
    if brand_assets:
        for nm in list(_KNOWN_BRANDS) + list(brand_assets):
            _logo = BRAND_LOGO_DIR / f"{_brand_safe(nm)}.png"
            if _logo.is_file():
                brand_names.append(nm)
    char_names = [c["name"] for c in _parse_shot_characters(shot)]

    # FAST PATH (Joe 2026-08-09): a deterministic keyword match first. If the
    # narration/scene literally names a cached brand or a known character, attach
    # it WITHOUT an LLM call - this keeps the ref-check near-instant for the
    # common case and never stalls the pre-verify pass.
    low_text = f"{narration} {scene}".lower()
    fast_brands, fast_chars = [], []
    for _bn in brand_names:
        if _bn.lower() in low_text:
            fast_brands.append(_bn)
    for _cn in char_names:
        if _cn.lower() in low_text:
            fast_chars.append(_cn)
    # Fast path wins only if it found something definite; otherwise fall back to
    # the LLM for ambiguous mentions. Fail-open to empty on any LLM problem.
    if fast_brands or fast_chars:
        return {"brands": fast_brands, "characters": fast_chars}
    if not _llm_fast_reachable():
        return {"brands": [], "characters": []}
    try:
        data = _llm_json([
            {"role": "system", "content":
                ("You attach reference images to documentary shots. Given the "
                 "narration spoken over a shot and its scene, list EXACTLY the "
                 "entities that should appear in the image and therefore need a "
                 "reference photo attached: every real business/company explicitly "
                 "named (pick ONLY from the provided brand list), and every named "
                 "person explicitly present as a subject (pick ONLY from the "
                 "provided character list). Do NOT list entities merely implied "
                 "or off-screen. Reply ONLY as JSON: "
                 '{"brands": ["exact brand name"], "characters": ["exact name"]} '
                 "with empty arrays when nothing needs a reference. No markdown.")},
            {"role": "user", "content":
                f"NARRATION: {narration[:900]}\nSCENE: {scene[:600]}\n"
                f"AVAILABLE BRANDS: {', '.join(brand_names) if brand_names else '(none)'}\n"
                f"AVAILABLE CHARACTERS: {', '.join(char_names) if char_names else '(none)'}\n"
                f"REFS TO ATTACH:"},
        ], max_tokens=160, temp=0.1)
        if not isinstance(data, dict):
            return {"brands": [], "characters": []}
        def _clean(v):
            if isinstance(v, list):
                return [str(x).strip() for x in v if str(x).strip()]
            if isinstance(v, str) and v.strip():
                return [v.strip()]
            return []
        return {"brands": _clean(data.get("brands")),
                "characters": _clean(data.get("characters"))}
    except Exception:
        return {"brands": [], "characters": []}


def _select_shot_refs(shot, char_panels_cache, brand_assets=None, llm_refs=None):
    """Pick the reference image(s) for a shot. Returns (refs, notes).
    refs = image files fed to Krea (char panels, optionally mirrored, + a
    brand logo for business shots). notes = human summary of the choice.

    Ref logic (Joe 2026-08-06):
      - wide shot -> body panel; close-up -> face panel
      - facing left -> side panel as-is; facing right -> side panel MIRRORED
      - back/from-behind -> back panel
      - a close-up of a hand / object -> NO person ref at all
      - multiple people -> one ref each (face/body can mismatch per framing)
      - business HQ / interior shot -> also include the real brand logo ref

    CODE-X BACKEND (Joe 2026-08-09): codex is text-to-image, so we do NOT feed
    it the generated 1280x1280 character sheet panels (they're for the Krea
    identity path and produce weird results through gpt-image-2). Instead each
    person uses their REAL photo directly (_find_real_reference) as the single
    identity ref - the panels pass is skipped entirely for codex.
    """
    refs, notes = [], []
    backend = _active_image_backend()
    use_real_refs = (backend == "codex")
    st = str(shot.get("shot_type", "")).upper()
    subject = _FRAMING_SUBJECT.get(st, "body")
    visible = _shot_uses_character(shot)
    scene = (shot.get("scene") or "").lower()
    for ch in _parse_shot_characters(shot):
        if not visible:
            break
        if use_real_refs:
            # Real-person photo as the identity ref (no sheet panels). Bug 2 alt:
            # use the PRE-STYLIZED canonical portrait (facing forward, neutral
            # expression, in the channel style) so every shot of this person holds
            # BOTH their likeness AND the style - no more photo-vs-style split.
            real = _stylized_identity_portrait(
                ch["name"], shot.get("character_role", ""))
            if real and os.path.isfile(real):
                refs.append(real)
                notes.append(f"{ch['name']}: stylized portrait ({ch['facing']})")
            continue
        panels = char_panels_cache.get(ch["name"])
        if not panels:
            continue
        facing = ch["facing"]
        # Secondary/background figure -> prefer a body ref (seen full-ish)
        eff_subject = subject
        if _BG_CHAR_HINT.search(scene) and len(_parse_shot_characters(shot)) > 1:
            eff_subject = "body"
        panel_key = _FACING_PANEL[facing][eff_subject]
        panel_path = panels.get(panel_key) or panels.get("body_front") \
            or panels.get("face")
        if not panel_path or not os.path.isfile(panel_path):
            continue
        mirrored = (facing == "right" and panel_key.endswith("_side"))
        if mirrored:
            m = _mirror_image(panel_path, panel_path + ".mirror.png")
            if m:
                refs.append(m)
                notes.append(f"{ch['name']}: {panel_key} (mirrored right)")
                continue
        refs.append(panel_path)
        notes.append(f"{ch['name']}: {panel_key} ({facing})")
    # Brand ref: attach when the scene reads as a business shot (deterministic),
    # OR when the LLM ref-check decided the narration names a real brand (Joe
    # 2026-08-09 - the narration is the authoritative source for what the shot
    # should reference). For a BUSINESS-LOCATION shot we attach the BUILDING
    # asset (the real logo baked onto the building facade) so the logo visibly
    # appears on the location itself - not the bare logo mark (Joe 2026-08-09).
    llm_brand = (llm_refs or {}).get("brands") or []
    is_loc = _is_business_shot(shot)
    attach_brands = set()
    if is_loc:
        b = _match_brand_asset(shot.get("scene", ""), brand_assets)
        if b:
            attach_brands.add(b)
    for bname in llm_brand:
        asset = None
        if is_loc:
            # Context-aware logo asset (Joe 2026-08-09): interior shot -> the
            # logo-on-counter/wall asset; exterior/HQ -> the building asset;
            # else the screen asset; then the bare logo mark.
            _assets = (brand_assets or {}).get(bname, {})
            if any(w in (shot.get("scene") or "").lower() for w in INTERIOR_WORDS):
                asset = _assets.get("interior") or _assets.get("building") \
                    or _assets.get("screen")
            else:
                asset = _assets.get("building") or _assets.get("screen") \
                    or _assets.get("interior")
        if not (asset and os.path.isfile(asset)):
            asset = _find_logo(bname)
        if asset and os.path.isfile(asset):
            attach_brands.add(asset)
    for brand in attach_brands:
        if brand not in refs and os.path.isfile(brand):
            refs.append(brand)
            notes.append(f"brand logo: {os.path.basename(brand)}")
    return refs, "; ".join(notes)


def _char_panels_paths(sheets_dir: Path, safe: str) -> dict:
    """dict of view -> panel file path for a character's individual panels."""
    return {v: str(sheets_dir / f"{safe}_{v}.png") for v in CHAR_PANEL_VIEWS}


def _sheet_for_name(character_sheets: dict, name: str) -> Optional[dict]:
    """Tolerant character-sheet lookup by name: exact key, case-insensitive
    key, then a token within a comma-separated key. The last case handles
    multi-person shots where the legacy pipeline keyed ONE sheet def by
    'Name A, Name B' (e.g. ep8) - the def is reused for whichever person."""
    if not character_sheets:
        return None
    v = character_sheets.get(name)
    if isinstance(v, dict):
        return v
    nl = name.lower()
    for k, val in character_sheets.items():
        if isinstance(val, dict) and k.lower() == nl:
            return val
    for k, val in character_sheets.items():
        if not isinstance(val, dict):
            continue
        for token in k.split(","):
            if token.strip().lower() == nl:
                return val
    return None


def _generate_character_sheet(char_name: str, sheet: dict, seed: int,
                              sheets_dir: Path) -> dict:
    """Generate a character's SIX INDIVIDUAL 1280x1280 panels (NO grid merge):
    face / face_side / face_back / body_front / body_side / body_back. Returns
    a dict {view -> panel file path} used as refs by _select_shot_refs (each
    shot picks the perfect panel by framing + facing).

    Identity mode (krea2edit LoRA + real photo):
      face      = [real_photo] ONLY (ONE tight identity ref, ref_boost 4.0)
      all other = [face-front] ONLY (ref_boost 2.0 - prompt controls pose,
                  low boost stops the face ref bleeding into the body shot)
    STYLE is injected as TEXT via _style_inject (no style-plate refs).
    Real photo comes from Google Images (SerpAPI). Panels that fail are
    skipped; if the face panel fails the char gets no usable panels.
    """
    safe = re.sub(r"[^A-Za-z0-9]+", "_", char_name.lower()).strip("_") or "char"
    sheets_dir.mkdir(parents=True, exist_ok=True)
    existing = {v: str(sheets_dir / f"{safe}_{v}.png") for v in CHAR_PANEL_VIEWS}
    if all(os.path.isfile(p) for p in existing.values()):
        _regen = os.environ.get("REGEN_IMAGES", "0").strip().lower() in ("1", "yes", "y", "true")
        if _regen:
            for _p in existing.values():
                try:
                    os.remove(_p)
                except OSError:
                    pass
            print(f"  [SHEET] {char_name}: REGEN - dropping {len(existing)} cached panels")
        else:
            print(f"  [SHEET] {char_name}: reuse all {len(existing)} individual panels (1280x1280)")
            return existing
    # MATERIAL STYLES (mannequin / roman-statue): REAL-FACE method - use the
    # real person's photo as the identity ref and render the material look
    # (porcelain mannequin or marble statue) whose facial features match the
    # ref. Falls back to text-only hair injection when no real photo exists.
    look = _active_style_name()
    if look in ("mannequin", "roman-statue"):
        return _generate_material_panels(char_name, sheet, seed, sheets_dir,
                                         existing, look)
    ref_photo = _find_real_reference(char_name, sheet.get("role", ""))
    char_block = _character_prompt_block(sheet, "eye-level")
    # Identity mode (krea2edit LoRA, approved on the Elon test) when a real
    # photo exists: panels chain off ONE tight ref at a time (real photo ->
    # face -> face_side/back/body_front -> body_side/back), euler, boost 4.
    # STYLE is always injected as TEXT (_style_inject) - no style plate ref.
    use_identity = ref_photo is not None
    if use_identity:
        print(f"  [SHEET] {char_name}: identity mode (krea2edit LoRA, real ref)")
    else:
        print(f"  [SHEET] {char_name}: Kontext reference mode (no real photo)")
    panels: dict[str, str] = {}
    _pan_iter = (tqdm(SHEET_PANELS, desc=f"  [SHEET] {char_name} panels",
                      unit="panel", leave=False)
                 if _HAS_PROGRESS else SHEET_PANELS)
    for view, ref_src, denoise, view_desc, ref_method in _pan_iter:
        pan = sheets_dir / f"{safe}_{view}.png"
        if pan.is_file():
            panels[view] = str(pan)
            continue
        if use_identity:
            # Identity mode prompt = view_desc ONLY + the selected STYLE
            # injected as TEXT (_style_inject). VERIFIED 2026-08-04: prepending
            # the long RENDER_STYLE character block to an identity panel prompt
            # flips the model into img2img copy mode - the body panels
            # reproduced the face ref (giant head, same pixel position). The
            # short view text + a style tag control pose/framing/style while
            # the ONE tight identity ref locks the face. Short prompts
            # = clean full bodies (71px face at top of frame).
            p = view_desc + " " + _style_inject()
        else:
            # Kontext fallback (no real photo): full descriptive prompt.
            p = (f"{RENDER_STYLE}. {char_block}. {view_desc}. character "
                 f"reference panel - 1280x1280 portrait frame. {_style_inject()}")
        if use_identity:
            # Face panel: [real_photo] ONLY (ONE tight identity ref) - style
            # is injected as TEXT via _style_inject, no style plate ref. ALL
            # other panels (face_side/back, body_front/side/back): chain off
            # the FACE-FRONT panel ONLY, with a LOWER ref_boost
            # (SHEET_CHAIN_BOOST, default 2.0) so the prompt fully controls
            # pose/framing - ref_boost 4.0 on a face close-up forced the
            # giant head into body shots (img2img-style bleed).
            if view == "face":
                refs_full = [ref_photo] if ref_photo else []
                boost = 4.0
                g_px = 1024
            else:
                if "face" not in panels:
                    print(f"  [SHEET] skip {view} (face panel missing)")
                    continue
                refs_full = [panels["face"]]
                boost = float(os.environ.get("SHEET_CHAIN_BOOST", "2.0"))
                # grounding_px 768 for chained panels: 1024 causes SPLIT/
                # DUPLICATED compositions (documented krea2edit advisory) -
                # verified 2026-08-04: body_side at 1024 rendered 2 Elons
                # (2 body columns), at 768 it renders ONE clean figure.
                g_px = int(os.environ.get("SHEET_CHAIN_GROUNDING", "768"))
            print(f"  [SHEET] {view} panel for {char_name} "
                  f"(identity, refs={len(refs_full)}, boost={boost}, "
                  f"grounding={g_px})...")
            ok = _krea_generate(p, seed + 111 * len(view), str(pan),
                                ref_images=refs_full, denoise=denoise,
                                upscale=(_active_image_backend() == "codex"),
                                steps=10, width=CHAR_PANEL_W, height=CHAR_PANEL_H,
                                ref_mode="identity", ref_boost=boost,
                                grounding_px=g_px,
                                negative_prompt=NO_DUPLICATE_NEGATIVE)
        else:
            # Kontext fallback (no real photo): strict build order - every
            # panel needs its ref source ready first.
            if view == "face":
                ref = None
            elif ref_src == "face":
                if "face" not in panels:
                    print(f"  [SHEET] skip {view} (face panel missing)")
                    continue
                ref = [panels["face"]]
            else:  # body_front -> body_side / body_back
                if "body_front" not in panels:
                    print(f"  [SHEET] skip {view} (body_front missing)")
                    continue
                ref = [panels["body_front"]]
            if ref and not os.path.isfile(ref[0]):
                print(f"  [SHEET] ref vanished ({ref[0]}) - skipping {view}")
                continue
            print(f"  [SHEET] {view} panel for {char_name} "
                  f"(ref={ref_src}, kontext={ref_method})...")
            ok = _krea_generate(p, seed + 111 * len(view), str(pan),
                                ref_images=ref, denoise=denoise,
                                upscale=(_active_image_backend() == "codex"),
                                steps=14, width=CHAR_PANEL_W, height=CHAR_PANEL_H,
                                ref_mode="reference", ref_method=ref_method)
        if ok:
            panels[view] = str(pan)
    if "face" not in panels:
        print(f"  [SHEET] {char_name}: face panel failed - no panels usable")
        return {}
    # Return the individual panels (NO grid merge - each is used directly as
    # the perfect ref for whichever shot needs it, per framing/facing).
    sheets_dir.mkdir(parents=True, exist_ok=True)
    print(f"  [SHEET] {char_name}: {len(panels)} individual 1280x1280 panels "
          f"-> {sheets_dir}")
    return panels


def _generate_material_panels(char_name: str, sheet: dict, seed: int,
                              sheets_dir: Path, existing: dict,
                              look: str = "mannequin") -> dict:
    """Generate a character's SIX material panels (mannequin or roman-statue).

    Canonical REAL-FACE method (Joe-approved): use the real person's photo as
    the ONE identity ref and render the material look (glossy porcelain
    mannequin OR classical marble statue) whose facial features match the ref
    EXACTLY (bone structure, brow, nose, lips, jaw). The face reads as the
    material resembling the person, not realistic human skin. Hair matches the
    ref (coloured sculpted hair for mannequin, carved marble hair for statue).

      face      = [real_photo] ONLY (ONE tight identity ref, ref_boost 4.0)
      all other = [face-front] ONLY (ref_boost 2.0 - prompt controls pose)

    When NO real photo exists, fall back to text-only hair injection: hair is
    fetched as TEXT (_describe_hair_text) and the panels are pure text-to-image
    of the material with that described hair. Returns {view -> path}.
    """
    panels_spec = ROMAN_STATUE_PANELS if look == "roman-statue" else MANNEQUIN_PANELS
    safe = re.sub(r"[^A-Za-z0-9]+", "_", char_name.lower()).strip("_") or "char"
    hair = _describe_hair_text(char_name, sheet.get("role", ""), sheet)
    outfit = (sheet.get("outfit") or "").strip()
    ref_photo = _find_real_reference(char_name, sheet.get("role", ""))
    use_ref = ref_photo is not None
    if use_ref:
        print(f"  [SHEET] {char_name}: {look} REAL-FACE method "
              f"(real photo ref -> {look} face matching ref)")
    else:
        print(f"  [SHEET] {char_name}: {look} text-hair fallback "
              f"(no real photo)")
    panels: dict[str, str] = {}
    _pan_iter = (tqdm(panels_spec, desc=f"  [SHEET] {char_name} {look}",
                      unit="panel", leave=False)
                 if _HAS_PROGRESS else panels_spec)
    for view, _src, denoise, view_desc, ref_method in _pan_iter:
        pan = sheets_dir / f"{safe}_{view}.png"
        if pan.is_file():
            panels[view] = str(pan)
            continue
        p = view_desc.format(hair=hair, outfit=outfit) + " " + _style_inject()
        if use_ref:
            # Real-face: face panel uses the real photo (boost 4.0); all other
            # panels chain off the face-front panel (boost 2.0, 768 grounding).
            if view == "face":
                refs_full = [ref_photo]
                boost, g_px = 4.0, 1024
            else:
                if "face" not in panels:
                    print(f"  [SHEET] skip {view} (face panel missing)")
                    continue
                refs_full = [panels["face"]]
                boost = float(os.environ.get("SHEET_CHAIN_BOOST", "2.0"))
                g_px = int(os.environ.get("SHEET_CHAIN_GROUNDING", "768"))
            print(f"  [SHEET] {view} {look} panel for {char_name} "
                  f"(real-face, refs={len(refs_full)}, boost={boost})...")
            ok = _krea_generate(p, seed + 111 * len(view), str(pan),
                                ref_images=refs_full, denoise=denoise,
                                upscale=(_active_image_backend() == "codex"),
                                steps=14,
                                width=CHAR_PANEL_W, height=CHAR_PANEL_H,
                                ref_mode="identity", ref_boost=boost,
                                grounding_px=g_px)
        else:
            # Text-hair fallback: no ref, prompt controls the whole material.
            print(f"  [SHEET] {view} {look} panel for {char_name} "
                  f"(txt2img, hair: '{hair[:50]}')...")
            ok = _krea_generate(p, seed + 111 * len(view), str(pan),
                                ref_images=None, denoise=denoise,
                                upscale=(_active_image_backend() == "codex"),
                                steps=14, width=CHAR_PANEL_W, height=CHAR_PANEL_H,
                                ref_mode="img2img")
        if ok:
            panels[view] = str(pan)
    if "face" not in panels:
        print(f"  [SHEET] {char_name}: {look} face panel failed - no panels usable")
        return {}
    print(f"  [SHEET] {char_name}: {len(panels)} {look} 1280x1280 panels "
          f"-> {sheets_dir}")
    return panels


def _image_concurrency() -> int:
    """How many images to generate in parallel.

    Bulk-parallel codex benchmark (Joe 2026-08-09) measured throughput
    (images/hour) across N concurrent `codex exec /imagegen` calls:

        N=5  -> ~130 img/hr (collisions)
        N=10 -> ~220 img/hr (collisions)
        N=20 -> ~478 img/hr  <-- PEAK
        N=25 -> ~390 img/hr
        N=30 -> ~230 img/hr
        N=35 -> ~274 img/hr
        N=40 -> ~252 img/hr

    Codex CLI is a local wrapper around the remote gpt-image-2 API, so all
    parallel calls contend for the SAME rate limit - throughput rises to a
    sharp peak at 20 then collapses. The local ComfyUI backend stays
    sequential (1) because a single ComfyUI server processes jobs one at a
    time. Override with IMAGE_CONCURRENCY env var.
    """
    env = os.environ.get("IMAGE_CONCURRENCY", "").strip()
    if env:
        try:
            return max(1, int(env))
        except ValueError:
            pass
    backend = _active_image_backend()
    return 20 if backend in ("codex", "fal", "runpod") else 1


def _build_all_character_sheets(shots: list[dict],
                                character_sheets: Optional[dict],
                                sheets_dir: Path,
                                seed: int,
                                sheets_cache: Optional[dict] = None,
                                max_retries: int = 2) -> dict:
    """DEDICATED 'panels first' pass: generate every character's six identity
    panels BEFORE any shot renders. Doing this up front (instead of lazily
    inside the shot loop) means a face-panel failure is retried and resolved
    before shots are drawn, and all shots reuse the same panels - so a mid-loop
    ComfyUI hiccup can't cascade into sheets (and therefore faces) being missing
    across every shot. Returns {char_name -> {view: panel_path}}.

    CHARACTERS ARE INDEPENDENT, so on cloud/codex backends they generate in
    PARALLEL (IMAGE_CONCURRENCY workers). Panels WITHIN one character stay
    sequential because they chain (face -> face_side/body).
    """
    sheets_cache = sheets_cache if sheets_cache is not None else {}
    if not character_sheets:
        character_sheets = {}
    # Collect every character that appears across ALL shots being (re)generated.
    seen_names: list[str] = []
    for shot in shots:
        for ch in _parse_shot_characters(shot):
            nm = ch["name"]
            if nm not in sheets_cache and nm not in seen_names:
                seen_names.append(nm)
    if not seen_names:
        return sheets_cache
    print(f"\n  [SHEET] building character panels first "
          f"({len(seen_names)} character(s), then shots)...")

    def _build_one(nm: str) -> None:
        if nm in sheets_cache:
            return
        sheet_obj = _sheet_for_name(character_sheets, nm) or {}
        if not sheet_obj:
            defs = _build_character_sheets(
                shots, [s.get("narration", "") for s in shots])
            sheet_obj = defs.get(nm) or {}
        # Reuse panels already on disk (a prior run may have finished them).
        safe = re.sub(r"[^A-Za-z0-9]+", "_", nm.lower()).strip("_") or "char"
        existing = {v: str(sheets_dir / f"{safe}_{v}.png")
                    for v in CHAR_PANEL_VIEWS}
        if all(os.path.isfile(p) for p in existing.values()):
            sheets_cache[nm] = existing
            print(f"  [SHEET] reuse {nm} individual panels (on disk)")
            return
        panels: dict = {}
        for attempt in range(1, max_retries + 1):
            panels = _generate_character_sheet(
                nm, sheet_obj or {}, seed, sheets_dir) or {}
            if panels.get("face") and os.path.isfile(panels["face"]):
                break
            if attempt < max_retries:
                print(f"  [SHEET] {nm} face panel failed (attempt "
                      f"{attempt}/{max_retries}) - retrying...")
                time.sleep(2)
        if panels.get("face") and os.path.isfile(panels["face"]):
            sheets_cache[nm] = panels
        else:
            print(f"  [SHEET] {nm}: face panel failed after {max_retries} "
                  f"attempts - shots will render without a face ref")

    n = _image_concurrency()
    if n > 1 and len(seen_names) > 1:
        with ThreadPoolExecutor(max_workers=n) as ex:
            list(ex.map(_build_one, seen_names))
    else:
        for nm in seen_names:
            _build_one(nm)
    return sheets_cache


def _generate_all_shots(shots: list[dict], character_sheets: Optional[dict] = None,
                        episode_num: int = 0,
                        context: Optional[dict] = None,
                        location_sheets: Optional[dict] = None,
                        prop_assets: Optional[dict] = None,
                        brand_assets: Optional[dict] = None,
                        topic: str = "") -> list[dict]:
    """Generate ALL shot images locally with Krea 2 Turbo (ComfyUI) to
    1920x1080 (in-graph FaceUpDAT upscale from 1280x720) + style-card grade.

    - Chapter shots: black placeholder (no generation).
    - Prompt: TEXT prompt + the channel STYLE prompt-injected (no style refs).
    - Refs: _select_shot_refs picks the PERFECT character panel(s) per shot
      (wide -> body panel, close-up -> face panel, mirrored side refs by
      facing, multi-person refs, no person ref for hand/object closeups) +
      the real brand logo for business shots. Location always lives in the
      scene prompt; props included in the scene when present.
    - Character panels: SIX individual 1280x1280 images per character, built
      once and cached. Set FACE_LOCK=0 to disable.
    - Resume-safe: shots with an existing image file are skipped; failed shots
      are retried once with a fresh seed.
    """
    character_sheets = character_sheets or {}
    ep_dir = _episode_dir(episode_num) if episode_num else None
    black = _black_placeholder(episode_num) if episode_num else None
    face_lock = os.environ.get("FACE_LOCK", "1") != "0"
    # Brand assets (hacker screens / logo-on-building) may be empty on resume
    # runs - rebuild the lookup from the on-disk caches.
    if not brand_assets:
        brand_assets = _scan_brand_assets()
    sheets_dir = (ep_dir / CHAR_SHEETS_DIR_NAME) if ep_dir else None
    if sheets_dir:
        sheets_dir.mkdir(parents=True, exist_ok=True)
    # Location sheets + prop assets for this episode's world (built once,
    # before the shot loop). STYLE chain: style plate styles the ASSETS, the
    # shots are composed ONLY from the already-styled asset refs.
    if location_sheets is None and context:
        location_sheets = _build_location_sheets(context, 42000 + episode_num * 7,
                                                 ep_dir or EPISODES_DIR)
    if prop_assets is None and context:
        prop_assets = _build_prop_assets(context, 43000 + episode_num * 7,
                                         ep_dir or EPISODES_DIR)
    location_sheets = location_sheets or {}
    prop_assets = prop_assets or {}
    backend = _active_image_backend()
    backend_label = {"codex": "Codex CLI (gpt-image-2)", "fal": "fal.ai",
                     "runpod": "RunPod z-image-turbo",
                     "local": "local Krea 2 Turbo"}.get(backend, backend)
    print(f"\n[IMAGES] Generating {len(shots)} 3D shots via {backend_label} "
          f"({len(shots)} -> FaceUpDAT to output resolution)...")
    # ---- PANELS FIRST (dedicated pass) ----
    # Generate EVERY character's six identity panels up front, before any shot
    # renders. A face-panel failure is retried and resolved here so it can't
    # cascade into every shot missing a face.
    # CODE-X (Joe 2026-08-09): skip panel generation entirely - codex shots use
    # each person's REAL photo directly as the identity ref (_select_shot_refs),
    # not the generated Krea identity panels (they render weird through
    # gpt-image-2). The character_sheets dict is still used for prompt text.
    sheets: dict[str, dict] = {}
    if face_lock and sheets_dir and backend != "codex":
        sheets = _build_all_character_sheets(
            shots, character_sheets, sheets_dir, 70000 + episode_num,
            sheets_cache=sheets)
    elif backend == "codex":
        print("  [SHEET] codex backend: using REAL-PERSON photo refs, "
              "skipping generated character panels")

    # ---- SHOT-PROMPT VERIFICATION DEFINITIONS (used by cards + chunked render) ----
    from concurrent.futures import ThreadPoolExecutor as _TPE
    CHUNK = max(1, min(int(os.environ.get("SHOT_CHUNK_SIZE", "5")), len(shots) or 1))
    _regen = os.environ.get("REGEN_IMAGES", "0").strip().lower() in ("1", "yes", "y", "true")
    _todo = [s for s in shots
             if not s.get("is_chapter")
             and (_regen or not (s.get("image_path") and os.path.isfile(s.get("image_path", ""))))]

    def _verify_chunk(chunk: list) -> int:
        """LLM pre-verify + ref-check ONE chunk. Returns rewrite count.
        Idempotent: shots already carrying `_verified_prompt` are skipped (so the
        background verify during card generation isn't re-done by the chunked
        render loop)."""
        rewrites = 0
        for _vs in chunk:
            if _vs.get("_verified_prompt"):
                continue
            _base = _build_shot_prompt(_vs, character_sheets) + " " + _style_inject(allow_logo=_is_business_shot(_vs))
            _vp = _base
            if _SHOT_RELEVANCE_ON and topic:
                _vp = _ensure_shot_prompt_relevant(_base, _vs, character_sheets, None, topic)
                if _vp != _base:
                    rewrites += 1
            _vs["_verified_prompt"] = _vp
            _vs["_llm_refs"] = _llm_shot_ref_check(_vs, brand_assets, topic)
        return rewrites

    # ---- CHAPTER CARDS FIRST (PARALLEL, deterministic filenames) ----
    # Generate ALL chapter title cards up front, in PARALLEL, BEFORE the shot
    # pool. Card filenames are now SAFE under parallelism: codex prints the
    # exact "Saved at: <path>" it produced for each call, so each card claims
    # its OWN output deterministically (no more "newest unclaimed file" race
    # where card A copied card B's art -> wrong filenames). While the cards
    # render, a background thread LLM-verifies + ref-checks ALL shot prompts so
    # the LLM is busy during card generation (overlap) (Joe 2026-08-09).
    _chap_shots = [s for s in shots if s.get("is_chapter")]
    if _chap_shots and backend in ("codex", "fal"):
        _cn = _image_concurrency()
        print(f"  [CARDS] rendering {len(_chap_shots)} chapter title cards "
              f"in PARALLEL ({_cn} workers, deterministic filenames)...")
        # Kick off the LLM shot-prompt verification in the background NOW so it
        # runs while the cards generate.
        _verify_future = None
        if _todo:
            _verify_future = _TPE(max_workers=1).submit(
                lambda: sum(_verify_chunk(_todo[i:i + CHUNK])
                            for i in range(0, len(_todo), CHUNK)))

        def _render_card(_cs):
            _c = _generate_chapter_card(_cs, episode_num, topic,
                                        shots=shots, brand_assets=brand_assets,
                                        character_sheets=character_sheets)
            if _c:
                _cs["image_path"] = _c
                return (f"  [CARD] chapter {_cs.get('chapter_num', 1)}: "
                        f"{os.path.basename(_c)}")
            return (f"  [CARD] chapter {_cs.get('chapter_num', 1)}: "
                    f"black placeholder")

        if _cn > 1 and len(_chap_shots) > 1:
            with ThreadPoolExecutor(max_workers=_cn) as _ex:
                for _msg in _ex.map(_render_card, _chap_shots):
                    print(_msg)
        else:
            for _cs in _chap_shots:
                print(_render_card(_cs))
        if _verify_future is not None:
            _verify_future.result()

    # ---- CHUNKED PRE-VERIFY + RENDER (Joe 2026-08-09) ----
    # Process shots in chunks of CHUNK_SIZE (default 5): for each chunk we run
    # the LLM prompt pre-verification + ref-check on JUST that chunk (giving the
    # LLM the go-ahead), then fire those shots in PARALLEL, then move to the
    # next chunk. This avoids the old stall where ALL shots were LLM-verified
    # up front (2 LLM calls x N shots) with no visible progress - a busy LM
    # Studio could hang the whole run on a 180s per-call timeout before a single
    # image was generated. Now each chunk prints progress and only ever blocks
    # on CHUNK_SIZE LLM calls at a time.
    # (CHUNK/_todo/_verify_chunk/_TPE are defined above the chapter-card pass.)

    # Chapter shots (if any) are handled inline in _render_one via the pre-pass
    # cards; they're excluded from _todo above. Everything else is chunked.
    _img_iter = (tqdm(shots, desc="  [IMAGES] rendering shots", unit="shot",
                      leave=False) if _HAS_PROGRESS else shots)

    # Each shot is independent (its character panels are already built above),
    # so shots render in PARALLEL on cloud/codex backends. State per shot is a
    # distinct dict, so concurrent writes don't collide. A lock guards the
    # progress bar + completion prints only.
    _plock = threading.Lock()

    def _render_one(idx: int, shot: dict) -> None:
        if _HAS_PROGRESS:
            with _plock:
                _img_iter.set_description(
                    f"  [IMAGES] shot {idx+1}/{len(shots)}")
        if shot.get("is_chapter"):
            shot["seed"] = 0
            # Chapter cards are pre-generated sequentially BEFORE the parallel
            # shot pool (see pre-pass above) to avoid a codex output-detection
            # race. Reuse that card here; only generate if it's still missing
            # (e.g. black placeholder on local backend, or resume without the
            # pre-pass). The ASS chapter burn is skipped for codex runs so the
            # card text isn't doubled.
            card = shot.get("image_path")
            if not (card and os.path.isfile(card) and "chapter_" in os.path.basename(card)):
                card = _generate_chapter_card(shot, episode_num, topic,
                                              shots=shots, brand_assets=brand_assets,
                                              character_sheets=character_sheets)
            shot["image_path"] = card if card else black
            if card:
                with _plock:
                    print(f"  [SHOT {idx+1}/{len(shots)}] chapter title card: "
                          f"{os.path.basename(card)}")
            else:
                with _plock:
                    print(f"  [SHOT {idx+1}/{len(shots)}] chapter placeholder (no image)")
            return
        # REGEN_IMAGES=1 -> force re-generate (overwrite) instead of resuming.
        _regen = os.environ.get("REGEN_IMAGES", "0").strip().lower() in ("1", "yes", "y", "true")
        if not _regen and shot.get("image_path") and os.path.isfile(shot["image_path"]):
            with _plock:
                print(f"  [SHOT {idx+1}/{len(shots)}] resume: keep "
                      f"{os.path.basename(shot['image_path'])}")
            return
        # SEED LOCK (Joe 2026-08-17): reuse the seed that produced the
        # original art when this shot is being regenerated, so the re-render
        # matches the stored frame instead of drifting.
        seed = int(shot.get("seed") or 0) or (10000 + idx * 137 + random.randint(0, 999))
        shot["seed"] = seed
        # Reuse the prompt verified in the PRE-VERIFICATION pass (Joe 2026-08-09)
        # when it exists; otherwise build + gate inline (fallback for resume or
        # when the gate was off during the pre-pass).
        prompt = shot.get("_verified_prompt")
        if not prompt:
            prompt = _build_shot_prompt(shot, character_sheets) + " " + _style_inject(allow_logo=_is_business_shot(shot))
            # LLM relevance gate (Joe 2026-08-09): cross-check the prompt against the
            # article topic; rewrite the scene + rebuild if it drifted off-story.
            prompt = _ensure_shot_prompt_relevant(prompt, shot, character_sheets, _plock, topic)
        # Panels were built up front by _build_all_character_sheets (before the
        # shot loop); _select_shot_refs just picks the PERFECT panel(s) here.
        refs, notes = _select_shot_refs(shot, sheets, brand_assets,
                                        llm_refs=shot.get("_llm_refs"))
        out_path = str((ep_dir or EPISODES_DIR)
                       / _shot_filename(shot, int(shot.get("seq", 0) or (shot.get("narration_idx", idx) + 1))))
        n = len(refs)
        if refs:
            # single ref -> tight identity boost; multiple refs -> lower boost
            # so the char/logo panels don't bleed into each other.
            boost = 4.0 if n == 1 else 2.5
            g_px = 768 if n == 1 else 1024
            # Hard-ban duplicate figures on SINGLE-character shots (2-humans
            # bug). Multi-person shots (n>1) keep multiple identities.
            np = NO_DUPLICATE_NEGATIVE if n == 1 else ""
            ok = _krea_generate(prompt, seed, out_path,
                                ref_images=refs, denoise=1.0,
                                ref_mode="identity", ref_boost=boost,
                                grounding_px=g_px, upscale=True,
                                negative_prompt=np)
        else:
            ok = _krea_generate(prompt, seed, out_path,
                                ref_images=None, denoise=1.0, upscale=True)
        if not ok:
            # one retry with a fresh seed - same descriptive filename (overwrite)
            seed2 = seed + 31337
            out2 = out_path
            with _plock:
                print(f"  [SHOT {idx+1}/{len(shots)}] retrying with new seed...")
            if refs:
                ok = _krea_generate(prompt, seed2, out2,
                                    ref_images=refs, denoise=1.0,
                                    ref_mode="identity", ref_boost=boost,
                                    grounding_px=g_px, upscale=True,
                                    negative_prompt=np)
            else:
                ok = _krea_generate(prompt, seed2, out2,
                                    ref_images=None, denoise=1.0, upscale=True)
            if ok:
                seed, out_path = seed2, out2
        shot["seed"] = seed
        shot["image_path"] = out_path if ok else None
        if ok:
            # Codex shots are upscaled ASYNC (enqueued) - the grade must run
            # AFTER the upscale or it gets overwritten. Apply it in the final
            # pass after flush_upscales(). Non-codex backends grade inline.
            if _active_image_backend() != "codex":
                _apply_grade(out_path)
            label = notes if notes else "txt2img (no refs)"
            with _plock:
                print(f"  [SHOT {idx+1}/{len(shots)}] image ready -> refs: {label} | "
                      f"{os.path.basename(out_path)} ({out_path})")
        else:
            with _plock:
                print(f"  [SHOT {idx+1}/{len(shots)}] IMAGE FAILED after retry")
        if _HAS_PROGRESS:
            with _plock:
                _img_iter.update(1)

    # PIPELINED CHUNKED RENDER: LLM verifies a chunk (the go-ahead), then that
    # chunk fires in PARALLEL while the LLM verifies the NEXT chunk in a
    # background thread (overlap) - the LLM never idles and codex never waits on
    # the LLM. Gives visible per-chunk progress and never blocks on more than
    # CHUNK LLM calls at once (Joe 2026-08-09).
    from concurrent.futures import ThreadPoolExecutor as _TPE
    _n = _image_concurrency()
    _chunks = [shots[i:i + CHUNK] for i in range(0, len(shots), CHUNK)]

    def _verify_todo_chunk(chunk: list) -> int:
        todo = [s for s in chunk if s in _todo]
        if not todo:
            return 0
        rw = _verify_chunk(todo)
        labels = ", ".join(str(s.get("narration_idx", 0) + 1) for s in todo)
        print(f"  [VERIFY] chunk ({labels}):{', ' + str(rw) + ' rewrites' if rw else ''}")
        return rw

    def _render_chunk(cstart: int, chunk: list) -> None:
        labels = ", ".join(str(s.get("narration_idx", 0) + 1) for s in chunk
                           if s in _todo)
        if labels:
            print(f"  [CHUNK {cstart//CHUNK + 1}] rendering ({labels}) - "
                  f"firing in parallel ({min(_n, len(chunk))} workers)...")
        if _n > 1 and len(chunk) > 1:
            with ThreadPoolExecutor(max_workers=_n) as ex:
                list(ex.map(_render_one, range(cstart, cstart + len(chunk)), chunk))
        else:
            for _j, shot in enumerate(chunk):
                _render_one(cstart + _j, shot)

    # Prime: verify chunk 0's todo up front so the first render has its prompts.
    _verify_todo_chunk(_chunks[0])
    # Pipeline: verify chunk 0 up front, then verify each LATER chunk in the
    # background WHILE an earlier chunk renders (codex generation overlaps both
    # the LLM verify AND the async upscale queue). We pre-submit chunks 1 and 2
    # and at each iteration submit the chunk TWO ahead, so a chunk's verify has a
    # full extra chunk-render to finish - it is ALWAYS ready before that chunk
    # renders, so _render_one never falls back to inline LLM calls (which hammered
    # LM Studio and looked like a stall). Joe 2026-08-16.
    _pending: dict = {}
    for _k in range(1, min(3, len(_chunks))):   # pre-submit chunks 1 and 2
        _pending[_k] = _TPE(max_workers=1).submit(_verify_todo_chunk, _chunks[_k])
    for _ci, _chunk in enumerate(_chunks):
        _cstart = _ci * CHUNK
        # Chunk 0 is verified (sync above); later chunks' verify was submitted
        # 1-2 renders ago and is done - pop + surface rewrites.
        if _ci in _pending:
            _rw = _pending.pop(_ci).result()
            if _rw:
                print(f"  [CHUNK {_ci + 1}] {_rw} scene rewrites applied")
        # Kick off verification of the chunk TWO ahead so it has this render plus
        # the next to complete (overlap, never idles the LLM).
        if _ci + 2 < len(_chunks) and (_ci + 2) not in _pending:
            _pending[_ci + 2] = _TPE(max_workers=1).submit(
                _verify_todo_chunk, _chunks[_ci + 2])
        # Render the CURRENT chunk (its prompts are verified) in the main thread.
        # API backends enqueue upscales ASYNC (providers.enqueue_upscale), so
        # codex fires back-to-back while the upscaler catches up in the background.
        _render_chunk(_cstart, _chunk)
    # Join any still-running background verifies so no thread is left dangling
    # and their prompt-cache writes land before we drop the cache below.
    for _f in _pending.values():
        try:
            _f.result()
        except Exception:
            pass
    # Wait for the async upscale queue to drain so every shot is at the final
    # resolution before the render pass consumes them (Joe 2026-08-09). The
    # queue lets codex fire prompts back-to-back while the upscaler catches up.
    try:
        import providers
        providers.flush_upscales()
    except Exception:
        pass
    # Drop the pre-verify prompt cache so it doesn't bloat resume state.
    for _s in shots:
        _s.pop("_verified_prompt", None)
        _s.pop("_llm_refs", None)
    ok = sum(1 for s in shots if s.get("image_path"))
    print(f"  [IMAGES] {ok}/{len(shots)} images generated")
    return shots

# -- TTS (PocketTTS built-in male voice, 0dB normalized) -------------

def _pocket_tts_generate(text: str, output_path: str, timeout: int = 180,
                         voice: Optional[str] = None) -> bool:
    """Generate TTS via PocketTTS HTTP API. voice = clone WAV path; defaults
    to the episode narrator (TTS_VOICE). Per-character quote voices route via
    voice_map.json (see _lookup_voice)."""
    # TTS gate: strip LLM meta-commentary before it is spoken (belt-and-
    # suspenders on top of the parse-time strip + prompt rule 10).
    text = _strip_narration_meta(text)
    if not text.strip():
        print("  [TTS skip] narration meta only, nothing to speak")
        return False
    voice = voice or TTS_VOICE
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    import urllib.request as _ur
    boundary = "----splitnode" + str(int(time.time() * 1000))
    def _field(name, value):
        return (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n"
                f"{value}\r\n").encode()
    body = _field("text", text)
    if os.path.isfile(voice):
        # Custom cloned voice: upload the reference WAV as voice_wav
        with open(voice, "rb") as vf:
            ref_data = vf.read()
        body += (f"--{boundary}\r\n"
                 f"Content-Disposition: form-data; name=\"voice_wav\"; "
                 f"filename=\"{os.path.basename(voice)}\"\r\n"
                 f"Content-Type: audio/wav\r\n\r\n").encode() + ref_data + b"\r\n"
    else:
        # Built-in catalog voice
        body += _field("voice_url", voice)
    body += f"--{boundary}--\r\n".encode()
    req = _ur.Request(POCKET_TTS_URL + "/tts", data=body, method="POST", headers={
        "Content-Type": f"multipart/form-data; boundary={boundary}"
    })
    try:
        with _ur.urlopen(req, timeout=timeout) as r:
            if r.status != 200:
                print(f"  [TTS error] HTTP {r.status}")
                return False
            data = r.read()
        if len(data) < 1000:
            print(f"  [TTS error] output too small: {len(data)}b")
            return False
        with open(output_path, "wb") as f:
            f.write(data)
        # Verify
        if not os.path.isfile(output_path) or os.path.getsize(output_path) < 1000:
            print(f"  [TTS error] output not created: {output_path}")
            return False
        return True
    except Exception as e:
        print(f"  [TTS error] {e}")
        return False


def _normalize_voice_0db(wav_path: str) -> str:
    """Peak-normalize a voice clip to 0 dB. Returns path (in place)."""
    tmp = wav_path + ".norm.wav"
    r = subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", wav_path,
         "-af", "loudnorm=I=-16:TP=0:LRA=11", "-c:a", "pcm_s16le",
         "-ar", "24000", "-ac", "1", tmp],
        capture_output=True, text=True, timeout=60)
    if r.returncode == 0 and os.path.isfile(tmp) and os.path.getsize(tmp) > 1000:
        os.replace(tmp, wav_path)
    else:
        try: os.unlink(tmp)
        except: pass
    return wav_path

def _tts_worker(narration_paras: list[str], episode_num: int,
                results: dict, stop: threading.Event,
                intro_count: int = 0) -> None:
    """Background worker: queue EVERY narration paragraph into the PocketTTS
    server, one at a time, with retries. Runs concurrently with the shot list,
    character sheets and image generation (the big time win of the pipeline).

    results[i] = path of the finished clip (or None on failure). Files are
    named by NARRATION index (narration_{i:02d}.wav) so they map 1:1 to shots
    via shot['narration_idx'] even when shot parsing skips a paragraph.

    Two-voice narration (Joe 2026-08-13): the first `intro_count` sentences
    (the episode INTRO) are spoken with INTRO_VOICE (announcement, video start);
    everything from chapter 1 onwards uses STORY_VOICE (storytelling, video
    middle).
    """
    ep_dir = _ep_tts_dir(episode_num)
    ep_dir.mkdir(parents=True, exist_ok=True)
    for i, text in enumerate(narration_paras):
        if stop.is_set():
            results[i] = None
            continue
        out = str(ep_dir / f"narration_{i:02d}.wav")
        if _tts_clip_matches(ep_dir, i, text, char=False, path=out):
            results[i] = out
            print(f"  [TTS {i+1}/{len(narration_paras)}] reused ({_get_audio_duration(out):.1f}s)")
            continue
        voice = INTRO_VOICE if i < intro_count else STORY_VOICE
        ok = False
        for attempt in range(3):
            if _pocket_tts_generate(text, out, voice=voice):
                _normalize_voice_0db(out)
                ok = os.path.isfile(out) and os.path.getsize(out) > 1000
                if ok:
                    _tts_map_record(ep_dir, i, text)
                    break
            time.sleep(1 + attempt)
        tag = "INTRO" if i < intro_count else "STORY"
        if ok:
            results[i] = out
            print(f"  [TTS {i+1}/{len(narration_paras)}] {tag} {_get_audio_duration(out):.1f}s - {text[:50]}...")
        else:
            results[i] = None
            print(f"  [TTS {i+1}/{len(narration_paras)}] {tag} FAILED after retries - {text[:50]}...")
        time.sleep(0.2)


def _start_tts_worker(narration_paras: list[str], episode_num: int,
                      intro_count: int = 0):
    """Kick off TTS generation in a background thread. Returns (thread, results,
    stop_event). Join the thread before rendering. intro_count = number of
    leading sentences spoken with INTRO_VOICE (announcement)."""
    n_intro = max(0, min(intro_count, len(narration_paras)))
    print(f"\n[TTS] Queueing {len(narration_paras)} narration clips into PocketTTS "
          f"(intro: {n_intro} x {INTRO_VOICE}, rest: {STORY_VOICE}) in the background...")
    results: dict[int, Optional[str]] = {}
    stop = threading.Event()
    t = threading.Thread(target=_tts_worker,
                         args=(narration_paras, episode_num, results, stop,
                               n_intro),
                         daemon=True)
    t.start()
    return t, results, stop


def _finalize_tts(shots: list[dict], results: dict, episode_num: int) -> None:
    """Map finished TTS clips onto shots by narration index."""
    ep_dir = _ep_tts_dir(episode_num)
    for pos, shot in enumerate(shots):
        nidx = shot.get("narration_idx", pos)
        if shot.get("is_chapter"):
            # CHAPTER CARDS (Joe 2026-08-12): the 'Chapter N - Title' line is
            # built programmatically (see _insert_chapter_markers) and must be
            # read as ONE single TTS call so the card is never silent. The
            # worker queues every narration index (incl. chapters); if its clip
            # is missing/failed we generate it here on the spot so the chapter
            # ALWAYS reads. Same title feeds the card art, the ffmpeg title
            # burn and the description - read exactly once, no LLM duplication.
            shot["tts_path"] = str(ep_dir / f"narration_{nidx:02d}.wav")
            if _tts_clip_matches(ep_dir, nidx, shot["narration"], char=False,
                                 path=shot["tts_path"]):
                continue
            speak = _strip_narration_meta(shot.get("narration") or "")
            if speak and _pocket_tts_generate(speak, shot["tts_path"]):
                _normalize_voice_0db(shot["tts_path"])
                _tts_map_record(ep_dir, nidx, speak, char=False)
                print(f"  [TTS] chapter {shot.get('chapter_num')} read: "
                      f"{speak[:50]}")
            continue
        # Per-character clone voices (voice_map.json) override the narrator
        voice = _lookup_voice(shot.get("character", "NONE"))
        if voice:
            out_v = str(ep_dir / f"narration_{nidx:02d}_char.wav")
            if _tts_clip_matches(ep_dir, nidx, shot["narration"], char=True, path=out_v):
                shot["tts_path"] = out_v
                continue
            if _pocket_tts_generate(shot["narration"], out_v, voice=voice):
                _normalize_voice_0db(out_v)
                _tts_map_record(ep_dir, nidx, shot["narration"], char=True)
                shot["tts_path"] = out_v
                continue
        path = results.get(nidx)
        if path and _tts_clip_matches(ep_dir, nidx, shot["narration"], char=False, path=path):
            shot["tts_path"] = path
        else:
            # fallback: only accept a file written by the worker at this index
            # if its recorded narration matches the shot's current text.
            cand = str(ep_dir / f"narration_{nidx:02d}.wav")
            shot["tts_path"] = (cand if _tts_clip_matches(ep_dir, nidx, shot["narration"], char=False, path=cand) else None)
    ok = sum(1 for s in shots if s.get("tts_path") and os.path.isfile(s["tts_path"]))
    print(f"  [TTS] {ok}/{len(shots)} clips ready (0dB)")


def _ensure_all_tts_before_render(shots: list[dict], episode_num: int) -> int:
    """Regenerate any narration clip that is missing on disk RIGHT BEFORE the
    audio mix, so a spoken beat is never silently dropped from the final video
    (Joe 2026-08-12, review finding 4).

    Both _build_audio_mix and _render_video filter to shots with an existing
    tts_path - if a worker clip failed or was left None, that whole beat (image
    + narration) silently vanished. This closes the gap by regenerating it here
    (chapter + narrator + per-character clone voices). Returns number fixed."""
    ep_dir = _ep_tts_dir(episode_num)
    fixed = 0
    for s in shots:
        narr = (s.get("narration") or "").strip()
        if not narr:
            continue
        nidx = s.get("narration_idx", 0)
        path = s.get("tts_path") or ""
        if path and os.path.isfile(path) and os.path.getsize(path) > 1000:
            continue
        voice = _lookup_voice(s.get("character", "NONE"))
        if not voice and nidx < _state_intro_count(episode_num):
            voice = INTRO_VOICE  # announcement intro voice (Joe 2026-08-13)
        char = bool(voice) and not s.get("is_chapter") and voice != INTRO_VOICE
        out = str(ep_dir / f"narration_{nidx:02d}{'_char' if char else ''}.wav")
        if _tts_clip_matches(ep_dir, nidx, narr, char=char, path=out):
            s["tts_path"] = out
            continue
        speak = _strip_narration_meta(narr)
        if speak and _pocket_tts_generate(speak, out, voice=voice):
            _normalize_voice_0db(out)
            _tts_map_record(ep_dir, nidx, speak, char=char)
            s["tts_path"] = out
            fixed += 1
            print(f"  [TTS-FIX] regenerated clip {nidx}: {narr[:42]}")
    if fixed:
        print(f"  [TTS-FIX] regenerated {fixed} missing narration clip(s) before render")
    return fixed


def _generate_all_tts(shots: list[dict], episode_num: int) -> None:
    """Sequential TTS (used by resume flows where parallelism isn't needed)."""
    print(f"\n[TTS] Generating {len(shots)} narration clips (built-in male voice: {TTS_VOICE})...")
    ep_dir = _ep_tts_dir(episode_num)
    ep_dir.mkdir(parents=True, exist_ok=True)
    for idx, shot in enumerate(shots):
        nidx = shot.get("narration_idx", idx)
        out = str(ep_dir / f"narration_{nidx:02d}.wav")
        voice = _lookup_voice(shot.get("character", "NONE"))
        if not voice and nidx < _state_intro_count(episode_num):
            voice = INTRO_VOICE  # announcement intro voice (Joe 2026-08-13)
        ok = _pocket_tts_generate(shot["narration"], out, voice=voice)
        if ok:
            _normalize_voice_0db(out)
            dur = _get_audio_duration(out)
            print(f"  [TTS {idx+1}/{len(shots)}] {dur:.1f}s (0dB) - {shot['narration'][:50]}...")
        else:
            print(f"  [TTS {idx+1}/{len(shots)}] FAILED")
        shot["tts_path"] = out if ok else None
        time.sleep(0.5)

# -- Audio mix: voice + music + timecoded SFX ------------------------

def _build_music_chain(pool: list, target_dur: float, out_path: Path,
                       xf: float = 2.0, max_clips: int = 24) -> bool:
    """Build a continuous music bed from a tone pool by CROSSFADING DISTINCT
    tracks back to back (cycling through the pool, not looping one track).

    Each source clip plays to its NATURAL full length (never cut to a fixed
    chunk, and never cut to a shot/sentence boundary - the music just runs),
    then crossfades into the next distinct track until the section fills
    ~target_dur. Writes out_path (24kHz mono PCM) and returns success.

    Joe 2026-08-13: multiple music tracks rather than the same one over and
    over - whole clips play out regardless of the shot/sentence, roughly 65%
    suspense then 35% triumphant, NOT a separate clip per shot.
    """
    try:
        segs = []
        total = 0.0
        i = 0
        while total < target_dur and i < max_clips:
            src = SFX_DIR / pool[i % len(pool)]
            if not src.is_file():
                i += 1
                continue
            d = _get_audio_duration(str(src))
            if d <= 0:
                i += 1
                continue
            seg = out_path.parent / f"{out_path.name}.s{i}.wav"
            ok = subprocess.run(
                ["ffmpeg", "-y", "-v", "error", "-stream_loop", "-1",
                 "-i", str(src), "-t", f"{d:.2f}",
                 "-af", (f"afade=t=in:st=0:d={min(xf, d):.2f},"
                         f"afade=t=out:st={max(d - xf, 0):.2f}:d={min(xf, d):.2f}"),
                 "-c:a", "pcm_s16le", "-ar", "24000", "-ac", "1", str(seg)],
                capture_output=True, text=True, timeout=180).returncode == 0
            if not ok or not seg.is_file():
                i += 1
                continue
            segs.append(seg)
            total += d
            i += 1
        if not segs:
            return False
        m = len(segs)
        inputs = []
        for s in segs:
            inputs += ["-i", str(s)]
        fc = []
        for k in range(1, m):
            prev = "[a0]" if k == 1 else f"[a{k-1}]"
            outl = "[afin]" if k == m - 1 else f"[a{k}]"
            fc.append(f"[{k-1}:a]{prev}acrossfade=d={xf}{outl}")
        fc.append(f"[afin]atrim=0:{target_dur:.2f}[out]")
        r = subprocess.run(
            ["ffmpeg", "-y", "-v", "error"] + inputs +
            ["-filter_complex", ";".join(fc), "-map", "[out]",
             "-c:a", "pcm_s16le", "-ar", "24000", "-ac", "1", str(out_path)],
            capture_output=True, text=True, timeout=300)
        return r.returncode == 0 and out_path.is_file() and out_path.stat().st_size > 1000
    except Exception:
        return False


def _pace_gaps_after(shots: list[dict]) -> None:
    """Deterministic pacing: assign the silence GAP AFTER each shot's clip.

    This is where the 'voice should have gaps where necessary' requirement is
    implemented. The LLM cannot be trusted to pace - we compute the pause after
    each narration clip in code, based on the SHOT's content:
      - chapter card       -> long pause (card needs time to land)   1.6s
      - rhetorical ?       -> beat for the question to hang          1.2s
      - reveal/drop openers-> breath before the turn                 1.0s
      - hero/ECU beat      -> hold on the magnified moment           1.0s
      - place anchor       -> pause so the scene shift registers     1.0s
      - default            -> regular breathing beat                 1.0s
    Every clip gets a 1 second breathing gap so sentences never cut straight
    into the next clip (Joe 2026-08-12: 'breathing gap 1 second').
    Each shot dict gets shot['gap_after'] (seconds). Deterministic, no LLM.
    """
    for s in shots:
        gap = 1.0  # regular breathing beat (Joe: 1 second)
        if s.get("is_chapter"):
            gap = 1.6
        else:
            narration = (s.get("narration") or "").strip()
            low = narration.lower()
            if low.endswith(("?", "?")):
                gap = 1.2
            elif low.startswith(_REVEAL_OPENERS) or low.startswith(_DROP_OPENERS):
                gap = 1.0
            elif s.get("hero"):
                gap = 1.0
            elif _is_place_anchor(narration):
                gap = 1.0
        s["gap_after"] = gap
    total = sum(s.get("gap_after", 0.4) for s in shots)
    print(f"  [PACING] per-shot gaps applied (total {total:.1f}s of pause across "
          f"{len(shots)} clips)")


def _is_place_anchor(text: str) -> bool:
    """Heuristic: does the clip open with a real place anchor sentence?"""
    if not text:
        return False
    first = text.split(".")[0].strip()
    # A place anchor is a short standalone location sentence (comma-delimited
    # place, ends without a verb). e.g. 'Goulburn, New South Wales.'
    if _sentence_words(first) > 12:
        return False
    if "," in first and not first.rstrip(".").lower().endswith(("said", "says", "was", "is")):
        return True
    # single known place keyword
    return bool(re.search(
        r"\b(St\.|Saint|New South Wales|Queensland|Victoria|Sydney|Melbourne|"
        r"Brisbane|Perth|Adelaide|Russia|Moscow|St Petersburg|Goulburn|Brooklyn|"
        r"New York|London|Macau|Poland|Peru|Singapore|Australia)\b", first))


def _sa3_prompt_suspense(topic: str) -> str:
    """SA3 music-bed prompt for the 0-65% suspense section. Adaptive to the
    episode topic, never a concrete leaked example (Joe's no-examples rule)."""
    return (
        "Dark cinematic documentary underscore, tense suspenseful orchestral "
        "bed, low pulsing strings, brooding synth pads, slow heartbeat drums, "
        "rising dread, atmospheric and restrained, no melody on top, wide and "
        "moody, 80 BPM"
    )


def _sa3_prompt_triumphant(topic: str) -> str:
    """SA3 music-bed prompt for the 65%-end triumphant section."""
    return (
        "Triumphant cinematic documentary score, warm uplifting orchestral "
        "swell, hopeful brass and strings building to a victory theme, "
        "triumphant drums, emotional and inspiring, big wide finale, 90 BPM"
    )


# ---------------------------------------------------------------------------
# Per-2-paragraph adaptive SA3 music (Joe 2026-08-16)
#
# Instead of a single suspense->triumphant bed, the music now matches the story
# beat by beat: narration clips are grouped into consecutive PAIRS, each pair is
# timed on the voice timeline (clip_starts - the same timeline faster-whisper
# transcribes), its 2 paragraphs are sent to the local LLM for a Stable Audio 3
# prompt (which ends with an explicit BPM), and a track is generated at exactly
# that pair's duration. All segments are laid back-to-back to fill the episode.
# ---------------------------------------------------------------------------
MUSIC_DEFAULT_BPM = 85
MUSIC_LLM_MAXWORDS = 40


def _llm_music_prompt(story: str) -> str:
    """Ask the local LLM to write a Stable Audio 3 music prompt for a
    2-paragraph story beat. The prompt ends with an explicit BPM so the track's
    tempo matches the scene. Falls back to a neutral underscore on LLM failure
    (never blocks the music pass)."""
    if not story or not story.strip():
        return f"Dark cinematic documentary underscore, atmospheric, restrained, {MUSIC_DEFAULT_BPM} BPM"
    try:
        text = _llm_chat([
            {"role": "system", "content": (
                "You write music prompts for Stable Audio 3, a text-to-music model. "
                "Given a short story beat (two narration paragraphs), write ONE "
                "music prompt that matches the scene. Format: a short comma-separated "
                "list of genre, mood, instruments and energy, ending with the tempo "
                "as '<N> BPM' (pick a fitting tempo between 60 and 140). One sentence "
                f"only, under ~{MUSIC_LLM_MAXWORDS} words. No labels, no quotes, no "
                "intro - just the prompt.")},
            {"role": "user", "content": story},
        ], max_tokens=90, temp=0.7).strip().strip('"').strip()
        if not text:
            raise ValueError("empty")
        if not re.search(r"\d+\s*BPM", text, re.I):
            text = f"{text}, {MUSIC_DEFAULT_BPM} BPM"
        return text
    except Exception:
        return (f"Dark cinematic documentary underscore, atmospheric, "
                f"restrained, {MUSIC_DEFAULT_BPM} BPM")


def _build_adaptive_music_bed(shots: list, clip_starts: list, total_dur: float,
                              temp_dir: Path, episode_num: int) -> Optional[str]:
    """Generate one SA3 music segment per 2 narration paragraphs and assemble
    them into a single bed of total_dur, laid at their voice-timeline windows.

    Returns the assembled bed WAV path (already at MUSIC_DB) or None if SA3 is
    unavailable or every segment failed (caller falls back to the static pool)."""
    import sa3_music
    if not sa3_music.available():
        print("  [SA3] not ready - using static music pool")
        return None
    # Group clips into consecutive pairs, timed on the voice timeline.
    pairs = []
    n = len(shots)
    i = 0
    while i < n:
        j = min(i + 2, n)
        start = clip_starts[i]
        end = clip_starts[j] if j < n else total_dur
        dur = max(end - start, 1.0)
        story = " ".join((s.get("narration") or "").strip() for s in shots[i:j])
        pairs.append((start, dur, story))
        i = j
    seg_paths = []
    gen_ok = 0
    total = len(pairs)
    bar = tqdm(total=total, desc="SA3 music", unit="seg", leave=False) if _HAS_PROGRESS else None
    for k, (start, dur, story) in enumerate(pairs):
        prompt = _llm_music_prompt(story)
        out = temp_dir / f"music_pair_{k:03d}.wav"
        ok = sa3_music.generate_via_gradio(prompt, dur, str(out), story_context=story)
        if ok and out.is_file() and out.stat().st_size > 1000:
            seg_paths.append((str(out), start))
            gen_ok += 1
        if bar:
            bar.update(1)
            bar.set_postfix(bpm=re.search(r"(\d+)\s*BPM", prompt, re.I).group(1) if re.search(r"(\d+)\s*BPM", prompt, re.I) else "?")
    if bar:
        bar.close()
    if not seg_paths:
        print(f"  [AUDIO] SA3 adaptive bed: 0/{total} segments generated - using static pool")
        return None
    print(f"  [AUDIO] SA3 adaptive bed: {gen_ok}/{total} 2-paragraph segments generated")
    # Assemble: place each segment at its start time (adelay) and mix at MUSIC_DB.
    inputs, fparts, labels = [], [], []
    for k, (path, start) in enumerate(seg_paths):
        inputs += ["-i", path]
        d = int(round(start * 1000))
        fparts.append(f"[{k}:a]aresample=44100,adelay={d}|{d}[s{k}]")
        labels.append(f"[s{k}]")
    fscript = temp_dir / "music_adaptive_filter.txt"
    fscript.write_text(
        ";".join(fparts) + ";" + "".join(labels) +
        f"amix=inputs={len(labels)}:duration=longest:normalize=0,"
        f"atrim=0:{total_dur:.2f},"
        f"afade=t=in:st=0:d=0.5,"
        f"afade=t=out:st={max(total_dur - 0.6, 0):.2f}:d=0.5,"
        f"volume={MUSIC_DB}dB[out]", encoding="utf-8")
    music_raw = temp_dir / "music_adaptive.wav"
    r = subprocess.run(
        ["ffmpeg", "-y", "-v", "error"] + inputs +
        ["-filter_complex_script", str(fscript), "-map", "[out]",
         "-c:a", "pcm_s16le", "-ar", "24000", "-ac", "1", str(music_raw)],
        capture_output=True, text=True, timeout=300)
    if r.returncode == 0 and music_raw.is_file() and music_raw.stat().st_size > 1000:
        return str(music_raw)
    print(f"  [AUDIO] SA3 adaptive bed assemble failed: {r.stderr[-200:]}")
    return None


def _build_audio_mix(shots: list[dict], episode_num: int,
                     title_events: Optional[list] = None):
    """Build the full audio track: voice (0dB) + music (-19.5dB) + SFX (-15dB hit-aligned).

    New SFX in this version:
      - mixkit glitchy suspense hit at t=0 (every video opens with it)
      - camera shutter at every new-character / new-location switch
      - typewriter clicks at each location/person title start (1.5s)
      - glitch-off at each title start + 5.5s (0.5s)

    Returns (mix_wav_path, voice_wav_path, clip_starts):
      voice_wav_path is the deterministic voice-only track (for whisper timing),
      clip_starts[i] is the REAL absolute start time of clip i (per-shot pacing gaps).
    """
    valid = [s for s in shots if s.get("tts_path") and os.path.isfile(s["tts_path"])]
    if not valid:
        print("  [AUDIO] No TTS clips")
        return None, None, []

    # Deterministic pacing gaps after each clip (before the concat math)
    _pace_gaps_after(valid)

    temp_dir = Path(tempfile.mkdtemp(prefix=f"sb_audio_{episode_num}_"))
    try:
        # -- Voice track: concat with per-shot pacing gaps; REAL start times --
        voice_parts = []
        clip_starts = []  # absolute start time of each clip in the final timeline
        cursor = 0.0
        for shot in valid:
            clip_starts.append(cursor)
            d = _get_audio_duration(shot["tts_path"])
            gap = shot.get("gap_after", 0.3)
            voice_parts.append((shot["tts_path"], cursor, d, gap))
            cursor += d + gap

        total_dur = cursor
        print(f"  [AUDIO] Voice timeline: {total_dur:.1f}s total, {len(valid)} clips")

        # Concat voice with silence pads
        concat_list = temp_dir / "voice_concat.txt"
        with open(concat_list, "w") as f:
            for path, start, d, gap in voice_parts:
                f.write(f"file '{str(Path(path).resolve())}'\n")
                # pad gap seconds of silence after each clip
                pad = temp_dir / f"pad_{int(start*1000)}.wav"
                subprocess.run(
                    ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                     f"anullsrc=r=24000:cl=mono", "-t", f"{gap:.2f}",
                     "-c:a", "pcm_s16le", str(pad)],
                    capture_output=True, text=True, timeout=30)
                f.write(f"file '{str(pad.resolve())}'\n")
        voice_raw = temp_dir / "voice_raw.wav"
        r_raw = subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
             "-i", str(concat_list), "-c:a", "pcm_s16le", str(voice_raw)],
            capture_output=True, text=True, timeout=120)
        if r_raw.returncode != 0 or not voice_raw.is_file() or voice_raw.stat().st_size < 1000:
            print(f"  [AUDIO] WARN voice_raw concat failed: {r_raw.stderr[-200:]} - "
                  f"skipping whisper voice track")
            voice_raw = None
        voice_path = temp_dir / "voice_0db.wav"
        if voice_raw is not None:
            r_0db = subprocess.run(
                ["ffmpeg", "-y", "-v", "error", "-i", str(voice_raw),
                 "-af", f"volume={VOICE_DB}dB", "-c:a", "pcm_s16le", str(voice_path)],
                capture_output=True, text=True, timeout=60)
            if r_0db.returncode != 0 or not voice_path.is_file() or voice_path.stat().st_size < 1000:
                print(f"  [AUDIO] WARN voice_0db volume step failed: {r_0db.stderr[-200:]} - "
                      f"using voice_raw for whisper track")
                voice_path = voice_raw
        # Deterministic copy of the voice-only track for the whisper title pass
        voice_out = str(_ep_audio_dir(episode_num) / "voice.wav")
        if os.path.isfile(voice_out) and os.path.getsize(voice_out) > 1000:
            pass
        elif voice_path is not None and os.path.isfile(str(voice_path)):
            try:
                shutil.copyfile(str(voice_path), voice_out)
            except Exception as _ve:
                print(f"  [AUDIO] WARN could not copy whisper voice track: {_ve}")

        # -- Music bed: continuous, MULTIPLE distinct tracks. Suspense 0-65%
        #    of the timeline crossfading into triumphant 65%-end. Within each
        #    section the pool's tracks are crossfaded back-to-back at their
        #    NATURAL length (no per-shot cuts, no fixed chunks, no single-track
        #    loop) - the music just runs under the whole episode and SFX sit on
        #    top (Joe 2026-08-13: multiple tracks, whole clips play out, ~65/35).
        music_segments = []  # fallback path only
        music_path = None
        try:
            suspense_pool = MUSIC_LIBRARY["suspense"]
            triumphant_pool = MUSIC_LIBRARY["triumphant"]
            section_cut = total_dur * 0.65
            xf = 2.0  # crossfade seconds at each track boundary and at the style switch

            if section_cut > 6 and (total_dur - section_cut) > 6:
                sus_raw = temp_dir / "music_sus_raw.wav"
                tri_raw = temp_dir / "music_tri_raw.wav"
                music_raw = temp_dir / "music_cont.wav"
                sa3_ok = False
                # STABLE AUDIO 3 bed (Joe 2026-08-14): generate a real text-to-audio
                # bed with SA3, falling back to the static pool if it's unavailable.
                if os.environ.get("MUSIC_BACKEND", "sa3").strip().lower() == "sa3":
                    import sa3_music
                    if sa3_music.available():
                        # Per-2-paragraph adaptive bed (Joe 2026-08-16): the music
                        # matches the story beat by beat instead of one fixed
                        # suspense->triumphant split.
                        adap = _build_adaptive_music_bed(
                            valid, clip_starts, total_dur, temp_dir, episode_num)
                        if adap:
                            music_path = adap
                            sa3_ok = True
                            print(f"  [AUDIO] Music: SA3 adaptive bed - one track per "
                                  f"2 narration paragraphs, ducked under voice")
                        else:
                            print("  [AUDIO] SA3 adaptive bed failed - static pool fallback")
                    else:
                        print("  [SA3] not ready - using static music pool")
                if not sa3_ok:
                    ok1 = _build_music_chain(suspense_pool, section_cut, sus_raw, xf)
                    ok2 = _build_music_chain(triumphant_pool, total_dur - section_cut, tri_raw, xf)
                if (not sa3_ok) and (ok1 and ok2) and sus_raw.is_file() and tri_raw.is_file():
                    r = subprocess.run(
                        ["ffmpeg", "-y", "-v", "error",
                         "-i", str(sus_raw), "-i", str(tri_raw),
                         "-filter_complex",
                         f"[0:a]atrim=0:{section_cut:.2f},"
                         f"afade=t=out:st={section_cut - xf:.2f}:d={xf:.2f}[a];"
                         f"[1:a]atrim=0:{total_dur - section_cut:.2f},asetpts=PTS-STARTPTS,"
                         f"afade=t=in:st=0:d={xf:.2f}[b];"
                         f"[a][b]amix=inputs=2:duration=longest:normalize=0,"
                         f"afade=t=in:st=0:d=0.5,"
                         f"afade=t=out:st={max(total_dur - 0.6, 0):.2f}:d=0.5,"
                         f"volume={MUSIC_DB}dB[out]",
                         "-map", "[out]", "-c:a", "pcm_s16le",
                         "-ar", "24000", "-ac", "1", str(music_raw)],
                        capture_output=True, text=True, timeout=300)
                    if r.returncode == 0 and music_raw.is_file() and music_raw.stat().st_size > 1000:
                        music_path = str(music_raw)
                        print(f"  [AUDIO] Music: multi-track continuous bed - "
                              f"suspense 0-{section_cut:.0f}s, {xf:.0f}s crossfade into "
                              f"triumphant to {total_dur:.0f}s, "
                              f"x{len(suspense_pool)}/{len(triumphant_pool)} tracks, "
                              f"-{abs(MUSIC_DB):.0f}dB, no per-shot cuts")
        except Exception as e:
            print(f"  [AUDIO] Continuous music bed failed ({e}) - using fallback")

        # FALLBACK (continuous failed): old per-shot cycling bed
        if music_path is None:
            sus_idx, tri_idx = 0, 0
            suspense_pool = MUSIC_LIBRARY["suspense"]
            triumphant_pool = MUSIC_LIBRARY["triumphant"]
            section_cut = total_dur * 0.65
            for shot, start in zip(valid, clip_starts):
                d = _get_audio_duration(shot["tts_path"]) + 0.3
                if start < section_cut:
                    pool, cur = suspense_pool, sus_idx
                    sus_idx += 1
                else:
                    pool, cur = triumphant_pool, tri_idx
                    tri_idx += 1
                track = pool[cur % len(pool)]
                track_path = SFX_DIR / track
                if not track_path.is_file():
                    continue
                seg = temp_dir / f"music_seg_{int(start*1000)}.wav"
                subprocess.run(
                    ["ffmpeg", "-y", "-v", "error", "-i", str(track_path),
                     "-t", f"{d:.2f}", "-af",
                     f"afade=t=in:st=0:d=0.4,afade=t=out:st={max(d-0.5,0):.2f}:d=0.5,volume={MUSIC_DB}dB",
                     "-c:a", "pcm_s16le", "-ar", "24000", "-ac", "1", str(seg)],
                    capture_output=True, text=True, timeout=60)
                if seg.is_file() and os.path.getsize(seg) > 1000:
                    music_segments.append((seg, start))
            print(f"  [AUDIO] Music (FALLBACK): suspense x{sus_idx} / triumphant x{tri_idx}, "
                  f"per-shot segments")
            if music_segments:
                mlist = temp_dir / "music_list.txt"
                with open(mlist, "w") as f:
                    for seg, start in music_segments:
                        f.write(f"file '{str(seg.resolve())}'\n")
                music_raw = temp_dir / "music_raw.wav"
                subprocess.run(
                    ["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
                     "-i", str(mlist), "-c:a", "pcm_s16le", str(music_raw)],
                    capture_output=True, text=True, timeout=120)
                if music_raw.is_file() and os.path.getsize(music_raw) > 1000:
                    music_path = str(music_raw)

        # -- SFX placements: (src, target_time, max_dur) -- hit lands at target --
        # Whisper word timings of the voice track - used to pin key-word whooshes
        # and foley hit points to the EXACT spoken time (Joe 2026-08-12).
        words = _transcribe_voice(episode_num, voice_out)

        placements = []  # (src, target_time, max_dur, db)
        # 1) Intro glitchy suspense hit at the very start of every video
        intro = SFX_DIR / TITLE_SFX["intro"]
        if intro.is_file():
            placements.append((str(intro), 0.0, 6.5, SFX_DB))
            print("  [AUDIO] SFX intro glitch hit @0.0s")
        rng = random.Random(episode_num * 7)
        def _pick_sfx(prefix: str) -> Optional[str]:
            ks = [k for k in SFX_LIBRARY
                  if k.startswith(prefix) and _sfx_path(k)]
            return rng.choice(ks) if ks else None
        if not MINIMAL_AUDIO:
            # 2) Per-shot LLM SFX (hit at shot start + 0.2s). Long ambience capped.
            for shot, start in zip(valid, clip_starts):
                name = shot.get("sfx", "NONE")
                if name == "NONE" or name not in SFX_LIBRARY:
                    continue
                src = _sfx_path(name)
                if src:
                    cap = min(SFX_LIBRARY.get(name, {}).get("dur", 8.0), 10.0)
                    placements.append((str(src), start + 0.2, cap, SFX_DB))
            # 2b) KEY-WORD whoosh (Joe 2026-08-12): on the 1 key sentence per
            #     paragraph, play the whoosh with its hit EXACTLY on the key word's
            #     spoken time (whisper-resolved). The words are ALSO shown on screen
            #     via the keyword ASS events built in _render_video.
            kw_whoosh = "soundreality-whoosh-pointer-243108.mp3"
            kw_meta = SFX_LIBRARY.get(kw_whoosh, {})
            if _sfx_path(kw_whoosh):
                for pos, (shot, start) in enumerate(zip(valid, clip_starts)):
                    if not shot.get("is_key") or not shot.get("key_words"):
                        continue
                    cs = start
                    ce = (clip_starts[pos + 1] if pos + 1 < len(clip_starts)
                          else cs + _get_audio_duration(shot["tts_path"]))
                    anchor = shot["key_words"][0]
                    t = _resolve_substring_time(shot.get("narration", ""), anchor,
                                                words, cs, ce)
                    if t <= cs + 0.3 and len(shot["key_words"]) > 1:
                        t = _resolve_substring_time(shot.get("narration", ""),
                                                    " ".join(shot["key_words"]),
                                                    words, cs, ce)
                    placements.append((str(_sfx_path(kw_whoosh)), t,
                                       kw_meta.get("max_dur", 2.0), KEYWORD_DB))
                    print(f"  [AUDIO] KEYWORD whoosh '{' '.join(shot['key_words'])}' "
                          f"@{t:.2f}s (-{abs(KEYWORD_DB):.0f}dB)")
            # 2c) FOLEY (Joe 2026-08-12): the LLM foley ledger (shot['foley']) plays
            #     at the trigger's whisper time; scene-keyword fallback otherwise.
            #     ALL foley plays at FOLEY_DB (-5dB).
            for pos, (shot, start) in enumerate(zip(valid, clip_starts)):
                if shot.get("is_chapter"):
                    continue
                cs = start
                ce = (clip_starts[pos + 1] if pos + 1 < len(clip_starts)
                      else cs + _get_audio_duration(shot["tts_path"]))
                planned = shot.get("foley") or []
                if planned:
                    for f in planned:
                        fsrc = _sfx_path(f.get("sfx", ""))
                        if not fsrc:
                            continue
                        ft = _resolve_substring_time(shot.get("narration", ""),
                                                     f.get("trigger", ""), words,
                                                     cs, ce)
                        bed = max(1.5, min(ce - ft - 0.2, 8.0))
                        placements.append((str(fsrc), ft, bed, FOLEY_DB))
                        print(f"  [AUDIO] FOLEY '{f.get('sfx')}' @{ft:.2f}s "
                              f"(-{abs(FOLEY_DB):.0f}dB) {shot.get('narration','')[:36]}")
                elif shot.get("sfx", "NONE") == "NONE":
                    foley = _foley_for_scene(shot.get("scene", ""))
                    if foley:
                        fsrc = _sfx_path(foley)
                        if fsrc:
                            bed = max(1.5, min(ce - cs - 0.2, 8.0))
                            placements.append((str(fsrc), cs + 0.2, bed, FOLEY_DB))
                            print(f"  [AUDIO] FOLEY '{foley}' @{cs + 0.2:.1f}s "
                                  f"(-{abs(FOLEY_DB):.0f}dB, scene fallback)")
        if not MINIMAL_AUDIO:
            # 3) Camera shutter ONLY on the FIRST establishing shot of a person OR
            #    of a location (Joe 2026-08-12), at -4dB - NOT every establishing
            #    frame and NOT every new-char/location switch.
            shutter = SFX_DIR / TITLE_SFX["shutter"]
            shutter_kinds_seen = set()
            for shot, start in zip(valid, clip_starts):
                if not shot.get("is_establishing"):
                    continue
                kind = shot.get("establishing_kind") or "person"
                if kind in shutter_kinds_seen:
                    continue
                if shutter.is_file():
                    placements.append((str(shutter), start + 0.1, None, SHUTTER_DB))
                    shutter_kinds_seen.add(kind)
                    print(f"  [AUDIO] Camera shutter @{start + 0.1:.1f}s "
                          f"(FIRST establishing {kind}, -{abs(SHUTTER_DB):.0f}dB)")
                # VCR/static sweep on establishing frames (Joe 2026-08-09, kept)
                if shot.get("sfx", "NONE") == "NONE":
                    wkey = _pick_sfx("sweep-")
                    if wkey:
                        wm = SFX_LIBRARY[wkey]
                        placements.append((str(_sfx_path(wkey)), start + 0.15,
                                           wm.get("hit", 0.5) + 1.0, SFX_DB))
                        print(f"  [AUDIO] Sweep '{wkey}' @{start + 0.15:.1f}s")
        # 3b) Chapter-card whoosh (Joe 2026-08-12): the Sub Bass whoosh REPLACES
        #     the old boom. Its hit lands exactly on the card transition
        #     (chapter TTS start); the whoosh BUILD plays in the gap BEFORE the
        #     card so SFX leads then the card TTS follows (spacious). -4dB.
        ch_whoosh = "Whooshs/Sub Bass - Whoosh - (Nikko Hunt's S.D.Essentials).wav"
        ch_meta = SFX_LIBRARY.get(ch_whoosh, {})
        for ev in title_events or []:
            if ev.get("kind") != "chapter":
                continue
            ct = ev.get("start", 0.0)
            if ct <= 1.0:
                continue
            riser = _pick_sfx("riser-")
            if riser:
                rm = SFX_LIBRARY[riser]
                placements.append((str(_sfx_path(riser)), ct - 0.5,
                                   rm.get("hit", 2.0) + 0.6, SFX_DB))
                print(f"  [AUDIO] Chapter riser '{riser}' -> {ct:.1f}s")
            if _sfx_path(ch_whoosh):
                placements.append((str(_sfx_path(ch_whoosh)), ct - 0.1,
                                   ch_meta.get("max_dur", 4.0), CHAPTER_DB))
                print(f"  [AUDIO] Chapter WHOOSH (sub bass) @{ct - 0.1:.1f}s "
                      f"(-{abs(CHAPTER_DB):.0f}dB)")
        # 4) Typewriter clicks + glitch-off for every location/person title,
        #    and typewriter clicks for the chapter title burn (Joe 2026-08-12).
        for ev in title_events or []:
            if ev.get("kind") not in ("location", "person", "chapter"):
                continue
            st = ev.get("start", 0.0)
            tw = SFX_DIR / TITLE_SFX["typewriter"]
            gl = SFX_DIR / TITLE_SFX["glitch"]
            # Chapter title types 0.15s after the card starts (kicker pops
            # first); location/person type immediately. Only the clicks for a
            # chapter card - no glitch-off (chapters don't glitch like the
            # bottom-left cards).
            tw_start = st + (0.15 if ev.get("kind") == "chapter" else 0.0)
            if tw.is_file():
                placements.append((str(tw), tw_start, TYPEWRITER_SEC, SFX_DB))
            if gl.is_file() and ev.get("kind") in ("location", "person"):
                placements.append((str(gl), st + TYPEWRITER_SEC + TITLE_HOLD_SEC,
                                   GLITCH_OFF_SEC, SFX_DB))
        # Dedupe: two titles on the same paragraph fire at the same moment -
        # keep only ONE sound so clicks don't double up (preserve db).
        deduped = []
        for src, target, max_dur, db in placements:
            dup = False
            for d_src, d_tgt, _d_max, _d_db in deduped:
                if d_src == src and abs(d_tgt - target) < 0.05:
                    dup = True
                    break
            if not dup:
                deduped.append((src, target, max_dur, db))
        placements = deduped
        # 5) Resolve placements -> delays/trims (per-sound db carried through)
        sfx_inputs, sfx_delays, sfx_trims, sfx_durs, sfx_dbs = [], [], [], [], []
        for src, target, max_dur, db in placements:
            name = os.path.basename(src)
            meta = SFX_LIBRARY.get(name)
            if meta is None:
                # not pre-analyzed: assume hit at 0.05, no head crop
                meta = {"hit": 0.05}
            hit = meta.get("hit", 0.05)
            if hit <= target:
                delay_ms = max(int((target - hit) * 1000), 0)
                skip_s = 0.0
            else:
                skip_s = hit - target
                delay_ms = 0
            sfx_inputs.append(src)
            sfx_delays.append(delay_ms)
            sfx_trims.append(skip_s)
            sfx_durs.append(max_dur or 0.0)
            sfx_dbs.append(db)
            print(f"  [AUDIO] SFX {name}: hit@{target:.1f}s (file hit={hit}s) "
                  f"{db}dB -> "
                  f"{'crop ' + f'{skip_s:.2f}s' if skip_s else f'delay {delay_ms}ms'}"
                  f"{f' (max {max_dur}s)' if max_dur else ''}")

        # -- Mix everything --
        inputs = []
        filter_parts = []
        idx = 0
        if voice_path and os.path.isfile(voice_path):
            inputs.append(str(voice_path))
            filter_parts.append(f"[{idx}:a]aresample=44100[v{idx}]")
            idx += 1
        if music_path:
            inputs.append(music_path)
            filter_parts.append(f"[{idx}:a]aresample=44100[m{idx}]")
            idx += 1
        for i, (s, d, sk, md) in enumerate(zip(sfx_inputs, sfx_delays, sfx_trims, sfx_durs)):
            inputs.append(s)
            pre = f"atrim=start={sk:.3f},asetpts=PTS-STARTPTS," if sk > 0 else ""
            post = f",atrim=0:{md:.2f}" if md > 0 else ""
            filter_parts.append(
                f"[{idx}:a]aresample=44100,{pre}adelay={d}|{d},volume={SFX_DB}dB{post}[s{idx}]")
            idx += 1

        if not inputs:
            print("  [AUDIO] No audio inputs")
            return None, None, [], []

        n_sfx = len(sfx_inputs)

        # Windows cmdline limit (WinError 206): one ffmpeg invocation with
        # every SFX input + its filter exceeds 32767 chars on long episodes
        # (hundreds of title SFX). Mix SFX in batches of BATCH into short
        # intermediate WAVs (filter graph written to a script file, never
        # the cmdline), then run one tiny final mix.
        final_wav = str(_ep_audio_dir(episode_num) / "mix.wav")
        work = _ep_audio_dir(episode_num) / "mixwork"
        work.mkdir(parents=True, exist_ok=True)
        batch_files = []
        BATCH = 40
        for b in range(0, n_sfx, BATCH):
            chunk = list(range(b, min(b + BATCH, n_sfx)))
            fparts, bin_labels = [], []
            for k, j in enumerate(chunk):
                s, d, sk, md = (sfx_inputs[j], sfx_delays[j],
                                sfx_trims[j], sfx_durs[j])
                pre = f"atrim=start={sk:.3f},asetpts=PTS-STARTPTS," if sk > 0 else ""
                # Duration cap MUST trim the SOURCE before adelay: atrim
                # after adelay keeps the first md seconds of the delayed
                # stream, which is pure silence for any real delay (verified
                # -91dB). Trimming first keeps the hit at `target` and caps
                # the ring-out at max_dur.
                durcap = f"atrim=0:{md:.2f}," if md > 0 else ""
                # NOTE: k (local index within this batch's ffmpeg invocation)
                # is the correct input label - this command feeds ONLY the
                # chunk's files, so [N:a] must be local, not global.
                fparts.append(
                    f"[{k}:a]aresample=44100,"
                    f"aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo,"
                    f"{pre}{durcap}adelay={d}|{d},"
                    f"volume={sfx_dbs[j]}dB[b{k}]")
                bin_labels.append(f"[b{k}]")
            bfilter = (";".join(fparts) + ";" + "".join(bin_labels) +
                       f"amix=inputs={len(chunk)}:duration=longest:normalize=0[bmix]")
            fscript = work / f"sfx_batch_{b // BATCH:02d}.txt"
            fscript.write_text(bfilter, encoding="utf-8")
            bfile = work / f"sfx_batch_{b // BATCH:02d}.wav"
            bcmd = ["ffmpeg", "-y", "-v", "error"]
            for j in chunk:
                bcmd += ["-i", sfx_inputs[j]]
            bcmd += ["-filter_complex_script", str(fscript), "-map", "[bmix]",
                     "-c:a", "pcm_s16le", "-ar", "44100", str(bfile)]
            r = subprocess.run(bcmd, capture_output=True, text=True, timeout=300)
            if r.returncode != 0 or not bfile.is_file() or bfile.stat().st_size < 1000:
                print(f"  [AUDIO] SFX batch {b // BATCH:02d} failed: {r.stderr[-300:]}")
                return None, None, [], []
            batch_files.append(str(bfile))
            print(f"  [AUDIO] SFX batch {b // BATCH:02d}: {len(chunk)} sounds -> {bfile.name}")

        # Final mix: voice + music + SFX batch tracks (tiny, safe cmdline).
        # DUCKING (Joe 2026-08-14): when voice + music are both present, the
        # music is sidechain-compressed against the voice so it pulls DOWN while
        # the narrator speaks and swells back in the gaps (classic ducking).
        fin_inputs, fin_parts = [], []
        fin_voice, fin_music = None, None
        sfx_fin_labels = []  # label for each SFX batch, in input order
        if voice_path and os.path.isfile(voice_path):
            fin_inputs.append(str(voice_path))
            fin_voice = len(fin_inputs) - 1
            fin_parts.append(f"[{fin_voice}:a]aresample=44100,"
                             f"aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo"
                             f"[fv]")
        if music_path:
            fin_inputs.append(music_path)
            fin_music = len(fin_inputs) - 1
            fin_parts.append(f"[{fin_music}:a]aresample=44100,"
                             f"aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo"
                             f"[fm]")
        for bf in batch_files:
            fin_inputs.append(bf)
            _lab = f"fx{len(fin_inputs)-1}"
            fin_parts.append(f"[{len(fin_inputs)-1}:a]aresample=44100,"
                             f"aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo"
                             f"[{_lab}]")
            sfx_fin_labels.append(f"[{_lab}]")
        if fin_voice is not None and fin_music is not None:
            # Duck the music under the voice: sidechaincompress uses the second
            # input as the control (gain-reduction trigger) signal.
            duck = (f"[fm][fv]sidechaincompress=threshold={DUCK_THRESHOLD}:"
                    f"ratio={DUCK_RATIO}:attack={DUCK_ATTACK}:release={DUCK_RELEASE}:"
                    f"makeup=1[fd]")
            mix_labels = "[fv][fd]" + "".join(sfx_fin_labels)
            mix_inputs = 2 + len(sfx_fin_labels)
            ducking_on = True
        else:
            # No ducking (no voice or no music): mix whatever inputs exist.
            duck = ""
            labels = []
            if fin_voice is not None:
                labels.append("[fv]")
            if fin_music is not None:
                labels.append("[fm]")
            labels += sfx_fin_labels
            mix_labels = "".join(labels)
            mix_inputs = len(labels)
            ducking_on = False
        fscript = work / "final_mix.txt"
        fscript.write_text(
            ";".join(fin_parts) + ((";" + duck) if duck else "") + ";" +
            mix_labels +
            f"amix=inputs={mix_inputs}:duration=first:normalize=0,"
            f"alimiter=limit=0.95,atrim=0:{total_dur:.2f}[out]",
            encoding="utf-8")
        if ducking_on:
            print(f"  [AUDIO] Ducking ON: music sidechain-compressed under voice "
                  f"(threshold {DUCK_THRESHOLD}, ratio {DUCK_RATIO}, "
                  f"attack {DUCK_ATTACK}ms, release {DUCK_RELEASE}ms)")
        cmd = ["ffmpeg", "-y", "-v", "error"]
        for inp in fin_inputs:
            cmd += ["-i", inp]
        cmd += ["-filter_complex_script", str(fscript), "-map", "[out]",
                "-c:a", "pcm_s16le", "-ar", "44100", final_wav]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if r.returncode != 0 or not os.path.isfile(final_wav) or os.path.getsize(final_wav) < 1000:
            print(f"  [AUDIO] Mix failed: {r.stderr[-300:]}")
            return None, None, [], []
        dur = _get_audio_duration(final_wav)
        print(f"  [OK] Mixed audio: {_fmt_time(dur)}, {os.path.getsize(final_wav)//1024}KB -> {final_wav}")
        return final_wav, voice_out, clip_starts, words
    finally:
        shutil.rmtree(str(temp_dir), ignore_errors=True)
        try:
            shutil.rmtree(str(work), ignore_errors=True)
        except Exception:
            pass

# -- Whisper title pass (faster-whisper word timings) -----------------

def _transcribe_voice(episode_num: int, voice_path: Optional[str] = None) -> list[dict]:
    """Word-level timings of the voice track via faster-whisper (base, CPU).

    Cached to episodes/ep{N:03d}/audio/whisper.json (reused on resume; deleted
    when the episode completes). vad_filter=False is critical - TTS voices have
    no natural speech pauses and VAD returns EMPTY segments.
    """
    cache = str(_ep_audio_dir(episode_num) / "whisper.json")
    if os.path.isfile(cache) and os.path.getsize(cache) > 100:
        try:
            words = json.loads(Path(cache).read_text())
            print(f"  [STT] whisper cache reused ({len(words)} words)")
            return words
        except Exception:
            pass
    if not voice_path or not os.path.isfile(voice_path):
        voice_path = str(_ep_audio_dir(episode_num) / "voice.wav")
    if not os.path.isfile(voice_path):
        print("  [STT] no voice track for whisper")
        return []
    print(f"  [STT] faster-whisper word timings on voice track...")
    try:
        from faster_whisper import WhisperModel
        model = WhisperModel("base", device="cpu", compute_type="int8")
        segments, _info = model.transcribe(voice_path, language="en",
                                           word_timestamps=True, vad_filter=False)
        words = []
        for seg in segments:
            if seg.words:
                for w in seg.words:
                    words.append({"word": w.word.strip(), "start": w.start, "end": w.end})
        Path(cache).write_text(json.dumps(words))
        print(f"  [STT] {len(words)} words timed")
        return words
    except Exception as e:
        print(f"  [STT] whisper failed: {e}")
        return []


def _build_resolved_title_events(chapter_events: list[dict],
                                 anchor_events: list[dict],
                                 words: list[dict],
                                 clip_starts: list[float]) -> list[dict]:
    """Combine chapter + anchor events into one resolved list for the burn pass.

    chapter events: start = whisper time of 'chapter N', end = black clip end.
    anchor events : start = whisper time of the date/location phrase.
    """
    resolved = []
    # Full number-word map (digits + spoken words + ordinals) for 1..12 so a
    # chapter's number is found even when whisper hears "five"/"5"/"fifth".
    num_words = {
        1: ["one", "1", "1st", "first"], 2: ["two", "2", "2nd", "second"],
        3: ["three", "3", "3rd", "third"], 4: ["four", "4", "4th", "fourth"],
        5: ["five", "5", "5th", "fifth"], 6: ["six", "6", "6th", "sixth"],
        7: ["seven", "7", "7th", "seventh"], 8: ["eight", "8", "8th", "eighth"],
        9: ["nine", "9", "9th", "ninth"], 10: ["ten", "10", "10th", "tenth"],
        11: ["eleven", "11", "11th", "eleventh"], 12: ["twelve", "12", "12th", "twelfth"],
    }
    # chapter -> find when "chapter N" is spoken
    for ev in chapter_events:
        pi = ev["para_idx"]
        fallback = (clip_starts[pi] + 0.4) if pi < len(clip_starts) else 0.0
        # Chapter card END = when the TTS finishes reading the chapter title
        # (whisper time of the last spoken word of "Chapter N - Title"), NOT the
        # next clip start. The card must only stay up as long as the narrator
        # reads it (Joe 2026-08-07: cards were staying on too long).
        end = (clip_starts[pi + 1] if pi + 1 < len(clip_starts) else
               (clip_starts[pi] + 5.0)) if pi < len(clip_starts) else fallback + 4.0
        t = None
        if words:
            # SEARCH WINDOW (Joe 2026-08-10): only look for this chapter's
            # "Chapter N" inside its OWN narration clip window
            # [clip_starts[pi], clip_starts[pi+1]], never the whole transcript.
            # Searching globally made whisper's number mis-hears cross-match to
            # the WRONG chapter (ep12: Ch5@655s landed before Ch3@686s, and the
            # 7-9 map gap dumped Ch9 at 0.00s).
            lo = clip_starts[pi] if pi < len(clip_starts) else 0.0
            hi = (clip_starts[pi + 1] if pi + 1 < len(clip_starts) else
                  (clip_starts[pi] + 8.0 if pi < len(clip_starts) else 8.0))
            my_nums = set(num_words.get(ev["chapter"], []))
            for i, w in enumerate(words):
                if w["start"] < lo - 0.2 or w["start"] > hi + 0.2:
                    continue
                wl = w["word"].strip(".,!?;:()\"'").lower()
                if wl != "chapter":
                    continue
                # "chapter" followed (within 3 words) by this chapter's number
                for j in range(i + 1, min(i + 4, len(words))):
                    nxt = words[j]["word"].strip(".,!?;:()\"'-").lower()
                    if nxt in my_nums:
                        t = w["start"]
                        break
                if t is not None:
                    break
            # Find the end of the spoken title: the last word spoken within the
            # chapter card's clip (between this card's start and the next clip's
            # start) whose timestamp is after the "chapter N" start.
            if t is not None:
                clip_end = end
                title_words = [w for w in words
                               if w["start"] >= t and w["start"] < clip_end]
                if title_words:
                    # include the title's full spoken duration + a short hold
                    end = min(title_words[-1]["end"] + 0.6, clip_end)
        resolved.append({
            "kind": "chapter", "start": round(t or fallback, 3), "end": round(end, 3),
            "chapter_num": ev["chapter"], "title": ev["title"],
            "text": f"Chapter {ev['chapter']} - {ev['title']}",
        })
    resolved.extend(_resolve_anchor_times(anchor_events, words, clip_starts))
    return resolved

# -- Render (FFmpeg 1080p) -------------------------------------------

def _render_clip(image_path: str, audio_path: str, output_path: str,
                 fallback_img: Optional[str] = None,
                 black_frames: bool = False,
                 vcr_effect: bool = False) -> bool:
    """Render one shot: slow-zoom image + narration audio -> 1080p clip.

    black_frames=True prepends 2 frames of pure black before the image
    (camera-shutter mimic when a new character/location is introduced).
    vcr_effect=True (establishing shots, Joe 2026-08-09) overlays scanlines +
    a VCR static/noise look so the establishing frame reads as an aged
    broadcast frame - pairs with the white-noise-flicker SFX added in the mix.
    """
    W_RES, H_RES = _get_output_resolution()
    OV_W, OV_H = W_RES * 4, H_RES * 4   # 4x overscan -> sub-pixel zoom steps
    if not image_path or not os.path.isfile(image_path):
        image_path = fallback_img or ""
    if not image_path or not os.path.isfile(image_path):
        from PIL import Image
        img = Image.new("RGB", (W_RES, H_RES), (18, 18, 22))
        image_path = str(FALLBACK_BG)
        img.save(image_path)
    dur = max(_get_audio_duration(audio_path), 0.5) + 0.6
    n_frames = max(int(dur * 24), 24)
    # Smooth zoom: upscale the source 4x with lanczos BEFORE zoompan so the
    # per-frame zoom steps are sub-pixel (measured: 4x prescale halves the
    # frame-to-frame motion variance vs 2x - cv 0.73 -> 0.41 on noise imagery),
    # and zoom from the exact center so the crop never drifts.
    zoom_expr = f"z='if(eq(on,1),1,min(1+0.06*(on-1)/{max(n_frames-1,1)},1.06))'"
    # Main image pipeline (single-pass render no longer calls this per-clip
    # path, but keep it as a minimal reference).
    main = (
        f"[0:v]loop=1:size=1:start=0,"
        f"scale={OV_W}:{OV_H}:flags=lanczos:force_original_aspect_ratio=increase,"
        f"crop={OV_W}:{OV_H},"
        f"zoompan={zoom_expr}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
        f"d={n_frames}:s={W_RES}x{H_RES}:fps=24,"
        f"fade=t=in:st=0:d=0.3,fade=t=out:st={max(dur-0.3,0):.2f}:d=0.3"
    )
    if black_frames:
        # 2 frames of black at the very start = camera shutter between images
        main += ",tpad=start=2:color=black"
    filter_graph = main + "[vout]"
    cmd = [
        "ffmpeg", "-y",
        "-loop", "1", "-i", image_path,
        "-i", audio_path,
        "-filter_complex", filter_graph,
        "-map", "[vout]", "-map", "1:a",
        "-c:v", "hevc_nvenc", "-preset", "p7", "-rc", "vbr", "-cq", "28", "-b:v", "0",
        "-c:a", "aac", "-b:a", "96k",
        "-pix_fmt", "yuv420p",
        "-shortest",
        output_path
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if r.returncode != 0 or not os.path.isfile(output_path) or os.path.getsize(output_path) < 1000:
        fb_cmd = [
            "ffmpeg", "-y",
            "-loop", "1", "-t", f"{dur:.2f}", "-i", image_path,
            "-i", audio_path,
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-c:a", "aac", "-b:a", "96k",
            "-pix_fmt", "yuv420p",
            "-shortest", output_path
        ]
        r2 = subprocess.run(fb_cmd, capture_output=True, text=True, timeout=300)
        return r2.returncode == 0 and os.path.isfile(output_path) and os.path.getsize(output_path) > 1000
    return True

def _master_gain_filter(audio_path: str) -> str:
    """Measure the mixed WAV's peak and return an ffmpeg -af filter string that
    raises the loudest peak to 0dB (0.0dB gain if already at/near 0dB).
    Relative levels inside the mix are preserved: voice 0dB, music -19.5dB, SFX -15dB."""
    try:
        probe = subprocess.run(
            ["ffmpeg", "-i", audio_path, "-af", "volumedetect", "-f", "null", "-"],
            capture_output=True, text=True, timeout=60)
        m = re.search(r"max_volume:\s*(-?[\d.]+)\s*dB", probe.stderr)
        if not m:
            print("  [AUDIO] volumedetect failed, no master gain applied")
            return ""
        peak_db = float(m.group(1))
        gain_db = -peak_db
        # Safety: never boost more than +6dB, never reduce
        gain_db = max(0.0, min(gain_db, 6.0))
        if gain_db < 0.05:
            print(f"  [AUDIO] Master peak already {peak_db:.1f}dB, no gain")
            return ""
        print(f"  [AUDIO] Master gain +{gain_db:.1f}dB (peak {peak_db:.1f}dB -> 0dB)")
        return f"volume={gain_db:.2f}dB,alimiter=limit=1.0"
    except Exception as e:
        print(f"  [AUDIO] Master gain probe error: {e}")
        return ""

def _compute_clip_starts(shots: list[dict]) -> list[float]:
    """Absolute start times of each clip in the voice/video timeline.

    Must stay in sync with _build_audio_mix's cursor math. Pacing gaps are
    applied via _pace_gaps_after BEFORE the math so the starts always use the
    REAL per-shot gaps (1.0s breathing / 1.6s chapter / 1.2s question), never
    the stale 0.3 default - otherwise title/label burn times drift earlier by
    ~0.7s per shot (Joe 2026-08-12, review finding). Idempotent: _pace_gaps_after
    re-sets the same deterministic values if already applied."""
    _pace_gaps_after(shots)
    starts, cursor = [], 0.0
    for s in shots:
        if not (s.get("tts_path") and os.path.isfile(s["tts_path"])):
            continue
        starts.append(cursor)
        cursor += _get_audio_duration(s["tts_path"]) + s.get("gap_after", 1.0)
    return starts


def _is_black_image(path: str) -> bool:
    """True if the image is essentially a solid black placeholder (a failed /
    default chapter card) vs real generated artwork. Samples a downscaled copy."""
    if not path or not os.path.isfile(path):
        return True
    try:
        from PIL import Image
        im = Image.open(path).convert("L")
        im.thumbnail((64, 64))
        px = list(im.getdata())
        if not px:
            return True
        mean = sum(px) / len(px)
        if mean < 8:
            return True
        return max(px) < 24
    except Exception:
        return True


def _deterministic_chapter_events(shots: list[dict], clip_starts: list[float],
                                  chapter_events: Optional[list] = None) -> list[dict]:
    """Chapter-card times derived DIRECTLY from the shot timeline, not whisper.

    Since every sentence is its own shot with a KNOWN TTS clip, the chapter
    card's on-screen window is EXACTLY the chapter sentence's clip window:
    start = clip_starts[pos], end = clip_starts[pos] + tts_dur. This is the
    root fix for the ep12 "incorrect chapter titles at the wrong time" bug -
    whisper mis-hearing a chapter number can no longer move a card. Falls back
    to whisper-resolved times (passed in) only when clip_starts is unavailable.
    """
    valid_pos = {}
    _vp = 0
    for _i, s in enumerate(shots):
        if s.get("tts_path") and os.path.isfile(s["tts_path"]):
            valid_pos[_i] = _vp
            _vp += 1
    out = []
    for ev in chapter_events or []:
        # Only actual chapter events belong here - location/person anchors must
        # NOT be treated as chapters (they'd get a None chapter_num and crash
        # the ASS burn + risk a doubled lower-third title). (Joe 2026-08-10)
        if ev.get("kind") != "chapter":
            continue
        pi = ev.get("para_idx")
        # para_idx is the narration index; map to its shot position
        shot_pos = None
        for _j, s in enumerate(shots):
            if int(s.get("narration_idx", -1)) == pi or (
                    s.get("is_chapter") and int(s.get("chapter_num", 0)) == int(ev.get("chapter_num", 0))):
                if s.get("tts_path") and os.path.isfile(s["tts_path"]):
                    shot_pos = _j
                break
        if shot_pos is None or shot_pos not in valid_pos:
            continue
        vp = valid_pos[shot_pos]
        if vp >= len(clip_starts):
            continue
        start = clip_starts[vp]
        dur = _get_audio_duration(shots[shot_pos]["tts_path"])
        ch_num = ev.get("chapter_num") or ev.get("chapter")
        # has_artwork: the card has real generated artwork (show it, burn the
        # title ON TOP) vs a black placeholder (draw the ASS black backdrop).
        out.append({
            "kind": "chapter",
            "start": round(start, 3),
            "end": round(start + dur, 3),
            "chapter_num": ch_num,
            "title": ev.get("title", ""),
            "text": f"Chapter {ch_num} - {ev.get('title', '')}",
            "has_artwork": not _is_black_image(shots[shot_pos].get("image_path", "")),
        })
    return out


def _ensure_voice_track(shots: list[dict], episode_num: int) -> Optional[str]:
    """Build rendered_audio/ep{N:03d}_voice.wav if missing (same concat as the
    mix: clips + per-shot pacing gaps). Used by the whisper title pass on resume."""
    out = str(_ep_audio_dir(episode_num) / "voice.wav")
    if os.path.isfile(out) and os.path.getsize(out) > 1000:
        return out
    valid = [s for s in shots if s.get("tts_path") and os.path.isfile(s["tts_path"])]
    if not valid:
        return None
    _pace_gaps_after(valid)
    temp_dir = Path(tempfile.mkdtemp(prefix=f"sb_voice_{episode_num}_"))
    try:
        concat_list = temp_dir / "vc.txt"
        with open(concat_list, "w") as f:
            for i, shot in enumerate(valid):
                f.write(f"file '{str(Path(shot['tts_path']).resolve())}'\n")
                pad = temp_dir / f"pad_{i}.wav"
                subprocess.run(
                    ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                     "anullsrc=r=24000:cl=mono", "-t",
                     f"{shot.get('gap_after', 0.3):.2f}",
                     "-c:a", "pcm_s16le", str(pad)],
                    capture_output=True, text=True, timeout=30)
                f.write(f"file '{str(pad.resolve())}'\n")
        r = subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
             "-i", str(concat_list), "-c:a", "pcm_s16le", out],
            capture_output=True, text=True, timeout=180)
        if r.returncode == 0 and os.path.isfile(out) and os.path.getsize(out) > 1000:
            return out
        # Padded concat failed (transient Windows file-lock / ffmpeg hiccup on a
        # long clip list - ep13's title pass died with empty stderr). Fall back
        # to a simple unpadded concat of the raw clips so the whisper title pass
        # still gets a voice track to time against; pacing is irrelevant for
        # timing since we only need relative whisper positions.
        print(f"  [STT] padded voice track build failed ({r.stderr[-150:]}) - "
              f"falling back to unpadded concat")
        try:
            plain = temp_dir / "vc_plain.txt"
            with open(plain, "w") as f:
                for shot in valid:
                    f.write(f"file '{str(Path(shot['tts_path']).resolve())}'\n")
            r2 = subprocess.run(
                ["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
                 "-i", str(plain), "-c:a", "pcm_s16le", out],
                capture_output=True, text=True, timeout=180)
            if r2.returncode == 0 and os.path.isfile(out) and os.path.getsize(out) > 1000:
                print("  [STT] unpadded voice track built OK")
                return out
            print(f"  [STT] unpadded voice track also failed: {r2.stderr[-150:]}")
        except Exception as _ve2:
            print(f"  [STT] unpadded fallback error: {_ve2}")
        return None
    finally:
        shutil.rmtree(str(temp_dir), ignore_errors=True)


def _cleanup_stt_artifacts(episode_num: int) -> None:
    """Delete whisper/STT caches + title markers when the episode completes."""
    try:
        for p in _ep_audio_dir(episode_num).glob("whisper.json"):
            p.unlink()
            print(f"  [CLEAN] removed {p.name}")
        for p in _ep_video_dir(episode_num).glob("*.titled"):
            p.unlink()
        for p in _ep_video_dir(episode_num).glob("titles.ass"):
            p.unlink()
    except Exception as e:
        print(f"  [CLEAN] stt cleanup error: {e}")


def _camera_shutter_paras(shots: list[dict], title_events: Optional[list] = None) -> set:
    """narration_idx of shots that introduce a NEW character or NEW location
    (camera shutter SFX + 2 black frames). Mirrors the mix's shutter logic."""
    loc_paras = {ev["para_idx"] for ev in (title_events or [])
                 if ev.get("kind") == "location"}
    out = set()
    prev_char = None
    for pos, shot in enumerate(shots):
        if shot.get("is_chapter"):
            continue
        # Establishing shots (new place/person introduced) always get the
        # shutter + instant cut to the establishing frame.
        if shot.get("is_establishing"):
            out.add(shot.get("narration_idx", pos))
            continue
        ch = shot.get("character", "NONE")
        nidx = shot.get("narration_idx", pos)
        new_char = False
        if ch != "NONE":
            if prev_char is not None and ch != prev_char:
                new_char = True
            prev_char = ch
        if new_char or nidx in loc_paras:
            out.add(nidx)
    return out


def _safe_replace(src: str, dst: str, tries: int = 6) -> bool:
    """Windows-safe os.replace. WinError 5 (Access denied) fires when the
    destination is briefly locked - Defender real-time scan or Explorer
    preview/indexing right after a large file is written - or has the
    read-only attribute. Clear read-only, retry with backoff, then fall
    back to copy+delete. Returns True on success."""
    import stat as _stat
    last_err = None
    for attempt in range(tries):
        try:
            os.chmod(dst, _stat.S_IWRITE)
        except OSError:
            pass
        try:
            os.replace(src, dst)
            return True
        except (PermissionError, OSError) as e:
            last_err = e
            if attempt < tries - 1:
                time.sleep(1.0 + attempt)  # 1s, 2s, 3s, 4s, 5s backoff
    try:
        os.chmod(dst, _stat.S_IWRITE)
        shutil.copy2(src, dst)
        try:
            os.remove(src)
        except OSError:
            pass
        return True
    except OSError as e:
        print(f"  [WARN] replace failed {src} -> {dst}: {e} "
              f"(last: {last_err}) - is the file open in a player?")
        return False


def _run_render_progress(cmd: list, cwd: str, total: float,
                         desc: str) -> tuple[int, str]:
    """Run ffmpeg with a live progress bar (mirrors burn_titles).

    Reads `-progress pipe:1 -nostats` stdout so the single-pass render shows
    % + ETA instead of dead air. The previous silent capture_output run looked
    like a stall after the title-serialization line and got killed, leaving a
    partial no-moov mp4 (Joe 2026-08-16). Stderr is drained in a background
    thread so the pipe can never fill and deadlock ffmpeg. Returns
    (returncode, stderr_text)."""
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, cwd=cwd)
    err_buf = []

    def _drain():
        try:
            for line in proc.stderr:
                err_buf.append(line)
        except Exception:
            pass

    th = threading.Thread(target=_drain, daemon=True)
    th.start()
    pbar = None
    if _HAS_PROGRESS and total > 0:
        pbar = tqdm(total=total, unit="s", desc=desc,
                    bar_format="{desc}: {percentage:3.0f}%|{bar}| "
                               "{n:.0f}/{total_fmt}s [{elapsed}<{remaining}]")
    last_sec = 0.0
    noted_finalize = False
    try:
        for line in proc.stdout:
            if pbar is None or not line:
                continue
            if line.startswith("out_time_us="):
                try:
                    sec = int(line.split("=", 1)[1].strip()) / 1e6
                except ValueError:
                    continue
            elif line.startswith("out_time_ms="):
                try:
                    sec = int(line.split("=", 1)[1].strip()) / 1e3
                except ValueError:
                    continue
            else:
                continue
            if pbar is not None:
                pbar.update(max(0.0, min(sec - last_sec, total - pbar.n)))
                # out_time hit the target but ffmpeg is still running (the
                # -movflags +faststart moov rewrite has no out_time), so the bar
                # would sit frozen at 100% and look stuck. Label it finalizing.
                if pbar.n >= total and not noted_finalize:
                    noted_finalize = True
                    pbar.set_postfix_str("finalizing (moov/faststart)...",
                                         refresh=True)
            last_sec = sec
    except Exception:
        pass
    proc.wait()
    th.join(timeout=5)
    if pbar:
        if not noted_finalize and pbar.n < total:
            pbar.update(total - pbar.n)
        pbar.close()
        print()
    return proc.returncode, "".join(err_buf)


def _render_video(shots: list[dict], episode_num: int,
                  title_events: Optional[list] = None) -> str:
    """Render all shots into one video with a SINGLE ffmpeg pass (Joe 2026-08-10).

    Each sentence is its own shot with its own image + TTS clip. The image is
    shown for EXACTLY that sentence's TTS duration (held through its pacing
    gap), so the picture always matches the narration being spoken. All images
    are zoompan'd, concatenated, and the ASS titles (chapter cards + typewriter
    loc/person labels) are burned INLINE in the same ffmpeg command - there is
    NO separate clip render, NO concat pass, NO pass-2 title burn.

    Chapter-card timing is DETERMINISTIC (derived from the sentence timeline,
    not whisper), which fixes the ep12 "incorrect chapter titles at the wrong
    time" bug. Scanlines/VCR effect is REMOVED (it was mangling timing).

    title_events = optional whisper-resolved events (used for location/person
    typewriter SFX placement + the burn). Chapter cards are recomputed here
    deterministically.
    """
    print("\n[VIDEO] Rendering documentary (SINGLE PASS)...")
    # Self-heal missing narration clips BEFORE filtering, so a spoken beat is
    # never silently dropped from the final video (Joe 2026-08-12, review #4).
    try:
        _ensure_all_tts_before_render(shots, episode_num)
    except Exception as _tfix_err:
        print(f"  [TTS-FIX] self-heal skipped: {_tfix_err}")
    valid = [s for s in shots if s.get("tts_path") and os.path.isfile(s["tts_path"])]
    if not valid:
        print("  [FAIL] No TTS clips to render")
        return ""

    # Build the full audio mix first (voice+music+sfx). Captures exact per-shot
    # start times (clip_starts) so each image can be shown for its exact
    # duration. Deterministic path -> reused on resume.
    mixed_audio = str(_ep_audio_dir(episode_num) / "mix.wav")
    clip_starts = []
    words = []
    if os.path.isfile(mixed_audio) and os.path.getsize(mixed_audio) > 1000:
        print(f"  [AUDIO] Mix exists, reusing ({os.path.getsize(mixed_audio)//1024}KB)")
        clip_starts = _compute_clip_starts(valid)
    else:
        _mix = _build_audio_mix(valid, episode_num, title_events)
        if _mix:
            _, _, clip_starts, words = _mix
    if not os.path.isfile(mixed_audio) or os.path.getsize(mixed_audio) < 1000:
        print("  [WARN] Audio mix failed, falling back to voice-only concat")
        mixed_audio = ""
    if not clip_starts:
        clip_starts = _compute_clip_starts(valid)
    if not words:
        words = _transcribe_voice(episode_num)

    # ---- DETERMINISTIC chapter-card times (from the sentence timeline) ----
    # The chapter sentence is its own clip, so its on-screen window = that
    # clip's exact start..end. No whisper -> a mis-heard number can never move
    # a card (the ep12 root-cause fix).
    chap_events = _deterministic_chapter_events(valid, clip_starts, title_events)
    # Keep location/person typewriter events (whisper-resolved) but drop the
    # old chapter events from the passed list so we use OUR deterministic ones.
    if title_events:
        others = [ev for ev in title_events if ev.get("kind") != "chapter"]
        title_events = chap_events + others

    # Key-word on-screen highlights (Joe 2026-08-12): burn the 2-3 key words of
    # each key sentence at its whisper-resolved spoken time.
    kw_events = _build_keyword_events(valid, words, clip_starts)
    if kw_events:
        title_events = (title_events or []) + kw_events
        print(f"  [KEYWORD] {len(kw_events)} key-word highlight(s) queued for burn")

    # Per-image on-screen duration: exactly this sentence's TTS + its pacing gap
    # (= clip_starts[i+1]-clip_starts[i]). Matches the mix timeline 1:1.
    durs = []
    for i, s in enumerate(valid):
        if i < len(valid) - 1:
            durs.append(max(clip_starts[i + 1] - clip_starts[i], 0.4))
        else:
            durs.append(max(_get_audio_duration(s["tts_path"]) + s.get("gap_after", 0.3), 0.4))
    total_vid = sum(durs)
    print(f"  [VIDEO] {len(valid)} sentence-images, {_fmt_time(total_vid)} total")

    W_RES, H_RES = _get_output_resolution()
    OV_W, OV_H = W_RES * 4, H_RES * 4
    fallback_img = str(FALLBACK_BG)
    output_path = str(_ep_video_dir(episode_num) / f"ep{episode_num:03d}.mp4")

    temp_dir = Path(tempfile.mkdtemp(prefix=f"sb_render_{episode_num}_"))
    try:
        # ---- Resolve per-shot image paths ----
        imgs = []
        for i, s in enumerate(valid):
            p = s.get("image_path") or ""
            if not os.path.isfile(p):
                p = fallback_img
            if not os.path.isfile(p):
                from PIL import Image as _PIL
                Image = _PIL
                img = Image.new("RGB", (W_RES, H_RES), (18, 18, 22))
                p = str(FALLBACK_BG)
                img.save(p)
            imgs.append(p)

        # ---- Merge clips that share one on-screen image (Joe 2026-08-12) ----
        # A genuinely-missing shot image must NEVER render as a fresh black clip
        # (or restart the zoom on a reused image). Instead:
        #   (1) a missing shot image is folded into the PREVIOUS clip, extending
        #       it to cover this sentence's duration too - the prior zoompan
        #       simply keeps going, no restart, no black frame; and
        #   (2) consecutive clips whose resolved image path is identical are
        #       merged into ONE continuous zoompan so a carried-forward/reused
        #       image doesn't re-start its zoom per sentence.
        # The AUDIO timeline is untouched (the mix still has every sentence's
        # narration at its real absolute time), so the merge only affects the
        # picture stream - and because merged durations are a sum of the same
        # contiguous durations, absolute time alignment is preserved.
        m_imgs: list[str] = []
        m_durs: list[float] = []
        for _i, (_p, _dur) in enumerate(zip(imgs, durs)):
            _shot = valid[_i]
            _missing = (not os.path.isfile(_shot.get("image_path") or "")) \
                and not _shot.get("is_chapter")
            if _missing and m_imgs:
                # fold this sentence into the previous clip (continue its zoom)
                m_durs[-1] += _dur
                continue
            if m_imgs and os.path.abspath(m_imgs[-1]) == os.path.abspath(_p):
                # same image consecutive -> one continuous zoom, don't restart
                m_durs[-1] += _dur
                continue
            m_imgs.append(_p)
            m_durs.append(_dur)
        if len(m_imgs) != len(imgs):
            print(f"  [VIDEO] merged {len(imgs)} shots into {len(m_imgs)} visual "
                  f"clips ({len(imgs)-len(m_imgs)} missing-image/same-image "
                  f"folds, zoom not restarted)")

        # ---- Build the ASS title file (chapter + typewriter) ----
        ass_path = str(_ep_video_dir(episode_num) / "titles.ass")
        _burn_ok = False
        if split_node_titles is not None and title_events:
            try:
                split_node_titles.build_title_ass(title_events, ass_path,
                                                  W_RES, H_RES, 24)
                _burn_ok = True
            except Exception as e:
                print(f"  [TITLES] ASS build failed: {e}")

        # ---- ONE ffmpeg pass: zoompan each image -> concat -> burn ASS -> mux ----
        # Filter graph written to a script file (avoids Windows cmdline length
        # limits with hundreds of inputs) and passed via -filter_complex_script.
        parts = []
        for i, (p, dur) in enumerate(zip(m_imgs, m_durs)):
            n_frames = max(int(dur * 24), 24)
            zoom_expr = f"z='if(eq(on,1),1,min(1+0.06*(on-1)/{max(n_frames-1,1)},1.06))'"
            parts.append(
                f"[{i}:v]"
                f"scale={OV_W}:{OV_H}:flags=lanczos:force_original_aspect_ratio=increase,"
                f"crop={OV_W}:{OV_H},"
                f"zoompan={zoom_expr}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
                f"d={n_frames}:s={W_RES}x{H_RES}:fps=24,"
                f"fade=t=in:st=0:d=0.2,fade=t=out:st={max(dur-0.2,0):.2f}:d=0.2,"
                f"setsar=1,format=yuv420p[v{i}]")
        concat_in = "".join(f"[v{i}]" for i in range(len(imgs)))
        parts.append(f"{concat_in}concat=n={len(imgs)}:v=1:a=0[vc]")
        if _burn_ok:
            # Burn the ASS titles inline (relative path from the episode video dir
            # to dodge the drive-letter-colon filter parsing issue).
            _sub = f"subtitles={Path(ass_path).name}"
            _fd = Path(__file__).resolve().parent / "fonts"
            if _fd.is_dir() and any(_fd.iterdir()):
                _rel = os.path.relpath(str(_fd), start=str(_ep_video_dir(episode_num))).replace("\\", "/")
                _sub += f":fontsdir={_rel}"
            parts.append(f"[vc]{_sub}[vout]")
        else:
            parts.append("[vc]null[vout]")
        graph = ";\n".join(parts)
        graph_file = temp_dir / "graph.txt"
        graph_file.write_text(graph, encoding="utf-8")

        cmd = ["ffmpeg", "-y"]
        for p in imgs:
            # Single-frame image input (NO -loop 1 / -framerate 24). zoompan's
            # d=N + fps=24 generates EXACTLY N frames then EOF, so the concat
            # advances past image 1. With -loop 1 the stream is infinite and
            # concat never leaves the first image (all later shots go black).
            cmd += ["-i", p]
        cmd += ["-i", mixed_audio] if (mixed_audio and os.path.isfile(mixed_audio)) else []
        audio_idx = len(imgs)
        cmd += ["-filter_complex_script", str(graph_file)]
        cmd += ["-map", "[vout]"]
        if (mixed_audio and os.path.isfile(mixed_audio)):
            cmd += ["-map", f"{audio_idx}:a"]
        # NVENC single-pass encode; audio copied from the mix (already levelled).
        cmd += ["-c:v", "hevc_nvenc", "-preset", "p7", "-rc", "vbr", "-cq", "28",
                "-b:v", "0", "-pix_fmt", "yuv420p"]
        if (mixed_audio and os.path.isfile(mixed_audio)):
            cmd += ["-c:a", "aac", "-b:a", "192k"]
        cmd += ["-movflags", "+faststart", "-t", f"{total_vid:.3f}",
                "-progress", "pipe:1", "-nostats", "-y", output_path]

        # Run with cwd=the episode video dir so the subtitles filter's relative .ass
        # name (and fontsdir) resolve correctly (absolute -i paths still work).
        # Streamed with a live progress bar (Joe 2026-08-16).
        r_code, r_err = _run_render_progress(cmd, str(_ep_video_dir(episode_num)),
                                             total_vid, "  [RENDER]")
        if r_code != 0 or not os.path.isfile(output_path) or os.path.getsize(output_path) < 1000:
            print(f"  [RENDER] single-pass failed: {r_err[-1500:]}")
            return ""

        dur = _get_audio_duration(output_path)
        size_mb = os.path.getsize(output_path) / 1024 / 1024
        print(f"  [OK] Video: {_fmt_time(dur)}, {size_mb:.1f}MB -> {output_path}")
        return output_path
    finally:
        shutil.rmtree(str(temp_dir), ignore_errors=True)

# -- Thumbnail (FAL GPT Image 2) -------------------------------------

def _thumbnail_headline(topic: str) -> str:
    """Short all-caps clickbait headline for the thumbnail (2-4 words)."""
    msg = [
        {"role": "system", "content": (
            "Write a short clickbait YouTube thumbnail headline for a documentary "
            "about a true story where ordinary people beat the system. Rules: exactly "
            "2-4 words, ALL CAPS, curiosity gap, dramatic, no punctuation except maybe "
            "one exclamation mark. Return ONLY the headline."
        )},
        {"role": "user", "content": f"Topic: {topic}\n\nWrite the headline."}
    ]
    text = _llm_chat(msg, max_tokens=30, temp=0.9).strip().strip('"\'')
    if text and 1 < len(text.split()) <= 5:
        return text.upper()
    # Fallback: keyword extraction from the topic
    stop = {"comcast", "security", "flaw", "exposed", "customers", "personal",
            "information", "that", "with", "from", "your", "this", "what", "the",
            "and", "for", "are", "was", "how", "why", "who"}
    words = [w for w in re.findall(r"[A-Za-z0-9']+", topic)
             if w.lower() not in stop and len(w) > 3]
    if not words:
        return "THEY BEAT THE SYSTEM"
    return " ".join(words[:3]).upper()

_THUMBNAIL_FONT = r"C:/Windows/Fonts/impact.ttf"      # classic bold YouTube thumbnail font
_THUMBNAIL_FONT_FALLBACK = "fonts/MyriadPro-Bold.otf"  # project font if Impact missing

def _thumb_font() -> str:
    if os.path.isfile(_THUMBNAIL_FONT):
        return _THUMBNAIL_FONT
    cand = os.path.join(str(PROJECT_DIR), _THUMBNAIL_FONT_FALLBACK) if PROJECT_DIR else _THUMBNAIL_FONT_FALLBACK
    return cand if os.path.isfile(cand) else _THUMBNAIL_FONT

def _burn_thumbnail_text(scene_path: str, headline: str, out_path: str) -> bool:
    """Overlay crisp 'SPLIT NODE' (top-left) + a short curiosity headline (lower
    third) onto the thumbnail via FFmpeg drawtext (Impact, white fill, black
    stroke, drop shadow). Rendering text IN the image via the image model garbles
    it; burning vector text guarantees legible, correctly positioned packaging.
    Aligns with Adam Del Duca's thumbnail rule: ~<=4 words, a curiosity gap the
    title doesn't answer. The font is staged next to the output as a bare
    filename so ffmpeg's filter parser never sees a drive-letter colon. Falls
    back gracefully if FFmpeg/font fails."""
    try:
        pr = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height", "-of", "csv=p=0:s=x",
             scene_path], capture_output=True, text=True)
        if pr.returncode == 0 and "x" in pr.stdout:
            try:
                w, h = (int(x) for x in pr.stdout.strip().split("x")[:2])
            except Exception:
                w, h = 1280, 720
        else:
            w, h = 1280, 720
        workdir = os.path.dirname(os.path.abspath(out_path)) or "."
        # Stage the font + text files beside the output (bare names, no colons)
        font_src = _thumb_font()
        font_name = os.path.basename(font_src)
        local_font = os.path.join(workdir, font_name)
        if os.path.abspath(font_src) != os.path.abspath(local_font):
            shutil.copyfile(font_src, local_font)
        wm_tf = os.path.join(workdir, "_thumb_wordmark.txt")
        hd_tf = os.path.join(workdir, "_thumb_headline.txt")
        with open(wm_tf, "w", encoding="utf-8") as fh:
            fh.write("SPLIT NODE")
        with open(hd_tf, "w", encoding="utf-8") as fh:
            fh.write(headline)
        wm_size = max(24, int(h * 0.060))
        wm_border = max(2, int(h * 0.005))
        hd_size = max(32, int(h * 0.100))
        # Fit the headline to the width (Impact cap-width estimate ~0.52*size)
        est = sum(0.52 * hd_size for ch in headline if not ch.isspace()) \
            + 0.2 * hd_size * max(0, len(headline.split()) - 1)
        if est > 0.88 * w:
            hd_size = max(24, int(hd_size * (0.88 * w) / est))
        hd_border = max(3, int(h * 0.007))
        vf = (
            f"drawtext=fontfile={font_name}:fontsize={wm_size}:fontcolor=white:"
            f"borderw={wm_border}:bordercolor=black:shadowx=3:shadowy=3:"
            f"shadowcolor=black@0.6:textfile={os.path.basename(wm_tf)}:"
            f"x={max(16, int(w * 0.02))}:y={max(16, int(h * 0.02))},"
            f"drawtext=fontfile={font_name}:fontsize={hd_size}:fontcolor=white:"
            f"borderw={hd_border}:bordercolor=black:shadowx=4:shadowy=4:"
            f"shadowcolor=black@0.7:textfile={os.path.basename(hd_tf)}:"
            f"x=(w-text_w)/2:y={int(h * 0.80)}"
        )
        cmd = ["ffmpeg", "-y", "-v", "error", "-i", scene_path,
               "-vf", vf, "-frames:v", "1", out_path]
        r = subprocess.run(cmd, capture_output=True, text=True, cwd=workdir)
        for tmp in (local_font, wm_tf, hd_tf):
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except Exception:
                    pass
        return r.returncode == 0 and os.path.isfile(out_path) \
            and os.path.getsize(out_path) > 1000
    except Exception as e:
        print(f"  [THUMB] text burn error: {e}")
        return False

def _generate_thumbnail(topic: str, output_path: str) -> bool:
    print(f"  [THUMB] Generating thumbnail for: {topic[:60]}...")
    headline = _thumbnail_headline(topic)
    # Use the SAME channel style prompt as the main video (Joe 2026-08-09) so
    # the thumbnail matches the episode's look exactly - no generic hardcoded
    # style that drifts from the actual video.
    style = _style_inject().strip()
    prompt = _sanitize_image_prompt(
        f"YouTube documentary thumbnail, {style}, "
        f"dramatic cinematic scene related to: {topic[:120]}. Moody lighting, "
        "dark color grade, high contrast, bold and clickable composition, "
        "16:9 landscape. "
        "CRITICAL: this image must contain NO text at all - no words, no "
        "letters, no numbers, no logos, no watermarks, no captions, no speech "
        "bubbles. Pure clean artwork only; text is added later by the video "
        "editor."
    )
    scene = os.path.join(os.path.dirname(output_path) or ".",
                         "_ep_scene.png")
    try:
        import providers
        ok = providers.generate_thumbnail(prompt, scene, seed=70001)
        if ok and os.path.isfile(scene) and os.path.getsize(scene) > 1000:
            if _burn_thumbnail_text(scene, headline, output_path):
                print(f"  [OK] Thumbnail: {os.path.getsize(output_path)//1024}KB "
                      f"-> {output_path} (headline '{headline}')")
                return True
            # Text burn failed - ship the art-only image rather than nothing.
            print("  [WARN] thumbnail text burn failed - using art-only image")
            shutil.copyfile(scene, output_path)
            return os.path.isfile(output_path) and os.path.getsize(output_path) > 1000
        print("  [FAIL] Thumbnail provider returned no usable image")
    except Exception as e:
        print(f"  [FAIL] Thumbnail error: {e}")
    return False

# -- Titles / description --------------------------------------------

def _generate_titles(topic: str, episode_num: int,
                     bible: Optional[dict] = None) -> list[str]:
    msg = [
        {"role": "system", "content": (
            "You are a viral YouTube title generator for 'Split Node' - a channel about "
            "ordinary people who beat the system. Write 6 clickbaity titles. "
            "Use the FERN formula: each title must IMPLICITLY promise the story's "
            "VISUAL HOOK (the striking thing the viewer will see) and tease the "
            "DEEPER QUESTION (the 'how did this happen / why' the episode answers) "
            "without giving it away. Split the 6 across three proven title formulas, "
            "2 each: (a) curiosity-driven - a mystery or tease the episode answers, "
            "(b) number-driven - lead with an exact figure/amount from the story, "
            "(c) outcome-driven - the transformation, the win, or the price paid. "
            "Do NOT include any episode number or '#XXX' prefix - these are the "
            "public YouTube titles and must stand alone with just the clickbaity "
            "text. Keep each under 70 characters. Reference "
            "the story directly. Return ONLY 6 lines, one title per line, no numbering."
        )},
        {"role": "user", "content": (
            f"Episode #{episode_num:03d}\nTopic: {topic}\n"
            + (f"VISUAL HOOK: {bible.get('visual_hook','')}\n"
               f"DEEPER QUESTION: {bible.get('deeper_question','')}\n"
               if bible and (bible.get('visual_hook') or bible.get('deeper_question')) else "")
            + "\nWrite 6 titles."
        )}
    ]
    text = _llm_chat(msg, max_tokens=250, temp=0.85)
    titles = [t.strip() for t in text.split("\n") if t.strip()]
    result = []
    for t in titles:
        # Defensively strip any episode-number prefix the model still emits
        t = re.sub(r"^#\s*\d+\s*[-:]\s*", "", t.strip())
        t = re.sub(r"^\d+\s*[-:]\s*", "", t.strip())
        if t:
            result.append(t)
    while len(result) < 6:
        result.append(f"The {topic[:40]} story that broke the system")
    result = result[:6]

    # Score the 3 titles against REAL Google Trends demand + YouTube competition
    # (trend-research-toolkit: SerpAPI trends + YouTube Data API via Split Node OAuth).
    if trend_scorer is not None:
        try:
            scored = trend_scorer.score_titles(result, creds_fn=_get_youtube_creds)
            print("  [TREND] title scores (best first):")
            for s in scored:
                print(f"    {s['score']:5.1f}  demand={str(s.get('demand')):>5}  "
                      f"traj={s.get('trajectory','n/a'):>9}  room={str(s.get('room_to_rank')):>5}  {s['title']}")
            result = [s["title"] for s in scored]
        except Exception as e:
            print(f"  [TREND] title scoring failed: {e}")
    return result

DESCRIPTION_SYSTEM_PROMPT = (
    "You write YouTube video descriptions for SPLIT NODE, a cinematic 3D animated "
    "documentary channel telling true stories of ordinary people "
    "who beat the system - hackers, lottery mathematicians, card counters, loophole "
    "finders, scam-baiters. "
    "\n\n"
    "Write a COMPREHENSIVE description for this episode. Structure:\n"
    "1. OPEN WITH THE TOPIC: 2-3 sentences hooking THIS episode's story - the person, "
    "the scheme, the stakes. Make it cinematic and specific to the topic. This is the "
    "main content, so make it rich: what happened, how they did it, what they won.\n"
    "2. THEN INTRODUCE THE CHANNEL: 1-2 sentences about Split Node - 3D animated "
    "documentaries about ordinary people who used their skills to beat the system.\n"
    "3. END WITH THE DISCORD PITCH: mention the Discord community where members get "
    "EARLY ACCESS to watch new videos before they go public, plus vote on future "
    "topics. Include the invite link: https://discord.gg/YSdqKR4wVB\n"
    "\n"
    "Rules:\n"
    "- Plain text with paragraph breaks (blank lines between the 3 sections)\n"
    "- No em dashes, no asterisks, no markdown headers\n"
    "- 120-250 words total\n"
    "- End with 3-5 topic hashtags on their own line\n"
    "- Mention the episode number\n"
)

def _generate_description(topic: str, episode_num: int, article_url: str,
                          bible: Optional[dict] = None) -> str:
    hook = ""
    if bible and (bible.get("visual_hook") or bible.get("deeper_question")):
        hook = (
            f"Visual hook (open the description with this image): {bible.get('visual_hook','')}\n"
            f"Deeper question (the mystery the episode answers): {bible.get('deeper_question','')}\n"
        )
    msg = [
        {"role": "system", "content": DESCRIPTION_SYSTEM_PROMPT},
        {"role": "user", "content": (
            f"Episode #{episode_num:03d}\n"
            f"Topic: {topic}\n"
            f"Source article: {article_url}\n"
            + hook
            + "\nWrite the comprehensive YouTube description."
        )}
    ]
    text = _llm_chat(msg, max_tokens=600, temp=0.75)
    text = text.strip().strip('"\'')
    if text and DISCORD_INVITE not in text:
        text = f"{text}\n\n{DISCORD_INVITE}"
    return text if text else (
        f"{topic}\n\n"
        f"An ordinary person. An extraordinary scheme. They beat the system.\n\n"
        f"Split Node tells true stories of hackers, mathematicians and loophole "
        f"finders who outsmarted the game, recreated in cinematic 3D animation. "
        f"Episode #{episode_num:03d}.\n\n"
        f"Join the Discord for EARLY ACCESS to new episodes before they go public, "
        f"and vote on future topics: {DISCORD_INVITE}\n\n"
        f"#{''.join(w for w in topic.split()[:3])} #Documentary #TrueStories"
    )


def _append_chapters_to_description(description: str,
                                    title_events: Optional[list]) -> str:
    """Append YouTube chapter markers (whisper-matched timecodes) to the
    description:

        CHAPTERS
        0:00 - Intro
        1:45 - The Account That Never Said No
        ...

    Idempotent: never appends twice. Returns the description unchanged if
    there are fewer than 2 chapter events (YouTube needs 3+ entries).
    """
    chapters = [ev for ev in (title_events or []) if ev.get("kind") == "chapter"]
    if len(chapters) < 2:
        return description
    if "\nCHAPTERS\n" in description or description.rstrip().endswith("CHAPTERS"):
        return description

    def _ts(s: float) -> str:
        s = max(int(round(s)), 0)
        m, sec = divmod(s, 60)
        return f"{m}:{sec:02d}"

    lines = ["", "", "CHAPTERS", "0:00 - Intro"]
    for ev in sorted(chapters, key=lambda e: e.get("start", 0)):
        title = (ev.get("title") or "").strip()
        if title:
            lines.append(f"{_ts(ev.get('start', 0))} - {title}")
    if len(lines) < 6:  # Intro + <3 chapters - YouTube won't show the panel
        return description
    return description + "\n".join(lines)

def _generate_tags(topic: str, episode_num: int) -> list[str]:
    msg = [
        {"role": "system", "content": (
            "Generate exactly 12 comma-separated YouTube tags for a video on a "
            "3D animated documentary channel. "
            "Return ONLY the tags separated by commas. Mix: 3 viral, 3 curiosity, "
            "3 specific topic, 3 broad category. All tags must be relevant to THIS "
            "video's topic and the documentary niche."
        )},
        {"role": "user", "content": f"Topic: {topic}\nEpisode #{episode_num:03d} of Split Node"}
    ]
    text = _llm_chat(msg, max_tokens=200, temp=0.6)
    tags = [t.strip().lower() for t in text.split(",") if t.strip()]
    tags = [t for t in tags if len(t) > 2 and len(t) < 50]
    return tags[:12]

# -- YouTube upload --------------------------------------------------

YOUTUBE_SETUP_LINK = "https://console.cloud.google.com/apis/credentials"

YOUTUBE_SETUP_INSTRUCTIONS = f"""
====================================================================
  YOUTUBE UPLOAD SETUP - your API secret .json is required
====================================================================
  Split Node auto-uploads finished episodes to YouTube. To enable that
  you need your OAuth client secret .json (one-time, ~5 min) and one
  browser authorization (~30 sec).

  GET THE SECRET .json HERE:
  {YOUTUBE_SETUP_LINK}

  1. Open the link above (Google Cloud console, Credentials page).
  2. Select the project you use for YouTube (or create a new one,
     then in "APIs & Services > Library" ENABLE the "YouTube Data API v3").
  3. Click "+ CREATE CREDENTIALS" -> "OAuth client ID"
     -> Application type = "Desktop app" -> name it -> CREATE.
  4. Click the DOWNLOAD icon on the client you just made - a .json
     file downloads. Save it as  client_secret_*.json  in this folder:
        {PROJECT_DIR}
  5. ADD THE CHANNEL EMAIL AS A TEST USER (required - without this the
     auth URL refuses to log in until your project is verified):
     OAuth consent screen -> "Test users" -> + Add users -> enter the
     email address of the YouTube CHANNEL itself (the account that owns
     the channel you upload to).
  6. Then run:  python oauth_split_node.py   to authorize once.
====================================================================
"""


def _ensure_youtube_secret() -> Optional[str]:
    """Ensure a YouTube API secret .json exists in the project folder.
    If creds are already saved, return immediately. Otherwise prompt the
    user to place client_secret_*.json here (with a link + instructions in
    the terminal log) and wait for it. Returns the secret path or None."""
    if YOUTUBE_CREDENTIALS.is_file():
        return None  # already authorized - no setup needed
    for p in sorted(PROJECT_DIR.glob("client_secret_*.json")):
        return str(p)
    print(YOUTUBE_SETUP_INSTRUCTIONS)
    print(f"  [YOUTUBE] Waiting for client_secret_*.json in {PROJECT_DIR} ...")
    print(f"  [YOUTUBE] Get it here: {YOUTUBE_SETUP_LINK}")
    deadline = time.time() + 3600
    while time.time() < deadline:
        for p in sorted(PROJECT_DIR.glob("client_secret_*.json")):
            return str(p)
        time.sleep(3)
    print("  [YOUTUBE] Timed out waiting for the secret .json - upload skipped")
    return None


def _get_youtube_creds():
    """Load + refresh YouTube creds; if auth fails, re-authorize inline via
    youtube_reauth (prints a link, waits for you to paste the code back)."""
    import youtube_reauth
    return youtube_reauth.ensure_youtube_creds(
        YOUTUBE_CREDENTIALS, PROJECT_DIR, "Split Node")

def _upload_video_with_progress(video_path: str, title: str, description: str,
                                tags_str: str, privacy: str = "public") -> Optional[str]:
    creds = _get_youtube_creds()
    if not creds:
        return None
    file_size = os.path.getsize(video_path)
    # YouTube caps the video description at 5000 chars. The LLM description +
    # Discord pitch + full chapter list routinely exceeds it, which makes the
    # resumable-upload INIT return HTTP 400 "invalidDescription". Clamp to the
    # limit on a newline boundary so the upload never 400s on metadata (Joe).
    if description and len(description) > 4990:
        _cut = description[:4990]
        _nl = _cut.rfind("\n")
        if _nl > 3000:
            _cut = _cut[:_nl]
        description = _cut.rstrip() + "\n\n[Full description truncated to YouTube's 5000-char limit]"
    body = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": tags_str.split(",")[:499],  # YouTube max 500 tags
            "categoryId": "24",
        },
        "status": {
            "privacyStatus": privacy,
            "embeddable": True,
            "selfDeclaredMadeForKids": False,
        },
    }
    try:
        headers_init = {
            "Authorization": f"Bearer {creds.token}",
            "Content-Type": "application/json",
            "X-Upload-Content-Length": str(file_size),
            "X-Upload-Content-Type": "video/mp4",
        }
        upload_url = None
        r = requests_post(
            "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status",
            headers=headers_init, json=body, timeout=30
        )
        if r.status_code != 200:
            print(f"  [WARN] Upload init failed (HTTP {r.status_code})")
            if r.status_code in (401, 403):
                print("  [WARN] Token invalid - re-authorizing and retrying...")
                creds = _get_youtube_creds()  # re-auths inline if needed
                if creds:
                    headers_init["Authorization"] = f"Bearer {creds.token}"
                    r = requests_post(
                        "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status",
                        headers=headers_init, json=body, timeout=30)
                    if r.status_code == 200:
                        upload_url = r.headers.get("Location")
            if not upload_url:
                return None
        else:
            upload_url = r.headers.get("Location")
        if not upload_url:
            return None
        chunk_size = 256 * 1024
        if _HAS_PROGRESS:
            pbar = tqdm(total=file_size, unit="B", unit_scale=True, desc="  [YT] Video")
        else:
            pbar = None
        bytes_sent = 0
        with open(video_path, "rb") as f:
            while bytes_sent < file_size:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                start = bytes_sent
                end = bytes_sent + len(chunk) - 1
                content_range = f"bytes {start}-{end}/{file_size}"
                for attempt in range(3):
                    try:
                        r = requests_put(upload_url, headers={
                            "Content-Length": str(len(chunk)),
                            "Content-Range": content_range,
                        }, data=chunk, timeout=120)
                        if r.status_code not in (308, 200, 201):
                            if attempt < 2:
                                time.sleep(2)
                                continue
                        break
                    except Exception:
                        if attempt < 2:
                            time.sleep(2)
                            continue
                        raise
                bytes_sent += len(chunk)
                if pbar:
                    pbar.update(len(chunk))
        if pbar:
            pbar.close()
        if r.status_code in (200, 201):
            vid = r.json().get("id")
            if vid:
                print(f"\n  [OK] Uploaded: https://youtu.be/{vid}")
                return vid
        return None
    except Exception as e:
        print(f"  [WARN] Upload error: {e}")
        return None

def _upload_thumbnail(video_id: str, thumbnail_path: str):
    if not os.path.isfile(thumbnail_path):
        return
    try:
        creds = _get_youtube_creds()
        if not creds:
            return
        r = requests_post(
            f"https://www.googleapis.com/upload/youtube/v3/thumbnails/set?videoId={video_id}",
            headers={"Authorization": f"Bearer {creds.token}"},
            files={"thumbnail": open(thumbnail_path, "rb")},
            timeout=30
        )
        if r.status_code == 200:
            print(f"  [OK] Thumbnail uploaded")
        else:
            print(f"  [WARN] Thumbnail upload failed: {r.status_code}")
    except Exception as e:
        print(f"  [WARN] Thumbnail upload error: {e}")

def _add_video_to_playlist(video_id: str) -> bool:
    creds = _get_youtube_creds()
    if not creds:
        return False
    try:
        r = requests_get(
            "https://www.googleapis.com/youtube/v3/playlists?part=snippet&mine=true&maxResults=50",
            headers={"Authorization": f"Bearer {creds.token}"}, timeout=15
        )
        playlist_id = None
        if r.status_code == 200:
            for pl in r.json().get("items", []):
                if pl["snippet"]["title"].lower() == YOUTUBE_PLAYLIST.lower():
                    playlist_id = pl["id"]
                    break
        if not playlist_id:
            r = requests_post(
                "https://www.googleapis.com/youtube/v3/playlists?part=snippet,status",
                headers={"Authorization": f"Bearer {creds.token}", "Content-Type": "application/json"},
                json={
                    "snippet": {
                        "title": YOUTUBE_PLAYLIST,
                        "description": f"{CHANNEL_NAME} - true stories of people who beat the system",
                    },
                    "status": {"privacyStatus": "public"}
                }, timeout=15
            )
            if r.status_code == 200:
                playlist_id = r.json().get("id")
        if playlist_id:
            r = requests_post(
                "https://www.googleapis.com/youtube/v3/playlistItems?part=snippet",
                headers={"Authorization": f"Bearer {creds.token}", "Content-Type": "application/json"},
                json={
                    "snippet": {
                        "playlistId": playlist_id,
                        "resourceId": {"kind": "youtube#video", "videoId": video_id}
                    }
                }, timeout=15
            )
            return r.status_code == 200
    except Exception as e:
        print(f"  [PLAYLIST] {e}")
    return False


def _post_first_comment(video_id: str, topic: str) -> bool:
    """Post a pinned-style first comment on a freshly-uploaded Split Node video
    (Joe 2026-08-14: auto-comment on Split Node long-form, NOT on Shorts). The
    comment is a short channel voice line that references the episode topic.

    Uses the youtube.force-ssl scope (commentThreads.insert). The stored creds
    already carry the full `youtube` scope which covers commenting, so no
    re-authorization is required. Non-fatal: a comment failure never blocks
    the upload/publish flow.
    """
    if not video_id:
        return False
    if os.environ.get("AUTO_COMMENT", "1") == "0":
        print("  [COMMENT] disabled (AUTO_COMMENT=0)")
        return False
    creds = _get_youtube_creds()
    if not creds:
        return False
    comment = ("This one got away with it... but the story doesn't end there. "
               "Drop a comment if you'd have tried the same loophole.")
    try:
        r = requests_post(
            "https://www.googleapis.com/youtube/v3/commentThreads?part=snippet",
            headers={"Authorization": f"Bearer {creds.token}",
                     "Content-Type": "application/json"},
            json={
                "snippet": {
                    "videoId": video_id,
                    "topLevelComment": {
                        "snippet": {"textOriginal": comment}
                    }
                }
            }, timeout=15
        )
        if r.status_code in (200, 201):
            cid = r.json().get("id", "")
            print(f"  [COMMENT] posted on https://youtu.be/{video_id}"
                  f" (thread {cid})")
            return True
        # 403 = comments disabled on the video (e.g. made-for-kids / defaults).
        print(f"  [COMMENT] failed (HTTP {r.status_code}): "
              f"{r.text[:200]}")
        return False
    except Exception as e:
        print(f"  [COMMENT] {e}")
        return False

try:
    import requests as _req
    def requests_get(*a, **kw): return _req.get(*a, **kw)
    def requests_post(*a, **kw): return _req.post(*a, **kw)
    def requests_put(*a, **kw): return _req.put(*a, **kw)
except ImportError:
    def _urllib_req(method, url, headers=None, json=None, data=None, files=None, timeout=30):
        body = data
        if json is not None:
            body = json.dumps(json).encode()
        hdrs = dict(headers or {})
        if json is not None:
            hdrs["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=body, headers=hdrs, method=method)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r
    def requests_get(url, headers=None, timeout=30):
        return _urllib_req("GET", url, headers=headers, timeout=timeout)
    def requests_post(url, headers=None, json=None, files=None, timeout=30):
        return _urllib_req("POST", url, headers=headers, json=json, timeout=timeout)
    def requests_put(url, headers=None, data=None, timeout=120):
        return _urllib_req("PUT", url, headers=headers, data=data, timeout=timeout)

# -- Discord announcement --------------------------------------------

def _strip_discord_pitch(text: str) -> str:
    """Remove Discord invite links + invite-pitch paragraphs from an
    announcement body. The announcement is posted INSIDE the Discord server,
    so pitching the server / linking the invite there is noise. The YouTube
    description itself keeps the pitch untouched."""
    if not text:
        return text
    t = text.replace(DISCORD_INVITE, "").replace(DISCORD_INVITE.rstrip("/"), "")
    keep = []
    for p in t.split("\n\n"):
        low = p.lower()
        is_pitch = ("discord" in low and any(
            k in low for k in ("join", "invite", "early access", "server",
                               "community", "vote on future")))
        if not is_pitch and p.strip():
            keep.append(p.strip())
    return re.sub(r"\n{3,}", "\n\n", "\n\n".join(keep)).strip()


def _post_discord_announcement(topic: str, video_id: str, episode_num: int,
                               wait_seconds: int = 60, description: str = "") -> None:
    """Wait, then post the announcement to all Discord channels.

    Uses the video's own YouTube description as the announcement body
    (with the Discord invite pitch stripped - we're already inside Discord),
    wrapped in a hype line at top + bottom, with the YouTube link.
    """
    if not video_id:
        print("  [DISCORD] No video ID - skipping announcement")
        return
    print(f"\n  [DISCORD] Waiting {wait_seconds}s before announcing...")
    time.sleep(wait_seconds)
    url = f"https://youtu.be/{video_id}"
    body = (description or f"{topic}\n\nSplit Node episode #{episode_num:03d} is live on YouTube!").strip()
    body = _strip_discord_pitch(body)
    message = (
        f"NEW EPISODE IS LIVE ON YOUTUBE!\n\n"
        f"{body}\n\n"
        f"Watch the full episode now!\n\n"
        f"{url}"
    )
    print(f"  [DISCORD] Announcement:\n    {message[:120]}...")
    try:
        import discord_bot
    except Exception as e:
        print(f"  [DISCORD] discord_bot import failed: {e}")
        return
    for ch in DISCORD_ANNOUNCE_CHANNELS:
        try:
            r = discord_bot.send_message(message, channel=ch,
                                         token=DISCORD_BOT_TOKEN)
            if r.get("error"):
                print(f"  [DISCORD] Failed channel {ch}: {r.get('message', r.get('error'))}")
            else:
                print(f"  [DISCORD] Posted to channel {ch} (id={r.get('id', '?')})")
        except Exception as e:
            print(f"  [DISCORD] Failed channel {ch}: {e}")
    print("  [DISCORD] Announcement done")


# -- Main ------------------------------------------------------------

def print_banner():
    print("""
  ==============================================
        SPLIT NODE
  True stories of ordinary people who
        beat the system.
  3D animated documentary, AI generated.
  ==============================================
""")

def _preflight() -> bool:
    print("\n  [PREFLIGHT] Checking environment...")
    ok = True
    try:
        req = urllib.request.Request(POCKET_TTS_URL + "/health", method="GET")
        with urllib.request.urlopen(req, timeout=5) as r:
            if r.status == 200:
                print(f"  [OK] PocketTTS server ({TTS_VOICE} voice)")
            else:
                print(f"  [WARN] PocketTTS returned {r.status}")
    except Exception as e:
        print(f"  [WARN] PocketTTS not reachable: {e}")
    try:
        req = urllib.request.Request(LM_STUDIO_URL, data=json.dumps({
            "model": LLM_MODEL,
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 1,
        }).encode(), headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as r:
            print(f"  [OK] LM Studio reachable")
    except Exception as e:
        print(f"  [WARN] LM Studio not reachable: {e}")
    sfx_count = sum(1 for _k in SFX_LIBRARY if _sfx_path(_k) is not None)
    sfx_disk = sum(1 for f in SFX_DIR.rglob("*") if f.is_file()) if SFX_DIR.is_dir() else 0
    print(f"  [OK] Cinematic sounds: {sfx_count} in library ({sfx_disk} files on disk)")
    if not CLIENT_SECRETS.is_file():
        print(f"  [FAIL] Split Node client secrets missing: {CLIENT_SECRETS.name}")
        ok = False
    if not YOUTUBE_CREDENTIALS.is_file():
        print(f"  [WARN] YouTube credentials missing - upload will fail (run OAuth first)")
    print()
    return ok

def _resume_file_for(ep_num: int) -> Path:
    """Resume-state path for a specific episode: .resume_state.ep{NNN}.json for
    ep>0, else the legacy .resume_state.json. Thread-safe (derived from the ep
    number, no global mutation) so a batch can save/resume many episodes in
    parallel without clobbering each other."""
    return (PROJECT_DIR / f".resume_state.ep{int(ep_num):03d}.json"
            if ep_num and int(ep_num) > 0
            else PROJECT_DIR / ".resume_state.json")

def _shotlist_incomplete_file(ep_num: int) -> Path:
    """Marker that the previous run died MID shot-list (per-shot checkpoint
    fired). Resume checks it and auto-runs _regenerate_shot_list_for_resume
    to fill the missing tail, so a kill during the longest LLM phase
    recovers the already-generated shots instead of starting over."""
    if ep_num and int(ep_num) > 0:
        return PROJECT_DIR / f".shotlist_incomplete.ep{int(ep_num):03d}"
    return PROJECT_DIR / ".shotlist_incomplete"

def _mark_shotlist_incomplete(ep_num: int) -> None:
    try:
        _shotlist_incomplete_file(ep_num).write_text("1", encoding="utf-8")
    except Exception:
        pass

def _clear_shotlist_incomplete(ep_num: int) -> None:
    try:
        _f = _shotlist_incomplete_file(ep_num)
        if _f.exists():
            _f.unlink()
    except Exception:
        pass

def _shotlist_incomplete(ep_num: int) -> bool:
    return _shotlist_incomplete_file(ep_num).exists()


def _save_resume_state(stage: str, episode_num: int, article_url: str = "", topic: str = "",
                       shots: Optional[list] = None, character_sheets: Optional[dict] = None,
                       titles: Optional[list] = None, description: str = "",
                       tags: Optional[list] = None, thumb_path: str = "",
                       video_path: str = "", video_id: str = "",
                       chapter_events: Optional[list] = None,
                       anchor_events: Optional[list] = None,
                       location_sheets: Optional[dict] = None,
                       prop_assets: Optional[dict] = None,
                       target_paras: int = 0,
                       narration: Optional[list] = None,
                       context: Optional[dict] = None,
                       bible: Optional[dict] = None,
                       sentence_para_map: Optional[dict] = None,
                       establishing_map: Optional[dict] = None,
                       resume_file: Optional[Path] = None,
                       intro_count: int = 0) -> None:
    """Save episode state so it can be resumed if interrupted."""
    state = {
        "version": 3,
        "stage": stage,
        "episode_num": episode_num,
        "article_url": article_url,
        "topic": topic,
        "style": _get_style_prompt(),
        "img_backend": _active_image_backend(),
        "resolution": os.environ.get("RESOLUTION", "1080p"),
        "shots": shots or [],
        "character_sheets": character_sheets or {},
        "location_sheets": location_sheets or {},
        "prop_assets": prop_assets or {},
        "target_paras": target_paras,
        "titles": titles or [],
        "description": description,
        "tags": tags or [],
        "thumb_path": thumb_path,
        "video_path": video_path,
        "video_id": video_id,
        "chapter_events": chapter_events or [],
        "anchor_events": anchor_events or [],
        # Shot-list regeneration support (Joe 2026-08-12): persist the flattened
        # narration + world context so a resume can re-run the shot list to fill
        # parse-failed/missing shots without a full script rebuild.
        "narration": narration or [],
        "context": context or {},
        "bible": bible or {},
        "sentence_para_map": sentence_para_map or {},
        "establishing_map": establishing_map or {},
        # Two-voice narration (Joe 2026-08-13): number of leading narration
        # sentences spoken in the announcement INTRO_VOICE (video start); the
        # rest use the storytelling STORY_VOICE (video middle). Persisted so a
        # resume regenerates missing clips with the correct voice.
        "intro_count": int(intro_count or 0),
    }
    try:
        rf = resume_file or _resume_file_for(episode_num)
        tmp = rf.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=2, default=str))
        tmp.replace(rf)
        # Backup: keep the previous good state alongside the main file so a
        # lost/corrupt/overwritten main file can never silently kill the
        # resume prompt (load falls back to the .bak).
        try:
            rf.with_name(rf.name + ".bak").write_text(
                json.dumps(state, indent=2, default=str))
        except Exception:
            pass
        # Ep-folder mirror (Joe 2026-08-12): also drop a copy inside the episode
        # folder so the state is co-located with the episode. Deleting this
        # mirror is the signal that the episode is gone - _load_resume_state /
        # _scan_resume_states then refuse to resume it.
        try:
            if episode_num and int(episode_num) > 0:
                mdir = _episode_dir(episode_num)
                mdir.mkdir(parents=True, exist_ok=True)
                (mdir / ".resume_state.json").write_text(
                    json.dumps(state, indent=2, default=str))
        except Exception:
            pass
        print(f"  [STATE] Saved resume state (stage={stage}, {len(state['shots'])} shots)")
    except Exception as e:
        print(f"  [STATE] Could not save resume state: {e}")


def _load_resume_state() -> Optional[dict]:
    """Load resume state if it exists and is valid.

    Falls back to the .bak copy when the main file is missing or corrupt -
    the resume prompt must never silently disappear because the state file
    got lost (e.g. wiped mid-run or by external tooling).

    EP-FOLDER MIRROR GATE (Joe 2026-08-12): for a per-episode state the
    authoritative existence marker is the mirror inside episodes/epNNN/. If
    that mirror has been deleted, the episode is treated as gone and is NOT
    resumed, even if the project-root file still lingers.
    """
    m = re.search(r"\.ep(\d{1,3})\.json$", RESUME_FILE.name)
    if m:
        ep = int(m.group(1))
        if not (_episode_dir(ep) / ".resume_state.json").exists():
            return None
    for f in (RESUME_FILE, RESUME_FILE.with_name(RESUME_FILE.name + ".bak")):
        if not f.exists():
            continue
        try:
            state = json.loads(f.read_text())
            if state.get("version") not in (1, 2, 3):
                continue
            if f != RESUME_FILE:
                print("  [STATE] Main resume state missing/corrupt - "
                      "restored from backup")
            return state
        except Exception:
            continue
    return None


def _state_intro_count(episode_num: int) -> int:
    """intro_count for an episode from its resume state (falls back to 0 when
    absent/mismatched). Used by render-time / sequential TTS repair paths so a
    regenerated missing INTRO clip is spoken in the announcement voice."""
    try:
        st = _load_resume_state()
        if st and int(st.get("episode_num", -1)) == int(episode_num):
            return int(st.get("intro_count", 0) or 0)
    except Exception:
        pass
    return 0


def _clear_resume_state(episode_num: int = 0, resume_file: Optional[Path] = None) -> None:
    try:
        rf = resume_file or _resume_file_for(episode_num)
        for f in (rf, rf.with_name(rf.name + ".bak")):
            if f.exists():
                f.unlink()
        # Also drop the ep-folder mirror so a cleared episode stays cleared.
        if episode_num and int(episode_num) > 0:
            mir = _episode_dir(int(episode_num)) / ".resume_state.json"
            if mir.exists():
                mir.unlink()
        print("  [STATE] Resume state cleared")
    except Exception:
        pass


def _set_resume_ep(ep_num: int) -> None:
    """Point the module-level RESUME_FILE at a specific episode's state file so a
    single process can save/load/resume MANY episodes in one batch. ep_num<=0
    -> the legacy single .resume_state.json."""
    global RESUME_FILE
    if ep_num and int(ep_num) > 0:
        RESUME_FILE = PROJECT_DIR / f".resume_state.ep{int(ep_num):03d}.json"
    else:
        RESUME_FILE = PROJECT_DIR / ".resume_state.json"


def _scan_resume_states() -> list:
    """Every valid resume state on disk (legacy + per-episode), newest first.
    Each carries '_file' + '_ep'. Used for the resume-all batch flow.

    Dedupes by EPISODE NUMBER (not filename): the legacy `.resume_state.json`
    and the per-episode `.resume_state.ep011.json` both describe ep #011, so we
    keep only the NEWEST state for each episode (files are sorted newest-first)
    to avoid asking the user to resume the same episode twice in sequence
    (Joe 2026-08-09)."""
    found = []
    seen_eps = set()
    for f in sorted(PROJECT_DIR.glob(".resume_state*.json"),
                    key=lambda p: p.stat().st_mtime, reverse=True):
        name = f.name
        if name.endswith(".bak") or name.endswith(".tmp"):
            continue
        try:
            state = json.loads(f.read_text())
            if state.get("version") not in (1, 2, 3):
                continue
            state["_file"] = str(f)
            m = re.search(r"\.ep(\d{1,3})\.json$", name)
            state["_ep"] = int(m.group(1)) if m else int(state.get("episode_num", 0))
            ep = state["_ep"]
            # Ep-folder mirror gate (Joe 2026-08-12): if the episode's mirror
            # inside its ep folder was deleted, the episode is considered gone
            # and is not offered for resume.
            if ep and int(ep) > 0 and not (_episode_dir(int(ep)) / ".resume_state.json").exists():
                continue
            if ep in seen_eps:
                # Newer state for this episode already collected - skip the older dup.
                continue
            seen_eps.add(ep)
            found.append(state)
        except Exception:
            continue
    return found


def _pause(prompt: str = "  Press Enter to exit...") -> None:
    """Wait for Enter, but return immediately when stdin is closed
    (unattended/piped run) so a finished pipeline exits cleanly."""
    try:
        input(prompt)
    except EOFError:
        return


def _yn(prompt: str, default: bool = False) -> bool:
    """Simple yes/no prompt. Returns the default on empty/unknown input."""
    while True:
        try:
            resp = input(prompt).strip().lower()
        except EOFError:
            # stdin closed (unattended/piped run finished) - take the default
            # so a completed pipeline exits cleanly instead of traceback-ing.
            return default
        if not resp:
            return default
        if resp in ("y", "yes"):
            return True
        if resp in ("n", "no"):
            return False
        print("  [WARN] enter y or n")


def _ask_image_model_swap() -> None:
    """Interactively pick the image backend + model for this run's shots.

    Sets IMAGE_BACKEND / IMAGE_MODEL env vars, which are read by
    _krea_generate -> providers.generate_image. A model change forces image
    regeneration (caller handles that). Existing IMAGE_BACKEND / IMAGE_MODEL
    env vars are shown as the current values and used as defaults.
    """
    try:
        import providers
    except Exception as e:
        print(f"  [IMG] providers import failed: {e}")
        return
    cur = (os.environ.get("IMAGE_BACKEND", "").strip().lower()
           or providers._env_backend("IMAGE"))
    cur_model = providers._env_model("IMAGE", cur)
    print("\n  Image generation model swap:")
    print(f"  current: backend={cur}, model={cur_model}")
    print(f"  backends: {', '.join(providers.IMAGE_BACKENDS)}")
    while True:
        b = input(f"  Backend? (enter for {cur}): ").strip().lower()
        if not b:
            b = cur
        if b not in providers.IMAGE_BACKENDS:
            print(f"  [WARN] unknown backend '{b}' - "
                  f"choose one of: {', '.join(providers.IMAGE_BACKENDS)}")
            continue
        break
    models = list(providers.IMAGE_MODELS[b].keys())
    default_model = providers.IMAGE_DEFAULTS.get(b, models[0] if models else "")
    print(f"  {b} models: {', '.join(models)}")
    while True:
        m = input(f"  Model? (enter for {default_model}): ").strip().lower()
        if not m:
            m = default_model
        if m not in providers.IMAGE_MODELS[b]:
            print(f"  [WARN] unknown model '{m}' for {b} - "
                  f"choose: {', '.join(models)}")
            continue
        break
    os.environ["IMAGE_BACKEND"] = b
    os.environ["IMAGE_MODEL"] = m
    print(f"  [IMG] image model -> backend={b}, model={m}")


def _rebuild_script_for_resume(state: dict) -> dict:
    """Re-fetch the article and rebuild the ENTIRE script pipeline so the user
    can regenerate an episode's script on resume.

    Mirrors the fresh-run path: story bible -> narration -> relevance rating ->
    chapter markers -> anchors -> establishing shots -> episode context ->
    directors bible -> scene board -> shot list -> character sheets -> brand
    assets -> location sheets -> prop assets. Returns a dict of updated state
    fields (empty dict on failure). The caller then forces image + TTS
    regeneration for the fresh shots.
    """
    episode_num = int(state.get("episode_num", 0))
    article_url = state.get("article_url", "")
    topic = state.get("topic", "")
    _set_img_topic(topic)   # for the LLM prompt-relevance gate (Joe 2026-08-09)
    target_paras = int(state.get("target_paras", 0) or TARGET_NARRATION_PARAS)
    if not article_url:
        print("  [SCRIPT] No article_url in state - cannot rebuild script")
        return {}

    print(f"\n[SCRIPT] Rebuilding narration script from: {article_url}")
    paragraphs = fetch_article_paragraphs(article_url)
    if paragraphs:
        paragraphs = _rate_paragraph_relevance(topic, paragraphs)
    if not paragraphs:
        print("  [HALT] Could not re-fetch article content - script rebuild aborted")
        return {}

    story_bible = _build_story_bible(topic, paragraphs)
    narration = _build_narration_script(paragraphs, target_paras, bible=story_bible)
    if narration:
        narration = _rate_paragraph_relevance(topic, narration)
        if not narration:
            print("  [FILTER] All rebuilt narration off-topic, retrying...")
            narration = _build_narration_script(paragraphs, target_paras, bible=story_bible)
    # Drop back-to-back same-location repeats BEFORE chapter/anchors/establishing
    # so every derived index map stays aligned with the deduped narration.
    narration = _dedupe_consecutive_locations(narration)
    # Intro hook + narration plan (key words + foley) at the PARAGRAPH level,
    # BEFORE chapters are inserted / sentences split (Joe 2026-08-12).
    plan = _plan_narration(narration, episode_num)
    intro, intro_plan = _generate_intro(paragraphs)
    if intro:
        narration = list(intro) + narration
        for _ki, _kv in (intro_plan or {}).items():
            plan[max(plan.keys(), default=-1) + 1] = _kv
        print(f"  [INTRO] {len(intro)}-phase shorts-formula intro (+"
              f"{len(intro_plan or {})} key highlight) prepended before chapter 1")
    narration, chapter_events = _insert_chapter_markers(narration)
    anchor_events = _extract_anchor_events(narration)
    establishing_map = {}
    if story_bible:
        narration, establishing_map = _inject_establishing_shots(
            narration, bible=story_bible, anchor_events=anchor_events)
    # SENTENCE-LEVEL SHOTS (Joe 2026-08-10): flatten to one shot per sentence.
    narration, sentence_para_map, chapter_events, establishing_map, anchor_events = \
        _flatten_narration_to_sentences(
            narration, chapter_events, establishing_map, anchor_events)
    narration, sentence_para_map, chapter_events, establishing_map, anchor_events = \
        _cap_flattened_narration(
            narration, sentence_para_map, chapter_events,
            establishing_map, anchor_events)
    context = _build_episode_context(topic, paragraphs)
    bible = _build_directors_bible(topic, narration)
    # Merge the STORY bible's character roster into the state bible (Joe
    # 2026-08-17): the directors bible has no 'characters' key, and persisting
    # only the directors bible made every resume see an EMPTY character roster
    # ("0 character sheets / character not found"). The merged dict is what
    # gets saved to the resume state so characters survive a crash.
    _state_bible = dict(bible or {})
    if story_bible and story_bible.get("characters"):
        _state_bible["characters"] = story_bible["characters"]
    _build_scene_board(narration, topic, episode_num)
    _plan_durations(narration)

    _shot_bible = dict(bible or {})
    if story_bible and story_bible.get("characters"):
        _shot_bible["characters"] = story_bible["characters"]
    shots = _build_shot_list(narration, bible=_shot_bible, context=context,
                             establishing_map=establishing_map,
                             sentence_para_map=sentence_para_map)
    _apply_plan_to_shots(shots, sentence_para_map, plan)  # key words + foley onto shots

    character_sheets = _build_character_sheets(shots, narration, bible=story_bible)
    brands = _extract_brands(topic, paragraphs, narration)
    if brands:
        print(f"\n  [BRAND] businesses detected: {', '.join(brands)}")
        for _b, _ctx in brands.items():
            _generate_brand_asset(_b, _ctx, random.randint(0, 99999))
    brand_assets = _scan_brand_assets()
    ep_dir = _episode_dir(episode_num)
    location_sheets = _build_location_sheets(
        context, 42000 + episode_num * 7, ep_dir, brands=brands)
    prop_assets = _build_prop_assets(
        context, 43000 + episode_num * 7, ep_dir, brands=brands)

    print(f"\n[SCRIPT] Rebuilt: {len(narration)} paras -> {len(shots)} shots")
    return {
        "shots": shots, "character_sheets": character_sheets,
        "location_sheets": location_sheets, "prop_assets": prop_assets,
        "brand_assets": brand_assets,
        "chapter_events": chapter_events, "anchor_events": anchor_events,
        "topic": topic, "article_url": article_url,
        "target_paras": target_paras,
    }


def _resume_tts_gap_fill(shots: list[dict], episode_num: int, regen_tts: bool,
                         save_cb, intro_count: int = 0) -> None:
    """Gap-fill TTS for a resume: reuse any narration clip already on disk and
    generate only what's missing. Runs BEFORE image generation (Joe 2026-08-09)
    so images aren't generated against missing audio. Matches both the narrator
    file (narration_XX.wav) and per-character clone file (narration_XX_char.wav
    via voice_map.json). Also strips leaked stage directions before speaking."""
    ep_dir = _ep_tts_dir(episode_num)
    ep_dir.mkdir(parents=True, exist_ok=True)
    # Integrity guard (Joe 2026-08-10): if this episode folder already holds
    # clips but has NO narration_map sidecar, we cannot prove any clip matches
    # its line (it may be stale narration from an earlier/different story that
    # reused this episode number). Force a re-speak rather than risk it.
    _ensure_tts_sidecar(ep_dir)
    if regen_tts:
        # Re-speak ALL narration clips INCLUDING chapter cards (Joe 2026-08-12:
        # chapters are read programmatically and must never be left silent).
        missing_tts = [s for s in shots
                       if (s.get("narration") or "").strip()]
        print(f"\n[TTS] REGEN - re-speaking ALL {len(missing_tts)} narration clips")
    else:
        # GAP-FILL (Joe 2026-08-09): reuse any clip already on disk, matching
        # BOTH the narrator file (narration_XX.wav) and the per-character clone
        # file (narration_XX_char.wav, used when voice_map.json maps this shot's
        # character to a different voice). Only generate what's actually missing.
        # Joe 2026-08-10: reuse is now CONTENT-GATED - a clip is only reused if
        # its recorded narration matches this shot's CURRENT text, so a stale
        # clip from a different story can never be reused by filename alone.
        missing_tts = []
        for s in shots:
            _nidx = s.get("narration_idx", 0)
            _voice = _lookup_voice(s.get("character", "NONE"))
            _narr = (s.get("narration") or "").strip()
            _disk = str(ep_dir / f"narration_{_nidx:02d}.wav")
            _disk_char = str(ep_dir / f"narration_{_nidx:02d}_char.wav")
            # Prefer the exact clip for this shot's voice (char variant if the
            # shot uses a clone voice, else the narrator variant).
            if _voice and _tts_clip_matches(ep_dir, _nidx, _narr, char=True, path=_disk_char):
                s["tts_path"] = _disk_char
                continue
            if _tts_clip_matches(ep_dir, _nidx, _narr, char=False, path=_disk):
                s["tts_path"] = _disk
                continue
            missing_tts.append(s)
    if missing_tts:
        print(f"\n[TTS] Generating {len(missing_tts)} missing narration clips "
              f"({len(shots) - len(missing_tts)} already on disk)...")
        for idx, shot in enumerate(missing_tts):
            nidx = shot.get("narration_idx", idx)
            _voice = _lookup_voice(shot.get("character", "NONE"))
            out = str(ep_dir / f"narration_{nidx:02d}.wav")
            _is_char = False
            # Two-voice narration (Joe 2026-08-13): a missing INTRO sentence
            # (no character clone, narration_idx < intro_count) is re-spoken in
            # the announcement INTRO_VOICE; everything else uses the character
            # clone voice if present, else the storytelling STORY_VOICE.
            if not _voice and intro_count and nidx < intro_count:
                _voice = INTRO_VOICE
            elif _voice:
                out = str(ep_dir / f"narration_{nidx:02d}_char.wav")
                _is_char = True
            shot["tts_path"] = out
            speak = _strip_stage_directions(shot.get("narration") or "")
            ok = _pocket_tts_generate(speak, out, voice=_voice)
            if ok:
                _normalize_voice_0db(out)
                _tts_map_record(ep_dir, nidx, speak, char=_is_char)
                print(f"  [TTS] {_get_audio_duration(out):.1f}s - {speak[:50]}...")
            else:
                print(f"  [TTS] FAILED - {speak[:50]}...")
            time.sleep(0.5)
        # Invalidate the old mix.wav: it was built WITHOUT these newly generated
        # clips, so _render_video would reuse it on resume and leave those
        # sentences silent while drifting every later clip (Joe 2026-08-12,
        # review finding 3). Rebuild on the next render.
        try:
            _mix = _ep_audio_dir(episode_num) / "mix.wav"
            if _mix.is_file():
                _mix.unlink()
                print("  [TTS] stale mix.wav invalidated (clips changed) - "
                      "audio mix will rebuild")
        except Exception as _mixerr:
            print(f"  [TTS] could not invalidate mix.wav: {_mixerr}")
        save_cb("tts")
    else:
        print(f"  [RESUME] All {len(shots)} TTS clips present")


def _regenerate_shot_list_for_resume(state: dict) -> list:
    """Re-run the shot-list LLM on resume to fill parse-failed/missing shots
    (Joe 2026-08-12). Reuses the stored narration + world context; carries
    forward each existing shot's image/tts by narration_idx so good shots keep
    their generated art and only missing sentences get fresh shots. Returns the
    merged shot list (or the existing one if regeneration isn't possible)."""
    existing = list(state.get("shots") or [])
    narration = list(state.get("narration") or [])
    if not narration:
        print("  [SHOTLIST] no stored narration - use 'Rebuild the narration SCRIPT' instead")
        return existing
    topic = state.get("topic", "")
    context = state.get("context") or {}
    bible = state.get("bible") or {}
    sentence_para_map = state.get("sentence_para_map") or \
        {i: p for i, p in enumerate(narration)}
    establishing_map = state.get("establishing_map") or {}
    # Rebuild world context from the article if it wasn't persisted.
    if (not context or not bible) and state.get("article_url"):
        try:
            paragraphs = fetch_article_paragraphs(state["article_url"])
            if paragraphs and not context:
                context = _build_episode_context(topic, paragraphs)
            if not bible:
                bible = _build_directors_bible(topic, narration)
        except Exception as e:
            print(f"  [SHOTLIST] could not rebuild world context: {e}")
    old = {}
    for s in existing:
        i = int(s.get("narration_idx", -1))
        if i >= 0:
            old.setdefault(i, s)
    _shot_bible = dict(bible or {})
    new_shots = _build_shot_list(narration, bible=_shot_bible, context=context,
                                 establishing_map=establishing_map,
                                 sentence_para_map=sentence_para_map)
    carried = 0
    for ns in new_shots:
        i = int(ns.get("narration_idx", -1))
        if i in old:
            o = old[i]
            for k in ("image_path", "tts_path", "is_chapter", "chapter_num",
                      "chapter_title", "is_establishing", "establishing_kind",
                      "is_key", "key_words", "foley"):
                if k in o:
                    ns[k] = o[k]
            carried += 1
    print(f"  [SHOTLIST] regenerated {len(new_shots)} shots "
          f"(carried forward {carried} existing image/tts)")
    return new_shots


def _reclaim_orphaned_codex_images(shots: list[dict], ep_shot_dir) -> int:
    """Reclaim codex images that were generated but never claimed (orphans left
    in ~/.codex/generated_images/ when the 'Saved at:' path wasn't parsed in a
    prior run). Joe 2026-08-12: before rendering we must NOT waste them or
    re-spend on regeneration - rescue them into the episode folder first.

    Orphans have no per-shot name, so a blind assignment risks putting the
    WRONG image on a sentence (Joe hates that). To stay correct we only map
    orphans onto missing shots when the count matches EXACTLY - a best-effort
    order match (orphans by mtime, missing by seq). When counts differ we leave
    them alone and let the regeneration path fill the gap instead. Returns the
    number of orphaned images reclaimed."""
    missing = [s for s in shots
               if not s.get("is_chapter")
               and not (s.get("image_path") and os.path.isfile(s["image_path"]))]
    if not missing:
        return 0
    import glob as _glob
    generated = Path.home() / ".codex" / "generated_images"
    orphans: list[str] = []
    if generated.is_dir():
        for p in (_glob.glob(str(generated / "**" / "call_*.png"), recursive=True)
                  + _glob.glob(str(generated / "**" / "ig_*.png"), recursive=True)):
            if os.path.isfile(p) and os.path.getsize(p) > 20000:
                orphans.append(p)
    if not orphans:
        return 0
    if len(orphans) != len(missing):
        print(f"  [PRE-RENDER] {len(orphans)} orphaned codex image(s) but "
              f"{len(missing)} missing shot(s) - count mismatch, cannot safely "
              f"match by order; regenerating the missing shots instead")
        return 0
    orphans.sort(key=lambda p: os.path.getmtime(p))
    missing_sorted = sorted(missing, key=lambda s: int(s.get("seq", 0) or 0))
    reclaimed = 0
    for s, op in zip(missing_sorted, orphans):
        seq = int(s.get("seq", 0) or 0)
        fname = _shot_filename(s, seq)
        dest = str(ep_shot_dir / fname)
        try:
            shutil.copy2(op, dest)
            s["image_path"] = dest
            reclaimed += 1
            print(f"  [PRE-RENDER] reclaimed orphaned codex image -> {fname}")
        except Exception as e:
            print(f"  [PRE-RENDER] reclaim failed {os.path.basename(op)}: {e}")
    return reclaimed


def _retry_realref_before_render(shots: list[dict]) -> int:
    """Retry real-person photo downloads for codex/fal runs just before ffmpeg.

    Joe 2026-08-13: when the internet was off during image generation, every
    person's real photo failed to download and got cached as 'no-real-ref', so
    all shots rendered without a real face. This pass re-runs the download for
    any character that is cached as a failure (and has no usable ref on disk),
    and if a ref now succeeds it flags the affected shots so the shot loop
    below regenerates them with the real face. Returns how many refs were
    freshly obtained."""
    if not shots:
        return 0
    fails = _load_realref_failures()
    if not fails:
        return 0
    # Unique characters that are cached as no-real-ref across the shot list.
    chars: set[str] = set()
    for s in shots:
        for ch in _parse_shot_characters(s):
            n = ch["name"].strip()
            if n and n.lower() in fails:
                chars.add(n)
    if not chars:
        return 0
    got = 0
    for name in sorted(chars):
        # Clear the cached failure and force a fresh search (the photo file
        # may already exist from a later successful run, in which case
        # _find_real_reference just reuses it).
        _clear_realref_failure(name)
        role = next((s.get("character_role", "") for s in shots
                     if any(c["name"].lower() == name.lower()
                            for c in _parse_shot_characters(s))), "")
        ref = _find_real_reference(name, role)
        if ref and os.path.isfile(ref):
            got += 1
            # Flag every shot featuring this person so the shot loop below
            # regenerates them with the real-face ref instead of skipping
            # because an image already exists.
            for s in shots:
                if any(c["name"].lower() == name.lower()
                       for c in _parse_shot_characters(s)):
                    s["_force_regen_realref"] = True
            print(f"  [REALREF] retry ok: {name} -> {os.path.basename(ref)} "
                  f"(shots flagged for regen)")
        else:
            print(f"  [REALREF] retry still failed: {name}")
    return got


def _regen_missing_images_before_render(episode_num: int, shots: list[dict],
                                        character_sheets: dict, topic: str,
                                        brand_assets: Optional[dict] = None) -> tuple:
    """PRE-RENDER image validation pass (Joe 2026-08-12).

    Runs right before FFmpeg render. Any shot (or chapter card) whose image
    file is missing or invalid on disk - e.g. Joe deleted it because he didn't
    like it - is regenerated in realtime here, using the SAME codex/API path
    as the normal image phase. This means a manual pass over the script after
    deleting bad frames self-heals: the video never renders a deleted/broken
    frame, and only the deleted shots cost a regeneration.

    Also persists the updated shot list back into the episode's resume state so
    a crash after this pass doesn't lose the regenerations.

    Returns (regenerated, still_missing). When still_missing > 0 the caller
    MUST NOT render (Joe 2026-08-12): only proceed to ffmpeg if every shot
    image is intact.
    """
    brand_assets = brand_assets or _scan_brand_assets()
    ep_shot_dir = _episode_dir(episode_num)
    regen = 0
    missing = 0

    # Chapter cards first (they're sequential + anchor the chapter burn).
    for s in shots:
        if not s.get("is_chapter"):
            continue
        if _reconcile_chapter_card(s, episode_num):
            continue
        print(f"  [PRE-RENDER] regenerating chapter card {s.get('chapter_num')}...")
        card = _generate_chapter_card(s, episode_num, topic, shots=shots,
                                      brand_assets=brand_assets,
                                      character_sheets=character_sheets)
        if card:
            s["image_path"] = card
            regen += 1
            print(f"  [PRE-RENDER] card ok -> {os.path.basename(card)}")
        else:
            missing += 1
            print(f"  [PRE-RENDER] card FAILED - black placeholder")

    # Reclaim generated-but-unclaimed codex images before regenerating anything,
    # so valid orphaned PNGs are rescued instead of re-spent (Joe 2026-08-12).
    try:
        _reclaimed = _reclaim_orphaned_codex_images(shots, ep_shot_dir)
        if _reclaimed:
            print(f"  [PRE-RENDER] reclaimed {_reclaimed} orphaned codex image(s)")
    except Exception as _re:
        print(f"  [PRE-RENDER] orphan reclaim skipped: {_re}")

    # REAL-PERSON PHOTO RETRY (Joe 2026-08-13): if the codex/fal backend uses
    # real photo refs and the internet was off when images were generated, every
    # shot rendered without its person's real face (cached as no-real-ref).
    # Retry the downloads here BEFORE ffmpeg; any that now succeed force the
    # affected shots to regenerate so the final video has the real faces.
    if _active_image_backend() in ("codex", "fal"):
        _retried = _retry_realref_before_render(shots)
        if _retried:
            print(f"  [PRE-RENDER] retried {_retried} real-person photo ref(s)")

    # Shot images.
    for idx, s in enumerate(shots):
        if s.get("is_chapter"):
            continue
        p = s.get("image_path") or ""
        if p and os.path.isfile(p) and not s.get("_force_regen_realref"):
            continue
        seq = int(s.get("seq", 0) or (s.get("narration_idx", idx) + 1))
        fname = _shot_filename(s, seq)
        print(f"  [PRE-RENDER] regenerating missing shot seq {s.get('seq')} "
              f"(nidx {s.get('narration_idx')}) -> {fname}")
        seed = s.get("seed") or (10000 + random.randint(0, 999))
        prompt = _build_shot_prompt(s, character_sheets) + " " + _style_inject()
        try:
            prompt = _ensure_shot_prompt_relevant(prompt, s, character_sheets, None, topic)
        except Exception:
            pass
        refs, _notes = _select_shot_refs(s, {}, brand_assets, llm_refs=s.get("_llm_refs"))
        out_path = str(ep_shot_dir / fname)
        n = len(refs)
        kwargs = {}
        if n:
            kwargs = {"ref_mode": "identity",
                      "ref_boost": (4.0 if n == 1 else 2.5),
                      "grounding_px": (768 if n == 1 else 1024),
                      "negative_prompt": (NO_DUPLICATE_NEGATIVE if n == 1 else "")}
        ok = _krea_generate(prompt, seed, out_path,
                            ref_images=refs if n else None,
                            denoise=1.0, upscale=True, **kwargs)
        if not ok:
            print("  [PRE-RENDER] retrying with new seed...")
            ok = _krea_generate(prompt, seed + 31337, out_path,
                                ref_images=refs if n else None,
                                denoise=1.0, upscale=True, **kwargs)
        s["seed"] = seed
        if ok:
            s["image_path"] = out_path
            regen += 1
            print(f"  [PRE-RENDER] ok -> {fname}")
        else:
            missing += 1
            print(f"  [PRE-RENDER] FAILED -> {fname} (will render fallback)")

    # Persist updated shots back into the episode's resume state (preserves all
    # other fields by reloading + swapping in the in-memory shot list).
    try:
        rf = _resume_file_for(episode_num)
        if rf.exists():
            st = json.loads(rf.read_text(encoding="utf-8"))
            st["shots"] = shots
            rf.write_text(json.dumps(st, indent=2, default=str), encoding="utf-8")
            print("  [PRE-RENDER] resume state updated with regenerated shots")
    except Exception as e:
        print(f"  [PRE-RENDER] state persist skipped: {e}")

    try:
        import providers
        providers.flush_upscales()
    except Exception:
        pass

    if regen or missing:
        print(f"  [PRE-RENDER] regenerated {regen}, still missing {missing}")
    else:
        print("  [PRE-RENDER] all shot images present")
    return regen, missing


def _regenerate_key_words(shots: list[dict], episode_num: int) -> bool:
    """Re-run the key-word LLM extraction on the EXISTING key sentences and
    update each key shot's key_words (now a CONTIGUOUS in-order phrase). Does
    NOT change which shots are key or their foley. Joe 2026-08-16."""
    key_shots = [s for s in shots
                 if s.get("is_key") and (s.get("narration") or "").strip()]
    if not key_shots:
        print("  [KEYWORDS] no key sentences to regenerate - skipping")
        return False
    sys_p = ("You pick the punch words for an on-screen highlight. I give you ONE "
             "sentence. Return JSON {\"key_words\": [...]} with 2-3 words that form "
             "a phrase that is an EXACT contiguous substring of the sentence - words "
             "that appear NEXT TO EACH OTHER, IN ORDER (not 3 random words). They "
             "are the words a viewer's eye should land on. Use the words exactly as "
             "written, no stemming, no rephrasing.")
    updated = 0
    for shot in key_shots:
        s = shot.get("narration") or ""
        try:
            data = _llm_json([{"role": "system", "content": sys_p},
                              {"role": "user", "content":
                               f"SENTENCE:\n{s}\n\nReturn the key_words JSON."}],
                             max_tokens=120, temp=0.3)
            raw = data.get("key_words") if isinstance(data, dict) else None
            kw = _sanitize_key_words(s, raw)
            if kw:
                shot["key_words"] = kw
                updated += 1
        except Exception:
            continue
        time.sleep(0.1)
    print(f"  [KEYWORDS] regenerated key-words for {updated}/{len(key_shots)} "
          f"key sentences (contiguous, in order)")
    return updated > 0


def _resume_episode(state: dict) -> None:
    """Resume a partially-completed episode from saved state.

    Only regenerates what's missing: images, TTS, render clips (batch_temp),
    and picks up from the last unfinished stage. Never re-uploads a video
    that already has a video_id.
    """
    episode_num = int(state.get("episode_num", 0))
    stage = state.get("stage", "story")
    topic = state.get("topic", "")
    article_url = state.get("article_url", "")
    target_paras = int(state.get("target_paras", 0) or TARGET_NARRATION_PARAS)
    shots = state.get("shots", [])
    character_sheets = state.get("character_sheets", {})
    location_sheets = state.get("location_sheets", {})
    prop_assets = state.get("prop_assets", {})
    brand_assets = _scan_brand_assets()
    titles = state.get("titles", [])
    description = state.get("description", "")
    tags = state.get("tags", [])
    thumb_path = state.get("thumb_path", "")
    video_path = state.get("video_path", "")
    video_id = state.get("video_id", "")
    chapter_events = state.get("chapter_events", [])
    anchor_events = state.get("anchor_events", [])

    print(f"\n{'='*60}")
    print(f"  RESUME - Split Node Episode #{episode_num:03d}")
    print(f"  Stage: {stage} | Shots: {len(shots)}")
    print(f"  Paragraph target: {target_paras} (sticking with the job-start count)")
    print(f"{'='*60}\n")

    # ---- Interactive resume options --------------------------------------
    # Let the user decide what to rebuild on resume instead of silently only
    # filling the gaps. SKIP_RESUME_MENU=1 restores the old gap-fill-only flow.
    regen_tts = False
    _wants_img_regen = False
    # Per-shot checkpoint recovery (Joe 2026-08-17): if the previous run died
    # MID shot-list (incomplete marker set), regenerate the missing tail so
    # the partially-generated shots are recovered instead of the episode
    # restarting the whole LLM phase from scratch.
    if _shotlist_incomplete(episode_num) and state.get("narration"):
        print("  [RESUME] previous run died mid-shot-list - regenerating "
              "the missing shots...")
        _new_shots = _regenerate_shot_list_for_resume(state)
        if _new_shots and len(_new_shots) > len(shots):
            shots = _new_shots
            print(f"  [SHOTLIST] recovered partial shot list -> {len(shots)} shots "
                  f"(missing tail regenerated)")
        _clear_shotlist_incomplete(episode_num)
    if not os.environ.get("SKIP_RESUME_MENU"):
        print("  [RESUME] What would you like to rebuild? (enter for No):")
        _regen_script = _yn("    Rebuild the narration SCRIPT from the article? [y/N]: ")
        regen_tts = _yn("    Regenerate ALL TTS clips (re-speak every line)? [y/N]: ")
        _regen_img = _yn("    Regenerate ALL images (overwrite)? [y/N]: ")
        _regen_chapters = _yn("    Regenerate CHAPTER CARD images (overwrite)? [y/N]: ")
        _regen_clips = _yn("    Regenerate ALL video clips (re-render from images)? [y/N]: ")
        _swap_model = _yn("    Swap the image-gen model (backend/model)? [y/N]: ")
        _regen_shotlist = _yn("    Regenerate the SHOT LIST (re-run shot-list LLM to fill parse-failed/missing shots)? [y/N]: ")
        _regen_keywords = _yn("    Regenerate key-words from existing narration? [y/N]: ")
        _regen_bible = _yn("    Regenerate STORY BIBLE (character detection, rebuilds sheets/refs)? [y/N]: ")
        if _regen_clips:
            os.environ["REGEN_CLIPS"] = "1"
            print("  [RESUME] Regenerating ALL video clips (reuse disabled)")
        if _regen_shotlist:
            _new_shots = _regenerate_shot_list_for_resume(state)
            if _new_shots and _new_shots != shots:
                shots = _new_shots
                # Missing sentences get fresh shots -> their images/TTS are absent,
                # so the gap-fill phases generate them. Carried-forward shots keep
                # their existing image/tts. No forced full regen.
                print(f"  [SHOTLIST] shot list regenerated -> {len(shots)} shots "
                      f"(missing images/TTS will gap-fill)")
            elif not _new_shots:
                print("  [SHOTLIST] regeneration produced no shots - keeping existing")
        if _regen_script:
            rebuilt = _rebuild_script_for_resume(state)
            if rebuilt:
                shots = rebuilt["shots"]
                character_sheets = rebuilt["character_sheets"]
                location_sheets = rebuilt["location_sheets"]
                prop_assets = rebuilt["prop_assets"]
                chapter_events = rebuilt["chapter_events"]
                anchor_events = rebuilt["anchor_events"]
                topic = rebuilt["topic"]
                article_url = rebuilt["article_url"]
                target_paras = rebuilt["target_paras"]
                # New narration means every line + every image must be re-done,
                # and the video clips embed that audio - so they must re-render
                # too (a reused clip would carry the OLD spoken line).
                regen_tts = True
                os.environ["REGEN_IMAGES"] = "1"
                os.environ["REGEN_CLIPS"] = "1"
                _wants_img_regen = True
                # Titles/description/tags derive from the script - reset them.
                titles, description, tags = [], "", []
                print("  [RESUME] Script rebuilt -> forcing image + TTS regeneration")
            else:
                print("  [RESUME] Script rebuild failed - continuing with existing script")
        if _regen_keywords:
            _regenerate_key_words(shots, episode_num)
            # Keyword highlights are baked into the single-pass render, so clear
            # the video path to force a re-render (audio mix/whisper are reused).
            video_path = ""
            os.environ["REGEN_CLIPS"] = "1"
            print("  [RESUME] Key-words regenerated from existing narration -> "
                  "video will re-render to bake the new highlights")
        if _regen_bible:
            # Re-run character detection from the article (re-fetched) or the
            # saved narration, then rebuild the character sheets so a character
            # the bible missed is finally locked in. No full script rebuild -
            # narration, shots and TTS stay untouched. (Joe 2026-08-17)
            _bible_src = None
            if article_url:
                try:
                    _bible_src = fetch_article_paragraphs(article_url)
                except Exception as _fe:
                    print(f"  [BIBLE] article re-fetch failed ({_fe}) - using saved narration")
            if not _bible_src:
                _bible_src = state.get("narration") or [
                    s.get("narration", "") for s in shots if s.get("narration")]
            if not _bible_src:
                print("  [BIBLE] no narration/article to detect characters from - "
                      "cannot regenerate the story bible")
            else:
                _rebuilt_bible = _build_story_bible(topic, list(_bible_src))
                _resume_bible = _rebuilt_bible
                character_sheets = _build_character_sheets(
                    shots, state.get("narration")
                    or [s.get("narration", "") for s in shots],
                    bible=_rebuilt_bible)
                _wants_img_regen = True
                os.environ["REGEN_IMAGES"] = "1"
                os.environ["REGEN_CLIPS"] = "1"  # clips embed the image - must re-render
                print(f"  [BIBLE] story bible regenerated -> "
                      f"{len(_rebuilt_bible.get('characters') or [])} character(s), "
                      f"{len(character_sheets)} sheet def(s) -> forcing image regeneration")
        if _swap_model:
            _ask_image_model_swap()
            os.environ["REGEN_IMAGES"] = "1"
            os.environ["REGEN_CLIPS"] = "1"  # clips embed the image - must re-render
            _wants_img_regen = True
            print("  [RESUME] Model changed -> forcing image regeneration")
        if _regen_img:
            os.environ["REGEN_IMAGES"] = "1"
            os.environ["REGEN_CLIPS"] = "1"  # clips embed the image - must re-render
            _wants_img_regen = True
        if _regen_chapters:
            os.environ["REGEN_CHAPTERS"] = "1"
            print("  [RESUME] Regenerating CHAPTER CARD images (REGEN_CHAPTERS=1)")
        if _regen_script or regen_tts or _regen_img or _regen_chapters or _swap_model:
            print("  [RESUME] Applying regeneration options...\n")
    else:
        print("  [RESUME] SKIP_RESUME_MENU=1 - gap-fill only\n")
    # ---- End interactive resume options ----------------------------------

    # Restore the episode's image backend (Joe 2026-08-09): the resume state
    # stores which backend (codex/local/fal/runpod) generated the episode, so a
    # resumed run uses the SAME backend - NOT defaulting to local/ComfyUI and
    # then stalling on a missing ComfyUI server. The user's explicit backend
    # choice via the swap-model menu (which sets IMAGE_BACKEND env) wins over
    # the stored value. No stored value (older state) = keep the env/default.
    _stored_backend = str(state.get("img_backend") or "").strip().lower()
    if not _stored_backend and not os.environ.get("IMAGE_BACKEND"):
        # Old-state fallback (Joe 2026-08-09): episodes generated on codex/fal
        # render REAL chapter-card image files (chapter_XX_card.png); the local
        # Krea backend uses black placeholder cards instead. So if real chapter
        # cards exist on disk, this episode was generated on codex/fal and must
        # resume on that backend (skip panels, use real-person refs) - NOT
        # default to local/ComfyUI and stall on a missing server.
        ep_shot_dir0 = _episode_dir(int(episode_num))
        _real_cards = list(ep_shot_dir0.glob("chapter_*.png")) \
            if ep_shot_dir0.is_dir() else []
        _real_cards = [c for c in _real_cards
                       if os.path.getsize(str(c)) > 2000]  # real image, not placeholder
        if _real_cards:
            _stored_backend = "codex"  # infer the cloud card backend
            print(f"  [RESUME] detected {len(_real_cards)} real chapter-card "
                  f"image(s) -> resuming on codex backend (no ComfyUI needed)")
    if _stored_backend and not os.environ.get("IMAGE_BACKEND"):
        os.environ["IMAGE_BACKEND"] = _stored_backend
        print(f"  [RESUME] Image backend -> {_stored_backend} (from episode state)")

    # Resume keeps the exact style the episode was generated with (unless the
    # user overrides with STYLE=<profile>) OR picks a new style interactively.
    if state.get("style"):
        global _RESUME_STYLE
        _RESUME_STYLE = state.get("style")
    # If the user didn't force a style via env, ask which style to use for the
    # resumed images. Picking a style DIFFERENT from the resume style only forces
    # a full re-render of EXISTING shots if the user ALSO opted to regenerate
    # images (_wants_img_regen) - a style change alone must NOT nuke already-made
    # shots, or resume would never pick up pre-existing images (Joe 2026-08-16).
    # If they kept images, the new style simply applies to any genuinely-missing
    # shots that still need generating.
    if not (os.environ.get("STYLE") or os.environ.get("STYLE_PROFILE")):
        _cur = _active_style_name()
        _chosen = _ask_style_selection(_cur)
        if _chosen and _chosen.lower() != _cur.lower():
            if _wants_img_regen:
                print(f"  [STYLE] changed {_cur or 'default'} -> {_chosen} - "
                      f"forcing full re-generate so the new look applies")
                os.environ["REGEN_IMAGES"] = "1"
                os.environ["REGEN_CLIPS"] = "1"  # clips embed the image - must re-render
            else:
                print(f"  [STYLE] changed {_cur or 'default'} -> {_chosen} - "
                      f"keeping existing shots (new look applies to any missing ones)")
        if _chosen:
            os.environ["STYLE"] = _chosen
    # Ask the user for the output resolution on resume too (Joe 2026-08-09):
    # defaults to 1440p but offers 1080p/4K, so a resumed run can change the
    # upscale/video target. RESOLUTION env var overrides the prompt.
    if not os.environ.get("RESOLUTION"):
        _chosen_res = _ask_resolution()
        os.environ["RESOLUTION"] = _chosen_res
        print(f"  [RESUME] Output resolution -> {_chosen_res.upper()}")

    def _save(stg):
        _save_resume_state(stg, episode_num, article_url, topic, shots,
                           character_sheets, titles, description, tags,
                           thumb_path, video_path, video_id,
                           chapter_events, anchor_events,
                           location_sheets, prop_assets,
                           target_paras=target_paras,
                           narration=state.get("narration") or [],
                           context=state.get("context") or {},
                           bible=_resume_bible,
                           sentence_para_map=state.get("sentence_para_map") or {},
                           establishing_map=state.get("establishing_map") or {},
                           intro_count=int(state.get("intro_count", 0) or 0))

    # 0a. Restore the story bible (Joe 2026-08-17): carry the locked character
    #     roster through resume saves so character sheets/refs are never lost.
    #     If the saved bible is empty (old-state / LLM miss), rebuild sheets
    #     from the narration so image gen still has identity refs.
    _resume_bible = state.get("bible") or {}

    # 0b. Rebuild character sheets if the crash-window checkpoint left them
    #     empty (shot list saved, sheets not yet built) so image gen still
    #     has identity refs for every character (Joe 2026-08-17). Falls back
    #     to per-shot narration when the state's narration list is missing
    #     (an old _save dropped it - Joe 2026-08-17).
    if not character_sheets and shots:
        _sheet_narr = state.get("narration") or [
            s.get("narration", "") for s in shots if s.get("narration")]
        if _sheet_narr:
            character_sheets = _build_character_sheets(
                shots, _sheet_narr, bible=_resume_bible)
            print(f"  [RESUME] rebuilt {len(character_sheets)} character sheet(s) "
                  f"from the checkpoint (they were not saved yet)")
            _save("story")

    # 0. TTS GAP-FILL FIRST (Joe 2026-08-09): generate any missing narration
    #    clips BEFORE image generation, so images are never rendered against
    #    audio that doesn't exist yet. Reuses clips already on disk.
    _resume_tts_gap_fill(shots, episode_num, regen_tts, _save,
                         intro_count=int(state.get("intro_count", 0) or 0))

    # 1. Images: regenerate only the missing ones (same seeds -> same look),
    #    or ALL of them when REGEN_IMAGES=1 (a style change forces this so the
    #    new look applies to every shot).
    ep_shot_dir = _episode_dir(episode_num)
    _force_regen = os.environ.get("REGEN_IMAGES", "0").strip().lower() in ("1", "yes", "y", "true")
    if _force_regen:
        missing_img = [s for s in shots if not s.get("is_chapter")]
        print(f"\n[IMAGES] REGEN - re-generating ALL {len(missing_img)} shots (overwrite)")
    else:
        # Check the episode folder PROPERLY (Joe 2026-08-16): reconcile each
        # shot against its deterministic on-disk filename so a genuinely
        # generated image is adopted (even if the stored path is stale/missing)
        # and only shots with no valid image on disk are treated as missing.
        missing_img = []
        for _s in shots:
            if _s.get("is_chapter"):
                continue
            if _reconcile_shot_image(_s, episode_num):
                continue
            missing_img.append(_s)
    # Chapter title cards (codex/fal): generate any missing card images on
    # resume too, so a mid-run crash doesn't leave a chapter on a black card.
    # Chapter-card regen is controlled ONLY by REGEN_CHAPTERS (Joe 2026-08-16) -
    # REGEN_IMAGES (a style-change shot regen) must NOT cascade into cards. The
    # stored image_path is reconciled against the deterministic chapter_XX_slug.png
    # on disk so an already-generated card is picked up.
    _regen_chapters = os.environ.get("REGEN_CHAPTERS", "").strip().lower() in ("1", "yes", "y", "true")
    _chap_missing = [s for s in shots
                     if s.get("is_chapter")
                     and _active_image_backend() in ("codex", "fal")
                     and not (_reconcile_chapter_card(s, episode_num) and not _regen_chapters)]
    if _chap_missing:
        _cn2 = _image_concurrency()
        print(f"\n[IMAGES] Generating {len(_chap_missing)} missing chapter title cards "
              f"in PARALLEL ({_cn2} workers, deterministic filenames)...")
        def _rcard(_cs):
            _card = _generate_chapter_card(_cs, episode_num, topic,
                                           shots=shots, brand_assets=brand_assets,
                                           character_sheets=character_sheets)
            if _card:
                _cs["image_path"] = _card
            return (f"  [CARD] chapter {_cs.get('chapter_num')}: "
                    f"{'OK' if _card else 'black placeholder'}")
        if _cn2 > 1 and len(_chap_missing) > 1:
            with ThreadPoolExecutor(max_workers=_cn2) as _ex2:
                for _msg2 in _ex2.map(_rcard, _chap_missing):
                    print(_msg2)
        else:
            for _cs2 in _chap_missing:
                print(_rcard(_cs2))
    if missing_img:
        print(f"\n[IMAGES] Regenerating {len(missing_img)} missing shots...")
        # ---- Rebuild the episode world assets the fresh run never finished ----
        # Character sheets live in state as DEFS; the sheet IMAGES, location
        # sheets and prop assets are generated by the fresh path and can be
        # missing after a mid-run crash (ep8: all three were empty). Rebuild
        # anything not on disk so resume shots get the SAME refs as fresh ones.
        sheets_dir = ep_shot_dir / CHAR_SHEETS_DIR_NAME
        sheets_dir.mkdir(parents=True, exist_ok=True)
        sheets_cache: dict[str, dict] = {}   # char -> {view: panel path}
        face_lock = os.environ.get("FACE_LOCK", "1") != "0"
        brand_assets = _scan_brand_assets()
        # ---- PANELS FIRST (dedicated pass) ----
        # Generate EVERY character's six identity panels up front, before any
        # shot renders. A face-panel failure is retried here and resolved here,
        # so it can't cascade into every shot missing a face (a lazy in-loop
        # build would leave sheets empty across all shots on a hiccup).
        # CODE-X (Joe 2026-08-09): skip panel generation on resume too - codex
        # shots use each person's REAL photo directly as the identity ref, so
        # panels are wasted work (and can leak into codex output detection).
        if face_lock and _active_image_backend() != "codex":
            sheets_cache = _build_all_character_sheets(
                missing_img, character_sheets, sheets_dir, 70000 + episode_num,
                sheets_cache=sheets_cache)
        elif face_lock:
            print("  [SHEET] codex backend: using REAL-PERSON photo refs, "
                  "skipping generated character panels (resume)")
        # ---- Smart shot regen (matches the fresh loop, PARALLEL on cloud/codex) ----
        # Each character's SIX individual 1280x1280 panels are built once and
        # _select_shot_refs picks the PERFECT panel(s) per shot (framing,
        # facing, mirrored sides, multi-person, business logo). Style is
        # prompt-injected; no style-plate refs. Shots are independent, so on
        # codex/fal/runpod they render in PARALLEL (IMAGE_CONCURRENCY) exactly
        # like the fresh path (Joe 2026-08-09).
        _re_iter = (tqdm(missing_img, desc="  [IMAGES] regenerating missing",
                         unit="shot", leave=False)
                    if _HAS_PROGRESS else missing_img)
        _plock = threading.Lock()

        def _regen_one(idx: int, shot: dict) -> None:
            if _HAS_PROGRESS:
                with _plock:
                    _re_iter.set_description(
                        f"  [IMAGES] regenerating {idx+1}/{len(missing_img)}")
            chars = _parse_shot_characters(shot)
            seed = shot.get("seed") or (10000 + random.randint(0, 999))
            # Reuse the pre-verified prompt when available (Joe 2026-08-09).
            prompt = shot.get("_verified_prompt")
            if not prompt:
                prompt = (_build_shot_prompt(shot, character_sheets)
                          + " " + _style_inject())
                # LLM relevance gate (Joe 2026-08-09): cross-check the prompt against
                # the article topic; rewrite the scene + rebuild if it drifted off-story.
                prompt = _ensure_shot_prompt_relevant(prompt, shot, character_sheets, _plock, topic)
            if face_lock and _active_image_backend() != "codex":
                # Panels were built up front by _build_all_character_sheets -
                # just confirm every char in this shot is present.
                for ch in chars:
                    if ch["name"] not in sheets_cache:
                        print(f"  [SHEET] {ch['name']} not in pre-built cache "
                              f"(face panel had failed) - shot renders w/o face ref")
            refs, notes = _select_shot_refs(shot, sheets_cache, brand_assets,
                                            llm_refs=shot.get("_llm_refs"))
            out_path = str(ep_shot_dir
                           / _shot_filename(shot, int(shot.get("seq", 0) or (shot.get("narration_idx", idx) + 1))))
            n = len(refs)
            if refs:
                # single ref -> tight identity boost; multiple refs -> lower
                # boost so the char/logo panels don't bleed into each other.
                boost = 4.0 if n == 1 else 2.5
                g_px = 768 if n == 1 else 1024
                np = NO_DUPLICATE_NEGATIVE if n == 1 else ""
                ok = _krea_generate(prompt, seed, out_path,
                                    ref_images=refs, denoise=1.0,
                                    ref_mode="identity", ref_boost=boost,
                                    grounding_px=g_px, upscale=True,
                                    negative_prompt=np)
            else:
                ok = _krea_generate(prompt, seed, out_path,
                                    ref_images=None, denoise=1.0, upscale=True)
            if not ok:
                seed2 = seed + 31337
                out2 = out_path  # same descriptive filename (overwrite)
                with _plock:
                    print("  [SHOT] retrying with new seed...")
                if refs:
                    ok = _krea_generate(prompt, seed2, out2,
                                        ref_images=refs, denoise=1.0,
                                        ref_mode="identity", ref_boost=boost,
                                        grounding_px=g_px, upscale=True,
                                        negative_prompt=np)
                else:
                    ok = _krea_generate(prompt, seed2, out2,
                                        ref_images=None, denoise=1.0, upscale=True)
                if ok:
                    seed, out_path = seed2, out2
            shot["seed"] = seed
            shot["image_path"] = out_path if ok else None
            label = notes if notes else "txt2img (no refs)"
            with _plock:
                print(f"  [SHOT] {'image ready' if ok else 'IMAGE FAILED - fallback'} "
                      f"-> refs: {label} | {os.path.basename(out_path)} ({out_path})")
                time.sleep(1)
            if _HAS_PROGRESS:
                with _plock:
                    _re_iter.update(1)

        # ---- PIPELINED CHUNKED PRE-VERIFY + REGEN (resume, Joe 2026-08-09) ----
        # Process shots in chunks of SHOT_CHUNK_SIZE (default 5). The LLM
        # verifies + ref-checks a chunk (the go-ahead), then that chunk renders
        # in PARALLEL while a background thread LLM-verifies the NEXT chunk
        # (overlap), so the LLM is never idle and we never stall pre-verifying
        # ALL shots up front. Never blocks on more than one chunk's LLM calls.
        _rn = _image_concurrency()
        _RCHUNK = max(1, min(int(os.environ.get("SHOT_CHUNK_SIZE", "5")),
                             len(missing_img) or 1))

        def _verify_chunk(chunk: list) -> int:
            rewrites = 0
            for _vs in chunk:
                _base = _build_shot_prompt(_vs, character_sheets) + " " + _style_inject(allow_logo=_is_business_shot(_vs))
                _vp = _base
                if _SHOT_RELEVANCE_ON and topic:
                    _vp = _ensure_shot_prompt_relevant(_base, _vs, character_sheets, None, topic)
                    if _vp != _base:
                        rewrites += 1
                _vs["_verified_prompt"] = _vp
                _vs["_llm_refs"] = _llm_shot_ref_check(_vs, brand_assets, topic)
            return rewrites

        def _render_chunk(cstart: int, chunk: list) -> None:
            _rlabels = ", ".join(str(s.get("narration_idx", 0) + 1) for s in chunk)
            print(f"  [CHUNK {cstart//_RCHUNK + 1}/{max(1,(len(missing_img)+_RCHUNK-1)//_RCHUNK)}] "
                  f"rendering {len(chunk)} (shots {_rlabels}) - "
                  f"firing in parallel ({min(_rn, len(chunk))} workers)...")
            if _rn > 1 and len(chunk) > 1:
                with ThreadPoolExecutor(max_workers=_rn) as _ex3:
                    list(_ex3.map(_regen_one, range(cstart, cstart + len(chunk)), chunk))
            else:
                for _i, _sh in enumerate(chunk):
                    _regen_one(cstart + _i, _sh)

        from concurrent.futures import ThreadPoolExecutor as _TPE
        _chunks = [missing_img[i:i + _RCHUNK] for i in range(0, len(missing_img), _RCHUNK)]
        # Pipeline: verify chunk 0 up front, then verify each LATER chunk in the
        # background WHILE an earlier chunk renders (codex generation overlaps
        # both the LLM verify AND the async upscale queue, so nothing serializes).
        # We pre-submit chunk 1 and chunk 2, and at each iteration submit the
        # chunk TWO ahead - so a chunk's verify has a full extra chunk-render to
        # finish before that chunk renders. It is ALWAYS ready, so _regen_one
        # never falls back to inline LLM calls (which hammered LM Studio and
        # looked like a stall after the first batch). Joe 2026-08-16.
        _rw0 = _verify_chunk(_chunks[0])
        if _rw0:
            print(f"  [CHUNK 1] {_rw0} scene rewrites applied")
        _pending: dict = {}
        for _k in range(1, min(3, len(_chunks))):   # pre-submit chunks 1 and 2
            _pending[_k] = _TPE(max_workers=1).submit(_verify_chunk, _chunks[_k])
        for _ci, _chunk in enumerate(_chunks):
            _cstart = _ci * _RCHUNK
            # Chunk 0 is verified (sync above); later chunks' verify was
            # submitted 1-2 renders ago and is done - pop + surface rewrites.
            if _ci in _pending:
                _rw = _pending.pop(_ci).result()
                if _rw:
                    print(f"  [CHUNK {_ci + 1}] {_rw} scene rewrites applied")
            # Kick off verification of the chunk TWO ahead so it has this render
            # plus the next to complete (overlap, never idles the LLM).
            if _ci + 2 < len(_chunks) and (_ci + 2) not in _pending:
                _pending[_ci + 2] = _TPE(max_workers=1).submit(
                    _verify_chunk, _chunks[_ci + 2])
            # Render the CURRENT chunk (its prompts are verified) in the main
            # thread, in parallel with the background next-verify. API backends
            # enqueue upscales ASYNC (providers.enqueue_upscale), so codex fires
            # back-to-back while the upscaler catches up in the background - the
            # generation/upscale overlap Joe wanted. Local (ComfyUI) upscales
            # inside the workflow, so it's naturally serial.
            _render_chunk(_cstart, _chunk)
        # Join any still-running background verify so no thread is left dangling
        # and their prompt-cache writes land before we drop the cache below.
        for _f in _pending.values():
            try:
                _f.result()
            except Exception:
                pass
        # Drain the async upscale queue so every regen shot is at the final
        # resolution before the next stage consumes them (Joe 2026-08-09).
        try:
            import providers
            providers.flush_upscales()
        except Exception:
            pass
        # Drop the pre-verify prompt cache so it doesn't bloat resume state.
        for _sh in missing_img:
            _sh.pop("_verified_prompt", None)
            _sh.pop("_llm_refs", None)
        _save("images")
    else:
        print(f"  [RESUME] All {len(shots)} images present")

    # 3. Title pass: whisper the voice track, resolve exact title times
    #    (chapter cards + location/timeline/person anchors). Runs before the
    #    render so the typewriter/glitch/shutter SFX land at whisper-matched
    #    times.
    title_events = []
    person_events = []
    if shots:
        clip_starts0 = _compute_clip_starts(shots)
        person_events = _build_person_events(shots, clip_starts0)
    if (chapter_events or anchor_events or person_events):
        print("\n[STT] Title pass: whisper timing + event resolution...")
        voice = _ensure_voice_track(shots, episode_num)
        words = _transcribe_voice(episode_num, voice)
        clip_starts = _compute_clip_starts(shots)
        title_events = _build_resolved_title_events(
            chapter_events, anchor_events + person_events, words, clip_starts)
        # Establishing shots render clean - merge their FFmpeg '/// NAME' labels
        # so every establishing frame gets exactly one burned label (Joe 2026-08-09).
        title_events = _merge_establishing_titles(
            title_events, _build_establishing_events(shots, clip_starts))
        # DETERMINISTIC chapter times (Joe 2026-08-10): use the exact chapter
        # sentence window so video burn + description markers both use reliable
        # times (whisper can mis-hear a chapter number).
        _det_chaps = _deterministic_chapter_events(shots, clip_starts, chapter_events)
        if _det_chaps:
            title_events = _det_chaps + [ev for ev in title_events
                                         if ev.get("kind") != "chapter"]
        for ev in title_events:
            print(f"    [{ev['kind']}] @{ev['start']:.2f}s '{ev.get('text', ev.get('title', ''))}'")

    # 4. Video render - single pass (finished mix reused, then one encode)
    if video_path and os.path.isfile(video_path) and os.path.getsize(video_path) > 1000:
        print(f"  [RESUME] Video exists, skipping: {video_path}")
    else:
        print("\n[PRE-RENDER] Checking all shot images before rendering...")
        _regen, _still = _regen_missing_images_before_render(
            episode_num, shots, character_sheets, topic)
        if _still:
            print(f"  [HALT] {_still} shot image(s) still missing - NOT "
                  f"rendering until every frame is intact. Fix/regenerate the "
                  f"missing images, then resume.")
            _save("video")
            return
        print("\n[VIDEO] Rendering (single pass)...")
        video_path = _render_video(shots, episode_num, title_events)
        if not video_path:
            print("  [HALT] Video render failed - state kept for another resume.")
            _save("video")
            return
        _save("video")
        egg_report = _easter_egg_report(shots)
        if egg_report:
            print(f"\n  {egg_report}")

    # 4. Titles / description / tags (stored, or regenerated once)
    if not titles:
        print("\n[TITLES] Generating...")
        titles = _generate_titles(topic, episode_num)
        for i, t in enumerate(titles):
            print(f"  Title {i+1}: {t}")
    if not description:
        description = _generate_description(topic, episode_num, article_url)
        description = _append_chapters_to_description(description, title_events)
    if not tags:
        llm_tags = _generate_tags(topic, episode_num)
        tags = YOUTUBE_BASE_TAGS + [t for t in llm_tags if t not in YOUTUBE_BASE_TAGS]
    tags_str = ",".join(tags)

    # 5. Thumbnail
    if not thumb_path:
        thumb_path = str(_ep_thumb_dir(episode_num) / "thumbnail.png")
    thumb_ok = os.path.isfile(thumb_path) and os.path.getsize(thumb_path) > 1000
    if not thumb_ok:
        thumb_ok = _generate_thumbnail(topic, thumb_path)

    # 6. Upload (skip if already uploaded this episode)
    print(f"\n  {'='*50}\n  YOUTUBE UPLOAD ({CHANNEL_NAME})\n  {'='*50}")
    print(f"  Video: {video_path}")
    if video_id:
        print(f"  [RESUME] Already uploaded: https://youtu.be/{video_id}")
    elif YOUTUBE_UPLOAD_ENABLED:
        title = titles[0] if titles else f"{topic[:60]}"
        print(f"  Title: {title}")
        video_id = _upload_video_with_progress(video_path, title, description, tags_str)
        if video_id and thumb_ok:
            _upload_thumbnail(video_id, thumb_path)
        if video_id:
            _add_video_to_playlist(video_id)
            EPISODE_COUNTER_FILE.write_text(str(episode_num))
            print(f"  [OK] Episode #{episode_num:03d} uploaded! https://youtu.be/{video_id}")
            _post_first_comment(video_id, topic)
            _post_discord_announcement(topic, video_id, episode_num, wait_seconds=60,
                                       description=description)
    else:
        print("  [SKIP] YouTube upload disabled")

    egg_report = _easter_egg_report(shots)
    if egg_report:
        print(f"\n  {egg_report}")

    _save("upload")

    print(f"\n  {'='*50}")
    print(f"  EPISODE #{episode_num:03d} COMPLETE (RESUMED)")
    print(f"  {'='*50}")
    if video_id:
        print(f"  YouTube:  https://youtu.be/{video_id}")
    print(f"  Shots: {len(shots)} | Stage: {stage} -> upload")

    _cleanup_stt_artifacts(episode_num)
    _clear_resume_state(episode_num)


def _ask_paragraph_target() -> int:
    """Ask for the DESIRED VIDEO LENGTH in minutes, then work backwards to
    the narration paragraph count.

    Fresh runs ask once; the confirmed count is persisted to resume state so
    a resumed job sticks with the same target (never re-asks). The conversion
    uses the measured narration pace (~14.3s per paragraph incl. pads):
        paragraphs = round(minutes * 60 / 14.3)
    The user can also type a raw number to set paragraphs directly, or enter
    a new minute length to re-estimate.
    """
    minutes = DEFAULT_VIDEO_MINUTES
    n = max(MIN_PARAS, min(round(minutes * 60 / SECONDS_PER_NARRATION_PARA),
                           MAX_PARAS))
    print("\n  Episode length:")
    while True:
        resp = input(f"  Video length in minutes? (enter for {minutes}): ").strip()
        if resp:
            try:
                minutes = float(resp)
                n = max(MIN_PARAS, min(round(minutes * 60 /
                                            SECONDS_PER_NARRATION_PARA),
                                       MAX_PARAS))
            except ValueError:
                print(f"  [LENGTH] '{resp}' isn't a number (minutes)")
                continue
        # estimate + confirm/change loop (typing a number re-estimates)
        while True:
            est = n * SECONDS_PER_NARRATION_PARA
            print(f"  [LENGTH] {minutes:g} min -> {n} narration paragraphs "
                  f"(~{int(est // 60)}m {int(est % 60)}s of narration)")
            resp2 = input("  Confirm? [Y/n] or type a new length in minutes: ").strip().lower()
            if resp2 in ("", "y", "yes"):
                return n
            if resp2 in ("n", "no"):
                break   # back to the length prompt
            try:
                minutes = float(resp2)
                n = max(MIN_PARAS, min(round(minutes * 60 /
                                            SECONDS_PER_NARRATION_PARA),
                                       MAX_PARAS))
            except ValueError:
                continue

def main():
    # ---- CLI flag handlers (kept from the original single-file flow) ----
    if "--setup-discord" in sys.argv:
        try:
            import discord_bot
            sys.exit(0 if discord_bot.setup() else 1)
        except Exception as e:
            print(f"  [DISCORD] setup failed: {e}")
            return
    if "--list-styles" in sys.argv:
        print("Selectable style profiles (STYLE=<name>):")
        list_style_profiles()
        print("\nCustom styles live in style_sheets/custom_styles.json - "
              "add with --add-style <name> \"<descriptor>\".")
        return
    if "--add-style" in sys.argv:
        args = sys.argv[sys.argv.index("--add-style") + 1:]
        if len(args) >= 2:
            add_custom_style(args[0], " ".join(args[1:]))
        else:
            print('Usage: python system_breakers.py --add-style <name> "<style descriptor>"')
        return
    if "--remove-style" in sys.argv:
        i = sys.argv.index("--remove-style")
        if i + 1 < len(sys.argv):
            remove_custom_style(sys.argv[i + 1])
        else:
            print("Usage: python system_breakers.py --remove-style <name>")
        return
    if "--list-easter-eggs" in sys.argv:
        print("Easter eggs (hidden in one shot per episode):")
        list_easter_eggs()
        print("\nCustom eggs live in style_sheets/easter_eggs.json - add with "
              "--add-easter-egg <name> \"<prompt>\". Pick one at run time, or "
              "set EASTER_EGG=<name>.")
        return
    if "--add-easter-egg" in sys.argv:
        args = sys.argv[sys.argv.index("--add-easter-egg") + 1:]
        if len(args) >= 2:
            add_easter_egg(args[0], " ".join(args[1:]))
        else:
            print('Usage: python system_breakers.py --add-easter-egg <name> "<prompt>"')
        return
    if "--remove-easter-egg" in sys.argv:
        i = sys.argv.index("--remove-easter-egg")
        if i + 1 < len(sys.argv):
            remove_easter_egg(sys.argv[i + 1])
        else:
            print("Usage: python system_breakers.py --remove-easter-egg <name>")
        return
    if "--cache-logos" in sys.argv:
        names = [a for a in sys.argv[1:] if not a.startswith("-")]
        if not names:
            print("Known AI orgs: " + ", ".join(AI_ORGS))
            print("Usage: python system_breakers.py --cache-logos OpenAI Claude Tesla")
            return
        for n in names:
            org = next((k for k in AI_ORGS if k.lower() == n.lower()), n)
            p = _find_logo(org)
            print(f"  {org}: {p or 'FAILED (no SERPAPI_API_KEY? see .env)'}")
        return

    # ---- Orchestrator: resume-all scan, then single or fresh batch ----
    print_banner()
    _preflight()

    # Pick the LLM backend + model (LM Studio loaded models, or Codex cheapest).
    _select_llm()

    # Ask which port Stable Audio 3 is running on BEFORE anything else
    # (SA3's Pinokio launcher opens on a different port each run).
    try:
        if os.environ.get("MUSIC_BACKEND", "sa3").strip().lower() == "sa3":
            import sa3_music
            sa3_music.resolve_sa3_port(project="Split Node")
    except Exception as e:
        print(f"  [SA3] port check skipped ({e}) - will fall back if music is needed")

    # 1. Offer to resume EVERY existing resume state (legacy + per-episode).
    states = _scan_resume_states()
    to_resume = []
    if states:
        print(f"\n  [RESUME] Found {len(states)} saved episode(s) in progress:")
        for st in states:
            ep = st.get("episode_num", st.get("_ep", 0))
            stg = st.get("stage", "?")
            resp = input(f"    Resume episode #{ep:03d} (stage '{stg}')? [Y/n]: ").strip().lower()
            if resp not in ("n", "no"):
                to_resume.append(st)
        if to_resume:
            if len(to_resume) == 1:
                print(f"  [RESUME] Resuming {len(to_resume)} episode\n")
            else:
                print(f"  [RESUME] Resuming {len(to_resume)} episodes in sequence\n")
            run_resume_all(to_resume)
            # If resumed episodes fully completed, continue to fresh batch for the rest
            states_after = [s for s in states if s not in to_resume]
            if not _yn("  Start a FRESH batch of new videos as well? [y/N]", default=False):
                _pause()
                return
        else:
            print("  [RESUME] Skipping all saved episodes - starting fresh\n")

    # 1b. Resume a previously-set BATCH (configs persisted in .batch_state.json).
    manifest = _load_batch_manifest()
    if manifest:
        pending = [c for c in manifest["configs"]
                   if not _batch_done(manifest.get("status"), c["episode_num"])]
        if pending:
            print(f"\n  [BATCH] A batch of {len(manifest['configs'])} videos was set "
                  f"({len(pending)} not yet complete).")
            if _yn("    Resume that batch? [Y/n]: ", default=True):
                run_batch_resume(list(manifest["configs"]),
                                 dict(manifest.get("status") or {}))
                if not _yn("    Start a FRESH batch of new videos too? [y/N]: ",
                           default=False):
                    _pause()
                    return
        # Batch fully done or declined -> drop the stale manifest, continue fresh.
        _clear_batch_manifest()

    # 2. Ask how many videos for the fresh batch.
    resp = input(f"\n  How many videos to generate in this batch? (1 for a single video) [1]: ").strip()
    try:
        count = int(resp) if resp else 1
    except ValueError:
        count = 1
    count = max(1, min(count, 50))
    if count == 1:
        print("\n  Single-video mode\n")
    else:
        print(f"\n  BATCH MODE: {count} videos\n")

    # 3. Run the exact setup flow once per video (topic, models, length,
    #    resolution, etc), then process them all.
    last_ep = _load_episode_num()
    default_ep = last_ep + 1
    configs = []
    for i in range(count):
        ep_num = default_ep + i
        print(f"\n{'='*60}\n  VIDEO {i+1}/{count} - SETUP (Episode #{ep_num:03d})\n{'='*60}")
        cfg = _episode_setup(ep_num)
        if cfg is None:
            print("  [SETUP] Skipped this video (no story / aborted).")
            continue
        configs.append(cfg)
        # next video picks up after this episode's number
        default_ep = cfg["episode_num"] + 1

    if not configs:
        print("  [HALT] No videos to generate.")
        _pause()
        return

    if len(configs) == 1:
        run_episode(configs[0])
    else:
        run_fresh_batch(configs)

    print("\n  All done! Press Enter to exit.")
    _pause()


def _apply_config_env(config: dict) -> None:
    os.environ["RESOLUTION"] = str(config.get("resolution", "1080p"))
    os.environ["THUMBNAIL_BACKEND"] = str(config.get("thumb_backend", "codex"))
    if config.get("thumb_model"):
        os.environ["THUMBNAIL_MODEL"] = str(config["thumb_model"])
    os.environ["IMAGE_BACKEND"] = str(config.get("img_backend", "local"))
    os.environ["IMAGE_MODEL"] = str(config.get("img_model", "krea2-turbo"))
    if config.get("style"):
        os.environ["STYLE"] = str(config["style"])
    os.environ["REGEN_IMAGES"] = "1" if config.get("regen_images") else "0"
    os.environ["REGEN_CHAPTERS"] = "1" if config.get("regen_chapters") else "0"


def _episode_setup(default_ep: int):
    """Run ALL setup prompts for ONE video. Returns a config dict, or None if the
    user aborted / no story was found. Does no heavy generation."""
    resp = input(f"  Episode number? (enter for {default_ep}): ").strip()
    try:
        episode_num = int(resp) if resp else default_ep
    except ValueError:
        print(f"  [WARN] '{resp}' not a number, using {default_ep}")
        episode_num = default_ep
    print(f"\n  Episode #{episode_num:03d}")

    target_paras = _ask_paragraph_target()
    print(f"  [LENGTH] Target {target_paras} narration paragraphs\n")

    res = _ask_resolution()
    os.environ["RESOLUTION"] = res
    print(f"  [RES] Output resolution: {res.upper()} "
          f"({_get_output_resolution()[0]}x{_get_output_resolution()[1]})\n")

    thumb_backend, thumb_model = _ask_thumbnail_backend()
    os.environ["THUMBNAIL_BACKEND"] = thumb_backend
    if thumb_model:
        os.environ["THUMBNAIL_MODEL"] = thumb_model
    print(f"  [THUMB] Thumbnail provider: {thumb_backend} ({thumb_model})\n")

    img_backend, img_model = _ask_image_backend()
    os.environ["IMAGE_BACKEND"] = img_backend
    os.environ["IMAGE_MODEL"] = img_model
    print(f"  [IMG] Episode image provider: {img_backend} ({img_model})\n")

    # ComfyUI gate (only local backends need it)
    _needs_comfy = (thumb_backend == "local" or img_backend == "local")
    if _needs_comfy:
        try:
            req = urllib.request.Request("http://127.0.0.1:8188/system_stats", method="GET")
            with urllib.request.urlopen(req, timeout=4) as r:
                _comfy_ok = r.status == 200
        except Exception:
            _comfy_ok = False
        if not _comfy_ok:
            print("\n  [WARN] ComfyUI is NOT running on port 8188.")
            if img_backend == "local":
                print("         The LOCAL image backend (Krea 2) needs ComfyUI up.")
                print("         Re-run with run_nvidia_gpu.bat --lowvram, OR pick")
                print("         codex / fal / runpod for the episode images instead.")
                _cont = input("  Continue anyway? (y = keep local & continue, "
                              "n = abort): ").strip().lower()
                if _cont in ("n", "no"):
                    print("  [ABORT] ComfyUI not running. Start it, then re-run.")
                    return None
                print("  [OK] Continuing with local backend despite ComfyUI being down.\n")
            else:
                print("         Only your THUMBNAIL backend is local; continuing.\n")

    _cur_style = _active_style_name()
    regen_shots, regen_chapters = _ask_image_regen()
    chosen_style = _ask_style_selection(_cur_style)
    if chosen_style:
        os.environ["STYLE"] = chosen_style
    _style_changed = chosen_style and chosen_style.lower() != _cur_style.lower()
    if _style_changed:
        print(f"  [STYLE] changed {_cur_style or 'default'} -> {chosen_style} - "
              f"forcing re-generate so the new look applies")
        regen_shots, regen_chapters = True, True
    os.environ["REGEN_IMAGES"] = "1" if regen_shots else "0"
    os.environ["REGEN_CHAPTERS"] = "1" if regen_chapters else "0"
    print(f"  [IMAGES] mode: shots={'REGEN' if regen_shots else 'resume'}, "
          f"chapters={'REGEN' if regen_chapters else 'resume'}\n")

    article_url, article_title, article_paras = _pick_resolvable_story()
    if not article_url:
        print("  [HALT] No story found (could not resolve any article). Check RSS feeds.")
        return None

    return {
        "episode_num": episode_num,
        "target_paras": target_paras,
        "resolution": res,
        "article_url": article_url,
        "article_title": article_title,
        "article_paras": article_paras,
        "thumb_backend": thumb_backend,
        "thumb_model": thumb_model,
        "img_backend": img_backend,
        "img_model": img_model,
        "regen_images": regen_shots,
        "regen_chapters": regen_chapters,
        "style": chosen_style or "",
    }


def _phase_llm(config: dict):
    """Run ALL the LLM stages for one episode (article -> narration -> shots ->
    world assets) and START its TTS worker. Returns an ep_ctx dict, or None."""
    global LLM_PROVIDER, NARRATIVE_MODEL, CODEX_SCRIPT_MODEL
    _apply_config_env(config)
    episode_num = config["episode_num"]
    article_url = config["article_url"]
    topic = config.get("article_title") or config.get("topic") or ""
    target_paras = config["target_paras"]

    # PRE-ROLL REACHABILITY GATE (Joe 2026-08-17): probe the selected writer
    # backend ONCE and auto-switch if it's down/busy, so the whole LLM phase
    # doesn't grind into per-call 420s timeouts.
    if not _llm_fail_disable() and not _llm_kill_switched():
        _writer_ok = True
        if LLM_PROVIDER == "codex":
            _writer_ok = _codex_script_reachable()
        else:
            _writer_ok = _llm_fast_reachable()
        if not _writer_ok and _llm_kill_switch_available():
            _oldp = LLM_PROVIDER
            if LLM_PROVIDER == "codex":
                LLM_PROVIDER = "lmstudio"
                NARRATIVE_MODEL = LLM_MODEL or NARRATIVE_MODEL
            else:
                LLM_PROVIDER = "codex"
                NARRATIVE_MODEL = CODEX_SCRIPT_MODEL
                CODEX_SCRIPT_MODEL = NARRATIVE_MODEL
            _LLM_KILL_SWITCHED = True
            print(f"  [PRE-ROLL] writer backend {_oldp} unreachable - switched to "
                  f"{LLM_PROVIDER} for this episode")

    # FAIL-FAST script-backend gate (Joe 2026-08-14): script writing now runs
    # through the Codex CLI (gpt-5.4) unless SCRIPT_BACKEND=lmstudio. Probe codex
    # ONCE up front with a short timeout so a dead/not-installed/throttled codex
    # is caught before the run, instead of every narration/shot call falling
    # through to LM Studio (or worse, serializing into 180s hangs). Fail-open:
    # a non-codex backend or an unprobeable codex never blocks the episode.
    if LLM_PROVIDER == "codex" and not _codex_script_reachable():
        print("  [WARN] Codex script backend unreachable - script writing will "
              "fall back to LM Studio for this episode")

    # Pre-resolved paragraphs (Joe 2026-08-14): _episode_setup already fetched +
    # verified the article, so reuse that instead of re-fetching (a second fetch
    # could fail on a site that blocks repeat hits). Fall back to a fresh fetch
    # for legacy configs / resume states that don't carry article_paras.
    paragraphs = list(config.get("article_paras") or [])
    if not paragraphs:
        paragraphs = fetch_article_paragraphs(article_url)
    if paragraphs:
        paragraphs = _rate_paragraph_relevance(topic, paragraphs)
    if not paragraphs:
        print("  [HALT] Could not extract article content.")
        return None

    print("\n[BIBLE] Building story bible from the article (before script)...")
    story_bible = _build_story_bible(topic, paragraphs)

    narration = _build_narration_script(paragraphs, target_paras, bible=story_bible)
    if narration:
        narration = _rate_paragraph_relevance(topic, narration)
        if not narration:
            print("  [FILTER] All narration segments off-topic, rebuilding from filtered article...")
            narration = _build_narration_script(paragraphs, target_paras, bible=story_bible)
    narration = _dedupe_consecutive_locations(narration)
    # Intro hook + narration plan (key words + foley) at the PARAGRAPH level,
    # BEFORE chapters are inserted / sentences split (Joe 2026-08-12).
    plan = _plan_narration(narration, episode_num)
    intro, intro_plan = _generate_intro(paragraphs)
    if intro:
        narration = list(intro) + narration
        for _ki, _kv in (intro_plan or {}).items():
            plan[max(plan.keys(), default=-1) + 1] = _kv
        print(f"  [INTRO] {len(intro)}-phase shorts-formula intro (+"
              f"{len(intro_plan or {})} key highlight) prepended before chapter 1")
    narration, chapter_events = _insert_chapter_markers(narration)
    anchor_events = _extract_anchor_events(narration)

    establishing_map = {}
    if story_bible:
        narration, establishing_map = _inject_establishing_shots(
            narration, bible=story_bible, anchor_events=anchor_events)

    # SENTENCE-LEVEL SHOTS (Joe 2026-08-10): split every narration paragraph
    # into its individual sentences. Each sentence becomes its own shot / TTS
    # clip / image, so every spoken sentence has a matching image that stays on
    # screen for exactly that sentence's TTS duration. Chapter/establishing/
    # anchor indices are remapped to the flattened sentence list.
    narration, sentence_para_map, chapter_events, establishing_map, anchor_events = \
        _flatten_narration_to_sentences(
            narration, chapter_events, establishing_map, anchor_events)
    narration, sentence_para_map, chapter_events, establishing_map, anchor_events = \
        _cap_flattened_narration(
            narration, sentence_para_map, chapter_events,
            establishing_map, anchor_events)

    # NOTE: TTS is NOT started here. PocketTTS runs on the same GPU as LM Studio,
    # so starting it before the shot-list/world LLM work makes the LLM time out
    # (VRAM contention). The TTS worker starts at the END of this phase, AFTER all
    # LLM work, so it then runs in parallel with the API/cloud image generation
    # (_phase_images) instead of fighting the LLM. (Joe 2026-08-12)

    context = _build_episode_context(topic, paragraphs)
    bible = _build_directors_bible(topic, narration)
    # Merge the STORY bible's character roster into the state bible (Joe
    # 2026-08-17): the directors bible has no 'characters' key, and persisting
    # only the directors bible made every resume see an EMPTY character roster
    # ("0 character sheets / character not found"). The merged dict is what
    # gets saved to the resume state so characters survive a crash.
    _state_bible = dict(bible or {})
    if story_bible and story_bible.get("characters"):
        _state_bible["characters"] = story_bible["characters"]
    _build_scene_board(narration, topic, episode_num)
    _plan_durations(narration)

    _shot_bible = dict(bible or {})
    if story_bible and story_bible.get("characters"):
        _shot_bible["characters"] = story_bible["characters"]
    # PER-SHOT CHECKPOINT (Joe 2026-08-17): as each shot is generated the
    # partial shot list is saved (with the incomplete marker). A kill during
    # the longest LLM phase then resumes by filling the missing tail instead
    # of restarting.
    def _chk_save(_partial):
        _cint = 0
        if intro:
            _cint = len([_s for _s in
                         re.split(r"(?<=[.!?])\s+", intro[0]) if _s.strip()])
        _save_resume_state("story", episode_num, article_url, topic, _partial,
                           {}, chapter_events=chapter_events,
                           anchor_events=anchor_events,
                           location_sheets={}, prop_assets={},
                           target_paras=target_paras,
                           narration=narration, context=context, bible=_state_bible,
                           sentence_para_map=sentence_para_map,
                           establishing_map=establishing_map,
                           intro_count=_cint)
        _mark_shotlist_incomplete(episode_num)

    _shots_sofar = []
    def _chk_cb(_partial):
        _chk_save(_partial)
        _shots_sofar[:] = _partial

    shots = _build_shot_list(narration, bible=_shot_bible, context=context,
                             establishing_map=establishing_map,
                             sentence_para_map=sentence_para_map,
                             checkpoint_cb=_chk_cb, checkpoint_every=int(
                                 os.environ.get("SHOT_CHECKPOINT_EVERY", "25")))
    _clear_shotlist_incomplete(episode_num)  # full shot list now on disk
    if _shots_sofar:
        print(f"  [CHECKPOINT] shot list built with incremental saves "
              f"({len(shots)} shots final) - crash-safe throughout")
    _apply_plan_to_shots(shots, sentence_para_map, plan)  # key words + foley onto shots

    easter_egg = _ask_easter_egg()
    if easter_egg:
        _inject_easter_egg(shots, easter_egg)

    character_sheets = _build_character_sheets(shots, narration, bible=story_bible)

    brands = _extract_brands(topic, paragraphs, narration)
    if brands:
        print(f"\n  [BRAND] businesses detected: {', '.join(brands)}")
        for _b, _ctx in brands.items():
            _logo = _find_logo(_b)
            if _logo:
                print(f"  [BRAND] {_b} logo cached: {os.path.basename(_logo)}")
            _generate_brand_asset(_b, _ctx, random.randint(0, 99999))
    else:
        print("\n  [BRAND] no businesses/AI models detected - no brand assets")
    brand_assets = _scan_brand_assets()

    location_sheets = _build_location_sheets(
        context, 42000 + episode_num * 7, _episode_dir(episode_num), brands=brands)
    prop_assets = _build_prop_assets(
        context, 43000 + episode_num * 7, _episode_dir(episode_num), brands=brands)

    # Two-voice narration (Joe 2026-08-13): the leading intro sentence(s) speak
    # in the announcement INTRO_VOICE; chapter 1 onwards uses STORY_VOICE. The
    # count is persisted in the resume state so a resume regenerates missing
    # clips with the correct voice.
    _intro_count = 0
    if intro:
        _intro_count = len([_s for _s in
                            re.split(r"(?<=[.!?])\s+", intro[0]) if _s.strip()])

    _save_resume_state("story", episode_num, article_url, topic, shots,
                       character_sheets, chapter_events=chapter_events,
                       anchor_events=anchor_events,
                       location_sheets=location_sheets, prop_assets=prop_assets,
                       target_paras=target_paras,
                       narration=narration, context=context, bible=_state_bible,
                       sentence_para_map=sentence_para_map,
                       establishing_map=establishing_map,
                       intro_count=_intro_count)

    # START TTS AFTER all LLM work is done (Joe 2026-08-12): PocketTTS shares the
    # GPU with LM Studio, so it must not run while the shot-list/world LLM calls
    # are in flight. Starting it here means it runs concurrently with the API/cloud
    # image generation (_phase_images) with the LLM already idle.
    tts_thread, tts_results, tts_stop = _start_tts_worker(
        narration, episode_num, intro_count=_intro_count)
    print(f"  [TTS] worker started after shot-list/world LLM work "
          f"({len(narration)} clips, {_intro_count} intro in announcement voice)")

    return {
        "config": config,
        "episode_num": episode_num, "article_url": article_url, "topic": topic,
        "target_paras": target_paras, "paragraphs": paragraphs,
        "narration": narration, "chapter_events": chapter_events,
        "anchor_events": anchor_events, "context": context, "bible": bible,
        "story_bible": story_bible, "shot_bible": _shot_bible,
        "shots": shots, "character_sheets": character_sheets,
        "brands": brands, "brand_assets": brand_assets,
        "location_sheets": location_sheets, "prop_assets": prop_assets,
        "tts_thread": tts_thread, "tts_results": tts_results, "tts_stop": tts_stop,
    }


def _phase_tts_join(ep_ctx: dict) -> None:
    _apply_config_env(ep_ctx["config"])
    print("\n[TTS] Waiting for ALL narration clips to finish before image generation...")
    ep_ctx["tts_thread"].join(timeout=1800)
    _finalize_tts(ep_ctx["shots"], ep_ctx["tts_results"], ep_ctx["episode_num"])
    _save_resume_state("tts", ep_ctx["episode_num"], ep_ctx["article_url"], ep_ctx["topic"],
                       ep_ctx["shots"], ep_ctx["character_sheets"],
                       chapter_events=ep_ctx["chapter_events"], anchor_events=ep_ctx["anchor_events"],
                       location_sheets=ep_ctx["location_sheets"], prop_assets=ep_ctx["prop_assets"],
                       target_paras=ep_ctx["target_paras"])


def _phase_images(ep_ctx: dict) -> None:
    _apply_config_env(ep_ctx["config"])
    ep_ctx["shots"] = _generate_all_shots(
        ep_ctx["shots"], ep_ctx["character_sheets"], episode_num=ep_ctx["episode_num"],
        context=ep_ctx["context"], location_sheets=ep_ctx["location_sheets"],
        prop_assets=ep_ctx["prop_assets"], brand_assets=ep_ctx["brand_assets"],
        topic=ep_ctx["topic"])
    _save_resume_state("images", ep_ctx["episode_num"], ep_ctx["article_url"], ep_ctx["topic"],
                       ep_ctx["shots"], ep_ctx["character_sheets"],
                       chapter_events=ep_ctx["chapter_events"], anchor_events=ep_ctx["anchor_events"],
                       location_sheets=ep_ctx["location_sheets"], prop_assets=ep_ctx["prop_assets"],
                       target_paras=ep_ctx["target_paras"])


def _phase_finish(ep_ctx: dict) -> None:
    _apply_config_env(ep_ctx["config"])
    episode_num = ep_ctx["episode_num"]
    topic = ep_ctx["topic"]
    article_url = ep_ctx["article_url"]
    shots = ep_ctx["shots"]
    character_sheets = ep_ctx["character_sheets"]
    chapter_events = ep_ctx["chapter_events"]
    anchor_events = ep_ctx["anchor_events"]
    location_sheets = ep_ctx["location_sheets"]
    prop_assets = ep_ctx["prop_assets"]
    target_paras = ep_ctx["target_paras"]
    story_bible = ep_ctx["story_bible"]

    # 6b. Title pass: whisper the voice track, resolve exact title times.
    title_events = []
    person_events = []
    if shots:
        clip_starts0 = _compute_clip_starts(shots)
        person_events = _build_person_events(shots, clip_starts0)
    if chapter_events or anchor_events or person_events:
        print("\n[STT] Title pass: whisper timing + event resolution...")
        voice = _ensure_voice_track(shots, episode_num)
        words = _transcribe_voice(episode_num, voice)
        clip_starts = _compute_clip_starts(shots)
        title_events = _build_resolved_title_events(
            chapter_events, anchor_events + person_events, words, clip_starts)
        title_events = _merge_establishing_titles(
            title_events, _build_establishing_events(shots, clip_starts))
        # DETERMINISTIC chapter times (Joe 2026-08-10): the chapter card's
        # window = the chapter sentence's exact clip window, so the video burn
        # AND the description chapter markers use the same reliable times
        # (whisper can mis-hear a chapter number - this fixes that at the root).
        _det_chaps = _deterministic_chapter_events(shots, clip_starts, chapter_events)
        if _det_chaps:
            title_events = _det_chaps + [ev for ev in title_events
                                         if ev.get("kind") != "chapter"]
        for ev in title_events:
            print(f"    [{ev['kind']}] @{ev['start']:.2f}s '{ev.get('text', ev.get('title', ''))}'")
        _save_resume_state("titles", episode_num, article_url, topic, shots,
                           character_sheets, chapter_events=chapter_events,
                           anchor_events=anchor_events, location_sheets=location_sheets,
                           prop_assets=prop_assets, target_paras=target_paras)

    # 7. Render 1080p with full audio mix, then burn the titles.
    # PRE-RENDER image validation (Joe 2026-08-12): regenerate any shot Joe
    # deleted (missing on disk) before rendering so no frame goes to black.
    print("\n[PRE-RENDER] Checking all shot images before rendering...")
    _regen, _still = _regen_missing_images_before_render(
        episode_num, shots, character_sheets, topic)
    if _still:
        print(f"  [HALT] {_still} shot image(s) still missing - NOT rendering "
              f"until every frame is intact. Fix/regenerate the missing images, "
              f"then resume.")
        _save_resume_state("video", episode_num, article_url, topic, shots,
                           character_sheets, titles=[], description="",
                           tags=[], video_path="",
                           chapter_events=chapter_events, anchor_events=anchor_events,
                           location_sheets=location_sheets, prop_assets=prop_assets,
                           target_paras=target_paras)
        return
    video_path = _render_video(shots, episode_num, title_events)
    if not video_path:
        print("  [HALT] Video render failed.")
        return
    _save_resume_state("video", episode_num, article_url, topic, shots,
                       character_sheets, titles=[], description="",
                       tags=[], video_path=video_path,
                       chapter_events=chapter_events, anchor_events=anchor_events,
                       location_sheets=location_sheets, prop_assets=prop_assets,
                       target_paras=target_paras)
    egg_report = _easter_egg_report(shots)
    if egg_report:
        print(f"\n  {egg_report}")

    # 8. Titles + description
    titles = _generate_titles(topic, episode_num, bible=story_bible)
    for i, t in enumerate(titles):
        print(f"  Title {i+1}: {t}")
    description = _generate_description(topic, episode_num, article_url, bible=story_bible)
    description = _append_chapters_to_description(description, title_events)
    llm_tags = _generate_tags(topic, episode_num)
    all_tags = YOUTUBE_BASE_TAGS + [t for t in llm_tags if t not in YOUTUBE_BASE_TAGS]
    tags_str = ",".join(all_tags)
    _save_resume_state("metadata", episode_num, article_url, topic, shots,
                       character_sheets, titles=titles, description=description,
                       tags=all_tags, video_path=video_path,
                       chapter_events=chapter_events, anchor_events=anchor_events,
                       location_sheets=location_sheets, prop_assets=prop_assets,
                       target_paras=target_paras)

    # 9. Thumbnail
    thumb_path = str(_ep_thumb_dir(episode_num) / "thumbnail.png")
    thumb_ok = _generate_thumbnail(topic, thumb_path)
    _save_resume_state("thumbnail", episode_num, article_url, topic, shots,
                       character_sheets, titles=titles, description=description,
                       tags=all_tags, thumb_path=thumb_path, video_path=video_path,
                       chapter_events=chapter_events, anchor_events=anchor_events,
                       location_sheets=location_sheets, prop_assets=prop_assets,
                       target_paras=target_paras)

    # 10. Upload
    video_id = None
    if YOUTUBE_UPLOAD_ENABLED:
        print(f"\n  {'='*50}\n  YOUTUBE UPLOAD ({CHANNEL_NAME})\n  {'='*50}")
        print(f"  Video: {video_path}")
        title = titles[0] if titles else f"{topic[:60]}"
        print(f"  Title: {title}")
        _ensure_youtube_secret()
        _privacy = os.environ.get("YOUTUBE_PRIVACY", "public").strip().lower()
        if _privacy not in ("public", "private", "unlisted"):
            _privacy = "public"
        video_id = _upload_video_with_progress(video_path, title, description, tags_str,
                                               privacy=_privacy)
        if video_id and thumb_ok:
            _upload_thumbnail(video_id, thumb_path)
        if video_id:
            _add_video_to_playlist(video_id)
            EPISODE_COUNTER_FILE.write_text(str(episode_num))
            print(f"  [OK] Episode #{episode_num:03d} uploaded! https://youtu.be/{video_id}")
            if _privacy == "public":
                _post_first_comment(video_id, topic)
                _post_discord_announcement(topic, video_id, episode_num, wait_seconds=60,
                                           description=description)
            else:
                print(f"  [SKIP] ({_privacy}) - no Discord announcement for non-public upload")
        else:
            print(f"  [WARN] Upload failed - video saved locally")
            EPISODE_COUNTER_FILE.write_text(str(episode_num))
    else:
        print(f"\n  [SKIP] YouTube upload disabled")
        print(f"  [SKIP] Video saved locally: {video_path}")
        EPISODE_COUNTER_FILE.write_text(str(episode_num))

    egg_report = _easter_egg_report(shots)
    if egg_report:
        print(f"\n  {egg_report}")

    print(f"\n  {'='*50}")
    print(f"  EPISODE #{episode_num:03d} COMPLETE")
    print(f"  {'='*50}")
    print(f"  Shots:   {len(shots)}")
    print(f"  Video:   {video_path}")
    if YOUTUBE_UPLOAD_ENABLED:
        print(f"  YouTube: {f'https://youtu.be/{video_id}' if video_id else 'NOT UPLOADED'}")
    _cleanup_stt_artifacts(episode_num)
    _clear_resume_state(episode_num)


def run_episode(config: dict) -> None:
    """Single-video pipeline (uses per-episode resume state)."""
    print(f"\n  {'='*60}\n  EPISODE #{config['episode_num']:03d}\n  {'='*60}")
    ep_ctx = _phase_llm(config)
    if not ep_ctx:
        return
    if config["img_backend"] == "local":
        # local Krea: TTS fully done first (GPU contention), then images
        _phase_tts_join(ep_ctx)
        _phase_images(ep_ctx)
    else:
        # codex/API: images run DURING TTS (remote gen, no local GPU)
        _phase_images(ep_ctx)
        _phase_tts_join(ep_ctx)
    _phase_finish(ep_ctx)


def run_resume_all(states: list) -> None:
    """Resume every chosen episode state, in sequence."""
    for st in states:
        ep = st.get("episode_num", st.get("_ep", 0))
        stg = st.get("stage", "?")
        print(f"\n  {'='*60}\n  RESUMING Episode #{ep:03d} (stage '{stg}')\n  {'='*60}")
        try:
            _resume_episode(st)
        except Exception as e:
            print(f"  [RESUME] Episode #{ep:03d} failed: {e}")
            continue


def run_batch_resume(configs: list, statuses: dict) -> None:
    """Resume a previously-set batch (Joe 2026-08-14).

    Skips episodes already finished, resumes episodes that have a saved
    per-episode resume state (stage 'story'/'tts'/'images'/...), and runs the
    remaining episodes fresh from their persisted config. The manifest is
    re-saved after every episode so a second crash still resumes cleanly.
    """
    print(f"\n{'='*60}\n  RESUME BATCH: {len(configs)} videos\n{'='*60}")
    for cfg in configs:
        ep = cfg["episode_num"]
        if _batch_done(statuses, ep):
            print(f"\n--- Episode #{ep:03d}: already complete - skipping ---")
            continue
        _set_resume_ep(ep)
        st = _load_resume_state()
        try:
            if st:
                print(f"\n--- Episode #{ep:03d}: resuming from stage "
                      f"'{st.get('stage', '?')}' ---")
                _resume_episode(st)
            else:
                print(f"\n--- Episode #{ep:03d}: fresh (from saved batch config) ---")
                run_episode(cfg)
            # Only mark DONE when a video actually exists in the resume state.
            # run_episode / _resume_episode return EARLY on HALT (e.g. shot
            # images still missing -> 'NOT rendering'), and marking those
            # episodes done made the batch skip them forever (Joe 2026-08-17).
            _st2 = _load_resume_state() or {}
            if _st2.get("video_path") or _st2.get("video_id"):
                statuses[str(ep)] = "done"
                print(f"  [BATCH] Episode #{ep:03d} complete")
            else:
                print(f"  [BATCH] Episode #{ep:03d} HALTED (no video on disk) - "
                      f"kept pending for the next batch resume")
        except Exception as e:
            print(f"  [BATCH] Episode #{ep:03d} FAILED ({e}) - "
                  f"will retry on the next batch resume")
        _save_batch_manifest(configs, statuses)
    if all(_batch_done(statuses, c["episode_num"]) for c in configs):
        _clear_batch_manifest()
    else:
        print("\n  [BATCH] Some episodes failed - manifest kept for a "
              "future batch resume.")
    print(f"\n{'='*60}\n  BATCH RESUME COMPLETE\n{'='*60}")


def _load_batch_manifest() -> Optional[dict]:
    """Load the batch manifest (configs + per-episode done status), or None."""
    try:
        if BATCH_FILE.exists():
            d = json.loads(BATCH_FILE.read_text())
            if isinstance(d, dict) and isinstance(d.get("configs"), list):
                return d
    except Exception:
        pass
    return None


def _save_batch_manifest(configs: list, statuses: dict) -> None:
    """Persist the batch manifest so a crash mid-batch can be resumed."""
    try:
        tmp = BATCH_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(
            {"configs": configs, "status": statuses or {}},
            indent=2, default=str))
        tmp.replace(BATCH_FILE)
    except Exception as e:
        print(f"  [BATCH] manifest save failed: {e}")


def _clear_batch_manifest() -> None:
    try:
        if BATCH_FILE.exists():
            BATCH_FILE.unlink()
    except Exception:
        pass


def _batch_done(statuses: Optional[dict], episode_num) -> bool:
    return bool(statuses and statuses.get(str(episode_num)) == "done")


def run_fresh_batch(configs: list) -> None:
    """Batch pipeline for N fresh videos.

    Phase 1: run ALL LLM stages for every video and queue TTS for all.
    Phase 2: image gen for all.
      - local Krea 2 selected -> image gen for all AFTER all TTS is done (GPU).
      - codex/API (thumbnail + image) -> image gen runs SIMULTANEOUSLY with TTS.
    Phase 3: render/metadata/thumbnail/upload each.

    The batch manifest (.batch_state.json) is persisted up front (all pending)
    and updated as each episode finishes, so a crash mid-batch can be resumed
    via main()'s batch-resume prompt (skip done / resume in-progress / fresh
    for the rest).
    """
    print(f"\n{'='*60}\n  BATCH: generating {len(configs)} videos\n{'='*60}")

    # Persist the batch manifest up front (Joe 2026-08-14: batch resume).
    statuses = {str(c["episode_num"]): "pending" for c in configs}
    _save_batch_manifest(configs, statuses)

    # Phase 1: LLM + start TTS for ALL
    ctxs = []
    for cfg in configs:
        print(f"\n--- Episode #{cfg['episode_num']:03d}: LLM / script ---")
        ctx = _phase_llm(cfg)
        if ctx:
            ctxs.append(ctx)
        else:
            # Couldn't prepare this episode (no story / HALT). Mark it done so a
            # batch resume doesn't loop retrying it forever.
            statuses[str(cfg["episode_num"])] = "done"
            _save_batch_manifest(configs, statuses)
    if not ctxs:
        print("  [HALT] No episodes could be prepared.")
        _clear_batch_manifest()
        return

    local = all(c.get("img_backend") == "local" for c in configs)
    if local:
        # local Krea: finish ALL TTS first (GPU contention), then image gen all.
        for ctx in ctxs:
            _phase_tts_join(ctx)
        for ctx in ctxs:
            print(f"\n--- Episode #{ctx['episode_num']:03d}: images ---")
            _phase_images(ctx)
    else:
        # codex/API: image gen for all episodes in parallel, DURING TTS.
        _cap = max(1, min(int(os.environ.get("BATCH_CONCURRENCY", "2")), len(ctxs)))

        def _img(ctx):
            print(f"\n--- Episode #{ctx['episode_num']:03d}: images (parallel, during TTS) ---")
            _phase_images(ctx)

        with ThreadPoolExecutor(max_workers=_cap) as _ex:
            list(_ex.map(_img, ctxs))
        for ctx in ctxs:
            _phase_tts_join(ctx)

    # Phase 3: finish each (whisper titles -> render -> metadata -> thumb -> upload)
    for ctx in ctxs:
        print(f"\n--- Episode #{ctx['episode_num']:03d}: finish (render/upload) ---")
        try:
            _phase_finish(ctx)
            statuses[str(ctx["episode_num"])] = "done"
            print(f"  [BATCH] Episode #{ctx['episode_num']:03d} complete")
        except Exception as e:
            print(f"  [BATCH] Episode #{ctx['episode_num']:03d} finish FAILED ({e}) - "
                  f"will resume from its saved state on the next batch resume")
        _save_batch_manifest(configs, statuses)

    # All finished -> drop the manifest so the next run starts fresh.
    if all(v == "done" for v in statuses.values()):
        _clear_batch_manifest()

    print(f"\n{'='*60}\n  BATCH COMPLETE ({len(ctxs)} videos)\n{'='*60}")

if __name__ == "__main__":
    main()
