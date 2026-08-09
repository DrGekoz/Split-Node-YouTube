"""Bulk-parallel codex image gen benchmark.

Launches N concurrent `providers.generate_image(backend='codex')` calls, each
with a UNIQUE prompt, and reports how many succeeded, how many failed, and
whether any two calls claimed the same output file (a collision = the
thread-safe claim logic failed).

Usage: python codex_bulk_bench.py N [--out DIR] [--clean]
"""
import os, sys, time, hashlib, threading, shutil
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["IMAGE_BACKEND"] = "codex"
import providers

N = int(sys.argv[1]) if len(sys.argv) > 1 else 20
OUT = sys.argv[sys.argv.index("--out") + 1] if "--out" in sys.argv else \
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "codex_bulk_test")
if "--clean" in sys.argv:
    shutil.rmtree(OUT, ignore_errors=True)
os.makedirs(OUT, exist_ok=True)

# unique, verifiable prompts (a timestamp makes each definitively distinct)
TS = int(time.time())
PROMPTS = [
    f"A cinematic documentary scene #{i}: a distant figure on a foggy ridge at dawn, "
    f"wide establishing shot, moody volumetric light, 16:9. TAG {TS}-{i}" for i in range(N)
]

results = {}
def run(i, prompt):
    out = os.path.join(OUT, f"img_{i:03d}.png")
    t0 = time.time()
    try:
        ok = providers.generate_image(
            prompt, 90000 + i, out, backend="codex", ref_images=None,
            denoise=1.0, upscale=False, width=1280, height=720,
            image_size="landscape_16_9", timeout=1200,
        )
        results[i] = (ok, out, time.time() - t0)
    except Exception as e:
        results[i] = (False, out, 0, repr(e))


def _verify(files_out: list):
    """Check existing outputs for duplicates/collisions without regenerating."""
    from PIL import Image as _PIL
    hashes = {}
    ok_n = fail_n = 0
    for i in range(len(files_out)):
        out = files_out[i]
        if os.path.isfile(out) and os.path.getsize(out) > 500:
            ok_n += 1
            with open(out, "rb") as f:
                h = hashlib.md5(f.read()).hexdigest()[:10]
            w, hh = _PIL.open(out).size
            hashes.setdefault(h, []).append((i, w, hh))
        else:
            fail_n += 1
            hashes.setdefault("__MISSING__", []).append((i, 0, 0))
    dupes = {h: v for h, v in hashes.items() if len(v) > 1}
    print(f"\n=== COLLISION CHECK ({len(files_out)} existing) ===")
    print(f"  distinct hashes: {len(hashes)}")
    if dupes:
        for h, v in dupes.items():
            print(f"  [COLLISION] {h} -> {[x[0] for x in v]}")
    else:
        print(f"  [OK] all {len(files_out)} outputs distinct, no collisions")
    verdict = "PASS" if (ok_n == len(files_out) and not dupes) else "FAIL"
    print(f"VERDICT: {verdict}  ({ok_n}/{len(files_out)} ok, {fail_n} failed)")
    sys.exit(0 if verdict == "PASS" else 1)


if "--verify" in sys.argv:
    _verify([os.path.join(OUT, f"img_{i:03d}.png") for i in range(N)])

print(f"[BENCH] launching {N} PARALLEL codex generate_image calls...", flush=True)
t0 = time.time()
threads = [threading.Thread(target=run, args=(i, p)) for i, p in enumerate(PROMPTS)]
for t in threads: t.start()
for t in threads: t.join()
wall = time.time() - t0

print(f"\n=== RESULTS ({N} parallel, wall clock {wall:.1f}s, avg {wall/max(N,1):.1f}s/img) ===")
ok_n, fail_n = 0, 0
hashes = {}
files = {}
for i in sorted(results):
    r = results[i]
    ok, out, dur = r[0], r[1], r[2]
    extra = r[3] if len(r) > 3 else None
    size = "MISSING"
    h = None
    if ok and os.path.isfile(out) and os.path.getsize(out) > 500:
        ok_n += 1
        with open(out, "rb") as f:
            h = hashlib.md5(f.read()).hexdigest()[:10]
        from PIL import Image as _PIL
        im_w, im_h = _PIL.open(out).size
        size = f"{im_w}x{im_h}"
        hashes.setdefault(h, []).append(i)
        files[out] = i
    else:
        fail_n += 1
        size = "FAILED" if not ok else "EMPTY/DUPE"
    print(f"  img_{i:03d}: ok={ok} dur={dur:.1f}s size={size} hash={h or 'NA'}"
          + (f" err={extra}" if extra else ""))

# collision check: any hash claimed by 2+ distinct indexes = duplicate output
dupes = {h: idxs for h, idxs in hashes.items() if len(idxs) > 1}
print(f"\n=== COLLISION CHECK ===")
print(f"  distinct outputs: {len(hashes)} of {N}")
if dupes:
    for h, idxs in dupes.items():
        print(f"  [COLLISION] hash {h} -> images {idxs} (SAME FILE claimed by multiple)")
else:
    print(f"  [OK] all {len(hashes)} outputs distinct, no collisions")

verdict = "PASS" if (ok_n == N and not dupes) else "FAIL"
print(f"\nVERDICT: {verdict}  ({ok_n}/{N} ok, {fail_n} failed, {len(dupes)} collisions)")
print(f"outputs in: {OUT}")
sys.exit(0 if verdict == "PASS" else 1)
