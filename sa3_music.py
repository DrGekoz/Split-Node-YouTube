"""Stable Audio 3 music-bed generator wrapper for Split Node (2026-08-14).

Joe: "add a music bed pipeline with ducking (we are swapping to Stable Audio 3)".
SA3 is installed via Pinokio at F:/pinokio/api/stable-audio-3-small.pinokio.git:
  app/                          the cloned Stability-AI/stable-audio-3 repo
  app/env/                      its venv (torch 2.7.1 cu128, stable-audio CLI)
  launch.py (bundle root)       registers the cocktailpeanut HF mirrors

This module wraps that install so Split Node can generate a real SA3 music bed
(text-to-audio) instead of crossfading the static MP3 pool, with a clean fallback
to the static pool if SA3 is unavailable/fails (an episode must never break).

Design:
  - Detect the app dir by the `stable_audio_3/` package marker, and the bundle
    root by its `launch.py`.
  - Write a tiny driver that loads the bundle's launch.py to register the
    working cocktailpeanut mirrors, then runs the SA3 CLI main().
  - Invoke:  <app>/env/Scripts/python.exe <driver> --model small-music
             -p "<prompt>" --duration <sec> -o <out.wav>
  - Model defaults to small-music (best quality for a full music bed); use
    small-sfx for one-shot whooshes/impacts if ever needed.
"""
from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
from pathlib import Path

SA3_ROOT = os.environ.get(
    "SA3_ROOT",
    r"F:\pinokio\api\stable-audio-3-small.pinokio.git",
)
SA3_MODEL = os.environ.get("SA3_MODEL", "medium")  # medium | small-music | small-sfx
SA3_STEPS = int(os.environ.get("SA3_STEPS", "8"))
SA3_CFG = float(os.environ.get("SA3_CFG", "1.0"))


def sa3_bundle_root() -> Path | None:
    """The pinokio bundle root, which holds launch.py (mirror registration)."""
    r = Path(SA3_ROOT)
    return r if (r / "launch.py").is_file() else None


def sa3_app_dir() -> Path | None:
    """The cloned SA3 repo (has the stable_audio_3/ package + its venv)."""
    for candidate in (Path(SA3_ROOT) / "app", Path(SA3_ROOT)):
        if (candidate / "stable_audio_3").is_dir():
            return candidate
    return None


def sa3_env_python() -> Path | None:
    """The venv python inside the SA3 app (Windows Scripts/python.exe)."""
    app = sa3_app_dir()
    if not app:
        return None
    for cand in (app / "env" / "Scripts" / "python.exe",
                 app / "env" / "bin" / "python"):
        if cand.is_file():
            return cand
    return None


def available() -> bool:
    return (sa3_app_dir() is not None and sa3_env_python() is not None
            and sa3_bundle_root() is not None)


def _write_driver(app: Path, bundle_root: Path) -> Path:
    """Write a driver into the app dir that registers the cocktailpeanut mirrors
    (from the bundle root's launch.py) then runs the SA3 CLI main().

    The plain `stable-audio` CLI would hit the stabilityai repos directly, which
    can be slow/blocked on this box; the pinokio bundle's launch.py remaps them
    to the working mirrors. We exec that launch.py as a module and call its
    register_mirrors() before handing off to the CLI.
    """
    driver = app / "_sa3_driver.py"
    driver.write_text(
        "import os, sys, importlib.util\n"
        f"sys.path.insert(0, {str(app)!r})\n"
        f"_bundle = {str(bundle_root)!r}\n"
        "sys.path.insert(0, _bundle)\n"
        "_spec = importlib.util.spec_from_file_location('_pinokio_launch', "
        "os.path.join(_bundle, 'launch.py'))\n"
        "_m = importlib.util.module_from_spec(_spec)\n"
        "_spec.loader.exec_module(_m)\n"
        "_m.register_mirrors()\n"
        "from stable_audio_3.cli import main\n"
        "sys.exit(main())\n",
        encoding="utf-8",
    )
    return driver


