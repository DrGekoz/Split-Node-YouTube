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
import random
import re
import time
import urllib.request
import urllib.error
from pathlib import Path
import queue as _queue
import threading as _threading

try:
    from tqdm import tqdm as _tqdm
except Exception:
    _tqdm = None

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


def _ref_is_valid_image(path: str) -> bool:
    """Return True if `path` is a file PIL can actually decode as an image.

    Guards codex reference attachments. A corrupt or misnamed ref (e.g. an SVG
    saved with a .png extension) makes codex report "image content omitted
    because it could not be processed", imagegen then emits no output, and the
    deterministic claiming fails (retry -> fallback to black/reused images).
    We detect it cheaply here and drop the ref so the call still generates
    (txt2img) rather than silently breaking.
    """
    try:
        from PIL import Image
    except Exception:
        return True  # PIL unavailable - don't block, let codex decide
    try:
        with Image.open(path) as im:
            im.verify()
        return True
    except Exception:
        return False


class Codex:
    # Parallel-safe output detection: each call records the set of generated
    # images present before it runs, generates, then claims the NEWEST file
    # that was NOT present before AND not already claimed by another thread.
    # The lock only guards the scan/claim step, not the codex subprocess, so
    # multiple codex calls run concurrently without stealing each other's output.
    _scan_lock = None
    _claimed = set()
    @classmethod
    def _lock(cls):
        if cls._scan_lock is None:
            import threading
            cls._scan_lock = threading.Lock()
        return cls._scan_lock

    def __init__(self):
        if not _codex_available():
            raise RuntimeError("codex CLI not found on PATH - install with: npm install -g @openai/codex")

    def generate_image(self, prompt: str, out_path: str,
                       ref_images: list | None = None,
                       timeout: int = 900) -> bool:
        import shutil
        import subprocess
        import glob
        import tempfile
        import uuid
        # Per-call CODEX_HOME isolation (Joe 2026-08-16): each parallel codex
        # call runs in its OWN fresh CODEX_HOME so its output lands in a unique
        # generated_images/ namespace. The images ARE generated but, under 5-way
        # parallelism, the shared ~/.codex/generated_images gets several fresh
        # uuid dirs at once and the grab can't tell which belongs to which call
        # ('Saved at:' is unreliable on Windows). Isolation makes grabbing
        # deterministic: each call's isolated dir holds exactly one new image.
        _user_home = Path.home() / ".codex"
        _home = None
        _env = None
        try:
            _home = Path(tempfile.gettempdir()) / f"codex_home_{uuid.uuid4().hex[:12]}"
            _home.mkdir(parents=True, exist_ok=True)
            for _f in ("auth.json", "config.toml"):
                _src = _user_home / _f
                if _src.is_file():
                    try:
                        shutil.copy2(_src, _home / _f)
                    except Exception:
                        pass
            _env = dict(os.environ)
            _env["CODEX_HOME"] = str(_home)
            generated = _home / "generated_images"
        except Exception:
            _home = None
            _env = None
            generated = _user_home / "generated_images"
        generated.mkdir(parents=True, exist_ok=True)
        # Codex 0.147+ names outputs call_*.png (older used ig_*.png) - match
        # both so a version bump never silently breaks detection.
        def _scan() -> dict:
            m = {}
            for p in (glob.glob(str(generated / "**" / "call_*.png"), recursive=True)
                      + glob.glob(str(generated / "**" / "ig_*.png"), recursive=True)):
                m[os.path.abspath(p)] = os.path.getmtime(p)
            # Also record every EXISTING uuid dir (keys prefixed 'dir:') so the
            # brand-new-dir fallback can tell a fresh dir from a stale one.
            for d in glob.glob(str(generated / "*")):
                if os.path.isdir(d):
                    m["dir:" + os.path.abspath(d)] = 0
            return m

        # Snapshot BEFORE (under lock) so concurrent threads each get their own
        # before-set and can't collide on which output belongs to whom.
        with self._lock():
            before = _scan()

        # Codex is a Windows Node app -> always shell through powershell.exe.
        # The --skip-git-repo-check flag MUST come BEFORE the /imagegen prompt.
        # Image references are attached via -i <file> so GPT Image 2 uses them
        # as identity/style refs (character panels, real-person refs, logos).
        # CRITICAL (Joe 2026-08-09): `/imagegen <prompt>` must be piped to codex
        # exec on STDIN as ONE payload. Passing `/imagegen` and the prompt as
        # SEPARATE positional args makes codex parse `/imagegen` as a subcommand
        # and reject the prompt as 'unexpected argument' -> it errors out in ~0s,
        # creates no output, and the fallback below would silently copy a stale
        # old on-disk image. Verified working: `echo '/imagegen <prompt>' |
        # codex exec --skip-git-repo-check [-i <ref>]` (with OR without refs).
        ref_args = ""
        for ref in (ref_images or []):
            if not (ref and os.path.isfile(ref)):
                continue
            # Validate the ref is a REAL image before handing it to codex.
            # A corrupt/misnamed file (e.g. an SVG saved as .png) makes codex
            # print "image content omitted because it could not be processed",
            # imagegen then produces NO output, and claiming fails + falls back
            # to black/reused images for that shot. Drop bad refs here so the
            # shot still generates (txt2img) instead of silently breaking.
            if not _ref_is_valid_image(ref):
                print(f"  [CODEX] WARN dropping unreadable image ref: {os.path.basename(ref)}")
                continue
            ref_args += " -i " + _ps_quote(os.path.abspath(ref))
        # Feed the prompt via a temp FILE, not the command line (Joe's ep014
        # fix): embedding a multi-KB prompt with double-quotes inside
        # `echo '<prompt>' | codex` pushes the powershell.exe -Command string
        # past its argument-parser limit -> PowerShell raises "The string is
        # missing the terminator: \"" and the call dies in ~0s (rc=1, no
        # output). Short prompts slipped through, but real 4-5KB shot prompts
        # failed every time. Writing `/imagegen <prompt>` to a temp file and
        # piping it in via Get-Content keeps the command line tiny and immune
        # to quote/length issues. The temp file is removed in every path below
        # (success, timeout, and any early return) so nothing lingers.
        _tmp = None
        _payload = "/imagegen " + prompt
        try:
            import tempfile
            import uuid
            _tmp = os.path.join(tempfile.gettempdir(),
                                f"codex_payload_{uuid.uuid4().hex[:8]}.txt")
            with open(_tmp, "w", encoding="utf-8") as _f:
                _f.write(_payload)
        except Exception as _e:
            print(f"  [CODEX] could not write prompt temp file: {_e}")
            return False

        def _del_tmp():
            if _tmp:
                try:
                    os.remove(_tmp)
                except Exception:
                    pass

        def _cleanup_home():
            if _home and _home.is_dir():
                try:
                    shutil.rmtree(_home, ignore_errors=True)
                except Exception:
                    pass

        ps_cmd = (f"Get-Content -Raw '{_tmp}' | codex exec --skip-git-repo-check "
                  f"{ref_args}")
        cmd = ["powershell.exe", "-NoProfile", "-Command", ps_cmd]
        print(f"  [CODEX] running codex exec /imagegen"
              f"{' (' + str(len(ref_images)) + ' image refs)' if ref_images else ''}...")
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True,
                                  timeout=timeout, env=_env)
        except subprocess.TimeoutExpired:
            print("  [CODEX] timed out generating image")
            _del_tmp()
            _cleanup_home()
            return False

        # Temp prompt file was consumed by Get-Content during the run - drop it
        # now so it's cleaned up on every remaining path (success, rate-limit,
        # copy failure, etc). Joe's rule: the helper cleans up after itself.
        _del_tmp()

        # Claim the output for THIS call DETERMINISTICALLY (Joe 2026-08-09).
        # Codex prints "Saved at: <path>" in its stdout, naming the exact file
        # it produced for THIS invocation. Parsing that is race-free under
        # parallelism - the old "newest unclaimed file" scan could, when two
        # codex calls finished concurrently, let card A copy card B's output
        # (and vice-versa), which is exactly the wrong-filenames bug on chapter
        # cards. We now trust codex's own reported path first, and only fall
        # back to the newest-unclaimed scan if the path can't be parsed.
        out_text = (proc.stdout or "") + "\n" + (proc.stderr or "")
        # Strip ANSI/colour escape codes (PowerShell pipes them into the
        # captured text and they corrupt the "Saved at:" path match).
        out_text = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", out_text)
        src = None
        # Codex prints the path as "Saved at:" but the exact wrapper varies by
        # version (sometimes "Saved at:", "Saved to:", trailing quotes, ANSI).
        # Match the first drive-letter / absolute path in the output so a
        # cosmetic format change never breaks claiming under parallelism.
        m = re.search(
            r"(?:Saved\s+(?:at|to)|\b(?:image|output)\s+(?:written|saved)\s+(?:to|at))\s*[:=]?\s*"
            r"[`'\"\u2018\u2019\u201c\u201d]?\s*"
            r"([A-Za-z]:[^`'\"\u2018\u2019\u201c\u201d\r\n]+?\.(?:png|jpg|jpeg|webp))",
            out_text, re.IGNORECASE)
        if not m:
            # Fall back to ANY absolute image path appearing in the output.
            # Restricted to .png (codex outputs are always PNG) and we skip any
            # candidate that is one of THIS call's reference images, so an
            # echoed "-i C:\...\ref.jpg" can never be claimed as the output.
            m = re.search(
                r"([A-Za-z]:[^`'\"\u2018\u2019\u201c\u201d\r\n]+?\.png)",
                out_text, re.IGNORECASE)
        _ref_abs = {os.path.abspath(r) for r in (ref_images or [])}
        while m and os.path.abspath(m.group(1)) in _ref_abs:
            # keep scanning past an echoed reference path
            m = re.search(
                r"([A-Za-z]:[^`'\"\u2018\u2019\u201c\u201d\r\n]+?\.png)",
                out_text[m.end():], re.IGNORECASE)
        if m:
            cand = os.path.abspath(m.group(1))
            # The image can land on disk a beat AFTER codex prints the path on
            # Windows (real-time Defender scan + async flush). A single
            # os.path.isfile() here returned False for many ep13 shots even
            # though codex had produced the image - the shot fell to a black
            # placeholder and the temp PNG was orphaned. Poll briefly for the
            # reported file to appear before declaring the call a failure.
            if not os.path.isfile(cand):
                import time as _t
                for _i in range(int(os.environ.get("CODEX_FLUSH_WAIT", "15"))):
                    if os.path.isfile(cand):
                        break
                    _t.sleep(1)
            if os.path.isfile(cand):
                with self._lock():
                    if cand not in self._claimed:
                        src = cand
                        self._claimed.add(src)
        if src is None:
            # DETERMINISTIC new-dir fallback (Joe 2026-08-12): codex creates a
            # FRESH uuid dir under ~/.codex/generated_images/<uuid>/ for every
            # single call. So if the "Saved at:" line was mangled/absent but a
            # BRAND-NEW uuid dir appeared since this call's `before` snapshot
            # and holds exactly one unclaimed image, that image belongs to THIS
            # call and only this call (each call owns a unique dir). This is NOT
            # the old racy "newest unclaimed file" scan (which guessed across
            # all of ~/.codex and caused the wrong-filename bug) - it is scoped
            # to dirs that did not exist before this call ran, so it can never
            # claim a concurrently-finished sibling's output. Only applied when
            # there is exactly one candidate to keep it unambiguous.
            try:
                import glob as _glob
                cands = []
                for p in (_glob.glob(str(generated / "**" / "call_*.png"), recursive=True)
                          + _glob.glob(str(generated / "**" / "ig_*.png"), recursive=True)):
                    ap = os.path.abspath(p)
                    # skip anything that existed before this call OR is already claimed
                    if ap in before:
                        continue
                    with self._lock():
                        if ap in self._claimed:
                            continue
                    # parent uuid dir must also be brand-new (this call's own)
                    if ("dir:" + os.path.dirname(ap)) in before:
                        continue
                    if os.path.isfile(ap):
                        cands.append(ap)
                if len(cands) == 1:
                    with self._lock():
                        if cands[0] not in self._claimed:
                            src = cands[0]
                            self._claimed.add(src)
                            print("  [CODEX] deterministic new-uuid-dir fallback: "
                                  f"{os.path.basename(cands[0])}")
            except Exception as _fb:
                print(f"  [CODEX] new-dir fallback error: {_fb}")
        if src is None:
            # STRICTLY DETERMINISTIC (Joe 2026-08-09): there is NO "newest
            # unclaimed file" fallback here anymore. That fallback was the root
            # cause of the wrong-filename bug - under parallel generation, if a
            # card's "Saved at:" path wasn't parsed, it would guess the newest
            # file in ~/.codex, which could be ANOTHER concurrently-finished
            # card's output, and copy that under the wrong name. Now a missing
            # deterministic path is treated as a genuine failure.
            # RATE-LIMIT: if codex text shows a rate limit / 429 / too many /
            # capacity / quota, throttle to one retry/hour (Joe's rule - never
            # fall back to another model). Any other failure returns False so the
            # caller retries THIS card cleanly. A card can never be saved under
            # another card's name.
            if re.search(r"(?i)rate\s*limit|429|too\s*many\s*requests|quota|"
                         r"limit\s*exceeded|capacity|temporarily\s*unavailable|"
                         r"overloaded|slow\s*down|try\s*again\s*in", out_text):
                print("  [CODEX] rate-limited - throttling: 1 retry/hour until success")
                return _codex_throttled_retry(self, prompt, out_path, ref_images,
                                              timeout, before)
            print("  [CODEX] could not deterministically locate this call's "
                  "output ('Saved at:' path missing) - returning failure to retry")
            _cleanup_home()
            return False
        try:
            shutil.copy2(src, out_path)
        except Exception as e:
            print(f"  [CODEX] failed to copy output: {e}")
            _cleanup_home()
            return False
        # Clean up the source from ~/.codex/generated_images/ (Joe 2026-08-12):
        # codex leaves a copy of every generated PNG in its temp dir which never
        # gets deleted - hundreds of files / ~1GB+ accumulate per run. Once the
        # image is copied into the episode folder, the temp source is no longer
        # needed. It's a unique per-generation path (already claimed + copied),
        # so removing it here is race-free. Any failure to delete is non-fatal.
        try:
            os.remove(src)
            # Drop the now-empty parent uuid dir too (codex makes one per call).
            _parent = os.path.dirname(src)
            try:
                os.rmdir(_parent)
            except Exception:
                pass
        except Exception as _cleanup_err:
            print(f"  [CODEX] could not remove temp source {os.path.basename(src)}: {_cleanup_err}")
        _cleanup_home()
        print(f"  [CODEX] {os.path.basename(out_path)} ({os.path.getsize(out_path)//1024}KB)")
        return os.path.getsize(out_path) > 500


