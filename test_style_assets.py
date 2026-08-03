#!/usr/bin/env python3
"""test_style_assets.py - Style sheet -> styled assets -> shot, no style in shot.

Chain test:
  1. LOCATION ref:  [style_sheet]               -> styled location image
  2. PROP ref:      [style_sheet]               -> styled prop image
  3. SHOT:          [location, prop, face]      -> NO style sheet - every ref
     is already styled, so the shot inherits style from its assets.

All identity mode (krea2edit LoRA, real references, not img2img)."""
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import krea2_splitnode as k

PROJECT = Path(__file__).resolve().parent
TEST_DIR = PROJECT / "test_output" / "style_assets"
TEST_DIR.mkdir(parents=True, exist_ok=True)

STYLE = str(PROJECT / "style_sheets" / "style_sheet.png")
FACE = str(PROJECT / "test_output" / "style_test" / "elon_face_front.png")

LOCATION_PROMPT = (
    "A cinematic establishing shot of a dark underground casino vault room, "
    "rows of safety deposit boxes along the walls, a single overhead lamp "
    "casting dramatic light, dust in the beam. Painted in the bold animated "
    "style of the reference artwork: strong stylized brushwork, saturated "
    "colors, dramatic rim lighting, dark moody background. NO people, NO "
    "text, no props with writing. Wide establishing shot, one room only."
)
PROP_PROMPT = (
    "A black leather briefcase sitting on a wooden table, brass latches, "
    "slightly open showing bundles of cash. Painted in the bold animated "
    "style of the reference artwork: strong stylized brushwork, saturated "
    "colors, dramatic rim lighting, dark moody background. Single prop "
    "centered, NO people, NO text, NO logos."
)
SHOT_PROMPT = (
    "A cinematic scene of a man in a dark suit standing in a dark underground "
    "casino vault room, holding a black leather briefcase, looking at the "
    "camera with a neutral expression. Painted in the bold animated style "
    "matching the reference artwork. Strong stylized brushwork, saturated "
    "colors, dramatic rim lighting, dark moody background. ONE person, "
    "cinematic wide shot."
)

JOBS = [
    ("location_vault", LOCATION_PROMPT, [STYLE]),
    ("prop_briefcase", PROP_PROMPT, [STYLE]),
]


def run_job(name: str, prompt: str, refs: list[str]) -> str:
    out = TEST_DIR / f"{name}.png"
    if out.is_file():
        print(f"  [reuse] {out.name}")
        return str(out)
    print(f"  [GEN] {name} (refs={[os.path.basename(r) for r in refs]})...")
    t0 = time.time()
    ok = k.generate(prompt, hash(name) % 100000 + 1000, str(out),
                    ref_images=refs, denoise=1.0,
                    ref_mode="identity", ref_boost=4.0, grounding_px=1024,
                    steps=10, upscale=False, prefix="assetstyle")
    print(f"  [GEN] {name}: {'OK' if ok else 'FAIL'} | {time.time()-t0:.0f}s")
    return str(out) if ok else None


def main() -> int:
    print("=== STYLE SHEET -> STYLED ASSETS -> SHOT (no style in shot) ===")
    ok_all = True
    for f in (STYLE, FACE):
        if not os.path.isfile(f):
            print(f"  [MISSING] {f}")
            ok_all = False
    if not ok_all:
        return 1
    # 1. styled location + styled prop
    location = run_job("location_vault", LOCATION_PROMPT, [STYLE])
    prop = run_job("prop_briefcase", PROP_PROMPT, [STYLE])
    # 2. shot from already-styled assets, NO style sheet
    if location and prop and os.path.isfile(FACE):
        shot_refs = [location, prop, FACE]
        print(f"  [GEN] shot (refs={[os.path.basename(r) for r in shot_refs]}, "
              f"NO style sheet)...")
        out = TEST_DIR / "shot_vault.png"
        if not out.is_file():
            t0 = time.time()
            ok = k.generate(SHOT_PROMPT, 777001, str(out),
                            ref_images=shot_refs, denoise=1.0,
                            ref_mode="identity", ref_boost=4.0, grounding_px=1024,
                            steps=10, upscale=False, prefix="assetstyle")
            print(f"  [GEN] shot: {'OK' if ok else 'FAIL'} | {time.time()-t0:.0f}s")
        else:
            print("  [reuse] shot_vault.png")
    print("=== DONE ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
