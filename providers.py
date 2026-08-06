#!/usr/bin/env python3
"""providers.py - Unified image + video generation backends for Split Node.

Every image and video call routes through ONE entry point and picks a backend
at runtime, so the pipeline can run fully local (ComfyUI), or fall back to /
mix in cloud providers (fal.ai, RunPod) per model.

Selection logic (env vars, all optional):

  IMAGE_BACKEND=local|runpod|fal      (default: local)
  IMAGE_MODEL=<name>                   (default: backend's default model)
  VIDEO_BACKEND=runpod|fal|local      (default: runpod)
  VIDEO_MODEL=<name>                   (default: backend's default model)

  A backend can also be chosen per-call by passing backend=/model=.

Backends:
  local   - ComfyUI (Krea 2 Turbo FP8, --lowvram) via krea2_splitnode.
            Images support character/location/prop reference panels and
            in-graph 4x-FaceUpDAT upscale. Video = ComfyUI (if a video
            workflow/model is installed), else not available.
  runpod  - RunPod serverless endpoints (async /run + /status poll).
            Images: z-image-turbo, google-nano-banana-2-edit.
            Video: minimax-hailuo-02-std, minimax-hailuo-2-3-fast,
                   google-veo3-1-fast-i2v, p-video.
  fal     - fal.ai (sync /fal.run + async queue).
            Images: flux/dev, flux/schnell, nano-banana-2, z-image-turbo.
            Video: minimax-hailuo, veo3.1, pika (registered by name).

Keys are read from environment or the project .env (never committed).
"""
import json
import os
import time
import urllib.request
import urllib.error
from pathlib import Path

# ---------------------------------------------------------------------------
# Keys + project root (.env loaded here; system_breakers also loads it)
# ---------------------------------------------------------------------------
PROJECT_DIR = Path(__file__).resolve().parent


def _load_dotenv():
    envf = PROJECT_DIR / ".env"
    if envf.is_file():
        for line in envf.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k, v = k.strip(), v.strip().strip("\"'")
            os.environ.setdefault(k, v)


_load_dotenv()


def _key(name: str) -> str:
    return (os.environ.get(name) or "").strip()


FAL_API_KEY = _key("FAL_API_KEY")
RUNPOD_API_KEY = _key("RUNPOD_API_KEY")
RUNPOD_BASE = "https://api.runpod.ai/v2"
FAL_SYNC = "https://fal.run"
FAL_QUEUE = "https://queue.fal.run"

# ---------------------------------------------------------------------------
# Backend / model registry + selection
# ---------------------------------------------------------------------------
IMAGE_BACKENDS = ("local", "runpod", "fal", "codex")
VIDEO_BACKENDS = ("runpod", "fal", "local")

IMAGE_MODELS = {
    "local": {"krea2-turbo": "krea2_turbo_fp8", "z-image-turbo": "z-image-turbo-Q6_K.gguf"},
    "runpod": {
        "z-image-turbo": "z-image-turbo",
        "nano-banana-2": "google-nano-banana-2-edit",
    },
    "fal": {
        "flux-dev": "fal-ai/flux/dev",
        "flux-schnell": "fal-ai/flux/schnell",
        "nano-banana-2": "fal-ai/nano-banana-2",
        "z-image-turbo": "fal-ai/z-image-turbo",
        "gpt-image-2": "openai/gpt-image-2",
    },
    "codex": {
        "gpt-image-2": "gpt-image-2",  # Codex CLI /imagegen -> GPT Image 2
    },
}

# video: value = (endpoint_id, kind)  kind: runpod / fal
VIDEO_MODELS = {
    "runpod": {
        "hailuo-02-std": ("minimax-hailuo-02-std", "runpod"),
        "hailuo-2-3-fast": ("minimax-hailuo-2-3-fast", "runpod"),
        "veo3-1-fast": ("google-veo3-1-fast-i2v", "runpod"),
        "p-video": ("p-video", "runpod"),
    },
    "fal": {
        "runway-gen3": ("fal-ai/runway-gen3/turbo/image-to-video", "fal"),
        "veo3-1": ("fal-ai/veo-3.1-fast", "fal"),
        "minimax-hailuo": ("fal-ai/minimax/video-01", "fal"),
    },
    "local": {"comfyui": ("", "comfyui")},
}

IMAGE_DEFAULTS = {"local": "krea2-turbo", "runpod": "z-image-turbo",
                  "fal": "flux-schnell", "codex": "gpt-image-2"}