def _codex_throttled_retry(codex, prompt: str, out_path: str,
                           ref_images: list | None, timeout: int,
                           before: dict) -> bool:
    """Rate-limit recovery for codex (Joe 2026-08-09).

    Codex/gpt-image-2 got rate-limited (no new output). We do NOT fall back to
    another image model. We wait one hour, retry this single image; if it still
    fails we keep waiting one hour and retrying until it succeeds, then return
    so the batch pushes the next image after it. The batch's parallel pool keeps
    its other slots; this call just blocks on the one slow retry.
    """
    import time as _time
    base_wait = max(60, int(os.environ.get("CODEX_RATELIMIT_WAIT", "3600")))
    attempt = 1
    while True:
        # Jitter the wait ±10% so that if several parallel threads hit the rate
        # limit together they DON'T all wake at the same moment and re-trip the
        # limit as a thundering herd (Joe 2026-08-09). Each wakes, retries its
        # one image, and only pushes the next after it succeeds.
        wait = base_wait * random.uniform(0.9, 1.1)
        print(f"  [CODEX][RATELIMIT] retry {attempt} in {wait/60:.0f} min "
              f"(single image/hour)...", flush=True)
        _time.sleep(wait)
        if codex.generate_image(prompt, out_path, ref_images=ref_images,
                                timeout=timeout):
            print(f"  [CODEX][RATELIMIT] succeeded after {attempt} retry")
            return True
        attempt += 1


