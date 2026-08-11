"""Split Node — title scoring: demand (Google Trends via SerpAPI) vs competition
(YouTube Data API, using Split Node's existing OAuth credentials).

Takes the 3 LLM-generated titles and scores each:

    demand      : SerpAPI Google Trends TIMESERIES (relative interest 0-100,
                  one call compares all 3 titles; trajectory bonus for rising)
    competition : YouTube Data API search + videos + channels stats, same
                  room-to-rank heuristic as the trend-research-toolkit:
                  median view-velocity vs large-channel share (0-100)

    final = 0.55*demand + 0.45*room_to_rank + trajectory_bonus

Fails OPEN: any API failure keeps the original title order with a warning,
so the pipeline never blocks on scoring.
"""

import json
import os
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from statistics import median


def _sys_python() -> str:
    return sys.executable if sys.executable else "python"

PROJECT_DIR = Path(__file__).parent.resolve()
TOOLKIT = PROJECT_DIR / "trend_toolkit" / "trends_serpapi.py"
YT_API = "https://www.googleapis.com/youtube/v3/"
TIMEOUT = 30
TREND_CACHE = PROJECT_DIR / "trend_scan_cache.json"

SERPAPI_KEY = ""  # read lazily at call time (pipeline loads .env after import)


def _serpapi_key() -> str:
    return os.environ.get("SERPAPI_API_KEY", "") or SERPAPI_KEY

# Category -> candidate topic terms (one SerpAPI TIMESERIES call per category,
# so a full scan is 5 calls; cached for TREND_SCAN_CACHE_HOURS, default 24h)
TREND_CATEGORIES = {
    "money-hack": ["money hack", "side hustle", "passive income", "cashback", "credit card rewards", "lottery loophole"],
    "hacker": ["hacker", "cybercrime", "data breach", "ethical hacking", "ransomware"],
    "beat-the-system": ["beat the system", "loophole", "scam", "fraud", "heist"],
    "lottery": ["lottery loophole", "lottery winner", "lottery math", "jackpot", "casino"],
    "ai": ["AI", "AI automation", "artificial intelligence", "machine learning", "AI tools"],
    "tech": ["tech scam", "software bug", "security flaw", "startup fraud", "crypto"],
}


def scan_topics(creds_fn=None, cache_hours: int = 24) -> dict:
    """Find RISING + UNDER-SERVED topics per category (demand vs competition).

    Returns {category: {category, term, avg, trajectory, room_to_rank, score}}
    best-first per category. Cached to trend_scan_cache.json. Never raises -
    a category with no data yields its first term with None scores.
    """
    try:
        if cache_hours > 0 and TREND_CACHE.is_file():
            age = time.time() - TREND_CACHE.stat().st_mtime
            if age < cache_hours * 3600:
                cached = json.loads(TREND_CACHE.read_text())
                if cached.get("categories"):
                    print("  [TREND] topic scan cache reused "
                          f"({int(age // 3600)}h old)")
                    return cached["categories"]
    except Exception:
        pass

    results = {}
    for cat, terms in TREND_CATEGORIES.items():
        entry = {"category": cat, "term": terms[0], "avg": None,
                 "trajectory": "n/a", "room_to_rank": None, "score": 50.0}
        demand = {}
        try:
            if _serpapi_key():
                demand = _trend_demand(terms)
        except Exception as e:
            print(f"  [TREND] {cat} demand failed: {str(e)[:120]}")
        if not demand:
            results[cat] = entry
            continue
        top2 = sorted(demand, key=lambda t: demand[t].get("avg", 0),
                      reverse=True)[:2]
        comp = {}
        if creds_fn is not None:
            try:
                creds = creds_fn()
                if creds is not None and creds.token:
                    comp = _yt_competition(creds.token, top2, max_results=20)
            except Exception as e:
                print(f"  [TREND] {cat} competition failed: {str(e)[:120]}")
        traj_bonus = {"rising": 15.0, "flat": 5.0, "declining": -10.0, "n/a": 0.0}
        best = None
        for t in top2:
            d = demand.get(t, {})
            c = comp.get(t, {})
            score = (0.55 * min(d.get("avg", 50) or 50, 100)
                     + 0.45 * min(c.get("room_to_rank", 50) or 50, 100)
                     + traj_bonus.get(d.get("trajectory", "flat"), 0.0))
            if best is None or score > best["score"]:
                best = {"category": cat, "term": t, "avg": d.get("avg"),
                        "trajectory": d.get("trajectory", "flat"),
                        "room_to_rank": c.get("room_to_rank"),
                        "score": round(score, 1)}
        results[cat] = best or entry
    try:
        TREND_CACHE.write_text(json.dumps({"categories": results}, indent=2))
    except Exception:
        pass
    print("  [TREND] topic scan (rising + under-served):")
    for cat, r in results.items():
        print(f"    {cat:16s} {r['term']:<22} score={r['score']:5.1f}  "
              f"demand={str(r['avg']):>5} traj={r['trajectory']:>9} "
              f"room={str(r['room_to_rank']):>5}")
    return results