VIDEO_DEFAULTS = {"runpod": "hailuo-02-std", "fal": "minimax-hailuo",
                  "local": "comfyui"}


def _env_backend(which: str) -> str:
    return (os.environ.get(f"{which}_BACKEND", "").strip() or
            ("local" if which == "IMAGE" else "runpod")).lower()


def _env_model(which: str, backend: str) -> str:
    return (os.environ.get(f"{which}_MODEL", "").strip() or
            (IMAGE_DEFAULTS if which == "IMAGE" else VIDEO_DEFAULTS)[backend])


def _resolve_image(backend: str | None, model: str | None) -> tuple[str, str]:
    backend = (backend or _env_backend("IMAGE")).lower()
    if backend not in IMAGE_BACKENDS:
        raise ValueError(f"unknown IMAGE_BACKEND '{backend}' (local|runpod|fal)")
    model = (model or _env_model("IMAGE", backend)).lower()
    if model not in IMAGE_MODELS[backend]:
        raise ValueError(
            f"unknown IMAGE_MODEL '{model}' for backend '{backend}' - "
            f"choose one of: {', '.join(IMAGE_MODELS[backend])}")
    return backend, model


def _resolve_video(backend: str | None, model: str | None) -> tuple[str, str, str]:
    backend = (backend or _env_backend("VIDEO")).lower()
    if backend not in VIDEO_BACKENDS:
        raise ValueError(f"unknown VIDEO_BACKEND '{backend}' (runpod|fal|local)")
    model = (model or _env_model("VIDEO", backend)).lower()
    if model not in VIDEO_MODELS[backend]:
        raise ValueError(
            f"unknown VIDEO_MODEL '{model}' for backend '{backend}' - "
            f"choose one of: {', '.join(VIDEO_MODELS[backend])}")
    endpoint, kind = VIDEO_MODELS[backend][model]
    return backend, endpoint, kind


def list_image_models() -> None:
    print("Image backends & models (IMAGE_BACKEND / IMAGE_MODEL):")
    for b in IMAGE_BACKENDS:
        print(f"  {b:8} default={IMAGE_DEFAULTS[b]:16} models: "
              f"{', '.join(IMAGE_MODELS[b])}")


def list_video_models() -> None:
    print("Video backends & models (VIDEO_BACKEND / VIDEO_MODEL):")
    for b in VIDEO_BACKENDS:
        print(f"  {b:8} default={VIDEO_DEFAULTS[b]:18} models: "
              f"{', '.join(VIDEO_MODELS[b])}")


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------
def _http_json(url: str, payload: dict | None = None, headers: dict | None = None,
               timeout: int = 120, method: str | None = None) -> dict:
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        url, data=data, method=method or ("POST" if payload is not None else "GET"),
        headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        raw = e.read().decode(errors="ignore")
        try:
            return json.loads(raw)
        except Exception:
            return {"error": f"HTTP {e.code}: {raw[:200]}"}
    except Exception as e:
        return {"error": str(e)}


def _download(url: str, out: str, timeout: int = 300) -> bool:
    try:
        urllib.request.urlretrieve(url, out)
        return os.path.getsize(out) > 500
    except Exception:
        return False


