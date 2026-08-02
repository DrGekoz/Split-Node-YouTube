"""Mini end-to-end test for the new Split Node title/SFX pipeline.

Exercises (no RunPod, no YouTube):
  1. _insert_chapter_markers + _extract_anchor_events (real LLM call)
  2. TTS clips (real PocketTTS)
  3. voice track + faster-whisper + event resolution
  4. audio mix with intro glitch / camera shutter / typewriter / glitch-off
  5. render pass 1 (shutter black frames + black chapter card)
  6. title burn pass 2 (animated glowing titles)
Outputs go to test_output/ and a verification report is printed.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.resolve()))
import system_breakers as sb

OUT = Path(__file__).parent / "test_output"
OUT.mkdir(exist_ok=True)

NARRATION = [
    "December 12th, 2012. Goulburn, New South Wales. Armed police surround a quiet suburban house at dawn and smash through the front door. Their target doesn't run.",
    "He's asleep. Officers move room to room and find an Aston Martin DB7, a Maserati, and a speedboat in the driveway.",
    "A bank account sitting 2.1 million dollars below zero. The seizure takes hours. They photograph everything, tag everything, tow the cars.",
    "Luke Moore is nobody's idea of a master criminal. A young man from a working-class town who'd been employed since his teens, long enough to get a mortgage before most people his age had a car.",
    "March 2010. The injuries from a road accident linger, the job disappears, and the rent stops getting paid.",
    "He walks into a St. George branch and opens an account called Complete Freedom. A bank officer accidentally tags it with premium status, switching off the human being.",
    "Late 2016. Queen Square, Sydney. Three judges of the Court of Criminal Appeal convene in the matter of Moore versus R.",
    "The crown never proved deception. Conviction quashed. He walks out a free man, thinner, broke, six months of maximum security behind his eyes.",
]

def main():
    print("=" * 70)
    print("  TEST 1: chapter markers + anchor extraction")
    print("=" * 70)
    # Chapter pass needs >= 12 paras; pad with repeats for the LLM test
    long_narr = NARRATION + [f"Follow-up beat paragraph number {i} about the evidence trail and the paperwork." for i in range(10)]
    narr2, chapter_events = sb._insert_chapter_markers(long_narr)
    print(f"  chapters: {json.dumps(chapter_events, indent=1)}")
    anchor_events = sb._extract_anchor_events(narr2)
    print(f"  anchors: {json.dumps(anchor_events, indent=1)}")

    print("=" * 70)
    print("  TEST 2: TTS clips (PocketTTS, real)")
    print("=" * 70)
    # build shots for the FIRST 6 paragraphs of NARRATION + a chapter card
    shots = []
    for i, para in enumerate(NARRATION[:6]):
        shots.append({
            "narration": para, "narration_idx": i,
            "shot_type": "MS", "angle": "eye-level",
            "character": "Luke Moore" if i != 2 else "Bank Officer",
            "character_role": "protagonist" if i != 2 else "bank officer",
            "scene": "dramatic 3D documentary scene", "sfx": "NONE", "tone": "suspense",
        })
    shots.append({
        "narration": "Chapter 1 - The Account That Never Said No", "narration_idx": 6,
        "shot_type": "CU", "angle": "eye-level", "character": "NONE",
        "character_role": "", "scene": "black chapter title card placeholder",
        "sfx": "NONE", "tone": "neutral", "is_chapter": True,
        "chapter_num": 1, "chapter_title": "The Account That Never Said No",
    })
    shots.append({
        "narration": NARRATION[6], "narration_idx": 7,
        "shot_type": "WS", "angle": "high-angle", "character": "Luke Moore",
        "character_role": "protagonist", "scene": "courthouse steps", "sfx": "NONE", "tone": "neutral",
    })
    ep = 997
    ep_dir = sb.TTS_TEMP / f"ep_{ep}"
    ep_dir.mkdir(parents=True, exist_ok=True)
    for s in shots:
        out = str(ep_dir / f"narration_{s['narration_idx']:02d}.wav")
        if os.path.isfile(out) and os.path.getsize(out) > 1000:
            s["tts_path"] = out
            print(f"  [TTS] {s['narration_idx']}: reused ({sb._get_audio_duration(out):.1f}s)")
            continue
        ok = sb._pocket_tts_generate(s["narration"], out)
        if ok:
            sb._normalize_voice_0db(out)
            s["tts_path"] = out
            print(f"  [TTS] {s['narration_idx']}: {sb._get_audio_duration(out):.1f}s ok")
        else:
            s["tts_path"] = None
            print(f"  [TTS] {s['narration_idx']}: FAILED")

    # simple gradient images for non-chapter shots
    from PIL import Image
    black = sb._black_placeholder(ep)
    for i, s in enumerate(shots):
        if s.get("is_chapter"):
            s["image_path"] = black
            continue
        img = Image.new("RGB", (1280, 720), ((i * 40) % 255, (i * 70) % 255, 120))
        p = str(OUT / f"shot_{i}.png")
        img.save(p)
        s["image_path"] = p

    print("=" * 70)
    print("  TEST 3: voice track + whisper + event resolution")
    print("=" * 70)
    voice = sb._ensure_voice_track(shots, ep)
    words = sb._transcribe_voice(ep, voice)
    print(f"  voice: {voice} | whisper words: {len(words)}")
    clip_starts = sb._compute_clip_starts(shots)
    print(f"  clip_starts: {[round(c, 2) for c in clip_starts]}")
    # events: re-extract anchors from the ACTUAL 8-item narration (same order
    # as the shots' narration_idx: 6 real paras + chapter + final para)
    anchor_narr = NARRATION[:6] + ["Chapter 1 - The Account That Never Said No"] + [NARRATION[6]]
    anchor_ev = sb._extract_anchor_events(anchor_narr)
    chapter_ev = [{"chapter": 1, "title": "The Account That Never Said No", "para_idx": 6}]
    # person titles: first appearance of each canonical character
    person_ev = sb._build_person_events(shots, clip_starts)
    print(f"  person events: {[e['text'] for e in person_ev]}")
    title_events = sb._build_resolved_title_events(
        chapter_ev, anchor_ev + person_ev, words, clip_starts)
    for ev in title_events:
        print(f"    [{ev['kind']}] @{ev['start']:.2f}s end={ev.get('end')} text='{ev.get('text', ev.get('title', ev.get('text')))}'")

    print("=" * 70)
    print("  TEST 4: audio mix (intro glitch / shutter / whoosh / chapter riser+hit / typewriter / glitch-off)")
    print("=" * 70)
    mix, voice2, starts2 = sb._build_audio_mix(shots, ep, title_events)
    print(f"  mix: {mix}")

    print("=" * 70)
    print("  TEST 5: render pass 1 + title burn pass 2")
    print("=" * 70)
    video = sb._render_video(shots, ep, title_events)
    if video:
        dur = sb._get_audio_duration(video)
        print(f"  VIDEO: {video} ({dur:.1f}s, {os.path.getsize(video)//1024//1024}MB)")
        titled = str(OUT / "mini_titled.mp4")
        # burn_titles resolves the .ass relative to the VIDEO's directory, so
        # the ass must live next to the video (Windows drive-colon quirk).
        ass = str(Path(video).parent / "mini_titles.ass")
        sb.split_node_titles.build_title_ass(title_events, ass)
        ok = sb.split_node_titles.burn_titles(video, ass, titled, timeout=900)
        print(f"  BURN: {ok} -> {titled}")
    else:
        print("  RENDER FAILED")

    print("=" * 70)
    print("  TEST 6: SFX placement verification (windowed RMS on the mix)")
    print("=" * 70)
    if mix and os.path.isfile(mix):
        r = subprocess.run(["ffmpeg", "-v", "error", "-i", mix, "-f", "f32le",
                            "-ac", "1", "-ar", "24000", "-"], capture_output=True)
        import numpy as np
        pcm = np.frombuffer(r.stdout, dtype=np.float32)
        sr = 24000
        win = sr // 10
        n = len(pcm) // win
        peaks = np.max(np.abs(pcm[:n * win].reshape(n, win)), axis=1)
        for ev in title_events:
            if ev["kind"] in ("location", "timeline", "person"):
                st = ev["start"]
                for label, t in (("typewriter", st), ("glitch", st + 5.5)):
                    idx = int(t * 10)
                    region = peaks[max(idx - 1, 0):idx + 3]
                    print(f"  {label:10s} @{t:6.2f}s  peak={float(region.max()):.3f}"
                          + ("  <-- SFX present" if region.max() > 0.05 else "  <-- quiet?"))
        # chapter riser+hit: find the chapter event and check ~its start
        for ev in title_events:
            if ev["kind"] == "chapter":
                ct = ev["start"]
                idx = int(ct * 10)
                region = peaks[max(idx - 1, 0):idx + 3]
                print(f"  chapterhit @{ct:6.2f}s  peak={float(region.max()):.3f}"
                      + ("  <-- SFX present" if region.max() > 0.05 else "  <-- quiet?"))
                idxr = int((ct - 0.3) * 10)
                rregion = peaks[max(idxr - 3, 0):idxr + 1]
                print(f"  riserbuild @{ct - 0.3:6.2f}s  peak={float(rregion.max()):.3f}"
                      + ("  <-- SFX present" if rregion.max() > 0.05 else "  <-- quiet?"))
                break
        # shutter check: shot with new character (Bank Officer at clip_starts[2])
        st2 = clip_starts[2]
        idx = int((st2 + 0.1) * 10)
        region = peaks[max(idx - 1, 0):idx + 3]
        print(f"  shutter    @{st2 + 0.1:6.2f}s  peak={float(region.max()):.3f}"
              + ("  <-- SFX present" if region.max() > 0.05 else "  <-- quiet?"))
        # intro glitch at 0
        print(f"  intro      @0.00s     peak={float(peaks[0:3].max()):.3f}"
              + ("  <-- SFX present" if peaks[0:3].max() > 0.05 else "  <-- quiet?"))
    print("\nMINI TEST DONE")

if __name__ == "__main__":
    main()
