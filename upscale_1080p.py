#!/usr/bin/env python3
"""Upscale still images to exactly 1920x1080 using GPU hardware scaling.

Uses ffmpeg's CUDA scaler (scale_cuda, interp_algo=lanczos) - the NVENC-class
hardware path, no AI model. Requires the format=nv12 pre-convert, otherwise
scale_cuda fails with "Unsupported conversion: rgb0 -> semiplanar8".

Usage:
  python upscale_1080p.py <input.png> [output.png]
  python upscale_1080p.py --dir <folder>            # process all *.png/*.jpg in place
  python upscale_1080p.py --dir <folder> --out <outdir>  # write to another folder
"""
import os
import subprocess
import sys
from pathlib import Path

TARGET_W, TARGET_H = 1920, 1080

# FFmpeg GPU pipeline: nv12 pre-convert -> upload to CUDA -> hardware lanczos
# scale -> download -> back to rgb24 for PNG encode.
FILTER = (
    f"format=nv12,hwupload_cuda,"
    f"scale_cuda={TARGET_W}:{TARGET_H}:interp_algo=lanczos,"
    f"hwdownload,format=nv12,format=rgb24"
)


def upscale_image(in_path: str, out_path: str, quiet: bool = False) -> bool:
    """GPU-upscale one image to 1920x1080. Returns True on success."""
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", in_path,
        "-vf", FILTER,
        "-frames:v", "1",
        out_path,
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0 or not os.path.isfile(out_path) or os.path.getsize(out_path) < 1000:
        print(f"[FAIL] {os.path.basename(in_path)}: {r.stderr.strip()[:200]}")
        return False
    if not quiet:
        print(f"[UPSCALE] {os.path.basename(in_path)} -> {TARGET_W}x{TARGET_H} -> {out_path}")
    return True


def main():
    args = [a for a in sys.argv[1:] if a]
    if not args:
        print(__doc__)
        return 1
    if args[0] == "--dir":
        folder = args[1]
        outdir = None
        if "--out" in args:
            outdir = args[args.index("--out") + 1]
        exts = (".png", ".jpg", ".jpeg", ".webp", ".bmp")
        files = [p for p in sorted(Path(folder).iterdir())
                 if p.suffix.lower() in exts and p.is_file()]
        if not files:
            print(f"[FAIL] no images found in {folder}")
            return 1
        ok = 0
        for p in files:
            out = (Path(outdir) / p.name) if outdir else p
            if upscale_image(str(p), str(out)):
                ok += 1
        print(f"[UPSCALE] done: {ok}/{len(files)} -> {TARGET_W}x{TARGET_H}")
        return 0 if ok == len(files) else 2
    else:
        in_path = args[0]
        out_path = args[1] if len(args) > 1 else (
            str(Path(in_path).with_suffix("")) + "_1080p.png")
        if not os.path.isfile(in_path):
            print(f"[FAIL] input not found: {in_path}")
            return 1
        return 0 if upscale_image(in_path, out_path) else 1


if __name__ == "__main__":
    sys.exit(main())
