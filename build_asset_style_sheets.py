#!/usr/bin/env python3
"""Build the dedicated location + prop STYLE SHEETS from Joe-approved panels.

The people-style sheet (style_sheets/style_sheet.png) contains faces that
bled into location/prop assets. Joe approved these CLEAN panels instead:
- Location style ref: 6 verified-clean location panels (no faces)
- Prop style ref: the good prop assets from the props folder

Both compose to 1920x1080 3x2 grids, same layout as the character sheet so
all sheets read consistently as references. Outputs:
  style_sheets/location_style_sheet.png
  style_sheets/prop_style_sheet.png
"""
import sys
from pathlib import Path
from PIL import Image, ImageDraw

PROJECT = Path(__file__).resolve().parent
OUT_DIR = PROJECT / "style_sheets"
OUT_DIR.mkdir(parents=True, exist_ok=True)

CELL_W, CELL_H = 640, 540
COLS, ROWS = 3, 2
GRID_W, GRID_H = CELL_W * COLS, CELL_H * ROWS

# Joe-approved clean location panels (from test_output/full_chain run)
LOCATION_PANELS = [
    PROJECT / "test_output" / "full_chain" / "location_sheets" / "underground_casino_vault_establishing.png",
    PROJECT / "test_output" / "full_chain" / "location_sheets" / "underground_casino_vault_front_left.png",
    PROJECT / "test_output" / "full_chain" / "location_sheets" / "dark_casino_floor_overhead.png",
    PROJECT / "test_output" / "full_chain" / "location_sheets" / "underground_casino_vault_interior.png",
    PROJECT / "test_output" / "full_chain" / "location_sheets" / "dark_casino_floor_establishing.png",
    PROJECT / "test_output" / "full_chain" / "location_sheets" / "dark_casino_floor_interior.png",
]

# Joe-approved prop assets (6 DIVERSE objects generated off the location
# style sheet - proves style-transfer-only: pistol/watch/bottle/lantern/
# book/chess). Rebuilt 2026-08-04.
PROP_PANELS = [
    PROJECT / "test_output" / "full_chain" / "props6" / "silver_pistol.png",
    PROJECT / "test_output" / "full_chain" / "props6" / "gold_pocket_watch.png",
    PROJECT / "test_output" / "full_chain" / "props6" / "whiskey_bottle.png",
    PROJECT / "test_output" / "full_chain" / "props6" / "brass_lantern.png",
    PROJECT / "test_output" / "full_chain" / "props6" / "leather-bound_book.png",
    PROJECT / "test_output" / "full_chain" / "props6" / "chess_set.png",
]


def contain_fit(im: Image.Image, cell_w: int, cell_h: int) -> Image.Image:
    """Contain-fit an image into a cell, preserving AR, centered on dark bg."""
    w, h = im.size
    scale = min(cell_w / w, cell_h / h)
    nw, nh = max(1, int(w * scale)), max(1, int(h * scale))
    im = im.resize((nw, nh), Image.LANCZOS)
    canvas = Image.new("RGB", (cell_w, cell_h), (10, 10, 12))
    canvas.paste(im, ((cell_w - nw) // 2, (cell_h - nh) // 2))
    return canvas


def compose_grid(panels, out_path: Path, label: str) -> bool:
    missing = [p for p in panels if not p.is_file()]
    if missing:
        print(f"  [MISSING] {label}:")
        for p in missing:
            print(f"    {p}")
        return False
    grid = Image.new("RGB", (GRID_W, GRID_H), (10, 10, 12))
    draw = ImageDraw.Draw(grid)
    for i, p in enumerate(panels):
        cell = contain_fit(Image.open(p).convert("RGB"), CELL_W, CELL_H)
        col, row = i % COLS, i // COLS
        grid.paste(cell, (col * CELL_W, row * CELL_H))
        draw.rectangle([col * CELL_W, row * CELL_H,
                        col * CELL_W + CELL_W - 1, row * CELL_H + CELL_H - 1],
                       outline=(120, 120, 130), width=4)
    grid.save(out_path)
    print(f"  [OK] {label} -> {out_path} ({len(panels)} panels)")
    return True


def main() -> int:
    print("=== BUILD LOCATION + PROP STYLE SHEETS ===")
    ok_loc = compose_grid(LOCATION_PANELS, OUT_DIR / "location_style_sheet.png",
                          "location style sheet")
    ok_prop = compose_grid(PROP_PANELS, OUT_DIR / "prop_style_sheet.png",
                           "prop style sheet")
    print("=== DONE ===")
    return 0 if (ok_loc and ok_prop) else 1


if __name__ == "__main__":
    sys.exit(main())