# ---------------------------------------------------------------------------
# Demand: Google Trends via SerpAPI (toolkit script, stdlib only)
# ---------------------------------------------------------------------------

def _extract_json(raw: str) -> dict:
    """The toolkit script prints human-readable text AFTER the JSON; pull just
    the JSON object (first { to last })."""
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("no JSON in toolkit output")
    return json.loads(raw[start:end + 1])


def _trend_demand(terms: list[str]) -> dict:
    """Return {term: {avg, trajectory}} — one SerpAPI call for all terms."""
    out = {}
    env = dict(os.environ)
    env["SERPAPI_API_KEY"] = _serpapi_key()
    r = subprocess.run(
        [_sys_python(), str(TOOLKIT), "--terms", ",".join(terms),
         "--timeframe", "today 3-m", "--type", "TIMESERIES"],
        capture_output=True, text=True, timeout=120, env=env)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip()[-300:] or "serpapi exit != 0")
    data = _extract_json(r.stdout)
    points = data.get("timeline", [])
    if not points:
        raise RuntimeError("no timeline data")
    keys = list(points[0].keys())
    for term in terms:
        vals = [p.get(term) for p in points
                if isinstance(p.get(term), (int, float))]
        avg = round(sum(vals) / len(vals), 1) if vals else 0.0
        # trajectory: compare first third vs last third
        traj = "flat"
        if len(vals) >= 4:
            k = max(1, len(vals) // 3)
            early = sum(vals[:k]) / len(vals[:k])
            late = sum(vals[-k:]) / len(vals[-k:])
            if early == 0:
                traj = "rising" if late > 0 else "flat"
            else:
                ch = (late - early) / early * 100.0
                traj = f"rising" if ch >= 15 else ("declining" if ch <= -15 else "flat")
        out[term] = {"avg": avg, "trajectory": traj}
    return out


# ---------------------------------------------------------------------------
# Competition: YouTube Data API via Split Node OAuth creds
# ---------------------------------------------------------------------------

def _yt_get(token: str, endpoint: str, params: dict) -> dict:
    url = YT_API + endpoint + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}",
        "User-Agent": "split-node/1.0"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def _yt_competition(token: str, terms: list[str], max_results: int = 25) -> dict:
    """Same room-to-rank heuristic as trend-research-toolkit."""
    out = {}
    for term in terms:
        search = _yt_get(token, "search", {
            "part": "snippet", "q": term, "type": "video",
            "order": "relevance", "maxResults": max_results})
        vids = [it["id"]["videoId"] for it in search.get("items", [])
                if it.get("id", {}).get("videoId")]
        if not vids:
            out[term] = {"sample_size": 0, "room_to_rank": 0.0,
                         "median_view_velocity_per_day": 0.0, "large_channel_share": 0.0}
            continue
        video_data = _yt_get(token, "videos", {
            "part": "statistics,snippet", "id": ",".join(vids[:50])})
        now = datetime.now(timezone.utc)
        rows = []
        for v in video_data.get("items", []):
            st = v.get("statistics", {})
            pub = v.get("snippet", {}).get("publishedAt", "")
            age_days = None
            try:
                dt = datetime.fromisoformat(pub.replace("Z", "+00:00"))
                age_days = max((now - dt).total_seconds() / 86400.0, 0.01)
            except Exception:
                pass
            try:
                views = int(st.get("viewCount", 0))
            except Exception:
                views = 0
            rows.append({"views": views, "age_days": age_days,
                         "channel_id": v.get("snippet", {}).get("channelId", "")})
        vel = [r["views"] / r["age_days"] for r in rows
               if r["age_days"] and r["views"]]
        med_vel = round(median(vel), 1) if vel else 0.0
        # channel subs (large = >= 1M)
        ch_ids = {r["channel_id"] for r in rows if r["channel_id"]}
        subs = {}
        for i in range(0, len(list(ch_ids)), 50):
            chunk = list(ch_ids)[i:i + 50]
            cd = _yt_get(token, "channels", {
                "part": "statistics", "id": ",".join(chunk)})
            for item in cd.get("items", []):
                st = item.get("statistics", {})
                if not st.get("hiddenSubscriberCount"):
                    try:
                        subs[item["id"]] = int(st.get("subscriberCount", 0))
                    except Exception:
                        subs[item["id"]] = 0
        large = sum(1 for r in rows if subs.get(r["channel_id"], 0) >= 1_000_000)
        share = round(large / len(rows), 2) if rows else 0.0
        out[term] = {
            "sample_size": len(rows),
            "median_view_velocity_per_day": med_vel,
            "large_channel_share": share,
            "room_to_rank": round(100 * med_vel / (med_vel or 1) * (1 - share), 1)
            if med_vel else 0.0,
        }
    return out


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def _title_term(title: str) -> str:
    """Shrink a clickbait title into a short Trends-friendly phrase (~5 words)."""
    t = re.sub(r"[^A-Za-z0-9 ]+", " ", title).strip()
    t = re.sub(r"\s+", " ", t)
    words = t.split()
    if len(words) <= 5:
        return t
    # try to keep the most meaningful tail (subject usually at the end)
    stop = {"the", "a", "an", "how", "why", "what", "who", "and", "of", "to",
            "in", "on", "for", "with", "from", "his", "her", "their", "that",
            "this", "was", "were", "did", "does", "man", "woman", "guy", "he", "she"}
    tail = [w for w in words if w.lower() not in stop][-4:]
    return " ".join(tail) if tail else " ".join(words[:5])


