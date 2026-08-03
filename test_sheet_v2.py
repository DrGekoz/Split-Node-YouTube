"""Sheet v2 test: 1920x1920 character sheet, 960x960 panels, 14 steps,
face panel first, body panels conditioned on [real photo + face panel]."""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import system_breakers as sb
from pathlib import Path

TEST_DIR = Path(__file__).parent / "test_output" / "sheet_v2"
TEST_DIR.mkdir(parents=True, exist_ok=True)

SHEET = {
    "role": "lottery mathematician",
    "name": "Stefan Mandel",
    "age": "40s",
    "gender": "male",
    "appearance": "sharp intelligent face, short dark hair, glasses",
    "clothing": "grey suit, white shirt, no tie",
}

t0 = time.time()
sheet_path = sb._generate_character_sheet("Stefan Mandel", SHEET, 5555, TEST_DIR)
print("SHEET:", sheet_path)
print("ELAPSED: %.1f min" % ((time.time() - t0) / 60))
if sheet_path:
    from PIL import Image
    im = Image.open(sheet_path)
    print("SHEET SIZE:", im.size, "| bytes:", os.path.getsize(sheet_path))
print("=== DONE ===")
