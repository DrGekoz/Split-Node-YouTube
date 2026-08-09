"""Clean single-shot: does codex exec actually generate a NEW file, and how long does it take?"""
import os, sys, time, glob, subprocess
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import providers

generated = os.path.expanduser("~/.codex/generated_images")
def scan():
    return {os.path.abspath(p): os.path.getmtime(p) for p in
            (glob.glob(generated+"/**/call_*.png", recursive=True) +
             glob.glob(generated+"/**/ig_*.png", recursive=True))}

before = scan()
print(f"[TEST] files on disk BEFORE: {len(before)}, newest mtime: "
      f"{max(before.values()) if before else 'NONE'}", flush=True)
print("[TEST] running ONE codex exec with a UNIQUE prompt...", flush=True)
t0 = time.time()
c = providers.Codex()
ok = c.generate_image(
    "A translucent glass jellyfish floating in deep ocean, bioluminescent, 1280x720, unique test gen "+str(int(time.time())),
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "codex_parallel_test", "single_test.png"),
    ref_images=None, timeout=900,
)
dt = time.time() - t0
after = scan()
new = {p: t for p, t in after.items() if p not in before}
print(f"\n[TEST] single-shot returned ok={ok} in {dt:.1f}s")
print(f"[TEST] files on disk AFTER: {len(after)}")
print(f"[TEST] NEW files created this run: {len(new)}")
for p, t in sorted(new.items(), key=lambda x: x[1]):
    print(f"   NEW {os.path.basename(p)}  mtime={t}")
if not new:
    print("\n[FAIL] codex exec did NOT create any new output file - "
          "the 'ok' result came from grabbing an OLD on-disk image via the fallback path")
