"""Test: does 3-way parallel codex image gen actually work (no output collision) at 1280x720?"""
import os, sys, threading, time, hashlib, subprocess
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["IMAGE_BACKEND"] = "codex"
import providers
from PIL import Image

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "codex_parallel_test")
os.makedirs(OUT, exist_ok=True)

PROMPTS = [
    "A red sports car parked on a rainy neon city street at night, cinematic, 1280x720 landscape",
    "A lone astronaut standing on a desert dune under two moons, 1280x720 landscape, cinematic",
    "An old wooden lighthouse on a cliff during a storm, waves crashing, 1280x720 landscape, cinematic",
]

results = {}
def run(i, prompt):
    out = os.path.join(OUT, f"img_{i}.png")
    t0 = time.time()
    try:
        ok = providers.generate_image(
            prompt,  # prompt
            70000 + i,  # seed
            out,
            backend="codex",
            ref_images=None, denoise=1.0, upscale=True,
            width=1280, height=720, image_size="landscape_16_9",
        )
        results[i] = (ok, out, time.time() - t0)
    except Exception as e:
        results[i] = (False, out, 0, repr(e))

print("[TEST] launching 3 parallel codex generate_image calls...", flush=True)
t0 = time.time()
threads = [threading.Thread(target=run, args=(i, p)) for i, p in enumerate(PROMPTS)]
for t in threads: t.start()
for t in threads: t.join()
wall = time.time() - t0

print(f"\n=== RESULTS (wall clock {wall:.1f}s for 3 parallel) ===")
all_ok = True
hashes = {}
for i in sorted(results):
    ok, out, dur = results[i][0], results[i][1], results[i][2]
    extra = results[i][3] if len(results[i]) > 3 else None
    size = "MISSING"
    if os.path.isfile(out) and os.path.getsize(out) > 500:
        with open(out, "rb") as f:
            h = hashlib.md5(f.read()).hexdigest()[:10]
        im = Image.open(out); w, hh = im.size
        size = f"{w}x{hh}"
        hashes[h] = hashes.get(h, []) + [i]
    else:
        all_ok = False
        size = "FAILED"
    print(f"  img_{i}: ok={ok} dur={dur:.1f}s size={size} hash={'NA' if 'FAILED' in size else hashes}")
    if extra: print(f"         error: {extra}")

print(f"\n=== DEDUP CHECK ===")
distinct = len(hashes)
print(f"  distinct images generated: {distinct}")
for h, idxs in hashes.items():
    print(f"  hash {h} -> images {idxs}")
if distinct < 3:
    print("  [FAIL] COLLISION DETECTED - parallel claims stole each other's output")
    all_ok = False
else:
    print("  [OK] 3 distinct images claimed, no collision")

# Ensure exact 1280x720 (codex may output non-720 sizes - force it here)
print(f"\n=== FORCE 1280x720 ===")
for i in sorted(results):
    out = results[i][1]
    if not os.path.isfile(out) or os.path.getsize(out) <= 500:
        continue
    im = Image.open(out)
    if im.size != (1280, 720):
        im = im.resize((1280, 720), Image.LANCZOS)
        im.save(out)
        print(f"  img_{i}: resized to 1280x720 (was {im.size})")
    else:
        print(f"  img_{i}: already 1280x720")

print(f"\nVERDICT: {'PASS - parallel codex gen works' if all_ok else 'FAIL'}")
print(f"outputs in: {OUT}")