def _ps_quote(s: str) -> str:
    """Escape a string for a PowerShell single-quoted argument."""
    return "'" + s.replace("'", "''") + "'"


# Path to the standalone FaceUpDAT upscale script + the Python that can run it.
# We use ComfyUI's embedded Python because it has the CUDA torch + spandrel
# needed to load 4xFaceUpDAT directly - NO ComfyUI server required.
_UPSCALE_SCRIPT = PROJECT_DIR / "faceupdat_upscale.py"
_COMFY_PY = r"F:\ComfyUI_windows_portable\python_embeded\python.exe"
# 2x upscaler - fast on the 8GB card, good at faces/eyes (Joe 2026-08-09).
# FaceUpDAT (4x) is the fallback if the 2x model is missing.
_UPSCALER_MODEL = r"F:\ComfyUI_windows_portable\ComfyUI\models\upscale_models\RealESRGAN_x2plus.pth"
_UPSCALER_MODEL_4X = r"F:\ComfyUI_windows_portable\ComfyUI\models\upscale_models\4xFaceUpDAT.safetensors"

# Persistent FaceUpDAT daemon: the ~40s model load happens ONCE per run and
# every subsequent upscale reuses the loaded model (job line in, 'DONE' line
# out). Falls back to one-shot subprocess (previous behaviour) if the daemon
# can't start, so the pipeline never hard-requires it.
_upscale_daemon = None
_upscale_daemon_lock = None
_UPSCALE_TIMEOUT = int(os.environ.get("UPSCALE_TIMEOUT", "300"))