def _fetch(url: str, out: str, auth_headers: dict | None = None,
           timeout: int = 300) -> bool:
    """Download a file honoring extra auth headers (fal media is public)."""
    req = urllib.request.Request(url, headers=auth_headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp, \
             open(out, "wb") as f:
            f.write(resp.read())
        return os.path.getsize(out) > 500
    except Exception:
        return False


# ---------------------------------------------------------------------------
# RunPod client (async /run + /status poll)
# ---------------------------------------------------------------------------
class RunPod:
    def __init__(self, key: str = ""):
        self.key = key or RUNPOD_API_KEY
        if not self.key:
            raise RuntimeError("RUNPOD_API_KEY not set")

    def _headers(self):
        return {"Authorization": f"Bearer {self.key}"}

    def submit(self, endpoint: str, input_: dict) -> str:
        r = _http_json(f"{RUNPOD_BASE}/{endpoint}/run",
                       payload={"input": input_}, headers=self._headers(),
                       timeout=60)
        if "error" in r or not r.get("id"):
            raise RuntimeError(f"RunPod submit failed: {r.get('error', r)}")
        return r["id"]

    def wait(self, endpoint: str, job_id: str, timeout: int = 600,
             interval: int = 6, label: str = "job") -> dict:
        t0 = time.time()
        last = {}
        while time.time() - t0 < timeout:
            last = _http_json(f"{RUNPOD_BASE}/{endpoint}/status/{job_id}",
                              headers=self._headers(), timeout=60)
            st = last.get("status")
            if st == "COMPLETED":
                return last
            if st == "FAILED":
                raise RuntimeError(f"RunPod {label} failed: "
                                   f"{str(last.get('output'))[:200]}")
            time.sleep(interval)
        raise RuntimeError(f"RunPod {label} timed out after {int(timeout)}s")

    def generate_image(self, endpoint: str, prompt: str, seed: int,
                       out_path: str, size: str = "1024*1024",
                       strength: float = 0.8, safety: bool = False,
                       image_url: str | None = None) -> bool:
        inp = {
            "prompt": prompt, "size": size, "strength": strength,
            "seed": seed, "output_format": "png",
            "enable_safety_checker": safety,
        }
        if image_url:  # nano-banana-2 edit takes an input image
            inp["image"] = image_url
        job = self.submit(endpoint, inp)
        res = self.wait(endpoint, job, label="image")
        url = (res.get("output") or {}).get("result", "")
        if not url:
            return False
        ok = _fetch(url, out_path)
        print(f"  [RUNPOD] {os.path.basename(out_path)} "
              f"({os.path.getsize(out_path)//1024 if ok else 0}KB)")
        return ok

    def generate_video(self, endpoint: str, prompt: str, out_path: str,
                       image_url: str | None = None, duration: int = 6,
                       aspect_ratio: str = "16:9", resolution: str = "720p",
                       generate_audio: bool = True, seed: int = 0,
                       go_fast: bool = True, timeout: int = 1200) -> bool:
        inp = {
            "prompt": prompt, "duration": duration,
            "enable_prompt_expansion": True, "seed": seed,
            "enable_safety_checker": False,
        }
        if image_url:
            inp["image"] = image_url
        if "hailuo-2-3-fast" in endpoint:
            inp["go_fast"] = go_fast
        if "veo3" in endpoint:
            inp.update({"aspect_ratio": aspect_ratio, "resolution": resolution,
                        "generate_audio": generate_audio})
        if "p-video" in endpoint:
            inp.update({"size": resolution, "fps": 24, "aspect_ratio": aspect_ratio,
                        "draft": False, "save_audio": True, "prompt_upsampling": True})
        job = self.submit(endpoint, inp)
        res = self.wait(endpoint, job, timeout=timeout, label="video")
        url = (res.get("output") or {}).get("result", "")
        if not url:
            return False
        ok = _fetch(url, out_path)
        print(f"  [RUNPOD] {os.path.basename(out_path)} "
              f"({os.path.getsize(out_path)//1024 if ok else 0}KB)")
        return ok


# ---------------------------------------------------------------------------
# Codex CLI client (local GPT Image 2 via `codex exec --skip-git-repo-check
# '/imagegen <prompt>'`). Uses OpenAI Codex CLI + its built-in image_gen tool,
# which calls GPT Image 2. The generated PNG lands in a fresh session folder
# under ~/.codex/generated_images/<uuid>/; we take the newest one.
# ---------------------------------------------------------------------------
def _codex_available() -> bool:
    try:
        import shutil
        return shutil.which("codex") is not None or shutil.which("codex.exe") is not None
    except Exception:
        return False


class Codex:
    def __init__(self):
        if not _codex_available():
            raise RuntimeError("codex CLI not found on PATH - install with: npm install -g @openai/codex")

    def generate_image(self, prompt: str, out_path: str,
                       timeout: int = 900) -> bool:
        import shutil
        import subprocess
        import tempfile
        import glob
        generated = Path.home() / ".codex" / "generated_images"
        generated.mkdir(parents=True, exist_ok=True)
        before = set(glob.glob(str(generated / "**" / "ig_*.png"), recursive=True))

        # Codex is a Windows Node app -> always shell through powershell.exe.
        # The --skip-git-repo-check flag MUST come BEFORE the /imagegen prompt.
        ps_cmd = ("codex exec --skip-git-repo-check " +
                  "/imagegen " + _ps_quote(prompt))
        cmd = ["powershell.exe", "-NoProfile", "-Command", ps_cmd]
        print(f"  [CODEX] running codex exec /imagegen (this can take a minute)...")
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True,
                                  timeout=timeout)
        except subprocess.TimeoutExpired:
            print("  [CODEX] timed out generating image")
            return False

        # No reliable "saved to X" line - find the NEWEST generated image.
        after = set(glob.glob(str(generated / "**" / "ig_*.png"), recursive=True))
        new = after - before
        if not new:
            # fall back to newest mtime if the session folder already existed
            all_imgs = sorted(glob.glob(str(generated / "**" / "ig_*.png"), recursive=True),
                              key=os.path.getmtime, reverse=True)
            if all_imgs:
                new = {all_imgs[0]}
        if not new:
            print("  [CODEX] no generated image found under ~/.codex/generated_images")
            return False
        src = sorted(new, key=os.path.getmtime, reverse=True)[0]
        try:
            shutil.copy2(src, out_path)
        except Exception as e:
            print(f"  [CODEX] failed to copy output: {e}")
            return False
        print(f"  [CODEX] {os.path.basename(out_path)} ({os.path.getsize(out_path)//1024}KB)")
        return os.path.getsize(out_path) > 500


