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
  -> FFmpeg render 1080p with music (-18dB) + timecoded SFX (-14dB)
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

TTS_TEMP = PROJECT_DIR / "tts_temp"
SHOTS_DIR = PROJECT_DIR / "shots"
RENDERED_AUDIO = PROJECT_DIR / "rendered_audio"
RENDERED_VIDEO = PROJECT_DIR / "rendered_video"
THUMBNAILS_DIR = PROJECT_DIR / "thumbnails"
SFX_DIR = PROJECT_DIR / "cinematic_sounds"
USED_ARTICLES_FILE = PROJECT_DIR / ".used_articles.json"
EPISODE_COUNTER_FILE = PROJECT_DIR / ".episode_counter"
RESUME_FILE = PROJECT_DIR / ".resume_state.json"
BATCH_TEMP = PROJECT_DIR / "batch_temp"

YOUTUBE_CREDENTIALS = Path.home() / ".youtube-upload-credentials.json"
CLIENT_SECRETS = PROJECT_DIR / "client_secret_874421706318-sl7gg802bovuib9h2q95hq9lvlb661oi.apps.googleusercontent.com.json"

for d in [TTS_TEMP, SHOTS_DIR, RENDERED_AUDIO, RENDERED_VIDEO, THUMBNAILS_DIR, BATCH_TEMP]:
    d.mkdir(exist_ok=True)

LM_STUDIO_URL = "http://localhost:1234/v1/chat/completions"
POCKET_TTS_URL = "http://127.0.0.1:8769"
FAL_API_KEY = os.environ.get("FAL_API_KEY", "")
RUNPOD_API_KEY = os.environ.get("RUNPOD_API_KEY", "")
RUNPOD_ENDPOINT = "https://api.runpod.ai/v2/z-image-turbo/runsync"

# TTS: custom cloned voice ref (from youtube.com/shorts/wBJdFVdCCyM).
# When TTS_VOICE is a file path it is uploaded as voice_wav (clone); a bare
# name (e.g. "alba") selects a built-in PocketTTS catalog voice via voice_url.
TTS_VOICE = str(PROJECT_DIR / "voice_refs" / "split_node.wav")

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
    "true stories", "true crime documentary", "documentary", "unreal engine",
    "3d animation", "metahuman", "people who beat the system", "incredible true stories",
]

# RSS feeds for the niche (fallback pool - primary source is HN Algolia search).
# Expanded Aug 2026 with AI / tech / security feeds to serve the trend-scan
# categories (hacker, beat-the-system, lottery, AI, tech).
RSS_FEEDS = [
    # security / hacker
    "https://www.wired.com/feed/tag/cybersecurity/latest/rss",
    "https://krebsonsecurity.com/feed/",
    "https://feeds.feedburner.com/TheHackersNews",
    "https://www.bleepingcomputer.com/feed/",
    "https://www.404media.co/rss/",
    "https://www.darkreading.com/rss.xml",
    "https://www.schneier.com/feed/atom/",
    "https://therecord.media/feed",
    "https://grahamcluley.com/feed/",
    "https://securityweekly.com/feed/",
    # tech / startup / exploits
    "https://news.ycombinator.com/rss",
    "https://arstechnica.com/feed/",
    "https://techcrunch.com/feed/",
    "https://www.theverge.com/rss/index.xml",
    "https://www.wired.com/feed/tag/tech/latest/rss",
    # AI
    "https://venturebeat.com/feed/",
    "https://www.technologyreview.com/feed/",
    "https://www.marktechpost.com/feed/",
    "https://syncedreview.com/feed/",
    # general news (beat-the-system stories surface here)
    "https://feeds.bbci.co.uk/news/technology/rss.xml",
    "https://feeds.bbci.co.uk/news/world/rss.xml",
    "https://www.theguardian.com/technology/rss",
    "https://www.theguardian.com/world/rss",
    "https://feeds.washingtonpost.com/rss/world",
]

# HN Algolia search queries - tuned to the niche: math beating the lottery,
# hackers making money, loopholes exploited. Each returns scored, dated stories.
HN_SEARCH_QUERIES = [
    "lottery math",
    "lottery loophole",
    "lottery jackpot mathematics",
    "won the lottery system",
    "card counting blackjack",
    "casino exploit",
    "gambling system beat",
    "hacker made millions",
    "exploit bank millions",
    "stole millions system",
    "beat the system loophole",
    "math professor lottery",
    "lottery algorithm",
    "counterfeit scheme",
    "poker math win",
    "security flaw millions",
    "social engineering scam millions",
    "fraud loophole millions",
]

# Scoring tiers - strong phrases are worth far more than weak ones
STRONG_KEYWORDS = [
    "lottery", "jackpot", "card counting", "blackjack", "casino", "loophole",
    "exploit", "hacked", "hacker", "million", "millions", "scam", "fraud",
    "counterfeit", "stole", "heist", "won", "wins", "poker", "gambling",
    "betting", "math", "mathematician", "algorithm",
]
WEAK_KEYWORDS = [
    "system", "security", "vulnerability", "breach", "hack", "cheat",
    "bet", "win", "prize", "money", "bank", "scheme",
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

# Render style base - 3D animation / Unreal Engine / Metahuman with real faces
RENDER_STYLE = (
    "Realistic 3D render style, photorealistic human character with perfect anatomy, "
    "realistic body proportions, detailed natural skin with visible pores and "
    "subsurface scattering, lifelike expressive eyes, realistic hair, high-fidelity "
    "Unreal Engine 5 Metahuman-quality 3D render, cinematic lighting, moody atmosphere, "
    "dark color grade, film grain, high detail, 8k, dramatic documentary recreation"
)

# Scene-only style for shots with NO character (establishing/landscape/object shots).
# Deliberately contains zero human/anatomy language so the image generator never
# adds a person - previously no-character shots reused RENDER_STYLE and the
# "human character with perfect anatomy" text made RunPod render a topless man.
SCENE_STYLE = (
    "Realistic 3D render style, Unreal Engine 5 Metahuman-quality environment and "
    "prop render, cinematic lighting, moody atmosphere, dark color grade, film grain, "
    "high detail, 8k, dramatic documentary recreation. EMPTY SCENE - no people, no "
    "humans, no characters, no figures, no silhouettes, no faces, no bodies, no hands, "
    "no clothing, no anatomy, absolutely no persons in the frame"
)

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
        "bold animated style, strong stylized brushwork, painterly shading, "
        "saturated colors, dramatic rim lighting, dark moody atmosphere, "
        "high detail, cinematic documentary recreation"),
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


def _ask_easter_egg() -> Optional[str]:
    """Ask whether to hide an easter egg in one shot. Returns the egg NAME or
    None. EASTER_EGG=<name> env selects directly without prompting."""
    if os.environ.get("EASTER_EGG"):
        name = os.environ.get("EASTER_EGG").strip().lower()
        eggs = _load_easter_eggs()
        if name in eggs:
            print(f"  [EGG] easter egg selected via env: '{name}'")
            return name
        print(f"  [EGG] unknown easter egg '{name}' - skipping")
        return None
    resp = input("\n  Hide an easter egg in one shot? [Y/n]: ").strip().lower()
    if resp in ("n", "no"):
        return None
    eggs = _load_easter_eggs()
    names = list(eggs.keys())
    print("  Select an easter egg:")
    for i, n in enumerate(names, 1):
        print(f"    {i}. {n}")
    print(f"    {len(names)+1}. add new")
    choice = input(f"  Choose [1-{len(names)+1}, or a name]: ").strip()
    if choice.lower() in ("add", "add new", "new", "custom", str(len(names)+1)):
        newname = input("  Easter egg name: ").strip()
        newprompt = input("  Easter egg prompt (describes the small background element): ").strip()
        if newname and newprompt:
            add_easter_egg(newname, newprompt)
            return newname.lower()
        print("  [EGG] need a name and a prompt - no easter egg added")
        return None
    if choice.isdigit() and 1 <= int(choice) <= len(names):
        return names[int(choice) - 1].lower()
    if choice.lower() in [n.lower() for n in names]:
        return choice.lower()
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
    human string, or None if no easter egg was injected."""
    egg_shot = next((s for s in shots if s.get("easter_egg")), None)
    if not egg_shot:
        return None
    cursor = 0.0
    for s in shots:
        if s.get("easter_egg"):
            break
        if s.get("tts_path") and os.path.isfile(s["tts_path"]):
            cursor += _get_audio_duration(s["tts_path"]) + 0.3
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


def _style_inject() -> str:
    """CRITICAL style injection appended to every image prompt (shots, b-roll,
    location/prop sheets, character panels). The style is a NON-NEGOTIABLE
    hard requirement, framed emphatically so the model can't drop or dilute it.
    Text-only style transfer (no image refs)."""
    desc = _get_style_prompt().rstrip(".")
    return (
        f"CRITICAL - THIS IMAGE MUST BE RENDERED STRICTLY IN THE FOLLOWING "
        f"VISUAL STYLE AND NOTHING ELSE: '{desc}'. DO NOT deviate from, "
        f"dilute, or replace this style with any other art direction, "
        f"painting style, or rendering style - the chosen style is mandatory "
        f"and overrides all other stylistic choices. Apply it to the ENTIRE "
        f"frame, every element, the background, the lighting, the color grade "
        f"and the rendering finish without exception."
    )


# B-roll image cache (DEPRECATED 2026-08-04 - no longer used by the pipeline;
# kept so the standalone generate_broll_cache.py helper still imports).
IMAGE_ASSETS_DIR = PROJECT_DIR / "image-assets"
_ASSETS_INDEX = IMAGE_ASSETS_DIR / "assets.json"

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


def _load_asset_index() -> dict:
    if _ASSETS_INDEX.is_file():
        try:
            return json.loads(_ASSETS_INDEX.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_asset_index(idx: dict) -> None:
    try:
        IMAGE_ASSETS_DIR.mkdir(parents=True, exist_ok=True)
        _ASSETS_INDEX.write_text(json.dumps(idx, indent=1), encoding="utf-8")
    except Exception:
        pass


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


def _lookup_broll_asset(scene: str) -> Optional[str]:
    """Find a cached no-character image matching the scene. None if no match."""
    if not IMAGE_ASSETS_DIR.is_dir():
        return None
    kw = _scene_keywords(scene)
    if not kw:
        return None
    # JSON index first: exact keyword-set matches across any past episode
    idx = _load_asset_index()
    for key, path in idx.items():
        if not path or not os.path.isfile(path):
            continue
        key_set = set(key.split("_"))
        if kw and all(t in key_set for t in kw[:2]):
            return str(path)
    best, best_score = None, 0
    for f in IMAGE_ASSETS_DIR.glob("*.png"):
        name_kw = set(f.stem.lower().split("_"))
        score = sum(1 for t in kw if t in name_kw)
        if score > best_score:
            best, best_score = f, score
    return str(best) if best_score >= 1 else None


def _cache_broll_asset(image_path: str, scene: str) -> str:
    """Copy a freshly generated no-character image into image-assets/ (keyword
    filename + assets.json entry) so future episodes reuse it instead of
    regenerating. Pipeline rule: every cached image is upscaled to 1920x1080."""
    try:
        if not image_path or not os.path.isfile(image_path):
            return image_path
        IMAGE_ASSETS_DIR.mkdir(parents=True, exist_ok=True)
        kw = _scene_keywords(scene)[:6]
        if not kw:
            return image_path
        dst = IMAGE_ASSETS_DIR / (f"{'_'.join(kw)}.png")
        if dst.exists():
            return str(dst)
        import shutil as _sh
        _sh.copy2(image_path, dst)
        try:
            from PIL import Image as _PILImg
            w, h = _PILImg.open(dst).size
        except Exception:
            w = h = 0
        if (w, h) != (1920, 1080):
            # only re-upscale sources that aren't already 1080p (Krea shots
            # come out of the in-graph FaceUpDAT upscale at 1920x1080)
            try:
                _upscale_to_1080p(str(dst))
            except Exception:
                pass
        idx = _load_asset_index()
        idx["_".join(kw)] = str(dst)
        _save_asset_index(idx)
        return str(dst)
    except Exception:
        return image_path

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
    # typing / keyboard / typewriter
    (("typing", "types", "typewriter", "keyboard", "keys on", "at the keyboard",
      "tapping", "taps on", "types on", "hits the keys"),
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
# whisper / STT artifacts are deleted on episode completion
WHISPER_JSON = "ep{ep:03d}_whisper.json"

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

# Mix levels (dB)
VOICE_DB = 0.0
MUSIC_DB = -18.0
SFX_DB = -14.0
# Camera shutter is a punchy transient - it needs to CUT through (user: -4dB)
SHUTTER_DB = -4.0

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

    # -- Primary: HN Algolia niche search --
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
            it["final_score"] = round(
                0.5 * min(it["score"] * 10, 100)
                + 0.3 * trend_rel
                + 0.2 * min(it.get("hn_points", 0), 100), 1)
            matches.append(it)
        if len(matches) >= 10:
            break
        time.sleep(0.4)

    # Sort by MOST RECENT first (recency-first, matching the filters), with
    # final_score as the tiebreak so a fresher niche hit wins over an older one.
    matches.sort(key=lambda x: (_parse_item_date(x), x.get("final_score", 0),
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
                if score >= 3:
                    it["score"] = score
                    it["hn_points"] = 0
                    trend_rel, matched_term = _trend_relevance(
                        f"{it['title']} {it['description']}", trend_topics)
                    it["trend_rel"] = trend_rel
                    it["trend_term"] = matched_term
                    it["final_score"] = round(
                        0.5 * min(score * 10, 100) + 0.3 * trend_rel, 1)
                    seen_titles.add(tkey)
                    matches.append(it)
            if len(matches) >= 8:
                break
            time.sleep(0.3)
        matches.sort(key=lambda x: (_parse_item_date(x),
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


def _pick_story() -> tuple[str, str]:
    """Pick a story with user confirmation. Asks Y/n per candidate;
    re-polls RSS when the candidate pool runs out.

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
            _save_used_article(src)
            return (src, title)
        print(f"  [WARN] '{src[:40]}' is not a valid http(s) URL - falling back to RSS")

    print("\n[RSS] Scraping feeds for a 'beat the system' story...")
    print("  [TREND] scanning rising + under-served topics (trend-research-toolkit)...")
    trend_topics = _trend_topics()
    pool = _collect_candidate_stories(used, rejected_set, trend_topics)
    if not pool:
        print("  [FAIL] No articles found at all")
        return ("", "")
    print(f"  [RSS] {len(pool)} candidate stories found\n")

    while True:
        # Pool exhausted -> re-poll RSS for fresh candidates
        if pool_idx >= len(pool):
            rounds += 1
            if rounds >= 6:
                print("  [FAIL] Ran out of stories after 6 re-polls. Try again later.")
                return ("", "")
            print(f"\n  [RSS] Pool exhausted ({len(pool)} candidates). Re-polling feeds...")
            time.sleep(2)
            pool = _collect_candidate_stories(used, rejected_set, trend_topics)
            pool_idx = 0
            if not pool:
                print("  [FAIL] No fresh articles found on re-poll")
                return ("", "")

        chosen = pool[pool_idx]
        pool_idx += 1
        print(f"  {'='*60}")
        print(f"  CANDIDATE STORY:")
        print(f"    {chosen['title']}")
        print(f"    {chosen['link']}")
        # Score line: niche + rising (Google Trends) + under-served (YouTube)
        fs = chosen.get("final_score")
        tr = chosen.get("trend_rel", 0)
        tt = chosen.get("trend_term", "")
        hp = chosen.get("hn_points", 0)
        print(f"    [final={fs if fs is not None else '?'} | niche={chosen.get('score', 0)*10}"
              f"/100 | rising_topic='{tt}' ({tr}/100) | hn={hp}]")
        print(f"  {'='*60}")
        resp = input("  Use this topic? (Y/n/q): ").strip().lower()
        if resp in ("q", "quit"):
            print("  [SKIP] Aborted by user")
            return ("", "")
        if resp in ("", "y", "yes"):
            _save_used_article(chosen["link"])
            print(f"  [OK] Story selected: {chosen['title'][:70]}")
            return (chosen["link"], chosen["title"])
        # User said no - persist it so it isn't re-presented for ~1 week
        _save_rejected_article(chosen["link"])
        rejected_set.add(chosen["link"])
        print("  [NEXT] Trying another story...")

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
    if re.match(r'^by\s+[A-Z][a-zA-Z\'\-]+(\s+[A-Z][a-zA-Z\'\-]+){0,3}\.?$', text):
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
    return text

