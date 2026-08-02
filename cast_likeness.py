"""Cast likeness pipeline: Google-image-search each archetype, download
candidates, ask the LOCAL vision LLM (LM Studio) for a detailed face
description, save to cast_refs/faces.json.

Usage:
    python cast_likeness.py --one hacker     # test one archetype
    python cast_likeness.py --all            # all 20 archetypes
"""
import base64
import json
import os
import re
import subprocess
import sys
import time
import urllib.request

LM_URL = "http://localhost:1234/v1/chat/completions"
VISION_MODEL = "gemma-4-e4b-uncensored-hauhaucs-aggressive"
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cast_refs")
FACES_JSON = os.path.join(OUT_DIR, "faces.json")

# archetype id -> search query (aim: clear front-facing portrait, plain bg)
QUERIES = {
    "hacker": "hacker man portrait",
    "police-officer": "police officer portrait man",
    "special-agent": "man suit portrait",
    "lawyer": "lawyer portrait man",
    "mid40s-male": "middle aged man portrait",
    "mid40s-female": "middle aged woman portrait",
    "young-male": "young man portrait",
    "young-female": "young woman portrait",
    "old-male": "old man portrait",
    "old-female": "old woman portrait",
    "politician": "politician portrait man",
    "banker": "banker portrait man",
    "casino-dealer": "casino dealer portrait",
    "accountant": "accountant woman portrait",
    "security-guard": "security guard portrait",
    "executive": "businessman suit portrait",
    "detective": "man trench coat portrait",
    "journalist": "journalist woman portrait",
    "scientist": "scientist portrait man",
    "lottery-clerk": "shopkeeper woman portrait",
}
GENERIC_FALLBACK = {
    "hacker": "man portrait",
    "police-officer": "man portrait",
    "special-agent": "man portrait",
    "lawyer": "man portrait",
    "mid40s-male": "man portrait",
    "mid40s-female": "woman portrait",
    "young-male": "young man face",
    "young-female": "young woman face",
    "old-male": "old man face",
    "old-female": "old woman face",
    "politician": "man portrait",
    "banker": "man portrait",
    "casino-dealer": "man portrait",
    "accountant": "woman portrait",
    "security-guard": "man portrait",
    "executive": "man portrait",
    "detective": "man portrait",
    "journalist": "woman portrait",
    "scientist": "man portrait",
    "lottery-clerk": "woman portrait",
}

FACE_PROMPT = (
    "Look at the human face in this image. Describe it in EXTREME detail so a "
    "3D artist can recreate the exact likeness: face shape (oval/square/round/"
    "heart/oblong), forehead, eyebrows (thickness, shape), eyes (colour, shape, "
    "size, spacing, eyelids), nose (bridge, tip, width), cheekbones, cheeks, "
    "jawline, chin, mouth and lips (shape, fullness), ears, precise skin tone, "
    "skin texture and blemishes (freckles, scars, wrinkles, pores, stubble), "
    "facial hair (style and coverage), age estimate, and hair (colour, length, "
    "style, texture, parting, hairline). Use precise painterly language. Finish "
    "with a dense 3-4 sentence LIKENESS paragraph combining everything. "
    "If the face is NOT clearly visible (masked, hooded, turned away, blurred, "
    "too small, no person), reply with exactly NO_CLEAR_FACE and nothing else."
)


def _curl(url, timeout=20):
    try:
        r = subprocess.run(
            ["curl", "-s", "-L", "-m", str(timeout), "-A", "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
             "-H", "Referer: https://duckduckgo.com/", url],
            capture_output=True, timeout=timeout + 10)
        return r.stdout
    except Exception:
        return b""


def ddg_images(query, n=6):
    """Openverse image search (open API, direct URLs, no key)."""
    q = urllib.parse.quote(query)
    try:
        raw = _curl(f"https://api.openverse.org/v1/images/?q={q}&page_size={n}")
        d = json.loads(raw.decode("utf-8", "ignore"))
        out = []
        for r in d.get("results", []):
            out.append({"image": r.get("url", ""), "thumb": r.get("url", ""),
                        "w": r.get("width", 0), "h": r.get("height", 0)})
        return out
    except Exception as e:
        print(f"  [SEARCH] openverse failed: {e}")
        return []