def _ps_quote(s: str) -> str:
    """Escape a string for a PowerShell single-quoted argument."""
    return "'" + s.replace("'", "''") + "'"


def _faceupdat_upscale(image_path: str, out_path: str,
                       width: int = 1920, height: int = 1080,
                       timeout: int = 900) -> bool:
    """Upscale an existing image through ComfyUI's 4xFaceUpDAT model, then
    ImageScale to the target resolution. Used to pipe Codex/GPT-Image-2 output
    up to the final shot/panel/thumbnail resolution (in-graph, no second GPU
    process). Reuses krea2_splitnode's ComfyUI connection helpers."""
    import shutil
    try:
        import krea2_splitnode as krea
    except Exception as e:
        print(f"  [UPSCALE] import krea2_splitnode failed: {e}")
        return False
    try:
        base = krea._comfy_url()
    except Exception as e:
        print(f"  [UPSCALE] ComfyUI not reachable: {str(e)[:80]}")
        return False
    try:
        # Upload the codex output into ComfyUI's input dir.
        ref = krea._upload_ref(image_path, base)
        api = {
            "1": {"class_type": "LoadImage", "inputs": {"image": ref}},
            "2": {"class_type": "UpscaleModelLoader",
                  "inputs": {"model_name": krea.UPSCALER}},
            "3": {"class_type": "ImageUpscaleWithModel",
                  "inputs": {"upscale_model": ["2", 0], "image": ["1", 0]}},
            "4": {"class_type": "ImageScale",
                  "inputs": {"image": ["3", 0], "upscale_method": "lanczos",
                             "width": width, "height": height, "crop": "center"}},
            "5": {"class_type": "SaveImage",
                  "inputs": {"images": ["4", 0], "filename_prefix": "splitnode_up"}},
        }
        queued = krea._req(base, "/prompt", {"prompt": api}, timeout=120)
        pid = queued.get("prompt_id")
        if not pid:
            print(f"  [UPSCALE] submit failed: {str(queued)[:150]}")
            return False
        t0 = time.time()
        while time.time() - t0 < timeout:
            try:
                hist = krea._req(base, f"/history/{pid}", timeout=30)
            except OSError:
                time.sleep(5)
                continue
            entry = hist.get(pid)
            if entry and entry.get("outputs"):
                imgs = []
                for node_out in entry["outputs"].values():
                    imgs.extend(node_out.get("images", []))
                if imgs:
                    img = imgs[0]
                    dl = (f"{base}/view?filename={img['filename']}"
                          f"&subfolder={img.get('subfolder', '')}"
                          f"&type={img.get('type', 'output')}")
                    with urllib.request.urlopen(dl, timeout=120) as r:
                        with open(out_path, "wb") as f:
                            f.write(r.read())
                    print(f"  [UPSCALE] {os.path.basename(out_path)} "
                          f"({os.path.getsize(out_path)//1024}KB, {width}x{height})")
                    return os.path.getsize(out_path) > 500
            time.sleep(3)
        print("  [UPSCALE] timed out waiting for upscale job")
    except Exception as e:
        print(f"  [UPSCALE] error: {str(e)[:150]}")
    return False


