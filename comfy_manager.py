#!/usr/bin/env python3
"""comfy_manager.py - Launch / verify / download-models / run workflows for
the local ComfyUI backend (Split Node provider 'local').

Responsibilities:
  1. auto_start()  - launch ComfyUI (run_nvidia_gpu.bat) if not already up,
                     wait until /system_stats answers.
  2. ensure_models() - download any missing model files into the right
                     ComfyUI models/ subdir from Hugging Face (hf CLI).
  3. run_workflow() - submit an API-format workflow graph to /prompt and
                     poll /history until the SaveImage outputs are written.

ComfyUI root is auto-detected: $COMFYUI_ROOT, else
F:/ComfyUI_windows_portable/ComfyUI (the known install).
"""
import json
import os
import subprocess
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

COMFYUI_ROOT = Path(os.environ.get(
    "COMFYUI_ROOT", "F:/ComfyUI_windows_portable/ComfyUI"))
PORTABLE_ROOT = Path(os.environ.get(
    "COMFYUI_PORTABLE", "F:/ComfyUI_windows_portable"))
LAUNCH_BAT = Path(os.environ.get(
    "COMFYUI_LAUNCH", str(PORTABLE_ROOT / "run_nvidia_gpu.bat")))

DEFAULT_PORTS = ["http://127.0.0.1:8188", "http://127.0.0.1:8199"]

# HF model sources: file path (relative to models/) -> (repo, filename)
# Models listed here are the ones Split Node's local workflows need.
MODEL_SOURCES = {
    "unet/krea2_turbo_fp8.safetensors": (
        "AlperKTS/Krea2_FP8", "krea2_turbo_fp8.safetensors"),
    "unet/z-image-turbo-Q6_K.gguf": (
        "comfyanonymous/z-image-turbo-GGUF", "z-image-turbo-Q6_K.gguf"),
    "text_encoders/qwen3vl_4b_fp8_scaled.safetensors": (
        "AlperKTS/Krea2_FP8", "qwen3vl_4b_fp8_scaled.safetensors"),
    "text_encoders/Qwen3-4B-Q2_K.gguf": (
        "comfyanonymous/Qwen3-4B-GGUF", "Qwen3-4B-Q2_K.gguf"),
    "vae/qwen_image_vae.safetensors": (
        "AlperKTS/Krea2_FP8", "qwen_image_vae.safetensors"),
}

_MODELS = None


def comfy_url() -> str:
    """Return a reachable ComfyUI base URL (env override, then ports)."""
    env = os.environ.get("COMFY_API_URL", "").strip()
    candidates = [env] if env else []
    candidates += DEFAULT_PORTS
    for base in candidates:
        if not base:
            continue
        try:
            req = urllib.request.Request(base.rstrip("/") + "/system_stats")
            with urllib.request.urlopen(req, timeout=4) as r:
                if r.status == 200:
                    return base.rstrip("/")
        except Exception:
            continue
    raise RuntimeError(
        "ComfyUI not reachable. Start it (run_nvidia_gpu.bat --lowvram).")


def is_running() -> bool:
    try:
        comfy_url()
        return True
    except Exception:
        return False


def start() -> bool:
    """Launch ComfyUI via its .bat and wait up to max_wait for it to come up."""
    if is_running():
        print("[COMFY] already running")
        return True
    if not LAUNCH_BAT.is_file():
        print(f"[COMFY] launcher not found: {LAUNCH_BAT}")
        return False
    print(f"[COMFY] starting {LAUNCH_BAT} ...")
    try:
        subprocess.Popen(
            ["cmd.exe", "/c", "start", "", str(LAUNCH_BAT)],
            cwd=str(PORTABLE_ROOT), shell=False)
    except Exception as e:
        print(f"[COMFY] launch failed: {e}")
        return False
    t0 = time.time()
    while time.time() - t0 < 300:
        try:
            comfy_url()
            print(f"[COMFY] ready after {time.time()-t0:.0f}s")
            return True
        except Exception:
            time.sleep(4)
    print("[COMFY] did not come up within 300s")
    return False


