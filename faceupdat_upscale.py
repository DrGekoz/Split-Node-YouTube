#!/usr/bin/env python3
"""Standalone 4xFaceUpDAT upscaler — NO ComfyUI needed.

Loads the FaceUpDAT model directly with torch + spandrel (same embedded Python
ComfyUI uses) and upscales an image to an exact target size. Runs standalone so
a codex/fal/runpod image-gen run can use neural FaceUpDAT upscaling without the
ComfyUI server being up.

Usage:
  python faceupdat_upscale.py <model.safetensors> <input> <output> <W> <H> [--skip-if-larger]
"""
import os
import sys
import time
from pathlib import Path


def upscale_to(model, device, in_path, out_path, target_w, target_h,
               skip_if_larger=False):
    import torch
    import numpy as np
    from PIL import Image, ImageOps
    t0 = time.time()
    img = Image.open(in_path).convert("RGB")
    w, h = img.size
    if skip_if_larger and w >= target_w and h >= target_h:
        print(f"[UPSCALE] {os.path.basename(in_path)} already {w}x{h} "
              f"(target {target_w}x{target_h}) - no upscale needed")
        return True
    arr = np.asarray(img, dtype=np.uint8)
    in_t = torch.from_numpy(arr.copy()).permute(2, 0, 1).unsqueeze(0).to(device).bfloat16() / 255.0
    in_t = in_t.to(memory_format=torch.channels_last)
    with torch.inference_mode():
        out = model(in_t)
    if isinstance(out, (tuple, list)):
        out = out[0]
    elif hasattr(out, "output"):
        out = out.output
    # 4x neural upscale, then bicubic-downscale/cover-crop to the EXACT target.
    out = torch.nn.functional.interpolate(
        out, size=(target_h * 4, target_w * 4), mode="bicubic", align_corners=False)
    out_u8 = (out.clamp(0, 1) * 255.0).round().to(torch.uint8)
    res = out_u8.squeeze(0).permute(1, 2, 0).contiguous().cpu().numpy()
    out_img = Image.fromarray(res)
    out_img = ImageOps.fit(out_img, (target_w, target_h), Image.LANCZOS)
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    out_img.save(out_path)
    print(f"[UPSCALE] {os.path.basename(in_path)} {w}x{h} -> "
          f"{target_w}x{target_h} in {time.time()-t0:.1f}s "
          f"({os.path.getsize(out_path)//1024}KB)")
    return True


def load_model(model_path):
    import torch
    from spandrel import ModelLoader
    print(f"[UPSCALE] Model {os.path.basename(model_path)} ...")
    if model_path.lower().endswith(".safetensors"):
        from safetensors.torch import load_file
        sd = load_file(model_path)
    else:
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
    print(f"[UPSCALE] device={device} bf16={torch.cuda.is_available()} "
          f"scale={model.scale}")
    return model, device


def main():
    if len(sys.argv) < 6:
        print("usage: faceupdat_upscale.py <model> <input> <output> <W> <H> "
              "[--skip-if-larger]")
        return 1
    model_path, in_path, out_path = sys.argv[1], sys.argv[2], sys.argv[3]
    target_w, target_h = int(sys.argv[4]), int(sys.argv[5])
    skip = "--skip-if-larger" in sys.argv
    if not os.path.isfile(model_path):
        print(f"[FAIL] model not found: {model_path}")
        return 1
    if not os.path.isfile(in_path):
        print(f"[FAIL] input not found: {in_path}")
        return 1
    model, device = load_model(model_path)
    try:
        ok = upscale_to(model, device, in_path, out_path,
                        target_w, target_h, skip_if_larger=skip)
        return 0 if ok else 1
    except Exception as e:
        print(f"[FAIL] {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
