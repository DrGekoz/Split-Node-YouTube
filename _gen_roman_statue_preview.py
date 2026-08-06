#!/usr/bin/env python3
"""Generate the roman-statue style preview (Elon face-front) using the
canonical REAL-FACE method - the same as the mannequin preview but rendered
as a classical Roman marble statue.

Output: style_previews/elon_musk_face_roman-statue.png
"""
import importlib.util, os, sys, time
from pathlib import Path
HERE = Path(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, str(HERE))
spec = importlib.util.spec_from_file_location("sb", str(HERE / "system_breakers.py"))
sb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sb)
import krea2_splitnode as krea

REF = HERE / "cast_refs" / "real" / "elon_musk.jpg"
OUT = HERE / "style_previews"
OUT.mkdir(exist_ok=True)
assert REF.is_file(), "elon real photo missing"

NAME = "roman-statue"
os.environ["STYLE"] = NAME

hair = ("short dark black-brown hair with grey at the temples, neatly "
        "styled, slicked-back modern cut")

# Canonical roman-statue real-face prompt (identical to ROMAN_STATUE_PANELS face).
STATUE_FACE = (
    "A classical ancient Roman marble statue head and face, full face "
    "centered, facing the camera. The statue's facial structure matches the "
    "reference person EXACTLY - same bone structure, same brow ridge, same "
    "nose shape, same lips, same jawline, same eyes. BUT the whole face is "
    "sculpted from smooth white Carrara marble like a museum-quality Roman "
    "portrait bust - polished stone surface, chiseled features, no skin "
    "pores, no realistic skin texture, no stubble, no wrinkles, no skin "
    "blemishes. Marble eyes, marble nose, marble lips - all carved in "
    "matching stone, face of a classical Roman statue that strongly "
    "resembles the reference person. Sculpted marble hair matching the "
    "reference: {hair}. Nothing else in frame - no shoulders, no neck, no "
    "body. Plain light grey studio background, flat even neutral lighting, "
    "no rim light, one statue head only."
).format(hair=hair)

p = STATUE_FACE + " " + sb._style_inject()
out = str(OUT / f"elon_musk_face_{NAME}.png")
print(f"[STYLEGEN] {NAME}: generating (real-face method, real photo ref)...", flush=True)
t0 = time.time()
ok = krea.generate(p, seed=70001 + 10, out_path=out,
                   ref_images=[str(REF)], denoise=1.0, upscale=False,
                   steps=14, width=1280, height=1280,
                   ref_mode="identity", ref_boost=2.0, grounding_px=768,
                   prefix="elonface_roman_statue")
print(f"[STYLEGEN] {NAME}: {'OK' if ok else 'FAIL'} in {time.time()-t0:.0f}s -> {out}", flush=True)
print("[STYLEGEN] DONE", flush=True)
