"""Split Node — animated title overlay engine (ASS + ffmpeg burn).

Generates an .ass subtitle file with three kinds of animated titles:

1. CHAPTER CARDS   — centered, big glowing title with a scale-pop + glow pulse.
                     Shown over the black placeholder clips while the narrator
                     reads "Chapter N - ...".
2. LOCATION TITLES — bottom-left, RED glow, per-character typewriter reveal
                     (0.7s), 4s hold, then a 0.5s glitch-off (staggered char
                     exits + RGB-split ghost copies + flicker).
3. PERSON TITLES    — bottom-left, GOLD glow, identical typewriter/glitch
                     behaviour. Fires the first time a character's name is
                     spoken, scoped to their first on-screen shot.

Timing contract (per event, absolute seconds in the final video):
    chapter : start = when "chapter N" is spoken, end = black clip end
    loc/person: start = when the anchor phrase is spoken
              typewriter  start .. start+0.7
              hold        start+0.7 .. start+4.7
              glitch-off  start+4.7 .. start+5.2

The typewriter uses a monospace font (Consolas) with per-character \pos
events; char advance is measured with PIL so characters never overlap.
"""

import math
import os
import random
import subprocess
import threading
from pathlib import Path
from typing import Optional

try:
    from PIL import ImageFont
    _HAS_PIL = True
except Exception:
    _HAS_PIL = False

try:
    from tqdm import tqdm as _tqdm
    _HAS_TQDM = True
except Exception:
    _HAS_TQDM = False

# ---------------------------------------------------------------------------
# ASS base template
# ---------------------------------------------------------------------------

HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 2
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: ChapCore,Bahnschrift,{chap_size},&H00FFFFFF,&H00FFFFFF,&H00000000,&H96000000,1,0,0,0,100,100,2,0,1,3,0,5,60,60,60,1
Style: ChapGlow,Bahnschrift,{chap_size},&H0000D7FF,&H0000D7FF,&H00000000,&H00000000,1,0,0,0,100,100,2,0,1,0,0,5,60,60,60,1
Style: ChapKicker,Bahnschrift,{kicker_size},&H00FFFFFF,&H00FFFFFF,&H00000000,&H96000000,1,0,0,0,100,100,8,0,1,2,0,5,60,60,60,1
Style: ChapBg,Arial,10,&H00000000,&H00000000,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1
Style: TypeLoc,Myriad Pro Bold,{type_size},&H000000FF,&H000000FF,&H00000000,&H00000000,1,0,0,0,100,100,0,0,1,0,0,7,40,40,40,1
Style: TypePerson,Myriad Pro Bold,{type_size},&H0000D7FF,&H0000D7FF,&H00000000,&H00000000,1,0,0,0,100,100,0,0,1,0,0,7,40,40,40,1
Style: TypeGhost,Myriad Pro Bold,{type_size},&H0000FF00,&H0000FF00,&H00000000,&H00000000,1,0,0,0,100,100,0,0,1,0,0,7,40,40,40,1
Style: TypePersonGhost,Myriad Pro Bold,{type_size},&H0000D7FF,&H0000D7FF,&H00000000,&H00000000,1,0,0,0,100,100,0,0,1,0,0,7,40,40,40,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def _ts(seconds: float) -> str:
    """ASS timestamp h:mm:ss.cc"""
    if seconds < 0:
        seconds = 0.0
    cs = int(round(seconds * 100))
    h, rem = divmod(cs, 360000)
    m, rem = divmod(rem, 6000)
    s, c = divmod(rem, 100)
    return f"{h}:{m:02d}:{s:02d}.{c:02d}"


def _dialog(start: float, end: float, style: str, text: str, layer: int = 0) -> str:
    return f"Dialogue: {layer},{_ts(start)},{_ts(end)},{style},,0,0,0,,{text}"


def _font_path(name: str) -> str:
    """Windows font file for measurement (PIL needs a real path)."""
    # Project fonts dir first (for fonts not installed system-wide, e.g.
    # Myriad Pro Bold), then C:\\Windows\\Fonts.
    _FONTS_DIR = Path(__file__).resolve().parent / "fonts"
    table = {
        "Consolas": "consola.ttf",
        "Myriad Pro Bold": "MyriadPro-Bold.otf",
        "Arial Black": "ariblk.ttf",
        "Bahnschrift": "bahnschrift.ttf",
        "Impact": "impact.ttf",
        "Arial": "arial.ttf",
    }
    for base in (_FONTS_DIR, Path(r"C:\Windows\Fonts")):
        p = base / table.get(name, "arial.ttf")
        if p.exists():
            return str(p)
    return ""