# ---------------------------------------------------------------------------
# fal.ai client (sync /fal.run + async queue fallback)
# ---------------------------------------------------------------------------
class Fal:
    def __init__(self, key: str = ""):
        self.key = key or FAL_API_KEY
        if not self.key:
            raise RuntimeError("FAL_API_KEY not set")

    def _headers(self):
        return {"Authorization": f"Key {self.key}"}

    def generate_image(self, model: str, prompt: str, seed: int,
                       out_path: str, num_steps: int = 4,
                       image_url: str | None = None,
                       image_size: str | None = None) -> bool:
        payload = {"prompt": prompt, "num_inference_steps": num_steps,
                   "enable_safety_checker": False}
        if "gpt-image-2" in model:
            # GPT Image 2: no steps, uses image_size + num_images
            payload = {"prompt": prompt, "image_size": image_size or "landscape_16_9",
                       "num_images": 1}
        elif "nano-banana" in model:
            payload["image_url"] = image_url if image_url else \
                "https://image.runpod.ai/assets/google/veo3-1-fast-i2v.png"
            payload["image_size"] = "square_hd"
        if image_url and "nano-banana" not in model and "gpt-image-2" not in model:
            payload["image_url"] = image_url
        if seed and "gpt-image-2" not in model:
            payload["seed"] = seed
        r = _http_json(f"{FAL_SYNC}/{model}", payload=payload,
                       headers=self._headers(), timeout=180)
        imgs = r.get("images") or r.get("output") or []
        url = None
        if isinstance(imgs, list) and imgs:
            url = imgs[0].get("url")
        elif isinstance(imgs, dict):
            url = imgs.get("url")
        if not url:
            raise RuntimeError(f"fal {model} returned no image: {str(r)[:200]}")
        ok = _fetch(url, out_path)
        print(f"  [FAL] {os.path.basename(out_path)} "
              f"({os.path.getsize(out_path)//1024 if ok else 0}KB)")
        return ok

    def generate_video(self, model: str, prompt: str, out_path: str,
                       image_url: str | None = None, duration: int = 6,
                       timeout: int = 1200) -> bool:
        payload = {"prompt": prompt}
        if image_url:
            payload["image_url"] = image_url
        if "minimax" in model or "video-01" in model:
            payload["duration"] = duration
            payload["num_frames"] = duration * 24
        elif "runway" in model or "gen3" in model:
            # runway-gen3 turbo: duration must be 5 or 10
            payload["duration"] = 5 if duration <= 5 else 10
        r = _http_json(f"{FAL_SYNC}/{model}", payload=payload,
                       headers=self._headers(), timeout=timeout)
        url = None
        vids = r.get("video") or r.get("output")
        if isinstance(vids, dict):
            url = vids.get("url")
        elif isinstance(vids, list) and vids:
            url = vids[0].get("url")
        if not url:
            raise RuntimeError(f"fal {model} returned no video: {str(r)[:200]}")
        ok = _fetch(url, out_path)
        print(f"  [FAL] {os.path.basename(out_path)} "
              f"({os.path.getsize(out_path)//1024 if ok else 0}KB)")
        return ok


# ---------------------------------------------------------------------------
# Public unified entry points
# ---------------------------------------------------------------------------
def generate_image(prompt: str, seed: int, out_path: str,
                   backend: str | None = None, model: str | None = None,
                   ref_images: list | None = None, denoise: float = 0.55,
                   upscale: bool = True, size: str = "1024*1024",
                   strength: float = 0.8, timeout: int = 1800,
                   steps: int = 8, cfg: float = 1.0,
                   width: int = 1280, height: int = 720,
                   ref_mode: str = "img2img",
                   ref_method: str = "index_timestep_zero",
                   ref_boost: float = 4.0, grounding_px: int = 1024,
                   ref_images_b: list | None = None,
                   out_dir: str | None = None,
                   image_url: str | None = None,
                   image_size: str | None = None,
                   negative_prompt: str = "") -> bool:
    """Generate one image on the selected backend. Returns True on success."""
    backend, model = _resolve_image(backend, model)

    if backend == "local":
        try:
            import krea2_splitnode as krea
        except Exception as e:
            print(f"  [LOCAL] import krea2_splitnode failed: {e}")
            return False
        try:
            return krea.generate(
                prompt, seed, out_path, ref_images, denoise, upscale,
                timeout=timeout, steps=steps, cfg=cfg, width=width,
                height=height, ref_mode=ref_mode, ref_method=ref_method,
                ref_boost=ref_boost, grounding_px=grounding_px,
                ref_images_b=ref_images_b, negative_prompt=negative_prompt)
        except Exception as e:
            print(f"  [LOCAL] {str(e)[:140]}")
            return False

    if backend == "runpod":
        try:
            rp = RunPod()
        except RuntimeError as e:
            print(f"  [RUNPOD] {e}")
            return False
        try:
            endpoint = IMAGE_MODELS["runpod"][model]  # key -> runpod endpoint id
            return rp.generate_image(endpoint, prompt, seed, out_path,
                                     size=size, strength=strength,
                                     image_url=image_url)
        except Exception as e:
            print(f"  [RUNPOD] {str(e)[:140]}")
            return False

    if backend == "codex":
        try:
            c = Codex()
        except RuntimeError as e:
            print(f"  [CODEX] {e}")
            return False
        ok = c.generate_image(prompt, out_path)
        if not ok:
            return False
        # Pipe codex output through FaceUpDAT upscaler to reach target res.
        if upscale:
            return _faceupdat_upscale(out_path, out_path, width=width,
                                      height=height)
        return True

    if backend == "fal":
        try:
            f = Fal()
        except RuntimeError as e:
            print(f"  [FAL] {e}")
            return False
        try:
            endpoint = IMAGE_MODELS["fal"][model]  # key -> fal model id
            return f.generate_image(endpoint, prompt, seed, out_path,
                                    num_steps=steps, image_url=image_url,
                                    image_size=image_size)
        except Exception as e:
            print(f"  [FAL] {str(e)[:140]}")
            return False

    return False