def score_titles(titles: list[str], creds_fn=None) -> list[dict]:
    """Score 3 titles. Returns [{title, term, demand, trajectory, room_to_rank,
    score}] sorted best-first. Never raises — fails open to original order."""
    if not titles:
        return []
    if len(titles) < 2:
        return [{"title": titles[0], "term": _title_term(titles[0]),
                 "demand": None, "trajectory": "n/a", "room_to_rank": None,
                 "score": 50.0}]
    terms = [_title_term(t) for t in titles]
    results = {t: {"demand": None, "trajectory": "n/a", "room_to_rank": None,
                   "score": 50.0} for t in titles}
    msgs = []

    # 1) demand
    if _serpapi_key():
        try:
            demand = _trend_demand(terms)
            for t, term in zip(titles, terms):
                d = demand.get(term, {})
                results[t]["demand"] = d.get("avg")
                results[t]["trajectory"] = d.get("trajectory", "flat")
        except Exception as e:
            msgs.append(f"trends: {str(e)[:150]}")
    else:
        msgs.append("trends: SERPAPI_API_KEY not set")

    # 2) competition via OAuth creds
    try:
        if creds_fn is not None:
            creds = creds_fn()
            if creds is not None and creds.token:
                comp = _yt_competition(creds.token, terms)
                for t, term in zip(titles, terms):
                    c = comp.get(term, {})
                    results[t]["room_to_rank"] = c.get("room_to_rank")
    except Exception as e:
        msgs.append(f"youtube: {str(e)[:150]}")

    # 3) combine
    traj_bonus = {"rising": 15.0, "flat": 5.0, "declining": -10.0, "n/a": 0.0}
    for t in titles:
        r = results[t]
        d = r["demand"] if r["demand"] is not None else 50.0
        c = r["room_to_rank"] if r["room_to_rank"] is not None else 50.0
        r["score"] = round(0.55 * min(d, 100.0) + 0.45 * min(c, 100.0)
                           + traj_bonus.get(r["trajectory"], 0.0), 1)
        r["term"] = _title_term(t)

    ranked = sorted(results.items(), key=lambda kv: kv[1]["score"], reverse=True)
    if msgs:
        print(f"  [TREND] scoring warnings: {'; '.join(msgs)}")
        print("  [TREND] keeping original title order (fail-open)")
        return [{"title": t, **results[t]} for t in titles]
    return [{"title": t, **r} for t, r in ranked]
