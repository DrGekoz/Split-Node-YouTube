"""End-to-end test: real person photo -> 3D character sheet -> conditioned shot."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import system_breakers as sb
from pathlib import Path

TEST_DIR = Path(__file__).parent / "test_output" / "sheet_test"
TEST_DIR.mkdir(parents=True, exist_ok=True)

NAME = "Stefan Mandel"
SHEET = {
    "role": "lottery mathematician",
    "name": NAME,
    "age": "40s",
    "gender": "male",
    "appearance": "sharp intelligent face, short dark hair, glasses",
    "clothing": "grey suit, white shirt, no tie",
}

print("=== STEP 1: real person reference (Openverse) ===")
ref = sb._find_real_reference(NAME, "lottery mathematician")
print("REALREF:", ref)

print("=== STEP 2: character sheet (4 panels + compose) ===")
sheet_path = sb._generate_character_sheet(NAME, SHEET, 9999, TEST_DIR)
print("SHEET:", sheet_path)

print("=== STEP 3: shot conditioned on the sheet (in-graph FaceUpDAT) ===")
if sheet_path:
    prompt = (f"{sb.RENDER_STYLE}. Stefan sits at a candlelit desk in a cramped "
              f"1980s apartment, hunched over a spreadsheet of number combinations, "
              f"a worn calculator in hand. MS framing, low-angle camera angle, "
              f"16:9 widescreen cinematic documentary frame")
    ok = sb._krea_generate(prompt, 777777, str(TEST_DIR / "conditioned_shot.png"),
                           ref_images=[sheet_path], denoise=0.55, upscale=True)
    print("SHOT OK" if ok else "SHOT FAILED")
    from PIL import Image
    if os.path.isfile(TEST_DIR / "conditioned_shot.png"):
        im = Image.open(TEST_DIR / "conditioned_shot.png")
        print("SHOT SIZE:", im.size)

print("=== DONE ===")
