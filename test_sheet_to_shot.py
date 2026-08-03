#!/usr/bin/env python3
"""test_sheet_to_shot.py - Full character sheet -> test shot (production path).

1. Build the complete 6-panel Elon character sheet through the real
   production function (_generate_character_sheet): identity mode, style
   plate on the FACE panel only, face -> side/back -> body chain carries
   the style through.
2. Generate a test shot with the PRODUCTION ref model: [styled face panel,
   styled location, styled prop] and NO style sheet - every ref is already
   styled so the shot inherits style from its assets.

Run from the project dir. Needs ComfyUI on 8199."""
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import system_breakers as sb

PROJECT = Path(__file__).resolve().parent
TEST_DIR = PROJECT / "test_output" / "sheet_to_shot"
TEST_DIR.mkdir(parents=True, exist_ok=True)

SHEET = {
    "role": "entrepreneur",
    "name": "Elon Musk",
    "age": "50s",
    "gender": "male",
    "appearance": "angular face, short dark hair, light stubble",
    "clothing": "black t-shirt, dark jeans",
}


def main() -> int:
    print("=== ELON FULL SHEET -> TEST SHOT (production path) ===")
    t0 = time.time()
    sheet_path = sb._generate_character_sheet("Elon Musk", SHEET, 42424, TEST_DIR)
    print(f"[SHEET] {'OK' if sheet_path else 'FAIL'} | {sheet_path}")
    print(f"[SHEET] elapsed {((time.time()-t0)/60):.1f} min")
    if not sheet_path or not os.path.isfile(sheet_path):
        return 1

    face_panel = TEST_DIR / "elon_musk_face.png"
    location = PROJECT / "test_output" / "style_assets" / "location_vault.png"
    prop = PROJECT / "test_output" / "style_assets" / "prop_briefcase.png"
    refs = []
    if os.path.isfile(face_panel):
        refs.append(str(face_panel))
    if os.path.isfile(location):
        refs.append(str(location))
    if os.path.isfile(prop):
        refs.append(str(prop))
    print(f"[SHOT] refs = {[os.path.basename(r) for r in refs]} (NO style sheet)")

    shot_prompt = (
        f"{sb.RENDER_STYLE}. Elon Musk in a dark underground casino vault "
        "room, standing at a long table holding a black leather briefcase, "
        "looking at the camera, neutral expression. Cinematic wide shot, "
        "eye-level camera angle. 16:9 widescreen cinematic documentary frame"
    )
    out = TEST_DIR / "shot_vault_elon.png"
    t1 = time.time()
    ok = sb._krea_generate(shot_prompt, 88888, str(out),
                           ref_images=refs, denoise=1.0,
                           ref_mode="identity", ref_boost=4.0, grounding_px=1024,
                           steps=10, upscale=True)
    print(f"[SHOT] {'OK' if ok else 'FAIL'} | {out if ok else 'n/a'}")
    print(f"[SHOT] elapsed {((time.time()-t1)/60):.1f} min")
    if ok:
        from PIL import Image
        im = Image.open(out)
        print(f"[SHOT] size {im.size}")
    print("=== DONE ===")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