def generate(prompt: str, duration_sec: float, out_path: str,
             model: str | None = None, seed: int = -1,
             timeout: int = 1800) -> bool:
    """Generate a Stable Audio 3 music bed clip to out_path (WAV, 44.1k).

    Returns True on success, False on any failure (caller falls back to the
    static pool). The CLI output is the generated audio; we also verify the file
    exists and is non-trivial before returning success.
    """
    model = model or SA3_MODEL
    app = sa3_app_dir()
    py = sa3_env_python()
    bundle = sa3_bundle_root()
    if not app or not py or not bundle:
        print("  [SA3] install not ready (app/env/launch missing) - using static music pool")
        return False
    driver = _write_driver(app, bundle)
    out_abs = os.path.abspath(out_path)
    out_dir = os.path.dirname(out_abs)
    if out_dir:
        Path(out_dir).mkdir(parents=True, exist_ok=True)
    cmd = [
        str(py), str(driver),
        "--model", model,
        "-p", prompt,
        "--duration", f"{duration_sec:.0f}",
        "--steps", str(SA3_STEPS),
        "--cfg-scale", str(SA3_CFG),
        "-o", out_abs,
    ]
    if seed is not None and seed >= 0:
        cmd += ["--seed", str(seed)]
    print(f"  [SA3] generating {duration_sec:.0f}s music ({model}, {SA3_STEPS} steps) ...")
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=timeout, cwd=str(app))
    except subprocess.TimeoutExpired:
        print(f"  [SA3] timed out after {timeout}s")
        return False
    except Exception as e:
        print(f"  [SA3] launch error: {e}")
        return False
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        print(f"  [SA3] generation failed (rc={proc.returncode}): {err[-400:]}")
        return False
    if not (os.path.isfile(out_abs) and os.path.getsize(out_abs) > 1000):
        alt = out_abs.replace(".wav", "_0.wav")
        if os.path.isfile(alt) and os.path.getsize(alt) > 1000:
            shutil.move(alt, out_abs)
        else:
            print("  [SA3] output file missing/empty")
            return False
    print(f"  [SA3] OK {os.path.getsize(out_abs)//1024}KB -> {out_abs}")
    return True


def generate_bed(prompt_suspense: str, prompt_triumphant: str,
                 dur_suspense: float, dur_triumphant: float,
                 out_suspense: str, out_triumphant: str,
                 seed: int = -1) -> bool:
    """Generate both sections of the bed (suspense + triumphant) for a Split Node
    episode. Any failure returns False so the caller falls back to the static pool."""
    ok_s = generate(prompt_suspense, dur_suspense, out_suspense,
                    model="medium", seed=seed if seed >= 0 else -1)
    ok_t = generate(prompt_triumphant, dur_triumphant, out_triumphant,
                    model="medium", seed=seed if seed >= 0 else -1)
    return ok_s and ok_t


# ---------------------------------------------------------------------------
# Resident-model (Gradio) backend (Joe 2026-08-14)
# ---------------------------------------------------------------------------
# The medium model is loaded ONCE in the running Pinokio Gradio UI on port 7861.
# Generating through its /generate endpoint reuses that resident copy (no second
# 5.7GB load) and chunks any duration > 380s into 6:20 segments automatically.
# Path of the chunking driver inside the SA3 bundle app folder.
SA3_GRADIO_URL = os.environ.get("SA3_GRADIO_URL", "http://127.0.0.1:7861/")
_SA3_GRADIO_DRIVER = "F:\\pinokio\\api\\stable-audio-3-small.pinokio.git\\app\\_sa3_gradio_gen.py"

# ---------------------------------------------------------------------------
# SA3 port resolution (Joe 2026-08-14)
# ---------------------------------------------------------------------------
# SA3's Pinokio launcher opens on a DIFFERENT port each run (7860, 7861, ...),
# so the hardcoded default above is unreliable. resolve_sa3_port() scans the
# local Gradio /config endpoint for the SA3 signature and asks the user to
# confirm/enter the port, then updates SA3_GRADIO_URL in-place. Every pipeline
# should call it at startup BEFORE doing any work.
_SA3_PORT_SCAN_RANGE = (7860, 7890)  # inclusive start, exclusive end


def _is_sa3_config(text: str) -> bool:
    """True if a Gradio /config payload looks like Stable Audio 3."""
    return ("pingpong" in text and "Stable Audio" in text)


def detect_sa3_port() -> int | None:
    """Return the localhost port where a live SA3 Gradio UI is listening, or
    None if none / ambiguous. First socket-probes the range (instant on refused
    ports), then fetches /config only on ports that are actually listening."""
    import socket
    import urllib.request
    listening = []
    for port in range(*_SA3_PORT_SCAN_RANGE):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.1)
        try:
            if s.connect_ex(("127.0.0.1", port)) == 0:
                listening.append(port)
        except OSError:
            pass
        finally:
            s.close()
    found = []
    for port in listening:
        try:
            with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/config", timeout=2) as r:
                text = r.read(200000).decode("utf-8", "ignore")
            if _is_sa3_config(text):
                found.append(port)
        except Exception:
            continue
    if len(found) == 1:
        return found[0]
    if len(found) > 1:
        # Multiple SA3 UIs - ambiguous, fall through to manual entry.
        print(f"  [SA3] Multiple SA3 UIs detected on ports {found} - please enter the active one.")
        return None
    return None