def _hf_cli() -> str | None:
    """Return an hf/huggingface-cli that can run, else None."""
    for cmd in ("hf", "huggingface-cli"):
        import shutil
        if shutil.which(cmd):
            return cmd
    return None


def missing_models() -> list:
    missing = []
    for rel, (repo, fn) in MODEL_SOURCES.items():
        target = COMFYUI_ROOT / "models" / rel
        if not target.is_file() or target.stat().st_size < 1000:
            missing.append((rel, repo, fn, str(target)))
    return missing


def ensure_models() -> list:
    """Download any missing Split Node models via the hf CLI. Returns the
    list of paths that are now present. Skips gracefully if hf isn't on PATH
    (system_breakers already covers this by falling back to cloud providers)."""
    global _MODELS
    if _MODELS is None:
        _MODELS = missing_models()
    if not _MODELS:
        print("[COMFY] all Split Node models present")
        return []
    cli = _hf_cli()
    if not cli:
        print("[COMFY] huggingface-cli not on PATH - cannot auto-download "
              "missing models (run locally or switch to runpod/fal)")
        return []
    got = []
    for rel, repo, fn, target in _MODELS:
        target = Path(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        print(f"[COMFY] downloading {repo}/{fn} -> {target}")
        try:
            r = subprocess.run(
                [cli, "download", repo, fn, "--local-dir", str(target.parent)],
                capture_output=True, text=True, timeout=1800)
            if r.returncode == 0 and target.is_file() and \
                    target.stat().st_size > 1000:
                print(f"[COMFY] downloaded {fn} "
                      f"({target.stat().st_size//1048576}MB)")
                got.append(str(target))
            else:
                print(f"[COMFY] download {fn} failed: "
                      f"{(r.stderr or r.stdout)[-200:]}")
        except Exception as e:
            print(f"[COMFY] download {fn} error: {e}")
    _MODELS = [m for m in _MODELS
               if not (Path(m[3]).is_file() and Path(m[3]).stat().st_size > 1000)]
    return got


def _http_json(base: str, path: str, body: dict | None = None,
               timeout: int = 120) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        base + path, data=data,
        method="POST" if body is not None else "GET",
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        raw = e.read().decode(errors="ignore")
        try:
            return json.loads(raw)
        except Exception:
            return {"error": f"HTTP {e.code}: {raw[:200]}"}


def run_workflow(graph: dict, timeout: int = 3600) -> bool:
    """Submit an API-format ComfyUI workflow and wait for its SaveImage
    output. graph keys are node ids. Returns True on success."""
    base = comfy_url()
    pid = _http_json(base, "/prompt", {"prompt": graph}).get("prompt_id")
    if not pid:
        return False
    t0 = time.time()
    while time.time() - t0 < timeout:
        entry = _http_json(base, f"/history/{pid}", timeout=30).get(pid)
        if entry and entry.get("outputs"):
            for node_out in entry["outputs"].values():
                if node_out.get("images"):
                    print("[COMFY] workflow completed")
                    return True
        if entry and entry.get("status", {}).get("status_str") in ("error", "failed"):
            print(f"[COMFY] workflow failed: {str(entry.get('status'))[:200]}")
            return False
        time.sleep(5)
    print(f"[COMFY] workflow timeout after {int(timeout)}s")
    return False


if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else "status"
    if action == "status":
        try:
            print(f"running at {comfy_url()}")
        except Exception as e:
            print(f"not running: {e}")
    elif action == "start":
        sys.exit(0 if start() else 1)
    elif action == "check-models":
        for rel, _, _, t in missing_models():
            print(f"MISSING {rel}")
        if not missing_models():
            print("all present")
    elif action == "download-models":
        sys.exit(0 if ensure_models() else 1)
    elif action == "run":
        if len(sys.argv) < 3:
            print("usage: comfy_manager.py run <workflow.json>")
            sys.exit(2)
        g = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
        sys.exit(0 if run_workflow(g) else 1)
    else:
        print("actions: status | start | check-models | download-models | run")
        sys.exit(2)