def _llm_score_batch(messages: list[dict], max_tokens: int = 300) -> str:
    """Minimal LM Studio call for relevance scoring (no stop tokens, low temp)."""
    data = json.dumps({
        "model": "gemma-4-e4b-uncensored-hauhaucs-aggressive",
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
        "model": "gemma-4-e4b-uncensored-hauhaucs-aggressive",
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temp,
    }).encode()
    req = urllib.request.Request(LM_STUDIO_URL, data=data,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            result = json.loads(r.read())
        return result["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"  [LLM error] {e}")
        return ""

# -- Stage 1: Narration script ---------------------------------------

TARGET_NARRATION_PARAS = 115
# Measured narration pace for length estimates (ep8: 120 paras -> 1712.7s
# voice timeline incl. 0.3s pads between clips => ~14.3s per paragraph).
SECONDS_PER_NARRATION_PARA = 14.3
# Default requested video length in minutes (maps to ~115 paragraphs).
DEFAULT_VIDEO_MINUTES = 25
# Clamp the derived paragraph count so a bad/typo'd length can't blow up.
MIN_PARAS, MAX_PARAS = 10, 400

NARRATION_SYSTEM_PROMPT = (
    "You are a documentary scriptwriter for a YouTube channel called SPLIT NODE. "
    "The channel tells true stories of ordinary people who used their skills, brains, "
    "or nerve to beat the system - hackers, lottery mathematicians, card counters, "
    "scam-baiters, people who found legal loopholes and won the game of life. "
    "Your writing style is the Black Files / FERN true-crime documentary style.\n\n"
    "STYLE RULES (follow ALL of them):\n"
    "1. COLD OPEN: the very first paragraph must drop the viewer into a specific, "
    "visceral scene - exact place, one dramatic image after another - escalate the "
    "stakes, then end with a twist tease ('Except this story doesn't end there...') "
    "and the question the whole episode answers.\n"
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
    "by the one before it.\n"
    "6. SENTENCE RHYTHM: vary sentence length aggressively - a one-word fragment "
    "('Case closed.') next to a long flowing sentence. Monotone sentence length is "
    "death. Write to be read aloud.\n"
    "7. CONTEXT FIRST, THEN ESCALATE: open simple enough for someone who knows "
    "nothing about the topic, then raise complexity beat by beat. Never open with the "
    "most advanced concept.\n"
    "8. EXACT NUMBERS, never vague. Dollar amounts, durations, counts "
    "('$449 a fortnight', '$2.1 million', '29 months', 'a $9 fee', 'five taps of $4,999'). "
    "Never write 'a lot of money' - write the exact figure from the article.\n"
    "9. PLACE ANCHORS: every time the scene shifts, START the new paragraph "
    "with a standalone location sentence ('Goulburn, New South Wales.' / "
    "'Queen Square, Sydney.'). The viewer must always know where the story is. "
    "Use REAL place names from the article. Do NOT use dates.\n"
    "10. METAPHOR AND SENSORY DETAIL: concrete images ('the account died mid-"
    "transaction like a heart stopping between beats', 'a paper monument to a number "
    "nobody at the bank appears to be reading').\n"
    "11. RHETORICAL QUESTIONS as pivots between beats - and 2-3 times per episode, "
    "ask the viewer to figure something out themselves instead of telling them "
    "('Who is watching this account?') then pay it off a few paragraphs later.\n"
    "12. IRONY AND REVERSAL: set up the obvious reading, then flip it ('The law has a "
    "name for that arrangement, and it isn't fraud. It's a loan.')\n"
    "13. DIRECT ADDRESS 1-2 times per episode ('Be honest. If some part of you would "
    "have typed that first $4,999 too...')\n"
    "14. NEVER invent facts that contradict the article. Expand with cinematic framing, "
    "sensory detail and dramatic tension only.\n"
    "15. OUTPUT CONTRACT: say NOTHING except the narration itself. Never write meta "
    "text or labels - no 'Here are exactly 5 narration paragraphs', no 'Paragraph 1:', "
    "no 'Narration:', no 'Sure, here are...', no 'I've written...', no numbering, no "
    "headers, no stage directions, no intros, no summaries, no signposting of any kind. "
    "Every line you output is read ALOUD by the narrator, so a single meta word is "
    "spoken on camera. Output ONLY the raw narration paragraphs.\n\n"
    "I will give you an excerpt of a news article plus story context. Your job: EXPAND "
    "it into a gripping documentary narration. Write in the present tense, cinematic, "
    "dramatic - build suspense, then resolve triumphantly near the end. Every narration "
    "paragraph must be 2-4 sentences and cover a DIFFERENT beat - do not repeat ideas "
    "across paragraphs, and never repeat beats I tell you are already covered."
    "\n\n"
    "When I ask you to 'generate exactly N narration paragraphs based on this context', "
    "produce EXACTLY N paragraphs, expanding the source material with cinematic detail "
    "and drama."
)

def _build_narration_script(paragraphs: list[str],
                            target_paras: int = 0) -> list[str]:
    """Stage 1: expand the article into ~target narration paragraphs.

    target_paras comes from the interactive length prompt (default
    TARGET_NARRATION_PARAS). Each article paragraph is expanded into X
    narration paragraphs where X = round(target / len(article_paragraphs)),
    so the total lands as close to the target as possible even when the
    article has fewer paragraphs.
    """
    target = target_paras or TARGET_NARRATION_PARAS
    print("\n[LLM] Stage 1: writing documentary narration script...")
    n_art = max(len(paragraphs), 1)
    per_para = max(2, round(target / n_art))
    print(f"  [LLM] Target {target} narration paragraphs "
          f"({per_para} per article paragraph x {n_art} article paragraphs)")
    narration_paras = []
    covered = []  # rolling summary of already-written beats (dedupe guard)
    for i, _para in enumerate(paragraphs):
        lo, hi = max(i - 1, 0), min(i + 2, len(paragraphs))
        ctx = "\n\n".join(paragraphs[lo:hi])
        user = (
            f"STORY CONTEXT (article excerpt {lo+1}-{hi} of {len(paragraphs)}):\n{ctx}\n\n"
            f"Generate exactly {per_para} narration paragraphs based on this context. "
            f"Focus on the facts and events in this excerpt - expand them with "
            f"cinematic detail, sensory description and dramatic tension."
        )
        if covered:
            user += (
                "\n\nALREADY COVERED in earlier narration - do NOT repeat these beats:\n"
                + "\n".join(f"- {c}" for c in covered[-2:])
            )
        text = _llm_chat([
            {"role": "system", "content": NARRATION_SYSTEM_PROMPT},
            {"role": "user", "content": user}
        ], max_tokens=min(1600, 250 + per_para * 120), temp=0.85)
        parts = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
        if len(parts) < 2 and "\n" in text:
            parts = [p.strip() for p in text.split("\n") if len(p.strip()) > 40]
        added = 0
        for p in parts:
            p_clean = re.sub(r"^\s*[-*#]+\s*", "", p).strip()
            p_clean = _strip_narration_meta(p_clean)
            if len(p_clean) > 40:
                narration_paras.append(p_clean)
                added += 1
        if added:
            covered.append(f"({i+1}/{n_art}) {narration_paras[-1][:110]}")
        time.sleep(0.3)

    if not narration_paras:
        print("  [LLM] Narration failed, using article paragraphs directly")
        narration_paras = [re.sub(r"\s+", " ", p).strip()[:500]
                           for p in paragraphs[:target]]

    print(f"  [LLM] Narration script: {len(narration_paras)} paragraphs")
    for i, p in enumerate(narration_paras):
        print(f"    {i+1}. {p[:70]}...")
    return narration_paras


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
    "Example:\n"
    "4 | The Account That Never Said No\n"
    "No other text."
)


def _llm_chapter_titles(narration_paras: list[str], breaks: list[int]) -> list[str]:
    """LLM writes one 2-6 word title per ALREADY-chosen chapter break.

    Returns a list parallel to breaks; empty string means the LLM skipped
    that break (caller falls back to a derived title).
    """
    numbered = "\n".join(f"{i+1}. {p[:160]}" for i, p in enumerate(narration_paras))
    break_nums = ", ".join(str(b + 1) for b in breaks)
    text = _llm_chat([
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
    earlier passing mention doesn't steal the title)."""
    canon = _character_canonical_map(shots)
    seen = set()
    events = []
    for pos, shot in enumerate(shots):
        if shot.get("is_chapter"):
            continue
        ch = shot.get("character", "NONE")
        if ch == "NONE":
            continue
        name = canon.get(ch, ch)
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


def _build_episode_context(topic: str, paragraphs: list[str]) -> dict:
    """One LLM pass: the story's world (era, places, environments, props).
    Injected into the shot list so scenes fit ANY topic - a rainforest story
    gets rainforest scenes, not city streets."""
    sample = " ".join(paragraphs[:10])[:2800]
    ctx = _llm_json([
        {"role": "system", "content":
            "You are a documentary production researcher. From the article "
            "excerpt, extract the story's world as STRICT JSON only: "
            '{"era": "one era descriptor", "places": ["3-5 real places"], '
            '"environments": ["3-5 environments/settings where scenes happen"], '
            '"props": ["4-8 objects central to the story"], '
            '"time_of_day": "when most scenes happen"}. '
            "Say NOTHING outside the JSON."},
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
    print("  [CONTEXT] era=%s | %d places | %d environments | %d props"
          % (defaults["era"], len(defaults["places"]),
             len(defaults["environments"]), len(defaults["props"])))
    return defaults


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
        res = _llm_json([
            {"role": "system", "content":
                "You are a storyboard artist. For each numbered narration beat "
                "produce STRICT JSON only: "
                '{"cards": [{"idx": 1, "beat": "one-line action beat", '
                '"location": "setting", "characters": ["names or []"], '
                '"mood": "suspense|triumphant|neutral"}]}. '
                "Match idx to the input numbers exactly. Say NOTHING else."},
            {"role": "user", "content": f"TOPIC: {topic}\n{chunk_txt}"}
        ], max_tokens=1200, temp=0.3)
        for c in res.get("cards", []):
            try:
                cards.append({
                    "idx": int(c.get("idx", i + 1)),
                    "beat": str(c.get("beat", ""))[:160],
                    "location": str(c.get("location", ""))[:80],
                    "characters": [str(x) for x in c.get("characters", [])][:4],
                    "mood": c.get("mood", "neutral"),
                })
            except Exception:
                continue
    if cards:
        ep_dir = SHOTS_DIR / f"ep{episode_num:03d}"
        ep_dir.mkdir(parents=True, exist_ok=True)
        try:
            (ep_dir / "scene_board.json").write_text(
                json.dumps(cards, indent=1), encoding="utf-8")
        except Exception:
            pass
    print(f"  [BOARD] {len(cards)} scene cards -> shots/ep{episode_num:03d}/scene_board.json")
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
    "You are a shot-list director for SPLIT NODE, a 3D documentary channel "
    "(Unreal Engine 5 / Metahuman style, photorealistic 3D render characters with "
    "perfect anatomy and realistic detailed faces). "
    "The visual style: every person in the story is a photorealistic 3D character with "
    "perfect anatomy, realistic detailed skin, styled hair, and clothing appropriate to the scene. "
    "Each character must be identified by NAME (use the real name from the story, or "
    "a clearly consistent invented name if the story doesn't give one - and reuse the "
    "exact same name every time that person appears). "
    "CHARACTER NAME RULE: once a person is named, ALWAYS repeat the exact same full name "
    "verbatim in every shot they appear in. NEVER switch to first-name-only, last-name-only, "
    "ALL CAPS, initials, or a different spelling - 'Stefan Mandel' stays 'Stefan Mandel' "
    "in every single shot. "
    "If a shot contains MULTIPLE people, put ALL of their names in the character field "
    "separated by commas (e.g. 'Stefan Mandel, Richard Lustig'). "
    "The scenes must show the characters actually DOING something - an action that "
    "moves the story forward. Never static portraits. Full scenes based on the actions "
    "they take in the narration. ALWAYS state which way each character faces in the scene "
    "description ('facing left', 'turned to the right', 'seen from behind', 'facing the "
    "camera') so the correct reference panel is chosen for the shot.\n\n"
    + CAMERA_LOGIC +
    "\nI will give you one paragraph of the narration script. Create ONE shot for it. "
    "Respond with EXACTLY ONE LINE of 7 pipe-separated fields, in this exact order, "
    "with NO labels, NO extra text, NO line breaks:\n"
    "<shot type EWS/WS/MS/CU/ECU> | <camera angle: eye-level, low-angle, high-angle, over-the-shoulder, from-behind, side-on> | "
    "<character NAME or NONE, or comma-separated names for multiple people> | <character role, e.g. lottery mathematician> | "
    "<full scene description: setting, what the character is DOING, which way each faces, props, lighting, camera framing. 2-4 sentences, action-focused> | "
    "<SFX filename or NONE> | <suspense | neutral | triumphant>\n"
    "Example line:\n"
    "MS | low-angle | Stefan Mandel | lottery mathematician | Stefan sits at a candlelit desk in a cramped 1980s Bucharest apartment, hunched over a spreadsheet of every number combination, a worn calculator in hand. | mixkit-cinematic-trailer-riser-790.wav | suspense\n"
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
    }


def _build_shot_list(narration_paras: list[str], bible: Optional[dict] = None,
                     context: Optional[dict] = None) -> list[dict]:
    """Stage 2: for each narration paragraph, generate a shot entry.

    Injects the episode context (era/places/environments/props) and the
    director's bible (hero paragraphs) so the shot list fits ANY topic and
    magnifies the right moments. Hero beats get ECU framing + a riser SFX.
    Chapter paragraphs get a direct black-card shot (no LLM call, no image
    generation - the render pass shows a black placeholder where the glowing
    chapter title is burned in pass 2).
    """
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
    shots = []
    for i, para in enumerate(narration_paras):
        if len(shots) >= 120:
            break
        m_chap = CHAPTER_RE.match(para)
        if m_chap:
            shots.append({
                "narration": para,
                "narration_idx": i,
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
            })
            print(f"  [LLM] Shot {len(shots)}: [CHAPTER {m_chap.group(1)}] '{m_chap.group(2).strip()}'")
            continue
        text = _llm_chat([
            {"role": "system", "content": SHOT_SYSTEM_PROMPT},
            {"role": "user", "content": (
                f"{ctx_line}NARRATION PARAGRAPH {i+1} of {len(narration_paras)}:\n{para[:1200]}\n\n"
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

        # Normalize character name: strip role-y artifacts, keep the name itself
        character = character.strip().strip(".").strip()
        if character.upper() in ("NONE", "N/A", "NOBODY", "NO ONE", "-", ""):
            character = "NONE"
        # If role field is absurdly long, the model squeezed scene text into it -
        # salvage: if scene is empty, use the tail of the long role as the scene
        if len(character_role) > 120:
            if not scene:
                scene = character_role
            character_role = "character in the story"
        # Validate SFX
        if sfx not in SFX_LIBRARY:
            sfx = "NONE"
        # Don't repeat the same SFX in consecutive shots
        if shots and shots[-1].get("sfx") == sfx and sfx != "NONE":
            sfx = "NONE"
        if tone not in ("suspense", "neutral", "triumphant"):
            tone = "neutral"
        if not scene:
            print(f"  [LLM] Shot {i+1}: parse failed, skipping ({text[:60]!r})")
            continue

        shots.append({
            "narration": para,
            "narration_idx": i,
            "shot_type": shot_type,
            "angle": angle,
            "character": character,
            "character_role": character_role,
            "scene": scene,
            "sfx": sfx,
            "tone": tone,
        })
        # Director's bible: hero beats get ECU magnification + a riser SFX
        if (i + 1) in hero_set:
            shots[-1]["hero"] = True
            if shots[-1]["shot_type"] not in ("ECU", "CU"):
                shots[-1]["shot_type"] = "ECU"
            if shots[-1]["sfx"] == "NONE":
                shots[-1]["sfx"] = "mixkit-cinematic-trailer-riser-790.wav"
        print(f"  [LLM] Shot {len(shots)}: [{shot_type}|{angle}] char={character} {scene[:50]}... (sfx={sfx}, tone={tone})")
        time.sleep(0.3)

    if not shots:
        print("  [LLM] Shot list failed, building fallback from narration")
        for i, para in enumerate(narration_paras[:12]):
            shots.append({
                "narration": para,
                "narration_idx": i,
                "shot_type": ["EWS", "WS", "MS", "CU", "ECU"][i % 5],
                "angle": ["eye-level", "low-angle", "high-angle", "over-the-shoulder", "from-behind"][i % 5],
                "character": "NONE" if i % 4 == 0 else f"Character{i}",
                "character_role": "protagonist",
                "scene": f"3D animated character in a dark cinematic documentary scene, dramatic lighting, {RENDER_STYLE}",
                "sfx": "NONE",
                "tone": "suspense" if i < len(narration_paras) - 2 else "triumphant",
            })
    shots = _merge_character_aliases(shots)
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
    "You are a character designer for SPLIT NODE, a 3D documentary channel "
    "(Unreal Engine 5 / Metahuman photorealistic 3D render style, perfect anatomy, "
    "realistic skin). You create PRECISE, REPEATABLE text character "
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
        "hints": ["ceo", "executive", "founder", "director", "chairman", "president of", "boss", "owner", "tycoon", "magnate"],
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


def _assign_archetype(name: str, role: str = "", scene: str = "") -> dict:
    """Map a story character (name + role) to the closest fixed archetype.

    Role keywords win; gender/age words in the role/scene drive the generic
    everyman fallback. Returns a CHARACTER_ROSTER dict (never None) so every
    story person gets a consistent, repeatable Metahuman look.
    """
    rl = f"{role} {scene}".lower()
    for arch in CHARACTER_ROSTER:
        if any(h in rl for h in arch["hints"]):
            return arch
    female = bool(re.search(r"\b(female|woman|women|girl|she|her|madam|lady|grandmother)\b", rl))
    old = bool(re.search(r"\b(old|elderly|60s|70s|80s|senior|retiree|grandmother|grandfather)\b", rl))
    young = bool(re.search(r"\b(young|teen|student|20s|twenties|intern)\b", rl))
    if female:
        return _roster_by_id("old-female" if old else "young-female" if young else "mid40s-female")
    return _roster_by_id("old-male" if old else "young-male" if young else "mid40s-male")


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


def _build_character_sheets(shots: list[dict], narration: list[str]) -> dict:
    """Map every unique story character to a FIXED roster archetype.

    Deterministic (no LLM, no cost, zero per-episode variance): a character's
    look comes from the static 20-archetype roster, so 'the hacker' looks the
    same in every episode. Falls back to the generic everyman archetype.
    """
    canon = _character_canonical_map(shots)
    sheets = {}
    for s in shots:
        c = canon.get(s.get("character", "NONE"), "NONE")
        if c == "NONE" or c in sheets:
            continue
        role = s.get("character_role", "")
        arch = _assign_archetype(c, role, s.get("scene", ""))
        sheets[c] = _character_sheet_from_archetype(arch, c, role)
        print(f"  [CAST] {c} -> {arch['label']}"
              f"{f' (role: {role})' if role else ''}")
    print(f"  [CAST] {len(sheets)} characters assigned from the fixed roster")
    return sheets

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

def _character_prompt_block(sheet: dict, angle: str) -> str:
    """Build the full prepend block for a character in a shot: identity + angle view."""
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
    # Full body canonical description last as the anchor (always included when
    # present - it carries the full outfit, so dropping it would lose the clothing)
    if sheet.get("full_body"):
        parts.append(f"Canonical: {sheet['full_body']}")
    return " ".join(parts)

# -- RunPod Z-Image-Turbo --------------------------------------------

def _runpod_generate(prompt: str, seed: int, size: str = "1280*720",
                     timeout: int = 240, out_dir: Optional[Path] = None) -> Optional[str]:
    out_dir = out_dir or SHOTS_DIR
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
    # Easter egg: inject the hidden background element into this shot's prompt
    # (set on exactly one shot by _inject_easter_egg).
    egg = shot.get("easter_egg_prompt")
    if egg:
        scene = (scene + " " + egg).strip()
    chars = _parse_shot_characters(shot)
    if not chars:
        # No character (establishing/landscape/object/hand-closeup shot) - use
        # the scene-only style with zero human language so no person appears.
        return (
            f"{SCENE_STYLE}. {scene}{cam_desc}, "
            f"16:9 widescreen cinematic documentary frame, EXACTLY ONE "
            f"continuous scene, one location, no collage, no split panels, "
            f"no duplicated scenes"
        )
    facing_txt = {"left": "facing left", "right": "facing right",
                  "front": "facing the camera", "back": "seen from behind",
                  "behind": "seen from behind"}
    blocks = []
    for ch in chars:
        name = ch["name"]
        sheet = _sheet_for_name(character_sheets, name)
        cb = _character_prompt_block(sheet, angle) if sheet else ""
        if not cb:
            cb = f"a person named {name}"
        facing = facing_txt.get(ch["facing"], "facing the camera")
        blocks.append(f"{cb} ({facing})")
    char_part = " ".join(blocks)
    return (
        f"{RENDER_STYLE}. {char_part}. {scene}{cam_desc}, "
        f"16:9 widescreen cinematic documentary frame, EXACTLY ONE continuous "
        f"scene, no collage, no duplicated figures"
    )


def _get_output_resolution() -> tuple:
    """(W, H) for the final image/video output - RESOLUTION env var.
    1080p (default) or 4K (3840x2160). Overridden by a per-run prompt that is
    persisted in resume state."""
    r = os.environ.get("RESOLUTION", "1080p").strip().lower()
    return (3840, 2160) if r.startswith("4k") or r in ("2160p", "uhd") else (1920, 1080)


def _ask_resolution() -> str:
    """Interactive resolution selection (1080p or 4K) - affects the image
    upscale target AND the final FFmpeg video output. RESOLUTION env var
    overrides the prompt; returns the chosen key ('1080p' or '4k')."""
    if os.environ.get("RESOLUTION"):
        r = os.environ.get("RESOLUTION").strip().lower()
        return "4k" if r.startswith("4k") or r in ("2160p", "uhd") else "1080p"
    print("\n  Output resolution (affects image upscale target + final video):")
    while True:
        resp = input("  1080p or 4K? [1080p]: ").strip().lower()
        if resp in ("4k", "2160p", "uhd", "4"):
            return "4k"
        if resp in ("1080p", "1080", "hd", ""):
            return "1080p"
        print(f"  [WARN] '{resp}' not recognised - enter 1080p or 4K")


def _ask_image_regen() -> bool:
    """Ask whether to RESUME existing episode images (keep what's already
    rendered) or RE-GENERATE everything (overwrite). REGEN_IMAGES env var
    overrides the prompt ('1'/'yes' = regenerate, '0'/'no' = resume)."""
    if os.environ.get("REGEN_IMAGES"):
        return os.environ["REGEN_IMAGES"].strip().lower() in ("1", "yes", "y", "true")
    print("\n  Image generation mode:")
    print("  [RESUME]  keep already-rendered images, only generate the missing ones")
    print("  [REGEN]   re-generate ALL images, overwriting existing ones")
    while True:
        resp = input("  Resume or regenerate? (R/e): ").strip().lower()
        if resp in ("", "r", "resume"):
            return False
        if resp in ("e", "regen", "regenerate", "regenerate"):
            return True
        print(f"  [WARN] '{resp}' not recognised - enter R (resume) or E (regenerate)")


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
    print("    2. fal       - fal.ai GPT Image 2 (default, best text rendering)")
    print("    3. runpod    - RunPod z-image-turbo")
    print("    4. codex     - Codex CLI /imagegen (local GPT Image 2, if installed)")
    while True:
        resp = input("  Pick 1-4 [2]: ").strip().lower()
        if resp in ("", "2", "fal"):
            return "fal", "gpt-image-2"
        if resp in ("1", "local"):
            return "local", "krea2-turbo"
        if resp in ("3", "runpod"):
            return "runpod", "z-image-turbo"
        if resp in ("4", "codex"):
            return "codex", "gpt-image-2"
        print(f"  [WARN] '{resp}' not recognised - enter 1, 2, 3 or 4")


def _black_placeholder(episode_num: int) -> str:
    """WxH pure-black PNG used for chapter title placeholder clips."""
    W_RES, H_RES = _get_output_resolution()
    ep_dir = SHOTS_DIR / f"ep{episode_num:03d}"
    ep_dir.mkdir(parents=True, exist_ok=True)
    out = str(ep_dir / "_black.png")
    if os.path.isfile(out) and os.path.getsize(out) > 1000:
        return out
    from PIL import Image
    Image.new("RGB", (W_RES, H_RES), (0, 0, 0)).save(out)
    return out


def _krea_generate(prompt: str, seed: int, out_path: str,
                   ref_images: Optional[list] = None, denoise: float = 0.55,
                   upscale: bool = True, timeout: int = 1800,
                   steps: int = 8, cfg: float = 1.0,
                   width: int = 1280, height: int = 720,
                   ref_mode: str = "img2img",
                   ref_method: str = "index_timestep_zero",
                   ref_boost: float = 4.0, grounding_px: int = 1024,
                   ref_images_b: Optional[list] = None) -> bool:
    """Generate one image, routed through the unified provider layer.

    Backend is selected at runtime by IMAGE_BACKEND (default 'local' ->
    ComfyUI Krea 2 Turbo). Set IMAGE_BACKEND=runpod or =fal to render shots
    through a cloud provider instead (ref_images/ref_mode only apply to the
    local backend - cloud models are text-to-image). Cloud providers need a
    RUNPOD_API_KEY / FAL_API_KEY in .env.
    """
    backend = (os.environ.get("IMAGE_BACKEND", "") or "local").strip().lower()
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
        grounding_px=grounding_px, ref_images_b=ref_images_b)


def _generate_motion_clip(prompt: str, out_path: str,
                          image_path: Optional[str] = None,
                          duration: int = 6, timeout: int = 1200) -> bool:
    """Generate an AI motion clip from a shot (or text prompt) via the
    selected VIDEO_BACKEND (runpod/fal). For local video, a ComfyUI video
    workflow must be installed. Returns True on success.

    Wired via env vars: VIDEO_BACKEND (default runpod), VIDEO_MODEL."""
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
        person_ok = bool(person and person.group(1).upper() == "YES")
        text_ok = bool(text and text.group(1).upper() == "NO")
        print(f"  [REALREF] audit: person={person.group(1) if person else '?'} "
              f"text/logo/watermark={'PRESENT' if text and text.group(1).upper()=='YES' else 'clean'}")
        return person_ok and text_ok
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
    the default/custom. Reads STYLE / STYLE_PROFILE env, then the resume style."""
    sel = (os.environ.get("STYLE") or os.environ.get("STYLE_PROFILE") or "").strip()
    if not sel and _RESUME_STYLE:
        sel = str(_RESUME_STYLE)
    low = sel.lower()
    if low in _load_style_profiles():
        return low
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


def _find_real_reference(char_name: str, role: str) -> Optional[str]:
    """Search GOOGLE IMAGES (SerpAPI, Openverse fallback) for a photo of the
    REAL person from the story and cache it to cast_refs/real/. Returns None
    when nothing usable is found (the sheet then falls back to txt2img)."""
    safe = re.sub(r"[^A-Za-z0-9]+", "_", char_name.lower()).strip("_") or "char"
    out = REAL_REFS_DIR / f"{safe}.jpg"
    if out.is_file():
        print(f"  [REALREF] reuse {os.path.basename(out)}")
        return str(out)
    urls = _google_images_candidates(char_name, role)
    if not urls:
        urls = _openverse_candidates(char_name, role)
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
                REAL_REFS_DIR.mkdir(parents=True, exist_ok=True)
                out.write_bytes(blob)
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


def _commons_logo_bytes(brand: str) -> Optional[bytes]:
    """Official logo from Wikimedia Commons, rasterized to a 512px PNG thumb.
    Returns raw image bytes, or None if unavailable (caller falls back to
    SerpAPI image search)."""
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
    "1. List ONLY real companies/brands mentioned (e.g. OpenAI, Tesla, Nike, "
    "Google). Skip generic nouns ('the company', 'the bank'), people, places, "
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
    """'building' if the text talks about the brand's HQ/physical location,
    else 'screen'."""
    low_name = name.lower()
    for t in texts:
        low = (t or "").lower()
        if low_name in low and any(w in low for w in HQ_WORDS):
            return "building"
    return "screen"


def _find_logo(brand: str) -> Optional[str]:
    """Logo for a brand, cached to cast_refs/logos/. Cache-first, then the
    OFFICIAL Wikimedia Commons source, and ONLY then SerpAPI image search
    (Openverse fallback) for brands not in the official registry."""
    safe = _brand_safe(brand)
    out = BRAND_LOGO_DIR / f"{safe}.png"
    if out.is_file():
        return str(out)
    # 1. Official source: Wikimedia Commons (rasterized PNG thumb)
    if brand in OFFICIAL_LOGOS:
        blob = _commons_logo_bytes(brand)
        if blob:
            BRAND_LOGO_DIR.mkdir(parents=True, exist_ok=True)
            out.write_bytes(blob)
            print(f"  [LOGO] {brand} cached (official Wikimedia)")
            return str(out)
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
        for attempt in (1, 2):
            try:
                req = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=25) as r:
                    blob = r.read()
                if len(blob) < 5000:
                    break
                BRAND_LOGO_DIR.mkdir(parents=True, exist_ok=True)
                out.write_bytes(blob)
                print(f"  [LOGO] {brand} cached <- {u[:70]}")
                return str(out)
            except Exception as e:
                if attempt == 2:
                    print(f"  [LOGO] download failed {u[:50]} ({str(e)[:50]})")
    return None


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
      kind='screen'   -> hacker computer screen with the real logo,
                         refs = [prop style sheet, logo]
      kind='building' -> the logo on a building, refs = [location style sheet, logo]
    """
    safe = _brand_safe(brand)
    out_dir = BRAND_SCREEN_DIR if kind == "screen" else BRAND_BUILDING_DIR
    out = out_dir / f"{safe}.png"
    if out.is_file():
        print(f"  [BRAND] reuse {os.path.basename(out)}")
        return str(out)
    logo = _find_logo(brand)
    if not logo:
        print(f"  [BRAND] no logo for '{brand}' - skipping {kind} asset")
        return None
    if kind == "building" and not os.path.isfile(str(LOCATION_STYLE_REF)):
        print(f"  [BRAND] no location style sheet - skipping building asset")
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
    """Rebuild {brand: {'screen': path, 'building': path}} from the on-disk
    caches + brand manifest (covers resume runs)."""
    _load_brand_manifest()
    out: dict[str, dict[str, str]] = {}
    for d, kind in ((BRAND_SCREEN_DIR, "screen"),
                    (BRAND_BUILDING_DIR, "building")):
        if d.is_dir():
            for f in sorted(d.glob("*.png")):
                for name in _KNOWN_BRANDS:
                    if _brand_safe(name) == f.stem:
                        out.setdefault(name, {})[kind] = str(f)
                        break
    return out


def _match_brand_asset(scene: str, brand_assets: dict) -> Optional[str]:
    """Pick the right brand asset for a shot: scene mentions a brand -> HQ-ish
    scene text gets the building asset, otherwise the hacker screen."""
    if not scene or not brand_assets:
        return None
    low = scene.lower()
    for name, assets in brand_assets.items():
        if name.lower() not in low:
            continue
        if any(w in low for w in HQ_WORDS):
            if assets.get("building"):
                return assets["building"]
        if assets.get("screen"):
            return assets["screen"]
        if assets.get("building"):
            return assets["building"]
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
    if os.environ.get("LOCATION_SHEETS", "1") == "0":
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
    if os.environ.get("PROP_SHEETS", "1") == "0":
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
    'Name(left)'. Defaults facing from the shot's scene/angle heuristics."""
    raw = str(shot.get("character", "NONE")).strip()
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
    scene = (shot.get("scene") or "").lower()
    return bool(re.search(
        r"(?i)\b(hq|headquarters|head office|office|corporate|company|"
        r"startup|founded|boardroom|executive suite|lobby|factory floor|"
        r"data center|server room|warehouse|office building|signage|"
        r"storefront|lab|the office|their office|at the company)\b", scene))


def _select_shot_refs(shot, char_panels_cache, brand_assets=None):
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
    """
    refs, notes = [], []
    st = str(shot.get("shot_type", "")).upper()
    subject = _FRAMING_SUBJECT.get(st, "body")
    visible = _shot_uses_character(shot)
    scene = (shot.get("scene") or "").lower()
    for ch in _parse_shot_characters(shot):
        if not visible:
            break
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
    if brand_assets and _is_business_shot(shot):
        brand = _match_brand_asset(shot.get("scene", ""), brand_assets)
        if brand and brand not in refs and os.path.isfile(brand):
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
            p = (f"{RENDER_STYLE}. {char_block}. {view_desc}. 3D character "
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
                                ref_images=refs_full, denoise=denoise, upscale=False,
                                steps=10, width=CHAR_PANEL_W, height=CHAR_PANEL_H,
                                ref_mode="identity", ref_boost=boost,
                                grounding_px=g_px)
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
                                ref_images=ref, denoise=denoise, upscale=False,
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
                                upscale=False, steps=14,
                                width=CHAR_PANEL_W, height=CHAR_PANEL_H,
                                ref_mode="identity", ref_boost=boost,
                                grounding_px=g_px)
        else:
            # Text-hair fallback: no ref, prompt controls the whole material.
            print(f"  [SHEET] {view} {look} panel for {char_name} "
                  f"(txt2img, hair: '{hair[:50]}')...")
            ok = _krea_generate(p, seed + 111 * len(view), str(pan),
                                ref_images=None, denoise=denoise, upscale=False,
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
    across every shot. Returns {char_name -> {view: panel_path}}."""
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
    for nm in seen_names:
        if nm in sheets_cache:
            continue
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
            continue
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
    return sheets_cache


def _generate_all_shots(shots: list[dict], character_sheets: Optional[dict] = None,
                        episode_num: int = 0,
                        context: Optional[dict] = None,
                        location_sheets: Optional[dict] = None,
                        prop_assets: Optional[dict] = None,
                        brand_assets: Optional[dict] = None) -> list[dict]:
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
    ep_dir = SHOTS_DIR / f"ep{episode_num:03d}" if episode_num else None
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
                                                 ep_dir or SHOTS_DIR)
    if prop_assets is None and context:
        prop_assets = _build_prop_assets(context, 43000 + episode_num * 7,
                                         ep_dir or SHOTS_DIR)
    location_sheets = location_sheets or {}
    prop_assets = prop_assets or {}
    print(f"\n[IMAGES] Generating {len(shots)} 3D shots via local Krea 2 Turbo "
          f"(1280x720 -> in-graph FaceUpDAT 1920x1080)...")
    # ---- PANELS FIRST (dedicated pass) ----
    # Generate EVERY character's six identity panels up front, before any shot
    # renders. A face-panel failure is retried and resolved here so it can't
    # cascade into every shot missing a face.
    sheets: dict[str, dict] = {}
    if face_lock and sheets_dir:
        sheets = _build_all_character_sheets(
            shots, character_sheets, sheets_dir, 70000 + episode_num,
            sheets_cache=sheets)
    _img_iter = (tqdm(shots, desc="  [IMAGES] rendering shots", unit="shot",
                      leave=False) if _HAS_PROGRESS else shots)
    for idx, shot in enumerate(_img_iter):
        if _HAS_PROGRESS:
            _img_iter.set_description(
                f"  [IMAGES] shot {idx+1}/{len(shots)}")
        if shot.get("is_chapter"):
            shot["seed"] = 0
            shot["image_path"] = black
            print(f"  [SHOT {idx+1}/{len(shots)}] chapter placeholder (no image)")
            continue
        # REGEN_IMAGES=1 -> force re-generate (overwrite) instead of resuming.
        _regen = os.environ.get("REGEN_IMAGES", "0").strip().lower() in ("1", "yes", "y", "true")
        if not _regen and shot.get("image_path") and os.path.isfile(shot["image_path"]):
            print(f"  [SHOT {idx+1}/{len(shots)}] resume: keep "
                  f"{os.path.basename(shot['image_path'])}")
            continue
        seed = 10000 + idx * 137 + random.randint(0, 999)
        prompt = _build_shot_prompt(shot, character_sheets) + " " + _style_inject()
        # Panels were built up front by _build_all_character_sheets (before the
        # shot loop); _select_shot_refs just picks the PERFECT panel(s) here.
        refs, notes = _select_shot_refs(shot, sheets, brand_assets)
        out_path = str((ep_dir or SHOTS_DIR) / f"shot_{seed}.png")
        n = len(refs)
        if refs:
            # single ref -> tight identity boost; multiple refs -> lower boost
            # so the char/logo panels don't bleed into each other.
            boost = 4.0 if n == 1 else 2.5
            g_px = 768 if n == 1 else 1024
            ok = _krea_generate(prompt, seed, out_path,
                                ref_images=refs, denoise=1.0,
                                ref_mode="identity", ref_boost=boost,
                                grounding_px=g_px, upscale=True)
        else:
            ok = _krea_generate(prompt, seed, out_path,
                                ref_images=None, denoise=1.0, upscale=True)
        if not ok:
            # one retry with a fresh seed
            seed2 = seed + 31337
            out2 = str((ep_dir or SHOTS_DIR) / f"shot_{seed2}.png")
            print(f"  [SHOT {idx+1}/{len(shots)}] retrying with new seed...")
            if refs:
                ok = _krea_generate(prompt, seed2, out2,
                                    ref_images=refs, denoise=1.0,
                                    ref_mode="identity", ref_boost=boost,
                                    grounding_px=g_px, upscale=True)
            else:
                ok = _krea_generate(prompt, seed2, out2,
                                    ref_images=None, denoise=1.0, upscale=True)
            if ok:
                seed, out_path = seed2, out2
        shot["seed"] = seed
        shot["image_path"] = out_path if ok else None
        if ok:
            # Shot images come out 1920x1080 from the in-graph FaceUpDAT
            # upscale - just apply the style-card grade.
            _apply_grade(out_path)
            label = notes if notes else "txt2img (no refs)"
            print(f"  [SHOT {idx+1}/{len(shots)}] image ready -> refs: {label}")
        else:
            print(f"  [SHOT {idx+1}/{len(shots)}] IMAGE FAILED after retry")
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
                results: dict, stop: threading.Event) -> None:
    """Background worker: queue EVERY narration paragraph into the PocketTTS
    server, one at a time, with retries. Runs concurrently with the shot list,
    character sheets and image generation (the big time win of the pipeline).

    results[i] = path of the finished clip (or None on failure). Files are
    named by NARRATION index (narration_{i:02d}.wav) so they map 1:1 to shots
    via shot['narration_idx'] even when shot parsing skips a paragraph.
    """
    ep_dir = TTS_TEMP / f"ep_{episode_num}"
    ep_dir.mkdir(parents=True, exist_ok=True)
    for i, text in enumerate(narration_paras):
        if stop.is_set():
            results[i] = None
            continue
        out = str(ep_dir / f"narration_{i:02d}.wav")
        if os.path.isfile(out) and os.path.getsize(out) > 1000:
            results[i] = out
            print(f"  [TTS {i+1}/{len(narration_paras)}] reused ({_get_audio_duration(out):.1f}s)")
            continue
        ok = False
        for attempt in range(3):
            if _pocket_tts_generate(text, out):
                _normalize_voice_0db(out)
                ok = os.path.isfile(out) and os.path.getsize(out) > 1000
                if ok:
                    break
            time.sleep(1 + attempt)
        if ok:
            results[i] = out
            print(f"  [TTS {i+1}/{len(narration_paras)}] {_get_audio_duration(out):.1f}s - {text[:50]}...")
        else:
            results[i] = None
            print(f"  [TTS {i+1}/{len(narration_paras)}] FAILED after retries - {text[:50]}...")
        time.sleep(0.2)


def _start_tts_worker(narration_paras: list[str], episode_num: int):
    """Kick off TTS generation in a background thread. Returns (thread, results,
    stop_event). Join the thread before rendering."""
    print(f"\n[TTS] Queueing {len(narration_paras)} narration clips into PocketTTS "
          f"({TTS_VOICE}) in the background...")
    results: dict[int, Optional[str]] = {}
    stop = threading.Event()
    t = threading.Thread(target=_tts_worker,
                         args=(narration_paras, episode_num, results, stop),
                         daemon=True)
    t.start()
    return t, results, stop


def _finalize_tts(shots: list[dict], results: dict, episode_num: int) -> None:
    """Map finished TTS clips onto shots by narration index."""
    ep_dir = TTS_TEMP / f"ep_{episode_num}"
    for pos, shot in enumerate(shots):
        nidx = shot.get("narration_idx", pos)
        if shot.get("is_chapter"):
            shot["tts_path"] = str(ep_dir / f"narration_{nidx:02d}.wav")
            continue
        # Per-character clone voices (voice_map.json) override the narrator
        voice = _lookup_voice(shot.get("character", "NONE"))
        if voice:
            out_v = str(ep_dir / f"narration_{nidx:02d}_char.wav")
            if _pocket_tts_generate(shot["narration"], out_v, voice=voice):
                _normalize_voice_0db(out_v)
                shot["tts_path"] = out_v
                continue
        path = results.get(nidx)
        if path and os.path.isfile(path):
            shot["tts_path"] = path
        else:
            # fallback: any file written by the worker at this narration index
            cand = str(ep_dir / f"narration_{nidx:02d}.wav")
            shot["tts_path"] = cand if os.path.isfile(cand) else None
    ok = sum(1 for s in shots if s.get("tts_path") and os.path.isfile(s["tts_path"]))
    print(f"  [TTS] {ok}/{len(shots)} clips ready (0dB)")


def _generate_all_tts(shots: list[dict], episode_num: int) -> None:
    """Sequential TTS (used by resume flows where parallelism isn't needed)."""
    print(f"\n[TTS] Generating {len(shots)} narration clips (built-in male voice: {TTS_VOICE})...")
    ep_dir = TTS_TEMP / f"ep_{episode_num}"
    ep_dir.mkdir(parents=True, exist_ok=True)
    for idx, shot in enumerate(shots):
        nidx = shot.get("narration_idx", idx)
        out = str(ep_dir / f"narration_{nidx:02d}.wav")
        ok = _pocket_tts_generate(shot["narration"], out,
                                  voice=_lookup_voice(shot.get("character", "NONE")))
        if ok:
            _normalize_voice_0db(out)
            dur = _get_audio_duration(out)
            print(f"  [TTS {idx+1}/{len(shots)}] {dur:.1f}s (0dB) - {shot['narration'][:50]}...")
        else:
            print(f"  [TTS {idx+1}/{len(shots)}] FAILED")
        shot["tts_path"] = out if ok else None
        time.sleep(0.5)

# -- Audio mix: voice + music + timecoded SFX ------------------------

def _build_audio_mix(shots: list[dict], episode_num: int,
                     title_events: Optional[list] = None):
    """Build the full audio track: voice (0dB) + music (-18dB) + SFX (-14dB hit-aligned).

    New SFX in this version:
      - mixkit glitchy suspense hit at t=0 (every video opens with it)
      - camera shutter at every new-character / new-location switch
      - typewriter clicks at each location/person title start (1.5s)
      - glitch-off at each title start + 5.5s (0.5s)

    Returns (mix_wav_path, voice_wav_path, clip_starts):
      voice_wav_path is the deterministic voice-only track (for whisper timing),
      clip_starts[i] is the REAL absolute start time of clip i (0.3s pads).
    """
    valid = [s for s in shots if s.get("tts_path") and os.path.isfile(s["tts_path"])]
    if not valid:
        print("  [AUDIO] No TTS clips")
        return None, None, []

    temp_dir = Path(tempfile.mkdtemp(prefix=f"sb_audio_{episode_num}_"))
    try:
        # -- Voice track: concat with 0.3s pads; REAL start times --
        voice_parts = []
        clip_starts = []  # absolute start time of each clip in the final timeline
        cursor = 0.0
        for shot in valid:
            clip_starts.append(cursor)
            d = _get_audio_duration(shot["tts_path"])
            voice_parts.append((shot["tts_path"], cursor, d))
            cursor += d + 0.3  # 0.3s pad after each clip (matches the pad files below)

        total_dur = cursor
        print(f"  [AUDIO] Voice timeline: {total_dur:.1f}s total, {len(valid)} clips")

        # Concat voice with silence pads
        concat_list = temp_dir / "voice_concat.txt"
        with open(concat_list, "w") as f:
            for path, start, d in voice_parts:
                f.write(f"file '{str(Path(path).resolve())}'\n")
                # pad 0.3s silence after each clip
                pad = temp_dir / f"pad_{int(start*1000)}.wav"
                subprocess.run(
                    ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                     f"anullsrc=r=24000:cl=mono", "-t", "0.3",
                     "-c:a", "pcm_s16le", str(pad)],
                    capture_output=True, text=True, timeout=30)
                f.write(f"file '{str(pad.resolve())}'\n")
        voice_raw = temp_dir / "voice_raw.wav"
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
             "-i", str(concat_list), "-c:a", "pcm_s16le", str(voice_raw)],
            capture_output=True, text=True, timeout=120)
        voice_path = temp_dir / "voice_0db.wav"
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-i", str(voice_raw),
             "-af", f"volume={VOICE_DB}dB", "-c:a", "pcm_s16le", str(voice_path)],
            capture_output=True, text=True, timeout=60)
        # Deterministic copy of the voice-only track for the whisper title pass
        RENDERED_AUDIO.mkdir(parents=True, exist_ok=True)
        voice_out = str(RENDERED_AUDIO / f"ep{episode_num:03d}_voice.wav")
        if os.path.isfile(voice_out) and os.path.getsize(voice_out) > 1000:
            pass
        else:
            shutil.copyfile(str(voice_path), voice_out)

        # -- Music bed: ONE continuous track, suspense 0-65% of the timeline
        #    crossfading into triumphant 65%-end. No per-shot cuts, no per-shot
        #    fades, no track cycling - the music runs uninterrupted under the
        #    whole episode and SFX sit on top (user: 'music running continuously').
        music_segments = []  # fallback path only
        music_path = None
        try:
            suspense_pool = MUSIC_LIBRARY["suspense"]
            triumphant_pool = MUSIC_LIBRARY["triumphant"]
            section_cut = total_dur * 0.65
            xf = 2.0  # crossfade seconds at the suspense->triumphant boundary

            def _pool_track(pool, idx):
                t = pool[idx % len(pool)]
                p = SFX_DIR / t
                return p if p.is_file() else None

            sus_src = _pool_track(suspense_pool, 0)
            tri_src = _pool_track(triumphant_pool, 0)
            if sus_src and tri_src and section_cut > 6 and (total_dur - section_cut) > 6:
                sus_raw = temp_dir / "music_sus_raw.wav"
                tri_raw = temp_dir / "music_tri_raw.wav"
                music_raw = temp_dir / "music_cont.wav"
                # stream_loop=-1 loops the source, -t trims to the section length
                ok1 = subprocess.run(
                    ["ffmpeg", "-y", "-v", "error", "-stream_loop", "-1",
                     "-i", str(sus_src), "-t", f"{section_cut:.2f}",
                     "-c:a", "pcm_s16le", "-ar", "24000", "-ac", "1", str(sus_raw)],
                    capture_output=True, text=True, timeout=180).returncode == 0
                ok2 = subprocess.run(
                    ["ffmpeg", "-y", "-v", "error", "-stream_loop", "-1",
                     "-i", str(tri_src), "-t", f"{total_dur - section_cut:.2f}",
                     "-c:a", "pcm_s16le", "-ar", "24000", "-ac", "1", str(tri_raw)],
                    capture_output=True, text=True, timeout=180).returncode == 0
                if ok1 and ok2 and sus_raw.is_file() and tri_raw.is_file():
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
                        print(f"  [AUDIO] Music: ONE continuous bed - suspense "
                              f"0-{section_cut:.0f}s, {xf:.0f}s crossfade into triumphant "
                              f"to {total_dur:.0f}s, -{abs(MUSIC_DB):.0f}dB, no per-shot cuts")
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
        placements = []
        # 1) Intro glitchy suspense hit at the very start of every video
        intro = SFX_DIR / TITLE_SFX["intro"]
        if intro.is_file():
            placements.append((str(intro), 0.0, 6.5))
            print("  [AUDIO] SFX intro glitch hit @0.0s")
        # 2) Per-shot LLM SFX (hit at shot start + 0.2s). Long ambience
        #    (soundscapes/nature run 20-60s) is capped at 10s so it beds under
        #    the shot without bleeding across the whole video.
        for shot, start in zip(valid, clip_starts):
            name = shot.get("sfx", "NONE")
            if name == "NONE" or name not in SFX_LIBRARY:
                continue
            src = _sfx_path(name)
            if src:
                cap = min(SFX_LIBRARY.get(name, {}).get("dur", 8.0), 10.0)
                placements.append((str(src), start + 0.2, cap))
        # 2b) FOLEY PIPELINE - detect the ACTION in each shot's scene text and
        #     bed the matching sound for the whole clip (typing -> typewriter,
        #     driving -> engine/traffic, walking -> footsteps, etc). Only runs
        #     when the LLM didn't already pick an sfx for that shot, so we
        #     don't stack a foley bed on top of a chosen dramatic hit.
        for pos, (shot, start) in enumerate(zip(valid, clip_starts)):
            if shot.get("is_chapter"):
                continue
            if shot.get("sfx", "NONE") != "NONE":
                continue  # LLM already scored this shot with an sfx
            foley = _foley_for_scene(shot.get("scene", ""))
            if not foley:
                continue
            fsrc = _sfx_path(foley)
            if not fsrc:
                continue
            # Bed the foley for the length of this clip (bounded to the sound's
            # own duration, so a long ambience doesn't bleed into the next shot).
            end = (clip_starts[pos + 1] if pos + 1 < len(clip_starts)
                   else start + 6.0)
            bed = max(1.5, min(end - start - 0.2, 8.0))
            placements.append((str(fsrc), start + 0.2, bed))
            print(f"  [AUDIO] FOLEY '{foley}' @{start + 0.2:.1f}s "
                  f"(bed {bed:.1f}s) for action in shot {pos + 1}")
        # 3) Camera shutter + whoosh: new character introduced OR new location
        #    (whoosh only when the LLM didn't already pick an sfx for the shot,
        #    so we never triple-stack sounds on one beat).
        rng = random.Random(episode_num * 7)
        def _pick_sfx(prefix: str) -> Optional[str]:
            ks = [k for k in SFX_LIBRARY
                  if k.startswith(prefix) and _sfx_path(k)]
            return rng.choice(ks) if ks else None
        loc_paras = {ev["para_idx"] for ev in (title_events or [])
                     if ev.get("kind") == "location"}
        prev_char = None
        for pos, (shot, start) in enumerate(zip(valid, clip_starts)):
            if shot.get("is_chapter") or start < 2.0:
                continue
            ch = shot.get("character", "NONE")
            nidx = shot.get("narration_idx", pos)
            is_new_char = False
            if ch != "NONE":
                if prev_char is not None and ch != prev_char:
                    is_new_char = True
                prev_char = ch
            is_new_loc = nidx in loc_paras
            if is_new_char or is_new_loc:
                shutter = SFX_DIR / TITLE_SFX["shutter"]
                if shutter.is_file():
                    placements.append((str(shutter), start + 0.1, None))
                    print(f"  [AUDIO] Camera shutter @{start + 0.1:.1f}s "
                          f"({'new char ' + ch if is_new_char else ''}"
                          f"{'new location' if is_new_loc else ''})")
                if shot.get("sfx", "NONE") == "NONE":
                    wkey = (_pick_sfx("whoosh-") if is_new_char
                            else _pick_sfx("sweep-"))
                    if wkey:
                        wm = SFX_LIBRARY[wkey]
                        placements.append((str(_sfx_path(wkey)),
                                           start + 0.15,
                                           wm.get("hit", 0.5) + 1.0))
                        print(f"  [AUDIO] {('Whoosh' if is_new_char else 'Sweep')} "
                              f"'{wkey}' @{start + 0.15:.1f}s")
        # 3b) Deterministic SFX: every chapter card gets a riser that builds
        #     INTO the card pop + a BOOM (Kick-Hit) landing exactly on it.
        #     Boom is Joe's pick (Aug 2026) - it punches through the mix.
        BOOM_NAME = "hit-kick"
        boom_path = _sfx_path(BOOM_NAME) if BOOM_NAME in SFX_LIBRARY else None
        for ev in title_events or []:
            if ev.get("kind") != "chapter":
                continue
            ct = ev.get("start", 0.0)
            if ct <= 1.0:
                continue
            riser = _pick_sfx("riser-")
            if riser:
                rm = SFX_LIBRARY[riser]
                placements.append((str(_sfx_path(riser)), ct - 0.15,
                                   rm.get("hit", 2.0) + 0.6))
                print(f"  [AUDIO] Chapter riser '{riser}' -> {ct:.1f}s")
            if boom_path:
                placements.append((str(boom_path), ct, 2.5))
                print(f"  [AUDIO] Chapter BOOM (Kick-Hit) @{ct:.1f}s")
            else:
                hit = _pick_sfx("hit-")
                if hit == "hit-shell-shock-high-ring-not-nice-for-ears":
                    hit = None  # ear-bleeding ring never goes on a chapter card
                if hit:
                    hm = SFX_LIBRARY[hit]
                    placements.append((str(_sfx_path(hit)), ct,
                                       hm.get("hit", 0.1) + 1.2))
                    print(f"  [AUDIO] Chapter hit '{hit}' @{ct:.1f}s")
        # 4) Typewriter clicks + glitch-off for every location/person title
        for ev in title_events or []:
            if ev.get("kind") not in ("location", "person"):
                continue
            st = ev.get("start", 0.0)
            tw = SFX_DIR / TITLE_SFX["typewriter"]
            gl = SFX_DIR / TITLE_SFX["glitch"]
            if tw.is_file():
                placements.append((str(tw), st, TYPEWRITER_SEC))
            if gl.is_file():
                placements.append((str(gl), st + TYPEWRITER_SEC + TITLE_HOLD_SEC, GLITCH_OFF_SEC))
        # Dedupe: two titles on the same paragraph fire at the same moment -
        # keep only ONE typewriter/glitch sound so the clicks don't double up.
        deduped = []
        for src, target, max_dur in placements:
            dup = False
            for d_src, d_tgt, _d_max in deduped:
                if d_src == src and abs(d_tgt - target) < 0.05:
                    dup = True
                    break
            if not dup:
                deduped.append((src, target, max_dur))
        placements = deduped
        # 5) Resolve placements -> delays/trims
        sfx_inputs, sfx_delays, sfx_trims, sfx_durs, sfx_dbs = [], [], [], [], []
        for src, target, max_dur in placements:
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
            sfx_dbs.append(SHUTTER_DB if name == TITLE_SFX["shutter"] else SFX_DB)
            print(f"  [AUDIO] SFX {name}: hit@{target:.1f}s (file hit={hit}s) -> "
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
            return None, None, clip_starts

        n_sfx = len(sfx_inputs)

        # Windows cmdline limit (WinError 206): one ffmpeg invocation with
        # every SFX input + its filter exceeds 32767 chars on long episodes
        # (hundreds of title SFX). Mix SFX in batches of BATCH into short
        # intermediate WAVs (filter graph written to a script file, never
        # the cmdline), then run one tiny final mix.
        final_wav = str(RENDERED_AUDIO / f"ep{episode_num:03d}_mix.wav")
        work = RENDERED_AUDIO / f"ep{episode_num:03d}_mixwork"
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
                return None, None, clip_starts
            batch_files.append(str(bfile))
            print(f"  [AUDIO] SFX batch {b // BATCH:02d}: {len(chunk)} sounds -> {bfile.name}")

        # Final mix: voice + music + SFX batch tracks (tiny, safe cmdline).
        fin_inputs, fin_parts = [], []
        if voice_path and os.path.isfile(voice_path):
            fin_inputs.append(str(voice_path))
            fin_parts.append(f"[{len(fin_inputs)-1}:a]aresample=44100,"
                             f"aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo"
                             f"[f{len(fin_inputs)-1}]")
        if music_path:
            fin_inputs.append(music_path)
            fin_parts.append(f"[{len(fin_inputs)-1}:a]aresample=44100,"
                             f"aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo"
                             f"[f{len(fin_inputs)-1}]")
        for bf in batch_files:
            fin_inputs.append(bf)
            fin_parts.append(f"[{len(fin_inputs)-1}:a]aresample=44100,"
                             f"aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo"
                             f"[f{len(fin_inputs)-1}]")
        n_fin = len(fin_inputs)
        fin_labels = "".join(f"[f{i}]" for i in range(n_fin))
        fscript = work / "final_mix.txt"
        fscript.write_text(";".join(fin_parts) + ";" + fin_labels +
                           f"amix=inputs={n_fin}:duration=first:normalize=0,"
                           f"alimiter=limit=0.95,atrim=0:{total_dur:.2f}[out]",
                           encoding="utf-8")
        cmd = ["ffmpeg", "-y", "-v", "error"]
        for inp in fin_inputs:
            cmd += ["-i", inp]
        cmd += ["-filter_complex_script", str(fscript), "-map", "[out]",
                "-c:a", "pcm_s16le", "-ar", "44100", final_wav]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if r.returncode != 0 or not os.path.isfile(final_wav) or os.path.getsize(final_wav) < 1000:
            print(f"  [AUDIO] Mix failed: {r.stderr[-300:]}")
            return None, None, clip_starts
        dur = _get_audio_duration(final_wav)
        print(f"  [OK] Mixed audio: {_fmt_time(dur)}, {os.path.getsize(final_wav)//1024}KB -> {final_wav}")
        return final_wav, voice_out, clip_starts
    finally:
        shutil.rmtree(str(temp_dir), ignore_errors=True)
        try:
            shutil.rmtree(str(work), ignore_errors=True)
        except Exception:
            pass

# -- Whisper title pass (faster-whisper word timings) -----------------

def _transcribe_voice(episode_num: int, voice_path: Optional[str] = None) -> list[dict]:
    """Word-level timings of the voice track via faster-whisper (base, CPU).

    Cached to rendered_audio/ep{N:03d}_whisper.json (reused on resume; deleted
    when the episode completes). vad_filter=False is critical - TTS voices have
    no natural speech pauses and VAD returns EMPTY segments.
    """
    RENDERED_AUDIO.mkdir(parents=True, exist_ok=True)
    cache = str(RENDERED_AUDIO / WHISPER_JSON.format(ep=episode_num))
    if os.path.isfile(cache) and os.path.getsize(cache) > 100:
        try:
            words = json.loads(Path(cache).read_text())
            print(f"  [STT] whisper cache reused ({len(words)} words)")
            return words
        except Exception:
            pass
    if not voice_path or not os.path.isfile(voice_path):
        voice_path = str(RENDERED_AUDIO / f"ep{episode_num:03d}_voice.wav")
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
    # chapter -> find when "chapter N" is spoken
    for ev in chapter_events:
        pi = ev["para_idx"]
        fallback = (clip_starts[pi] + 0.4) if pi < len(clip_starts) else 0.0
        end = (clip_starts[pi + 1] if pi + 1 < len(clip_starts) else
               (clip_starts[pi] + 5.0)) if pi < len(clip_starts) else fallback + 4.0
        t = None
        num_words = {1: ["one", "1"], 2: ["two", "2"], 3: ["three", "3"],
                     4: ["four", "4"], 5: ["five", "5"], 6: ["six", "6"]}
        if words:
            for i, w in enumerate(words):
                wl = w["word"].strip(".,!?;:()\"'").lower()
                if wl != "chapter":
                    continue
                nxt = words[i + 1]["word"].strip(".,!?;:()\"'-").lower() if i + 1 < len(words) else ""
                if nxt in num_words.get(ev["chapter"], []):
                    t = w["start"]
                    break
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
                 black_frames: bool = False) -> bool:
    """Render one shot: slow-zoom image + narration audio -> 1080p clip.

    black_frames=True prepends 2 frames of pure black before the image
    (camera-shutter mimic when a new character/location is introduced).
    """
    W_RES, H_RES = _get_output_resolution()
    OV_W, OV_H = W_RES * 4, H_RES * 4   # 4x overscan -> sub-pixel zoom steps
    if not image_path or not os.path.isfile(image_path):
        image_path = fallback_img or ""
    if not image_path or not os.path.isfile(image_path):
        from PIL import Image
        img = Image.new("RGB", (W_RES, H_RES), (18, 18, 22))
        image_path = str(SHOTS_DIR / "_fallback_bg.png")
        img.save(image_path)
    dur = max(_get_audio_duration(audio_path), 0.5) + 0.6
    n_frames = max(int(dur * 24), 24)
    # Smooth zoom: upscale the source 4x with lanczos BEFORE zoompan so the
    # per-frame zoom steps are sub-pixel (measured: 4x prescale halves the
    # frame-to-frame motion variance vs 2x - cv 0.73 -> 0.41 on noise imagery),
    # and zoom from the exact center so the crop never drifts.
    zoom_expr = f"z='if(eq(on,1),1,min(1+0.06*(on-1)/{max(n_frames-1,1)},1.06))'"
    chain = (
        f"[0:v]loop=1:size=1:start=0,"
        f"scale={OV_W}:{OV_H}:flags=lanczos:force_original_aspect_ratio=increase,"
        f"crop={OV_W}:{OV_H},"
        f"zoompan={zoom_expr}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
        f"d={n_frames}:s={W_RES}x{H_RES}:fps=24,"
        f"fade=t=in:st=0:d=0.3,fade=t=out:st={max(dur-0.3,0):.2f}:d=0.3"
    )
    if black_frames:
        # 2 frames of black at the very start = camera shutter between images
        chain += ",tpad=start=2:color=black"
    filter_graph = chain + "[vout]"
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
    Relative levels inside the mix are preserved: voice 0dB, music -18dB, SFX -14dB."""
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
    """Absolute start times of each clip in the voice/video timeline (0.3s pads).
    Must stay in sync with _build_audio_mix's cursor math."""
    starts, cursor = [], 0.0
    for s in shots:
        if not (s.get("tts_path") and os.path.isfile(s["tts_path"])):
            continue
        starts.append(cursor)
        cursor += _get_audio_duration(s["tts_path"]) + 0.3
    return starts


