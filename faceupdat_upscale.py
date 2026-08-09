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
               skip_if_larger=False, tile=512, tile_overlap=64):
    """Tile-based neural upscale -> exact target size.

    Uses the model's OWN scale factor (model.scale, e.g. 2 for RealESRGAN
    x2plus, 4 for FaceUpDAT). Splitting the source into ~512px tiles keeps each
    pass tiny (fast, low VRAM), then we mosaic the result and cover-fit to the
    exact target. This is the standard low-VRAM upscale pattern. Returns True.
    """
    import torch
    import numpy as np
    from PIL import Image, ImageOps, ImageFilter
    t0 = time.time()
    img = Image.open(in_path).convert("RGB")
    w, h = img.size
    if skip_if_larger and w >= target_w and h >= target_h:
        print(f"[UPSCALE] {os.path.basename(in_path)} already {w}x{h} "
              f"(target {target_w}x{target_h}) - no upscale needed")
        return True
    scale = int(getattr(model, "scale", 4) or 4)
    # scale x the source -> cover-fit to target. Mosaic canvas at scale x size.
    ow, oh = w * scale, h * scale
    canvas = Image.new("RGB", (ow, oh))
    t = max(int(tile), 64)
    ov = max(int(tile_overlap), 16)
    step = t - ov
    xs = list(range(0, w, step))
    ys = list(range(0, h, step))
    with torch.inference_mode():
        for yi, y0 in enumerate(ys):
            for xi, x0 in enumerate(xs):
                x1 = min(x0 + t, w)
                y1 = min(y0 + t, h)
                tile_img = img.crop((x0, y0, x1, y1))
                arr = np.asarray(tile_img, dtype=np.uint8)
                in_t = (torch.from_numpy(arr.copy()).permute(2, 0, 1)
                        .unsqueeze(0).to(device).bfloat16() / 255.0)
                in_t = in_t.to(memory_format=torch.channels_last)
                out = model(in_t)
                if isinstance(out, (tuple, list)):
                    out = out[0]
                elif hasattr(out, "output"):
                    out = out.output
                out_u8 = (out.clamp(0, 1) * 255.0).round().to(torch.uint8)
                res = (out_u8.squeeze(0).permute(1, 2, 0)
                       .contiguous().cpu().numpy())
                canvas.paste(Image.fromarray(res), (x0 * scale, y0 * scale))
    # Seams from tiling: light blur across tile boundaries, then exact cover-fit.
    canvas = canvas.filter(ImageFilter.GaussianBlur(1))
    out_img = ImageOps.fit(canvas, (target_w, target_h), Image.LANCZOS)
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    out_img.save(out_path)
    print(f"[UPSCALE] {os.path.basename(in_path)} {w}x{h} -> "
          f"{target_w}x{target_h} ({scale}x neural) in {time.time()-t0:.1f}s "
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
    # --serve mode: load the model ONCE, then process JSON job lines from
    # stdin. One embedded-python subprocess is reused for every upscale, so
    # the ~40s model load happens a single time instead of per image.
    if "--serve" in sys.argv:
        return _serve_main()
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


def _serve_main() -> int:
    """Read JSON jobs line-by-line from stdin, one upscale per line.

    Job line: {"in": <in>, "out": <out>, "w": <w>, "h": <h>, "skip": <bool>}
    After each job prints a single 'DONE <out> <0|1>' line (flushed) so the
    parent can pair results to requests under concurrency.
    """
    import json
    import threading
    if len(sys.argv) < 3:
        print("[FAIL] usage: faceupdat_upscale.py --serve --model <model>")
        return 1
    model_path = None
    i = 2
    while i < len(sys.argv):
        if sys.argv[i] == "--model" and i + 1 < len(sys.argv):
            model_path = sys.argv[i + 1]
            i += 2
        else:
            i += 1
    if not model_path or not os.path.isfile(model_path):
        print(f"[FAIL] model not found: {model_path}")
        return 1
    model, device = load_model(model_path)
    _lock = threading.Lock()
    print("[READY]", flush=True)
    for raw in sys.stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            job = json.loads(raw)
        except Exception as e:
            print(f"[FAIL] bad job: {e}", flush=True)
            continue
        in_path = job.get("in")
        out_path = job.get("out")
        w = int(job.get("w", 1920))
        h = int(job.get("h", 1080))
        skip = bool(job.get("skip", False))
        ok = 0
        if not (in_path and out_path and os.path.isfile(in_path)):
            print(f"[FAIL] missing in/out for {in_path}", flush=True)
            continue
        try:
            with _lock:
                ok = 1 if upscale_to(model, device, in_path, out_path,
                                     w, h, skip_if_larger=skip) else 0
        except Exception as e:
            print(f"[FAIL] {e}", flush=True)
            ok = 0
        print(f"DONE {out_path} {ok}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
