#!/usr/bin/env python3
"""Generate ONE 1280x1280 face-front panel of Elon Musk for EVERY selectable
style profile, using the cached real photo as the ONLY identity ref + the
style injected as TEXT. Output: style_previews/elon_musk_face_<style>.png"""
import importlib.util, os, sys, time
from pathlib import Path
HERE = Path(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, str(HERE))
spec = importlib.util.spec_from_file_location("sb", str(HERE / "system_breakers.py"))
sb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sb)
import krea2_splitnode as krea

REF = HERE / "cast_refs" / "real" / "elon_musk.jpg"
assert REF.is_file(), "elon real photo missing"
OUT = HERE / "style_previews"
OUT.mkdir(exist_ok=True)

# Clean face-front view_desc (style injected separately - no hardcoded style
# text, no 'reference artwork' language, no people-to-copy confusion).
FACE = ("Close-up portrait of THIS EXACT MAN's face, head and face only, full "
        "face centered, both eyes looking at camera, hair styled as in the "
        "reference, expression neutral. Nothing else in frame - no shoulders, "
        "no neck, no body. The person shown is THIS EXACT MAN and no one else. "
        "Plain light grey studio background, flat even neutral lighting, no "
        "dramatic lighting, no rim light, one person only.")

styles = list(sb.STYLE_PROFILES.keys())
print(f"[STYLEGEN] {len(styles)} styles -> {OUT}", flush=True)
for i, name in enumerate(styles, 1):
    os.environ["STYLE"] = name
    sb._STYLE_SELECTED_PRINTED["done"] = False
    p = FACE + " " + sb._style_inject()
    out = str(OUT / f"elon_musk_face_{name}.png")
    if os.path.isfile(out) and os.path.getsize(out) > 5000:
        print(f"[{i}/{len(styles)}] reuse {name}", flush=True)
        continue
    print(f"[{i}/{len(styles)}] {name}: generating (ref=elon_musk.jpg)...", flush=True)
    t0 = time.time()
    ok = krea.generate(p, seed=70001 + i, out_path=out,
                       ref_images=[str(REF)], denoise=1.0, upscale=False,
                       steps=10, width=1280, height=1280,
                       ref_mode="identity", ref_boost=4.0, grounding_px=1024,
                       prefix=f"elonface_{name}")
    print(f"[{i}/{len(styles)}] {name}: {'OK' if ok else 'FAIL'} "
          f"in {time.time()-t0:.0f}s -> {out}", flush=True)
print("[STYLEGEN] DONE", flush=True)