def _ensure_voice_track(shots: list[dict], episode_num: int) -> Optional[str]:
    """Build rendered_audio/ep{N:03d}_voice.wav if missing (same concat as the
    mix: clips + 0.3s pads). Used by the whisper title pass on resume."""
    RENDERED_AUDIO.mkdir(parents=True, exist_ok=True)
    out = str(RENDERED_AUDIO / f"ep{episode_num:03d}_voice.wav")
    if os.path.isfile(out) and os.path.getsize(out) > 1000:
        return out
    valid = [s for s in shots if s.get("tts_path") and os.path.isfile(s["tts_path"])]
    if not valid:
        return None
    temp_dir = Path(tempfile.mkdtemp(prefix=f"sb_voice_{episode_num}_"))
    try:
        concat_list = temp_dir / "vc.txt"
        with open(concat_list, "w") as f:
            for i, shot in enumerate(valid):
                f.write(f"file '{str(Path(shot['tts_path']).resolve())}'\n")
                pad = temp_dir / f"pad_{i}.wav"
                subprocess.run(
                    ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                     "anullsrc=r=24000:cl=mono", "-t", "0.3",
                     "-c:a", "pcm_s16le", str(pad)],
                    capture_output=True, text=True, timeout=30)
                f.write(f"file '{str(pad.resolve())}'\n")
        r = subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
             "-i", str(concat_list), "-c:a", "pcm_s16le", out],
            capture_output=True, text=True, timeout=180)
        if r.returncode == 0 and os.path.isfile(out) and os.path.getsize(out) > 1000:
            return out
        print(f"  [STT] voice track build failed: {r.stderr[-200:]}")
        return None
    finally:
        shutil.rmtree(str(temp_dir), ignore_errors=True)


