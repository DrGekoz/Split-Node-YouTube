#!/usr/bin/env python3
"""
SPANkendata CUDA video upscaler (near-realtime on RTX 3070).
Runs on ComfyUI's embedded Python (torch cu130 + spandrel).

Model: 4x-SPANkendata (9MB, spandrel auto-detects SPAN arch)
Speed: ~8-14 fps @ 720p->4K on RTX 3070 bf16+channels_last (pipelined,
       no disk I/O - raw frames streamed between ffmpeg processes)

Pipeline:
  ffmpeg (raw decode) -> Python reader thread -> SPAN 4x on GPU
  -> bicubic to 2160p -> uint8 on GPU -> raw pipe -> ffmpeg hevc_nvenc
  -> mux with original audio.

NOTE: fp16 overflows on this SPAN arch (NaN output). bf16 is required.

Usage:
  python upscale_4k.py <input_video> [output_video]
"""
import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path

UPSCALE_MODEL = r"F:\ComfyUI_windows_portable\ComfyUI\models\upscale_models\SPANkendata.pth"
TARGET_HEIGHT = 2160  # 4K UHD
FPS = 24

import numpy as np


def get_duration(path: str) -> float:
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True, timeout=15)
        return float(r.stdout.strip())
    except Exception:
        return 0.0


def get_video_info(path: str):
    """Return (width, height, fps) via ffprobe."""
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height,r_frame_rate",
         "-of", "json", path],
        capture_output=True, text=True, timeout=15)
    import json
    d = json.loads(r.stdout)
    s = d["streams"][0]
    w, h = int(s["width"]), int(s["height"])
    num, den = s.get("r_frame_rate", "24/1").split("/")
    fps = float(num) / float(den) if float(den) else 24.0
    return w, h, fps


def main():
    if len(sys.argv) < 2:
        print("usage: upscale_4k.py <input.mp4> [output.mp4]")
        sys.exit(1)
    in_path = sys.argv[1]
    out_path = sys.argv[2] if len(sys.argv) > 2 else (
        str(Path(in_path).with_suffix("")) + "_4k.mp4")

    if not os.path.isfile(in_path):
        print(f"[FAIL] input not found: {in_path}")
        sys.exit(1)

    dur = get_duration(in_path)
    src_w, src_h, src_fps = get_video_info(in_path)
    print(f"[UPSCALE] {in_path} ({dur:.0f}s, {src_w}x{src_h}@{src_fps:.0f}fps) -> 4K {out_path}")

    import torch
    from spandrel import ModelLoader

    # -- Load model --
    print(f"[UPSCALE] Loading {UPSCALE_MODEL} ...")
    sd = torch.load(UPSCALE_MODEL, map_location="cpu", weights_only=False)
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
    print(f"[UPSCALE] Model on {device}, bf16={torch.cuda.is_available()}, scale={model.scale}")

    # Output frame size
    out_w = src_w * TARGET_HEIGHT // src_h
    out_h = TARGET_HEIGHT
    frame_bytes = out_w * out_h * 3
    print(f"[UPSCALE] Output frame: {out_w}x{out_h}")

    # -- Audio check --
    audio_ok = False
    try:
        r = subprocess.run(
            ["ffmpeg", "-v", "error", "-i", in_path, "-map", "0:a:0", "-c:a", "copy",
             "-f", "null", "-"], capture_output=True, text=True, timeout=30)
        audio_ok = r.returncode == 0
    except Exception:
        pass

    # -- Encoder --
    ffmpeg_cmd = ["ffmpeg", "-y", "-v", "error",
                  "-f", "rawvideo", "-pix_fmt", "rgb24",
                  "-s", f"{out_w}x{out_h}", "-r", str(FPS),
                  "-i", "pipe:0"]
    if audio_ok:
        ffmpeg_cmd += ["-i", in_path, "-map", "0:v:0", "-map", "1:a:0?",
                       "-c:a", "copy"]
    else:
        ffmpeg_cmd += ["-map", "0:v:0"]
    ffmpeg_cmd += ["-c:v", "hevc_nvenc", "-preset", "p7", "-rc", "vbr",
                   "-cq", "24", "-b:v", "0", "-pix_fmt", "yuv420p", out_path]
    enc = subprocess.Popen(ffmpeg_cmd, stdin=subprocess.PIPE,
                           stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

    # -- Decoder (raw RGB pipe) --
    dec = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-i", in_path,
         "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    # -- Reader thread: decode -> numpy -> queue --
    q = queue.Queue(maxsize=8)
    src_bytes = src_w * src_h * 3
    n_expected = max(int(dur * src_fps), 1)

    def reader():
        try:
            while True:
                buf = dec.stdout.read(src_bytes)
                if not buf or len(buf) < src_bytes:
                    break
                arr = np.frombuffer(buf, dtype=np.uint8).reshape(src_h, src_w, 3)
                q.put(arr)
        except Exception as e:
            print(f"  [READER] {e}")
        finally:
            q.put(None)

    thr = threading.Thread(target=reader, daemon=True)
    thr.start()

    # -- Process frames --
    print("[UPSCALE] Upscaling frames (streaming, pipelined)...")
    t0 = time.time()
    n = 0
    try:
        while True:
            arr = q.get()
            if arr is None:
                break
            # uint8 -> GPU, normalize on GPU (avoid CPU float cost)
            in_t = torch.from_numpy(arr).permute(2, 0, 1).unsqueeze(0).to(device).bfloat16() / 255.0
            in_t = in_t.to(memory_format=torch.channels_last)

            with torch.inference_mode():
                out = model(in_t)
            if isinstance(out, (tuple, list)):
                out = out[0]
            elif hasattr(out, "output"):
                out = out.output

            oh, ow = out.shape[2], out.shape[3]
            if oh != out_h or ow != out_w:
                out = torch.nn.functional.interpolate(
                    out, size=(out_h, out_w), mode="bicubic", align_corners=False)

            # clamp + quantize on GPU -> uint8 bytes
            out_u8 = (out.clamp(0, 1) * 255.0).round().to(torch.uint8)
            data = out_u8.squeeze(0).permute(1, 2, 0).contiguous().cpu().numpy().tobytes()
            enc.stdin.write(data)
            n += 1

            if n % 100 == 0 or (n % 25 == 0 and n < 100):
                el = time.time() - t0
                fps = n / el
                eta = (n_expected - n) / fps if fps > 0 else 0
                print(f"  [{n}/{n_expected}] {fps:.1f} fps, ETA {eta:.0f}s")

    finally:
        enc.stdin.close()

    dec.stdout.close()
    enc.wait(timeout=600)
    elapsed = time.time() - t0
    print(f"[UPSCALE] {n} frames in {elapsed:.0f}s ({n/elapsed:.1f} fps)")
    if enc.returncode != 0:
        err = enc.stderr.read().decode(errors="replace")[-400:]
        print(f"[FAIL] NVENC encode: {err}")
        sys.exit(1)
    if not os.path.isfile(out_path) or os.path.getsize(out_path) < 1000:
        print("[FAIL] output not created")
        sys.exit(1)
    print(f"[OK] 4K video -> {out_path} ({os.path.getsize(out_path)//1024//1024}MB)")


if __name__ == "__main__":
    main()
