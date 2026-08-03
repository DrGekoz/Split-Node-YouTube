#!/usr/bin/env python3
"""test_elon_identity.py - Identity-mode character sheet test for Split Node.

Uses the TRAINED path (comfyui-krea2edit nodes + krea2_identity_edit_v1_2
LoRA) instead of the Ostris patch + ref strips that were artifacting.

Fixes applied vs the old pipeline:
  - euler sampler (er_sde disrupts the reference-copy channel - official
    krea2edit advisory)
  - single tight reference photo (no 6-panel montage strip)
  - Krea2EditModelPatch with fit_mode=fit + pixel path (vae/source_image/
    target_latent) - training-matched geometry, no stretched/letterboxed refs
  - ref_boost 4 (strong identity lock; example workflow ships at 4)
  - grounding_px 1024 (people; drop to 768 if split/duplicated comps)
  - panels at 640x540 (0.35MP, well under the 1-1.5MP trained range)

Generates the 6 sheet panels from cast_refs/real/elon_musk.jpg, then
composes them into the 1920x1080 sheet exactly like system_breakers.py.
"""
import sys, os, time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import krea2_splitnode as k

TEST_DIR = Path(__file__).parent / "test_output" / "elon_identity"
TEST_DIR.mkdir(parents=True, exist_ok=True)

REF = r"F:\aaaaaVIBECODING\System Breakers\cast_refs\real\elon_musk.jpg"
LORA = "krea2_identity_edit_v1_2_r128.safetensors"
PANEL_W, PANEL_H = 640, 540

# (view, prompt instruction). Single ref photo drives identity for all panels.
PANELS = [
    ("face",
     "Create a close-up portrait of THIS EXACT MAN's face, head and face only, "
     "full face centered, both eyes looking at camera, hair styled as in the "
     "reference, expression neutral. NOTHING else in frame - no shoulders, no "
     "neck, no body. Plain dark studio background, one person only."),
    ("face_side",
     "Show THIS EXACT MAN in left side profile, head only, same hair, same "
     "face, no body, no shoulders. Plain dark studio background, one person only."),
    ("face_back",
     "Show the back of THIS EXACT MAN's head, rear view, hair as in the "
     "reference, no face visible, no body. Plain dark studio background, one person only."),
    ("body_front",
     "Show THIS EXACT MAN full body standing facing the camera, complete "
     "outfit as in the reference, face identical, entire body head to feet, "
     "both feet on the ground, arms relaxed at sides. ONLY ONE person, no "
     "props. Plain dark studio background."),
    ("body_side",
     "Show THIS EXACT MAN full body side profile view facing left, same "
     "outfit, same face, same build, entire body head to feet. ONLY ONE "
     "person, no props. Plain dark studio background."),
    ("body_back",
     "Show THIS EXACT MAN full body rear view, back of head and full outfit "
     "visible, standing, entire body head to feet. ONLY ONE person, no "
     "props. Plain dark studio background."),
]


def build_identity_api(prompt: str, seed: int, ref_name: str,
                       ref_boost: float = 4.0) -> dict:
    """Krea2Edit graph: ref -> source_latent + grounded encode, LoRA applied."""
    api = {}
    api["1"] = {"class_type": "EmptySD3LatentImage",
                "inputs": {"width": PANEL_W, "height": PANEL_H, "batch_size": 1}}
    api["2"] = {"class_type": "CLIPLoader",
                "inputs": {"clip_name": k.CLIP, "type": "krea2", "device": "default"}}
    api["3"] = {"class_type": "UNETLoader",
                "inputs": {"unet_name": k.UNET, "weight_dtype": "default"}}
    api["4"] = {"class_type": "VAELoader", "inputs": {"vae_name": k.VAE}}
    api["5"] = {"class_type": "LoraLoaderModelOnly",
                "inputs": {"model": ["3", 0], "lora_name": LORA, "strength_model": 1.0}}
    api["6"] = {"class_type": "LoadImage", "inputs": {"image": ref_name}}
    api["7"] = {"class_type": "VAEEncode",
                "inputs": {"pixels": ["6", 0], "vae": ["4", 0]}}
    api["8"] = {"class_type": "Krea2EditModelPatch", "inputs": {
        "model": ["5", 0], "source_latent": ["7", 0],
        "ref_boost": ref_boost, "ref_boost_a": 1.0,
        "fit_mode": "fit", "vae": ["4", 0], "source_image": ["6", 0],
        "target_latent": ["1", 0]}}
    api["9"] = {"class_type": "Krea2EditGroundedEncode", "inputs": {
        "clip": ["2", 0], "prompt": prompt, "image": ["6", 0],
        "grounding_px": 1024}}
    api["10"] = {"class_type": "Krea2EditGroundedEncode", "inputs": {
        "clip": ["2", 0], "prompt": "", "image": ["6", 0],
        "grounding_px": 1024}}
    api["11"] = {"class_type": "KSampler", "inputs": {
        "model": ["8", 0], "positive": ["9", 0], "negative": ["10", 0],
        "latent_image": ["1", 0], "seed": seed, "control_after_generate": "fixed",
        "steps": 10, "cfg": 1.0, "sampler_name": "euler", "scheduler": "simple",
        "denoise": 1.0}}
    api["12"] = {"class_type": "VAEDecode",
                 "inputs": {"samples": ["11", 0], "vae": ["4", 0]}}
    api["13"] = {"class_type": "SaveImage",
                 "inputs": {"images": ["12", 0], "filename_prefix": "elon_id"}}
    return api