# Async upscale queue (Joe 2026-08-09): codex generation should NOT wait for
# the previous shot's upscale to finish before firing the next prompt. Shots
# enqueue their resolution enforcement here and return immediately; a single
# background worker drains the queue (itself using the persistent FaceUpDAT
# daemon, so upscales stay cheap). _flush_upscales() blocks until the queue is
# empty and is called before the render pass consumes the images.
_upscale_q = _queue.Queue()
_upscale_q_worker = None
_upscale_q_lock = _threading.Lock()


def _upscale_worker_loop():
    while True:
        job = _upscale_q.get()
        if job is None:
            _upscale_q.task_done()
            break
        try:
            image_path, width, height = job
            _name = os.path.basename(image_path)
            _t0 = time.time()
            _bar = None
            if _tqdm is not None:
                # Estimated duration (source-pixel proportional) so the per-image
                # progress bar has a plausible total (Joe 2026-08-09).
                _est = _estimate_upscale_seconds(image_path)
                _bar = _tqdm(total=_est, unit="s", leave=False,
                             desc=f"  [UPSCALE] {_name}",
                             bar_format="{desc}: {percentage:3.0f}%|{bar}| "
                                        "{n:.1f}/{total:.1f}s")
            _res = {}

            def _run():
                _res["ok"] = _enforce_resolution(image_path, width, height)

            _th = _threading.Thread(target=_run)
            _th.start()
            if _bar is not None:
                try:
                    while _th.is_alive():
                        time.sleep(0.1)
                        # Cap the update so the bar NEVER overruns its estimated
                        # total - tqdm throws "unsupported format string passed
                        # to NoneType" (percentage computes to None) once n > total,
                        # which killed the worker before _th.join() and left the
                        # upscaled output unwritten (Joe 2026-08-09: shots looked
                        # stuck "waiting to be upscaled").
                        _remain = _est - _bar.n
                        if _remain > 0:
                            _bar.update(min(0.1, _remain))
                finally:
                    _th.join()
                    _bar.n = _est
                    _bar.refresh()
                    _bar.close()
            else:
                _th.join()
            _ok = _res.get("ok")
            _sz = ""
            try:
                from PIL import Image
                _im = Image.open(image_path)
                _sz = f"{_im.size[0]}x{_im.size[1]}"
            except Exception:
                pass
            print(f"  [UPSCALE] {'OK' if _ok else 'FAILED'} {_name} ({_sz}) "
                  f"in {time.time()-_t0:.1f}s", flush=True)
        except Exception as _e:
            print(f"  [UPSCALE] worker error: {str(_e)[:120]}", flush=True)
        finally:
            _upscale_q.task_done()