def resolve_sa3_port(project: str = "pipeline") -> int | None:
    """Ask the user which port SA3 is running on and update SA3_GRADIO_URL.

    Auto-detects a single live SA3 UI and proposes it. The detected-port prompt
    accepts any of:
      - Enter / y / yes  -> accept the detected port
      - a port number    -> override and use that port (e.g. if detection is wrong)
      - n / no           -> fall through to a manual port entry prompt
    If nothing is detected it prompts for the port directly. Returns the
    resolved port or None if the user chose to skip (music generation will
    fall back to the static pool).
    """
    global SA3_GRADIO_URL
    detected = detect_sa3_port()
    if detected is not None:
        try:
            ans = input(f"\n  [{project}] Stable Audio 3 detected on port "
                        f"{detected} - use it? [Y/n, or type a port]: ").strip()
        except EOFError:
            ans = ""
        low = ans.lower()
        if low in ("", "y", "yes"):
            SA3_GRADIO_URL = f"http://127.0.0.1:{detected}/"
            print(f"  [SA3] using http://127.0.0.1:{detected}/")
            return detected
        # A numeric answer overrides the detected port directly.
        try:
            port = int(low)
            SA3_GRADIO_URL = f"http://127.0.0.1:{port}/"
            print(f"  [SA3] using http://127.0.0.1:{port}/ (override)")
            return port
        except ValueError:
            pass  # treat 'n'/'no' as "enter it manually"
    # Manual entry (or rejected auto-detect).
    try:
        raw = input(f"  [{project}] Enter SA3 port (or blank to skip music): ").strip()
    except EOFError:
        raw = ""
    if not raw:
        print("  [SA3] skipping music (fallback to static pool)")
        return None
    try:
        port = int(raw)
    except ValueError:
        print(f"  [SA3] invalid port '{raw}' - skipping music")
        return None
    SA3_GRADIO_URL = f"http://127.0.0.1:{port}/"
    print(f"  [SA3] using http://127.0.0.1:{port}/")
    return port


def generate_via_gradio(prompt: str, duration_sec: float, out_path: str,
                        timeout: int = 3600, story_context: str = "") -> bool:
    """Generate a music bed through the ALREADY-LOADED medium model.

    Uses the resident Gradio UI (default http://127.0.0.1:7861/) via
    gradio_client, chunking anything longer than 380s (6:20) into N x 380s
    segments + a final remainder (e.g. a 20m video = 380s x 3 + 60s). Returns
    True on success, False on any failure (caller falls back to static pool).

    story_context (optional): the story/narration text for this bed. It is split
    proportionally across the audio chunks so each chunk's music prompt reflects
    the part of the story happening in that time window (adaptive music).

    Music is generated raw here; the caller applies the -10dB base and ducks it
    to -19.5dB under the voice during the mix step.
    """
    py = sa3_env_python()
    app = sa3_app_dir()
    if not py or not app:
        print("  [SA3] install not ready (app/env missing) - using static music pool")
        return False
    driver = app / "_sa3_gradio_gen.py"
    if not driver.is_file():
        print(f"  [SA3] gradio driver missing: {driver} - using static music pool")
        return False
    out_abs = os.path.abspath(out_path)
    out_dir = os.path.dirname(out_abs)
    if out_dir:
        Path(out_dir).mkdir(parents=True, exist_ok=True)
    print(f"  [SA3] resident-model gen {duration_sec:.0f}s "
          f"({len(prompt)}-char prompt, chunked @380s) ...")
    cmd = [
        str(py), str(driver),
        "--prompt", prompt,
        "--duration", f"{duration_sec:.1f}",
        "--out", out_abs,
        "--url", SA3_GRADIO_URL,
    ]
    if story_context:
        cmd += ["--story", story_context]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=timeout, cwd=str(app))
    except subprocess.TimeoutExpired:
        print(f"  [SA3] resident-model gen timed out after {timeout}s")
        return False
    except Exception as e:
        print(f"  [SA3] resident-model launch error: {e}")
        return False
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        print(f"  [SA3] resident-model gen failed (rc={proc.returncode}): {err[-300:]}")
        return False
    if not (os.path.isfile(out_abs) and os.path.getsize(out_abs) > 1000):
        print("  [SA3] resident-model output missing/empty")
        return False
    print(f"  [SA3] OK {os.path.getsize(out_abs)//1024}KB -> {out_abs}")
    return True


def generate_bed_via_gradio(prompt_suspense: str, prompt_triumphant: str,
                            dur_suspense: float, dur_triumphant: float,
                            out_suspense: str, out_triumphant: str,
                            story_suspense: str = "", story_triumphant: str = "") -> bool:
    """Generate both bed sections (suspense + triumphant) through the resident
    medium model. Any section >380s is chunked automatically. The story text for
    each section makes the prompts adaptive to that section's content."""
    ok_s = generate_via_gradio(prompt_suspense, dur_suspense, out_suspense,
                               story_context=story_suspense)
    ok_t = generate_via_gradio(prompt_triumphant, dur_triumphant, out_triumphant,
                               story_context=story_triumphant)
    return ok_s and ok_t

