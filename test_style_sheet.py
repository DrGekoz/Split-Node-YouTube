#!/usr/bin/env python3
"""test_style_sheet.py - Style-sheet + real-photo identity test.

Refs (training order): image 1 = style_sheet (scene/style), image 2 = the
real photo (subject). Generates a face-front panel, then a body shot, so
Joe can judge whether the Arcane style comes through while the face stays
Elon. Uses the N-ref identity path (krea2edit LoRA, real references, NOT
img2img)."""
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import krea2_splitnode as k

PROJECT = Path(__file__).resolve().parent
TEST_DIR = PROJECT / "test_output" / "style_test"
TEST_DIR.mkdir(parents=True, exist_ok=True)

STYLE = str(PROJECT / "style_sheets" / "style_sheet.png")
REAL = str(PROJECT / "cast_refs" / "real" / "elon_musk.jpg")

PANELS = [
    ("face_front",
     "A cinematic painted portrait of THIS EXACT MAN, face and head only, "
     "full face centered, both eyes looking at camera, hair styled as in the "
     "reference, expression neutral. Painted in the bold animated style of "
     "the reference artwork: strong stylized brushwork, saturated colors, "
     "dramatic rim lighting, dark moody background. NOTHING else in frame - "
     "no shoulders, no neck, no body. One person only."),
    ("body_shot",
     "THIS EXACT MAN full body standing facing the camera, complete outfit "
     "as in the reference, face identical, entire body head to feet, both "
     "feet on the ground, arms relaxed at sides. Painted in the bold "
     "animated style of the reference artwork: strong stylized brushwork, "
     "saturated colors, dramatic rim lighting, dark moody background. ONLY "
     "ONE person, no props."),
]

def main() -> int:
    print("=== STYLE SHEET + ELON IDENTITY TEST (2 refs, identity mode) ===")
    for f in (STYLE, REAL):
        print(("  [OK] " if os.path.isfile(f) else "  [MISSING] ") + f)
    if not os.path.isfile(STYLE) or not os.path.isfile(REAL):
        return 1
    base = k._comfy_url()
    print(f"comfy: {base}")
    seed = int(time.time()) % 100000
    ok_any = False
    for view, prompt in PANELS:
        out = TEST_DIR / f"elon_{view}.png"
        if out.is_file():
            print(f"  [reuse] {out.name}")
            ok_any = True
            continue
        print(f"  [TEST] panel {view} (refs: style_sheet + real photo)...")
        t0 = time.time()
        ok = k.generate(prompt, seed + 111 * len(view), str(out),
                        ref_images=[STYLE, REAL], denoise=1.0,
                        ref_mode="identity", ref_boost=4.0, grounding_px=1024,
                        steps=10, upscale=False, prefix="styletest")
        print(f"  [TEST] {view}: {'OK' if ok else 'FAIL'} | {time.time()-t0:.0f}s")
        if ok:
            ok_any = True
    print("=== DONE ===" if ok_any else "=== ALL FAILED ===")
    return 0 if ok_any else 1

if __name__ == "__main__":
    sys.exit(main())
