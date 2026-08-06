#!/usr/bin/env python3
"""krea2_splitnode.py - Local Krea 2 Turbo image generation for Split Node.

Split Node generates ALL images locally on Joe's RTX 3070 via ComfyUI
(Krea 2 Turbo FP8, --lowvram). No RunPod, no FAL, no per-image cost.

Pipeline (per shot):
  1280x720 txt2img or img2img (multi-reference supported) -> 4x-FaceUpDAT
  upscale in the SAME ComfyUI job -> ImageScale to 1920x1080. In-graph
  upscale avoids a second process fighting the GPU for VRAM.

Modes:
  generate(prompt, seed, out, ref_images=[...], denoise=0.55, upscale=True)
    - ref_images: 0+ local image paths (character sheets, props, location
      refs). Multiple refs are concatenated side-by-side as one conditioning
      strip (ImageConcat), so a shot can be composed from a character sheet
      + prop + location all at once.
    - upscale=False: raw 1280x720 output (used for character-sheet panels).

ComfyUI port auto-detect: $COMFY_API_URL else 8199 then 8188.
"""
import json
import os
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

CLIP = "qwen3vl_4b_fp8_scaled.safetensors"
UNET = "krea2_turbo_fp8.safetensors"
VAE = "qwen_image_vae.safetensors"
UPSCALER = "4xFaceUpDAT.safetensors"
IDENTITY_LORA = "krea2_identity_edit_v1_2_r128.safetensors"
WIDTH, HEIGHT = 1280, 720
OUT_W, OUT_H = 1920, 1080


def _out_res() -> tuple:
    """Upscale/Output resolution from the RESOLUTION env var (1080p default,
    4k -> 3840x2160). Also used for the final FFmpeg video output."""
    r = os.environ.get("RESOLUTION", "1080p").strip().lower()
    return (3840, 2160) if r.startswith("4k") or r in ("2160p", "uhd") else (1920, 1080)

_COMFY = None


def _comfy_url() -> str:
    global _COMFY
    if _COMFY:
        return _COMFY
    env = os.environ.get("COMFY_API_URL", "").strip()
    candidates = [env] if env else []
    candidates += ["http://127.0.0.1:8199", "http://127.0.0.1:8188"]
    for base in candidates:
        if not base:
            continue
        try:
            req = urllib.request.Request(base.rstrip("/") + "/system_stats",
                                         method="GET")
            with urllib.request.urlopen(req, timeout=4) as r:
                if r.status == 200:
                    _COMFY = base.rstrip("/")
                    return _COMFY
        except Exception:
            continue
    raise RuntimeError(
        "ComfyUI not reachable on 8199/8188. Start it (run_nvidia_gpu.bat "
        "--lowvram) before generating images.")


def _req(base: str, path: str, body: dict | None = None, timeout: int = 120) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(base + path, data=data,
                               method="POST" if body is not None else "GET",
                               headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        raw = e.read().decode(errors="ignore")
        try:
            return json.loads(raw)
        except Exception:
            return {"error": f"HTTP {e.code}: {raw[:200]}"}


def _base_graph(prompt: str, seed: int, width: int, height: int,
                prefix: str) -> dict:
    return {
        "1": {"class_type": "EmptyLatentImage",
              "inputs": {"width": width, "height": height, "batch_size": 1}},
        "2": {"class_type": "CLIPLoader",
              "inputs": {"clip_name": CLIP, "type": "krea2", "device": "default"}},
        "3": {"class_type": "UNETLoader",
              "inputs": {"unet_name": UNET, "weight_dtype": "default"}},
        "4": {"class_type": "VAELoader", "inputs": {"vae_name": VAE}},
        "5": {"class_type": "CLIPTextEncode",
              "inputs": {"text": prompt, "clip": ["2", 0]}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "", "clip": ["2", 0]}},
        "7": {"class_type": "KSampler", "inputs": {
            "model": ["3", 0], "positive": ["5", 0], "negative": ["6", 0],
            "latent_image": ["1", 0], "seed": seed, "control_after_generate": "fixed",
            "steps": 8, "cfg": 1.0, "sampler_name": "euler", "scheduler": "simple",
            "denoise": 1.0}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["7", 0], "vae": ["4", 0]}},
        "9": {"class_type": "SaveImage",
              "inputs": {"images": ["8", 0], "filename_prefix": prefix}},
    }


