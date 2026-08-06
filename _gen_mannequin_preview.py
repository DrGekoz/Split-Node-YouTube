#!/usr/bin/env python3
"""Regenerate ONLY the mannequin style preview with high prompt adherence.

The other styles re-use the 'THIS EXACT MAN' face prompt + identity mode,
which copies the whole face. The mannequin style is the opposite: we want a
blank glossy porcelain head whose ONLY carried-over trait is the reference
person's hair. So this script:

  * uses a mannequin-specific prompt (featureless porcelain face, no human
    features) instead of the shared FACE prompt,
  * uses ref_mode='reference' (Krea Kontext - prompt controls composition,
    ref guides style/hair only), NOT identity (which copies the whole face),
  * lower ref_boost so the porcelain face is NOT dragged toward the human ref.

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

# Mannequin-specific prompt: the ONLY human trait that transfers is the HAIR.
# Everything else is a blank porcelain mannequin head, fully prompt-controlled.
MANNEQUIN_FACE = (
    "Close-up portrait of a seamless glossy porcelain mannequin head and face, "
    "full face centered, facing the camera. Featureless smooth blank porcelain "
    "face - NO eyes, NO nose, NO mouth, NO eyebrows, NO facial hair, NO skin "
    "texture, NO human facial features of any kind. Completely smooth matte "
    "off-white cream porcelain surface, like a museum display mannequin. "
    "The ONLY part carried from the reference person is their HAIR: the "
    "mannequin's hair is styled, colored and textured EXACTLY like the "
    "reference man's hair (same cut, same colour, same texture, same "
    "parting), sculpted into that hairstyle. Nothing else in frame - no "
    "shoulders, no neck, no body. Plain light grey studio background, flat "
    "even neutral lighting, no dramatic lighting, no rim light, one mannequin "
    "head only."
)

p = MANNEQUIN_FACE + " " + sb._style_inject()
out = str(OUT / f"elon_musk_face_{NAME}.png")
print(f"[STYLEGEN] {NAME}: regenerating (ref=elon_musk.jpg, ref_mode=reference)...", flush=True)
t0 = time.time()
ok = krea.generate(p, seed=70001 + 9, out_path=out,
                   ref_images=[str(REF)], denoise=1.0, upscale=False,
                   steps=14, width=1280, height=1280,
                   ref_mode="reference", ref_method="index_timestep_zero",
                   ref_boost=2.0, grounding_px=768,
                   prefix="elonface_mannequin")
print(f"[STYLEGEN] {NAME}: {'OK' if ok else 'FAIL'} in {time.time()-t0:.0f}s -> {out}", flush=True)
print("[STYLEGEN] DONE", flush=True)