def _estimate_upscale_seconds(image_path: str) -> float:
    """Rough per-image upscale time from source pixel count (2.6e-6 s/px on the
    RealESRGAN x2 daemon, plus a daemon warm-up allowance on the first call) so
    the progress bar has a plausible total that doesn't overrun. Clamped."""
    try:
        from PIL import Image
        w, h = Image.open(image_path).size
        est = w * h * 2.6e-6 + 0.8
    except Exception:
        est = 3.0
    return max(1.0, min(30.0, est))


def _start_upscale_worker():
    global _upscale_q_worker
    with _upscale_q_lock:
        if _upscale_q_worker is None or not _upscale_q_worker.is_alive():
            _upscale_q_worker = _threading.Thread(
                target=_upscale_worker_loop, daemon=True)
            _upscale_q_worker.start()


def enqueue_upscale(image_path: str, width: int, height: int) -> None:
    """Queue a resolution-enforcement job for the background worker. Returns
    immediately so codex can fire the next prompt without waiting."""
    _start_upscale_worker()
    _upscale_q.put((image_path, int(width), int(height)))


def flush_upscales(timeout: float = 3600.0) -> None:
    """Block until every queued upscale job has finished. Safe to call with an
    empty queue. Used before the render pass consumes the upscaled images."""
    _start_upscale_worker()
    _upscale_q.join()


