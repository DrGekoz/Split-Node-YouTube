"""Reconstruct ep8's resume state from on-disk artifacts.

The original .resume_state.json for ep8 was accidentally destroyed. This
rebuilds a working state so the pipeline can resume ep8:

- narration text per clip recovered from the whisper word timings
  (rendered_audio/ep008_whisper.json, 4504 words over the voice track)
- the 9 chapter paragraphs re-inserted at their spoken positions (titles +
  times taken from the ep8 title-pass log)
- shot list regenerated via Stage 2 (_build_shot_list, LM Studio) - chapter
  paras become black cards, regular paras get fresh shot metadata
- tts_path wired to the EXISTING clips (tts_temp/ep_8/narration_*.wav) so
  resume reuses all 125 clips and rebuilds the same mix
- character sheet defs (deterministic), chapter events, location anchors

Run:  python reconstruct_ep8_state.py
"""
import json
import re
import wave
from pathlib import Path

import system_breakers as sb

EP = 8
TOPIC = ("Two arrested over credit card phishing - as the Netherlands is "
         "named Europe's worst for payment fraud")
USED = json.loads((Path(__file__).parent / ".used_articles.json").read_text())
ARTICLE_URL = next(u for u in USED if "bitdefender.com" in u
                   and "two-arrested-credit-card-phishing" in u)
# (chapter, title, spoken time) - from the ep8 STT title-pass log
CHAPTERS = [
    (1, "Surgical Strikes Against Normalcy", 267.98),
    (2, "Dust Motes and Stale Smoke", 435.12),
    (3, "Phantom Websites Unmasked", 597.98),
    (4, "Proliferation of Digital Assets", 739.74),
    (5, "Colossal Tide of Lost Value", 900.02),
    (6, "Urgent Account Alert Lure", 1066.00),
    (7, "Beyond The Statistical Rankings", 1238.20),
    (8, "Tracing Glowing Threat Lines", 1389.58),
    (9, "Selling the Blueprints Digitally", 1545.94),
]


def clip_dur(p: Path) -> float:
    with wave.open(str(p)) as w:
        return w.getnframes() / w.getframerate()


def main() -> int:
    proj = Path(__file__).parent
    ep_tts = proj / "tts_temp" / f"ep_{EP}"
    clips = sorted(ep_tts.glob("narration_*.wav"),
                   key=lambda p: int(re.search(r"narration_(\d+)", p.name).group(1)))
    if not clips:
        print("[RECON] no clips found - aborting")
        return 1
    print(f"[RECON] {len(clips)} clips")

    # clip timeline (0.3s pads - same math as _compute_clip_starts/_build_audio_mix)
    durs = [clip_dur(p) for p in clips]
    starts, cur = [], 0.0
    for d in durs:
        starts.append(cur)
        cur += d + 0.3

    # narration text per clip from whisper word timings
    words = json.loads((proj / "rendered_audio" / f"ep{EP:03d}_whisper.json").read_text())
    clip_words = [[] for _ in clips]
    ci = 0
    for wd in words:
        t = wd.get("start", 0.0)
        while ci < len(clips) - 1 and t >= starts[ci + 1]:
            ci += 1
        clip_words[ci].append(wd.get("word", ""))
    texts = [" ".join(w).strip() for w in clip_words]
    print(f"[RECON] texts recovered for {sum(1 for t in texts if t)} clips")

    # entries: (narration text, tts clip path or None) in clip order
    entries = [(texts[i], str(p)) for i, p in enumerate(clips)]

    # chapters: canonical "Chapter N - Title" line at the clip whose window
    # contains the spoken time (the chapter audio is already in that clip)
    chapter_idx: dict[int, int] = {}
    for n, title, t in CHAPTERS:
        idx = next((i for i in range(len(clips))
                    if starts[i] <= t < starts[i] + durs[i] + 0.3), None)
        if idx is None:
            idx = min(range(len(clips)), key=lambda i: abs(starts[i] - t))
        chapter_idx[n] = idx
        entries[idx] = (f"Chapter {n} - {title}", str(clips[idx]))
        print(f"[RECON] chapter {n} '{title}' -> clip {idx} (@{starts[idx]:.1f}s)")
    order = [chapter_idx[n] for n, _, _ in CHAPTERS]
    if order != sorted(order):
        print(f"[RECON] WARNING chapters out of clip order: {order}")

    paras = [e[0] for e in entries]
    print(f"\n[RECON] Stage 2: building shot list from {len(paras)} paragraphs (LLM)...")
    shots = sb._build_shot_list(paras, bible={}, context={})
    print(f"[RECON] {len(shots)} shots")

    black = sb._black_placeholder(EP)
    for sh in shots:
        i = sh.get("narration_idx", 0)
        sh["tts_path"] = entries[i][1] if 0 <= i < len(entries) else None
        if sh.get("is_chapter"):
            sh["image_path"] = black          # black card for the title burn
            sh["seed"] = 0
    missing_tts = [s for s in shots
                   if not (s.get("tts_path") and Path(s["tts_path"]).is_file())]
    print(f"[RECON] shots with tts clips: {len(shots) - len(missing_tts)}/{len(shots)}")

    chapter_events = [{"chapter": n, "title": title, "para_idx": chapter_idx[n]}
                      for n, title, _t in CHAPTERS]
    anchor_events = sb._extract_anchor_events(paras)
    character_sheets = sb._build_character_sheets(shots, paras)

    sb._save_resume_state("images", EP, ARTICLE_URL, TOPIC, shots,
                          character_sheets,
                          chapter_events=chapter_events,
                          anchor_events=anchor_events,
                          target_paras=len(paras))

    # verify round-trip
    st = sb._load_resume_state()
    print("\n[RECON] === STATE VERIFY ===")
    print("  stage:", st.get("stage"), "| ep:", st.get("episode_num"),
          "| shots:", len(st.get("shots", [])))
    print("  target_paras:", st.get("target_paras"))
    print("  chapters:", len(st.get("chapter_events", [])),
          "| anchors:", len(st.get("anchor_events", [])))
    tts_ok = sum(1 for s in st["shots"]
                 if s.get("tts_path") and Path(s["tts_path"]).is_file())
    print(f"  tts clips on disk: {tts_ok}/{len(st['shots'])}")
    chapters = [s for s in st["shots"] if s.get("is_chapter")]
    print(f"  chapter cards: {len(chapters)} | "
          f"characters: {sorted({s.get('character') for s in st['shots'] if s.get('character') != 'NONE'})}")
    print("  sample shot:", json.dumps(
        {k: st["shots"][1].get(k) for k in ("narration_idx", "character", "scene", "sfx", "tone")}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
