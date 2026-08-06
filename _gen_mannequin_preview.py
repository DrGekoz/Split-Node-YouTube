#!/usr/bin/env python3
"""Regenerate ONLY the mannequin style preview with NO image reference.

The mannequin look is fully prompt-driven: the porcelain face is
text-controlled and the ONLY trait carried from the real person is their
HAIR, injected as TEXT (quick web search -> archetype fallback), exactly like
the mannequin character panels in the pipeline.

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

OUT = HERE / "style_previews"
OUT.mkdir(exist_ok=True)

NAME = "mannequin"
os.environ["STYLE"] = NAME

# Text hair description (NO image ref) - same path the character panels use.
# Use a specific, COLOURED hair description so the hair clearly stands out
# against the blank porcelain (dark black-brown, greying, styled short).
hair = "short dark black-brown hair with grey at the temples, neatly styled, slicked-back modern cut"
print(f"[STYLEGEN] hair text: '{hair}'", flush=True)

MANNEQUIN_FACE = (
    "Close-up portrait of a seamless glossy porcelain mannequin head and "
    "face, full face centered, facing the camera. Featureless smooth blank "
    "porcelain face - NO eyes, NO nose, NO mouth, NO eyebrows, NO facial "
    "hair, NO human facial features, NO skin texture. Smooth matte off-white "
    "cream porcelain surface, completely blank and featureless. "
    "The mannequin HAS rich, COLOURED, clearly visible sculpted hair styled "
    "exactly as: {hair} - full realistic dark hair colour that stands out "
    "vividly against the blank white porcelain face. The hair is the ONLY "
    "coloured part of the mannequin. Nothing else in frame - no shoulders, "
    "no neck, no body. Plain light grey studio background, flat even neutral "
    "lighting, no rim light, one mannequin head only."
).format(hair=hair)

p = MANNEQUIN_FACE + " " + sb._style_inject()
out = str(OUT / f"elon_musk_face_{NAME}.png")
print(f"[STYLEGEN] {NAME}: regenerating (NO image ref, text hair)...", flush=True)
t0 = time.time()
ok = krea.generate(p, seed=70001 + 9, out_path=out,
                   ref_images=None, denoise=1.0, upscale=False,
                   steps=14, width=1280, height=1280,
                   ref_mode="img2img",
                   prefix="elonface_mannequin")
print(f"[STYLEGEN] {NAME}: {'OK' if ok else 'FAIL'} in {time.time()-t0:.0f}s -> {out}", flush=True)
print("[STYLEGEN] DONE", flush=True)