def _char_width(fontname: str, size: int) -> float:
    """Advance width of a monospace char in px (PIL measure of the TTF)."""
    if _HAS_PIL:
        try:
            f = ImageFont.truetype(_font_path(fontname), size)
            return f.getlength("M")
        except Exception:
            pass
    return size * 0.55


def _text_width(fontname: str, size: int, text: str) -> float:
    if _HAS_PIL:
        try:
            f = ImageFont.truetype(_font_path(fontname), size)
            return f.getlength(text)
        except Exception:
            pass
    return len(text) * size * 0.55


def _char_advance(fontname: str, size: int, ch: str) -> float:
    """Advance width of a single character (needed for PROPORTIONAL fonts like
    Myriad Pro Bold - a monospace proxy width would overlap narrow chars)."""
    if _HAS_PIL:
        try:
            f = ImageFont.truetype(_font_path(fontname), size)
            return f.getlength(ch)
        except Exception:
            pass
    return _char_width(fontname, size)


# ---------------------------------------------------------------------------
# Chapter cards
# ---------------------------------------------------------------------------

def _chapter_events(ev, W, H, fps) -> list[str]:
    """ev: {kind:'chapter', chapter_num, title, start, end, text}

    Renders BOTH the "CHAPTER N" kicker (0.30H, 20% ABOVE center) and the
    title text (0.70H, 20% BELOW center) as ASS dialogs - no pre-rendered
    clips, everything is one ASS burn pass. Both get the glow-pop treatment.
    """
    dur = max(ev["end"] - ev["start"], 0.5)
    pop = min(0.5, dur * 0.5)
    lines = []

    title = ev["title"]

    # ---- FULL-FRAME BLACK BACKGROUND (layer 0, under everything) ----
    # Guarantees the chapter card never bleeds over the next scene - the card
    # always sits on a solid black backdrop for exactly its on-screen duration.
    bg = (f"{{\\an7\\pos(0,0)\\p1\\bord(0)\\shad(0)\\1c&H000000&\\alpha&H00&}}"
          f"m 0 0 l {W} 0 l {W} {H} l 0 {H} l 0 0"
          f"{{\\p0}}")
    lines.append(_dialog(ev["start"], ev["end"], "ChapBg", bg, layer=0))

    # ---- KICKER "CHAPTER N" at 0.30H (big, Bahnschrift, glow-pop) ----
    kcx, kcy = W // 2, int(H * 0.30)
    kicker = f"CHAPTER {int(ev.get('chapter_num', 1)):02d}"
    kfs = int(H * 0.11)  # ~120px @1080, matching the old pre-rendered clips
    kglow = (f"{{\\an5\\pos({kcx},{kcy})\\fs{kfs}\\blur(14)\\bord(2)\\1c&H0000D7FF&\\alpha&H70&"
             f"\\fscx(60)\\fscy(60)\\t(0,{int(pop*1000)},\\fscx(100)\\fscy(100)\\alpha&H55&)"
             f"\\t({int(pop*1000)},{int(pop*1000)+700},\\bord(12)\\alpha&H40&)"
             f"\\t({int(pop*1000)+700},{int(pop*1000)+1500},\\bord(3)\\alpha&H60&)}}{kicker}")
    lines.append(_dialog(ev["start"], ev["end"], "ChapKicker", kglow, layer=1))
    kcore = (f"{{\\an5\\pos({kcx},{kcy})\\fs{kfs}\\1c&HFFFFFF&\\bord(3)\\3c&H000000&\\shad(0)"
             f"\\fscx(50)\\fscy(50)\\alpha&HFF&"
             f"\\t(0,{int(pop*1000)},\\fscx(110)\\fscy(110)\\alpha&H00&)"
             f"\\t({int(pop*1000)},{int(pop*1000)+350},\\fscx(100)\\fscy(100))}}{kicker}")
    lines.append(_dialog(ev["start"], ev["end"], "ChapKicker", kcore, layer=3))

    # ---- TITLE TEXT at 0.70H ----
    cx, cy = W // 2, int(H * 0.70)
    # Glow layer (soft bloom, pulses)
    glow = (f"{{\\an5\\pos({cx},{cy})\\blur(16)\\bord(2)\\1c&H0000D7FF&\\alpha&H70&"
            f"\\fscx(60)\\fscy(60)\\t(0,{int(pop*1000)},\\fscx(100)\\fscy(100)\\alpha&H55&)"
            f"\\t({int(pop*1000)},{int(pop*1000)+700},\\bord(14)\\alpha&H40&)"
            f"\\t({int(pop*1000)+700},{int(pop*1000)+1500},\\bord(3)\\alpha&H60&)}}{title}")
    lines.append(_dialog(ev["start"], ev["end"], "ChapGlow", glow, layer=1))

    # Core layer (sharp white, scale-pop in)
    core = (f"{{\\an5\\pos({cx},{cy})\\1c&HFFFFFF&\\bord(3)\\3c&H000000&\\shad(0)"
            f"\\fscx(50)\\fscy(50)\\alpha&HFF&"
            f"\\t(0,{int(pop*1000)},\\fscx(110)\\fscy(110)\\alpha&H00&)"
            f"\\t({int(pop*1000)},{int(pop*1000)+350},\\fscx(100)\\fscy(100))}}{title}")
    lines.append(_dialog(ev["start"], ev["end"], "ChapCore", core, layer=3))
    return lines


