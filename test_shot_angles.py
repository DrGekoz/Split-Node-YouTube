#!/usr/bin/env python3
"""test_shot_angles.py - Prompt-adherence test: same refs, 5 different shots.

Uses the finished Elon sheet's face panel + styled location/prop refs (NO
style sheet). Each shot demands a different camera angle / pose / action to
prove the prompt controls composition instead of the refs pasting on top of
each other:

  1. low_angle     - camera LOW, looking up at him
  2. briefcase_side- briefcase held DOWN BY HIS SIDE, relaxed
  3. briefcase_cu  - CLOSEUP of the briefcase in his hand
  4. from_behind   - WIDE shot from BEHIND, back of him
  5. drawer_side   - SIDE angle, opening a cabinet drawer

Waits for test_output/sheet_to_shot/elon_musk_sheet.png (the full sheet
test) before starting. Run after that job completes."""
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import system_breakers as sb

PROJECT = Path(__file__).resolve().parent
SHEET_DIR = PROJECT / "test_output" / "sheet_to_shot"
TEST_DIR = PROJECT / "test_output" / "shot_angles"
TEST_DIR.mkdir(parents=True, exist_ok=True)

FACE = SHEET_DIR / "elon_musk_face.png"
LOCATION = PROJECT / "test_output" / "style_assets" / "location_vault.png"
PROP = PROJECT / "test_output" / "style_assets" / "prop_briefcase.png"

BASE = (
    "Realistic 3D render style, photorealistic human character with perfect "
    "anatomy, painted in the bold animated ARCANE style (strong stylized "
    "brushwork, saturated colors, dramatic rim lighting). Elon Musk in the "
    "dark underground casino vault room."
)
SHOTS = [
    ("low_angle",
     BASE + " Camera LOW angle looking up at him, he stands tall over the "
     "camera holding the black leather briefcase, dominant imposing framing. "
     "16:9 widescreen cinematic documentary frame"),
    ("briefcase_side",
     BASE + " He stands facing the camera holding the black leather "
     "briefcase DOWN BY HIS SIDE, arm relaxed, neutral stance, looking at "
     "the camera. Eye-level camera angle, medium shot. 16:9 widescreen "
     "cinematic documentary frame"),
    ("briefcase_cu",
     BASE + " CLOSEUP of the black leather briefcase held in his hand, "
     "brass latches, his fingers wrapped around the handle, shallow depth "
     "of field, the vault room blurred behind. 16:9 widescreen cinematic "
     "documentary frame"),
    ("from_behind",
     BASE + " WIDE shot from BEHIND him, back of his head and shoulders "
     "visible as he looks at the rows of safety deposit boxes, briefcase at "
     "his side, the whole vault room stretching out ahead. 16:9 widescreen "
     "cinematic documentary frame"),
    ("drawer_side",
     BASE + " SIDE angle view of him reaching to open one of the cabinet "
     "drawers in the vault wall, hand on the drawer handle, profile visible, "
     "briefcase on the floor beside him. 16:9 widescreen cinematic "
     "documentary frame"),
]


def wait_for_sheet(timeout_min: int = 40) -> bool:
    print(f"[WAIT] polling for {FACE.name} (timeout {timeout_min} min)...")
    t0 = time.time()
    while time.time() - t0 < timeout_min * 60:
        if os.path.isfile(FACE) and os.path.getsize(FACE) > 1000:
            print(f"[WAIT] sheet face panel ready ({((time.time()-t0)/60):.1f} min)")
            return True
        time.sleep(30)
    print("[WAIT] TIMEOUT - sheet never appeared")
    return False


def main() -> int:
    print("=== PROMPT-ADHERENCE TEST: same refs, 5 angles ===")
    refs = [str(FACE), str(LOCATION), str(PROP)]
    for r in refs:
        print(("  [OK] " if os.path.isfile(r) else "  [MISSING] ") + r)
    if not all(os.path.isfile(r) for r in refs):
        if not wait_for_sheet():
            return 1
    ok_count = 0
    for name, prompt in SHOTS:
        out = TEST_DIR / f"shot_{name}.png"
        if out.is_file():
            print(f"  [reuse] {out.name}")
            ok_count += 1
            continue
        print(f"  [SHOT] {name} ...")
        t0 = time.time()
        ok = sb._krea_generate(prompt, 99000 + hash(name) % 999, str(out),
                               ref_images=refs, denoise=1.0,
                               ref_mode="identity", ref_boost=4.0,
                               grounding_px=1024, steps=10, upscale=True)
        print(f"  [SHOT] {name}: {'OK' if ok else 'FAIL'} | "
              f"{((time.time()-t0)/60):.1f} min")
        if ok:
            ok_count += 1
    print(f"=== DONE ({ok_count}/{len(SHOTS)}) -> {TEST_DIR} ===")
    return 0 if ok_count else 1


if __name__ == "__main__":
    sys.exit(main())