def _cleanup_stt_artifacts(episode_num: int) -> None:
    """Delete whisper/STT caches + title markers when the episode completes."""
    try:
        for p in RENDERED_AUDIO.glob(f"ep{episode_num:03d}_whisper.json"):
            p.unlink()
            print(f"  [CLEAN] removed {p.name}")
        for p in RENDERED_VIDEO.glob(f"split_node_ep{episode_num:03d}*.titled"):
            p.unlink()
        for p in RENDERED_VIDEO.glob(f"split_node_ep{episode_num:03d}_titles.ass"):
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


def _render_video(shots: list[dict], episode_num: int,
                  title_events: Optional[list] = None) -> str:
    """Render all shots into one 1080p video with full audio mix.

    title_events = RESOLVED title events ({kind, start, end, ...}) - used to
    (a) place typewriter/glitch/shutter SFX into the mix, and (b) burn the
    animated glowing titles in pass 2 after the render.
    """
    print("\n[VIDEO] Rendering 1080p documentary...")
    valid = [s for s in shots if s.get("tts_path") and os.path.isfile(s["tts_path"])]
    if not valid:
        print("  [FAIL] No TTS clips to render")
        return ""

    # Build the full audio mix first (voice+music+sfx+title sfx). Output path is
    # deterministic, so an already-finished mix is reused on resume.
    mixed_audio = str(RENDERED_AUDIO / f"ep{episode_num:03d}_mix.wav")
    if os.path.isfile(mixed_audio) and os.path.getsize(mixed_audio) > 1000:
        print(f"  [AUDIO] Mix exists, reusing ({os.path.getsize(mixed_audio)//1024}KB)")
    else:
        _build_audio_mix(valid, episode_num, title_events)
    if not os.path.isfile(mixed_audio) or os.path.getsize(mixed_audio) < 1000:
        print("  [WARN] Audio mix failed, falling back to voice-only concat")
        mixed_audio = ""

    shutter_paras = _camera_shutter_paras(valid, title_events)

    temp_dir = Path(tempfile.mkdtemp(prefix=f"sb_render_{episode_num}_"))
    clip_files = []
    try:
        fallback_img = str(SHOTS_DIR / "_fallback_bg.png")
        # Persistent clip folder: finished clips survive crashes so a resume
        # run skips re-rendering them. Deleted after the final video succeeds.
        clip_dir = BATCH_TEMP / f"ep{episode_num:03d}"
        clip_dir.mkdir(parents=True, exist_ok=True)
        reused = 0
        for idx, shot in enumerate(shots):
            if not (shot.get("tts_path") and os.path.isfile(shot["tts_path"])):
                continue
            clip_out = str(clip_dir / f"clip{idx:02d}.mp4")
            if (os.path.isfile(clip_out) and os.path.getsize(clip_out) > 1000
                    and _get_audio_duration(clip_out) > 0.5):
                clip_files.append(clip_out)
                reused += 1
                print(f"  [CLIP {idx+1}/{len(valid)}] reused from batch_temp")
                continue
            nidx = shot.get("narration_idx", idx)
            black_frames = nidx in shutter_paras
            ok = _render_clip(shot.get("image_path", ""), shot["tts_path"], clip_out,
                              fallback_img, black_frames=black_frames)
            if ok:
                clip_files.append(clip_out)
                print(f"  [CLIP {idx+1}/{len(valid)}] rendered"
                      f"{' (shutter: 2 black frames)' if black_frames else ''}")
            else:
                print(f"  [CLIP {idx+1}/{len(valid)}] FAILED")
        print(f"  [CLIPS] {reused}/{len(clip_files)} reused from batch_temp, "
              f"{len(clip_files) - reused} freshly rendered")

        if not clip_files:
            print("  [FAIL] No clips rendered")
            return ""

        concat_list = temp_dir / "concat.txt"
        with open(concat_list, "w") as f:
            for c in clip_files:
                f.write(f"file '{c}'\n")
        output_path = str(RENDERED_VIDEO / f"split_node_ep{episode_num:03d}.mp4")
        # Stream-copy concat (NO re-encode): every clip is rendered with identical
        # hevc_nvenc/aac params by _render_clip, so the demuxer merges them
        # losslessly and ~100x faster than re-encoding. Re-encoding 100+ files
        # through NVENC+AAC is the NaN AAC corruption failure mode (Qavg: 65461).
        if mixed_audio and os.path.isfile(mixed_audio):
            # Video only - the audio is replaced by the separate mix below
            concat_cmd = [
                "ffmpeg", "-y", "-v", "error", "-fflags", "+genpts",
                "-f", "concat", "-safe", "0",
                "-i", str(concat_list),
                "-c:v", "copy", "-an",
                "-movflags", "+faststart",
                output_path
            ]
        else:
            # No mix available: keep each clip's narration audio, still stream copy
            concat_cmd = [
                "ffmpeg", "-y", "-v", "error", "-fflags", "+genpts",
                "-f", "concat", "-safe", "0",
                "-i", str(concat_list),
                "-c:v", "copy", "-c:a", "copy",
                "-movflags", "+faststart",
                output_path
            ]
        r = subprocess.run(concat_cmd, capture_output=True, text=True, timeout=600)
        if r.returncode != 0 or not os.path.isfile(output_path) or os.path.getsize(output_path) < 1000:
            print(f"  [RENDER] Concat failed: {r.stderr[-200:]}")
            return ""

        # Mux the full mixed audio (voice + music + sfx) over the video,
        # with a final master gain so the loudest peak reaches 0dB
        # (voice 0dB, music -18dB, SFX -14dB relative in the mix).
        if mixed_audio and os.path.isfile(mixed_audio):
            final_path = str(RENDERED_VIDEO / f"split_node_ep{episode_num:03d}_final.mp4")
            master_filter = _master_gain_filter(mixed_audio)
            mux_cmd = [
                "ffmpeg", "-y", "-v", "error",
                "-i", output_path, "-i", mixed_audio,
                "-map", "0:v:0", "-map", "1:a:0",
                "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
            ]
            if master_filter:
                mux_cmd += ["-af", master_filter]
            mux_cmd += [
                "-avoid_negative_ts", "make_zero",
                "-movflags", "+faststart",
                "-shortest", final_path
            ]
            r2 = subprocess.run(mux_cmd, capture_output=True, text=True, timeout=300)
            if r2.returncode == 0 and os.path.isfile(final_path) and os.path.getsize(final_path) > 1000:
                _safe_replace(final_path, output_path)

        dur = _get_audio_duration(output_path)
        size_mb = os.path.getsize(output_path) / 1024 / 1024
        print(f"  [OK] 1080p video: {_fmt_time(dur)}, {size_mb:.1f}MB -> {output_path}")

        # -- PASS 2: burn animated glowing titles at whisper-matched times --
        if split_node_titles is not None and title_events:
            marker = output_path + ".titled"
            if os.path.isfile(marker):
                print("  [TITLES] already burned (marker present), skipping pass 2")
            else:
                ass_path = str(RENDERED_VIDEO / f"split_node_ep{episode_num:03d}_titles.ass")
                burned = str(RENDERED_VIDEO / f"split_node_ep{episode_num:03d}_titled.mp4")
                try:
                    split_node_titles.build_title_ass(title_events, ass_path)
                    print(f"  [TITLES] pass 2: burning {len(title_events)} title events...")
                    # Kicker + title are both inside the ASS now (Bahnschrift),
                    # no pre-rendered chapter clips needed.
                    if split_node_titles.burn_titles(
                            output_path, ass_path, burned, timeout=2400):
                        _safe_replace(burned, output_path)
                        Path(marker).write_text("1")
                        print("  [TITLES] burned OK (animated glowing titles)")
                except Exception as e:
                    print(f"  [TITLES] pass 2 failed: {e}")

        # Episode complete: clean up the batch clips
        for clip in clip_dir.glob("clip*.mp4"):
            try: clip.unlink()
            except: pass
        try: clip_dir.rmdir()
        except: pass
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