def _enforce_resolution(image_path: str, width: int, height: int) -> bool:
    """Enforce EXACT target resolution on an image, in place.

    GPT Image 2 / codex has a FIXED native output (1672x941 on this setup)
    regardless of the prompt size hint, so it rarely matches the requested
    width x height. Resize to the EXACT requested size: downscale via PIL
    lanczos when larger (or wrong ratio), upscale via the neural upscaler
    (RealESRGAN x2) when smaller. Returns True on success.
    """
    from PIL import Image
    try:
        im = Image.open(image_path)
        w, h = im.size
        im.close()
    except Exception:
        return False
    if w >= width and h >= height and (w, h) != (width, height):
        # larger than target (or wrong ratio) -> downscale to exact
        with Image.open(image_path) as im:
            im = im.resize((width, height), Image.LANCZOS)
            im.save(image_path)
        print(f"  [SIZE] {os.path.basename(image_path)} downscaled "
              f"{w}x{h} -> {width}x{height}")
        return True
    return _ensure_image_size(image_path, image_path, width=width,
                              height=height)


def _upscale_model_path() -> str:
    """Return the 2x upscaler if present, else the 4x FaceUpDAT fallback."""
    return (_UPSCALER_MODEL if os.path.isfile(_UPSCALER_MODEL)
            else _UPSCALER_MODEL_4X if os.path.isfile(_UPSCALER_MODEL_4X)
            else _UPSCALER_MODEL)