def _upload_ref(image_path: str, base: str) -> str:
    """Upload a local image into ComfyUI's input dir via /upload/image,
    return the filename LoadImage should use. Escape-proof multipart.

    Every ref is re-encoded as a clean 8-bit RGB PNG (capped at 4096px)
    before upload: ComfyUI 0.29.0 dies with a native access violation in
    load_image on odd formats (paletted / 16-bit / CMYK / oversized PNGs),
    which took the whole server down mid-run on ep8. The re-encode removes
    that trigger and caps the VAE-encode VRAM cost of huge reference photos.
    """
    import uuid
    import mimetypes
    boundary = "----krea" + uuid.uuid4().hex[:12]
    fn = os.path.basename(image_path)
    ct = mimetypes.guess_type(image_path)[0] or "image/png"
    tmp = None
    try:
        from PIL import Image
        im = Image.open(image_path)
        im = im.convert("RGB")
        if max(im.size) > 4096:
            im.thumbnail((4096, 4096), Image.LANCZOS)
        tmp = image_path + ".clean.png"
        im.save(tmp, "PNG")
        image_path = tmp
        fn = os.path.basename(tmp)
        ct = "image/png"
    except Exception:
        tmp = None
    try:
        with open(image_path, "rb") as f:
            data = f.read()
        _CR = bytes([13])
        _LF = bytes([10])
        _CRLF = _CR + _LF
        head = (
            "--" + boundary + "\r\n"
            "Content-Disposition: form-data; name=\"image\"; filename=\"" + fn + "\"\r\n"
            "Content-Type: " + ct + "\r\n\r\n"
        ).encode()
        tail = ("\r\n--" + boundary + "--\r\n").encode()
        body = head + data + tail
        req = urllib.request.Request(base + "/upload/image", data=body, method="POST",
                                     headers={"Content-Type":
                                              "multipart/form-data; boundary=" + boundary})
        with urllib.request.urlopen(req, timeout=120) as r:
            out = json.loads(r.read().decode())
    finally:
        if tmp and os.path.exists(tmp):
            try:
                os.remove(tmp)
            except Exception:
                pass
    name = out.get("name") or fn
    return name