def _generate_thumbnail(topic: str, output_path: str) -> bool:
    print(f"  [THUMB] Generating thumbnail for: {topic[:60]}...")
    headline = _thumbnail_headline(topic)
    prompt = (
        "YouTube documentary thumbnail, bold animated animation style "
        "(painted look: strong stylized brushwork, saturated "
        "colors, dramatic rim lighting, cinematic painterly shading), "
        f"dramatic cinematic scene related to: {topic[:120]}. Moody lighting, "
        "dark color grade, high contrast, bold and clickable composition, "
        "16:9 landscape. "
        "Large bold uppercase text 'SPLIT NODE' in the top-left corner. "
        f"Large bold uppercase clickbait headline text '{headline}' centered in the "
        "lower third. Crisp legible text, high-impact YouTube thumbnail, FERN "
        "documentary channel style."
    )
    try:
        import providers
        ok = providers.generate_thumbnail(prompt, output_path, seed=70001)
        if ok and os.path.isfile(output_path) and os.path.getsize(output_path) > 1000:
            print(f"  [OK] Thumbnail: {os.path.getsize(output_path)//1024}KB -> {output_path}")
            return True
        print("  [FAIL] Thumbnail provider returned no usable image")
    except Exception as e:
        print(f"  [FAIL] Thumbnail error: {e}")
    return False

