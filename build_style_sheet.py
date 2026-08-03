#!/usr/bin/env python3
"""build_style_sheet.py - Merge style_sheets/* into ONE 1920x1080 sheet.

Each panel is CONTAIN-fitted into a 640x540 cell (whole image visible,
correct aspect ratio preserved, nothing stretched or cropped), arranged 3x2
like the character sheets. Output: style_sheets/style_sheet.png - the
channel-wide style reference for Split Node (fed as ref #1 in identity
mode: style + character + location all real references, not img2img).

Usage: python build_style_sheet.py
"""
import glob
import os
import sys
from pathlib import Path

from PIL import Image, ImageDraw

PROJECT = Path(__file__).resolve().parent
SRC = PROJECT / "style_sheets"
OUT = SRC / "style_sheet.png"
CELL_W, CELL_H, COLS = 640, 540, 3
GAP = 8  # px between cells


def _load_images():
    files = []
    for ext in ("*.jpg", "*.jpeg", "*.png", "*.webp", "*.bmp"):
        files.extend(sorted(SRC.glob(ext)))
    # exclude the merged output itself + any existing panel files
    files = [f for f in files if f.name != "style_sheet.png"]
    imgs = []
    for p in files:
        try:
            im = Image.open(p).convert("RGB")
            imgs.append((p.name, im))
        except Exception as e:
            print(f"  [WARN] skip {p.name}: {e}")
    return imgs


def main() -> int:
    imgs = _load_images()
    if not imgs:
        print("[FAIL] no images found in style_sheets/")
        return 1
    print(f"[STYLE] merging {len(imgs)} images -> 1920x1080 sheet (contain-fit cells)")
    rows = (len(imgs) + COLS - 1) // COLS
    sheet = Image.new("RGB", (COLS * CELL_W, rows * CELL_H), (10, 10, 12))
    draw = ImageDraw.Draw(sheet)
    for i, (name, im) in enumerate(imgs):
        col, row = i % COLS, i // COLS
        cx, cy = col * CELL_W, row * CELL_H
        # contain-fit: scale so the whole image fits the cell, keep AR
        scale = min((CELL_W - 2 * GAP) / im.width, (CELL_H - 2 * GAP) / im.height)
        nw, nh = max(1, int(im.width * scale)), max(1, int(im.height * scale))
        thumb = im.resize((nw, nh), Image.LANCZOS)
        px = cx + (CELL_W - nw) // 2
        py = cy + (CELL_H - nh) // 2
        sheet.paste(thumb, (px, py))
        draw.rectangle([cx, cy, cx + CELL_W - 1, cy + CELL_H - 1],
                       outline=(90, 90, 100), width=2)
        print(f"  [STYLE] {name:16s} {im.size} -> cell {nw}x{nh} @ ({px},{py})")
    sheet.save(OUT)
    print(f"[STYLE] sheet: {OUT} ({os.path.getsize(OUT)//1024}KB, {sheet.size})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