# ---------------------------------------------------------------------------
# Typewriter location / person titles
# ---------------------------------------------------------------------------

def _typewriter_events(ev, W, H, fps) -> list[str]:
    """ev: {kind:'location'|'person', text, start, end, display_text}"""
    style = {"location": "TypeLoc",
             "person": "TypePerson"}.get(ev["kind"], "TypeLoc")
    ghost_style = "TypePersonGhost" if ev["kind"] == "person" else "TypeGhost"
    fontsize = 56
    margin = 48
    # Row layout (bottom-left): person titles sit on the baseline; a location
    # (red) fires stacked ABOVE it. A person title that collides with a
    # location moves up one row (then up two if needed).
    base_y = H - 110
    if ev["kind"] == "location":
        base_y -= 74
    elif ev.get("_stack_up"):
        base_y -= 74 * min(ev.get("_stack_up", 0), 2)

    text = ev["text"]
    # Escape ASS characters
    text = text.replace("\\", "\\\\").replace("{", "(").replace("}", ")")
    # Myriad Pro Bold is PROPORTIONAL - measure each char's advance so the
    # reveal and the cursor never overlap (monospace proxy would misalign).
    widths = [_char_advance("Myriad Pro Bold", fontsize, ch) for ch in text]
    n = max(len(text), 1)
    step = 0.7 / n                 # per-char typewriter delay
    hold_end = ev["start"] + 4.7   # glitch starts here (0.7 type + 4.0 hold)
    glitch_end = ev["start"] + 5.2

    lines = []
    x = margin
    rng = random.Random(137 + sum(ord(c) for c in text))

    for i, ch in enumerate(text):
        if ch == " ":
            x += widths[i]
            continue
        t_show = ev["start"] + i * step
        # random staggered exit inside the 0.5s glitch window
        t_exit = hold_end + rng.uniform(0.0, 0.5)
        # glitch flicker in the final ~0.35s of this char's life
        fl = max(t_exit - 0.32, hold_end)
        fl_ms = int((t_exit - fl) * 1000)
        jitter = rng.uniform(-6, 6)
        tags = (f"{{\\an7\\pos({x:.1f},{base_y})\\bord(2)\\3c&H000000&"
                f"\\blur(0.6)\\alpha&HFF&\\t({int((t_show-ev['start'])*1000)},"
                f"{int((t_show-ev['start'])*1000+120)},\\alpha&H00&)"
                f"\\t({int((fl-ev['start'])*1000)},{int((fl-ev['start'])*1000)+80},\\alpha&H55&\\fscx(115)\\fscy(115))"
                f"\\t({int((fl-ev['start'])*1000)+80},{int((fl-ev['start'])*1000)+160},\\alpha&H00&\\fscx(100)\\fscy(100))"
                f"\\t({int((fl-ev['start'])*1000)+160},{int((t_exit-ev['start'])*1000)},\\alpha&HFF&\\fscx(120)\\fscy(120))"
                f"\\move({x + jitter:.1f},{base_y},{x:.1f},{base_y})}}")
        lines.append(_dialog(t_show, t_exit, style, tags + ch, layer=4))
        x += widths[i]

    # Blinking block cursor after the typed text during the hold
    cx = x + 4
    blink = "".join(
        f"\\t({k*400},{k*400+200},\\alpha&H00&)\\t({k*400+200},{k*400+400},\\alpha&HFF&)"
        for k in range(10))
    cursor = (f"{{\\an7\\pos({cx:.1f},{base_y})\\1c&HFFFFFF&\\bord(1)\\blur(0.4)\\alpha&HFF&{blink}}}"
              f"{{\\alpha&H00&}}_")
    # NOTE: alpha&H00& after the brace means cursor starts visible; blink chain then runs
    lines.append(_dialog(ev["start"] + 0.7, hold_end, style, cursor, layer=4))

    # RGB-split ghost copies during the glitch window (chromatic aberration)
    full_w = _text_width("Myriad Pro Bold", fontsize, text)
    for off, ghost_alpha in ((-7, "&HAA&"), (7, "&H88&")):
        ghost = (f"{{\\an7\\pos({margin + off},{base_y})\\blur(1)\\1c&H00FFFF&\\alpha{ghost_alpha}"
                 f"\\t(0,{int(0.3*1000)},\\alpha&HFF&)}}{text}")
        lines.append(_dialog(hold_end - 0.1, hold_end + 0.45, ghost_style, ghost, layer=6))

    return lines


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_title_ass(events: list[dict], out_path: str,
                    video_w: int = 1920, video_h: int = 1080, fps: int = 24) -> str:
    """Write the .ass file for a list of resolved title events.

    events: [{kind, start, end?, text, title?, chapter_num?}]
    - chapter: text = full "Chapter N - Title" read by TTS; title + chapter_num
      used for the card.
    - location/person: text = display string (already shortened).
      location = red, person = gold; all bottom-left.
    """
    chap_size = int(video_h * 0.075)      # ~81px @1080
    kicker_size = int(video_h * 0.037)    # ~40px
    type_size = int(video_h * 0.052)      # ~56px

    body = HEADER.format(W=video_w, H=video_h, chap_size=chap_size,
                         kicker_size=kicker_size, type_size=type_size)
    # Compute row stacking for person titles: how many OTHER typewriter events
    # (location/person) fire within 2s - the person card moves up a
    # row per collision so cards never overlap on the bottom-left.
    tw_evs = [ev for ev in events
              if ev.get("kind") in ("location", "person")]
    # SERIALIZE (Joe 2026-08-09): a typewriter title occupies
    # start .. start+5.2s (0.7 type + 4.0 hold + 0.5 glitch). If two typewriter
    # titles would be on screen at the SAME time, push the later one to start
    # AFTER the earlier one's window ends, so only ONE title ever shows at once
    # (no more unreadable stacking/overlap). Chapter cards occupy the CENTRE so
    # they don't collide with the bottom-left typewriter row.
    _TW_WINDOW = 5.2
    tw_sorted = sorted(tw_evs, key=lambda e: e.get("start", 0))
    _last_tw_end = -1.0
    for ev in tw_sorted:
        s = ev.get("start", 0)
        if s < _last_tw_end:
            # Overlaps the previous title -> shift to start after it finishes.
            ev["start"] = _last_tw_end
            s = _last_tw_end
            print(f"  [TITLES] serialized {ev['kind']} '{ev.get('text','')[:24]}' -> "
                  f"@{s:.2f}s (avoid overlap)")
        _last_tw_end = s + _TW_WINDOW
    for ev in tw_evs:
        if ev.get("kind") == "person":
            ev["_stack_up"] = sum(
                1 for o in tw_evs
                if o is not ev and o.get("kind") in ("location",)
                and abs(o.get("start", 0) - ev.get("start", 0)) < 2.0)
    parts = []
    for ev in events:
        kind = ev.get("kind")
        try:
            if kind == "chapter":
                parts.extend(_chapter_events(ev, video_w, video_h, fps))
            elif kind in ("location", "person"):
                parts.extend(_typewriter_events(ev, video_w, video_h, fps))
        except Exception as e:
            print(f"  [TITLES] skip event {kind}: {e}")
    body += "\n".join(parts) + "\n"
    Path(out_path).write_text(body, encoding="utf-8")
    return out_path