# -- Titles / description --------------------------------------------

def _generate_titles(topic: str, episode_num: int) -> list[str]:
    msg = [
        {"role": "system", "content": (
            "You are a viral YouTube title generator for 'Split Node' - a channel about "
            "ordinary people who beat the system. Write 3 clickbaity titles. "
            "Each starts with '#XXX - ' where XXX is the episode number. "
            "Use curiosity gaps, under 70 chars, reference the story topic directly. "
            "Return ONLY 3 lines, one title per line, no numbering."
        )},
        {"role": "user", "content": f"Episode #{episode_num:03d}\nTopic: {topic}\n\nWrite 3 titles."}
    ]
    text = _llm_chat(msg, max_tokens=250, temp=0.85)
    titles = [t.strip() for t in text.split("\n") if t.strip()]
    prefix = f"#{episode_num:03d} -"
    result = []
    for t in titles:
        if not t.startswith("#"):
            t = f"{prefix} {t}"
        elif prefix not in t:
            t = f"{prefix} {t.lstrip('#0123456789').lstrip('- ')}"
        result.append(t)
    while len(result) < 3:
        result.append(f"{prefix} The {topic[:40]} story that broke the system")
    result = result[:3]

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
    "You write YouTube video descriptions for SPLIT NODE, a 3D animated documentary "
    "channel (Unreal Engine / Metahuman style) telling true stories of ordinary people "
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