def _compose_ref_strip(ref_images: list[str], sidecar_path: str) -> str:
    """Compose multiple reference images into ONE strip saved next to the
    output. Each ref is CONTAIN-fitted (whole image visible, nothing cropped)
    within a 640px-wide cell capped at 720px tall - a sheet or photo used as
    a reference must never lose panels to a cover-crop. Avoids custom
    ComfyUI concat nodes."""
    from PIL import Image
    imgs = []
    for p in ref_images:
        try:
            im = Image.open(p).convert("RGB")
        except Exception:
            continue
        w, h = im.size
        scale = min(640 / w, 720 / h)
        nw, nh = max(1, int(w * scale)), max(1, int(h * scale))
        imgs.append(im.resize((nw, nh), Image.LANCZOS))
    if not imgs:
        return ref_images[0]
    strip_h = max(im.height for im in imgs) or 720
    strip = Image.new("RGB", (sum(im.width for im in imgs), strip_h),
                      (10, 10, 12))
    x = 0
    for im in imgs:
        strip.paste(im, (x, (strip_h - im.height) // 2))
        x += im.width
    strip_path = sidecar_path + ".refstrip.png"
    strip.save(strip_path)
    return strip_path


def build_identity_api(prompt: str, seed: int, ref_names: list[str],
                       width: int, height: int,
                       ref_boost: float = 4.0, grounding_px: int = 1024,
                       steps: int = 10, upscale: bool = False,
                       prefix: str = "krea2id",
                       negative_prompt: str = "") -> dict:
    """Krea2Edit identity graph: N tight refs -> VAE source tokens (RoPE
    frames 1..N) + Qwen3-VL grounded instruction. Trained path
    (krea2_identity_edit LoRA). euler sampler (er_sde disrupts the
    reference-copy channel - official advisory), fit_mode=fit pixel path
    with target_latent wired (no mid-sampling VRAM eviction on 8GB lowvram).

    ref_names: ordered list of reference images. Training order is fixed:
    image 1 = SCENE/style, image 2 = SUBJECT/person, refs 3+ = additional
    subjects/props/location. Style-plate system: [style_plate, face_a,
    face_b, location, prop...]. Max 8 (node socket limit).
    """
    if not ref_names:
        raise ValueError("identity mode needs at least one ref image")
    if len(ref_names) > 8:
        print(f"  [KREA] WARNING: {len(ref_names)} refs given, node supports 8 - "
              f"keeping the first 8")
        ref_names = ref_names[:8]
    api = {}
    api["1"] = {"class_type": "EmptySD3LatentImage",
                "inputs": {"width": width, "height": height, "batch_size": 1}}
    api["2"] = {"class_type": "CLIPLoader",
                "inputs": {"clip_name": CLIP, "type": "krea2", "device": "default"}}
    api["3"] = {"class_type": "UNETLoader",
                "inputs": {"unet_name": UNET, "weight_dtype": "default"}}
    api["4"] = {"class_type": "VAELoader", "inputs": {"vae_name": VAE}}
    api["5"] = {"class_type": "LoraLoaderModelOnly",
                "inputs": {"model": ["3", 0], "lora_name": IDENTITY_LORA,
                           "strength_model": 1.0}}
    # refs: node 6/7 = ref A (LoadImage/VAEEncode), 14/15 = ref B,
    # 16/17 = ref C, 18/19 = D, 20/21 = E, 22/23 = F, 24/25 = G, 26/27 = H
    _SLOT_LOAD = [6, 14, 16, 18, 20, 22, 24, 26]
    _SLOT_VAE = [7, 15, 17, 19, 21, 23, 25, 27]
    load_nodes = []
    for i, rn in enumerate(ref_names):
        ln, vn = _SLOT_LOAD[i], _SLOT_VAE[i]
        api[str(ln)] = {"class_type": "LoadImage", "inputs": {"image": rn}}
        api[str(vn)] = {"class_type": "VAEEncode",
                        "inputs": {"pixels": [str(ln), 0], "vae": ["4", 0]}}
        load_nodes.append(str(ln))
    patch_inputs = {
        "model": ["5", 0],
        "source_latent": [str(_SLOT_VAE[0]), 0],
        "ref_boost": ref_boost, "ref_boost_a": 1.0,
        "fit_mode": "fit", "vae": ["4", 0],
        "source_image": [str(_SLOT_LOAD[0]), 0],
        "target_latent": ["1", 0]}
    enc_inputs_a = {"clip": ["2", 0],
                    "image": [str(_SLOT_LOAD[0]), 0],
                    "grounding_px": grounding_px}
    # second ref onwards -> _b.._h sockets
    for i in range(1, len(ref_names)):
        suf = "b" if i == 1 else chr(ord("a") + i)  # b, c, d, e, f, g, h
        patch_inputs[f"source_latent_{suf}"] = [str(_SLOT_VAE[i]), 0]
        patch_inputs[f"source_image_{suf}"] = [str(_SLOT_LOAD[i]), 0]
        if i == 1:
            enc_inputs_a["image_b"] = [str(_SLOT_LOAD[i]), 0]
        else:
            enc_inputs_a[f"image_{suf}"] = [str(_SLOT_LOAD[i]), 0]
    api["8"] = {"class_type": "Krea2EditModelPatch", "inputs": patch_inputs}
    api["9"] = {"class_type": "Krea2EditGroundedEncode",
                "inputs": dict(enc_inputs_a, prompt=prompt)}
    api["10"] = {"class_type": "Krea2EditGroundedEncode",
                 "inputs": dict(enc_inputs_a, prompt=negative_prompt)}
    api["11"] = {"class_type": "KSampler", "inputs": {
        "model": ["8", 0], "positive": ["9", 0], "negative": ["10", 0],
        "latent_image": ["1", 0], "seed": seed, "control_after_generate": "fixed",
        "steps": steps, "cfg": 1.0, "sampler_name": "euler", "scheduler": "simple",
        "denoise": 1.0}}
    api["12"] = {"class_type": "VAEDecode",
                 "inputs": {"samples": ["11", 0], "vae": ["4", 0]}}
    if upscale:
        api["50"] = {"class_type": "UpscaleModelLoader", "inputs": {"model_name": UPSCALER}}
        api["51"] = {"class_type": "ImageUpscaleWithModel",
                     "inputs": {"upscale_model": ["50", 0], "image": ["12", 0]}}
        api["52"] = {"class_type": "ImageScale", "inputs": {
            "image": ["51", 0], "upscale_method": "lanczos",
            "width": _out_res()[0], "height": _out_res()[1], "crop": "disabled"}}
        api["13"] = {"class_type": "SaveImage",
                     "inputs": {"images": ["52", 0], "filename_prefix": prefix}}
    else:
        api["13"] = {"class_type": "SaveImage",
                     "inputs": {"images": ["12", 0], "filename_prefix": prefix}}
    return api


def build_api(prompt: str, seed: int, ref_images: list[str] | None = None,
              denoise: float = 0.55, width: int = WIDTH, height: int = HEIGHT,
              upscale: bool = True, prefix: str = "splitnode",
              steps: int = 8, cfg: float = 1.0,
              ref_mode: str = "img2img",
              ref_method: str = "index_timestep_zero") -> dict:
    """Full graph with optional reference conditioning + optional in-graph
    FaceUpDAT upscale to 1920x1080.

    ref_mode:
      "img2img"   - VAEEncode the ref, KSampler denoise <1 (composition
                    copies the ref - good for shots, BAD for pose changes:
                    a front-facing ref stays front-facing).
      "reference" - Krea 2 native reference conditioning
                    (Krea2OstrisEditModelPatch + TextEncodeKrea2OstrisEdit +
                    FluxKontextMultiReferenceLatentMethod). The ref guides
                    IDENTITY/STYLE only; the prompt fully controls pose and
                    composition. denoise is forced to 1.0.

    ref_method (reference mode only): "zero" = reference-only (pose from
      prompt - use for side/back views), "index_timestep_zero" = structure
      copied at late timesteps (use for front views where the ref IS the
      composition).

    steps/cfg: turbo defaults 8/1.0 (fast); sheets use steps=14 for prompt
    coherence (cfg above 1.0 oversaturates the turbo arch)."""
    api = _base_graph(prompt, seed, width, height, prefix)
    api["7"]["inputs"]["steps"] = steps
    api["7"]["inputs"]["cfg"] = cfg
    if ref_images:
        api["11"] = {"class_type": "LoadImage", "inputs": {"image": ref_images}}
        if ref_mode == "reference":
            # Krea 2 reference conditioning: identity from ref, pose from prompt
            api["32"] = {"class_type": "Krea2OstrisEditModelPatch",
                         "inputs": {"model": ["3", 0], "kv_cache": False}}
            api["7"]["inputs"]["model"] = ["32", 0]
            api["33"] = {"class_type": "TextEncodeKrea2OstrisEdit", "inputs": {
                "clip": ["2", 0], "prompt": prompt, "vae": ["4", 0],
                "image1": ["11", 0]}}
            api["34"] = {"class_type": "TextEncodeKrea2OstrisEdit", "inputs": {
                "clip": ["2", 0], "prompt": "", "vae": ["4", 0],
                "image1": ["11", 0]}}
            api["35"] = {"class_type": "FluxKontextMultiReferenceLatentMethod",
                         "inputs": {"conditioning": ["33", 0],
                                    "reference_latents_method": ref_method}}
            api["36"] = {"class_type": "FluxKontextMultiReferenceLatentMethod",
                         "inputs": {"conditioning": ["34", 0],
                                    "reference_latents_method": ref_method}}
            api["7"]["inputs"]["positive"] = ["35", 0]
            api["7"]["inputs"]["negative"] = ["36", 0]
            api["7"]["inputs"]["denoise"] = 1.0
        else:
            api["12"] = {"class_type": "VAEEncode",
                         "inputs": {"pixels": ["11", 0], "vae": ["4", 0]}}
            api["7"]["inputs"]["latent_image"] = ["12", 0]
            api["7"]["inputs"]["denoise"] = denoise
    if upscale:
        api["50"] = {"class_type": "UpscaleModelLoader", "inputs": {"model_name": UPSCALER}}
        api["51"] = {"class_type": "ImageUpscaleWithModel",
                     "inputs": {"upscale_model": ["50", 0], "image": ["8", 0]}}
        api["52"] = {"class_type": "ImageScale", "inputs": {
            "image": ["51", 0], "upscale_method": "lanczos",
            "width": _out_res()[0], "height": _out_res()[1], "crop": "disabled"}}
        api["9"]["inputs"]["images"] = ["52", 0]
    return api


def _generate_once(prompt: str, seed: int, out_path: str,
             ref_images: list[str] | None = None, denoise: float = 0.55,
             upscale: bool = True, timeout: int = 1800,
             prefix: str = "splitnode", steps: int = 8, cfg: float = 1.0,
             width: int = WIDTH, height: int = HEIGHT,
             ref_mode: str = "img2img",
             ref_method: str = "index_timestep_zero",
             ref_boost: float = 4.0, grounding_px: int = 1024,
             ref_images_b: list[str] | None = None,
             negative_prompt: str = "") -> bool:
    """Generate one image via ComfyUI (single attempt). Blocks until the queue finishes.
    Every reference (single or multiple) is normalized to a 640x720 strip
    BEFORE conditioning - a full-res ref (e.g. a 4K photo) would otherwise
    make the KSampler denoise a 4K latent at ~60s/step.

    ref_mode="identity": krea2edit trained path - the ref is uploaded
    FULL-RES (no strip) and fit to the target grid by the node's pixel
    path (fit_mode=fit). Use ONE tight ref (real photo / face panel), never
    a montage. ref_images_b (identity only): optional SECOND ref = style
    plate (scene, image 1 is ref_images[0], image 2 is ref_images_b[0]) -
    training order is scene first, subject second.
    """
    base = _comfy_url()
    if ref_mode == "identity":
        if not ref_images:
            print("  [KREA] identity mode needs at least one ref image")
            return False
        # identity refs: [scene/style, subject, subject2, props...] in
        # training order (image 1 = scene, image 2+ = subjects). ref_images_b
        # is kept for callers that pass the old two-arg shape.
        refs_all = list(ref_images)
        if ref_images_b:
            refs_all.extend(ref_images_b)
        ref_names = [_upload_ref(r, base) for r in refs_all]
        api = build_identity_api(prompt, seed, ref_names, width, height,
                                 ref_boost=ref_boost, grounding_px=grounding_px,
                                 steps=steps, upscale=upscale, prefix=prefix,
                                 negative_prompt=negative_prompt)
    else:
        ref_name = None
        if ref_images:
            if ref_mode == "reference" and len(ref_images) == 1:
                # Reference conditioning: the sample latent comes from
                # EmptyLatentImage (width/height), NOT from the ref - so no
                # strip is needed, and a padded strip actively hurts (the
                # dark bars bleed into the t=0 ref tokens as layout). Upload
                # the raw normalized image instead.
                ref_name = _upload_ref(ref_images[0], base)
            else:
                strip = _compose_ref_strip(ref_images, out_path)
                ref_name = _upload_ref(strip, base)
        api = build_api(prompt, seed, ref_name, denoise, upscale=upscale,
                        prefix=prefix, steps=steps, cfg=cfg,
                        width=width, height=height, ref_mode=ref_mode,
                        ref_method=ref_method)
    queued = _req(base, "/prompt", {"prompt": api}, timeout=120)
    pid = queued.get("prompt_id")
    if not pid:
        print(f"  [KREA] submit failed: {str(queued)[:200]}")
        return False
    t0 = time.time()
    poll_fail = 0
    while time.time() - t0 < timeout:
        # ComfyUI blocks its HTTP handler while staging the 12.9GB UNET
        # between jobs (~80s, --lowvram), so a transient timeout here does
        # NOT mean the job died. Keep polling instead of aborting - aborting
        # made the retry wrapper re-submit and queue duplicate jobs (each
        # shot burned an "attempt 1/4: timed out" + a redundant render).
        # Only bail after ~3 min of HARD consecutive failures (server
        # crashed/restarted -> our prompt_id is gone forever -> the wrapper
        # waits for recovery and re-runs the whole job).
        try:
            hist = _req(base, f"/history/{pid}", timeout=30)
        except OSError:
            poll_fail += 1
            if poll_fail > 5:
                raise
            time.sleep(5)
            continue
        poll_fail = 0
        entry = hist.get(pid)
        if entry and entry.get("outputs"):
            imgs = []
            for node_out in entry["outputs"].values():
                imgs.extend(node_out.get("images", []))
            if imgs:
                img = imgs[0]
                dl = (f"{base}/view?filename={img['filename']}"
                      f"&subfolder={img.get('subfolder', '')}&type={img.get('type', 'output')}")
                try:
                    urllib.request.urlretrieve(dl, out_path)
                except Exception as e:
                    print(f"  [KREA] download failed: {e}")
                    return False
                if os.path.getsize(out_path) > 1000:
                    print(f"  [KREA] {os.path.basename(out_path)} "
                          f"({os.path.getsize(out_path)//1024}KB, {time.time()-t0:.0f}s)")
                    return True
                return False
        if entry and entry.get("status", {}).get("status_str") in ("error", "failed"):
            print(f"  [KREA] node error: {str(entry.get('status'))[:150]}")
            return False
        time.sleep(5)
    print(f"  [KREA] timeout after {timeout:.0f}s (job {pid})")
    return False


def _wait_for_comfy(max_wait: float = 240.0) -> str | None:
    """ComfyUI 0.29.0 intermittently dies with a native access violation in
    the image loader (Krea2 on 8GB --lowvram) and goes unresponsive for a
    while - new connections are refused/reset until it recovers or is
    relaunched. Poll /system_stats until it answers again. Clears the cached
    URL so port re-detection happens. Returns a fresh base URL or None."""
    global _COMFY
    _COMFY = None
    t0 = time.time()
    while time.time() - t0 < max_wait:
        try:
            return _comfy_url()
        except Exception:
            time.sleep(5)
    return None


def generate(prompt: str, seed: int, out_path: str,
             ref_images: list[str] | None = None, denoise: float = 0.55,
             upscale: bool = True, timeout: int = 1800,
             prefix: str = "splitnode", steps: int = 8, cfg: float = 1.0,
             width: int = WIDTH, height: int = HEIGHT,
             ref_mode: str = "img2img",
             ref_method: str = "index_timestep_zero",
             ref_boost: float = 4.0, grounding_px: int = 1024,
             ref_images_b: list[str] | None = None,
             negative_prompt: str = "") -> bool:
    """Generate one image via ComfyUI, surviving server crashes/wedges.

    ComfyUI 0.29.0 with Krea2 on 8GB --lowvram intermittently crashes with
    a native access violation in the image loader and refuses/resets
    connections until it recovers or is restarted. Instead of marking the
    image FAILED on the first refused connection (which cascaded into
    111/120 failed shots on ep8), wait for the server to answer again and
    re-run the whole job - refs are re-uploaded, a fresh prompt_id is
    queued. Gives up after max_retries so a permanently-dead server can't
    stall the run (missing images fall back to dark plates at render).
    """
    max_retries = 4
    for attempt in range(1, max_retries + 1):
        try:
            return _generate_once(prompt, seed, out_path, ref_images, denoise,
                                  upscale, timeout, prefix, steps, cfg, width,
                                  height, ref_mode, ref_method, ref_boost,
                                  grounding_px, ref_images_b, negative_prompt)
        except (OSError, RuntimeError) as e:
            if attempt >= max_retries:
                print(f"  [KREA] ComfyUI unreachable after {attempt} attempts "
                      f"({str(e)[:80]}) - giving up on this image")
                return False
            print(f"  [KREA] ComfyUI connection lost (attempt {attempt}/{max_retries}): "
                  f"{str(e)[:80]}. Waiting for it to recover...")
            if _wait_for_comfy(240.0) is None:
                print("  [KREA] ComfyUI did not come back within 240s - giving up")
                return False
    return False


def main() -> int:
    args = sys.argv[1:]
    if len(args) < 2:
        print(__doc__)
        return 2
    out = args[0]
    prompt = args[1]
    seed = 10000
    refs: list[str] = []
    denoise, upscale = 0.55, True
    i = 2
    while i < len(args):
        if args[i] == "--seed":
            seed = int(args[i + 1]); i += 2
        elif args[i] == "--ref":
            refs.append(args[i + 1]); i += 2
        elif args[i] == "--denoise":
            denoise = float(args[i + 1]); i += 2
        elif args[i] == "--no-upscale":
            upscale = False; i += 1
        else:
            i += 1
    ok = generate(prompt, seed, out, refs, denoise, upscale)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