def _probe_duration(path: str) -> float:
    """Total video duration in seconds (0.0 on failure)."""
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True, timeout=30)
        return float(r.stdout.strip())
    except Exception:
        return 0.0


def burn_titles(video_path: str, ass_path: str, out_path: str,
                timeout: int = 2400) -> bool:
    """Re-encode video with the title .ass burned in (NVENC, faststart).

    Everything (chapter kicker + title, typewriter loc/person cards) is
    rendered inside the ASS - no pre-rendered chapter clips. The kicker
    and title text are both ASS dialogs (see _chapter_events).

    Streams ffmpeg -progress to a live bar (tqdm when available, otherwise
    plain ASCII) so a 15-25 min burn shows % + ETA instead of dead air.
    """
    # Windows: drive-letter colon in absolute paths breaks the subtitles filter.
    # Use relative paths with cwd set to the video's directory instead.
    vdir = Path(video_path).resolve().parent
    vname = Path(video_path).name
    aname = Path(ass_path).name
    oname = Path(out_path).name
    total = _probe_duration(video_path)
    # libass resolves font names from installed system fonts; for fonts that
    # live only in the project fonts/ dir (e.g. Myriad Pro Bold) pass a
    # fontsdir so the .ass style name actually resolves instead of falling back.
    sub_filter = f"subtitles={aname}"
    _fonts_dir = Path(__file__).resolve().parent / "fonts"
    if _fonts_dir.is_dir() and any(_fonts_dir.iterdir()):
        # Pass fontsdir as a RELATIVE path from the video's directory (the
        # process cwd). An absolute path like "F:/aaaaaVIBECODING/System
        # Breakers/fonts" contains a COLON and a SPACE, which ffmpeg's filter
        # parser splits on even when backslash-escaped (fails with "No option
        # name near..."). The relative path has neither, so it parses cleanly
        # and libass still resolves the .ass font names (Joe 2026-08-09).
        _fd = os.path.relpath(str(_fonts_dir), start=str(vdir)).replace("\\", "/")
        sub_filter += f":fontsdir={_fd}"
    cmd = [
        "ffmpeg", "-y", "-v", "error",
        "-i", vname,
        "-vf", sub_filter,
        "-c:v", "hevc_nvenc", "-preset", "p7", "-rc", "vbr", "-cq", "28", "-b:v", "0",
        "-c:a", "copy",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        "-progress", "pipe:1", "-nostats",
        oname,
    ]
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, cwd=str(vdir))
    except Exception as e:
        print(f"  [TITLES] Burn launch failed: {e}")
        return False
    # Drain stderr in a background thread so the ~64KB stderr pipe can NEVER fill
    # and deadlock ffmpeg (libass emits lots of font/warning output). The parent
    # must read stderr continuously while it reads stdout, otherwise ffmpeg
    # blocks writing stderr and the whole burn hangs (Joe 2026-08-09). Collect
    # stderr so it can be surfaced if the burn fails.
    stderr_buf = []
    def _drain_stderr():
        try:
            for line in proc.stderr:
                stderr_buf.append(line)
        except Exception:
            pass
    _s_thread = threading.Thread(target=_drain_stderr, daemon=True)
    _s_thread.start()
    pbar = None
    if _HAS_TQDM and total > 0:
        pbar = _tqdm(total=total, unit="s", desc="  [TITLES] Burn",
                     bar_format="{desc}: {percentage:3.0f}%|{bar}| "
                                "{n:.0f}/{total_fmt}s [{elapsed}<{remaining}]")
    last_sec = 0.0
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
            pbar.update(max(0.0, min(sec - last_sec, total - pbar.n)))
            last_sec = sec
    except Exception:
        pass
    proc.wait()
    _s_thread.join(timeout=5)
    stderr = "".join(stderr_buf)
    if pbar:
        pbar.close()
        print()
    if proc.returncode != 0 or not os.path.isfile(out_path) or os.path.getsize(out_path) < 1000:
        print(f"  [TITLES] Burn failed: {stderr[-400:]}")
        return False
    return True