def _generate_description(topic: str, episode_num: int, article_url: str) -> str:
    msg = [
        {"role": "system", "content": DESCRIPTION_SYSTEM_PROMPT},
        {"role": "user", "content": (
            f"Episode #{episode_num:03d}\n"
            f"Topic: {topic}\n"
            f"Source article: {article_url}\n\n"
            f"Write the comprehensive YouTube description."
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
    if not YOUTUBE_CREDENTIALS.is_file():
        return None
    try:
        data = json.loads(YOUTUBE_CREDENTIALS.read_text())
        # Parse the stored expiry so google.auth can detect an expired token.
        # Without it, refresh never fires and the stale token gets 401s.
        expiry_raw = data.get("token_expiry") or data.get("expiry")
        expiry = None
        if expiry_raw:
            try:
                if isinstance(expiry_raw, str):
                    expiry_raw = expiry_raw.replace("Z", "+00:00")
                expiry = datetime.fromisoformat(expiry_raw)
                if expiry.tzinfo is not None:
                    # google.auth compares against naive UTC - strip the tz
                    expiry = expiry.astimezone(timezone.utc).replace(tzinfo=None)
            except Exception:
                expiry = None
        creds = GoogleCreds(
            token=data.get("access_token", data.get("token", "")),
            refresh_token=data.get("refresh_token"),
            client_id=data.get("client_id"),
            client_secret=data.get("client_secret"),
            token_uri=data.get("token_uri", "https://oauth2.googleapis.com/token"),
            scopes=data.get("scopes", ["https://www.googleapis.com/auth/youtube.upload"]),
            expiry=expiry,
        )
        if not creds.valid:
            creds.refresh(AuthRefresh())
            data["access_token"] = creds.token
            data["token"] = creds.token
            data["token_expiry"] = creds.expiry.isoformat() if creds.expiry else None
            data["expiry"] = data["token_expiry"]
            YOUTUBE_CREDENTIALS.write_text(json.dumps(data, indent=2))
            print("  [OK] YouTube token refreshed")
        return creds
    except Exception as e:
        print(f"  [WARN] Credential load failed: {e}")
        print("  [WARN] Re-authorize Split Node: python oauth_split_node.py")
        return None

def _upload_video_with_progress(video_path: str, title: str, description: str,
                                tags_str: str, privacy: str = "public") -> Optional[str]:
    creds = _get_youtube_creds()
    if not creds:
        return None
    file_size = os.path.getsize(video_path)
    body = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": tags_str.split(","),
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
        r = requests_post(
            "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status",
            headers=headers_init, json=body, timeout=30
        )
        if r.status_code != 200:
            print(f"  [WARN] Upload init failed (HTTP {r.status_code})")
            if r.status_code in (401, 403):
                print("  [WARN] Token invalid - re-run: python oauth_split_node.py")
            return None
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
            "model": "gemma-4-e4b-uncensored-hauhaucs-aggressive",
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

def _save_resume_state(stage: str, episode_num: int, article_url: str = "", topic: str = "",
                       shots: Optional[list] = None, character_sheets: Optional[dict] = None,
                       titles: Optional[list] = None, description: str = "",
                       tags: Optional[list] = None, thumb_path: str = "",
                       video_path: str = "", video_id: str = "",
                       chapter_events: Optional[list] = None,
                       anchor_events: Optional[list] = None,
                       location_sheets: Optional[dict] = None,
                       prop_assets: Optional[dict] = None,
                       target_paras: int = 0) -> None:
    """Save episode state so it can be resumed if interrupted."""
    state = {
        "version": 3,
        "stage": stage,
        "episode_num": episode_num,
        "article_url": article_url,
        "topic": topic,
        "style": _get_style_prompt(),
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
    }
    try:
        tmp = RESUME_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=2, default=str))
        tmp.replace(RESUME_FILE)
        # Backup: keep the previous good state alongside the main file so a
        # lost/corrupt/overwritten main file can never silently kill the
        # resume prompt (load falls back to the .bak).
        try:
            RESUME_FILE.with_name(RESUME_FILE.name + ".bak").write_text(
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
    """
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


def _clear_resume_state() -> None:
    try:
        for f in (RESUME_FILE, RESUME_FILE.with_name(RESUME_FILE.name + ".bak")):
            if f.exists():
                f.unlink()
        print("  [STATE] Resume state cleared")
    except Exception:
        pass


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

    # Resume keeps the exact style the episode was generated with (unless the
    # user overrides with STYLE=<profile>) OR picks a new style interactively.
    if state.get("style"):
        global _RESUME_STYLE
        _RESUME_STYLE = state.get("style")
    # If the user didn't force a style via env, ask which style to use for the
    # resumed images. Picking a style DIFFERENT from the resume style forces a
    # full re-generate (overwrite) so the new look actually applies.
    if not (os.environ.get("STYLE") or os.environ.get("STYLE_PROFILE")):
        _cur = _active_style_name()
        _chosen = _ask_style_selection(_cur)
        if _chosen and _chosen.lower() != _cur.lower():
            print(f"  [STYLE] changed {_cur or 'default'} -> {_chosen} - "
                  f"forcing full re-generate so the new look applies")
            os.environ["REGEN_IMAGES"] = "1"
        if _chosen:
            os.environ["STYLE"] = _chosen
    # Resume keeps the episode's output resolution too (unless RESOLUTION set).
    if state.get("resolution") and not os.environ.get("RESOLUTION"):
        os.environ["RESOLUTION"] = str(state.get("resolution"))

    def _save(stg):
        _save_resume_state(stg, episode_num, article_url, topic, shots,
                           character_sheets, titles, description, tags,
                           thumb_path, video_path, video_id,
                           chapter_events, anchor_events,
                           location_sheets, prop_assets,
                           target_paras=target_paras)

    # 1. Images: regenerate only the missing ones (same seeds -> same look),
    #    or ALL of them when REGEN_IMAGES=1 (a style change forces this so the
    #    new look applies to every shot).
    ep_shot_dir = SHOTS_DIR / f"ep{episode_num:03d}"
    _force_regen = os.environ.get("REGEN_IMAGES", "0").strip().lower() in ("1", "yes", "y", "true")
    if _force_regen:
        missing_img = [s for s in shots if not s.get("is_chapter")]
        print(f"\n[IMAGES] REGEN - re-generating ALL {len(missing_img)} shots (overwrite)")
    else:
        missing_img = [s for s in shots
                       if not (s.get("is_chapter") or
                               (s.get("image_path") and os.path.isfile(s["image_path"])))]
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
        # build would leave sheets empty across all 111 shots on a hiccup).
        if face_lock:
            sheets_cache = _build_all_character_sheets(
                missing_img, character_sheets, sheets_dir, 70000 + episode_num,
                sheets_cache=sheets_cache)
        # ---- Smart shot regen (matches the fresh loop) ----
        # Each character's SIX individual 1280x1280 panels are built once and
        # _select_shot_refs picks the PERFECT panel(s) per shot (framing,
        # facing, mirrored sides, multi-person, business logo). Style is
        # prompt-injected; no style-plate refs.
        _re_iter = (tqdm(missing_img, desc="  [IMAGES] regenerating missing",
                         unit="shot", leave=False)
                    if _HAS_PROGRESS else missing_img)
        for shot in _re_iter:
            chars = _parse_shot_characters(shot)
            seed = shot.get("seed") or (10000 + random.randint(0, 999))
            prompt = (_build_shot_prompt(shot, character_sheets)
                      + " " + _style_inject())
            if face_lock:
                # Panels were built up front by _build_all_character_sheets -
                # just confirm every char in this shot is present.
                for ch in chars:
                    if ch["name"] not in sheets_cache:
                        print(f"  [SHEET] {ch['name']} not in pre-built cache "
                              f"(face panel had failed) - shot renders w/o face ref")
            refs, notes = _select_shot_refs(shot, sheets_cache, brand_assets)
            out_path = str(ep_shot_dir / f"shot_{seed}.png")
            n = len(refs)
            if refs:
                # single ref -> tight identity boost; multiple refs -> lower
                # boost so the char/logo panels don't bleed into each other.
                boost = 4.0 if n == 1 else 2.5
                g_px = 768 if n == 1 else 1024
                ok = _krea_generate(prompt, seed, out_path,
                                    ref_images=refs, denoise=1.0,
                                    ref_mode="identity", ref_boost=boost,
                                    grounding_px=g_px, upscale=True)
            else:
                ok = _krea_generate(prompt, seed, out_path,
                                    ref_images=None, denoise=1.0, upscale=True)
            if not ok:
                seed2 = seed + 31337
                out2 = str(ep_shot_dir / f"shot_{seed2}.png")
                print("  [SHOT] retrying with new seed...")
                if refs:
                    ok = _krea_generate(prompt, seed2, out2,
                                        ref_images=refs, denoise=1.0,
                                        ref_mode="identity", ref_boost=boost,
                                        grounding_px=g_px, upscale=True)
                else:
                    ok = _krea_generate(prompt, seed2, out2,
                                        ref_images=None, denoise=1.0, upscale=True)
                if ok:
                    seed, out_path = seed2, out2
            shot["seed"] = seed
            shot["image_path"] = out_path if ok else None
            label = notes if notes else "txt2img (no refs)"
            print(f"  [SHOT] {'image ready' if ok else 'IMAGE FAILED - fallback'} "
                  f"-> refs: {label}")
            time.sleep(1)
        _save("images")
    else:
        print(f"  [RESUME] All {len(shots)} images present")

    # 2. TTS: regenerate only the missing narration clips
    missing_tts = [s for s in shots if not (s.get("tts_path") and os.path.isfile(s["tts_path"]))]
    if missing_tts:
        print(f"\n[TTS] Generating {len(missing_tts)} missing narration clips...")
        ep_dir = TTS_TEMP / f"ep_{episode_num}"
        ep_dir.mkdir(parents=True, exist_ok=True)
        for idx, shot in enumerate(missing_tts):
            nidx = shot.get("narration_idx", idx)
            out = str(ep_dir / f"narration_{nidx:02d}.wav")
            shot["tts_path"] = out
            ok = _pocket_tts_generate(shot["narration"], out)
            if ok:
                _normalize_voice_0db(out)
                print(f"  [TTS] {_get_audio_duration(out):.1f}s - {shot['narration'][:50]}...")
            else:
                print(f"  [TTS] FAILED - {shot['narration'][:50]}...")
            time.sleep(0.5)
        _save("tts")
    else:
        print(f"  [RESUME] All {len(shots)} TTS clips present")

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
        for ev in title_events:
            print(f"    [{ev['kind']}] @{ev['start']:.2f}s '{ev.get('text', ev.get('title', ''))}'")

    # 4. Video render - reuses finished clips in batch_temp + finished mix
    if video_path and os.path.isfile(video_path) and os.path.getsize(video_path) > 1000:
        print(f"  [RESUME] Video exists, skipping: {video_path}")
    else:
        print(f"\n[VIDEO] Rendering 1080p (finished clips reused from batch_temp)...")
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
        thumb_path = str(THUMBNAILS_DIR / f"ep{episode_num:03d}_thumb.png")
    thumb_ok = os.path.isfile(thumb_path) and os.path.getsize(thumb_path) > 1000
    if not thumb_ok:
        thumb_ok = _generate_thumbnail(topic, thumb_path)

    # 6. Upload (skip if already uploaded this episode)
    print(f"\n  {'='*50}\n  YOUTUBE UPLOAD ({CHANNEL_NAME})\n  {'='*50}")
    print(f"  Video: {video_path}")
    if video_id:
        print(f"  [RESUME] Already uploaded: https://youtu.be/{video_id}")
    elif YOUTUBE_UPLOAD_ENABLED:
        title = titles[0] if titles else f"#{episode_num:03d} - {topic[:60]}"
        print(f"  Title: {title}")
        video_id = _upload_video_with_progress(video_path, title, description, tags_str)
        if video_id and thumb_ok:
            _upload_thumbnail(video_id, thumb_path)
        if video_id:
            _add_video_to_playlist(video_id)
            EPISODE_COUNTER_FILE.write_text(str(episode_num))
            print(f"  [OK] Episode #{episode_num:03d} uploaded! https://youtu.be/{video_id}")
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
    _clear_resume_state()


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
    print_banner()
    _preflight()

    # Check for a resumable episode (state survives crashes until completion)
    resume_state = _load_resume_state()
    if resume_state:
        ep = resume_state.get("episode_num", 0)
        stg = resume_state.get("stage", "?")
        resp = input(f"\n  Resume episode #{ep:03d} (stage '{stg}')? [Y/n]: ").strip().lower()
        if resp not in ("n", "no"):
            _resume_episode(resume_state)
            return
        print("  [RESUME] Skipping - starting a fresh episode")

    # Ask for the episode number every run (default = last + 1)
    last_ep = _load_episode_num()
    default_ep = last_ep + 1
    resp = input(f"  Episode number? (enter for {default_ep}): ").strip()
    try:
        episode_num = int(resp) if resp else default_ep
    except ValueError:
        print(f"  [WARN] '{resp}' not a number, using {default_ep}")
        episode_num = default_ep
    print(f"\n  Episode #{episode_num:03d}")

    # 1a. Video length: paragraph target up front, with estimated runtime +
    #     confirm/change loop. Persisted to resume state so a resumed job
    #     sticks with the count it started with (never re-asked).
    target_paras = _ask_paragraph_target()
    print(f"  [LENGTH] Target {target_paras} narration paragraphs\n")

    # 1b. Output resolution: 1080p or 4K (affects the image upscale target AND
    #     the final FFmpeg video output). Persisted to resume state.
    res = _ask_resolution()
    os.environ["RESOLUTION"] = res
    print(f"  [RES] Output resolution: {res.upper()} "
          f"({_get_output_resolution()[0]}x{_get_output_resolution()[1]})\n")

    # 1c. Thumbnail provider: local / fal / runpod (sets THUMBNAIL_BACKEND).
    thumb_backend, thumb_model = _ask_thumbnail_backend()
    os.environ["THUMBNAIL_BACKEND"] = thumb_backend
    if thumb_model:
        os.environ["THUMBNAIL_MODEL"] = thumb_model
    print(f"  [THUMB] Thumbnail provider: {thumb_backend} ({thumb_model})\n")

    # 1d. Image generation mode: resume existing or re-generate (overwrite).
    #     Then pick the style; a style DIFFERENT from the current/resume style
    #     forces re-generate so the new look actually applies to the images.
    _cur_style = _active_style_name()
    regen_images = _ask_image_regen()
    chosen_style = _ask_style_selection(_cur_style)
    if chosen_style:
        os.environ["STYLE"] = chosen_style
    _style_changed = chosen_style and chosen_style.lower() != _cur_style.lower()
    if _style_changed:
        print(f"  [STYLE] changed {_cur_style or 'default'} -> {chosen_style} - "
              f"forcing re-generate so the new look applies")
        regen_images = True
    os.environ["REGEN_IMAGES"] = "1" if regen_images else "0"
    print(f"  [IMAGES] mode: {'RE-GENERATE (overwrite all)' if regen_images else 'resume (keep existing)'}\n")

    # Reusable episode template: load the last episode's winning formula
    tpl = _load_episode_template()
    if tpl:
        print(f"  [TEMPLATE] reuse ep{tpl.get('episode')} formula: "
              f"{tpl.get('topic', '')[:70]}")

    # 1. Find a story
    article_url, article_title = _pick_story()
    if not article_url:
        print("  [HALT] No story found. Check RSS feeds.")
        input("  Press Enter to exit...")
        return
    topic = article_title

    # 2. Fetch article
    paragraphs = fetch_article_paragraphs(article_url)
    if paragraphs:
        # LLM relevance rating: discard paragraphs scoring <= 4/10 so
        # off-topic webpage content (ads, self-promo) never reaches the narration
        paragraphs = _rate_paragraph_relevance(article_title, paragraphs)
    if not paragraphs:
        print("  [HALT] Could not extract article content.")
        input("  Press Enter to exit...")
        return

    # 3. Stage 1: narration script (Black Files style, cold open + anchors)
    narration = _build_narration_script(paragraphs, target_paras)

    # 3b. Rate each narration segment against the topic, discard <= 4/10
    if narration:
        narration = _rate_paragraph_relevance(article_title, narration)
        if not narration:
            print("  [FILTER] All narration segments off-topic, rebuilding from filtered article...")
            narration = _build_narration_script(paragraphs, target_paras)

    # 3c. Chapter pass: insert 'Chapter N - Title' paragraphs (black cards)
    narration, chapter_events = _insert_chapter_markers(narration)
    # 3d. Location/timeline anchors -> red/green bottom-left typewriter titles
    anchor_events = _extract_anchor_events(narration)

    # 3e. START TTS IN PARALLEL: queue ALL narration into PocketTTS in a
    # background thread, while the main thread builds the bible, scene board
    # and images. TTS and image gen run at the same time.
    tts_thread, tts_results, tts_stop = _start_tts_worker(narration, episode_num)

    # 3f. Episode world (works for ANY topic/environment/location)
    context = _build_episode_context(article_title, paragraphs)

    # 3g. Director's bible: deeper problem, transformation, chapter moods,
    #     hero paragraphs (ECU magnification) - the plan before any image.
    bible = _build_directors_bible(article_title, narration)

    # 3h. Scene board: one storyboard card per narration beat, saved to the
    #     episode folder for review before image generation.
    _build_scene_board(narration, article_title, episode_num)

    # 3i. Duration planning: per-chapter runtime estimates vs target length.
    _plan_durations(narration)

    # 3j. Style test frame (Krea 2 Turbo local) + human review gate.
    style_test = str(SHOTS_DIR / f"ep{episode_num:03d}" / "style_test.png")
    st_env = ", ".join(context.get("environments", [])) or "the primary setting"
    print("\n[STYLE] generating style test frame (Krea 2 Turbo local)...")
    _krea_generate(
        f"{RENDER_STYLE}. A moody establishing frame of the episode's main "
        f"environment: {st_env}. 16:9 widescreen cinematic documentary frame",
        4242 + episode_num, style_test)
    if os.path.isfile(style_test):
        print(f"  [STYLE] test frame: {style_test}")
        if not _gate("Approve style + director's bible? (n = rebuild bible)"):
            print("  [BIBLE] rebuilding with a fresh perspective...")
            bible = _build_directors_bible(article_title, narration)
    else:
        print("  [STYLE] test frame failed (ComfyUI not running?) - continuing")

    # 4. Stage 2: shot list from narration (bible + episode world injected;
    #    chapter paras become black cards)
    shots = _build_shot_list(narration, bible=bible, context=context)

    # 4a. Easter egg: ask whether to hide one, pick the egg (duck pope built-in
    #     or add-new), and inject it into EXACTLY one shot of the episode.
    easter_egg = _ask_easter_egg()
    if easter_egg:
        _inject_easter_egg(shots, easter_egg)

    # 4b. Stage 2b: character sheets for every named character
    character_sheets = _build_character_sheets(shots, narration)
    # 4c0. Brand logos: detect AI companies/models and real businesses in the
    #      article, ensure their logos are cached (search -> cache -> reuse),
    #      and render the context-appropriate asset: hacker computer screen
    #      (entity/product talk, prop style sheet + logo) or logo on a
    #      building (HQ talk, location style sheet + logo).
    brands = _extract_brands(article_title, paragraphs, narration)
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

    # 4c. Stage 2c: stylized location sheets (6-grid per location) + prop
    #     assets (front/back each) from the episode world - the STYLE chain:
    #     style plate styles these ASSETS, shots then use ONLY the styled
    #     assets as refs (no style plate in the shot).
    location_sheets = _build_location_sheets(
        context, 42000 + episode_num * 7, SHOTS_DIR / f"ep{episode_num:03d}",
        brands=brands)
    prop_assets = _build_prop_assets(
        context, 43000 + episode_num * 7, SHOTS_DIR / f"ep{episode_num:03d}",
        brands=brands)
    _save_resume_state("story", episode_num, article_url, topic, shots,
                       character_sheets, chapter_events=chapter_events,
                       anchor_events=anchor_events,
                       location_sheets=location_sheets, prop_assets=prop_assets,
                       target_paras=target_paras)

    # 5. Generate images (Krea 2 Turbo local, character sheet prepended,
    #    angle-matched view, face-lock portraits) - runs while the TTS worker
    #    keeps generating in the background.
    shots = _generate_all_shots(shots, character_sheets, episode_num=episode_num,
                                context=context,
                                location_sheets=location_sheets,
                                prop_assets=prop_assets,
                                brand_assets=brand_assets)
    _save_resume_state("images", episode_num, article_url, topic, shots,
                       character_sheets, chapter_events=chapter_events,
                       anchor_events=anchor_events,
                       location_sheets=location_sheets, prop_assets=prop_assets,
                       target_paras=target_paras)
    # Reusable episode template: this episode's winning formula for next time
    _save_episode_template(article_title, episode_num, bible, context,
                           roster_ids=list(character_sheets.keys())[:8])

    # 6. Join the TTS worker: all narration clips should be ready now
    tts_thread.join(timeout=1800)
    _finalize_tts(shots, tts_results, episode_num)
    _save_resume_state("tts", episode_num, article_url, topic, shots,
                       character_sheets, chapter_events=chapter_events,
                       anchor_events=anchor_events,
                       location_sheets=location_sheets, prop_assets=prop_assets,
                       target_paras=target_paras)

    # 6b. Title pass: whisper the voice track, resolve exact title times so
    #     the typewriter/glitch/shutter SFX + title cards match the narration.
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
        for ev in title_events:
            print(f"    [{ev['kind']}] @{ev['start']:.2f}s '{ev.get('text', ev.get('title', ''))}'")
        _save_resume_state("titles", episode_num, article_url, topic, shots,
                           character_sheets, chapter_events=chapter_events,
                           anchor_events=anchor_events,
                           location_sheets=location_sheets, prop_assets=prop_assets,
                       target_paras=target_paras)

    # 7. Render 1080p with full audio mix (voice+music+SFX+title SFX), black
    #    chapter placeholders, shutter black frames, then burn the titles.
    video_path = _render_video(shots, episode_num, title_events)
    if not video_path:
        print("  [HALT] Video render failed.")
        input("  Press Enter to exit...")
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

    # 8. Titles + description (3 titles scored by Google Trends + YouTube
    #    competition, best first)
    titles = _generate_titles(topic, episode_num)
    for i, t in enumerate(titles):
        print(f"  Title {i+1}: {t}")
    description = _generate_description(topic, episode_num, article_url)
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
    thumb_path = str(THUMBNAILS_DIR / f"ep{episode_num:03d}_thumb.png")
    thumb_ok = _generate_thumbnail(topic, thumb_path)
    _save_resume_state("thumbnail", episode_num, article_url, topic, shots,
                       character_sheets, titles=titles, description=description,
                       tags=all_tags, thumb_path=thumb_path, video_path=video_path,
                       chapter_events=chapter_events, anchor_events=anchor_events,
                       location_sheets=location_sheets, prop_assets=prop_assets,
                       target_paras=target_paras)

    # 10. Upload to Split Node channel
    if YOUTUBE_UPLOAD_ENABLED:
        print(f"\n  {'='*50}\n  YOUTUBE UPLOAD ({CHANNEL_NAME})\n  {'='*50}")
        print(f"  Video: {video_path}")
        title = titles[0] if titles else f"#{episode_num:03d} - {topic[:60]}"
        print(f"  Title: {title}")
        # Auto-upload setup: if the user hasn't authorized yet, prompt for
        # their YouTube API secret .json (instructions + link in the log).
        _ensure_youtube_secret()
        video_id = _upload_video_with_progress(video_path, title, description, tags_str)
        if video_id and thumb_ok:
            _upload_thumbnail(video_id, thumb_path)
        if video_id:
            _add_video_to_playlist(video_id)
            EPISODE_COUNTER_FILE.write_text(str(episode_num))
            print(f"  [OK] Episode #{episode_num:03d} uploaded! https://youtu.be/{video_id}")
            # Announce to Discord: wait 60s, then post description + hype + link
            _post_discord_announcement(topic, video_id, episode_num, wait_seconds=60,
                                       description=description)
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
    print(f"\n  Done! Press Enter to exit.")
    _cleanup_stt_artifacts(episode_num)
    _clear_resume_state()
    input()

if __name__ == "__main__":
    main()
