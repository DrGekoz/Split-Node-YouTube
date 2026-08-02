"""Split Node — SFX library analyzer.

Walks cinematic_sounds/, measures every audio file's envelope (duration,
build, hit, decay) and writes sfx_library_extra.json with SHORT aliases so the
LLM shot prompt can reference sounds by friendly names:

    "Cinematic Hits\\Cinematic - Hit - (Nikko Hunt's S.D.Essentials).wav"
        ->  hit-cinematic

Aliases are prefixed by their folder category (hit- / whoosh- / riser- /
sweep- / glitch- / foley- / nature- / soundscape-). The pipeline loads
sfx_library_extra.json at startup and merges it into SFX_LIBRARY.

Re-run after adding new sounds:  python analyze_sfx.py
"""

import json
import os
import re
import subprocess
from pathlib import Path

import numpy as np

ROOT = Path(__file__).parent.resolve()
SFX_DIR = ROOT / "cinematic_sounds"
OUT = ROOT / "sfx_library_extra.json"

SR = 24000
WIN = SR // 20  # 50ms windows


def measure(path: str) -> dict:
    r = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", path, "-f", "f32le", "-ac", "1",
         "-ar", str(SR), "-"],
        capture_output=True)
    if r.returncode != 0 or len(r.stdout) < SR // 2:
        return {"dur": 0.0, "build": 0.0, "hit": 0.0, "decay": 0.0}
    pcm = np.frombuffer(r.stdout, dtype=np.float32)
    n = len(pcm) // WIN
    if n == 0:
        return {"dur": 0.0, "build": 0.0, "hit": 0.0, "decay": 0.0}
    frames = pcm[:n * WIN].reshape(n, WIN)
    peaks = np.max(np.abs(frames), axis=1)
    hit_i = int(np.argmax(peaks))
    hit = hit_i * 0.05
    thresh = np.max(peaks) / 10 ** 0.45  # within 9dB of peak
    build = 0.0
    for i, p in enumerate(peaks):
        if p >= thresh:
            build = i * 0.05
            break
    dec = n * 0.05
    for i in range(hit_i, n):
        if peaks[i] < np.max(peaks) / 10:
            dec = i * 0.05
            break
    dur = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", path],
        capture_output=True, text=True).stdout.strip()
    return {"dur": round(float(dur or 0), 2), "build": round(build, 2),
            "hit": round(hit, 2), "decay": round(dec, 2)}


def slug(name: str, cat: str) -> str:
    # strip a trailing audio extension, twice (some files are "x.wav.wav")
    for _ in range(3):
        if re.search(r"\.(wav|mp3)$", name, flags=re.IGNORECASE):
            name = re.sub(r"\.(wav|mp3)$", "", name, flags=re.IGNORECASE)
        else:
            break
    name = re.sub(r"\s*-\s*\(.*?\)\s*$", "", name)   # strip (Nikko Hunt's...)
    # strip the trailing category word ("Deep - Whoosh" -> "Deep",
    # "2 Motorbikes Driving Past - Foley_Humans" -> "2 Motorbikes Driving Past")
    name = re.sub(
        r"\s*-\s*(?:hit|whoosh|glitch|riser|sweep|foley|foley humans|foley_humans|"
        r"nature|soundscape)s?\s*$", "", name, flags=re.IGNORECASE)
    n = re.sub(r"[^A-Za-z0-9]+", "-", name).strip("-").lower()
    n = re.sub(r"-+", "-", n)
    return f"{cat}-{n}" if n else cat


CAT_ALIASES = {
    "cinematic hits": "hit", "whooshs": "whoosh", "riser": "riser",
    "sweeps": "sweep", "glitches": "glitch",
    "foley humans": "foley", "foley_humans": "foley",
    "nature": "nature", "soundscapes": "soundscape",
}


def main():
    entries = {}
    for root, _dirs, files in sorted(os.walk(SFX_DIR)):
        for f in sorted(files):
            if not f.lower().endswith((".wav", ".mp3")):
                continue
            rel = os.path.relpath(os.path.join(root, f), SFX_DIR)
            # normalize folder names so "Foley_Humans" matches the alias table
            folder = os.path.dirname(rel).split(os.sep)[0].lower().replace("_", " ")
            cat = CAT_ALIASES.get(folder, "sfx")
            alias = slug(f, cat)
            full = str(SFX_DIR / rel)
            meta = measure(full)
            if meta["dur"] <= 0:
                print(f"  [SKIP] {rel} (unreadable)")
                continue
            entries[alias] = {
                "file": rel.replace("\\", "/"),
                "dur": meta["dur"],
                "build": meta["build"],
                "hit": meta["hit"],
                "decay": meta["decay"],
                "desc": slug(f, cat).replace("-", " "),
            }
    OUT.write_text(json.dumps(entries, indent=1))
    print(f"  [SFX] analysed {len(entries)} sounds -> {OUT.name}")


if __name__ == "__main__":
    main()
