#!/usr/bin/env python3
"""Upscale a still image to exactly 1920x1080 with a chosen ComfyUI upscale model.

Runs on ComfyUI's embedded Python (torch cu130 + spandrel). Model upscales 4x
(bf16 + channels_last, fp16 overflows on some arches), then bicubic-downscales
with center-crop cover to exactly 1920x1080.

Usage:
  python upscale_model.py <model.pth> <input.png> [output.png]
"""
import os
import sys
import time
from pathlib import Path

TARGET_W, TARGET_H = 1920, 1080

import numpy as np


def upscale_one(model, device, in_path: str, out_path: str) -> bool:
    import torch
    from PIL import Image, ImageOps
    t0 = time.time()
    img = Image.open(in_path).convert("RGB")
    w, h = img.size
    arr = np.asarray(img, dtype=np.uint8)
    in_t = torch.from_numpy(arr.copy()).permute(2, 0, 1).unsqueeze(0).to(device).bfloat16() / 255.0
    in_t = in_t.to(memory_format=torch.channels_last)
    with torch.inference_mode():
        out = model(in_t)
    if isinstance(out, (tuple, list)):
        out = out[0]
    elif hasattr(out, "output"):
        out = out.output
    out = torch.nn.functional.interpolate(
        out, size=(TARGET_H * 4, TARGET_W * 4), mode="bicubic", align_corners=False)
    out_u8 = (out.clamp(0, 1) * 255.0).round().to(torch.uint8)
    res = out_u8.squeeze(0).permute(1, 2, 0).contiguous().cpu().numpy()
    out_img = Image.fromarray(res)
    out_img = ImageOps.fit(out_img, (TARGET_W, TARGET_H), Image.LANCZOS)
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    out_img.save(out_path)
    print(f"[UPSCALE] {os.path.basename(in_path)} {w}x{h} -> {TARGET_W}x{TARGET_H} in {time.time()-t0:.1f}s")
    return True


def load_model(model_path: str):
    import torch
    from spandrel import ModelLoader
    print(f"[UPSCALE] Model {os.path.basename(model_path)} ...")
    sd = torch.load(model_path, map_location="cpu", weights_only=False)
    if "params-ema" in sd:
        sd = sd["params-ema"]
    if "params" in sd and isinstance(sd["params"], dict):
        sd = sd["params"]
    model = ModelLoader().load_from_state_dict(sd).eval()
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = model.to(device)
    if torch.cuda.is_available():
        model = model.bfloat16()
        inner = model.model
        inner = inner.to(memory_format=torch.channels_last)
    torch.set_grad_enabled(False)
    print(f"[UPSCALE] device={device} bf16={torch.cuda.is_available()} scale={model.scale}")
    return model, device


def main():
    if len(sys.argv) < 3:
        print("usage: upscale_model.py <model.pth> <input.png> [output.png]")
        print("       upscale_model.py <model.pth> --dir <folder> [--out <outdir>] [--skip-1080p]")
        return 1
    model_path = sys.argv[1]
    if not os.path.isfile(model_path):
        print(f"[FAIL] model not found: {model_path}")
        return 1
    model, device = load_model(model_path)

    if sys.argv[2] == "--dir":
        folder = sys.argv[3]
        outdir = None
        skip_1080p = False
        if "--out" in sys.argv:
            outdir = sys.argv[sys.argv.index("--out") + 1]
        if "--skip-1080p" in sys.argv:
            skip_1080p = True
        exts = (".png", ".jpg", ".jpeg", ".webp", ".bmp")
        files = [p for p in sorted(Path(folder).iterdir())
                 if p.suffix.lower() in exts and p.is_file()]
        if skip_1080p:
            from PIL import Image
            kept = []
            for p in files:
                try:
                    with Image.open(p) as im:
                        if im.size == (TARGET_W, TARGET_H):
                            continue
                except Exception:
                    pass
                kept.append(p)
            files = kept
        if not files:
            print(f"[UPSCALE] nothing to do in {folder}")
            return 0
        print(f"[UPSCALE] batch: {len(files)} images -> 1920x1080")
        ok = 0
        for i, p in enumerate(files, start=1):
            out = (Path(outdir) / p.name) if outdir else p
            try:
                if upscale_one(model, device, str(p), str(out)):
                    ok += 1
            except Exception as e:
                print(f"[FAIL] {p.name}: {e}")
            if i % 10 == 0:
                print(f"[UPSCALE] {i}/{len(files)}")
        print(f"[UPSCALE] done: {ok}/{len(files)} -> 1920x1080")
        return 0 if ok == len(files) else 2

    in_path = sys.argv[2]
    out_path = sys.argv[3] if len(sys.argv) > 3 else (
        str(Path(in_path).with_suffix("")) + "_1080p.png")
    if not os.path.isfile(in_path):
        print(f"[FAIL] input not found: {in_path}")
        return 1
    try:
        upscale_one(model, device, in_path, out_path)
        return 0
    except Exception as e:
        print(f"[FAIL] {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