def _get_upscale_daemon():
    """Return (proc, lock) for a persistent upscale --serve subprocess,
    starting it on first use. Returns (None, None) if it can't be started."""
    global _upscale_daemon, _upscale_daemon_lock
    if _upscale_daemon is not None:
        return _upscale_daemon, _upscale_daemon_lock
    if (not os.path.isfile(_UPSCALE_SCRIPT)
            or not os.path.isfile(_upscale_model_path())
            or not os.path.isfile(_COMFY_PY)):
        return None, None
    import subprocess
    import threading
    cmd = [_COMFY_PY, str(_UPSCALE_SCRIPT), "--serve", "--model",
           _upscale_model_path()]
    try:
        # stderr -> DEVNULL: torch model-load warnings fill the stderr pipe and
        # deadlock the daemon before [READY] if we don't drain it. The serve
        # daemon reports per-job success/failure on stdout (DONE lines), so we
        # don't lose error info by discarding stderr.
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL,
                                text=True, bufsize=1)
        # wait for [READY] (model loaded) with a bounded timeout
        line = ""
        deadline = time.time() + 120
        while time.time() < deadline:
            line = proc.stdout.readline()
            if "READY" in line:
                break
        if "READY" not in line:
            proc.terminate()
            return None, None
    except Exception:
        return None, None
    _upscale_daemon = proc
    _upscale_daemon_lock = threading.Lock()
    return _upscale_daemon, _upscale_daemon_lock


def _faceupdat_upscale(image_path: str, out_path: str,
                       width: int = 1920, height: int = 1080,
                       timeout: int = None) -> bool:
    """Upscale an image with 4xFaceUpDAT run DIRECTLY in Python (torch + spandrel).

    No ComfyUI server needed - the embedded Python loads the model and upscales
    standalone, then cover-fits to the exact target resolution. Uses a PERSISTENT
    daemon so the model is loaded only once per run. Returns True on success.
    """
    import json
    import subprocess
    timeout = timeout or _UPSCALE_TIMEOUT
    if not os.path.isfile(image_path):
        return False
    daemon, lock = _get_upscale_daemon()
    if daemon is not None and lock is not None:
        try:
            with lock:
                job = json.dumps({"in": os.path.abspath(image_path),
                                  "out": os.path.abspath(out_path),
                                  "w": width, "h": height, "skip": True})
                try:
                    daemon.stdin.write(job + "\n")
                    daemon.stdin.flush()
                except Exception:
                    # daemon died mid-run - fall through to one-shot
                    return _faceupdat_oneshot(image_path, out_path,
                                              width, height, timeout)
                # read the single DONE line for this job
                line = ""
                for _ in range(20):
                    line = daemon.stdout.readline()
                    if line.startswith("DONE"):
                        break
                parts = line.split()
                # ok flag is ALWAYS the LAST token. parts[2] is wrong when the
                # output path contains spaces (e.g. "System Breakers") - the
                # split() breaks the path across tokens. (Joe 2026-08-09)
                if len(parts) >= 3 and parts[0] == "DONE" and parts[-1] == "1":
                    return True
                return False
        except Exception:
            return _faceupdat_oneshot(image_path, out_path, width, height, timeout)
    return _faceupdat_oneshot(image_path, out_path, width, height, timeout)