def gen_panel(view: str, prompt: str, seed: int) -> Path:
    pan = TEST_DIR / f"elon_musk_{view}.png"
    if pan.is_file():
        print(f"  [ID] reuse {pan.name}")
        return pan
    base = k._comfy_url()
    ref_name = k._upload_ref(REF, base)
    api = build_identity_api(prompt, seed, ref_name)
    queued = k._req(base, "/prompt", {"prompt": api}, timeout=60)
    pid = queued.get("prompt_id")
    if not pid:
        print(f"  [ID] submit failed: {str(queued)[:200]}")
        return None
    t0 = time.time()
    while time.time() - t0 < 1800:
        hist = k._req(base, f"/history/{pid}", timeout=30)
        entry = hist.get(pid)
        if entry and entry.get("outputs"):
            for node_out in entry["outputs"].values():
                for img in node_out.get("images", []):
                    dl = (f"{base}/view?filename={img['filename']}"
                          f"&subfolder={img.get('subfolder','')}&type={img.get('type','output')}")
                    try:
                        urllib_urlretrieve = __import__("urllib.request", fromlist=["urlretrieve"])
                        urllib_urlretrieve.urlretrieve(dl, pan)
                    except Exception as e:
                        print(f"  [ID] download failed: {e}")
                        return None
                    if pan.is_file() and pan.stat().st_size > 1000:
                        print(f"  [ID] {pan.name} ({pan.stat().st_size//1024}KB, {time.time()-t0:.0f}s)")
                        return pan
                    return None
        if entry and entry.get("status", {}).get("status_str") in ("error", "failed"):
            print(f"  [ID] node error: {str(entry.get('status'))[:200]}")
            return None
        time.sleep(5)
    print(f"  [ID] timeout after 1800s (job {pid})")
    return None


def compose_sheet(panels: dict) -> Path:
    from PIL import Image, ImageDraw, ImageFont
    W, H, COLS = 640, 540, 3
    grid = Image.new("RGB", (W * COLS, H * 2), (10, 10, 12))
    draw = ImageDraw.Draw(grid)
    order = ["face", "face_side", "face_back", "body_front", "body_side", "body_back"]
    for i, view in enumerate(order):
        if view not in panels or panels[view] is None:
            print(f"  [ID] missing panel {view} - leaving blank")
            continue
        im = Image.open(panels[view]).convert("RGB").resize((W, H), Image.LANCZOS)
        col, row = i % COLS, i // COLS
        grid.paste(im, (col * W, row * H))
        draw.rectangle([col * W, row * H, col * W + W - 1, row * H + H - 1],
                       outline=(120, 120, 130), width=4)
    try:
        font = ImageFont.truetype("arial.ttf", 26)
        draw.text((14, 6), "Elon Musk - 3D character sheet (identity mode)",
                  fill=(255, 255, 255), font=font)
    except Exception:
        pass
    sheet = TEST_DIR / "elon_musk_sheet.png"
    grid.save(sheet)
    return sheet


def main() -> int:
    print(f"=== ELON IDENTITY SHEET TEST (krea2edit v1.2 r128) ===")
    print(f"ref: {REF}")
    if not os.path.isfile(REF):
        print(f"  [FAIL] ref photo missing: {REF}")
        return 1
    lora_path = r"F:\ComfyUI_windows_portable\ComfyUI\models\loras" + "\\" + LORA
    if not os.path.isfile(lora_path):
        print(f"  [WARN] LoRA not on disk yet: {lora_path} - is the download finished?")
    base = k._comfy_url()
    print(f"comfy: {base}")
    seed = int(time.time()) % 100000
    panels = {}
    for view, prompt in PANELS:
        print(f"  [ID] panel {view} ...")
        pan = gen_panel(view, prompt, seed + 111 * len(view))
        if pan:
            panels[view] = str(pan)
    sheet = compose_sheet(panels)
    print("SHEET:", sheet)
    print("=== DONE ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
