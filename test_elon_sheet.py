"""Sheet test v3: Elon Musk. 6-panel chain -> 1920x1080 sheet."""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import system_breakers as sb
from pathlib import Path

TEST_DIR = Path(__file__).parent / "test_output" / "elon_sheet"
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
sheet_path = sb._generate_character_sheet("Elon Musk", SHEET, 3333, TEST_DIR)
print("SHEET:", sheet_path)
print("ELAPSED: %.1f min" % ((time.time() - t0) / 60))
if sheet_path:
    from PIL import Image
    im = Image.open(sheet_path)
    print("SHEET SIZE:", im.size, "| bytes:", os.path.getsize(sheet_path))
    print("PANEL FILES:", sorted(p.name for p in TEST_DIR.iterdir()))
print("=== DONE ===")