# ---------------------------------------------------------------------------
# Thumbnail generation - routed through the same provider backends but with a
# separate backend/model selection (THUMBNAIL_BACKEND / THUMBNAIL_MODEL) and
# 16:9 landscape sizing (YouTube thumbnails). Falls back to IMAGE_* when the
# thumbnail vars aren't set.
# ---------------------------------------------------------------------------
def _resolve_thumbnail() -> tuple[str, str]:
    backend = (os.environ.get("THUMBNAIL_BACKEND", "").strip()
               or _env_backend("IMAGE") or "local").lower()
    if backend not in IMAGE_BACKENDS:
        backend = "local"
    model = (os.environ.get("THUMBNAIL_MODEL", "").strip()
             or _env_model("IMAGE", backend)).lower()
    if model not in IMAGE_MODELS[backend]:
        model = IMAGE_DEFAULTS[backend]
    return backend, model

def generate_thumbnail(prompt: str, out_path: str,
                       seed: int = 70001,
                       backend: str | None = None,
                       model: str | None = None) -> bool:
    """Generate a 16:9 landscape YouTube thumbnail on the selected backend."""
    if (backend or model) is None:
        backend, model = _resolve_thumbnail()
    else:
        b, m = _resolve_thumbnail()
        backend, model = backend or b, model or m
    # route through the shared image path with landscape sizing
    return generate_image(
        prompt, seed, out_path, backend=backend, model=model,
        upscale=False, size="1280*720", width=1280, height=720,
        steps=6, image_size="landscape_16_9")


def generate_video(prompt: str, out_path: str,
                   backend: str | None = None, model: str | None = None,
                   image_url: str | None = None, duration: int = 6,
                   aspect_ratio: str = "16:9", resolution: str = "720p",
                   generate_audio: bool = True, seed: int = 0,
                   go_fast: bool = True, timeout: int = 1200) -> bool:
    """Generate one video clip on the selected backend. Returns True."""
    backend, endpoint, kind = _resolve_video(backend, model)

    if kind == "runpod":
        try:
            rp = RunPod()
        except RuntimeError as e:
            print(f"  [RUNPOD] {e}")
            return False
        try:
            return rp.generate_video(
                endpoint, prompt, out_path, image_url=image_url,
                duration=duration, aspect_ratio=aspect_ratio,
                resolution=resolution, generate_audio=generate_audio,
                seed=seed, go_fast=go_fast, timeout=timeout)
        except Exception as e:
            print(f"  [RUNPOD] {str(e)[:140]}")
            return False

    if kind == "fal":
        try:
            f = Fal()
        except RuntimeError as e:
            print(f"  [FAL] {e}")
            return False
        try:
            return f.generate_video(endpoint, prompt, out_path,
                                    image_url=image_url, duration=duration,
                                    timeout=timeout)
        except Exception as e:
            print(f"  [FAL] {str(e)[:140]}")
            return False

    if backend == "local":
        print("  [LOCAL] no video workflow/model installed yet - "
              "set VIDEO_BACKEND=runpod or fal")
        return False

    return False


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] in ("--list-images", "list-images"):
        list_image_models()
    elif len(sys.argv) > 1 and sys.argv[1] in ("--list-videos", "list-videos"):
        list_video_models()
    else:
        list_image_models()
        list_video_models()