def _faceupdat_oneshot(image_path: str, out_path: str,
                       width: int, height: int, timeout: int) -> bool:
    """Original per-image subprocess path (fallback if the daemon is unavailable)."""
    import subprocess
    if not os.path.isfile(_UPSCALE_SCRIPT) or not os.path.isfile(_upscale_model_path()):
        return False
    cmd = [_COMFY_PY, str(_UPSCALE_SCRIPT), _upscale_model_path(),
           os.path.abspath(image_path), os.path.abspath(out_path),
           str(width), str(height), "--skip-if-larger"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        print(f"  [UPSCALE] timed out ({timeout}s)")
        return False
    if r.returncode != 0 or not os.path.isfile(out_path) or os.path.getsize(out_path) < 500:
        print(f"  [UPSCALE] failed: {r.stderr.strip()[-300:]}")
        return False
    return True


def _ensure_image_size(image_path: str, out_path: str,
                       width: int = 1920, height: int = 1080,
                       timeout: int = 900) -> bool:
    """Ensure an image is at least `width`x`height`, upscaling only if smaller.

    Uses the neural 2x upscaler (RealESRGAN x2plus) via the persistent daemon -
    FAST on the 8GB card (~2-5s per 1280x720 shot) and good at faces/eyes. The
    daemon's tile-based mosaic covers the source at the model's scale then
    cover-fits to the exact target, so 1080p/1440p/4K all come out correct.
    Never downsizes; an already->=target source is left untouched. NO PIL
    lanczos resize is used (Joe 2026-08-09 - PIL upscales were blurry).
    """
    from PIL import Image
    try:
        im = Image.open(image_path)
        w, h = im.size
    except Exception as e:
        print(f"  [SIZE] could not read image ({str(e)[:60]})")
        return False
    if w >= width and h >= height:
        print(f"  [SIZE] {os.path.basename(image_path)} already {w}x{h} "
              f"(target {width}x{height}), no upscale needed")
        return True
    if _faceupdat_upscale(image_path, out_path, width=width, height=height,
                          timeout=timeout):
        return True
    print(f"  [SIZE] neural upscale failed for "
          f"{os.path.basename(image_path)}")
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
            ok = rp.generate_image(endpoint, prompt, seed, out_path,
                                   size=size, strength=strength,
                                   image_url=image_url)
            if ok and upscale:
                # Async resolution enforcement, same as codex (Joe 2026-08-16):
                # don't block the shot loop on the upscale - enqueue it so the
                # next prompt fires immediately and the upscaler catches up in
                # the background. flush_upscales() drains before the render pass.
                enqueue_upscale(out_path, width, height)
            return ok
        except Exception as e:
            print(f"  [RUNPOD] {str(e)[:140]}")
            return False

    if backend == "codex":
        try:
            c = Codex()
        except RuntimeError as e:
            print(f"  [CODEX] {e}")
            return False
        ok = c.generate_image(prompt, out_path, ref_images=ref_images)
        if not ok:
            return False
        # Enforce the target resolution ASYNCHRONOUSLY (Joe 2026-08-09): GPT
        # Image 2 / codex has a FIXED native output (1672x941 on this setup)
        # regardless of the prompt size hint. Instead of blocking the shot
        # loop here on the upscale, enqueue the exact-size enforcement so codex
        # can fire the next prompt immediately and the upscaler catches up in
        # the background. flush_upscales() is called before the render pass.
        if upscale:
            enqueue_upscale(out_path, width, height)
        return True

    if backend == "fal":
        try:
            f = Fal()
        except RuntimeError as e:
            print(f"  [FAL] {e}")
            return False
        try:
            endpoint = IMAGE_MODELS["fal"][model]  # key -> fal model id
            ok = f.generate_image(endpoint, prompt, seed, out_path,
                                  num_steps=steps, image_url=image_url,
                                  image_size=image_size)
            if ok and upscale:
                # Async resolution enforcement, same as codex (Joe 2026-08-16):
                # don't block the shot loop on the upscale - enqueue it so the
                # next prompt fires immediately and the upscaler catches up in
                # the background. flush_upscales() drains before the render pass.
                enqueue_upscale(out_path, width, height)
            return ok
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
