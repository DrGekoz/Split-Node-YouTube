#!/usr/bin/env python3
"""Regenerate the mannequin style preview using the CANONICAL REAL-FACE method.

Uses the real Elon photo as the ONE identity ref and renders a glossy
porcelain mannequin whose facial features (bone structure, brow, nose, lips,
jaw) match the ref EXACTLY - the face reads as a polished museum mannequin
resembling the person, not realistic human skin. Hair is coloured and matches
the ref. This is the method the pipeline uses (MANNEQUIN_PANELS).

Output: style_previews/elon_musk_face_mannequin.png  (forced overwrite)
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

NAME = "mannequin"
os.environ["STYLE"] = NAME

hair = ("short dark black-brown hair with grey at the temples, neatly "
        "styled, slicked-back modern cut")

# Canonical real-face mannequin prompt (identical to MANNEQUIN_PANELS['face']).
MANNEQUIN_FACE = (
    "A seamless glossy porcelain mannequin head and face, full face centered, "
    "facing the camera. The mannequin's facial structure matches the "
    "reference person EXACTLY - same bone structure, same brow ridge, same "
    "nose shape, same lips, same jawline, same eyes. BUT the whole face is "
    "rendered in smooth glossy off-white porcelain like a museum display "
    "mannequin - polished ceramic skin, no skin pores, no realistic skin "
    "texture, no stubble, no wrinkles, no skin blemishes. Glossy porcelain "
    "eyes, porcelain nose, porcelain lips - all in matching smooth ceramic "
    "finish, face of a high-end display mannequin that strongly resembles "
    "the reference person. Rich COLOURED sculpted hair styled exactly as in "
    "the reference: {hair}. Nothing else in frame - no shoulders, no neck, "
    "no body. Plain light grey studio background, flat even neutral lighting, "
    "no rim light, one mannequin head only."
).format(hair=hair)

p = MANNEQUIN_FACE + " " + sb._style_inject()
out = str(OUT / f"elon_musk_face_{NAME}.png")
print(f"[STYLEGEN] {NAME}: regenerating (real-face method, real photo ref)...", flush=True)
t0 = time.time()
ok = krea.generate(p, seed=70001 + 9, out_path=out,
                   ref_images=[str(REF)], denoise=1.0, upscale=False,
                   steps=14, width=1280, height=1280,
                   ref_mode="identity", ref_boost=2.0, grounding_px=768,
                   prefix="elonface_mannequin")
print(f"[STYLEGEN] {NAME}: {'OK' if ok else 'FAIL'} in {time.time()-t0:.0f}s -> {out}", flush=True)
print("[STYLEGEN] DONE", flush=True)
