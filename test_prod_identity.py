#!/usr/bin/env python3
"""test_prod_identity.py - Verify PRODUCTION wiring: _generate_character_sheet
with identity mode + one shot with face-panel identity ref (the exact code
paths patched into system_breakers.py)."""
import sys, os, time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import system_breakers as sb

TEST_DIR = Path(__file__).parent / "test_output" / "prod_identity"
TEST_DIR.mkdir(parents=True, exist_ok=True)

SHEET = {
    "role": "entrepreneur",
    "name": "Elon Musk",
    "age": "50s",
    "gender": "male",
    "appearance": "angular face, short dark hair, light stubble",
    "clothing": "black t-shirt, dark jeans",
}

t0 = time.time()
print("=== TEST 1: _generate_character_sheet (identity mode) ===")
sheet_path = sb._generate_character_sheet("Elon Musk", SHEET, 3333, TEST_DIR)
print("SHEET:", sheet_path)
print("ELAPSED: %.1f min" % ((time.time() - t0) / 60))

if sheet_path and os.path.isfile(sheet_path):
    face_panel = os.path.join(TEST_DIR, "elon_musk_face.png")
    print(f"\n=== TEST 2: shot with face-panel identity ref (ref_mode=identity) ===")
    t1 = time.time()
    shot_prompt = (
        "Realistic 3D render style, photorealistic human character with perfect anatomy. "
        "Elon Musk in a dark boardroom, standing at a long oak table, dramatic "
        "overhead lighting, cinematic wide shot, eye-level camera angle. "
        "3D documentary frame - 1920x1080"
    )
    out = TEST_DIR / "shot_identity_test.png"
    ok = sb._krea_generate(shot_prompt, 7777, str(out),
                           ref_images=[face_panel], denoise=1.0,
                           ref_mode="identity", ref_boost=4.0, grounding_px=1024)
    print("SHOT OK:", ok, "| path:", out if ok else "n/a")
    print("SHOT ELAPSED: %.1f min" % ((time.time() - t1) / 60))
    if ok:
        from PIL import Image
        im = Image.open(out)
        print("SHOT SIZE:", im.size)
else:
    print("SKIPPED shot test (no sheet)")
print("=== DONE ===")