def download(url, path):
    try:
        data = _curl(url, timeout=25)
        if len(data) < 2000:
            return False
        with open(path, "wb") as f:
            f.write(data)
        return True
    except Exception:
        return False


def _strip_preamble(desc):
    """Cut snarky model preamble - keep from the first real field onward."""
    markers = ["face shape", "forehead", "eyebrows", "eyes:", "nose:", "jawline",
               "likeness", "skin tone", "age estimate"]
    low = desc.lower()
    cut = None
    for mk in markers:
        i = low.find(mk)
        if i >= 0 and (cut is None or i < cut):
            cut = i
    if cut is not None and cut > 0:
        desc = desc[cut:]
    # drop trailing markdown separators
    desc = re.sub(r"\n{2,}", "\n", desc).strip()
    return desc[:1400]


def vision_describe(image_path):
    with open(image_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    payload = {
        "model": VISION_MODEL,
        "messages": [
            {"role": "system", "content": (
                "You are a precise casting-documentation tool for a 3D character "
                "pipeline. Output ONLY the requested description. No commentary, "
                "no preamble, no roleplay, no personality, no markdown headers.")},
            {"role": "user", "content": [
                {"type": "text", "text": FACE_PROMPT},
                {"type": "image_url",
                 "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
            ]},
        ],
        "max_tokens": 700,
        "temperature": 0.2,
    }
    req = urllib.request.Request(LM_URL, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            out = json.loads(r.read())
        return out["choices"][0]["message"]["content"].strip()
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "ignore")[:400]
        print(f"  [VISION] HTTP {e.code}: {body}")
        return None
    except Exception as e:
        print(f"  [VISION] {e}")
        return None


def process_arch(arch_id, query):
    faces = {}
    if os.path.isfile(FACES_JSON):
        try:
            faces = json.load(open(FACES_JSON, encoding="utf-8"))
        except Exception:
            faces = {}
    print(f"[CAST] {arch_id}: searching '{query}'...")
    results = ddg_images(query)
    if not results and GENERIC_FALLBACK.get(arch_id):
        alt = GENERIC_FALLBACK[arch_id]
        print(f"  0 hits, retrying '{alt}'...")
        results = ddg_images(alt)
    if not results:
        print(f"  no search results")
        return
    # prefer portrait-ish images, try each until a clear face is found
    results.sort(key=lambda r: -r["h"] * 1000 - r["w"])  # tall first
    for i, r in enumerate(results[:4]):
        url = r.get("thumb") or r.get("image")
        path = os.path.join(OUT_DIR, f"{arch_id}_{i}.jpg")
        if not download(url, path):
            continue
        desc = vision_describe(path)
        if desc is None:
            continue
        if "NO_CLEAR_FACE" in desc.upper():
            print(f"  [{i}] no clear face, next...")
            os.remove(path)
            continue
        desc = _strip_preamble(desc)
        if len(desc) < 120:
            print(f"  [{i}] description too thin, next...")
            os.remove(path)
            continue
        faces[arch_id] = {"query": query, "source": url, "image": path,
                          "face_desc": desc}
        json.dump(faces, open(FACES_JSON, "w", encoding="utf-8"), indent=2)
        print(f"  [{i}] FACE OK -> {path}")
        print(f"  desc: {desc[:220]}...")
        return
    print(f"  no usable face found in 4 candidates")


if __name__ == "__main__":
    os.makedirs(OUT_DIR, exist_ok=True)
    import urllib.parse
    if "--one" in sys.argv:
        arch = sys.argv[sys.argv.index("--one") + 1]
        process_arch(arch, QUERIES.get(arch, arch))
    else:
        for arch, q in QUERIES.items():
            process_arch(arch, q)
            time.sleep(1)
        print("[CAST] done. faces.json written.")
