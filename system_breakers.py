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

# TTS: built-in male PocketTTS voice (no voice clone)
TTS_VOICE = "alba"

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

# Timeline anchors: dates/locations the narrator reads aloud, which become
# bottom-left typewriter titles (GREEN = timeline, RED = location).
MONTHS = r"(?:January|February|March|April|May|June|July|August|September|October|November|December)"
TIMELINE_PATTERNS = [
    re.compile(rf"{MONTHS}\s+\d{{1,2}}(?:st|nd|rd|th)?[,\s]+\d{{4}}", re.IGNORECASE),   # March 2010 / March 12th, 2012
    re.compile(rf"\d{{1,2}}(?:st|nd|rd|th)?\s+{MONTHS}\s+\d{{4}}", re.IGNORECASE),       # 12th March 2012
    re.compile(rf"{MONTHS}\s+\d{{4}}", re.IGNORECASE),                                   # March 2010 (no day)
    re.compile(rf"(?:Late|Early|Mid)\s+\d{{4}}", re.IGNORECASE),                         # Late 2016
    re.compile(rf"\b20\d{{2}}\b"),                                                       # bare year (accepted only at para start)
]
LOCATION_PATTERNS = [
    # "Goulburn, New South Wales" / "Queen Square, Sydney" (comma pairs)
    re.compile(r"([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+){0,2}),\s+([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+){0,2})"),
    # "in Sydney" / "at the kitchen table of his flat" (in/at + place)
    re.compile(rf"\b(?:in|at|from)\s+(?:(?:the|a|an)\s+)?({MONTHS}|[A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+){{0,2}})\b"),
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
TYPEWRITER_SEC = 1.5
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

# Discord announcement bot
DISCORD_BOT_TOKEN = os.environ.get("DISCORD_BOT_TOKEN", "")
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
            if title and link:
                items.append({"title": title, "link": link, "description": desc})
        if not items:
            for entry in root.iter("{http://www.w3.org/2005/Atom}entry"):
                title_el = entry.find("{http://www.w3.org/2005/Atom}title")
                link_el = entry.find("{http://www.w3.org/2005/Atom}link")
                title = title_el.text if title_el is not None else ""
                link = link_el.get("href", "") if link_el is not None else ""
                if title and link:
                    items.append({"title": title, "link": link, "description": ""})
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

    # Sort by final score (niche + trend + engagement), tiebreak HN points
    matches.sort(key=lambda x: (x.get("final_score", 0), x.get("hn_points", 0)),
                 reverse=True)

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
        matches.sort(key=lambda x: x.get("final_score", 0), reverse=True)
    return matches


def _pick_story() -> tuple[str, str]:
    """Pick a story with user confirmation. Asks Y/n per candidate;
    re-polls RSS when the candidate pool runs out.

    Before collecting candidates, runs the trend-research-toolkit scan so each
    candidate is shown with its RISING (Google Trends) and UNDER-SERVED (YouTube
    competition) scores plus a final score. used articles are never re-displayed;
    rejected candidates are skipped for the rest of the session.
    """
    used = _load_used_articles()
    rejected = set()  # candidates the user said no to this session
    pool: list[dict] = []
    pool_idx = 0
    rounds = 0

    print("\n[RSS] Scraping feeds for a 'beat the system' story...")
    print("  [TREND] scanning rising + under-served topics (trend-research-toolkit)...")
    trend_topics = _trend_topics()
    pool = _collect_candidate_stories(used, rejected, trend_topics)
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
            pool = _collect_candidate_stories(used, rejected, trend_topics)
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
        # User said no - mark rejected so re-polls skip it
        rejected.add(chosen["link"])
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

TARGET_NARRATION_PARAS = 90

NARRATION_SYSTEM_PROMPT = (
    "You are a documentary scriptwriter for a YouTube channel called SPLIT NODE. "
    "The channel tells true stories of ordinary people who used their skills, brains, "
    "or nerve to beat the system - hackers, lottery mathematicians, card counters, "
    "scam-baiters, people who found legal loopholes and won the game of life. "
    "Your writing style is the Black Files / FERN true-crime documentary style.\n\n"
    "STYLE RULES (follow ALL of them):\n"
    "1. COLD OPEN: the very first paragraph must drop the viewer into a specific, "
    "visceral scene - exact date, exact place, one dramatic image after another - "
    "escalate the stakes, then end with a twist tease ('Except this story doesn't "
    "end there...') and the question the whole episode answers.\n"
    "2. PRESENT TENSE, CINEMATIC. Short punchy sentences and fragments for impact "
    "('Case closed.' 'Declined. One word on a screen.').\n"
    "3. EXACT NUMBERS, never vague. Dollar amounts, dates, durations, counts "
    "('$449 a fortnight', '$2.1 million', '29 months', 'a $9 fee', 'five taps of $4,999'). "
    "Never write 'a lot of money' - write the exact figure from the article.\n"
    "4. TIME AND PLACE ANCHORS: every time the scene shifts, START the new paragraph "
    "with a standalone date and/or location sentence ('December 12th, 2012. Goulburn, "
    "New South Wales.' / 'March 2010.' / 'Late 2016, Queen Square, Sydney.'). The "
    "viewer must always know where and when the story is. Use REAL place names from "
    "the article.\n"
    "5. METAPHOR AND SENSORY DETAIL: concrete images ('the account died mid-transaction "
    "like a heart stopping between beats', 'a paper monument to a number nobody at the "
    "bank appears to be reading').\n"
    "6. RHETORICAL QUESTIONS as pivots between beats ('Who is watching this account? "
    "'How do you take $2.1 million from a bank without breaking a single law?')\n"
    "7. IRONY AND REVERSAL: set up the obvious reading, then flip it ('The law has a "
    "name for that arrangement, and it isn't fraud. It's a loan.')\n"
    "8. DIRECT ADDRESS 1-2 times per episode ('Be honest. If some part of you would "
    "have typed that first $4,999 too...')\n"
    "9. NEVER invent facts that contradict the article. Expand with cinematic framing, "
    "sensory detail and dramatic tension only.\n\n"
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

def _build_narration_script(paragraphs: list[str]) -> list[str]:
    """Stage 1: expand the article into ~TARGET_NARRATION_PARAS narration paragraphs.

    Each article paragraph is expanded into X narration paragraphs where
    X = round(TARGET / len(article_paragraphs)), so the total lands as close
    to the target as possible even when the article has fewer paragraphs.
    """
    print("\n[LLM] Stage 1: writing documentary narration script...")
    n_art = max(len(paragraphs), 1)
    per_para = max(2, round(TARGET_NARRATION_PARAS / n_art))
    print(f"  [LLM] Target {TARGET_NARRATION_PARAS} narration paragraphs "
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
            if len(p_clean) > 40:
                narration_paras.append(p_clean)
                added += 1
        if added:
            covered.append(f"({i+1}/{n_art}) {narration_paras[-1][:110]}")
        time.sleep(0.3)

    if not narration_paras:
        print("  [LLM] Narration failed, using article paragraphs directly")
        narration_paras = [re.sub(r"\s+", " ", p).strip()[:500]
                           for p in paragraphs[:TARGET_NARRATION_PARAS]]

    print(f"  [LLM] Narration script: {len(narration_paras)} paragraphs")
    for i, p in enumerate(narration_paras):
        print(f"    {i+1}. {p[:70]}...")
    return narration_paras


CHAPTER_PLAN_PROMPT = (
    "You are a documentary editor for SPLIT NODE. You are given a finished "
    "narration script (numbered paragraphs) for a true-crime documentary in the "
    "Black Files style. The episode must be divided into 4-6 CHAPTERS, each "
    "opening with a title card the narrator reads aloud as 'Chapter N - <Title>'.\n"
    "Pick natural break points: where the story shifts location, era, or moves to "
    "a new major event. The FIRST 1-3 paragraphs are the cold-open hook and must "
    "NOT be a chapter start.\n"
    "Respond with EXACTLY 4-6 lines, one per chapter, in this format:\n"
    "<paragraph_number> | <Chapter Title, 2-6 words, punchy, no period>\n"
    "Example:\n"
    "4 | The Account That Never Said No\n"
    "12 | Complete Freedom\n"
    "No other text."
)


def _insert_chapter_markers(narration_paras: list[str]) -> tuple[list[str], list[dict]]:
    """Split the narration into chapters: inserts 'Chapter N - Title' paragraphs.

    Returns (new_narration, chapter_events) where each chapter event is
    {chapter: n, title: str, para_idx: index of the inserted paragraph}.
    Falls back to no chapters if the LLM call fails.
    """
    if len(narration_paras) < 12:
        return narration_paras, []
    print("\n[LLM] Chapter pass: picking chapter breaks + titles...")
    try:
        numbered = "\n".join(f"{i+1}. {p[:160]}" for i, p in enumerate(narration_paras))
        text = _llm_chat([
            {"role": "system", "content": CHAPTER_PLAN_PROMPT},
            {"role": "user", "content": f"NARRATION SCRIPT:\n{numbered}"}
        ], max_tokens=400, temp=0.5)
        breaks = []
        for line in text.splitlines():
            m = re.match(r"^\s*(\d{1,3})\s*[|:]\s*(.+)$", line.strip())
            if m:
                idx = int(m.group(1)) - 1  # to 0-based paragraph index
                title = re.sub(r"\s+", " ", m.group(2)).strip().strip(".\"'")
                if 1 <= idx <= len(narration_paras) - 2 and 2 <= len(title) <= 60:
                    if idx not in [b[0] for b in breaks]:
                        breaks.append((idx, title))
        breaks.sort()
        breaks = breaks[:6]
        if len(breaks) < 2:
            print("  [LLM] Chapter plan unparsable, skipping chapters")
            return narration_paras, []
        out = list(narration_paras)
        events = []
        for n, (idx, title) in enumerate(breaks, start=1):
            # insert at idx (0-based) in the CURRENT list
            pos = idx + (n - 1)  # earlier insertions shift indices
            para = f"Chapter {n} - {title}"
            out.insert(pos, para)
            events.append({"chapter": n, "title": title, "para_idx": pos})
        print(f"  [LLM] {len(events)} chapters: " +
              ", ".join(f"#{e['chapter']} '{e['title']}' @para{e['para_idx']+1}" for e in events))
        return out, events
    except Exception as e:
        print(f"  [LLM] Chapter pass failed: {e}")
        return narration_paras, []


def _extract_anchor_events(narration_paras: list[str]) -> list[dict]:
    """Find location (red) and timeline (green) anchors in paragraph leads.

    Each event: {kind: 'location'|'timeline', text, para_idx, anchor_words}.
    anchor_words are the whisper search words used to pin the exact read time.
    """
    events = []
    for i, para in enumerate(narration_paras):
        if CHAPTER_RE.match(para):
            continue
        lead = para[:TITLE_ANCHOR_MAX_CHARS]
        # --- timeline: prefer the most specific date pattern in the lead ---
        timeline = None
        for pat in TIMELINE_PATTERNS:
            m = pat.search(lead)
            if m:
                timeline = m.group(0).strip()
                # bare-year matches must sit in the first 30 chars (scene anchor)
                if re.fullmatch(r"20\d{2}", timeline) and m.start() > 30:
                    timeline = None
                    continue
                break
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
        # A location lead often carries a timeline too ("Goulburn, NSW, March 2010") —
        # both events fire together at the paragraph start; no filtering needed.
        if timeline:
            words = re.findall(r"[A-Za-z0-9]+", timeline.lower())
            events.append({
                "kind": "timeline", "text": timeline, "para_idx": i,
                "anchor_words": words[:2] if words else [timeline.lower()],
            })
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
    "The scenes must show the characters actually DOING something - an action that "
    "moves the story forward. Never static portraits. Full scenes based on the actions "
    "they take in the narration.\n\n"
    + CAMERA_LOGIC +
    "\nI will give you one paragraph of the narration script. Create ONE shot for it. "
    "Respond with EXACTLY ONE LINE of 7 pipe-separated fields, in this exact order, "
    "with NO labels, NO extra text, NO line breaks:\n"
    "<shot type EWS/WS/MS/CU/ECU> | <camera angle: eye-level, low-angle, high-angle, over-the-shoulder, from-behind, side-on> | "
    "<character NAME or NONE> | <character role, e.g. lottery mathematician> | "
    "<full scene description: setting, what the character is DOING, props, lighting, camera framing. 2-4 sentences, action-focused> | "
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


def _build_shot_list(narration_paras: list[str]) -> list[dict]:
    """Stage 2: for each narration paragraph, generate a shot entry.

    Chapter paragraphs ("Chapter N - Title") get a direct black-card shot
    (no LLM call, no image generation - the render pass shows a black
    placeholder where the glowing chapter title is burned in pass 2).
    """
    print("\n[LLM] Stage 2: building shot list from narration...")
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
                f"NARRATION PARAGRAPH {i+1} of {len(narration_paras)}:\n{para[:1200]}\n\n"
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

def _build_character_sheets(shots: list[dict], narration: list[str]) -> dict:
    """Stage 2b: poll the LLM once per unique character for a precise repeatable sheet."""
    print("\n[LLM] Stage 2b: building character sheets...")
    # Collect unique named characters in order of first appearance, using the
    # same canonical map as _merge_character_aliases so case/acronym/honorific
    # variants ('IRS' vs 'I.R.S.', 'IRWIN' vs 'Jessy Irwin') NEVER produce
    # duplicate sheets for the same person.
    canon = _character_canonical_map(shots)
    names = []
    for s in shots:
        c = canon.get(s.get("character", "NONE"), "NONE")
        if c != "NONE" and c not in names:
            names.append(c)
    if not names:
        print("  [LLM] No named characters found - skipping sheets")
        return {}

    story_ctx = "\n".join(narration[:30])[:6000]
    sheets = {}
    for name in names:
        role = ""
        for s in shots:
            if s.get("character") == name and s.get("character_role"):
                role = s["character_role"]
                break
        text = _llm_chat([
            {"role": "system", "content": CHARACTER_SHEET_SYSTEM_PROMPT},
            {"role": "user", "content": (
                f"CHARACTER: {name}\nROLE: {role or 'character in the story'}\n\n"
                f"STORY CONTEXT:\n{story_ctx}\n\n"
                f"Create the precise character sheet for {name}."
            )}
        ], max_tokens=900, temp=0.7)

        sheet = {"name": name, "role": role}
        fields = ["ROLE", "GENDER", "AGE", "BUILD", "FACE", "HAIR", "OUTFIT",
                  "FRONT VIEW", "LEFT VIEW", "RIGHT VIEW", "BACK VIEW", "FULL BODY"]
        for f in fields:
            m = re.search(rf"^{f}:\s*(.+)$", text, re.MULTILINE)
            if m:
                sheet[f.lower().replace(" ", "_")] = m.group(1).strip()
        # FULL BODY fallback: synthesize from parts if missing
        if not sheet.get("full_body"):
            parts = [sheet.get("build", ""), sheet.get("face", ""), sheet.get("hair", ""), sheet.get("outfit", "")]
            sheet["full_body"] = ". ".join(p for p in parts if p)
        sheets[name] = sheet
        print(f"  [LLM] Character sheet: {name} (gender={sheet.get('gender','?')}, age={sheet.get('age','?')})")
        time.sleep(0.3)
    print(f"  [LLM] Character sheets complete: {len(sheets)} characters")
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
    """Build the RunPod prompt for one shot (shared by full gen and resume regen)."""
    character_sheets = character_sheets or {}
    angle = shot.get("angle", "eye-level")
    cam_desc = ""
    if shot.get("shot_type"):
        cam_desc = f", {shot['shot_type']} framing, {angle} camera angle"

    char_name = shot.get("character", "NONE")
    sheet = None
    if char_name != "NONE":
        # Case-insensitive lookup: sheet keys and shot character names can differ
        # in casing ('ARS' vs 'Ars') - a missed match would wrongly fall through
        # to the scene-only branch and drop the character entirely.
        sheet = character_sheets.get(char_name)
        if sheet is None:
            for k, v in character_sheets.items():
                if k.lower() == char_name.lower():
                    sheet = v
                    break
    if sheet:
        char_block = _character_prompt_block(sheet, angle)
        prompt = (
            f"{RENDER_STYLE}. {char_block}. {shot['scene']}{cam_desc}, "
            f"16:9 widescreen cinematic documentary frame"
        )
    else:
        # No character (establishing/landscape/object shot) - use the scene-only
        # style with zero human language so no person is ever generated.
        prompt = (
            f"{SCENE_STYLE}. {shot['scene']}{cam_desc}, "
            f"16:9 widescreen cinematic documentary frame"
        )
    return prompt


def _black_placeholder(episode_num: int) -> str:
    """1920x1080 pure-black PNG used for chapter title placeholder clips."""
    ep_dir = SHOTS_DIR / f"ep{episode_num:03d}"
    ep_dir.mkdir(parents=True, exist_ok=True)
    out = str(ep_dir / "_black.png")
    if os.path.isfile(out) and os.path.getsize(out) > 1000:
        return out
    from PIL import Image
    Image.new("RGB", (1920, 1080), (0, 0, 0)).save(out)
    return out


def _generate_all_shots(shots: list[dict], character_sheets: Optional[dict] = None,
                        episode_num: int = 0) -> list[dict]:
    character_sheets = character_sheets or {}
    ep_dir = SHOTS_DIR / f"ep{episode_num:03d}" if episode_num else None
    black = _black_placeholder(episode_num) if episode_num else None
    print(f"\n[IMAGES] Generating {len(shots)} 3D shots via RunPod Z-Image-Turbo...")
    for idx, shot in enumerate(shots):
        if shot.get("is_chapter"):
            shot["seed"] = 0
            shot["image_path"] = black
            print(f"  [SHOT {idx+1}/{len(shots)}] chapter placeholder (no image)")
            continue
        seed = 10000 + idx * 137 + random.randint(0, 999)
        prompt = _build_shot_prompt(shot, character_sheets)
        path = _runpod_generate(prompt, seed, out_dir=ep_dir)
        shot["seed"] = seed
        shot["image_path"] = path
        if path:
            print(f"  [SHOT {idx+1}/{len(shots)}] image ready (char={shot.get('character','NONE')})")
        else:
            print(f"  [SHOT {idx+1}/{len(shots)}] IMAGE FAILED - will use fallback")
        time.sleep(1)
    ok = sum(1 for s in shots if s.get("image_path"))
    print(f"  [IMAGES] {ok}/{len(shots)} images generated")
    return shots

# -- TTS (PocketTTS built-in male voice, 0dB normalized) -------------

def _pocket_tts_generate(text: str, output_path: str, timeout: int = 180) -> bool:
    """Generate TTS via PocketTTS HTTP API using built-in catalog voice (alba)."""
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    import urllib.request as _ur
    boundary = "----splitnode" + str(int(time.time() * 1000))
    def _field(name, value):
        return (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n"
                f"{value}\r\n").encode()
    body = (_field("text", text) + _field("voice_url", TTS_VOICE) +
            f"--{boundary}--\r\n".encode())
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
        ok = _pocket_tts_generate(shot["narration"], out)
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
      - typewriter clicks at each location/timeline title start (1.5s)
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

        # -- Music bed: suspense first 65% of the timeline, triumphant last 35%. --
        music_segments = []
        suspense_pool = MUSIC_LIBRARY["suspense"]
        triumphant_pool = MUSIC_LIBRARY["triumphant"]
        sus_idx, tri_idx = 0, 0
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
        print(f"  [AUDIO] Music: suspense x{sus_idx} (0-{section_cut:.0f}s) / "
              f"triumphant x{tri_idx} ({section_cut:.0f}s-end), -{abs(MUSIC_DB):.0f}dB, cycling")
        music_path = None
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
        #     INTO the card pop + a hit landing exactly on it.
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
            hit = _pick_sfx("hit-")
            if hit == "hit-shell-shock-high-ring-not-nice-for-ears":
                hit = None  # ear-bleeding ring never goes on a chapter card
            if hit:
                hm = SFX_LIBRARY[hit]
                placements.append((str(_sfx_path(hit)), ct,
                                   hm.get("hit", 0.1) + 1.2))
                print(f"  [AUDIO] Chapter hit '{hit}' @{ct:.1f}s")
        # 4) Typewriter clicks + glitch-off for every location/timeline/person title
        for ev in title_events or []:
            if ev.get("kind") not in ("location", "timeline", "person"):
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
        sfx_inputs, sfx_delays, sfx_trims, sfx_durs = [], [], [], []
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

        # Collect processed labels in input order
        labels = []
        li = 0
        if voice_path and os.path.isfile(voice_path):
            labels.append(f"[v{li}]")
            li += 1
        if music_path:
            labels.append(f"[m{li}]")
            li += 1
        for j in range(len(sfx_inputs)):
            labels.append(f"[s{li}]")
            li += 1

        amix_in = "".join(labels)
        n_inputs = len(labels)
        filter_complex = ";".join(filter_parts) + (
            f";{amix_in}amix=inputs={n_inputs}:duration=first:normalize=0,"
            f"alimiter=limit=0.95,atrim=0:{total_dur:.2f}[out]"
        )

        final_wav = str(RENDERED_AUDIO / f"ep{episode_num:03d}_mix.wav")
        cmd = ["ffmpeg", "-y", "-v", "error"]
        for inp in inputs:
            cmd += ["-i", inp]
        cmd += ["-filter_complex", filter_complex, "-map", "[out]",
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
    W_RES, H_RES = 1920, 1080
    if not os.path.isfile(image_path):
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
        f"scale=7680:4320:flags=lanczos:force_original_aspect_ratio=increase,"
        f"crop=7680:4320,"
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
                os.replace(final_path, output_path)

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
                    if split_node_titles.burn_titles(output_path, ass_path, burned, timeout=2400):
                        os.replace(burned, output_path)
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
    print(f"  [THUMB] GPT Image 2 thumbnail for: {topic[:60]}...")
    headline = _thumbnail_headline(topic)
    prompt = (
        "YouTube documentary thumbnail, realistic 3D render style (Unreal Engine 5 / "
        "Metahuman quality, photorealistic character with perfect anatomy), dramatic "
        f"cinematic scene related to: {topic[:120]}. Moody lighting, dark color grade, "
        "high contrast, bold and clickable composition, 16:9 landscape. "
        "Large bold uppercase text 'SPLIT NODE' in the top-left corner. "
        f"Large bold uppercase clickbait headline text '{headline}' centered in the "
        "lower third. Crisp legible text, high-impact YouTube thumbnail, FERN "
        "documentary channel style."
    )
    data = json.dumps({
        "prompt": prompt,
        "image_size": "landscape_16_9",
        "num_images": 1,
    }).encode()
    headers = {"Authorization": f"Key {FAL_API_KEY}", "Content-Type": "application/json"}
    try:
        req = urllib.request.Request("https://fal.run/openai/gpt-image-2", data=data, headers=headers)
        with urllib.request.urlopen(req, timeout=300) as r:
            result = json.loads(r.read())
        image_url = result.get("images", [{}])[0].get("url", "")
        if image_url:
            urllib.request.urlretrieve(image_url, output_path)
            if os.path.isfile(output_path) and os.path.getsize(output_path) > 1000:
                print(f"  [OK] Thumbnail: {os.path.getsize(output_path)//1024}KB -> {output_path}")
                return True
        print("  [FAIL] GPT Image 2 returned no image")
    except Exception as e:
        print(f"  [FAIL] GPT Image 2 error: {e}")
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
    for ch_id in DISCORD_ANNOUNCE_CHANNELS:
        try:
            data = json.dumps({"content": message}).encode()
            req = urllib.request.Request(
                f"https://discord.com/api/v10/channels/{ch_id}/messages",
                data=data,
                headers={
                    "Authorization": f"Bot {DISCORD_BOT_TOKEN}",
                    "Content-Type": "application/json",
                    "User-Agent": "DiscordBot (https://discord.gg/YSdqKR4wVB, 1.0)",
                },
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=15) as r:
                print(f"  [DISCORD] Posted to channel {ch_id} (HTTP {r.status})")
        except Exception as e:
            print(f"  [DISCORD] Failed channel {ch_id}: {e}")
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
                       anchor_events: Optional[list] = None) -> None:
    """Save episode state so it can be resumed if interrupted."""
    state = {
        "version": 2,
        "stage": stage,
        "episode_num": episode_num,
        "article_url": article_url,
        "topic": topic,
        "shots": shots or [],
        "character_sheets": character_sheets or {},
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
        print(f"  [STATE] Saved resume state (stage={stage}, {len(state['shots'])} shots)")
    except Exception as e:
        print(f"  [STATE] Could not save resume state: {e}")


def _load_resume_state() -> Optional[dict]:
    """Load resume state if it exists and is valid."""
    if not RESUME_FILE.exists():
        return None
    try:
        state = json.loads(RESUME_FILE.read_text())
        if state.get("version") != 1:
            return None
        return state
    except Exception:
        return None


def _clear_resume_state() -> None:
    try:
        if RESUME_FILE.exists():
            RESUME_FILE.unlink()
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
    shots = state.get("shots", [])
    character_sheets = state.get("character_sheets", {})
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
    print(f"{'='*60}\n")

    def _save(stg):
        _save_resume_state(stg, episode_num, article_url, topic, shots,
                           character_sheets, titles, description, tags,
                           thumb_path, video_path, video_id,
                           chapter_events, anchor_events)

    # 1. Images: regenerate only the missing ones (same seeds -> same look)
    ep_shot_dir = SHOTS_DIR / f"ep{episode_num:03d}"
    missing_img = [s for s in shots
                   if not (s.get("is_chapter") or
                           (s.get("image_path") and os.path.isfile(s["image_path"])))]
    if missing_img:
        print(f"\n[IMAGES] Regenerating {len(missing_img)} missing shots...")
        for shot in missing_img:
            seed = shot.get("seed") or (10000 + random.randint(0, 999))
            prompt = _build_shot_prompt(shot, character_sheets)
            path = _runpod_generate(prompt, seed, out_dir=ep_shot_dir)
            shot["seed"] = seed
            shot["image_path"] = path
            print(f"  [SHOT] {'image ready' if path else 'IMAGE FAILED - fallback'} "
                  f"(char={shot.get('character', 'NONE')})")
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

    _save("upload")

    print(f"\n  {'='*50}")
    print(f"  EPISODE #{episode_num:03d} COMPLETE (RESUMED)")
    print(f"  {'='*50}")
    if video_id:
        print(f"  YouTube:  https://youtu.be/{video_id}")
    print(f"  Shots: {len(shots)} | Stage: {stage} -> upload")

    _cleanup_stt_artifacts(episode_num)
    _clear_resume_state()


def main():
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
    narration = _build_narration_script(paragraphs)

    # 3b. Rate each narration segment against the topic, discard <= 4/10
    if narration:
        narration = _rate_paragraph_relevance(article_title, narration)
        if not narration:
            print("  [FILTER] All narration segments off-topic, rebuilding from filtered article...")
            narration = _build_narration_script(paragraphs)

    # 3c. Chapter pass: insert 'Chapter N - Title' paragraphs (black cards)
    narration, chapter_events = _insert_chapter_markers(narration)
    # 3d. Location/timeline anchors -> red/green bottom-left typewriter titles
    anchor_events = _extract_anchor_events(narration)

    # 3e. START TTS IN PARALLEL: queue ALL narration into PocketTTS in a
    # background thread, while the main thread builds shots, character sheets
    # and images. TTS and image gen run at the same time.
    tts_thread, tts_results, tts_stop = _start_tts_worker(narration, episode_num)

    # 4. Stage 2: shot list from narration (chapter paras become black cards)
    shots = _build_shot_list(narration)

    # 4b. Stage 2b: character sheets for every named character
    character_sheets = _build_character_sheets(shots, narration)
    _save_resume_state("story", episode_num, article_url, topic, shots,
                       character_sheets, chapter_events=chapter_events,
                       anchor_events=anchor_events)

    # 5. Generate images (character sheet prepended, angle-matched view) -
    #    runs while the TTS worker keeps generating in the background.
    shots = _generate_all_shots(shots, character_sheets, episode_num=episode_num)
    _save_resume_state("images", episode_num, article_url, topic, shots,
                       character_sheets, chapter_events=chapter_events,
                       anchor_events=anchor_events)

    # 6. Join the TTS worker: all narration clips should be ready now
    tts_thread.join(timeout=1800)
    _finalize_tts(shots, tts_results, episode_num)
    _save_resume_state("tts", episode_num, article_url, topic, shots,
                       character_sheets, chapter_events=chapter_events,
                       anchor_events=anchor_events)

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
                           anchor_events=anchor_events)

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
                       chapter_events=chapter_events, anchor_events=anchor_events)

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
                       chapter_events=chapter_events, anchor_events=anchor_events)

    # 9. Thumbnail
    thumb_path = str(THUMBNAILS_DIR / f"ep{episode_num:03d}_thumb.png")
    thumb_ok = _generate_thumbnail(topic, thumb_path)
    _save_resume_state("thumbnail", episode_num, article_url, topic, shots,
                       character_sheets, titles=titles, description=description,
                       tags=all_tags, thumb_path=thumb_path, video_path=video_path,
                       chapter_events=chapter_events, anchor_events=anchor_events)

    # 10. Upload to Split Node channel
    if YOUTUBE_UPLOAD_ENABLED:
        print(f"\n  {'='*50}\n  YOUTUBE UPLOAD ({CHANNEL_NAME})\n  {'='*50}")
        print(f"  Video: {video_path}")
        title = titles[0] if titles else f"#{episode_num:03d} - {topic[:60]}"
        print(f"  Title: {title}")
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
